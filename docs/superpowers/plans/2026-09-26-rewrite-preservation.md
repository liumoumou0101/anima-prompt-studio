# 通用改写保真 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for integration and bounded parallel tasks for source classification and validation.

**Goal:** 通过清晰的输入来源和优先级减少遗漏，保留有效的创意扩写；不增加独立 LLM 审核。

**Architecture:** 服务端将明确输入分为当前约束、兼容历史上下文和已失效选择，随原始要求传给现有单次生成请求。保留格式修复、锁、手工标签和原子保存。来源清单不翻译、不推断任意语义、不按具体题材打补丁。

**Tech Stack:** Python、Pydantic、pytest、现有 LLMService 与 WorkspaceStore。

**Spec:** 用户 2026-09-26 确认移除额外审核、继续优化，并明确接受当前便宜非思考模型的能力边界，不要求百分之百完成度。基线见 `.local/prompt-guidance-general-20260926/baseline-review.md`。

## Global Constraints

- 不添加具体题材分支或中英关键词补丁，不改采样参数与出图流程。
- 手改英文优先级、锁层、字面锁、手工标签和 CAS 继续生效。
- 允许语义等价、适度扩写；不因追求完美而反复采样或增加调用链。
- 移除额外审核的运行时代码、开关和专用测试，仅保留历史实验记录。
- 不改变用户当前模型与思考设置，保留当前未提交工作。

## Review Focus

- 原始 delta 的要求可能已被模型从持久化层中漏掉。
- 来源清单不能把锁、手工标签或独立正文当成过期信息删除。
- 手改英文与旧要求冲突时不能恢复旧内容。
- 已清空的场景控件不能从旧提示词中恢复。
- 正常成功改写仍只调用一次模型；异常格式沿用一次格式修复。

## Tasks

- [x] 在 `core/rewrite_sources.py` 整理确定的来源分类，保留原始字段值；6 项单元回归。
- [x] 移除实验审核接入，保留原来的生成、格式修复及保存流程。
- [x] `test_conversation_sources.py` 验证来源传递、手改优先、失效选择及调用次数。
- [x] 八条固定文本样本各运行一次并逐条复核；7 次完成、1 次上游不完整，明确记录局部越界与台账未同步，未择优采样。
- [x] V3 全量 973 项通过，完成来源分类独立代码审查及文档更新；不自动提交已有未提交内容。
