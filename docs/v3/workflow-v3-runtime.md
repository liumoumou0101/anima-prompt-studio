# V3 工作流参数执行规则

## 已实现

- V3RuntimeProfiles 独立提供模型默认值，不再查询 V2 ConfigService 的生成配方。
- V3WorkflowCompiler 负责最终图参数注入；队列显式使用该编译器。
- 显式 steps、cfg、sampler、scheduler 优先于任何新旧配方名称。合法性及云端支持检查不通过时报错，不静默替换。
- 前端手动修改标记为 custom；自动解析或切换目标保留自定义参数。明确重新选择配方才应用推荐值。
- 已保存目标的过期配方名称保留参数并转为 custom，不自动重置。
- 高清修复中的高级采样参数修改基础阶段，精修阶段保留模板配置。
- 新增 Base v1.0、Aesthetic v1.0/v1.1 官方模板。资产名称需通过服务器能力检测及显式映射确认。
- 模板 checkpoint 不再被旧 remote.model_aliases 覆盖。任务记录保存最终图及 v3-workflow/1 编译标记。
- 原始正负提示词路径仍保持原文，不暗中追加模型前后缀。

## 兼容边界

SQLite 仓库、SSH/ComfyUI 传输、执行协调器与生图队列的实现已归入 V3，旧适配器导入路径仅作转接。仍复用旧 DTO；图库后处理、旧自然语言工具和翻译服务仍有 V2 依赖。这不是全部 V2 代码的移除。
任务已冻结输入与模板快照，最终图在提交前生成。本次是代码归属迁移，不迁移数据库文件或表结构；入队时最终图冻结尚未实现。
本轮未修改真实用户数据库，未进行付费云端生图或固定 Seed 画质对照；参数正确写入不等于已经证明画质改善。

## 本地验证（2026-09-07）

- 归属迁移后 V3 后端：292 passed，排除 1 项已存在的 LLM 超时取消失败。
- 旧版后端：597 passed，旧版源代码未修改。
- 前端参数及两条生图入口相关测试：14 passed；类型检查通过。
- 前端构建：Node 24.19.0 成功，仍有大于 500 kB 的分包警告。
- 系统 Node 24.11.1 在转换模块后异常退出，临时使用修改前的 generationSettings.ts 亦复现；未修改系统 Node 或锁文件。
- 旧 WorkbenchPage 测试中此前存在的过期 UI 断言未在本轮重写。

后续验收应以相同提示词、负面词、Seed、尺寸做各模型参数对照，核对保存的 actual_workflow 和输出图片，再决定调整推荐配方。

## 维护位置

- `v3/src/anima_prompt_studio_v3/runtime/`：参数准备、生图队列、工作流管理及常驻 ComfyUI 通道管理。
- `v3/src/anima_prompt_studio_v3/remote/`：SSH、ComfyUI 协议、执行协调、凭据及结果落盘。
- `v3/src/anima_prompt_studio_v3/storage/runtime_repository.py`：运行记录与配置持久化，保留 schema version 4。
- `v3/src/anima_prompt_studio_v3/adapters/v2/` 中已迁移的七个模块：通过模块别名转接到同一 V3 实现，兼容旧名称与测试注入，不在这里继续开发。

旧版根包仍保留自己的原实现，以保持 V2 应用可独立运行；V3 主生图链不再导入旧仓库或旧远程服务。
旧 DTO 与序列化 schema 名称保持原样，避免破坏已有任务记录。凭据目标前缀仍为 `AnimaPromptStudio/SSH/` 与 `AnimaPromptStudio/AI/`。
命令行支持 `--runtime-database`（旧 `--v2-database` 继续可用）；桌面入口支持 `--without-runtime`（旧 `--without-v2` 继续可用）。
Python API 的 `v2_database` 参数名暂保留以兼容调用者。V3 远程依赖可在 v3 目录以 `pip install -e ".[remote]"` 安装。

验证覆盖包括原有传输回归、双向数据库读取、表结构不变、凭据命名兼容、旧模块与新模块对象一致，以及禁止主运行时重新依赖 V2 传输和存储的架构测试。
