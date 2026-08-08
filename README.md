# ANIMA 中文提示词辅助工具 V1

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
- 五种质量预设、动作/场景/弱情绪增强及逐条编辑/开关；增强编辑、禁用和锁定会同步重建 Canonical Prose 与最终标签。
- 离线智能构图推荐：根据人数、动作、场景、视线目标和重要细节推荐景别、机位、角度、视线、画幅和主体位置。
- 构图项支持自动、手动和锁定状态，附带可追溯的推荐理由；锁定值不会被重新推荐、模型或质量预设覆盖。
- 人数、主体类型和角色槽编辑会立即重编译最终 Prompt；保存、复制和导出前还会执行一次最终同步保险。
- 单人、双人、三人独立角色段落和 4+ 群像警告。
- 画师串、LoRA 记录和触发词插入；文本派生与手工/锁定来源分离，权威文本变化只替换文本派生项。
- 可复用的角色卡、画师库、LoRA 库及任务内直接应用。
- SQLite 历史/收藏、正负提示词复制、完整参数复制、任务 JSON 导出。
- Scene 模式隐藏角色槽但保留编辑态人物数据，切回人物模式可恢复；Scene 任务包仍导出空 `characters`。

## 安装运行

推荐 Python 3.12（3.13 也可运行核心服务）：

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

## 高质量本地翻译模型

内置翻译用于无模型时的可用回退，覆盖常见出图词汇，但不是完整语言模型。项目默认使用 Helsinki-NLP 的 `opus-mt-zh-en` 与 `opus-mt-en-zh`。安装依赖并自动下载双向模型与真实标签库：

```powershell
python -m pip install -r requirements-translation.txt
python -m anima_prompt_studio.tools.resource_setup
```

下载完成后软件会自动发现资源，日常翻译和标签匹配均离线运行。也可在“设置 → 配置本地 Marian 翻译模型”中选择其他本地模型目录。

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

用户数据默认保存在 `%LOCALAPPDATA%\AnimaPromptStudio`，包括 SQLite 数据库和滚动日志。模型、质量词、标签库均位于 `src/anima_prompt_studio/configs`，可以直接扩充 JSON，而不需要修改业务代码。标准 pytest 在没有下载标签数据库或翻译模型的干净环境中也可运行；测试包含 76 条真实语义用例、36 条智能构图用例，以及服务、数据库、导出和桌面状态检查。

## 数据来源与当前边界

标签库由资源安装命令从 Danbooru 官方只读 API 获取，并按 ANIMA 官方公布的 2025-09 训练数据截止时间过滤；数据库保存来源、下载时间与 schema。ANIMA 配置依据 CircleStone Labs 官方模型卡设置，但实际工作流仍建议固定种子复验。

完整的第三方来源和许可说明见 `THIRD_PARTY_RESOURCES.md`。

V1 按设计不连接 ComfyUI；导出的 schema 1.3 任务 JSON 已包含 canonical prose、主体模式、排除概念、LoRA/画师及其来源、构图值、状态、推荐理由和来源规则。
