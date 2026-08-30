# V3 收尾会话交接（2026-08-30）

## 当前状态

- 分支：`codex/v3-development`
- HEAD：`84174a6b7d06`
- 工作区仍有本轮与此前标签、画师、画廊和工作台开发改动，尚未提交。
- `tools/_*.py` 真实验收脚本属于现有未跟踪文件；不要在收尾时顺手删除或提交，除非逐项确认用途。
- 本地工作区数据库中保留了“关系确认验收”revision 1，供打开检查确认关系与 Hybrid 恢复。

## 产品决策

当前 ANIMA 纯提示词功能进入冻结与收尾。下载的标签组、Tag–Tag 和 Artist–Tag 数据继续支持标签浏览、分类、相关标签、画师推荐和画师场景分析，但共现数据不被解释为实体关系。

不再为多人动作、左右/前后、接触轨迹或复杂事件扩展通用 schema。只有直接 canonical 标签，或用户明确确认且经固定 Seed 证明稳定有效的关系表达，才允许进入正式候选。模型不能稳定执行的内容应显示边界，不继续增加提示词特判。

下一正式阶段可评估 Illustrious（光辉系）和 Pony 模型族兼容，必须使用独立 ModelProfile 与工作流合同。区域提示、姿势控制、局部重绘等 ComfyUI 操作下沉属于更后续正式版本。

## 本轮完成

- Scene Draft 事实分层、实体锚点与人工属性归属。
- 服装归属确认后单独建议并确认 `wearing`；确认关系只影响 ConstraintGraph 与 Hybrid，Literal 不变。
- 关系、归属和候选可随工作台快照保存、刷新和重新打开。
- 修复自然语言候选保存时把临时 `local_translation` 元数据写入严格快照合同导致的 422。
- 修复刷新后已保存工作台错误显示为“未保存”；恢复数据现在保留工作台 ID 与 revision，不重复保存整份服务器记录。
- 标签三层浏览、未分组安全/NSFW 筛选、画师搜索/详情、画师 1～20 人固定 Seed 对照等此前开发均保留。

## 2026-08-30 验收结果

- V3 Python：88 passed。
- V2 Python：全量通过（现有 585 项基线）。
- V3 Web：30 passed。
- TypeScript 与 Vite production build：通过。
- 静态门槛：required 8/8，excluded 泄漏 0，受保护角色/版权泄漏 0，validator 错误 0。
- `git diff --check`：无空白错误，只有 Windows LF→CRLF 提醒。
- 真实浏览器：打开“关系确认验收”r1，刷新后仍显示 r1；Scene Draft、归属、确认关系、Literal 与 Hybrid 均无需重新编译即可恢复。
- 新增四图固定 Seed 收尾脚本 `v3/tools/run_finish_image_smoke.py`；干跑与语法检查通过，默认不会提交远程任务。
- 2026-08-30 首次实跑的 4 个任务均在读取 SSH banner 时失败，未进入 ComfyUI、未生成图片。随后连续 3 次只读 TCP 探测均连接成功但立即收到空响应，表明保存的远端入口当前没有提供 SSH 服务。
- 脚本已补上提交前 SSH banner 预检，以及“未全部 completed 即非零退出”规则，避免远端未就绪时继续制造失败队列。
- 3080 Ti 初始化完成后以 `--suffix 20260830b` 复跑成功：Aesthetic v1.1 四图矩阵 4/4 completed、4 个文件均下载、错误 0。
- 关系组确认 Literal 与 Hybrid 都能表现灵梦穿女仆装及神社；Hybrid 没有解决同角色多人/多视图重复，故 `wearing` 继续作为可选、可取消的确认表达。
- `@himadera` 画师组中，保留/移除负向 `artist name` 未产生明显风格削弱差异；移除版本右下角出现署名伪文字，决定继续保留默认 `artist name`。
- 机器报告：`reports/v3_finish_image_smoke_20260830_134608_20260830b/report.json`；人工复核：同目录 `visual-review.md`。
- 面向产品真实目标新增 5 组精致二次元插画探索；Aesthetic v1.1 / 3080 Ti 5/5 completed。
- `樱暮神社 @mocha_(cotton)`、`雨夜霓虹 @gemi`、`深海书库 @makoron117117` 是当前最值得保留的三条效果基线；前两条偏人物与氛围，后一条偏宏大场景。
- `星空冰术 @vinartwork` 出现极小署名样伪文字，`雪夜灯影 @pochi_(poti1990)` 暴露手部与提灯关系不稳；两者作为模型边界样本保留。
- 五图报告和人工复核位于 `reports/v3_anime_illustration_exploration_20260830_135823_20260830a/`；可复跑脚本为 `v3/tools/run_anime_illustration_exploration.py`。

## 已知边界

- Marian 首次按需加载曾出现约 1 分半；后续复用译文的归属和关系操作约 1～2 秒。本轮按产品决定只记录，不扩成性能项目。
- `wearing` 是关系基础设施和单一可审查切片，不代表 ANIMA 已稳定解决多人属性绑定。
- 画师正向 `@artist` 与负向 `artist name` 是否互相削弱仍需固定 Seed 实图决定。
- 当前静态门槛只证明编译合同，不替代图片质量和关系执行率。
- 四图只证明本轮固定 Seed 下的定向结果，不代表 ANIMA 已解决通用实体绑定或复杂关系执行率。
- 数据包联网分发、正式安装包地址和发布索引仍未完成。

## 推荐收尾顺序

1. 按 [../../v3/RELEASE_FINISH_CHECKLIST.md](../../v3/RELEASE_FINISH_CHECKLIST.md) 执行固定 Aesthetic v1.1 Seed 图像验收。
2. 优先比较 Literal/Hybrid、直接动作标签，以及画师任务保留/移除负向 `artist name`。
3. 记录成功率和失败图片，不为单张偶然结果增加规则。
4. 复核生成、恢复、再生成、放大和安装包路径后，再决定提交与发布候选。

## 常用命令

```powershell
# V3
Set-Location D:\soft\提示词辅助工具\v3
..\.venv\Scripts\python.exe -m pytest -q

# V2
Set-Location D:\soft\提示词辅助工具
.\.venv\Scripts\python.exe -m pytest -q

# Web
Set-Location D:\soft\提示词辅助工具\v3\web
npm test -- --run --reporter=dot
npm run build

# 静态门槛
Set-Location D:\soft\提示词辅助工具\v3
..\.venv\Scripts\python.exe -m anima_prompt_studio_v3.tools.run_static_benchmark `
  --suite benchmarks\static_v1.json `
  --reference-db .local\data\packs\anima-v3-dso-0636f762-r1\reference.db

# 四图效果验收（默认干跑；加 --execute 才远程提交）
Set-Location D:\soft\提示词辅助工具
.\.venv\Scripts\python.exe .\v3\tools\run_finish_image_smoke.py
.\.venv\Scripts\python.exe .\v3\tools\run_finish_image_smoke.py --execute --suffix <本轮标识>
```

## 敏感信息

- 不提交 V2 用户数据库、私钥、passphrase、API Key、远程主机凭据或浏览器会话。
- 本轮文档与代码没有新增凭据。
