# 会话工作台与参考画廊设计

设计来源：项目负责人多轮讨论；初稿由 Grok 整理；Codex 根据审计修订。  
初稿：2026-09-09；本版：2026-09-10，修订 2。  
状态：分阶段实施合同；后端基础与 turns/reset 首批已实现，见 [实施进展](../../v3/STATUS.md)。其他阶段及真实模型验收未完成，两项用户可见 flag 仍关闭。  
目标分支：`feature/llm-workbench`。  
关联：[ADR-025](DECISIONS.md)、[API 合同](API_CONTRACT.md)、[现有原型](LLM_PROTOTYPE.md)、[数据合同](DATA_CONTRACT.md)、[产品基线](PRODUCT_BASELINE.md)。  
历史：[原稿](audits/2026-09-09-conversational-workbench/ORIGINAL_DESIGN.md)、[初稿审计](audits/2026-09-09-conversational-workbench/AUDIT.md)。原稿只作历史记录；实现以本版及同步修订的 API 合同为准。

## 1. 产品目标与冻结范围

工作台帮助用户逐轮形成并保持画面意图。用户输入一句要求，检查本轮修改，再显式生图；无需每轮重写完整提示词。参考图帮助用户表达画风、光影和构图，分析成可编辑要求后进入同一流程。

**用户已决定的三项范围不变：**

1. v1 随附少量官方例图包。策展、可少、可管理；不爬 Animadex/Civitai；更新不得覆盖用户收藏和备注。
2. v1 不做“改完直接出图”，不增加该草稿字段。生图始终是显式按钮。
3. 本地 4B 不纳入 v1 验收。模型接口保持可扩展，真实验收使用已配置的云端/API LLM。

### 1.1 主路径

`表达要求 / 选择参考 → requirements → 编译 Anima 正负提示词 → 审阅或手改 → 显式生图 → 看结果 → 下一轮`

requirements 是持久的结构化记忆；聊天记录只用于用户回看，不是 LLM 上下文。编译稿可见、可编辑，资源独立显示。允许用户用自然语言迭代，也允许精确调整 tag、LoRA 和工作流。

### 1.2 三个表面

| 表面 | 路由 | 职责与数据 |
| --- | --- | --- |
| 会话工作台 | `/workbench`，演进现页 | 草稿、修改回执、正负编辑器、当前会话产物；`workspaces.db` |
| 参考画廊 | `/references`，新路由 | 长期收藏、分析、手填、按角色钉选；`examples.db` 与只读官方包 |
| 历史画廊 | `/gallery`，现有 | 履历、kept/rejected、回收站、再生成/放大；现有输出和用户状态 |

历史 kept 不等于参考收藏。必须显式复制文件和元数据后进入参考库；历史原图被回收不损坏已复制收藏。胶片条使用 run artifacts 的画廊相对路径，不靠项目名过滤历史列表。

### 1.3 非目标

- 不做 img2img / IP-Adapter / ControlNet；参考像素不进入采样器。
- 不做公开风格卡市场、站点发现或抓取；找图发生在产品外。
- 不做 Civitai/HF 下载、SFTP/SCP 上传 LoRA，submit 不安装模型。v1 只映射远端已有资源。
- 不做多例图同时钉选；v1 一个草稿最多一个当前 pin。
- 不把插件通用/人像/Tags 等扩写模板做成主芯片；主芯片只有 faithful/expand。
- 不把完整 transcript 发给模型，不向模型要求 JSON Patch。
- 不接受 JSON 任意本机路径导入；from-gallery/from-run 是受限相对路径的专用入口。
- 不推翻现有词典/Literal 候选和旧 LLM 原型；作为兼容路径保留。

## 2. 现状与实施边界

以下是本版修订时核对到的现状；后文的新增字段、表和端点均是待实现合同。

| 能力 | 现状 / 必须补齐 |
| --- | --- |
| `POST /workbench/prompt` | `PromptGenerateRequest` extra=forbid；source_text、excluded_text、mode、可选 rule_id/source_language；rule_id 非空拒绝；不扩展为会话端点 |
| LLM | 现有 `expand_prompt` 不传图；新增 `complete()` 给 turns/ingest，旧原型保留原协议 |
| WorkspaceStore | 整数 revision、短事务 BEGIN IMMEDIATE、连接 busy timeout 5 秒；没有会话字段或历史 requirements |
| 直出 | prepare_direct 只 strip 正负、不补默认负面；目前没有任务 LoRA 和 workspace 提交协议 |
| 队列 | submit 保存 run 后唤醒执行线程；仅队列已有幂等不等于 workspace 副作用幂等；新增持久提交协调层 |
| Workflow mapping | 键为 node_id.input_name，值是远端枚举资产名；编译器随后会用 job.lora_selection 写槽，必须统一解析结果 |
| 官方工作流 | 随包 txt2img 模板当前 lora_slots=[]；有槽的用户导入工作流才可承载 LoRA |
| Run 响应 | 当前只有 artifact_count，不能直接构成胶片条；新增 artifacts 投影，禁止下发 local_path/request_json |
| 模型管理 | ResourceManager 是 Helsinki 翻译缓存；不是 LoRA 目录。现有只读 read-file/上传 input 图不构成模型安装器 |

## 3. 权威对象与字段所有权

### 3.1 Requirements

契约 `anima-requirements/1`，对象 extra=forbid。层文本保持用户语言；只有编译稿为 Anima 英文。输入文本去首尾空白，空串不等于删除其他字段。字段默认、长度、枚举由 PR-1 的 DTO 与契约测试统一。

```json
{
  "contract": "anima-requirements/1",
  "revision": 3,
  "layers": {
    "subject": {"text": "成年女性侦探，短发，风衣，右手拿信", "locked": false},
    "style": {"text": "黑白炭笔，黑色电影", "medium": "charcoal", "artists": [], "locked": false},
    "lighting": {"text": "左侧台灯，硬侧光", "locked": false, "include_with_style_pin": true},
    "composition": {"text": "半身，平视", "shot": "upper_body", "locked": false, "include_with_style_pin": true},
    "exclusions": {"global": ["文字", "水印"], "scoped": [{"target": "信封", "concept": "文字"}], "locked": false}
  },
  "loras": [{
    "logical_id": "film_grain_style", "file_name": "film_grain_style.safetensors",
    "weight": 0.8, "trigger_words": ["film grain"], "required": true,
    "source": {"kind": "user", "model_version_id": null}
  }]
}
```

相对初稿，`pins`、`notes`、`compat` 移到各自拥有者，不再重复放入 requirements。这是尚未实现合同的修订，仍用 /1；实现后变更 schema 必须升级版本。

- `layers` 固定五层，完整对象必填；lighting/composition 的 include 标志默认 false；artists 默认 []，canonical 名不含 @。
- logical_id 在同一列表唯一，列表顺序有意义并参与指纹。最多 16 项；weight 有限数且在 [-2, 2] 内；trigger 最多 32 项、每项最长 200；层 text 最长 10000；global/scoped 各最多 100 项。目标工作流/模型可施加更严限制并明确 422。
- `file_name` 是声明的资产名称，允许合法远端枚举子目录，不是本机路径；不得通过它打开本机文件。模型不得新增或改写 LoRA 列表。
- required 是来源对资源依赖的声明。当前草稿中保留的每一项均必须解析成功，包括 required=false 的用户主动保留项；系统不静默剥离。用户显式删除是正常编辑。
- artists 只能来自用户声明或已经确认的例图元数据；vision 不凭画面风格猜作者。画面签名只能作为待确认建议进入 warnings，不能自动加入 artists。
- LLM 只能请求更新未锁层的内容字段，不能修改 locked/include 标志；这些控制由用户拥有。locked 表示系统不得自动改该层，不阻止用户直接编辑。

### 3.2 Workspace 草稿读模型

保留既有 positive_text/excluded_text/input_mode/natural_text/selected_tags/generation_settings 等字段，新增：

| 字段 | 所有权与含义 |
| --- | --- |
| `mode` | 用户输入 faithful/expand，默认 faithful |
| `requirements` | null 或完整 /1；revision 仅服务端递增 |
| `compiled` | null 或 §4 编译记录；服务端维护 |
| `reference_pin` | null 或 `{example_id, source_version, role, pinned_at, source_snapshot}`；服务端由 pins 写入 |
| `reference_preset_id` | 只读投影，等于 reference_pin.example_id 或 null；不另存可编辑副本 |
| `conversation_events` | 服务端保存最近 100 条修改回执，含事件 id、delta、changed_layers、warnings、前后 workspace revision、时间；不存推理链 |
| `session_previews` | 服务端从接受的提交/run 派生 `{run_id,path,created_at}`；客户端不可任意写路径 |

source_snapshot 是钉选当时的 requirements 和兼容性声明、来源版本；不含图片字节、凭据或完整外部 notes。pin 是来源说明，草稿 requirements 才是钉选后的编辑权威。例图更新/删除/官方包换版不会回头改变草稿。`compat` 属于例图/run 来源元数据，不是模型可编辑要求。

### 3.3 Workspace 写模型与旧保存兼容

`PUT /workspaces/{id}` 沿用现有 revision 乐观锁；既有字段仍按现有整段替换。新增用户输入为可选 `mode`、`requirements_edit`、`prompt_edit`：

- requirements_edit 只含完整 layers 和 loras。规范化值变化才递增 requirements.revision，并使已有 compiled stale；不能提交 revision。
- prompt_edit 只含 positive/negative。已有 compiled 且输入仍新时才接受，生成新 compiled token、source=user；不使 stale 输入恢复有效。无 compiled 时使用 turns 首编，不能靠手改声明“已编译”。
- mode 变化使已有 compiled stale。一个请求若既改编译输入又带实际 prompt_edit，422 `invalid_workspace_edit`；用户先重编译。
- 省略所有新写字段表示保留现有会话状态；旧 UI 禁止主动填空。清除会话使用独立 reset 端点，不用 compiled=null 偷渡。
- GET 回传的 requirements/compiled/reference_pin/reference_preset_id/conversation_events 若被 round-trip 放进 PUT：只能与当前服务端存盘值深度相等，视为只读回显；不同则 422 `read_only_field`。revision 冲突优先 409；同值回显不改变 source/token。动态投影 session_previews/compile_state 可接受符合读 schema 的回显但直接丢弃，绝不存盘或据此读文件，避免后台产物到达导致旧保存失败。新 UI 只发写 DTO。
- 所有其他未知字段 extra=forbid。读存盘旧 draft_json 可忽略未知历史键，但不能让忽略字段成为写入方式。读模型与写模型必须分开。
- POST 创建只接受既有字段、mode、可选 requirements_edit；缺省 requirements=null。首次非空 delta 建立空层后更新；空 delta 且没有任何可编译要求则 422 `empty_requirements`。
- `POST /workbench/reset {workspace_id,revision}` 原子清除 requirements/compiled/pin/回执，mode 重置 faithful，升 workspace revision。保留已接受提交和产物关联；UI 有明确“重置会话”动作。历史提交不会被重置或草稿软删取消。

## 4. 编译版本与 stale

```json
{
  "positive": "charcoal drawing, ...",
  "negative": "text, watermark",
  "mode": "faithful",
  "source": "llm",
  "compiled_token": "cmp_<uuid>",
  "inputs_fingerprint": "<sha256>",
  "prompt_fingerprint": "<sha256>",
  "compiler_contract": "anima-rewrite/1"
}
```

- compiled_token 是服务端随机且不复用的版本标识。每次成功 turns、接受实际手改正负时换新；即使文本相同的重编译也换新。客户端只拷贝，不计算。
- prompt_fingerprint 仅用于内容比对/诊断，不再当并发 etag。哈希前仅 strip 正负，与实际直出一致。
- inputs_fingerprint 哈希规范化 `{requirements 内容（不含 revision）, mode, model_profile, compiler_contract}`，包括 loras 顺序、weight、trigger、层锁和 include 标志。不哈希聊天记录、预览、来源备注、seed/steps。参考内容已经复制到 requirements，无需动态查询例图。
- JSON 使用 UTF-8、sort_keys=True、separators=(",", ":")、ensure_ascii=False、allow_nan=False；数值按 DTO 统一为同一类型。指纹由后端唯一计算；GET 返回 `compile_state=missing|fresh|stale`，前端不另造浮点/JSON 哈希算法。
- 已有 compiled 且重算输入不等于存盘值即 stale；无 compiled 是 missing，不能被会话 UI 当成可提交。任何未保存的本地 requirements/mode/model_profile 修改也立即禁用会话生图。
- 用户仅改正负可以基于当前 token 提交实际编辑器文本；它不自动修改 requirements。下一轮以 requirements 为约束，当前编译稿为上下文，delta 明确提出的改动优先于未锁旧约束。无 delta 时 requirements 优先；无法协调的手改应给 warnings，不能悄悄改锁层。

工作台草稿 revision 保护写入并发；compiled_token 保护提交所基于的编译状态；两者职责不同。提交要求两者均匹配（仅 §7 定义的新会话路径），避免 seed/目标等草稿变化和相同文本 ABA 漏检。

## 5. Turns：事务外调用，事务内比较并交换

### 5.1 请求与响应

新 `POST /workbench/turns`：

```json
{
  "workspace_id": "workspace_abc", "revision": 4,
  "task": "rewrite", "mode": "faithful",
  "delta": {"kind": "user_text", "text": "再冷一点的侧光，人物不要动"},
  "compiled": {"positive": "当前编辑器英文", "negative": ""}
}
```

workspace_id/revision 必填；task 只有 rewrite；delta.text 最长 4000、可空。compiled 可省略，省略读取草稿；仅正负，不接收 token/指纹。无 requirements、reference_preset_id、rule_id、messages 或图像字段，extra=forbid。有未保存分层编辑时，UI 先保存并采用新 revision，再发送 turns。

响应包含 workspace_id、新 revision、完整 draft/compile_state、本轮 changed_layers、positive/negative/warnings、engine。正负是 draft.compiled 的展示投影，不另有一份权威。成功回执加入 conversation_events；失败只显示错误，不加入成功历史。

### 5.2 执行顺序

1. 短读取得 canonical 草稿及 revision，入口冲突 409 `workspace_revision_conflict`，无草稿 404。同 workspace 最多一个活动 turns，额外请求 429；这不代替最终 CAS。
2. 在内存副本设置 request.mode，判断 empty/stale；**此时不持久化**。无 compiled 有要求可首编；输入已变可空 delta 重编译；fresh 且无 delta 返回 422 `empty_turn`。
3. 事务外调用 LLM，timeout 120 秒。允许用户继续编辑；超时或服务端在提交前检测到请求断开时使 attempt 失效，迟到回调不得写库。已经提交的结果不能靠断开请求撤销，客户端重连先 GET 确认。v1 不另设 turns 取消按钮/API。不给 LLM 调用持有 SQLite 写锁。
4. 验证模型输出并在副本合并。短事务 BEGIN IMMEDIATE 重新检查原 revision 和 attempt 有效性；不匹配 409，整轮结果不写入。
5. 一次提交 mode、requirements、compiled、新 token、回执和 workspace revision+1。requirements 内容未变不升其 revision；成功重编译仍换 token。失败不改任何草稿字段。

刷新页面丢失 HTTP 响应后，客户端先 GET 草稿和最近回执，不自动重发收费 LLM 请求。v1 turns 不承诺客户端盲重试幂等。

### 5.3 模型输出与合并

模型只返回 touched_layers、layer_updates、positive、negative、warnings。layer_updates 是所触及层的完整**内容字段**，不含 locked/include 控制。touched_layers 无重复且集合恰等于更新键；未知层、漏字段、锁层更新、模型试图改控制字段 → 422 `invalid_layer_updates`，整轮丢弃。额外顶层 requirements/requirements_patch 等以 extra=ignore 丢弃；嵌套层 DTO 严格校验。

已有要求的首次空 delta 编译/纯重编译应返回 [] 与 {}。从空草稿提交第一句非空描述时，必须返回相应层更新，把描述写入持久要求；不能只返回提示词而保留空记忆。首次建立 requirements 的 revision 为 1。模型不能用“未声明 touched”绕过字段更新。合法内容合并也不代表自由文本正负语义必然忠实，质量约束见 §13。

非 JSON、缺 positive、空正向或上游失败 → 502 `llm_generation_failed`；timeout 使用相同 HTTP 502、details.reason=llm_timeout。不返回 Key、整段 prompt、上游原始错误。

### 5.4 SYSTEM 与 LLM 出口

REWRITE_SYSTEM + mode 指令；user JSON 仅 canonical requirements、当前正负、本轮 delta、mode。禁止发送完整聊天。user JSON/notes 是数据，不接受越权指令。

- faithful 只翻译/整理明确事实；expand 可补少量兼容细节并逐项 warnings，不自行增加主体/画师或改变画风/构图。用户 delta 明确要求的改动属于有依据的修改。
- 层文本保持用户语言；正负为英文 Danbooru 空格标签或短语。画师直接写 @name；本路径不跑 literal renderer 二次加 @。
- 局部排除不扩大为全局；无全局排除则 negative=""；不补默认质量负面。文件名不进正文，已声明 trigger 保留原文。
- notes.external_prompt 仅在例图 ingest 显式使用，工作台不自动发送整段外部笔记；不整段搬作 Anima 正文。

新增 `LLMService.complete(messages, images, disable_thinking, timeout_s, task)`，task=rewrite|ingest|probe，返回 text 与 capabilities。新 turns/ingest 唯一出站口；旧 expand_prompt 保留兼容，不改变旧请求和原型测试语义。

rewrite/probe 强制请求 disable_thinking=True；ingest 取 not settings.ingest_enable_thinking。supports_vision 默认 false、由用户设置，不按模型名猜。无法关闭推理的协议不得伪造参数；过滤展示中的推理残渣并说明限制，不宣称未产生推理费用。

OpenAI 兼容图像为 user.content 的 text + image_url data:image/jpeg;base64 部件；Ollama native 为 user.images 的 base64 列表。rewrite 的 images=None。v1 不做自动 capability probe，不要求本地模型验收；高级采样参数仍只在用户显式启用时发送。

## 6. 钉选与资源解析

### 6.1 钉选是一次复制，随后可编辑

`POST /workbench/pins {workspace_id,revision,example_id,source_version,role}`；source_version 从例图详情读取，必填。先验证来源版本，再复制冻结内容，在 workspace 短事务 CAS；若来源之后变化，本次仍使用已读取的指定版本，不混入新内容。

| role | 覆盖未锁层 |
| --- | --- |
| style | style；来源 lighting/composition 的 include_with_style_pin=true 时一并复制 |
| lighting | lighting |
| composition | composition |
| whole_scene | 全部五层，包括 subject/exclusions |

目标锁值始终保留；自动复制只替换内容，不把例图 locked 标志带进工作台。include 标志由用户管理，复制按来源标志选择覆盖，不修改目标标志。pins 不调用 LLM、不自动编译，已有 compiled 留作可见旧稿并标 stale。

v1 pin 把 loras 替换为来源 required 项；保留来源顺序，当前旧 LoRA 会被替换，UI 在执行前展示变更清单。即使只取 lighting，也可能带入该图的风格 LoRA；明确展示，不声称资源能按视觉属性精确拆分。用户可在复制后删除不想要的项再重编译。

钉选不以远端是否在线/有槽为前置条件：保存创作要求与执行检查分开。缺 LoRA/零槽时钉选成功但返回当前 availability 和不可生图原因；允许改资源或切目标。**生成提交**仍必须 422 拒绝不可执行状态，禁止后台剥离。

`DELETE /workbench/pins` 请求 `{workspace_id,revision}`：清除来源 pin，保留已经复制和手改的 requirements/LoRA，不恢复旧层。仅解除来源不使内容编译过期，但升 workspace revision。重新钉选是一次新的显式覆盖。

### 6.2 最终资源只从一个来源取

- 会话提交：只读 canonical requirements.loras。禁止动态从例图 required 列表补回；请求不得覆盖资源或 reference ID。
- 独立 preset 提交：无 workspace，必须提供 reference_preset_id + source_version；冻结该版本 required 项，可与显式 lora_selection 按 logical_id 合并、覆盖权重。空列表不能删除 preset required 项。想改依赖可先钉入草稿编辑。
- 纯直出/旧候选：无新增参考字段则保持原行为；显式资源列表按独立任务资源处理。

### 6.3 同一结果驱动 availability 与编译器

先选实际工作流（当前目录或 frozen），获取当前远端 object_info/连接 fingerprint，验证模型兼容、recipe、资源、槽位，然后输出：

```json
{
  "workflow_revision": "<digest>", "remote_fingerprint": "<digest>",
  "bindings": [{
    "logical_id": "film_grain_style", "slot_key": "12.lora_name",
    "remote_file_name": "styles/film_grain_v2.safetensors", "weight": 0.8,
    "trigger_words": ["film grain"]
  }]
}
```

优先显式资源绑定；无绑定时只允许 file_name 在对应枚举精确命中，按 requirements 顺序分配未用槽。不能猜相似文件名；重复 slot/缺枚举/槽不足拒绝。映射 UI 复用 WorkflowManager，但新增 LoRA 绑定存储：`{remote,workflow_revision,logical_id,resource_digest} → {slot_key,remote_file_name}`；resource_digest 哈希声明的 file_name/source/trigger_words，不含 weight，避免两个来源复用 logical_id 时误用旧绑定。原 node mapping 本身不代表 logical_id 绑定。

新增 `PUT /workflows/servers/{remote}/{workflow}/lora-bindings`：请求含 mapping_revision（首写 0）、workflow_revision、remote_fingerprint、bindings 完整列表；每项 logical_id/resource_digest/slot_key/remote_file_name。服务端检查工作流版本、连接指纹、槽位与实际枚举，短 CAS 更新 mapping_revision；冲突 409 mapping_revision_conflict。传 [] 明确清空绑定；响应带新版本与列表。GET 同路径用于恢复 UI。只映射已存在文件，不能写任意节点或生成新枚举名；availability 返回需要绑定的 resource_digest，前端不自行计算。

最终 job.lora_selection 使用 resolved remote_file_name 和槽位顺序；编译器不得再次用原始声明名或另一套 alias 覆盖已解析绑定。记录每个 slot 与最终文件，渲染后的节点值必须与解析结果一致。未用槽保留合法枚举文件并把 strength 归零，沿用现有行为。

availability=`ready|missing_lora|lora_unmapped|incompatible_model|incompatible_workflow`；未选目标或无法获取能力时返回 unknown + reason（如 remote_unreachable），不能当 ready。提交非 ready 返回 422 `lora_not_installed`（缺文件）或 `reference_preset_unavailable`，details 列出状态/冲突资源。非资源的连接失败沿用现有远端错误。映射修改、工作流换版、连接 fingerprint 改变都使旧绑定失效。pin 仍绑定来源时，source_snapshot.compat 的非空模型/工作流类型限制亦须检查；用户可以显式解除来源后自主使用已复制要求，不能由模型消掉兼容限制。

绑定只表示用户选择了一个远端文件，不声称文件内容与来源模型同一 SHA 或保证风格。source 中的 Civitai/HF ID 仅为元数据；不安装、不访问模型下载器。

## 7. 生图提交、幂等与执行

### 7.1 新旧请求区分

两个生图端点继续存在：`POST /direct-prompt/runs`、`POST /generation-runs`。新增 `submission_kind=legacy|conversational|reference`，默认 legacy。

| 模式 | 必需/禁止 | 兼容行为 |
| --- | --- | --- |
| legacy | 既有 payload；reference 字段不允许；可显式独立 lora_selection | 原候选 workspace_id/workspace_revision 仅元数据，不把词典候选写回 compiled；不因已有会话 compiled 要求 token |
| conversational | workspace_id、workspace_revision、compiled_token；禁止 reference_preset_id/source_version/lora_selection | canonical 草稿资源，双端点共用协议；候选正负视为显式编辑稿，必须明确进入此模式 |
| reference | 无 workspace；reference_preset_id/source_version；可 lora_selection | 独立参考版本快照，无草稿写回 |

DirectPromptSubmitRequest 新增可选 workspace_id/workspace_revision/compiled_token；GenerationSubmitRequest 已继承前两项，不重复声明。两端增加 submission_kind、资源/参考字段及可选 workflow_snapshot_run_id。prompt_fingerprint 只读，不增加为提交前置条件。

此区分保留旧原型/词典功能；legacy 不获得任何“会话要求已校验”的标记。新会话 UI 固定发 conversational，缺字段不能回退 legacy。flag 回滚后旧路径仍能用；不会自动清空新草稿。

### 7.2 不可变提交记录

新增 `generation_submissions` 放在 workspaces.db，同库承载会话 CAS 与提交接受事务；无 workspace 的新 reference/独立资源请求也使用它。纯旧任务可保留原队列协议，但幂等 key 在两个路径间必须共用入口去重，不能重复分配 run。

关键列：submission_id、唯一 idempotency_key、payload_hash、预分配 run_id（唯一）、workspace_id（nullable）、accepted_workspace_revision、snapshot_json、accepted_response_json、dispatch_state、error_code、created_at/updated_at。snapshot 不可变；dispatch_state=accepted|enqueued|failed|canceled，实际执行状态仍由 run 管理。V2 run 增加唯一 submission_id 映射或等效唯一约束。

snapshot 至少含完整 requirements（旧图允许 null）、实际 strip 后正负、mode/compiler_contract/token/inputs fingerprint、model_profile、resolved LoRA bindings、固定 workflow dump/revision、remote ID/fingerprint、generation_settings、reference 来源版本与快照、workspace 接受版本、已解析 seed。seed=-1 在接受前解析并冻结。不得包含凭据、推理链、整段外部笔记。

### 7.3 接受协议与线性化时点

1. 认证和 schema 验证后查 Idempotency-Key。相同 key + 相同规范化请求哈希返回原接受响应；不同 payload → 409 `idempotency_conflict`。必须先做此查重，再检查旧 token 是否 stale。key 全局唯一，不按端点分开；请求哈希包含端点/模式和所有语义字段（含客户端 -1 seed），不含凭据、后续随机解析 seed。
2. 读取工作台/来源，检查 conversational revision+token、fresh、请求 model_profile 与草稿一致。目标和 settings 为本次用户请求；目标能力验证不改变 requirements。事务外解析目标、凭据和资产并构造冻结计划，准备阶段不启动生图。
3. 短 BEGIN IMMEDIATE 再查 key、CAS workspace revision+token、检查未接受队列容量与关闭状态。目标/映射配置版本由短生命周期校验票据绑定；若提交前已变化则拒绝重新准备，不静默换目标。需要跨存储读取的配置不假称与 workspace 原子；执行前仍须验证票据。
4. 同一事务插入不可变 submission + 202 接受响应 + workspace 必要变更：正负实际不同才写 source=user、换 token、升 workspace revision。正文相同则保持 compiled/token/revision。这里是**接受时点**。没有网络调用、没有远端执行。
5. 提交事务后唤醒 dispatcher；dispatcher 以预分配 run_id/submission_id 幂等落入原队列，消费已冻结计划，不再次根据当前草稿/例图编译。持久 run 存在后标 enqueued。

202 保留现有 GenerationRun 响应的 id（即 run_id）/state 等字段，新路径增加 submission_id；conversational 另带 workspace_id、接受时 workspace_revision 和 compiled_token。不把 id 改名为 run_id。重试返回原接受回执，不套入后来草稿的新版本；UI 遇到旧回执不得倒退本地 revision，必要时 GET 草稿。run 列表/详情从接受记录与实际 run 合并投影；尚未交给 dispatcher 时对外 state=draft、status_message=已接受，等待入队，不出现短暂 404；沿用现有 draft→connecting 等执行状态。

本次请求使用请求体实际正负；手改是用户授权，不要求正文哈希等于旧 compiled。stale 输入、旧版本/token、缺资源仍禁止接受。接受后即使 workspace 被编辑、重置或软删，该任务仍执行冻结版本。

### 7.4 恢复、容量与失败

- 重启扫描 accepted：同 submission_id 已有 run 则关联，不重复执行；没有则按同 run_id 交付。崩溃发生在队列持久化与标记 enqueued 之间也只产生一个 run。
- 容量检查计入所有尚未完成的新提交（包括 accepted 和队列中的任务），在接受前拒绝超限，不以未交付任务无限扩充队列。旧队列与新协调层共享容量预算。
- 接受前失败不改草稿、不新建任务；接受后 dispatcher 永久失败则持久 failed，run 投影显示错误，接受回执仍成立。草稿不回滚到旧版本；不会用后续草稿重试旧任务。
- 在远端发送前复验远端 fingerprint 与冻结资产；改变/文件缺失 → 明确失败，不静默换文件。远端行为与本地事务无法原子化：远端可能已接受但响应丢失时对外 state=failed、error.code=generation_execution_uncertain，提示“执行结果待确认”，只提供能查询已知 remote prompt ID 的恢复动作。没有 ID 时要求用户检查远端，不展示会重复采样的自动重试动作。
- 取消已接受任务沿用显式 run actions；取消与 dispatch 以持久状态 CAS 仲裁。不能靠删草稿取消任务。
- Idempotency-Key 的任务关联随任务持久保存；删除可见履历保留 key/run_id/payload_hash 墓碑，不能释放 key 造成重试重复生图。

### 7.5 同工作流重放

只有显式“按原工作流再来一张”填写 workflow_snapshot_run_id。引用的是 generation_run_id，不是 workflow_profile_id。从提交/run 获取冻结工作流；缺失 → 422 workflow_snapshot_missing，不猜其他模板。

必须**先选择旧 dump，再对这个 dump**验证当前远端资产/兼容性/槽位；不能先用当前目录槽数验证再换 frozen。请求 workflow_profile_id 与 dump.id 不同 → 422 workflow_incompatible。目录同 ID 换版不阻止旧 dump 验证，资产已不可用则明确失败。新 run 再冻结该 dump；正负、recipe、seed 使用当前请求，资源来自本次模式的权威列表。

仅服务端证实自家 Anima run 的例图展示重放按钮；外部上传即使 sidecar 带 run 字符串也不能伪造来源身份。普通钉选不自动重放。

## 8. 参考库、官方包与编辑

### 8.1 存储

桌面 `app_data/v3/examples.db`，开发 `.local/state/examples.db`，与 workspaces.db 并列；媒体 `example-media/{id}/original.*`。官方包只读 overlay，安装不写用户库。

`examples`：id(ex_<hex>)、title、origin(upload|session_pin|gallery_keep|grok_dump)、origin_ref、image_relpath、requirements_json(nullable)、notes_json(external_prompt,user_notes,source_url)、compat_json(model_profiles,workflow_kinds,workflow_snapshot_ref)、provenance_json(nullable，服务端核实的 run_id/实际正负/生成快照摘要)、revision、ingest_state(none|pending|ready|failed)、ingest_attempt_id、ingest_error_code、created_at/updated_at/deleted_at。

`example_files`：example_id、sha256、byte_size、width、height。requirements_json 是资源唯一副本，不另存 loras_json。notes/compat 各自单份；vision 不写 compat。

`official_example_overrides`：official_id（稳定 off_ ID）、revision、notes_json、updated_at。仅存用户备注，不覆盖官方 requirements/media；不创建缺图的伪 examples 行。用户想修改官方要求时“复制为我的例图”，复制完整文件与元数据后获得 ex_ ID。

source_version 是服务端内容版本：用户例图为不可复用 edit revision；官方为 pack_id + catalog 条目摘要。source_version 用于钉选/独立 reference 提交 CAS。官方备注版本独立，不改变其视觉规格；旧包移除后的备注仍保留，条目恢复时可重新显示。

requirements_valid 是从 schema 校验派生的布尔值，与 ingest_state 独立。ready 表示最近成功 ingest；failed 可以仍有旧合法 requirements。可钉选依据 requirements_valid，不能以 failed 一概禁止。手填合法层无需 vision 即可钉选。

### 8.2 CRUD / 媒体合同

所有写请求要求 X-Anima-Session + Origin，extra=forbid；revision 冲突 409 example_revision_conflict，已删除按 404。

| 方法 | 路径与请求 |
| --- | --- |
| GET | `/reference-examples`：q/origin/limit/cursor；limit 默认 40、最多 100；返回 source_version、revision、requirements_valid、official_pack |
| POST | `/reference-examples`：multipart file + title + 可选 metadata JSON 文本字段；只接受字节；metadata 只允许 notes、requirements_edit、声明的兼容模型/类型，不允许运行身份 |
| GET | `/reference-examples/{id}`：完整用户可见元数据，不含绝对路径/凭据 |
| PATCH | `/reference-examples/{id}`：revision + 可选 title/notes/requirements_edit/声明兼容性；省略保留；revision 仅比较，不用于赋值；禁止客户端改 origin、run ref、provenance 或 ingest 状态 |
| DELETE | `/reference-examples/{id}`：revision，软删；媒体清理独立，不影响已冻结草稿/run |
| PATCH | `/reference-examples/{off_id}/notes`：override_revision（首写 0）+ 完整 notes；仅改覆盖行 |
| POST | `/reference-examples/{off_id}/copy`：source_version；复制到用户库，返回 ex_ ID |
| POST | `/reference-examples/from-gallery`：path，受 gallery 根目录授权；复制元数据和文件 |
| POST | `/reference-examples/from-run`：run_id、path；path 必须属于该 run 的 artifacts |
| GET | `/reference-examples/{id}/content`、`/thumbnail`：只访问已登记媒体 |

列表游标绑定查询与排序 `(updated_at,id)`；官方记录使用包中的稳定时间。不承诺跨编辑的列表快照，前端按 id 去重；单次详情/钉选用版本防并发。媒体缩略图键包含 id+媒体 SHA+尺寸，不能仅 id 防止旧缓存。原图不暴露本机路径；若 img cookie 使用专用前缀限定，不能扩大到全部 /api/v3。

上传限制：请求 file ≤20MB，允许 PNG/JPEG/WebP 静态图；验证 MIME 与实际解码，限制解码总像素≤40MP，拒绝动画/解压炸弹。先临时文件、验证/转码成功，再原子移动并写元数据；失败清理临时文件，重启清理未登记孤儿。EXIF 定向后为 ingest 转 JPEG，最长边 2048、quality 85；原始收藏文件保留，不以转码图覆盖。

路径验证基于 resolve 后实际根目录，拒绝 ..、绝对路径、越界链接/reparse 目标，不只字符串检查。from-run/from-gallery 复制前复验仍可读，历史删除竞态返回明确 404；不得登记空壳。

### 8.3 从产物收藏必须对应生成当时

from-run 从不可变提交快照取得 requirements、实际正负、LoRA 和 workflow_snapshot_ref，不读取当前草稿。from-gallery 只有能通过服务端 manifest/artifact 关系证实 run 身份时复用相同快照，否则 requirements=null，仅保存可核实元数据和 notes，允许手填/ingest。

例图的实际生成提示词作为 provenance 元数据（只读，来源 run）；上传的外部提示词归 notes.external_prompt，不能冒充 Anima 正文。草稿已删除、继续编辑、模型运行期间改要求均不影响收藏结果。

### 8.4 官方例图包

`anima-v3-examples/1`：examples-pack.json(pack_id/generated_at/counts/各文件 path,size,sha256)、catalog.json、NOTICE.txt、LICENSES/、media/{off_id}/original.webp。catalog 条目含稳定 off_ ID、title、requirements、compat、media；LoRA 只在 requirements 内，不重复声明。

源目录 `v3/src/anima_prompt_studio_v3/data/official-examples/`；安装到 app_data/v3/official-examples/{pack_id}/，用 current.json 原子指针切换，不覆盖正在使用的目录。校验 manifest/数量/schema/路径/哈希后启用，失败保留旧包。安装、升级、卸载不删除 overrides 用户行；已钉选工作台有冻结规格，仍可编辑/提交。

GET 列表合并用户与官方，off_ 与 ex_ 分轨；official_pack={id,ready,count}，未装或校验失败 ready=false、count 可省略，用户库仍可用。官方区不能把包缺失伪装为空成功。官方卡无软删/直接编辑/重新 ingest；复制为用户条目后可改。官方 required LoRA 不随包安装，提交仍检查实际资源。

## 9. 提示词提取与可选读图分析的版本与恢复

`POST /reference-examples/{id}/ingest {revision,source,use_external_prompt_notes}`，只支持用户条目。source 为 image（省略时兼容旧调用）或 prompt。界面优先提供提示词提取，读图分析折叠为可选能力。请求无 enable_thinking；额外字段 422。两种来源共用最多 1 个活动分析，第二个返回 429 rate_limited。仅 image 检查 supports_vision，false 时立即 422 vision_unsupported。

按用户 2026-09-10 的方向调整，prompt 模式只分析已保存 notes.external_prompt，不读取或发送图像，不需要视觉模型。空文本返回 422 reference_prompt_required，不创建 pending；未保存笔记必须先保存。正负提示词需要清楚区分，局部排除保持作用对象；未提及的内容不补全。来源文本作为数据处理，不能控制合同或自动添加 LoRA/画师；资源与作者标签通过 warnings 提醒人工确认，已确认元数据保留。prompt_ingest 强制关闭思考，不受视觉分析思考开关影响。

成功后记录服务端 analysis_source=image/prompt，刷新后仍可显示“上次分析来源”；手改后的要求不能因此声称未经修改。提示词分析明确提示未核对图片，其首次要求不自动开启光线/构图随风格钉选。失败保留上次成功的来源和要求。读图质量保持单独的实验性评测，不再作为文字提取流程的必经步骤；文字提取自身仍需真实语义验收，不能拿 JSON 合法代替保真。

1. CAS revision，分配 ingest_attempt_id、保存输入 revision/hash、冻结图/notes/现有 requirements，设 pending 并升 example revision。短事务结束后再解码/调用 LLM。settings.ingest_enable_thinking 默认 false，超时 120 秒。
2. INGEST_SYSTEM 只返回五层内容建议和 warnings；lighting/composition 可建议 include 标志，仅首次空 requirements 时初始化；已有 locked/include 控制保留。artists 从已确认元数据复制，不信任视觉猜测；loras/compat 从已存元数据复制，模型输出这些字段一律丢弃。
3. 结果写回 CAS pending revision + attempt ID + 未删除；保留所有锁层原值，合并未锁层，完整 schema 校验。成功一次提交 requirements、ready、清错和 revision+1；requirements 内容变化才升其内部 revision。
4. 用户 pending 期间 PATCH/DELETE 会使 attempt 失效，PATCH 结束 pending（设 none）并保留旧合法 JSON；迟到结果 409 ingest_superseded，不覆盖手改。其他重入依然受全局限流。
5. 当前 attempt 失败写 failed/error_code、升 revision、保留旧 requirements。重启把残留 pending 收敛为 failed/ingest_interrupted，保留合法旧结果。不得自动再调用收费模型。

INGEST 输出只作为描述初稿：层文本用用户语言；notes 未授权不发送；授权且非空时 warnings 说明外部提示词仅作线索。成功返回完整例图草稿、warnings、新 revision，不修改 workspace。UI 在失败但有旧结果时显示“分析失败，仍可使用上次要求”。

## 10. 工作台交互与产物

默认流程是 delta 输入 + faithful/expand + 本轮变更摘要 + 正负编辑器 + 显式生图按钮。requirements 五层（含排除）和 LoRA/高级生成设置按需展开；不要求用户每轮维护所有字段。编译稿仍可见，折叠面板有 stale/锁层/缺资源摘要。

- 初次输入占位“描述你想画的内容”，已有要求后为“继续追加要求”。“发送修改”可带 delta；“重新编译”是空 delta 动作，不暗含生图。
- 本轮显示哪些层变化、哪些锁层保留、扩写补充和 warnings。修改回执最近 100 条随草稿恢复；不构建完整聊天上下文，不声称无限历史/自动撤销。
- LoRA 芯片可删除/改权重，保存后 stale；来源卡标注“已编辑”，删除不会被下次提交加回。来源卡解除保留已复制内容，按钮说明清楚。
- 生图禁用条件：missing/stale、未保存编译输入、空正向、目标不可执行。按钮请求始终 conversational，并使用最新 workspace revision/token。正负可带尚未单独保存的手改。
- 一次读取旧响应不能倒退新状态；409 拉取服务端版本并保留用户尚未提交的文本供人工合并，不自动覆盖输入。
- pin 前显示预计覆盖层及 LoRA 替换；已锁层保留。没有可用远端也允许收藏、分析和编辑。

`GET /generation-runs/{id}/artifacts` 返回 `{items:[{id,path,content_url,thumbnail_url}]}`，path 为输出根内画廊相对路径。run 存在但产物未下载时 items=[]，run 仍非 completed；missing run 才 404。复用 GET /gallery/assets/content 和 thumbnail，不新建历史缩略图缓存。

服务端用 submission.workspace_id 关联本轮任务，刷新页面后仍能找回运行中任务；完成后派生 session_previews，不依赖浏览器记住 run_id 才登记。GET /workspaces/{id}/runs 支持 cursor/limit，未完成优先；预览只分页取最近产物，避免把无限列表写进 draft_json。

workspace 软删后工作台预览入口消失，但 submission/run 仍保留且历史可访问。产物被历史回收时胶片显示已移除状态，不提供失效缩略图假成功。

## 11. 预设投影与 API 总表

`reference_preset_id` 是例图 ID（ex_ 或 off_），与 mode/rule_id、generation_settings.preset_id 分开。旧 `/workbench/prompt` 永不新增 reference_preset_id；合并只在 pins，改写只在 turns。

`GET /reference-presets` 支持 q/model_profile/workflow_kind/availability/limit/cursor，v1 无 category；响应 catalog_version=anima-ref-1，条目 source_version、id/title/source、风格/光影/构图骨架、兼容性、LoRA、availability。无 few-shot 和整段 external_prompt，可有 has_external_notes。GET /reference-presets/{id} 与 /{id}/availability 使用同一 source_version，availability 查询可带当前 remote_profile_id/workflow_profile_id/model_profile/workflow_snapshot_run_id；版本变化返回冲突而非混合结果。

工作台 actual availability 用 `GET /workbench/availability?workspace_id=...&revision=...&remote_profile_id=...&workflow_profile_id=...`（可 workflow_snapshot_run_id），检查草稿资源，不用原例图 availability 替代。只有 submit 的重新解析是最终执行门闩，GET 成功不是远端资源永不变化的保证。

新增路由汇总：turns、pins POST/DELETE、reset、workbench/availability、workspaces/{id}/runs、generation-runs/{id}/artifacts；reference-examples CRUD/from-gallery/from-run/content/thumbnail/ingest/off notes/copy；reference-presets 列表/详情/availability；workflows/servers/{remote}/{workflow}/lora-bindings GET/PUT。具体请求见各节。写端点统一会话/Origin；未注册 404 not_found，已注册但 flag 关可供测试返回真实数据，不伪造目录成功。

错误增量：empty_turn、empty_requirements、invalid_layer_updates、invalid_workspace_edit、read_only_field、stale_compiled_prompt、example_revision_conflict、reference_version_conflict、ingest_superseded、vision_unsupported、workflow_snapshot_missing、idempotency_conflict、mapping_revision_conflict。workspace revision 冲突 409；token 不匹配/inputs stale 422 stale_compiled_prompt；例图/来源/幂等/attempt/映射冲突 409；模型/timeout 502。generation_execution_uncertain 是已接受 run 的状态错误，不将其追溯成提交 HTTP 失败。沿用缺资源、工作流、认证等既有错误族，详情不含绝对路径或秘密。

## 12. 存储、安全、可观测性

| 存储 | 所有内容 |
| --- | --- |
| reference.db | 只读标签/画师；不写用户钉选 |
| workspaces.db | 既有草稿、会话读写状态、有限回执、generation_submissions |
| examples.db / example-media | 用户参考条目、官方备注覆盖、复制媒体 |
| official-examples | 只读版本包与 current.json |
| 现有 V2/V3 runtime 存储和输出 | run/job/artifacts；唯一 submission 映射与冻结生成快照 |
| prompt-assistant 配置 | LLM Key、supports_vision、ingest_enable_thinking 等；不复制进任务 |

迁移只新增字段/表/索引，不重写既有历史。已存在会话数据版本不识别时明确报兼容错误，不默认重置为空。flag 回滚是 UI 回滚，不能停掉 accepted dispatcher 或破坏恢复能力。

服务端日志不记录完整 delta/requirements/prompt/图像/base64/Key/绝对路径；持久业务快照可含创作内容，用于本机恢复，与日志分开。错误不可回显 Bearer。保留既有 NSFW 设置；不扩充本机文件读取权限。

日志：turn workspace_id/mode/attempt/latency/error/changed_layers；ingest example_id/attempt/settings flags/原始及转码字节/latency/error；submission/run_id/dispatch_state/has_reference/lora_count/availability；artifacts item_count。统计解析失败、版本冲突、收费调用次数、dispatch 积压；媒体体积软上限只提示，不静默删收藏。

## 13. 验收：确定性合同与模型质量分开

### 13.1 必须通过的确定性反例

| 编号 | 用例与通过条件 |
| --- | --- |
| T01 | 旧 prompt/直出/词典测试保持原语义；无 compiled 的 legacy workspace 候选仍合法 |
| T02 | 旧保存省略新键不清会话；GET 同值回显不改变 source/token；伪造 server 字段拒绝 |
| T03 | 慢 LLM 不持写锁；期间保存导致回写 409；失败不持久化 mode/半截结果 |
| T04 | 锁层更新、控制字段篡改、层键不匹配整轮拒绝；纯重编译不改要求 |
| T05 | LoRA 权重变而正负相同、P→Q→P 后旧 token 提交拒绝 |
| T06 | 删除 LoRA 后重编译，实际任务不含该项；来源更新/删除不影响已钉草稿 |
| T07 | 模拟 BEGIN 提交前失败、接受后交付前崩溃、落 run 后标记前崩溃；每 key 一个 run |
| T08 | 丢 202 后同 payload 重试返回原回执；不同 payload 同 key 409；回执不倒退 UI |
| T09 | 接受后编辑/重置/删草稿不改变任务快照；旧图收藏仍匹配生成时要求和实际正负 |
| T10 | 远端子目录/重命名/多槽映射：最终发送节点与 resolved binding 完全相同 |
| T11 | 同 ID 工作流换版后重放验证旧 dump；缺文件明确失败；外部图不可伪造重放 |
| T12 | ingest 期间编辑/删除、迟到结果、重启 pending；不覆盖手改/锁层，保留旧合法结果 |
| T13 | 上传超限/解码超限/越界路径/复制删除竞态拒绝；原图回收不损坏已复制收藏 |
| T14 | 官方缺包诚实显示；更新不删备注；官方复制可编辑；ex_/off_ 投影可钉选 |
| T15 | 刷新恢复运行中胶片；队列容量含 accepted；取消与 dispatch 竞态不重复执行 |
| T16 | OpenAI/Ollama 视觉消息形状、thinking 设置隔离；supports_vision=false 不调用模型 |

上述测试用 fake LLM/远端和故障注入证明协议；不把这些测试冒充真实生成质量。恢复必须包含进程重启和持久库重新打开，不能只测内存 mock。

### 13.2 云端模型最低评测

模型选择以质量优先（用户 2026-09-10 补充）：套餐内可比较较贵模型，不因少量 token 成本固定使用廉价候选。固定合同和同一组场景初筛；候选反复违反硬约束时优先换模型，不为单个模型堆叠特殊提示规则。接口不兼容和未完成响应与语义失败分别记录；初筛胜出仍需完成下述验收，不能直接当作默认发布质量通过。

使用已配置 API LLM，记录实际模型 ID、设置、SYSTEM/合同版本和失败记录；不测本地 4B。五个场景均跑三次 rewrite 调用并独立重复三次，共至少 45 个 turn；ingest、手改、锁层是轮间准备动作，不抵扣 rewrite 次数。每轮审阅 requirements 与正负，不能仅看 JSON 合法。

| 场景 | 三轮要求 | 必须保留 |
| --- | --- | --- |
| 黑白侦探 | 锁主体 → 改冷侧光 → 改为半身 | 一人、短发、风衣、右手信；不得自发换人物 |
| 双人帽子 | 左不戴右戴 → 改光线 → 改背景 | 左右关系与帽子作用对象；negative 不全局禁止 hat |
| 木刻交接包裹 | 明确两人和木刻 → 加逆光 → expand | 数量、动作、媒介；新增细节有 warnings |
| 炭笔参考 | ingest/style pin 准备后首编 → 改侧光 → 删除风格 LoRA 后重编译 | 不复制参考主体；删除资源不回来；不臆造作者 |
| 手改英文 | 首编 → 手改局部 tag 后 delta 改光线 → delta 改背景 | 手改上下文被考虑；与锁层冲突明确提示，不静默覆盖要求 |

每条注明预期事实、禁止事实、实际正负和人工判定。数量/身份/局部排除/锁层/未声明画师任一硬约束失败，该模型配置不得通过忠实模式验收；修正 SYSTEM 后重跑完整对应套件，不删除失败样本挑成功结果。可确定检查的 artists allowlist、声明 trigger、资源字段独立验证；不另建大型中文语义引擎。

风格效果另测：至少 3 张官方例图、每张 2 个固定 seed，对照手写英文基准与本工作台输出（至少 12 张生成图，6 张基准+6 张工作台）；固定模型、工作流、LoRA、recipe、尺寸。分别记录参考描述、提示词保真和实际图的媒介/光影/构图；官方冻结要求与另行 ingest 的描述分开记录。六张工作台测试图每项按 0=不符、1=部分符合、2=符合评分：无主体硬约束错误、各维度均分≥1，且与手写基准均分差不超过 0.5，才作为 v1 最低可用证据。评分是人工产品验收，不宣称普适模型质量或精确复刻。

锁层的结构保护可由代码保证，自由文本及成图的语义保真仍有模型限制；UI 保留显式审阅。未通过实际评测只能称协议实现完成，不称产品验收完成。

## 14. 实施顺序与发布门槛

合同先于实现，本版同步 ADR-025/API，不再把正式合同修订排到末尾。

| PR | 内容 | 依赖 |
| --- | --- | --- |
| 1 | DTO/所有权/规范化/flags；requirements merge 与 token；迁移和旧保存兼容 | 本版合同 |
| 2 | complete()、settings、thinking 与视觉消息测试 | 1 的接口约定 |
| 3 | workspace-backed turns、短事务 CAS、回执、reset、错误语义 | 1、2 |
| 4 | 最终目标/资源 binding resolver 与编译器统一；frozen 验证 | 1 |
| 5 | 不可变 submission、队列唯一映射、双提交模式、幂等/容量/恢复 | 1、4 |
| 6 | 会话 UI、分层编辑、版本提交、变更摘要 | 3、5 |
| 7 | artifacts、workspace runs、刷新恢复胶片、run 快照收藏基础 | 5 |
| 8 | examples CRUD/媒体/版本/官方 overrides、from-run/gallery | 1、7 |
| 9 | vision ingest、attempt CAS、锁层与恢复 | 2、8 |
| 10 | pins/unpin、presets 投影、workspace availability、映射引导 | 3、4、8 |
| 11 | 官方包安装/overlay/NOTICE 与少量真实策展样本 | 8 |
| 12 | 参考 UI、收藏/重放按钮、端到端反例与真实云端评测 | 6–11 |

flags：llm_prompt_prototype 保留；conversational_workbench/reference_gallery 默认 false。内部集成测试可以按依赖打开；面向用户默认开启及 v1 发布必须 PR-12 完成、T01–T16 通过、官方包就绪、云端质量评测通过。没有 lora_installer 或 auto_generate flag。

回滚关闭新 UI，不删旧 `/workbench/prompt`，不丢会话数据；已接受提交继续恢复/执行或由用户显式取消。发布说明区分协议完成、模型质量结果和剩余限制。

## 15. 审计问题闭合映射

| 初稿问题 | 本版修订位置 |
| --- | --- |
| F1 草稿/例图资源多权威 | §3、§6：冻结 pin，草稿资源唯一，显式删资源 |
| F2 文本哈希 ABA | §4、§7：不可复用 token + workspace revision |
| F3 队列/草稿竞态与幂等 | §7：同库接受事务、持久交付、唯一 run、重试先查 |
| F4 turns 提前持久化 | §5：内存 mode、事务外 LLM、结果 CAS |
| F5 收藏旧图错配 | §7.2、§8.3：完整不可变生成快照 |
| F6 映射被覆盖 | §6.3：显式 binding、同结果验证与渲染 |
| F7 frozen 校验错对象 | §7.5：先选执行 dump 再验证 |
| F8 ingest 并发/锁层 | §9：attempt/version、控制字段所有权、失败保留 |
| F9 写接口/字段权限 | §3.3、§8.2：独立写 DTO、CRUD、官方备注覆盖 |
| F10 质量验收不足 | §13：确定性反例、45 turn、多维固定 seed 对照 |

“设计问题已给出修订合同”不等于“对应实现或模型质量已通过”。后续实现发现需要改合同，应同步修改本文、API 合同和相关测试；不得靠前端特判偷偷改变资源或版本语义。
