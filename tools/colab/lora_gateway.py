"""Content-addressed LoRA routes, embedded verbatim by update_notebook.py.

Only the configured runtime and Drive model roots are writable. This module
does not fetch remote resources and relies on the enclosing gateway's auth.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from aiohttp import web


LORA_MAX_BYTES = 4 * 1024 * 1024 * 1024
LORA_CHUNK_BYTES = 1024 * 1024
LORA_TRANSFER_BYTES = 8 * 1024 * 1024


class LoraAssetConflict(ValueError):
    pass


class LoraAssetInvalid(ValueError):
    pass


class LoraGatewayStore:
    def __init__(self, model_root, catalog_path):
        self.runtime_root = Path(model_root).absolute() if model_root else None
        self.drive_root = Path(catalog_path).absolute().parent / 'models' if catalog_path else None
        self.locks = {}

    def lock(self, sha256):
        return self.locks.setdefault(sha256, asyncio.Lock())

    def path(self, root, sha256, *, create=False):
        if root is None:
            raise LoraAssetConflict('LoRA storage is not configured')
        # Do not follow a symlink at any level, including configured roots.
        for ancestor in reversed((root, *root.parents)):
            if ancestor.is_symlink() or (hasattr(ancestor, 'is_junction') and ancestor.is_junction()):
                raise LoraAssetConflict('LoRA storage cannot contain symlinks')
        directory = root / 'loras' / 'anima_library'
        for part in (root, root / 'loras', directory):
            if part.is_symlink() or (part.exists() and not part.is_dir()):
                raise LoraAssetConflict('LoRA storage must use regular directories')
            if create:
                part.mkdir(exist_ok=True, parents=True)
        target = directory / (sha256 + '.safetensors')
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise LoraAssetConflict('LoRA asset must be a regular file')
        return target

    @staticmethod
    def verified_size(path, sha256):
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
        except FileNotFoundError:
            return 0
        except OSError as exc:
            raise LoraAssetConflict('Cannot safely read LoRA asset') from exc
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= LORA_MAX_BYTES:
                return 0
            digest = hashlib.sha256()
            while chunk := stream.read(LORA_CHUNK_BYTES):
                digest.update(chunk)
            after = os.fstat(stream.fileno())
            if ((before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
                return 0
            return before.st_size if digest.hexdigest() == sha256 else 0

    def status(self, sha256):
        runtime = self.verified_size(self.path(self.runtime_root, sha256), sha256)
        cached = self.verified_size(self.path(self.drive_root, sha256), sha256)
        result = {'sha256': sha256, 'size_bytes': runtime or cached,
                'cached': bool(cached), 'installed': bool(runtime),
                'file_name': 'anima_library/' + sha256 + '.safetensors'}
        if not runtime and not cached:
            state = self.partial_state(sha256)
            if state:
                result.update(upload_offset=state['offset'], upload_total_bytes=state['total'])
        return result

    def partial_paths(self, sha256, *, create=False):
        target = self.path(self.drive_root, sha256, create=create)
        paths = (target.parent / ('.' + sha256 + '.upload.part'),
                 target.parent / ('.' + sha256 + '.upload.json'))
        for path in paths:
            if path.is_symlink() or (path.exists() and not path.is_file()):
                raise LoraAssetConflict('LoRA partial must be a regular file')
        return paths

    def partial_state(self, sha256):
        partial, metadata = self.partial_paths(sha256)
        if not metadata.exists():
            return None
        try:
            if metadata.stat().st_size > 4096:
                raise ValueError()
            state = json.loads(metadata.read_text(encoding='utf-8'))
            if (not isinstance(state, dict) or type(state.get('offset')) is not int
                    or type(state.get('total')) is not int
                    or not 0 <= state['offset'] < state['total'] <= LORA_MAX_BYTES
                    or not partial.exists() or partial.stat().st_size < state['offset']):
                raise ValueError()
            return state
        except (ValueError, OSError, UnicodeError) as exc:
            raise LoraAssetConflict('LoRA upload metadata is invalid') from exc

    def commit_offset(self, sha256, offset, total):
        _, metadata = self.partial_paths(sha256, create=True)
        fd, name = tempfile.mkstemp(prefix='.' + sha256 + '-', suffix='.json.part', dir=metadata.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as output:
                json.dump({'offset': offset, 'total': total}, output)
                output.flush()
                os.fsync(output.fileno())
            self.partial_paths(sha256)
            os.replace(temporary, metadata)
        finally:
            temporary.unlink(missing_ok=True)

    def clear_partial(self, sha256):
        for path in self.partial_paths(sha256):
            path.unlink(missing_ok=True)

    async def upload_range(self, request, sha256):
        match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', request.headers.get('Content-Range', ''))
        if match is None:
            raise LoraAssetInvalid('Invalid Content-Range')
        start, end, total = map(int, match.groups())
        length = end - start + 1
        if (not 0 <= start <= end < total <= LORA_MAX_BYTES
                or not 0 < length <= LORA_TRANSFER_BYTES or request.content_length != length
                or request.headers.get('Content-Encoding', 'identity').lower() != 'identity'):
            raise LoraAssetInvalid('Invalid range size or encoding')
        partial, _ = self.partial_paths(sha256, create=True)
        state = self.partial_state(sha256)
        if state is not None and (state['total'] != total or state['offset'] != start):
            raise LoraAssetConflict('Query the committed upload offset before retrying')
        if state is None:
            if start:
                raise LoraAssetConflict('Upload must start at offset zero')
            with partial.open('wb'):
                pass
            await asyncio.to_thread(self.commit_offset, sha256, 0, total)
        # A disconnected chunk may have written a suffix without committing it.
        # Truncate to the last atomic metadata offset before accepting a retry.
        received = 0
        with partial.open('r+b') as output:
            output.truncate(start)
            output.seek(start)
            async for chunk in request.content.iter_chunked(LORA_CHUNK_BYTES):
                received += len(chunk)
                if received > length:
                    raise LoraAssetInvalid('Chunk is larger than its range')
                await asyncio.to_thread(output.write, chunk)
            if received != length:
                raise LoraAssetInvalid('Chunk is incomplete')
            await asyncio.to_thread(output.flush)
            await asyncio.to_thread(os.fsync, output.fileno())
        if end + 1 < total:
            await asyncio.to_thread(self.commit_offset, sha256, end + 1, total)
            return
        if await asyncio.to_thread(self.verified_size, partial, sha256) != total:
            await asyncio.to_thread(self.clear_partial, sha256)
            raise LoraAssetInvalid('Final upload SHA-256 does not match')
        target = self.path(self.drive_root, sha256)
        os.replace(partial, target)
        await asyncio.to_thread(self.clear_partial, sha256)
        await asyncio.to_thread(self.install, sha256)

    def install(self, sha256):
        source = self.path(self.drive_root, sha256)
        if not self.verified_size(source, sha256):
            raise LoraAssetConflict('Verified Drive cache is not available')
        target = self.path(self.runtime_root, sha256, create=True)
        fd, name = tempfile.mkstemp(prefix='.' + sha256 + '-', suffix='.part', dir=target.parent)
        temporary = Path(name)
        try:
            digest, size = hashlib.sha256(), 0
            with os.fdopen(fd, 'wb') as output, source.open('rb') as stream:
                while chunk := stream.read(LORA_CHUNK_BYTES):
                    size += len(chunk)
                    if size > LORA_MAX_BYTES:
                        raise LoraAssetInvalid('LoRA asset exceeds the size limit')
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if not size or digest.hexdigest() != sha256:
                raise LoraAssetInvalid('Drive asset changed during restoration')
            self.path(self.runtime_root, sha256)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    async def upload(self, request, sha256):
        length = request.content_length
        if length is not None and not 0 < length <= LORA_MAX_BYTES:
            raise LoraAssetInvalid('LoRA content length is outside the size limit')
        if request.headers.get('Content-Encoding', 'identity').lower() != 'identity':
            raise LoraAssetInvalid('LoRA upload must use unencoded raw bytes')
        target = self.path(self.drive_root, sha256, create=True)
        fd, name = tempfile.mkstemp(prefix='.' + sha256 + '-', suffix='.part', dir=target.parent)
        temporary = Path(name)
        try:
            digest, size = hashlib.sha256(), 0
            with os.fdopen(fd, 'wb') as output:
                async for chunk in request.content.iter_chunked(LORA_CHUNK_BYTES):
                    size += len(chunk)
                    if size > LORA_MAX_BYTES or (length is not None and size > length):
                        raise LoraAssetInvalid('LoRA upload length exceeds the limit')
                    digest.update(chunk)
                    # Drive writes run off the event loop so status/auth remains responsive.
                    await asyncio.to_thread(output.write, chunk)
                if not size or (length is not None and size != length) or digest.hexdigest() != sha256:
                    raise LoraAssetInvalid('LoRA upload size or SHA-256 does not match')
                await asyncio.to_thread(output.flush)
                await asyncio.to_thread(os.fsync, output.fileno())
            self.path(self.drive_root, sha256)
            os.replace(temporary, target)
            await asyncio.to_thread(self.clear_partial, sha256)
            await asyncio.to_thread(self.install, sha256)
        finally:
            temporary.unlink(missing_ok=True)


def register_lora_routes(app, model_root, catalog_path):
    store = LoraGatewayStore(model_root, catalog_path)

    async def lora_asset(request):
        sha256 = request.match_info.get('sha256', '')
        if not re.fullmatch(r'[0-9a-f]{64}', sha256):
            return web.json_response({'error': 'A lowercase SHA-256 asset ID is required'}, status=422)
        restore = request.path.endswith('/restore')
        allowed = ('POST',) if restore else ('GET', 'PUT')
        if request.method not in allowed:
            return web.json_response({'error': 'Unsupported LoRA method'}, status=405,
                                     headers={'Allow': ', '.join(allowed)})
        try:
            async with store.lock(sha256):
                status = await asyncio.to_thread(store.status, sha256)
                if restore and not status['installed']:
                    await asyncio.to_thread(store.install, sha256)
                elif request.method == 'PUT':
                    # Even when cached, validate bytes supplied to PUT. Ordinary
                    # cache reuse uses GET/restore and sends no local bytes.
                    if request.headers.get('Content-Range'):
                        await store.upload_range(request, sha256)
                    else:
                        await store.upload(request, sha256)
                status = await asyncio.to_thread(store.status, sha256)
                return web.json_response(status, headers={'Cache-Control': 'no-store'})
        except LoraAssetConflict:
            return web.json_response({'error': 'LoRA cache is unavailable or has an unsafe path'}, status=409)
        except (LoraAssetInvalid, asyncio.IncompleteReadError, ConnectionError):
            return web.json_response({'error': 'LoRA upload is incomplete or failed verification'}, status=422)
        except OSError:
            return web.json_response({'error': 'LoRA storage operation failed; retry safely'}, status=503)

    app.router.add_route('*', '/_moss/loras/{sha256}', lora_asset)
    app.router.add_route('*', '/_moss/loras/{sha256}/restore', lora_asset)
    app.router.add_route('*', '/_moss/loras/{tail:.*}', lora_asset)
