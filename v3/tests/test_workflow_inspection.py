from anima_prompt_studio_v3.remote.comfy_client import ComfyUIClient
from anima_prompt_studio_v3.adapters.v2.packaged_workflows import packaged_workflow_profiles
from anima_prompt_studio_v3.adapters.v2.workflow_inspection import inspect_workflows


def test_two_servers_produce_independent_dependency_results():
    profile = packaged_workflow_profiles()[0]
    info = {}
    for node in profile.api_workflow.values():
        info[node["class_type"]] = {"input": {"required": {
            name: [[value]] for name, value in node["inputs"].items()
            if not isinstance(value, (list, dict))
        }}}
    ready = ComfyUIClient("http://unused", session=object())
    ready._object_info_cache = info
    missing = ComfyUIClient("http://unused", session=object())
    missing._object_info_cache = {}
    assert inspect_workflows(ready, [profile])["items"][0]["state"] == "checks_passed"
    result = inspect_workflows(missing, [profile])
    assert result["items"][0]["state"] == "missing_nodes"
    assert result["generation_verified"] is False
    assert result["checked_at"]


def test_model_filename_mismatch_is_reported():
    profile = packaged_workflow_profiles()[0]
    client = ComfyUIClient("http://unused", session=object())
    client._object_info_cache = {node["class_type"]: {} for node in profile.api_workflow.values()}
    client._object_info_cache["UNETLoader"] = {"input": {"required": {"unet_name": [["different.safetensors"]]}}}
    result = inspect_workflows(client, [profile])["items"][0]
    assert result["state"] == "invalid_inputs"
    assert "different.safetensors" in result["invalid_inputs"][0]
