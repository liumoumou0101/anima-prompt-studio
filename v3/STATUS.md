# V3 开发状态

当前开发版本：`0.1.0`（工作流级生成配方与参数能力契约）

更新日期：2026-09-10

## 会话工作台实施进展（2026-09-10）

### 当前结论

最高优先级方向更新（2026-09-11）：已进入全模型生图效果优化阶段，不限 Aesthetic。用户担心 V2 自身的旧预设/隐式处理被继承，要求不再以旧代码正确为前提；允许按证据重写整个生图管线。下一轮从作者原始说明与独立 ComfyUI 基线验证全部模型，审计所有默认/预设/提示词/资源/后处理来源，同时优化准备阶段延迟。旧新图一致只能证明一致性，不能证明质量。见 [全模型效果计划及对照图](../docs/v3/GENERATION_QUALITY_PHASE_20260911.md)；这条方向优先于下方历史功能收尾安排。

提交前验证（2026-09-11）：V3 全量 440 项通过，0 失败/错误/跳过；alpha.2 前端最近 76 项及正式构建通过，V2 全量已通过。本地 `.local/`、安装包、凭据和用户参考素材未加入代码提交。当前成果与未解决问题随 feature/llm-workbench 交接。

下一轮开发重点（2026-09-11）：用户人工测试反馈“提交前准备阶段比生图还慢”及“Aesthetic 多次普遍不如 Turbo”。均未解决，不能以任务后来成功或旧新节点图一致判为排除。下一轮分别追踪准备阶段耗时、核验 Aesthetic 配套资源与作者参考工作流；连接复用/预检提前和实验图标注、大 seed 精度随后处理。完整成果、证据、限制和继续开发顺序见 [9 月 11 日交接](../docs/v3/SESSION_HANDOFF_2026-09-11.md)。本次只提交现有实现与问题记录，不做正式发布。

人工测试修复（2026-09-10，alpha.2）：LLM 设置增加服务商模型目录刷新、名称搜索、下拉选择及手动 ID 输入。真实 OpenCode 已刷新 36 个模型，当前选择保持不变；仅目录读取，没有 LLM/GPU 生成。保留模型参数和自定义模型，未保存地址/Key 禁止刷新，失败不覆盖旧配置。前端 76 项与正式构建通过，相关后端回归通过。详见 [模型选择修复](../docs/v3/audits/2026-09-09-conversational-workbench/LLM_MODEL_PICKER_20260910.md)。

人工测试交接就绪（2026-09-10）：Setup 已实际编译并通过安装、安装后网页/API、同版本覆盖安装、卸载与外部数据库哈希保留检查。冻结 EXE 完整运行时已通过真实远端 1 张生图与下载、回执重放，产物 768×1024 和哈希一致；结束队列 running=0/pending=0。最新 V3 全量 436 项通过，V2 全量回归通过，前端最近全量 74 项及构建通过。静态基准 v1.1 保留率 8/8、泄漏和验证错误为 0；修正了无合格推荐时强求 conservative lane 的旧套件假失败，原报告保留。便携与 Setup 产物、校验和及人工说明位于 release/，未对外发布或提交 Git。接下来由用户人工测试，不再扩展模型试验。详见 [交接验收](../docs/v3/audits/2026-09-09-conversational-workbench/RELEASE_HANDOFF_20260910.md) 与 [人工测试步骤](../docs/v3/MANUAL_TEST_20260910.md)。下方待构建/待安装验收描述均为本轮之前的历史记录。

最新发行验收（2026-09-10）：实际 Windows 便携版已构建，约 287 MB。EXE 内置样例安装、首次启动、重复启动时数据包/样例指针和参考数据库哈希保留通过；额外真实 HTTP 检查了打包网页资源、参考安装、缩略图、笔记与工作台进程重启恢复。全程隔离目录、无 LLM/GPU。本机无 Inno Setup，Setup 安装/卸载和打包环境远端执行尚未复测；未对外发布。详见 [Windows 便携版验收](../docs/v3/audits/2026-09-09-conversational-workbench/WINDOWS_PORTABLE_20260910.md)。这条更新取代下方历史“未构建实际 EXE”的状态。

质量取舍确认（2026-09-10）：用户确认继续采用非思考模式，不以最强模型为使用前提。文字提取允许少量可人工修正的细节遗漏或术语偏差，不再追求零遗漏、反复堆特判。数量、身份、否定关系等关键语义仍单独记录；确定性的锁层、保存、幂等与恢复缺陷仍需修复。下一步推进发行构建与启动验证，历史模型失败记录不改判。

产品定位确认（2026-09-10）：用户明确读图仅作参考，不适合主力。主流程以原始提示词提取和人工编辑为准；视觉质量改进降为可选后续，不再作为主流程收尾的阻塞项。界面入口改为“辅助：读图建议”，说明未锁层更新与核对要求，完成反馈始终保留“仅供参考”。不改变调用、锁层与恢复协议；下一优先项是文字提取遗漏。

最新功能收尾（2026-09-10）：参考收藏新增“安装内置样例”，把已随发行携带的三图包接到实际操作入口。后端严格空对象、会话校验、固定源、进程内串行安装；已有有效官方包直接保留，错误不回显路径。界面安装后刷新，保留正在编辑的参考笔记，失败可以重试。新增真实内置包 API/个人备注保留/认证/失败测试及前端显式安装回归。V3 后端全量 435 项、前端全量 74 项通过，TypeScript 与正式构建通过；没有新增 LLM/GPU 调用。本轮接口经真实临时库测试，未重复浏览器视觉验收或实际 Windows EXE 构建。使用时重启项目启动器加载新接口。

最新界面收尾（2026-09-10）：经典工作台新增“试用会话创作”入口，低频设置默认折叠；会话页整理为对话与画面工作区，提示词、五层要求、生成设置使用支持键盘切换的页签，补齐复制反馈、初始想法入口和生成不可用原因。统一导航图标、间距与窄屏布局。修复旧记录缺少生成设置、后端 JSON 字段排序导致的“未保存”误报，以及修改非尺寸参数误改画幅的问题。前端全量 72 项、类型检查与正式构建通过；桌面和 390px 窄屏浏览器已检查，实际保存/刷新恢复通过。未追加 LLM/GPU 调用，默认发布 flags 保持不变。详见 [工作台界面验收](../docs/v3/audits/2026-09-09-conversational-workbench/WORKBENCH_UI_20260910.md)。

最新开发决策与实现（2026-09-10）：用户明确成图测试用于确定 ANIMA 的描述执行边界，并授权继续开发。基础主体、服装、场景和常见动作具备可用性；精确手势/局部绑定/裁切仍不稳定。提示词正确而成图偏差不再阻止功能开发，历史质量失败保留；编译遗漏、锁层/持久化/重试错误仍按软件缺陷处理。当前已补齐官方三图包的 sdist/wheel 携带、Windows 资源配置和显式内置安装命令（保留个人备注、正常启动不替换激活包）。V3 全量 433 项通过，新增 6 项含实际 sdist → wheel → 脱离项目目录安装，最后构建路径加固后 6 项复测通过；PowerShell 语法及 diff 检查通过。Windows EXE 资源与 smoke 已接线，本机缺少 PyInstaller，尚未构建/运行实际新 EXE。下一步继续可用版本的入口与操作闭环收尾，不再反复扩展成图试验或为模型动作偏差堆叠提示词特判。默认模型与发布 flags 未改。

新增多风格测试接续（2026-09-10）：从原会话本地记录恢复“四风格 × 三模型”的 12 张二次元成图，全部图片哈希/尺寸、接受快照、同风格提示词一致性及同模型冻结工作流核验通过；没有重复调用。固定 Qwen3.7-Max，比较 Aesthetic v1.1、AnimaYume v1.0 Final、MiaoMiao v1.6 各自基线配方。已整理逐图视觉复核：MiaoMiao 细节更精致，Yume 复古感突出，Aesthetic 水彩质感较强；手势、帽尖裁切等要求仍有偏差，单 seed 不能作总体排名或发布通过依据。详见 [多风格测试](../docs/v3/audits/2026-09-09-conversational-workbench/ANIME_STYLES_20260910.md)，本机完整图文在 `.local/conversation-acceptance/anime-styles-20260910/REVIEW.md`。

最新本机接续（2026-09-10 晚）：优云网络恢复，RTX 3080 Ti 的固定 seed 12 张成图对照已完成，下载/哈希/尺寸、6 对参数与要求一致、12 个冻结工作流一致、同 key 回执重放均通过；结束时云端队列为空，已告知用户可关机。**成图质量未通过**：两张工作台木刻图漏掉挤奶人物，炭笔朝向与水彩小人物也有未确认项。三维均分虽达最低数值条件，主体硬约束仍阻止发布，flags 不变。旧机器本地计划未迁移，本轮从官方人工要求重建三组基准与 Qwen3.7-Max 输出。详见 [12 张成图对照](../docs/v3/audits/2026-09-09-conversational-workbench/IMAGE_COMPARISON_20260910.md)。本机原图/接受快照/评分位于 `.local/conversation-acceptance/20260910-local/`，不随 Git 同步。下一步是固定条件下排查提示词组织与主体动作遗漏，不再把网络作为当前阻塞。下段“尚未提交生图”是上一机器交接时的历史状态。

交接状态（2026-09-10）：本次提交前重新验证后端 427 项、前端 68 项测试通过，TypeScript 与生产构建通过。下一步是实际成图对照：木刻、炭笔、水彩三类，各用 seed 20260910 / 20260911，对比人工基线与工作台提示词，共 12 张；本轮尚未提交生图。云主机内部 ComfyUI 和 GPU 正常，公网 SSH、ComfyUI 和文件管理入口访问异常，待更换网络后重试或换云平台。不要将此次网络阻塞计为生成或模型质量失败。临时评测报告、冻结提示词计划和执行脚本保留在本机 `.local/conversation-acceptance/`，不随 Git 同步；换电脑测试需重新准备或单独迁移这些测试文件，API Key、SSH 凭据及本地数据库也不随 Git 同步。发布 flags 继续关闭。

最新重复验收：Qwen3.7-Max 固定规则完成五场景各三轮、独立三组，共 45 次 rewrite，全部结构/恢复通过，改写核心要求人工复核通过；单轮约 3～8 秒。炭笔参考另三次 prompt ingest 中一次漏掉“单色”，该组继承了不完整要求，整条参考流程仍不通过。新增 charcoal 提取/pin/删测试 LoRA 场景；无 GPU，默认模型未改。详见 [45 轮重复验证](../docs/v3/audits/2026-09-09-conversational-workbench/QWEN37_REPEATED_ACCEPTANCE.md)。

最新选型：按用户“质量优先、不死磕单模型”的方向，冻结规则比较四个候选。Qwen3.8-Max 漏逆光、MiMo-V2.5-Pro 漏排线，暂不推荐；Kimi-K2.6 首轮返回不完整，未评语义。Qwen3.7-Max 木刻扩写、双人帽子、手改英文共九轮核心语义审阅通过，单轮约 3～8 秒，作为后续验证首选候选；默认配置尚未改、完整 45 轮与成图验收未完成。新增进程内 --model 覆盖，相关回归 58 项通过。本轮无 GPU。详见 [模型初筛](../docs/v3/audits/2026-09-09-conversational-workbench/MODEL_SCREENING.md)。

处于设计实施表 PR-11～PR-12 的收尾阶段：核心交互与后端协议已实现，官方内容和真实质量验收未完成。下方“第一批～第五批”是历史记录；其中“尚未接入”等描述只代表该批完成时的状态。

| 范围 | 当前状态 | 尚待验证或交付 |
| --- | --- | --- |
| 会话编辑 | 多轮改写、五层要求、锁层、手改正负、保存恢复已实现；Qwen3.7-Max 45 轮改写核心要求已复核 | 参考提取遗漏问题与成图质量 |
| 生图链路 | 显式提交、冻结快照、幂等、队列恢复、产物关联已实现 | 更多固定 seed 效果对比 |
| 用户参考库 | 上传、编辑、分析接口、收藏、风格钉选、缩略图缓存已实现 | 真实视觉分析的语义质量 |
| LoRA | 声明、资源映射、可用性与提交绑定已实现 | 质量评测中确认资源效果 |
| 官方样例 | 构建、校验、安装、切换、个人备注与复制已实现；三图首包已成包 | 真实质量评测、wheel/Windows 发行集成 |
| 用户入口 | `/workbench/conversation` 可试用 | 两项发布 flags 仍为 false，默认入口未切换 |

真实服务证据包含初期两轮 LLM 改写、一张 3080 Ti 生图及收藏，以及下文新增的文字多轮验证，不代表完整模型质量通过。当前无需启动云显卡；正式参考和提示词评测准备好后，再集中执行 12 张成图对照。

用户方向调整：优先从原始提示词提取参考要求，读图为可选实验能力。新增 source=prompt 的文本分析路径，无图片读取/发送、无需 supports_vision、强制关闭思考；保存 analysis_source，保留锁层/资源/CAS 与失败保护。界面新增“从提示词提取要求（不发送图片）”，未保存笔记时禁止分析。相关后端 58 项、参考库前端 7 项通过，TypeScript 与生产构建通过。一次真实 MiMo 文本提取保留左右戴帽关系和全局排除，但排线术语有翻译偏差；见 [验收记录](../docs/v3/audits/2026-09-09-conversational-workbench/PROMPT_INGEST_ACCEPTANCE.md)，不表示全面语义验收通过。

最新后端全量回归：427 passed；1 条依赖弃用警告。最新前端全量为 68 passed，最近一次 TypeScript 与生产构建通过；本轮未修改前端。

新增 [可重复文字验收工具](../docs/v3/audits/2026-09-09-conversational-workbench/TEXT_EVALUATION_RUNNER.md)，默认预检，单场景三轮、最多独立重复三组；隔离记录、首个失败停止、保存 SYSTEM 哈希和耗时，质量仍需人工判断。木刻交接包裹首组发现 expand 擅自添加中景/平视构图，虽 warnings 完整仍判失败，已强化 SYSTEM 的扩写边界。完整重跑后三轮完成，扩写未再改变构图，新增细节均有提示；英文遗漏排线密集程度，保真仍有备注。两组六次调用各约 35～76 秒，未使用 GPU，尚不能宣布完整质量与稳定性通过。详见 [木刻扩写验收](../docs/v3/audits/2026-09-09-conversational-workbench/WOODCUT_EXPANSION_ACCEPTANCE.md)。

接口补测已定位 GLM-5.2 此次上游实际路由为仅思考的 GLM-5.3，拒绝关闭思考参数；增加安全错误分类和不可重试提示，未修改用户默认模型。MiMo 双人三轮与手改三轮新测试均通过：改光线、改背景后左右帽子关系与手加红围巾分别保留，负向不变，重开持久库一致。此前超时原因尚未被证明，不能据此宣布稳定性验收完成。详见 [接口诊断与补测](../docs/v3/audits/2026-09-09-conversational-workbench/PROVIDER_STABILITY_ACCEPTANCE.md)。下段为上一批记录，最新结果以此补测为准。

新增边界验收：删除 LoRA 后旧编译不可提交，重编译后的冻结快照和各阶段规划不再携带已删资源，本地调度集成测试通过。真实双人用例首轮超时；手改用例首轮和保存英文成功，但下一轮超时，尚不能确认跨轮语义保留。GLM 对照发现 5.3/Flash 禁止关闭思考，已修复参数匹配并增加文字任务联网前的明确拒绝；5.2 完整改写也失败，原因未定。未继续增加模型调用、未改默认配置、未使用 GPU。详见 [边界场景验收](../docs/v3/audits/2026-09-09-conversational-workbench/EDIT_CASE_ACCEPTANCE.md)。

真实多轮功能验证：提示词提取结果经人工纠正术语后，通过 API 上传、style pin、换女侦探主体、锁定主体/风格，再分别修改光线和构图；三轮只改变预期层，完整英文和负向保留，重开持久库状态一致。此前一次超时和一次结构失败均保留；另修复 SSE DONE 后等待连接关闭的问题。详见 [文字链路验收](../docs/v3/audits/2026-09-09-conversational-workbench/TEXT_FLOW_ACCEPTANCE.md)。没有提交生图；尚未完成全部场景和成图质量验收。

最新内容交付：新增 [cma-styles-20260910-v1](example-packs/README.md) 三图包（木刻、炭笔、水彩），来自 CMA 标记 CC0 的开放馆藏。逐张查看后编写五层要求，保留逐图来源和许可，JPEG→WebP 解码像素一致。包相关 15 项测试通过（新增真实包集成测试 1 项），包含安装、图片/缩略图读取及 style pin 不复制主体/光线/构图。只安装到测试临时目录，未改用户运行时配置；模型效果尚未验收。

视觉验收准备：新增 `tools.evaluate_reference_ingest`，默认只预检，显式执行时最多顺序调用三张参考；隔离存储、不给官方答案、保留逐次记录、失败停止且不自动重试。此前误读系统默认目录，报告了 zhipu / glm-4.5-flash 未就绪；实际仓库启动器使用 `v3/.local/prompt-assistant`，用户的 OpenCode Go / mimo-v2.5 Key 已正确保存。工具补充 `--config-dir` 和配置选择测试，避免再次混用。视觉能力标记已启用，模型列表接口返回 200。

真实视觉诊断：首轮失败后停止；独立单图诊断证实能识别肖像，但模型把 SYSTEM 中 `subject/lighting` 的简写理解为单个字段。已改成五个独立字段的完整 JSON 示例，并同步消除 rewrite 中的相同歧义。参考库/会话/验收工具相关 59 项测试通过。修订后木刻首图结构通过但媒介/动作判断有误，肖像第二图失败后停止，水彩未调用；整套质量验收未通过。本轮共 4 次视觉请求，未使用 GPU，详见 [MiMo 视觉验收记录](../docs/v3/audits/2026-09-09-conversational-workbench/VISION_ACCEPTANCE_MIMO.md)。

### 分批实施记录

按 [修订设计](../docs/v3/CONVERSATIONAL_WORKBENCH.md) 启动开发，首批完成后端基础与会话改写（实施表 PR-1～PR-3 的后端范围）：

- requirements /1 五层、锁层、资源校验、内容合并和 pin 复制纯函数；独立编译 token、完整输入指纹与服务端 stale 投影。
- workspace 写 DTO 与服务端字段保护；旧保存省略新键不清会话，同值回显不把 LLM 结果改记为手写；未知会话版本明确拒绝，不重置原数据。
- 新 `POST /workbench/turns` / `POST /workbench/reset`；LLM 事务外执行、结果短事务 CAS、同工作台限流、回执持久化及重启恢复。
- 新 `LLMService.complete()`：有界响应、无自动收费重试、OpenAI/Ollama 视觉消息形状、设置 owns thinking；GET/PUT LLM settings 支持 vision/ingest thinking 字段。旧 expand_prompt 协议保留，并修复其内部吞掉外层超时取消的问题。
- `conversational_workbench` / `reference_gallery` 仍为 false。旧前端仍走原型；新会话 API 可供集成测试，不表示整套 v1 已上线。

第二批已接通资源绑定、持久提交和会话界面主链路：

- GET/PUT workflow `lora-bindings` 使用修订号 CAS；按实际远端文件枚举和明确插槽解析，执行器不再用旧别名覆盖最终绑定。重放先选择冻结工作流，再验证节点、文件和槽位。
- `generation_submissions` 与 workspace 共库接受事务：冻结要求、正负、资源、工作流、实际 seed 和接受回执；相同 key 重试返回原回执，payload 不同返回 409。接受记录占用队列容量；重启交付沿用 run ID；远端回执丢失标记结果待确认，不自动再次采样。
- 直出/候选端点支持 conversational 字段及独立 LoRA 资源；reference DTO 已校验，但来源目录尚未接入，reference 请求明确拒绝，不伪装成功。
- 新 `/workbench/conversation` 试用界面：逐轮追加/重新编译、五层编辑与锁定、LoRA 编辑、正负手改、显式生成、冲突时保留本地输入、网络中断后复用原幂等请求。本会话任务和产物通过服务端关联恢复，展示最近结果。
- `GET /workbench/availability`、`GET /workspaces/{id}/runs` 和 `GET /generation-runs/{id}/artifacts` 已接入。产物复用现有画廊，不存在的文件显示已移除；无已下载产物时返回空列表。

第三批已接入用户参考库：独立图片副本、上传校验、检索分页、CAS 编辑/软删、内容/缩略图、画廊/run 收藏、视觉 ingest 与 pins/unpin。分析失败保留旧要求，编辑使迟到结果失效，重启不自动收费重试；from-run 使用接受快照。界面增加上传、笔记、分析、覆盖预览、钉选、移除、结果收藏及 LLM 视觉设置。

第四批已完成（全程离线，未调用云 GPU/收费模型）：

- 官方包目录校验、哈希/图片/数量检查、不可变版本安装与 current.json 原子切换；重复包 ID 不允许改内容，失败保留原激活版本，损坏包不影响用户库。新增 anima-v3-example-pack 本地安装命令。
- 官方笔记独立 CAS 覆盖、复制为个人参考、官方/用户合并分页与来源版本冲突。正式精选样例仍未入包，测试像素不作为正式官方内容。
- reference-presets 列表/详情/目标 availability，投影不泄露外部笔记正文；独立 reference 提交冻结指定来源，资源可显式覆盖，幂等重试优先于来源重读，来源删除不破坏已接受任务。
- 参考五层/局部排除/画师/LoRA 编辑器；未保存要求不能钉选。LoRA 映射界面读取服务器枚举和版本信息、显式选槽/文件、CAS 保存后重新检查；无有效能力时禁止保存。
- 视觉 ingest 保留已确认画师，不能因模型遗漏而清空；官方卡只允许笔记和复制，不直接改包内容。

第五批已完成参考缩略图持久缓存与旧工作台测试迁移（离线）：

- 缩略图按条目、原图内容哈希、尺寸和渲染版本缓存；跨进程重启可复用，损坏自动重建，默认容量 256 MiB，按最近使用淘汰缓存文件。缓存写入失败仍返回生成的缩略图；读取前检查原图和条目是否仍有效。
- 旧工作台 29 项过时界面测试已完整归档，迁移为当前入口的 16 项交互测试；不恢复旧入口、不通过跳过测试隐藏失败。详见 [迁移记录](../docs/v3/audits/2026-09-09-conversational-workbench/TEST_MIGRATION.md)。
- 后端全量 388 项、前端全量 67 项通过，TypeScript 与生产构建通过（沿用 `--emptyOutDir false`）；后端新增缩略图缓存测试 5 项。

剩余：正式官方样例精选与许可说明、更多真实视觉/固定 seed 质量评测。默认入口仍为旧工作台，两项 feature flags 保持 false；试用路由可直接访问，尚不表示会话 v1 全部完成。

后续离线收尾：缩略图再次检查原图格式、静态帧和像素上限，原图损坏返回领域错误；增加缓存不可写回退测试。参考库/缩略图相关 26 项通过（本批新增 3 项，未重跑全量）。已整理 [质量验收执行单](../docs/v3/audits/2026-09-09-conversational-workbench/QUALITY_ACCEPTANCE_PLAN.md)：先准备正式样例并完成无需 GPU 的 45 次改写及视觉分析，再启动云主机生成 12 张固定 seed 对照图；计划尚未执行。

参考包制作：新增 `anima-v3-build-example-pack`，从本地策展目录生成清单/哈希并复用完整安装校验，不覆盖已有 manifest，不安装激活。新增构建测试 5 项，与官方包测试合计 14 项通过。三张开放馆藏候选已核对 API `is_public_domain=true` 并留存来源记录；图片下载返回 403，尚未视觉筛选或制作正式包。未调用 GPU 或收费模型。

首批验证记录：新增测试见 `tests/test_conversation.py`。V3 后端全量通过；旧 `WorkbenchLlm.test.tsx` 与 `DirectPromptPage.test.tsx` 合计 10 项通过。额外检查的旧 `WorkbenchPage.test.tsx` 29 项失败，存在过时词典页面标签和不匹配的 mock 响应（LLM settings / generation targets）；首批没有修改前端文件，保留失败记录，后续前端迁移时修订，不能把前端全量标记为通过。未调用真实云端 LLM 或生图服务。

第二批验证：V3 后端 353 项通过（新增资源/提交测试 23 项）；新会话页面 5 项交互测试及旧改写/直出页面 10 项通过；TypeScript 与生产构建通过。通过离线样例检查桌面与 390 px 窄屏布局，未发现横向溢出。原 `WorkbenchPage.test.tsx` 的既有失败仍未修订，不能把整个前端套件标为通过。没有调用真实模型或远端生图。当前 Windows Node/Vite 在清理既有 outDir 时发生原生进程异常退出；新 outDir 或 `npm run build -- --emptyOutDir false` 可成功构建，后者保留旧的 hash 资产，不影响新 index 指向当前产物。

## 当前阶段

第四批验证：后端全量 383 项通过；相关前端 23 项通过，TypeScript/生产构建通过。新增参考编辑/映射离线样例检查默认桌面与 390×844 无横向溢出；修正勾选框对齐。旧直出测试明确选择目标兼容模型并等待工作流说明，避免依赖异步默认选择。旧 WorkbenchPage 的 29 项既有失败仍未计为通过。

第三批验证（2026-09-10）：后端全量 368 项通过（参考库 15 项）；参考库前端 4 项、新会话及旧改写/直出页面 15 项通过；TypeScript 与生产构建通过（仍使用 --emptyOutDir false）。展开的参考上传区在默认桌面与 390×844 均无横向溢出。旧 WorkbenchPage 的既有失败仍不计为通过。

真实验收：OpenCode Go / MiMo-V2.5 两轮改写成功，第二轮只改光线/排除项。临时 Key 仅在测试进程内使用，未写入配置/文件。RTX 3080 Ti / Anima Base v1 完成 768×768、20 steps、固定 seed 单图；重复幂等请求、产物下载与工作台关联、收藏原始字节与冻结要求、风格钉选不复制主体均通过。详见 [验收报告](../docs/v3/audits/2026-09-09-conversational-workbench/LIVE_ACCEPTANCE.md)。不表示复杂动作或视觉 ingest 质量全部通过。

既有 Phase 3 主路径继续维护；新增会话工作台按 ADR-025 分阶段实施并置于关闭的 feature flags 后。下方“已完成”列表为既有产品历史能力，不代表会话 v1 已完成。

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
  - V3 已改为工作流级生成配方：配方随目标返回，包含用途、证据等级、实际参数、可编辑/固定能力和多阶段快照，不再复制 V2 的模型三档数值。
  - DMDX 四步和 HiRes 分阶段参数由真实工作流模板锁定；普通 Turbo 约束为 8–12 Steps/CFG 1；Base/Aesthetic 将稳定基线、创意风格和待验证细节实验分开表达。
  - Web 工作台在生成规格区选择云主机、工作流和对应配方；手动调参会标记为“自定义参数”，固定字段只读并说明原因，HiRes 显示基础/精修两个阶段。
  - 工作区持久化远程目标和工作流 ID，重新打开时不再静默套用最近一次全局目标。
  - 服务端在入队前校验配方与工作流能力，阻止普通 Turbo 参数覆盖 DMDX；V3 HiRes 的声明基础参数会写入实际基础节点。
  - V3 候选、Intent、工作区 revision 和版本信息作为不透明快照进入 V2 任务及结果 manifest。
  - `/generation-requests/preview` 可在不发起远程请求的情况下检查桥接结果；bootstrap 明确报告 V2 runtime 是否可用。
  - V2 `RemoteExecutionCoordinator` 仅新增向后兼容的预创建 run 入口；伪远程端到端流程确认 SSH/ComfyUI/工作流/归档主链仍直接复用。
  - 无 UI 单工作线程 FIFO 队列支持等待上限、排队取消、快照执行与安全停止。
  - 生成幂等键进入 V2 run 快照，API 服务重启后仍不会重复提交。
  - V2 SQLite 的云主机、工作流、输出目录及系统凭据直接复用；job/run/artifact 持续写回原有仓库。
  - 提交、查询和 `cancel_queued` API 已实现，响应不包含任务内部快照、工作流或凭据。
  - 历史未完成 run 可使用 `retry_check` / `continue_download` 恢复，沿用原 remote prompt ID，不重复提交。
  - Web 工作台只展示已确认指纹且兼容当前模型的 V2 目标，候选可直接提交并跳转生成页。
  - 工作台可锁定一条无画师候选，从当前推荐池选择 1–20 位画师，以同一模型、工作流、生成配方、尺寸和固定 Seed 分别提交独立任务；不会混合画师或静默修改基准提示词。
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
