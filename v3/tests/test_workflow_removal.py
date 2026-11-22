"""Removing obsolete choices preserves exact historical execution snapshots."""
import json
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from anima_prompt_studio.domain.execution_models import GenerationRun, GenerationRunState, RemoteAuthType
from anima_prompt_studio_v3.api import create_api_runtime
from anima_prompt_studio_v3.remote.credential_store import CredentialStore, MemoryCredentialBackend
from anima_prompt_studio_v3.runtime.generation import CandidateToPromptJobAdapter
from anima_prompt_studio_v3.runtime.generation_queue import build_generation_queue
from anima_prompt_studio_v3.runtime.lora_catalog import LoraCatalog
from anima_prompt_studio_v3.runtime.packaged_workflows import (
    ensure_packaged_workflow_profiles, migrate_packaged_workflow_ownership, workflow_revision,
)
from anima_prompt_studio_v3.runtime.workflow_catalog import WorkflowCatalog, catalog
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
from test_api import ORIGIN, reference_db
from test_workflow_catalog import capabilities, manager


def selected(manager, *ids):
    return {p.id: workflow_revision(p) for p, _ in catalog(manager.database) if p.id in ids}


def test_removal_archives_exact_graph_and_stays_removed_after_restart_and_seeding(manager):
    official = LoraCatalog(manager).profile("26_Turbo_v1.1")
    user_id = manager.import_profile(manager.export_profile("23_Turbo_v1.1"))["id"]
    revisions = selected(manager, official.id, user_id)
    before = {p.id: p.model_dump(mode="json") for p, _ in catalog(manager.database) if p.id in revisions}
    result = manager.remove_many(list(revisions), revisions, reason="旧工作流清理")
    assert set(result["removed"]) == set(revisions)
    repo = SQLiteRepository(manager.database)
    try:
        for workflow_id, revision in revisions.items():
            archived = repo.get_setting(f"workflow_version:{workflow_id}:{revision}")
            assert archived == before[workflow_id]
            removal = repo.get_setting("workflow_removed:" + workflow_id)
            assert removal["workflow_id"] == workflow_id and removal["revision"] == revision
            assert removal["reason"] == "旧工作流清理" and removal["removed_at"]
            assert removal["source"]["id"] and removal["source"]["revision"]
        assert repo.get_workflow_profile(user_id).id == user_id  # A recoverable record, not a public choice.
    finally:
        repo.close()
    ensure_packaged_workflow_profiles(manager.database)
    migrate_packaged_workflow_ownership(manager.database)
    restarted = WorkflowCatalog(manager.database)
    assert not set(revisions) & {p.id for p, _ in catalog(manager.database)}
    assert not set(revisions) & {p["workflow_id"] for p in restarted.library()["items"]}
    assert not set(revisions) & {p["workflow_id"] for p in restarted.report("server-a")["items"]}
    duplicate = restarted.remove_many(list(revisions), revisions, reason="重复执行不改变原记录")
    assert duplicate["removed"] == [] and set(duplicate["already_removed"]) == set(revisions)


@pytest.mark.parametrize("invalid", ["revision", "unknown"])
def test_remove_many_prevalidates_entire_batch_before_any_change(manager, invalid):
    ids = ["26_Turbo_v1.1", "27_AnimaYume"]
    revisions = selected(manager, *ids)
    if invalid == "revision":
        revisions[ids[-1]] = "0" * 64
        expected = ValueError
    else:
        ids.append("not-a-workflow")
        revisions[ids[-1]] = "0" * 64
        expected = KeyError
    with pytest.raises(expected):
        manager.remove_many(ids, revisions)
    assert set(ids[:2]) <= {p.id for p, _ in catalog(manager.database)}
    assert manager._read("workflow_removed:" + ids[0]) is None
    assert manager.versions(ids[0]) == []


def test_remove_many_rolls_back_archives_and_marks_when_a_later_write_fails(manager):
    ids = ["26_Turbo_v1.1", "27_AnimaYume"]
    revisions = selected(manager, *ids)
    repo = SQLiteRepository(manager.database)
    repo.connection.execute("CREATE TRIGGER reject_second_removal BEFORE INSERT ON settings "
        "WHEN NEW.key='workflow_removed:27_AnimaYume' BEGIN SELECT RAISE(ABORT,'blocked test write'); END")
    repo.connection.commit()
    repo.close()
    with pytest.raises(sqlite3.IntegrityError, match="blocked test write"):
        manager.remove_many(ids, revisions)
    assert set(ids) <= {p.id for p, _ in catalog(manager.database)}
    assert all(manager._read("workflow_removed:" + workflow_id) is None for workflow_id in ids)
    assert all(manager.versions(workflow_id) == [] for workflow_id in ids)


def test_removed_source_can_be_restored_only_as_a_new_independent_copy(manager):
    workflow_id = "26_Turbo_v1.1"
    revision = selected(manager, workflow_id)[workflow_id]
    manager.remove_many([workflow_id], {workflow_id: revision})
    restored = manager.restore_version(workflow_id, revision)
    assert restored["id"].startswith("user:") and restored["id"] != workflow_id
    assert restored["id"] in {p.id for p, _ in catalog(manager.database)}
    with pytest.raises(KeyError):
        manager.export_profile(workflow_id)


def test_removal_does_not_disable_frozen_graph_or_rewrite_completed_history(manager):
    capabilities(manager, "server-a")
    resolver = LoraCatalog(manager)
    profile = resolver.profile("23_Turbo_v1.1")
    frozen = profile.model_dump(mode="json")
    prepared = CandidateToPromptJobAdapter().prepare_direct(
        positive_prompt="adult woman, blue coat", model_profile_id="anima_turbo_v1_1")
    run = GenerationRun(prompt_job_id=prepared.job.id, remote_profile_id="server-a",
        workflow_profile_id=profile.id, state=GenerationRunState.COMPLETED,
        request_json={"workflow_snapshot": frozen, "prompt_job": prepared.job.model_dump(mode="json")},
        actual_workflow=profile.api_workflow)
    repo = SQLiteRepository(manager.database)
    repo.save_generation_run(run)
    repo.close()
    manager.remove_many([profile.id], {profile.id: workflow_revision(profile)})
    with pytest.raises(KeyError):
        resolver.resolve("server-a", profile.id, "anima_turbo_v1_1", [], refresh=False)
    graph, resolution = resolver.resolve("server-a", profile.id, "anima_turbo_v1_1", [], frozen=frozen, refresh=False)
    assert graph.api_workflow == profile.api_workflow and resolution["availability"] == "ready"
    assert manager._read("workflow_disabled:" + profile.id, False) is False
    repo = SQLiteRepository(manager.database)
    try:
        assert repo.get_generation_run(run.id) == run
    finally:
        repo.close()


def test_removed_templates_are_absent_from_targets_settings_and_optional_inspection(manager, reference_db, monkeypatch):
    removed = "26_Turbo_v1.1"
    user_id = manager.import_profile(manager.export_profile("23_Turbo_v1.1"))["id"]
    revisions = selected(manager, removed, user_id)
    repo = SQLiteRepository(manager.database)
    for remote in repo.list_remote_profiles():
        repo.save_remote_profile(remote.model_copy(update={"auth_type": RemoteAuthType.AGENT}))
    repo.close()
    store = CredentialStore(MemoryCredentialBackend())
    monkeypatch.setattr("anima_prompt_studio_v3.remote.credential_store.CredentialStore", lambda: store)
    queue = build_generation_queue(manager.database, credential_store=store)
    assert removed in {p["workflow_profile_id"] for p in queue.targets()}
    try:
        manager.remove_many(list(revisions), revisions)
        runtime = create_api_runtime(reference_db, v2_database=manager.database, generation_queue=queue)
        with TestClient(runtime.app, base_url=ORIGIN) as client:
            exchanged = client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token}, headers={"Origin": ORIGIN})
            headers = {"Origin": ORIGIN, "X-Anima-Session": exchanged.json()["session_token"]}
            targets = client.get("/api/v3/generation-targets", headers=headers).json()["items"]
            assert not set(revisions) & {p["workflow_profile_id"] for p in targets}
            settings = client.get("/api/v3/settings/remote-profiles", headers=headers).json()["workflows"]
            assert not set(revisions) & {p["id"] for p in settings}
            assert "23_Turbo_v1.1" in {p["id"] for p in settings}
            monkeypatch.setattr("anima_prompt_studio_v3.remote.connections.connection_factory", lambda *a, **kw:
                SimpleNamespace(base_url="http://unused", open=lambda *a: None, close=lambda: None))
            class Client:
                def __init__(self, *a, **kw): pass
                def validate_environment(self):
                    return SimpleNamespace(devices=["Test GPU"], queue_running=0, queue_pending=0,
                        system_stats={"system": {"comfyui_version": "0.42.0"}})
                def validate_workflow_nodes(self, graph): return []
                def validate_workflow_inputs(self, graph): return []
            monkeypatch.setattr("anima_prompt_studio_v3.remote.comfy_client.ComfyUIClient", Client)
            response = client.post("/api/v3/settings/remote-profiles/server-a/test-connection?inspect_templates=true", headers=headers, json={})
            assert response.status_code == 200, response.text
            inspection = response.json()["workflow_inspection"]["items"]
            assert not set(revisions) & {p["workflow_id"] for p in inspection}
    finally:
        queue.shutdown()
