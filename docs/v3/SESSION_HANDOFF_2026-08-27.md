# ANIMA Prompt Studio V3 会话交接

更新时间：2026-08-27 13:45（Asia/Shanghai）

本文用于在新的 Codex 会话中继续 V3 开发。请先阅读本文，再检查实际工作树；不要仅依据聊天历史或 `v3/STATUS.md` 推断当前实现。

## 1. 用户的真实目标

V3 不是在 V2 提示词流水线上继续堆功能，而是重做提示词生成核心，并有选择地复用 V2 已经稳定的外围能力：

- 复用远程 SSH/ComfyUI 生图、任务队列、画廊、本地翻译和配置存储。
- 重做自然语言到 ANIMA 提示词的生成方式、标签检索、候选比较和画师推荐。
- 主要面向二次元插画、人物立绘和 ANIMA 系列模型。
- 默认离线可用；联网预览、标签数据更新和远程生图可以保留。
- V3 计划按 GPL-3.0 发布。
- `danbooru-tag-pipeline` 只作为外部数据构建工具，不作为运行时依赖。

用户当前最关心的不是“功能是否存在”，而是能否稳定地产生足够好的提示词并方便人工测试。

## 2. 已确定的方向性结论

### 2.1 自然语言主路径不能依赖 AI API 拆解

此前 V3 的自然语言模式复用了 V2 的 AI 抽取器。真实测试发现：

- 常见耗时约 50～100 秒，配置超时为 180 秒。
- 相同输入的拆解结果不稳定。
- `pose/action/lighting` 偶尔返回数组而不是字符串。
- `subject_mode` 会返回契约外枚举值，例如 `interaction`。
- 风格、构图和小道具信息容易丢失。
- 以前的对比已经表明，本地翻译生成提示词的效果通常优于 API 拆解。

因此已锁定的新主路径：

```text
中文原文
  → V2 本地翻译服务
  → 本地词典、别名、短语规则和 V3 标签索引
  → Literal 基准与显式关系 Hybrid 候选
  → 可选标签池与画师池
  → 用户确认后远程生图
```

AI API 只能作为未来显式触发的“AI 辅助拆解”，不得阻塞或清空主工作台。旧 `/api/v3/intent/parse` 接口暂时仍存在，但当前前端主流程不调用它。

### 2.2 画师和自动标签不能静默加入

原实现自动选一个画师并生成 Artist lane。用户明确认为只给一个画师无法比较，至少应展示匹配度前 10。

当前决定：

- 默认提示词不加入任何画师。
- 展示 Top 10 画师候选、匹配来源、共现数和相对分数。
- 后续支持用户选择 1～3 位画师，以固定 Seed 做对照生成。
- 普通相关标签已改为建议池；仅原文精确命中或用户确认的标签进入 Literal。

### 2.3 人工测试状态必须保留

用户曾遇到：写完描述并等待解析后，点击远程生成立即跳页；返回时所有解析和编辑结果丢失。

现阶段必须保证：

- 远程提交后留在工作台。
- 草稿、最后一次候选和工作台标题可从本地恢复。
- 保存到工作区数据库时连同候选快照和画师建议一起保存。
- 后续增强为明确的自动保存状态和跨重启恢复提示。

## 3. 仓库和 Git 状态

- 工作区：`D:\soft\提示词辅助工具`
- 当前分支：`codex/v3-development`
- HEAD：`de05ab3 Build ANIMA Prompt Studio V3 end-to-end`
- 远端分支：`origin/codex/v3-development`
- 本会话的修复尚未提交，也尚未推送。

当前已修改的跟踪文件：

```text
v3/src/anima_prompt_studio_v3/api/app.py
v3/src/anima_prompt_studio_v3/api/models.py
v3/src/anima_prompt_studio_v3/api/server.py
v3/src/anima_prompt_studio_v3/core/hybrid.py
v3/src/anima_prompt_studio_v3/core/literal.py
v3/src/anima_prompt_studio_v3/core/validation.py
v3/tests/test_api.py
v3/web/src/App.tsx
v3/web/src/components/AppShell.tsx
v3/web/src/lib/types.ts
v3/web/src/pages/WorkbenchPage.test.tsx
v3/web/src/pages/WorkbenchPage.tsx
v3/web/src/styles.css
```

应纳入后续提交的新文件：

```text
docs/v3/ISSUES_AND_RECOVERY_PLAN.md
docs/v3/PROMPT_CORE_LESSONS_AND_BOUNDARIES.md
docs/v3/SESSION_HANDOFF_2026-08-27.md
v3/web/src/pages/SettingsPage.tsx
```

工作树中还有多个未跟踪的 `tools/_real_*.py` 和 `tools/_inspect_local_db.py`。它们是本地真实生图/诊断探针，默认不要删除，也不要在不了解用途时批量加入提交。提交前应逐个审查或继续排除。

## 4. 本轮尚未提交的实现

### 4.1 V3 远程连接设置页

已加入侧栏齿轮和 `/settings` 页面，复用 V2 SQLite 配置与 Windows Credential Manager：

- 列出、新建和修改远程 SSH 配置。
- 支持密码、SSH Agent、私钥三类认证配置。
- 密码不通过 API 返回，也不写进普通配置响应。
- 可检测 SSH 主机指纹，再由用户明确确认。
- 修改主机、端口、用户名、认证方式或私钥路径时，会清除旧指纹并要求重新确认。
- 列出现有 V2 工作流；尚未在 V3 中实现“导入 ComfyUI API 工作流”。

主要文件：

- `v3/web/src/pages/SettingsPage.tsx`
- `v3/src/anima_prompt_studio_v3/api/app.py`
- `v3/src/anima_prompt_studio_v3/api/models.py`
- `v3/src/anima_prompt_studio_v3/api/server.py`

### 4.2 工作台恢复与原地远程提交

`WorkbenchPage.tsx` 当前：

- 使用 `anima-v3-workbench-recovery` 将草稿、候选和标题写入 `localStorage`。
- 初始化时恢复上一次本地快照。
- 提交远程生成后不再强制导航到 `/generate`。
- 显示“已提交到远程队列”，用户可继续比较或修改候选。
- 工作区数据库快照支持保存标签建议、画师建议与 Scene Draft。

注意：测试模式中 `loadRecoveredWorkbench()` 主动跳过恢复，以避免测试相互污染，因此目前自动化主要覆盖保存到工作区数据库，尚未专门覆盖浏览器刷新后的 `localStorage` 恢复。

### 4.3 本地自然语言候选接口

新增：

```text
POST /api/v3/local-natural/candidates
```

行为：

- 调用 V2 本地翻译适配器，不调用 AI API 抽取器。
- 从中文原文和英文译文提取本地检索词，保留原文 source span。
- 原文精确命中进入“已确认”；译文索引和相关标签进入“待确认建议”，未命中内容单独保留。
- 完整英文译文保留为可追踪 prose baseline；无安全标签命中时 Literal 仍可用，不再 422。
- 用户选择/取消建议时复用当前译文重新编译，不重新翻译或解析。
- 响应附带翻译引擎和 `local_only: true`。
- 前端自然语言入口现在由 `bootstrap.features.local_translation` 控制，不再由 `natural_language_parse` 控制。

当前仍是第一版：Scene Draft 已可选择建议，但还不能逐项编辑实体、动作、关系、构图、风格或排除事实。不要以随意补 `1girl` 或导入 V2 平铺结构的方式掩盖这些缺口。

### 4.4 画师 Top 10 候选池

默认候选生成已停止调用 `RecommendationLaneGenerator.add_artist()`：

- 默认返回 Literal、可选的显式关系 Hybrid，不再自动生成 Conservative 或 Artist lane。
- API 响应新增 `artist_suggestions`，取当前基础标签对应的前 10 个画师。
- 前端展示排名、`render_name`、命中来源、共现数和相对分数。
- 工作区候选快照模型可以保存这份建议池。
- 当前只展示，尚不能选择并重新编译提示词。

核心实现仍保留 `add_artist()`，供现有核心单元测试和未来显式选择流程使用；不要误删。

## 5. 已完成验证

最近一次验证结果：

```text
Python V3 全量：75 passed
Web：5 test files，19 passed
TypeScript/Vite 生产构建：通过
git diff --check：通过，仅有 Git 的 LF/CRLF 提示
```

复现命令：

```powershell
Set-Location 'D:\soft\提示词辅助工具'
.\.venv\Scripts\python.exe -m pytest v3\tests -q

Set-Location 'D:\soft\提示词辅助工具\v3\web'
npm test -- --reporter=dot
npm run build

Set-Location 'D:\soft\提示词辅助工具'
git diff --check
```

根目录的双击入口是：

```text
启动 ANIMA V3.cmd
```

首次数据包安装/校验可能需要 40～60 秒。关闭启动窗口会停止本地 API。

## 6. 真实远程生图结论

远程生图闭环此前已经跑通。最近主要测试的是：

- Checkpoint：`anima-aesthetic-v1.1.safetensors`
- 工作流：`22___Aesthetic_v1.1`
- Steps：30
- CFG：4
- Sampler：`er_sde`
- Scheduler：`simple`

真实测试表明，远程执行、下载和画廊不是当前主要瓶颈；提示词解析和候选质量才是。无需现在重新开启云显卡，应先把本地生成逻辑、候选选择和人工测试体验修稳，再做固定 Seed 对照。

已有本地报告目录包括：

```text
reports/v3_3080ti_scene_sweep_20260827
reports/v3_3080ti_anime_character_sweep_20260827
reports/v3_3080ti_anime_style_direct_20260827
```

这些报告通常被 Git 忽略，不要为了提交而移动或删除。

安全说明：旧会话中用户曾临时提供过云主机登录凭据。本文故意不记录任何密码。新会话也不要从聊天历史复制或持久化凭据；用户会在测试完成后删除临时云镜像。

## 7. 仍需修复的问题，按顺序

完整列表见 `docs/v3/ISSUES_AND_RECOVERY_PLAN.md`。推荐下一会话按以下顺序继续：

补充复盘结论：先阅读 `docs/v3/PROMPT_CORE_LESSONS_AND_BOUNDARIES.md`。V2 的本地翻译只能作为可编辑 prose baseline，旧 `PromptPipeline`、平铺语义结构和默认增强不能整体回接；也不要把当前“本地翻译 + 精确标签”误认为最终提示词方案。

### P0：扩展可编辑 Scene Draft

1. 从 V2 已验证失败族选择代表案例，为实体、明确事实、主动作/关系、构图、风格与排除项增加最小的逐项编辑能力，不设计万能 schema。
2. 选择性迁移 V2 中有真实失败族证据的否定、人数、冲突和概念规则，但不得导入旧 `PromptPipeline` 控制流。
3. 增加耗时统计和取消机制；本地主路径应在可感知的短时间内完成。
4. 如保留 AI 能力，增加单独的“AI 辅助拆解”按钮，结果作为草案合并，不覆盖当前工作台。

### P1：标签与画师选择池

1. 已完成：普通相关标签默认不应用，用户选择/取消标签后会复用当前译文重新编译；以 `snow → snowman/christmas` 做真实数据回归。
3. 让用户选择 1～3 位画师，生成明确标注的对照候选。
4. 固定 Seed、模型和参数，比较“无画师 / 单画师 / 多画师”的效果。

### P2：页面与文档

1. 实现可打开的画师搜索/详情页，目前只有工作台建议池和 API。
2. 增加风格预设，重点覆盖二次元插画、人物立绘、赛璐璐、线稿和构图。
3. 文档已同步当前默认路径；后续接口或候选策略变动应一起更新契约与本交接。
4. 完成后运行真实 Aesthetic v1.1 固定 Seed 回归。

## 8. 下一会话建议的起手动作

新会话开始后建议先执行：

```powershell
Set-Location 'D:\soft\提示词辅助工具'
git status --short
git diff --stat
.\.venv\Scripts\python.exe -m pytest v3\tests -q

Set-Location 'D:\soft\提示词辅助工具\v3\web'
npm test -- --reporter=dot
npm run build
```

确认基线后，优先审查以下位置：

```text
v3/src/anima_prompt_studio_v3/api/app.py
  - candidate_response
  - generate_local_natural_candidates
  - _local_natural_intent
  - _local_lookup_terms
  - _local_index_matches
  - _local_natural_intent

v3/src/anima_prompt_studio_v3/core/recommendation.py
  - add_conservative / add_artist（仅供未来显式选择；默认流程不调用）

v3/web/src/pages/WorkbenchPage.tsx
  - generate
  - localStorage 恢复
  - SceneDraftReview
  - ArtistSuggestionPool
```

不要先做大规模重构或重新跑云显卡。最小的高价值纵向切片调整为：

```text
最小 Scene Draft 的逐项编辑
  → 覆盖否定/人数/动作/关系失败族
  → 真实数据建议池回归
  → 固定 Seed 生图对照
  → 自动化测试
```

## 9. 可直接复制给新会话的提示

> 请先阅读 `D:\soft\提示词辅助工具\docs\v3\SESSION_HANDOFF_2026-08-27.md`、`docs\v3\PROMPT_CORE_LESSONS_AND_BOUNDARIES.md` 和 `docs\v3\ISSUES_AND_RECOVERY_PLAN.md`，然后检查当前 `codex/v3-development` 工作树。不要恢复以 AI API 拆解为默认自然语言主路径，也不要把本地翻译或 V2 平铺结构当成最终结构权威；不要自动把画师或普通相关标签写入提示词。先跑交接文档中的回归命令，再从“原文/译文证据 + 最小可编辑 Scene Draft + 可选标签池”这个纵向切片继续开发。保留所有现有未提交改动和未跟踪真实测试脚本，未经检查不要批量提交或删除。
