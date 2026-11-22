"""Ownership changes must not invalidate imports, credentials or persisted history."""
import ast
import importlib
import inspect

import pytest

from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio.domain.execution_models import GenerationRun, GenerationRunState, RemoteProfile
from anima_prompt_studio.repositories.sqlite_repository import SQLiteRepository as LegacyRepository
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository


@pytest.mark.parametrize("name", [
    "generation", "generation_queue", "workflow_catalog", "packaged_workflows",
    "workflow_import", "workflow_inspection", "comfy_access",
])
def test_legacy_adapter_module_is_the_same_v3_implementation(name):
    legacy = importlib.import_module("anima_prompt_studio_v3.adapters.v2." + name)
    current = importlib.import_module("anima_prompt_studio_v3.runtime." + name)
    assert legacy is current


@pytest.mark.parametrize("name", [
    "remote.comfy_client", "remote.ssh_tunnel", "remote.credential_store",
    "remote.result_organizer", "remote.execution_coordinator",
    "storage.runtime_repository", "runtime.generation", "runtime.generation_queue",
    "runtime.workflow_catalog", "runtime.packaged_workflows", "runtime.comfy_access",
])
def test_runtime_does_not_import_legacy_transport_or_storage(name):
    module = importlib.import_module("anima_prompt_studio_v3." + name)
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        imports = [node.module or ""] if isinstance(node, ast.ImportFrom) else [
            alias.name for alias in node.names
        ] if isinstance(node, ast.Import) else []
        assert not any(value.startswith(("anima_prompt_studio.services", "anima_prompt_studio.repositories"))
                       for value in imports)


def test_existing_database_is_readable_and_new_records_are_backward_compatible(tmp_path):
    path = tmp_path / "existing.db"
    legacy = LegacyRepository(path)
    job = PromptJob(positive_prompt="unchanged prompt")
    profile = RemoteProfile(id="server", display_name="server", ssh_host="example.invalid", ssh_user="tester")
    run = GenerationRun(prompt_job_id=job.id, remote_profile_id=profile.id, workflow_profile_id="workflow",
                        remote_prompt_id="already-submitted", state=GenerationRunState.RUNNING,
                        actual_workflow={"7": {"class_type": "KSampler", "inputs": {"steps": 47}}})
    legacy.save_job(job)
    legacy.save_remote_profile(profile)
    legacy.save_generation_run(run)
    legacy.set_setting("user-custom-setting", {"keep": True})
    schema = legacy.connection.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall()
    schema = [tuple(row) for row in schema]
    version = legacy.connection.execute("PRAGMA user_version").fetchone()[0]
    legacy.close()

    current = SQLiteRepository(path)
    assert current.load_job(job.id).positive_prompt == "unchanged prompt"
    restored = current.list_active_generation_runs()[0]
    assert restored.remote_prompt_id == "already-submitted"
    assert restored.actual_workflow == run.actual_workflow
    assert current.get_remote_profile(profile.id) == profile
    assert current.get_setting("user-custom-setting") == {"keep": True}
    assert current.connection.execute("PRAGMA user_version").fetchone()[0] == version == 4
    assert [tuple(row) for row in current.connection.execute(
        "SELECT type,name,sql FROM sqlite_master ORDER BY type,name"
    )] == schema
    restored.state = GenerationRunState.COMPLETED
    current.save_generation_run(restored)
    current.close()
    legacy = LegacyRepository(path)
    assert legacy.get_generation_run(run.id).state == GenerationRunState.COMPLETED
    legacy.close()
    assert not list(tmp_path.glob("*.bak"))


def test_credential_targets_are_unchanged_without_accessing_real_credentials():
    from anima_prompt_studio.services.remote.credential_store import CredentialStore as LegacyStore
    from anima_prompt_studio_v3.remote.credential_store import CredentialStore
    class MemoryBackend:
        values = {}
        def read(self, target):
            return self.values.get(target, "")
        def write(self, target, username, password):
            self.values[target] = password
        def delete(self, target):
            self.values.pop(target, None)
    backend = MemoryBackend()
    LegacyStore(backend).save_password("test-server", "test-user", "test-password")
    assert CredentialStore(backend).read_password("test-server") == "test-password"
    assert CredentialStore.TARGET_PREFIX == LegacyStore.TARGET_PREFIX
    assert CredentialStore.AI_TARGET_PREFIX == LegacyStore.AI_TARGET_PREFIX


def test_default_coordinator_uses_v3_compiler_and_transport():
    from anima_prompt_studio_v3.remote.execution_coordinator import RemoteExecutionCoordinator
    from anima_prompt_studio_v3.remote.ssh_tunnel import SshTunnel
    from anima_prompt_studio_v3.remote.comfy_client import ComfyUIClient
    from anima_prompt_studio_v3.core.workflow_compiler import V3WorkflowCompiler
    coordinator = RemoteExecutionCoordinator()
    assert isinstance(coordinator.renderer, V3WorkflowCompiler)
    assert coordinator.tunnel_factory is SshTunnel
    assert coordinator.client_factory is ComfyUIClient
