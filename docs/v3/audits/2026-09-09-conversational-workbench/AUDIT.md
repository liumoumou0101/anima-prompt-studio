# 会话工作台设计审计

2026-09-10 修订记录：本文审计的是 [2026-09-09 原稿](ORIGINAL_DESIGN.md)，下文行号均对应该归档。主设计已按 F1–F10 修订，见 [当前设计](../../CONVERSATIONAL_WORKBENCH.md) §15；这是设计整改记录，尚不是实现或真实模型验收结论。

日期：2026-09-09  
对象：`docs/v3/CONVERSATIONAL_WORKBENCH.md`，本次读取为 1141 行  
方法：全文契约审查、跨章节反例推演、对照现有 workspace / queue / workflow compiler / API 源码。未修改原设计，未运行云端 LLM 或真实生图，未把尚未实现的功能当作现有代码缺陷。

## 结论

建议保留产品方向，修订下列合同后再按 PR Plan 实现。当前不建议把“未决项：无”理解为工程合同已经闭合。

发现 6 项 P1（实现前需要解决的正确性或一致性问题）、4 项 P2（需要补齐的接口、恢复及验收约定），未发现需要推翻整体产品方向的 P0。

值得保留的设计：requirements 作为持久记忆；工作台、参考收藏、历史履历分开；显式生图；只在 ingest 发送像素；资源与提示词分开；单例图；不在 v1 做模型安装器。官方例图包进入 v1、不做自动出图、不验收本地 4B 这三项用户决定应原样保留。

## 发现

### F1 · P1 · 提交重新读取例图 LoRA，使草稿失去资源权威

位置：设计第 279、285、527、729–735、1032 行。

合同允许用户删除 LoRA 芯片、调整权重，草稿因此过期并重新编译；但提交算法从例图读取 required LoRA，再与请求列表合并，完全没有把草稿 `requirements.loras` 定义为最终资源来源。

反例：钉选含 A 的例图 → 用户删除 A → 成功重编译 → 提交空 LoRA 列表。第 730 行会重新加入 A。用户可能仍收到缺文件/槽位不足的 422，或实际使用已删除的 A。第 1032 行给出的“删芯片”解决方式因此不成立。手填草稿 LoRA 在请求省略资源时也没有服务端兜底。

另一反例：草稿钉选例图的 A 并完成编译；例图被编辑或官方包将同一稳定 ID 的资源改成 B。提交按 ID 动态读取 B，草稿 revision / inputs fingerprint 均未变化，可能用 A 的提示词配 B 的资源生图。删除例图或移除旧包也可能让已编译草稿突然无法解析。

修订建议：钉选时冻结本次应用的例图版本和资源快照；有 workspace 的提交只解析该草稿确认过的资源，参考 ID 保留来源用途。用户主动删除资源是明确编辑，不属于“系统静默剥离”。无 workspace 的独立 preset 提交可继续要求全部 required 资源。如果坚持原 preset 不可修改，则删除动作必须显式解除 preset 绑定，不能保留当前“可删芯片但提交加回”的合同。

验收：删 required 芯片后重编译确实不再携带该资源；更新/删除来源例图不改变现有草稿的任务资源；省略请求资源不会丢失草稿资源。

### F2 · P1 · 正负文本哈希不是完整编译版本，无法挡住旧标签页

位置：设计第 312–323、718–719 行。

`prompt_fingerprint` 只哈希 positive/negative，而 direct submit 明确不检查 workspace revision。服务端 inputs-stale 检查比较的是当前草稿和当前 compiled，并未校验客户端持有的输入版本。

反例：标签页 A 保存旧 etag H；B 只把 LoRA 权重 0.8 改为 0.6 并重编译。提示词完全可能相同，因此 etag 仍为 H。此时服务端当前 compiled 不 stale，A 的旧 etag 也相等；A 携带旧资源权重 0.8 提交仍会通过，且第 730 行允许请求覆盖权重。更一般地，文本 P → Q → P 会恢复旧 etag（ABA 问题）。

修订建议：把“提示词内容哈希”和“编译状态版本”分开。提交携带服务端生成的单调 compiled revision 或不可复用 token；成功编译及接受手改时更新 token，并绑定 inputs fingerprint 和最终资源快照。纯正负手改仍可被接受，但必须基于当前 token。不要仅用内容相同判断客户端状态未过期。

验收：正负相同但 LoRA 权重或输入版本已变时，旧标签页提交被拒绝；P → Q → P 后旧 token 不可复用；新 token 下的合法手改仍可提交。

### F3 · P1 · 入队后写草稿存在竞态和幂等重试缺口

位置：设计第 323、736、876 行。代码：`runtime/generation_queue.py:181–244`，`api/workspace_store.py:86–119`。

设计先验证 compiled，再入队，入队成功后才开启 workspace 写事务。这三步之间允许另一个 PUT / turns 改变草稿。之后直接覆盖会丢掉新编译；如果补版本检查并失败，任务已进入队列，仍可能实际生图。

现有 queue.submit 会持久化 run、append pending 并 notify 执行线程；workspace 是另一份数据库、另一连接。workspace 的 `BEGIN IMMEDIATE` 不能回滚已经被唤醒的队列，也不能构成两个存储的共同事务。

幂等反例：第一次提交手改 P1，成功更新 etag，但 202 响应丢失。客户端携原 etag 和同一 Idempotency-Key 重试，如果先做新 stale 检查，会 422 而不是返回已有 run；若绕开检查后重复执行写回，又可能产生重复 revision 或覆盖后续状态。现有 queue 自身的 key 去重不能自动覆盖新增的 workspace 副作用。

修订建议：明确提交线性化时点。通过短事务 CAS 创建持久 submission 记录，冻结输入、资源、目标和 key；队列只消费已接受的提交，崩溃后可恢复。也可采用其他等效协议，但必须证明“检查、接受、草稿写回、可执行任务”的顺序和恢复行为。同 key 重试先返回同一提交结果；同 key 不同 payload 的行为也须固定。

验收：并发 PUT/turns 与 submit；202 丢失重试；接受后入队前崩溃；队列拒绝；workspace 写入失败。每种情况下不得隐式覆盖新草稿、重复生图或把已接受任务报告成未发生。

### F4 · P1 · Turns 的提前持久化与失败不改版本没有一致事务解释

位置：设计第 243、307、350、398–400、1064 行。代码：`api/workspace_store.py` 的连接超时和 `BEGIN IMMEDIATE`。

文档要求在空 delta / stale 检查前“持久化 mode”，同时要求非法更新整轮丢弃、解析失败 workspace 不升 revision，未说明跨 LLM 请求的事务边界。

两种直译实现都有问题：先提交 mode 会在失败时留下未升版本的输入变化；把整个 LLM 请求包在 BEGIN IMMEDIATE 内则长期占用 SQLite 写锁。现有 workspace busy timeout 为 5 秒，云端调用可能轻易超过它，影响其他工作台写入。若调用前释放锁，又必须在结果写回时重新 CAS，不能只检查入口 revision。

修订建议：读取版本快照 → 在内存副本设置 request.mode 并判定首次/重编译 → 事务外调用 LLM → 短事务 CAS 原 workspace revision，原子写入 mode、requirements、compiled。任何错误或版本冲突均不提交这轮结果。若产品要求失败后也保留 mode，应作为单独、明确升版本的编辑，而非隐式副作用。

验收：LLM 超时、非法 JSON、非法层更新不改变草稿；慢请求不阻塞其他 workspace 保存；模型运行期间的编辑导致结果回写 409，且不覆盖编辑。

### F5 · P1 · 收藏旧产物时没有生成当时的完整 requirements 可用

位置：设计第 531、641、735、887 行。代码：`runtime/generation_queue.py:215–220`。

胶片条允许收藏旧 run，却要求复制“当前 requirements + prompts”；from-run 请求只有 run_id/path。新增 run 元数据只约定保存 requirements revision、reference ID 和 fingerprint，没有完整 requirements 快照。哈希和 revision 不能还原历史内容，现有 workspace 也没有版本历史表。

反例：R1 用黑白侦探要求出图；用户把草稿改成彩色海边人物；随后收藏 R1。读取当前草稿会把海边要求贴到侦探图片上；只读取 run 又无法还原原 requirements。R1 仍在运行时用户继续修改，也会出现这个问题。

修订建议：接受生图时冻结完整的 requirements、实际正负、最终 LoRA、mode、来源版本和工作流快照。from-run 一律从该 run 的冻结记录派生。对没有 requirements 的历史产物，明确表示缺少结构化要求，允许手填或 ingest，不拿当前草稿补齐。

验收：生图后改变/删除 workspace，再收藏旧 run，所得元数据仍对应原图；手改正负后的实际提交文本被准确保存。

### F6 · P1 · 映射节点文件名与任务 LoRA 文件名之间缺少可执行的绑定规则

位置：设计第 724–733、762–764 行。代码：`runtime/workflow_catalog.py:102–109`，`core/workflow_compiler.py:157–168`。

现有 mapping 是 `node_id.input_name → 枚举文件名`，apply_mapping 修改工作流节点。编译器随后逐槽把 `job.lora_selection[index].file_name`（或 logical_id，经 remote.model_aliases）写回同一节点，覆盖前一步的值。映射本身不含例图 logical_id，也未规定多 LoRA 顺序怎样绑定槽。

反例：例图声明 A.safetensors，用户在 WorkflowManager 把槽映射到远端的 folder/B.safetensors。若 availability 按映射结果判断 ready，但 job 仍带 A，最终节点仍可能被写回不存在的 A。仅复用映射 UI 不会自动完成资源解析。

修订建议：冻结解析输出：每个 logical_id 对应哪个 slot、哪个实际远端枚举文件名、哪个权重；明确顺序和映射失效条件。把最终远端文件名写进 job，或让编译器直接消费同一 resolved binding。availability 和渲染必须使用同一解析结果，不能分别猜测。

验收：远端重命名/带子目录、多槽顺序变化、切换例图、映射过期；断言最终发往 ComfyUI 的节点值，而不只测 availability 返回 ready。

### F7 · P2 · 重放校验使用当前目录，执行却使用冻结工作流

位置：设计第 731–747 行。代码：`runtime/generation_queue.py:481–496`。

提交步骤先对当前 workflow_profile_id 的目录/mapping 做资源可用性判断，再载入 frozen dump 执行。相同 ID 的当前工作流可能已从一槽改成零槽，或节点/模型资产已变化：当前目录验证失败不代表旧快照不能执行；当前目录成功也不证明旧快照的文件仍可用。现有 frozen 分支绕过 resolve_for_submission，不能直接把恢复通道等同为完整的新提交验证。

修订建议：先选择实际执行目标（当前目录或旧快照），再基于该目标的节点和槽位，对当前远端实际资产做统一验证。不要为了让旧快照可运行而悄悄重写它；不兼容应在入队前明确失败。

验收：同 ID 工作流更新后重放；原文件已删除；更换远端；当前目录槽数与旧快照不同。

### F8 · P2 · 重新 ingest 缺少例图版本与锁层保护协议

位置：设计第 226、438、453、479–483、546–568 行。

“全局只有一个 ingest”只能排除另一个 ingest，不能排除用户编辑 requirements/notes、删除例图或更新 overlay。例图表没有 edit revision，ingest 请求也无 expected version；结果完成后如何避免覆盖期间的手改未定义。服务端每次组装 revision=1，同时契约又保证 ingest 不改 locked 层，组装规则没有说明从现有例图读取锁并合并。

修订建议：增加例图 edit revision 和 ingest attempt ID，冻结启动时的 notes/requirements；结果只在版本和 attempt 匹配时提交。锁值由现有例图拥有，锁层原样保留。重启时收敛遗留 pending。失败状态与“已有可用 requirements”分开表达：目前第 571 行 ready 当且仅当 schema 合法，与失败后保留原合法 JSON 的第 483 行相矛盾。

验收：ingest 期间手改/删除、旧结果迟到、重新 ingest 保留锁层、失败后旧 requirements 仍可使用、进程重启遗留 pending。

### F9 · P2 · 可编辑承诺缺少写接口，workspace 写字段权限也未收口

位置：设计第 213–226、325、438、573、645–653、696–703、842–857 行。

例图要求手填层、改 notes、改 LoRA、软删；但 API 增量表只有 GET/POST 创建、ingest、媒体和投影，未列更新/删除接口。官方备注覆盖行的稳定 ID、读写合并和不同包版本的继承规则也未确定。requirements.notes 与 examples.notes_json 同时保存笔记，缺少权威方向。

workspace PUT 又约定新字段出现即替换，而 requirements.revision、compiled.inputs_fingerprint、pins 和只读 snapshot_ref 属于服务端维护状态。extra=forbid 只能拒绝未知字段，不能保护这些已知字段。必须明确写 DTO，而不能期待客户端诚实保留指纹或同时更新重复 pin ID。普通 GET→PUT round-trip 携带未变 compiled，也不应仅因键出现就把 source=llm 改记成 user。

修订建议：补齐带 revision 的例图更新/删除契约和官方覆盖语义；笔记确定一个权威来源。workspace 写 DTO 区分用户可编辑输入与服务端输出；requirements revision 和指纹只由服务端生成；校验 pin/reference ID 一致；明确清空 compiled 的合法语义；仅实际手改正负才改变来源。

验收：无 vision 时手填至可钉选；改备注后重分析；官方备注跨包保留；普通保存不改变来源；不能用输入字段伪造“已编译且不 stale”。

### F10 · P2 · 验收计划尚不能证明多轮忠实与锁层承诺

位置：设计第 262–266、402–415、827、982、1134 行。

服务端校验能证明“被锁的结构化层未写入”，不能证明模型返回的自由文本 positive/negative 没改变对应事实。例如 subject 锁为一位短发人物，模型返回 touched_layers=[]，positive 却写 two people：当前定义的结构检查仍全部通过。类似地，局部排除扩大为全局负向、画师臆造主要依赖 SYSTEM。文档提到“五案例评测”，但没有列出五例、连续轮次、判定标准和失败处理。

这不是要求另造一套中文语义编译器。需要把可确定执行的不变量和依赖模型质量的承诺分开，并给后者实测证据。若要保证实际画面风格接近参考图，还必须把“ingest 描述像不像”和“编译后生成效果像不像”分开验收，schema 合法不能替代图像质量。

修订建议：列出固定多轮用例、每轮必须保留/禁止的事实、允许手改行为和失败标准。对 artist allowlist、已声明 trigger 等能可靠检查的字段添加检查；对主体、构图、局部排除等语义保真，用已配置云端模型的多轮评审记录验收，明确剩余限制。模型未达标时不得仅以 JSON 成功率宣布完成。

最低用例：锁主体连续三轮改光影；局部“帽子无花纹”不变成全局禁止花纹；只改 LoRA 权重后重编译；手改提示词再追加 delta；重新 ingest 不覆盖锁层；旧 run 收藏后再次钉选。并补入 F1–F9 的确定性反例。

## 建议的修订顺序

1. 先解决 F1/F2/F5：确定草稿资源权威、编译版本、run 快照。
2. 再解决 F3/F4：确定 turns 与 submit 的并发、幂等、恢复协议。
3. 解决 F6/F7：让 availability 与实际执行共用最终目标和资源绑定。
4. 补齐 F8/F9 的写接口、所有权和 ingest 状态机。
5. 把 F10 的用例写入验收表，更新 PR 依赖，再开始实现。

契约修订应在消费它的实现 PR 之前或同 PR 合入；目前“PR-9 实现新含义，PR-13 才改正式 API 合同”的安排会留下两个同时有效的解释。

功能 flag 可在内部测试时提前打开，但 v1 发布清单必须单独包含官方例图包、真实云端多轮评测和上述一致性检查；flag 的几个 PR 测试通过不等于 v1 交付完成。

## 审计边界

本次没有运行新增功能测试，因为对应实现尚不存在；结论来自文档中可构造的行为反例和现有代码的静态核对。未验证任何具体云端模型的视觉识别、Anima 方言质量或最终风格还原率。那些结果应由后续验收提供，不能从设计篇幅、讨论时间或模型消耗推断。
