"""Safe reference projections and target-specific availability checks."""
from __future__ import annotations

from fastapi import Depends, Query

from ..core.requirements import RequirementLora, WorkbenchError
from ..core.lora_resolution import ResourceUnavailable
from ..core.model_versions import matches_model_declaration


def projection(example, model_profile=None, workflow_kind=None):
    requirements, compat = example["requirements"], example["compat"]
    availability = "unknown"
    if model_profile and compat["model_profiles"] and not matches_model_declaration(model_profile, compat["model_profiles"]):
        availability = "incompatible_model"
    elif workflow_kind and compat["workflow_kinds"] and workflow_kind not in compat["workflow_kinds"]:
        availability = "incompatible_workflow"
    return {"id": example["id"], "title": example["title"], "source": example["origin"],
        "source_version": example["source_version"], "compat": compat,
        "layers": {key: requirements["layers"][key] for key in ("style", "lighting", "composition")},
        "loras": requirements["loras"], "has_external_notes": bool(example["notes"]["external_prompt"]),
        "availability": availability}


def register_preset_routes(app, store, require_session):
    prefix = "/api/v3/reference-presets"
    dependencies = [Depends(require_session)]

    @app.get(prefix, dependencies=dependencies)
    def list_presets(q: str = Query(default="", max_length=200), model_profile: str | None = None,
                     workflow_kind: str | None = None, availability: str | None = None,
                     limit: int = Query(default=40, ge=1, le=100), cursor: str | None = Query(default=None, max_length=4000)):
        # The cursor is additionally bound to projection filters, not merely the source list.
        import base64
        import json
        filters = [q, model_profile, workflow_kind, availability]
        inner = None
        if cursor:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor))
                if decoded[0] != filters or not isinstance(decoded[1], str):
                    raise ValueError()
                inner = decoded[1]
            except (ValueError, TypeError, KeyError, IndexError):
                raise WorkbenchError("reference_version_conflict", "参考预设查询已变化，请重新加载。") from None
        page = store.list(q=q, limit=limit, cursor=inner)
        items = [projection(item, model_profile, workflow_kind) for item in page["items"] if item["requirements_valid"]]
        items = [item for item in items if (not model_profile or item["availability"] != "incompatible_model")
                 and (not workflow_kind or item["availability"] != "incompatible_workflow")
                 and (availability is None or item["availability"] == availability)]
        next_cursor = base64.urlsafe_b64encode(json.dumps([filters, page["next_cursor"]]).encode()).decode() if page["next_cursor"] else None
        return {"catalog_version": "anima-ref-1", "items": items,
                "next_cursor": next_cursor, "official_pack": page["official_pack"]}

    @app.get(prefix + "/{example_id}", dependencies=dependencies)
    def preset(example_id: str, source_version: str | None = Query(default=None, max_length=200)):
        example = store.get(example_id, source_version)
        if not example["requirements_valid"]:
            raise WorkbenchError("empty_requirements", "参考图尚无有效要求。")
        return projection(example)

    @app.get(prefix + "/{example_id}/availability", dependencies=dependencies)
    def preset_availability(example_id: str, source_version: str = Query(min_length=1, max_length=200),
                            remote_profile_id: str | None = None, workflow_profile_id: str | None = None,
                            model_profile: str | None = None, workflow_snapshot_run_id: str | None = None):
        from ..runtime.generation import CandidateToPromptJobAdapter
        from ..runtime.generation_queue import GenerationRunNotFoundError, GenerationQueueError

        example = store.get(example_id, source_version)
        if not example["requirements_valid"]:
            raise WorkbenchError("empty_requirements", "参考图尚无有效要求。")
        projected = projection(example, model_profile)
        base = {"id": example_id, "source_version": source_version}
        if projected["availability"] == "incompatible_model":
            return {**base, "availability": "incompatible_model"}
        queue = app.state.generation_queue
        if not remote_profile_id or not workflow_profile_id or not model_profile or queue is None or not hasattr(queue, "plan"):
            return {**base, "availability": "unknown", "message": "请选择模型、服务器和工作流后检查资源。"}
        frozen = None
        if workflow_snapshot_run_id:
            try:
                frozen = queue.get(workflow_snapshot_run_id).request_json.get("workflow_snapshot")
            except GenerationRunNotFoundError:
                pass
            if not frozen:
                raise WorkbenchError("workflow_snapshot_missing", "原任务没有可用工作流快照。")
        try:
            prepared = CandidateToPromptJobAdapter().prepare_direct(positive_prompt="reference availability check", model_profile_id=model_profile)
        except ValueError:
            raise WorkbenchError("invalid_request", "模型配置无效。") from None
        try:
            _, target, resolution = queue.plan(prepared, remote_profile_id, workflow_profile_id,
                [RequirementLora.model_validate(item) for item in example["requirements"]["loras"] if item["required"]], frozen)
            kinds = example["compat"]["workflow_kinds"]
            if kinds and target.workflow_profile.workflow_kind not in kinds:
                resolution = {"availability": "incompatible_workflow"}
        except ResourceUnavailable as exc:
            resolution = {**exc.details, "message": str(exc)}
        except (GenerationQueueError, KeyError):
            resolution = {"availability": "unknown", "message": "目标不可达或能力尚未检测。"}
        store.get(example_id, source_version)
        return {**base, **resolution}
