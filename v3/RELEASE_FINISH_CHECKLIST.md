# V3 ANIMA 收尾清单

更新日期：2026-08-30

## 功能冻结

- 不再新增通用多人关系、空间方向或复杂事件 schema。
- 直接标签、人工确认关系和模型配置必须保持可追踪、可取消。
- Literal 不接受共现、画师或风格建议的静默写入。
- Hybrid 只承载用户保留的画面计划和显式确认关系。

## 自动化放行门槛

- V3 Python 全量测试通过。
- V2 Python 全量回归通过。
- Web 全量测试、TypeScript 与 production build 通过。
- 静态 benchmark required 保留率 100%，排除泄漏、受保护类别泄漏和 validator 错误均为 0。
- `git diff --check` 无空白错误；Windows 换行提醒不计为失败。

## 真实操作门槛

- 自然语言首次编译成功；Marian 首次加载较慢时不丢输入或候选。
- 归属与关系分开确认，Literal 不变，Hybrid 只增加已确认关系。
- 工作台保存、刷新、revision 恢复和数据库重新打开成功。
- 画师 1～20 人对照保持相同模型、工作流、尺寸、预设和 Seed。
- 远程生成、失败恢复、画廊归档、再生成和放大至少各复核一条已验证路径。

## 效果验收

- Aesthetic v1.1 下固定 Seed 比较 Literal、Hybrid 和画师对照。
- 对直接动作标签只验证 ANIMA 实际执行率，不从共现数据推断实体关系。
- 单人物、明确排除、角色服装、简单动作和双人物绑定分别保留失败样本。
- 模型不能稳定执行的关系记录为边界，不继续增加提示词特判。
- 画师正向标签与负向 `artist name` 是否互相削弱必须通过实际图片决定。

### 当前执行状态（2026-08-30）

- 已新增 `v3/tools/run_finish_image_smoke.py`：默认仅打印四图矩阵，只有显式传入 `--execute` 才提交远程任务。
- 四图矩阵固定使用 Aesthetic v1.1、1024×1024，并分别锁定关系对照 Seed 与画师负向词对照 Seed。
- 首次提交的 4 个任务均在 SSH banner 阶段失败，没有进入 ComfyUI，也没有生成图片；这不能计为效果失败或通过。
- 脚本现已增加提交前 SSH banner 预检，并在任一任务未完成时返回非零退出码。
- 云实例启动且 SSH 地址/端口刷新后，执行：

```powershell
Set-Location D:\soft\提示词辅助工具
.\.venv\Scripts\python.exe .\v3\tools\run_finish_image_smoke.py --execute --suffix <本轮标识>
```

### 3080 Ti 复跑结论（2026-08-30）

- 实例初始化完成后 SSH 预检通过，4/4 任务经 Aesthetic v1.1 完成并各下载 1 张 1024×1024 图片，报告错误数为 0。
- Literal 与确认 `wearing` 的 Hybrid 都正确表现博丽灵梦、女仆装和神社；Hybrid 未消除同角色多人/多视图重复，因此继续作为可选表达，不替代 Literal。
- `@himadera` 对照中，保留/移除负向 `artist name` 的整体风格与构图高度接近；移除后出现右下角 `@himad...` 署名伪文字，保留时没有。
- 当前 Aesthetic 配置继续保留 `artist name`；明确不要对话框、文字或水印时仍由用户排除项表达，不静默扩大默认负向词。
- 机器报告与人工视觉结论分别位于 `reports/v3_finish_image_smoke_20260830_134608_20260830b/report.json` 和 `visual-review.md`。

### 精致二次元插画探索（2026-08-30）

- 新增 `v3/tools/run_anime_illustration_exploration.py`，默认仅本地编译，显式 `--execute` 才提交 5 个远程任务。
- Aesthetic v1.1 / 3080 Ti 实跑 5/5 completed，覆盖樱暮神社、雨夜霓虹、星空冰术、深海书库和雪夜灯影五种独立视觉方向。
- `樱暮神社 / 雨夜霓虹 / 深海书库` 已达到较完整的单张二次元插画效果，可作为人物环境、都市氛围和幻想场景基线。
- `星空冰术` 仍出现极小署名样伪文字；`雪夜灯影` 的手部与提灯动作关系不稳定，作为真实失败边界保留。
- 机器报告与视觉复核位于 `reports/v3_anime_illustration_exploration_20260830_135823_20260830a/`。

## 后续版本边界

- 下一正式阶段可评估 Illustrious（光辉系）与 Pony 模型族兼容，使用独立 ModelProfile 和工作流合同。
- 更后续正式版本再评估把区域提示、姿势控制、局部重绘等 ComfyUI 操作编排下沉到工具中。
- 后续模型适配不反向污染当前 ANIMA 配置、数据包或回归基线。
