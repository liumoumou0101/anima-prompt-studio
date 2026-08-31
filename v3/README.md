# ANIMA Prompt Studio V3

状态：Phase 3 主产品闭环已完成；进入数据更新、真实环境验收和质量 benchmark 阶段

V3 在本目录中独立开发，避免继续扩大 V2 根目录中的源码、测试和文档耦合。当前正式可运行版本仍是仓库根目录的 V2。

## 目录

```text
v3/
├── pyproject.toml
├── src/anima_prompt_studio_v3/   # V3 Python 包
├── tests/                         # 只包含 V3 自动化测试与小样
├── web/                           # V3 React/Vite 产品层
└── tools/                         # V3 开发和数据构建工具
```

产品基线、架构、数据/API 契约和路线见 [../docs/v3/README.md](../docs/v3/README.md)。

当前实现进度和测试结果见 [STATUS.md](STATUS.md)。

## 与 V2 的边界

- 不把 V3 代码加入 `src/anima_prompt_studio` 的旧提示词流水线。
- 不移动或删除 V2 现有测试、报告、探针和历史文档。
- 需要复用 V2 时，通过 `anima_prompt_studio_v3.adapters.v2` 的显式适配器调用稳定服务。
- 禁止 V3 业务代码导入 V2 的 `ui.main_window` 或 PySide 控件。
- V2 回归与 V3 测试使用不同命令，开发阶段都必须保持可运行。
- V3 达到替代门槛后，再决定是否把仓库根布局迁移到 V3；Phase 0 不做目录大扫除。

## 开发命令

环境和 `web/dist` 准备完成后，也可以直接双击仓库根目录的 `启动 ANIMA V3.cmd`。纯 ASCII 批处理只负责进入 PowerShell 启动器，避免 `cmd.exe` 在中文路径下破坏变量或续行符；启动窗口会显示首次数据包安装进度和错误信息。首次校验、复制 374 MB 数据包可能需要 40～60 秒，出现 `ready` 后才打开浏览器；关闭窗口会停止仅监听 loopback 的本地 API。

Windows 正式发布构建见 [`../packaging/README_V3.md`](../packaging/README_V3.md)。生成的便携版解压后直接双击 `AnimaPromptStudioV3.exe`；安装版会创建开始菜单入口，并可选创建桌面快捷方式。V2 与 V3 的 AppId、安装目录和 EXE 名称相互独立。

从本目录建立独立开发环境：

```powershell
Set-Location ..
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,remote]"
python -m pip install -e ".\v3[dev]"
Set-Location v3
python -m pytest
```

V3 产品层通过正式包依赖复用 V2 的稳定服务。按上面的顺序开发安装，或发布时同时提供 V2/V3 wheel，安装器会解析 V2、PySide6、FastAPI 与 Uvicorn 等完整运行依赖；是否启用远程生成、自然语言解析和画廊，则由启动时是否传入现有 V2 数据库决定。

数据构建的可选 Parquet 依赖：

```powershell
python -m pip install -e ".[dev,data]"
```

使用 UTF-8 JSON 配置构建版本化参考数据包：

```powershell
anima-v3-build-data --config .local\build-real.json
```

命令默认拒绝覆盖现有数据包，成功或失败都输出结构化 JSON。锁定上游文件的大小和 SHA-256 见 `data-sources/`；下载缓存和构建产物位于 `.local/`，不会进入版本控制。

将已解包的数据包安装到版本化目录并原子启用：

```powershell
anima-v3-data-pack --root .local\data install --source .local\packs\anima-v3-dso-0636f762-r1
anima-v3-data-pack --root .local\data status
anima-v3-data-pack --root .local\data resolve
```

更新时不会覆盖正在使用的 SQLite 文件。每个版本保存在 `packs/<pack_id>/`，只有 `active.json` 指针会在强校验通过后通过 `os.replace` 原子切换；切换失败保持旧指针，必要时执行：

```powershell
anima-v3-data-pack --root .local\data rollback
```

API 可直接读取受管理目录中的活动版本：

```powershell
anima-v3-api --data-root .local\data
```

`install` 当前接收本地已解包目录；联网下载仍属于独立分发层，下载完成后必须经过同一个安装入口，不能绕过 manifest、SHA-256、记录数、SQLite integrity 和健康查询。

运行 Phase 1 静态硬门槛：

```powershell
anima-v3-benchmark `
  --suite benchmarks\static_v1.json `
  --reference-db .local\packs\anima-v3-dso-0636f762-r1\reference.db
```

报告检查 required 保留率、excluded 泄漏、自动受保护类别泄漏、候选格式和 lane 差异。它不能替代固定参数生图盲测。

先构建 Web，再启动同源的 loopback 应用：

```powershell
Set-Location web
npm install
npm run build
Set-Location ..
anima-v3-api `
  --reference-db .local\packs\anima-v3-dso-0636f762-r1\reference.db `
  --frontend-dist web\dist
```

命令只监听 `127.0.0.1` 随机端口，并输出一次性的 `bootstrap_url`；在浏览器打开该地址即可进入工作台和标签页。所有业务 API 默认要求交换后的 session token。

如需启用复用 V2 配置的远程生成队列，增加：

```powershell
anima-v3-api `
  --reference-db .local\packs\anima-v3-dso-0636f762-r1\reference.db `
  --v2-database "$env:LOCALAPPDATA\AnimaPromptStudio\anima_prompt_studio.db"
```

远程密码仍保存在 Windows 凭据管理器。加密私钥的 passphrase 可在 V3 工作台生图栏一次输入，只保留在当前 V3 进程内，退出即清空；它通过独立凭据端点传递，不进入工作台、任务快照、SQLite、日志或 API 响应。

指定 `--v2-database` 会启用 V2 本地翻译薄适配器，并保留一个显式触发的 AI 辅助拆解接口。自然语言工作台默认使用本地翻译、原文/译文证据和 V3 标签索引：只有原文精确命中或用户确认的标签进入 Literal，译文索引和相关标签只显示为建议；无标签命中时译文以可追踪 prose baseline 保留。AI 抽取不再是默认主路径。本地翻译优先使用已安装 Marian 模型并保持 `local_files_only`，否则使用内置离线词典；两者均不会调用 V2 旧提示词编译管线。

可变工作台状态默认写入 `.local/state/workspaces.db`，与只读 `reference.db` 分离。可用 `--workspace-db` 指定其他本地位置。

前端依赖已在 `web/package-lock.json` 独立锁定，不复用 V2 `web_gallery` 的依赖锁文件。
