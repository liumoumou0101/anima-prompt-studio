# ANIMA 中文提示词辅助工具 V2 Beta

本地优先的 ANIMA 中文提示词翻译、检查、标签化、编译和远程生图桌面工具。提示词处理仍完全在本地运行；只有用户主动启用远程生成时，软件才会通过 SSH 隧道连接用户自己的 ComfyUI 云主机。

## 已实现

- 中文规范化、角色/画师/LoRA/锁定文本占位保护。
- 本地中译英、英译中接口；内置基础离线引擎可立即使用。
- 可配置用户本地 Marian/Hugging Face 双向模型，加载时强制 `local_files_only`。
- 英文编辑和锁定、回译展示、关键概念差异检查；编辑或锁定后英文成为唯一语义权威源，旧中文不再注入增强、否定或构图事实。
- 语义事实层与 Canonical Prose 收口：高置信动作、关系和冲突属性只保留最终有效描述。
- 自动识别人像/纯场景；纯场景人数为 0，不会注入 `1girl`、`solo` 或人物视线，并清空自动人物角度和主体位置。
- 中文否定概念独立追踪；从正向标签排除，并在支持 Negative 的模型配置中编译到负面提示词。
- 标签直接/同义词匹配、来源展示、冲突处理、锁定和永久排除。
- ANIMA Base、Aesthetic、Turbo 独立配置和参数切换。
- 每个 Model 独立维护快速、平衡、高质量三套确定性生成预设；Model 仍由用户选择，不做语义猜测。
- Width、Height、Steps、CFG、Sampler、Scheduler 均支持自动、手动和锁定状态；画幅会驱动自动宽高。
- 五种质量预设、动作/场景/弱情绪增强及逐条编辑/开关；增强编辑、禁用和锁定会同步重建 Canonical Prose 与最终标签。
- “增强内容”页分别展示始终生效的质量预设词和按描述触发的可编辑上下文增强；未触发上下文规则时会显示明确说明，不再呈现空白页。
- 离线智能构图推荐：根据人数、动作、场景、视线目标和重要细节推荐景别、机位、角度、视线、画幅和主体位置。
- 构图项支持自动、手动和锁定状态，附带可追溯的推荐理由；锁定值不会被重新推荐、模型或质量预设覆盖。
- 提供标准人物、人物特写、半身人物、全身立绘、动态动作、环境人物和大场景构图预设。
- 对过长、复合动作过多或抽象内容较多的输入给出软提醒，但不会自动删改用户原文。
- 人数、主体类型和角色槽编辑会立即重编译最终 Prompt；保存、复制和导出前还会执行一次最终同步保险。
- 单人、双人、三人独立角色段落和 4+ 群像警告。
- 画师串、LoRA 记录和触发词插入；文本派生与手工/锁定来源分离，权威文本变化只替换文本派生项。
- 可复用的角色卡、画师库、LoRA 库及任务内直接应用；点击“应用到当前任务”也会自动持久化资料卡，重启后仍可使用。
- SQLite 历史/收藏、正负提示词复制、完整参数复制、任务 JSON 导出。
- Scene 模式隐藏角色槽但保留编辑态人物数据，切回人物模式可恢复；Scene 任务包仍导出空 `characters`。
- 保存多个 SSH 云主机配置，通过已确认的主机指纹防止连接到错误服务器。
- 通过 SSH 本地端口转发访问云端 ComfyUI，不需要把 ComfyUI 的 8188 端口暴露到公网。
- 自动识别 ComfyUI API Format 基础文生图工作流的 KSampler 连线，将 Prompt、模型、尺寸、步数、CFG、采样器、调度器、Seed 和批量数注入工作流。
- 远程任务排队、执行和失败状态持久化；网络中断或软件重启后可恢复已经提交的任务。
- 生图完成后自动下载全部图片，按项目、主体类型、模型和日期分类归档。
- 内置生成图片浏览页：完成后自动预览最新图片，可按批次切换、浏览缩略图、查看生成参数，并打开原图或所在文件夹；也能从磁盘 `manifest.json` 恢复旧记录。
- 独立 Web“画廊”菜单会在系统浏览器中打开本地画廊服务，支持成熟相册网格、Lightbox、大图查看、项目/模型/批次/文本筛选和多选批量移入回收站；会补扫保存根目录中的散落图片。
- 每次生成同时保存 `manifest.json` 和实际提交的 `workflow_api.json`，方便追踪和复现。

## 基础安装（推荐先使用）

推荐 Python 3.12。基础版包含桌面界面、内置离线基础翻译、提示词编译和内置标签，不安装 PyTorch，也不下载模型权重：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m anima_prompt_studio
```

也可双击或执行：

```powershell
.\run_anima.ps1
```

启动脚本会优先使用项目目录下的 `.venv`，避免误用其他项目的 Python 环境。

当前 Windows wheel 的参考量级：基础依赖下载约 100 MB，安装后约 200–300 MB。实际体积会随 Python、Qt 版本和 pip 缓存变化。项目仅依赖 `PySide6-Essentials`，不会再安装用不到的完整 Qt Addons。

## 可选：SSH 云主机与 ComfyUI 远程生成

安装远程执行依赖：

```powershell
python -m pip install -r requirements-remote.txt
```

推荐云端 ComfyUI 只监听 `127.0.0.1:8188`，公网安全组只开放 SSH 端口。优云智算容器/社区镜像的首次使用步骤：

1. 在优云智算实例卡片中点击“ssh登录指令”旁的复制按钮，在软件里点击“粘贴并解析”。软件会从完整指令中自动提取地址、`root` 用户和 `23` 端口。
2. 点击实例卡片“密码”旁的复制按钮，再点击软件里的“粘贴密码”。勾选“安全记住密码”后，密码保存在 Windows 凭据管理器中，不写入项目数据库；下次启动会恢复上次云主机并自动连接。
3. 点击“一键连接并识别”，核对并确认首次连接显示的 SSH 主机指纹。软件会自动保存连接、探测 `127.0.0.1:8188`，并从 `/workspace/ComfyUI/user/default/workflows` 发现镜像自带的 `01`–`20` 号工作流。
4. 工作流列表会标出“V2 可直接生成”和“下一版本适配”。当前已完成真实端到端测试的是 `01 基础高质量`、`02 极速文生图`、`05 四步 DMDX`，以及自动派生的 `21 Aesthetic v1.0`、`22 Aesthetic v1.1`。21/22 只会在云端存在相应模型文件时出现，选择后会自动切换到本地 `ANIMA Aesthetic` 模型配置。完成提示词编译后点击“生成并自动下载”即可。

Ubuntu 系统镜像和其他云主机仍可从云平台列表切换，并通过“显示高级连接设置”填写地址、私钥、ComfyUI 端口或模型覆盖。也继续支持手动导入 ComfyUI API Format 工作流。

图片默认保存到 `%USERPROFILE%\Pictures\AnimaPromptStudio`，可以在“设置 → 设置图片保存目录”中修改。生图完成后软件会自动切换到“生成图片”页；也可以点击远程生成区的“查看生成图片”或按 `Ctrl+G` 随时打开即时预览。菜单栏“画廊”或 `Ctrl+Shift+G` 用于查看全部历史图片。SSH 密码仅可选择保存到 Windows 凭据管理器；私钥口令仍只在当前连接时使用，二者都不会写入数据库、任务 JSON 或日志。

画廊不会在 Qt 主程序内嵌浏览器内核。点击“打开全部历史图片”后，程序只在 `127.0.0.1` 启动临时本地服务，并交给系统浏览器打开；主程序关闭后该服务也会停止。批量清理默认是移动到图片根目录下的 `.trash` 回收站，不会直接永久删除文件。

Web 画廊前端源码位于 `web_gallery`，发布前端静态资源已经随 Python 包提供。修改前端后可执行：

```powershell
cd web_gallery
npm install
npm run build
```

V2 当前只执行已经通过真实测试的基础文生图工作流。其余复杂工作流仍会被发现、列出并允许查看选择，但生成按钮会停用，具体参数适配留到下一版本。远程执行的完整架构、状态恢复和安全约束见 `docs/V2_REMOTE_COMFYUI_DESIGN.md`。当前 Beta 已在优云智算的 Anima Omni v2.0 镜像上完成 SSH 隧道、ComfyUI API、20 个镜像工作流发现，以及 01、02、05、21、22 五个工作流的真实生图和自动下载验收。

## 可选：真实标签库

只需要扩充标签时，不必安装 PyTorch 或翻译模型：

```powershell
python -m pip install -r requirements-resources.txt
python -m anima_prompt_studio.tools.resource_setup --tags
```

## 可选：高质量本地翻译模型

内置翻译覆盖常见出图词汇，但不是完整语言模型。需要更完整的本地翻译时，可选安装 Helsinki-NLP 的 `opus-mt-zh-en` 与 `opus-mt-en-zh`。

Windows 建议先从 PyTorch 官方 CPU 索引安装纯 CPU 版，避免误装不需要的 CUDA 运行库：

```powershell
.\install_translation_cpu.ps1
```

同时下载约 600 MB 的双向模型：

```powershell
.\install_translation_cpu.ps1 -DownloadModels
```

当前 Windows CPU 环境的参考量级：Torch wheel 约 120 MB、安装后约 500 MB；Transformers 及其依赖安装后约 100–200 MB；双向模型约 600 MB。加上 Qt 和缓存，完整增强环境通常占用约 1.4–2 GB，安装过程的临时峰值可能更高。这一整套均为可选能力，不是基础运行条件。

下载完成后软件会自动发现资源，日常翻译和标签匹配均离线运行。也可在“设置 → 配置本地 Marian 翻译模型”中选择其他本地模型目录。资源命令必须明确使用 `--tags` 或 `--models`，不会再因省略参数而意外下载全部资源。

只检查当前环境，不安装任何内容：

```powershell
python -m anima_prompt_studio.tools.verify_translation_env
```

## 测试

```powershell
python -m pytest
```

运行真实 Marian 模型的智能构图专项审计：

```powershell
python -m anima_prompt_studio.tools.composition_audit
```

运行包含 canonical prose、主体模式、排除概念、画师和 LoRA 结构断言的真实语义审计：

```powershell
python -m anima_prompt_studio.tools.semantic_audit
```

## 智能构图用法

- `混合模式`：默认模式，自动字段会随输入更新，手动和锁定字段保持不变。
- `智能推荐`：将除锁定项外的构图字段恢复为自动并重新推荐。
- `手动模式`：停止自动更新构图。
- 用户修改任一构图下拉框后，该项自动转为“手动”；可再切换为“自动”或“锁定”。
- `重新推荐构图` 只更新自动项。中文中明确写出的“正面”“全身”“看镜头”等要求会高于普通动作推荐。
- `构图预设` 负责填充可继续修改的初始值；已经锁定的构图项不会被预设覆盖。

## 生成参数用法

- Model 由用户明确选择，软件不会根据 Prompt 自动切换 Model。
- `生成预设` 决定 Steps、CFG、Sampler 和 Scheduler 的查表结果；`质量预设` 负责质量词和表现意图，两者职责不同。
- 修改参数后该字段转为“手动”，重新分析 Prompt 不会覆盖；“锁定”后控件不可编辑。
- 把字段恢复成“自动”会重新采用当前 Model 与生成预设的值；切换生成预设会重置手动项，但保留锁定项。
- 生成预设只管理 Steps、CFG、Sampler、Scheduler，不会重置手工或锁定的 Width/Height。
- 切换 Model 时，模型强相关的手动 Steps、CFG、Sampler、Scheduler 会恢复自动；锁定参数和手工 Width/Height 保留。
- 快速和高质量档位依据 ANIMA 官方建议区间设置，仍需在具体 ComfyUI 工作流中使用固定 Seed 验证，不宣称对所有场景都优于平衡档。

用户数据默认保存在 `%LOCALAPPDATA%\AnimaPromptStudio`，包括 SQLite 数据库和滚动日志。Model、生成预设、质量词和构图预设位于 `src/anima_prompt_studio/configs`，可以扩充 JSON 而不需要修改业务代码；下载的标签数据库和翻译模型保存在用户数据目录，不提交到 Git。标准 pytest 在没有下载标签数据库或翻译模型的干净环境中也可运行。

## 数据来源与当前边界

标签库由资源安装命令从 Danbooru 官方只读 API 获取，并按 ANIMA 官方公布的 2025-09 训练数据截止时间过滤；数据库保存来源、下载时间与 schema。ANIMA 配置依据 CircleStone Labs 官方模型卡设置，但实际工作流仍建议固定种子复验。

完整的第三方来源和许可说明见 `THIRD_PARTY_RESOURCES.md`。

本工具定位为 ANIMA Prompt 编译与用户自有 ComfyUI 执行客户端，不是全自动 Prompt Agent。它不会自动选择 Model、调用大模型重写长 Prompt，或替用户决定创作意图。远程执行只连接用户明确配置并确认过 SSH 指纹的云主机。
