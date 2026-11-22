"""Data-only gateway protocol. Never retain arbitrary remote metadata."""
import json
import math
import re

MAX_CATALOG_BYTES = 1024 * 1024
CATEGORIES = {'diffusion_models', 'checkpoints', 'text_encoders', 'clip', 'vae', 'loras'}


def text(value, maximum=256):
    if not isinstance(value, str) or not 0 < len(value) <= maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('云端目录文本无效。')
    return value


def asset_path(value):
    value = text(value, 1024)
    parts = value.split('/')
    if len(parts) < 2 or parts[0] not in CATEGORIES or any(p in {'', '.', '..'} for p in parts) or any(c in value for c in '\\:%?#'):
        raise ValueError('云端目录资产路径无效。')
    return {'path': value, 'category': parts[0], 'filename': '/'.join(parts[1:])}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('云端目录包含重复字段。')
        result[key] = value
    return result


def parse_catalog(raw):
    if len(raw) > MAX_CATALOG_BYTES:
        raise ValueError('云端目录超过 1 MiB。')
    try:
        document = json.loads(raw, object_pairs_hook=_pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError('云端目录 JSON 无效。') from None
    if not isinstance(document, dict) or type(document.get('protocol_version')) is not int or document['protocol_version'] != 1:
        raise ValueError('不支持此云端目录协议。')
    models = document.get('models')
    if not isinstance(models, list) or len(models) > 128:
        raise ValueError('云端目录最多支持 128 个模型。')
    result, identifiers = [], set()
    for model in models:
        if not isinstance(model, dict):
            raise ValueError('云端模型格式无效。')
        identifier = text(model.get('id'), 128)
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', identifier) or identifier in identifiers:
            raise ValueError('云端模型 ID 无效或重复。')
        identifiers.add(identifier)
        item = {key: text(model.get(key)) for key in ('id', 'display_name', 'family')}
        assets = model.get('assets')
        if not isinstance(assets, list) or not 1 <= len(assets) <= 64:
            raise ValueError('云端模型资产格式无效。')
        item['assets'] = [asset_path(path) for path in assets]
        if len(set(assets)) != len(assets):
            raise ValueError('云端模型资产重复。')
        for field in ('checkpoint', 'text_encoder', 'vae'):
            if field in model:
                if model[field] not in assets:
                    raise ValueError('云端资产别名无效。')
                item[field] = model[field]
        for field in ('ready', 'selected_for_startup'):
            if type(model.get(field, False)) is not bool:
                raise ValueError('云端就绪状态无效。')
            item[field] = model.get(field, False)
        defaults = model.get('suggested_defaults', {})
        if not isinstance(defaults, dict) or set(defaults) - {'steps', 'cfg', 'sampler', 'scheduler'}:
            raise ValueError('云端建议参数无效。')
        for key, value in defaults.items():
            if key == 'steps' and (type(value) is not int or not 1 <= value <= 200):
                raise ValueError('云端建议步数无效。')
            if key == 'cfg' and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 30):
                raise ValueError('云端建议 CFG 无效。')
            if key in {'sampler', 'scheduler'}:
                text(value, 128)
        item['suggested_defaults'] = dict(defaults)
        result.append(item)
    runtime = document.get('runtime_id')
    return {'models': result, 'runtime_id': text(runtime) if runtime is not None else None}
