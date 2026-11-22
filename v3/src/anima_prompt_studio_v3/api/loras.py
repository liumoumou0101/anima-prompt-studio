"""User-supplied local assets and background preparation of the chosen environment."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from contextvars import Context
from copy import deepcopy
import hashlib
import json
import os
from threading import Lock
from typing import Literal
from uuid import uuid4

from fastapi import Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..remote.comfy_client import ComfyAPIError
from ..remote.connections import connection_factory, client_for_connection, read_runtime_identity
from ..runtime.lora_library import LoraLibrary
from ..runtime.workflow_catalog import WorkflowCatalog, fingerprint


class LoraEdit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str | None = Field(default=None, min_length=1, max_length=200)
    family: Literal['anima', 'moss', 'sdxl', 'unknown'] | None = None
    model_profiles: list[str] | None = Field(default=None, max_length=100)
    trigger_words: list[str] | None = Field(default=None, max_length=32)
    weight: float | None = Field(default=None, ge=-2, le=2)
    clip_weight: float | None = Field(default=None, ge=-2, le=2)


class LoraSyncRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sha256s: list[str] = Field(min_length=1, max_length=16)


class LoraSyncJobs:
    def __init__(self, library, manager, client=None):
        self.library, self.manager, self.client = library, manager, client
        self.jobs, self.active = {}, {}
        self.lock = Lock()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='lora-sync')

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)

    def get(self, job_id):
        with self.lock:
            return deepcopy(self.jobs[job_id])

    def _update(self, job_id, **fields):
        with self.lock:
            self.jobs[job_id].update(fields)

    def _signature(self, remote_id):
        return (fingerprint(self.manager.remote(remote_id)),
                self.manager._read('environment_epoch:' + remote_id, 0))

    def identity(self, remote_id):
        remote = self.manager.remote(remote_id)
        stamp = (fingerprint(remote), self.manager._read('environment_epoch:' + remote_id, 0))
        if not remote.enabled or not remote.connection_ready:
            raise ComfyAPIError('当前连接不可用，请重新准备 LoRA。', code='lora_connection_unavailable')
        if remote.connection_type == 'http' and remote.http_base_url.startswith('https://'):
            # Readiness checks run on focus and before submit, outside of any
            # generation preparation deadline. The shared identity guard records a restart.
            Context().run(self._probe_identity, remote)
        if self._signature(remote_id) != stamp:
            raise ComfyAPIError('当前连接已变化，请重新准备 LoRA。', code='lora_connection_changed')
        signature = hashlib.sha256(json.dumps(stamp, separators=(',', ':')).encode()).hexdigest()
        return {'signature': signature}

    def _probe_identity(self, remote):
        with connection_factory(remote) as connection:
            connection.open()
            client = client_for_connection(connection, identity_database=self.manager.database, timeout=(3, 5))
            with closing(client.session):
                # Raw HTTPS imports can also address the authenticated Colab gateway.
                if not read_runtime_identity(client, remote.model_copy(update={'http_gateway': True})):
                    raise ComfyAPIError('无法确认云端运行时，请重新准备 LoRA。', code='runtime_identity_unavailable')

    def start(self, remote_id, sha256s):
        hashes = list(dict.fromkeys(sha256s))
        for sha in hashes:
            self.library.get(sha)
        stamp = self._signature(remote_id)
        key = (remote_id, stamp, tuple(sorted(hashes)))
        with self.lock:
            if key in self.active:
                return deepcopy(self.jobs[self.active[key]])
            job_id = str(uuid4())
            job = {'id': job_id, 'state': 'queued', 'progress': 0, 'message': '正在准备 LoRA',
                   'remote_id': remote_id, 'results': [], 'error': None,
                   'environment_signature': hashlib.sha256(json.dumps(stamp, separators=(',', ':')).encode()).hexdigest()}
            self.jobs[job_id], self.active[key] = job, job_id
            # Bound retained, finished job summaries without evicting active jobs.
            finished = [i for i, value in self.jobs.items() if value['state'] in {'completed', 'failed'}]
            for old in finished[:-100]:
                self.jobs.pop(old)
            self.executor.submit(self._run, job_id, key, hashes)
            return deepcopy(job)

    def _run(self, job_id, key, hashes):
        remote_id, stamp, _ = key
        results = []
        try:
            self._update(job_id, state='running')
            if self._signature(remote_id) != stamp:
                raise ValueError('连接已发生变化，请重新准备当前环境。')
            if self.client is None:
                from ..runtime.lora_assets import LoraAssetClient
                client = LoraAssetClient(self.manager)
            else:
                client = self.client
            for index, sha in enumerate(hashes):
                def progress(value):
                    total = value.get('total_bytes') or 1
                    fraction = min(1, value.get('uploaded_bytes', 0) / total)
                    self._update(job_id, progress=round((index + fraction) / len(hashes), 3),
                                 message=value.get('message', '正在准备 LoRA'))
                if self._signature(remote_id) != stamp:
                    raise ValueError('连接已发生变化，请重新准备当前环境。')
                result = client.ensure(remote_id, sha, lambda sha=sha: self.library.local_path(sha),
                                       progress=progress, expected_signature=stamp)
                results.append(result)
                self._update(job_id, results=list(results), progress=(index + 1) / len(hashes))
            if self._signature(remote_id) != stamp:
                raise ValueError('连接已发生变化，请重新准备当前环境。')
            self._update(job_id, message='正在刷新当前环境的 LoRA 列表')
            self.manager.inspect(remote_id)
            if self._signature(remote_id) != stamp:
                raise ValueError('连接已发生变化，请重新准备当前环境。')
            snapshot = self.manager._read('workflow_capabilities:' + remote_id, {})
            info = snapshot.get('object_info', {})
            files = set()
            for kind in ('LoraLoader', 'LoraLoaderModelOnly'):
                spec = info.get(kind, {}).get('input', {}).get('required', {}).get('lora_name', [])
                if spec and isinstance(spec[0], list):
                    files.update(spec[0])
            if any(result['file_name'] not in files for result in results):
                raise ValueError('文件已保存，但 ComfyUI 尚未识别 LoRA 目录。请检查模型目录后重新准备。')
            self._update(job_id, state='completed', progress=1, message='当前环境已就绪', results=results)
        except Exception as exc:
            message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else '同步失败，请检查当前连接后重试。'
            self._update(job_id, state='failed', error=message[:500], message=message[:500], results=results)
        finally:
            with self.lock:
                self.active.pop(key, None)


def register_lora_routes(app, database, require_session, *, library_root=None, asset_client=None, manager=None):
    library = LoraLibrary(database, library_root)
    manager = manager or WorkflowCatalog(database)
    jobs = LoraSyncJobs(library, manager, asset_client)
    app.state.lora_library, app.state.lora_sync_jobs = library, jobs
    app.router.add_event_handler('shutdown', jobs.close)
    root = '/api/v3/loras'

    def guarded(call):
        try:
            return call()
        except ComfyAPIError as exc:
            changed = exc.code in {'runtime_identity_mismatch', 'runtime_identity_session_changed',
                                   'lora_connection_changed', 'lora_connection_unavailable'}
            return JSONResponse({'error': {'code': exc.code, 'message': str(exc)}}, status_code=409 if changed else 503)
        except KeyError:
            return JSONResponse({'error': {'code': 'lora_not_found', 'message': 'LoRA、连接或同步任务不存在。'}}, status_code=404)
        except ValueError as exc:
            return JSONResponse({'error': {'code': 'lora_invalid', 'message': str(exc)}}, status_code=422)
        except OSError:
            return JSONResponse({'error': {'code': 'lora_file_error', 'message': '无法读取 LoRA 目录，请检查文件和访问权限。'}}, status_code=422)

    @app.get(root, dependencies=[Depends(require_session)])
    def listing():
        return guarded(library.list)

    @app.post(root + '/scan', dependencies=[Depends(require_session)])
    def scan():
        return guarded(library.scan)

    @app.post(root + '/open-folder', dependencies=[Depends(require_session)])
    def open_folder():
        def run():
            library.root.mkdir(parents=True, exist_ok=True)
            if os.name != 'nt':
                return {'root_path': str(library.root), 'opened': False}
            os.startfile(library.root)
            return {'root_path': str(library.root), 'opened': True}
        return guarded(run)

    @app.put(root + '/{sha256}', dependencies=[Depends(require_session)])
    def edit(sha256: str, payload: LoraEdit):
        value = payload.model_dump(exclude_unset=True)
        for field in ('name', 'family', 'weight', 'trigger_words', 'model_profiles'):
            if field in value and value[field] is None:
                return JSONResponse({'error': {'code': 'lora_invalid', 'message': '该资料项不能留空。'}}, status_code=422)
        return guarded(lambda: library.update(sha256, value))

    @app.post(root + '/environments/{remote_id}/sync', dependencies=[Depends(require_session)])
    def sync(remote_id: str, payload: LoraSyncRequest):
        return guarded(lambda: jobs.start(remote_id, payload.sha256s))

    @app.get(root + '/environments/{remote_id}/identity', dependencies=[Depends(require_session)])
    def identity(remote_id: str):
        return guarded(lambda: jobs.identity(remote_id))

    @app.get(root + '/jobs/{job_id}', dependencies=[Depends(require_session)])
    def job(job_id: str):
        return guarded(lambda: jobs.get(job_id))
