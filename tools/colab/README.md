# Colab notebook update

`MOSS_ComfyUI_OneClick.ipynb` contains the updated five original cells and a final foreground generation monitor. It has no saved execution output or connection keys. `original.ipynb` is the unmodified source baseline fetched on 2026-10-26, preserved for comparison.

Rebuild offline with the project's Python:

```powershell
& 'H:/soft/提示词工具2/.venv/Scripts/python.exe' tools/colab/update_notebook.py
```

The updater also accepts an original notebook path and an output directory. It identifies cells by `metadata.id`, fails on missing, duplicate, or unexpected source anchors, compiles every changed cell, and never executes notebook code. Run it against the original, rather than the already updated output.

## Apply in the original notebook

Preserve an original source copy and review the generated differences before applying. Replace only these cell sources, keeping their existing IDs and order:

| Existing cell ID | Replacement source |
| --- | --- |
| `moss-prepare` | `moss-prepare.py` |
| `moss-start` | `moss-start.py` |
| `moss-cloud-api` | `moss-cloud-api.py` |

Alternatively, upload the full generated notebook to replace the original file contents. The instructions, mount cell, notebook settings, pinned ComfyUI revision, model source revisions/checksums, cloudflared version/checksum, and storage paths remain unchanged. No model caches are removed.

For an existing notebook with additional user cells, append `moss-monitor.py` in a new code cell after setup. The updater's `add_generation_monitor()` also supports adding or replacing only that identified cell in a downloaded notebook, preserving every other cell and its metadata.

## 生图运行状态

连接就绪后运行最后的“生图运行状态”单元格，测试期间保持它运行。在本地工作台发起生图时，它读取本机 ComfyUI 的实际队列和 `/content/moss_comfyui.log`，显示执行、排队、采样进度和错误。忙碌时至少每 15 秒更新一次观察时长，日志有变化时约每 2 秒刷新。空闲时显示等待任务。

输出在同一面板更新，最多保留最近 20 条日志。模型加载和解码阶段以真实日志为准，可能没有百分比。`MONITOR_MINUTES` 默认观察 120 分钟，可改为 1 至 1440 分钟，到时自然结束，后台服务继续运行。新启动的 ComfyUI、认证网关和隧道各自使用独立进程会话，停止前台监控不会向它们转发进程组中断信号。更新前已经运行的进程需要重启后才有这项保护。要运行其他单元格，可等观察时段结束，或者在完成出图后停止观察，操作完再运行监控。新启动的 ComfyUI 使用 Python 无缓冲输出；已有运行中的服务也能直接运行监控查看队列和已写入的日志。

监控启动前会检查 Linux 后台服务的实际进程会话。若复用了更新前未隔离的进程，或无法确认会话，它会立即显示处理说明并退出，避免进入必须手动中断的监控循环。

该功能用于查看实际任务状态。Colab 官方说明存在动态空闲超时、实例寿命和计算额度限制，持续输出无法保证避免断联。参考 [Colab FAQ](https://research.google.com/colaboratory/faq.html)。

## CunnyFunky v4 对照实验

`cunnyfunky-v4.py` 是独立的 Colab 实验单元。将它保存在云盘 `ComfyUI_Colab/cunnyfunky-v4.py`，先挂载 Drive、选择 `anima_turbo_v1_1` 准备模型并启动 ComfyUI，然后执行该脚本。线上 notebook 的“CunnyFunky v4 开关对照”单元已提供入口。

脚本下载并核验发布版 `cf_style_v4.safetensors`，保存到云盘 `models/loras/`，再复制到当前运行时。两张图均使用 832×1216、种子 4444、8 步、CFG 1、Euler/simple 和同一成年女性咖啡馆提示词，LoRA 权重分别为 0、1。底模为本项目已有的 Turbo v1.1 safetensors，shift 3。作者样图用 Q8 GGUF，底模文件和加载方式与本实验有区别。

原图、对比图、两份 API 工作流、执行历史和参数清单保存在云盘 `ComfyUI_Colab/research/cunnyfunky_v4/` 的本次实验目录。当前服务实例内重跑会继续查询已提交的任务，避免重复提交。新服务实例开始新实验。输出由实际任务历史和 PNG 尺寸共同校验。

`MODEL_GROUP` keeps `全部 / 仅 ANIMA / 仅 MOSS`. `MODEL_ID` defaults to `按模型组`; selecting a concrete ID overrides the group filter and prepares only that model's deduplicated dependencies. The original directory contains seven models: six ANIMA variants plus MOSS. Every directory entry remains available to the gateway, whose readiness checks use actual local files.

The preparation summary reports selected assets' logical byte totals, verified local/Drive cached bytes, and complete assets still needed at each location. The download figure is complete missing asset bytes; resumable download caches may reduce actual transfer. These figures do not measure Drive remaining quota, filesystem blocks, or program/download/temporary-file overhead.

ANIMA-only preparation skips the MOSS web template. Selecting MOSS retains the original official-template requirement.

## Runtime identity

A random 256-bit ID is attached only to a newly launched ComfyUI `Popen` object. Repeating the start cell for that same living process retains the ID. A dead process, imported JSON, Drive file, or global ID cannot supply an identity. An already running service created by the old notebook has no process-owned ID and requires a controlled stop/relaunch before using the new cells.

Before a replacement ComfyUI process starts, the notebook retires its own old gateway; this prevents an old gateway from advertising the previous ID while forwarding to the new service. Reuse of a living gateway requires both its source digest and upstream process ID to match, plus an authenticated live info response with the same ID. The runtime-only connection JSON includes this same `runtime_id`. Bearer authentication, browser cookie security, loopback-only upstreams, streaming/proxy behavior, and TLS remain as before. A standalone gateway without the optional ID keeps the previous info shape.

The notebook update itself does not start services or publish an endpoint. Browser confirmation requirements for enabling the public tunnel still apply when the cells are run.

## LoRA library cache

`lora_gateway.py` is embedded verbatim in the generated gateway, behind its existing authentication. `GET /_moss/loras/{sha256}` reports verified runtime/Drive availability. Raw `PUT` uploads are accepted up to 4 GiB; the app sends larger assets as resumable `Content-Range: bytes start-end/total` requests of at most 8 MiB each, so transfers fit the tunnel's request limits. While incomplete, status additionally reports `upload_offset` and `upload_total_bytes`. Only an atomically committed prefix counts toward that offset; reconnecting clients query it before retrying. A final whole-file SHA-256 check precedes installation.

`POST /_moss/loras/{sha256}/restore` copies a verified Drive cache into the current runtime without uploading local bytes. Paths are fixed to `models/loras/anima_library/<sha256>.safetensors` under the Drive root derived from the model catalog, and `loras/anima_library/<sha256>.safetensors` under the runtime model root. Human names and arbitrary paths are never accepted. Incomplete prefixes remain hidden `.part` files, and each asset's writes are serialized. Runtime replacement and connection changes invalidate an in-progress client job.

## Local verification

```powershell
& 'H:/soft/提示词工具2/.venv/Scripts/python.exe' -m pytest tests/test_colab_notebook.py tests/test_lora_gateway.py
```

The tests evaluate selected AST functions and controlled service/network stubs. They exercise selection, storage accounting, template independence, actual start-cell process lifecycle, gateway reuse/readiness, authenticated info, connection JSON identity, artifact reproducibility, and cell compilation. They never run downloaded sources, mount Drive, launch a GPU service, or contact a tunnel. Actual Colab preparation and image generation require separate runtime verification.
