# 可重复的文字多轮验收

工具：`anima_prompt_studio_v3.tools.evaluate_conversation`。直接使用生产 ConversationService、WorkspaceStore 和 LLM completion，隔离保存草稿，无标签数据库依赖，不调用生图或向模型发送图片。炭笔场景使用独立 ExampleStore、prompt ingest 与生产 apply_pin；本地图仅供参考库上传及来源哈希。HTTP 认证与请求 DTO 的验证仍由已有 API 集成测试覆盖，不能将本工具运行称作浏览器端到端验证。

在仓库根目录的 PowerShell 执行，默认只预检，不产生模型调用：

```powershell
$env:PYTHONPATH='v3/src;src'
.venv/Scripts/python.exe -m anima_prompt_studio_v3.tools.evaluate_conversation woodcut --config-dir v3/.local/prompt-assistant
```

显式执行一次独立的三轮场景，输出目录必须不存在：

```powershell
.venv/Scripts/python.exe -m anima_prompt_studio_v3.tools.evaluate_conversation woodcut --config-dir v3/.local/prompt-assistant --output .local/conversation-acceptance/woodcut-review-new --execute
```

场景支持 `dual`、`manual`、`detective`、`woodcut`。可加 `--repeats 3`，同一场景最多独立重复三组，共九次 rewrite；默认一组。不自动运行所有场景，不自动换模型、重试或恢复中断请求。木刻最后一轮使用 expand；手改与锁层在第二轮之前进行，不计入 rewrite 次数。

模型对照可加 `--model qwen3.8-max`（必须使用套餐实际可用的模型 ID）。该覆盖只在本次进程生效，预检和实际服务读取同一模型，不写用户配置，结束或异常后恢复原读取器。每个进程只运行一个套件，不在同进程并行使用不同覆盖。所有候选使用相同 SYSTEM 和场景；出现硬约束失败先更换候选，不为了单个模型反复修改通用规则。

`report.json` 记录场景、人工审阅要点、compiler 合同、SYSTEM 哈希、配置模型名及高级参数开关、每轮输入状态/准备动作/实际结果、耗时、错误枚举和持久化恢复。配置模型名不保证代理实际路由，已知偏差需在人工记录注明。Key 和上游异常正文不写报告。报告包含测试提示词和模型输出，放在忽略的 `.local` 目录，不应直接公开真实私有输入。

每次网络调用之前持久化 started，成功或失败后更新报告。失败会停止剩余轮次和重复组；started 残留代表结果不明，不能自动续跑。已有目录拒绝覆盖。成功只代表调用、结构校验及恢复完成，`quality_verdict` 始终是 `pending_manual_review`，每轮 `manual_review` 初始为空。请另行核对要求、正负与 warnings，不能仅靠关键词或 JSON 合法性判定通过。

第五个场景 `charcoal` 已补充：需传 `--reference-image` 指向本地图；先从固定参考提示词提取炭笔要求，人工声明一个明确的测试 LoRA 元数据，再 style pin 到新工作台。第三轮前删掉测试 LoRA，使用空 delta 纯重编译。测试文件名仅为 synthetic fixture，不安装、不解析远端文件、不执行 GPU，不能代替真实 LoRA 效果验证。参考提示词为测试数据，不宣称来自该图片的嵌入元数据或对图片观察准确。每组另有一次 prompt ingest，不计入三次 rewrite；预检显示 planned_prompt_ingests，报告保存准备动作及原始提取结果，准备失败即停止全部后续。

```powershell
.venv/Scripts/python.exe -m anima_prompt_studio_v3.tools.evaluate_conversation charcoal --model qwen3.7-max --repeats 3 --config-dir v3/.local/prompt-assistant --reference-image v3/example-packs/cma-styles-20260910-v1/media/off_cma_166868/original.webp --output .local/conversation-acceptance/charcoal-review-new --execute
```

五个场景仍需各三轮、独立三组的实际结果，不能把模型探针、准备动作或其他模型的结果抵扣，也不包含固定 seed 成图验收。

工具测试覆盖默认无调用/无输出、独立草稿、手改及锁层准备、expand 模式、已有目录拒绝、调用前记录、首个失败停止全部后续及异常脱敏。与会话测试一起共 56 项通过；本轮仅增加验收工具，未修改产品行为。
