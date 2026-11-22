#@title 2. 准备模型库
MODEL_GROUP = "全部" #@param ["全部", "仅 ANIMA", "仅 MOSS"]
MODEL_ID = "按模型组" #@param ["按模型组", "moss_image_sft_int8", "anima_turbo_v1_1", "anima_aesthetic_v1_1", "anima_base_v1", "wai_anima_v1_0", "animayume_v1_5_base", "miaomiao_harem_anima_v1_6"]
import json
from pathlib import PurePosixPath

MODEL_GROUPS={'全部':None,'仅 ANIMA':'ANIMA','仅 MOSS':'MOSS'}

def select_model_assets(registry, group, model_id="按模型组"):
    if group not in MODEL_GROUPS:
        raise ValueError('未知模型组，请选择全部、仅 ANIMA 或仅 MOSS。')
    if registry.get('schema_version')!=1:
        raise ValueError('模型目录版本不受支持。')
    files=registry['files']; models=registry['models']
    asset_map={item['path']:item for item in files}
    if len(asset_map)!=len(files) or len({m['id'] for m in models})!=len(models):
        raise ValueError('模型目录含重复的路径或 ID。')
    for path in asset_map:
        p=PurePosixPath(path)
        if p.is_absolute() or '..' in p.parts or '\\' in path:
            raise ValueError('模型目录含非法资产路径。')
    family=MODEL_GROUPS[group]
    if model_id == '按模型组':
        selected=[m for m in models if family is None or m['family']==family]
    else:
        selected=[m for m in models if m['id']==model_id]
        if not selected: raise ValueError('未知模型 ID，请从 MODEL_ID 列表选择。')
    if not selected: raise ValueError('本次模型组为空。')
    required={path for m in selected for path in m['assets']}
    if not required.issubset(asset_map): raise ValueError('模型目录缺少依赖资产。')
    return [m['id'] for m in selected],[f for f in files if f['path'] in required]

MODEL_REGISTRY = json.loads('{\n  "schema_version": 1,\n  "checked_at": "2026-10-26",\n  "models": [\n    {\n      "id": "moss_image_sft_int8",\n      "display_name": "MOSS-Image INT8",\n      "family": "MOSS",\n      "version": "SFT INT8",\n      "checkpoint": "diffusion_models/moss_image_sft_int8_convrot.safetensors",\n      "text_encoder": "text_encoders/qwen3.5_9b_w4a8_gptq.safetensors",\n      "vae": "vae/flux2-vae_small.safetensors",\n      "assets": [\n        "diffusion_models/moss_image_sft_int8_convrot.safetensors",\n        "text_encoders/qwen3.5_9b_w4a8_gptq.safetensors",\n        "vae/flux2-vae_small.safetensors"\n      ],\n      "suggested_defaults": {\n        "steps": 25,\n        "cfg": 2.5,\n        "sampler": "er_sde",\n        "scheduler": "simple"\n      },\n      "notes": ""\n    },\n    {\n      "id": "anima_turbo_v1_1",\n      "display_name": "ANIMA Turbo v1.1",\n      "family": "ANIMA",\n      "version": "v1.1",\n      "checkpoint": "diffusion_models/anima-turbo-v1.1.safetensors",\n      "text_encoder": "text_encoders/qwen_3_06b_base.safetensors",\n      "vae": "vae/qwen_image_vae.safetensors",\n      "assets": [\n        "diffusion_models/anima-turbo-v1.1.safetensors",\n        "text_encoders/qwen_3_06b_base.safetensors",\n        "vae/qwen_image_vae.safetensors"\n      ],\n      "suggested_defaults": {\n        "steps": 10,\n        "cfg": 1,\n        "sampler": "euler",\n        "scheduler": "normal"\n      },\n      "notes": "快速预览；蒸馏版。"\n    },\n    {\n      "id": "anima_aesthetic_v1_1",\n      "display_name": "ANIMA Aesthetic v1.1",\n      "family": "ANIMA",\n      "version": "v1.1",\n      "checkpoint": "diffusion_models/anima-aesthetic-v1.1.safetensors",\n      "text_encoder": "text_encoders/qwen_3_06b_base.safetensors",\n      "vae": "vae/qwen_image_vae.safetensors",\n      "assets": [\n        "diffusion_models/anima-aesthetic-v1.1.safetensors",\n        "text_encoders/qwen_3_06b_base.safetensors",\n        "vae/qwen_image_vae.safetensors"\n      ],\n      "suggested_defaults": {\n        "steps": 35,\n        "cfg": 4.5,\n        "sampler": "er_sde",\n        "scheduler": "normal"\n      },\n      "notes": "默认插画审美；官方版本。"\n    },\n    {\n      "id": "anima_base_v1",\n      "display_name": "ANIMA Base v1.0",\n      "family": "ANIMA",\n      "version": "v1.0",\n      "checkpoint": "diffusion_models/anima-base-v1.0.safetensors",\n      "text_encoder": "text_encoders/qwen_3_06b_base.safetensors",\n      "vae": "vae/qwen_image_vae.safetensors",\n      "assets": [\n        "diffusion_models/anima-base-v1.0.safetensors",\n        "text_encoders/qwen_3_06b_base.safetensors",\n        "vae/qwen_image_vae.safetensors"\n      ],\n      "suggested_defaults": {\n        "steps": 35,\n        "cfg": 4.5,\n        "sampler": "er_sde",\n        "scheduler": "normal"\n      },\n      "notes": "官方基础模型；用于风格、LoRA 对照。"\n    },\n    {\n      "id": "wai_anima_v1_0",\n      "display_name": "WAI-ANIMA v1.0",\n      "family": "ANIMA",\n      "version": "v1.0 Base 1.0",\n      "checkpoint": "diffusion_models/waiANIMA_v10Base10.safetensors",\n      "text_encoder": "text_encoders/qwen_3_06b_base.safetensors",\n      "vae": "vae/qwen_image_vae.safetensors",\n      "assets": [\n        "diffusion_models/waiANIMA_v10Base10.safetensors",\n        "text_encoders/qwen_3_06b_base.safetensors",\n        "vae/qwen_image_vae.safetensors"\n      ],\n      "suggested_defaults": {\n        "steps": 25,\n        "cfg": 4.5,\n        "sampler": "euler_ancestral",\n        "scheduler": "normal"\n      },\n      "notes": "社区模型；镜像字节大小与完整 SHA-256 对照作者文件。"\n    },\n    {\n      "id": "animayume_v1_5_base",\n      "display_name": "AnimaYume v1.5 Base",\n      "family": "ANIMA",\n      "version": "v1.5 Base",\n      "checkpoint": "diffusion_models/AnimaYume_v15_base.safetensors",\n      "text_encoder": "text_encoders/qwen_3_06b_base.safetensors",\n      "vae": "vae/qwen_image_vae.safetensors",\n      "assets": [\n        "diffusion_models/AnimaYume_v15_base.safetensors",\n        "text_encoders/qwen_3_06b_base.safetensors",\n        "vae/qwen_image_vae.safetensors"\n      ],\n      "suggested_defaults": {\n        "steps": 30,\n        "cfg": 5,\n        "sampler": "euler_ancestral",\n        "scheduler": "normal"\n      },\n      "notes": "复杂描述；旧版 LoRA 需要重新验证。"\n    },\n    {\n      "id": "miaomiao_harem_anima_v1_6",\n      "display_name": "MiaoMiao Harem ANIMA v1.6",\n      "family": "ANIMA",\n      "version": "Anima 1.6",\n      "checkpoint": "diffusion_models/miaomiaoHarem_anima16.safetensors",\n      "text_encoder": "text_encoders/qwen_3_06b_base.safetensors",\n      "vae": "vae/qwen_image_vae.safetensors",\n      "assets": [\n        "diffusion_models/miaomiaoHarem_anima16.safetensors",\n        "text_encoders/qwen_3_06b_base.safetensors",\n        "vae/qwen_image_vae.safetensors"\n      ],\n      "suggested_defaults": {\n        "steps": 35,\n        "cfg": 4.5,\n        "sampler": "er_sde",\n        "scheduler": "normal"\n      },\n      "notes": "保留已采用的 2B 分支，不自动替换为 2.9B Beta。"\n    }\n  ],\n  "files": [\n    {\n      "path": "diffusion_models/moss_image_sft_int8_convrot.safetensors",\n      "repo_id": "Comfy-Org/MOSS-Image",\n      "repo_file": "diffusion_models/moss_image_sft_int8_convrot.safetensors",\n      "revision": "24147db865fcdc207270f844777587223fed8d6e",\n      "size_bytes": 5413698958,\n      "sha256": "b4d1475bc7eeffd7b809e82ea13a1fba1fb85c4e18365af3813722faa5c0fe4f"\n    },\n    {\n      "path": "text_encoders/qwen3.5_9b_w4a8_gptq.safetensors",\n      "repo_id": "Comfy-Org/MOSS-Image",\n      "repo_file": "text_encoders/qwen3.5_9b_w4a8_gptq.safetensors",\n      "revision": "24147db865fcdc207270f844777587223fed8d6e",\n      "size_bytes": 7343591088,\n      "sha256": "4cc6a1543ad2061806da46f35f90cadb4801dcba246c44782cf42ec0feb6407c"\n    },\n    {\n      "path": "vae/flux2-vae_small.safetensors",\n      "repo_id": "Comfy-Org/MOSS-Image",\n      "repo_file": "vae/flux2-vae_small.safetensors",\n      "revision": "24147db865fcdc207270f844777587223fed8d6e",\n      "size_bytes": 249521340,\n      "sha256": "d8d52ba036475f5fb07c8b435e176d3d97ebfa82f0d1a1c317f9cc1e25bd013b"\n    },\n    {\n      "path": "diffusion_models/anima-base-v1.0.safetensors",\n      "repo_id": "circlestone-labs/Anima",\n      "repo_file": "split_files/diffusion_models/anima-base-v1.0.safetensors",\n      "revision": "f973fc41ec7545364ac9776c2440285f43ff2a30",\n      "size_bytes": 4182218328,\n      "sha256": "bd43b7cffe1ed1153d9c41e7beb2f18cb1273eafbaa3af3edd6a173dc90a006e"\n    },\n    {\n      "path": "diffusion_models/anima-aesthetic-v1.1.safetensors",\n      "repo_id": "circlestone-labs/Anima",\n      "repo_file": "split_files/diffusion_models/anima-aesthetic-v1.1.safetensors",\n      "revision": "f973fc41ec7545364ac9776c2440285f43ff2a30",\n      "size_bytes": 4182230656,\n      "sha256": "3c1868387a3a1ff504bbb87c33678321965ead381fcf87afbd0264daa600c082"\n    },\n    {\n      "path": "diffusion_models/anima-turbo-v1.1.safetensors",\n      "repo_id": "circlestone-labs/Anima",\n      "repo_file": "split_files/diffusion_models/anima-turbo-v1.1.safetensors",\n      "revision": "f973fc41ec7545364ac9776c2440285f43ff2a30",\n      "size_bytes": 4182230656,\n      "sha256": "fba11953276b57edf59d1dc4f1857ac05aa079c56f982b4d7c20298d57d3f7eb"\n    },\n    {\n      "path": "text_encoders/qwen_3_06b_base.safetensors",\n      "repo_id": "circlestone-labs/Anima",\n      "repo_file": "split_files/text_encoders/qwen_3_06b_base.safetensors",\n      "revision": "f973fc41ec7545364ac9776c2440285f43ff2a30",\n      "size_bytes": 1192135096,\n      "sha256": "cd2a512003e2f9f3cd3c32a9c3573f820bb28c940f73c57b1ddaa983d9223eba"\n    },\n    {\n      "path": "vae/qwen_image_vae.safetensors",\n      "repo_id": "circlestone-labs/Anima",\n      "repo_file": "split_files/vae/qwen_image_vae.safetensors",\n      "revision": "f973fc41ec7545364ac9776c2440285f43ff2a30",\n      "size_bytes": 253806246,\n      "sha256": "a70580f0213e67967ee9c95f05bb400e8fb08307e017a924bf3441223e023d1f"\n    },\n    {\n      "path": "diffusion_models/waiANIMA_v10Base10.safetensors",\n      "repo_id": "kaibara/WAI-ANIMA",\n      "repo_file": "waiANIMA_v10Base10.safetensors",\n      "revision": "f328985446678f0b60e1c4e2645fd563aa69b4ff",\n      "size_bytes": 4182233976,\n      "sha256": "9d5a1e1393c2978d6a979fab38fb0dee00bc2a94e354196c9f3cf2f6f56d5fbf",\n      "source_url": "https://civitai.red/models/2544636/wai-anima",\n      "mirror_hash_matched_to_publisher": true\n    },\n    {\n      "path": "diffusion_models/AnimaYume_v15_base.safetensors",\n      "repo_id": "duongve/AnimaYume",\n      "repo_file": "split_files/diffusion_models/AnimaYume_v15_base.safetensors",\n      "revision": "e6d0f401dedb712a0a1b9620cd926ccf99c8ece3",\n      "size_bytes": 4182218328,\n      "sha256": "16354589c360b1690842c4c4d04046c35ad4de4516b15a06ac7aa350dc3265f2",\n      "source_url": "https://huggingface.co/duongve/AnimaYume"\n    },\n    {\n      "path": "diffusion_models/miaomiaoHarem_anima16.safetensors",\n      "repo_id": "icekinfe/civitai_models",\n      "repo_file": "miaomiaoHarem_anima16.safetensors",\n      "revision": "09873412000c699868b4961a678ab47a2dfbab32",\n      "size_bytes": 4182218328,\n      "sha256": "6bbb6b6785b4eb0df467658ce47f5f52f1d11fe992b1375b3c67ff02becf193b",\n      "source_url": "https://civitai.red/models/934764/miaomiao-harem?modelVersionId=3248362",\n      "mirror_hash_matched_to_publisher": true\n    }\n  ],\n  "selected_for_startup": [\n    "moss_image_sft_int8",\n    "anima_turbo_v1_1",\n    "anima_aesthetic_v1_1",\n    "anima_base_v1",\n    "wai_anima_v1_0",\n    "animayume_v1_5_base",\n    "miaomiao_harem_anima_v1_6"\n  ]\n}')
SELECTED_MODEL_IDS, MODEL_ASSETS = select_model_assets(MODEL_REGISTRY, MODEL_GROUP, MODEL_ID)
MODEL_REGISTRY["selected_for_startup"] = SELECTED_MODEL_IDS
# Prepare selected models locally and preserve verified weights on Drive.
import hashlib, json, os, shutil, subprocess, sys, time, zipfile
from pathlib import Path
from importlib import metadata

COMFY_COMMIT = 'fe298e4e20f1ff26d30e8639267bbd0b57811390'
MODEL_REVISION = '24147db865fcdc207270f844777587223fed8d6e'
DRIVE_ROOT = Path('/content/drive/MyDrive/ComfyUI_Colab')
PROJECT = Path('/content') / ('ComfyUI-' + COMFY_COMMIT)
LOCAL_MODELS = Path('/content/moss_models')
MODEL_STORE = DRIVE_ROOT / 'models'
MODEL_FILES = globals().get('MODEL_ASSETS', [
 {'path':'diffusion_models/moss_image_sft_int8_convrot.safetensors','size_bytes':5413698958,'sha256':'b4d1475bc7eeffd7b809e82ea13a1fba1fb85c4e18365af3813722faa5c0fe4f'},
 {'path':'text_encoders/qwen3.5_9b_w4a8_gptq.safetensors','size_bytes':7343591088,'sha256':'4cc6a1543ad2061806da46f35f90cadb4801dcba246c44782cf42ec0feb6407c'},
 {'path':'vae/flux2-vae_small.safetensors','size_bytes':249521340,'sha256':'d8d52ba036475f5fb07c8b435e176d3d97ebfa82f0d1a1c317f9cc1e25bd013b'}])


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()


def receipt(path):
    return path.with_name(path.name + '.verified.json')


def mark_verified(path, spec):
    st = path.stat()
    receipt(path).write_text(json.dumps({'sha256':spec['sha256'], 'size_bytes':st.st_size, 'mtime_ns':st.st_mtime_ns}), encoding='utf-8')


def verified(path, spec):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size != spec['size_bytes']: return False
    st = path.stat()
    expected = {'sha256':spec['sha256'], 'size_bytes':st.st_size, 'mtime_ns':st.st_mtime_ns}
    try:
        if json.loads(receipt(path).read_text(encoding='utf-8')) == expected: return True
    except (OSError, ValueError): pass
    if sha256_file(path) != spec['sha256']: return False
    mark_verified(path, spec)
    return True


def copy_verified(src, dst, spec):
    src, dst = Path(src), Path(dst)
    if src.resolve() == dst.resolve(): raise RuntimeError('模型源与目标为同一路径，已停止。')
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink(): raise RuntimeError(f'目标不能是符号链接：{dst}')
    part = dst.with_name(dst.name + '.part')
    if part.is_symlink(): raise RuntimeError(f'临时目标不能是符号链接：{part}')
    h, done, last = hashlib.sha256(), 0, time.monotonic()
    with src.open('rb') as source, part.open('wb') as target:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b''):
            target.write(chunk); h.update(chunk); done += len(chunk)
            if time.monotonic() - last > 20:
                print(f'  {dst.name}: {done / spec["size_bytes"]:.0%}', flush=True); last = time.monotonic()
        target.flush(); os.fsync(target.fileno())
    if done != spec['size_bytes'] or h.hexdigest() != spec['sha256']:
        raise RuntimeError(f'文件校验失败，原文件未替换：{dst.name}')
    os.replace(part, dst)
    mark_verified(dst, spec)


def selected_model_specs():
    # Old standalone MOSS cells only specified the canonical path and checksum.
    unique = {}
    for original in MODEL_FILES:
        spec = dict(original)
        spec.setdefault('repo_id', 'Comfy-Org/MOSS-Image')
        spec.setdefault('repo_file', spec['path'])
        spec.setdefault('revision', MODEL_REVISION)
        for field in ['path', 'repo_file']:
            relative = Path(spec[field])
            if relative.is_absolute() or '..' in relative.parts or '\\' in spec[field]:
                raise RuntimeError(f'Invalid relative model path: {spec[field]}')
        previous = unique.get(spec['path'])
        if previous is not None:
            if (previous['sha256'], previous['size_bytes']) != (spec['sha256'], spec['size_bytes']):
                raise RuntimeError(f'Conflicting assets for {spec["path"]}')
            continue
        unique[spec['path']] = spec
    return list(unique.values())


def download_model(spec, local, hf_hub_download):
    # Each source has its own resumable local_dir, separate from ComfyUI paths.
    source = spec['repo_id'] + '@' + spec['revision']
    readable = ''.join(c if c.isalnum() or c in '-_.' else '-' for c in source)[:100]
    cache = LOCAL_MODELS.parent/'model_download_cache'/(readable + '-' + hashlib.sha256(source.encode()).hexdigest()[:12])
    if cache.is_symlink(): raise RuntimeError(f'Download directory cannot be a symlink: {cache}')
    cache.mkdir(parents=True, exist_ok=True)
    candidate = cache/spec['repo_file']
    if candidate.is_symlink() or (candidate.exists() and not candidate.is_file()):
        raise RuntimeError(f'Download candidate is not a regular file: {candidate}')
    force = candidate.is_file() and not verified(candidate, spec)
    kwargs = {'repo_id': spec['repo_id'], 'filename': spec['repo_file'],
              'revision': spec['revision'], 'local_dir': str(cache)}
    downloaded = Path(hf_hub_download(**kwargs, force_download=force))
    if not verified(downloaded, spec):
        # Retry only when the returned, completed file itself is proven corrupt.
        # A corrupt canonical target must never discard a good resumable cache.
        if not force and downloaded.is_file() and not downloaded.is_symlink():
            downloaded = Path(hf_hub_download(**kwargs, force_download=True))
        if not verified(downloaded, spec):
            raise RuntimeError(f'Model download checksum failed: {spec["path"]}')
    if downloaded.resolve() != local.resolve():
        local.parent.mkdir(parents=True, exist_ok=True)
        os.replace(downloaded, local)
        mark_verified(local, spec)


def run_checked(args, **kwargs):
    subprocess.run(args, check=True, **kwargs)



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



def prepare_workflow_template(workflows):
    selected = globals().get('SELECTED_MODEL_IDS', [])
    catalog = globals().get('MODEL_REGISTRY')
    if catalog is not None and not any(
            model['family'] == 'MOSS' and model['id'] in selected for model in catalog['models']):
        print('本次未选择 MOSS，跳过 MOSS 网页模板。', flush=True)
        return
    source = None
    for package in ['comfyui-workflow-templates-json', 'comfyui-workflow-templates']:
        try: dist = metadata.distribution(package)
        except metadata.PackageNotFoundError: continue
        for file in dist.files or []:
            if Path(str(file)).name == 'image_moss_image_t2i.json':
                candidate = Path(dist.locate_file(file))
                if candidate.is_file():
                    source = candidate
                    break
        if source is not None: break
    if source is None: raise RuntimeError('未找到官方 MOSS-Image 工作流，请重新运行以检查模板依赖。')
    json.loads(source.read_text(encoding='utf-8'))
    target = workflows/'MOSS-Image_Official_INT8.json'
    try:
        json.loads(target.read_text(encoding='utf-8'))
        template_ready = True
    except (OSError, ValueError):
        template_ready = False
    if not template_ready:
        part = target.with_name(target.name+'.part')
        if part.is_symlink(): raise RuntimeError(f'工作流临时目标不能是符号链接：{part}')
        shutil.copyfile(source, part)
        os.replace(part, target)

def prepare_environment():
    if not Path('/content/drive/MyDrive').is_dir():
        raise RuntimeError('Drive 未挂载。请先完成第一步的 Google 授权，再重新运行全部。')
    gpu = subprocess.run(['nvidia-smi','--query-gpu=name,memory.total','--format=csv,noheader'], capture_output=True, text=True, check=True)
    print('GPU:', gpu.stdout.strip(), flush=True)
    for p in [DRIVE_ROOT, MODEL_STORE, LOCAL_MODELS, DRIVE_ROOT/'project', DRIVE_ROOT/'input', DRIVE_ROOT/'output', DRIVE_ROOT/'user']:
        if p.is_symlink(): raise RuntimeError(f'新环境目录不能是符号链接：{p}')
        p.mkdir(parents=True, exist_ok=True)
    print('[1/4] 准备 ComfyUI 固定版本', COMFY_COMMIT[:12], flush=True)
    archive = DRIVE_ROOT/'project'/f'ComfyUI-{COMFY_COMMIT}.zip'
    if not archive.is_file() or not zipfile.is_zipfile(archive):
        import urllib.request
        part = archive.with_suffix('.zip.part')
        urllib.request.urlretrieve(f'https://github.com/Comfy-Org/ComfyUI/archive/{COMFY_COMMIT}.zip', part)
        if not zipfile.is_zipfile(part): raise RuntimeError('程序下载不完整，请重新运行。')
        os.replace(part, archive)
    if PROJECT.is_symlink(): raise RuntimeError(f'本地程序目录不能是符号链接：{PROJECT}')
    marker = PROJECT/'.colab-extract-complete'
    required = [PROJECT/'main.py', PROJECT/'requirements.txt']
    try:
        complete = not marker.is_symlink() and marker.read_text(encoding='utf-8') == COMFY_COMMIT and all(p.is_file() for p in required)
    except OSError:
        complete = False
    if not complete:
        marker.unlink(missing_ok=True)
        with zipfile.ZipFile(archive) as z:
            for item in z.infolist():
                dest = (PROJECT.parent / item.filename).resolve()
                if not dest.is_relative_to(PROJECT.resolve()): raise RuntimeError('程序压缩包路径异常。')
            z.extractall(PROJECT.parent)
        if not all(p.is_file() for p in required): raise RuntimeError('ComfyUI 程序恢复失败。')
        marker_part = marker.with_name(marker.name+'.part')
        marker_part.unlink(missing_ok=True)
        marker_part.write_text(COMFY_COMMIT, encoding='utf-8')
        os.replace(marker_part, marker)
    print('[2/4] 检查依赖，保留已安装的 PyTorch/CUDA', flush=True)
    from packaging.requirements import Requirement
    missing = []
    for line in (PROJECT/'requirements.txt').read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'): continue
        req = Requirement(line)
        if req.marker and not req.marker.evaluate(): continue
        try:
            if not req.specifier.contains(metadata.version(req.name), prereleases=True): missing.append(line)
        except metadata.PackageNotFoundError: missing.append(line)
    try: metadata.version('huggingface_hub')
    except metadata.PackageNotFoundError: missing.append('huggingface_hub')
    if missing:
        run_checked([sys.executable,'-m','pip','install','--disable-pip-version-check'] + missing)
    else: print('依赖已满足，跳过安装。', flush=True)
    specs = selected_model_specs()
    plan = model_storage_plan(specs)
    print(f'[3/4] 本次准备 {len(specs)} 个去重资产，共 {plan["planned_bytes"]:,} 字节', flush=True)
    print(f'本次所选模型的已验证缓存：本地 {plan["local_cached_bytes"]:,} 字节；Drive {plan["drive_cached_bytes"]:,} 字节', flush=True)
    print(f'待准备完整资产：本地 {plan["local_new_bytes"]:,} 字节；Drive {plan["drive_new_bytes"]:,} 字节；待下载资产 {plan["download_bytes"]:,} 字节（续传可能减少实际传输）', flush=True)
    print('以上为模型逻辑字节，未计程序、下载缓存及临时副本；不是 Drive 剩余配额或精确物理新增占用。已有缓存不删除。', flush=True)
    from huggingface_hub import hf_hub_download
    for spec in specs:
        local, saved = LOCAL_MODELS/spec['path'], MODEL_STORE/spec['path']
        print(spec['path'], flush=True)
        if not verified(local, spec):
            if verified(saved, spec):
                print('Copying verified model from Drive.', flush=True)
                copy_verified(saved, local, spec)
            else:
                print(f'Downloading from {spec["repo_id"]}.', flush=True)
                if local.is_symlink() or (local.exists() and not local.is_file()):
                    raise RuntimeError(f'Local model target is not a regular file: {local}')
                download_model(spec, local, hf_hub_download)
        else: print('Reusing verified local model.', flush=True)
        if not verified(saved, spec):
            print('Saving verified model to Drive.', flush=True)
            copy_verified(local, saved, spec)
        else: print('Drive copy is verified.', flush=True)
    manifest = {'schema_version': 1, 'files': specs}
    if 'SELECTED_MODEL_IDS' in globals(): manifest['selected_model_ids'] = SELECTED_MODEL_IDS
    sources = {(spec['repo_id'], spec['revision']) for spec in specs}
    if len(sources) == 1:
        manifest['repo_id'], manifest['revision'] = next(iter(sources))
    (DRIVE_ROOT/'model_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    if 'MODEL_REGISTRY' in globals():
        (DRIVE_ROOT/'model_registry.json').write_text(json.dumps(MODEL_REGISTRY, ensure_ascii=False, indent=2), encoding='utf-8')
    print('[4/4] 准备工作流和用户设置', flush=True)
    user = DRIVE_ROOT/'user'
    old_user = Path('/content/drive/MyDrive/ComfyUI/user')
    if old_user.is_dir() and not old_user.is_symlink() and not (user/'default').exists():
        shutil.copytree(old_user, user, dirs_exist_ok=True)
    workflows = user/'default'/'workflows'; workflows.mkdir(parents=True, exist_ok=True)
    prepare_workflow_template(workflows)
    print('准备完成。模型从本地加载；图片、工作流和设置保存到：', DRIVE_ROOT, flush=True)
    return True


if __name__ == '__main__':
    MOSS_READY = False
    MOSS_READY = prepare_environment()
