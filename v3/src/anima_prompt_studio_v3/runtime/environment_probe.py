"""Read-only deadline-bound environment checks with epoch fenced persistence."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from threading import BoundedSemaphore, Event, Lock, Timer
import time

from anima_prompt_studio.domain.execution_models import RemoteAuthType, RemoteCredentials
from ..remote.comfy_client import ComfyUIClient
from ..remote.credential_store import CredentialStore
from ..remote.local_connection import LocalComfyConnection
from ..remote.connections import connection_factory, client_for_connection, read_runtime_identity
from ..remote.runtime_identity import bind_runtime_identity, confirm_runtime_identity, identity_state
from ..remote.ssh_tunnel import SshTunnel, HostKeyConfirmationRequired, HostKeyMismatchError
from ..storage.runtime_repository import SQLiteRepository
from .workflow_catalog import fingerprint


@dataclass(frozen=True)
class ProbeResult:
    environment_id: str
    environment_epoch: int
    checked_at: float
    connection_state: str
    capabilities_state: str
    reason_codes: list[str] = field(default_factory=list)
    identity_strength: str = 'weak'
    instance_identity: str | None = None


class EnvironmentProbe:
    CONNECTION_TTL = 30
    CAPABILITIES_TTL = 900

    def __init__(self, database, *, credentials=None, clock=time.monotonic, wall_clock=time.time, transport_factory=None, client_factory=ComfyUIClient):
        self.database, self.clock, self.wall_clock = database, clock, wall_clock
        self.credentials = credentials or (lambda _: RemoteCredentials())
        self.transport_factory, self.client_factory = transport_factory, client_factory
        self.lock, self.slots, self.inflight = Lock(), BoundedSemaphore(2), {}
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='anima-environment-probe')

    def _read(self, key, default=None):
        repo = SQLiteRepository(self.database)
        try:
            return repo.get_setting(key, default)
        finally:
            repo.close()

    async def __call__(self, candidate, deadline, expected_epoch):
        profile = candidate['profile']
        if not profile.enabled or not profile.connection_ready:
            return ProbeResult(profile.id, expected_epoch, self.wall_clock(), 'untrusted', 'unchecked', ['disabled_or_untrusted'])
        key = candidate['signature']
        cached = self._read('environment_probe:' + profile.id)
        if cached and cached.get('signature') == key and not candidate.get('recheck'):
            age = self.wall_clock() - cached['result']['checked_at']
            if cached['result']['connection_state'] != 'online' and self.wall_clock() < cached.get('backoff_until', 0):
                return ProbeResult(**cached['result'])
            # Weak identity always refreshes the required capabilities before acceptance.
            if profile.connection_type != 'http' and cached['result']['identity_strength'] == 'strong' and 0 <= age <= self.CONNECTION_TTL:
                capability = self._read('workflow_capabilities:' + profile.id, {})
                if 0 <= self.wall_clock() - capability.get('checked_at', 0) <= self.CAPABILITIES_TTL:
                    return ProbeResult(**cached['result'])
        with self.lock:
            future = self.inflight.get(key)
            if future is None:
                future = self.executor.submit(self._check, candidate, deadline, expected_epoch)
                self.inflight[key] = future
                def finished(_):
                    with self.lock:
                        self.inflight.pop(key, None)
                # Register outside the lock: an already finished Future calls back inline.
            else:
                finished = None
        if finished:
            future.add_done_callback(finished)
        return await asyncio.shield(asyncio.wrap_future(future))

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)

    def _check(self, candidate, deadline, expected_epoch):
        profile = candidate['profile']
        if self.clock() >= deadline:
            return ProbeResult(profile.id, expected_epoch, self.wall_clock(), 'offline', 'unchecked', ['timeout'])
        cancel = Event()
        remaining = lambda: max(.01, deadline - self.clock())
        if not self.slots.acquire(timeout=remaining()):
            return ProbeResult(profile.id, expected_epoch, self.wall_clock(), 'offline', 'unchecked', ['timeout'])
        factory = self.transport_factory or (lambda profile, **options: connection_factory(profile, ssh_factory=SshTunnel, **options))
        options = {'connect_timeout': remaining()}
        if not self.transport_factory and profile.connection_type == 'ssh':
            options.update(deadline=deadline, cancel=cancel, max_attempts=1)
        tunnel = factory(profile, **options)
        timer = Timer(remaining(), lambda: (cancel.set(), tunnel.close()))
        timer.daemon = True
        timer.start()
        result, info, stats, devices = None, None, {}, []
        identity, capability_checked_at, connection_online = None, self.wall_clock(), False
        previous = self._read('environment_probe:' + profile.id, {})
        old_result = previous.get('result', {})
        old_identity = old_result.get('instance_identity')
        if profile.connection_type == 'http':
            # Failed checks must not erase authenticated identity evidence. Bind
            # it to the import session, while allowing epochs to be invalidated.
            if previous.get('http_session_id') == profile.http_session_id:
                old_identity = previous.get('last_runtime_id') or old_identity
            elif previous.get('http_session_id') is not None or previous.get('signature') != candidate['signature']:
                old_identity = None
        try:
            credentials = self.credentials(profile.id)
            if profile.connection_type == 'ssh' and profile.auth_type == RemoteAuthType.PASSWORD and not credentials.password:
                credentials = credentials.model_copy(update={'password': CredentialStore().read_password(profile.id)})
            tunnel.open(credentials)
            if cancel.is_set() or self.clock() >= deadline:
                raise TimeoutError('timeout')
            client = client_for_connection(tunnel, self.client_factory, timeout=(remaining() / 2, remaining() / 2))
            bind_runtime_identity(client, profile, self.database)
            stats = client._get_json('/system_stats')
            connection_online = True
            devices = [str(d.get('name') or d.get('type')) for d in stats.get('devices', [])]
            # Only fixed non-secret identity files; failure explicitly leaves weak evidence.
            if profile.connection_type == 'http':
                identity = read_runtime_identity(client, profile)
                confirm_runtime_identity(self.database, profile, identity)
            if profile.connection_type == 'ssh' and getattr(tunnel, 'client', None) is not None and remaining() > .2:
                try:
                    _, stdout, _ = tunnel.client.exec_command('cat /etc/machine-id /proc/sys/kernel/random/boot_id', timeout=remaining())
                    raw = stdout.read(256).decode('ascii', errors='ignore').strip().splitlines()
                    if len(raw) == 2 and all(16 <= len(value) <= 64 and all(c in '0123456789abcdef-' for c in value) for value in raw):
                        identity = ':'.join(raw)
                except Exception:
                    pass
            capability = self._read('workflow_capabilities:' + profile.id, {})
            changed = old_identity and old_identity != identity
            valid_capabilities = (identity and old_identity == identity and not changed and capability.get('fingerprint') == fingerprint(profile)
                                  and capability.get('environment_epoch') == expected_epoch
                                  and 0 <= self.wall_clock() - capability.get('checked_at', 0) <= self.CAPABILITIES_TTL)
            if valid_capabilities:
                info = capability['object_info']
                capability_checked_at = capability['checked_at']
            else:
                client.timeout = (remaining() / 2, remaining() / 2)
                info = client.object_info(refresh=True)
            if changed:
                # Do not bless existing asset mappings on a reconstructed machine.
                raise RuntimeError('instance_changed')
            result = ProbeResult(profile.id, expected_epoch, self.wall_clock(), 'online', 'ready', [], 'strong' if identity else 'weak', identity)
        except (HostKeyConfirmationRequired, HostKeyMismatchError):
            result = ProbeResult(profile.id, expected_epoch, self.wall_clock(), 'untrusted', 'unchecked', ['host_fingerprint'])
        except Exception as exc:
            reason = 'instance_changed' if str(exc) == 'instance_changed' or getattr(exc, 'code', '').startswith('runtime_identity_') else 'connection_failed'
            if connection_online and reason != 'instance_changed':
                result = ProbeResult(profile.id, expected_epoch, self.wall_clock(), 'online', 'unchecked', ['inspection_required'])
            else:
                result = ProbeResult(profile.id, expected_epoch, self.wall_clock(), 'offline', 'unchecked', [reason])
        finally:
            timer.cancel()
            tunnel.close()
            self.slots.release()
        if cancel.is_set() or self.clock() >= deadline:
            return ProbeResult(profile.id, expected_epoch, self.wall_clock(), 'online' if connection_online else 'offline',
                               'unchecked', ['inspection_required'] if connection_online else ['timeout'])
        repo = SQLiteRepository(self.database)
        try:
            with repo.connection:
                repo.connection.execute('BEGIN IMMEDIATE')
                current = repo.get_remote_profile(profile.id)
                epoch = repo.get_setting('environment_epoch:' + profile.id, 0)
                if epoch != expected_epoch or fingerprint(current) != fingerprint(profile):
                    if 'instance_changed' in result.reason_codes:
                        return result
                    return ProbeResult(profile.id, expected_epoch, self.wall_clock(), 'changed', 'unchecked', ['environment_changed'])
                previous = repo.get_setting('environment_probe:' + profile.id, {})
                failures = 0 if result.connection_state == 'online' else min(previous.get('failures', 0) + 1, 3)
                backoff = (30, 60, 120)[failures - 1] if failures else 0
                def write(key, value):
                    import json
                    repo.connection.execute('INSERT INTO settings(key,value_json) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json', (key, json.dumps(value)))
                snapshot = {'signature': candidate['signature'], 'result': asdict(result), 'failures': failures, 'backoff_until': self.wall_clock() + backoff}
                if profile.connection_type == 'http':
                    snapshot.update(http_session_id=profile.http_session_id, last_runtime_id=old_identity or identity)
                write('environment_probe:' + profile.id, snapshot)
                if result.connection_state == 'online' and result.capabilities_state == 'ready':
                    write('workflow_capabilities:' + profile.id, {'fingerprint': fingerprint(profile), 'environment_epoch': epoch, 'checked_at': capability_checked_at, 'object_info': info,
                          'devices': devices, 'comfyui_version': stats.get('system', {}).get('comfyui_version'), 'error': None})
                elif 'instance_changed' in result.reason_codes:
                    if not identity_state(repo, current).get('conflicted'):
                        write('environment_epoch:' + profile.id, epoch + 1)
                    write('workflow_capabilities:' + profile.id, {})
            return result
        finally:
            repo.close()
