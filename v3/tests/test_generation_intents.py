from concurrent.futures import ThreadPoolExecutor

import pytest

from anima_prompt_studio_v3.api.workspace_store import WorkspaceStore
from anima_prompt_studio_v3.storage.generation_submissions import IdempotencyConflict
from anima_prompt_studio_v3.storage.generation_intents import IntentStore, LeaseLost
from test_generation_submissions import harness, payload, submit


def test_concurrent_create_and_changed_body(tmp_path):
    store = IntentStore(WorkspaceStore(tmp_path / 'workspace.db'), clock=lambda: 100)
    with ThreadPoolExecutor(max_workers=20) as pool:
        entries = list(pool.map(lambda _: store.create('key', {'prompt': 'cat'}), range(20)))
    assert len({entry['id'] for entry in entries}) == 1
    with pytest.raises(IdempotencyConflict):
        store.create('key', {'prompt': 'dog'})


def test_lease_fencing_cancel_and_progress_survive_reopen(tmp_path):
    now = [100.]
    workspace = WorkspaceStore(tmp_path / 'workspace.db')
    store = IntentStore(workspace, clock=lambda: now[0])
    entry = store.create('key', {'prompt': 'cat'})
    lease = store.acquire(entry['id'], 'first', seconds=2)
    assert store.acquire(entry['id'], 'second') is None
    store.block(entry['id'], lease, {'order': ['a', 'b'], 'cursor': 1}, 'unchecked', True)
    assert IntentStore(workspace).get(entry['id'])['candidate_progress']['cursor'] == 1
    lease = store.acquire(entry['id'], 'first', seconds=2)
    now[0] += 3
    newer = store.acquire(entry['id'], 'second')
    with pytest.raises(LeaseLost):
        store.block(entry['id'], lease, {}, 'offline', True)
    store.cancel(entry['id'])
    with pytest.raises(LeaseLost):
        store.block(entry['id'], newer, {}, 'offline', True)
    assert store.get(entry['id'])['state'] == 'canceled'


def intent_body():
    return {'source': payload().model_dump(mode='json', exclude={'remote_profile_id', 'workflow_profile_id'}),
            'creationConfiguration': {'workflow': {'id': 'anima_base_api_v1', 'revision': 'revision'}},
            'executionPolicy': {'mode': 'auto', 'preferredEnvironmentIds': []}}


def fake_candidates(*_):
    return [{'id': 'remote-1', 'epoch': 0, 'signature': 'sig', 'display_name': 'test'}]


async def fake_probe(candidate, deadline, expected_epoch):
    from anima_prompt_studio_v3.runtime.environment_probe import ProbeResult
    return ProbeResult(candidate['id'], expected_epoch, 1, 'online', 'ready', [])


def test_twenty_concurrent_http_requests_accept_one_submission_and_replay(harness):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient
    from anima_prompt_studio_v3.api.generation_intents import install_generation_intents
    from anima_prompt_studio_v3.runtime.generation import CandidateToPromptJobAdapter
    store, start, _, executed, _, _ = harness
    queue, submissions = start()
    app = FastAPI()
    @app.exception_handler(IdempotencyConflict)
    def conflict(request, exc):
        return JSONResponse({'error': str(exc)}, status_code=409)
    service = install_generation_intents(app, store, submissions, CandidateToPromptJobAdapter(), None, lambda: None)
    service.probe.close()
    service.probe, service.candidates_override = fake_probe, fake_candidates
    try:
        with TestClient(app) as client:
            def post(_):
                return client.post('/api/v3/generation-intents', json=intent_body(), headers={'Idempotency-Key': 'stable'})
            with ThreadPoolExecutor(max_workers=20) as pool:
                responses = list(pool.map(post, range(20)))
            assert {response.status_code for response in responses} == {202}
            ids = {response.json()['id'] for response in responses}
            assert len(ids) == 1
            intent_id = ids.pop()
            service.jobs[intent_id].result(timeout=3)
            record = client.get('/api/v3/generation-intents/' + intent_id).json()
            assert record['state'] == 'accepted', record
            assert len(submissions.store.list()) == 1 and len(queue.reserved_ids()) == 1 and not executed
            # Lost acceptance response is recovered without a fresh target selection.
            service.probe = lambda *_: pytest.fail('accepted retry must not probe')
            replay = client.post('/api/v3/generation-intents', json=intent_body(), headers={'Idempotency-Key': 'stable'}).json()
            assert replay['run_id'] == record['run_id']
            assert client.post('/api/v3/generation-intents/' + intent_id + '/retry-resolution').json()['run_id'] == record['run_id']
            assert client.post('/api/v3/generation-intents/' + intent_id + '/cancel').json()['state'] == 'accepted'
            changed = intent_body()
            changed['source']['positive_prompt'] = 'new draft'
            assert client.post('/api/v3/generation-intents', json=changed, headers={'Idempotency-Key': 'stable'}).status_code == 409
    finally:
        service.close()


def test_acceptance_failure_rolls_back_intent_submission_and_workspace(harness):
    store, start, _, _, _, _ = harness
    queue, submissions = start()
    intents = IntentStore(store)
    record = intents.create('logical', {})
    epoch = intents.acquire(record['id'], 'owner')
    hook = intents.acceptance(record['id'], epoch, {'id': 'remote-1'}, {})
    def fail_after_submission(db, entry=None):
        hook(db, entry)
        if entry:
            raise RuntimeError('crash before transaction commit')
    from anima_prompt_studio_v3.runtime.generation import CandidateToPromptJobAdapter
    request = payload()
    with pytest.raises(RuntimeError, match='crash'):
        submissions.submit(request, 'intent-v1:' + record['id'], 'direct',
            lambda: CandidateToPromptJobAdapter().prepare_direct(positive_prompt='cat', model_profile_id='anima_base_v1'),
            acceptance_hook=fail_after_submission)
    assert submissions.store.list() == [] and queue.reserved_ids() == []
    assert intents.get(record['id'])['state'] == 'resolving'


def test_canceled_probe_cannot_accept_or_publish_run(harness):
    from anima_prompt_studio_v3.api.generation_intents import GenerationIntentService
    from anima_prompt_studio_v3.runtime.generation import CandidateToPromptJobAdapter
    store, start, _, _, _, _ = harness
    queue, submissions = start()
    service = GenerationIntentService(store, submissions, CandidateToPromptJobAdapter(), None,
                                      candidates=fake_candidates, probe=fake_probe)
    record = service.store.create('logical', intent_body())
    async def cancel_during_probe(candidate, deadline, epoch):
        service.store.cancel(record['id'])
        return await fake_probe(candidate, deadline, epoch)
    service.probe = cancel_during_probe
    try:
        assert service.resolve(record['id'])['state'] == 'canceled'
        assert submissions.store.list() == [] and queue.reserved_ids() == []
    finally:
        service.close()


@pytest.mark.parametrize('shared_database', [False, True])
@pytest.mark.parametrize('identity_strength', ['strong', 'weak'])
def test_real_catalog_auto_routes_only_same_workflow_and_freezes_schema(tmp_path, shared_database, identity_strength):
    from types import SimpleNamespace
    from anima_prompt_studio.domain.execution_models import RemoteProfile
    from anima_prompt_studio_v3.api.generation_intents import GenerationIntentService
    from anima_prompt_studio_v3.runtime.generation import CandidateToPromptJobAdapter
    from anima_prompt_studio_v3.runtime.generation_queue import build_generation_queue
    from anima_prompt_studio_v3.runtime.submissions import SubmissionService
    from anima_prompt_studio_v3.runtime.workflow_catalog import WorkflowCatalog, fingerprint
    from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
    from test_workflow_catalog import capabilities
    database = tmp_path / 'runtime.db'
    repo = SQLiteRepository(database)
    for name in ['server-a', 'server-b']:
        repo.save_remote_profile(RemoteProfile(id=name, display_name=name, ssh_host='example.invalid', ssh_user='tester', known_host_fingerprint='SHA256:test'))
    repo.close()
    manager = WorkflowCatalog(database)
    for remote in ['server-a', 'server-b']:
        capabilities(manager, remote)
    workflow = next(item for item in manager.library()['items'] if item['workflow_id'] == '23_Turbo_v1.1')
    for remote in ['server-a', 'server-b']:
        manager.save_mapping(remote, workflow['workflow_id'], workflow['revision'], {})
    queue = build_generation_queue(database, credential_store=SimpleNamespace(read_password=lambda _: 'fake'))
    workspaces = WorkspaceStore(database if shared_database else tmp_path / 'workspaces.db')
    submissions = SubmissionService(workspaces, queue, lambda run: {'id': run.id}, start=False)
    called = []
    async def probe(candidate, deadline, epoch):
        from anima_prompt_studio_v3.runtime.environment_probe import ProbeResult
        called.append(candidate['id'])
        return ProbeResult(candidate['id'], epoch, 1, 'offline' if candidate['id'] == 'server-a' else 'online', 'ready', ['offline'] if candidate['id'] == 'server-a' else [], identity_strength)
    service = GenerationIntentService(workspaces, submissions, CandidateToPromptJobAdapter(), database, probe=probe)
    body = {'source': {'positive_prompt': 'cat', 'model_profile': 'anima_turbo_v1_1', 'settings': {'seed': '8798399215689017476'}},
            'creationConfiguration': {'workflow': {'id': workflow['workflow_id'], 'revision': workflow['revision']}},
            'executionPolicy': {'mode': 'auto', 'preferredEnvironmentIds': ['server-a']}}
    try:
        record = service.store.create('real', body)
        result = service.resolve(record['id'])
        if identity_strength == 'weak':
            import time
            from anima_prompt_studio_v3.core.requirements import digest
            assert result['state'] == 'blocked'
            assert result['candidate_progress']['checked']['server-b']['reasons'] == ['resource_identity_unconfirmed']
            mapping = manager._read('workflow_mapping:server-b:' + workflow['workflow_id'])
            manager._write('environment_asset_confirmation:server-b:' + workflow['workflow_id'],
                {'epoch': 0, 'fingerprint': fingerprint(manager.remote('server-b')), 'workflow_revision': workflow['revision'],
                 'mapping_hash': digest(mapping), 'confirmed_at': time.time()})
            result = service.resolve(record['id'])
        assert result['state'] == 'accepted', result
        assert result['resolved_target']['id'] == 'server-b'
        assert called == (['server-a', 'server-b', 'server-b'] if identity_strength == 'weak' else ['server-a', 'server-b'])
        entry = submissions.store.list()[0]
        assert entry['snapshot']['job']['generation_params']['seed'] == 8798399215689017476
        schema = entry['snapshot']['job']['integration_metadata']['workflow_parameters']
        assert schema['templateRevision'] == workflow['revision']
        assert schema['values']['seed'] == '8798399215689017476'
        assert queue.get(result['run_id']).remote_profile_id == 'server-b'
        # Reconstruction never changes an already accepted receipt.
        repo = SQLiteRepository(database)
        repo.rebuild_environment('server-b')
        repo.close()
        assert service.resolve(record['id'])['run_id'] == result['run_id']
        assert len(submissions.store.list()) == 1
        if identity_strength == 'weak' and not shared_database:
            # The current library revision can differ from the exact retained run.
            capabilities(manager, 'server-b')
            from copy import deepcopy
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from anima_prompt_studio_v3.api.generation_intents import install_generation_intents
            from anima_prompt_studio_v3.runtime.lora_catalog import LoraCatalog
            old_graph = LoraCatalog(manager).profile(workflow['workflow_id']).model_dump(mode='json')
            old_graph['runtime_assets']['binding_template_revision'] = 'old-reviewed-template'
            old_body = deepcopy(body)
            old_body['creationConfiguration']['workflow']['revision'] = 'old-reviewed-template'
            old_body['source']['workflow_snapshot_run_id'] = 'historical-source'
            old_get = queue.get
            queue.get = lambda run_id: SimpleNamespace(remote_profile_id='server-a', workflow_profile_id=workflow['workflow_id'],
                request_json={'workflow_snapshot': old_graph, 'prompt_job': {'model_profile_id': 'anima_turbo_v1_1'}}) if run_id == 'historical-source' else old_get(run_id)
            app = FastAPI()
            continued = install_generation_intents(app, workspaces, submissions, CandidateToPromptJobAdapter(), database, lambda: None)
            continued.probe.close()
            continued.probe = probe
            with TestClient(app) as client:
                old_record = continued.store.create('old-template', old_body)
                blocked = continued.resolve(old_record['id'])
                assert blocked['state'] == 'blocked'
                confirmed = client.post('/api/v3/execution-environments/server-b/confirm-assets', json={
                    'workflow_id': workflow['workflow_id'], 'revision': 'old-reviewed-template', 'intent_id': old_record['id']})
                assert confirmed.status_code == 200, confirmed.text
                assert continued.resolve(old_record['id'])['state'] == 'accepted'
    finally:
        service.close()
        submissions.close()
        queue.shutdown()


def test_first_manual_prompt_intent_requires_no_llm_or_semantic_requirements(harness):
    from anima_prompt_studio_v3.api.generation_intents import GenerationIntentService
    from anima_prompt_studio_v3.runtime.generation import CandidateToPromptJobAdapter
    from test_workbench_direct_generation import current_prompt_request
    store, start, _, executed, _, _ = harness
    _, submissions = start()
    workspace, request = current_prompt_request(store, first_manual=True)
    assert workspace['draft']['requirements'] is None
    service = GenerationIntentService(store, submissions, CandidateToPromptJobAdapter(), None, probe=fake_probe, candidates=fake_candidates)
    body = {'source': request.model_dump(mode='json', exclude_unset=True, exclude={'remote_profile_id', 'workflow_profile_id'}),
            'creationConfiguration': {'workflow': {'id': request.workflow_profile_id, 'revision': 'revision'}}, 'executionPolicy': {'mode': 'auto'}}
    try:
        record = service.store.create('first-manual', body)
        result = service.resolve(record['id'])
        assert result['state'] == 'accepted', result
        assert len(submissions.store.list()) == 1 and not executed
    finally:
        service.close()


def test_restart_exposes_expired_resolution_for_same_intent(tmp_path):
    now = [100.]
    workspace = WorkspaceStore(tmp_path / 'workspace.db')
    store = IntentStore(workspace, clock=lambda: now[0])
    record = store.create('logical', {})
    epoch = store.acquire(record['id'], 'dead-process', seconds=1)
    now[0] += 2
    restarted = IntentStore(workspace, clock=lambda: now[0])
    assert restarted.recover_expired(record['id'])['reason'] == 'resolution_interrupted'
    assert restarted.acquire(record['id'], 'new-process') == epoch + 1
    with pytest.raises(LeaseLost):
        store.block(record['id'], epoch, {}, 'late', True)


def test_old_image_routes_from_offline_a_to_compatible_b_without_changing_frozen_workflow(harness, monkeypatch):
    from types import SimpleNamespace
    from anima_prompt_studio_v3.api.generation_intents import GenerationIntentService
    from anima_prompt_studio_v3.core.requirements import WorkbenchError
    from anima_prompt_studio_v3.runtime.generation import CandidateToPromptJobAdapter
    from anima_prompt_studio_v3.runtime.generation_queue import GenerationTarget
    from anima_prompt_studio_v3.runtime.environment_probe import ProbeResult
    from test_generation_submissions import workspace_payload
    from test_v2_generation_adapter import workflow_profile
    store, start, _, _, _, base_plan = harness
    queue, submissions = start()
    workspace, request = workspace_payload(store)
    frozen = workflow_profile().model_dump(mode='json')
    def attach(draft):
        draft['generation_source'] = {'run_id': 'source-a', 'remote_profile_id': 'remote-1',
                                     'workflow_profile_id': request.workflow_profile_id, 'model_profile': request.model_profile}
        return draft
    workspace = store.transform(workspace['id'], expected_revision=workspace['revision'], operation=attach)
    request = request.model_copy(update={'workspace_revision': workspace['revision'], 'workflow_snapshot_run_id': 'source-a'})
    original_get = queue.get
    monkeypatch.setattr(queue, 'get', lambda run_id: SimpleNamespace(request_json={'workflow_snapshot': frozen}) if run_id == 'source-a' else original_get(run_id))
    seen = []
    def plan(prepared, remote, workflow, resources, snapshot):
        seen.append((remote, snapshot))
        prepared, target, resolution = base_plan(prepared, remote, workflow, resources, snapshot)
        return prepared, GenerationTarget(target.remote_profile.model_copy(update={'id': remote}), target.workflow_profile, target.credentials, target.output_root), resolution
    queue._plan_resolver = plan
    async def probe(candidate, deadline, epoch):
        return ProbeResult(candidate['id'], epoch, 1, 'offline' if candidate['id'] == 'remote-1' else 'online', 'ready', ['offline'] if candidate['id'] == 'remote-1' else [])
    candidates = lambda *_: [{'id': remote, 'epoch': 0, 'signature': remote} for remote in ['remote-1', 'remote-b']]
    service = GenerationIntentService(store, submissions, CandidateToPromptJobAdapter(), None, probe=probe, candidates=candidates)
    body = {'source': request.model_dump(mode='json', exclude={'remote_profile_id', 'workflow_profile_id', 'lora_selection'}),
            'creationConfiguration': {'workflow': {'id': request.workflow_profile_id, 'revision': 'old-frozen'}},
            'executionPolicy': {'mode': 'auto', 'preferredEnvironmentIds': ['remote-1']}}
    try:
        record = service.store.create('continue-image', body)
        result = service.resolve(record['id'])
        assert result['state'] == 'accepted', result
        assert result['resolved_target']['id'] == 'remote-b'
        assert seen == [('remote-b', frozen)]
        entry = submissions.store.list()[0]
        assert entry['snapshot']['workflow'] == frozen
        assert queue.get(result['run_id']).remote_profile_id == 'remote-b'
        # Existing direct-submission source contracts remain unchanged.
        with pytest.raises(WorkbenchError, match='解除原工作流快照'):
            submit(submissions, request.model_copy(update={'remote_profile_id': 'remote-b',
                'workspace_revision': result['response']['workspace_revision'], 'compiled_token': result['response']['compiled_token']}), key='legacy-other')
    finally:
        service.close()
