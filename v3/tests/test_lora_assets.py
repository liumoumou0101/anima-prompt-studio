"""LoRA syncing reuses authenticated current ComfyUI connections."""
import hashlib
from pathlib import Path

import pytest

from anima_prompt_studio_v3.remote.comfy_client import ComfyUIClient, ComfyAPIError
from anima_prompt_studio_v3.remote.connections import HttpComfyConnection, client_for_connection
from anima_prompt_studio_v3.runtime.lora_assets import LoraAssetClient
from anima_prompt_studio_v3.remote.preparation_budget import DirectPreparationBudget
from anima_prompt_studio_v3.runtime.workflow_catalog import WorkflowCatalog
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
from test_http_runtime_identity import profile, Response

DATA = b'fixture-file-bytes'
SHA = hashlib.sha256(DATA).hexdigest()


class AssetSession:
    def __init__(self):
        self.cached = self.installed = False
        self.identity = 'runtime-1'
        self.calls = []
        self.options = []
        self.fail_once = False
        self.on_upload = None
    def status(self):
        return {'sha256': SHA, 'size_bytes': len(DATA) if self.cached or self.installed else 0,
                'cached': self.cached, 'installed': self.installed,
                'file_name': 'anima_library/' + SHA + '.safetensors'}
    def get(self, url, **kwargs):
        self.calls.append(('get', url)); self.options.append(kwargs)
        return Response({'runtime_id': self.identity} if url.endswith('/_moss/info') else self.status())
    def post(self, url, **kwargs):
        self.calls.append(('post', url)); self.options.append(kwargs)
        assert url.endswith('/restore') and self.cached
        self.installed = True
        return Response(self.status())
    def put(self, url, **kwargs):
        self.calls.append(('put', url)); self.options.append(kwargs)
        stream = kwargs['data']
        received = b''
        while chunk := stream.read(3):
            received += chunk
        assert received == DATA
        if self.on_upload:
            self.on_upload()
        if self.fail_once:
            self.fail_once = False
            raise ConnectionError('interrupted')
        self.cached = self.installed = True
        return Response(self.status())
    def close(self): pass


def setup_client(tmp_path, monkeypatch):
    from anima_prompt_studio_v3.runtime import lora_assets
    manager = WorkflowCatalog(tmp_path / 'runtime.db')
    remote = profile()
    repo = SQLiteRepository(manager.database)
    repo.save_remote_profile(remote)
    repo.close()
    session = AssetSession()
    def factory(connection, **kwargs):
        connection.api_key = 'secret-never-log'
        return client_for_connection(connection, session=session, **kwargs)
    monkeypatch.setattr(lora_assets, 'client_for_connection', factory)
    monkeypatch.setattr(HttpComfyConnection, 'open', lambda self, *args: self)
    source = tmp_path / 'test.safetensors'
    source.write_bytes(DATA)
    return LoraAssetClient(manager), manager, remote, session, source


def test_upload_then_zero_upload_and_drive_restore(tmp_path, monkeypatch):
    assets, manager, remote, session, source = setup_client(tmp_path, monkeypatch)
    progress = []
    with DirectPreparationBudget(seconds=0):
        first = assets.ensure(remote.id, SHA, source, progress.append)
    assert first['uploaded_bytes'] == len(DATA) and first['installed'] and not first['restored']
    assert progress[-1]['phase'] == 'completed'
    source.unlink()
    repeat = assets.ensure(remote.id, SHA, None)
    assert repeat['uploaded_bytes'] == 0 and repeat['installed'] and not repeat['restored']
    session.installed = False
    restored = assets.ensure(remote.id, SHA, None)
    assert restored['uploaded_bytes'] == 0 and restored['restored'] and restored['installed']
    assert len([c for c in session.calls if c[0] == 'put']) == 1
    assert all(o['headers']['Authorization'] == 'Bearer secret-never-log' for o in session.options)
    assert all(o['allow_redirects'] is False and o['verify'] for o in session.options)


def test_retry_and_corrupt_local_source(tmp_path, monkeypatch):
    assets, manager, remote, session, source = setup_client(tmp_path, monkeypatch)
    session.fail_once = True
    result = assets.ensure(remote.id, SHA, source)
    assert result['installed'] and result['uploaded_bytes'] == 2 * len(DATA)
    session.installed = session.cached = False
    source.write_bytes(b'changed')
    with pytest.raises(ComfyAPIError) as error:
        assets.ensure(remote.id, SHA, source)
    assert error.value.code == 'lora_source_changed'
    assert len([c for c in session.calls if c[0] == 'put']) == 2


def test_runtime_or_connection_changed_cannot_report_ready(tmp_path, monkeypatch):
    assets, manager, remote, session, source = setup_client(tmp_path, monkeypatch)
    session.on_upload = lambda: setattr(session, 'identity', 'runtime-2')
    with pytest.raises(ComfyAPIError) as error:
        assets.ensure(remote.id, SHA, source)
    assert error.value.code.startswith('runtime_identity_')


def test_reject_non_gateway_sync_without_affecting_other_paths(tmp_path, monkeypatch):
    assets, manager, remote, session, source = setup_client(tmp_path, monkeypatch)
    changed = remote.model_copy(update={'connection_type': 'ssh', 'ssh_host': 'example.test', 'ssh_user': 'user'})
    monkeypatch.setattr(manager, 'remote', lambda _remote_id: changed)
    with pytest.raises(ComfyAPIError) as error:
        assets.ensure(remote.id, SHA, source)
    assert error.value.code == 'lora_sync_unsupported'
    assert not session.calls


def test_connection_change_after_upload_cannot_publish_old_ready(tmp_path, monkeypatch):
    assets, manager, remote, session, source = setup_client(tmp_path, monkeypatch)
    session.on_upload = lambda: manager._write('environment_epoch:' + remote.id, 1)
    with pytest.raises(ComfyAPIError) as error:
        assets.ensure(remote.id, SHA, source)
    assert error.value.code == 'lora_connection_changed'


def test_concurrent_jobs_reuse_one_verified_upload(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    assets, manager, remote, session, source = setup_client(tmp_path, monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _index: assets.ensure(remote.id, SHA, source), range(2)))
    assert all(result['installed'] for result in results)
    assert sum(result['uploaded_bytes'] for result in results) == len(DATA)
    assert len([c for c in session.calls if c[0] == 'put']) == 1


def test_connection_changed_before_open_cannot_use_previous_url(tmp_path, monkeypatch):
    assets, manager, remote, session, source = setup_client(tmp_path, monkeypatch)
    changed = remote.model_copy(update={'http_base_url': 'https://new.example.test'})
    calls = []
    def current(_remote_id):
        calls.append(True)
        return remote if len(calls) == 1 else changed
    monkeypatch.setattr(manager, 'remote', current)
    with pytest.raises(ComfyAPIError) as error:
        assets.ensure(remote.id, SHA, source)
    assert error.value.code == 'lora_connection_changed'
    assert not session.calls


def test_queued_signature_and_lazy_source(tmp_path, monkeypatch):
    from anima_prompt_studio_v3.runtime.workflow_catalog import fingerprint
    assets, manager, remote, session, source = setup_client(tmp_path, monkeypatch)
    def missing_source():
        raise AssertionError('A cache hit must not resolve or validate the local source')
    session.installed = session.cached = True
    assert assets.ensure(remote.id, SHA, missing_source)['uploaded_bytes'] == 0
    session.calls.clear()
    with pytest.raises(ComfyAPIError) as error:
        assets.ensure(remote.id, SHA, missing_source, expected_signature=(fingerprint(remote), 123))
    assert error.value.code == 'lora_connection_changed'
    assert not session.calls


def test_32mb_ranged_transfer_resumes_exact_acknowledged_offset(tmp_path, monkeypatch):
    import re
    from anima_prompt_studio_v3.runtime import lora_assets
    assets, manager, remote, session, source = setup_client(tmp_path, monkeypatch)
    monkeypatch.setattr(lora_assets, 'LORA_TRANSFER_BYTES', 1024 * 1024)
    data = bytes(range(256)) * (32 * 1024 * 1024 // 256)
    sha = hashlib.sha256(data).hexdigest()
    source.write_bytes(data)
    committed, calls, received, fail = 0, [], bytearray(), True
    def status():
        result = {'sha256': sha, 'size_bytes': len(data) if session.installed else 0,
                  'cached': session.installed, 'installed': session.installed,
                  'file_name': 'anima_library/' + sha + '.safetensors'}
        if committed and not session.installed:
            result.update(upload_offset=committed, upload_total_bytes=len(data))
        return result
    def put(url, **kwargs):
        nonlocal committed, fail
        assert kwargs['headers']['Authorization'] == 'Bearer secret-never-log'
        assert kwargs['timeout'] == (300, 600)
        match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', kwargs['headers']['Content-Range'])
        start, end, total = map(int, match.groups())
        assert start == committed and total == len(data) and end - start + 1 <= 1024 * 1024
        chunk = bytearray()
        while block := kwargs['data'].read(65536):
            chunk.extend(block)
        assert len(chunk) == end - start + 1
        calls.append(start); received.extend(chunk); committed = end + 1
        if fail and committed == 3 * 1024 * 1024:
            fail = False
            raise ConnectionError('Server committed the chunk, but its acknowledgement was lost')
        if committed == total:
            assert hashlib.sha256(received).hexdigest() == sha
            session.installed = session.cached = True
        return Response(status())
    monkeypatch.setattr(session, 'status', status)
    monkeypatch.setattr(session, 'put', put)
    result = assets.ensure(remote.id, sha, source)
    assert result['installed'] and result['uploaded_bytes'] == len(data)
    assert bytes(received) == data
    assert calls == list(range(0, len(data), 1024 * 1024))


def test_requests_http_transport_sends_exact_chunks_from_nonzero_source_offsets(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    import requests
    from anima_prompt_studio_v3.runtime.lora_assets import _ProgressReader
    data = bytes(range(256)) * (10 * 1024 * 1024 // 256)
    source = tmp_path / 'large.safetensors'
    source.write_bytes(data)
    received = []
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def do_PUT(self):
            length = int(self.headers['Content-Length'])
            body = self.rfile.read(length)
            received.append((self.path, length, self.headers.get('Content-Range'), body))
            self.send_response(200)
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b'{}')
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    count = 2 * 1024 * 1024
    starts = [1024 * 1024, 3 * 1024 * 1024]
    try:
        with requests.Session() as session, source.open('rb') as stream:
            for index, start in enumerate(starts):
                stream.seek(start)
                reader = _ProgressReader(stream, count, None)
                response = session.put(f'http://127.0.0.1:{server.server_port}/{index}',
                    data=reader, headers={'Content-Range': f'bytes {start}-{start + count - 1}/{len(data)}'},
                    timeout=(3, 3))
                assert response.status_code == 200
                assert reader.sent == count and reader.tell() == count
                assert reader.read(65536) == b''
        assert len(received) == 2
        for index, start in enumerate(starts):
            path, length, content_range, body = received[index]
            assert path == '/' + str(index)
            assert length == count
            assert content_range == f'bytes {start}-{start + count - 1}/{len(data)}'
            assert body == data[start:start + count]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_transient_failures_on_separate_chunks_resume_without_duplicate_bytes(tmp_path, monkeypatch):
    import re
    from anima_prompt_studio_v3.runtime import lora_assets
    assets, manager, remote, session, source = setup_client(tmp_path, monkeypatch)
    monkeypatch.setattr(lora_assets, 'LORA_TRANSFER_BYTES', 4)
    committed, received, starts = 0, bytearray(), []
    failures = {4, 12}
    def status():
        result = {'sha256': SHA, 'size_bytes': len(DATA) if session.installed else 0,
                  'cached': session.installed, 'installed': session.installed,
                  'file_name': 'anima_library/' + SHA + '.safetensors'}
        if committed and not session.installed:
            result.update(upload_offset=committed, upload_total_bytes=len(DATA))
        return result
    def put(url, **kwargs):
        nonlocal committed
        match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', kwargs['headers']['Content-Range'])
        start, end, total = map(int, match.groups())
        assert start == committed
        chunk = kwargs['data'].read()
        starts.append(start); received.extend(chunk); committed = end + 1
        if start in failures:
            failures.remove(start)
            raise ConnectionError('Lost chunk acknowledgement')
        if committed == total:
            session.installed = session.cached = True
        return Response(status())
    monkeypatch.setattr(session, 'status', status)
    monkeypatch.setattr(session, 'put', put)
    result = assets.ensure(remote.id, SHA, source)
    assert result['installed'] and result['uploaded_bytes'] == len(DATA)
    assert bytes(received) == DATA
    assert starts == list(range(0, len(DATA), 4))
    assert not failures


@pytest.mark.parametrize('initial_offset', [0, 4])
def test_repeated_transient_failure_stops_after_three_consecutive_retries(tmp_path, monkeypatch, initial_offset):
    assets, manager, remote, session, source = setup_client(tmp_path, monkeypatch)
    attempts = []
    if initial_offset:
        original_status = session.status
        monkeypatch.setattr(session, 'status', lambda: {**original_status(),
            'upload_offset': initial_offset, 'upload_total_bytes': len(DATA)})
    def put(url, **kwargs):
        attempts.append(True)
        raise ConnectionError('Always disconnected before acknowledgement')
    monkeypatch.setattr(session, 'put', put)
    with pytest.raises(ComfyAPIError) as error:
        assets.ensure(remote.id, SHA, source)
    assert error.value.code == 'connection_error'
    assert len(attempts) == 4  # Original attempt plus three bounded retries.


def test_progressing_transfer_still_stops_at_twelve_total_retries(tmp_path, monkeypatch):
    import re
    from anima_prompt_studio_v3.runtime import lora_assets
    assets, manager, remote, session, source = setup_client(tmp_path, monkeypatch)
    monkeypatch.setattr(lora_assets, 'LORA_TRANSFER_BYTES', 1)
    committed, attempts, failed_offsets = 0, [], set()
    def status():
        result = {'sha256': SHA, 'size_bytes': 0, 'cached': False, 'installed': False,
                  'file_name': 'anima_library/' + SHA + '.safetensors'}
        if committed:
            result.update(upload_offset=committed, upload_total_bytes=len(DATA))
        return result
    def put(url, **kwargs):
        nonlocal committed
        match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', kwargs['headers']['Content-Range'])
        start, end, _ = map(int, match.groups())
        assert start == committed
        attempts.append(start)
        if start not in failed_offsets:
            failed_offsets.add(start)
            raise ConnectionError('One transient failure at every new chunk')
        assert kwargs['data'].read() == DATA[start:end + 1]
        committed = end + 1
        return Response(status())
    monkeypatch.setattr(session, 'status', status)
    monkeypatch.setattr(session, 'put', put)
    with pytest.raises(ComfyAPIError) as error:
        assets.ensure(remote.id, SHA, source)
    assert error.value.code == 'connection_error'
    assert committed == lora_assets.MAX_TOTAL_RETRIES == 12
    assert len(attempts) == 25


def test_background_upload_gets_long_socket_write_timeout_independent_of_generation_budget(tmp_path, monkeypatch):
    assets, manager, remote, session, source = setup_client(tmp_path, monkeypatch)
    with DirectPreparationBudget(seconds=0):
        assert assets.ensure(remote.id, SHA, source)['installed']
    put_timeouts = [options['timeout'] for (method, _url), options in zip(session.calls, session.options)
                    if method == 'put']
    get_timeouts = [options['timeout'] for (method, _url), options in zip(session.calls, session.options)
                    if method == 'get']
    # requests/urllib3 keeps the connect/socket timeout during body writes and
    # switches to the read timeout only after the whole body has been sent.
    assert put_timeouts == [(300, 600)]
    assert get_timeouts and all(value == (10, 300) for value in get_timeouts)
