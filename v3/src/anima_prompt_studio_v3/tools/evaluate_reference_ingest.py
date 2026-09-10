"""Isolated, sequential reference quality capture; no automatic retries or scoring."""
import argparse
import asyncio
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path

from ..api.reference_ingest import INGEST_SYSTEM, IngestRequest, IngestService
from ..core.requirements import WorkbenchError, dump
from ..storage.official_examples import OfficialPack
from ..storage.reference_examples import ExampleMetadata, ExampleStore


def configured_model():
    from ..prompt_assistant.config_manager import config_manager
    from ..prompt_assistant.services.llm import LLMService
    config = LLMService._get_config()
    service = config_manager.get_service(config.get("provider", "")) or {}
    ready = bool(config.get("model") and config.get("api_key") and service.get("supports_vision"))
    # This suite intentionally excludes local models, as required by the quality plan.
    ready = ready and config.get("provider") != "ollama"
    return ready, {key: config.get(key) for key in ("provider", "model", "temperature", "top_p", "max_tokens")} | {
        "supports_vision": bool(service.get("supports_vision")),
        "ingest_enable_thinking": bool(service.get("ingest_enable_thinking", False)),
    }


async def evaluate(source, output):
    manifest, entries = OfficialPack.validate(source)
    ready, model = configured_model()
    if not ready:
        raise ValueError("Configure a cloud model, API key and vision support before evaluation")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    store = ExampleStore(output / "examples.db")
    ingest = IngestService(store)
    report = {"contract": "anima-ingest-evaluation/1", "pack_id": manifest.pack_id,
        "manifest_sha256": sha256((Path(source) / "examples-pack.json").read_bytes()).hexdigest(),
        "system_sha256": sha256(INGEST_SYSTEM.encode()).hexdigest(), "model": model,
        "started_at": datetime.now(UTC).isoformat(), "status": "running", "results": [],
        "quality_verdict": "pending_manual_review"}

    def save():
        temporary = output / "report.tmp"
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output / "report.json")

    save()
    for entry in entries:
        data = (Path(source) / entry.media).read_bytes()
        # Blind ingestion: do not seed confirmed requirements, title, artist or notes.
        example = store.create(data, "视觉验收图片", ExampleMetadata())
        row = {"official_id": entry.id, "example_id": example["id"],
            "image_sha256": sha256(data).hexdigest(), "expected_requirements": dump(entry.requirements),
            "status": "started", "actual_requirements": None, "manual_scores": None}
        report["results"].append(row)
        save()  # A crash leaves an ambiguous started attempt; never resume automatically.
        try:
            result = await ingest.ingest(example["id"], IngestRequest(revision=example["revision"]))
        except (Exception, asyncio.CancelledError) as exc:
            row.update(status="interrupted" if isinstance(exc, asyncio.CancelledError) else "failed",
                       error_code=exc.code if isinstance(exc, WorkbenchError) else "evaluation_failed")
            report["status"] = "stopped"
            save()
            if isinstance(exc, asyncio.CancelledError):
                raise
            return report
        row.update(status="completed", actual_requirements=result["requirements"], warnings=result["warnings"])
        save()
    report["status"] = "completed"
    save()
    return report


def main():
    parser = argparse.ArgumentParser(description="隔离记录参考图视觉分析；默认只检查，--execute 才调用模型。")
    parser.add_argument("source", type=Path)
    parser.add_argument("--config-dir", type=Path, help="与应用一致的 prompt-assistant 目录；覆盖 ANIMA_PROMPT_ASSISTANT_DIR")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.config_dir is not None:
            directory = args.config_dir.resolve(strict=True)
            if not (directory / "config/config.json").is_file():
                raise ValueError("Configuration directory has no saved config")
            os.environ["ANIMA_PROMPT_ASSISTANT_DIR"] = str(directory)
        manifest, _ = OfficialPack.validate(args.source)
        ready, model = configured_model()
        if not args.execute:
            print(json.dumps({"pack_id": manifest.pack_id, "planned_calls": manifest.counts.examples,
                              "ready": ready, "model": model, "executed": False}, ensure_ascii=True))
            return
        if args.output is None:
            parser.error("--execute requires a new --output directory")
        report = asyncio.run(evaluate(args.source, args.output))
        print(f"{report['status']}: {len(report['results'])} attempts; quality verdict pending manual review")
        if report["status"] != "completed":
            parser.exit(1)
    except (ValueError, OSError):
        parser.exit(1, "验收未能启动或写入记录，请检查配置、参考包和全新输出目录。\n")


if __name__ == "__main__":
    main()
