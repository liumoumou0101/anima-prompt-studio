# Colab ANIMA 第一版兼容 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 在已有临时连接上完成六款 ANIMA 的云端目录、文件映射、建议参数、真实实例核验和本地出图闭环。

**Architecture:** 云端目录只作当前环境的能力证据，本地模型注册与显式工作流决定支持范围。复用已有连接、鉴权、工作流目录、资源映射、生成队列和设置状态。Notebook 增加单模型准备及实例 ID；MOSS 暂只显示尚未适配。

**Tech Stack:** Python / FastAPI / SQLite / Pydantic；React / TypeScript / Vitest；Colab / ComfyUI / aiohttp。

**Spec:** `docs/superpowers/specs/2026-10-26-colab-model-compatibility-design.md`（本次执行第3、4节和 ANIMA 验收；第5节 MOSS 延后）。

## Global Constraints

- 既有 HTTPS/Bearer、密钥隔离、TLS 与禁止重定向规则不变；POST `/prompt` 不自动重试。
- 只读取同源固定 `/_moss/models`、`/_moss/info` 和标准 ComfyUI API；远端不能注册任意模型或执行下载。
- 不覆盖五款现有 ANIMA 的默认/手动参数或原工作流；仅新增 WAI，复用正式 catalog 的基础图。
- 缓存、映射和晚返回受连接会话、指纹、environment_epoch 保护；无实时身份的连接保持弱身份。
- 保留本机/SSH 与无目录 HTTPS 入口兼容。目录不可用不是普通 ComfyUI 的致命错误；明确运行时 ID 不匹配必须阻止执行/恢复。
- Notebook 保留原模型组选项，增加单模型选项；不删除用户缓存，不重新下载已验证权重，不修改用户原始图片/工作流。
- 产品变更只在当前已附加的隔离工作副本实施；最终按文件比对同步回原项目，不改原项目既有分支和其他未提交内容。

## Review Focus

1. 刷新期间换连接，旧返回不能覆盖新会话状态或保存旧映射（Task 1）。
2. 目录 ready 不是推理成功，未知/MOSS 模型不能凭目录自动提交（Task 1、4）。
3. 子目录同名文件不可取 basename，MiaoMiao 编码器须显式映射（Task 1、2）。
4. 刷新/重渲染不改手动参数；云端建议只改四个采样字段（Task 4）。
5. 相同 URL/密钥下服务重启，实时身份须在任务网络执行前核验，不能只信导入 ID（Task 1、3）。

## Task 1: 云端目录与实时身份后端

**Files:**
- Create: `v3/src/anima_prompt_studio_v3/remote/cloud_model_catalog.py`（有界协议解析与分类路径转换）。
- Create: `v3/src/anima_prompt_studio_v3/runtime/cloud_model_catalog.py`（读取、会话隔离缓存、映射建议与状态）。
- Create: `v3/src/anima_prompt_studio_v3/api/cloud_model_catalog.py`（受保护 API）。
- Modify: `api/app.py` 注册路由；按需要修改 `remote/comfy_client.py`、`remote/connections.py`、`runtime/environment_probe.py`、工作流预检/执行入口。
- Test: 新增 `v3/tests/test_cloud_model_catalog.py`、`test_cloud_model_catalog_api.py`、`test_http_runtime_identity.py`；复用现有探测、连接和队列测试。

**Interfaces:**
- `GET /api/v3/settings/remote-profiles/{remote_id}/model-catalog`：只读缓存。
- `POST /api/v3/settings/remote-profiles/{remote_id}/model-catalog/refresh`：执行有界刷新；错误返回安全消息，不回显密钥。
- 公共响应：`{remote_profile_id, session_id, environment_epoch, status, checked_at, message, runtime_id, items}`；status 为 `unchecked|ready|stale|unavailable|unsupported`。item 至少 `{id,display_name,family,supported,ready,selected_for_startup,suggested_defaults,assets,workflow_mappings}`。`workflow_mappings` 为 `{workflow_profile_id,revision,mapping,errors}[]`，mapping 使用现有 `node.input` 键；无精确枚举匹配不得给出可应用建议。
- `POST .../{remote_id}/model-catalog/apply-mapping`，body `{model_id,workflow_profile_id,session_id,environment_epoch}`：核对当前会话、目录/能力和工作流版本后保存建议，复用现有映射校验；返回当前目录响应。不得默默选择模型/工作流。
- `read_runtime_identity(client, profile)`（具体模块可在所有者内部确定）：认证读取实时 info；无 ID 返回弱证据，有明确期望 ID 时错误/缺失/不匹配拒绝。探测与执行/恢复路径共用，不改变 SSH 身份来源。

- [x] 先补测试：合法目录、越界/穿越/重复/非有限参数、子目录保留、未知模型、404/鉴权/超时、会话晚返回和映射冲突；运行并记录预期失败。
- [x] 实现最大 1 MiB / 最多128模型的目录读取与严格白名单，校验建议 steps1–200 / cfg0–30 与远端 sampler/scheduler 枚举。限制字符串长度，不缓存秘密。
- [x] 目录/工作流映射服务复用实际模型注册和 catalog；保留分类内子目录。缓存签名覆盖当前会话/指纹/epoch，失败后旧成功不能保持 ready。
- [x] 实时身份不得把导入字符串单独提升为 strong。测试同 URL 重启、不匹配时在 prompt/history/view 请求前拒绝；旧网关 info 无 runtime_id 可保持弱兼容。
- [x] 运行该任务及既有临时连接、环境探测、工作流目录、队列相关测试，提交本任务所有权内文件。向界面实施者确认最终 JSON 类型，不更名上述路由。

## Task 2: 六款 ANIMA 模型配置与基础图

**Files:** `v3/src/anima_prompt_studio_v3/core/runtime_profiles.py`、`core/model_versions.py`、`core/generation_recipes.py`、`configs/model_profiles/`、`configs/workflow_profiles/`、`configs/workflow_catalog.json`；相应配置/编译/配方测试。

**Interfaces:** 新增本地模型 ID `wai_anima_v1_0`，family=anima / variant=community；runtime 默认 25 / 4.5 / euler_ancestral / normal；UNet `waiANIMA_v10Base10.safetensors`、TE `qwen_3_06b_base.safetensors`、VAE `qwen_image_vae.safetensors`，明确兼容该模型的单阶段基础工作流。其余五款 ID 与默认不变；云端建议由 Task 1 返回，Task 4 显式应用。

- [x] 先写 WAI 通过 registry/bootstrap/recipe/catalog/compiler 的行为测试并记录失败；不测试单纯文件内容相等。
- [x] 沿现有社区模型模式补注册、基础图、版本信息与配方，不加实验优化节点；核对原有五款配置无行为变化。
- [x] 测试六款基础图在原生节点枚举上通过，以及 MiaoMiao 显式 TE 映射后的实际编译资产正确；复用 catalog 的 ResolutionSelector 清理。
- [x] 运行配置/编译/recipe/catalog 相关测试，提交所有权内文件；报告 WAI profile/workflow 的准确 ID。

## Task 3: Notebook 单模型准备与服务实例身份

**Files:** 新建可复用的 notebook 更新器/源与测试（优先 `tools/colab/`、`tests/` 或项目已有 notebook 目录）；交付可在原 notebook 应用的三个单元源码和完整 `.ipynb`。不在仓库中保存真实连接密钥和输出。

**Interfaces:** 保留 MODEL_GROUP 的 `全部|仅 ANIMA|仅 MOSS`；增加默认“按模型组”的 MODEL_ID 选择及六个 ANIMA/MOSS 的具体 ID。选择具体模型时只准备依赖去重后的资产，目录保留所有模型条目。新 ComfyUI 进程生成随机 `runtime_id`，同活进程重跑保留；网关 info 和 connection.json 返回相同 ID，网关复用同时核对源码与上游 ID。

- [x] 以本地原 notebook 缓存为输入写转换/行为测试，先观察失败：单 Turbo 3 文件、组选择不变、同进程/重启身份、网关复用条件。
- [x] 准备单元展示本次准备/新增所需空间及已有缓存量，不声称 Drive 实际剩余配额；不因缺 MOSS 网页模板阻止 ANIMA。
- [x] 启动/网关实例 ID 保留于本运行时，不从 Drive、旧连接 JSON 或旧死进程继承；不弱化 Bearer、Cookie、TLS 或网关权限。
- [x] 验证所有代码单元可编译、转换后原指令/存储路径/固定依赖保持兼容，运行 notebook 相关测试并提交本任务文件。
- [x] 在实际 Colab 应用前由 root 保留原 notebook 源码副本并审阅差异，随后验证单模型准备和实时 info；启用公网入口前遵循浏览器要求的当场确认。

## Task 4: 工作台模型状态与显式应用

**Files:** 新增 `v3/web/src/components/CloudModelCatalogPanel.tsx` 和 `lib/cloudModelCatalog.ts`（必要时）；修改 `pages/ConversationWorkbenchPage.tsx`、`lib/types.ts` 及相关组件/测试。

**Interfaces:** 消费 Task 1 固定路由/响应。在当前工作流/环境附近显示云端模型信息，支持刷新、为当前兼容模型/图显式应用文件映射；未知/MOSS 显示尚未适配。显式应用当前模型的云端建议时，只更新 steps/cfg/sampler/scheduler，使用现有 creationConfiguration 和设置保存入口；尺寸、Seed、批量、提示词不变。

- [x] 先写组件/状态测试：加载、失败、缺文件/未适配、当前模型与环境切换、请求晚返回、映射成功和冲突；观察预期失败。
- [x] 设置面板不制造独立模型来源：仍使用 bootstrap 已注册模型；展示 ready 为“文件齐全”，不能叫已加载/已验证出图。目录刷新本身不改任何设置。
- [x] 建议参数提供改动预览和显式应用按钮；验证参数 schema/enum 后应用，非法建议不可用。相同来源刷新不重置已编辑参数。
- [x] 当前环境 auto 模式没有确定目标时说明先选环境，不暗中使用其他连接。切换/卸载后忽略旧请求，错误消息不暴露原始连接。
- [x] 运行相关 Vitest/TypeScript；提交本任务文件，并与 Task 1 契约核对。

## Task 5: 整合、独立审查与真实联调

**Files:** 集成修正、测试证据、使用说明与本计划完成标记；只修改审查发现的实际问题。

- [x] 独立审查 Task 1–4；针对重要问题集中修复并复核。
- [x] 运行 V3 后端全套、前端全套、根目录受影响 remote/gallery 测试、TypeScript 和生产构建；确认输出后再称完成。
- [x] 在隔离本地数据库/专用测试凭据中导入真实 Colab 连接，浏览器实际操作模型目录、建议参数、映射和出图；六款 ANIMA 逐款单图归档，额外常用画幅验证。密钥不进入报告、日志或截图。
- [x] 实例验证用已有测试任务和安全的受控重启；不销毁用户数据，不重提含糊的 POST 请求；保留生成结果和参数证据。
- [x] 按改动文件与执行前 baseline 比对后同步至 `H:/soft/提示词工具2`；保留原文件备份，确认构建和文件哈希；不重写用户数据库或覆盖无关变更。
- [x] 补使用说明、实际测试范围与剩余限制；MOSS 不列为本轮已完成兼容。
