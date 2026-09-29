# Personal Tag Market Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 V3 交付能自由维护、组合和使用旧标签资产的个人标签超市，并完成真实数据迁移。

**Architecture:** 使用独立 `personal-tags.db` 和同源 FastAPI 接口，前端提供选词与管理两个视图。独立原文传递记录把组合追加到工作台，通过工作台数据库内的事务回执防止重复执行。旧 PostgreSQL 仅为一次性只读导出来源。

**Tech Stack:** Python 3.12+、现有 FastAPI/Pydantic、标准库 sqlite3、React/TypeScript、现有 CSS 外观变量、pytest、Vitest/Testing Library；不新增运行依赖。

**Spec:** `docs/superpowers/specs/2026-09-29-personal-tag-market-design.md`（用户已于 2026-09-29 确认）。

**状态：** 待用户审核计划及选择执行方式；当前只编写文档，未开始产品实现。

## Global Constraints

- 导航新增「个人标签超市」，路径 `/personal-tags`。
- 使用现有 `workspace_db` 同目录的独立 `personal-tags.db`，通过同源 FastAPI 接口访问。
- 不修改只读参考数据包，不向 V2 旧流水线加入业务逻辑，不增加 PostgreSQL 常驻依赖。
- 权重必须是有限数值，范围 0.1–2.0，步长 0.05，可手输；1.0 输出原文。
- 原始内容作为独立字段保存；搜索规范化键只用于检索，不用作条目主键，也不覆盖原文。
- 修改本次权重不写回词库；保存组合保留条目内容快照。
- 原文、逗号、换行、大小写和下划线保持不变，不自动翻译或调用模型。
- 删除采用回收站；非空分类不隐式删除其标签或子分类。
- 原 PostgreSQL 数据保持可供核对，正常使用无需 Docker。
- 用户数据库和完整导出不提交进 Git；避开现有参考案例库未提交文件。

## Review Focus

1. 包含 `%`、`_`、引号、中文及 HTML 样式文本的查询和内容：按文字检索、显示和导出，不变成 SQL 通配符或 HTML（任务 1、5）。
2. 多标签页乱序响应、编辑期间保存失败：新搜索不能被旧响应覆盖，冲突不能静默覆盖用户修改，组合可恢复（任务 3–5）。
3. 导入预览后数据变化，以及非法记录夹在有效记录之间：拒绝过期预览，事务失败不能留下半批数据（任务 2、3）。
4. 工作台已经保存追加、浏览器却未消费记录：重试只返回回执和最新状态，不重复追加、不覆盖后续编辑（任务 6）。
5. 只有负向内容、目标正向为空，以及撤销后正向变空：不伪造正向或报假成功，保留待用内容；撤销能恢复追加前的空会话状态（任务 6）。

## 执行方式与工作区

建议当前对话连续实现，每个任务完成后运行针对性检查，最后做一次独立整体审查。任务共享数据契约和同一追加链路，连续实现能减少接口交接；用户也可选择按任务交给子代理并逐项独立审查。

计划审核时一并确认使用隔离工作区。获确认后先检查本聊天附件；若仍无合适工作区，用原生 `create_worktree` 从当前 `codex/workbench-ux-fixes` 建立 `personal-tag-market`，以返回路径为实际工作目录，不从 `origin/main` 开始。用户未提交的参考案例工作保持在原目录。

测试复用原目录 Python 解释器 `D:\soft\提示词辅助工具2\.venv\Scripts\python.exe`，以隔离目录 `v3` 为工作目录，依靠 pytest 配置加载该工作区源码。前端在隔离目录 `v3/web` 执行 `npm ci`。预览服务显式设置指向隔离目录 `v3/src` 和 `src` 的 `PYTHONPATH`，避免 editable install 加载原目录代码。

开始前记录原目录状态，并运行下方已有相关回归作为基线。若失败，记录命令与失败原因，区分原有问题和本次变化；不能将基线失败报告为本次通过。

## 任务 1：独立个人库与数据契约

**Files:** 新增 `v3/src/anima_prompt_studio_v3/core/personal_tags.py`、`v3/src/anima_prompt_studio_v3/storage/personal_tags.py`、`v3/src/anima_prompt_studio_v3/storage/personal_tag_compositions.py`、`v3/tests/test_personal_tags.py`。

**Interfaces:**

- `PersonalTagStore(path: Path)` 初始化带版本的 SQLite，启用外键和有限 busy timeout，写入以事务完成。
- `TagWrite`：`display_name: str, content: str, aliases: list[str], category_id: str | None, kind: Literal['tag','fragment'], notes: str, default_weight: float`。内容仅检查非空和长度，不能 trim 后覆盖原文。条目单项内容上限 20,000 字符；标签名 200、备注 4,000、别名每项 200。
- `TagRecord` 在写入字段外包含 `id: str, revision: int, created_at: str, updated_at: str, deleted_at: str | None, source_key: str | None, source_id: str | None, source_metadata: dict, needs_review: list[str]`。
- `CategoryWrite(name: str, parent_id: str | None, position: int)`；记录另含稳定 ID、revision、来源字段、时间和 deleted_at。
- `list_tags(*, q='', category_id=None, include_descendants=True, trash=False, offset=0, limit=60) -> dict` 返回 `{items,total,offset,limit,has_more}`；limit 最大 200，稳定排序为规范化中文名、原文、ID。
- `get_tag(tag_id: str) -> TagRecord` 返回含回收站状态的单项；不存在时抛 PersonalTagNotFoundError。
- `create_tag(value: TagWrite) -> TagRecord`、`update_tag(tag_id: str, value: TagWrite, *, expected_revision: int) -> TagRecord`、`set_tag_deleted(tag_id: str, deleted: bool, *, expected_revision: int) -> TagRecord`。
- `list_categories(*, trash=False) -> list[CategoryRecord]`、`create_category(value: CategoryWrite) -> CategoryRecord`、`update_category(category_id: str, value: CategoryWrite, *, expected_revision: int) -> CategoryRecord`、`set_category_deleted(category_id: str, deleted: bool, *, expected_revision: int) -> CategoryRecord`。
- `move_tags(items: list[dict], category_id: str | None) -> int`；items 为 `{id,revision}`，全批成功或全批回滚。非空分类检查包括回收站条目，保证可恢复引用。
- `normalize_search(value: str) -> str` 只生成 NFKC/casefold/下划线空格等价搜索键；原文与稳定 ID 独立。所有值绑定 SQL 参数，LIKE 特殊字符转义。
- 冲突抛出 `PersonalTagConflictError`，缺失抛出 `PersonalTagNotFoundError`，输入问题抛出 `ValueError`；全库另维护 `library_revision`，供导入预览检查。
- `CompositionItem`：`id: str, source_tag_id: str | None, display_name: str, content: str, kind: Literal['tag','fragment'], polarity: Literal['positive','negative'], weight: float`。数组顺序就是输出顺序，保存内容快照；每个组合最多 300 项，输出每段最大 20,000 字符。
- `CompositionWrite(name: str, items: list[CompositionItem])`；`CompositionRecord` 另含 `id,revision,created_at,updated_at,deleted_at`，字段类型与 TagRecord 对应字段相同。
- `PersonalTagCompositions(path: Path)` 与个人库使用同一数据库：`list(*, trash: bool = False) -> list[CompositionRecord]`、`create(value: CompositionWrite) -> CompositionRecord`、`update(id: str, value: CompositionWrite, *, expected_revision: int) -> CompositionRecord`、`set_deleted(id: str, deleted: bool, *, expected_revision: int) -> CompositionRecord`。
- `PersonalTagCompositions.get(id: str) -> CompositionRecord` 返回组合详情，不存在时使用同一 NotFound 错误。
- `get_draft() -> dict` 和 `save_draft(items: list[CompositionItem], *, expected_revision: int) -> dict` 返回 `{items,revision,updated_at}`；单一 current 草稿初始 revision=0。记录更新有各自 revision，library_revision 记录分类、条目和命名组合的变动，草稿自动保存不导致导入预览失效。

- [ ] 写失败测试 `test_search_keeps_raw_variants_and_literal_wildcards`：`long hair` 与 `long_hair` ID 不同、都能被中文/别名查到；搜索 `%` 只匹配字面 `%`。
- [ ] 写失败测试 `test_category_cycle_nonempty_delete_and_bulk_move_are_atomic`、`test_stale_edit_preserves_saved_value`、`test_trash_restore_keeps_source_metadata`，断言异常后行数、父级和原文未变。
- [ ] 写失败测试 `test_composition_snapshots_survive_source_edit_delete_and_reload`、`test_stale_draft_save_returns_conflict`，断言快照不随原条目变化、旧草稿 revision 不能覆盖新值；任务 2 可直接使用该持久化契约做完整备份测试。
- [ ] 从隔离目录 `v3` 运行 `& 'D:\soft\提示词辅助工具2\.venv\Scripts\python.exe' -m pytest tests/test_personal_tags.py -q`，确认失败来自尚未实现的接口。
- [ ] 实现上述契约、分类后代查询、稳定分页、回收站和事务；相近项单独按规范化键查询，不能作为唯一索引。
- [ ] 重跑该测试文件至通过，仅提交本任务文件：`feat(v3): add independent personal tag storage`。

## 任务 2：可预览、可恢复的导入导出

**Files:** 新增 `v3/src/anima_prompt_studio_v3/storage/personal_tag_import.py`、`v3/src/anima_prompt_studio_v3/tools/export_legacy_tags.py`、`v3/tests/test_personal_tag_import.py`、`v3/tests/fixtures/personal_tags_legacy.json`；必要时扩展任务 1 的模型。

**Interfaces:**

- 旧库中间格式：`{format:'anima-legacy-tags',version:1,source_key:str,categories:list[dict],tags:list[dict]}`，原始行仅来自 sys_categories/sys_tags，不导出用户、密码或网站配置。
- 新库备份格式：`{format:'anima-personal-tags',version:1,source_key:str,categories:list[dict],tags:list[dict],combinations:list[dict],draft:dict | None}`，保存稳定 ID、来源、回收站状态和完整快照。
- `ImportOptions(use_legacy_weights: bool = False, fragment_ids: list[str] = [])`；片段候选由导入预览供用户勾选。默认新权重 1.0，旧值始终留在元数据。
- `preview_import(store: PersonalTagStore, document: dict, options: ImportOptions) -> dict` 返回 `digest,library_revision,counts,issues`；digest 是文档与选项的规范 JSON 的 SHA-256；counts 包含 `new,existing,invalid,similar,unmapped,fragment_candidates,legacy_weights`。不写库。
- `commit_import(store: PersonalTagStore, document: dict, options: ImportOptions, *, digest: str, expected_library_revision: int) -> dict` 重新校验摘要和库版本，在同一事务内写分类/条目/组合；重复来源 ID 跳过且不覆盖用户修改。无效记录阻止整批写入，问题列表供修正后重试。
- `export_bundle(store: PersonalTagStore) -> dict` 导出版本化完整内容；`backup_database(store: PersonalTagStore) -> Path` 用 SQLite backup API 保存到同目录 `personal-tags-backups`，不直接复制正在写入的 WAL 数据文件。
- `export_legacy_tags.main(argv: list[str] | None = None) -> int` 支持 `--container pg-local --database postgres --output <绝对路径>`。用参数列表调用 `docker exec -i ... psql`、固定 SELECT 和 `BEGIN READ ONLY`，导出 UTF-8 JSON；不拼接 SQL 标识符或输出凭据。
- 分类只采纳唯一匹配；不能定位的保留原根分类并标记，近似变体不合并。相同 source_key/source_id 生成或映射到稳定 ID，避免重复导入分类。

- [ ] 写失败测试 `test_legacy_import_preserves_variants_fragments_weights_and_unmapped_paths`：相近两条均保留，片段内部逗号/换行不变，默认使用权重 1.0 且元数据包含原值，模糊分类仍有原始路径。
- [ ] 写失败测试 `test_reimport_does_not_overwrite_local_edits`、`test_invalid_or_stale_import_rolls_back_all_records`、`test_export_roundtrip_keeps_ids_trash_and_snapshots`；断言第二次新增数为 0、编辑内容未变、失败前后库一致。
- [ ] 运行 `python -m pytest tests/test_personal_tag_import.py -q`，确认预期失败后实现预览、事务写入、备份和只读导出。
- [ ] 重跑上述测试与任务 1 测试至通过；用小样验证导出 CLI 的 JSON 编码，不接触真实库写入。
- [ ] 仅提交相关文件：`feat(v3): add lossless personal tag import and export`。

## 任务 3：受保护 API 与前后端契约

**Files:** 新增 `v3/src/anima_prompt_studio_v3/api/personal_tags.py`、`v3/tests/test_personal_tag_api.py`、`v3/web/src/lib/personalTags.ts`；修改 `v3/src/anima_prompt_studio_v3/api/app.py` 注册。

**Interfaces:**

- 使用任务 1 的分类、条目、组合和草稿接口，以及任务 2 的导入导出接口；不另建一套组合存储。版本冲突返回当前版本，但不覆盖请求中的待保存内容。
- `register_personal_tag_routes(app, workspace_db: Path, require_session)` 在现有 workspace_db 非空分支注册；全部端点复用 require_session 和统一错误格式。
- TypeScript `personalTags.ts` 导出与后端同名记录类型及 `personalTagsApi` 对象，其方法对应下表，统一使用 `apiRequest`。
- GET 筛选参数放 query；DELETE 的 expected_revision 放 query；其余写请求和恢复请求使用 JSON body。更新记录请求为 `{value,expected_revision}`；恢复请求为 `{expected_revision}`；批量移动为 `{items:[{id,revision}],category_id}`。

| 路径（前缀 `/api/v3/personal-tags`） | 方法与行为 |
|---|---|
| `/categories`、`/categories/{id}` | GET/POST 列出/新建；PUT 带 expected_revision 编辑；DELETE 带 expected_revision 回收 |
| `/categories/{id}/restore` | POST 带 expected_revision 恢复，父级不可用时返回可理解错误 |
| `/tags`、`/tags/{id}` | GET 搜索/详情；POST 新建；PUT 编辑；DELETE 回收，写操作遵循记录 revision |
| `/tags/{id}/restore`、`/tags/bulk-move` | POST 恢复/事务批量移动；静态路由先于动态 ID 路由 |
| `/combinations`、`/combinations/{id}` | GET/POST/PUT/DELETE 命名组合与回收；`/{id}/restore` POST 恢复 |
| `/draft` | GET/PUT 当前组合，PUT 包含 expected_revision |
| `/imports/preview`、`/imports/commit` | POST 文档与选项，commit 另带 digest 和 expected_library_revision |
| `/export` | GET JSON 下载；Content-Disposition 使用固定安全文件名 |

- [ ] 写失败测试 `test_personal_api_works_without_reference_pack`、`test_personal_routes_require_session`、`test_api_conflicts_preserve_existing_data`，分别断言独立可用、401、409 与数据不变。
- [ ] 写失败测试 `test_composition_api_roundtrip_and_stale_draft_conflict`，通过 API 保存/读取组合和草稿，确认快照原文不变、旧 revision 返回 409。
- [ ] 运行 `python -m pytest tests/test_personal_tag_api.py -q`，确认失败后实现 API 和前端类型；导入请求限制为 50 MiB，分页/文本/有限权重由模型校验，输入错误返回 422，资源缺失 404，版本冲突 409。
- [ ] 重跑个人模块全部后端测试及 session 相关测试至通过，核对 API 导出和任务 2 底层导出内容一致。
- [ ] 仅提交相关文件：`feat(v3): expose personal library and composition APIs`。

## 任务 4：可恢复组合及精确输出

**Files:** 新增 `v3/web/src/lib/personalTagComposition.ts`、其 `.test.ts`、`v3/web/src/pages/personalTags/usePersonalComposition.ts`、其 `.test.tsx`。

**Interfaces:**

- `addCompositionItem(items: CompositionItem[], tag: TagRecord, polarity: 'positive' | 'negative'): CompositionItem[]` 同一 source_tag_id/方向只加入一次；不同来源 ID 不按文本合并。
- `renderComposition(items: CompositionItem[]): {positive: string; negative: string; warnings: string[]}` 保留每项原文，项间用 `, ` 连接；权重 1 原文输出，其他输出 `(原文:去除无意义尾零的数值)`；正负同内容提示但不删除。
- `moveCompositionItem(items, itemId, direction: -1 | 1): CompositionItem[]` 只调整同一区顺序；其他操作使用明确 item ID，不能按文本误改其他条目。
- `usePersonalComposition()` 返回 `items,setItems,saveState,error,flush,reload`；服务端草稿为持久来源，本地 immediate cache 只用于未完成保存的恢复。保存串行化，基于最近成功 revision；离开/带入前调用 flush，冲突保留输入并提供重新加载。

- [ ] 写失败测试 `preserves_raw_text_and_formats_explicit_weights`，断言 `Blue_eyes` 保持大小写/下划线，片段 `a, b\nc` 不拆分，1.1 输出 `(Blue_eyes:1.1)`，NaN/Infinity/越界拒绝。
- [ ] 写失败测试 `deduplicates_only_same_source_and_side`、`does_not_mutate_library_defaults`、`restores_unsaved_composition_after_reload`、`serializes_saves_and_preserves_draft_on_conflict`。
- [ ] 在 `v3/web` 运行 `npm test -- src/lib/personalTagComposition.test.ts src/pages/personalTags/usePersonalComposition.test.tsx`，确认失败后实现纯函数与草稿 hook。
- [ ] 重跑至通过，并运行 `npm run typecheck`。类型错误须在当前任务修复，不能用 any 掩盖接口不一致。
- [ ] 提交：`feat(v3): add recoverable personal prompt compositions`。

## 任务 5：选词与管理两个视图

**Files:** 新增 `v3/web/src/pages/PersonalTagsPage.tsx`、`PersonalTagsPage.test.tsx`、`personalTags.css`；在 `pages/personalTags/` 新增 `CategoryTree.tsx`、`TagPicker.tsx`、`CompositionPanel.tsx`、`TagManager.tsx`、`TagEditor.tsx`、`CategoryEditor.tsx`、`ImportDialog.tsx` 和 `usePersonalCatalog.ts`；修改 `App.tsx`、`components/AppShell.tsx` 及相应导航测试。

**Interfaces:**

- `PersonalTagsPage()` 注册 `/personal-tags`，两视图共享 catalog 和 composition；所有新样式限定 `.personal-tags-page`，使用现有外观变量和 Phosphor 图标，不改 `libraryPages.css`。
- `usePersonalCatalog()` 管理 `q,categoryId,includeDescendants,trash,page,items,total,categories,refresh`；搜索请求使用取消/序号保护，旧响应不能覆盖最新条件。
- 组件以任务 3/4 类型传递 props，编辑器回调 `onSave(value: TagWrite, expectedRevision?: number): Promise<void>`，保存失败保持表单。
- 管理视图涵盖标签新增/编辑/回收/恢复、分类新增/改名/移动/排序/回收/恢复、批量移动、相近项提示。组合面板涵盖排序、正负位置、权重、复制、命名保存/加载/回收/恢复。
- 导入对话框选择本地 JSON → 预览问题与候选类型/旧权重选项 → 提交，选项变化后重新预览；导出下载使用当前 API 内容。浏览时查看原始来源字段为只读，不能误当成编辑后数据。
- 保存条目或分类后刷新结果，保持当前组合快照。编辑离开有未保存确认，按钮有可访问名称，动态结果用适度 aria-live。

- [ ] 写失败行为测试 `browses_descendants_and_searches_aliases`、`keeps_selection_across_modes_and_refresh`、`edits_and_restores_without_changing_composition_snapshot`、`ignores_stale_search_responses`。
- [ ] 写失败行为测试 `previews_import_options_before_commit`、`copies_exact_positive_and_negative_text`、`renders_imported_html_as_text`、`supports_category_cycle_error_and_failed_save_recovery`。
- [ ] 运行 `npm test -- src/pages/PersonalTagsPage.test.tsx`，确认失败后实现两个视图和路由导航；桌面参考已选效果图，窄屏顺序重排而不裁剪核心控件。
- [ ] 重跑个人页、原标签页和 AppShell 测试，并执行 `npm run typecheck`；验证所见按钮有实际行为，非首版功能不放空按钮。
- [ ] 提交：`feat(v3): add personal tag browsing and management views`。

## 任务 6：工作台原文追加、回执与撤销

**Files:** 新增 `v3/src/anima_prompt_studio_v3/api/personal_prompt_transfer.py`、`v3/tests/test_personal_prompt_transfer.py`、`v3/web/src/lib/personalPromptTransfer.ts` 及 `.test.ts`、`v3/web/src/components/PersonalPromptTransfer.tsx`；修改 `v3/src/anima_prompt_studio_v3/api/workspace_store.py`、`v3/src/anima_prompt_studio_v3/api/app.py`、`v3/web/src/pages/ConversationWorkbenchPage.tsx` 及其测试。不更改旧 `contentTransfer.ts` 的单标签契约。

**Interfaces:**

- `storePersonalPromptTransfer(value: {positive:string;negative:string}): string` 写独立 localStorage 命名空间并返回 `/workbench?personal_transfer=<uuid>`；内容不得出现在 URL。`readPersonalPromptTransfer(id)` 校验版本、非空总内容和每段 20,000 字符上限；`consumePersonalPromptTransfer(id)` 仅在后端确认已应用后执行。
- 工作台先 flush 自己的未保存编辑，再显示追加前后预览；取消不改正文。源组合留在个人库。无当前会话时复用现有创建幂等键，键与传递 ID 固定绑定。
- `WorkspaceStore.append_personal_prompt(workspace_id: str, *, transfer_id: str, expected_revision: int, positive: str, negative: str) -> dict`；返回 `{workspace,receipt,replayed}`，receipt 包含 ID、工作台 ID、result_revision、state 和 can_undo。
- 新增 `workspace_prompt_transfers` 表，存 transfer_id、workspace_id、payload_hash、before_compiled_json、after_positive、after_negative、result_revision、state、created_at。回执与 `_save_revision` 同一个 `BEGIN IMMEDIATE` 事务写入；先查回执再检查 revision。
- 同一 ID 和相同正文重试返回回执及工作台当前状态，不返回旧版本覆盖后续修改；相同 ID 不同内容/目标拒绝 409。待处理 proposal 不得被 `_save_revision` 隐式清除，必须在写入前拒绝并提示处理。
- 构造 `apply_workspace_edit` 输入时保留当前 draft 的模型和生成配置等字段，只替换 prompt_edit，不能只传一个 prompt_edit 对象导致现有字段被投影默认值覆盖。前端等待确认时禁用重复提交；收到重放响应后，如又存在本地未保存修改，先进入现有冲突/合并流程，不直接替换本地状态。
- `WorkspaceStore.undo_personal_prompt(workspace_id: str, *, transfer_id: str, expected_revision: int) -> dict`；只在当前正负文本仍等于回执 after 文本时恢复追加前 compiled 状态，保留当前其他字段，记录撤销回执。原先无 compiled 时恢复为 None，不伪造非空正向。重复撤销不产生新版本，已撤销 transfer 不得重放追加。
- 新增受 session 保护的 `POST /api/v3/workspaces/{id}/personal-prompt-transfers` 与 `POST /api/v3/workspaces/{id}/personal-prompt-transfers/{transfer_id}/undo`，GET 后者不带 `/undo` 查询回执用于刷新恢复；接口错误沿用 workspace 冲突/未找到格式。
- 如果目标与组合的正向都为空，预览提示「请先在工作台填写正向提示词，再追加这段负向内容」，禁止提交，保留传递记录和组合；取消后仍可单独复制负向。沿用已有非空正向契约，不伪造提示词。
- 工作台因生成中、建议待处理或版本冲突不能写入时保留预览；正文继续编辑后禁用快照撤销并显示 spec 指定文案。更新提示词依旧是用户另行发起的操作，追加不触发 AI 或生成。

- [ ] 写失败后端测试 `test_append_retry_after_lost_response_is_exactly_once`、`test_retry_returns_latest_workspace_without_overwriting_later_edits`、`test_key_reuse_with_other_payload_conflicts`。
- [ ] 写失败后端测试 `test_pending_proposal_and_revision_conflict_do_not_consume_transfer`、`test_undo_preserves_settings_and_handles_original_empty_prompt`、`test_undo_after_further_prompt_edit_is_rejected`、`test_undone_transfer_never_reapplies`。
- [ ] 写失败前端测试 `previews_cancels_and_recovers_personal_transfer`、`keeps_transfer_on_save_failure`、`negative_only_empty_target_is_not_false_success`；断言原有正文/设置保留、取消无写入、只有回执成功才消费。
- [ ] 先运行新增前后端测试确认失败，再实现回执事务、API 和独立预览组件；复用 `apply_workspace_edit`/现有手工保存语义，输入、输出限制与现有 PromptEdit 保持一致。
- [ ] 运行 `python -m pytest tests/test_personal_prompt_transfer.py tests/test_workspace_creation_idempotency.py tests/test_workspace_history.py tests/test_workbench_direct_generation.py tests/test_manual_identity_tags.py -q`，以及 `npm test -- src/lib/personalPromptTransfer.test.ts src/lib/contentTransfer.test.ts src/pages/ConversationWorkbenchPage.test.tsx` 至通过。
- [ ] 提交：`feat(v3): append personal prompts with durable receipts and undo`。

## 任务 7：真实迁移、界面检查与交付

**Files:** 更新 `v3/STATUS.md` 和 `v3/README.md`；新增 `docs/v3/PERSONAL_TAG_MARKET_20260929.md` 记录用法、迁移统计及检查结果。用户数据、备份和截图预览用本地数据/审计目录，不混入产品源码。

- [ ] 后端在 `v3` 运行 `python -m pytest tests/test_personal_tags.py tests/test_personal_tag_import.py tests/test_personal_tag_api.py tests/test_personal_prompt_transfer.py tests/test_api.py tests/test_reference_examples.py tests/test_reference_pagination.py tests/test_workspace_history.py tests/test_workspace_creation_idempotency.py tests/test_workbench_direct_generation.py tests/test_manual_identity_tags.py tests/test_session_recovery.py tests/test_package_boundary.py -q`；用上述绝对解释器执行并记录实际结果。
- [ ] 前端在 `v3/web` 运行 `npm test`、`npm run typecheck`、`npm run build`。仅在失败或出现新风险时扩大验证，不反复运行已充分验证的无关检查。
- [ ] 用只读 CLI 将 `pg-local/postgres` 的两张目标表导出到应用用户数据目录，核对实际总数与之前的 11,473/174 是否一致。差异必须解释后再导入，不以旧数字覆盖真实新数据。
- [ ] 先将真实导出导入临时验证库，检查全部分类父子关系、原文/别名/原权重与源 ID，一次导入及重复导入统计都可解释。真实库首次导入前备份；采用默认权重 1.0、保留变体、不拆片段的设计，导入报告随交付保存。
- [ ] 在实际用户个人库完成导入，记录数据位置和备份位置；不修改旧 PostgreSQL。使用未配置 Docker 连接的运行环境验证日常读写不依赖容器，无需停止用户容器。
- [ ] 通过隔离目录构建产物启动 loopback 预览。先在测试用户数据副本演练编辑、回收、恢复、分类移动、导入失败和工作台追加，避免把验收条目留在用户正式库。
- [ ] 在可用的 Codex in-app browser 核查 1440px 桌面及 390px 窄屏、浅色和深色主题；使用真实 UI 点击找词→选词→改权重→保存组合→切换管理→编辑→恢复→复制→追加预览→确认→刷新→撤销。截图对照已选两张效果图，修正裁剪、重叠、焦点和状态反馈问题。
- [ ] 根据所选执行方式完成最终独立代码审查，修复确实影响 spec 的问题并重跑相关检查；使用 verification-before-completion 核实结论。记录无法核验的项，不能用效果图替代实际界面验证。
- [ ] 提交功能文档与最终修正，报告隔离工作区、分支、运行入口、导入数量、测试结果和剩余限制。遵循用户「之后再合并」的安排，保留可审查的隔离分支，不自动覆盖原目录未提交工作。

## 自审记录与执行审核

已将 spec 的两视图、快照组合、分类维护、回收恢复、原文权重、可重复迁移、JSON 迁移及原文追加分别映射到任务 1–7；五项 Review Focus 均有明确所属测试。

执行前请审核以上计划，并选择：

1. 当前对话连续实现＋隔离工作区（建议）：按任务推进，完成后独立整体审查。
2. 子代理按任务实现＋隔离工作区：逐项实施与独立审查，使用更多代理上下文。

此审核完成前，不开始产品代码改动、安装产品依赖或真实数据导入。
