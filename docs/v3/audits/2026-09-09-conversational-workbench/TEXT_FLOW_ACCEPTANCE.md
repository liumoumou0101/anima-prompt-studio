# 文字参考多轮功能验证（2026-09-10）

结论：一条“已有提示词提取结果 → 人工核对 → 风格钉选 → 新主体 → 锁层 → 改光线 → 改构图 → 保存恢复”的真实接口链路通过。不是 45 次改写套件全部通过，也不代表成图效果通过。全程没有提交生图任务，没有使用 GPU。

## 输入与隔离

使用上次 `prompt-ingest-001` 的真实提取结果，不重复计为本轮新提取。先明确手动纠正其“平行交叉阴影”误译为“密集平行排线（dense parallel hatching）”，保留原始英文作为对照。该人工动作记录在每轮报告的 manual_correction 中。

通过真实 FastAPI 路由、会话认证与 Origin 校验，上传参考副本、创建工作台并 style pin。工作台与参考状态只写入 `.local/conversation-acceptance/text-flow-*`，标签库只读；用户正式草稿和参考库未修改。模型使用用户已保存的 OpenCode Go / mimo-v2.5，图片不传给改写模型。

## 失败与修复

本轮共 5 次真实 rewrite 请求，分为三次明确记录的客户端/协议版本试验，没有后台收费重试：

| 记录 | 请求数 | 结果 |
| --- | --- | --- |
| text-flow-001 | 1 | 首轮 120 秒超时，HTTP 502/llm_timeout；后两轮停止。重开持久库确认草稿完全未变。 |
| text-flow-002 | 1 | 客户端修订后收到结果，但未满足改写响应结构；返回 502，后两轮停止。原始响应未捕获，不能推断具体字段错误。 |
| text-flow-003 | 3 | 补充完整响应 JSON 示例后，三轮成功，原始返回单独保存在隔离目录。 |

排查时修复独立的流式结束问题：传输层收到 SSE `[DONE]` 后立即完成并关闭响应，不再等待服务器断开。新增测试覆盖标记跨网络块、CRLF 与连接继续保持的情况。本轮没有证据证明第一轮超时一定由此造成。

改写 SYSTEM 新增完整 JSON 形状，明确 touched_layers/layer_updates、字符串正负、warnings 数组及返回所有要求的完整英文提示词。没有放宽五层校验或修补模型输出以伪装通过。

## 三轮复核

1. 风格 pin 后主体、光线及排除项为空，没有复制原参考提示词里的两个人、帽子和负向项。首轮另行描述短发女侦探、风衣、右手拿信、车站，要求保留木刻，并排除文字与水印。实际只更新 subject/exclusions，英文保留原先钉选的木刻、黑墨、象牙色纸和平行排线。
2. 通过保存接口锁定 subject/style 后，只要求清晨冷侧光。实际 changed_layers 只有 lighting；锁层内容、人物属性、持信手和风格不变。
3. 只要求半身近景。实际 changed_layers 只有 composition，光线和锁层内容不变。三轮 negative 均为 `text watermark`。

最终英文：

```text
short-haired female detective wearing trench coat holding letter in right hand standing at station early morning cold side light half-body close-up woodcut black ink on ivory paper dense parallel hatching
```

重新 GET 工作台、重新实例化 WorkspaceStore 打开持久库，均与最后一轮 draft 一致。以上判断只涵盖文字和状态；图中左右手、服装、构图及木刻效果仍需后续固定 seed 生图验证。

## 回归与余项

本轮后端全量 405 passed（1 条依赖弃用警告），前端全量 68 passed。完整后端回归在最后一次 SYSTEM 文案强化之前完成；该强化随后通过上述三轮真实调用验证，未改程序分支。之前的类型检查和构建已通过，本轮没有修改前端。

仍需扩大场景和独立重复，覆盖双人局部排除、提示词手改、资源删除与扩写，再做固定 seed 成图对照。先前超时和结构失败必须保留为稳定性证据，不能仅凭最后一轮成功默认开启新功能。
