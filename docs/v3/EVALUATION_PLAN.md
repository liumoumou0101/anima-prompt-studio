# V3 质量评测与放行方案

状态：开发前基线

目标：证明 V3 解决“默认结果不如外部优秀提示词”的原始问题。

## 1. 评测原则

- 提示词字符串正确不等于出图效果正确。
- 共现分和 NPMI 不是画质分，只能解释候选来源。
- A/B 必须使用相同模型、工作流、尺寸、采样器、调度器、步数、CFG 和 seed。
- 先判断语义是否在生成前被破坏，再判断模型是否执行失败。
- 简单场景不能掩盖复杂动作、双人关系、构图和排除项的系统性失败。

现有 [VISUAL_SEMANTICS_BENCHMARK_V1.md](../VISUAL_SEMANTICS_BENCHMARK_V1.md) 继续作为关系与复杂度评测基础，本文件增加 V2、外部参考和 V3 多 lane 对比。

## 2. 基准集组成

### A. 外部优秀提示词集

首批收集 12～20 个已经通过实际图片验证的优秀提示词，覆盖：

- 单人肖像、半身、全身。
- 明确服装和角色。
- 动态动作。
- 室内、城市、自然和复杂背景。
- 双人关系。
- 强风格或画师控制。
- 至少两例纯场景。

每例保存：

```text
case_id
source_title
source_url
source_author
source_prompt
source_negative
source_model/workflow/params（已知时）
normalized_user_intent_zh
required_facts
forbidden_facts
notes
```

若原提示词不适合公开再分发，基准文件保存在本地私有目录，仓库只提交脱敏 case ID、意图和评分，不提交原文。

### B. V2 现有语义集

- `benchmarks/visual_semantics_v1.json`
- `tests/golden_cases.json`
- 已有真实 novel/fidelity 对比材料中可复现的案例

### C. 专项反例集

至少包含：

- 共现推荐容易引入角色或作品泄漏。
- 人数、左右、前后、视线、持物和作用对象。
- 明确否定和用户排除标签。
- 低频但必须保留的视觉概念。
- Aesthetic 不应使用 `score_*` 的模型专用差异。
- Danbooru canonical 与 ANIMA 空格输出差异。

## 3. 对比 lane

每个 case 至少生成：

| Lane | 内容 |
| --- | --- |
| `REF` | 外部优秀提示词原文；仅在模型和参数可比时参与画质排名 |
| `V2` | 当前正式 V2 编译结果 |
| `V3-L` | literal，高保真映射，无共现、无自动画师 |
| `V3-C` | conservative，少量共现扩展 |
| `V3-A` | conservative + 推荐画师 |
| `V3-H` | 标签 + 自然语言关系补充；仅适用 case 启用 |

`V3-L` 是硬基线，任何算法异常都不能让它消失。

## 4. 分阶段执行

当前已提供 `anima-v3-benchmark` 静态 runner 和 `v3/benchmarks/static_v1.json` 起始套件。该套件只负责在开发期持续执行下述编译前硬门槛；案例数量仍需扩展到本文件规定的正式基准规模，且不能替代生图评测。

### 4.1 编译前静态门槛

对所有 case 自动检查：

- required 元素保留率。
- excluded 元素泄漏率。
- 人数、角色、作品和画师位置。
- canonical tag 是否可解析。
- ANIMA 输出空格/下划线规则。
- Base/Aesthetic/Turbo 模板差异。
- lane 差异是否真实存在。
- 每个自动标签是否有 provenance。

硬门槛：

- `V3-L` 的可表达 required 元素保留率必须为 100%。
- excluded 元素进入正向提示词的数量必须为 0。
- 自动添加的 character/copyright tag 如果没有用户或实体解析依据，数量必须为 0。
- 所有画师标签正确渲染 `@`，且只出现在允许画师的 lane。

### 4.2 快速生图筛查

- 每例每 lane 先生成 1 张。
- 同一 case 所有 lane 使用相同 seed。
- 不使用随机 Prompt 扩展、ControlNet 或未列入 case 的 LoRA。
- 保存实际提交的 workflow 和 manifest。

首轮用于发现失败，不用于最终统计结论。

### 4.3 稳定性复测

对首轮存在差异或失败的 case，每 lane 使用 4 个额外相同 seed，形成每 lane 5 张。

外部参考提示词如果依赖不可获得模型或工作流，只作为结构研究，不与 V3 进行错误的同模型排名。

### 4.4 盲评

图片随机化文件名，评审时不显示 lane。每张按以下维度评分：

| 维度 | 分值 |
| --- | ---: |
| 必需事实 | 0–4 |
| 关键关系/构图 | 0–2 |
| 解剖与实体完整性 | 0–2 |
| 禁止失败未出现 | 0–1 |
| 审美偏好 | 0–2，单独统计 |

语义通过仍沿用 0–9 中 8 分以上通过的规则；审美分不用于掩盖关键关系失败。

## 5. 归因

| 现象 | 归因方向 |
| --- | --- |
| V3-L 在提交前已缺少 required | 意图抽取、映射或 renderer 错误 |
| V3-L 正确，V3-C 变差 | 共现扩展或冲突策略错误 |
| V3-C 正确，V3-A 变差 | 画师推荐或画师强度策略错误 |
| V3-H 明显优于纯标签 | 该类关系应优先使用混合表达 |
| 所有 lane 同 seed 均失败 | 模型/工作流能力或 case 超出纯文生图边界 |
| V2 与 V3 都差，REF 好 | 检查参考提示词结构、特殊 token、模型和工作流差异 |

任何算法修复都应针对至少一个可复现失败族，不为单张偶然图片增加特判。

## 6. Phase 放行门槛

### 推荐引擎进入默认候选前

- 在专项反例集中没有新增 character/copyright 泄漏。
- `V3-C` 相比 `V3-L` 的语义通过率不下降超过 5 个百分点。
- `V3-C` 在至少两个不同场景族中表现出可复现正收益。

### 画师 lane 默认展示前

- 画师推荐结果有稳定来源和最小共现量。
- `V3-A` 不覆盖用户锁定风格，不默认混合多个画师。
- 用户可一键移除画师并回到相同的 `V3-C`。

### V3 替代 V2 主入口前

- 固定参数盲测中，V3 默认推荐 lane 相比 V2 的语义通过率至少提高 15 个百分点，或在通过率相近时审美偏好胜率有明确提升。
- 不得有某个关键场景族相比 V2 下降超过 10 个百分点而没有风险提示或回退策略。
- 崩溃、数据损坏、任务丢失和凭据泄漏为 0。
- 远程执行和画廊的 V2 回归测试全部通过。

这些数值在第一次正式基准运行前可以由项目负责人调整一次；开始采样后不得为了通过结果临时降低门槛。

## 7. 记录格式

每次编译保存：

```text
case_id, lane, source_hash, prompt_hash,
data_pack_id, algorithm_version, template_version, model_profile_id,
positive_prompt, negative_prompt, required_result, excluded_result, warnings
```

每张图片保存：

```text
case_id, lane, seed, run_id, workflow_hash,
required_score, relation_score, anatomy_score,
forbidden_score, aesthetic_score, hard_failure, notes, image_path
```

报告按 `family + complexity + model_profile + lane` 汇总，禁止只给一个总平均分。
