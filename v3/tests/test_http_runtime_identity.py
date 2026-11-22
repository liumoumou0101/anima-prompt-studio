import pytest
from anima_prompt_studio.domain.execution_models import RemoteProfile, RemoteArtifact
from anima_prompt_studio_v3.remote.comfy_client import ComfyUIClient, ComfyAPIError
from anima_prompt_studio_v3.remote.connections import HttpComfyConnection, client_for_connection


class Response:
    status_code = 200
    headers = {}
    def __init__(self, data):
        import json
        self.content = json.dumps(data).encode()
    def json(self):
        import json
        return json.loads(self.content)
    def iter_content(self, chunk_size):
        yield self.content
    def close(self): pass
    def raise_for_status(self): pass


class Session:
    def __init__(self, identity):
        self.identity, self.calls = identity, []
    def get(self, url, **kwargs):
        self.calls.append(url)
        return Response({'runtime_id': self.identity} if url.endswith('/_moss/info') else {})
    def post(self, url, **kwargs):
        self.calls.append(url)
        return Response({'prompt_id': 'p'})


def profile(expected='runtime-1', gateway=True):
    return RemoteProfile(connection_type='http', http_base_url='https://example.test', http_session_id='s',
                         http_runtime_id=expected, http_gateway=gateway, ssh_host='', ssh_user='')


@pytest.mark.parametrize('action', ['prompt', 'history', 'view'])
def test_runtime_mismatch_blocks_sensitive_request(action):
    session = Session('runtime-2')
    client = client_for_connection(HttpComfyConnection(profile()), session=session)
    with pytest.raises(ComfyAPIError, match='运行'):
        if action == 'prompt': client.submit({}, 'c', 'p')
        elif action == 'history': client.get_history_entry('p')
        else: client.download_artifact(RemoteArtifact(node_id='1', filename='a.png'))
    assert session.calls == ['https://example.test/_moss/info']


def test_live_identity_not_imported_string_and_old_gateway_weak():
    from anima_prompt_studio_v3.remote.connections import read_runtime_identity
    assert read_runtime_identity(ComfyUIClient('https://example.test', session=Session(None)), profile(None)) is None
    with pytest.raises(ComfyAPIError):
        read_runtime_identity(ComfyUIClient('https://example.test', session=Session(None)), profile())


def test_plain_comfyui_compatibility_and_same_url_restart():
    session = Session('first')
    plain = client_for_connection(HttpComfyConnection(profile(None, False)), session=session)
    plain.submit({}, 'c', 'p')
    assert not any('/_moss/info' in call for call in session.calls)
    session = Session('runtime-1')
    client = client_for_connection(HttpComfyConnection(profile()), session=session)
    client.get_history_entry('p')
    session.identity = 'runtime-2'
    with pytest.raises(ComfyAPIError): client.submit({}, 'c', 'p')
    assert not any(call.endswith('/prompt') for call in session.calls)


def test_exact_node_preflight_blocks_catalog_missing_file_even_when_enum_present():
    import json
    from test_cloud_model_catalog import document
    doc = document()
    doc['models'][0]['ready'] = False
    class CatalogSession(Session):
        def get(self, url, **kwargs):
            if url.endswith('/_moss/models'):
                return Response(doc)
            return super().get(url, **kwargs)
    client = client_for_connection(HttpComfyConnection(profile()), session=CatalogSession('runtime-1'))
    client._object_info_cache = {'UNETLoader': {'input': {'required': {'unet_name': [['sub/model.safetensors']]}}}}
    errors = client.validate_workflow_inputs({'1': {'class_type': 'UNETLoader', 'inputs': {'unet_name': 'sub/model.safetensors'}}})
    assert errors and 'Turbo' in errors[0]


def test_run_freezes_live_identity_when_import_has_no_identity_and_rejects_resume_restart():
    from anima_prompt_studio.domain.execution_models import GenerationRun
    from anima_prompt_studio_v3.remote.connections import verify_run_runtime_identity, http_connection_snapshot
    remote = profile(None)
    run = GenerationRun(prompt_job_id='job', remote_profile_id=remote.id, workflow_profile_id='workflow',
                        request_json={'http_connection': http_connection_snapshot(remote)})
    original = client_for_connection(HttpComfyConnection(remote), session=Session('first'))
    verify_run_runtime_identity(original, remote, run)
    assert run.request_json['http_connection']['observed_runtime_id'] == 'first'
    restarted = client_for_connection(HttpComfyConnection(remote), session=Session('second'))
    with pytest.raises(ComfyAPIError): verify_run_runtime_identity(restarted, remote, run)


def test_bounded_gateway_reader_stops_oversized_stream_and_closes_response():
    response = Response({})
    closed = []
    response.iter_content = lambda **kwargs: iter([b'1234', b'5678'])
    response.close = lambda: closed.append(True)
    session = Session(None)
    session.get = lambda *a, **k: response
    client = ComfyUIClient('https://example.test', session=session)
    with pytest.raises(ComfyAPIError) as exc: client.read_bounded('/_moss/models', maximum=5)
    assert exc.value.code == 'response_too_large' and closed == [True]


def test_bounded_reader_has_absolute_stream_deadline(monkeypatch):
    clock = iter([0, 16])
    monkeypatch.setattr('anima_prompt_studio_v3.remote.comfy_client.time.monotonic', lambda: next(clock))
    client = ComfyUIClient('https://example.test', session=Session(None))
    with pytest.raises(ComfyAPIError) as exc: client.read_bounded('/_moss/models')
    assert exc.value.code == 'timeout'


def test_probe_imported_identity_alone_is_never_strong_and_invalidates_epoch(tmp_path):
    import asyncio
    from test_environment_probe import setup_probe
    from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
    probe, candidate, _, database = setup_probe(tmp_path)
    remote = profile().model_copy(update={'id': candidate['profile'].id})
    candidate['profile'] = remote
    repo = SQLiteRepository(database)
    repo.save_remote_profile(remote)
    repo.close()
    try:
        result = asyncio.run(probe(candidate, probe.clock() + 5, 0))
        assert result.identity_strength == 'weak' and result.capabilities_state == 'unchecked'
        assert result.reason_codes == ['instance_changed']
        repo = SQLiteRepository(database)
        assert repo.get_setting('environment_epoch:' + remote.id) == 1
        assert repo.get_setting('workflow_capabilities:' + remote.id) == {}
        repo.close()
    finally:
        probe.close()


@pytest.mark.parametrize('intermediate_failure', [False, True])
def test_probe_retains_observed_identity_until_connection_session_replaced(tmp_path, monkeypatch, intermediate_failure):
    import asyncio
    from test_environment_probe import setup_probe
    from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
    probe, candidate, _, database = setup_probe(tmp_path)
    remote = profile(None).model_copy(update={'id': candidate['profile'].id})
    candidate.update(profile=remote, recheck=True)
    repo = SQLiteRepository(database)
    repo.save_remote_profile(remote)
    repo.close()
    observed = ['first']
    def read_identity(*args):
        if isinstance(observed[0], Exception):
            raise observed[0]
        return observed[0]
    monkeypatch.setattr('anima_prompt_studio_v3.runtime.environment_probe.read_runtime_identity', read_identity)
    def check():
        repo = SQLiteRepository(database)
        epoch = repo.get_setting('environment_epoch:' + remote.id, 0)
        repo.close()
        return asyncio.run(probe(candidate, probe.clock() + 5, epoch))
    try:
        assert check().capabilities_state == 'ready'
        if intermediate_failure:
            observed[0] = TimeoutError()
            assert check().capabilities_state == 'unchecked'
        observed[0] = 'second'
        assert check().reason_codes == ['instance_changed']
        assert check().reason_codes == ['instance_changed']
        replacement = remote.model_copy(update={'http_session_id': 'replacement'})
        repo = SQLiteRepository(database)
        repo.save_remote_profile(replacement)
        repo.close()
        candidate.update(profile=replacement, signature='replacement')
        assert check().capabilities_state == 'ready'
    finally:
        probe.close()
