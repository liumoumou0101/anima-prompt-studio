from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from anima_prompt_studio.domain.models import CompositionFieldState, PromptJob
from anima_prompt_studio.services.pipeline import PromptPipeline
from anima_prompt_studio.services.prompt_compiler import PromptCompiler
from anima_prompt_studio.services.resource_manager import ResourceManager
from anima_prompt_studio.services.translation_service import LocalMarianEngine, TranslationService


def evaluate(case: dict, job: PromptJob) -> list[str]:
    failures = []
    for field_name, expected in case.get("expect", {}).items():
        actual = getattr(job.composition, field_name)
        if actual != expected:
            failures.append(f"{field_name}: 期望 {expected}，实际 {actual}")
    tag_list = [tag.strip() for tag in job.positive_prompt.partition("\n\n")[0].split(",") if tag.strip()]
    tags = set(tag_list)
    natural = job.positive_prompt.partition("\n\n")[2].lower()
    for value in case.get("require_en_all", []):
        if value.lower() not in natural:
            failures.append(f"英文缺少：{value}")
    for value in case.get("forbid_en", []):
        if value.lower() in natural:
            failures.append(f"英文出现禁止内容：{value}")
    for tag in case.get("require_tags", []):
        if tag not in tags:
            failures.append(f"缺少标签：{tag}")
    for tag in case.get("forbid_tags", []):
        if tag in tags:
            failures.append(f"出现禁止标签：{tag}")
    for field_name, expected in case.get("expect_context", {}).items():
        actual = getattr(job.composition_context, field_name)
        if isinstance(expected, bool):
            actual = bool(actual)
        if actual != expected:
            failures.append(f"上下文 {field_name}: 期望 {expected}，实际 {actual}")
    if case.get("only_one_main_angle"):
        angle_tags = [tag for tag in tag_list if PromptCompiler._exclusive_group(tag) == "angle"]
        if len(angle_tags) != 1:
            failures.append("主角度标签数量不是 1：" + ", ".join(angle_tags))
    dimension = case.get("dimension")
    width, height = job.generation_params.width, job.generation_params.height
    if dimension == "landscape" and width <= height:
        failures.append(f"期望横图尺寸，实际 {width}x{height}")
    if dimension == "locked" and (width, height) != tuple(case["dimensions"]):
        failures.append(f"锁定尺寸被覆盖：{width}x{height}")
    for field_name in case.get("expect", {}):
        decision = job.composition.decision(field_name)
        if decision.state == CompositionFieldState.AUTO and not decision.reason:
            failures.append(f"{field_name} 缺少推荐理由")
    return failures


def run(cases_path: Path, output_dir: Path) -> dict:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    resources = ResourceManager()
    if not resources.models_available():
        raise RuntimeError("真实双向翻译模型尚未安装。")
    started = time.perf_counter()
    engine = LocalMarianEngine(resources.model_path("zh_en"), resources.model_path("en_zh"))
    pipeline = PromptPipeline(translation=TranslationService(engine))
    results = []
    print(f"已加载真实模型，构图用例数：{len(cases)}", flush=True)
    for index, case in enumerate(cases, 1):
        job = PromptJob(original_zh=case["input"])
        job.composition.people_count = case.get("people_count", 1)
        for field_name, value in case.get("initial", {}).items():
            setattr(job.composition, field_name, value)
        for field_name, state in case.get("states", {}).items():
            job.composition.decision(field_name).state = CompositionFieldState(state)
        if "dimensions" in case:
            job.generation_params.width, job.generation_params.height = case["dimensions"]
            job.generation_params.locked_fields = ["width", "height"]
        before = time.perf_counter()
        try:
            pipeline.translate(job)
            failures = evaluate(case, job)
            error = None
        except Exception as exc:
            failures = [f"{type(exc).__name__}: {exc}"]
            error = failures[0]
        elapsed = time.perf_counter() - before
        results.append({
            "id": case["id"], "input": case["input"], "passed": not failures,
            "failures": failures, "seconds": round(elapsed, 3), "translated_en": job.translated_en,
            "composition": job.composition.model_dump(mode="json"),
            "dimensions": [job.generation_params.width, job.generation_params.height],
            "positive_prompt": job.positive_prompt, "error": error,
        })
        print(f"[{index:02d}/{len(cases)}] {'PASS' if not failures else 'FAIL'} {case['id']} ({elapsed:.2f}s)", flush=True)
    summary = {"total": len(results), "passed": sum(x["passed"] for x in results)}
    summary["failed"] = summary["total"] - summary["passed"]
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "summary": summary, "results": results}
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "composition_audit.json"; md_path = output_dir / "composition_audit.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 智能构图真实模型审计", "", f"总计：{summary['total']}；通过：{summary['passed']}；失败：{summary['failed']}", ""]
    for item in results:
        status = "PASS" if item["passed"] else "FAIL"
        c = item["composition"]
        lines.extend([f"## {status} · {item['id']}", "", f"输入：`{item['input']}`", "",
                      f"构图：`{c['shot']} / {c['camera_height']} / {c['angle']} / {c['gaze']} / {c['aspect']} / {c['subject_position']}`", "",
                      f"尺寸：`{item['dimensions'][0]}x{item['dimensions'][1]}`", ""])
        if item["failures"]:
            lines.extend(["失败：" + "；".join(item["failures"]), ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"report": report, "json": json_path, "markdown": md_path}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行智能构图真实 Marian 模型审计")
    parser.add_argument("--cases", type=Path, default=Path(__file__).resolve().parents[3] / "tests" / "composition_semantic_cases.json")
    parser.add_argument("--output", type=Path, default=Path("reports/composition_audit"))
    args = parser.parse_args(argv)
    result = run(args.cases, args.output); summary = result["report"]["summary"]
    print(f"完成：{summary['passed']}/{summary['total']} 通过；报告：{result['markdown']}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
