"""Run only locally owned notebook functions, never downloaded code or GPU work."""
import ast
import asyncio
import copy
import importlib.util
import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
COLAB = ROOT / 'tools' / 'colab'
ORIGINAL = json.loads((COLAB / 'original.ipynb').read_text(encoding='utf-8'))


def updated():
    path = COLAB / 'update_notebook.py'
    if not path.exists():
        return copy.deepcopy(ORIGINAL)
    spec = importlib.util.spec_from_file_location('colab_updater', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.update_notebook(ORIGINAL)


def source(identifier, notebook=None):
    return ''.join(next(c for c in (notebook or updated())['cells']
                        if c.get('metadata', {}).get('id') == identifier)['source'])


def functions(identifier, names, namespace=None):
    tree = ast.parse(source(identifier))
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name in names]
    assert {node.name for node in nodes} == set(names), 'Notebook behavior has not been implemented'
    namespace = namespace if namespace is not None else {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<notebook-functions>', 'exec'), namespace)
    return namespace


def registry():
    tree = ast.parse(source('moss-prepare'))
    node = next(n for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'MODEL_REGISTRY' for t in n.targets))
    return json.loads(ast.literal_eval(node.value.args[0]))


def test_explicit_turbo_prepares_only_three_dependencies_and_preserves_catalog():
    catalog = registry()
    ns = functions('moss-prepare', ['select_model_assets'],
                   {'MODEL_GROUPS': {'全部': None, '仅 ANIMA': 'ANIMA', '仅 MOSS': 'MOSS'},
                    'PurePosixPath': PurePosixPath})
    ids, assets = ns['select_model_assets'](catalog, '全部', 'anima_turbo_v1_1')
    assert ids == ['anima_turbo_v1_1']
    assert [a['path'] for a in assets] == [
        'diffusion_models/anima-turbo-v1.1.safetensors',
        'text_encoders/qwen_3_06b_base.safetensors', 'vae/qwen_image_vae.safetensors']
    assert len(catalog['models']) == 7
    assert len(catalog['files']) == 11


@pytest.mark.parametrize(('group', 'models', 'assets'), [('全部', 7, 11), ('仅 ANIMA', 6, 8), ('仅 MOSS', 1, 3)])
def test_group_selection_remains_compatible(group, models, assets):
    ns = functions('moss-prepare', ['select_model_assets'],
                   {'MODEL_GROUPS': {'全部': None, '仅 ANIMA': 'ANIMA', '仅 MOSS': 'MOSS'},
                    'PurePosixPath': PurePosixPath})
    ids, selected = ns['select_model_assets'](registry(), group)
    assert (len(ids), len(selected)) == (models, assets)
    with pytest.raises(ValueError):
        ns['select_model_assets'](registry(), group, 'unknown-model')


def test_storage_plan_counts_verified_local_and_drive_separately(tmp_path):
    local, drive = tmp_path / 'local', tmp_path / 'drive'
    specs = [{'path': 'a', 'size_bytes': 10}, {'path': 'b', 'size_bytes': 20}, {'path': 'c', 'size_bytes': 30}]
    ns = functions('moss-prepare', ['model_storage_plan'], {
        'LOCAL_MODELS': local, 'MODEL_STORE': drive,
        'verified': lambda path, spec: path in {local / 'a', drive / 'b'}})
    assert ns['model_storage_plan'](specs) == {
        'planned_bytes': 60, 'local_cached_bytes': 10, 'drive_cached_bytes': 20,
        'download_bytes': 30, 'local_new_bytes': 50, 'drive_new_bytes': 40}


def test_anima_workflow_preparation_never_requires_moss_template(tmp_path):
    class NoTemplate:
        def distribution(self, package):
            raise AssertionError('ANIMA attempted to discover a MOSS template')
    ns = functions('moss-prepare', ['prepare_workflow_template'], {
        'MODEL_REGISTRY': registry(), 'SELECTED_MODEL_IDS': ['anima_turbo_v1_1'],
        'metadata': NoTemplate()})
    ns['prepare_workflow_template'](tmp_path)


def test_runtime_identity_retains_same_process_and_rejects_dead_or_unowned():
    ns = functions('moss-start', ['runtime_identity'])
    alive = SimpleNamespace(poll=lambda: None, _moss_runtime_id='a' * 64)
    assert ns['runtime_identity'](alive) == 'a' * 64
    assert ns['runtime_identity'](alive) == 'a' * 64
    fresh = SimpleNamespace(poll=lambda: None, _moss_runtime_id='b' * 64)
    assert ns['runtime_identity'](fresh) != ns['runtime_identity'](alive)
    for invalid in [None, SimpleNamespace(poll=lambda: 0, _moss_runtime_id='a' * 64),
                    SimpleNamespace(poll=lambda: None)]:
        with pytest.raises(RuntimeError):
            ns['runtime_identity'](invalid)


def test_start_cell_new_service_rotates_id_and_retires_stale_gateway(tmp_path):
    import os
    import secrets
    import tempfile
    events = []
    drive, local, project = tmp_path / 'My Drive', tmp_path / 'local-models', tmp_path / 'project'
    drive_upscale = drive / 'models' / 'upscale_models'
    local_upscale = local / 'upscale_models'
    for folder in (drive_upscale, local_upscale, project):
        folder.mkdir(parents=True)
    (drive_upscale / 'from-drive.pth').write_text('drive fixture')
    (local_upscale / 'already-local.pth').write_text('local fixture')
    user_config = project / 'extra_model_paths.yaml'
    user_config.write_text('user config stays intact')
    configs = []
    class Process:
        dead = False
        def poll(self):
            return 0 if self.dead else None
        def terminate(self):
            events.append('retire-gateway')
            self.dead = True
        def wait(self, timeout):
            return 0
    class Socket:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def settimeout(self, timeout): pass
        def connect_ex(self, address): return 1
    def launch(command, **kwargs):
        assert command[1] == '-u'
        assert kwargs.get('start_new_session') is True
        assert Path(command[command.index('--models-directory') + 1]) == local
        config = Path(command[command.index('--extra-model-paths-config') + 1])
        assert config != user_config and not config.is_relative_to(drive)
        configs.append(config)
        search = json.loads(config.read_text(encoding='utf-8'))
        assert list(search.values()) == [{'upscale_models': str(drive_upscale)}]
        assert (Path(next(iter(search.values()))['upscale_models']) / 'from-drive.pth').is_file()
        events.append('launch-comfy')
        return Process()
    tree = ast.parse(source('moss-start'))
    tree.body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))
                 and not (isinstance(n, ast.FunctionDef) and n.name == 'server_ready')]
    ns = {'MOSS_READY': True, 'MODEL_FILES': [], 'PROJECT': project, 'DRIVE_ROOT': drive,
          'LOCAL_MODELS': local, 'COMFY_COMMIT': 'fixed', 'secrets': secrets,
          'os': os, 'tempfile': tempfile, 'json': json,
          'server_ready': lambda: True, 'Path': lambda value: tmp_path / Path(value).name,
          'sys': SimpleNamespace(executable='python'), 'time': SimpleNamespace(monotonic=lambda: 0),
          'socket': SimpleNamespace(socket=Socket), 'subprocess': SimpleNamespace(Popen=launch, STDOUT=-2),
          'print': lambda *args, **kwargs: None, 'MOSS_RUNTIME_ID': 'stale-drive-id'}
    code = compile(tree, '<start-cell>', 'exec')
    exec(code, ns)
    first_process, first_id = ns['MOSS_PROCESS'], ns['MOSS_RUNTIME_ID']
    assert len(first_id) == 64 and first_id != 'stale-drive-id'
    exec(code, ns)
    assert ns['MOSS_PROCESS'] is first_process and ns['MOSS_RUNTIME_ID'] == first_id
    first_process.dead = True
    stale_gateway = Process()
    ns['MOSS_GATEWAY_PROCESS'] = stale_gateway
    exec(code, ns)
    assert ns['MOSS_RUNTIME_ID'] != first_id
    assert events == ['launch-comfy', 'retire-gateway', 'launch-comfy']
    assert stale_gateway.dead
    assert len(configs) == 2 and all(not config.exists() for config in configs)
    assert user_config.read_text() == 'user config stays intact'
    assert {p.name for p in local_upscale.iterdir()} == {'already-local.pth'}


@pytest.mark.parametrize(('digest', 'identity', 'alive', 'expected'), [
    ('new', 'runtime-a', True, True), ('old', 'runtime-a', True, False),
    ('new', 'runtime-b', True, False), ('new', 'runtime-a', False, False)])
def test_gateway_reuse_requires_live_process_source_and_upstream(digest, identity, alive, expected):
    ns = functions('moss-cloud-api', ['gateway_reusable'])
    process = SimpleNamespace(poll=lambda: None if alive else 0,
                              _moss_source_digest=digest, _moss_upstream_runtime_id=identity)
    assert ns['gateway_reusable'](process, 'new', 'runtime-a') is expected


def test_all_cells_compile_and_mount_instructions_metadata_remain_intact():
    notebook = updated()
    for cell in notebook['cells']:
        if cell['cell_type'] == 'code':
            compile(''.join(cell['source']), '<colab>', 'exec')
            assert not cell.get('outputs')
            assert cell.get('execution_count') is None
    assert notebook['cells'][:2] == ORIGINAL['cells'][:2]
    assert notebook['metadata'] == ORIGINAL['metadata']


def test_gateway_info_identity_remains_behind_authentication():
    # Only the embedded, locally authored gateway module is executed. Its startup guard is inert.
    tree = ast.parse(source('moss-cloud-api'))
    assignment = next(n for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'GATEWAY_SOURCE' for t in n.targets))
    gateway_source = ast.literal_eval(assignment.value)
    gateway_tree = ast.parse(gateway_source)
    create = next(n for n in gateway_tree.body if isinstance(n, ast.FunctionDef) and n.name == 'create_app')
    assert 'runtime_id' in [arg.arg for arg in create.args.args], 'Optional identity is missing'
    nested = [n for n in create.body if isinstance(n, ast.AsyncFunctionDef) and n.name in {'authenticate', 'info'}]
    helpers = [n for n in gateway_tree.body if isinstance(n, ast.FunctionDef) and n.name in {'equal', 'error'}]
    import hmac
    def json_response(payload, status=200, headers=None):
        return SimpleNamespace(status=status, body=json.dumps(payload).encode())
    ns = {'runtime_id': 'c' * 64, 'api_key': 'a' * 32, 'browser_session': 'b' * 32,
          'COOKIE': 'moss_session', 'NO_STORE': {}, 'hmac': hmac,
          'web': SimpleNamespace(middleware=lambda fn: fn, json_response=json_response)}
    exec(compile(ast.Module(body=helpers + nested, type_ignores=[]), '<gateway-functions>', 'exec'), ns)
    async def check():
        denied = await ns['authenticate'](SimpleNamespace(path='/_moss/info', method='GET', headers={}, cookies={}), ns['info'])
        assert denied.status == 401
        allowed = await ns['authenticate'](SimpleNamespace(path='/_moss/info', method='GET',
            headers={'Authorization': 'Bearer ' + 'a' * 32}, cookies={}), ns['info'])
        assert json.loads(allowed.body)['runtime_id'] == 'c' * 64
    asyncio.run(check())


def test_connection_json_uses_current_live_identity(tmp_path):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            return json.dumps({'service': 'moss-comfyui-gateway', 'runtime_id': 'a' * 64}).encode()
    ns = functions('moss-start', ['runtime_identity'])
    ns.update({
        'prepare_gateway': lambda: None,
        'MOSS_PROCESS': SimpleNamespace(poll=lambda: None, _moss_runtime_id='a' * 64),
        'MOSS_TUNNEL_PROCESS': SimpleNamespace(poll=lambda: None),
        'MOSS_API_URL': 'https://test.invalid', 'MOSS_API_KEY': 'test-only-placeholder',
        'Path': lambda value: tmp_path / Path(value).name, 'json': json,
        'time': SimpleNamespace(monotonic=lambda: 0), 'html': SimpleNamespace(escape=lambda value, **kw: value),
        'urllib': SimpleNamespace(request=SimpleNamespace(Request=lambda *args, **kw: None,
                                                         urlopen=lambda *args, **kw: Response())),
        'display': lambda value: None, 'Markdown': lambda value: value, 'HTML': lambda value: value,
        'print': lambda *args: None})
    functions('moss-cloud-api', ['start_cloud_api'], ns)['start_cloud_api']()
    connection = json.loads((tmp_path / 'moss_connection.json').read_text(encoding='utf-8'))
    assert connection['runtime_id'] == 'a' * 64
    assert connection['auth_scheme'] == 'Bearer'


@pytest.mark.parametrize(('reported', 'expected'), [('a' * 64, True), ('b' * 64, False), (None, False)])
def test_gateway_readiness_rejects_old_or_missing_upstream_identity(reported, expected):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            return json.dumps({'service': 'moss-comfyui-gateway', 'runtime_id': reported}).encode()
    ns = functions('moss-start', ['runtime_identity'])
    ns.update({'json': json, 'GATEWAY_URL': 'http://127.0.0.1:8190',
               'MOSS_PROCESS': SimpleNamespace(poll=lambda: None, _moss_runtime_id='a' * 64),
               'urllib': SimpleNamespace(request=SimpleNamespace(Request=lambda *args, **kwargs: None,
                                                                urlopen=lambda *args, **kwargs: Response()))})
    assert functions('moss-cloud-api', ['gateway_ready'], ns)['gateway_ready']('test-placeholder') is expected


def test_generated_artifacts_match_reproducible_transformation():
    notebook = updated()
    assert json.loads((COLAB / 'MOSS_ComfyUI_OneClick.ipynb').read_text(encoding='utf-8')) == notebook
    for identifier in ['moss-prepare', 'moss-start', 'moss-cloud-api', 'moss-monitor']:
        assert (COLAB / (identifier + '.py')).read_text(encoding='utf-8') == source(identifier, notebook)


def test_all_background_services_start_in_independent_sessions():
    launches = []
    for identifier in ('moss-start', 'moss-cloud-api'):
        calls = [node for node in ast.walk(ast.parse(source(identifier)))
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and isinstance(node.func.value, ast.Name) and node.func.value.id == 'subprocess'
                 and node.func.attr == 'Popen']
        launches.extend(calls)
    assert len(launches) == 3, 'ComfyUI, gateway, and tunnel each need an isolated background process'
    for call in launches:
        assert any(keyword.arg == 'start_new_session' and isinstance(keyword.value, ast.Constant)
                   and keyword.value.value is True for keyword in call.keywords)


def test_isolated_background_child_survives_foreground_group_interrupt():
    import os
    import subprocess
    import sys
    if os.name != 'posix':
        pytest.skip('POSIX process-group signals are used by the Linux Colab runtime')
    # The driver has its own session, so sending SIGINT to its group cannot
    # interrupt pytest. Compare inherited and isolated children in that group.
    driver = r'''
import json, os, signal, subprocess, sys
signal.signal(signal.SIGINT, signal.SIG_IGN)
child = "import signal,time; signal.signal(signal.SIGINT, signal.SIG_DFL); print('ready',flush=True); time.sleep(30)"
shared = subprocess.Popen([sys.executable, '-c', child], stdout=subprocess.PIPE, text=True)
isolated = subprocess.Popen([sys.executable, '-c', child], stdout=subprocess.PIPE, text=True, start_new_session=True)
try:
    assert shared.stdout.readline().strip() == isolated.stdout.readline().strip() == 'ready'
    os.killpg(os.getpgrp(), signal.SIGINT)
    shared.wait(timeout=5)
    print(json.dumps({'shared_returncode': shared.returncode, 'isolated_alive': isolated.poll() is None}), flush=True)
finally:
    for process in (shared, isolated):
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
'''
    completed = subprocess.run([sys.executable, '-c', driver], start_new_session=True,
                               capture_output=True, text=True, timeout=15, check=True)
    assert json.loads(completed.stdout) == {'shared_returncode': -2, 'isolated_alive': True}


def test_monitor_is_appended_and_preserves_existing_user_cells():
    spec = importlib.util.spec_from_file_location('colab_updater', COLAB / 'update_notebook.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = copy.deepcopy(ORIGINAL)
    original['cells'].append({'cell_type': 'code', 'metadata': {'id': 'user-extra'},
                              'source': ['print("my cell")'], 'outputs': [], 'execution_count': 3})
    result = module.add_generation_monitor(original)
    assert result['cells'][:-1] == original['cells']
    assert result['metadata'] == original['metadata']
    assert len(module.add_generation_monitor(result)['cells']) == len(result['cells'])
    assert result['cells'][-1]['metadata']['id'] == 'moss-monitor'


def test_monitor_reads_carriage_return_progress_and_truncated_log(tmp_path):
    log_path = tmp_path / 'comfy.log'
    log_path.write_bytes(b'old log\n')
    ns = functions('moss-monitor', ['read_generation_log'])
    with log_path.open('rb') as stream:
        stream.seek(0, 2)
        with log_path.open('ab') as writer:
            writer.write(b'\r 10% 1/10\r 20% 2/10')
        assert ns['read_generation_log'](stream, log_path) == [' 10% 1/10', ' 20% 2/10']
        log_path.write_bytes(b'restarted\n')
        assert ns['read_generation_log'](stream, log_path) == ['restarted']


def test_monitor_reports_work_and_stops_without_terminating_service(tmp_path):
    from collections import deque
    import html
    log_path = tmp_path / 'comfy.log'
    log_path.write_text('old log')
    queues = iter([{'queue_running': [[0, 'job-a']], 'queue_pending': [[1, 'job-b']]},
                   OSError('temporary unavailable'), {'queue_running': [], 'queue_pending': []}])
    panels = []
    status = {'alive': True, 'ticks': 0}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            queue = next(queues)
            if isinstance(queue, Exception): raise queue
            return json.dumps(queue).encode()
    def sleep(seconds):
        status['ticks'] += 1
        with log_path.open('ab') as writer:
            writer.write(b'\r50% <progress>')
        if status['ticks'] == 3:
            raise KeyboardInterrupt
    def show(content, **kwargs):
        panels.append(content)
        return SimpleNamespace(update=panels.append)
    process = SimpleNamespace(pid=100, poll=lambda: None)
    ns = {'deque': deque, 'html': html, 'json': json, 'Path': Path,
          'os': SimpleNamespace(name='posix', getsid=lambda pid: pid),
          'display': show, 'HTML': lambda value: value,
          'time': SimpleNamespace(monotonic=lambda: status['ticks'] * 2, sleep=sleep,
                                  strftime=lambda pattern: '12:00:00'),
          'urllib': SimpleNamespace(request=SimpleNamespace(urlopen=lambda *args, **kwargs: Response())),
          'MOSS_PROCESS': process, 'LOG_PATH': log_path, 'print': lambda *args, **kwargs: None}
    functions('moss-monitor', ['read_generation_log', 'monitor_generation'], ns)['monitor_generation']()
    assert any('执行 1' in value and '排队 1' in value for value in panels)
    assert any('暂时无法读取' in value for value in panels)
    assert any('当前空闲' in value for value in panels)
    assert any('&lt;progress&gt;' in value for value in panels)
    assert '监控已停止' in panels[-1]
    assert process.poll() is None


@pytest.mark.parametrize('process_exits', [False, True])
def test_monitor_natural_end_keeps_service_or_drains_final_error(tmp_path, process_exits):
    from collections import deque
    import html
    log_path = tmp_path / 'comfy.log'
    log_path.write_text('')
    ticks = [0]
    panels = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{"queue_running": [], "queue_pending": []}'
    def sleep(seconds):
        ticks[0] += 1
        log_path.write_text('CUDA out of memory\n' if process_exits else 'task finished\n')
    ns = {'deque': deque, 'html': html, 'json': json, 'Path': Path,
          'os': SimpleNamespace(name='posix', getsid=lambda pid: pid),
          'display': lambda *args, **kwargs: SimpleNamespace(update=panels.append), 'HTML': lambda x: x,
          'time': SimpleNamespace(monotonic=lambda: ticks[0] * 60, sleep=sleep, strftime=lambda x: '12:00'),
          'urllib': SimpleNamespace(request=SimpleNamespace(urlopen=lambda *args, **kwargs: Response())),
          'MOSS_PROCESS': SimpleNamespace(pid=100, poll=lambda: 1 if process_exits and ticks[0] else None),
          'LOG_PATH': log_path}
    functions('moss-monitor', ['read_generation_log', 'monitor_generation'], ns)['monitor_generation'](1)
    assert ticks == [1]
    if process_exits:
        assert '服务进程已结束' in panels[-1] and 'CUDA out of memory' in panels[-1]
    else:
        assert '观察时段已结束' in panels[-1] and '后台服务仍在运行' in panels[-1]


@pytest.mark.parametrize('unsafe_service', ['MOSS_PROCESS', 'MOSS_GATEWAY_PROCESS', 'MOSS_TUNNEL_PROCESS'])
def test_monitor_refuses_inherited_process_sessions_before_entering_monitor(unsafe_service):
    processes = {name: SimpleNamespace(pid=100 + index, poll=lambda: None)
                 for index, name in enumerate(('MOSS_PROCESS', 'MOSS_GATEWAY_PROCESS', 'MOSS_TUNNEL_PROCESS'))}
    unsafe_pid = processes[unsafe_service].pid
    def session_id(pid):
        return 999 if pid == unsafe_pid else pid
    def entered_monitor(_path):
        raise AssertionError('An unsafe process must be rejected before opening the monitor')
    ns = {**processes, 'os': SimpleNamespace(name='posix', getsid=session_id), 'Path': entered_monitor}
    monitor = functions('moss-monitor', ['monitor_generation'], ns)['monitor_generation']
    with pytest.raises(RuntimeError, match='重启运行时'):
        monitor()


def test_monitor_rejects_unverifiable_session_without_interrupting_process():
    def missing_session(pid):
        raise ProcessLookupError('Process exited before the session check')
    ns = {'MOSS_PROCESS': SimpleNamespace(pid=100, poll=lambda: None),
          'os': SimpleNamespace(name='posix', getsid=missing_session)}
    monitor = functions('moss-monitor', ['monitor_generation'], ns)['monitor_generation']
    with pytest.raises(RuntimeError, match='重启运行时'):
        monitor()
