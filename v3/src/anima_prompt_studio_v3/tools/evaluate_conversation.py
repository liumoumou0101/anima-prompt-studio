"""Bounded text-only quality capture through the real conversation service."""
import argparse
import asyncio
from copy import deepcopy
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
from time import monotonic

from ..api.conversation import ConversationService, REWRITE_SYSTEM, TurnRequest
from ..api.workspace_store import WorkspaceStore
from ..core.requirements import COMPILER_CONTRACT, WorkbenchError


CASES = {
    "dual": {
        "turns": ["两个男人并排站立。画面左边的男人没有戴帽子，画面右边的男人戴着黑色帽子。背景是街道。木刻风格。不要文字和水印。",
                  "只把光线改为傍晚暖侧光，人物和各自的帽子状态不变。", "只把背景从街道改成火车站，其他不变。"],
        "review": "两人、左不戴帽右戴黑帽、木刻不变；negative 不全局禁止帽子；只改光线和背景。"},
    "manual": {
        "turns": ["一位短发女子穿深蓝色外套，站在安静的街道。水彩风格。不要文字。",
                  "只把光线改成柔和的清晨侧光，保留已手改的英文细节。", "只把背景改成火车站，保留其他内容和已手改的英文细节。"],
        "review": "第二轮前手加 red scarf；发型、深蓝外套、水彩、红围巾和负向保留。"},
    "woodcut": {
        "turns": ["两个成年人面对面交接一个包裹，左边的人双手递出包裹，右边的人双手接过。黑白木刻，密集平行排线。不要文字和水印。",
                  "只增加逆光，保留两人交接同一个包裹的动作和木刻媒介。",
                  "适度扩写画面细节，保持人数、交接动作、木刻媒介和逆光不变，不添加人物或画师。列明新增细节。"],
        "review": "两人交接一个包裹、左右动作、木刻和平行排线保留；扩写新增内容须有 warnings；不臆造画师或资源。"},
    "detective": {
        "turns": ["一位短发女侦探穿风衣，右手拿信，站在车站。黑白画面。不要文字和水印。",
                  "只把光线改成清晨冷侧光。", "只把构图改为半身近景。"],
        "review": "首轮后锁主体；一人、短发、风衣、右手信不变；只改光线和构图。"},
    "charcoal": {
        "turns": ["一位短发女子抱着一只小猫，站在窗边。保留钉选的炭笔风格。不要文字和水印。",
                  "只把光线改成柔和侧光，主体和炭笔风格不变。", ""],
        "review": "提示词提取后 style pin 不复制原男性主体；第三轮前删除测试 LoRA 再纯重编译，不带回资源，不臆造作者。"},
}

CHARCOAL_PROMPT = "one elderly man with a beard, charcoal drawing on textured paper, soft smudged shading, monochrome"


async def prepare_charcoal(output, store, workspace, reference_image):
    from ..api.reference_ingest import IngestRequest, IngestService
    from ..storage.reference_examples import ExampleStore, ExampleMetadata, ExamplePatch, now
    from ..core.requirements import Requirements, apply_pin, dump
    examples = ExampleStore(output / "examples.db")
    example = examples.create(reference_image.read_bytes(), "炭笔文字验收", ExampleMetadata(notes={"external_prompt": CHARCOAL_PROMPT}))
    analyzed = await IngestService(examples).ingest(example["id"], IngestRequest(revision=example["revision"], source="prompt"))
    requirements = deepcopy(analyzed["requirements"])
    # Explicit synthetic metadata fixture, never an installed or executed model.
    requirements["loras"] = [{"logical_id": "evaluation-charcoal", "file_name": "evaluation-charcoal.safetensors"}]
    source = examples.patch(example["id"], ExamplePatch(revision=analyzed["revision"], title=example["title"],
        notes=analyzed["notes"], requirements_edit={key: requirements[key] for key in ("layers", "loras")}))
    def pin(draft):
        draft["requirements"] = dump(apply_pin(Requirements.empty(), Requirements.model_validate(source["requirements"]), "style"))
        draft["reference_pin"] = dict(example_id=source["id"], source_version=source["source_version"], role="style",
            pinned_at=now(), source_snapshot={"requirements": source["requirements"], "compat": source["compat"]})
        return draft
    workspace = store.transform(workspace["id"], expected_revision=workspace["revision"], operation=pin)
    return workspace, {"analyzed": analyzed, "source": source, "after_pin": workspace, "synthetic_lora": True}


def configured_model():
    from ..prompt_assistant.config_manager import config_manager
    from ..prompt_assistant.services.llm import LLMService
    config = LLMService._get_config()
    service = config_manager.get_service(config.get("provider", "")) or {}
    ready = bool(config.get("model") and config.get("base_url") and config.get("api_key") and config.get("provider") != "ollama")
    return ready, {key: config.get(key) for key in ("provider", "model", "temperature", "top_p", "max_tokens")} | {
        "enable_advanced_params": bool(service.get("enable_advanced_params", False)), "thinking_disabled_requested": True}


@contextmanager
def temporary_model(model):
    """CLI-only override; never write provider settings or leave an override behind."""
    if model is None:
        yield
        return
    if not isinstance(model, str) or not model.strip() or len(model) > 200:
        raise ValueError("Invalid model override")
    from ..prompt_assistant.services.llm import LLMService
    original = LLMService.__dict__["_get_config"]
    get_config = LLMService._get_config
    LLMService._get_config = staticmethod(lambda: {**get_config(), "model": model.strip()})
    try:
        yield
    finally:
        LLMService._get_config = original


async def evaluate(case, output, *, repeats=1, model_override=None, reference_image=None):
    # Run one suite per process: the service reads the same process-local override.
    with temporary_model(model_override):
        return await _evaluate(case, output, repeats=repeats, reference_image=reference_image)


async def _evaluate(case, output, *, repeats=1, reference_image=None):
    if case not in CASES or type(repeats) is not int or not 1 <= repeats <= 3:
        raise ValueError("Invalid scenario or repeat count")
    if case == "charcoal" and (reference_image is None or not Path(reference_image).is_file()):
        raise ValueError("Charcoal evaluation requires a local reference image")
    ready, model = configured_model()
    if not ready:
        raise ValueError("Configure a cloud text model and key first")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    store = WorkspaceStore(output / "workspaces.db")
    service = ConversationService(store)
    report = {"contract": "anima-conversation-evaluation/1", "compiler_contract": COMPILER_CONTRACT,
              "system_sha256": sha256(REWRITE_SYSTEM.encode()).hexdigest(), "model": model,
              "case": case, "scenario": deepcopy(CASES[case]), "planned_calls": repeats * 3,
              "planned_prompt_ingests": repeats if case == "charcoal" else 0, "reference_preparations": [],
              "started_at": datetime.now(UTC).isoformat(), "status": "running", "results": [],
              "quality_verdict": "pending_manual_review", "entrypoint": "ConversationService.turn"}

    def save():
        temp = output / "report.tmp"
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(output / "report.json")

    save()
    for repeat in range(repeats):
        workspace = store.create(case, {"model_profile": "anima_base_v1"})
        if case == "charcoal":
            prep = {"repeat": repeat + 1, "status": "started", "source": "prompt", "external_prompt": CHARCOAL_PROMPT,
                    "reference_sha256": sha256(Path(reference_image).read_bytes()).hexdigest()}
            report["reference_preparations"].append(prep)
            save()
            try:
                workspace, detail = await prepare_charcoal(output, store, workspace, Path(reference_image))
            except (Exception, asyncio.CancelledError) as exc:
                prep.update(status="failed", reason="reference_preparation_failed")
                report["status"] = "stopped"
                save()
                if isinstance(exc, asyncio.CancelledError):
                    raise
                return report
            prep.update(status="completed", **detail)
            save()
        for index, delta in enumerate(CASES[case]["turns"]):
            preparation = None
            if case == "charcoal" and index == 2:
                requirements = deepcopy(workspace["draft"]["requirements"])
                requirements["loras"] = []
                workspace = store.update(workspace["id"], expected_revision=workspace["revision"], title=case,
                    draft={"model_profile": workspace["draft"]["model_profile"],
                           "requirements_edit": {key: requirements[key] for key in ("layers", "loras")}})
                preparation = deepcopy(workspace)
            if index == 1 and case in {"manual", "detective"}:
                if case == "manual":
                    prompt = {key: workspace["draft"]["compiled"][key] for key in ("positive", "negative")}
                    prompt["positive"] += ", wearing a red scarf"
                    edit = {"prompt_edit": prompt}
                else:
                    requirements = deepcopy(workspace["draft"]["requirements"])
                    requirements["layers"]["subject"]["locked"] = True
                    edit = {"requirements_edit": {key: requirements[key] for key in ("layers", "loras")}}
                edit["model_profile"] = workspace["draft"]["model_profile"]
                workspace = store.update(workspace["id"], expected_revision=workspace["revision"], title=case, draft=edit)
                preparation = deepcopy(workspace)
            mode = "expand" if case == "woodcut" and index == 2 else "faithful"
            row = {"repeat": repeat + 1, "turn": index + 1, "mode": mode, "delta": delta,
                   "started_at": datetime.now(UTC).isoformat(), "before": deepcopy(workspace),
                   "preparation": preparation, "status": "started", "manual_review": None}
            report["results"].append(row)
            save()  # Persist attempt before a possibly chargeable request; never auto-resume.
            started = monotonic()
            try:
                workspace = await service.turn(TurnRequest(workspace_id=workspace["id"], revision=workspace["revision"],
                                                           mode=mode, delta={"text": delta}))
            except (Exception, asyncio.CancelledError) as exc:
                from ..prompt_assistant.services.completion import CompletionError
                details = exc.safe_details if isinstance(exc, CompletionError) else {
                    "reason": "llm_timeout" if isinstance(exc, TimeoutError) else "evaluation_failed"}
                if isinstance(exc, WorkbenchError) and exc.code in {"invalid_layer_updates", "llm_generation_failed", "thinking_disable_unsupported", "rate_limited"}:
                    details = {"reason": exc.code}
                restored = WorkspaceStore(output / "workspaces.db").get(workspace["id"])
                row.update(status="interrupted" if isinstance(exc, asyncio.CancelledError) else "failed", error=details,
                           elapsed_s=round(monotonic() - started, 3),
                           failure_preserved_workspace=restored["draft"] == workspace["draft"] and restored["revision"] == workspace["revision"])
                report["status"] = "stopped"
                save()
                if isinstance(exc, asyncio.CancelledError):
                    raise
                return report
            restored = WorkspaceStore(output / "workspaces.db").get(workspace["id"])
            row.update(status="completed", result=workspace, elapsed_s=round(monotonic() - started, 3),
                       restored=restored["draft"] == workspace["draft"] and restored["revision"] == workspace["revision"])
            save()
            if not row["restored"]:
                report["status"] = "stopped"
                save()
                return report
    report["status"] = "completed"
    save()
    return report


def main():
    parser = argparse.ArgumentParser(description="文字多轮隔离验收；默认预检，显式 --execute 才调用模型。")
    parser.add_argument("case", choices=CASES)
    parser.add_argument("--repeats", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--config-dir", type=Path)
    parser.add_argument("--model", help="仅本次进程使用该模型，不保存到用户配置")
    parser.add_argument("--reference-image", type=Path, help="charcoal 场景的本地图；模型只收到固定提示词文字")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.config_dir is not None:
            directory = args.config_dir.resolve(strict=True)
            if not (directory / "config/config.json").is_file():
                raise ValueError("Configuration not saved")
            os.environ["ANIMA_PROMPT_ASSISTANT_DIR"] = str(directory)
        with temporary_model(args.model):
            ready, model = configured_model()
        if args.case == "charcoal" and (args.reference_image is None or not args.reference_image.is_file()):
            parser.error("charcoal requires --reference-image")
        if not args.execute:
            print(json.dumps({"ready": ready, "model": model, "case": args.case, "planned_calls": args.repeats * 3,
                              "planned_prompt_ingests": args.repeats if args.case == "charcoal" else 0, "executed": False}))
            return
        if args.output is None:
            parser.error("--execute requires a new --output directory")
        report = asyncio.run(evaluate(args.case, args.output, repeats=args.repeats, model_override=args.model, reference_image=args.reference_image))
        print(f"{report['status']}: {len(report['results'])} attempts; quality verdict pending manual review")
        if report["status"] != "completed":
            parser.exit(1)
    except (ValueError, OSError):
        parser.exit(1, "验收未启动或记录写入失败，请检查配置和全新输出目录。\n")


if __name__ == "__main__":
    main()
