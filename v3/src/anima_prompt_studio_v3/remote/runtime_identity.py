"""Persistent authenticated HTTP identity, shared by all clients in a session."""
import json

from .comfy_client import ComfyAPIError
from ..storage.runtime_repository import SQLiteRepository

_UNOBSERVED = object()


def identity_state(repository, profile):
    """Read without opening a second transaction (also used during mapping save)."""
    if profile.connection_type != 'http':
        return {}
    saved = repository.get_setting('http_runtime_identity:' + profile.id, {})
    if saved.get('session_id') == profile.http_session_id:
        return saved
    # Reconcile evidence written before the shared authority was introduced.
    catalog = repository.get_setting('cloud_model_catalog:' + profile.id, {})
    probe = repository.get_setting('environment_probe:' + profile.id, {})
    identities, conflicted = set(), False
    if catalog.get('signature', [None, None])[1] == profile.http_session_id:
        identity = catalog.get('last_runtime_id') or catalog.get('runtime_id')
        if identity:
            identities.add(identity)
        conflicted = bool(catalog.get('identity_changed'))
    if probe.get('http_session_id') == profile.http_session_id:
        identity = probe.get('last_runtime_id') or probe.get('result', {}).get('instance_identity')
        if identity:
            identities.add(identity)
    return {'session_id': profile.http_session_id, 'runtime_id': next(iter(identities), None),
            'conflicted': conflicted or len(identities) > 1}


def confirm_runtime_identity(database, profile, observed=_UNOBSERVED):
    """Atomically accept the first live ID or reject a changed/stale session.

    Epochs and caches can be invalidated independently; they never reset the
    accepted ID. A mismatch stays blocked until a newly imported session.
    """
    if database is None or profile.connection_type != 'http':
        return None if observed is _UNOBSERVED else observed
    repo = SQLiteRepository(database)
    error = None
    expected = None
    try:
        with repo.connection:
            repo.connection.execute('BEGIN IMMEDIATE')
            try:
                current = repo.get_remote_profile(profile.id)
            except KeyError:
                current = None
            if (current is None or current.connection_type != 'http'
                    or current.http_session_id != profile.http_session_id
                    or current.http_base_url != profile.http_base_url):
                error = 'runtime_identity_session_changed'
            else:
                key = 'http_runtime_identity:' + profile.id
                previous = repo.get_setting(key, {})
                state = identity_state(repo, profile)
                expected = state.get('runtime_id') or profile.http_runtime_id
                mismatch = observed is not _UNOBSERVED and expected and observed != expected
                if state.get('conflicted') or mismatch:
                    state['conflicted'] = True
                    error = 'runtime_identity_mismatch'
                    if previous.get('session_id') != profile.http_session_id or not previous.get('conflicted'):
                        epoch = repo.get_setting('environment_epoch:' + profile.id, 0)
                        _write(repo, 'environment_epoch:' + profile.id, epoch + 1)
                        _write(repo, 'workflow_capabilities:' + profile.id, {})
                elif observed is not _UNOBSERVED and observed:
                    state['runtime_id'] = observed
                    expected = observed
                _write(repo, key, state)
        if error:
            raise ComfyAPIError('云端运行时身份已变化，请重新导入当前连接；不能继续旧任务。', code=error)
        return expected if observed is _UNOBSERVED else observed
    finally:
        repo.close()


def _write(repository, key, value):
    repository.connection.execute(
        'INSERT INTO settings(key,value_json) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json',
        (key, json.dumps(value, ensure_ascii=False)))


def bind_runtime_identity(client, profile, database):
    if profile.connection_type == 'http':
        client._runtime_profile = profile.model_copy(deep=True)
        client._identity_database = database
    return client
