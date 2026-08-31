# V3 开发交接（2026-09-01）

## 当前分支

- 分支：`codex/v3-development`
- 默认云显卡持久化：`4146ada fix(v3): persist preferred remote GPU`
- 画廊画师 Tag 继承 + 批量彻底删除：`2558f64 fix(gallery): preserve artist tags and delete batches`
- 本交接文档与诊断报告位于上述代码提交之后的最新提交。

## 本轮已完成

1. 默认云显卡选择持久化，前台不再在多个连接间随机跳转。
2. 画廊“同提示词再出图”保留原始画师对照元数据，下载后可继续显示画师 Tag。
3. 画廊支持批量移入回收站、批量从磁盘彻底删除，同时清理缩略图缓存。
4. 完成 20 张自然语言失败族和 8 张受控 A/B 真实云端生成。

详细结论、图片总览、根因和验收条件见：

- `docs/v3/audits/2026-09-01-anime-illustration-quality/REPORT.md`
- `docs/v3/audits/2026-09-01-anime-illustration-quality/cases.json`

## 已验证的测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_gallery_upscale.py v3\tests\test_api.py v3\tests\test_v2_gallery_adapter.py -q
cd v3\web
npm test -- src/pages/GalleryPage.test.tsx
npm run typecheck
```

结果：Python 49 项通过，GalleryPage 5 项通过，TypeScript 类型检查通过。

## 下一个开发任务

先修复自然语言标签污染，不要先继续增加质量词或批量生图。优先级：

1. 禁止普通原文自动确认 character/copyright 类别。
2. 修复跨词子串命中和长语模糊后回落短语的问题。
3. 建立高频人物核心词的最小受控词典。
4. 增加正负向冲突审计。
5. 通过报告中的 `cases.json` 建立 API 回归测试，再跑真实 Aesthetic v1.1 固定 Seed A/B。

完成 P0 后，再做 6 张“无画师 / 3 个固定风格 / 基础与高清细化工作流”对照，目标是从干净动画立绘提升到高细节二次元插画。

## 给下一个代理的建议开场指令

> 请先阅读 `docs/v3/SESSION_HANDOFF_2026-09-01.md` 和 `docs/v3/audits/2026-09-01-anime-illustration-quality/REPORT.md`，再检查 `codex/v3-development` 分支。优先修复 `v3/src/anima_prompt_studio_v3/api/app.py` 的中文本地匹配：普通原文不得自动引入 character/copyright，修复“女孩”、“白色过膝袜”、“性格温柔”、“黑色长发”和“黑色袜子/短袜”回归。使用报告中的 `cases.json` 作为验收基线。不要恢复 AI API 作为默认解析链路，不要自动切换画师。
