"""Authenticated content-addressed LoRA cache protocol, using only local transports."""
import ast
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1]
COLAB = ROOT / 'tools' / 'colab'
KEY = 'a' * 32


def gateway_namespace():
    spec = importlib.util.spec_from_file_location('colab_updater_loras', COLAB / 'update_notebook.py')
    updater = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(updater)
    original = json.loads((COLAB / 'original.ipynb').read_text(encoding='utf-8'))
    cloud = ''.join(next(c for c in updater.update_notebook(original)['cells'] if c.get('metadata', {}).get('id') == 'moss-cloud-api')['source'])
    node = next(n for n in ast.parse(cloud).body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'GATEWAY_SOURCE' for t in n.targets))
    namespace = {'__name__': 'local_gateway_test'}
    exec(compile(ast.literal_eval(node.value), '<gateway>', 'exec'), namespace)
    return namespace


def fixture_bytes():
    header = json.dumps({'test.lora_down.weight': {'dtype': 'F32', 'shape': [1], 'data_offsets': [0, 4]}}).encode()
    return len(header).to_bytes(8, 'little') + header + b'\0' * 4


def test_gateway_asset_upload_restore_auth_and_corruption(tmp_path):
    async def scenario():
        ns = gateway_namespace()
        local, drive = tmp_path / 'runtime', tmp_path / 'drive'
        local.mkdir(); drive.mkdir()
        app = ns['create_app'](api_key=KEY, browser_session='b' * 32,
                               model_root=str(local), catalog_path=str(drive / 'model_registry.json'), runtime_id='r1')
        async with TestClient(TestServer(app)) as client:
            data = fixture_bytes(); sha = hashlib.sha256(data).hexdigest()
            path = '/_moss/loras/' + sha
            for method, suffix in [('get', ''), ('put', ''), ('post', '/restore')]:
                response = await getattr(client, method)(path + suffix, data=data if method == 'put' else None)
                assert response.status == 401
            headers = {'Authorization': 'Bearer ' + KEY}
            response = await client.get(path, headers=headers)
            assert response.status == 200
            assert await response.json() == {'sha256': sha, 'size_bytes': 0, 'cached': False, 'installed': False, 'file_name': 'anima_library/' + sha + '.safetensors'}
            response = await client.put(path, data=b'corrupt', headers=headers)
            assert response.status == 422
            assert not list(drive.rglob('*.safetensors'))
            response = await client.put(path, data=data, headers=headers)
            assert response.status == 200
            assert (await response.json())['installed']
            runtime_file = local / 'loras' / 'anima_library' / (sha + '.safetensors')
            drive_file = drive / 'models' / 'loras' / 'anima_library' / runtime_file.name
            assert runtime_file.read_bytes() == drive_file.read_bytes() == data
            response = await client.put(path, data=b'wrong-even-if-already-cached', headers=headers)
            assert response.status == 422
            assert runtime_file.read_bytes() == drive_file.read_bytes() == data
            runtime_file.unlink()
            response = await client.post(path + '/restore', headers=headers)
            assert response.status == 200 and (await response.json())['installed']
            runtime_file.write_bytes(b'corrupted-after-install')
            response = await client.get(path, headers=headers)
            status = await response.json()
            assert not status['installed'] and status['cached']
            response = await client.post(path + '/restore', headers=headers)
            assert response.status == 200 and runtime_file.read_bytes() == data
            for invalid in ['invalid', 'A' * 64, 'a.safetensors', '..%2Fescape']:
                response = await client.put('/_moss/loras/' + invalid, data=data, headers=headers)
                assert response.status in (409, 422)
    asyncio.run(scenario())


def test_interrupted_and_wrong_length_uploads_leave_no_ready_file(tmp_path):
    async def scenario():
        ns = gateway_namespace()
        store = ns['LoraGatewayStore'](tmp_path / 'runtime', tmp_path / 'drive' / 'model_registry.json')
        data = fixture_bytes(); sha = hashlib.sha256(data).hexdigest()
        class Stream:
            def __init__(self, chunks, interrupted=False):
                self.chunks, self.interrupted = chunks, interrupted
            async def iter_chunked(self, size):
                for chunk in self.chunks:
                    yield chunk
                    # A temporary prefix must never be accepted as a final asset.
                    assert not store.status(sha)['installed']
                    assert not store.status(sha)['cached']
                if self.interrupted:
                    raise ConnectionError('transfer disconnected')
        for content, length, error in [
                (Stream([data[:12]], True), len(data), ConnectionError),
                (Stream([data]), len(data) + 1, ns['LoraAssetInvalid']),
                (Stream([data[:12]]), None, ns['LoraAssetInvalid'])]:
            request = SimpleNamespace(content_length=length, headers={}, content=content)
            with pytest.raises(error):
                await store.upload(request, sha)
            assert not store.status(sha)['cached']
            assert not list(tmp_path.rglob('*.part'))
        request = SimpleNamespace(content_length=len(data), headers={}, content=Stream([data]))
        await store.upload(request, sha)
        assert store.status(sha)['installed'] and store.status(sha)['cached']
    asyncio.run(scenario())


def test_concurrent_uploads_size_cap_and_unsafe_directories(tmp_path):
    async def scenario():
        ns = gateway_namespace()
        local, drive = tmp_path / 'runtime', tmp_path / 'drive'
        app = ns['create_app'](api_key=KEY, browser_session='b' * 32,
                               model_root=str(local), catalog_path=str(drive / 'model_registry.json'))
        async with TestClient(TestServer(app)) as client:
            data = fixture_bytes(); sha = hashlib.sha256(data).hexdigest()
            path, headers = '/_moss/loras/' + sha, {'Authorization': 'Bearer ' + KEY}
            response = await client.post(path + '/restore', headers=headers)
            assert response.status == 409
            responses = await asyncio.gather(*[client.put(path, data=data, headers=headers) for _ in range(3)])
            assert all(r.status == 200 for r in responses)
            assert all(result['installed'] for result in await asyncio.gather(*[r.json() for r in responses]))
            assert not list(tmp_path.rglob('*.part'))
            ns['LORA_MAX_BYTES'] = 16
            response = await client.put(path, data=data, headers=headers)
            assert response.status == 422
            ns['LORA_MAX_BYTES'] = 4 * 1024 * 1024 * 1024
            runtime = local / 'loras' / 'anima_library' / (sha + '.safetensors')
            runtime.unlink(); runtime.mkdir()
            response = await client.get(path, headers=headers)
            assert response.status == 409
    asyncio.run(scenario())


def test_symlink_asset_cannot_read_or_write_outside_cache(tmp_path):
    async def scenario():
        ns = gateway_namespace()
        data = fixture_bytes(); sha = hashlib.sha256(data).hexdigest()
        local, drive = tmp_path / 'runtime', tmp_path / 'drive'
        directory = local / 'loras' / 'anima_library'
        directory.mkdir(parents=True)
        outside = tmp_path / 'outside.safetensors'
        outside.write_bytes(data)
        try:
            (directory / (sha + '.safetensors')).symlink_to(outside)
        except OSError:
            pytest.skip('This Windows account cannot create symbolic links')
        app = ns['create_app'](api_key=KEY, browser_session='b' * 32,
                               model_root=str(local), catalog_path=str(drive / 'model_registry.json'))
        async with TestClient(TestServer(app)) as client:
            path, headers = '/_moss/loras/' + sha, {'Authorization': 'Bearer ' + KEY}
            for method, suffix in [('get', ''), ('put', ''), ('post', '/restore')]:
                response = await getattr(client, method)(path + suffix, headers=headers,
                                                         data=data if method == 'put' else None)
                assert response.status == 409
            assert outside.read_bytes() == data
    asyncio.run(scenario())


def test_ranged_upload_resumes_committed_prefix_and_installs_only_final_hash(tmp_path):
    async def scenario():
        ns = gateway_namespace()
        ns['LORA_TRANSFER_BYTES'] = 32
        local, drive = tmp_path / 'runtime', tmp_path / 'drive'
        app = ns['create_app'](api_key=KEY, browser_session='b' * 32,
                               model_root=str(local), catalog_path=str(drive / 'model_registry.json'))
        async with TestClient(TestServer(app)) as client:
            data = fixture_bytes(); sha = hashlib.sha256(data).hexdigest()
            path, auth = '/_moss/loras/' + sha, {'Authorization': 'Bearer ' + KEY}
            for start in range(0, len(data), 32):
                chunk = data[start:start + 32]
                response = await client.put(path, data=chunk, headers={**auth,
                    'Content-Range': f'bytes {start}-{start + len(chunk) - 1}/{len(data)}'})
                assert response.status == 200
                status = await response.json()
                if start + len(chunk) < len(data):
                    assert not status['installed'] and not status['cached']
                    assert status['upload_offset'] == start + len(chunk)
                    # New gateway objects recover the committed offset from disk.
                    other = ns['LoraGatewayStore'](local, drive / 'model_registry.json')
                    assert other.status(sha)['upload_offset'] == start + len(chunk)
                else:
                    assert status['installed'] and status['cached']
            assert not list(tmp_path.rglob('*.part'))
    asyncio.run(scenario())


def test_ranged_interruption_discards_uncommitted_suffix_and_final_corruption(tmp_path):
    async def scenario():
        ns = gateway_namespace()
        data = fixture_bytes(); sha = hashlib.sha256(data).hexdigest()
        store = ns['LoraGatewayStore'](tmp_path / 'runtime', tmp_path / 'drive' / 'model_registry.json')
        class Stream:
            def __init__(self, value, interrupted=False):
                self.value, self.interrupted = value, interrupted
            async def iter_chunked(self, size):
                yield self.value
                if self.interrupted:
                    raise ConnectionError('disconnected during a chunk')
        def request(start, value, declared=None, interrupted=False):
            length = len(value) if declared is None else declared
            return SimpleNamespace(content_length=length,
                headers={'Content-Range': f'bytes {start}-{start + length - 1}/{len(data)}'},
                content=Stream(value, interrupted))
        await store.upload_range(request(0, data[:32]), sha)
        with pytest.raises(ConnectionError):
            await store.upload_range(request(32, data[32:48], 32, True), sha)
        assert store.status(sha)['upload_offset'] == 32
        restarted = ns['LoraGatewayStore'](tmp_path / 'runtime', tmp_path / 'drive' / 'model_registry.json')
        await restarted.upload_range(request(32, data[32:64]), sha)
        assert restarted.status(sha)['upload_offset'] == 64
        await restarted.upload_range(request(64, data[64:]), sha)
        assert restarted.status(sha)['installed']
        assert (tmp_path / 'runtime' / 'loras' / 'anima_library' / (sha + '.safetensors')).read_bytes() == data

        bad_sha = '1' * 64
        await restarted.upload_range(request(0, data[:32]), bad_sha)
        with pytest.raises(ns['LoraAssetInvalid']):
            await restarted.upload_range(request(32, data[32:]), bad_sha)
        assert not restarted.status(bad_sha)['cached']
        assert 'upload_offset' not in restarted.status(bad_sha)
        assert not list(tmp_path.rglob('*.part'))
    asyncio.run(scenario())
