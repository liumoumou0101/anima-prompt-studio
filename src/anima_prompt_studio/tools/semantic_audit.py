from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from anima_prompt_studio.domain.models import LoRAProfile, PromptJob
from anima_prompt_studio.services.pipeline import PromptPipeline
from anima_prompt_studio.services.resource_manager import ResourceManager
from anima_prompt_studio.services.translation_service import LocalMarianEngine, TranslationService


def evaluate(case: dict, job: PromptJob) -> list[str]:
    failures: list[str] = []
    tag_section, _, prose = job.positive_prompt.partition("\n\n")
    english = job.translated_en.lower()
    natural = (prose or "\n".join(
        [job.translated_en] + [item.content for item in job.enhancements if item.enabled]
    )).lower()
    tags = ({tag.strip().lower() for tag in tag_section.split(",") if tag.strip()}
            if job.positive_prompt else {item.tag.lower() for item in job.matched_tags})
    combined = english + "\n" + "\n".join(tags)
    enhancement_ids = {item.id for item in job.enhancements if item.enabled}
    for value in case.get("require_all", []):
        if value.lower() not in combined:
            failures.append(f"缺少概念：{value}")
    for value in case.get("require_en_all", []):
        if value.lower() not in natural:
            failures.append(f"英文缺少：{value}")
    for group in case.get("require_en_any", []):
        if not any(value.lower() in natural for value in group):
            failures.append("英文未命中任一表达：" + " | ".join(group))
    for tag in case.get("require_tags", []):
        if tag.lower() not in tags:
            failures.append(f"缺少标签：{tag}")
    for group in case.get("require_tags_any", []):
        if not any(tag.lower() in tags for tag in group):
            failures.append("标签未命中任一值：" + " | ".join(group))
    for tag in case.get("forbid_tags", []):
        if tag.lower() in tags:
            failures.append(f"出现禁止标签：{tag}")
    for value in case.get("forbid_en", []):
        if value.lower() in natural:
            failures.append(f"出现禁止英文：{value}")
    for rule in case.get("require_enhancements", []):
        if rule not in enhancement_ids:
            failures.append(f"未触发增强：{rule}")
    for rule in case.get("forbid_enhancements", []):
        if rule in enhancement_ids:
            failures.append(f"错误触发增强：{rule}")
    if "expect_people_count" in case and job.composition.people_count != case["expect_people_count"]:
        failures.append(f"人数错误：期望 {case['expect_people_count']}，实际 {job.composition.people_count}")
    for artist in case.get("expect_artists", []):
        if artist not in job.artist_selection:
            failures.append(f"画师未进入画师区：{artist}")
    for field_name, expected in case.get("expect_composition", {}).items():
        actual = getattr(job.composition, field_name)
        if actual != expected:
            failures.append(f"构图 {field_name}：期望 {expected}，实际 {actual}")
    red_warnings = [warning for warning in job.semantic_warnings if warning.level.value == "red"]
    if case.get("fail_on_red_warning") and red_warnings:
        failures.append("存在红色语义警告：" + "；".join(x.message for x in red_warnings))
    negative = job.negative_prompt.lower()
    for value in case.get("require_negative", []):
        if value.lower() not in negative:
            failures.append(f"负面提示词缺少：{value}")
    for value in case.get("forbid_negative", []):
        if value.lower() in negative:
            failures.append(f"负面提示词出现禁止内容：{value}")
    excluded = {x.canonical_tag.lower() for x in job.semantic_frame.excluded_concepts}
    for value in case.get("require_excluded_concepts", []):
        if value.lower() not in excluded:
            failures.append(f"排除概念缺少：{value}")
    expected_subject = case.get("expect_subject_mode")
    if expected_subject and job.effective_subject_mode().value != expected_subject:
        failures.append(f"主体模式：期望 {expected_subject}，实际 {job.effective_subject_mode().value}")
    selected_loras = {x.logical_id: x for x in job.lora_selection}
    for expected in case.get("expect_loras", []):
        logical_id = expected if isinstance(expected, str) else expected["logical_id"]
        if logical_id not in selected_loras:
            failures.append(f"未绑定 LoRA：{logical_id}")
            continue
        if isinstance(expected, dict):
            actual = selected_loras[logical_id]
            for field_name in ("file_name", "weight", "trigger_words"):
                if field_name in expected and getattr(actual, field_name) != expected[field_name]:
                    failures.append(f"LoRA {logical_id} 的 {field_name} 不匹配")
    failures.extend("最终一致性：" + value for value in job.consistency_failures)
    failures.extend("英文清洁性：" + value for value in job.cleanliness_failures)
    return failures


def run(cases_path: Path, output_dir: Path) -> dict:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    resources = ResourceManager()
    if not resources.models_available():
        raise RuntimeError("真实双向翻译模型尚未安装。")
    started = time.perf_counter()
    engine = LocalMarianEngine(resources.model_path("zh_en"), resources.model_path("en_zh"))
    load_seconds = time.perf_counter() - started
    pipeline = PromptPipeline(translation=TranslationService(engine))
    results = []
    print(f"已加载真实模型，用例数：{len(cases)}", flush=True)
    for index, case in enumerate(cases, 1):
        before = time.perf_counter()
        job = PromptJob(original_zh=case["input"])
        pipeline.set_lora_profiles([LoRAProfile.model_validate(x) for x in case.get("lora_profiles", [])])
        pipeline.compiler.apply_model_defaults(job)
        error = None
        try:
            pipeline.translate(job, [tuple(x) for x in case.get("known_entities", [])])
            failures = evaluate(case, job)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            failures = ["执行异常：" + error]
        elapsed = time.perf_counter() - before
        result = {
            "id": case["id"], "group": case["group"], "input": case["input"],
            "passed": not failures, "failures": failures, "seconds": round(elapsed, 3),
            "translated_en": job.translated_en, "back_translated_zh": job.back_translated_zh,
            "canonical_prose": job.canonical_prose, "negative_prompt": job.negative_prompt,
            "positive_prompt": job.positive_prompt,
            "tags": [tag.strip() for tag in job.positive_prompt.partition("\n\n")[0].split(",") if tag.strip()],
            "enhancements": [{"id": x.id, "type": x.type, "content": x.content, "enabled": x.enabled} for x in job.enhancements],
            "warnings": [{"level": x.level.value, "message": x.message} for x in job.semantic_warnings],
            "excluded_concepts": [x.model_dump(mode="json") for x in job.semantic_frame.excluded_concepts],
            "subject_mode": job.effective_subject_mode().value,
            "composition": job.composition.model_dump(mode="json"),
            "artists": job.artist_selection,
            "loras": [x.model_dump(mode="json") for x in job.lora_selection],
            "consistency_failures": job.consistency_failures,
            "cleanliness_failures": job.cleanliness_failures,
            "error": error,
        }
        results.append(result)
        print(f"[{index:02d}/{len(cases)}] {'PASS' if result['passed'] else 'FAIL'} {case['id']} ({elapsed:.2f}s)", flush=True)

    group_counts: dict[str, Counter] = defaultdict(Counter)
    for result in results:
        group_counts[result["group"]]["total"] += 1
        group_counts[result["group"]]["passed" if result["passed"] else "failed"] += 1
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_engine": engine.name, "model_load_seconds": round(load_seconds, 3),
        "total_seconds": round(time.perf_counter() - started, 3),
        "summary": {
            "total": len(results), "passed": sum(x["passed"] for x in results),
            "failed": sum(not x["passed"] for x in results),
            "groups": {key: dict(value) for key, value in group_counts.items()},
        },
        "results": results,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "semantic_audit_current.json"
    md_path = output_dir / "semantic_audit_current.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 当前版本真实模型语义审计", "", f"生成时间：{report['generated_at']}",
        f"模型加载：{report['model_load_seconds']} 秒", f"总耗时：{report['total_seconds']} 秒", "",
        f"总计：{report['summary']['total']}；通过：{report['summary']['passed']}；失败：{report['summary']['failed']}", "",
        "## 分类结果", "", "| 分类 | 通过 | 失败 | 总计 |", "|---|---:|---:|---:|",
    ]
    for group, counts in report["summary"]["groups"].items():
        lines.append(f"| {group} | {counts.get('passed',0)} | {counts.get('failed',0)} | {counts.get('total',0)} |")
    red_results = [item for item in results if any(x["level"] == "red" for x in item["warnings"])]
    lines.extend(["", f"红色警告用例：{len(red_results)}", "", "## 失败详情", ""])
    for result in results:
        if result["passed"]:
            continue
        lines.extend([
            f"### {result['id']}", "", f"输入：`{result['input']}`", "",
            "失败：" + "；".join(result["failures"]), "", f"英文：`{result['translated_en']}`", "",
            f"Canonical prose：`{result['canonical_prose']}`", "",
            "标签：`" + ", ".join(result["tags"]) + "`", "",
            f"Negative：`{result['negative_prompt']}`", "",
            f"主体模式：`{result['subject_mode']}`", "",
        ])
    lines.extend(["", "## 红色警告详情", ""])
    for result in red_results:
        messages = "；".join(x["message"] for x in result["warnings"] if x["level"] == "red")
        lines.extend([f"### {result['id']}", "", f"输入：`{result['input']}`", "", f"警告：{messages}", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": json_path, "markdown": md_path, "report": report}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行真实 Marian 模型语义审计")
    default_cases = Path(__file__).resolve().parents[3] / "tests" / "discovery_semantic_cases.json"
    parser.add_argument("--cases", type=Path, default=default_cases)
    parser.add_argument("--output", type=Path, default=Path("reports"))
    args = parser.parse_args(argv)
    result = run(args.cases, args.output)
    summary = result["report"]["summary"]
    print(f"完成：{summary['passed']}/{summary['total']} 通过；报告：{result['markdown']}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
