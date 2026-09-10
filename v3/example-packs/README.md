# 官方参考样例包

首包：`cma-styles-20260910-v1`，三张精选开放馆藏图片。已完成图片查看、分层描述、许可与哈希记录、安装/读取/缩略图和 style pin 验证；真实模型质量尚未验收。

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

此包作为独立源码资源交付，尚未捆绑到 wheel/Windows 安装器，也不会在应用启动时自动激活。保持版本目录不可变；修订内容时另建新 pack_id。两项新功能发布 flags 仍关闭，正式发布还需要完成质量验收及发行包集成。
