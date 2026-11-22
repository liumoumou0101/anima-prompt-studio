#@title 生图运行状态（连接就绪后运行，测试期间保持此单元运行）
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
