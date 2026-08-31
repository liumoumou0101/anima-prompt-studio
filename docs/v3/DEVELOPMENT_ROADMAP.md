# V3 开发路线与退出条件

状态：开发前计划

原则：按可验证的纵向切片推进，不先铺满全部页面和算法。

实际进度以 [../../v3/STATUS.md](../../v3/STATUS.md) 为准。当前已完成 V3-001、V3-003～V3-012 的首个完整纵向切片；锁定上游真实数据已通过全量构建、validator、静态硬门槛、localhost API、标签页和候选工作台真实浏览器冒烟。默认候选已收敛为 Literal 与显式关系 Hybrid，标签和画师改为需用户确认的建议池；下一步扩展可编辑 Scene Draft 并做固定 Seed 质量验收。

## 0. 当前阶段：开发准备

交付物：

- 产品基线。
- 架构和存储边界。
- 数据包与 API 契约。
- V2 复用清单。
- 质量评测方案。
- 开源与数据边界。
- 架构决策记录。

退出条件：本目录文档一致、可链接、无占位性的核心产品决策。上游 commit 与真实基准样本允许在正式开发启动动作中补齐。

## 1. Phase 0：技术与质量假设验证

目标：在大规模 UI 开发前证明数据能够导入、推荐能够工作，并建立 V2/外部提示词基线。

### 工作项

1. 创建 V3 开发分支和 `core_v3/data_v3/api_v3` 骨架。
2. 固定 DanbooruSearchOnline、Booru Tag Gallery、prompt-translator 的 commit 和许可证副本。
3. 准备上游数据小样 fixture，不先提交完整数据包。
4. 实现只读 importer spike，验证当前 Tag–Tag 与 Artist–Tag 真实字段。
5. 对 20～50 个手工标签组合复现 SearchOnline 的推荐结果。
6. 准备首批外部优秀提示词 benchmark。
7. 用 V2 的“提示词直出”能力保存 REF 与 V2 固定参数基线。
8. 决定语义 embeddings 是基础包还是可选增强包，并测量体积、冷启动和内存。

### 退出条件

- 上游数据 schema 差异已被 fixture 测试锁定。
- 能从小样构建合法 `reference.db` 和 `data-pack.json`。
- 至少一条查询能完成 tag 搜索、相关标签和画师推荐。
- 基准 case、固定工作流和 seed 已保存。
- 没有需要推翻数据或许可证总体路线的新阻塞项。

## 2. Phase 1：无 UI 纵向主链路

目标：通过测试或 CLI 完成“输入—literal—保守增强—候选快照”。

### 工作项

- `IntentElement`、关系与约束模型。
- V2 翻译适配器。
- 精确、别名、中文和语义 tag mapping。
- literal renderer 和 Base/Aesthetic/Turbo 规则。
- 共现推荐 adapter、过滤和解释。
- 可选画师 lane。
- fidelity/conflict/format validator。
- 候选快照与算法版本记录。
- 静态 benchmark runner。

### 退出条件

- `V3-L` required 保留和 excluded 泄漏达到评测硬门槛。
- 没有 embeddings 或共现数据时能正确降级。
- 相同输入、数据和配置生成确定性候选。
- 各 lane 有结构差异，不是单纯换序。
- 所有自动标签可追踪来源。

## 3. Phase 2：统一 API 与 Web 工作台

目标：完成本地可用但尚未接远程生图的产品主界面。

### 工作项

- localhost 生命周期与会话交换。
- 标签搜索、详情、相关标签和画师 API。
- 工作台和候选 API。
- React/Vite 应用壳与路由。
- `/workbench`、`/tags`、`/tags/:name`、`/artists`。
- 候选对比、标签来源和冲突说明。
- 工作台持久化、撤销/恢复、收藏和 Prompt 导入。
- 在线预览的显式开关、限流、NSFW 与缓存。

### 退出条件

- 断网时可以完成搜索、候选、编辑、复制和恢复。
- 4 万以上标签滚动和搜索满足交互性能目标。
- 刷新浏览器不丢已保存工作台。
- 两个浏览器标签页不会静默互相覆盖。
- 所有 API 写接口通过会话、Origin 和输入验证测试。

## 4. Phase 3：生成与画廊闭环

目标：把选定 V3 候选送入已验证 V2 远程执行并统一画廊。

### 工作项

- 抽离 `GenerationQueueService`。
- V3 candidate 到 V2 生成快照的 adapter。
- `/generate` 页面和任务状态。
- 把画廊路由迁入统一 API。
- 合并当前 Web 画廊，新增候选 lane 与版本信息。
- 再生成、放大、回收站、恢复和永久删除。
- manifest 增加 data/algorithm/template/model profile 版本。

### 退出条件

- V2 已验收工作流继续通过模拟和真实服务器检查。
- 网络中断和应用重启后任务可恢复。
- 用户选择候选与实际提交 Prompt 完全一致。
- 画廊可以追溯每张图来自哪个 lane 和哪个数据版本。
- 永久删除与路径安全回归通过。

## 5. Phase 4：生图质量验证与调优

目标：证明默认候选实际优于 V2，而不是只完成工程迁移。

### 工作项

- 执行 [EVALUATION_PLAN.md](EVALUATION_PLAN.md)。
- 逐场景族分析 V3-L/C/A/H。
- 调整共现阈值、类别预算、冲突规则和 lane 默认顺序。
- 只针对可复现失败修改算法。
- 完成 Base/Aesthetic/Turbo 分别验收。
- 增加性能、内存、数据包更新和离线安装测试。

### 退出条件

- 达到 V3 替代 V2 主入口的质量门槛。
- 不存在已知的数据损坏、凭据泄漏或路径越界问题。
- 推荐关闭或数据缺失时仍有完整 literal 工作流。
- 项目负责人确认默认候选策略。

## 6. Phase 5：开源发布准备

- GPL-3.0 根许可证和源码获取说明。
- 第三方 notices 与上游修改记录。
- 数据包来源、许可、manifest 和哈希。
- Windows 安装版与便携版升级/回滚测试。
- 从干净环境验证基础安装、可选资源和离线运行。
- V2 用户数据库迁移和备份说明。
- 最终用户文档、隐私说明和联网功能说明。

## 7. 首批实现任务单

按顺序执行；每项只在前一依赖通过后进入主干。

| ID | 任务 | 依赖 | 完成定义 |
| --- | --- | --- | --- |
| V3-001 | 创建 V3 分支与包骨架 | 文档准备 | V2 测试仍通过，无功能改变 |
| V3-002 | 固定上游 commit 与 notices | V3-001 | commit、license、修改策略入库 |
| V3-003 | 建立上游小样 fixtures | V3-002 | 覆盖当前和一个错误 schema |
| V3-004 | 实现 manifest 与 importer | V3-003 | 构建小型 reference.db，坏数据拒绝 |
| V3-005 | 实现 ReferenceDataStore | V3-004 | 搜索、详情、tag/artist edges 有测试 |
| V3-006 | 定义 Intent/Constraint/Candidate | V3-001 | Pydantic/domain 模型及序列化测试 |
| V3-007 | 实现 literal mapper/renderer | V3-005/006 | 三种模型配置静态硬门槛通过 |
| V3-008 | 接入 SearchOnline 推荐 adapter | V3-005/006 | 对 fixture 排名与上游对照一致 |
| V3-009 | 实现 lane 策略与 validator | V3-007/008 | L/C/A/H 可解释且可降级 |
| V3-010 | 建立本地 API 会话和只读端点 | V3-005 | 安全测试与 API DTO 测试通过 |
| V3-011 | 创建 Web 壳和标签页 | V3-010 | 离线标签搜索和详情可用 |
| V3-012 | 创建工作台与候选对比 | V3-009/011 | 完成输入到复制的离线闭环 |
| V3-013 | 抽离远程生成队列 | V3-012 | 不依赖 MainWindow 控件运行 |
| V3-014 | 合并画廊与统一 API | V3-010/013 | V2 画廊行为回归通过 |
| V3-015 | 执行正式质量 benchmark | V3-014 | 生成分族报告并做放行判断 |

## 8. 开发纪律

- 每个任务先写或固定失败测试，再实现。
- 不在数据 adapter 尚未稳定时开发依赖真实大数据的 UI 细节。
- 不以 UI 已完成代替质量评测。
- 不把未来“自动学习”作为当前排序效果不足的补救。
- 不在同一提交中同时重写 V2 远程执行和 V3 提示词核心。
- 对外部上游的移植保留单独 commit，方便审查许可证和后续同步。
