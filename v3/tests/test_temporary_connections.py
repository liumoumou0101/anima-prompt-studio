import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from anima_prompt_studio_v3.api import create_api_runtime
from anima_prompt_studio_v3.remote.credential_store import CredentialStore, MemoryCredentialBackend
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
from test_api import reference_db


@pytest.fixture
def imported_api(reference_db, tmp_path, monkeypatch):
    store = CredentialStore(MemoryCredentialBackend())
    monkeypatch.setattr('anima_prompt_studio_v3.remote.credential_store.CredentialStore', lambda: store)
    database = tmp_path / 'runtime.db'
    runtime = create_api_runtime(reference_db, v2_database=database)
    with TestClient(runtime.app, base_url='http://127.0.0.1') as client:
        exchanged = client.post('/api/v3/session/exchange', json={'bootstrap_token': runtime.bootstrap_token},
                                headers={'Origin': 'http://127.0.0.1'})
        client.headers.update({'Origin': 'http://127.0.0.1', 'X-Anima-Session': exchanged.json()['session_token']})
        yield client, database, store
    runtime.app.state.workflow_jobs.close()


def import_connection(client, text='https://example.test/prefix/_moss/login', **kwargs):
    return client.post('/api/v3/settings/temporary-connections/import',
                       json={'connection_text': text, 'display_name': 'Cloud', **kwargs})


def test_import_normalizes_and_persists_metadata_only(imported_api):
    client, database, store = imported_api
    response = import_connection(client, json.dumps({'protocol': 'comfyui-http',
        'base_url': 'https://EXAMPLE.test/prefix/_moss/login', 'api_key': 'private-key',
        'auth_header': 'Authorization', 'auth_scheme': 'Bearer', 'scope': 'current-colab-runtime',
        'model_catalog': '/_moss/models'}))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['connection_type'] == 'http'
    assert data['http_base_url'] == 'https://example.test/prefix'
    assert data['comfy_endpoint'] == 'https://example.test/prefix'
    assert data['web_url'] == 'https://example.test/prefix/_moss/login'
    assert data['http_session_id'] and data['has_saved_api_key']
    assert not data.get('http_runtime_id')
    assert 'private-key' not in response.text
    assert b'private-key' not in database.read_bytes()
    assert store.read_comfy_api_key(data['http_session_id']) == 'private-key'
    listed = client.get('/api/v3/settings/remote-profiles')
    assert listed.json()['items'][0] == data


@pytest.mark.parametrize('text', [
    'http://example.test', 'https://user:secret@example.test', 'https://example.test?key=secret',
    'https://example.test/#secret', 'https://example.test/\nsecret',
    'https://colab.research.google.com/drive/secret',
    json.dumps({'protocol': 'ssh', 'base_url': 'https://example.test', 'api_key': 'secret'}),
    json.dumps({'protocol': 'comfyui-http', 'base_url': 'https://example.test', 'auth_scheme': 'Basic', 'api_key': 'secret'}),
    json.dumps({'protocol': 'comfyui-http', 'base_url': 'https://example.test', 'auth_scheme': 'Bearer'}),
    '{"api_key":"secret",broken}', '{"api_key":"secret","padding":"' + 'x' * 70000 + '"}',
], ids=['http', 'userinfo', 'query', 'fragment', 'control', 'notebook', 'protocol', 'auth', 'missing-key', 'malformed', 'oversized'])
def test_invalid_import_never_echoes_secret_or_mutates(imported_api, text):
    client, database, _ = imported_api
    saved = import_connection(client).json()
    response = import_connection(client, text, target_profile_id=saved['id'])
    assert response.status_code == 422, response.text
    assert 'secret' not in response.text
    assert client.get('/api/v3/settings/remote-profiles').json()['items'] == [saved]


def test_update_preserves_id_mappings_and_idempotence_invalidates_epoch(imported_api):
    client, database, _ = imported_api
    first = import_connection(client, api_key='one').json()
    repo = SQLiteRepository(database)
    profile = repo.get_remote_profile(first['id'])
    repo.save_remote_profile(profile.model_copy(update={'model_aliases': {'logical': 'physical'}}))
    repo.set_setting('workflow_mapping:' + first['id'] + ':workflow', {'mapping': {'a': 'b'}})
    repo.set_setting('workflow_capabilities:' + first['id'], {'checked_at': 100})
    same = import_connection(client, api_key='one', target_profile_id=first['id']).json()
    assert same['http_session_id'] == first['http_session_id']
    changed = import_connection(client, 'https://replacement.test', api_key='two', target_profile_id=first['id']).json()
    assert changed['id'] == first['id']
    assert changed['http_session_id'] != first['http_session_id']
    assert repo.get_remote_profile(first['id']).model_aliases == {'logical': 'physical'}
    assert repo.get_setting('workflow_mapping:' + first['id'] + ':workflow')['mapping'] == {'a': 'b'}
    assert repo.get_setting('workflow_capabilities:' + first['id']) == {}
    assert repo.get_setting('environment_epoch:' + first['id']) == 2
    repo.close()


def test_credential_failure_preserves_old_connection_and_key(imported_api, monkeypatch):
    client, database, store = imported_api
    saved = import_connection(client, api_key='original').json()
    def fail(*args):
        raise RuntimeError('secret input must not be echoed')
    monkeypatch.setattr(store.backend, 'write', fail)
    result = import_connection(client, 'https://new.test', api_key='replacement', target_profile_id=saved['id'])
    assert result.status_code == 503
    assert 'secret input' not in result.text
    assert client.get('/api/v3/settings/remote-profiles').json()['items'] == [saved]
    assert store.read_comfy_api_key(saved['http_session_id']) == 'original'


def test_deleting_http_profile_deletes_comfy_key(imported_api):
    client, database, store = imported_api
    saved = import_connection(client, api_key='private-key').json()
    response = client.request('DELETE', '/api/v3/settings/remote-profiles/' + saved['id'], json={})
    assert response.status_code == 204, response.text
    assert not store.read_comfy_api_key(saved['http_session_id'])


def test_only_http_target_can_be_updated_and_ssh_operations_reject_http(imported_api):
    client, database, _ = imported_api
    local = client.post('/api/v3/settings/remote-profiles', json={'display_name': 'local', 'connection_type': 'local'}).json()
    assert import_connection(client, target_profile_id=local['id']).status_code == 409
    saved = import_connection(client).json()
    for action in ('probe-host-key', 'confirm-host-key'):
        response = client.post('/api/v3/settings/remote-profiles/' + saved['id'] + '/' + action,
                               json={'fingerprint': 'SHA256:fake'} if action == 'confirm-host-key' else {})
        assert response.status_code == 409


@pytest.mark.parametrize('extra', [
    {'scope': 'permanent'}, {'model_catalog': 'https://elsewhere.test/models'},
    {'model_catalog': '/arbitrary/models'}, {'api_key': 'json-key'},
], ids=['scope', 'catalog-origin', 'catalog-path', 'conflicting-key'])
def test_rejects_unsupported_metadata_and_conflicting_keys(imported_api, extra):
    client, _, _ = imported_api
    text = json.dumps({'protocol': 'comfyui-http', 'base_url': 'https://example.test', **extra})
    response = import_connection(client, text, api_key='explicit-key')
    assert response.status_code == 422
    assert 'explicit-key' not in response.text and 'json-key' not in response.text


def test_http_metadata_edit_and_reimport_preserve_credentials_and_gateway(imported_api):
    client, _, store = imported_api
    saved = import_connection(client, api_key='original').json()
    edited = client.put('/api/v3/settings/remote-profiles/' + saved['id'], json={
        'connection_type': 'http', 'display_name': 'Renamed', 'enabled': False})
    assert edited.status_code == 200
    assert edited.json()['http_session_id'] == saved['http_session_id']
    repeated = import_connection(client, 'https://example.test/prefix', display_name='', target_profile_id=saved['id']).json()
    assert repeated['http_session_id'] == saved['http_session_id']
    assert repeated['web_url'] == saved['web_url']
    assert repeated['display_name'] == 'Renamed' and not repeated['enabled']
    assert store.read_comfy_api_key(saved['http_session_id']) == 'original'


def test_retired_key_cleanup_failure_does_not_report_successful_import_as_failure(imported_api, monkeypatch):
    client, database, store = imported_api
    saved = import_connection(client, api_key='original').json()
    original_delete = store.backend.delete
    def fail(target):
        if target.endswith(saved['http_session_id']):
            raise RuntimeError('private backend data')
        return original_delete(target)
    monkeypatch.setattr(store.backend, 'delete', fail)
    replacement = import_connection(client, 'https://new.test', api_key='replacement', target_profile_id=saved['id'])
    assert replacement.status_code == 200, replacement.text
    current = replacement.json()
    assert current['http_session_id'] != saved['http_session_id']
    assert store.read_comfy_api_key(current['http_session_id']) == 'replacement'
    monkeypatch.setattr(store.backend, 'delete', original_delete)
    assert client.request('DELETE', '/api/v3/settings/remote-profiles/' + saved['id'], json={}).status_code == 204
    assert not store.read_comfy_api_key(current['http_session_id'])
    assert not store.read_comfy_api_key(saved['http_session_id'])


def test_bearer_json_update_without_new_key_preserves_existing_key(imported_api):
    client, _, store = imported_api
    saved = import_connection(client, api_key='original').json()
    text = json.dumps({'protocol': 'comfyui-http', 'base_url': 'https://new.test', 'auth_scheme': 'Bearer'})
    response = import_connection(client, text, target_profile_id=saved['id'])
    assert response.status_code == 200, response.text
    assert store.read_comfy_api_key(response.json()['http_session_id']) == 'original'


def test_public_update_with_explicit_blank_key_clears_saved_authentication(imported_api):
    client, database, store = imported_api
    saved = import_connection(client, api_key='original').json()
    response = import_connection(client, 'https://public.test/prefix', api_key='', target_profile_id=saved['id'])
    assert response.status_code == 200, response.text
    current = response.json()
    assert not current['has_saved_api_key']
    assert current['http_session_id'] != saved['http_session_id']
    assert store.read_comfy_api_key(current['http_session_id']) == ''
    assert store.read_comfy_api_key(saved['http_session_id']) == ''
    repo = SQLiteRepository(database)
    try:
        assert not repo.get_remote_profile(saved['id']).http_auth_required
    finally:
        repo.close()


def test_key_and_explicit_runtime_identity_changes_rotate_sessions(imported_api):
    client, database, _ = imported_api
    saved = import_connection(client, 'https://example.test', api_key='one').json()
    rekey = import_connection(client, 'https://example.test', api_key='two', target_profile_id=saved['id']).json()
    assert rekey['http_session_id'] != saved['http_session_id']
    text = json.dumps({'protocol': 'comfyui-http', 'base_url': 'https://example.test', 'runtime_id': 'runtime-2'})
    identified = import_connection(client, text, target_profile_id=saved['id']).json()
    assert identified['http_session_id'] != rekey['http_session_id']
    assert identified['http_runtime_id'] == 'runtime-2'


def test_failed_key_delete_keeps_http_profile_and_credentials(imported_api, monkeypatch):
    client, _, store = imported_api
    saved = import_connection(client, api_key='original').json()
    monkeypatch.setattr(store.backend, 'delete', lambda *_args: (_ for _ in ()).throw(RuntimeError('backend-secret')))
    response = client.request('DELETE', '/api/v3/settings/remote-profiles/' + saved['id'], json={})
    assert response.status_code == 503
    assert 'backend-secret' not in response.text
    assert client.get('/api/v3/settings/remote-profiles').json()['items'] == [saved]
    assert store.read_comfy_api_key(saved['http_session_id']) == 'original'


@pytest.mark.parametrize('key', ['Bearer value', 'line\nbreak', 'tab\tkey'])
def test_key_format_errors_are_safe(imported_api, key):
    client, _, _ = imported_api
    response = import_connection(client, api_key=key)
    assert response.status_code == 422
    assert key not in response.text


def test_response_credential_read_failure_rolls_back_import(imported_api, monkeypatch):
    client, database, store = imported_api
    monkeypatch.setattr(store.backend, 'read', lambda *_args: (_ for _ in ()).throw(RuntimeError('private-storage-error')))
    response = import_connection(client, api_key='new-key')
    assert response.status_code == 503
    assert 'private-storage-error' not in response.text
    repository = SQLiteRepository(database)
    assert repository.list_remote_profiles() == []
    repository.close()
    assert store.backend.values == {}


@pytest.mark.parametrize('failure', ['delete-sql', 'commit', 'partial-credential'])
def test_failed_http_deletion_restores_current_and_retired_credentials(imported_api, monkeypatch, failure):
    from anima_prompt_studio_v3.remote.temporary_connections import delete_http_credentials
    from anima_prompt_studio_v3.remote.credential_store import CredentialStoreError
    client, database, credentials = imported_api
    saved = import_connection(client, api_key='active-key').json()
    repo = SQLiteRepository(database)
    profile = repo.get_remote_profile(saved['id'])
    credentials.save_comfy_api_key('retired-session', 'retired-key')
    repo.set_setting('http_retired_sessions:' + profile.id, ['retired-session'])
    original_connection = repo.connection
    if failure == 'delete-sql':
        repo.connection.executescript("CREATE TRIGGER abort_delete BEFORE DELETE ON remote_profiles BEGIN SELECT RAISE(ABORT, 'simulated deletion failure'); END;")
    elif failure == 'commit':
        class FailingCommit:
            def __getattr__(self, name):
                return getattr(original_connection, name)
            def commit(self):
                raise sqlite3.OperationalError('simulated commit failure')
        repo.connection = FailingCommit()
    else:
        original_delete = credentials.backend.delete
        def partially_fail(target):
            original_delete(target)
            if target.endswith(profile.http_session_id):
                raise RuntimeError('credential deletion failed after removal')
        monkeypatch.setattr(credentials.backend, 'delete', partially_fail)
    try:
        with pytest.raises(CredentialStoreError if failure == 'partial-credential' else sqlite3.Error):
            repo.delete_remote_profile(profile.id, before_delete=lambda current: delete_http_credentials(repo, credentials, current))
        assert repo.get_remote_profile(profile.id) == profile
        assert credentials.read_comfy_api_key(profile.http_session_id) == 'active-key'
        assert credentials.read_comfy_api_key('retired-session') == 'retired-key'
        assert repo.get_setting('http_retired_sessions:' + profile.id) == ['retired-session']
        assert b'active-key' not in database.read_bytes() and b'retired-key' not in database.read_bytes()
    finally:
        repo.connection = original_connection
        repo.close()


def test_http_delete_api_preserves_key_when_sql_delete_aborts(imported_api):
    client, database, credentials = imported_api
    saved = import_connection(client, api_key='active-key').json()
    repo = SQLiteRepository(database)
    repo.connection.executescript("CREATE TRIGGER abort_delete BEFORE DELETE ON remote_profiles BEGIN SELECT RAISE(ABORT, 'simulated deletion failure'); END;")
    repo.close()
    with pytest.raises(sqlite3.IntegrityError):
        client.request('DELETE', '/api/v3/settings/remote-profiles/' + saved['id'], json={})
    assert client.get('/api/v3/settings/remote-profiles').json()['items'] == [saved]
    assert credentials.read_comfy_api_key(saved['http_session_id']) == 'active-key'
