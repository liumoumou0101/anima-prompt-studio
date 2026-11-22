"""Reproducible, offline update of the original five-cell Colab notebook.

Never executes notebook cells, installs dependencies, contacts Drive, or reads keys.
Run: python tools/colab/update_notebook.py [input.ipynb] [output-directory]
"""
import ast
import copy
import json
from pathlib import Path
import sys
from textwrap import indent


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f'Expected exactly one original source anchor: {old[:100]!r}')
    return source.replace(old, new, 1)


STORAGE_PLAN = '''
def model_storage_plan(specs):
    # Logical verified asset bytes, not physical filesystem usage or Drive quota.
    result = dict(planned_bytes=0, local_cached_bytes=0, drive_cached_bytes=0,
                  download_bytes=0, local_new_bytes=0, drive_new_bytes=0)
    for spec in specs:
        size = spec['size_bytes']
        local_ok = verified(LOCAL_MODELS/spec['path'], spec)
        drive_ok = verified(MODEL_STORE/spec['path'], spec)
        result['planned_bytes'] += size
        result['local_cached_bytes'] += size if local_ok else 0
        result['drive_cached_bytes'] += size if drive_ok else 0
        result['download_bytes'] += size if not local_ok and not drive_ok else 0
        result['local_new_bytes'] += 0 if local_ok else size
        result['drive_new_bytes'] += 0 if drive_ok else size
    return result

'''

RUNTIME_IDENTITY = '''
def runtime_identity(process):
    # Identity belongs to this actual Popen object, never to Drive or connection JSON.
    if process is None or process.poll() is not None:
        raise RuntimeError('ComfyUI 服务进程已停止，请重新运行启动单元格。')
    identity = getattr(process, '_moss_runtime_id', None)
    if (not isinstance(identity, str) or len(identity) != 64
            or any(char not in '0123456789abcdef' for char in identity)):
        raise RuntimeError('已有 ComfyUI 进程没有实例身份；请停止该笔记本进程后重新运行启动单元格。')
    return identity

'''

GATEWAY_REUSABLE = '''
def gateway_reusable(process, source_digest, upstream_runtime_id):
    return (process is not None and process.poll() is None
            and getattr(process, '_moss_source_digest', None) == source_digest
            and getattr(process, '_moss_upstream_runtime_id', None) == upstream_runtime_id)

'''


def update_prepare(source):
    source = replace_once(source, 'import json\nfrom pathlib import PurePosixPath',
        'MODEL_ID = "按模型组" #@param ["按模型组", "moss_image_sft_int8", "anima_turbo_v1_1", "anima_aesthetic_v1_1", "anima_base_v1", "wai_anima_v1_0", "animayume_v1_5_base", "miaomiao_harem_anima_v1_6"]\nimport json\nfrom pathlib import PurePosixPath')
    source = replace_once(source, 'def select_model_assets(registry, group):',
                          'def select_model_assets(registry, group, model_id="按模型组"):')
    source = replace_once(source, "    selected=[m for m in models if family is None or m['family']==family]",
        "    if model_id == '按模型组':\n        selected=[m for m in models if family is None or m['family']==family]\n    else:\n        selected=[m for m in models if m['id']==model_id]\n        if not selected: raise ValueError('未知模型 ID，请从 MODEL_ID 列表选择。')")
    source = replace_once(source, 'select_model_assets(MODEL_REGISTRY, MODEL_GROUP)',
                          'select_model_assets(MODEL_REGISTRY, MODEL_GROUP, MODEL_ID)')
    source = replace_once(source, '\ndef prepare_environment():', '\n' + STORAGE_PLAN + '\ndef prepare_environment():')
    source = replace_once(source,
        '    total_gb = sum(spec[\'size_bytes\'] for spec in specs) / 1_000_000_000\n'
        '    print(f\'[3/4] Selected model assets: {len(specs)} files ({total_gb:.2f} GB)\', flush=True)',
        '''    plan = model_storage_plan(specs)
    print(f'[3/4] 本次准备 {len(specs)} 个去重资产，共 {plan["planned_bytes"]:,} 字节', flush=True)
    print(f'本次所选模型的已验证缓存：本地 {plan["local_cached_bytes"]:,} 字节；Drive {plan["drive_cached_bytes"]:,} 字节', flush=True)
    print(f'待准备完整资产：本地 {plan["local_new_bytes"]:,} 字节；Drive {plan["drive_new_bytes"]:,} 字节；待下载资产 {plan["download_bytes"]:,} 字节（续传可能减少实际传输）', flush=True)
    print('以上为模型逻辑字节，未计程序、下载缓存及临时副本；不是 Drive 剩余配额或精确物理新增占用。已有缓存不删除。', flush=True)''')
    start = source.index('    source = None\n    for package in')
    end = source.index("    print('准备完成。", start)
    template = source[start:end]
    helper = '''
def prepare_workflow_template(workflows):
    selected = globals().get('SELECTED_MODEL_IDS', [])
    catalog = globals().get('MODEL_REGISTRY')
    if catalog is not None and not any(
            model['family'] == 'MOSS' and model['id'] in selected for model in catalog['models']):
        print('本次未选择 MOSS，跳过 MOSS 网页模板。', flush=True)
        return
'''
    source = source[:start] + '    prepare_workflow_template(workflows)\n' + source[end:]
    source = replace_once(source, '\ndef prepare_environment():', '\n' + helper + template + '\ndef prepare_environment():')
    return source


def update_start(source):
    source = replace_once(source, 'import json, os, socket, subprocess, sys, time, urllib.request',
        'import json, os, secrets, socket, subprocess, sys, tempfile, time, urllib.request')
    source = replace_once(source, 'command = [sys.executable, str(PROJECT',
                          "command = [sys.executable, '-u', str(PROJECT")
    source = replace_once(source,
        'MOSS_PROCESS = subprocess.Popen(command, cwd=PROJECT, stdout=log, stderr=subprocess.STDOUT)',
        'MOSS_PROCESS = subprocess.Popen(command, cwd=PROJECT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)')
    source = replace_once(source, '\nMOSS_PROCESS = globals().get', '\n' + RUNTIME_IDENTITY + '\nMOSS_PROCESS = globals().get')
    source = replace_once(source, "    print('复用本笔记本已启动的 ComfyUI。')",
        """    MOSS_RUNTIME_ID = runtime_identity(MOSS_PROCESS)
    print('复用本笔记本已启动的 ComfyUI。')
    if not getattr(MOSS_PROCESS, '_moss_drive_upscalers', False):
        print('当前进程沿用旧的模型搜索路径。要使用云盘放大模型，请重启本笔记本的 ComfyUI，再运行临时连接单元格。')""")
    source = replace_once(source, 'else:\n    with socket.socket() as sock:',
        '''else:
    # Retire our old gateway before replacing ComfyUI, so it cannot advertise an
    # old identity while forwarding requests into the new service process.
    stale_gateway = globals().get('MOSS_GATEWAY_PROCESS')
    if stale_gateway is not None and stale_gateway.poll() is None:
        stale_gateway.terminate()
        stale_gateway.wait(timeout=10)
    with socket.socket() as sock:''')
    source = replace_once(source, '    deadline = time.monotonic() + 180',
        "    MOSS_PROCESS._moss_runtime_id = secrets.token_hex(32)\n    MOSS_PROCESS._moss_drive_upscalers = True\n    MOSS_RUNTIME_ID = runtime_identity(MOSS_PROCESS)\n    deadline = time.monotonic() + 180")
    start = source.index('    with LOG_PATH.open(')
    end = source.index('        time.sleep(1)\n', start) + len('        time.sleep(1)\n')
    launch = source[start:end]
    source = replace_once(source, launch, """    with tempfile.TemporaryDirectory(prefix='moss-model-paths-') as config_dir:
        # ComfyUI appends this search path to its local model folders. JSON is valid YAML.
        config = os.path.join(config_dir, 'gallery-model-paths.yaml')
        with open(config, 'w', encoding='utf-8') as extra:
            json.dump({'drive_gallery': {'upscale_models': str(DRIVE_ROOT / 'models' / 'upscale_models')}}, extra)
        command.extend(['--extra-model-paths-config', config])
""" + indent(launch, '    '))
    return source


def update_gateway(source):
    # Keep the complete asset service in a normal, testable source file and
    # embed it in the generated gateway. Colab needs no extra local imports.
    lora_helpers = (Path(__file__).resolve().parent / 'lora_gateway.py').read_text(encoding='utf-8')
    source = replace_once(source, '\ndef create_app(', '\n' + lora_helpers + '\n\ndef create_app(')
    source = replace_once(source,
        '    app.router.add_route("*", "/{tail:.*}", proxy)',
        '    register_lora_routes(app, model_root, catalog_path)\n'
        '    app.router.add_route("*", "/{tail:.*}", proxy)')
    source = replace_once(source, 'catalog_path=None, model_root=None):',
                          'catalog_path=None, model_root=None, runtime_id=None):')
    source = replace_once(source, '    @web.middleware\n', '''    runtime_id = runtime_id if runtime_id is not None else os.environ.get("MOSS_RUNTIME_ID", "")
    if (not isinstance(runtime_id, str) or len(runtime_id) > 128
            or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for char in runtime_id)):
        raise ValueError("Invalid runtime identity")

    @web.middleware
''')
    source = replace_once(source,
        '''        return web.json_response({"service": "moss-comfyui-gateway", "version": 1,
                                  "auth": "bearer-or-browser-session", "upstream": "ComfyUI"},
                                 headers=NO_STORE)''',
        '''        payload = {"service": "moss-comfyui-gateway", "version": 1,
                   "auth": "bearer-or-browser-session", "upstream": "ComfyUI"}
        if runtime_id:
            payload["runtime_id"] = runtime_id
        return web.json_response(payload, headers=NO_STORE)''')
    return source


def update_cloud_api(source):
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'GATEWAY_SOURCE' for t in n.targets))
    lines = source.splitlines(keepends=True)
    gateway = update_gateway(ast.literal_eval(node.value))
    compile(gateway, 'embedded-gateway', 'exec')
    lines[node.lineno - 1:node.end_lineno] = ['GATEWAY_SOURCE = ' + repr(gateway) + '\n']
    source = ''.join(lines)
    source = replace_once(source,
        "MOSS_GATEWAY_PROCESS = subprocess.Popen([sys.executable,str(source_path),'--port','8190','--upstream',BASE_URL],env=environment,stdout=log,stderr=subprocess.STDOUT)",
        "MOSS_GATEWAY_PROCESS = subprocess.Popen([sys.executable,str(source_path),'--port','8190','--upstream',BASE_URL],env=environment,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)")
    source = replace_once(source,
        "MOSS_TUNNEL_PROCESS = subprocess.Popen([str(binary),'--no-autoupdate','tunnel','--url',GATEWAY_URL,'--protocol','http2'],stdout=log,stderr=subprocess.STDOUT)",
        "MOSS_TUNNEL_PROCESS = subprocess.Popen([str(binary),'--no-autoupdate','tunnel','--url',GATEWAY_URL,'--protocol','http2'],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)")
    source = replace_once(source, '\ndef gateway_ready(key):', '\n' + GATEWAY_REUSABLE + '\ndef gateway_ready(key):')
    source = replace_once(source,
        "            return json.load(response).get('service') == 'moss-comfyui-gateway'",
        "            info = json.load(response)\n            return (info.get('service') == 'moss-comfyui-gateway'\n                    and info.get('runtime_id') == runtime_identity(globals().get('MOSS_PROCESS')))")
    source = replace_once(source, '    except (OSError,ValueError): return False',
                          '    except (OSError,ValueError,RuntimeError): return False')
    source = replace_once(source, "    api_dir = DRIVE_ROOT/'api'",
        "    runtime_id = runtime_identity(globals().get('MOSS_PROCESS'))\n    api_dir = DRIVE_ROOT/'api'")
    source = replace_once(source, "        if globals().get('MOSS_GATEWAY_DIGEST') != digest:",
        '        if not gateway_reusable(process, digest, runtime_id):')
    source = replace_once(source,
        "MOSS_MODEL_CATALOG=str(DRIVE_ROOT/'model_registry.json'),MOSS_MODEL_ROOT=str(LOCAL_MODELS))",
        "MOSS_MODEL_CATALOG=str(DRIVE_ROOT/'model_registry.json'),MOSS_MODEL_ROOT=str(LOCAL_MODELS),\n                       MOSS_RUNTIME_ID=runtime_id)")
    source = replace_once(source, '    MOSS_GATEWAY_DIGEST = digest',
        '    MOSS_GATEWAY_PROCESS._moss_source_digest = digest\n    MOSS_GATEWAY_PROCESS._moss_upstream_runtime_id = runtime_id\n    MOSS_GATEWAY_DIGEST = digest')
    source = replace_once(source,
        "                if json.load(response).get('service') != 'moss-comfyui-gateway': raise ValueError('Unexpected response')",
        "                info = json.load(response)\n                if (info.get('service') != 'moss-comfyui-gateway'\n                        or info.get('runtime_id') != runtime_identity(globals().get('MOSS_PROCESS'))):\n                    raise ValueError('Unexpected gateway runtime identity')")
    source = replace_once(source, "'model_catalog':'/_moss/models'}",
        "'model_catalog':'/_moss/models','runtime_id':runtime_identity(globals().get('MOSS_PROCESS'))}")
    return source


TRANSFORMS = {'moss-prepare': update_prepare, 'moss-start': update_start, 'moss-cloud-api': update_cloud_api}


GENERATION_MONITOR = r'''#@title 生图运行状态（连接就绪后运行，测试期间保持此单元运行）
MONITOR_MINUTES = 120 #@param {type:"integer"}
import html, json, os, time, urllib.request
from collections import deque
from pathlib import Path
from IPython.display import display, HTML


def read_generation_log(stream, path):
    size = path.stat().st_size
    if size < stream.tell():
        stream.seek(0)
    if size - stream.tell() > 65536:
        stream.seek(size - 65536)
    text = stream.read(65536).decode('utf-8', errors='replace')
    return [line for line in text.splitlines() if line.strip()]


def monitor_generation(duration_minutes=120, poll_seconds=2):
    if not 1 <= duration_minutes <= 1440:
        raise ValueError('观察时长请填写 1 至 1440 分钟。')
    process = globals().get('MOSS_PROCESS')
    if process is None or process.poll() is not None:
        raise RuntimeError('ComfyUI 尚未启动，请先运行启动和云端连接单元格。')
    if os.name == 'posix':
        for name, label in (('MOSS_PROCESS', 'ComfyUI'), ('MOSS_GATEWAY_PROCESS', '认证网关'),
                            ('MOSS_TUNNEL_PROCESS', '临时连接')):
            background = globals().get(name)
            if background is None or background.poll() is not None:
                continue
            pid = getattr(background, 'pid', None)
            try:
                isolated = type(pid) is int and pid > 0 and os.getsid(pid) == pid
            except (OSError, ValueError):
                isolated = False
            if not isolated:
                raise RuntimeError(label + ' 未使用独立进程会话，停止监控可能中断后台任务。'
                                   '请在任务完成后重启运行时，并重新运行准备、启动和云端连接单元格，再开启监控。')
    log_path = Path(globals().get('LOG_PATH', '/content/moss_comfyui.log'))
    recent = deque(maxlen=20)
    panel = display(HTML('<pre>正在读取生图状态……</pre>'), display_id=True)
    active_since = None
    previous_status = None
    last_output = float('-inf')
    status = '正在读取生图状态'
    deadline = time.monotonic() + duration_minutes * 60

    def render(message):
        content = '\n'.join([time.strftime('%H:%M:%S') + '  ' + message, '', *recent])
        panel.update(HTML('<pre style="white-space:pre-wrap;max-height:32em;overflow:auto">'
                          + html.escape(content) + '</pre>'))

    try:
        with log_path.open('rb') as log:
            log.seek(0, 2)
            while process.poll() is None and time.monotonic() < deadline:
                now = time.monotonic()
                active = False
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8188/queue', timeout=3) as response:
                        queue = json.load(response)
                    running, pending = queue['queue_running'], queue['queue_pending']
                    if not isinstance(running, list) or not isinstance(pending, list):
                        raise ValueError('Invalid queue response')
                    active = bool(running)
                    if active:
                        if active_since is None:
                            active_since = now
                        elapsed = int(now - active_since)
                        status = f'执行 {len(running)} 个任务，排队 {len(pending)} 个'
                        message = f'{status}；本轮连续执行已观察 {elapsed} 秒'
                    else:
                        active_since = None
                        status = f'排队 {len(pending)} 个任务，等待执行' if pending else '当前空闲，等待工作台提交任务'
                        message = status
                except (OSError, ValueError, KeyError, TypeError):
                    status = '暂时无法读取队列，继续观察日志并重试'
                    message = status
                lines = read_generation_log(log, log_path)
                recent.extend(line[:2000] for line in lines)
                if lines or status != previous_status or (active and now - last_output >= 15):
                    render(message)
                    previous_status, last_output = status, now
                time.sleep(poll_seconds)
            recent.extend(line[:2000] for line in read_generation_log(log, log_path))
            if process.poll() is None:
                render('本次观察时段已结束。后台服务仍在运行；再次运行本单元可继续查看。')
            else:
                render('ComfyUI 服务进程已结束，请查看最后的日志并重新启动服务。')
    except KeyboardInterrupt:
        render('监控已停止。请确认后台服务状态；再次运行本单元即可继续查看。')


monitor_generation(MONITOR_MINUTES)
'''


def add_generation_monitor(original):
    notebook = copy.deepcopy(original)
    matches = [cell for cell in notebook['cells'] if cell.get('metadata', {}).get('id') == 'moss-monitor']
    if len(matches) > 1:
        raise ValueError('Duplicate cell ID: moss-monitor')
    compile(GENERATION_MONITOR, 'moss-monitor', 'exec')
    cell = {'cell_type': 'code', 'metadata': {'id': 'moss-monitor', 'cellView': 'form'},
            'source': GENERATION_MONITOR.splitlines(keepends=True), 'outputs': [], 'execution_count': None}
    if matches:
        notebook['cells'][notebook['cells'].index(matches[0])] = cell
    else:
        notebook['cells'].append(cell)
    return notebook


def update_notebook(original):
    notebook = copy.deepcopy(original)
    found = set()
    for cell in notebook['cells']:
        identifier = cell.get('metadata', {}).get('id')
        if identifier in TRANSFORMS:
            if identifier in found:
                raise ValueError(f'Duplicate cell ID: {identifier}')
            source = TRANSFORMS[identifier](''.join(cell['source']))
            compile(source, identifier, 'exec')
            cell['source'] = source.splitlines(keepends=True)
            found.add(identifier)
        if cell['cell_type'] == 'code':
            cell['outputs'] = []
            cell['execution_count'] = None
    if found != set(TRANSFORMS):
        raise ValueError('Expected all three original notebook cell IDs')
    return add_generation_monitor(notebook)


def main():
    home = Path(__file__).resolve().parent
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else home / 'original.ipynb'
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else home
    notebook = update_notebook(json.loads(input_path.read_text(encoding='utf-8')))
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'MOSS_ComfyUI_OneClick.ipynb').write_text(
        json.dumps(notebook, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for cell in notebook['cells']:
        identifier = cell.get('metadata', {}).get('id')
        if identifier in TRANSFORMS or identifier == 'moss-monitor':
            (output_dir / (identifier + '.py')).write_text(''.join(cell['source']), encoding='utf-8')
    print('Wrote updated notebook, three replacement cells and generation monitor (no execution).')


if __name__ == '__main__':
    main()
