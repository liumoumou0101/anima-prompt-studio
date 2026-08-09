# ANIMA Prompt Studio V2：云端 ComfyUI 执行设计

状态：设计草案  
日期：2026-08-09

实施状态：V2 Beta 的阶段 A 已完成本地实现和模拟协议测试；真实云主机兼容性验收待执行。联调准备见 `V2_REAL_SERVER_TEST_CHECKLIST.md`。

## 1. 目标

V2 在保留 V1 本地提示词编译能力的基础上，增加一条完整的远程生图闭环：

1. 通过 SSH 安全连接云主机。
2. 通过 SSH 隧道调用云主机上的 ComfyUI API。
3. 提交由当前 `PromptJob` 编译出的提示词、模型和生成参数。
4. 展示排队、执行、下载和失败状态。
5. 生图完成后自动下载全部输出到本地。
6. 按项目、主体类型、模型和日期自动归档，并保存可追溯元数据。
7. 软件重启或网络中断后可以恢复未完成任务。

V2 不把业务逻辑绑定到某一家云厂商，也不要求把 ComfyUI 端口暴露到公网。

## 2. 核心判断

### 2.1 SSH 负责安全通道，ComfyUI API 负责生图

推荐链路：

```text
ANIMA Prompt Studio
    │
    ├── SSH 登录云主机
    │     └── 本地 127.0.0.1:随机端口
    │             转发到云端 127.0.0.1:8188
    │
    └── ComfyUI API
          ├── 提交 API 格式工作流
          ├── WebSocket 接收进度
          ├── History 查询最终输出
          └── View 下载图片
```

这样有三个直接好处：

- 云主机只需要开放 SSH 端口，ComfyUI 可以继续监听 `127.0.0.1`。
- 不需要在云端安装 ANIMA Prompt Studio 的 Agent。
- ComfyUI 的执行、排队、历史和输出协议由官方 API 负责，软件只做客户端。

SSH 命令通道只用于连接测试，以及可选的 ComfyUI 启动/状态检查。常规生图不通过拼接 Shell 命令完成。

### 2.2 V1 已经留出了正确的扩展点

当前 `src/anima_prompt_studio/execution.py` 已定义 `ExecutionTarget`，V2 应扩展这一边界，而不是把远程逻辑塞进 `MainWindow` 或提示词 `PromptPipeline`。

建议的职责边界：

```text
PromptPipeline
    └── 只负责生成权威 PromptJob

ExecutionCoordinator
    ├── WorkflowRenderer
    ├── SshTunnel
    ├── ComfyUIClient
    ├── GenerationRunRepository
    └── ResultOrganizer
```

## 3. V2 MVP 范围

第一版优先完成最短、稳定的纵向闭环：

- 保存多个云主机配置。
- 支持 SSH 私钥和密码认证。
- 首次连接显示并确认主机指纹；后续拒绝指纹变化。
- 建立到云端 ComfyUI 的 SSH 本地端口转发。
- 检查 ComfyUI 是否在线、GPU 信息、队列状态和必需节点。
- 导入一个 ComfyUI “API Format”工作流模板。
- 将正向、负向、宽高、步数、CFG、采样器、调度器、种子、批量数和模型映射进模板。
- 提交任务并显示排队/执行进度。
- 自动发现并下载该任务产生的全部图片。
- 按分类规则保存图片、任务清单和实际提交的工作流。
- 网络中断或软件重启后，根据远程 `prompt_id` 恢复查询和下载。

当前版本只执行已经完成真实端到端测试的基础文生图工作流。优云智算 Anima Omni v2.0 镜像中已验收 `01 基础高质量`、`02 极速文生图`、`05 四步 DMDX`，以及在对应权重存在时自动派生的 `21 Aesthetic v1.0`和 `22 Aesthetic v1.1`。镜像的其余编号工作流仍会被发现、列出并允许选择查看，但生成按钮会停用；Control、局部重绘、图生图、细节修复和放大等复杂链路的参数适配留到下一版本。

暂不放进首个 MVP：

- 自动安装或升级 ComfyUI、模型和自定义节点。
- 任意远程 Shell 控制台。
- 多台云主机自动调度和负载均衡。
- 输入图片上传、ControlNet、局部重绘和视频工作流。
- 在多用户共享 ComfyUI 上强制中断正在运行的全局任务。

这些能力可以在远程执行主链路稳定后逐步增加。

## 4. 配置模型

### 4.1 云主机配置 `RemoteProfile`

建议字段：

| 字段 | 含义 |
| --- | --- |
| `id` | 本地稳定 ID |
| `provider_preset_id` | 云平台连接预设；默认优云智算容器实例，也可切换 Ubuntu 或其他云主机 |
| `display_name` | 例如“东京 4090” |
| `ssh_host` / `ssh_port` | SSH 地址与端口 |
| `ssh_user` | SSH 用户 |
| `auth_type` | `private_key` 或 `password` |
| `private_key_path` | 私钥路径，不复制私钥内容 |
| `known_host_fingerprint` | 首次确认后的主机指纹 |
| `comfy_host` | 默认 `127.0.0.1` |
| `comfy_port` | 默认 `8188` |
| `startup_mode` | `manual`、`systemd` 或 `command` |
| `startup_command` | 可选，用户明确配置的启动命令 |
| `model_aliases` | 本地逻辑模型到云端文件名的映射 |
| `enabled` | 是否可用 |

密码和私钥口令不写入 SQLite、JSON、日志或导出任务包。优先使用系统凭据库；用户也可以选择每次连接时输入。

### 4.2 工作流配置 `WorkflowProfile`

ComfyUI 的普通 UI 工作流 JSON 不能原样提交，但 V2 可以通过节点、连线和 widget 元数据把基础前端工作流转换为 API Format。优云智算预设会通过 SSH 自动读取镜像的 `user/default/workflows`；其他云主机仍支持用户直接导入 API Format。V2 保存转换后的工作流副本以及字段绑定：

```json
{
  "id": "anima_turbo_api_v1",
  "display_name": "ANIMA Turbo 标准工作流",
  "api_workflow_file": "anima_turbo_api_v1.json",
  "bindings": {
    "positive_prompt": {"node_id": "6", "input": "text"},
    "negative_prompt": {"node_id": "7", "input": "text"},
    "checkpoint": {"node_id": "4", "input": "ckpt_name"},
    "seed": {"node_id": "3", "input": "seed"},
    "steps": {"node_id": "3", "input": "steps"},
    "cfg": {"node_id": "3", "input": "cfg"},
    "sampler": {"node_id": "3", "input": "sampler_name"},
    "scheduler": {"node_id": "3", "input": "scheduler"},
    "width": {"node_id": "5", "input": "width"},
    "height": {"node_id": "5", "input": "height"},
    "batch_size": {"node_id": "5", "input": "batch_size"},
    "filename_prefix": {"node_id": "8", "input": "filename_prefix"}
  }
}
```

节点 ID 不应写死在 Python 代码中。导入工作流时立即验证：

- 节点 ID 和输入字段是否存在。
- 云端 `/object_info` 是否包含工作流需要的节点类型。
- 逻辑模型是否能映射到云端真实 checkpoint。
- 当前模板是否支持所选 LoRA。

首个 MVP 对 LoRA 采用“模板插槽”方案：工作流提前准备固定数量的 LoRA Loader 节点，绑定配置描述每个插槽。后续再实现动态插入和连接 LoRA 节点，避免第一版图结构改写过于复杂。

## 5. 远程执行流程

### 5.1 连接检查

1. 解析并验证云主机配置。
2. 建立 SSH 连接并验证主机指纹。
3. 将本机随机端口转发到云端 `127.0.0.1:8188`。
4. 通过隧道请求 ComfyUI `/system_stats`。
5. 请求 `/object_info`、模型列表和 `/queue`，形成环境检查报告。
6. 如果 ComfyUI 未运行，仅在用户配置并授权后执行固定启动命令，再重试健康检查。

### 5.2 提交任务

1. UI 先执行现有 `_sync_and_recompile()`，得到最终 `PromptJob`。
2. 创建本地 `GenerationRun`，状态写为 `preparing`。
3. 深拷贝 API 工作流模板。
4. 使用绑定配置注入 Prompt、参数、模型、LoRA 和唯一输出前缀。
5. 保存本次实际提交的工作流快照。
6. `POST /prompt`，保存返回的 ComfyUI `prompt_id`，状态改为 `queued`。
7. 通过 `/ws?clientId=...` 监听状态和节点进度。
8. WebSocket 断开时退化为轮询 `/history/{prompt_id}`，而不是判定任务失败。

### 5.3 完成和下载

1. 从 `/history/{prompt_id}` 读取该任务所有输出节点。
2. 收集其中的 `filename`、`subfolder` 和 `type`。
3. 通过 `/view` 下载每个输出。
4. 先写入同目录的 `.part` 临时文件。
5. 校验响应类型、文件大小和 SHA-256 后原子改名。
6. 写入 `manifest.json` 和实际的 `workflow_api.json`。
7. 将任务状态改为 `completed`。

任何阶段失败都保留 `prompt_id`、当前状态和错误信息。用户可以执行“重试检查”“继续下载”，不需要重复生图。

## 6. 任务状态与恢复

建议状态机：

```text
draft
  → connecting
  → preparing
  → queued
  → running
  → downloading
  → completed

任一活动状态 → failed
queued → canceled
running → cancel_requested → canceled / completed
```

关键规则：

- `remote_prompt_id` 一旦取得必须立即落库。
- 应用启动时扫描 `connecting` 到 `downloading` 的未终结任务。
- 有 `prompt_id` 的任务先查询远端 history；已经完成则只补下载。
- 下载按远程输出标识和哈希去重，不覆盖已有文件。
- 如果远端 history 已被清理，将任务标记为 `remote_missing`，保留本地记录并给出明确提示。
- “取消正在运行的任务”可能影响共享 ComfyUI 的当前执行，默认只允许取消仍在队列中的本软件任务；全局 interrupt 必须单独确认。

## 7. 本地分类和文件管理

默认根目录：

```text
%USERPROFILE%\Pictures\AnimaPromptStudio
```

默认分类模板：

```text
{project_name}\{subject_mode}\{model_profile}\{date}\{time}_{run_id}
```

实际示例：

```text
AnimaPromptStudio/
└── 雨夜少女/
    └── character/
        └── anima_turbo_v1/
            └── 2026-08-09/
                └── 173015_a1b2c3d4/
                    ├── 雨夜少女_173015_seed42_01.png
                    ├── 雨夜少女_173015_seed42_02.png
                    ├── manifest.json
                    └── workflow_api.json
```

用户可以在设置中调整分类模板，但只开放受控占位符：

- `{project_name}`
- `{subject_mode}`
- `{model_profile}`
- `{quality_profile}`
- `{date}`
- `{year_month}`
- `{run_id}`

文件管理规则：

- 清理 Windows 非法字符、保留名、尾部空格和尾部句点。
- 限制单段长度，避免路径过长。
- 同名文件追加序号，绝不静默覆盖。
- 图片保持 ComfyUI 原始字节，不二次编码。
- `manifest.json` 保存项目、Prompt、生成参数、种子、工作流、云主机配置 ID、ComfyUI `prompt_id`、原始远程文件名、哈希和本地路径。
- 清单不包含密码、私钥、口令或完整 SSH 命令。

## 8. 数据库迁移

现有 SQLite schema 从版本 1 升级，新增以下表：

### `remote_profiles`

保存非敏感的云主机配置和模型别名。

### `workflow_profiles`

保存工作流名称、版本、模板位置、绑定配置和校验结果。

### `generation_runs`

建议字段：

- `id`
- `prompt_job_id`
- `remote_profile_id`
- `workflow_profile_id`
- `remote_prompt_id`
- `client_id`
- `state`
- `progress`
- `created_at` / `updated_at` / `completed_at`
- `output_dir`
- `error_code` / `error_message`
- `request_json`

### `generation_artifacts`

建议字段：

- `id`
- `generation_run_id`
- `node_id`
- `remote_filename`
- `remote_subfolder`
- `remote_type`
- `local_path`
- `sha256`
- `byte_size`
- `mime_type`
- `download_state`

迁移前沿用当前机制备份旧数据库。旧 `PromptJob` 历史不需要重写。

## 9. 代码结构

建议新增：

```text
src/anima_prompt_studio/
├── domain/
│   └── execution_models.py
├── execution.py
├── repositories/
│   └── generation_repository.py
├── services/remote/
│   ├── ssh_tunnel.py
│   ├── comfy_client.py
│   ├── workflow_renderer.py
│   ├── execution_coordinator.py
│   └── result_organizer.py
└── ui/
    ├── remote_profile_dialog.py
    ├── workflow_profile_dialog.py
    ├── generation_panel.py
    └── generation_history_dialog.py
```

推荐依赖作为可选安装项 `remote`：

- `paramiko`：SSH、主机密钥验证和端口转发。
- `requests`：ComfyUI HTTP API。
- `websocket-client`：实时进度。
- `keyring`：系统凭据库，可选；不可用时每次输入口令。

远程执行必须在后台工作线程运行，通过 Qt signal 更新 UI。不得在主线程执行 SSH、HTTP、WebSocket、哈希计算或大文件写入。

## 10. UI 方案

主窗口增加一个“远程生成”区域：

```text
[云主机 ▼] [工作流 ▼] [连接测试]
[生成并自动下载] [取消排队] [打开输出目录]

状态：已连接 · RTX 4090 · 队列 1
任务：运行中 · KSampler · 63%
输出：D:\Pictures\AnimaPromptStudio\...
```

同时增加：

- “设置 → 云主机管理”
- “设置 → ComfyUI 工作流管理”
- “查看 → 生成任务”
- 任务列表中的“重试检查”“继续下载”“打开目录”“复制错误详情”

点击“生成并自动下载”前显示一次摘要：目标云主机、工作流、模型映射、尺寸、批量数和本地保存位置。确认后，本次任务的参数快照固定；用户继续编辑当前 Prompt 不会改变已入队任务。

## 11. 安全要求

- ComfyUI 默认仅监听云端回环地址，通过 SSH 隧道访问。
- 不提供“忽略所有主机密钥错误”的永久选项。
- 首次连接展示 SHA-256 指纹，明确确认后保存。
- 私钥文件只保存路径，不读取后复制到程序数据目录。
- 密码和口令不进入 SQLite、任务 JSON、异常消息或日志。
- 自定义启动命令必须由用户手工配置；软件不根据服务器返回内容拼接命令。
- API 下载返回的路径字段仅作为远程查询参数，本地文件名重新清理，防止路径穿越。
- 请求和下载设置连接、读取和总时限，并支持取消。

## 12. 测试策略

### 单元测试

- 工作流绑定和参数注入。
- 模型别名解析和缺失提示。
- Windows 文件名清理、分类路径和防覆盖。
- 状态机合法迁移。
- History 输出解析和下载去重。
- 敏感字段不会进入序列化结果或日志。

### 协议测试

使用本地假的 ComfyUI HTTP/WebSocket 服务覆盖：

- 提交成功、校验失败和节点错误。
- 排队、进度、完成、执行失败。
- WebSocket 断开后轮询恢复。
- 多输出节点和批量图片。
- 下载中断、续传或重新下载。

SSH 层通过可替换接口测试，不在普通测试中依赖真实云主机。

### 真实环境验收

1. ComfyUI 只监听云端 `127.0.0.1:8188`，公网无法直接访问。
2. 软件通过 SSH 隧道完成连接检查。
3. ANIMA Turbo API 工作流成功生成至少两张图。
4. 两张图自动下载到正确分类目录，图片可打开。
5. `manifest.json` 中参数与实际提交一致。
6. 生图中关闭软件，再启动后能恢复并完成下载。
7. 错误私钥、主机指纹变化、模型缺失、节点缺失都有可理解的中文错误。

## 13. 推荐实施顺序

### 阶段 A：最小远程闭环

- execution 数据模型和数据库表。
- SSH 配置、指纹确认和端口转发。
- ComfyUI 健康检查客户端。
- 单一 ANIMA Turbo API 工作流及字段绑定。
- 提交、轮询完成、下载和默认分类。

### 阶段 B：产品化

- WebSocket 实时进度和队列界面。
- 工作流导入、校验与模型映射 UI。
- 断线恢复、任务重试、下载去重。
- 生成历史和打开输出目录。

### 阶段 C：扩展

- 多 LoRA 动态工作流。
- 输入图片上传、图生图和 ControlNet。
- 多服务器和队列调度。
- 可选的 ComfyUI 远程启动、停止和更新管理。

## 14. V2 完成定义

当用户只完成一次云主机与工作流配置后，日常操作应缩短为：

```text
输入中文 → 翻译并编译 → 点击“生成并自动下载”
```

软件自动完成连接、参数注入、排队、进度跟踪、结果下载、分类归档和历史记录；任何失败都可以从已保存状态继续，而不是要求用户重新运行整个流程。

## 参考

- ComfyUI Server Routes: https://docs.comfy.org/development/comfyui-server/comms_routes
- ComfyUI Server Overview: https://docs.comfy.org/development/comfyui-server/comms_overview
- ComfyUI 官方 WebSocket API 示例: https://github.com/comfyanonymous/ComfyUI/blob/master/script_examples/websockets_api_example.py
