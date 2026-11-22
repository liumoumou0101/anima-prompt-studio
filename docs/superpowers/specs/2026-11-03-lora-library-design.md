# 本地 LoRA 库、多项叠加与 Colab 缓存

用户已于 2026-11-03 批准实施。用户自行下载文件并放入项目目录，工具管理和使用，首版支持多 LoRA，ANIMA 与 MOSS 分别真实出图验收。未来增加 Illustrious/SDXL 复用资源管理。

## 已选方案

项目 `loras/` 为默认收件目录，可递归扫描 safetensors。独立管理页允许刷新、打开目录和编辑分类、兼容模型、触发词、默认权重。文件内容 SHA-256 是资产身份，改名不重复建档，内容改变产生新版本。保留缺失文件记录以支持云端缓存复用和历史。扫描只登记。

曾考虑 URL 自动下载及每个 LoRA 固定工作流。用户明确排除站点下载登录功能，选择本地文件。工作流由支持的底模模板声明扩展点，按启用项顺序生成链。

## 本地与云端协议

统一远端文件名 `anima_library/<sha256>.safetensors`，位于 ComfyUI 的 loras 搜索目录。Drive 同样保存此内容寻址文件。管理页用人类可读名称。

当前运行时已安装直接使用。Drive 已缓存则恢复到运行时。两处均无则从本机上传，完整校验后原子安装。失败可安全重试、不能把半文件标为可用。云端只接受 SHA 标识，路径由服务固定生成。使用现有 HTTPS/Bearer 网关，不额外公开服务。状态必须来自当前连接，不凭旧 URL 推断当前实例。

同步在独立任务中进行，显示准备进度。工作台启用库资源时准备当前环境，重连时重新核验当前启用列表。生成检查必须检查实际枚举，保存实际图和资源快照。

## 数据与接口约定

沿用 `RequirementLora` 的 logical_id/file_name/weight/trigger_words/source。追加可选 sha256、enabled(默认 true)、clip_weight(默认继承 weight)。旧记录缺少字段继续工作，旧序列化快照与摘要保持原格式。首版沿用现有最大 16 项限制。

库资源 logical_id 为 `library:<sha256>`，file_name 为上述内容寻址远端名。库记录字段 id/sha256/name/file_name/relative_path/size_bytes/family/model_profiles/trigger_words/weight/clip_weight/present/valid/error。family 为 anima/moss/sdxl/unknown。未知兼容信息由用户确认，保留已声明与已实测的区别。

接口前缀 `/api/v3/loras`。GET 列表返回 root_path/items。POST /scan。PUT /{sha256} 编辑资料。POST /open-folder。POST /environments/{remote_id}/sync 接收 sha256s 并返回同步任务。GET /jobs/{job_id} 返回 queued/running/completed/failed、进度、结果。所有接口沿用本地安全会话。

Colab 网关提供 GET /_moss/loras/{sha256} 查询、PUT 同地址接收字节、POST /_moss/loras/{sha256}/restore 从 Drive 恢复。结果包含 sha256/size_bytes/cached/installed/file_name。仅管理本模块文件，验证摘要、长度和认证。客户端复用当前 Comfy 连接与凭据，不把密钥保存到记录或日志。

## 工作流与组合

声明式扩展点包含 model 源和目标输入，可选 clip 源与目标输入，以及支持的加载器类型。只扩展受控内置基础模板，用户固定插槽图沿用既有行为。ANIMA 保留 shift/采样结构，MOSS 模型专用加载不改变文本编码链。可选 clip_strength_input 支持 LoraLoaderModelOnly。

按启用列表动态实例化节点，禁用项旁路且不检查文件，不注入触发词。节点 ID 稳定，物化图可重复验证和冻结，历史重放不二次扩展。固定图的实际插槽顺序明确显示，不伪装成任意排序。

触发词按启用项去重，工具新增部分可撤回，用户手写、锁定或其他启用项共享的文字保留。直接提示词模式保留其明确授权的文字处理语义。

每次提交冻结文件摘要、启用顺序、两种权重、触发词、底模与实际工作流。后续编辑库资料不改变已接受任务或历史。

## 实现分工

根代理负责本地资产索引、API 注册、同步任务包装、集成和交付。
工作流代理负责领域字段、模板扩展、解析器/编译器/队列兼容及回归测试。
云端代理负责网关资产接口、连接客户端、Notebook 可复现更新与协议测试。
前端代理负责库页面、导航、工作台选择/排序/开关/准备状态、MOSS 接入及 UI 测试。

## 验收

扫描重复/移动/改名/内容替换；旧任务与无 LoRA 生图；模型专用与双路加载；两个不同文件组合及单独开关；文件名/路径约束；上传中断/重试/并发；当前运行时零上传复用、Drive 恢复零本机上传；按实际 PNG 和 history 校验图与权重。

真实 Colab 用隔离生成记录，ANIMA 从已验证 CunnyFunky v4 出发，MOSS 使用匹配 INT8 的作者公开 LoRA，按需取得测试文件。用户手工下载是产品入口，验收中的样例取得沿用本轮明确授权。增加第二个不同兼容文件做多项验收。保存原图、图快照、日志、文件摘要及同步统计。若某个文件不能匹配，修正受支持组合并记录原因。

保持现有工作区其他修改。所有开发先在当前工作态快照的隔离目录完成，再按基线哈希检查后同步本次文件。
