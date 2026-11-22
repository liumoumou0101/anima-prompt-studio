import asyncio
from dataclasses import asdict

from anima_prompt_studio_v3.runtime.environment_probe import EnvironmentProbe
from anima_prompt_studio_v3.runtime.workflow_catalog import fingerprint
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
from test_v2_generation_adapter import remote_profile


def setup_probe(tmp_path, *, clock=None, wall_clock=None, info=None, failing=False, identity=None):
    database = tmp_path / 'runtime.db'
    profile = remote_profile()
    repo = SQLiteRepository(database)
    repo.save_remote_profile(profile)
    repo.close()
    calls = []
    class Transport:
        def __init__(self, profile, **kwargs):
            self.base_url = 'http://fake'
            self.client = self if identity else None
            calls.append(('timeout', kwargs['connect_timeout']))
        def open(self, credentials):
            calls.append(('open', None))
            if failing:
                raise OSError('offline')
        def close(self):
            pass
        def exec_command(self, command, timeout):
            import io
            return None, io.BytesIO(identity.encode()), None
    class Client:
        def __init__(self, url, timeout):
            self.timeout = timeout
        def _get_json(self, path):
            calls.append((path, self.timeout))
            return {'system': {'comfyui_version': '0.3.100'}, 'devices': []}
        def object_info(self, refresh):
            calls.append(('object_info', self.timeout))
            return info() if callable(info) else info or {}
    kwargs = {}
    if clock:
        kwargs['clock'] = clock
    if wall_clock:
        kwargs['wall_clock'] = wall_clock
    probe = EnvironmentProbe(database, transport_factory=Transport, client_factory=Client, **kwargs)
    candidate = {'id': profile.id, 'profile': profile, 'epoch': 0, 'signature': 'same'}
    return probe, candidate, calls, database


def test_coalesces_concurrent_probe_and_refreshes_weak_identity(tmp_path):
    from threading import Event
    gate = Event()
    def info():
        assert gate.wait(2)
        return {}
    probe, candidate, calls, _ = setup_probe(tmp_path, info=info)
    async def run():
        tasks = [asyncio.create_task(probe(candidate, probe.clock() + 5, 0)) for _ in range(10)]
        await asyncio.sleep(0)
        gate.set()
        result = await asyncio.gather(*tasks)
        assert all(item.connection_state == 'online' and item.identity_strength == 'weak' for item in result)
        assert sum(name == 'object_info' for name, _ in calls) == 1
        await probe(candidate, probe.clock() + 5, 0)
        assert sum(name == 'object_info' for name, _ in calls) == 2
    try:
        asyncio.run(run())
        assert all(0 < value <= 5 for name, value in calls if name == 'timeout')
    finally:
        probe.close()


def test_strong_identity_cache_thirty_seconds_and_capabilities_nine_hundred(tmp_path):
    now = [100.]
    identity = 'abcdef0123456789abcdef0123456789\n01234567-89ab-cdef-0123-456789abcdef'
    probe, candidate, calls, database = setup_probe(tmp_path, wall_clock=lambda: now[0], identity=identity)
    try:
        result = asyncio.run(probe(candidate, probe.clock() + 5, 0))
        assert result.identity_strength == 'strong'
        now[0] += 29
        asyncio.run(probe(candidate, probe.clock() + 5, 0))
        assert sum(name == 'open' for name, _ in calls) == 1
        now[0] += 2
        asyncio.run(probe(candidate, probe.clock() + 5, 0))
        assert sum(name == 'open' for name, _ in calls) == 2
        assert sum(name == 'object_info' for name, _ in calls) == 1
        now[0] += 900
        asyncio.run(probe(candidate, probe.clock() + 5, 0))
        assert sum(name == 'object_info' for name, _ in calls) == 2
    finally:
        probe.close()


def test_epoch_change_fences_late_capability_write(tmp_path):
    database_holder = []
    def info():
        repo = SQLiteRepository(database_holder[0])
        repo.rebuild_environment('remote-1')
        repo.close()
        return {'late': {}}
    probe, candidate, _, database = setup_probe(tmp_path, info=info)
    database_holder.append(database)
    try:
        result = asyncio.run(probe(candidate, probe.clock() + 5, 0))
        assert result.connection_state == 'changed'
        repo = SQLiteRepository(database)
        assert repo.get_setting('environment_epoch:remote-1') == 1
        assert repo.get_setting('workflow_capabilities:remote-1') == {}
        repo.close()
    finally:
        probe.close()


def test_backoff_30_60_120_and_explicit_recheck(tmp_path):
    now = [100.]
    probe, candidate, calls, database = setup_probe(tmp_path, wall_clock=lambda: now[0], failing=True)
    try:
        for attempt, backoff in enumerate([30, 60, 120], start=1):
            asyncio.run(probe(candidate, probe.clock() + 5, 0))
            repo = SQLiteRepository(database)
            saved = repo.get_setting('environment_probe:remote-1')
            repo.close()
            assert saved['backoff_until'] == now[0] + backoff
            asyncio.run(probe(candidate, probe.clock() + 5, 0))
            assert sum(name == 'open' for name, _ in calls) == attempt
            now[0] += backoff + 1
        asyncio.run(probe({**candidate, 'recheck': True}, probe.clock() + 5, 0))
        assert sum(name == 'open' for name, _ in calls) == 4
    finally:
        probe.close()


def test_probe_ssh_deadline_disables_internal_retry_sleeps(monkeypatch):
    from types import SimpleNamespace
    import pytest
    from anima_prompt_studio.domain.execution_models import RemoteCredentials
    from anima_prompt_studio_v3.remote.ssh_tunnel import SshTunnel, SSHError
    now, attempts = [0.], []
    class TransportFailure(Exception):
        pass
    class AuthFailure(Exception):
        pass
    class Client:
        def load_system_host_keys(self): pass
        def set_missing_host_key_policy(self, policy): pass
        def close(self): pass
        def connect(self, **kwargs):
            attempts.append(kwargs)
            now[0] += 4
            raise TransportFailure('fake offline')
    monkeypatch.setattr('anima_prompt_studio_v3.remote.ssh_tunnel.time.monotonic', lambda: now[0])
    monkeypatch.setattr('anima_prompt_studio_v3.remote.ssh_tunnel.time.sleep', lambda _: pytest.fail('probe must not retry/sleep'))
    profile = remote_profile()
    tunnel = SshTunnel(profile, connect_timeout=5, deadline=5, max_attempts=1)
    monkeypatch.setattr(tunnel, 'probe_fingerprint', lambda: profile.known_host_fingerprint)
    monkeypatch.setattr(tunnel, '_paramiko', lambda: SimpleNamespace(SSHClient=Client, SSHException=TransportFailure, AuthenticationException=AuthFailure))
    with pytest.raises(SSHError):
        tunnel.open(RemoteCredentials(password='fake'))
    assert len(attempts) == 1 and attempts[0]['timeout'] == 5
    now[0] = 6
    with pytest.raises(SSHError, match='截止'):
        tunnel.open(RemoteCredentials(password='fake'))
    assert len(attempts) == 1


def test_online_health_with_large_inventory_exposes_bounded_inspection_fallback(tmp_path):
    now = [0.]
    def info():
        now[0] = 6
        return {'too_late': {}}
    probe, candidate, _, database = setup_probe(tmp_path, clock=lambda: now[0], info=info)
    try:
        result = asyncio.run(probe(candidate, 5, 0))
        assert result.connection_state == 'online' and result.capabilities_state == 'unchecked'
        assert result.reason_codes == ['inspection_required']
        repo = SQLiteRepository(database)
        assert repo.get_setting('workflow_capabilities:remote-1') is None
        repo.close()
    finally:
        probe.close()


def test_first_strong_identity_refreshes_legacy_filename_only_capabilities(tmp_path):
    identity = 'abcdef0123456789abcdef0123456789\n01234567-89ab-cdef-0123-456789abcdef'
    probe, candidate, calls, database = setup_probe(tmp_path, identity=identity)
    repo = SQLiteRepository(database)
    repo.set_setting('workflow_capabilities:remote-1', {'fingerprint': fingerprint(candidate['profile']),
        'environment_epoch': 0, 'checked_at': probe.wall_clock(), 'object_info': {'legacy': {}}})
    repo.close()
    try:
        asyncio.run(probe(candidate, probe.clock() + 5, 0))
        assert sum(name == 'object_info' for name, _ in calls) == 1
    finally:
        probe.close()
