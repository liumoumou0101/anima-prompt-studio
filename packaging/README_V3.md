# ANIMA Prompt Studio V3 Windows 发布

## 产物

- 便携版：`release/ANIMA-Prompt-Studio-V3-Portable-v<version>.zip`
- 安装版：`release/ANIMA-Prompt-Studio-V3-Setup-v<version>.exe`
- 双击入口：`AnimaPromptStudioV3.exe`

V3 与 V2 使用不同的可执行文件名、安装目录和 Inno Setup `AppId`，可以并存。用户数据继续写入 `%LOCALAPPDATA%/AnimaPromptStudio`，不会放进安装目录或 ZIP 解压目录。

## 构建

```powershell
python -m pip install "pyinstaller>=6.10,<7"
.\packaging\build_windows_v3.ps1 `
  -Python .\.venv\Scripts\python.exe `
  -Version 3.0.0-alpha.1 `
  -DataPackSource .\v3\.local\packs\anima-v3-dso-0636f762-r1
```

脚本默认执行：

1. `npm ci` 与 V3 Web production build。
2. PyInstaller onedir 构建。
3. 冻结 EXE 首次启动 smoke test。
4. 同一用户数据目录第二次启动的升级 smoke test。
5. 活动指针和已安装 `reference.db` SHA-256 不变检查。
6. 便携 ZIP 压缩。
7. 若已安装 Inno Setup，则生成安装版。

开发调试可使用 `-SkipWebBuild`、`-SkipInstaller` 或 `-SkipExeSmoke`，正式发布不应跳过 Web 和 EXE smoke。

## 冻结环境注意事项

PyInstaller 运行环境的 PATH 可能包含 Poppler 自带的 `icuuc.dll`/`icudt78.dll`。它们会遮蔽 Qt 期望使用的 Windows ICU 并造成 `PySide6.QtCore` 的 WinError 127。V3 spec 会按目标文件名排除这两个外部 DLL；不要把它们重新复制进 `_internal`。

## 数据包

发布包内的数据包位于 PyInstaller `_internal/data-packs/<pack_id>/`。首次启动时仍通过正式 `DataPackManager` 校验和安装到用户数据目录，而不是直接信任或写入内置副本。软件升级只能替换程序目录，不能修改已有活动指针、工作区或安装后的参考数据库。

## CI 安装版

`.github/workflows/release-v3.yml` 只允许手动触发，并要求提供数据包 HTTPS 地址及预期 SHA-256。CI 会在构建前校验下载归档，随后安装 Inno Setup、生成两种 Windows 产物，并在临时目录执行 Setup 静默安装、冻结 EXE 启动和卸载 smoke test。正式数据发布地址确定前，不会把临时下载源写死在工作流中。
