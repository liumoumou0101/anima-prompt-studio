import copy
import json
import pytest


def document():
    return {'protocol_version': 1, 'models': [{'id': 'anima_turbo_v1_1', 'display_name': 'Turbo', 'family': 'ANIMA',
        'checkpoint': 'diffusion_models/sub/model.safetensors', 'text_encoder': 'text_encoders/qwen.safetensors',
        'vae': 'vae/image.safetensors', 'assets': ['diffusion_models/sub/model.safetensors', 'text_encoders/qwen.safetensors', 'vae/image.safetensors'],
        'ready': True, 'selected_for_startup': True,
        'suggested_defaults': {'steps': 10, 'cfg': 1, 'sampler': 'euler', 'scheduler': 'normal'}, 'api_key': 'do-not-cache'}]}


def parse(raw):
    from anima_prompt_studio_v3.remote.cloud_model_catalog import parse_catalog
    return parse_catalog(json.dumps(raw).encode())


def test_protocol_preserves_category_subdirectories_and_whitelists_metadata():
    model = parse(document())['models'][0]
    assert model['checkpoint'] == 'diffusion_models/sub/model.safetensors'
    assert model['assets'][0]['filename'] == 'sub/model.safetensors'
    assert 'api_key' not in json.dumps(model)


@pytest.mark.parametrize('change', [
    lambda d: d.update(protocol_version=2),
    lambda d: d['models'].append(copy.deepcopy(d['models'][0])),
    lambda d: d['models'][0].update(assets=['diffusion_models/../bad']),
    lambda d: d['models'][0].update(assets=['/diffusion_models/a']),
    lambda d: d['models'][0].update(assets=['unknown/a']),
    lambda d: d['models'][0].update(assets=['diffusion_models/a%2fb']),
    lambda d: d['models'][0]['suggested_defaults'].update(cfg=float('nan')),
    lambda d: d['models'][0]['suggested_defaults'].update(steps=201),
    lambda d: d['models'][0]['suggested_defaults'].update(steps=True),
    lambda d: d['models'][0]['suggested_defaults'].update(download='https://secret'),
    lambda d: d.update(models=[dict(d['models'][0], id=str(i)) for i in range(129)]),
])
def test_protocol_rejects_invalid_documents(change):
    doc = document()
    change(doc)
    with pytest.raises(ValueError):
        parse(doc)


def test_protocol_rejects_oversize_and_duplicate_json_keys():
    from anima_prompt_studio_v3.remote.cloud_model_catalog import parse_catalog
    for raw in (b' ' * (1024 * 1024 + 1), b'{"protocol_version":1,"protocol_version":1,"models":[]}'):
        with pytest.raises(ValueError):
            parse_catalog(raw)


def setup_service(tmp_path, monkeypatch, *, change=None, failure=None):
    from anima_prompt_studio_v3.runtime.cloud_model_catalog import CloudModelCatalog
    from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
    from test_http_runtime_identity import profile
    from anima_prompt_studio_v3.runtime.workflow_catalog import catalog
    database = tmp_path / 'runtime.db'
    repo = SQLiteRepository(database)
    remote = profile()
    repo.save_remote_profile(remote)
    repo.close()
    workflow = next(p for p, _ in catalog(database) if remote and 'anima_turbo_v1_1' in p.compatible_model_profiles)
    doc = document()
    info = {}
    aliases = {'unet_name': 'sub/model.safetensors', 'clip_name': 'qwen.safetensors', 'vae_name': 'image.safetensors',
               'sampler_name': 'euler', 'scheduler': 'normal'}
    for node in workflow.api_workflow.values():
        info.setdefault(node['class_type'], {'input': {'required': {}}})
        for key, value in node['inputs'].items():
            if key in aliases:
                info[node['class_type']]['input']['required'][key] = [[aliases[key], value] if key in {'sampler_name', 'scheduler'} else [aliases[key]]]
    class Connection:
        def open(self, *args): pass
        def close(self): pass
    class Client:
        def read_bounded(self, path, **kwargs):
            if failure: raise failure
            if change: change(database, remote)
            return json.dumps(doc).encode()
        def object_info(self, **kwargs): return info
    monkeypatch.setattr('anima_prompt_studio_v3.runtime.cloud_model_catalog.connection_factory', lambda *a, **k: Connection())
    monkeypatch.setattr('anima_prompt_studio_v3.runtime.cloud_model_catalog.client_for_connection', lambda *a, **k: Client())
    monkeypatch.setattr('anima_prompt_studio_v3.runtime.cloud_model_catalog.read_runtime_identity', lambda *a: 'runtime-1')
    return CloudModelCatalog(database), remote, workflow, doc, info


def test_service_maps_exact_enumerations_and_applies_without_changing_defaults(tmp_path, monkeypatch):
    service, remote, workflow, doc, info = setup_service(tmp_path, monkeypatch)
    assert service.report(remote.id)['status'] == 'unchecked'
    result = service.refresh(remote.id)
    assert result['status'] == 'ready'
    item = result['items'][0]
    assert item['supported'] and item['ready']
    mapping = next(m for m in item['workflow_mappings'] if m['workflow_profile_id'] == workflow.id)
    assert not mapping['errors']
    assert 'sub/model.safetensors' in mapping['mapping'].values()
    service.apply_mapping(remote.id, item['id'], workflow.id, remote.http_session_id, 0)
    from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
    repo = SQLiteRepository(service.database)
    assert repo.get_setting('workflow_mapping:' + remote.id + ':' + workflow.id)['mapping'] == mapping['mapping']
    assert repo.get_setting('selected_model_profile_id') is None
    repo.close()
    doc['models'][0]['id'] = 'unknown_future_model'
    unknown = service.refresh(remote.id)['items'][0]
    assert not unknown['supported'] and unknown['workflow_mappings'] == []


def test_service_late_session_result_discarded(tmp_path, monkeypatch):
    def replace(database, remote):
        from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
        repo = SQLiteRepository(database)
        repo.save_remote_profile(remote.model_copy(update={'http_session_id': 'new'}))
        repo.close()
    service, remote, *_ = setup_service(tmp_path, monkeypatch, change=replace)
    result = service.refresh(remote.id)
    assert result['session_id'] == 'new' and result['status'] != 'ready'
    assert result['items'] == []


def test_service_failure_invalidates_old_ready_and_mapping_conflict(tmp_path, monkeypatch):
    from anima_prompt_studio_v3.remote.comfy_client import ComfyAPIError
    service, remote, workflow, doc, info = setup_service(tmp_path, monkeypatch)
    result = service.refresh(remote.id)
    with pytest.raises(ValueError):
        service.apply_mapping(remote.id, result['items'][0]['id'], workflow.id, 'old-session', 0)
    monkeypatch.setattr('anima_prompt_studio_v3.runtime.cloud_model_catalog.client_for_connection',
                        lambda *a, **k: (_ for _ in ()).throw(ComfyAPIError('secret-key')))
    failed = service.refresh(remote.id)
    assert failed['status'] == 'unavailable' and failed['items'] == []
    assert 'secret-key' not in json.dumps(failed)


def test_service_enum_conflict_never_offers_partial_mapping(tmp_path, monkeypatch):
    service, remote, workflow, doc, info = setup_service(tmp_path, monkeypatch)
    doc['models'][0]['checkpoint'] = doc['models'][0]['assets'][0] = 'diffusion_models/other/model.safetensors'
    result = service.refresh(remote.id)
    suggestion = next(m for m in result['items'][0]['workflow_mappings'] if m['workflow_profile_id'] == workflow.id)
    assert suggestion['errors'] and not suggestion['mapping']
    with pytest.raises(ValueError): service.apply_mapping(remote.id, 'anima_turbo_v1_1', workflow.id, remote.http_session_id, 0)


@pytest.mark.parametrize('key', ['do-not-cache', 'a'])
def test_service_never_caches_bearer_key_even_in_whitelisted_metadata(tmp_path, monkeypatch, key):
    from test_http_runtime_identity import Response, Session
    from anima_prompt_studio_v3.remote.comfy_client import ComfyUIClient
    service, remote, _, doc, info = setup_service(tmp_path, monkeypatch)
    doc['models'][0]['display_name'] = key
    class CatalogSession(Session):
        def get(self, url, **kwargs):
            if url.endswith('/_moss/info'):
                return Response({'runtime_id': 'runtime-1'})
            return Response(doc if url.endswith('/_moss/models') else info)
    client = ComfyUIClient('https://example.test', session=CatalogSession('runtime-1'), api_key=key)
    monkeypatch.setattr('anima_prompt_studio_v3.runtime.cloud_model_catalog.client_for_connection', lambda *a, **k: client)
    result = service.refresh(remote.id)
    assert result['status'] == ('unavailable' if key == 'a' else 'ready')
    if key != 'a':
        assert key not in json.dumps(result)
        assert key.encode() not in service.database.read_bytes()


def test_newer_refresh_failure_cannot_be_overwritten_by_late_success(tmp_path, monkeypatch):
    from anima_prompt_studio_v3.runtime.cloud_model_catalog import CloudModelCatalog
    def newer_failure(database, remote):
        monkeypatch.setattr('anima_prompt_studio_v3.runtime.cloud_model_catalog.client_for_connection',
                            lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
        assert CloudModelCatalog(database).refresh(remote.id)['status'] == 'unavailable'
    service, remote, *_ = setup_service(tmp_path, monkeypatch, change=newer_failure)
    assert service.refresh(remote.id)['status'] == 'unavailable'


def test_changed_live_instance_invalidates_capabilities_and_epoch(tmp_path, monkeypatch):
    from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
    service, remote, *_ = setup_service(tmp_path, monkeypatch)
    assert service.refresh(remote.id)['status'] == 'ready'
    monkeypatch.setattr('anima_prompt_studio_v3.runtime.cloud_model_catalog.read_runtime_identity', lambda *a: 'new-runtime')
    result = service.refresh(remote.id)
    assert result['status'] == 'unavailable' and result['environment_epoch'] == 1
    repo = SQLiteRepository(service.database)
    assert repo.get_setting('workflow_capabilities:' + remote.id) == {}
    repo.close()
    assert service.refresh(remote.id)['status'] == 'unavailable'
    from anima_prompt_studio_v3.runtime.cloud_model_catalog import assert_runtime_confirmed
    repo = SQLiteRepository(service.database)
    try:
        with pytest.raises(ValueError): assert_runtime_confirmed(repo, remote)
    finally:
        repo.close()


def test_mapping_rejects_workflow_revision_change_and_filters_unavailable_sampler(tmp_path, monkeypatch):
    from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
    service, remote, workflow, doc, info = setup_service(tmp_path, monkeypatch)
    doc['models'][0]['suggested_defaults']['sampler'] = 'unavailable_sampler'
    result = service.refresh(remote.id)
    assert 'sampler' not in result['items'][0]['suggested_defaults']
    repo = SQLiteRepository(service.database)
    repo.save_workflow_profile(workflow.model_copy(update={'display_name': 'Changed workflow revision'}))
    repo.close()
    with pytest.raises(ValueError, match='刷新'):
        service.apply_mapping(remote.id, 'anima_turbo_v1_1', workflow.id, remote.http_session_id, 0)


def test_catalog_retains_identity_through_failure_epoch_and_resets_for_new_session(tmp_path, monkeypatch):
    from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
    from anima_prompt_studio_v3.runtime.cloud_model_catalog import assert_runtime_confirmed
    service, remote, *_ = setup_service(tmp_path, monkeypatch)
    assert service.refresh(remote.id)['status'] == 'ready'
    with monkeypatch.context() as failure:
        failure.setattr('anima_prompt_studio_v3.runtime.cloud_model_catalog.client_for_connection',
                        lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
        assert service.refresh(remote.id)['status'] == 'unavailable'
    repo = SQLiteRepository(service.database)
    repo.set_setting('environment_epoch:' + remote.id, 4)
    repo.close()
    monkeypatch.setattr('anima_prompt_studio_v3.runtime.cloud_model_catalog.read_runtime_identity', lambda *a: 'new-runtime')
    assert service.refresh(remote.id)['status'] == 'unavailable'
    repo = SQLiteRepository(service.database)
    try:
        with pytest.raises(ValueError): assert_runtime_confirmed(repo, remote)
        replacement = remote.model_copy(update={'http_session_id': 'replacement', 'http_runtime_id': 'new-runtime'})
        repo.save_remote_profile(replacement)
        assert_runtime_confirmed(repo, replacement)
    finally:
        repo.close()
    assert service.refresh(remote.id)['status'] == 'ready'
