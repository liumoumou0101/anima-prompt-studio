# 官方参考样例包

首包：`cma-styles-20260910-v1`，三张精选开放馆藏图片。已完成图片查看、分层描述、许可与哈希记录、安装/读取/缩略图和 style pin 验证；真实成图已评测并保留模型能力限制，详情见文末。

| 条目 | 用途 | 画面特征 |
| --- | --- | --- |
| off_cma_144688 · 木刻牧场 | 排线、黑白版画与纸底风格 | 牧场、牲畜、人物和远山；复杂场景优先用作风格参考 |
| off_cma_166868 · 炭笔肖像 | 颗粒、擦抹、明暗概括 | 单人半身肖像，灰色纸底与白垩高光 |
| off_cma_159769 · 水彩田野 | 透明色层、低饱和色彩和空气透视 | 湖畔田野、远山、羊群和大面积天空 |

图片及来源元数据来自 [Cleveland Museum of Art 开放馆藏](https://www.clevelandart.org/open-access)，每张 API 记录均标记 CC0。每图署名、原作链接和下载 URL 位于包内 NOTICE.txt / SOURCES；LICENSES 包含完整 CC0 文本。馆方不为本应用背书。

包内 WebP 是馆方 web JPEG 的无损格式转换，逐像素校验解码后的 RGB 值一致；未裁切、缩放或重绘。它是本应用保存的参考原图副本，不是馆方最高分辨率档案。中文要求由 Codex 看图后编写；作者信息仅留在来源记录，artists 和 LoRA 均为空。风格钉选不默认复制光线、构图或主体。未给排除层凭空补充禁用项。

在仓库根目录、已设置源码 Python 路径的环境执行：

```text
python -m anima_prompt_studio_v3.tools.install_example_pack v3/example-packs/cma-styles-20260910-v1 --destination <工作台数据库同级的 official-examples 目录>
```

此包进入 wheel 和 Windows 打包资源，图片、NOTICE、SOURCES、LICENSES 与清单原始字节一同保存；普通启动不自动替换用户已激活的版本。安装程序自带的样例无需源码目录或网络：

```text
anima-v3-example-pack --bundled --destination <工作台数据库同级的 official-examples 目录>
```

Windows 便携版/安装版也可使用：

```text
AnimaPromptStudioV3.exe --install-bundled-examples
```

该命令安装到默认工作台目录后退出；自定义工作台使用 `--workspace-db <路径>`。不需要启动前端、LLM 或 GPU。重复安装同版本保留个人备注；安装仍执行完整图片及哈希校验。保持版本目录不可变，修订内容时另建新 pack_id。两项新功能发布 flags 仍关闭。

实际成图已完成：木刻等复杂动作有遗漏，记录为能力边界，见 `docs/v3/audits/2026-09-09-conversational-workbench/IMAGE_COMPARISON_20260910.md`；样例适合提取媒介风格，不承诺完整复刻原画。
