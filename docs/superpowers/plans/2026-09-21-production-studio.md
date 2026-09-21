# 正式工作台交互替换实施计划

> **For agentic workers:** 使用 subagent-driven-development 协作实施；用户已确认原型并明确要求替换正式工作台，连续执行至编译、页面验证完成。

**Goal:** 正式 /workbench 使用已确认的左右编辑预览与底部固定改词/生图流程，真实调用现有服务，常规操作无需采用/保存/同步确认。

**Architecture:** 保留 ConversationWorkbenchPage 的会话、并发冲突与请求去重管理；将主视图拆为 ConversationStudioView、WorkbenchImageResults、WorkbenchHistory。直接生图明确冻结当前文字与条件，后端保留版本与资源验证；新增显式 use_current_prompt 只解除旧编译状态的额外门槛。

**Tech Stack:** React 19 / TypeScript / Vite 8；FastAPI / Python；Vitest 与 pytest。构建使用仓库 .nvmrc 指定的现有 Node 24.19.0。

**Spec:** ../specs/2026-09-21-conversation-first-workbench-design.md；../specs/2026-09-21-workbench-history-and-undo-design.md；../../prototypes/workbench-v1。

## Global Constraints

- 已有 reference library 未提交修改保留，本次不修改其文件。
- 原型示例图片与规则不接入生产；所有图片、更新、生成来自实际接口。
- 更新直接生效；失败保留原词和意见；生成使用可见文本，忽略未发送意见。
- 生图和后台刷新不得清空撤销；恢复前必须持久保留当前草稿，恢复失败不替换编辑。
- 真实多窗口冲突、未知提交状态、资源不兼容继续处理；不重复提交未知请求。
- 本轮直接在用户当前运行目录接入以便立即查看，新增文件隔离展示层，不切换/覆盖其他工作。

## Review Focus

1. 修改模型后，显式当前文字生成仍需通过 CAS、模型/工作流与资源一致性验证。
2. 更新期间输入下一条意见，迟到结果不能清空新意见；组合动作必须生成新提示词。
3. 未知网络提交必须复用同一请求键和冻结正文，不能以新草稿重复生图。
4. 旧图恢复与仅用提示词的资源/设置边界不同；随机批次种子不能冒称单张实际种子。
5. 恢复或更新后撤销可找回意见，生图/刷新不截断编辑和历史。

## Tasks

- [x] API：DirectPromptSubmitRequest 显式当前词模式与缺失/过期编译、旧token、重复请求、资源检查回归测试（production_api）。
- [x] 布局：ConversationStudioView + conversationStudio.css；左右slots、固定dock、窄屏切换、历史modal与测试（production_layout）。
- [x] 历史与图片：WorkbenchHistory / WorkbenchImageResults，中文意图关联、真实图片、详情与恢复callbacks，覆盖无图版本和缺失元数据（production_history）。
- [x] 页面动作：更新使用 turns preview:false 返回的Record；保存内部自动完成；生成带use_current_prompt并保存冻结草稿；单步撤销/恢复与旧proposal恢复入口（root）。
- [x] 集成 JSX：保留会话管理、参考选择、LLM与高级参数入口，移除日常采用/同步/保存门槛，接入三个主按钮与历史抽屉（root）。
- [x] 验证：相关Vitest与pytest、类型检查、构建；独立代码复核；本地正式浏览器检查布局与无副作用流程。真实LLM/GPU调用不用于自动回归。
- [x] 交付：运行服务使用新前后端，说明可打开入口与已验证/未实际执行边界。

关键测试命令：Node 24.19.0 运行 npm run test -- <相关测试> 和 npm run build；.venv Python 运行相关pytest。遇到旧测试明确断言多确认流程，应更新为用户已认可的新流程，同时保留其并发/恢复保障断言。

## Decisions / Progress

- 用户明确授权替换正式工作台；设计与原型已审阅，本轮无需再次审批设计或选择执行方式。
- 工作区有其他未提交内容，保持其原状；不创建不含这些依赖的另一个运行实例。

## 交付验证（2026-09-21）

- 正式工作台已使用 ConversationStudioView、真实图片与历史接口；保留原会话、参考、LoRA、LLM 设置等次级入口。
- 后端定向 pytest 159 项通过；新增当前提示词模式不绕过版本、资源、锁定及幂等校验。
- 前端新增直接更新、组合生成、未知响应查询、旧图恢复、撤销、快照迁移等回归；旧工作台 68 项用例已迁移并通过。
- 全套前端运行覆盖 443 项；并发下出现过计时/异步 fixture 波动，失败项另行隔离定位和验证，不将首次全套运行描述为零失败。
- Node 24.19.0 生产构建通过；最终前端资源为 index-BXJAHQ6D.js；浏览器已加载正式构建，无页面控制台 error。
- 在 1280×720 验证真实历史图片与三主按钮：主区高 384px，底栏约 178px，图片不受遮挡；820px 窄屏验证图片/提示词切换及历史抽屉，完成后重置视口。
- 正式入口 http://127.0.0.1:59243/workbench；已启动使用当前源码与 dist 的本地桌面服务。无需另开原型页面。
- 未执行真实 LLM 改词或 GPU 生图；此部分以接口回归测试验证调用契约，留作用户真实模型体验。

## GitHub 提交前复核

- 前端单 worker 全套：52 个文件、444 项测试通过；TypeScript 与 Vite 生产构建通过。
- 后端全套 v3/tests 共 961 项：首次 960 项通过，参考库并发导入测试 test_import_collection_serializes_concurrent_writers 出现一次 Windows PermissionError；该失败项隔离复跑通过（1 passed）。首次失败及复跑分别记录，不将首次全套结果描述为零失败。
- 本次提交包含工作台实现、回归测试、设计和独立原型；已有参考库修改与其他历史审计材料保留在本地。
