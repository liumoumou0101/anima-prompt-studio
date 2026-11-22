import time
from datetime import datetime
from threading import Event

import pytest

from anima_prompt_studio.domain.execution_models import RemoteCredentials, RemoteProfile, WorkflowProfile
from anima_prompt_studio.services.gallery_upscale import GalleryUpscaleManager
from anima_prompt_studio_v3.remote.credential_store import CredentialStore, MemoryCredentialBackend
from anima_prompt_studio_v3.remote.temporary_connections import import_temporary_connection
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository


@pytest.mark.parametrize('scenario', [
    'replaced-http', 'missing-http-snapshot', 'wrong-profile', 'wrong-base', 'wrong-runtime',
    'http-to-local', 'legacy-local-to-http', 'same-http', 'legacy-local', 'legacy-ssh',
    'local-to-different-local', 'ssh-endpoint-changed',
])
def test_reloaded_gallery_queue_checks_durable_http_session_before_execution(tmp_path, scenario):
    database = tmp_path / 'queue.db'
    output = tmp_path / 'outputs'
    output.mkdir()
    store = CredentialStore(MemoryCredentialBackend())
    repo = SQLiteRepository(database)
    legacy = scenario in {'legacy-local', 'legacy-ssh', 'legacy-local-to-http',
                          'local-to-different-local', 'ssh-endpoint-changed'}
    if legacy:
        profile = RemoteProfile(id='legacy', connection_type='ssh' if scenario in {'legacy-ssh', 'ssh-endpoint-changed'} else 'local',
            ssh_host='localhost', ssh_user='test', auth_type='agent', known_host_fingerprint='SHA256:test')
    else:
        profile = import_temporary_connection(repo, store, connection_text='https://old.test/prefix', api_key='old-key')
    workflow = WorkflowProfile(id='20_recovery', display_name='20_Recovery', bindings={}, api_workflow={
        '1': {'class_type': 'LoadImage', 'inputs': {'image': 'source.png'}},
        '2': {'class_type': 'UpscaleModelLoader', 'inputs': {'model_name': 'test.pth'}},
        '3': {'class_type': 'ImageUpscaleWithModel', 'inputs': {'image': ['1', 0], 'upscale_model': ['2', 0]}},
        '4': {'class_type': 'SaveImage', 'inputs': {'images': ['3', 0]}},
    })
    active = Event()
    release = Event()

    class HoldActiveExecution:
        def execute(self, **_options):
            active.set()
            assert release.wait(10)
            raise RuntimeError('isolated active execution')

    original = GalleryUpscaleManager(database, output, coordinator_factory=lambda **_options: HoldActiveExecution())
    original.configure(profile, workflow, RemoteCredentials(comfy_api_key='old-key' if not legacy else None))
    restored = None
    reached_execution = Event()
    captured = []

    class StopBeforeNetwork:
        def execute(self, **options):
            captured.append(options)
            reached_execution.set()
            raise RuntimeError('isolated recovery sentinel')

    try:
        for name in ('active.png', 'queued.png'):
            source = output / name
            source.write_bytes(b'image')
            queued = original.submit(source, name, {'width': 16, 'height': 16})
            if name == 'active.png':
                assert active.wait(5)
        assert original.get(queued['id'])['state'] == 'queued'
        original.shutdown(cancel_queued=False, timeout=0)
        release.set()
        assert original.shutdown(cancel_queued=False, timeout=5)
        persisted = next(job for job in repo.list_gallery_process_jobs(output) if job['id'] == queued['id'])
        assert persisted['state'] == 'queued'
        if scenario in {'legacy-local', 'legacy-ssh', 'legacy-local-to-http'}:
            persisted.pop('connectionFingerprint', None)
            repo.save_gallery_process_job(output, queued['id'], 'queued', 1,
                datetime.fromisoformat(persisted['updatedAt']), persisted)

        current = profile
        if scenario == 'replaced-http':
            current = import_temporary_connection(repo, store, connection_text='https://new.test/next',
                api_key='new-key', target_profile_id=profile.id)
        elif scenario == 'missing-http-snapshot':
            persisted.pop('httpConnection', None)
            repo.save_gallery_process_job(output, queued['id'], 'queued', 1,
                datetime.fromisoformat(persisted['updatedAt']), persisted)
        elif scenario == 'wrong-profile':
            current = profile.model_copy(update={'id': 'different-profile'})
        elif scenario == 'wrong-base':
            current = profile.model_copy(update={'http_base_url': 'https://different.test'})
        elif scenario == 'wrong-runtime':
            current = profile.model_copy(update={'http_runtime_id': 'runtime-two'})
        elif scenario == 'http-to-local':
            current = profile.model_copy(update={'connection_type': 'local'})
        elif scenario == 'legacy-local-to-http':
            current = import_temporary_connection(repo, store, connection_text='https://new.test/next', api_key='new-key')
        elif scenario == 'local-to-different-local':
            current = profile.model_copy(update={'id': 'another-local'})
        elif scenario == 'ssh-endpoint-changed':
            current = profile.model_copy(update={'ssh_port': 2222})

        restored = GalleryUpscaleManager(database, output, coordinator_factory=lambda **_options: StopBeforeNetwork())
        restored.configure(current, workflow, RemoteCredentials(comfy_api_key='new-key' if scenario == 'replaced-http' else 'old-key'))
        deadline = time.monotonic() + 5
        while restored.get(queued['id'])['state'] != 'failed' and time.monotonic() < deadline:
            time.sleep(0.01)
        result = restored.get(queued['id'])
        assert result['state'] == 'failed'
        if scenario in {'same-http', 'legacy-local', 'legacy-ssh'}:
            assert reached_execution.is_set()
            assert captured[0]['remote_profile'] == profile
            if scenario == 'same-http':
                assert captured[0]['credentials'].comfy_api_key == 'old-key'
                assert persisted['httpConnection'] == {'profile_id': profile.id,
                    'session_id': profile.http_session_id, 'base_url': 'https://old.test/prefix', 'runtime_id': None}
            else:
                assert 'httpConnection' not in persisted
        else:
            assert not reached_execution.is_set(), 'recovery must reject before coordinator execution'
            assert '连接' in result['error']
        assert b'old-key' not in database.read_bytes() and b'new-key' not in database.read_bytes()
    finally:
        release.set()
        original.shutdown(cancel_queued=False, timeout=5)
        if restored:
            restored.shutdown(timeout=5)
        repo.close()


@pytest.mark.parametrize('original_kind,new_kind', [
    ('local', 'http'), ('ssh', 'http'), ('http', 'local'), ('http', 'ssh')
])
def test_gallery_switches_only_new_submissions_and_explicit_retries(tmp_path, original_kind, new_kind):
    from queue import Queue
    from anima_prompt_studio_v3.adapters.v2.gallery import build_v2_gallery_service

    database = tmp_path / 'runtime.db'
    output = tmp_path / 'outputs'
    output.mkdir()
    repo = SQLiteRepository(database)
    store = CredentialStore(MemoryCredentialBackend())

    def select(kind):
        if kind == 'http':
            return import_temporary_connection(repo, store, connection_text='https://isolated.test', api_key='http-key')
        profile = RemoteProfile(id=kind, connection_type=kind, ssh_host='localhost', ssh_user='demo',
                                auth_type='password', known_host_fingerprint='SHA256:fixture')
        repo.save_remote_profile(profile)
        repo.set_setting('last_remote_profile_id', profile.id)
        if kind == 'ssh':
            store.save_password(profile.id, profile.ssh_user, 'ssh-password')
        return profile

    first = select(original_kind)
    repo.set_setting('generation_output_root', str(output))
    repo.save_workflow_profile(WorkflowProfile(id='20_test', display_name='20_Test', bindings={}, api_workflow={
        '1': {'class_type':'LoadImage','inputs':{'image':'source.png'}},
        '2': {'class_type':'UpscaleModelLoader','inputs':{'model_name':'test.pth'}},
        '3': {'class_type':'ImageUpscaleWithModel','inputs':{'image':['1',0],'upscale_model':['2',0]}},
        '4': {'class_type':'SaveImage','inputs':{'images':['3',0]}},
    }))
    manager = build_v2_gallery_service(database, credential_store=store).process_manager
    received = Queue()
    release = Event()

    class Capture:
        def execute(self, **options):
            received.put((options['remote_profile'], options['credentials']))
            assert release.wait(10)
            raise RuntimeError('isolated gallery test')

    manager.coordinator_factory = lambda **_: Capture()

    def submit(name):
        source = output / name
        source.write_bytes(b'fixture')
        return manager.submit(source, name, {'width':16, 'height':16})

    def expect(profile):
        captured, credentials = received.get(timeout=5)
        assert captured == profile
        assert (credentials.comfy_api_key or '') == ('http-key' if profile.connection_type == 'http' else '')
        assert (credentials.password or '') == ('ssh-password' if profile.connection_type == 'ssh' else '')

    try:
        active = submit('active.png')
        expect(first)
        submit('already-queued.png')
        new = select(new_kind)
        submit('new.png')
        release.set()
        expect(first)
        expect(new)
        manager.retry(active['id'])
        expect(new)
    finally:
        release.set()
        manager.shutdown()
        repo.close()
