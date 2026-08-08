# 第三方资源与来源

本项目代码不嵌入第三方模型权重。资源安装命令将文件保存到用户本地数据目录，并在 `resource_manifest.json` 中记录来源和下载时间。

## 翻译模型

- `Helsinki-NLP/opus-mt-zh-en`
  - 来源：https://huggingface.co/Helsinki-NLP/opus-mt-zh-en
  - 用途：中文到英文的本地 Marian 翻译。
  - 许可：CC BY 4.0。
- `Helsinki-NLP/opus-mt-en-zh`
  - 来源：https://huggingface.co/Helsinki-NLP/opus-mt-en-zh
  - 用途：英文到中文的本地 Marian 回译。
  - 许可：Apache 2.0（以模型仓库当前模型卡及所附文件为准）。

模型加载始终使用 `local_files_only=True`；下载完成后日常使用不需要网络。

## 标签数据

- 标签名称、类别、热度、弃用状态和创建时间来自 Danbooru 官方只读 API：
  - https://danbooru.donmai.us/tags.json
- 别名快照来自 SD WebUI Tag Autocomplete 的 `danbooru.csv`：
  - https://github.com/DominikDoom/a1111-sd-webui-tagcomplete
  - 项目许可：MIT。

构建器仅保留创建时间不晚于 `2025-09-30` 的标签，以对应 ANIMA 官方公布的动漫训练数据截止时间。标签名称会在输出时转换为空格形式；画师标签仍由软件显式加 `@` 管理。

标签体系可能包含成人或敏感概念。软件只下载文本词表，不下载 Danbooru 图片或帖子内容。

## ANIMA 配置依据

模型参数、提示词格式和训练截止日期参考 CircleStone Labs 官方模型卡：

- https://huggingface.co/circlestone-labs/Anima

ANIMA 模型本身未被本工具下载或再分发。
