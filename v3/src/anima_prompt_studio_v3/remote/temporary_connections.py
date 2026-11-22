"""Bounded connection imports; secrets are staged under immutable session references."""
from __future__ import annotations

import json
from urllib.parse import unquote, urlsplit, urlunsplit
from uuid import uuid4

from anima_prompt_studio.domain.execution_models import RemoteAuthType, RemoteProfile
from .credential_store import CredentialStoreError

MAX_CONNECTION_TEXT = 65536


def normalize_https_url(raw: str) -> tuple[str, bool]:
    message = "请输入有效的 HTTPS ComfyUI API 地址；不支持凭据、查询参数或片段。"
    if not isinstance(raw, str) or any(ord(c) < 32 or ord(c) == 127 for c in raw):
        raise ValueError(message)
    try:
        value = urlsplit(raw.strip())
        port = value.port
        decoded = unquote(value.path)
        if (value.scheme != 'https' or not value.hostname or value.username is not None
                or value.password is not None or '?' in raw or '#' in raw or '\\' in raw
                or any(ord(c) < 32 or ord(c) == 127 for c in decoded)
                or any(part in {'.', '..'} for part in decoded.split('/'))
                or any(c.isspace() for c in raw.strip())
                or value.hostname.lower() in {'colab.research.google.com', 'www.kaggle.com', 'kaggle.com', 'github.com', 'www.github.com'}):
            raise ValueError(message)
        host = value.hostname.lower().encode('idna').decode('ascii')
        if ':' in host:
            host = '[' + host + ']'
        if port is not None and port != 443:
            host += ':' + str(port)
        path = value.path.rstrip('/')
        gateway = path.endswith('/_moss/login')
        if gateway:
            path = path[:-len('/_moss/login')]
        return urlunsplit(('https', host, path, '', '')), gateway
    except (ValueError, UnicodeError):
        raise ValueError(message) from None


def parse_connection(connection_text: str, api_key: str | None = None, *, allow_missing_key=False):
    if not isinstance(connection_text, str) or not 0 < len(connection_text.encode('utf-8')) <= MAX_CONNECTION_TEXT:
        raise ValueError("连接信息不能为空或超过 64 KB。")
    text = connection_text.strip()
    document = {}
    if text.startswith('{') or text.startswith('['):
        try:
            document = json.loads(text)
        except (ValueError, RecursionError):
            raise ValueError("连接 JSON 无效。") from None
        if not isinstance(document, dict) or document.get('protocol') != 'comfyui-http':
            raise ValueError("仅支持 comfyui-http 连接 JSON。")
        if document.get('auth_header', 'Authorization') != 'Authorization' or document.get('auth_scheme', 'Bearer') != 'Bearer':
            raise ValueError("仅支持 Authorization Bearer 认证。")
        if 'scope' in document and document['scope'] != 'current-colab-runtime':
            raise ValueError("不支持此连接范围。")
        if 'model_catalog' in document and document['model_catalog'] != '/_moss/models':
            raise ValueError("仅支持同源 /_moss/models 模型目录声明。")
        if api_key is not None and document.get('api_key') is not None and api_key != document['api_key']:
            raise ValueError("JSON 密钥与访问密钥输入不同，请只保留一个正确的密钥。")
        text = document.get('base_url')
    base_url, gateway = normalize_https_url(text)
    key = api_key if api_key is not None else document.get('api_key')
    if isinstance(key, str) and key.lower().startswith('bearer '):
        raise ValueError("请只填写访问密钥本身，不要包含 Bearer 前缀。")
    required = bool(document.get('auth_scheme') or document.get('auth_header') or document.get('api_key'))
    if key is not None and (not isinstance(key, str) or len(key) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in key)):
        if key != '':
            raise ValueError("访问密钥格式无效。")
    if required and not key and not allow_missing_key:
        raise ValueError("此连接需要 Bearer 访问密钥。")
    identity = document.get('runtime_id')
    if identity is not None and (not isinstance(identity, str) or not 1 <= len(identity) <= 256 or any(ord(c) < 33 for c in identity)):
        raise ValueError("运行时身份格式无效。")
    gateway = gateway or document.get('model_catalog') == '/_moss/models' or document.get('scope') == 'current-colab-runtime'
    return base_url, key, required or bool(key), identity, gateway


def import_temporary_connection(repository, credentials, *, connection_text, api_key=None, display_name='', target_profile_id=None, serialize=None):
    existing = repository.get_remote_profile(target_profile_id) if target_profile_id else None
    if existing and existing.connection_type != 'http':
        raise TypeError("只能更新现有 HTTPS 临时连接。")
    base_url, key, auth_required, runtime_id, gateway = parse_connection(connection_text, api_key, allow_missing_key=bool(existing))
    # Omitting an optional key on an update preserves it; an explicit empty string clears it.
    if existing and key is None:
        key = credentials.read_comfy_api_key(existing.http_session_id)
        auth_required = auth_required or existing.http_auth_required
    if auth_required and not key:
        raise ValueError("此连接需要 Bearer 访问密钥。")
    if existing and existing.http_base_url == base_url:
        gateway = gateway or existing.http_gateway
    key = key or ''
    unchanged = bool(existing and (existing.http_base_url, existing.http_runtime_id, existing.http_auth_required,
                     credentials.read_comfy_api_key(existing.http_session_id)) == (base_url, runtime_id, auth_required, key))
    session_id = existing.http_session_id if unchanged else uuid4().hex
    profile = (existing or RemoteProfile(ssh_host='', ssh_user='', auth_type=RemoteAuthType.AGENT)).model_copy(update={
        'connection_type': 'http', 'http_base_url': base_url, 'http_session_id': session_id,
        'http_runtime_id': runtime_id, 'http_auth_required': auth_required, 'http_gateway': gateway,
        'display_name': display_name.strip() or (existing.display_name if existing else '临时 ComfyUI'),
    })
    # Stage new credentials without overwriting the old session's key. A failed write leaves the
    # old profile/key pair intact, including on credential backends that partially write then fail.
    if not unchanged and key:
        try:
            credentials.save_comfy_api_key(session_id, key)
        except CredentialStoreError:
            try:
                credentials.delete_comfy_api_key(session_id)
            except CredentialStoreError:
                pass
            raise
    try:
        with repository.connection:
            repository.connection.execute('BEGIN IMMEDIATE')
            repository.connection.execute('INSERT INTO remote_profiles(id,display_name,payload_json) VALUES(?,?,?) '
                'ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name,payload_json=excluded.payload_json',
                (profile.id, profile.display_name, profile.model_dump_json()))
            if not unchanged:
                epoch = repository.get_setting('environment_epoch:' + profile.id, 0) + 1
                for setting, value in [('environment_epoch:' + profile.id, epoch),
                    ('workflow_capabilities:' + profile.id, {}), ('environment_probe:' + profile.id, {})]:
                    repository.connection.execute('INSERT INTO settings(key,value_json) VALUES(?,?) ON CONFLICT(key) '
                        'DO UPDATE SET value_json=excluded.value_json', (setting, json.dumps(value)))
                if existing:
                    retired = repository.get_setting('http_retired_sessions:' + profile.id, [])
                    if existing.http_session_id not in retired:
                        retired.append(existing.http_session_id)
                    repository.connection.execute('INSERT INTO settings(key,value_json) VALUES(?,?) ON CONFLICT(key) '
                        'DO UPDATE SET value_json=excluded.value_json', ('http_retired_sessions:' + profile.id, json.dumps(retired)))
            if existing is None:
                repository.connection.execute('INSERT INTO settings(key,value_json) VALUES(?,?) ON CONFLICT(key) '
                    'DO UPDATE SET value_json=excluded.value_json', ('last_remote_profile_id', json.dumps(profile.id)))
            # Serialize while the transaction can still roll back. In particular, failure to
            # read credential availability must not produce a 503 after saving a new profile.
            result = serialize(profile, credentials) if serialize is not None else profile
    except Exception:
        if not unchanged and key:
            credentials.delete_comfy_api_key(session_id)
        raise
    if existing and not unchanged:
        # Cleanup cannot turn a committed import into a reported failure. Keep durable,
        # non-secret references so deletion also retries cleanup of retired sessions.
        try:
            credentials.delete_comfy_api_key(existing.http_session_id)
        except CredentialStoreError:
            pass
    return result


def web_url(profile):
    return profile.http_base_url + '/_moss/login' if profile.http_gateway else ''


def delete_http_credentials(repository, credentials, profile):
    session_ids = list(dict.fromkeys([
        *repository.get_setting('http_retired_sessions:' + profile.id, []), profile.http_session_id]))
    # Keep the only secret backup in memory until the surrounding SQLite deletion commits.
    # Read every key before removing any, so an unavailable store has no partial effects.
    backups = {session_id: credentials.read_comfy_api_key(session_id) for session_id in session_ids}
    attempted = []

    def restore():
        for session_id in attempted:
            if backups[session_id]:
                credentials.save_comfy_api_key(session_id, backups[session_id])

    try:
        for session_id in session_ids:
            attempted.append(session_id)  # Also covers a backend that removes then raises.
            credentials.delete_comfy_api_key(session_id)
    except Exception:
        restore()
        raise
    return restore
