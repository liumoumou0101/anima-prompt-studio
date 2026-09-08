# 生成参数检查：2026-09-08

## 修正内容

含 `AnimaNormalizedAttentionGuidance` 或 `AnimaLayerReplayPatcher` 的工作流，现在将整套配方标记为实验。采样参数来自模型作者建议，不代表作者验证过附加社区节点的效果；原先的“作者参数基线”和“稳定基线”显示改为“社区增强对照”。配方 ID 和实际采样数值保持不变。

旧 Turbo 的默认阶段概览同步为实际默认提交的 10 步，避免概览沿用模板中的 12 步。

## 检查范围与结果

- 检查本机保存的 28 个工作流，其中 12 个可供 V3 生成、共 32 套配方。其余复杂导入工作流未被 V3 生图入口开放。
- 4 份主机配置共 128 组本地渲染检查通过。
- RTX 3080 Ti 实机执行 32/32 套配方，使用固定 Seed 20260908、同一机械鸟工作坊提示词、896×1152、批量 1。高清修复输出为 1344×1728。
- 逐项核对已保存的实际提交工作流：正负提示词、尺寸、Seed、批量数、步数、CFG、采样器和调度器与请求一致，32 张下载图片尺寸正确。
- DMDX 请求 10 步的反例在入队前返回 HTTP 422。
- 相关 70 项回归测试通过；阶段概览修正后的 9 项配方测试通过。

实机通过产品的直接提示词 API 与正式生成队列执行。本次是单一提示词和单个 Seed 的对照，不构成跨题材统计排名，也不能证明所有预设都适合成稿。V2 独立 fast/balanced/quality 配置经过代码检查与回归，本次 32 张实图对应 V3 配方。

## 实图结论

| 工作流 | 观察与使用建议 |
| --- | --- |
| 01 Base | 默认画面完整、线条清晰；40 步没有明显整体升级。保留默认。 |
| 02 旧 Turbo | 使用 Base + Turbo LoRA v0.2（0.7）+ 社区增强，不是完整 Turbo v1.1；8 步道具纹理杂乱，适合速度/风格实验。 |
| 04 高清修复 | 34 步基础 + 18 步精修、denoise 0.35、1.5 倍放大正常执行；细节增加，也改变面部及笔触。有放大需求再选。 |
| 05 DMDX | 出图成功，但机械鸟退化成瓶状道具；仅推荐快速预览。 |
| 21/22 Aesthetic | 常规默认可用，Euler 改变构图与风格；增加步数不是统一质量升级。 |
| 23 完整 Turbo v1.1 | 四档均可用，较旧 Turbo 纹理干净；保留 10 步默认。 |
| 24 AnimaYume | 两套配方画面完整；保留 30 / 5.5 / Euler a / normal 默认。 |
| 25 MiaoMiao | 人物和金属鸟清晰；Euler a 样本出现小片伪文字。保留 30 / 4.5 / Euler / normal。 |
| 26 Turbo 社区增强 | 未见稳定升级；12 步道具更偏怪异机械形状。优先 23。 |
| 27 AnimaYume 社区增强 | 两档明显变软，背景与道具失真，弱于基础工作流。优先 24。 |
| 28 MiaoMiao 社区增强 | 纹理偏软，部分对照出现围裙伪文字。优先 25。 |

常规默认参数可作为日常生成起点。DMDX、旧 Turbo 增强链以及 26–28 不应作为统一高质量选项；更多步数和更多节点都不保证更好。

## 参数依据

- [ANIMA 官方模型卡](https://huggingface.co/circlestone-labs/Anima)：Base/Aesthetic 建议 30–50 步、CFG 4–5；Turbo 使用 CFG 1、8–12 步。
- [Comfy-Org Base 模板](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_anima_base_v1.json)：30 / 4 / er_sde / simple。
- [AnimaYume 发布页](https://huggingface.co/changan2026/AnimaYume)：25–40 步、CFG 4–7、Euler a / normal。
- MiaoMiao 保留项目历史验证基线；本次原始 Civitai 页面无法读取，未根据混合版本的转载说明调整 CFG。

## 本地复核工具

在已安装项目依赖的环境下运行：

```powershell
python tools/audit_generation_parameters.py
python tools/audit_generation_parameters.py reports/<实机报告目录>/report.json
```

第一条命令只读检查本机数据库并生成渲染报告，不提交远程任务；第二条核对已有配方验收报告对应的实际提交记录和下载图片。原始本地报告与图片保留在被 Git 忽略的 `reports/`，不随源码发布。
