# V2 复用清单

状态：依据 2026-08-25 当前源码盘点

原则：复用已验证行为和服务，不把 V2 主窗口当作 V3 架构。

## 1. 分类定义

- **直接复用**：接口基本稳定，可以从 V3 服务层直接调用。
- **抽离适配**：现有能力可用，但与 PySide、单库或 V2 `PromptJob` 耦合，需要薄适配或提取编排。
- **参考迁移**：保留交互、测试和业务规则，在 V3 新边界内重新接线。
- **冻结对照**：不进入 V3 主路径，仅用于兼容、回归和效果基准。
- **全新实现**：V3 差异化核心。

## 2. 可以直接复用

| 能力 | 当前文件 | V3 用法 | 注意事项 |
| --- | --- | --- | --- |
| 本地 Marian 与内置翻译 | `services/translation_service.py` | 作为 `TranslationPort` 实现 | 保持模型可选和 `local_files_only` |
| 资源下载与清单 | `services/resource_manager.py` | 扩展为数据包下载基础 | V3 数据包另做强校验和回滚 |
| SSH 隧道与指纹验证 | `services/remote/ssh_tunnel.py` | 原服务接入 Generation API | 不降低首次确认和指纹变化拒绝策略 |
| ComfyUI API 客户端 | `services/remote/comfy_client.py` | 原服务接入 | 保留 WebSocket 失败后的轮询策略 |
| 工作流发现与转换 | `services/remote/workflow_discovery.py` | 原服务接入 | 继续按兼容范围限制执行 |
| 工作流渲染 | `services/remote/workflow_renderer.py` | 接收 V3 候选渲染结果 | 输入 DTO 适配，不改图结构安全校验 |
| 远程执行协调器 | `services/remote/execution_coordinator.py` | GenerationService 内部实现 | 不允许反向修改提示词候选 |
| 结果归档 | `services/remote/result_organizer.py` | 原样复用 | 任务 manifest 增加 V3 版本快照 |
| 系统凭据存储 | `services/remote/credential_store.py` | 原样复用 | API 响应不得回传秘密 |
| 远程领域对象 | `domain/execution_models.py` | 保留并向后兼容扩展 | 数据库迁移需有测试 |
| ANIMA 模型配置 | `configs/model_profiles/*.json` | 作为 V3 `ModelProfile` 起点 | 增加 renderer/version 字段，不合并 Base/Aesthetic/Turbo |
| 生成预设 | `configs/generation_presets.json` | 不迁移数值；V3 从具体工作流模板生成配方与参数能力契约 | V2 预设仅为缺字段的旧记录回退，不得覆盖 DMDX、HiRes 等工作流约束 |
| AI 画面事实抽取 | `services/ai_extract_service.py`、`ai_prompt_service.py` | 经 `V2NaturalLanguageIntentAdapter` 转为 V3 Intent | 只复用抽取、provider 配置和凭据；禁止进入 V2 编译器 |
| 画廊索引与安全路径 | `services/gallery_index.py`、`gallery_assets.py` | 经 `V2GalleryReadService` 接入统一 API | 不复用旧 stdlib HTTP server；`.trash` 保持私有 |

## 3. 需要抽离适配

| 能力 | 当前位置 | 问题 | V3 处理 |
| --- | --- | --- | --- |
| 文生图队列编排 | `ui/main_window.py` 中 `_prepare_generation_request`、`_enqueue_or_start_generation`、`_launch_generation_worker` | 与 PySide 控件、确认框和窗口状态耦合 | 提取 `GenerationQueueService`；UI 只调用 API |
| 画廊 localhost 服务 | `services/gallery_server.py` | 使用独立 stdlib HTTP handler，和 V3 API 会形成两套后端 | 保留业务函数，将路由迁入统一 API |
| 画廊处理队列 | `services/gallery_upscale.py` | 可用，但配置入口依赖主窗口同步 | 由 Generation/Gallery service 注入配置 |
| 画廊索引 | `services/gallery_index.py`、`gallery_assets.py` | 与现有用户库和路径结构绑定 | 保留扫描与安全路径逻辑，适配 `user.db` |
| SQLiteRepository | `repositories/sqlite_repository.py` | 同一个数据库承担多类状态；V3 要拆 reference/user | 保留用户状态方法，新增迁移；不承载参考标签库 |
| `PromptJob` | `domain/models.py` | 同时包含 V2 编译状态和生成输入 | 作为旧任务与远程适配对象；V3 新建 `PromptCandidateSnapshot` |
| 当前标签数据库 | `repositories/tag_database.py` | 数据量、字段和索引不满足 V3 数据包合同 | 仅复用查询经验；由 `ReferenceDataStore` 替代 |
| 应用启动 | `app/main.py` | 默认直接创建完整 PySide 主窗口 | 改为启动统一 API、轻量壳和系统浏览器 |

“原样保留”在这些模块上指功能行为保持，不指复制当前耦合方式。

### 已落地的首个复用切片（2026-08-26）

- V3 `CandidateToV2PromptJobAdapter` 已将通过校验的 `PromptCandidate + IntentDocument` 转成 V2 `PromptJob`，不引入 PySide 主窗口。
- 模型预设、生成参数、工作流模板、正负提示词和排除项继续使用 V2 现有合同。
- V2 `PromptJob` 仅增加不透明 `integration_metadata`，用来在任务和结果 manifest 中保存 V3 候选、Intent、工作区和版本快照；V2 不解析或修改其语义。
- `/api/v3/generation-requests/preview` 已可在真正提交远程任务前预览桥接结果。
- 复用未修改的 V2 `RemoteExecutionCoordinator` 已通过伪远程端到端测试，但尚未连接用户的真实 ComfyUI 服务器。

- V2 主窗口中的单任务 FIFO 队列已抽成 `V2GenerationQueueService`：支持快照执行、队列上限、进程内及重启后幂等、排队取消和安全停止。
- `build_v2_generation_queue` 直接读取 V2 SQLite 的 profile/workflow/output setting，从系统凭据库读取 SSH 密码，并将 job/run/artifact 写回 V2 库。
- `/api/v3/generation-runs` 已开放提交、查询和 `cancel_queued`，运行状态不暴露工作流或凭据。

历史 run 恢复、前端生图状态页和工作台直接提交也已接入；整条路径仍不重写 SSH、ComfyUI 客户端、工作流渲染和结果归档。加密私钥 passphrase 已通过独立 API 写入进程内保险箱，退出清空且不进入任务/数据库/日志。远程主链只剩用户真实 ComfyUI 验收。

### 已落地的本地翻译薄适配（2026-08-26）

- `V2LocalTranslationAdapter` 只包装 V2 `TranslationService`，不导入旧 `PromptPipeline` 或 `PromptCompiler`。
- 已安装且运行依赖齐全时按需加载本地 Marian，始终 `local_files_only`；否则使用 V2 内置离线基础翻译。
- `/api/v3/translation` 仍是独立预览；工作台的 `/api/v3/local-natural/candidates` 则把翻译作为可编辑 prose baseline。它不会把译文索引或 V2 平铺结构静默转换成 required 标签，也不会调用 V2 旧提示词编译管线。

### 已落地的自然语言复用切片（2026-08-26）

- V2 `AIExtractService` 继续负责把小说片段或描述抽成人物、动作、关系、场景、构图和排除事实。
- V3 adapter 只把 `ExtractedPrompt` 转成 `IntentDocument`，不会调用 V2 `PromptPipeline`、`PromptCompiler`、`NovelSceneCompiler` 或主窗口。
- V2 provider/model/timeout 设置仍从原 SQLite 读取，API Key 仍从 Windows 凭据管理器读取；V3 API 和工作台不接收或显示 Key。
- 英文画面计划作为可审阅的 `scene_plan_en` 进入独立 Hybrid lane；V3 Literal/Conservative/Artist 仍由新标签核心生成。

### 已落地的画廊读取切片（2026-08-26）

- V3 直接读取 V2 run、artifact、manifest、散落图片与保留/淘汰状态，已有图片无需迁移或复制。
- V3 candidate 的 lane、算法和数据包版本会从 `integration_metadata` 恢复到图片详情；纯 V2/外部图片保持可浏览但明确没有 V3 来源。
- 旧画廊缩略图逻辑已抽成无 HTTP 状态的 `GalleryThumbnailCache`，两版共用缓存算法；V3 不启动第二套 GalleryServer。
- 保留/淘汰状态、可恢复回收站、再生成和 1.5× 放大已经按 V3 session/Origin 合同接入；活动处理任务的源图沿用 V2 锁定语义。永久删除仍不开放，避免把可恢复操作与不可逆删除混在同一阶段。
- `GalleryUpscaleManager` 新增生命周期停止接口，V3 关闭时取消未开始任务并等待活动调用安全返回；V2 原队列格式与恢复行为不变。

## 4. 参考迁移

| 能力 | 当前文件 | 迁移内容 |
| --- | --- | --- |
| Web 画廊 | `web_gallery/src/main.jsx`、`styles.css` | 网格、Lightbox、筛选、比较、回收站、再生成、响应式布局 |
| 即时画廊 | `ui/image_gallery.py` | 最新结果入口和批次语义，合并到 Web 画廊 |
| 标签浏览弹窗 | `ui/tag_browser_dialog.py` | 用户操作与测试用例；UI 由完整 `/tags` 页面替代 |
| 直接提示词直出 | `ui/direct_prompt_dialog.py` | 保留为 literal/import 工作流和基准测试入口 |
| 模型/参数状态规则 | `domain/models.py`、主窗口相关处理 | 自动、手动、锁定语义迁移到 Web 控件和 API |
| 导出与任务快照 | `services/export_service.py` | 扩展保存候选 lane、数据包、算法、模板版本 |
| 一致性检查 | `services/final_consistency.py`、`quality_guard.py` | 迁移通用约束，避免把 V2 标签流水线假设带入 V3 |

## 5. 冻结为兼容和基准

以下模块不作为 V3 主提示词路径的基类：

- `services/pipeline.py`
- `services/prompt_compiler.py`
- `services/enhancer.py`
- `services/composition_recommender.py`
- `services/tag_matcher.py`
- `services/concept_resolver.py`
- `services/canonical_prose.py`
- `services/novel_scene_compiler.py`
- V2 主窗口中的翻译—编译 UI 编排

处理规则：

1. V3 开发期间保持它们可运行，用于生成 V2 对照结果。
2. 不在这些模块中加入 V3 共现、画师排序或 Web API 逻辑。
3. 可以提取纯函数或通用测试，但必须进入新的 V3 命名空间并说明来源。
4. V3 达到验收门槛后再决定是否保留“V2 兼容模式”。

## 6. 全新实现

- `IntentElement` 与约束图。
- canonical 映射结果的多候选和置信度模型。
- DanbooruSearchOnline 推荐 adapter 与稳定数据包接口。
- literal/conservative/artist/hybrid 候选策略。
- 模型专用 Prompt renderer。
- 候选保真、冲突、格式和来源解释。
- 完整 React 工作台、标签详情和画师探索页面。
- `reference.db` 导入器、manifest、安装与原子更新。
- 统一 localhost API 和会话安全。

## 7. 可继续使用的测试资产

| 测试资产 | V3 用法 |
| --- | --- |
| `benchmarks/visual_semantics_v1.json` | 复杂关系与方向保真回归 |
| `tests/golden_cases.json` | V2 语义基线和兼容对照 |
| `tests/composition_semantic_cases.json` | 构图约束案例来源 |
| `tests/test_remote_execution.py` | 远程协议与恢复回归 |
| `tests/test_gallery_server.py`、`test_gallery_upscale.py` | 画廊行为与文件安全回归 |
| `tests/test_translation_guard.py` | 占位保护与翻译边界 |
| `docs/VISUAL_SEMANTICS_BENCHMARK_V1.md` | V3 生图评测方法的基础 |

V3 新测试不能只验证字符串和分数公式，必须同时保留固定参数生图验收。

## 8. 上游复用范围

### DanbooruSearchOnline（GPL-3.0）

优先复用或改造：

- 语义搜索数据和多视图检索思路。
- Tag–Tag 关联推荐。
- Artist–Tag 推荐。
- alias 解析、Prompt 导入、工作区撤销/恢复/收藏的可移植业务逻辑。

不得直接依赖其未版本化全局文件路径；所有数据经 V3 adapter 与 manifest。

### Booru Tag Gallery（MIT）

优先复用或改造：

- React 页面结构和标签卡片。
- 虚拟列表、搜索体验、详情、相关标签和在线帖子预览。
- NSFW 开关与缓存交互。

移除公开站点专用的 SEO、Netlify/Vercel serverless、在线翻译默认路径和公开部署分析功能。

### danbooru-tag-pipeline（无许可证）

只记录外部运行步骤和输入产物。不复制源码、不 vendor、不作为安装依赖、不在 CI 自动拉取执行。
