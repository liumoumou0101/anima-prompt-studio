# V3 上游快照

检查日期：2026-08-25

用途：固定 V3 开发起点，避免上游在开发期间变化导致数据字段、算法或许可证结论漂移。这里记录的是调查基线，不代表代码已经复制到本仓库。

## 固定版本

| 项目 | HEAD commit | 已知许可 | V3 角色 |
| --- | --- | --- | --- |
| [DanbooruSearchOnline](https://github.com/SuzumiyaAkizuki/DanbooruSearchOnline) | `0636f762694fc436b4ac472cf59b85d172eaaac4` | GPL-3.0 | 搜索、Tag–Tag、Artist–Tag 和工作区逻辑的主要上游 |
| [Booru Tag Gallery](https://github.com/Mexes-GM/booru-tags-gallery) | `ea27df671ab5066240f8c77e62a2d8a7bfb487b6` | MIT | 标签/画师 Web 页面和交互上游 |
| [prompt-translator](https://github.com/Naccl/prompt-translator) | `fcfabac1129776f9805a4a6eb2e12ec68262eec9` | MIT | 可选离线翻译实现参考 |
| [danbooru-tag-pipeline](https://github.com/SuzumiyaAkizuki/danbooru-tag-pipeline) | `a5a2d0ef085748eaa4a67e77eecee37a6680f776` | 未发现 LICENSE | 仅外部运行的数据构建工具 |

commit 通过 `git ls-remote <repository> HEAD` 获取。开始实际移植时应按上述 commit checkout，不直接跟随浮动 `main`。

## 已观察到的数据/算法合同

在本快照下：

- pipeline 的 Tag–Tag 精简输出逻辑最终写出 `tag_a`、`tag_b`、`count`。
- pipeline 的 Artist–Tag 处理代码使用 `tag`、`artist`、`artist_post_count`、`cooc_count`、`frequency`、`pmi`、`npmi`。
- SearchOnline 当前引擎读取 `cooc_count`、`artist_post_count`，并在运行时根据边际计数重新计算画师 NPMI。
- SearchOnline 关联标签会从 count 和标签边际计数计算 NPMI；多 seed tag 的分数累加。
- Booru Tag Gallery 是 React/TypeScript/Vite Web 应用，包含本地标签搜索、详情、相关标签、在线帖子预览和 NSFW 交互。

这些观察只用于为 fixture 和 adapter 建立首版预期。实际实现仍以锁定 commit 的代码、fixture 和 [DATA_CONTRACT.md](DATA_CONTRACT.md) 为准。

## 开发时的更新规则

1. 首个可用纵向切片完成前不升级上述 commit。
2. 必须升级时，先在本文件新增“候选版本”，比较许可证、schema、依赖和行为。
3. importer fixture 与推荐对照测试通过后才能替换固定版本。
4. 上游更新不得直接改变已发布数据包的算法版本；需要新 `data_pack_id` 或 `algorithm_version`。
5. pipeline 即使更新了代码，只要仍无许可证，分发边界不变。

## 尚未执行

- 尚未把 GPL/MIT 许可证原文复制到 V3 的 `LICENSES/` 目录，因为本轮没有开始移植第三方代码。
- 尚未对上游完整依赖树做发布许可证扫描。
- 尚未发布或再分发任何上游数据文件。

这些动作安排在 V3-002，且必须先于相应第三方代码进入 V3 主干。
