import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest
import requests

from anima_prompt_studio.domain.execution_models import GenerationRun, GenerationRunState, RemoteProfile
from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio_v3.remote.comfy_client import ComfyAPIError, ComfyUIClient
from anima_prompt_studio_v3.remote.execution_coordinator import RemoteExecutionCoordinator, RemoteExecutionError
from anima_prompt_studio_v3.remote.preparation_budget import (
    DirectPreparationBudget, DirectPreparationTimeout, current_preparation_budget,
)
from anima_prompt_studio_v3.remote.result_organizer import ResultOrganizer
from anima_prompt_studio_v3.runtime.lora_catalog import LoraCatalog
from anima_prompt_studio_v3.runtime.workflow_catalog import WorkflowCatalog
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
from test_generation_submissions import harness, payload, submit
from test_http_comfy_runtime import protocol, http_profile
from test_remote_runtime_regression import workflow_profile


def test_execution_preflight_is_bounded_only_until_remote_acceptance(protocol, tmp_path, monkeypatch):
    calls = []
    original = ComfyUIClient._request
    def request(self, method, url, **options):
        calls.append((urlsplit(url).path.removeprefix('/prefix'), current_preparation_budget() is not None))
        return original(self, method, url, **options)
    monkeypatch.setattr(ComfyUIClient, '_request', request)
    job = PromptJob(model_profile_id='anima_turbo_v1', positive_prompt='cat')
    profile = http_profile()
    run = GenerationRun(prompt_job_id=job.id, remote_profile_id=profile.id, workflow_profile_id=workflow_profile().id,
                        request_json={'preparation_policy': 'direct-fast-v1'})
    result = RemoteExecutionCoordinator(organizer=ResultOrganizer(tmp_path), poll_interval=0).execute(
        job, profile, workflow_profile(), 'anima_turbo_v1', run=run)
    assert result.run.state == GenerationRunState.COMPLETED
    assert all(bounded for path, bounded in calls if path in {'/system_stats', '/queue', '/object_info', '/prompt'})
    assert all(not bounded for path, bounded in calls if path in {'/history/remote-prompt', '/view'})
    assert current_preparation_budget() is None


def test_direct_execution_ssh_uses_one_short_attempt_and_cleans_scope_on_failure():
    from test_remote_runtime_regression import remote_profile
    options = []
    class Tunnel:
        def __init__(self, _profile, **kwargs):
            options.append(kwargs)
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
        def open(self, _credentials):
            raise TimeoutError('SSH unavailable')
    job = PromptJob(model_profile_id='anima_turbo_v1', positive_prompt='cat')
    remote = remote_profile()
    run = GenerationRun(prompt_job_id=job.id, remote_profile_id=remote.id, workflow_profile_id=workflow_profile().id,
                        request_json={'preparation_policy': 'direct-fast-v1'})
    with pytest.raises(RemoteExecutionError) as error:
        RemoteExecutionCoordinator(tunnel_factory=Tunnel).execute(job, remote, workflow_profile(), 'anima_turbo_v1', run=run)
    assert error.value.run.state == GenerationRunState.FAILED
    assert not run.request_json.get('submission_attempted')
    assert options[0]['max_attempts'] == 1 and 0 < options[0]['connect_timeout'] <= 5
    assert options[0]['deadline'] > time.monotonic() and current_preparation_budget() is None


def test_stale_direct_inventory_fails_locally_instead_of_reinspecting(harness):
    from anima_prompt_studio_v3.core.lora_resolution import ResourceUnavailable
    _, start, _, executed, _, base_plan = harness
    refreshes = []
    def plan(*args):
        refreshes.append(1)
        return base_plan(*args)
    def stale(*_args):
        raise ResourceUnavailable('unknown', '服务器能力尚未检测或已过期。')
    queue, service = start(plan_resolver=plan, cached_plan_resolver=stale)
    accepted = submit(service)
    service.dispatch_pending()
    assert queue.get(accepted['id']).state == GenerationRunState.FAILED
    assert refreshes == [1] and executed == []


def test_slow_real_http_preparation_rejects_without_later_acceptance(harness, tmp_path, monkeypatch):
    from anima_prompt_studio_v3.core.lora_resolution import ResourceUnavailable
    from anima_prompt_studio_v3.remote.preparation_budget import DirectPreparationTimeout
    from anima_prompt_studio_v3.runtime import submissions
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(0.4)
            body = json.dumps({'devices': []}).encode()
            self.send_response(200)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    _, start, _, executed, _, base_plan = harness
    database = tmp_path / 'local.db'
    repo = SQLiteRepository(database)
    repo.save_remote_profile(RemoteProfile(id='remote-1', connection_type='local', ssh_host='', ssh_user='',
        comfy_host='127.0.0.1', comfy_port=server.server_port))
    repo.close()
    manager = WorkflowCatalog(database)
    def plan(*args):
        LoraCatalog(manager).capabilities('remote-1', refresh=True)
        return base_plan(*args)
    monkeypatch.setattr(submissions, 'DirectPreparationBudget', lambda: DirectPreparationBudget(0.1))
    queue, service = start(plan_resolver=plan)
    try:
        began = time.monotonic()
        with pytest.raises((ResourceUnavailable, DirectPreparationTimeout)):
            submit(service, payload())
        assert time.monotonic() - began < 1.5
        time.sleep(0.45)  # Let the abandoned server response finish; there is no background acceptance.
        service.dispatch_pending()
        assert service.store.lookup('key') is None and queue.reserved_ids() == [] and executed == []
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)


def test_scoped_http_timeouts_leave_unrelated_client_defaults_unchanged():
    timeouts = []
    class Response:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {}
    class Session:
        def get(self, _url, **options):
            timeouts.append(options['timeout'])
            return Response()
    client = ComfyUIClient('http://127.0.0.1', session=Session())
    with DirectPreparationBudget():
        client.object_info()
    client.object_info(refresh=True)
    connect, read = timeouts[0]
    assert 0 < connect <= 2 and 3 < read < 8
    assert connect + read <= 8
    assert timeouts[1] == (10.0, 60.0)


def test_three_second_environment_response_uses_the_shared_preparation_budget(monkeypatch):
    from anima_prompt_studio_v3.remote import preparation_budget
    clock, calls = [0.0], []
    monkeypatch.setattr(preparation_budget.time, 'monotonic', lambda: clock[0])

    class Session:
        def get(self, url, **options):
            path = urlsplit(url).path
            calls.append((path, options['timeout']))
            delay = 3.0 if path == '/system_stats' else 0.25
            if delay > options['timeout'][1]:
                clock[0] += options['timeout'][1]
                raise requests.ReadTimeout('private transport diagnostic')
            clock[0] += delay
            response = requests.Response()
            response.status_code = 200
            response._content = json.dumps({'runtime_id': 'test-runtime'} if path == '/_moss/info' else {}).encode()
            response._content_consumed = True
            return response

    client = ComfyUIClient('https://healthy.test', session=Session())
    client._runtime_profile = RemoteProfile(
        id='http-test', connection_type='http', ssh_host='', ssh_user='',
        http_base_url='https://healthy.test', http_session_id='test-session',
        http_gateway=True, http_runtime_id='test-runtime',
    )
    with DirectPreparationBudget():
        client.validate_environment()
    assert [path for path, _ in calls] == ['/_moss/info', '/system_stats', '/_moss/info', '/queue']
    assert clock[0] == 3.75
    assert all(sum(timeout) <= 8 - index * 0.25 for index, (_, timeout) in enumerate(calls[:2]))


def test_read_timeout_stays_within_remaining_budget_and_is_classified(monkeypatch):
    from anima_prompt_studio_v3.remote import preparation_budget
    clock, calls = [0.0], []
    monkeypatch.setattr(preparation_budget.time, 'monotonic', lambda: clock[0])

    class Session:
        def get(self, url, **options):
            calls.append((url, options['timeout']))
            clock[0] += options['timeout'][1]
            raise requests.ReadTimeout('private-key-in-transport-error')

    client = ComfyUIClient('https://slow.test', session=Session())
    with DirectPreparationBudget():
        clock[0] = 6.0
        with pytest.raises(DirectPreparationTimeout) as error:
            client.validate_environment()
    assert error.value.code == 'direct_preparation_timeout'
    assert 'private-key' not in str(error.value)
    assert len(calls) == 1 and sum(calls[0][1]) <= 2.0 and clock[0] <= 8


def test_unscoped_read_timeout_has_safe_timeout_error_and_no_retry():
    calls = []

    class Session:
        def get(self, *args, **kwargs):
            calls.append(kwargs['timeout'])
            raise requests.ReadTimeout('private-key-in-transport-error')

    client = ComfyUIClient('https://slow.test', session=Session())
    with pytest.raises(ComfyAPIError) as error:
        client.validate_environment()
    assert error.value.code == 'timeout'
    assert '超时' in str(error.value) and 'private-key' not in str(error.value)
    assert calls == [(10.0, 60.0)]


def test_scoped_submit_timeout_is_reported_once_without_a_second_post():
    calls = []

    class Session:
        def post(self, _url, **options):
            calls.append(options['json']['prompt_id'])
            raise requests.ReadTimeout('private-key-in-transport-error')

    client = ComfyUIClient('https://slow.test', session=Session())
    with DirectPreparationBudget():
        with pytest.raises(DirectPreparationTimeout) as error:
            client.submit({}, 'client', 'requested-once')
    assert error.value.code == 'direct_preparation_timeout'
    assert 'private-key' not in str(error.value)
    assert calls == ['requested-once']


def test_successful_remote_ack_is_preserved_when_request_finishes_after_budget(monkeypatch):
    from anima_prompt_studio_v3.remote import preparation_budget
    clock = [0.0]
    monkeypatch.setattr(preparation_budget.time, 'monotonic', lambda: clock[0])
    class Response:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {'prompt_id': 'accepted-remotely'}
    class Session:
        def post(self, _url, **_options):
            clock[0] = 9.0
            return Response()
    client = ComfyUIClient('http://127.0.0.1', session=Session())
    with DirectPreparationBudget():
        assert client.submit({}, 'client', 'requested-id') == 'accepted-remotely'
