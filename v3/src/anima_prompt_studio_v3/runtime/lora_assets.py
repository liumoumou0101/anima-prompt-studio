"""Prepare selected content-addressed LoRAs on the current HTTPS connection."""
from contextvars import Context
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from threading import Lock

from anima_prompt_studio.domain.execution_models import RemoteCredentials
from ..remote.comfy_client import ComfyAPIError
from ..remote.connections import connection_factory, client_for_connection, read_runtime_identity
from .workflow_catalog import fingerprint


MAX_LORA_BYTES = 4 * 1024 * 1024 * 1024
LORA_TRANSFER_BYTES = 8 * 1024 * 1024
MAX_CONSECUTIVE_RETRIES = 3
MAX_TOTAL_RETRIES = 12
LORA_STATUS_TIMEOUT = (10, 300)
# requests/urllib3 applies its connect/socket timeout while sending a body;
# the separate read bound only starts after sending. Background asset writes
# need a longer socket bound than small generation/control requests.
LORA_UPLOAD_TIMEOUT = (300, 600)
_locks_guard = Lock()
_locks = {}


class _ProgressReader:
    def __init__(self, stream, size, progress):
        self.stream, self.size, self.progress = stream, size, progress
        self.sent = 0

    def __len__(self):
        return self.size

    def read(self, size=-1):
        remaining = self.size - self.sent
        chunk = self.stream.read(remaining if size is None or size < 0 else min(size, remaining))
        self.sent += len(chunk)
        if chunk and self.progress:
            self.progress({'phase': 'uploading', 'uploaded_bytes': self.sent,
                           'total_bytes': self.size, 'message': '正在上传 LoRA 并写入云盘缓存'})
        return chunk

    def tell(self):
        return self.sent


class LoraAssetClient:
    """No stored URL or credential: each operation opens the manager's live profile.

    Progress callbacks receive phase/uploaded_bytes/total_bytes/message. These
    explicit preparation jobs have their own transfer timeout, independent of a
    direct generation request's short pre-acceptance budget.
    """
    def __init__(self, manager):
        self.manager = manager

    def status(self, remote_id, sha256):
        return Context().run(self._operate, remote_id, sha256, None, None, False)

    def ensure(self, remote_id, sha256, local_path, progress=None, *, expected_signature=None):
        return Context().run(self._operate, remote_id, sha256, local_path, progress, True, expected_signature)

    def _signature(self, remote_id):
        return (fingerprint(self.manager.remote(remote_id)),
                self.manager._read('environment_epoch:' + remote_id, 0))

    def _guard(self, remote_id, signature):
        if self._signature(remote_id) != signature:
            raise ComfyAPIError('连接或运行时已变化，请重新准备当前环境。', code='lora_connection_changed')

    @staticmethod
    def _validate_status(value, sha256):
        expected = 'anima_library/' + sha256 + '.safetensors'
        if (not isinstance(value, dict) or value.get('sha256') != sha256 or value.get('file_name') != expected
                or type(value.get('size_bytes')) is not int or not 0 <= value['size_bytes'] <= MAX_LORA_BYTES
                or type(value.get('cached')) is not bool or type(value.get('installed')) is not bool
                or (value['cached'] or value['installed']) != (value['size_bytes'] > 0)):
            raise ComfyAPIError('云端返回了无效的 LoRA 状态。', code='lora_invalid_response')
        result = {key: value[key] for key in ('sha256', 'size_bytes', 'cached', 'installed', 'file_name')}
        if 'upload_offset' in value or 'upload_total_bytes' in value:
            offset, total = value.get('upload_offset'), value.get('upload_total_bytes')
            if (type(offset) is not int or type(total) is not int
                    or not 0 <= offset < total <= MAX_LORA_BYTES):
                raise ComfyAPIError('云端返回了无效的 LoRA 续传状态。', code='lora_invalid_response')
            result.update(upload_offset=offset, upload_total_bytes=total)
        return result

    def _call(self, client, remote_id, signature, sha256, method='get', *, data=None, headers=None):
        self._guard(remote_id, signature)
        path = '/_moss/loras/' + sha256 + ('/restore' if method == 'post' else '')
        response = None
        try:
            response = client._request(method, client.base_url + path, data=data,
                                       headers=headers or {},
                                       timeout=LORA_UPLOAD_TIMEOUT if method == 'put' else LORA_STATUS_TIMEOUT,
                                       stream=True)
            if response.status_code in (404, 405):
                raise ComfyAPIError('当前服务未提供 LoRA 缓存接口，请更新 Colab 网关。', code='lora_sync_unsupported')
            if response.status_code == 409:
                raise ComfyAPIError('云端 LoRA 缓存不可用，请检查笔记本存储后重试。', code='lora_cache_unavailable')
            if response.status_code == 422:
                raise ComfyAPIError('LoRA 字节、长度或摘要校验失败，请重新扫描本地文件。', code='lora_verification_failed')
            if response.status_code >= 500:
                raise ComfyAPIError('LoRA 云端服务暂时不可用，请稍后重试。', code='connection_error')
            client._raise_for_status(response, path)
            chunks, length = [], 0
            for chunk in response.iter_content(chunk_size=16384):
                length += len(chunk)
                if length > 65536:
                    raise ComfyAPIError('云端 LoRA 状态超过大小限制。', code='lora_invalid_response')
                chunks.append(chunk)
            value = self._validate_status(json.loads(b''.join(chunks)), sha256)
            # The URL may have started forwarding to another runtime while a
            # long upload was in progress. Never publish its old ready result.
            if not read_runtime_identity(client, client._runtime_profile):
                raise ComfyAPIError('无法确认当前运行时，请更新网关并重新导入连接。', code='runtime_identity_unavailable')
            self._guard(remote_id, signature)
            return value
        except ComfyAPIError:
            raise
        except Exception:
            raise ComfyAPIError('LoRA 同步连接中断，请检查当前连接后重试。', code='connection_error') from None
        finally:
            if response is not None:
                response.close()

    @staticmethod
    def _source(local_path, sha256):
        if callable(local_path):
            local_path = local_path()
        if local_path is None:
            raise ComfyAPIError('当前环境和云盘均无此资源，请恢复本地文件后重新扫描。', code='lora_source_missing')
        path = Path(local_path).expanduser().absolute()
        if any(part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction())
               for part in (path, *path.parents)):
            raise ComfyAPIError('LoRA 上传源不能是链接文件或链接目录。', code='lora_source_changed')
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
            stream = os.fdopen(fd, 'rb')
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_LORA_BYTES:
                stream.close()
                raise ComfyAPIError('LoRA 文件为空、过大或不是普通文件。', code='lora_source_changed')
            digest = hashlib.sha256()
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
            if digest.hexdigest() != sha256:
                stream.close()
                raise ComfyAPIError('本地 LoRA 文件内容已变化，请重新扫描。', code='lora_source_changed')
            stream.seek(0)
            return stream, info.st_size
        except ComfyAPIError:
            raise
        except OSError:
            raise ComfyAPIError('无法读取本地 LoRA 文件，请恢复文件并重新扫描。', code='lora_source_missing') from None

    def _operate(self, remote_id, sha256, local_path, progress, ensure, expected_signature=None):
        if not isinstance(sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', sha256):
            raise ValueError('需要有效的小写 SHA-256 资源标识。')
        remote = self.manager.remote(remote_id)
        if remote.connection_type != 'http' or not remote.http_base_url.startswith('https://'):
            raise ComfyAPIError('自动 LoRA 同步仅支持 HTTPS Colab 连接；此环境可继续使用已安装文件。', code='lora_sync_unsupported')
        if not remote.enabled or not remote.connection_ready:
            raise ComfyAPIError('请先启用并准备当前连接。', code='lora_connection_unavailable')
        signature = (fingerprint(remote), self.manager._read('environment_epoch:' + remote_id, 0))
        if expected_signature is not None and tuple(expected_signature) != signature:
            raise ComfyAPIError('同步任务创建后连接已变化，请为当前环境重新准备。', code='lora_connection_changed')
        key = (str(self.manager.database), remote_id, signature, sha256)
        with _locks_guard:
            lock = _locks.setdefault(key, Lock())
        with lock:
            self._guard(remote_id, signature)
            connection = connection_factory(remote)
            client = None
            uploaded, restored = 0, False
            consecutive_retries = total_retries = acknowledged_offset = 0
            def acknowledge(value):
                nonlocal consecutive_retries, acknowledged_offset
                offset = value.get('upload_offset', 0)
                if value['installed'] or offset > acknowledged_offset:
                    acknowledged_offset = max(acknowledged_offset, offset)
                    consecutive_retries = 0
            try:
                connection.open(RemoteCredentials())
                client = client_for_connection(connection, identity_database=self.manager.database, timeout=LORA_STATUS_TIMEOUT)
                # A plain imported URL may still point to this gateway. Require
                # its live identity for asset jobs, including that first use.
                client._runtime_profile = remote.model_copy(update={'http_gateway': True})
                while True:
                    try:
                        if progress:
                            progress({'phase': 'checking', 'uploaded_bytes': uploaded, 'total_bytes': 0,
                                      'message': '正在检查当前运行时和云盘缓存'})
                        result = self._call(client, remote_id, signature, sha256)
                        acknowledge(result)
                        if ensure and not result['installed']:
                            if result['cached']:
                                if progress:
                                    progress({'phase': 'restoring', 'uploaded_bytes': uploaded,
                                              'total_bytes': result['size_bytes'], 'message': '正在从云盘恢复 LoRA'})
                                result = self._call(client, remote_id, signature, sha256, 'post')
                                restored = True
                                acknowledge(result)
                            else:
                                stream, size = self._source(local_path, sha256)
                                with stream:
                                    offset = result.get('upload_offset', 0)
                                    if result.get('upload_total_bytes', size) != size:
                                        raise ComfyAPIError('云端续传长度与本地文件不一致，请重新扫描。', code='lora_verification_failed')
                                    ranged = size > LORA_TRANSFER_BYTES or 'upload_offset' in result
                                    while offset < size:
                                        stream.seek(offset)
                                        count = min(LORA_TRANSFER_BYTES, size - offset) if ranged else size
                                        def chunk_progress(value, uploaded_before=uploaded):
                                            if progress:
                                                progress({**value, 'uploaded_bytes': uploaded_before + value['uploaded_bytes'],
                                                          'total_bytes': size})
                                        reader = _ProgressReader(stream, count, chunk_progress if progress else None)
                                        headers = {'Content-Range': f'bytes {offset}-{offset + count - 1}/{size}'} if ranged else {}
                                        try:
                                            result = self._call(client, remote_id, signature, sha256, 'put',
                                                                data=reader, headers=headers)
                                        finally:
                                            uploaded += reader.sent
                                        offset += count
                                        if offset < size and result.get('upload_offset') != offset:
                                            raise ComfyAPIError('云端未确认 LoRA 分段传输进度，请重试。', code='lora_invalid_response')
                                        acknowledge(result)
                            if not result['installed']:
                                raise ComfyAPIError('云端尚未安装完成此 LoRA，请重试。', code='lora_not_installed')
                        self._guard(remote_id, signature)
                        if progress:
                            progress({'phase': 'completed', 'uploaded_bytes': uploaded,
                                      'total_bytes': result['size_bytes'], 'message': 'LoRA 已准备完成'})
                        return {**result, 'uploaded_bytes': uploaded, 'restored': restored} if ensure else result
                    except ComfyAPIError as exc:
                        if (exc.code not in {'connection_error', 'timeout'}
                                or consecutive_retries >= MAX_CONSECUTIVE_RETRIES
                                or total_retries >= MAX_TOTAL_RETRIES):
                            raise
                        consecutive_retries += 1
                        total_retries += 1
                        # Query verified live status before retrying a possibly
                        # completed transfer. Only a confirmed advancing offset
                        # or a ready installation replenishes consecutive retries;
                        # the overall cap still bounds a long, flaky transfer.
            finally:
                if client is not None:
                    client.session.close()
                connection.close()
