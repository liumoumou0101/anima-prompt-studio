from anima_prompt_studio.domain.execution_models import RemoteProfile
from anima_prompt_studio_v3.runtime.generation_queue import build_generation_queue
from anima_prompt_studio_v3.runtime.packaged_workflows import packaged_workflow_profiles
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository


def test_targets_report_source_without_merging_user_and_builtin_id_collision(tmp_path):
    database = tmp_path / "offline.db"
    profile = next(p for p in packaged_workflow_profiles() if p.id == "v3_aesthetic_v1_1")
    custom = profile.model_copy(update={"display_name": "我的同 ID 模板"})
    repository = SQLiteRepository(database)
    try:
        repository.save_remote_profile(RemoteProfile(
            id="offline", display_name="离线环境", ssh_host="example.invalid", ssh_user="tester",
        ))
        repository.save_workflow_profile(custom)
    finally:
        repository.close()
    queue = build_generation_queue(database)
    try:
        targets = {item["workflow_profile_id"]: item for item in queue.targets()}
        assert targets[profile.id]["workflow_origin"] == "user"
        assert targets[profile.id]["workflow_display_name"] == "我的同 ID 模板"
        assert targets["official:" + profile.id]["workflow_origin"] == "official"
        assert targets["official:" + profile.id]["workflow_display_name"] == profile.display_name
        assert targets["23_Turbo_v1.1"]["workflow_origin"] == "official"
        assert all(item["availability"] == "unchecked" for item in targets.values())
    finally:
        queue.shutdown()


def test_targets_expose_local_http_endpoint_instead_of_ssh_placeholders(tmp_path):
    database = tmp_path / "local-offline.db"
    repository = SQLiteRepository(database)
    try:
        for port in (8188, 8189):
            repository.save_remote_profile(RemoteProfile(
                id=f"local-{port}", display_name="本机 ComfyUI", connection_type="local",
                ssh_host="unused", ssh_user="unused", comfy_host="::1", comfy_port=port,
            ))
    finally:
        repository.close()
    queue = build_generation_queue(database)
    try:
        targets = queue.targets()
        for remote_id, port in (("local-8188", 8188), ("local-8189", 8189)):
            selected = next(item for item in targets if item["remote_profile_id"] == remote_id)
            assert selected["connection_type"] == "local"
            assert selected["remote_comfy_host"] == "::1"
            assert selected["remote_comfy_port"] == port
            assert selected["availability"] == "unchecked"
    finally:
        queue.shutdown()
