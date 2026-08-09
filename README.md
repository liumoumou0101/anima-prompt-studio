# ANIMA 中文提示词辅助工具 V1.1

完全本地运行的 ANIMA 中文提示词翻译、检查、标签化和编译桌面工具。软件不会调用在线 API。

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
- 离线智能构图推荐：根据人数、动作、场景、视线目标和重要细节推荐景别、机位、角度、视线、画幅和主体位置。
- 构图项支持自动、手动和锁定状态，附带可追溯的推荐理由；锁定值不会被重新推荐、模型或质量预设覆盖。
- 提供标准人物、人物特写、半身人物、全身立绘、动态动作、环境人物和大场景构图预设。
- 对过长、复合动作过多或抽象内容较多的输入给出软提醒，但不会自动删改用户原文。
- 人数、主体类型和角色槽编辑会立即重编译最终 Prompt；保存、复制和导出前还会执行一次最终同步保险。
- 单人、双人、三人独立角色段落和 4+ 群像警告。
- 画师串、LoRA 记录和触发词插入；文本派生与手工/锁定来源分离，权威文本变化只替换文本派生项。
- 可复用的角色卡、画师库、LoRA 库及任务内直接应用。
- SQLite 历史/收藏、正负提示词复制、完整参数复制、任务 JSON 导出。
- Scene 模式隐藏角色槽但保留编辑态人物数据，切回人物模式可恢复；Scene 任务包仍导出空 `characters`。

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
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements-translation.txt
python -m anima_prompt_studio.tools.resource_setup --models
```

当前 Windows CPU 环境的参考量级：Torch wheel 约 120 MB、安装后约 500 MB；Transformers 及其依赖安装后约 100–200 MB；双向模型约 600 MB。加上 Qt 和缓存，完整增强环境通常占用约 1.4–2 GB，安装过程的临时峰值可能更高。这一整套均为可选能力，不是基础运行条件。

下载完成后软件会自动发现资源，日常翻译和标签匹配均离线运行。也可在“设置 → 配置本地 Marian 翻译模型”中选择其他本地模型目录。资源命令必须明确使用 `--tags` 或 `--models`，不会再因省略参数而意外下载全部资源。

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
- 快速和高质量档位依据 ANIMA 官方建议区间设置，仍需在具体 ComfyUI 工作流中使用固定 Seed 验证，不宣称对所有场景都优于平衡档。

用户数据默认保存在 `%LOCALAPPDATA%\AnimaPromptStudio`，包括 SQLite 数据库和滚动日志。Model、生成预设、质量词和构图预设位于 `src/anima_prompt_studio/configs`，可以扩充 JSON 而不需要修改业务代码；下载的标签数据库和翻译模型保存在用户数据目录，不提交到 Git。标准 pytest 在没有下载标签数据库或翻译模型的干净环境中也可运行。

## 数据来源与当前边界

标签库由资源安装命令从 Danbooru 官方只读 API 获取，并按 ANIMA 官方公布的 2025-09 训练数据截止时间过滤；数据库保存来源、下载时间与 schema。ANIMA 配置依据 CircleStone Labs 官方模型卡设置，但实际工作流仍建议固定种子复验。

完整的第三方来源和许可说明见 `THIRD_PARTY_RESOURCES.md`。

本工具定位为 ANIMA Prompt 辅助编译工具，不是全自动 Prompt Agent。它不会自动选择 Model、调用大模型重写长 Prompt，或替用户决定创作意图。V1.1 按设计不连接 ComfyUI；导出的 schema 1.4 任务 JSON 包含生成预设和最终底层参数，可作为后续远程 ComfyUI/云显卡集成的稳定输入。
