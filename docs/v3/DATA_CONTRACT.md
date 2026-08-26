# V3 参考数据契约

状态：首版开发合同

契约版本：`anima-v3-data/1`

## 1. 目的

V3 运行时不执行 `danbooru-tag-pipeline`，只接受经过自有导入器验证的版本化数据包。上游文件名和字段可以变化，V3 对外只承诺本文件定义的稳定契约。

参考数据不是用户数据。参考数据包可以整包替换，用户工作台、历史、收藏和反馈必须保存在独立的 `user.db`。

## 2. 数据包布局

```text
anima-v3-data-YYYYMMDD/
├── data-pack.json
├── reference.db
├── NOTICE.txt
└── LICENSES/
    └── upstream-*.txt
```

首版发布包不包含 Danbooru 投稿图片。在线预览由运行时按用户操作获取并缓存。

## 3. `data-pack.json`

示例：

```json
{
  "contract": "anima-v3-data/1",
  "pack_id": "anima-v3-data-2025-09-r1",
  "generated_at": "2026-08-25T00:00:00Z",
  "snapshot": {
    "target_cutoff": "2025-09-30",
    "cutoff_mode": "approximate",
    "source_observed_at": "2026-08-25",
    "corpus_size": 0,
    "corpus_size_mode": "estimated"
  },
  "sources": [
    {
      "name": "DanbooruSearchOnline",
      "repository": "https://github.com/SuzumiyaAkizuki/DanbooruSearchOnline",
      "commit": "REQUIRED_BEFORE_BUILD",
      "license": "GPL-3.0"
    }
  ],
  "algorithms": {
    "tag_related": "npmi-v1",
    "artist_related": "npmi-v1",
    "search_index": "fts5-v1"
  },
  "counts": {
    "tags": 0,
    "artists": 0,
    "aliases": 0,
    "tag_edges": 0,
    "artist_edges": 0
  },
  "diagnostics": {
    "duplicate_tags_merged": 0,
    "aliases_skipped_missing_target": 0,
    "tag_edges_skipped_unknown_tag": 0,
    "tag_edges_margin_mismatch": 0,
    "artist_edges_skipped_unknown_tag": 0,
    "artist_edges_margin_mismatch": 0
  },
  "files": [
    {
      "path": "reference.db",
      "size": 0,
      "sha256": "REQUIRED"
    }
  ]
}
```

规则：

- `contract` 不匹配时拒绝安装。
- `commit`、`size` 和 `sha256` 在正式数据包中不得使用占位值。
- `cutoff_mode` 只能是 `exact` 或 `approximate`。
- 只有基于截止日期历史帖子快照重新统计时，才可以写 `exact`。
- `corpus_size_mode=estimated` 时，UI 和日志不得把 NPMI 描述成训练语料精确概率。
- `diagnostics` 必须保留构建期间所有可接受隔离项的计数；未知字段、负计数和非法分数仍然硬失败。

## 4. 上游输入适配

导入器首版接受以下逻辑输入；具体字段通过 adapter 映射：

| 逻辑输入 | 已知上游形式 | V3 处理 |
| --- | --- | --- |
| 标签主表 | `tags_enhanced.csv` | 校验名称、分类、热度、中文词和 NSFW 标记 |
| Tag–Tag | `cooccurrence_clean.parquet` | 当前已知字段为 `tag_a, tag_b, count` |
| Artist–Tag | `tag_artist_cooc.parquet` | 兼容 `cooc_count/artist_post_count/...` 和旧讨论稿字段 |
| 标签组 | `tag_groups.json` | 转换为稳定 group 与 member 表 |
| 别名 | `tag_aliases.parquet` 或其他快照 | 只接受可唯一解析的 canonical target |
| Wiki | CSV/Parquet/主表字段 | 保存清洗后的本地摘要与原始来源信息 |

锁定的真实快照中，`tags_enhanced.csv` 使用 GB18030，别名字段为 `antecedent_name/consequent_name`。这些属于绑定 commit 的 adapter 行为，不扩散为 V3 运行时合同。

不得把上游 README 中的示例字段当作运行时合同。每个 adapter 必须绑定上游 commit，并有 fixture 契约测试。

## 5. `reference.db` 表

### 5.1 `metadata`

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `key` | TEXT | PRIMARY KEY |
| `value` | TEXT | NOT NULL |

至少保存 `contract`、`pack_id`、`generated_at`、`target_cutoff`、`cutoff_mode`、`corpus_size` 和算法版本。

### 5.2 `tags`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER | 稳定包内主键 |
| `name` | TEXT UNIQUE | canonical 名，例如 `school_uniform` |
| `render_name` | TEXT | 默认 ANIMA 文本，例如 `school uniform` |
| `category` | INTEGER | Danbooru category 原值 |
| `category_name` | TEXT | general/artist/copyright/character/meta |
| `post_count` | INTEGER | 与数据快照一致的边际计数或已注明近似值 |
| `created_at` | TEXT NULL | 已知时保存 |
| `cn_name` | TEXT NULL | 主要中文名 |
| `cn_terms` | TEXT NULL | 搜索用中文扩展词，JSON 数组 |
| `wiki_summary` | TEXT NULL | 本地说明摘要 |
| `nsfw` | INTEGER | 0/1/unknown，不把未知当安全 |
| `deprecated` | INTEGER | 0/1 |

### 5.3 `artists`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER | 稳定包内主键 |
| `name` | TEXT UNIQUE | 不含 `@` 的 canonical 画师名 |
| `render_name` | TEXT | ANIMA 展示形式，以 `@` 开头 |
| `post_count` | INTEGER | 画师边际计数 |

画师与普通标签必须分表保存。Danbooru 中可能出现画师和角色/版权标签同名；把二者塞进同一 UNIQUE canonical 表会错误冲突。

### 5.4 `tag_aliases`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `alias` | TEXT | 规范化别名 |
| `tag_id` | INTEGER | canonical tag |
| `source` | TEXT | Danbooru/upstream/manual |
| `status` | TEXT | active/deprecated/ambiguous |

只有 `active` 且唯一的别名允许自动替换；歧义别名只能返回待确认候选。

### 5.5 `tag_groups` / `tag_group_members`

`tag_groups` 保存稳定 group ID、英文名、中文名和来源。`tag_group_members` 保存 group 与 tag 的多对多关系。

标签组用于分类、同类提示和冲突辅助，不自动代表标签互斥。互斥关系必须有单独规则或明确人工确认。

### 5.6 `tag_cooccurrence`

查询表使用有向形式，每个源标签保留排序后的邻居：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `tag_id` | INTEGER | 源标签 |
| `related_tag_id` | INTEGER | 邻居标签 |
| `cooc_count` | INTEGER | 共现次数 |
| `pmi` | REAL NULL | 可复现时保存 |
| `npmi` | REAL NULL | 可复现时保存 |
| `rank` | INTEGER | 在源标签邻居中的排序 |
| `score_version` | TEXT | 公式版本 |

若上游只有无向 `tag_a/tag_b/count`，导入器生成两条有向查询记录。NPMI 必须使用同一快照中的 corpus size、两个边际计数和共现计数计算；条件不满足时保留 count，并标注为近似分数。

### 5.7 `artist_tag_cooccurrence`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `artist_id` | INTEGER | `artists.id` |
| `tag_id` | INTEGER | 关联标签 |
| `cooc_count` | INTEGER | 共现次数 |
| `artist_post_count` | INTEGER | 画师边际计数 |
| `tag_post_count` | INTEGER | 标签边际计数 |
| `pmi` | REAL NULL | 计算值 |
| `npmi` | REAL NULL | 计算值 |
| `rank` | INTEGER | 画师内或标签内的稳定排序 |
| `score_version` | TEXT | 公式版本 |

运行时优先使用数据包内已经验证的 `npmi`，不得在不同版本的边际计数上静默重算。

### 5.8 搜索索引

首版采用 SQLite FTS5 保存英文、空格渲染名、中文名、扩展词和别名。Wiki 摘要用于详情展示，是否加入全文搜索在产品切片中评测后决定。拼写容错可以在 FTS 候选集上使用轻量编辑距离或前端 Fuse.js，但最终 canonical 解析必须回到 `tags.id`。

若前端额外生成静态 Fuse 索引，必须在索引文件中写入相同 `pack_id`；版本不一致时拒绝加载，防止 UI 搜索结果与后端详情错位。

## 6. canonical 与渲染规则

- 数据库 ID 使用 Danbooru 风格 canonical 名称和下划线。
- 搜索同时匹配下划线与空格形式。
- 最终 ANIMA 输出由 `ModelProfile` renderer 决定，不能直接复制数据库 `name`。
- `score_N`、模型规定的特殊 token 和用户锁定原文按白名单保留下划线。
- 画师输出由 renderer 加 `@`；数据库中不把 `@` 作为 canonical 名称的一部分。
- Danbooru 与 Gelbooru 名称不同时，使用独立 render alias，不改 canonical 主键。

## 7. 导入验证

构建器必须在生成数据包前完成：

1. 必需文件、字段和类型校验。
2. canonical tag 唯一性与 category 合法性校验。
3. alias 目标存在性与歧义统计。
4. 所有共现边的两端存在性校验；近似快照可隔离未知端点并计数，精确快照不得接受。
5. `cooc_count <= min(marginal_a, marginal_b)` 的一致性检查；近似快照异常行显式报告，精确快照硬失败。
6. NaN、无穷值、负计数和非法 NPMI 范围检查。
7. Top-K、最低共现量和最低分数参数写入 manifest。
8. 数据库 `PRAGMA integrity_check`。
9. 固定健康查询与抽样快照测试。
10. 生成 SHA-256 后再发布。

校验报告保存到构建产物，但不要求随终端用户包分发全部中间数据。

## 8. 更新协议

- 下载到用户数据目录内的唯一临时文件，不直接写现用数据库。
- 下载大小、SHA-256、契约版本和 SQLite 健康检查全部通过后才替换。
- 替换前关闭只读连接，并保留一个最近可用版本。
- Windows 下替换失败时保持旧版本运行，不循环删除或重命名未知文件。
- 数据版本变化后使搜索缓存和推荐缓存整体失效。
- `user.db` 中保存的 tag 使用 canonical 名；数据更新后无法解析的 tag 标记 orphaned，保留用户文本，不静默删除。

## 9. 数据许可与来源

`reference.db` 必须带 `NOTICE.txt`，列出来源、commit、构建方式、截止模式和已知限制。V3 代码采用 GPL-3.0 不代表第三方事实数据、Wiki 文本或图片自动变成 GPL 数据；数据包的授权与归属单独记录。

无许可证 pipeline 不进入仓库、安装包或数据包。正式公开发布数据包前，仍需确认源数据再分发条件或取得维护者授权。
