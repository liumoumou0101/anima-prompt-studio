# Anima 2.9B 与 AnimaYume 1.5 接入记录

日期：2026-09-12。模型只安装在现有云实例，没有保存私有镜像。

## 默认工作流与参数

| 模型配置 | 云端权重 | Steps / CFG | Sampler / Scheduler |
|---|---|---|---|
| `anima_2_9b_preview_v1` | `Anima-2.9B-preview-v1.safetensors` | 30 / 4 | euler / sgm_uniform |
| `animayume_v1_5_base` | `AnimaYume_v15_base.safetensors` | 30 / 5.5 | euler_ancestral / normal |

两套都是单阶段原生文生图，默认 896×1152，复用 `qwen_3_06b_base.safetensors`（CLIPLoader type=stable_diffusion）和 `qwen_image_vae.safetensors`。不需要新增文本编码器或 VAE。没有必需 LoRA，没有额外 ModelSamplingAuraFlow shift 覆盖、NAG 或 Layer Replay。模板来自本实例升级后实际跑通的图，不是直接改旧工作流的模型文件名。

2.9B 配方额外提供 50 步细节对照、Beta 调度对照；Yume 1.5 提供 40 步细节对照。这些参数在作者推荐范围内，增加步数并不保证每个提示词的质量都会提升。默认 30 步兼顾初次试用速度。参数可以手动编辑。

所有入口支持两个模型。会话创作、经典工作台、英文直出切换模型时选择对应工作流并应用默认配方，保留尺寸和种子；同一模型内的普通目标刷新仍保留已有自定义参数。导入工作流优先识别实际加载权重，区分 Yume 1.0 / 1.5，以及 Hugging Face 与 Civitai 的 1.5 文件名。已知权重和兼容模型声明冲突会阻止执行。

2.9B 是 40 层扩展模型，工作流检测要求 ComfyUI >=0.33.1，避免旧程序把它当 28 层模型加载。旧能力缓存没有版本号时，提交前重新检测。当前实例为 0.35.0，原生支持已经验证，无需作者旧版补丁。

## LoRA 是否需要下载

**基础生成均不需要额外 LoRA。** 社区模型身份本身不是需要加载 LoRA 的理由。

- **Anima 2.9B：** 层数从 28 增至 40，旧 Anima LoRA 不能直接视为兼容。作者在讨论中建议重新训练；层编号映射或仅连接旧层即使能运行，也可能改变颜色与纹理。不要默认套用旧 Turbo、DMDX、画师或角色 LoRA。
- **AnimaYume 1.5：** 作者明确提醒，这次微调可能影响所有基于 Anima 1.0 及衍生模型训练的 LoRA。应按 LoRA 发布者说明及同种子对照逐个确认，不能因为结构仍是 28 层就保证效果相同。
- 发现可选社区项目 [anima29b-turbo-unofficial](https://huggingface.co/Langzaigg/anima29b-turbo-unofficial)。其中 `anima29b-turbo-v2.9-remap.safetensors` 是映射到 40 层的加速 LoRA；同仓库还提供合并后的完整权重，二者不是同一安装方式。发布者给出的 LoRA 用法是 model-only，强度 0.8，Euler / sgm_uniform，8–12 步，CFG 1（空负向）或 1.2（使用负向）。其中 v2.9 是原 Turbo LoRA 的版本标识，不能只按名字判断兼容。
- 该加速方案目前可作为**后续实验候选**。仓库提供的映射一致性验证不等于独立的画质评测；本次没有下载或默认叠加，也没有宣称它能改善之前的失败图片。若要测试，应单独建立实验工作流，与原始 30 步基线使用相同提示词、种子、分辨率比较。

## 提示词与后续优化

2.9B 作者说明训练没有使用 score tags；可以使用一般质量词、角色与作品标签、`@画师`，较详细描述有助于稳定结果。Yume 1.5 是未做 aesthetic tuning 的 Base 微调模型，详细提示词同样有价值。两者都不能承诺新角色的外观完全正确。

应用不自动添加正向质量前缀、score 标签或负向文本。负向建议按钮仅在用户点击时补充本项目验收使用过的简短词组，不宣称是作者最佳配方。保留空负向测试的能力。

下一步优先使用相同角色、提示词、尺寸与种子，对比当前 Anima Aesthetic、2.9B、Yume 1.5。先分别观察角色知识、人体结构、构图和画风，再对选中模型测试更高步数、CFG 或调度器。不要同时叠加多种加速和模型修改后归因。

## 来源

- [Anima 2.9B 作者模型卡](https://huggingface.co/Gazingstars123/Anima-2.9B)：原生支持版本、训练与推荐采样参数。
- [2.9B 作者 LoRA 兼容讨论](https://huggingface.co/Gazingstars123/Anima-2.9B/discussions/2)：旧 LoRA 兼容限制。
- [AnimaYume 作者模型卡](https://huggingface.co/duongve/AnimaYume)：1.5 发布说明、LoRA 警告、Euler a / normal、25–40 步与 CFG 4–7。
- [云端安装与升级记录](CLOUD_MODELS_UPDATE_20260912.md)：权重哈希、ComfyUI / PyTorch 版本和升级前后回归结果。

## 验证入口

后端 `test_new_community_models.py` 覆盖模型到实际 API 图的权重、采样参数、种子和空负向透传；工作流目录测试覆盖旧 ComfyUI 拦截与旧缓存刷新；前端模型切换测试覆盖三个生成入口。

真实云端验收使用 `v3/tools/validate_workflow_installation.py --workflow ...`，可以重复该参数只选择两个新工作流。工具通过项目实际生成队列和 OS 凭据存储运行，在临时空数据库中验证内置工作流，无需事先导入模板。结果及原始图片保存在 `.local/community-integration-20260912/`。

本次结果：后端 515 项、前端 117 项测试通过，TypeScript 与生产构建通过；会话页最终目标选择调整后额外复跑 21 项相关前端测试通过。Vite 保留原有单包体积提示，未产生构建失败。

两次真实生成使用相同小木屋提示词、640×832、seed=20260905、30 步：2.9B 65.93 秒，Yume 1.5 38.30 秒（包含连接、加载、生成、下载，不是纯推理性能基准）。两张 PNG 均可正常打开，PNG 内嵌 prompt 与各自 `workflow_api.json` 完全相同。该小尺寸验收证明接入可用，不替代角色画质评测；安装阶段还验证过 896×1152，见云端升级记录。

正式数据库的两个工作流已检测为 ready，ComfyUI 0.35.0。本地服务已重新启动，并通过真实浏览器确认模型、工作流和默认参数同步；运行中的页面保留供手动测试。数据库备份及验收明细位于上述本地结果目录。
