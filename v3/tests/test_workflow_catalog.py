import time
from pathlib import Path

import pytest
from anima_prompt_studio.domain.execution_models import RemoteProfile
from anima_prompt_studio.repositories import SQLiteRepository
from anima_prompt_studio_v3.adapters.v2.workflow_catalog import WorkflowCatalog, catalog, fingerprint
from anima_prompt_studio_v3.adapters.v2.packaged_workflows import packaged_workflow_profiles, migrate_packaged_workflow_ownership


@pytest.fixture
def manager(tmp_path):
    db = tmp_path / "user.db"
    repo = SQLiteRepository(db)
    for name in ("server-a", "server-b"):
        repo.save_remote_profile(RemoteProfile(id=name, display_name=name, ssh_host="example.invalid", ssh_user="tester", known_host_fingerprint="SHA256:test"))
    repo.close()
    return WorkflowCatalog(db)


def capabilities(manager, remote_id, replacement=None):
    info = {}
    for profile in packaged_workflow_profiles():
        for node in profile.api_workflow.values():
            specs = info.setdefault(node["class_type"], {"input": {"required": {}}})["input"]["required"]
            for name, value in node["inputs"].items():
                if isinstance(value, (str, float, int)):
                    choices = specs.setdefault(name, [[]])[0]
                    if value not in choices:
                        choices.append(value)
    if replacement:
        info["UNETLoader"]["input"]["required"]["unet_name"] = [[replacement]]
    manager._write("workflow_capabilities:" + remote_id, {"checked_at": time.time(), "fingerprint": fingerprint(manager.remote(remote_id)), "object_info": info})


def test_empty_database_uses_resources_without_seeding(manager):
    assert len(catalog(manager.database)) == 6
    repo = SQLiteRepository(manager.database)
    assert repo.list_workflow_profiles() == []
    repo.close()
    assert all(i["state"] == "unchecked" for i in manager.report("server-a")["items"])
    with pytest.raises(ValueError, match="检测"):
        manager.resolve("server-a", "23_Turbo_v1.1")


@pytest.mark.parametrize("initial", ["unchecked", "stale", "connection_failed", "ready"])
def test_submission_refreshes_only_when_needed(manager, monkeypatch, initial):
    from anima_prompt_studio.domain.execution_models import RemoteCredentials
    if initial != "unchecked":
        capabilities(manager, "server-a")
        snapshot = manager._read("workflow_capabilities:server-a")
        if initial == "stale":
            snapshot["checked_at"] = 0
        if initial == "connection_failed":
            snapshot["error"] = "offline"
        manager._write("workflow_capabilities:server-a", snapshot)
    seen = []
    credentials = RemoteCredentials(passphrase="memory-only")
    def inspect(remote_id, supplied):
        assert supplied is credentials
        seen.append(remote_id)
        capabilities(manager, remote_id)
    monkeypatch.setattr(manager, "inspect", inspect)
    assert manager.resolve_for_submission("server-a", "23_Turbo_v1.1", credentials).id == "23_Turbo_v1.1"
    manager.resolve_for_submission("server-a", "23_Turbo_v1.1", credentials)
    assert len(seen) == (0 if initial == "ready" else 1)


def test_auto_inspection_does_not_bypass_missing_assets(manager, monkeypatch):
    monkeypatch.setattr(manager, "inspect", lambda remote, credentials: capabilities(manager, remote, "different.safetensors"))
    with pytest.raises(ValueError):
        manager.resolve_for_submission("server-a", "23_Turbo_v1.1", None)


def test_auto_inspection_failure_is_safe_and_retryable(manager, monkeypatch):
    def fail(*args):
        raise RuntimeError("private connection details")
    monkeypatch.setattr(manager, "inspect", fail)
    with pytest.raises(ValueError, match="任务尚未入队") as caught:
        manager.resolve_for_submission("server-a", "23_Turbo_v1.1", None)
    assert "private" not in str(caught.value)
    monkeypatch.setattr(manager, "inspect", lambda remote, credentials: capabilities(manager, remote))
    assert manager.resolve_for_submission("server-a", "23_Turbo_v1.1", None).id == "23_Turbo_v1.1"


def test_preflight_invalidation_is_server_scoped(manager):
    capabilities(manager, "server-a")
    capabilities(manager, "server-b")
    manager.invalidate("server-a")
    assert all(i["state"] == "stale" for i in manager.report("server-a")["items"])
    assert all(i["state"] == "ready" for i in manager.report("server-b")["items"])


def test_malformed_export_wrapper_is_validation_error(manager):
    with pytest.raises(ValueError, match="profile"):
        manager.import_profile({"schema": "anima-user-workflow/1"})


def test_inspection_jobs_deduplicate_limit_and_cancel():
    from threading import Event
    from anima_prompt_studio_v3.adapters.v2.workflow_catalog import InspectionJobs
    entered = Event()
    calls = []

    class BlockingManager:
        def inspect(self, remote_id, credentials, cancel):
            calls.append(remote_id)
            entered.set()
            assert cancel.wait(3)

    jobs = InspectionJobs(BlockingManager())
    try:
        jobs.start("a", None)
        assert entered.wait(1)
        jobs.start("a", None)
        jobs.start("b", None)
        with pytest.raises(ValueError, match="两个"):
            jobs.start("c", None)
        jobs.cancel("a")
        deadline = time.monotonic() + 2
        while jobs.status("a")["state"] == "running" and time.monotonic() < deadline:
            time.sleep(.01)
        assert jobs.status("a")["state"] == "canceled"
        assert calls.count("a") == 1
    finally:
        jobs.close()


def test_mapping_is_server_scoped_and_affects_rendered_asset(manager):
    capabilities(manager, "server-a", "renamed.safetensors")
    capabilities(manager, "server-b")
    item = next(i for i in manager.report("server-a")["items"] if i["workflow_id"] == "23_Turbo_v1.1")
    assert item["state"] == "invalid_inputs"
    checkpoint = next(a for a in item["assets"] if a["key"].endswith(".unet_name"))
    manager.save_mapping("server-a", item["workflow_id"], item["revision"], {checkpoint["key"]: "renamed.safetensors"})
    a = manager.resolve("server-a", item["workflow_id"])
    b = manager.resolve("server-b", item["workflow_id"])
    binding = a.bindings["checkpoint"]
    assert a.api_workflow[binding.node_id]["inputs"][binding.input_name] == "renamed.safetensors"
    assert b.api_workflow[binding.node_id]["inputs"][binding.input_name] != "renamed.safetensors"
    with pytest.raises(ValueError):
        manager.save_mapping("server-a", item["workflow_id"], item["revision"], {checkpoint["key"]: "absent.safetensors"})


def test_stale_and_changed_server_are_not_ready(manager):
    capabilities(manager, "server-a")
    key = "workflow_capabilities:server-a"
    data = manager._read(key)
    data["checked_at"] -= 901
    manager._write(key, data)
    assert all(i["state"] == "stale" for i in manager.report("server-a")["items"])
    capabilities(manager, "server-a")
    repo = SQLiteRepository(manager.database)
    repo.save_remote_profile(manager.remote("server-a").model_copy(update={"ssh_port": 10022}))
    repo.close()
    assert all(i["state"] == "stale" for i in manager.report("server-a")["items"])


def test_user_conflict_preserved_and_export_import_creates_copy(manager):
    p = packaged_workflow_profiles()[0]
    repo = SQLiteRepository(manager.database)
    repo.save_workflow_profile(p.model_copy(update={"notes": "user edit"}))
    repo.close()
    entries = catalog(manager.database)
    assert any(item.id == "official:" + p.id for item, _ in entries)
    assert next(item for item, _ in entries if item.id == p.id).notes == "user edit"
    exported = manager.export_profile(p.id)
    imported = manager.import_profile(exported)
    assert imported["id"].startswith("user:")
    assert imported["id"] != p.id


def test_migration_backs_up_and_does_not_seed(manager):
    migrate_packaged_workflow_ownership(manager.database)
    migrate_packaged_workflow_ownership(manager.database)
    assert len(list((manager.database.parent / "backups").glob("*.db"))) == 1
    repo = SQLiteRepository(manager.database)
    assert repo.list_workflow_profiles() == []
    repo.close()


def test_mapping_rejects_old_revision(manager):
    capabilities(manager, "server-a")
    with pytest.raises(ValueError, match="模板"):
        manager.save_mapping("server-a", "23_Turbo_v1.1", "old", {})


def test_disabled_workflow_cannot_resolve(manager):
    capabilities(manager, "server-a")
    manager.set_enabled("23_Turbo_v1.1", False)
    with pytest.raises(ValueError, match="停用"):
        manager.resolve("server-a", "23_Turbo_v1.1")
    manager.set_enabled("23_Turbo_v1.1", True)
    assert manager.resolve("server-a", "23_Turbo_v1.1")


def test_old_mapping_requires_explicit_reconfirmation(manager):
    capabilities(manager, "server-a")
    manager._write("workflow_mapping:server-a:23_Turbo_v1.1", {"revision": "old", "mapping": {}})
    with pytest.raises(ValueError, match="重新确认"):
        manager.resolve("server-a", "23_Turbo_v1.1")
    item = next(i for i in manager.report("server-a")["items"] if i["workflow_id"] == "23_Turbo_v1.1")
    manager.save_mapping("server-a", "23_Turbo_v1.1", item["revision"], {})
    assert manager.resolve("server-a", "23_Turbo_v1.1")


def test_archived_version_restores_as_independent_user_copy(manager):
    manager.archive_official_versions()
    manager.archive_official_versions()
    versions = manager.versions("23_Turbo_v1.1")
    assert len(versions) == 1
    restored = manager.restore_version("23_Turbo_v1.1", versions[0]["revision"])
    assert restored["id"].startswith("user:")
    assert len(catalog(manager.database)) == 7


def test_simple_api_import_and_invalid_graph(manager):
    profile = next(p for p, origin in catalog(manager.database) if p.id == "23_Turbo_v1.1")
    imported = manager.import_profile(profile.api_workflow)
    assert imported["id"].startswith("user:")
    malformed = profile.model_dump(mode="json")
    malformed["api_workflow"]["1"]["inputs"]["broken"] = ["missing", 0]
    with pytest.raises(ValueError, match="不存在|无效"):
        manager.import_profile(malformed)


def test_official_baseline_has_no_ui_resolution_dependency(manager):
    for profile, origin in catalog(manager.database):
        assert origin == "official"
        assert all(n["class_type"] != "ResolutionSelector" for n in profile.api_workflow.values())
