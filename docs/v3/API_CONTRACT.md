# V3 本地 API 契约

## LLM 模型目录刷新（2026-09-10）

`POST /api/v3/llm/services/{service_id}/models/refresh` 沿用会话与 Origin 校验，仅使用已保存服务端点与 Key，返回 `{models: string[], count: number}`。OpenAI 兼容服务 GET `/models`，Ollama GET `/api/tags`，超时 20 秒且不跟随重定向；不生成文本、不改变当前模型或思考配置。目录合并保留已有模型参数与自定义 ID。请求期间地址/Key/协议变化返回 422 `llm_config_invalid`，读取或保存失败返回 502 `llm_models_failed`，不泄漏上游错误正文。列表不保证当前套餐对每个模型都有生成权限。

## 工作流管理扩展（2026-09-06）

下列路径相对 `/api/v3/workflows`，均须本地会话认证；服务器参数是已保存连接 ID。

| 方法与路径 | 内容 |
| --- | --- |
| GET `/servers/{remote}` | checked_at/devices/items/inspection；项含版本、来源、级别、状态、错误与资产候选 |
| POST `/servers/{remote}/inspect` | 可选临时 password/passphrase；后台检测，最多两个并发，同服务器去重 |
| POST `/servers/{remote}/cancel` | 请求取消，底层有界超时退出 |
| PUT `/servers/{remote}/{workflow}/mapping` | revision + mapping；空映射明确确认默认文件，失效版本拒绝 |
| POST `/import` | 配置封装或受支持 API 图，返回新副本 ID |
| GET `/export/{workflow}` | anima-user-workflow/1；清除 source_path，节点内容仍需用户审阅 |
| PUT `/{workflow}/enabled` | enabled 布尔值 |
| GET `/{workflow}/versions` | 本机存档版本 |
| POST `/{workflow}/restore` | revision，恢复为独立副本 |
| POST `/servers/{remote}/read-file` | path 和可选临时凭据；指定绝对 JSON 路径，最大 2 MB，仅预览 |
| GET `/servers/{remote}/diagnostics` | 白名单 schema、checked_at、版本/来源/状态/实验标志 |

目标查询增加 availability、availability_errors、experimental、template_revision。非 ready 不可入队，实验项不自动替补。旧 `test-connection?inspect_templates=true` 保留兼容只读接口，不保存缓存；正式 UI 使用新检测接口。导入验证错误 422，目标不存在 404，远端读取错误 502，响应沿用 error.code/message。

状态：首版接口合同；V3-010～012 已实现 session、标签/推荐和工作台候选纵向切片

基础路径：`/api/v3`

当前实现端点：`/health`、`/session/exchange`、`/bootstrap`、`/tags/search`、`/tags/{canonical_name}`、`/related-tags`、`/artists/search`、`/artists/{canonical_name}`、`/artists/recommend`、`/intent/parse`、`/workbench/candidates`、`/prompt-candidates`、`/generation-requests/preview`、`/generation-targets`、`/generation-runs` 提交/列表/查询/排队取消/恢复、`/artist-comparisons` 批量画师对照、`/gallery/assets` 列表/原图/缩略图和 `/workspaces` CRUD。其余端点按后续任务继续实现，未实现能力不会返回伪造成功响应。

## 1. 通用规则

- Content-Type 使用 `application/json; charset=utf-8`。
- 时间使用 UTC ISO 8601。
- tag 的机器字段使用 canonical 下划线名，展示字段单独返回。
- ID 是不透明字符串或整数；前端不得解析 ID 结构。
- 写请求支持 `Idempotency-Key`，生成任务和数据更新必须实现幂等。
- 列表分页首版使用 `limit + cursor`，不使用易受数据变化影响的页码。
- API DTO 与内部 Pydantic/domain 对象分离，允许内部重构。

## 2. 会话与安全

桌面壳启动浏览器时生成一次性 bootstrap token：

```text
http://127.0.0.1:{port}/?bootstrap={one_time_token}
```

前端立即交换会话：

```http
POST /api/v3/session/exchange
```

成功后返回短期会话令牌；一次性 token 立即失效。后续请求使用：

```http
X-Anima-Session: <token>
```

除 `/health` 和静态文件外，所有 API 默认要求会话。所有写请求同时校验 Host、Origin、Content-Type 和请求体上限。正式环境不开放通配 CORS。

## 3. 错误模型

```json
{
  "error": {
    "code": "constraint_conflict",
    "message": "必需标签与排除标签冲突",
    "details": {
      "element_ids": ["e_1", "e_4"]
    },
    "request_id": "req_xxx",
    "retryable": false
  }
}
```

稳定错误码首版至少包含：

- `invalid_request`
- `session_invalid`
- `data_pack_missing`
- `data_pack_incompatible`
- `tag_not_found`
- `constraint_conflict`
- `candidate_generation_failed`
- `candidate_validation_failed`
- `invalid_workbench_intent`
- `model_profile_unknown`
- `workspace_store_missing`
- `workspace_not_found`
- `workspace_revision_conflict`
- `v2_runtime_missing`
- `generation_bridge_incompatible`
- `generation_run_not_found`
- `generation_action_invalid`
- `remote_not_configured`
- `remote_connection_failed`
- `workflow_incompatible`
- `generation_failed`
- `update_verification_failed`
- `rate_limited`
- `reference_preset_not_found`（预留）
- `reference_preset_unavailable`（预留：缺 LoRA、未映射或与当前模型/工作流不兼容）
- `lora_not_installed`（预留）

HTTP 500 的 `message` 不返回本地绝对路径、凭据、远程命令或堆栈。

## 4. Bootstrap

### `GET /bootstrap`

返回前端初始化所需的轻量状态：

```json
{
  "app_version": "3.0.0-dev",
  "api_version": "v3",
  "data_pack": {
    "id": "anima-v3-data-2025-09-r1",
    "ready": true,
    "cutoff_mode": "approximate"
  },
  "features": {
    "semantic_search": true,
    "cooccurrence": true,
    "artist_recommendation": true,
    "online_preview": false,
    "remote_generation": true
  },
  "model_profiles": [],
  "settings_summary": {}
}
```

## 5. 标签与画师

### `GET /tags/search`

参数：`q`、`category`、`nsfw`、`sort`、`limit`、`cursor`。

返回：

```json
{
  "items": [
    {
      "id": 123,
      "name": "school_uniform",
      "display_name": "school uniform",
      "cn_name": "校服",
      "category": "general",
      "post_count": 1000,
      "nsfw": false,
      "match": {"kind": "alias", "score": 0.92}
    }
  ],
  "next_cursor": null,
  "data_pack_id": "..."
}
```

### `GET /tags/{canonical_name}`

返回标签详情、别名、组、Wiki 摘要、相关标签摘要和预览能力状态。在线图片 URL 不进入参考数据库；预览通过受控 proxy/cache endpoint 获取。

### `POST /related-tags`

```json
{
  "tags": ["maid", "twintails"],
  "excluded": ["blonde_hair"],
  "categories": ["general"],
  "limit": 20
}
```

响应必须包含每个结果的 `sources`、`cooc_count`、`raw_score`、`display_score`、`algorithm_version` 和 `data_pack_id`。

### `GET /artists/search`

已实现 canonical 名、`@render name` 和空格形式搜索，并返回历史作品量、关联线索数和代表性非敏感通用标签。当前数据包没有画师中文名/别名字段，因此不会伪造这两类检索能力。

### `GET /artists/{canonical_name}`

返回画师基本信息及最多 50 条画师—标签共现线索。每条线索包含 NPMI 特征关联、画师作品覆盖率、历史共现数、敏感属性和场景维度；这些指标用于安排测试，不得称为画质分。

### `POST /artists/recommend`

只做推荐，不自动修改工作台。响应包含命中标签、NPMI 分解、热度和警告；不得把分数命名为“画质分”。

## 6. 工作台与候选

### `POST /workbench/candidates`（已实现）

首个产品切片接收由工作台明确拆分的元素，而不把模糊自然语言解析伪装成已完成能力：

```json
{
  "source_text": "女仆，双马尾，不要金发",
  "source_language": "zh",
  "model_profile": "anima_base_v1",
  "elements": [
    {"id": "e_maid", "text": "女仆", "state": "locked"},
    {"id": "e_hair", "text": "双马尾", "state": "required"},
    {"id": "e_no_blonde", "text": "金发", "state": "excluded"}
  ],
  "relations": []
}
```

服务端执行 Literal 和由显式关系触发的 Hybrid 生成，并在响应前运行独立 validator。成功响应包含 `intent`、`candidates`、`validation`、`data_pack_id`、`tag_suggestions` 与 `artist_suggestions`；必须包含 Literal。普通相关标签和画师只作为建议返回，绝不自动写入提示词。`relations` 只接受引用现有 element ID 的明确关系，不从普通文本猜测。

当结构化工作台传入的是用户分拆的中文概念（而非 `canonical_tag` 或关系图）时，它与自然语言入口共用本地翻译和 Scene Draft 消歧：唯一的 canonical/别名/中文主名可确认；一对多的中文检索词不自动确认。`selected_tags` 可在复用 `translated_text` 的前提下重新编译；明确排除项仍独立进入负向提示词。

### `POST /local-natural/candidates`（已实现）

中文自然语言主入口。它调用 V2 的离线翻译适配器，并将原文、译文和本地索引结果分别保留为可审查的 `scene_draft`；不调用 AI API 抽取器，也不调用 V2 的旧编译管线。

```json
{
  "source_text": "一位未知角色站在雨中，不要文字和水印",
  "excluded_text": "签名",
  "model_profile": "anima_aesthetic_v1",
  "translated_text": "An unknown character stands in the rain",
  "selected_tags": ["rain"],
  "fact_owners": {},
  "confirmed_relations": []
}
```

`translated_text` 省略时由本地翻译生成；传入时会原样复用，便于用户编辑画面计划或确认/取消 `selected_tags` 后只重新映射和渲染。显式的“不要/避免/排除”等原文片段会在翻译前分流，`excluded_text` 可补充或修正排除事实；两者均按排除优先，不能进入正向提示词。

响应中的 `scene_draft` 按 `confirmed`、`exclusions`、`suggestions` 和 `unresolved` 展示证据状态：原文精确命中与用户选择才进入 Literal；译文索引与共现结果只进入建议池；部分命中不会再宣称整句已理解。像“文字”这种没有唯一 canonical 的广义排除概念，会透明展开成多个可审阅负向标签，并标记为概念展开而非精确命中。若没有安全正向标签命中，Literal 使用可追踪的 `local_prose_baseline` 保留译文，而不是返回 422 或擅自补充标签。

每个 `SceneDraftItem` 同时返回 `fact_type`。本地入口只根据参考数据中唯一对应的标签组标记角色/主体、外观、服装、动作、场景、构图或风格；缺少分组或存在跨层歧义时返回 `other`。Literal renderer 使用同一事实类型排序已有标签，同层保持原始证据顺序；该步骤不会添加原文未出现的质量词、构图词或增强标签。

`scene_draft.entities` 只包含由 character 类别或明确人物/传说生物标签组支持的可见实体锚点。可归属事实分别返回 `owner_entity_id` 与 `suggested_owner_entity_id`：前者是用户已确认结果，后者只是单实体情况下的界面建议。客户端通过 `fact_owners: {element_id: entity_id}` 确认或取消归属；服务端只接受当前草稿仍存在的实体，归属变化不会重新调用翻译模型，也不会改变 Literal 提示词文本。

`scene_draft.relations` 返回当前可建立的显式关系及 `suggested | confirmed` 状态。首版只在服装事实已经通过 `fact_owners` 归属到实体后，建议 `wearing`；客户端还必须通过 `confirmed_relations: [{source_entity_id, target_element_id, relation: "wearing"}]` 单独确认。确认后的关系进入 `ConstraintGraph.edges` 并生成或更新 Hybrid，未确认关系不影响任何候选，Literal 在两种状态下都不变。关系引用失效时服务端丢弃该关系并返回风险说明，不把它迁移给其他事实或实体。

### `POST /intent/parse`（已实现）

输入原始中文/英文，复用 V2 `AIExtractService` 和用户已有 AI provider/凭据，返回完整 V3 `IntentDocument`、抽取摘要与解析器来源。人物归属、外观、服装、动作、关系、场景、构图和排除项都保留 semantic provenance；此接口不调用 V2 `PromptPipeline`/`PromptCompiler`，也不做共现扩展。未配置 API Key 返回 `intent_parser_unavailable`（503），上游 AI 失败返回可重试的 `intent_parse_failed`（502）。

### `POST /prompt-candidates`（已实现）

```json
{
  "intent": {"source_text": "...", "source_language": "zh", "graph": {"elements": [], "edges": []}},
  "model_profile": "anima_base_v1"
}
```

该入口与 `/workbench/candidates` 共用同一生成和独立校验函数。`scene_plan_en` 存在时只追加一条 Hybrid 候选，不改变 Literal；未经用户选择的 Hybrid 不会自动提交远程生图。

### `POST /translation`（已实现）

接收 `source_text` 与 `zh_en | en_zh` 方向，返回本地翻译文本、引擎名和模型就绪状态。该端点本身只提供翻译；`/local-natural/candidates` 可将同一翻译作为可编辑 prose baseline 进入候选编译。两者都复用 V2 `TranslationService`，且不联网下载模型。

`PromptCandidate`：

```json
{
  "id": "candidate_xxx",
  "lane": "literal",
  "title": "高保真基准",
  "positive_prompt": "...",
  "negative_prompt": "...",
  "artists": [],
  "tags": [
    {
      "name": "school_uniform",
      "rendered": "school uniform",
      "state": "required",
      "source": "exact",
      "source_element_ids": ["e_3"],
      "reason": "用户明确要求",
      "score": null
    }
  ],
  "preserved_element_ids": [],
  "unresolved_element_ids": [],
  "warnings": [],
  "score_breakdown": {},
  "versions": {
    "data_pack": "...",
    "algorithm": "...",
    "templates": "...",
    "model_profile": "..."
  }
}
```

## 7. 画廊（首个只读切片已实现）

- `GET /gallery/assets`：扫描 V2 run、manifest 与输出目录中的散落图片，返回项目、模型、批次、提示词和可用的 V3 candidate 版本快照。
- `GET /gallery/assets/content?path=...`：只读取配置输出根目录内且不属于 `.trash` 的图片。
- `GET /gallery/assets/thumbnail?path=...&size=640`：使用 V2/V3 共用的确定性 WebP 缩略图缓存；损坏或不支持的图片安全回退为源文件。
- `POST /gallery/assets/state`：设置 `kept`、`rejected` 或清除状态，只写用户状态库。
- `POST /gallery/assets/trash`：把图片移动到可恢复的 `.trash`；正在处理的源图拒绝移动。
- `GET /gallery/trash`、`GET /gallery/trash/content|thumbnail`：列出和安全读取回收站图片。
- `POST /gallery/trash/restore`：恢复到原相对路径；若原位置已有文件，使用 V2 的安全重命名规则。
- `GET /gallery/process`：返回 V2 画廊处理配置和持久化任务。
- `POST /gallery/process`：以 `regenerate` 或 `upscale` 提交图片；复用 V2 队列和远程执行。
- `POST /gallery/process/action`：只允许排队取消、失败重试和清理终态任务。

图片元素无法附加自定义 Header，因此 session exchange 会额外设置仅限 `/api/v3/gallery/` 路径的 HttpOnly、SameSite=Strict cookie。标签、工作台、生图等普通业务 API 仍要求 `X-Anima-Session`，不会因画廊而扩大 cookie 鉴权范围；所有画廊写请求仍需通过 Origin 与 JSON 校验。

工作台 create/update 请求可附带 `candidate_snapshot`：完整 `IntentDocument`、1～4 个 `PromptCandidate`、`CandidateSetValidationReport` 和 `data_pack_id`。服务端按领域合同重新校验后持久化；旧数据库自动增加 nullable 列，不重写历史草稿。

不论其他 lane 是否可用，成功响应必须包含 `literal`。若 literal 无法表达某个必需元素，将其放入 `unresolved_element_ids` 并给出警告，不伪造标签。

### 工作台持久化（首版已实现）

- `GET /workspaces`
- `POST /workspaces`
- `GET /workspaces/{id}`
- `PUT /workspaces/{id}`
- `DELETE /workspaces/{id}`

工作台草稿包含 `positive_text`、`excluded_text` 和 `model_profile`。创建返回 revision 1；`PUT` 和 `DELETE` 必须携带当前 revision。更新使用 SQLite `BEGIN IMMEDIATE` 和 revision 乐观锁，旧 revision 返回 HTTP 409 及服务端当前 revision，避免两个标签页互相覆盖。

待实现的会话扩展见第 9 节：`reference_preset_id` 为只读来源投影，与 `generation_settings.preset_id` 无关；新增写 DTO 和旧保存兼容规则不能改变上述现有接口的已实现状态。

状态库存放在独立的 `workspaces.db`，不写入只读参考数据包。删除当前使用软删除，不直接永久清除；恢复端点尚未开放。

## 8. 生图与画廊写操作

### `POST /generation-requests/preview`（已实现）

接收已校验的 V3 `candidate + intent`、生成设置和可选工作区版本，返回将要交给 V2 远程服务的 `PromptJob` 快照。该端点不创建队列任务、不连接 SSH，用于在产生副作用前检查提示词、显式参数和版本快照；工作流配方能力在选择具体目标并提交时校验。

生成设置由 V3 正式拥有并校验：兼容字段 `preset_id` 保存当前 recipe ID，另含 `width`、`height`、`steps`、`cfg`、`sampler`、`scheduler`、`seed` 和 `batch_size`。V3 发送的显式高级参数优先于兼容层的旧预设值。

完整仓库或安装 V2 运行时时，bootstrap 的 `features.v2_generation_bridge` 为 `true`。单独安装 V3 且缺少 V2 包时，其他 API 仍可使用，本端点返回 HTTP 503 / `v2_runtime_missing`。

### `POST /generation-runs`（已实现）

输入附带完整的已验证 `candidate + intent` 快照、生成参数、`remote_profile_id` 和 `workflow_profile_id`。必须提供 `Idempotency-Key`；键与 V2 任务一起持久化，服务重启后重试仍返回原任务。

服务端使用原 V2 SQLite 中的云主机、工作流和输出目录配置，密码只从系统凭据库读取，不接收或返回 API 明文凭据。提交成功返回 HTTP 202 和本地 `draft` run，单工作线程依次交给现有 V2 `RemoteExecutionCoordinator`。

### `POST /artist-comparisons`（已实现）

画师对照把一条用户锁定的无画师基准候选复制为多个独立任务。请求必须提供 1–20 个当前基准推荐池中的 `artist_names`、固定非负 `seed`、同一个远程目标及 `Idempotency-Key`。服务端对每位画师只追加一个 `@artist`，并保持基准的正/负提示词、模型、预设、尺寸、工作流与 Seed 不变；它不会把多个画师混写进同一条提示词。

响应按画师返回已进入队列的 run 和明确失败项。每个 V2 `PromptJob`、run 响应和画廊资产都会保留安全的 `artist_comparison` 元数据（批次 ID、画师、位置、总数和 Seed），便于按批次比较或单项重试；不返回内部 request JSON 或凭据。默认本地等待队列可容纳 20 项，若已有任务占满队列，响应会明确列出未接受的画师。

### `POST /generation-credentials/private-key-passphrase`（已实现）

接收 `remote_profile_id` 和加密私钥口令。口令只写入当前服务进程内的可清理字节缓冲区，服务停止时覆写并移除；响应只返回是否已配置。它不会写入 V2/V3 SQLite、工作区、生成 run/request JSON、manifest 或日志。传空字符串可清除该主机当前进程内的口令。

### `GET /generation-runs/{id}`（已实现）

返回 draft、connecting、preparing、queued、running、downloading、completed、failed、canceled 等状态、进度、产物数量以及可安全展示的错误。不返回 `request_json`、完整工作流或凭据。

### `GET /generation-runs`（已实现）

返回按更新时间倒序的最近任务。每个任务包含 `available_actions`，前端不根据错误字符串猜测可执行动作。

### `GET /generation-targets`（已实现）

返回 V2 中已启用的云主机和已验证工作流组合、兼容模型、主机指纹就绪状态，以及由该工作流真实模板派生的 V3 生成配方契约。不包含用户名、密码或私钥路径。

每个目标包含：

- `generation_recipes`：只适用于该工作流的结果导向配方，包含参数、用途和证据等级；
- `parameter_capabilities`：逐项声明 `editable` 或 `fixed`、范围、候选值和锁定原因；
- `stages`：实际执行阶段快照。HiRes 会分别返回基础生成和精修阶段；
- `default_recipe_id`：切换到该工作流时使用的基线配方。

DMDX、HiRes 等结构性工作流的关键参数由模板锁定。提交时服务端再次验证配方 ID、参数一致性和能力范围，不能通过手写请求绕过。旧工作区的 `fast/balanced/quality` 仅作为 `custom` 兼容输入，不再拥有覆盖工作流模板的权力。

### `POST /generation-runs/{id}/actions`（已实现）

`cancel_queued` 只能取消未开始的本地等待任务。`retry_check` 和 `continue_download` 把已有 remote prompt ID 的历史 run 交给 V2 `resume()`，不重复提交 ComfyUI 工作流。中断共享 ComfyUI 的全局运行任务不放进普通动作。

### 画廊

- `GET /gallery/assets`
- `POST /gallery/assets/state`
- `POST /gallery/assets/trash`
- `POST /gallery/assets/restore`
- `POST /gallery/assets/delete-permanently`
- `POST /gallery/assets/regenerate`

所有写接口都要求会话令牌和相对资源 ID。永久删除保留二次确认参数，并在响应中说明是否可恢复。

## 9. 会话工作台与参考画廊（分阶段实现合同）

本节按 ADR-025 修订原 ADR-024 预留接口；完整状态机、DTO 所有权和验收见 [CONVERSATIONAL_WORKBENCH.md](CONVERSATIONAL_WORKBENCH.md) 修订 2。本文与设计须同 PR 同步；若有歧义先修合同，不能由实现默选含义。2026-09-10 首批已实现 §9.1 的草稿字段、turns/reset，以及 LLM settings 的 supports_vision/ingest_enable_thinking；其他新路由与 §9.2 提交扩展仍待实现，客户端不得提前发送。两项用户可见 flag 保持 false，实际进展见 [STATUS](../../v3/STATUS.md)。

三类 ID 分轨：mode/rule_id 是处理方式（会话仅 faithful/expand）；generation_settings.preset_id 是生成配方；reference_preset_id 是例图来源 ID（ex_ 或 off_）。旧 POST /workbench/prompt 永不增加参考字段，新能力走 turns/pins。未注册路径 404 not_found；未知请求键 422；不以空目录伪装功能上线。

### 9.1 草稿和会话

草稿新增 requirements(/1)、mode、compiled、reference_pin、只读 reference_preset_id、最近 100 条 conversation_events，以及分页派生的 session_previews。参考内容在 pins 时复制，草稿后续独立编辑。来源备注不重复进入 requirements；模型不写资源和控制标志。

PUT /workspaces/{id} 新增可选 mode、requirements_edit（layers/loras）、prompt_edit（positive/negative）。仍需当前 revision；省略新字段保留原状态。存盘读字段 round-trip 只允许与服务端同值，差异 422 read_only_field；动态 session_previews/compile_state 的合法回显直接丢弃，不作为写入或文件访问来源。不能赋值 revision/指纹/pin 等服务端权威字段。仅正负实际手改且输入 fresh 时更新 compiled；输入编辑和实际 prompt_edit 不得同请求混写。POST 不接受客户端 compiled；会话 reset 使用独立端点。

compiled 含 positive/negative/mode/source/compiled_token/inputs_fingerprint/prompt_fingerprint/compiler_contract。token 服务端生成且不复用，是版本；prompt_fingerprint 只是文本内容哈希。inputs 指纹覆盖完整规范化 requirements、mode、model_profile、compiler_contract；后端返回 compile_state=missing|fresh|stale，前端不自行实现哈希。

| 方法 | 路径 | 请求/结果 |
| --- | --- | --- |
| POST | `/workbench/turns` | workspace_id/revision/task=rewrite/mode/delta；可选当前正负 compiled；无完整 requirements、messages、图片或参考 ID |
| POST | `/workbench/pins` | workspace_id/revision/example_id/source_version/role；role=style\|lighting\|composition\|whole_scene；冻结来源并复制未锁层 |
| DELETE | `/workbench/pins` | workspace_id/revision；只解除来源，保留已复制内容 |
| POST | `/workbench/reset` | workspace_id/revision；清会话状态，不删除/取消已接受任务 |
| GET | `/workbench/availability` | workspace_id/revision/remote_profile_id/workflow_profile_id，可选 workflow_snapshot_run_id；检查草稿实际资源 |
| GET | `/workspaces/{id}/runs` | cursor/limit，恢复运行中及历史本轮任务 |

Turns 在内存设置本轮 mode，事务外调用模型，结果以原 workspace revision CAS 短事务写回。失败/冲突不持久化半轮；delta 最长 4000。首编有要求或 stale 重编译允许空 delta；fresh 空 delta 返回 empty_turn，无要求返回 empty_requirements。响应含完整 draft、新 revision、compile_state、changed_layers、正负/warnings。

### 9.2 双提交端点扩展

POST /direct-prompt/runs 和 POST /generation-runs 新增 submission_kind（默认 legacy）、compiled_token、参考/资源字段、workflow_snapshot_run_id。Direct 新增 workspace_id/workspace_revision；Generation 已继承这两个字段，不重复声明。

| submission_kind | 契约 |
| --- | --- |
| legacy | 原请求继续合法；workspace 版本仅元数据，不写 compiled、不自动读参考资源；可显式独立 lora_selection；禁止参考 ID/version |
| conversational | workspace_id/workspace_revision/compiled_token 必填；服务端检查 revision、token、fresh；资源只从草稿读，禁止请求 reference_preset_id/source_version/lora_selection |
| reference | 无 workspace；reference_preset_id/source_version 必填；冻结该版本 required 资源；可显式 lora_selection 按 logical_id 覆盖权重，空列表不删除 required |

LoraSelectionDto 为 logical_id/file_name/weight/trigger_words，extra=forbid。新 UI 固定 conversational，不可在字段缺失时退回 legacy。请求实际正负只 strip、不重跑词典编译或补负面；合法手改在接受事务中更新 source/token/revision。请求模型与草稿模型必须一致。

所有生图请求必须 Idempotency-Key。新模式先查已有接受记录：同 key 同规范化 payload 返回原接受回执；不同 payload 409 idempotency_conflict；查重先于 stale 检查。草稿 CAS、不可变生成快照、预分配 run_id、接受响应在 workspaces.db 同一短事务提交，再幂等交付队列；禁止“先可执行入队，后写草稿”。纯旧任务协议仍保留，但 key 入口不能与新模式分裂。

202 保留既有 run 响应字段（id 不改名为 run_id），新协议路径新增 submission_id；会话模式另含 workspace_id/workspace_revision/compiled_token。队列接手前也能按 run ID 查询到 draft 状态及“已接受，等待入队”，响应丢失重试不重复生图。完整 requirements/实际正负/最终 LoRA/生成设置/已解析 seed/工作流/来源版本在内部冻结，不下发整个 request_json。收藏历史图读取该快照；没有快照的旧图明确缺少要求，不拿当前草稿补齐。

重放先从 workflow_snapshot_run_id 取得 frozen dump，再验证该 dump 对当前远端是否可执行；workflow_profile_id 必须与 dump.id 一致。缺快照 422 workflow_snapshot_missing；不自动选回当前目录。普通参考提交不隐式重放。

### 9.3 参考例图 CRUD 与 ingest

用户例图 ex_ ID，官方 off_ ID。用户例图存 examples.db/example-media，官方包只读；官方备注用独立 overrides 表，改官方要求需复制为我的例图。

| 方法 | 路径 | 请求要点 |
| --- | --- | --- |
| GET/POST | `/reference-examples` | 列表 q/origin/limit/cursor；创建仅 multipart file/title/可选 metadata JSON 字段，不接本机路径 |
| GET/PATCH/DELETE | `/reference-examples/{id}` | PATCH/DELETE 必须 revision；PATCH 允许 title/notes/requirements_edit/声明兼容性；不能伪造 run 身份 |
| PATCH | `/reference-examples/{off_id}/notes` | override_revision（首次 0）+ notes |
| POST | `/reference-examples/{off_id}/copy` | source_version；复制为新 ex_ ID |
| POST | `/reference-examples/install-bundled` | 严格空对象 `{}`；显式安装内置包，返回 `{id,ready,count}`；已有有效激活包时原样返回，不替换 |
| POST | `/reference-examples/from-gallery` | 受 gallery 根目录授权的 path，服务端复制 |
| POST | `/reference-examples/from-run` | run_id/path，须属于该 run 的 artifacts |
| GET | `/reference-examples/{id}/content`、`/thumbnail` | 已登记媒体；无绝对路径；cookie 限参考媒体前缀或用 session header |
| POST | `/reference-examples/{id}/ingest` | revision/source/use_external_prompt_notes；source=image（兼容默认）或 prompt；仅用户条目；没有 enable_thinking |

source_version 标识要应用的例图版本；与用户 edit revision/官方 pack+条目摘要对应。列表、详情返回 requirements_valid 与 ingest_state，二者独立：失败可保留旧合法 JSON，仍允许钉选。

Ingest 全局最多 1 个活动请求，supports_vision=false 立即 422 不收费调用；设置 ingest_enable_thinking 默认 false。先短事务分配 attempt/版本和 pending，再事务外调用，写回 CAS pending revision+attempt；用户编辑/删除使旧 attempt 失效。重启 pending 转 failed/ingest_interrupted，不自动重发。锁层/现有控制标志保留，模型只建议内容，LoRA/compat 不得臆造。

上传 file≤20MB，解码≤40MP，静态 PNG/JPEG/WebP；拒绝越界路径/reparse 目标和解码炸弹。原图保存；发送 LLM 前 2048 最长边 JPEG quality 85。key/图像/整段 prompt 不记日志。

### 9.4 参考预设投影与 LoRA

GET /reference-presets 参数 q/model_profile/workflow_kind/availability/limit/cursor，v1 无 category；catalog_version=anima-ref-1；返回 id/source_version/title/source、style/lighting/composition 骨架、兼容性、loras、availability。无 few-shot、无整段 external_prompt，可有 has_external_notes。

GET /reference-presets/{id} 返回当前版本详情；GET /reference-presets/{id}/availability 带 source_version 和目标参数（remote_profile_id/workflow_profile_id/model_profile，可 workflow_snapshot_run_id），版本冲突 409 reference_version_conflict。

availability 为 ready/missing_lora/lora_unmapped/incompatible_model/incompatible_workflow，未选目标或能力未知为 unknown + reason。生成前统一解析实际工作流、槽位和远端文件绑定，渲染消费同一结果。缺文件/槽位 422 lora_not_installed/reference_preset_unavailable，不剥离提交。钉选本身允许离线/缺资源；复制后用户删除资源是合法编辑，不得在提交时加回。

GET/PUT /workflows/servers/{remote}/{workflow}/lora-bindings 为 logical_id/resource_digest 到 slot_key/remote_file_name 的显式绑定；PUT 必须 mapping_revision/workflow_revision/remote_fingerprint 与完整 bindings，[] 清空。实际枚举/槽位校验后 CAS，冲突 409 mapping_revision_conflict；resource_digest 由后端按声明文件/source/trigger 计算，避免同名 logical_id 混用。不能只保存原节点 mapping 后让编译器写回旧文件名。

官方包 anima-v3-examples/1，SHA 校验后 current.json 原子切换；列表返回 official_pack={id,ready,count}，缺包 ready=false，仍提供用户收藏。换包不删除用户备注或改变已钉草稿资源。

`install-bundled` 沿用会话与 Origin 校验，不接收路径、不联网、不调用模型。进程内串行安装，源仅为随发行携带的内置包；个人笔记不变。内置文件缺失返回 422 `bundled_examples_missing`，文件校验或写入失败返回 422 `bundled_examples_install_failed`；错误不回显文件路径，失败后可显式重试。

### 9.5 产物投影、flags 与错误

GET /generation-runs/{id}/artifacts 返回 `{items:[{id,path,content_url,thumbnail_url}]}`，只含画廊根内相对路径，复用现有 content/thumbnail。产物未就绪 items=[]，不伪造 completed；missing run 404。不下发 local_path/request_json。

conversational_workbench/reference_gallery 默认 false；内部可按依赖打开，发布要求恢复/并发测试、官方包及真实云端多轮/固定 seed 评测。回滚新 UI 不删除数据或停止已接受提交的恢复。

错误增量：empty_turn/empty_requirements/invalid_layer_updates/invalid_workspace_edit/read_only_field/vision_unsupported/workflow_snapshot_missing 为 422；stale_compiled_prompt（token 不匹配或输入 stale）422；workspace_revision_conflict/example_revision_conflict/reference_version_conflict/ingest_superseded/idempotency_conflict/mapping_revision_conflict 为 409；模型失败 502 llm_generation_failed（超时 details.reason=llm_timeout）；并发限制 429 rate_limited。已接受 run 在远端是否接收不确定时为 failed/generation_execution_uncertain，不能自动重发。缺资源沿用既有错误族。

### 9.6 用户参考库实施状态（2026-09-10）

会话改写错误诊断补充：`llm_generation_failed` 的 `details.reason` 可为 `upstream_http_error`、`transport_error`、`invalid_response`、`response_too_large`、`incomplete_response`、`empty_response`、`thinking_disable_unsupported`；HTTP 上游拒绝附安全整数 `upstream_status`。不返回上游正文、Key、请求或异常原文。上游 400/401/403/404/422 标记 `retryable=false`，其余仍不自动重试。已知 GLM-5.3/Flash 关闭思考的任务在联网前直接返回 422 `thinking_disable_unsupported`；代理将其他名称路由到仅思考模型时，已发生的请求仍返回 502 并以 reason 提示更换模型。

已实现 GET/POST /reference-examples、单项 GET/PATCH/DELETE、content/thumbnail、from-gallery/from-run、ingest，以及 POST/DELETE /workbench/pins。上传独占 multipart/form-data，其他写请求仍为 JSON，均验证会话和 Origin。metadata 只允许 notes、requirements_edit、compat（模型/工作流类型声明）。PATCH revision 必填，省略字段保留，requirements_edit 不接受 null。

列表返回 items、next_cursor、official_pack（未安装/校验失败 ready=false，已就绪含 id/count）。游标绑定查询、用户目录版本及官方包版本，变动返回 409 reference_version_conflict；官方条目按 ID 排在用户条目前，用户条目按更新时间倒序。用户 source_version 为 revision 字符串，官方为 pack_id 与条目内容摘要。failed ingest 可保留合法要求。from-run 验证已登记 artifact，公开 provenance 仅含 run_id、实际正负、model_profile、settings、workflow_snapshot_ref。

分析失败返回 502；编辑/删除使 late result 返回 409 ingest_superseded。pending 启动/完成各升例图 revision，用户编辑使 attempt 失效。

官方 PATCH /reference-examples/{off_id}/notes 接收 override_revision 与 notes；POST /{off_id}/copy 接收 source_version，返回新的用户条目。官方笔记不改变包内容与内容版本。reference-presets 列表/详情/availability 已注册，列表过滤后的页可少于 limit，继续分页应使用 next_cursor；未检查远端时 availability 为 unknown，不宣称 ready。availability 的 source_version 必填。

独立 reference 提交现已读取真实目录：要求与来源快照冻结在接受日志中；lora_selection 省略时使用来源 required 项，显式 [] 表示不使用 LoRA，不从来源自动补回。实际资源与原始来源分别记录。重复请求不重读已删除/已更新来源，不重新生成。

GET LoRA bindings 增加 slots（槽位到枚举文件列表）、capabilities_ready；未检测/已过期返回空 slots 与 false，不发起检测。workbench availability 增加 resource_requirements（logical_id/file_name/resource_digest）供映射界面使用。

## 10. 设置与更新

- `GET /settings`
- `PATCH /settings`
- `GET /data-pack/status`
- `POST /data-pack/check-update`
- `POST /data-pack/install`
- `GET /data-pack/install/{job_id}`

设置响应永远不返回密码或 API Key。凭据只通过桌面壳或专用一次性输入流程写入系统凭据库。

## 11. 兼容与演进

- 新增响应字段属于向后兼容。
- 删除、重命名、改变字段含义必须升级 `/api/vN`。
- `algorithm_version`、`data_pack_id` 和 `model_profile_id` 是生成快照的一部分，不随应用升级回写旧记录。
- 前端与后端启动时比较 API major，不兼容时显示升级提示，不尝试带病运行。
