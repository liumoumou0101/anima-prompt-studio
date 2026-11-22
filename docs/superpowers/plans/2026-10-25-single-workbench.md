# 单一工作台分阶段实施计划

> **For agentic workers:** 执行本计划时按任务逐项落实，可使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans`；必须服从用户当时的执行授权和项目约束。本文是本轮要求的计划交付，不是已经开始实施的记录。

**Goal:** 让用户在一套工作台内可靠回退和继续编辑、调整工作流参数，并自动使用满足当前创作条件的环境。

**Architecture:** 保留 React/Vite 前端、FastAPI 服务、工作区版本库、V2 运行服务与现有提交恢复协议。逐步分离编辑日志、创作配置、执行策略；新增接受前的后端环境路由，最终替换展示层。

**Tech Stack:** 现有 TypeScript / React 19、Vitest / Testing Library、Python 3.12+、FastAPI / SQLite / pytest；浏览器草稿日志使用 IndexedDB。不因 UI 改造更换框架或整套组件库。

**Spec:** [单一工作台改造方案](../specs/2026-10-25-single-workbench-design.md)。规格与本计划应一起阅读；出现未覆盖的实现细节时，按现有代码模式处理并记录，不扩大产品范围。

日期：2026-10-25。所有复选框均未执行。本文中的新增文件、类型和 API 为拟定名称；已有文件的行号会变化，实施前按符号定位。

## 全局约束

- 不覆盖当前工作区已有的 conversation / prompt_guidance / requirements / prompt_language 及相关测试改动；开始实施时先确认归属并隔离新增工作。
- 不重写历史提交摘要，不改旧 pending 请求的幂等键；新协议用独立版本区分。
- 环境变化不得修改创作内容、模型、工作流版本、配方、Seed、LoRA或手动参数。
- 任务接受后不跨环境自动重发；结果不确定时恢复原请求。
- 快捷撤销最多 50 步；操作日志与草稿同事务持久化。历史版本及图片不因撤销删除。
- 新会话默认 auto；已有显式固定环境以及来源无法判定的旧草稿保留 pinned，用户可以显式转换。
- 旧图“从这张继续”默认恢复已知当时创作设置；提示词版本继续默认保留当前生成设置；两者均保留当前执行策略。
- 保留明亮 / 深色 / 系统主题，仅移除 studio / editorial 布局分支。
- 真实 LLM / GPU 验证单独记录来源与结果；mock 测试不能作为质量或真实连通性的证据。
- 方案确定的预算：探测并发 2、单候选连接 5 秒、单轮路由 15 秒、连通性正缓存 30 秒、能力缓存上限 900 秒、网络退避 30 / 60 / 120 秒。异步资源 inspection 不伪装成已通过。

## 评审重点

1. AI 成功前后发生恢复、切页、保存或冲突时，撤销链和内容基点是否一致（任务 2、3）。
2. 旧图只有批次 Seed 或旧快照缺字段时，是否伪造可重现参数（任务 3、10）。
3. 同地址同 SSH key 的新实例、弱身份与同名不同资源是否误用旧映射（任务 6）。
4. 接受事务完成但浏览器没有收到响应时，是否生成第二个 run（任务 7）。
5. 旧 direct 草稿、旧 fixed 草稿、旧 pending 和复制窗口是否发生静默覆盖或重新提交（任务 1、2、9）。

## 阶段与退出条件

| 阶段 | 任务 | 可交付结果 | 进入下一阶段前的条件 |
| --- | --- | --- | --- |
| S0 已知故障与基线 | 1 | 导入断链与环境覆盖参数修复；撤销现场可诊断 | 真实 App 路由测试和参数保留测试通过；不假称“一次撤销”根因已找到 |
| S1 连续创作 | 2–3 | 持久化撤销、可搜索版本、从任意版本继续 | 版本、草稿、多窗口和迟到响应场景通过 |
| S2 参数契约 | 4–5 | 共用参数面板、字段覆盖、声明式工作流参数 | 更换环境不变参数；模板/实际发送/历史快照一致 |
| S3 自动环境 | 6–7 | 检测、筛选、逻辑意图、原子接受与恢复 | 并发、重启、丢响应至多一次接受；失败说明准确 |
| S4 唯一工作台 | 8–9 | 新布局、同一原文路径、旧数据与链接迁移 | 尺寸与可达性检查、能力去向表及旧入口迁移通过 |
| S5 完整验收与清理 | 10 | 主流程与真实效果报告，移除确认冗余实现 | 所有必需能力有去向；已验收/未验收明确记录 |

依赖：1 → 2 → 3；1 → 4 → 5 → 6 → 7；3、5、7 → 8 → 9 → 10。任务 2 与 4 可并行设计/实现，修改 `ConversationWorkbenchPage.tsx` 的接入由同一执行者串行整合。每阶段可以独立评审和回退，不在用户设置里长期保留多套 UI。

## 任务 1：修正已确认故障并保留现场证据（S0）

**Files**

- 修改：`v3/web/src/pages/ConversationWorkbenchPage.tsx`、`v3/web/src/pages/DirectPromptPage.tsx`、`v3/web/src/lib/directPrompt.ts`、`v3/web/src/lib/generationSettings.ts`。
- 新增测试：`v3/web/src/WorkbenchImportRoute.test.tsx`；扩展 `v3/web/src/pages/ConversationWorkbenchUX.test.tsx`、`v3/web/src/lib/generationSettings.test.ts`。

**Interfaces**

- 复用现有 direct import 数据结构；新增 `readDirectImport()` 与 `acknowledgeDirectImport(importId)`，消费必须在草稿持久化/服务端接收后确认，挂载不能提前丢数据。
- 新增 `selectExecutionBinding(settings, target)`：仅变更运行绑定，不应用 recipe；后续任务 4 将绑定移出创作设置。
- 开发诊断记录 operation kind、栈长度、workspace/document/request 身份、清栈原因和构建版本；不记录完整提示词、连接凭据或访问令牌。

- [ ] 写 `direct_import_reaches_current_app_route`：从真实 `/direct` 点击到真实 `/workbench`，断言 lighthouse 文本和目标说明出现，而非旧 workspace 文本；重复挂载不重复追加，失败后可重试。
- [ ] 写 `environment_switch_keeps_custom_values`：22 steps / 3.2 CFG / dpmpp_2m / karras 换到新环境后完全相等；显式应用默认 recipe 才改变。
- [ ] 将审查时真实组件的 A→B→C→D 按钮用例纳入正式测试，并补 save、failed rewrite、unchanged rewrite、切页、冲突路径；对尚未实现的持久化行为在任务 2 实现前保持明确待完成。
- [ ] 修复导入回执和绑定选择；对“只能撤一次”的现场问题收集准确路径，区分已复现根因与预防性改进。
- [ ] 运行 `npm test -- src/WorkbenchImportRoute.test.tsx src/pages/ConversationWorkbenchUX.test.tsx src/lib/generationSettings.test.ts`（cwd `v3/web`），全部通过后单独记录/提交本任务变更。

## 任务 2：持久化、按作用范围撤销（S1）

**Files**

- 新增：`v3/web/src/lib/editorHistory.ts`、`v3/web/src/lib/editorHistoryStore.ts`、`v3/web/src/lib/useEditorHistory.ts`。
- 修改：`v3/web/src/lib/conversationDrafts.ts`、`v3/web/src/pages/ConversationWorkbenchPage.tsx`。
- 测试：新增上述纯逻辑与存储的 `.test.ts`，扩展 `conversationDrafts.test.ts` 和 `ConversationWorkbenchUX.test.tsx`。存储适配器使用可控事务替身测试，并在真实浏览器验证 IndexedDB；不让测试替身冒充浏览器持久化实测。

**Interfaces**

- `EditOperation`、`EditorJournal` 采用规格 §4.2；`scope` 为明确字段路径集合，禁止用全 LocalConversation 覆盖无关参数。
- `recordOperation(journal, operation): EditorJournal`、`undoOperation(state, journal): {state, journal}`、`redoOperation(...)` 为纯函数。
- `commitEditorState({workspaceId, documentId, local, journal}): Promise<SaveResult>`；`loadEditorState(workspaceId, documentIdentity): Promise<EditorEnvelope | null>`。`SaveResult` 返回 ok/warning，成功后才更新持久化状态提示。
- `useEditorHistory` 负责动作边界与持久化；提交 pending 仍由既有独立协议恢复，不混入撤销日志。
- 本地 `checkpointOutbox` 与草稿同事务保存，按 operationId 同步任务 3 的 checkpoint 接口；50 步之外的快照先成功归档再截快捷链，未同步副本不能删除。

- [ ] 先写 V1/V2 用例：三次 AI 三次撤销/重做；保存、生图、卸载重挂与刷新不清栈；第 51 步只截快捷链，历史仍在。后端离线时第 1 步仍在 outbox 可恢复，重连同步不重复。
- [ ] 写逐字段合并用例：800ms 内改 steps 再改 cfg 是两步；同一 textarea 连续输入可合并；IME composition、失焦、控件点击形成边界。
- [ ] 实现 journal 与草稿原子存储，沿用窗口隔离；迁移成功标记落盘后才停止读取旧槽位，失败保留原数据。
- [ ] 写复制窗口/崩溃恢复/损坏数据/QuotaExceeded 场景：游标不共写，存储失败仍能当前内存撤销且不显示“已保存”。
- [ ] 写跨窗口 revision 变化场景：本窗口保存不清栈；真正合并建立新基点，旧链可恢复但不能跨基点应用。
- [ ] 运行 `npm test -- src/lib/editorHistory.test.ts src/lib/editorHistoryStore.test.ts src/lib/conversationDrafts.test.ts src/pages/ConversationWorkbenchUX.test.tsx`，并完成真实刷新/关闭重开验收后记录结果。

## 任务 3：历史继续编辑与异步一致性（S1）

**Files**

- 新增：`v3/web/src/lib/restoreScope.ts`；修改 `WorkbenchHistory.tsx`、`workbenchHistory.ts`、`ConversationWorkbenchPage.tsx`。
- 修改：`v3/src/anima_prompt_studio_v3/api/conversation.py`、`api/workspace_store.py`；新增 `api/editor_context.py` 并在 `api/app.py` 注册。
- 测试：`restoreScope.test.ts`、`WorkbenchHistory.test.tsx`、`v3/tests/test_workspace_history.py`、新增 `v3/tests/test_editor_context.py`。

**Interfaces**

- `buildRestore(current, snapshot, scope: "content" | "creative_settings"): RestoreResult`，包含 next、changedFields、missingFields、resourceWarnings；两种 scope 都保留当前 executionPolicy。
- 历史条目附 `operation_kind、label、source_version_id、source_run_id`，查询支持 q 与有图筛选；旧记录缺字段保留可读摘要，不虚构。
- 拟新增 `POST /api/v3/workspaces/{id}/editor-context`：上下文按 `(workspaceId, documentId)` 隔离。`action: invalidate` 只失效本窗口 token、不改草稿；`action: restore` 携带 operationId、expected_revision、document_id、new_epoch 和基点快照，原子保存并失效旧 token。同 operationId 返回原回执。turn 请求增加 token；现有 revision CAS 继续有效。
- 拟新增 `POST /api/v3/workspaces/{id}/checkpoints`：按 operationId 幂等保存不可变完整快照/已有版本引用、baseRevision 与来源；不覆盖当前 workspace draft。工作区内持久化递增用户编号，旧编号不因筛选/分页变化。checkpoint 事件遵循规格 §4.2，GET 版本查询合并这些节点与关联图片。

- [ ] 写 V3/V4：从 B 继续保留当前 22 / 3.2 与 LoRA 选择，后续改写不带回 D 的内容要求；旧图主操作恢复已知设置，次级只用提示词保持当前设置。
- [ ] 写当前草稿和未发送意见的自动备份、撤销恢复、后续版本保留；备份失败则编辑区不变。
- [ ] 写缺内容快照/缺单图 Seed/旧模型或模板不可用用例：可加载已知内容，未知项明确标示，禁止填假值或静默替换。
- [ ] 实现 checkpoint 与 outbox 接口、稳定编号、搜索、预览、差异和卡片直接继续入口；来源编号与底层 revision 分离，生成记录不能替换掉可编辑版本条目。
- [ ] 写可控异步用例：AI pending 时恢复，旧结果到达也不覆盖、不自动生图；后端 token 在最终写事务失效则拒绝；若旧 turn 抢先完成则返回冲突而非强写。窗口 A 切页不使窗口 B token 失效；恢复响应丢失重试只建一个节点。
- [ ] 运行 `npm test -- src/lib/restoreScope.test.ts src/components/WorkbenchHistory.test.tsx src/pages/ConversationWorkbenchUX.test.tsx` 和 `python -m pytest tests/test_workspace_history.py tests/test_editor_context.py tests/test_workspace_fork.py`（后者 cwd `v3`）。

## 任务 4：创作配置与环境分离，共用参数面板（S2）

**Files**

- 修改：`v3/web/src/lib/types.ts`、`generationSettings.ts`、`pages/ConversationWorkbenchPage.tsx`、`pages/DirectPromptPage.tsx`、`v3/src/anima_prompt_studio_v3/api/models.py`。
- 新增：`v3/web/src/components/GenerationSettingsPanel.tsx`、`v3/web/src/lib/creationConfiguration.ts` 及各自测试。

**Interfaces**

- `CreationConfiguration {modelProfile, workflow: {id, revision}, baseRecipeId, parameterOverrides, resourceRequirements}`。
- `ExecutionPolicy = {mode: "auto", preferredEnvironmentIds: string[]} | {mode: "pinned", environmentId: string}`；resolved target 不是表单字段。
- `proposeConfigurationChange(current, nextWorkflow, schema): {compatible, incompatible, suggested}`；`applyRecipe(...)` 只在显式动作中调用。
- `GenerationSettingsPanel` 消费 configuration/schema/validation，输出单字段修改或 recipe 操作；不负责选择环境、请求网络或生图。

- [ ] 写 P1/P2：环境变化所有创作字段深相等；单项复位与应用配方能一步撤销；基于配方名称始终保留。
- [ ] 实现 common / sampling / workflow / LoRA 分组；尺寸快捷选择、数字暂存文本、错误提示与 Seed 字符串协议。
- [ ] 写 empty/NaN/越界/不支持 sampler/超大 Seed 用例；范围按模板约束，不将所有失效环境的能力求交集。
- [ ] 接入两个现有入口同一面板，确保更换模型/工作流的不兼容项显式解决后再提交。
- [ ] 运行 `npm test -- src/lib/generationSettings.test.ts src/lib/creationConfiguration.test.ts src/components/GenerationSettingsPanel.test.tsx` 和 `npm run typecheck`。

## 任务 5：工作流声明与两阶段参数（S2）

**Files**

- 新增：`v3/src/anima_prompt_studio_v3/core/workflow_parameters.py`、`v3/web/src/lib/workflowParameterSchema.ts` 及测试。
- 修改：`core/workflow_compiler.py`、`runtime/workflow_catalog.py`、`runtime/workflow_import.py`、相关明确支持模板配置、`v3/web/src/pages/WorkflowsPage.tsx`。

**Interfaces**

- `WorkflowParameterSchema` 使用规格 §5.3 字段；`resolve_workflow_parameters(schema, overrides) -> ResolvedParameters` 输出验证后的值与 schema/version 标识。
- binding 通过支持列表映射到已声明工作流输入；参数未知键、类型冲突或越界返回字段错误。

- [ ] 写基础 8 字段与高清 6 字段的解析测试；不存在第二阶段时不产生第二阶段参数。
- [ ] 将现有固定第二阶段值纳入模板声明；设置输出与编译输入共用 resolver，避免 UI 一套默认、编译另一套默认。
- [ ] 写模板更新后旧快照仍使用旧 schema/模板/实际值；固定字段不可被 override；未知复杂图继续使用固定模板/高级 JSON。
- [ ] 管理页提供声明预览与绑定校验反馈，不承诺任意图自动识别。
- [ ] 运行 `python -m pytest tests/test_workflow_parameters.py tests/test_v3_workflow_compiler.py tests/test_workflow_catalog.py tests/test_generation_recipes.py`；前端运行 `npm test -- src/lib/workflowParameterSchema.test.ts src/components/GenerationSettingsPanel.test.tsx`。

## 任务 6：环境探测与确定性筛选（S3）

**Files**

- 新增：`v3/src/anima_prompt_studio_v3/runtime/environment_probe.py`、`runtime/environment_router.py`。
- 修改：`runtime/workflow_catalog.py`、`runtime/lora_catalog.py`、`runtime/generation_queue.py`、`storage/runtime_repository.py`。
- 测试：新增 `v3/tests/test_environment_probe.py`、`test_environment_router.py`，复用 workflow inspection 替身。

**Interfaces**

- `ProbeResult {environment_id, environment_epoch, checked_at, connection_state, capabilities_state, reason_codes}`。
- `async probe_environment(profile, deadline, expected_epoch) -> ProbeResult`；`async resolve_environment(intent_snapshot, policy, deadline) -> ResolutionResult`。
- ResolutionResult 包含 eligible target 或 blocked，以及 checked/unchecked 候选、游标、轮次、原因与检测时间；没有权力创建 run 或改变创作配置。任务 7 将游标持久化，继续检查优先 unchecked。
- 缓存 key 包含配置指纹、environment_epoch、模板及映射版本；“此环境已重建”显式递增 epoch。未知实例身份按弱证据处理。

- [ ] 使用 fake clock 和连接替身覆盖 2 并发、5 秒候选、15 秒单轮、30/900 秒缓存与退避；不以真实网络睡眠测试超时。
- [ ] 写五失效一可用、首选离线、固定模式离线、资源缺少、工作流版本不匹配；只返回相同创作条件的候选。
- [ ] 写预算耗尽但仍有 unchecked 的场景，返回“待继续检查”，不能标所有环境离线；继续检查从未检查候选推进，末位可用环境不能被前面失败候选长期饿死。
- [ ] 写原址重建、配置变动、未知指纹、弱身份能力刷新、同名不同资源；失效结果不能回写新 epoch 的缓存。
- [ ] 提取已有检测能力并传递底层超时；合并同环境并发 probe，取消或迟到结果不得突破 epoch。
- [ ] 运行 `python -m pytest tests/test_environment_probe.py tests/test_environment_router.py tests/test_workflow_inspection.py tests/test_remote_profile_delete_races.py`。

## 任务 7：逻辑意图、原子接受与恢复（S3）

**Files**

- 新增：`v3/src/anima_prompt_studio_v3/api/generation_intents.py`、`storage/generation_intents.py`、`v3/web/src/lib/generationIntents.ts`、`components/ExecutionEnvironmentControl.tsx`。
- 修改：`api/app.py`、`runtime/submissions.py`、`storage/generation_submissions.py`、`v3/web/src/lib/conversationDrafts.ts`、`pages/ConversationWorkbenchPage.tsx`。
- 测试：新增 `v3/tests/test_generation_intents.py`、`generationIntents.test.ts`、`ExecutionEnvironmentControl.test.tsx`，扩展现有 submissions/source 测试。

**Interfaces**

- `POST /api/v3/generation-intents` 使用 `Idempotency-Key`（前端 clientRequestId），body 为不可变 source/prompt/creationConfiguration/executionPolicy；资源与锁定由服务端版本核对。
- `GET /api/v3/generation-intents/{id}`；`POST .../{id}/retry-resolution` 同意图继续检查；`POST .../{id}/cancel` 仅取消未接受意图。
- `IntentState = resolving | blocked | accepted | canceled`。blocked 带 `retryable` 和 reason；修改输入、revision 冲突、非法参数等不可原请求自动修复。
- 同工作区 SQLite 数据库新增 generation_intents：id/key 唯一、logical_hash、request_json、state、lease_owner/epoch/until、candidate_progress_json（顺序/证据/游标/轮次）、resolved_target_json、submission_id/run_id、result_json。
- `accept_in_transaction(db, ..., intent_id, lease_epoch)` 从现有接受逻辑提取，原子写 intent 与 submission；旧 `SubmissionStore.accept` 使用同 helper，保持旧摘要行为。
- 前端 pending 记录带 `protocol: legacy | intent-v1`，key 与冻结 body；恢复先查询原记录，不重新组装。

- [ ] 写 20 次并发同键仅 1 intent/submission/run；同键不同内容 409；查询重试先找已接受回执再看当前草稿。
- [ ] 写探测中取消、租约过期、旧 resolver 迟到、接受事务前后进程崩溃；任何分支不产生半个接受记录或第二个 run。
- [ ] 写接受后浏览器丢响应、随后用户改草稿再重试仍返回原 run；提交不确定不自动换机。
- [ ] 实现异步解析租约和 budget，接受事务再验证 revision/token/资源指纹；全局参数错误不浪费时间轮换所有环境。
- [ ] 接入自动/固定面板，显示实际已选环境、原因和检测时间；接受前的预计目标不标为最终目标。
- [ ] 运行 `python -m pytest tests/test_generation_intents.py tests/test_generation_submissions.py tests/test_generation_run_source.py tests/test_session_recovery.py`；前端运行 `npm test -- src/lib/generationIntents.test.ts src/components/ExecutionEnvironmentControl.test.tsx src/lib/conversationDrafts.test.ts`。

## 任务 8：搭建唯一工作台与统一导入反馈（S4）

**Files**

- 修改：`v3/web/src/components/ConversationStudioView.tsx`、`conversationStudio.css`、`AppShell.tsx`、`WorkbenchImageResults.tsx`、`WorkbenchHistory.tsx`、`PersonalPromptTransfer.tsx`。
- 修改：`pages/ConversationWorkbenchPage.tsx`、`pages/conversationWorkbench.css`、`styles.css`；按职责新增 `components/PromptEditor.tsx`、`RewriteComposer.tsx`、`WorkbenchResourcePanel.tsx`。
- 配套页面：`pages/ReferencesPage.tsx`、`ArtistSearchPage.tsx`、`PersonalTagsPage.tsx`、`GenerationPage.tsx`；按同一视觉体系压缩顶部说明/筛选占位，改善无样图状态与任务来源呈现，不改检索、收藏和数据权限语义。
- 测试：扩展 `ConversationStudioView.test.tsx`、`ConversationWorkbenchUX.test.tsx`、`PersonalPromptTransfer.test.tsx` 与实际 App 路由测试。

**Interfaces**

- 继续沿用 ConversationStudioView 展示插槽边界，新增 `inspectorView: results | parameters | versions` 和对应 onChange；展示组件不读写 workspace 或调用生成 API。
- PromptEditor 接收内容/撤销状态/来源；RewriteComposer 接收意见、改写模式与操作回调；ResourcePanel 输出明确的 import action，不直接污染编辑状态。
- 共享 controller 组合任务 2、3、4、7；不再让展示布局定义数据保存和请求恢复时机。

- [ ] 按规格结构实现两列/单栏及参数版本切换；保留插槽组件身份，切面板不卸载草稿控制器。
- [ ] 移除 fixed dock，常用参数与生成条在布局流中；意见未应用提示贴近生成动作。
- [ ] 资源导入预览包含来源、目标创作、写入位置、增量差异和可撤销结果；保留各类导入语义。
- [ ] 结果页加缩略图、来源版本和实际参数详情；角色画师/场景在一层工具入口可达。
- [ ] 配套页面让首批参考图片更早可见；无样图画师显示准确状态与筛选入口；个人标签在窄屏取消多列嵌套滚动；任务页显示缩略图与来源版本。各页保留已有过滤条件与返回位置。
- [ ] 浏览器实查 1366×768、900×768、390px、200% 缩放；键盘导航/焦点返回/Esc/IME/无 hover 使用；明暗主题测量文字对比度。
- [ ] 运行 `npm test -- src/components/ConversationStudioView.test.tsx src/pages/ConversationWorkbenchUX.test.tsx src/components/PersonalPromptTransfer.test.tsx src/WorkbenchImportRoute.test.tsx`；记录截图与问题，不把 jsdom 作为几何布局验证。

## 任务 9：入口、草稿与布局偏好迁移（S4）

**Files**

- 修改：`v3/web/src/App.tsx`、`pages/DirectPromptPage.tsx`、`lib/directPrompt.ts`、`lib/appearance.ts`、`appearance.css`、`pages/SettingsPage.tsx`、`lib/conversationDrafts.ts`。
- 新增：`v3/web/src/lib/workbenchMigration.ts` 及测试；新界面迁移报告 `docs/v3/SINGLE_WORKBENCH_MIGRATION.md`。

**Interfaces**

- `migrateWorkbenchState(legacy, context): MigrationResult` 是可重复运行的迁移，返回数据/警告/消费回执；迁移完成标记在新持久化成功后写入。
- `/direct` 保留兼容入口到工作台原文编辑；`/workbench/conversation` 保留别名。不再新建第二套编辑 controller。
- appearance layout 旧值映射 unified，theme 原值保留；旧 pending 协议原样恢复。

- [ ] 覆盖旧 direct 草稿、项目名称、原文与词典回译；无 LLM 配置仍能使用真实可见原文提交。
- [ ] 覆盖旧显式环境→pinned、来源未知→pinned、可证明的全局默认→auto 偏好、用户显式转换；迁移不猜测缺失的 provenance。
- [ ] 覆盖历史任务、未知提交、复制窗口、损坏旧 JSON、存储不足、重复迁移；不生成新任务或覆盖用户原草稿。
- [ ] 去掉用户可见 layout 选择；记录内部回退方法与数据兼容边界，不删除新旧日志。
- [ ] 运行 `npm test -- src/lib/workbenchMigration.test.ts src/lib/appearance.test.ts src/lib/conversationDrafts.test.ts src/WorkbenchImportRoute.test.tsx`，使用匿名化旧数据副本进行一次升级/回退演练。

## 任务 10：能力覆盖、真实效果与最终清理（S5）

**Files**

- 盘点：`v3/web/src/pages/WorkbenchPage.tsx` 及旧 tests、`pages/DirectPromptPage.tsx`、旧布局 CSS、相关 imports。
- 更新：`v3/web/design-qa.md`、`v3/STATUS.md`、`docs/v3/SINGLE_WORKBENCH_MIGRATION.md`。
- 新增报告：`reports/single-workbench-acceptance/`（本地证据）与仓库中的简短验收索引。

- [ ] 对规格 §8 每项能力填写当前入口/新入口/测试/处置；旧候选编译、场景事实归属、同 Seed 画师对照、本地翻译未处置时不得删除其实现。
- [ ] 将明确保留的旧独有功能迁到统一高级工具并补行为测试；若建议退役，单独说明用户影响，不能由清理提交暗中删除。
- [ ] 跑前端全套 `npm test -- --reporter=dot`、`npm run typecheck`、`npm run build`；后端运行全部受影响模块以及 submissions / history / recovery / compiler / workflow / imports 回归。失败先定位，不能仅更新快照使其通过。
- [ ] 使用隔离测试数据验证完整路径：导入 → 连续改写 → 多次撤销 → 从 B 继续 → 改参数 → 自动选环境 → 图片关联版本 → 从旧图继续。
- [ ] 有可用且授权的实测环境时执行固定案例：保持人物与构图只改光线、只改局部衣着、保留锁定标签；核对实际发送文本、工作流参数与图像。视觉效果人工判断并记录，不将“看起来相似”当作参数未生效。
- [ ] 实测标准工作流与明确支持的高清流程；记录实际模型/模板/资源标识、单图 Seed、快照、输出和耗时。验证断线恢复原任务；不通过故意重复付费生成来证明幂等。
- [ ] 在能力、迁移与回归均通过后移除确定冗余的布局和组件，复查引用、包构建与启动；若尚缺真实环境，明确哪些项未验收，不能宣称完整发布通过。

## 首次实施应从哪里开始

从任务 1 开始，随后执行任务 2 与任务 4 的基础模型；先让行为稳定，再搬进新界面。当前方案、草图和清单是本轮的全部交付，产品代码、数据库与连接设置均保持本轮开始时状态。
