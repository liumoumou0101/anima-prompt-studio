# 真实服务验收 · 2026-09-10

用户授权使用云端 RTX 3080 Ti 和临时 OpenCode Key。验收配置/输出放在不进入版本库的 .local/conversation-acceptance。Key 未写入文件、命令行参数或应用配置，测试进程已结束；未自动撤销服务商侧 Key。

## 改写

OpenCode Go / MiMo-V2.5 的 /zen/go/v1/chat/completions 成功完成两轮实际请求。其他模型可能使用 Responses 或 Anthropic Messages；不能据此声称全部协议兼容。[OpenCode Go 文档](https://opencode.ai/docs/go/)

第一轮：雨后街道、短发女侦探、右手拿信、水彩插画、柔和傍晚侧光。返回四层内容，workspace revision 2。第二轮：人物动作不变，改清晨柔光，不要文字。仅改 lighting/exclusions，negative=text，revision 3。无自动重试，未执行真实视觉 ingest 调用。

## 生图与收藏

沿用已保存的 SSH 身份校验连接 ComfyUI，设备 RTX 3080 Ti / 12 GB。Anima Base v1，768×768，20 steps，CFG 4.5，er_sde / normal，seed 20260910，batch 1。

手动编译场景经 conversational 提交 API、持久日志/队列、SSH/ComfyUI 完成。该图并非前述 LLM 输出的自动后续执行。run b711b65c-37a0-4699-8dae-c3731562115b 从 draft/preparing/running 到 completed，下载一张。重复相同幂等请求返回完全相同回执，未再次采样；工作台与产物查询通过。

from-run 收藏与原文件字节一致，要求取自接受快照；风格 pin 到空工作台后主体仍为空。画面可见水彩、深蓝外套短发女侦探、雨后街景与信件；左右手关系未作严格质量通过判定。

本次真实验收发生时，官方包、reference-presets、独立 reference 提交、完整参考要求编辑界面及映射引导仍待实施。上述协议及界面后续已完成离线实现与回归，见 `v3/STATUS.md`；这不补充任何真实模型质量证据。两项发布 flags 继续关闭，后续真实质量验收按 [执行单](QUALITY_ACCEPTANCE_PLAN.md) 进行。
