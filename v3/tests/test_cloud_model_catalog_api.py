import pytest
from test_api import reference_db
from test_temporary_connections import imported_api, import_connection
from anima_prompt_studio_v3.remote.comfy_client import ComfyAPIError


def test_catalog_api_cache_only_protected_and_missing_remote(imported_api):
    client, database, _ = imported_api
    remote = import_connection(client).json()
    path = '/api/v3/settings/remote-profiles/' + remote['id'] + '/model-catalog'
    result = client.get(path)
    assert result.status_code == 200
    assert result.json()['status'] == 'unchecked'
    assert client.get(path.replace(remote['id'], 'does-not-exist')).status_code == 404
    client.headers.pop('X-Anima-Session')
    assert client.get(path).status_code == 401
    assert client.post(path + '/refresh', json={}).status_code == 401


@pytest.mark.parametrize('failure,status', [(ComfyAPIError('HTTP 404 secret', code='unsupported'), 'unsupported'),
    (ComfyAPIError('HTTP 401 secret', code='http_error'), 'unavailable'), (TimeoutError('secret timeout'), 'unavailable')])
def test_catalog_refresh_remote_errors_are_safe(imported_api, monkeypatch, failure, status):
    client, _, _ = imported_api
    remote = import_connection(client).json()
    path = '/api/v3/settings/remote-profiles/' + remote['id'] + '/model-catalog'
    monkeypatch.setattr('anima_prompt_studio_v3.runtime.cloud_model_catalog.client_for_connection', lambda *a, **k: (_ for _ in ()).throw(failure))
    assert client.post(path + '/refresh').status_code == 415
    result = client.post(path + '/refresh', json={})
    assert result.status_code == 200
    assert result.json()['status'] == status
    assert 'secret' not in result.text
    apply = client.post(path + '/apply-mapping', json={'model_id': 'anima_turbo_v1_1', 'workflow_profile_id': 'x',
                                                       'session_id': remote['http_session_id'], 'environment_epoch': 0})
    assert apply.status_code == 409
