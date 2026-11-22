import time
from types import SimpleNamespace

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from anima_prompt_studio_v3.api.loras import register_lora_routes
from anima_prompt_studio_v3.runtime.lora_library import LoraLibrary
from test_lora_library import tensor_file


def test_authenticated_library_and_sync_jobs_reuse_missing_local_cloud_cache(tmp_path):
    library = LoraLibrary(tmp_path / 'state.db', tmp_path / 'loras')
    sha = tensor_file(library.root / 'style.safetensors')
    profile = SimpleNamespace(model_dump=lambda **kwargs: {'connection_type': 'http', 'http_session_id': 'current'})
    calls = []
    class Client:
        def ensure(self, remote_id, digest, path, progress=None, expected_signature=None):
            path = path() if callable(path) else path
            calls.append((remote_id, digest, path))
            return {'sha256': digest, 'file_name': f'anima_library/{digest}.safetensors', 'installed': True, 'cached': True, 'uploaded_bytes': 0, 'restored': path is None}
    class Manager:
        def remote(self, remote_id): return profile
        def inspect(self, remote_id): calls.append(('inspect', remote_id))
        def _read(self, key, default):
            if key.startswith('workflow_capabilities:'):
                return {'object_info': {'LoraLoader': {'input': {'required': {'lora_name': [[f'anima_library/{sha}.safetensors']]}}}}}
            return default
    def session(x_anima_session: str | None = Header(default=None)):
        if x_anima_session != 'test': raise HTTPException(401)
    app = FastAPI()
    register_lora_routes(app, library.database, session, library_root=library.root, asset_client=Client(), manager=Manager())
    with TestClient(app) as client:
        assert client.get('/api/v3/loras').status_code == 401
        headers = {'x-anima-session': 'test'}
        scanned = client.post('/api/v3/loras/scan', headers=headers).json()
        assert scanned['items'][0]['sha256'] == sha
        updated = client.put('/api/v3/loras/' + sha, json={'family': 'anima', 'name': 'Style'}, headers=headers)
        assert updated.status_code == 200 and updated.json()['name'] == 'Style'
        (library.root / 'style.safetensors').unlink()
        client.post('/api/v3/loras/scan', headers=headers)
        result = client.post('/api/v3/loras/environments/test-env/sync', json={'sha256s': [sha]}, headers=headers)
        assert result.status_code == 200
        for _ in range(100):
            job = client.get('/api/v3/loras/jobs/' + result.json()['id'], headers=headers).json()
            if job['state'] in {'completed', 'failed'}: break
            time.sleep(.01)
        assert job['state'] == 'completed', job
        assert job['results'][0]['restored']
        assert ('inspect', 'test-env') in calls
        assert client.post('/api/v3/loras/environments/test-env/sync', json={'sha256s': ['../outside']}, headers=headers).status_code == 422


def test_library_api_rejects_mutating_resource_identity(tmp_path):
    app = FastAPI()
    register_lora_routes(app, tmp_path / 'state.db', lambda: None, library_root=tmp_path / 'loras')
    with TestClient(app) as client:
        response = client.put('/api/v3/loras/' + 'a' * 64, json={'relative_path': '../escape'})
        assert response.status_code == 422


def test_lora_identity_probes_authenticated_gateway_and_rejects_same_url_restart(tmp_path, monkeypatch):
    import requests
    from anima_prompt_studio_v3.remote.credential_store import CredentialStore
    from anima_prompt_studio_v3.remote.preparation_budget import DirectPreparationBudget
    from anima_prompt_studio_v3.runtime.workflow_catalog import WorkflowCatalog
    from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
    from test_http_runtime_identity import profile, Response

    remote = profile()
    database = tmp_path / "runtime.db"
    manager = WorkflowCatalog(database)
    repo = SQLiteRepository(database)
    repo.save_remote_profile(remote)
    repo.close()
    observed = [remote.http_runtime_id]
    calls = []
    def gateway(session, method, url, **options):
        assert options['headers']['Authorization'] == 'Bearer test-access-token'
        assert options['allow_redirects'] is False
        calls.append((method.lower(), url))
        return Response({'runtime_id': observed[0]})
    monkeypatch.setattr(requests.Session, 'request', gateway)
    monkeypatch.setattr(CredentialStore, 'read_comfy_api_key', lambda self, session_id: 'test-access-token')
    app = FastAPI()
    register_lora_routes(app, database, lambda: None, manager=manager)
    route = f'/api/v3/loras/environments/{remote.id}/identity'
    with TestClient(app) as client:
        ready = client.get(route)
        assert ready.status_code == 200 and len(ready.json()['signature']) == 64
        with DirectPreparationBudget(seconds=0):
            assert app.state.lora_sync_jobs.identity(remote.id) == ready.json()
        observed[0] = 'replacement-runtime'
        stale = client.get(route)
        assert stale.status_code == 409
        assert stale.json()['error']['code'] == 'runtime_identity_mismatch'
        assert 'test-access-token' not in stale.text
    assert calls == [('get', remote.http_base_url + '/_moss/info')] * 3
    assert manager._read('environment_epoch:' + remote.id) == 1
