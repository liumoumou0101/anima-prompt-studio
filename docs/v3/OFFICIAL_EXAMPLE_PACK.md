# 官方参考包格式与安装

当前已实现构建、校验、安装、激活、读取、笔记覆盖与复制功能。首个三图精选包位于 [v3/example-packs](../../v3/example-packs/README.md)，包含木刻、炭笔和水彩，已完成内容与许可记录及离线集成验证；真实质量评测和发行包集成尚未完成。单元测试中的纯色像素仍仅为测试数据。

目录包含 examples-pack.json、catalog.json、NOTICE.txt、LICENSES/ 与 media/{off_id}/original.webp。manifest 的 contract 为 anima-v3-examples/1，pack_id 为最多 80 字符的稳定目录标识，generated_at 记录生成时间；counts 包含 examples/files。files 列出除 manifest 自身之外每个文件的 path、字节 size 与 SHA-256。

catalog.json 是条目数组。每项含稳定 off_ ID、title、完整 requirements、compat 和 media 相对路径。图片限静态 WebP、20 MB/4000 万像素。LoRA 只声明在 requirements 中，包内不携带或自动安装 LoRA 权重。

使用 `anima-v3-example-pack <源目录> --destination <工作台数据库同级的 official-examples 目录>` 安装。源码环境可用 `python -m anima_prompt_studio_v3.tools.install_example_pack` 调用相同入口。

## 制作本地包

准备 `catalog.json`、`NOTICE.txt`、`LICENSES/` 和每个条目的 `media/{off_id}/original.webp` 后，运行：

```text
anima-v3-build-example-pack <源目录> --pack-id <新的版本标识>
```

源码环境对应 `python -m anima_prompt_studio_v3.tools.build_example_pack`。命令生成 `examples-pack.json`，自动记录文件数量、字节数和 SHA-256，并复用安装器检查合同与图片。不会下载、转换、安装或激活图片，也不覆盖已有 manifest；内容改变后使用新版本目录重新构建。构建校验失败时移除本次新建的 manifest，保留输入文件。

可以在 `SOURCES/` 保存来源 API 摘要与人工筛选记录，它们会一起进入哈希清单。命令拒绝符号链接和源目录中不属于上述结构的文件，避免将临时配置意外打包。许可文件存在只证明结构齐全，不代替对许可内容和每张图分发依据的人工核对。

早期候选及 API 公开领域标记保存在 [REFERENCE_CANDIDATES.json](audits/2026-09-09-conversational-workbench/REFERENCE_CANDIDATES.json)。这些芝加哥艺术博物馆图片端点返回 403，未入选。首包改用可下载并逐张查看的 Cleveland Museum of Art 图片，来源证据保存在包内 SOURCES；没有根据标题直接生成分层要求。

安装时校验文件登记、目录边界、数量、结构、哈希与解码，再写入新的版本目录并原子替换 current.json。相同 pack_id 内容不同会拒绝；旧版本目录不覆盖，用户笔记覆盖表不清除。切换版本后旧来源版本请求返回冲突，已经钉选或提交的冻结快照继续有效。

用户笔记保存在 examples.db 的 official_example_overrides 中，使用 override_revision；官方 source_version 由 pack_id 和条目内容摘要组成。复制为个人参考会复制原始图片与要求、兼容声明和当前笔记，后续可独立编辑。
