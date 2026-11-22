import asyncio
import json

import pytest

from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio_v3.remote.comfy_client import ComfyAPIError
from anima_prompt_studio_v3.remote.execution_coordinator import RemoteExecutionError
from anima_prompt_studio_v3.runtime.cloud_model_catalog import CloudModelCatalog, assert_runtime_confirmed
from anima_prompt_studio_v3.runtime.environment_probe import EnvironmentProbe
from anima_prompt_studio_v3.runtime.generation_queue import build_generation_queue
from anima_prompt_studio_v3.runtime.workflow_catalog import WorkflowCatalog, catalog, fingerprint
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
from test_cloud_model_catalog import document
from test_http_runtime_identity import Response, profile


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    database = tmp_path / 'runtime.db'
    remote = profile(None)
    repo = SQLiteRepository(database)
    repo.save_remote_profile(remote)
    repo.close()
    workflow = next(p for p, _ in catalog(database) if 'anima_turbo_v1_1' in p.compatible_model_profiles)
    doc, info, calls = document(), {}, []
    aliases = {'unet_name': 'sub/model.safetensors', 'clip_name': 'qwen.safetensors',
               'vae_name': 'image.safetensors', 'sampler_name': 'euler', 'scheduler': 'normal'}
    for node in workflow.api_workflow.values():
        required = info.setdefault(node['class_type'], {'input': {'required': {}}})['input']['required']
        for name, value in node['inputs'].items():
            if name in aliases:
                required[name] = [[aliases[name], value] if name in {'sampler_name', 'scheduler'} else [aliases[name]]]
    state = {'identity': 'A', 'failure': False, 'on_info': None, 'on_object_info': None}
    class Session:
        def get(self, url, **kwargs):
            path = url.removeprefix(remote.http_base_url)
            calls.append(path)
            if state['failure']:
                raise TimeoutError('private upstream error')
            if path == '/_moss/info':
                identity = state['identity']
                if state['on_info']:
                    callback, state['on_info'] = state['on_info'], None
                    callback()
                return Response({'runtime_id': identity})
            if path == '/_moss/models':
                return Response({**doc, 'runtime_id': state['identity']})
            if path == '/object_info':
                if state['on_object_info']:
                    callback, state['on_object_info'] = state['on_object_info'], None
                    callback()
                return Response(info)
            return Response({})
        def post(self, url, **kwargs):
            calls.append(url.removeprefix(remote.http_base_url))
            return Response({'prompt_id': 'should-not-submit'})
    monkeypatch.setattr('requests.Session', Session)
    from anima_prompt_studio_v3.remote.credential_store import CredentialStore, MemoryCredentialBackend
    secrets = CredentialStore(MemoryCredentialBackend())
    monkeypatch.setattr('anima_prompt_studio_v3.remote.connections.HttpComfyConnection.open', lambda self, *a, **k: self)
    return database, remote, workflow, state, calls, secrets


def check_probe(database, remote):
    repo = SQLiteRepository(database)
    epoch = repo.get_setting('environment_epoch:' + remote.id, 0)
    repo.close()
    probe = EnvironmentProbe(database)
    try:
        return asyncio.run(probe({'profile': remote, 'signature': fingerprint(remote) + ':' + str(epoch), 'recheck': True}, probe.clock() + 5, epoch))
    finally:
        probe.close()


@pytest.mark.parametrize('first', ['catalog', 'probe'])
@pytest.mark.parametrize('intervening_failure', [False, True])
@pytest.mark.parametrize('change_epoch', [False, True])
def test_identity_is_shared_across_catalog_probe_failures_and_epochs(gateway, first, intervening_failure, change_epoch):
    database, remote, _, state, _, _ = gateway
    service = CloudModelCatalog(database)
    def check(source):
        result = service.refresh(remote.id) if source == 'catalog' else check_probe(database, remote)
        return result['status'] == 'ready' if isinstance(result, dict) else result.capabilities_state == 'ready'
    assert check(first)
    if intervening_failure:
        state['failure'] = True
        assert not check(first)
        state['failure'] = False
    if change_epoch:
        repo = SQLiteRepository(database)
        repo.set_setting('environment_epoch:' + remote.id, repo.get_setting('environment_epoch:' + remote.id, 0) + 1)
        repo.close()
    state['identity'] = 'B'
    second = 'probe' if first == 'catalog' else 'catalog'
    assert not check(second)
    assert not check(second)
    assert service.report(remote.id)['status'] != 'ready'
    repo = SQLiteRepository(database)
    try:
        with pytest.raises(ValueError):
            assert_runtime_confirmed(repo, remote)
        assert repo.get_remote_profile(remote.id).http_runtime_id is None
        replacement = remote.model_copy(update={'http_session_id': 'replacement'})
        repo.save_remote_profile(replacement)
    finally:
        repo.close()
    assert CloudModelCatalog(database).refresh(remote.id)['runtime_id'] == 'B'
    assert check_probe(database, replacement).capabilities_state == 'ready'


def test_fresh_workflow_inspection_enforces_catalog_identity(gateway):
    database, remote, _, state, calls, _ = gateway
    assert CloudModelCatalog(database).refresh(remote.id)['status'] == 'ready'
    calls.clear()
    state['identity'] = 'B'
    with pytest.raises(ComfyAPIError):
        WorkflowCatalog(database).inspect(remote.id)
    assert '/system_stats' not in calls
    assert CloudModelCatalog(database).report(remote.id)['status'] != 'ready'


def test_workflow_inspection_identity_constrains_catalog_and_fresh_submission(gateway):
    database, remote, workflow, state, calls, secrets = gateway
    WorkflowCatalog(database).inspect(remote.id)
    queue = build_generation_queue(database, credential_store=secrets)
    try:
        coordinator = queue._coordinator_factory(database.parent, lambda run: None)
        state['identity'] = 'B'
        calls.clear()
        with pytest.raises(RemoteExecutionError):
            coordinator.execute(PromptJob(model_profile_id='anima_turbo_v1_1', positive_prompt='test'), remote, workflow, 'anima_turbo_v1_1')
        assert '/prompt' not in calls and '/system_stats' not in calls
        assert CloudModelCatalog(database).refresh(remote.id)['status'] != 'ready'
    finally:
        queue.shutdown()


def test_genuinely_idless_legacy_gateway_remains_weak_compatible(gateway):
    database, remote, _, state, _, _ = gateway
    state['identity'] = None
    assert CloudModelCatalog(database).refresh(remote.id)['status'] == 'ready'
    result = check_probe(database, remote)
    assert result.capabilities_state == 'ready' and result.identity_strength == 'weak'
    WorkflowCatalog(database).inspect(remote.id)


def test_late_identity_observation_cannot_seed_replaced_session(gateway):
    database, remote, _, state, _, _ = gateway
    replacement = remote.model_copy(update={'http_session_id': 'replacement'})
    def replace():
        repo = SQLiteRepository(database)
        repo.save_remote_profile(replacement)
        repo.close()
        state['identity'] = 'B'
    state['on_info'] = replace
    result = CloudModelCatalog(database).refresh(remote.id)
    assert result['status'] != 'ready' and result['session_id'] == 'replacement'
    result = CloudModelCatalog(database).refresh(remote.id)
    assert result['status'] == 'ready' and result['runtime_id'] == 'B'
    assert check_probe(database, replacement).capabilities_state == 'ready'


def test_late_inspection_cannot_restore_capabilities_after_identity_conflict(gateway):
    database, remote, _, state, _, _ = gateway
    assert CloudModelCatalog(database).refresh(remote.id)['status'] == 'ready'
    def detect_restart():
        state['identity'] = 'B'
        assert CloudModelCatalog(database).refresh(remote.id)['status'] != 'ready'
    state['on_object_info'] = detect_restart
    with pytest.raises(ValueError):
        WorkflowCatalog(database).inspect(remote.id)
    repo = SQLiteRepository(database)
    try:
        assert repo.get_setting('workflow_capabilities:' + remote.id) == {}
        with pytest.raises(ValueError):
            assert_runtime_confirmed(repo, remote)
    finally:
        repo.close()


def test_shared_identity_reconciles_prior_catalog_evidence_without_changing_profile(gateway):
    database, remote, _, state, _, _ = gateway
    repo = SQLiteRepository(database)
    repo.set_setting('cloud_model_catalog:' + remote.id, {
        'signature': [fingerprint(remote), remote.http_session_id, 0],
        'runtime_id': 'A', 'last_runtime_id': 'A'})
    before = repo.get_remote_profile(remote.id).model_dump()
    repo.close()
    state['identity'] = 'B'
    assert check_probe(database, remote).capabilities_state != 'ready'
    repo = SQLiteRepository(database)
    try:
        assert repo.get_remote_profile(remote.id).model_dump() == before
    finally:
        repo.close()


def test_generation_targets_expose_public_https_address(gateway):
    database, remote, _, _, _, secrets = gateway
    queue = build_generation_queue(database, credential_store=secrets)
    try:
        target = next(item for item in queue.targets() if item['remote_profile_id'] == remote.id)
        assert target['connection_type'] == 'http'
        assert target['remote_http_base_url'] == remote.http_base_url
    finally:
        queue.shutdown()


def test_same_identity_can_recover_in_another_path_after_network_failure(gateway):
    database, remote, _, state, _, _ = gateway
    assert CloudModelCatalog(database).refresh(remote.id)['status'] == 'ready'
    state['failure'] = True
    assert CloudModelCatalog(database).refresh(remote.id)['status'] != 'ready'
    state['failure'] = False
    assert check_probe(database, remote).capabilities_state == 'ready'
    repo = SQLiteRepository(database)
    try:
        assert_runtime_confirmed(repo, remote)
    finally:
        repo.close()
