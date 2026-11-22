"""Common connection/client construction for every V3 ComfyUI consumer."""
from .comfy_client import ComfyUIClient, ComfyAPIError
from .local_connection import LocalComfyConnection
from .ssh_tunnel import SshTunnel
from .temporary_connections import normalize_https_url
from .preparation_budget import DirectPreparationTimeout


class HttpComfyConnection:
    def __init__(self, profile, **_options):
        self.profile = profile.model_copy(deep=True)
        self.base_url, _ = normalize_https_url(profile.http_base_url)
        self.active = False
        self.api_key = ""

    def open(self, credentials=None):
        if credentials is not None and credentials.comfy_api_key is not None:
            self.api_key = credentials.comfy_api_key
        else:
            from .credential_store import CredentialStore
            self.api_key = CredentialStore().read_comfy_api_key(self.profile.http_session_id)
        if self.profile.http_auth_required and not self.api_key:
            raise ComfyAPIError('临时连接缺少访问密钥，请重新导入。', code='http_credentials_missing')
        self.active = True
        return self

    def close(self):
        self.active = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def connection_factory(profile, *, ssh_factory=SshTunnel, **options):
    factory = {'http': HttpComfyConnection, 'local': LocalComfyConnection}.get(profile.connection_type, ssh_factory)
    return factory(profile, **options)


def client_for_connection(connection, factory=ComfyUIClient, *, identity_database=None, **options):
    if isinstance(connection, HttpComfyConnection) and factory is ComfyUIClient:
        options['api_key'] = connection.api_key
    client = factory(connection.base_url, **options)
    if isinstance(connection, HttpComfyConnection) and isinstance(client, ComfyUIClient):
        from .runtime_identity import bind_runtime_identity
        bind_runtime_identity(client, connection.profile, identity_database)
    return client


def read_runtime_identity(client, profile):
    """Only a live authenticated gateway response can provide strong identity."""
    if profile.connection_type != 'http':
        return None
    import json
    from .runtime_identity import confirm_runtime_identity
    database = getattr(client, '_identity_database', None)
    shared = confirm_runtime_identity(database, profile)
    expected = profile.http_runtime_id or shared or getattr(client, '_observed_runtime_id', None)
    if not profile.http_gateway and not expected:
        return None
    try:
        data = json.loads(client.read_bounded('/_moss/info', maximum=65536))
        identity = data.get('runtime_id') if isinstance(data, dict) else None
        if identity is not None and (not isinstance(identity, str) or not 1 <= len(identity) <= 256
                                    or any(ord(c) < 33 or ord(c) == 127 for c in identity)):
            raise ValueError()
        if identity != getattr(client, '_clean', lambda value: value)(identity):
            raise ValueError()
    except DirectPreparationTimeout:
        raise
    except Exception:
        if expected:
            raise ComfyAPIError('无法确认当前运行时身份，请重新导入连接。', code='runtime_identity_unavailable') from None
        return None
    confirm_runtime_identity(database, profile, identity)
    if expected and identity != expected:
        raise ComfyAPIError('云端运行时已更换，请重新导入连接；不能继续旧任务。', code='runtime_identity_mismatch')
    if identity:
        client._observed_runtime_id = identity
    return identity


def http_connection_snapshot(profile):
    if profile.connection_type != 'http':
        return {}
    return {'session_id': profile.http_session_id, 'base_url': profile.http_base_url,
            'runtime_id': profile.http_runtime_id}


def verify_run_runtime_identity(client, profile, run):
    if profile.connection_type != 'http':
        return
    snapshot = run.request_json.get('http_connection', {})
    frozen = snapshot.get('observed_runtime_id')
    if frozen:
        client._observed_runtime_id = frozen
    identity = read_runtime_identity(client, profile)
    if frozen and identity != frozen:
        raise ComfyAPIError('云端运行时与任务快照不符，不能恢复旧任务。', code='runtime_identity_mismatch')
    if identity:
        snapshot['observed_runtime_id'] = identity


def validate_http_session(run, profile):
    snapshot = run.request_json.get('http_connection')
    if profile.connection_type == 'http' or snapshot:
        if (profile.connection_type != 'http' or not isinstance(snapshot, dict)
                or not profile.http_session_id or snapshot.get('session_id') != profile.http_session_id
                or snapshot.get('base_url') != profile.http_base_url
                or snapshot.get('runtime_id') != profile.http_runtime_id):
            raise ValueError('临时连接已替换或任务缺少连接会话快照，不能恢复旧任务；请重新生成。')
