# Windows 便携版实际验收

日期：2026-09-10。本轮接续功能收尾，未调用 LLM 或 GPU。

## 构建与产物

在项目虚拟环境安装 PyInstaller 6.22.2，执行现有 Windows 构建脚本，版本 `3.0.0-alpha.1`。使用本轮先前通过 TypeScript 与生产构建的 Web dist，因此传入 `-SkipWebBuild`；未跳过 EXE smoke。正式发布流水线仍应执行完整 Web 构建。

生成 `release/ANIMA-Prompt-Studio-V3-Portable-v3.0.0-alpha.1.zip`，286810508 字节。

SHA-256：`5F05082F95BEBDD7FD25D77552B965FA6D6C6C4032E951E9E2F53B5BA0DB6B1A`。

## 已通过

- PyInstaller 实际冻结构建，EXE 内置网页、数据包与三图参考样例。
- EXE 显式安装内置样例，返回三条；首次启动校验并安装主数据包后就绪。
- 同一测试目录第二次启动成功，活动数据包指针、reference.db 哈希和官方样例指针保持不变。
- 额外启动真实 EXE，从其 HTTP 服务读取会话页与引用的 JS/CSS，均成功。
- 在新的隔离参考库中通过实际 HTTP 接口安装样例、读取缩略图、保存个人笔记与创建工作台。
- 终止测试进程再启动，个人笔记、工作台 draft 与 revision 均恢复一致。

本机日志：`.local/windows-build-20260910.log`。HTTP 验收脚本：`.local/smoke_frozen_http.py`；结果：`.local/frozen-http-20260910-233401/report.json`。测试全部使用隔离工作区，不改用户创作数据。HTTP 测试进程已结束。

## 范围限制

本机没有 Inno Setup，未产出 Setup 安装包，安装与卸载仍待验收。重复启动检查证明本轮冻结程序的数据保留，不等于跨历史版本迁移的全面验证。此次 EXE 以 `--without-runtime` 运行，未复测打包环境中的远端 GPU 执行或本地翻译；没有重跑模型语义试验。没有上传、发布或提交 Git。
