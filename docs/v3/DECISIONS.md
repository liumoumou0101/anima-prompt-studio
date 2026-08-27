# V3 架构决策记录

本文件记录已经确定、会影响多个模块的决策。修改已接受决策时，应新增一条决策，而不是静默改写历史原因。

## ADR-001：V3 重做提示词中轴

状态：Accepted

V3 不在 V2 的翻译、增强和编译链路上继续叠加共现逻辑。V2 流水线冻结为兼容与对照，V3 新建 intent、mapping、recommendation、candidate 和 renderer 边界。

原因：原始重构目标就是解决 V2 默认出图弱于成熟外部提示词的问题；继续加规则会保留错误抽象和耦合。

## ADR-002：V3 按 GPL-3.0 发布

状态：Accepted

主项目允许整合 GPL-3.0 的 DanbooruSearchOnline，同时兼容 MIT 前端和翻译组件。所有第三方 notice 和修改说明随源代码发布。

## ADR-003：pipeline 只作为外部数据构建工具

状态：Accepted

`danbooru-tag-pipeline` 当前无许可证，不进入仓库、安装包、CI 或运行时依赖。V3 只实现自有 importer，消费开发者自行取得的产物。

## ADR-004：完整 Web 产品层，桌面壳保持轻量

状态：Accepted

标签、画师、工作台、候选、生成和画廊采用 React/Vite 页面。首版由 PySide 启动 localhost 服务并交给系统浏览器，不引入 Qt WebEngine。

原因：用户需要完整标签展示网页；V2 画廊已验证系统浏览器路径，且避免同时维护大型 PySide UI 和 Web UI。

## ADR-005：单一 localhost API

状态：Accepted

V3 不长期维持“画廊 HTTP server + 标签 server + 生成 server”多个后端。所有业务路由进入统一 API，旧服务的业务函数逐步迁移。

## ADR-006：参考数据与用户数据分离

状态：Accepted

`reference.db` 只读、可整体更新；`user.db` 保存设置、历史、收藏、反馈和任务。更新参考数据不得覆盖用户数据。

## ADR-007：literal 候选是硬基线

状态：Accepted

每次成功的候选生成都必须有一组不做共现扩展、不自动添加画师的 literal 候选。推荐模块不可用时仍能完成工作流。

原因：共现代表数据关联，不代表对用户意图或出图审美一定有正收益。

## ADR-008：画师推荐是可选分支

状态：Accepted

画师推荐保留并进入产品，但不成为所有候选的必经步骤，不默认混合多个画师。用户可以一键移除画师回到相同保守候选。

## ADR-009：模型配置驱动提示词渲染与执行

状态：Accepted

Base、Aesthetic、Turbo 保持独立 `ModelProfile`。模型配置共同决定 tag 渲染、质量/负面模板、生成参数和工作流兼容性。

## ADR-010：canonical tag 与最终文本分离

状态：Accepted

内部稳定 ID 使用下划线 canonical 名；最终 ANIMA 文本由 renderer 转换为空格形式，并处理 `score_*`、`@artist` 和 Danbooru/Gelbooru 差异。

## ADR-011：离线主路径，联网按能力降级

状态：Accepted

标签搜索、推荐、候选、历史和画廊本地管理离线可用。数据更新、在线预览、AI 辅助和远程生图按需联网；失败时不阻断离线主路径。

## ADR-012：反馈只记录，不自动在线学习

状态：Accepted

V3 可以记录用户选择、淘汰和评分，但首版不根据单个用户操作静默更新算法权重。权重变更通过离线评测、版本化配置和明确发布完成。

## ADR-013：质量验收优先于功能数量

状态：Accepted

V3 替代 V2 主入口前必须执行固定模型、工作流、参数和 seed 的分族盲测。UI 完成、NPMI 分数更高或标签数量更多都不能替代实际生图验收。

## ADR-014：V3 使用顶层独立工程目录

状态：Accepted

V3 源码、测试、前端和开发工具放在仓库顶层 `v3/`，使用独立 `pyproject.toml` 和 Python 包名 `anima_prompt_studio_v3`。产品与架构文档继续集中在 `docs/v3/`。

原因：V2 根目录已经包含大量历史测试、真实探针、报告和阶段文档；继续混写会模糊回归边界。Phase 0 不移动或清理 V2 文件，避免破坏当前可运行版本。稳定 V2 能力只能通过 `adapters/v2` 显式接入，V3 禁止导入 V2 主窗口。

## ADR-015：本地翻译是可编辑语义保底，不是结构权威

状态：Accepted

V2 本地翻译继续作为离线默认入口和完整 prose baseline。翻译结果不得直接证明人数、实体可见性、属性所有权、动作关系、构图或 canonical tag；没有标签命中时仍必须保留原文和译文并返回可编辑结果。

原因：V2 真实语义审计证明否定、属性覆盖、多人作用域和复杂动作不能仅由翻译保证；最近 AI 抽取虽更结构化，但延迟、稳定性和合同一致性也不适合作为默认入口。二者必须作为不同来源的证据或草案，而非最终真相。

## ADR-016：画面事实、映射、推荐和渲染分层

状态：Accepted

V3 将原文证据与可编辑画面草稿、canonical 映射、可选推荐和模型专用渲染分开。只有用户明确内容或已验证的确定性映射可进入 Literal；语义匹配、共现、画师和审美补全在用户确认前不得改变基准候选。

原因：V2 平铺结构、默认增强和标签拼接在真实出图中出现决定性动作丢失、可见实体错误、属性串人和构图合影化。详见 [PROMPT_CORE_LESSONS_AND_BOUNDARIES.md](PROMPT_CORE_LESSONS_AND_BOUNDARIES.md)。
