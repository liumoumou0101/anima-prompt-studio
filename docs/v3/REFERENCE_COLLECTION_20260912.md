# 本地参考案例接入

本次把已有 `anima-ref/batches` 资料接入 V3 的 `ExampleStore`，没有修改源 JSON 或图片，也没有下载新资料、调用 LLM 或占用云端 GPU。

## 已交付

- 参考库可按原 checkpoint、画师、LoRA 依赖、内容标记筛选，搜索提示词、标题、风格说明和个人笔记。
- 详情保留原正负提示词、已知参数、原 checkpoint、画师、LoRA、资料说明、来源地址和完整原记录。
- 可分别复制原始正负提示词，或直接借用原提示词创建会话，不必先做 AI 提取。
- 借用提示词采用可识别模型的默认参数；未接入的原模型从 Aesthetic 1.1 开始，并明确提示可切换。它不携带原种子、工作流或 LoRA，不能当作复现。
- 画师样图组件按需读取最多 4 张已标记为一般内容的本地案例，标注原模型、组合画师与 LoRA 依赖，区分模型输出与画师原作。

## 数据可信度

当前集合共 12 个批次、124 条案例，图片全部通过解码与 SHA-256 验证。全部缺少种子和完整工作流，因此统一保持 `seed: null`、`workflow_snapshot_ref: null`、`reproducibility: partial`。

LoRA 判定只依赖明确记录：非空 `lora` 为“含 LoRA”；`unet_pure: true` 且无 LoRA 才为“已确认无 LoRA”；其他情况保留未知。实际分别为 62、34、28 条。不会因为 LoRA 字段为空就推断纯底模。

内容标记完全继承资料已有标记，未重新判图：一般内容 96、敏感内容 5、成人内容 14、露骨内容 9。画师样图入口只展示其中的一般内容；参考库可自行筛选。

## 导入方式

从仓库根目录运行，先备份实际使用的 `examples.db`，再填写明确的目标路径：

```powershell
$env:PYTHONPATH='src;v3/src'
$env:PYTHONIOENCODING='utf-8'
.venv/Scripts/python.exe v3/tools/import_reference_collection.py --source anima-ref --database <state>/examples.db --receipt <output>/reference-import.json --dry-run
.venv/Scripts/python.exe v3/tools/import_reference_collection.py --source anima-ref --database <state>/examples.db --receipt <output>/reference-import.json
```

`--dry-run` 会初始化目标存储结构并验证素材，但不新增案例。CLI 禁止将数据库或回执写进来源集合。所有源文件、ID 和图片先统一验证，发现重复 ID、路径越界、无效图片或已导入图片校验不一致时停止。

案例 ID 根据 Civitai 来源 ID 稳定生成。重复导入不新增记录，保留个人标题、全部笔记、结构化要求及用户指定兼容信息。来源文字变更只更新服务器持有的来源记录；同 ID 的来源图片变更会拒绝。用户已删除的案例保持删除状态。回执列出每条案例的操作、原记录 SHA-256、图片 SHA-256 和批次文件 SHA-256。

本轮隔离验收文件位于 `.local/reference-import-acceptance-20260912/`：首次新增 124 条，第二次 124 条全部 `unchanged`；原图 SHA-256 全部相同，3 张缩略图通过解码。该隔离库不是正式库。

## API 与组件

- `GET /api/v3/reference-examples?model=...&artist=...&lora_dependency=none|lora|unknown&content=safe|sensitive|nsfw|explicit|unknown`
- `GET /api/v3/reference-examples/facets` 返回 `models`、`artists`、个人案例 `count`。
- `GET /api/v3/reference-examples/by-artist?artist=...&limit=4` 返回安全标记案例的 ID、标题、模型、组合画师、LoRA 依赖、缩略图 URL 和参考库链接。
- `POST /api/v3/reference-examples/{id}/workspace` 新增 `mode: "prompt"`；仍要求匹配 `source_version`。
- `ArtistReferencePreview` 的 props 为 `{artist: string}`；仅在展开时加载。应位于 Router 下，避免嵌套在另一个整卡按钮内。

所有接口沿用现有会话授权和图片 cookie 范围。分页游标绑定全部筛选条件及资料库版本；筛选变化后旧游标被拒绝。
