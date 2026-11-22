# Colab 模型兼容改造方案（草案 v1）

制定日期：2026-10-26。2026-10-27 用户批准实施；第一阶段 ANIMA 已完成，见 [交付与真实验收记录](../../v3/COLAB_ANIMA_COMPATIBILITY_20261027.md)。第二阶段 MOSS 留待后续。下文保留制定时的事实、方案和边界。

## 1. 目标与建议路线

让现有 V3 工作台通过已完成的临时连接功能，选择 Colab 中实际可用的模型并完成出图、取图、保存与重绘。换一个 Colab 运行时后，更新原连接即可继续使用；原连接 ID、用户提示词和历史记录保留，但旧任务不能被误投到新实例。

建议分两次交付：先完成六款 ANIMA 的模型识别和出图，再加入 MOSS 的独立模型家族与简化文生图工作流。第一阶段内部先用 Turbo 跑通一张，再逐款扩展和验收。每个阶段均以本地工作台实际出图作为结束条件。

考虑的实现方式：

| 方式 | 优点 | 代价与结论 |
| --- | --- | --- |
| 只补模型文件名和手动映射 | 最快取得单张实验结果 | 仍看不到云端缺哪些文件，换环境容易误用旧映射；只用作探索性测试 |
| 云端目录提供能力证据，本地维护支持的模型和工作流 | 复用现有体系；能区分文件、节点与已验证出图 | 需补目录读取和几份模型配置；**本方案建议采用** |
| 任意云端目录自动创建模型、自动转换任意工作流 | 表面上更通用 | 无法仅凭文件名判断提示词策略、节点连线和模型兼容性；本轮不采用 |

本方案由助手建议，尚未把这些实现选择视作用户已批准的细节。固定域名、自动发现服务不属于本轮。

## 2. 当前事实与本轮实测

目标笔记本：[MOSS_ComfyUI_OneClick.ipynb](https://colab.research.google.com/drive/1mdB_uIc_xcMOxBbUy-D4fTVm5y8YqQBv)。本轮核对 Drive 元数据未变：修改时间 `2026-10-26T04:23:22.332Z`、大小 63969 字节；因此此前取得的代码副本仍可用于静态核验。

已完成的临时链接功能提供 HTTPS / Bearer、连接替换、会话版本、密钥保管，以及生成、上传、取图和队列恢复保护。本轮不重新实现这些功能。现有 `model_catalog` 字段仅用于校验和识别网关，尚未读取模型目录。

2026-10-26 23:27（北京时间），通过 Colab 单元实际执行只读检查，结果为：

- GPU：NVIDIA L4，23034 MiB 显存，检查时使用 0 MiB。
- Python 环境中的 PyTorch：`2.11.0+cu130`。
- 干净运行时：无 `/content/ComfyUI*` 项目，无 `/content/moss_models` 权重，无 ComfyUI 模板包；8188 服务不可用。
- 初始 Drive 未挂载。用户随后允许挂载，23:30 返回 `Mounted at /content/drive`。23:33 只读检查确认目标缓存目录中有七款 UNet、两款文本编码器、两款 VAE 和固定版本 ComfyUI 压缩包，字节大小与清单一致；这一步未做缓存全量 SHA 检查。

随后完成隔离的单 Turbo 实验：仅把其三份缓存文件恢复到运行时，使用原准备逻辑核对 SHA 和官方依赖；测试目录设为 `/content/colab_compatibility_probe`，不覆盖原 Drive 的目录清单、输出和用户配置。准备耗时 124.605 秒，ComfyUI 启动耗时 27.073 秒。

**资源探测不证明 ANIMA 或 MOSS 已出图，也不证明 L4 能承载所有目标设置。** 模型文件、节点枚举、API 提交和图片回传须在服务启动后分别验证。

本轮实际完成的推理：

| 项目 | 结果 |
| --- | --- |
| 工作流来源 | 本地正式 `catalog()` 的 `23_Turbo_v1.1`，经现有 `V3WorkflowCompiler` 编译；未读取用户数据库 |
| 提示词 | `a small red teapot on a wooden table in a sunlit garden, watercolor illustration`，负面为空 |
| 参数 | Turbo 1.1；512×512；batch 1；10 步；CFG 1；euler / normal；Seed 20261026；shift 3 |
| 节点预检 | 图中 10 个节点全部存在；实际环境共 1014 个节点；资产枚举准确包含三份目标权重 |
| 实际服务版本 | ComfyUI 0.42.0；frontend 1.57.1；templates 0.11.96；Python 3.13.16；PyTorch 2.11.0+cu130 |
| 执行 | 单次 POST `/prompt` 被接受，history 返回 success，`/view` 返回有效 512×512 PNG，Colab 中已显示核对 |
| 耗时 | 提交到取得图片约 10.03 秒，其中 history 的 execution_start → execution_success 约 8.173 秒；不含准备和启动 |
| 图像证据 | PNG 原始响应 397477 字节，SHA-256 `601dacd43af16db88bb011a7b4e37c8c85ff30e68c2ebb2486292cede8999bc7`；本地保存结果 JSON、实际提交图和界面截图 |

现场 `ResolutionSelector` 存在；`AnimaNormalizedAttentionGuidance`、`AnimaLayerReplayPatcher` 不存在；`EmptyFlux2LatentImage`、`TextGenerate` 及 CLIP 的 `moss_image` 选项存在。这些节点证据支持基础图优先，但不能替代 MOSS 权重推理测试。

边界：这是**本地项目编译图在 Colab 内通过回环 API 的真实推理**，没有开启公网隧道，没有验证本地工作台经 HTTPS/Bearer 的完整生图闭环，也未测试其余五款 ANIMA 或 MOSS。原始响应图仍在本次运行时的测试目录；本地保存的图片证据是界面截图，不把截图文件当作上述原始 PNG 哈希的对象。

收尾：停止本次 ComfyUI 进程并把启动状态置为未准备，Drive 保持挂载；未回收或删除运行时。删除本次四个临时单元后，重新通过 Drive 读取 notebook，与测试前副本逐一核对，原有五个单元的源码与类型全部相同。后续正常启动仍需先运行原准备单元。

笔记本当前固定 ComfyUI 提交 `fe298e4e20f1ff26d30e8639267bbd0b57811390`；服务位于 `127.0.0.1:8188`，网关位于 `127.0.0.1:8190`。认证后的 `/_moss/models` 返回 `protocol_version=1` 和模型列表。`ready` 只检查本地普通文件及字节大小；`selected_for_startup` 只描述准备时的选择，二者均不是 GPU 已加载或生图已验证。

## 3. 第一阶段：ANIMA 可用闭环

### 3.1 模型目录与状态

复用现有认证客户端，显式刷新或连接检测时读取同源固定路径 `/_moss/models`，并读取 `/object_info`。目录只能提供数据，不能触发执行、下载、自定义 URL 请求或模型自动注册。远端不提供目录时，现有本机和 SSH 流程仍可工作。

增加有界、严格的目录解析，核对协议版本、唯一 ID、字段类型、资产相对路径、有限数值和建议参数白名单。拒绝绝对路径、目录穿越、非法分类和无效数字；未知模型只显示“尚未适配”，不能凭目录元数据直接提交。

目录缓存绑定 `profile_id + http_session_id + environment_epoch`，并沿用能力缓存的实例条件；新导入和实例变化立即失效。断线时显示“上次检查/当前未确认”，不能沿用旧 `ready` 作为可提交依据。刷新返回时再比较会话，丢弃旧请求结果。

工作台在现有模型选择附近显示对应连接的状态：未检查、文件缺失、节点/映射待处理、可提交、已完成出图验证。文件齐全、预检通过、历史出图成功分别记录时间和环境版本；既往成功不替代当前预检。

### 3.2 六款模型的注册和资源映射

| 云端模型 ID | 本地现状 | 本阶段处理 |
| --- | --- | --- |
| `anima_turbo_v1_1` | 已有 | 复用 ID、模板；检查 CFG=1 与负面提示词行为 |
| `anima_aesthetic_v1_1` | 已有 | 复用 ID、模板 |
| `anima_base_v1` | 已有 | 复用 ID、模板 |
| `wai_anima_v1_0` | 缺失 | 补 ModelProfile、runtime、版本声明和单阶段工作流 |
| `animayume_v1_5_base` | 已有 | 复用 ID、模板 |
| `miaomiao_harem_anima_v1_6` | 已有 | 显式映射 Colab 的共享文本编码器 |

本地 MiaoMiao 模板使用 `miaomiaoHarem_anima16_txt.safetensors`，笔记本安装的是 `qwen_3_06b_base.safetensors`，须配置并核验编码器映射。不能把“同属 ANIMA”当成任意资产可互换的充分证据。

目录路径相对 models 根，例如 `diffusion_models/subdir/model.safetensors`；ComfyUI 节点参数通常相对具体分类。转换只移除已知分类前缀，保留 `subdir/model.safetensors`，再与 `/object_info` 枚举精确核对。不得只取 basename、猜最相近文件或替用户选择另一版本。

基础图应复用正式 catalog 返回的版本，而非直接把磁盘 JSON 提交。静态 JSON 中 `23/24/25` 含 `ResolutionSelector`，但现有 `runtime/workflow_catalog.py` 已会固化官方图的尺寸并删除不再被引用的此节点，因此不据此新增重复 Turbo/MiaoMiao 模板。本轮正式 Turbo 图已验证成功；补 WAI 基础图并验证其他模型即可，若现场再发现实际缺失，才有针对性处理。

`26/27/28` 优化图仍依赖 `AnimaNormalizedAttentionGuidance` 和 `AnimaLayerReplayPatcher`。保留这些工作流，不静默删除其可达优化节点、不放宽全图节点预检；干净 Colab 首先验证现有非实验基础图。若用户固定到缺扩展的优化图，解释原因并让用户选择基础图，不能暗中替换算法。用户副本和历史冻结图不适用官方 catalog 清理，应保留并按原图预检。

### 3.3 参数策略

保持已有本地默认、用户手动参数和历史任务不变。增加显式“应用云端建议参数”的操作，按当前支持的采样器和调度器校验后应用；保留尺寸、Seed、批量等建议未提供的字段，清楚显示实际改动。目录刷新本身不改用户设置。

当前已确认的差异如下，作为回归用例：

| 模型 | 本地默认 | Colab 目录建议 |
| --- | --- | --- |
| Turbo 1.1 | 10 / 1 / er_sde / simple | 10 / 1 / euler / normal |
| Aesthetic 1.1 | 35 / 4.5 / euler / normal | 35 / 4.5 / er_sde / normal |
| Yume 1.5 | 30 / 5.5 / euler_ancestral / normal | 30 / 5 / euler_ancestral / normal |
| MiaoMiao 1.6 | 30 / 4.5 / euler / normal | 35 / 4.5 / er_sde / normal |

列中顺序为步数 / CFG / 采样器 / 调度器。WAI 是新增配置，先采用目录的 25 / 4.5 / euler_ancestral / normal 作为待实测默认；发布前核对模型来源与单图结果。

### 3.4 预检与任务

继续使用现有显式工作流 bindings、资源映射、节点能力检查、冻结工作流及结果归档。提交前确认模型受支持、目标模板匹配、所有绑定资源存在、节点与参数枚举可用。远端 `POST /prompt` 校验失败按实际节点报告，不能算排队成功。

任何模型缺失都在提交前提示具体原因；目录不可用时可退回现有显式配置和完整节点/资源检查，不自动换模型。已有自动环境路由规则继续生效，新的目录信息不能暗中放宽用户固定连接选择。

## 4. 笔记本的小幅配套改造

这些是第一阶段的建议伴随改动，须独立验证，保留原来“全部 / 仅 ANIMA / 仅 MOSS”入口。

**按单模型准备。** 增加具体模型选择，根据依赖去重准备所需资产，首个联调使用 Turbo。缓存代码显示单款 ANIMA 约 5.628 GB、全部 ANIMA 约 26.539 GB、全部模型约 39.546 GB。切换模型不删除已有 Drive 缓存，并展示本次新增和累计空间；分次下载仍会累积占空间。相同运行时复用验证完成的权重和服务，避免为每个测试重建环境。ANIMA 准备不应因缺少无关 MOSS 模板而失败。

**真实服务实例标识。** 每次真正创建新 ComfyUI 服务实例生成随机 `runtime_id`，同服务重跑单元保留；从 Drive 或旧连接文件恢复的 ID 不得代表新实例。网关绑定该上游实例；上游重启时即使 gateway 源码相同，也须更新/重启网关，不能沿用旧身份。通过认证后的 `/_moss/info` 和连接 JSON 返回同一 ID，目录响应也可附带。

本地必须读取当前网关身份并与任务冻结身份核对，不能仅信任导入 JSON 中的 ID。实例变化使能力缓存和旧任务恢复失效，用户重新确认连接后才允许新任务。没有此字段的旧 notebook 保留弱身份兼容：每次重新检查能力，不声称已验证真实实例；不把导入字符串单独升级为强身份。

身份检查只能证明检查时刻的网关/服务标识，无法消除检查与提交之间重启的竞态。第一阶段不承诺服务端原子身份校验：若要覆盖该竞态，需要网关对执行请求校验 expected-runtime-id，再作为后续协议扩展设计。

## 5. 第二阶段：MOSS 最小文生图

MOSS 不能伪装为 community ANIMA：当前 `family` 只允许 `anima`，负面规则、质量词、写作指导和配方均有 ANIMA 假设。第二阶段增加明确的 MOSS 家族、`moss_image_sft_int8` 本地配置、独立参数和尺寸规则，已有 ANIMA 行为保持兼容。

首版先支持原样提示词的单阶段纯文生图。复用 `prepare_direct` 语义，改进界面名称以兼容自然语言，不添加 ANIMA 的 score/质量词，不执行云端提示词扩写。用户手动文本保持不变；负面提示词的实际生效方式以原生节点和实测为准，未支持的输入不得静默丢弃。

提供维护的、扁平的 API 格式 `WorkflowProfile`，包含显式 bindings 与 `compatible_model_profiles`：

- MOSS INT8 UNet，Qwen3.5 编码器，`CLIPLoader.type=moss_image`，Flux2 VAE。
- `EmptyFlux2LatentImage`、采样、解码和保存，准确节点输入以目标提交的 `/object_info` 为准。
- 原生默认 shift 5；需要显式调整时采用原生 `ModelSamplingAuraFlow`，不沿用旧插件的 ModelSamplingSD3。
- 25 步 / CFG 2.5 / er_sde / simple 目前仅为 notebook 建议，先用于联调，验证后才标为支持的默认。

现有自动工作流导入器要求 `EmptyLatentImage`，且要求采样器直接连接 CLIPTextEncode。因此官方带子图、TextGenerate 和切换节点的编辑器 JSON 不能直接导入使用。首版采用显式 API 工作流，不扩成任意编辑器图转换器。

ANIMA ↔ MOSS 切换时，切换模型和匹配工作流；采用该模型的基础配方并移除不兼容的工作流 overrides / LoRA 绑定，同时展示变更。提示词、尺寸与用户明确编辑的通用参数保留，但无效参数阻止提交并要求调整；不继承不兼容参数、不暗中改写手动文本。精确交互由实施者沿用现有设置状态和修改标记，避免新增一套独立页面。

MOSS 提示词助手作为后续增量：增加独立自然语言写作规则和双语文字保留；本地润色与云端 upsampler 不同时默认开启。首版不包含图生图、布局编辑器、官方扩写子图、MOSS LoRA、多阶段放大或高清修复。

官方依据：[OpenMOSS 原生 ComfyUI 说明](https://github.com/OpenMOSS/MOSS-Image/blob/main/comfyui/README.md)、[Comfy 官方 MOSS 模板](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_moss_image_t2i.json)。这些说明支持模型组件与原生工作流选择；实际安装版本仍须现场核验。

## 6. 实施边界和顺序

| 顺序 | 可验收产物 | 主要代码范围 |
| --- | --- | --- |
| A1 | 有界模型目录客户端、会话绑定缓存、状态接口 | `v3/src/anima_prompt_studio_v3/remote/` 新目录解析模块；`runtime/environment_probe.py`、现有 settings / workflow 能力 API |
| A2 | 六款 ANIMA 的配置、基础图核验与 WAI 新图、资源映射，建议配方显式应用 | `core/runtime_profiles.py`、`core/model_versions.py`、`core/generation_recipes.py`；`configs/model_profiles/`、`configs/workflow_profiles/`、`configs/workflow_catalog.json` |
| A3 | 工作台可见模型状态、提交前检查、参数不被刷新覆盖 | `runtime/workflow_catalog.py`；`v3/web/src/pages/ConversationWorkbenchPage.tsx`、现有生成设置与环境状态组件 |
| A4 | Notebook 单模型准备、实时实例身份、本地身份验证 | 原 notebook 准备/启动/网关单元；`remote/connections.py`、`runtime/environment_probe.py` 及提交/恢复入口 |
| A5 | 本地工作台通过 Colab 完成 ANIMA 全链路验收 | 使用隔离测试连接与数据，保存脱敏测试记录和图像 |
| B1 | MOSS 家族、简化 API 工作流及独立配方 | `core/profiles.py`、`core/runtime_profiles.py`、`core/workflow_parameters.py`、配置和绑定 |
| B2 | 原样提示词出图、跨家族切换与回归 | `runtime/generation.py`、现有设置状态和界面；之后再扩 `core/prompt_guidance.py` |

A1/A2 可以分开实现，但 A3 依赖双方接口，A5 依赖 A1–A4。B 阶段在 A 阶段验收后展开。实施前再将已选定阶段拆成文件/接口/测试明确的执行计划，不在草案中预先锁死所有内部命名。

## 7. 测试与验收

自动检查重点：目录协议和路径校验；未知模型、坏数据、超时与认证失败；旧请求晚返回；环境替换后旧状态失效；六模型资源映射；建议参数不覆盖手动设置；缺节点/缺资产在提交前失败；真实 runtime_id 与冻结任务不匹配时拒绝恢复。维持现有本机、SSH、临时连接和历史记录回归。

真实 Colab 验收分级记录，不能用只读接口或模拟器通过替代 GPU 出图：

1. 保存当前服务版本、GPU、目录、节点能力及资产枚举的脱敏证据；不记录密钥或带密钥的 URL。
2. 首张 Turbo：固定 Seed、batch=1、512×512、目录建议步数，使用普通中性提示词；记录请求、prompt_id、完成状态、耗时和取图结果。小图用于验证通路，不作为画质比较。
3. 六款 ANIMA 分别完成节点/资源预检、单图生成、图片下载和本地归档，核对冻结图中模型/TE/VAE/参数；Turbo 验证负面行为，MiaoMiao 验证共享 TE，WAI 验证准确模型。再用常用画幅做至少一张实际工作负载验证。
4. 原连接更新到新运行时：保留映射模板但强制重新核验；旧任务不能向新实例查询历史或自动重提。短暂断网恢复不产生重复请求；不为测试强制销毁含用户数据的运行时。
5. MOSS 阶段单独做固定 Seed、两个画幅、实际输入绑定、图片回传与 ANIMA ↔ MOSS 切换测试，观察 L4 加载峰值/速度。相同参数再次执行只核对参数传递与成功，不承诺 GPU 像素级确定性。

每个阶段只有在对应真实生成成功后才写“已兼容”。无法启动、显存不足或权重未就绪时记录具体事实，保留待验证标记。

## 8. 当前仍需验证

- 已确认 Drive 缓存文件与本地磁盘约 207.41 GB 可用；尚未通过此检查取得可靠的 Drive 剩余配额，不能据本地磁盘值推断云盘空间。
- 固定版本的依赖安装、模板包版本、Turbo 基础图节点与单图推理已验证；其余模型的实际图与推理仍待验收。
- L4 上 MOSS INT8 与 Qwen3.5 编码器的显存和耗时；是否需要低显存启动选项，须用实测决定。
- ANIMA 各模型在共享编码器上的行为与推荐参数是否符合预期。

本轮先交付设计和实测证据；不因某项探测未完成而假定兼容，也不为取得一个成功标记而更换模型、降低认证或重写用户配置。
