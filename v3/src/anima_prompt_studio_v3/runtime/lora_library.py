"""Local, content-addressed LoRA assets supplied by the user."""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import struct
import sys
from threading import Lock, RLock

from ..core.lora_resolution import ResourceUnavailable

KEY = 'lora_library_v1'
SHA = re.compile(r'^[a-f0-9]{64}$')
MAX_BYTES = 4 * 1024 ** 3
DTYPE_BYTES = {'BOOL': 1, 'I8': 1, 'U8': 1, 'I16': 2, 'U16': 2, 'I32': 4, 'U32': 4,
               'I64': 8, 'U64': 8, 'F16': 2, 'BF16': 2, 'F32': 4, 'F64': 8,
               'F8_E4M3': 1, 'F8_E5M2': 1, 'F8_E8M0': 1}
_LOCK = RLock()
EDITABLE = {'name', 'family', 'model_profiles', 'trigger_words', 'weight', 'clip_weight'}


def default_lora_root():
    if os.environ.get('ANIMA_LORA_DIR'):
        return Path(os.environ['ANIMA_LORA_DIR']).absolute()
    base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[4]
    return base / 'loras'


def remote_file_name(sha256):
    if not SHA.fullmatch(sha256):
        raise ValueError('LoRA 文件标识无效。')
    return f'anima_library/{sha256}.safetensors'


def file_digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_tensor_file(path):
    """Read only the bounded safetensors header and check payload offsets."""
    size = path.stat().st_size
    if size < 10 or size > MAX_BYTES:
        raise ValueError('文件大小无效，最大支持 4 GiB。')
    with path.open('rb') as stream:
        length = struct.unpack('<Q', stream.read(8))[0]
        if not 2 <= length <= min(16 * 1024 ** 2, size - 8):
            raise ValueError('文件头不完整，请等文件复制完成后刷新。')
        header = json.loads(stream.read(length))
    if not isinstance(header, dict):
        raise ValueError('不是有效的 safetensors 文件。')
    intervals = []
    lora_keys = False
    for key, tensor in header.items():
        if key == '__metadata__':
            continue
        if not isinstance(tensor, dict) or not isinstance(tensor.get('dtype'), str):
            raise ValueError('模型张量信息无效。')
        shape, offsets = tensor.get('shape'), tensor.get('data_offsets')
        if (not isinstance(shape, list) or any(type(n) is not int or n < 0 for n in shape)
                or not isinstance(offsets, list) or len(offsets) != 2
                or any(type(n) is not int for n in offsets)
                or not 0 <= offsets[0] <= offsets[1] <= size - 8 - length):
            raise ValueError('模型数据不完整或偏移无效。')
        width = DTYPE_BYTES.get(tensor['dtype'])
        if width is None:
            raise ValueError('LoRA 使用了暂不支持的数据类型。')
        if offsets[1] - offsets[0] != math.prod(shape) * width:
            raise ValueError('LoRA 张量形状与实际数据长度不符。')
        intervals.append(tuple(offsets))
        lora_keys = lora_keys or any(word in key.lower() for word in ('lora_', '.lora', 'lokr_', 'hada_'))
    end = 0
    for start, stop in sorted(intervals):
        if start != end:
            raise ValueError('模型数据存在缺口或重复区间。')
        end = stop
    if not intervals or end != size - 8 - length or not lora_keys:
        raise ValueError('文件不完整，或没有识别到 LoRA 权重。')


class LoraLibrary:
    def __init__(self, database, root=None):
        self.database = Path(database)
        self.root = Path(root) if root is not None else default_lora_root()
        self._scan_lock = Lock()

    @contextmanager
    def _connection(self):
        self.database.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.database, timeout=15)
        try:
            conn.execute('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value_json TEXT NOT NULL)')
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _read(conn):
        row = conn.execute('SELECT value_json FROM settings WHERE key=?', (KEY,)).fetchone()
        return json.loads(row[0]) if row else {}

    def _records(self):
        with self._connection() as conn:
            return self._read(conn)

    def _save(self, mutate):
        with _LOCK, self._connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            records = self._read(conn)
            result = mutate(records)
            conn.execute('INSERT INTO settings(key,value_json) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json',
                         (KEY, json.dumps(records, ensure_ascii=False)))
            conn.commit()
            return result

    def _safe_path(self, relative):
        path = self.root / relative
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError('文件路径超出 LoRA 目录。')
        for part in (path, *path.parents):
            if part.is_symlink() or part.is_junction():
                raise ValueError('LoRA 目录内不支持链接或目录联接。')
            if part == self.root:
                break
        return path

    def list(self):
        return {'root_path': str(self.root), 'items': sorted(self._records().values(), key=lambda i: (i['name'].casefold(), i['sha256'])),
                'errors': []}

    def get(self, sha256):
        remote_file_name(sha256)
        item = self._records().get(sha256)
        if item is None:
            raise KeyError(sha256)
        return item

    def scan(self):
        with self._scan_lock:
            return self._scan()

    def _scan(self):
        self.root.mkdir(parents=True, exist_ok=True)
        assets, errors = {}, []
        for path in sorted(self.root.rglob('*.safetensors')):
            try:
                relative = path.relative_to(self.root).as_posix()
                self._safe_path(relative)
                before = path.stat()
                validate_tensor_file(path)
                sha = file_digest(path)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError('文件仍在复制或被修改，请稍后刷新。')
                assets.setdefault(sha, {'relative_path': relative, 'size_bytes': after.st_size,
                                       'suggested_name': path.stem})
            except (OSError, ValueError, TypeError, struct.error) as exc:
                errors.append({'path': str(path.relative_to(self.root)), 'error': str(exc)[:400]})

        def merge(records):
            for record in records.values():
                record['present'] = False
            for sha, asset in assets.items():
                record = records.setdefault(sha, {'id': sha, 'sha256': sha, 'name': asset['suggested_name'],
                    'family': 'unknown', 'model_profiles': [], 'trigger_words': [], 'weight': 1.0, 'clip_weight': None})
                record.update({k: v for k, v in asset.items() if k != 'suggested_name'})
                record.update(file_name=remote_file_name(sha), present=True, valid=True, error='')
        self._save(merge)
        return {**self.list(), 'errors': errors}

    def update(self, sha256, payload):
        payload = dict(payload)
        remote_file_name(sha256)
        if set(payload) - EDITABLE:
            raise ValueError('只允许编辑 LoRA 资料。')
        if payload.get('family', 'unknown') not in {'anima', 'moss', 'sdxl', 'unknown'}:
            raise ValueError('模型系列无效。')
        for field in ('weight', 'clip_weight'):
            value = payload.get(field)
            if value is not None and (type(value) not in (int, float) or not -2 <= value <= 2):
                raise ValueError('LoRA 权重须在 -2 至 2 之间。')
        for field, limit in (('trigger_words', 32), ('model_profiles', 100)):
            if field in payload and (not isinstance(payload[field], list) or len(payload[field]) > limit
                    or any(not isinstance(v, str) or len(v) > 200 for v in payload[field])):
                raise ValueError('LoRA 资料格式无效。')
            if field in payload:
                payload[field] = list(dict.fromkeys(value.strip() for value in payload[field] if value.strip()))
        if 'name' in payload and (not isinstance(payload['name'], str) or not 1 <= len(payload['name'].strip()) <= 200):
            raise ValueError('名称须包含 1 至 200 个字符。')
        if 'name' in payload:
            payload['name'] = payload['name'].strip()
        def change(records):
            if sha256 not in records:
                raise KeyError(sha256)
            records[sha256].update(payload)
            return dict(records[sha256])
        return self._save(change)

    def local_path(self, sha256):
        record = self.get(sha256)
        if not record['present']:
            return None
        path = self._safe_path(record['relative_path'])
        if not path.is_file():
            return None
        if file_digest(path) != sha256:
            raise ValueError('本地 LoRA 文件已改变，请刷新资料库后重试。')
        return path


def validate_library_resources(database, model_profile, resources):
    """Validate newly requested library selections; frozen jobs use their saved graph."""
    library = LoraLibrary(database)
    family = ('moss' if model_profile.startswith('moss') else
              'anima' if 'anima' in model_profile.lower() else
              'sdxl' if any(word in model_profile.lower() for word in ('sdxl', 'illustrious')) else None)
    for resource in resources:
        value = resource if isinstance(resource, dict) else resource.model_dump()
        if not value.get('enabled', True) or not (value.get('sha256') or value['logical_id'].startswith('library:')):
            continue
        sha = value.get('sha256') or value['logical_id'].removeprefix('library:')
        try:
            record = library.get(sha)
        except (KeyError, ValueError) as exc:
            raise ResourceUnavailable('missing_lora', 'LoRA 尚未收录，请刷新本地资料库。') from exc
        if value['file_name'] != remote_file_name(sha) or value['logical_id'] != 'library:' + sha:
            raise ResourceUnavailable('lora_unmapped', 'LoRA 的内容标识与文件不一致。')
        if record['family'] == 'unknown':
            raise ResourceUnavailable('incompatible_model', '请先在 LoRA 库中确认这个文件的适用模型系列。')
        if record['family'] != family or (record['model_profiles'] and model_profile not in record['model_profiles']):
            raise ResourceUnavailable('incompatible_model', '所选 LoRA 的声明适用模型与当前底模不一致。')
