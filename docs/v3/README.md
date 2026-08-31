# ANIMA Prompt Studio V3 开发准备文档

状态：开发前基线

版本：V3.2-prep

日期：2026-08-25

本目录是 V3 开发的权威入口。V3 是一次产品级重构：保留 V2 已验证的本地翻译、资源管理、远程 ComfyUI 执行、任务恢复、凭据存储和画廊能力，重新实现提示词核心与完整本地 Web 工作台。

V3 实现位于仓库顶层 [../../v3/README.md](../../v3/README.md)，使用独立包、测试和前端目录；当前 V2 文件保持原位。

## 文档索引

| 文档 | 作用 |
| --- | --- |
| [PRODUCT_BASELINE.md](PRODUCT_BASELINE.md) | 产品目标、范围、页面和候选策略 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 运行时架构、模块边界、离线/联网边界和安全约束 |
| [DATA_CONTRACT.md](DATA_CONTRACT.md) | 数据包、表结构、版本、导入和更新协议 |
| [API_CONTRACT.md](API_CONTRACT.md) | 本地 API、核心对象、错误模型和会话安全 |
| [V2_REUSE_INVENTORY.md](V2_REUSE_INVENTORY.md) | V2 能力的复用、抽离、冻结和重做清单 |
| [PROMPT_CORE_LESSONS_AND_BOUNDARIES.md](PROMPT_CORE_LESSONS_AND_BOUNDARIES.md) | V2 提示词核心复盘、真实测试结论和 V3 输入/编译边界 |
| [EVALUATION_PLAN.md](EVALUATION_PLAN.md) | 与 V2、外部优秀提示词的固定参数对比验收 |
| [OPEN_SOURCE_AND_DATA.md](OPEN_SOURCE_AND_DATA.md) | GPL 发布、第三方代码和外部数据构建边界 |
| [UPSTREAM_SNAPSHOT.md](UPSTREAM_SNAPSHOT.md) | 开发起点采用的上游 commit 与许可检查快照 |
| [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) | 实施顺序、交付物、退出条件和首批任务 |
| [DECISIONS.md](DECISIONS.md) | 已确定的架构决策记录 |

## 权威顺序

发生冲突时按下列顺序处理：

1. 本目录中的 `DECISIONS.md` 和具体契约文档。
2. `PRODUCT_BASELINE.md` 与 `ARCHITECTURE.md`。
3. `DEVELOPMENT_ROADMAP.md`。
4. V2 现有文档和代码行为。
5. 下载目录中的 V3.1 讨论稿及更早讨论记录。

V3.1 讨论稿用于保存思路来源，不再作为直接编码合同。

## 已冻结的产品决策

- V3 主仓库按 GPL-3.0 发布。
- V3 不是在 V2 提示词流水线上继续加功能；旧流水线冻结，仅作兼容和基准对照。
- `danbooru-tag-pipeline` 只在外部构建环境中运行，不复制、不打包进 V3。
- DanbooruSearchOnline 的 GPL 算法和工作区能力允许移植、改造和注明来源。
- Booru Tag Gallery 的 MIT 前端允许改造成 V3 的完整标签与画师网页。
- 保留标签页、标签详情页、画师探索、提示词工作台、候选对比、生图和画廊。
- 标签检索、提示词生成和历史管理离线可用；数据更新、图片预览和远程生图按需联网。
- 每次生成候选必须包含一组“不做共现扩展、不自动加画师”的高保真基准组。
- 画师推荐是可选增强分支，不是所有提示词的强制步骤。
- V3 使用独立的只读参考数据与可写用户数据，数据包更新不得覆盖用户历史。

## 开发启动门槛

开始写 V3 功能前，应满足：

- [x] 产品范围和非目标已记录。
- [x] 架构边界、存储边界和联网边界已记录。
- [x] 数据包和 API 首版契约已记录。
- [x] V2 复用清单已按当前源码盘点。
- [x] 质量对比和退出条件已记录。
- [x] 第三方代码与无许可证外部工具边界已记录。
- [x] 创建顶层 `v3/` 独立工程目录。
- [x] 需要提交开发时创建 V3 开发分支。
- [x] 固定第一批上游 commit 并记录许可检查结果。
- [ ] 正式移植代码时把相应许可证原文和版权 notice 放入仓库。
- [ ] 准备首批外部优秀提示词基准样本。
- [x] 由开发者确认 Phase 1 的任务顺序后开始实现。

外部优秀提示词基准和第三方许可证原文仍需在相应代码移植或正式质量评测前完成；它们不阻塞当前完全自有的领域模型与 literal 主链路开发。
