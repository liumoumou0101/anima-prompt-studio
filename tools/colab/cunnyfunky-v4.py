#@title CunnyFunky v4 画风对照实验（同一提示词和种子，约 350 MiB LoRA）
def run_cunnyfunky_v4():
    import copy
    import hashlib
    import json
    import os
    import tempfile
    import time
    import urllib.error
    import urllib.parse
    import urllib.request
    import uuid
    from datetime import datetime, timezone
    from pathlib import Path
    from PIL import Image, ImageDraw, ImageFont
    from IPython.display import display

    name = 'cf_style_v4.safetensors'
    size = 367103160
    digest = 'e454687f9b4585282225774fb53800a3e30643f9686ee02f0a7af357204d871f'
    download = 'https://civitai.red/api/download/models/3321859'
    loopback = 'http://127.0.0.1:8188'
    process = globals().get('MOSS_PROCESS')
    if process is None or process.poll() is not None:
        raise RuntimeError('请先准备 ANIMA Turbo 1.1 并启动本笔记本的 ComfyUI。')
    if not os.path.ismount('/content/drive') or not Path('/content/drive/MyDrive').is_dir():
        raise RuntimeError('请先挂载 Google Drive。')
    drive_root = Path(globals().get('DRIVE_ROOT', '/content/drive/MyDrive/ComfyUI_Colab'))
    models = Path(globals().get('LOCAL_MODELS', '/content/moss_models'))
    log_path = Path(globals().get('LOG_PATH', '/content/moss_comfyui.log'))

    def api(path, payload=None):
        body = None if payload is None else json.dumps(payload).encode('utf-8')
        request = urllib.request.Request(loopback + path, data=body,
                                         headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)

    api('/system_stats')
    unet, encoder, vae = 'anima-turbo-v1.1.safetensors', 'qwen_3_06b_base.safetensors', 'qwen_image_vae.safetensors'
    for folder, filename in [('diffusion_models', unet), ('text_encoders', encoder), ('vae', vae)]:
        if not (models / folder / filename).is_file():
            raise RuntimeError(f'请先在准备模型单元选择 ANIMA Turbo 1.1。缺少 {folder}/{filename}')

    def verified(path):
        if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
            return False
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest() == digest

    def install(target, source):
        if verified(target):
            print(f'已校验并复用 {target}', flush=True)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f'正在准备 {target}', flush=True)
        part = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, suffix='.part', delete=False) as output:
                part = Path(output.name)
                check = hashlib.sha256()
                count = 0
                previous = time.monotonic()
                with source() as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        count += len(block)
                        if count > size:
                            raise ValueError('LoRA 文件大于发布版本的大小。')
                        check.update(block)
                        output.write(block)
                        if time.monotonic() - previous >= 15:
                            print(f'已写入 {count / size:.0%}', flush=True)
                            previous = time.monotonic()
            if count != size or check.hexdigest() != digest:
                raise ValueError('LoRA 文件大小或 SHA-256 与发布版本不符。')
            part.replace(target)
            print(f'LoRA 校验通过：{target.name}', flush=True)
        finally:
            if part is not None:
                part.unlink(missing_ok=True)

    cached = drive_root / 'models' / 'loras' / name
    request = urllib.request.Request(download, headers={'User-Agent': 'Mozilla/5.0', 'Accept': '*/*'})
    install(cached, lambda: urllib.request.urlopen(request, timeout=90))
    install(models / 'loras' / name, lambda: cached.open('rb'))
    choices = api('/object_info/LoraLoader')['LoraLoader']['input']['required']['lora_name'][0]
    if name not in choices:
        raise RuntimeError(f'ComfyUI 的 LoraLoader 尚未识别 {name}，请检查本地模型目录。')

    # Same café prompt as the published sample (Civitai image 142625063).
    positive = ('CF, safe, masterpiece, best quality, 1girl, solo, (adult woman:1.3), light brown hair, '
                'long hair, neat hair, casual clothes, white cardigan, sweater, holding coffee cup, '
                'sitting at table, cafe interior, warm light, smile, looking at viewer')
    negative = 'lowres, bad anatomy, bad hands, text, error, worst quality, low quality, blurry, nsfw, explicit, nude'

    def node(kind, **inputs):
        return {'class_type': kind, 'inputs': inputs}

    graph = {
        '1': node('UNETLoader', unet_name=unet, weight_dtype='default'),
        '2': node('ModelSamplingAuraFlow', model=['12', 0], shift=3.0),
        '3': node('CLIPLoader', clip_name=encoder, type='stable_diffusion', device='default'),
        '4': node('CLIPTextEncode', clip=['12', 1], text=positive),
        '5': node('CLIPTextEncode', clip=['12', 1], text=negative),
        '6': node('EmptyLatentImage', width=832, height=1216, batch_size=1),
        '7': node('KSampler', model=['2', 0], positive=['4', 0], negative=['5', 0], latent_image=['6', 0],
                  seed=4444, steps=8, cfg=1.0, sampler_name='euler', scheduler='simple', denoise=1.0),
        '8': node('VAELoader', vae_name=vae),
        '9': node('VAEDecode', samples=['7', 0], vae=['8', 0]),
        '10': node('SaveImage', images=['9', 0], filename_prefix='CFv4'),
        '12': node('LoraLoader', model=['1', 0], clip=['3', 0], lora_name=name,
                   strength_model=0.0, strength_clip=0.0),
    }
    state = globals().get('CUNNYFUNKY_V4_AB_STATE')
    if state is None or state['process'] is not process:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        folder = drive_root / 'research' / 'cunnyfunky_v4' / stamp
        folder.mkdir(parents=True, exist_ok=False)
        state = {'process': process, 'client': str(uuid.uuid4()), 'folder': folder, 'jobs': {}}
        globals()['CUNNYFUNKY_V4_AB_STATE'] = state
    folder = state['folder']
    print(f'本次结果目录：{folder}', flush=True)

    def save_json(path, data):
        part = path.with_suffix('.json.part')
        part.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        part.replace(path)

    def tail(log, offset):
        if not log.is_file():
            return '', offset
        with log.open('rb') as stream:
            end = stream.seek(0, 2)
            stream.seek(max(offset if end >= offset else 0, end - 8192))
            lines = stream.read().decode('utf-8', 'replace').splitlines()
        return next((line.strip()[:500] for line in reversed(lines) if line.strip()), ''), end

    def wait_for_image(label, job_id):
        started = time.monotonic()
        reported = started - 15
        offset = log_path.stat().st_size if log_path.exists() else 0
        while time.monotonic() - started < 1200:
            if process.poll() is not None:
                raise RuntimeError('ComfyUI 已停止，请查看服务日志。')
            try:
                entry = api('/history/' + urllib.parse.quote(job_id, safe='')).get(job_id)
                detail = ''
            except (OSError, ValueError) as exc:
                entry = None
                detail = f'历史查询暂未成功：{exc}'
            if entry:
                save_json(folder / f'{label}-history.json', entry)
                status = entry.get('status', {})
                if status.get('status_str') == 'error':
                    errors = [v.get('exception_message') for k, v in status.get('messages', [])
                              if k == 'execution_error' and isinstance(v, dict)]
                    raise RuntimeError(f'{label} 执行失败：{errors or status.get("messages")}')
                if status.get('completed'):
                    images = entry.get('outputs', {}).get('10', {}).get('images', [])
                    if status.get('status_str') != 'success' or len(images) != 1:
                        raise RuntimeError(f'{label} 的历史记录未包含一张成功输出的图片。')
                    return images[0]
            now = time.monotonic()
            if now - reported >= 15:
                latest, offset = tail(log_path, offset)
                print(f'{label} 已观察 {int(now - started)} 秒  {detail or latest or "等待 ComfyUI 完成"}', flush=True)
                reported = now
            time.sleep(2)
        raise TimeoutError(f'{label} 等待超时。可重跑本单元继续查询同一任务 {job_id}。')

    for label, strength in [('OFF', 0.0), ('ON', 1.0)]:
        variant = copy.deepcopy(graph)
        variant['12']['inputs'].update(strength_model=strength, strength_clip=strength)
        variant['10']['inputs']['filename_prefix'] = f'CFv4_{folder.name}_{label}'
        save_json(folder / f'{label}-workflow_api.json', variant)
        jobs = state['jobs']
        if label not in jobs:
            # Set the requested ID BEFORE POST. On a lost response/interrupt, poll that ID on re-run.
            jobs[label] = str(uuid.uuid4())
            try:
                result = api('/prompt', {'prompt': variant, 'client_id': state['client'], 'prompt_id': jobs[label]})
            except urllib.error.HTTPError as exc:
                if exc.code == 400:
                    del jobs[label]  # Explicit validation rejection, never queued.
                    raise RuntimeError('工作流校验被拒绝：' + exc.read(1600).decode('utf-8', 'replace')) from exc
                raise
            jobs[label] = result['prompt_id']
        print(f'{label} 任务 {jobs[label]}', flush=True)
        image = wait_for_image(label, jobs[label])
        query = urllib.parse.urlencode({key: image[key] for key in ('filename', 'subfolder', 'type')})
        part = folder / f'{label}.png.part'
        with urllib.request.urlopen(loopback + '/view?' + query, timeout=90) as response:
            part.write_bytes(response.read())
        with Image.open(part) as picture:
            if picture.format != 'PNG' or picture.size != (832, 1216):
                raise ValueError(f'{label} 返回的图片格式或尺寸不符。')
            picture.verify()
        part.replace(folder / f'{label}.png')
        print(f'{label} 原图已保存。', flush=True)

    comparison = Image.new('RGB', (1664, 1272), 'white')
    draw = ImageDraw.Draw(comparison)
    try:
        font = ImageFont.truetype('DejaVuSans.ttf', 30)
    except OSError:
        font = ImageFont.load_default()
    for index, label in enumerate(('OFF', 'ON')):
        x = index * 832
        draw.text((x + 16, 7), f'LoRA {label}  |  weight {index}.0', fill='black', font=font)
        with Image.open(folder / f'{label}.png') as picture:
            comparison.paste(picture.convert('RGB'), (x, 56))
    comparison.save(folder / 'OFF-vs-ON.png')
    save_json(folder / 'manifest.json', {
        'lora': name, 'sha256': digest, 'size_bytes': size, 'source': download, 'model': unet,
        'sample': 'https://civitai.com/images/142625063', 'shift': 3, 'seed': 4444, 'steps': 8,
        'sampler': 'euler', 'scheduler': 'simple', 'cfg': 1.0, 'width': 832, 'height': 1216,
        'variants': {label: {'strength_model': value, 'strength_clip': value, 'prompt_id': state['jobs'][label],
                             'workflow': f'{label}-workflow_api.json', 'history': f'{label}-history.json',
                             'image': f'{label}.png'} for label, value in [('OFF', 0.0), ('ON', 1.0)]},
        'comparison': 'OFF-vs-ON.png',
    })
    print(f'对照实验完成，已保存到 {folder}', flush=True)
    display(comparison.resize((832, 636), Image.Resampling.LANCZOS))


run_cunnyfunky_v4()
