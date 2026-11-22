# 文字接口诊断与补测（2026-09-10）

## 定位结果

为结构化 completion 增加安全错误分类后，同套餐 GLM-5.2 完整改写确认是 HTTP 400，而非超时。两次独立短文本诊断均收到 400；第二次检查返回说明，明确写着实际模型 GLM-5.3 是 thinking-only，不允许关闭思考。这是该套餐此次路由的实测证据，不据此更改所有服务商的 GLM-5.2 能力定义。

现在能区分上游 HTTP 拒绝、网络连接错误、超时、格式错误、空结果、截断与响应超限。上游 400/401/403/404/422 不标记可重试。对于代理返回的明确 thinking-only 拒绝，界面提示更换文字模型；不会自动移除参数并重新收费，也不会静默开启思考。400 错误正文只在内存中有界读取最多 16 KiB 用于固定模式分类，不存储或传给前端。公开诊断只包含枚举原因和 HTTP 状态码。

已知 GLM-5.3/Flash 仍在请求前拦截不兼容的关闭思考任务。默认用户配置未变，仍使用 MiMo-v2.5。本轮没有读图或提交生图。

## 双人关系三轮

隔离目录：`.local/conversation-acceptance/case-dual-mimo-003`。真实 API 与 MiMo 调用共三次，均通过结构校验和保存恢复，另对原始返回作语义核对：

1. 两个男人并排，左边不戴帽，右边戴黑帽，木刻、街道；全局负向仅 `text, watermark`。
2. 只改傍晚暖侧光，changed_layers 只有 lighting。人数、左右帽子、背景和风格保留。
3. 只改车站背景，changed_layers 只有 composition。前轮光线与其他要求保留。

最终正向为 `two men standing side by side, left man no hat, right man black hat, train station background, woodcut style, evening warm side light`。帽子没有进入全局 negative，重开数据库 draft 一致。单组成功不代表已达到稳定性或成图验收门槛；此前超时仍计入历史证据。

## 回归

手改用例补测完成，隔离目录 `.local/conversation-acceptance/case-manual-mimo-003`。MiMo 三次调用全部成功：首轮建立短发女子、深蓝外套、街道、水彩；通过真实 PUT 保存手改英文 `wearing a red scarf`，compiled.source 确认为 user；第二轮只改柔和清晨侧光，第三轮换火车站，红围巾、外套、发型、水彩与负向 `text` 均保留。最终正向为 `short-haired woman, dark blue coat, standing at train station, watercolor style, soft morning side light, wearing a red scarf`。此用例首轮把街道写进 subject，因此换背景时 changed_layers 为 subject，内容符合要求；不能机械要求所有背景修改都必须触碰 composition。重开数据库确认 draft 一致，两组语义检查记录分别保存为 semantic-review.json。

本轮总计 9 次模型请求：GLM-5.2 完整改写 1 次、短诊断 2 次、MiMo 双人 3 次、MiMo 手改 3 次。未自动重试，未传图片，未改变默认配置。此次 MiMo 六轮全部成功，但此前 120 秒超时原因仍未被证明，不能宣称稳定性已解决。后续仍需独立重复与设计中的完整场景套件，再做 GPU 成图对照。

新增测试覆盖状态分类、密钥及私有正文不泄漏、无重试、HTTP 客户端超时归类、代理参数拒绝不可重试及草稿保护。本轮后端全量 418 passed，1 条现有依赖弃用警告。前端未修改。
