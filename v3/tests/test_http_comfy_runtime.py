import asyncio
import json
from pathlib import Path

import pytest
import requests
from requests.adapters import BaseAdapter

from anima_prompt_studio.domain.execution_models import GenerationRun, GenerationRunState, RemoteArtifact, RemoteProfile
from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio_v3.remote.comfy_client import ComfyAPIError, ComfyUIClient
from anima_prompt_studio_v3.remote.credential_store import CredentialStore, MemoryCredentialBackend
from anima_prompt_studio_v3.remote.execution_coordinator import RemoteExecutionCoordinator, RemoteExecutionError
from anima_prompt_studio_v3.remote.result_organizer import ResultOrganizer
from anima_prompt_studio_v3.runtime.environment_probe import EnvironmentProbe
from anima_prompt_studio_v3.runtime.workflow_catalog import WorkflowCatalog, fingerprint
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
from test_remote_runtime_regression import api_workflow, workflow_profile
from test_api import reference_db


@pytest.fixture
def protocol(monkeypatch):
    calls = []
    state = {'status': 200, 'key': 'runtime-secret', 'redirects': 0}
    class Adapter(BaseAdapter):
        def send(self, request, **options):
            from urllib.parse import urlsplit
            path = urlsplit(request.url).path.removeprefix('/prefix')
            calls.append((path, request.headers.get('Authorization'), options.get('verify')))
            assert request.url.startswith('https://example.test/prefix/')
            response = requests.Response()
            response._content_consumed = True  # This adapter supplies fully buffered bodies.
            response.request, response.url = request, request.url
            response.status_code = state['status']
            if response.status_code != 200:
                response.headers['Location'] = 'https://example.test/prefix/stolen'
                response._content = state.get('error_body', 'runtime-secret: echoed by upstream').encode()
                return response
            assert request.headers.get('Authorization') == 'Bearer ' + state['key']
            if path == '/_moss/info':
                value = {}  # Legacy gateway: deliberately no strong runtime identity.
            elif path == '/_moss/models':
                response.status_code = 404  # Ordinary ComfyUI has no optional model catalog.
                value = {'error': 'unsupported'}
            elif path == '/system_stats':
                value = {'devices': [{'name': 'HTTPS simulator'}]}
            elif path == '/queue':
                value = {'queue_running': [], 'queue_pending': []}
            elif path == '/object_info':
                value = state.get('object_info', {node['class_type']: {} for node in api_workflow().values()})
            elif path == '/prompt':
                state['submitted_graph'] = json.loads(request.body)['prompt']
                value = {'prompt_id': 'remote-prompt'}
            elif path == '/history/remote-prompt':
                value = {'remote-prompt': {'status': {'completed': True}, 'outputs': {
                    '8': {'images': [{'filename': 'remote.png', 'type': 'output'}]}}}}
            elif path == '/upload/image':
                state['uploaded_body'] = request.body
                value = {'name': state.get('upload_name', 'source.png'), 'subfolder': 'anima_gallery'}
            elif path == '/view':
                response.headers['Content-Type'] = 'image/png'
                response._content = state.get('view_data', b'simulated-image')
                return response
            else:
                pytest.fail('Unexpected network path: ' + path)
            response._content = json.dumps(value).encode()
            return response
        def close(self):
            pass
    original = requests.Session
    def session():
        result = original()
        result.mount('https://', Adapter())
        return result
    monkeypatch.setattr(requests, 'Session', session)
    store = CredentialStore(MemoryCredentialBackend())
    store.backend.write('AnimaPromptStudio/COMFY/session-one', 'ComfyUI', 'runtime-secret')
    monkeypatch.setattr('anima_prompt_studio_v3.remote.credential_store.CredentialStore', lambda: store)
    return calls, state, store


def test_prompt_400_identifies_rejected_model_input_without_echoing_server_data(protocol):
    calls, state, _ = protocol
    state.update(status=400, error_body=json.dumps({
        'error': {'type': 'prompt_outputs_failed_validation', 'message': 'private diagnostic'},
        'node_errors': {'2': {'class_type': 'UpscaleModelLoader', 'errors': [{
            'type': 'value_not_in_list', 'details': 'runtime-secret and source image',
            'extra_info': {'input_name': 'model_name', 'received_value': 'private path'},
        }]}}
    }))
    graph = {'2': {'class_type': 'UpscaleModelLoader', 'inputs': {'model_name': 'missing.pth'}}}
    client = ComfyUIClient('https://example.test/prefix', api_key='runtime-secret')
    with pytest.raises(ComfyAPIError) as rejected:
        client.submit(graph, 'client', 'requested')
    assert rejected.value.code == 'workflow_rejected'
    reason = str(rejected.value)
    assert all(part in reason for part in ('400', 'UpscaleModelLoader', 'model_name', '可选'))
    assert not any(part in reason for part in ('访问密钥', 'runtime-secret', 'private', 'source image'))
    assert len(calls) == 1


def http_profile():
    return RemoteProfile(id='http', connection_type='http', ssh_host='', ssh_user='',
        http_base_url='https://example.test/prefix', http_session_id='session-one',
        http_auth_required=True, model_aliases={'anima_turbo_v1': 'anima-turbo.safetensors'})


def test_authenticated_generation_and_resume_download_use_all_standard_endpoints(tmp_path, protocol):
    calls, state, store = protocol
    coordinator = RemoteExecutionCoordinator(organizer=ResultOrganizer(tmp_path), poll_interval=0,
        tunnel_factory=lambda _: pytest.fail('HTTPS must not create SSH'))
    job = PromptJob(model_profile_id='anima_turbo_v1', positive_prompt='1girl')
    result = coordinator.execute(job, http_profile(), workflow_profile(), 'anima_turbo_v1')
    assert result.run.state == GenerationRunState.COMPLETED
    assert Path(result.artifacts[0].local_path).read_bytes() == b'simulated-image'
    assert result.run.request_json['http_connection']['session_id'] == 'session-one'
    assert 'runtime-secret' not in result.run.model_dump_json()
    assert all(auth == 'Bearer runtime-secret' and verify for _, auth, verify in calls)
    assert {path for path, *_ in calls} >= {'/system_stats', '/object_info', '/prompt', '/queue', '/history/remote-prompt', '/view'}
    coordinator.resume(result.run, http_profile(), workflow_profile())
    assert sum(path == '/prompt' for path, *_ in calls) == 1
    assert all(b'runtime-secret' not in p.read_bytes() for p in Path(result.run.output_dir).glob('*.json'))


def test_authenticated_upload_and_cancel(protocol, tmp_path):
    calls, _, _ = protocol
    client = ComfyUIClient('https://example.test/prefix', api_key='runtime-secret')
    source = tmp_path / 'source.png'
    source.write_bytes(b'image')
    assert client.upload_image(source) == 'anima_gallery/source.png'
    client.cancel_pending('remote-prompt')
    assert calls == [('/upload/image', 'Bearer runtime-secret', True), ('/queue', 'Bearer runtime-secret', True)]


@pytest.mark.parametrize('operation', ['stats', 'prompt', 'upload', 'view'])
@pytest.mark.parametrize('status', [302, 307, 401, 403, 500])
def test_rejects_redirects_and_never_echoes_upstream_secret(protocol, tmp_path, operation, status):
    calls, state, _ = protocol
    state['status'] = status
    client = ComfyUIClient('https://example.test/prefix', api_key='runtime-secret')
    source = tmp_path / 'source.png'
    source.write_bytes(b'image')
    operations = {'stats': client.validate_environment,
        'prompt': lambda: client.submit({}, 'client', 'prompt'),
        'upload': lambda: client.upload_image(source),
        'view': lambda: client.download_artifact(RemoteArtifact(filename='x.png'))}
    with pytest.raises(ComfyAPIError) as error:
        operations[operation]()
    assert 'runtime-secret' not in str(error.value)
    assert 'runtime-secret' not in str(error.value.details)
    assert len(calls) == 1  # Especially POST /prompt: no retry or redirected submission.


@pytest.mark.parametrize('snapshot', [None, {'session_id': 'old-session'}])
def test_http_resume_refuses_missing_or_replaced_session_before_network(protocol, snapshot):
    calls, _, _ = protocol
    run = GenerationRun(prompt_job_id='job', remote_profile_id='http', workflow_profile_id='workflow',
        remote_prompt_id='remote-prompt', request_json={'prompt_job': PromptJob().model_dump(mode='json')})
    if snapshot:
        run.request_json['http_connection'] = snapshot
    with pytest.raises(RemoteExecutionError, match='临时连接'):
        RemoteExecutionCoordinator(tunnel_factory=lambda _: pytest.fail('Resume must reject before opening a connection')).resume(run, http_profile(), workflow_profile())
    assert calls == []


def test_probe_and_catalog_use_http_auth_but_session_id_is_weak_identity(protocol, tmp_path):
    calls, _, _ = protocol
    database = tmp_path / 'runtime.db'
    repo = SQLiteRepository(database)
    profile = http_profile()
    repo.save_remote_profile(profile)
    probe = EnvironmentProbe(database)
    try:
        result = asyncio.run(probe({'id': profile.id, 'profile': profile, 'signature': fingerprint(profile)}, probe.clock() + 5, 0))
        assert result.connection_state == 'online'
        assert result.identity_strength == 'weak' and result.instance_identity is None
        WorkflowCatalog(database).inspect(profile.id)
        assert repo.get_setting('workflow_capabilities:' + profile.id)['devices'] == ['HTTPS simulator']
        assert repo.get_setting('cloud_model_catalog:' + profile.id)['status'] == 'unsupported'
        assert ('/_moss/models', 'Bearer runtime-secret', True) in calls
        assert repo.get_remote_profile(profile.id) == profile
        with pytest.raises(ValueError, match='文件导入'):
            WorkflowCatalog(database).read_remote_file(profile.id, '/tmp/workflow.json', None)
    finally:
        probe.close()
        repo.close()


def test_uploaded_image_receipt_cannot_insert_credentials_in_workflow(protocol, tmp_path):
    _, state, _ = protocol
    state['upload_name'] = 'runtime-secret.png'
    image = tmp_path / 'source.png'
    image.write_bytes(b'image')
    receipt = ComfyUIClient('https://example.test/prefix', api_key='runtime-secret').upload_image(image)
    assert 'runtime-secret' not in receipt


def test_opened_client_keeps_captured_key_after_profile_replacement(protocol):
    from anima_prompt_studio_v3.remote.connections import connection_factory, client_for_connection
    from anima_prompt_studio.domain.execution_models import RemoteCredentials
    calls, state, store = protocol
    connection = connection_factory(http_profile())
    connection.open(RemoteCredentials())
    client = client_for_connection(connection)
    store.delete_comfy_api_key('session-one')
    store.save_comfy_api_key('session-two', 'new-key')
    client.validate_environment()
    assert all(auth == 'Bearer runtime-secret' for _, auth, _ in calls)


def test_gallery_uses_v3_authenticated_client_and_freezes_session(protocol, tmp_path, monkeypatch):
    from anima_prompt_studio_v3.adapters.v2 import gallery
    calls, state, store = protocol
    state['object_info'] = {name: {} for name in ('LoadImage', 'ImageUpscaleWithModel', 'ImageScale', 'SaveImage')}
    state['object_info']['UpscaleModelLoader'] = {'input': {'required': {'model_name': [['test.pth']]}}}
    class Manager:
        def __init__(self, *args, coordinator_factory, **kwargs):
            self.factory = coordinator_factory
        def configure(self, profile, workflow, credentials):
            self.profile, self.workflow, self.credentials = profile, workflow, credentials
    monkeypatch.setattr(gallery, 'GalleryUpscaleManager', Manager)
    database = tmp_path / 'runtime.db'
    repo = SQLiteRepository(database)
    repo.save_remote_profile(http_profile())
    repo.set_setting('generation_output_root', str(tmp_path / 'outputs'))
    repo.close()
    service = gallery.build_v2_gallery_service(database, credential_store=store)
    manager = service.process_manager
    coordinator = manager.factory(organizer=ResultOrganizer(tmp_path / 'outputs'), poll_interval=0)
    source = tmp_path / 'source.png'
    source.write_bytes(b'image')
    result = coordinator.execute(job=PromptJob(positive_prompt='1girl'), source_path=source,
        source_relative_path='source.png', source_width=512, source_height=512,
        remote_profile=manager.profile, workflow_profile=manager.workflow, credentials=manager.credentials)
    assert result.run.state == GenerationRunState.COMPLETED
    assert result.run.request_json['http_connection']['session_id'] == 'session-one'
    assert {path for path, *_ in calls} >= {'/upload/image', '/prompt', '/view'}
    assert all(auth == 'Bearer runtime-secret' for _, auth, _ in calls)


@pytest.mark.parametrize('queue_before_update', [False, True], ids=['active-snapshot', 'queued-snapshot'])
@pytest.mark.parametrize('import_after_start', [False, True], ids=['existing-http', 'first-import'])
def test_gallery_submissions_capture_current_import_without_changing_accepted_jobs(tmp_path, queue_before_update, import_after_start):
    from queue import Queue
    from threading import Event
    from anima_prompt_studio.domain.execution_models import WorkflowProfile
    from anima_prompt_studio_v3.adapters.v2.gallery import build_v2_gallery_service
    from anima_prompt_studio_v3.remote.temporary_connections import import_temporary_connection

    database = tmp_path / 'runtime.db'
    output = tmp_path / 'outputs'
    output.mkdir()
    store = CredentialStore(MemoryCredentialBackend())
    repo = SQLiteRepository(database)
    if not import_after_start:
        old = import_temporary_connection(repo, store, connection_text='https://old.test/prefix', api_key='old-key')
    repo.set_setting('generation_output_root', str(output))
    repo.save_workflow_profile(WorkflowProfile(id='20_test', display_name='20_Test_Upscale', bindings={}, api_workflow={
        '1': {'class_type': 'LoadImage', 'inputs': {'image': 'source.png'}},
        '2': {'class_type': 'UpscaleModelLoader', 'inputs': {'model_name': 'test.pth'}},
        '3': {'class_type': 'ImageUpscaleWithModel', 'inputs': {'image': ['1', 0], 'upscale_model': ['2', 0]}},
        '4': {'class_type': 'SaveImage', 'inputs': {'images': ['3', 0]}},
    }))
    service = build_v2_gallery_service(database, credential_store=store)
    manager = service.process_manager
    if import_after_start:
        assert not manager.configuration_payload()['available']
        old = import_temporary_connection(repo, store, connection_text='https://old.test/prefix', api_key='old-key')
    captured = Queue()
    release = Event()

    class StopBeforeNetwork:
        def execute(self, **options):
            captured.put(options)
            assert release.wait(10), 'test must release the blocked execution'
            raise RuntimeError('isolated execution sentinel')

    manager.coordinator_factory = lambda **_options: StopBeforeNetwork()

    def submit(name):
        source = output / name
        source.write_bytes(b'isolated-image')
        return manager.submit(source, name, {'width': 16, 'height': 16})

    try:
        assert manager.configuration_payload()['available']
        submit('active.png')
        active = captured.get(timeout=5)
        if queue_before_update:
            submit('queued.png')
        current = import_temporary_connection(repo, store, connection_text='https://new.test/next',
            api_key='new-key', target_profile_id=old.id)
        submit('new.png')
        release.set()
        accepted = [active]
        if queue_before_update:
            accepted.append(captured.get(timeout=5))
        latest = captured.get(timeout=5)
        for previous in accepted:
            assert previous['remote_profile'].http_base_url == 'https://old.test/prefix'
            assert previous['remote_profile'].http_session_id == old.http_session_id
            assert previous['credentials'].comfy_api_key == 'old-key'
        assert latest['remote_profile'].id == old.id
        assert latest['remote_profile'].http_base_url == 'https://new.test/next'
        assert latest['remote_profile'].http_session_id == current.http_session_id != old.http_session_id
        assert latest['credentials'].comfy_api_key == 'new-key'
        assert store.read_comfy_api_key(old.http_session_id) == ''
        assert b'old-key' not in database.read_bytes() and b'new-key' not in database.read_bytes()
    finally:
        release.set()
        service.shutdown(timeout=5)
        repo.close()


def test_durable_queue_rejects_replaced_http_session_before_workflow_resolution(protocol, tmp_path, monkeypatch):
    from anima_prompt_studio_v3.runtime.generation_queue import build_generation_queue, GenerationRunActionError
    calls, _, store = protocol
    database = tmp_path / 'runtime.db'
    repo = SQLiteRepository(database)
    repo.save_remote_profile(http_profile())
    run = GenerationRun(prompt_job_id='job', remote_profile_id='http', workflow_profile_id='workflow',
        remote_prompt_id='remote-prompt', state=GenerationRunState.FAILED,
        request_json={'prompt_job': PromptJob().model_dump(mode='json'), 'http_connection': {'session_id': 'replaced'}})
    repo.save_generation_run(run)
    repo.close()
    monkeypatch.setattr(WorkflowCatalog, 'resolve_for_submission', lambda *args: pytest.fail('No capability network checks before session rejection'))
    queue = build_generation_queue(database, credential_store=store)
    try:
        with pytest.raises(GenerationRunActionError, match='临时连接'):
            queue.resume(run.id)
        assert calls == []
    finally:
        queue.shutdown()


def test_frozen_credentials_do_not_reread_os_store_when_execution_starts(protocol, monkeypatch):
    from anima_prompt_studio_v3.remote.connections import connection_factory, client_for_connection
    from anima_prompt_studio.domain.execution_models import RemoteCredentials
    calls, _, store = protocol
    credentials = RemoteCredentials(comfy_api_key='runtime-secret')
    monkeypatch.setattr(store.backend, 'read', lambda *args: (_ for _ in ()).throw(RuntimeError('credential backend unavailable')))
    connection = connection_factory(http_profile())
    connection.open(credentials)
    client_for_connection(connection).validate_environment()
    assert all(auth == 'Bearer runtime-secret' for _, auth, _ in calls)


def test_credential_read_failure_in_probe_returns_offline(protocol, tmp_path, monkeypatch):
    _, _, store = protocol
    database = tmp_path / 'runtime.db'
    repo = SQLiteRepository(database)
    profile = http_profile()
    repo.save_remote_profile(profile)
    repo.close()
    monkeypatch.setattr(store.backend, 'read', lambda *args: (_ for _ in ()).throw(RuntimeError('credential backend unavailable')))
    probe = EnvironmentProbe(database)
    try:
        result = asyncio.run(probe({'id': profile.id, 'profile': profile, 'signature': fingerprint(profile)}, probe.clock() + 5, 0))
        assert result.connection_state == 'offline'
    finally:
        probe.close()


def test_http_api_connection_and_gateway_login_are_authenticated(reference_db, protocol, tmp_path):
    from fastapi.testclient import TestClient
    from anima_prompt_studio_v3.api import create_api_runtime
    from anima_prompt_studio_v3.runtime.comfy_access import ManagedComfyAccess
    calls, _, store = protocol
    database = tmp_path / 'runtime.db'
    repo = SQLiteRepository(database)
    profile = http_profile().model_copy(update={'http_gateway': True})
    repo.save_remote_profile(profile)
    repo.close()
    manager = ManagedComfyAccess(database, credential_store=store)
    runtime = create_api_runtime(reference_db, v2_database=database, comfy_access=manager)
    try:
        with TestClient(runtime.app, base_url='http://127.0.0.1') as client:
            exchanged = client.post('/api/v3/session/exchange', json={'bootstrap_token': runtime.bootstrap_token},
                headers={'Origin': 'http://127.0.0.1'})
            headers = {'Origin': 'http://127.0.0.1', 'X-Anima-Session': exchanged.json()['session_token']}
            tested = client.post('/api/v3/settings/remote-profiles/http/test-connection', headers=headers, json={})
            assert tested.status_code == 200, tested.text
            assert tested.json()['comfy_endpoint'] == 'https://example.test/prefix'
            listed = client.get('/api/v3/settings/remote-profiles', headers=headers)
            assert listed.status_code == 200
            assert listed.json()['items'][0]['comfy_endpoint'] == 'https://example.test/prefix'
            opened = client.post('/api/v3/settings/remote-profiles/http/open-comfy', headers=headers, json={})
            assert opened.status_code == 200, opened.text
            assert opened.json()['local_url'] == 'https://example.test/prefix/_moss/login'
            assert 'runtime-secret' not in opened.text and '手动输入' in opened.json()['message']
            assert opened.json()['ready']
        assert all(auth == 'Bearer runtime-secret' for _, auth, _ in calls)
    finally:
        manager.close()
        runtime.app.state.workflow_jobs.close()


def test_browser_access_honors_injected_http_credential_store(protocol, tmp_path, monkeypatch):
    from anima_prompt_studio_v3.runtime.comfy_access import ManagedComfyAccess
    _, _, store = protocol
    database = tmp_path / 'runtime.db'
    repo = SQLiteRepository(database)
    repo.save_remote_profile(http_profile())
    repo.close()
    monkeypatch.setattr('anima_prompt_studio_v3.remote.credential_store.CredentialStore', lambda: CredentialStore(MemoryCredentialBackend()))
    manager = ManagedComfyAccess(database, credential_store=store)
    try:
        assert manager.open('http')['ready']
    finally:
        manager.close()
