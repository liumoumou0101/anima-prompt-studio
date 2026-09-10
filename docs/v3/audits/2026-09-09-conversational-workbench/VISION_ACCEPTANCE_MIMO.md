# MiMo-V2.5 视觉验收记录（2026-09-10）

结论：OpenCode Go / mimo-v2.5 确实能读图，但本轮三图质量验收未通过。未切换模型，未使用云 GPU。

## 配置与能力

实际配置目录是启动脚本指定的 `v3/.local/prompt-assistant`。早期脚本读到系统默认目录，误判 Key 未保存；用户原保存操作没有问题。工具已补充 `--config-dir` 和对应测试。已有 Key 原样保留，不写入报告；启用了 supports_vision，ingest_enable_thinking 保持 false。

[小米官方图像理解文档](https://mimo.mi.com/docs/en-US/quick-start/usage-guide/multimodal-understanding/image-understanding) 列出 mimo-v2.5，并支持图片 URL / Base64。[OpenCode Go 文档](https://dev.opencode.ai/docs/go/) 列出相应 Chat Completions 地址。本机使用已保存凭据请求 models 返回 200，包含 mimo-v2.5；这仅验证列表访问，不代替视觉测试。

## 实际调用与修订

共发起 4 次视觉模型请求，外加一次只读 models 查询：

1. 初始三图套件在木刻首图返回 `llm_generation_failed`，立即停止，未执行后两张。报告保存在 `.local/conversation-acceptance/vision-mimo-001`。当次原始输出没有保留，不能断言其具体失败原因。
2. 独立肖像诊断使用 768 px 缩略图。模型识别了男性半身像、胡须、深色衣服及素描特征，但返回了 `subject/lighting` 合并字段。发现 SYSTEM 用该简写表达两个独立层，容易被按字面理解。诊断原文保存在 `vision-mimo-diagnostic.json`。
3. 将 ingest SYSTEM 改为五个独立层的完整 JSON 示例；rewrite 中也分别写出 subject 和 lighting，消除同类歧义。修改后相关 59 项自动测试通过。
4. 修订后重跑完整套件，记录在 `vision-mimo-002`：木刻首图结构通过；肖像第二图返回 `llm_generation_failed`，依规则停止，水彩第三图未调用。第二图具体失败原因尚未定位，不能直接判定模型不支持视觉，也不能将诊断的成功当作该次验收成功。

## 木刻图内容复核

模型正确识别人物、牲畜、远处建筑与分层构图，未添加画师、LoRA 或全局排除项。但以下问题阻止质量通过：

- 将馆藏标注的木刻判断为蚀刻，且没有提示媒介判断存在不确定性。
- 将前景两个人都描述为正在挤奶；画面右侧挤奶动作明确，左侧人物不能据此认定执行相同动作。
- 断言光源来自左上方，证据不足；warnings 为空。

该结果只是未经确认的分析建议，未覆盖官方冻结要求。报告不计为三图完成，不计入 45 次 rewrite 或固定 seed 生图评测。正式质量验收和新入口默认开放仍保持未通过；后续需改进不确定性表达和错误诊断，并保留本轮失败记录。
