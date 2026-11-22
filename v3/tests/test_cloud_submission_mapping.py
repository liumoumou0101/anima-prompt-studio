"""An inspection can provide exact catalog mappings without changing user bindings."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from anima_prompt_studio_v3.remote.comfy_client import ComfyAPIError
from anima_prompt_studio_v3.remote.preparation_budget import DirectPreparationTimeout
from anima_prompt_studio_v3.runtime.cloud_model_catalog import CloudModelCatalog
from anima_prompt_studio_v3.runtime.packaged_workflows import packaged_workflow_profiles
from anima_prompt_studio_v3.runtime.workflow_catalog import WorkflowCatalog, apply_mapping
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
from test_http_runtime_identity import profile


@pytest.fixture
def inspected_catalog(tmp_path, monkeypatch):
    database = tmp_path / "runtime.db"
    remote = profile(None, False)
    repository = SQLiteRepository(database)
    repository.save_remote_profile(remote)
    repository.close()
    workflows = [workflow for workflow in packaged_workflow_profiles()
                 if "miaomiao_harem_anima_v1_6" in workflow.compatible_model_profiles]
    info = {}
    choices = {"unet_name": ["miaomiaoHarem_anima16.safetensors"],
               "clip_name": ["qwen_3_06b_base.safetensors"],
               "vae_name": ["qwen_image_vae.safetensors"]}
    for workflow in workflows:
        for node in workflow.api_workflow.values():
            required = info.setdefault(node["class_type"], {"input": {"required": {}}})["input"]["required"]
            for key, value in node["inputs"].items():
                if key in choices:
                    required[key] = [choices[key]]
                elif key in {"sampler_name", "scheduler"}:
                    required.setdefault(key, [[value]])
                    if value not in required[key][0]:
                        required[key][0].append(value)
    document = {"protocol_version": 1, "runtime_id": "catalog-runtime", "models": [{
        "id": "miaomiao_harem_anima_v1_6", "display_name": "MiaoMiao", "family": "ANIMA",
        "ready": True, "selected_for_startup": True,
        "checkpoint": "diffusion_models/miaomiaoHarem_anima16.safetensors",
        "text_encoder": "text_encoders/qwen_3_06b_base.safetensors",
        "vae": "vae/qwen_image_vae.safetensors",
        "assets": ["diffusion_models/miaomiaoHarem_anima16.safetensors",
                   "text_encoders/qwen_3_06b_base.safetensors", "vae/qwen_image_vae.safetensors"],
        "suggested_defaults": {"steps": 35, "cfg": 4.5, "sampler": "er_sde", "scheduler": "normal"},
    }]}
    state = SimpleNamespace(database=database, remote=remote, workflows=workflows, info=info,
                            document=document, calls=[], failure=None, on_read=None)

    class Client:
        def validate_environment(self):
            state.calls.append("environment")
            return SimpleNamespace(devices=["GPU"], system_stats={"system": {"comfyui_version": "0.33.1"}})

        def object_info(self, **kwargs):
            state.calls.append("object_info")
            return info

        def read_bounded(self, path, **kwargs):
            state.calls.append(path)
            if path == "/_moss/info":
                return json.dumps({"runtime_id": document["runtime_id"]}).encode()
            if state.on_read:
                state.on_read()
            if state.failure:
                raise state.failure
            assert path == "/_moss/models"
            return json.dumps(document).encode()

    monkeypatch.setattr("anima_prompt_studio_v3.runtime.workflow_catalog.connection_factory",
                        lambda *args, **kwargs: SimpleNamespace(open=lambda *args: None, close=lambda: None))
    monkeypatch.setattr("anima_prompt_studio_v3.runtime.workflow_catalog.client_for_connection",
                        lambda *args, **kwargs: Client())
    state.manager = WorkflowCatalog(database)
    state.service = CloudModelCatalog(database)
    return state


def test_first_plain_http_inspection_captures_catalog_and_exact_miao_mapping(inspected_catalog):
    state = inspected_catalog
    state.manager.inspect(state.remote.id)
    assert state.calls == ["environment", "object_info", "/_moss/models"]
    report = state.service.report(state.remote.id)
    assert report["status"] == "ready" and report["runtime_id"] == "catalog-runtime"
    for workflow in state.workflows:
        mapping = state.service.get_submission_mapping(state.remote.id, "miaomiao_harem_anima_v1_6", workflow.id, state.info)
        assert mapping == {"1.unet_name": "miaomiaoHarem_anima16.safetensors",
                           "3.clip_name": "qwen_3_06b_base.safetensors", "8.vae_name": "qwen_image_vae.safetensors"}
        mapped = apply_mapping(workflow, mapping)
        assert mapped.runtime_assets["text_encoder"] == "qwen_3_06b_base.safetensors"
    repository = SQLiteRepository(state.database)
    try:
        assert repository.get_remote_profile(state.remote.id) == state.remote
        assert repository.get_setting("http_runtime_identity:" + state.remote.id)["runtime_id"] == "catalog-runtime"
        assert repository.get_setting("workflow_mapping:" + state.remote.id + ":" + state.workflows[0].id) is None
    finally:
        repository.close()


@pytest.mark.parametrize("change", ["session", "epoch", "fingerprint", "revision", "age", "identity"])
def test_submission_mapping_rejects_changed_snapshot(inspected_catalog, change):
    state = inspected_catalog
    state.manager.inspect(state.remote.id)
    repository = SQLiteRepository(state.database)
    try:
        if change == "session":
            repository.save_remote_profile(state.remote.model_copy(update={"http_session_id": "new-session"}))
        elif change == "fingerprint":
            repository.save_remote_profile(state.remote.model_copy(update={"http_base_url": "https://new.example.test"}))
        elif change == "epoch":
            repository.set_setting("environment_epoch:" + state.remote.id, 1)
        elif change == "revision":
            repository.save_workflow_profile(state.workflows[0].model_copy(update={"display_name": "new revision"}))
        elif change == "identity":
            repository.set_setting("http_runtime_identity:" + state.remote.id,
                {"session_id": state.remote.http_session_id, "runtime_id": "different-runtime", "conflicted": False})
        else:
            snapshot = repository.get_setting("cloud_model_catalog:" + state.remote.id)
            snapshot["checked_at"] = 0
            repository.set_setting("cloud_model_catalog:" + state.remote.id, snapshot)
    finally:
        repository.close()
    assert state.service.get_submission_mapping(state.remote.id, "miaomiao_harem_anima_v1_6", state.workflows[0].id, state.info) is None


def test_submission_mapping_revalidates_live_enums_and_returns_independent_values(inspected_catalog):
    state = inspected_catalog
    state.manager.inspect(state.remote.id)
    mapping = state.service.get_submission_mapping(state.remote.id, "miaomiao_harem_anima_v1_6", state.workflows[0].id, state.info)
    mapping["3.clip_name"] = "changed"
    assert state.service.get_submission_mapping(state.remote.id, "miaomiao_harem_anima_v1_6", state.workflows[0].id, state.info)["3.clip_name"] == "qwen_3_06b_base.safetensors"
    info = deepcopy(state.info)
    info["CLIPLoader"]["input"]["required"]["clip_name"] = [["unrelated.safetensors"]]
    assert state.service.get_submission_mapping(state.remote.id, "miaomiao_harem_anima_v1_6", state.workflows[0].id, info) is None


def test_ordinary_http_without_catalog_keeps_workflow_inspection(inspected_catalog):
    state = inspected_catalog
    state.info["CLIPLoader"]["input"]["required"]["clip_name"] = [["miaomiaoHarem_anima16_txt.safetensors"]]
    state.failure = ComfyAPIError("not supported", code="unsupported")
    state.manager.inspect(state.remote.id)
    report = state.manager.report(state.remote.id)
    assert report["checked_at"] is not None
    assert next(item for item in report["items"] if item["workflow_id"] == state.workflows[0].id)["state"] == "ready"
    assert state.service.get_submission_mapping(state.remote.id, "miaomiao_harem_anima_v1_6", state.workflows[0].id, state.info) is None


@pytest.mark.parametrize("change", ["missing_file", "unsupported_model", "missing_node"])
def test_submission_mapping_never_returns_incomplete_or_unsupported_catalog(inspected_catalog, change):
    state = inspected_catalog
    if change == "missing_file":
        state.document["models"][0]["ready"] = False
    elif change == "unsupported_model":
        state.document["models"][0]["family"] = "MOSS"
    state.manager.inspect(state.remote.id)
    info = deepcopy(state.info)
    if change == "missing_node":
        info.pop("ModelSamplingAuraFlow")
    assert state.service.get_submission_mapping(state.remote.id, "miaomiao_harem_anima_v1_6", state.workflows[0].id, info) is None


def test_inspection_catalog_timeout_preserves_preparation_timeout(inspected_catalog):
    state = inspected_catalog
    state.failure = DirectPreparationTimeout()
    with pytest.raises(DirectPreparationTimeout):
        state.manager.inspect(state.remote.id)


def test_inspection_runtime_conflict_is_not_downgraded_to_missing_catalog(inspected_catalog):
    state = inspected_catalog
    state.manager.inspect(state.remote.id)
    state.document["runtime_id"] = "replacement-runtime"
    with pytest.raises(ComfyAPIError) as error:
        state.manager.inspect(state.remote.id)
    assert error.value.code == "runtime_identity_mismatch"
    repository = SQLiteRepository(state.database)
    try:
        assert repository.get_setting("http_runtime_identity:" + state.remote.id)["conflicted"]
        assert repository.get_remote_profile(state.remote.id).http_session_id == state.remote.http_session_id
    finally:
        repository.close()


def test_inspection_catalog_discards_result_if_epoch_changes_during_read(inspected_catalog):
    state = inspected_catalog
    def rebuild():
        repository = SQLiteRepository(state.database)
        repository.set_setting("environment_epoch:" + state.remote.id, 1)
        repository.close()
    state.on_read = rebuild
    state.manager.inspect(state.remote.id)
    assert state.service.get_submission_mapping(state.remote.id, "miaomiao_harem_anima_v1_6", state.workflows[0].id, state.info) is None
