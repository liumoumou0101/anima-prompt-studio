# 第三步：启动 ComfyUI，并显示 Colab 内置的访问链接。
import json, os, secrets, socket, subprocess, sys, tempfile, time, urllib.request
from IPython.display import display, Markdown

if not globals().get('MOSS_READY', False):
    raise RuntimeError('准备阶段未完成，请先运行前两个单元格。')
for spec in MODEL_FILES:
    if not verified(LOCAL_MODELS/spec['path'], spec):
        raise RuntimeError('本地模型校验失败，请重新运行准备阶段。')

BASE_URL = 'http://127.0.0.1:8188'
LOG_PATH = Path('/content/moss_comfyui.log')

def server_ready():
    try:
        with urllib.request.urlopen(BASE_URL+'/system_stats', timeout=2) as response:
            return 'system' in json.load(response)
    except (OSError, ValueError): return False


def runtime_identity(process):
    # Identity belongs to this actual Popen object, never to Drive or connection JSON.
    if process is None or process.poll() is not None:
        raise RuntimeError('ComfyUI 服务进程已停止，请重新运行启动单元格。')
    identity = getattr(process, '_moss_runtime_id', None)
    if (not isinstance(identity, str) or len(identity) != 64
            or any(char not in '0123456789abcdef' for char in identity)):
        raise RuntimeError('已有 ComfyUI 进程没有实例身份；请停止该笔记本进程后重新运行启动单元格。')
    return identity


MOSS_PROCESS = globals().get('MOSS_PROCESS')
if MOSS_PROCESS is not None and MOSS_PROCESS.poll() is None:
    if not server_ready(): raise RuntimeError('已有进程尚未就绪，请查看 /content/moss_comfyui.log。')
    MOSS_RUNTIME_ID = runtime_identity(MOSS_PROCESS)
    print('复用本笔记本已启动的 ComfyUI。')
    if not getattr(MOSS_PROCESS, '_moss_drive_upscalers', False):
        print('当前进程沿用旧的模型搜索路径。要使用云盘放大模型，请重启本笔记本的 ComfyUI，再运行临时连接单元格。')
else:
    # Retire our old gateway before replacing ComfyUI, so it cannot advertise an
    # old identity while forwarding requests into the new service process.
    stale_gateway = globals().get('MOSS_GATEWAY_PROCESS')
    if stale_gateway is not None and stale_gateway.poll() is None:
        stale_gateway.terminate()
        stale_gateway.wait(timeout=10)
    with socket.socket() as sock:
        sock.settimeout(1)
        if sock.connect_ex(('127.0.0.1',8188)) == 0:
            raise RuntimeError('8188 端口已被其他服务占用，未重复启动或终止它。')
    command = [sys.executable, '-u', str(PROJECT/'main.py'), '--listen','127.0.0.1','--port','8188',
               '--models-directory',str(LOCAL_MODELS),'--user-directory',str(DRIVE_ROOT/'user'),
               '--input-directory',str(DRIVE_ROOT/'input'),'--output-directory',str(DRIVE_ROOT/'output')]
    with tempfile.TemporaryDirectory(prefix='moss-model-paths-') as config_dir:
        # ComfyUI appends this search path to its local model folders. JSON is valid YAML.
        config = os.path.join(config_dir, 'gallery-model-paths.yaml')
        with open(config, 'w', encoding='utf-8') as extra:
            json.dump({'drive_gallery': {'upscale_models': str(DRIVE_ROOT / 'models' / 'upscale_models')}}, extra)
        command.extend(['--extra-model-paths-config', config])
        with LOG_PATH.open('w', encoding='utf-8') as log:
            MOSS_PROCESS = subprocess.Popen(command, cwd=PROJECT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        MOSS_PROCESS._moss_runtime_id = secrets.token_hex(32)
        MOSS_PROCESS._moss_drive_upscalers = True
        MOSS_RUNTIME_ID = runtime_identity(MOSS_PROCESS)
        deadline = time.monotonic() + 180
        while not server_ready():
            if MOSS_PROCESS.poll() is not None or time.monotonic() >= deadline:
                print(LOG_PATH.read_text(encoding='utf-8',errors='replace')[-10000:])
                raise RuntimeError('ComfyUI 启动失败或超时，请按上方日志处理后重新运行。')
            time.sleep(1)


print('ComfyUI 本地服务已就绪。下一个单元格将显示网页和 API 连接方式。')
print('ComfyUI commit:', COMFY_COMMIT)
