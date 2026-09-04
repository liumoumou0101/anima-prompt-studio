# 模型与远程工作流兼容性基线

更新日期：2026-09-04

本文记录 V2/V3 共用的远程 ComfyUI 模型契约、工作流来源、运行时参数和真实服务器验证结果。后续新增模型时，应先更新这里，再修改配置与工作流发现逻辑。

## 1. 运行链路

远程生图使用的是“云端工作流快照 + 本地运行时渲染”模式：

1. 从云主机读取 ComfyUI API 工作流，并以 `WorkflowProfile` 保存到本地 SQLite。
2. 用户在界面选择模型、参数预设和兼容工作流。
3. 本地 renderer 将提示词、正负面、尺寸、Seed、采样参数及模型资产注入完整工作流。
4. 完整 API 工作流经 SSH 隧道提交给云端 ComfyUI；云端不自行选择另一份工作流。

工作流不是每次从云端重新读取。ComfyUI 会缓存未变化的节点和当前模型：同模型连续任务可复用缓存；切换 UNet、文本编码器或 VAE 时会产生相应加载成本。

## 2. 新模型正式基线

| 模型配置 ID | 默认工作流 | UNet | 文本编码器 | VAE | Shift | 默认采样 |
| --- | --- | --- | --- | --- | ---: | --- |
| `anima_turbo_v1_1` | `23_Turbo_v1.1_验证基线` | `anima-turbo-v1.1.safetensors` | `qwen_3_06b_base.safetensors` | `qwen_image_vae.safetensors` | 3 | 10 步，CFG 1，`er_sde` + `simple` |
| `animayume_v1_0_final` | `24_AnimaYume_v1.0_Final_验证基线` | `animayume_v10BaseFinal.safetensors` | `qwen_3_06b_base.safetensors` | `qwen_image_vae.safetensors` | 3 | 30 步，CFG 5.5，`euler_ancestral` + `normal` |
| `miaomiao_harem_anima_v1_6` | `25_MiaoMiao_Harem_ANIMA_v1.6_验证基线` | `miaomiaoHarem_anima16.safetensors` | `miaomiaoHarem_anima16_txt.safetensors` | `qwen_image_vae.safetensors` | 3 | 30 步，CFG 4.5，`euler` + `normal` |

Turbo v1.1 是完整模型，不叠加旧版 `anima-turbo-lora-v0.2`。Turbo 默认禁用负面提示词；两个社区模型启用各自的负面提示词规则。

MiaoMiao 附带的 `miaomiaoHarem_anima16_txt.safetensors` 与服务器上的 `qwen_3_06b_base.safetensors` 大小及 SHA-256 完全一致。两者当前是同一权重的不同文件名；正式配置仍使用随模型提供的专用名称，以保持模型包语义并兼容将来文件更新。

## 3. 社区优化实验

以下工作流只用于显式 A/B，不作为自动默认：

| 实验工作流 | 对应模型 | 额外节点 |
| --- | --- | --- |
| `26_Turbo_v1.1_社区优化实验` | Turbo v1.1 | NAG + Layer Replay |
| `27_AnimaYume_社区优化实验` | AnimaYume | NAG + Layer Replay |
| `28_MiaoMiao_社区优化实验` | MiaoMiao | NAG + Layer Replay |

实验链位于 `ModelSamplingAuraFlow` 之后、`KSampler` 之前，参数继承已验证社区工作流；不会继承旧 Turbo LoRA。界面必须显示“社区优化实验（非默认）”说明，默认选择仍为 23、24、25。

固定 Seed、相同提示词的实机结果：

- Turbo：实验版构图更强烈，但出现红青色边缘伪影，不能替代干净基线。
- AnimaYume：实验版明显变软，城市和服装细节损失，基线更可靠。
- MiaoMiao：实验版构图接近基线但纹理更软，基线更适合作为默认。

因此结论是保留社区优化为可选实验，不把“节点更多”视为质量更高。

## 4. 缓存与性能证据

在 RTX 3080 Ti 云主机上，以 640×832、固定 Seed 的复杂场景连续执行“基线 → 同模型实验版”：

| 模型 | 首次基线 | 同模型后续任务 | 后续耗时变化 |
| --- | ---: | ---: | ---: |
| Turbo v1.1 | 9.95 s | 6.15 s | -38% |
| AnimaYume | 16.02 s | 11.26 s | -30% |
| MiaoMiao | 16.81 s | 11.35 s | -32% |

这说明连续生图不会无条件重新加载全部模型。性能策略应优先按模型分组排队，避免在多个大模型之间频繁交替。

## 5. 防错约束

- 工作流必须声明 `compatible_model_profiles`；未知兼容性不得提交。
- renderer 除 checkpoint 外还要绑定并记录文本编码器、编码器类型、VAE 和 model shift。
- 提交前用 ComfyUI `object_info` 校验远程文件名及枚举值，错误在排队前返回到界面。
- UI 的模型列表、预设、工作流列表均来自后端 bootstrap；模型切换后必须同步刷新预设和兼容工作流。
- 工作台与直接提示词页都应展示工作流说明；实验工作流不可静默成为默认。
- 画廊重绘必须按原图记录的模型选择兼容工作流，不能回退到不匹配的通用工作流。
- SSH/ComfyUI 的瞬时连接失败允许有限重试，但参数或兼容性错误不得重试掩盖。

## 6. 服务器安全状态

ComfyUI 当前以 `--listen 127.0.0.1 --port 8188 --highvram` 启动，只通过 SSH 隧道访问。公网 8188 探测已不可直接访问，隧道内 API、队列与生图均正常。

V3 桌面项目启动时会为默认云主机建立一条独立、长期存活的网页维护隧道：

`http://127.0.0.1:18188`

设置页同时提供“打开 ComfyUI 网页”按钮，可为当前选择的云主机建立或切换该隧道。18188 只绑定本机回环地址；项目退出后隧道关闭。生图任务仍使用各自的临时随机端口，两种连接互不影响。

远端启动脚本修改前的备份：

`/workspace/proxy/start.d/ComfyUI-Recommended-Safe-ManagerWeak.sh.bak-20260904-loopback`

本地工作流数据库修改前的备份：

`.local/backups/anima_prompt_studio.before_workflow_26_28_20260904.db`

## 7. 验证产物

固定 Seed 的基线、社区优化和复杂场景 A/B 结果保存在：

- `.local/model-validation-20260904/`
- `.local/model-validation-20260904-optimized/`
- `.local/model-validation-20260904-complex-ab/`
- `.local/model-validation-20260904-miaomiao-te-ab/`

这些目录是本轮兼容性证据，不参与应用运行或打包。
