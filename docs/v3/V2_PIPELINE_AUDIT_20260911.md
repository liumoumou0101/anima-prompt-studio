# V2 遗留管线专项检查（2026-09-11）

更新：本文第 4、5 项已完成本轮改造，详见 [画廊管线改造与验收](GALLERY_PIPELINE_MIGRATION_20260911.md)。以下保留改造前的发现与证据；第 6 项默认配方来源仍待继续。

用户补充：V2 的许多配方最初仅为快速打通功能临时填写，不能把旧参数、旧测试或“tested/verified/baseline”命名当作质量依据。用户当前观察 Turbo、MiaoMiao 较正常，其他模型在过去测试中明显异常。今天不制作安装包，优先审计参数继承与模型管线。

## 已证实并修复

### 1. 切换模型会继承不适配的采样参数

入口：经典工作台、英文直出。两页切换模型都调用 `applyGenerationRecipe(settings, target)`。该函数为保护历史草稿和手动调整，遇到 custom 或目标不认识的旧 recipe ID 时保留所有采样参数。因此 Aesthetic 切换 Turbo 可继续用 CFG 4.5、35 步；Turbo 切换 Aesthetic/Yume 同理可继续用 CFG 1、10 步。它属于 V3 选择逻辑中的兼容行为缺陷，不是证明所有 V2 执行节点有错。

修复：显式切换模型使用新模型目标配方；画幅、种子、张数保留。目标暂未加载时清除旧工作流和配方身份，后续加载新目标时应用对应默认。同模型刷新连接/恢复历史工作台仍保留手调参数。会话页已有显式选择默认配方的行为。

验证：两个页面的交互测试覆盖 Aesthetic → Turbo → Aesthetic，以及手动 CFG 后切换 Yume。用原选择行为运行同一组测试，两页均失败（预期 Turbo CFG 1，实际保留 4.5）；恢复修复后通过。只读筛查本机 365 条运行记录，尚未发现非 Turbo 已实际提交 CFG ≤ 1 或步数 < 20 的记录，不将这个缺陷直接归因为用户历史图的全部异常。

### 2. Yume 的旧候选路径仍套用 Base 负向模板

入口：V3 本地候选/标签编译器 `LiteralCandidateGenerator`。会话页已经说明不自动套用未经确认的评分负向，但打包 ModelProfile 仍含 score_1/2/3 等默认内容。作者 1.0 说明训练未包含质量评分标签，也未找到本次可确认的专属负向配方。

修复：移除该路径未验证的自动负向模板，保留 negative 输入能力和用户明确排除项。不是宣称 Yume 不需要负向，也不清空用户已保存或手填负向。后续按该版本独立验证建议词。

### 3. MiaoMiao 的旧候选路径自动加入画面内容

打包配置把作者的示例正向前缀整段用于所有候选，包含 sensitive、fair skin、high contrast。这是内容取向、肤色和光影偏好，不应作为所有场景的隐藏默认。

修复：去掉这三个自动项，保留当前质量词和作者负向建议；手动输入同样词语仍允许。只影响候选生成路径，不改本轮已验收的直出/会话提示词和采样图。测试确认用户排除项仍生效。

## 已确认存在、尚未改造

### 4. 画廊再出图重新选模型版本，丢失原图工作流条件

`adapters/v2/gallery.py` 的 submit_process 只转交模型族、提示词、宽高和部分参数，没有转交原 run 工作流快照及完整 LoRA/绑定信息。V2 `choose_txt2img_workflow` 按固定 01/02/22/23/24/25 前缀重新选图。

本机直接调用选图函数验证：模型族 `anima_aesthetic_v1` 固定选到 `22___Aesthetic_v1.1`，其权重为 anima-aesthetic-v1.1.safetensors。因此源图若是 1.0，不能保证保留版本。增强节点或 LoRA 也可能丢失。之后还经过 V2 ConfigService/PromptCompiler 默认填充与 V2 执行器。

待改：新生成任务应沿用原图的冻结工作流、原模型版本和资源，走统一 V3 提交/执行路径；历史源图缺少证据时应明确让用户选新配方，不能声称复现原条件。不要仅把 V2 Renderer 类名换成 V3 就当修复完成。

### 5. 画廊放大是另一条固定重绘链

`GalleryUpscaleRenderer.render` 将正向绑定改为 WD14Tagger 输出，模型接固定模板 UNET，使用模板负向、独立采样设置，并修改 bongmath 等参数。它不会保留原图提示词/模型。当前本机 20_Tile_Upscale 模板权重为 `waiANIMA_v10（anima3）.safetensors`；该文件不在前一轮十文件身份核验清单内，尚未验证可用性或身份。

这是代码和模板证据，本轮未实际运行该放大链，不能报告其具体画质。待改为显式说明的独立增强配方，或者保留原模型/提示词的可追踪精修；不能继续混称原图高质量版本。

### 6. 默认配方存在多处来源，命名高估证据

旧 JSON 的 Base/Aesthetic balanced 参数与 V3 RuntimeProfiles 数值相同。V3 `build_workflow_recipe_contract` 对 Base/Aesthetic 使用 RuntimeProfiles 覆盖导入模板默认：本机旧 Aesthetic 模板为 30/4/er_sde/simple，页面默认可变为 35/4.5/euler/normal。并非这些数值必错，而是不能根据“稳定基线”标签证明其已质量验收。Aesthetic 的“创意变化”与当前基线同为 Euler，区分也不成立。

待改：单一模型/版本配方来源，区分模板值、作者推荐、实验值和用户覆盖；展示实际生效参数和来源。独立作者建议确实包含 Aesthetic 可用 Euler、Base/Aesthetic 30–50 步 CFG 4–5，因此本轮不凭怀疑随意替换采样器。

## 已检查、尚未发现本轮主路径有该类错误

工作台 → SubmissionService → V3RuntimeProfiles/PromptJob DTO → WorkflowCatalog 映射/冻结 → V3WorkflowCompiler → V3RemoteExecutionCoordinator → ComfyUI。主路径已使用 V3 编译/执行模块，仍使用旧 DTO 不等于仍在执行 V2 的全部策略。

V3 编译器将已提交的采样参数写入绑定，服务器显式资产映射优先于旧 checkpoint alias；正负向直接写到绑定文本。普通 Aesthetic/Base 基线未发现额外重采样或注意力增强；单阶段 denoise 1、shift 3。上一轮十文件哈希核验和 Aesthetic 同参独立参考 RGB 一致仍成立，但只说明那一个条件下执行一致，不是多模型质量验收。

社区“优化”模板叠加 NAG 与 LayerReplay。上一轮同条件 Yume 实验图明显模糊，必须把两个增强分别做消融，不能视为常规基线。此次未改用户云节点、未新发成图任务；代码检查和参数测试不能冒充成图质量验证。

## 验证与后续顺序

- 后端 V3 全量 459 项通过，前端 83 项通过；TypeScript、生产网页构建通过。未制作安装包，未提交或推送。
- 下一步优先统一画廊再出图与工作台执行条件，再独立处理放大链；同时追踪 Base/Aesthetic/Yume 最终参数来源，做少量有明确假设的对照。Turbo、MiaoMiao 保留为用户观察正常的参照，不作无依据的整套重写。
- 用户之前的异常图尚未全部匹配到实际工作流，不宣称已经定位全部画质根因。

来源：[ANIMA 作者说明](https://huggingface.co/circlestone-labs/Anima/blob/main/README.md)、[AnimaYume 1.0 Final 作者页面](https://civitai.com/models/2385278?modelVersionId=3065644)、[MiaoMiao 1.6 作者页面](https://civitai.com/models/934764?modelVersionId=3248362)。模型作者快照和旧行为失败测试保存在本机 `.local`，不随 Git 同步。
