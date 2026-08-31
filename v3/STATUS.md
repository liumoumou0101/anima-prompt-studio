# V3 开发状态

更新日期：2026-08-30

## 当前阶段

Phase 3 主产品闭环已进入功能冻结与收尾：远程生成、画廊、标签/画师浏览、自然语言 Scene Draft、Literal/Hybrid、画师批量对照和候选快照持久化均已可用。当前版本不再扩展超出 ANIMA 纯提示词稳定能力的复杂语义结构，剩余工作集中在缺陷修复、固定 Seed 效果验收、发布整理和风险说明。

## 已完成

- 顶层 `v3/` 独立工程、包、测试、Web 和工具目录。
- V3 wheel 明确依赖 V2 核心包，干净环境安装时会一并解析画廊、远程执行和 PySide6 运行依赖，不再只在源码工作区内偶然可用。
- V3.2 产品、架构、数据/API、评测、合规和路线文档。
- 四个上游项目的开发起点 commit 快照。
- `anima-v3-data/1` manifest 领域模型：
  - 截止模式和 corpus size 模式一致性。
  - 上游 HTTPS、40 位 commit 和许可字段。
  - 安全相对路径、文件大小和 SHA-256。
  - manifest 读取、写入和安装文件验证。
- `reference.db` 构建器：
  - CSV、JSON 和可选 Parquet 输入。
  - tags、aliases、groups、Tag–Tag、Artist–Tag 和 FTS5 表。
  - 当前 upstream 字段及旧 `count` 命名兼容。
  - 普通标签与画师独立存储，支持同名而不发生 category 冲突。
  - UTF-8/GB18030 CSV、当前别名 Parquet 字段和缺失目标过滤。
  - 共现边双向展开、NPMI 计算或上游分数验证。
  - SQLite integrity check、临时构建、默认拒绝覆盖。
- 只读 `ReferenceDataStore`：
  - 英文、中文、别名 FTS 搜索。
  - 标签详情和标签组。
  - 多 seed 相关标签聚合。
  - 多标签画师推荐和 `@` 展示渲染。
  - SQLite `mode=ro`。
- 小型上游 fixtures，包含当前 schema 与错误 schema。
- 数据构建 CLI、结构化 diagnostics 和锁定快照文件哈希。
- 锁定 commit 的 40 MB 真实上游数据首次全量构建及健康查询。
- `IntentElement`、`ConstraintGraph`、`IntentDocument` 领域合同：
  - locked/excluded/required/user-selected/suggested/automatic 固定优先级。
  - 关系边、悬空引用保护和 required/excluded 冲突检测。
  - 输入 span、canonical tag、置信度和 provenance。
- `PromptCandidate` 与 `CandidateSet` 领域合同：
  - literal/conservative/artist/hybrid lane。
  - 标签和画师来源、分数、理由及数据/算法版本追踪。
  - literal 唯一基线、必需元素覆盖、excluded 泄漏和版本一致性硬约束。
  - 可供后续 API/前端使用的 JSON Schema 导出。
- 正式开发分支：`codex/v3-development`。
- ANIMA 模型配置和 literal 主链路：
  - Base/Aesthetic/Turbo 配置随 V3 包分发并做变体一致性校验。
  - exact、alias 和本地中文精确词映射；不把模糊结果伪装成必需标签。
  - canonical 下划线到 ANIMA 空格文本渲染，`score_*` 特殊 token 保留。
  - 模型专用正向前缀、负向模板、排除项和 unresolved 警告。
- 推荐候选纵向切片：
  - Literal 只保留精确映射、用户确认和可追踪的本地 prose baseline。
  - 相关标签与画师按可解释的建议池返回；它们默认不进入提示词。
  - 已保留 `RecommendationLaneGenerator` 的 Conservative/Artist 实现，供将来的显式选择与对照流程复用，但默认 API 不调用它们。
  - alias 解析后才显现的 required/excluded 冲突会在生成前阻断。
- hybrid、validator 与静态 benchmark：
  - 显式关系边或经 V2 抽取器产生的英文画面计划会生成 hybrid；普通结构化输入不会凭空猜测自然语言关系。
  - validator 独立复核 tag 可解析性、渲染格式、模型/数据/算法版本和排除项。
  - 自动 character/copyright 泄漏、重复 lane、可解析必需项误报 unresolved 会阻断放行。
  - `anima-v3-benchmark` 输出结构化硬门槛报告。
- 统一 localhost API：
  - `LocalApiServer` 只绑定 `127.0.0.1` 随机端口，可由桌面壳安全启动和停止。
  - 一次性 bootstrap token 交换短期 session；服务端只保存 token SHA-256。
  - Host、Origin、Content-Type、请求体大小和 session 保护。
  - `/health`、bootstrap、标签搜索/详情、相关标签和画师推荐端点。
  - 数据包缺失时 bootstrap 降级，数据查询返回稳定错误合同。
  - API 每次查询单独只读打开 reference.db，不把连接跨线程共享。
  - 可选同源托管 React 生产构建，前端路由回退不会掩盖不存在的 API。
- React/Vite/TypeScript 产品层：
  - 独立依赖锁文件，不复用 V2 `web_gallery`。
  - 一次性 bootstrap token 交换 session 后立即清理地址栏。
  - 响应式应用壳、标签搜索、分类筛选、空/加载/离线/错误状态。
  - 标签详情展示本地说明、别名、中文检索词、标签组和相关标签。
  - 在线图片预览保留明确的离线占位，尚未静默发起联网请求。
- 工作台候选闭环：
  - `/workbench/candidates` 把结构化输入转换为 Intent，并生成 Literal 与显式关系 Hybrid；相关标签和画师单独作为建议池返回。
  - 每次响应前运行独立 CandidateValidator，未知模型、冲突和不可生成输入返回稳定错误。
  - 工作台支持正向概念、显式排除、`!` 锁定和 Base/Aesthetic/Turbo 配置。
  - Literal 与显式关系 Hybrid 使用同一 DTO，逐条展示正负提示词、标签来源和 unresolved 说明；选择池不会静默成为候选内容。
  - 正负提示词可一键复制；工作台与标签浏览器保留为并列入口。
- 自然语言输入闭环：
  - 默认 `/local-natural/candidates` 使用 V2 `TranslationService`、原文精确索引和 V3 标签数据；不调用 AI API、V2 UI、`PromptPipeline` 或 `PromptCompiler`。
  - 结构化概念页签同样接受中文概念而不要求用户输入 canonical；无关系图的中文条目会复用同一 Scene Draft 消歧与译文，明确排除项单独进入负向提示词。
  - 响应保留 `scene_draft`：已确认、待确认建议、未命中内容、原文证据与译文彼此分离。用户确认标签时复用当前译文重新编译，不重新翻译或解析。
  - Scene Draft 已按参考数据支持事实分层、可见实体锚点和人工属性归属；单实体只给归属建议，不会自动确认或改写 Literal。
  - 首个显式关系切片支持在服装归属确认后单独确认 `wearing`；关系只写入 ConstraintGraph 与 Hybrid，Literal 保持不变，并可随工作台候选快照保存和恢复。
  - 没有安全标签命中时，Literal 使用 `local_prose_baseline` 保留译文，避免 422 或擅自增加 `1girl` 等内容。
  - `/intent/parse` 与 `V2NaturalLanguageIntentAdapter` 保留为未来明确触发的 AI 辅助拆解，不是前端默认主路径。
  - 工作台可在“结构化概念”和“自然语言描述”之间切换，自然语言正文、选中的建议和输入模式随工作台草稿保存。
- V2 本地翻译薄适配：
  - `V2LocalTranslationAdapter` 仅复用 `TranslationService`，禁止引入 V2 `PromptPipeline`、`PromptCompiler` 或 UI。
  - 已安装 Marian 模型及运行依赖时按需、本地文件限定加载；否则自动使用内置离线基础翻译，不触发下载。
  - `/translation` 提供独立英译预览；工作台可将翻译作为可编辑 prose baseline，但不会把它或其索引结果静默并入 required 标签。
- 独立工作台状态层：
  - `.local/state/workspaces.db` 与只读参考数据包物理分离。
  - 工作台创建、列表、读取、更新和软删除 API；每条记录包含 revision 和 UTC 时间。
  - `BEGIN IMMEDIATE` 加 revision 乐观锁，旧标签页更新稳定返回 409，不发生静默覆盖。
  - Web 工作台支持保存、刷新后重新打开、当前 revision 展示，以及 50 步本地撤销/恢复。
  - 冲突时保留页面内未保存编辑，并提示重新打开后人工合并。
- V2 生图能力复用桥：
  - `CandidateToV2PromptJobAdapter` 把已验证 V3 候选和 Intent 转为现有 V2 `PromptJob`，不依赖 PySide UI。
  - 继续使用 V2 模型配置、生成预设、工作流模板和 checkpoint 逻辑。
  - V3 候选、Intent、工作区 revision 和版本信息作为不透明快照进入 V2 任务及结果 manifest。
  - `/generation-requests/preview` 可在不发起远程请求的情况下检查桥接结果；bootstrap 明确报告 V2 runtime 是否可用。
  - V2 `RemoteExecutionCoordinator` 仅新增向后兼容的预创建 run 入口；伪远程端到端流程确认 SSH/ComfyUI/工作流/归档主链仍直接复用。
  - 无 UI 单工作线程 FIFO 队列支持等待上限、排队取消、快照执行与安全停止。
  - 生成幂等键进入 V2 run 快照，API 服务重启后仍不会重复提交。
  - V2 SQLite 的云主机、工作流、输出目录及系统凭据直接复用；job/run/artifact 持续写回原有仓库。
  - 提交、查询和 `cancel_queued` API 已实现，响应不包含任务内部快照、工作流或凭据。
  - 历史未完成 run 可使用 `retry_check` / `continue_download` 恢复，沿用原 remote prompt ID，不重复提交。
  - Web 工作台只展示已确认指纹且兼容当前模型的 V2 目标，候选可直接提交并跳转生成页。
  - 工作台可锁定一条无画师候选，从当前推荐池选择 1–20 位画师，以同一模型、工作流、预设、尺寸和固定 Seed 分别提交独立任务；不会混合画师或静默修改基准提示词。
  - 批量任务及其画廊资产保留画师对照批次、画师顺序和 Seed；生成页和画廊可直接识别每张对照图。
  - V2 本地等待队列默认容量提高至 20，以支持一次提交完整对照组。
  - Web 生成页轮询展示进度、产物数量、安全错误和服务端明确授予的恢复动作。
  - 加密私钥 passphrase 通过独立端点进入按云主机隔离的进程内保险箱；工作台只在提交前传递一次，退出时覆写清空，不进入工作区、run 快照、SQLite、manifest、日志或响应。
  - RTX 4090 / ComfyUI 0.25.0 真实验收已完成：V3 Literal 候选经 API、V2 队列、SSH 隧道和 01 Base 工作流生成并下载 640×640 图片，run 达到 completed 且 manifest 保留候选/数据包版本。
- V3 统一画廊首个切片：
  - `V2GalleryReadService` 复用 V2 `load_gallery_batches`、manifest 恢复、资产状态和路径安全函数，不导入旧 GalleryServer 或 V2 UI。
  - `/gallery/assets` 返回本地归档、项目/模型筛选项及 V3 candidate lane/算法/数据包版本线索。
  - 原图和缩略图经统一 session API 提供；图片专用 HttpOnly SameSite cookie 只作用于 `/gallery/assets/`，不会把普通 API 改为 cookie 鉴权。
  - V2 原缩略图算法已抽成 `GalleryThumbnailCache`，V2 旧画廊与 V3 共用确定性 WebP 缓存。
  - V3 `/gallery` 支持本地网格、懒加载缩略图、项目/模型/文本筛选和包含正负提示词的 Lightbox。
  - Lightbox 可标记保留/淘汰；状态继续写入 V2 用户库而不修改图片或只读参考数据包。
  - “移入回收站”只移动到输出根目录的 `.trash`，不永久删除；活动中的放大/再生成源图会被拒绝。
  - 回收站页面可浏览被移走的图片并恢复原路径；原位置冲突时沿用 V2 的安全重命名规则。
  - 再生成与 1.5× 放大直接复用 V2 `GalleryUpscaleManager`、SSH/ComfyUI coordinator、持久化任务和重启恢复，不建立第二套远程实现。
  - 处理任务页展示排队/运行/失败进度，并支持排队取消和失败重试；服务停止时安全取消尚未开始的队列项。
  - 同一 4090 镜像已真实完成画廊同提示词再生成和 20 Tile Upscale；结果分别为 640×640 与严格 960×960，并重新进入统一画廊。
- 候选快照持久化：
  - 工作台新增可迁移的 `candidate_snapshot_json`，保存最后一次通过 validator 的完整 Intent、候选、校验报告和 data pack ID。
  - 编辑、撤销或恢复输入会清除旧候选，避免把与当前草稿不一致的结果保存为快照。
  - 刷新后打开工作台会恢复当时的候选卡片，可直接复制或提交同一不可变候选。
  - 浏览器恢复快照同时保存工作台 ID 与 revision；刷新后不再把已保存工作台错误显示为“未保存”。
- 数据包安装、原子更新与回滚：
  - `DataPackManager` 将每个 pack 安装到不可变 `packs/<pack_id>/`，不直接替换 Windows 上可能仍被读取的 SQLite 文件。
  - 安装前后都验证 manifest、文件大小/SHA-256、SQLite integrity、五类记录数、数据库契约、pack ID 和固定健康查询。
  - 只有强校验通过后才用 `os.replace` 原子切换 `active.json`；写入失败保持旧状态并清理临时指针。
  - 自动保留上一个活动版本，支持显式 activate 和双向 rollback；同 ID 不同内容、篡改包和损坏状态均拒绝处理。
  - 跨进程更新锁在进程异常退出后由操作系统释放，不依赖删除可能遗留的锁文件。
  - `anima-v3-data-pack` 提供 install/status/resolve/activate/rollback；`anima-v3-api --data-root` 从活动指针启动。
- 可双击启动入口：
  - 仓库根目录 `启动 ANIMA V3.cmd` 改为纯 ASCII 薄入口，由 `tools/start_anima_v3.ps1` 处理中文路径，自动使用项目 `.venv`，显式加入 V2/V3 开发源码路径，并调用与正式发布包共用的 `anima-v3-desktop` 启动核心。
  - 首次运行会从随项目数据包完成强校验和安装，随后复用活动指针、现有 V2 数据库、V3 工作区数据库及已构建 Web。
  - 启动成功后自动打开一次性 bootstrap URL；失败时保留窗口和中文错误，关闭窗口会停止 loopback API。
  - 已复现并修复旧 `.cmd` 在中文目录下错误解析变量/续行符的问题；修复后的真实双击等价入口完成首次数据包安装、浏览器启动和 `/health` 检查。
- Windows 发布工程：
  - 独立 `AnimaPromptStudioV3.exe`、PyInstaller onedir spec、便携 ZIP 构建脚本和 Inno Setup 安装配置已完成；V2/V3 使用不同 AppId 和安装目录。
  - 冻结包内置 V3 Web、V2 稳定服务、V3 配置和版本化数据包；首次启动仍经过正式安装器强校验，不直接信任内置数据库。
  - 修复构建环境 Poppler ICU 污染导致的 QtCore WinError 127，spec 明确拒绝同名外部 ICU DLL。
  - EXE 已分别通过无 V2 和真实 V2 数据库桥接 smoke；自然语言、远程队列和画廊适配器均可从冻结包装载。
  - 发布脚本连续启动冻结 EXE 两次并验证活动指针和已安装 reference.db 哈希不变，覆盖首次安装和程序升级场景。
  - 已用 374,484,992-byte 真实数据重建完整 alpha.1 便携包；最新 ZIP 为 265,776,659 bytes，SHA-256 `581897C5C2765DE809FD71B65522CCFC9D63A91F94DB4421D4BB56C24E163E77`，内容含 EXE、Web、manifest、reference.db、本地翻译和内存凭据通道，未携带 `.local`、临时脚本或源码测试数据。
  - 手动触发的 Windows CI 要求数据包 HTTPS 地址和固定 SHA-256，使用 Inno Setup 生成安装版并执行静默安装、冻结 EXE 启动和卸载 smoke；临时数据源不会硬编码进仓库。

## 测试结果

```text
V3 Python 全量：88 passed
V3 Web：30 passed；TypeScript typecheck 与 Vite production build 通过
V2 全量回归：585 passed
真实数据静态门槛：4 个 case/profile 组合全部通过
真实数据 manifest：大小、SHA-256、SQLite integrity 和 5 类记录计数通过
Web 依赖审计：npm 官方源 high 级别 0 vulnerabilities
发布包：V2/V3 wheel 构建、内容扫描、干净安装、pip check、CLI 与 HTTP smoke 全部通过
Windows 冻结包：真实数据 EXE 首启/升级/V2 桥接通过；便携 ZIP 内容与哈希检查通过
真实远程闭环：RTX 4090 上基础生成、下载、画廊索引、再生成和 1.5× 放大全部通过
收尾四图效果矩阵：3080 Ti / Aesthetic v1.1 复跑 4/4 completed；关系确认保持可选，默认负向 `artist name` 保留
精致二次元插画探索：3080 Ti / Aesthetic v1.1 五方向 5/5 completed；人物环境、都市氛围和幻想场景已形成可保留基线
```

V2 回归覆盖远程执行、Web 画廊、本地翻译保护和模型参数预设。本阶段对 V2 `PromptJob` 仅做向后兼容的不透明集成元数据扩展，585 项全量回归全部通过。

发布包内容扫描确认未携带 `.local`、参考数据库、临时脚本、`.env` 或 `__pycache__`。从 wheel 安装后的 API 已用真实 `anima-v3-dso-0636f762-r1` 数据包完成一次性 session 交换、bootstrap 和 `1girl` 检索；同源保护也在缺失 `Origin` 时按设计拒绝写请求。终端中曾出现的中文乱码已核对为 PowerShell 输出编码问题，数据库内 `1个女孩` 的 Unicode 与 UTF-8 字节均正确。

真实 374,484,992-byte 数据包已通过管理器完成复制安装、强校验、原子激活、状态/路径解析和 `--data-root` API 启动。测试同时确认完整强校验只发生在安装、切换或显式 `resolve`，普通 API 冷启动不会重复扫描整个数据库。

## 已验证的失败保护

- 路径穿越 manifest 文件名被拒绝。
- `exact` 截止模式配 estimated corpus size 被拒绝。
- Artist–Tag 缺少 `artist_post_count` 被拒绝，不留下数据库或 manifest 半成品。
- 精确快照中，共现次数超过两端边际计数会被拒绝；近似快照会隔离统计并显式报告。
- 画师与普通标签可安全同名。
- 已存在的数据包默认不覆盖。
- 只读 store 不能执行写 SQL。
- ConstraintGraph 的重复 ID、悬空边和直接约束冲突被拒绝或显式报告。
- literal 候选不能包含共现扩展或自动画师。
- required/locked 元素必须被 literal 保留或列入 unresolved。
- excluded canonical tag 不能进入任何候选正向标签。
- 自动标签没有来源 element，或共现标签没有数据/算法版本时被拒绝。
- Aesthetic 默认加入 `score_*`、Turbo 启用 negative prompt 等模型配置错误被拒绝。
- 推荐策略允许自动 character/copyright 泄漏时被拒绝。
- bootstrap token 复用、无 session、恶意 Host/Origin 和错误 Content-Type 被拒绝。
- API 查询前后 reference.db SHA-256 保持不变。
- SPA 深链接正常回退到 `index.html`，未知 `/api/v3/*` 不会误返回网页。
- 实际 Uvicorn 工作线程中的 SQLite 连接不会跨线程复用。
- 未知模型配置、无效工作台 intent 和候选内部验证失败不会伪装成成功响应。
- 普通输入不会凭空生成 Hybrid；只有显式 relation edge 或明确的抽取画面计划才生成自然语言表达。
- 自然语言适配器源码边界测试禁止引入 V2 UI、旧 PromptPipeline 或 PromptCompiler。
- 本地翻译适配器边界测试禁止引入 V2 UI、旧 PromptPipeline/PromptCompiler 或远程模型下载调用。
- 私钥 passphrase 测试确认其可到达 SSH tunnel，但不会出现在 SQLite 字节中，服务重启后配置状态恢复为未设置。
- 未配置 AI API Key 时 `/intent/parse` 稳定返回 503，不伪装成本地解析成功。
- 画廊原图/缩略图要求有效会话；目录穿越和 `.trash` 私有目录访问返回 404。
- V3 画廊 adapter 边界测试禁止导入 V2 GalleryServer、PySide 或 UI。
- 活动画廊处理任务的源图不能移入回收站；完成后才允许移动，状态记录同步清理。
- 回收站恢复只接受 `.trash` 内受支持图片，目录越界不会产生文件操作。
- 画廊处理队列沿用 V2 上限、重复任务、缺失提示词、缺失尺寸、工作流兼容和凭据检查。
- 旧工作台数据库启动时只新增 nullable 快照列；没有快照的历史记录继续读取为 `null`。
- 工作台状态不会写入 reference.db；创建、恢复、软删除和旧 revision 冲突均有 API 测试。
- 真实远程报告不含 SSH 密码；临时 profile/credentials 只存在于验收进程内，镜像上的 3 个测试输出和 1 个上传副本已在下载、哈希及尺寸校验后删除。

## 首次真实数据结果

锁定来源：`DanbooruSearchOnline@0636f762694fc436b4ac472cf59b85d172eaaac4`。

```text
原始文件：约 40 MB
构建时间：约 2 分 17 秒
峰值内存：约 667 MB
reference.db：374,484,992 bytes
tags：52,475
artists：24,636
aliases：14,122
tag_edges：3,755,808
artist_edges：614,772
```

真实数据 diagnostics 已记录 1 个合并重复标签、25,907 个缺失目标别名、528 个与 canonical 冲突的别名、52 条未知 Tag–Tag 边、15 条未知 Artist–Tag 边，以及近似快照中的边际计数差异。`maid` 的英文搜索、中文详情、标签组、相关标签和画师推荐均已通过抽查；数据库大小和 SHA-256 复核通过。

Phase 1 真实数据 smoke test 使用“女仆、双马尾、不要金发”得到：literal 为 `score_7, maid, twintails`；conservative 只增加 `maid headdress / maid apron / enmaided`；artist 在相同保守候选上增加单个 `@motizou`。三条 lane 都保留 `blonde hair` 排除项。

`v3-static-v1` 已在真实数据包执行 4 个 case/profile 组合：8/8 required 保留、excluded 泄漏 0、自动 character/copyright 泄漏 0、validator 错误 0。显式 `wearing` 关系案例生成 literal/conservative/artist/hybrid 四条不同 lane。

真实数据 API smoke test 已完成 session exchange、bootstrap、`maid` 搜索、`maid_uniform → maid` 详情解析、相关标签和画师推荐；数据包 ID 正确返回 `anima-v3-dso-0636f762-r1`。

真实浏览器 smoke test 已完成“女仆”中文搜索和 `maid` 详情导航；页面读取 52,475 标签的真实数据包，正确展示中文说明、5 个别名、3 个标签组和 12 个相关标签，浏览器控制台无警告或错误。

真实浏览器工作台 smoke test 使用“锁定女仆、双马尾、排除金发”生成 3 条通过验证的候选：Literal 保持 `score_7, maid, twintails`，Conservative 增加 3 个可追踪共现标签，Artist 增加 `@motizou`；金发只进入负向提示词。一键复制、桌面和 390px 窄屏布局均通过，控制台无警告或错误。

真实持久化 smoke test 已完成保存 revision 1、刷新页面、从独立状态库重新打开，并模拟另一个标签页推进到 revision 2。持有旧 revision 的页面收到 409 冲突提示，未保存的“咖啡厅”编辑仍保留，未发生静默覆盖。

## 尚未开始

- 数据包联网下载、发布索引和带宽中断续传。
- 语义 embeddings 的体积、冷启动与内存测试。
- 更多静态 benchmark 家族和正式生图 benchmark。
- 工作台软删除恢复入口和多标签页可视化合并。
- 在线标签图片预览、限流和缓存。
- 用户 ComfyUI 环境的真实生图验收。
- Illustrious（光辉系）、Pony 等后续模型族的独立 ModelProfile 与工作流兼容。
- 将区域提示、姿势控制、局部重绘等 ComfyUI 操作编排下沉到产品层；该项属于更后续正式版本。

## 下一步

1. 按 [RELEASE_FINISH_CHECKLIST.md](RELEASE_FINISH_CHECKLIST.md) 完成当前 ANIMA 版本收尾，不再增加未经过生图证明的复杂语义结构。
2. 保留四图机器报告与人工视觉复核作为当前 ANIMA 固定 Seed 基线，不为单张结果继续增加关系特判。
3. 数据包正式下载地址确定后，在 Windows CI 实际生成并安装/卸载测试 Setup EXE。
4. 在用户真实 ComfyUI 环境复核生成、恢复、再生成和放大。
