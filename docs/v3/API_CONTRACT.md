# V3 本地 API 契约

状态：首版接口合同；V3-010～012 已实现 session、标签/推荐和工作台候选纵向切片

基础路径：`/api/v3`

当前实现端点：`/health`、`/session/exchange`、`/bootstrap`、`/tags/search`、`/tags/{canonical_name}`、`/related-tags`、`/artists/recommend`、`/intent/parse`、`/workbench/candidates`、`/prompt-candidates`、`/generation-requests/preview`、`/generation-targets`、`/generation-runs` 提交/列表/查询/排队取消/恢复、`/gallery/assets` 列表/原图/缩略图和 `/workspaces` CRUD。其余端点按后续任务继续实现，未实现能力不会返回伪造成功响应。

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

支持名称、中文名、别名和擅长标签搜索。

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

服务端依次执行 literal、conservative、artist 和显式关系 hybrid 生成，并在响应前运行独立 validator。成功响应包含 `intent`、`candidates`、`validation` 和 `data_pack_id`；没有安全增量时允许省略相应 lane，但必须包含 literal。`relations` 只接受引用现有 element ID 的明确关系，不从普通文本猜测。

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

接收 `source_text` 与 `zh_en | en_zh` 方向，返回本地翻译文本、引擎名和模型就绪状态。该端点复用 V2 `TranslationService`，不联网下载模型，也不参与 Intent 抽取或候选编译。

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

状态库存放在独立的 `workspaces.db`，不写入只读参考数据包。删除当前使用软删除，不直接永久清除；恢复端点尚未开放。

## 8. 生图与画廊写操作

### `POST /generation-requests/preview`（已实现）

接收已校验的 V3 `candidate + intent`、生成设置和可选工作区版本，返回将要交给 V2 远程服务的 `PromptJob` 快照。该端点不创建队列任务、不连接 SSH，用于在产生副作用前校验模型预设、提示词和版本快照。

完整仓库或安装 V2 运行时时，bootstrap 的 `features.v2_generation_bridge` 为 `true`。单独安装 V3 且缺少 V2 包时，其他 API 仍可使用，本端点返回 HTTP 503 / `v2_runtime_missing`。

### `POST /generation-runs`（已实现）

输入附带完整的已验证 `candidate + intent` 快照、生成参数、`remote_profile_id` 和 `workflow_profile_id`。必须提供 `Idempotency-Key`；键与 V2 任务一起持久化，服务重启后重试仍返回原任务。

服务端使用原 V2 SQLite 中的云主机、工作流和输出目录配置，密码只从系统凭据库读取，不接收或返回 API 明文凭据。提交成功返回 HTTP 202 和本地 `draft` run，单工作线程依次交给现有 V2 `RemoteExecutionCoordinator`。

### `POST /generation-credentials/private-key-passphrase`（已实现）

接收 `remote_profile_id` 和加密私钥口令。口令只写入当前服务进程内的可清理字节缓冲区，服务停止时覆写并移除；响应只返回是否已配置。它不会写入 V2/V3 SQLite、工作区、生成 run/request JSON、manifest 或日志。传空字符串可清除该主机当前进程内的口令。

### `GET /generation-runs/{id}`（已实现）

返回 draft、connecting、preparing、queued、running、downloading、completed、failed、canceled 等状态、进度、产物数量以及可安全展示的错误。不返回 `request_json`、完整工作流或凭据。

### `GET /generation-runs`（已实现）

返回按更新时间倒序的最近任务。每个任务包含 `available_actions`，前端不根据错误字符串猜测可执行动作。

### `GET /generation-targets`（已实现）

返回 V2 中已启用的云主机和已验证工作流组合、兼容模型以及主机指纹就绪状态。不包含 host 地址、用户名、密码或私钥路径。

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

## 9. 设置与更新

- `GET /settings`
- `PATCH /settings`
- `GET /data-pack/status`
- `POST /data-pack/check-update`
- `POST /data-pack/install`
- `GET /data-pack/install/{job_id}`

设置响应永远不返回密码或 API Key。凭据只通过桌面壳或专用一次性输入流程写入系统凭据库。

## 10. 兼容与演进

- 新增响应字段属于向后兼容。
- 删除、重命名、改变字段含义必须升级 `/api/vN`。
- `algorithm_version`、`data_pack_id` 和 `model_profile_id` 是生成快照的一部分，不随应用升级回写旧记录。
- 前端与后端启动时比较 API major，不兼容时显示升级提示，不尝试带病运行。
