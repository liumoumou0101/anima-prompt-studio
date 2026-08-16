"""Run the visual-semantic benchmark without opening the Qt UI.

The worker uses the same PromptPipeline and SSH + ComfyUI execution layer as
the desktop app, but processes cases sequentially in a standalone process.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from anima_prompt_studio.domain.execution_models import RemoteCredentials
from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio.repositories.sqlite_repository import SQLiteRepository
from anima_prompt_studio.services.pipeline import PromptPipeline
from anima_prompt_studio.services.resource_manager import ResourceManager
from anima_prompt_studio.services.remote.credential_store import CredentialStore
from anima_prompt_studio.services.remote.execution_coordinator import (
    RemoteExecutionCoordinator,
    RemoteExecutionError,
)
from anima_prompt_studio.services.remote.result_organizer import ResultOrganizer
from anima_prompt_studio.services.translation_service import (
    LazyLocalMarianEngine,
    TranslationService,
    marian_runtime_available,
)


BENCHMARK_PATH = ROOT / "benchmarks" / "visual_semantics_v1.json"
CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")


def build_pipeline() -> PromptPipeline:
    """Build the same translation pipeline used by the desktop UI.

    A visual benchmark must fail before contacting the GPU when the full local
    translator is unavailable.  Silently falling back to the small builtin
    lexicon leaves free-form Chinese in prompts and invalidates model results.
    """
    resources = ResourceManager()
    if not marian_runtime_available():
        raise RuntimeError("Marian 翻译运行环境不可用，已中止测试，未提交云端任务。")
    if not resources.models_available():
        raise RuntimeError("Marian 中英双向模型不完整，已中止测试，未提交云端任务。")
    translation = TranslationService(LazyLocalMarianEngine(
        resources.model_path("zh_en"),
        resources.model_path("en_zh"),
    ))
    return PromptPipeline(translation=translation)


def validate_generation_prompt(job: PromptJob) -> None:
    residual = CJK_PATTERN.search(job.positive_prompt)
    if residual:
        context_start = max(0, residual.start() - 24)
        context_end = min(len(job.positive_prompt), residual.end() + 24)
        context = job.positive_prompt[context_start:context_end]
        raise RuntimeError(f"最终正向提示词仍含中文，拒绝提交云端：{context!r}")


def atomic_write(path: Path, payload: object) -> None:
    temporary = path.with_name(path.name + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def choose_workflow(repository: SQLiteRepository, workflow_id: str, model_profile_id: str):
    profiles = repository.list_workflow_profiles()
    if workflow_id:
        return repository.get_workflow_profile(workflow_id)
    candidates = [
        profile for profile in profiles
        if profile.workflow_kind == "txt2img_basic"
        and model_profile_id in profile.compatible_model_profiles
    ]
    preferred_prefix = "02" if model_profile_id == "anima_turbo_v1" else "22"
    preferred = next((item for item in candidates if item.id.startswith(preferred_prefix)), None)
    return preferred or (candidates[0] if candidates else None)


def build_job(
    case: dict,
    pipeline: PromptPipeline,
    seed: int,
    index: int,
    model_profile_id: str,
    generation_preset_id: str,
) -> PromptJob:
    job = PromptJob(
        project_name=f"visual_benchmark_fast_{index:02d}_{case['id']}",
        original_zh=case["source_zh"],
        model_profile_id=model_profile_id,
        generation_preset_id=generation_preset_id,
        quality_profile_id="standard",
    )
    pipeline.compiler.apply_model_defaults(job)
    job.generation_params.seed = seed
    job.generation_params.batch_size = 1
    pipeline.translate(job)
    # Applying the model defaults before translation is sufficient for the
    # current pipeline, but this keeps fast-preset settings authoritative if
    # future translation stages alter the job.
    pipeline.compiler.apply_model_defaults(job)
    job.generation_params.seed = seed
    job.generation_params.batch_size = 1
    return job


def main() -> int:
    parser = argparse.ArgumentParser(description="后台执行 ANIMA 视觉语义快速筛查")
    parser.add_argument("--workflow-id", default="", help="已保存的 ComfyUI 工作流 ID")
    parser.add_argument("--model-profile", default="anima_turbo_v1")
    parser.add_argument("--preset", default="fast")
    parser.add_argument("--seed-start", type=int, default=761001)
    parser.add_argument("--case-id", action="append", dest="case_ids", default=[])
    parser.add_argument("--poll-interval", type=float, default=1.5)
    args = parser.parse_args()

    benchmark = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    cases = benchmark["cases"]
    if args.case_ids:
        wanted = set(args.case_ids)
        cases = [case for case in cases if case["id"] in wanted]
        missing = wanted - {case["id"] for case in cases}
        if missing:
            raise SystemExit(f"未知用例：{', '.join(sorted(missing))}")

    repository = SQLiteRepository()
    remote_id = repository.get_setting("last_remote_profile_id", "")
    if not remote_id:
        raise SystemExit("没有保存的上次云主机配置。")
    remote = repository.get_remote_profile(remote_id)
    workflow = choose_workflow(repository, args.workflow_id, args.model_profile)
    if workflow is None:
        raise SystemExit(f"没有找到兼容 {args.model_profile} 的基础文生图工作流。")

    password = CredentialStore().read_password(remote.id)
    if remote.auth_type.value == "password" and not password:
        raise SystemExit("云主机使用密码认证，但 Windows 凭据管理器中没有读取到密码。")
    credentials = RemoteCredentials(password=password)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_label = re.sub(r"[^a-z0-9]+", "_", args.model_profile.lower()).strip("_")
    report_root = ROOT / "reports" / f"visual_benchmark_{model_label}_{stamp}"
    prompt_root = report_root / "prompt_snapshots"
    prompt_root.mkdir(parents=True, exist_ok=True)
    artifact_root = report_root / "images"
    artifact_root.mkdir(parents=True, exist_ok=True)
    report_path = report_root / "benchmark_report.json"
    log_path = report_root / "worker.log"

    report = {
        "schema_version": "1.0",
        "started_at": datetime.now().astimezone().isoformat(),
        "benchmark": str(BENCHMARK_PATH),
        "model_profile_id": args.model_profile,
        "generation_preset_id": args.preset,
        "workflow_profile_id": workflow.id,
        "remote_profile_id": remote.id,
        "seed_start": args.seed_start,
        "cases": [],
    }
    atomic_write(report_path, report)

    def log(message: str) -> None:
        line = f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] {message}"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(line, flush=True)

    pipeline = build_pipeline()
    coordinator = RemoteExecutionCoordinator(
        organizer=ResultOrganizer(artifact_root),
        on_update=lambda run: log(f"{run.prompt_job_id} {run.state.value} {run.progress:.0%} {run.status_message}"),
        poll_interval=args.poll_interval,
    )

    log(
        f"开始视觉筛查：{len(cases)} 项；工作流={workflow.id}；"
        f"模型={args.model_profile}；预设={args.preset}；翻译={pipeline.translation.engine_name}"
    )
    for index, case in enumerate(cases, 1):
        seed = args.seed_start + index - 1
        entry = {
            "id": case["id"],
            "family": case["family"],
            "level": case["level"],
            "source_zh": case["source_zh"],
            "control_en": case["control_en"],
            "seed": seed,
            "state": "preparing",
            "error": "",
            "images": [],
        }
        try:
            job = build_job(case, pipeline, seed, index, args.model_profile, args.preset)
            validate_generation_prompt(job)
            snapshot = {
                "case": case,
                "job": job.task_package(),
                "translated_en": job.translated_en,
                "back_translated_zh": job.back_translated_zh,
                "canonical_prose": job.canonical_prose,
                "matched_tags": [item.model_dump(mode="json") for item in job.matched_tags],
                "semantic_warnings": [item.model_dump(mode="json") for item in job.semantic_warnings],
            }
            atomic_write(prompt_root / f"{index:02d}_{case['id']}.json", snapshot)
            entry["positive_prompt"] = job.positive_prompt
            entry["negative_prompt"] = job.negative_prompt
            entry["translated_en"] = job.translated_en
            entry["matched_tags"] = [item.tag for item in job.matched_tags]
            log(f"[{index}/{len(cases)}] {case['id']} 提交")
            result = coordinator.execute(job, remote, workflow, args.model_profile, credentials)
            entry["state"] = result.run.state.value
            entry["run_id"] = result.run.id
            entry["images"] = [artifact.local_path for artifact in result.artifacts]
            log(f"[{index}/{len(cases)}] {case['id']} 完成：{len(result.artifacts)} 张")
        except RemoteExecutionError as exc:
            entry["state"] = exc.run.state.value
            entry["run_id"] = exc.run.id
            entry["error"] = str(exc)
            log(f"[{index}/{len(cases)}] {case['id']} 失败：{exc}")
        except Exception as exc:
            entry["state"] = "failed"
            entry["error"] = f"{type(exc).__name__}: {exc}"
            log(f"[{index}/{len(cases)}] {case['id']} 异常：{exc}")
            with log_path.open("a", encoding="utf-8") as handle:
                traceback.print_exc(file=handle)
        report["cases"].append(entry)
        report["updated_at"] = datetime.now().astimezone().isoformat()
        atomic_write(report_path, report)

    report["finished_at"] = datetime.now().astimezone().isoformat()
    report["completed"] = sum(item["state"] == "completed" for item in report["cases"])
    report["failed"] = sum(item["state"] == "failed" for item in report["cases"])
    atomic_write(report_path, report)
    log(f"全部结束：完成 {report['completed']}，失败 {report['failed']}；报告={report_path}")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
