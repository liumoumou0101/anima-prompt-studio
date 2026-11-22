# LLM 工作台可行性原型

2026-09-10：后续会话工作台设计见 [CONVERSATIONAL_WORKBENCH.md](CONVERSATIONAL_WORKBENCH.md) 与 ADR-025。该设计尚待实现；旧 `/workbench/prompt` 及本文原型协议保留，参考钉选与多轮编辑另走新端点。下文描述原型现状，不表示新增能力已上线。

本实验仅在 `H:\soft\提示词工具2` 实现。它验证“LLM 忠实英文转换”路线，不宣称已证明真实模型的画质提升。

## 启动与配置

1. 关闭这个实验副本之前打开的服务窗口。
2. 双击项目根目录的 `启动 ANIMA V3.cmd`，打开工作台。
3. 顶部默认展开 **LLM 服务配置（API Key / 模型）**。
4. 选择预设服务商或“自定义 API”，填写 Base URL、实际模型 ID 和 Key。模型名称可以自由输入，预设列表不代表服务商当前一定支持。
5. 点击“保存配置”仅保存；“保存并测试连接”会发出一次真实短文本请求，可能计费。成功仅表示模型能返回内容。

通过本项目启动脚本运行时，LLM 配置独立保存在 `v3/.local/prompt-assistant/config/config.json`，已被 Git 忽略。原有系统级 LLM 配置不会自动复制，首次需要重新填写。显式设置 `ANIMA_PROMPT_ASSISTANT_DIR` 时优先使用指定目录。直接运行 Python 模块而不使用脚本时，仍遵循内核原有的系统用户目录默认值。

Key 仍是本机明文存储，前端读取接口仅返回是否存在和 `***`。更换 API 地址必须重新输入或清除 Key，切换服务商会清空尚未保存的 Key。自定义服务目前提供一个配置槽；本地 Ollama 可在首次创建时选择协议。

## 提示词与生图

- 默认“忠实英文转换”：只转换明确事实，不主动添加主体、画师、镜头或质量套话。
- “适度扩写”：允许兼容的细节补充，要求在审阅提示中说明。
- 描述和“明确排除”一起传入 LLM。返回结构化 `positive / negative / warnings`。
- 局部排除要求保留作用对象，不能一律变成全局负向。该语义依赖 LLM，仍需人工核对。
- 返回格式异常或空正向时明确报错，不会自动提交生图。
- 正、负提示词可编辑。修改原始描述、排除项或处理方式后，旧结果禁止提交，需重新生成。
- 生图使用当前所选模型、远程主机、工作流及高级参数。正负提示词原样进入直出桥接（仅去除首尾空白），不重新词典编译、不自动补默认负面词。
- 负面词为空就保持空。若想沿用质量负面词，请手动加入，且对照组保持完全相同。
- 原有词典候选/画师代码尚未整体清理；它们不参与新的 LLM 主调用链。LLM 结果暂不提供专用历史归档，请复制保存重要结果。

## 公平测试建议

先使用同一个模型与工作流，固定 seed、尺寸、steps、CFG、sampler、scheduler、batch 和 LoRA 状态。分别比较：人工英文基准、忠实转换、适度扩写。每组至少两个 seed。

建议覆盖：水墨白鹤（物种与媒介）、像素机器人照料多肉（对象含义）、木刻两人交接包裹（人物数量与左右关系）、玻璃香水产品（材质与局部景深）、黑白女性侦探（性别、持物动作与构图）。另测“左边男人不戴帽，右边男人戴帽”：不得把全局 `hat` 写入负面词。

先核对最终英文和负面词，再比较图片；否则无法区分语义转换错误与生成模型本身的随机性。

## 自动验证

后端：`python -m pytest v3/tests/test_api.py v3/tests/test_llm_workbench.py v3/tests/test_direct_prompt.py v3/tests/test_v2_generation_adapter.py -q`

前端：`npm --prefix v3/web run test -- src/pages/WorkbenchLlm.test.tsx src/pages/DirectPromptPage.test.tsx src/pages/SettingsPage.test.tsx`

编译：`npm --prefix v3/web run build`

本机验证 Node 24.12.0 会在 Vite 转换完成后异常退出，且保留旧 dist；同一份源码和依赖使用 Node 24.19.0 正常构建。`.nvmrc` 记录已验证版本。若使用其他运行时，请同时检查退出码和 `dist/index.html` 引用的资源是否更新，不能仅看到“modules transformed”就认定编译成功。

本地 HTTP 模拟测试走真实的流式传输内核，验证 URL、认证头、模型 ID、输出语言指令和 JSON 解析；它不证明真实服务商可用，也不评价 LLM 生成质量。真实 Key 与云显卡效果需用户配置后验证。
