# 个人标签超市交付记录（2026-09-29）

状态：在隔离工作区 `D:/soft/提示词辅助工具2/.worktrees/personal-tag-market`、分支 `codex/personal-tag-market` 开发和验证；尚未合并、推送或重新打包发布。真实迁移已完成；集成测试与界面复核已执行，结论和限制如下。浏览器检查使用 QA 副本。已完成整分支独立审查；发现的导入与边界问题已修复，专项验证见下。修复复审记录保存在本地审计目录。

## 使用

1. 打开导航「个人标签超市」或 `/personal-tags`。在「挑选标签」中搜索名称、原文或别名，按分类筛选；同义或相似原文分别保留，可独立挑选。加入正向或负向组合，逐项设置 0.1–2.0、步长 0.05 的权重，也可手动输入。1.0 输出原文；原有逗号、换行、大小写、下划线及提示词片段保持不变。
2. 组合可命名保存、重新载入、回收和恢复。保存时记录原文快照；之后修改或回收词库条目不改写已保存内容。复制预览输出不翻译或调用模型。
3. 在「管理词库」中新增或编辑原文、显示名、别名和分类；可批量移动、管理分类、回收及恢复。非空分类不会隐式删除其标签或子分类。JSON 导入先预览风险与选项，再确认提交；JSON 导出可作为个人备份。修改当前组合权重不会写回词库默认值。
4. 工作台追加会显示原文正负向预览，确认后追加到工作台提示词。若当前工作台状态允许，可按回执撤销本次追加；有较新提示词编辑时不会覆盖新内容。

个人标签库始终位于 `--workspace-db` 所在目录，文件名固定为 `personal-tags.db`。隔离工作区中的 QA 副本位于 `v3/.local/qa-personal-tags`；它不是正式用户库。以下整段 PowerShell 默认选择 **QA 副本**，可在任意工作目录复制运行。将唯一的 `$useRealLibrary` 改为 `$true`，才会明确选择原目录已迁移的正式库；同时会在原目录 `v3/.local/state` 写入独立的工作台状态文件。运行前应核对路径并备份正式库。

```powershell
$checkout = 'D:\soft\提示词辅助工具2\.worktrees\personal-tag-market'
$python = 'D:\soft\提示词辅助工具2\.venv\Scripts\python.exe'
$reference = 'D:\soft\提示词辅助工具2\v3\.local\data\packs\anima-v3-dso-0636f762-r1\reference.db'
$qaState = Join-Path $checkout 'v3\.local\qa-personal-tags'
New-Item -ItemType Directory -Path $qaState -Force | Out-Null
$useRealLibrary = $false  # 只有主动使用正式个人库时改为 $true
$workspaceDb = if ($useRealLibrary) {
  'D:\soft\提示词辅助工具2\v3\.local\state\personal-tags-workspaces.db'
} else {
  Join-Path $qaState 'workspaces.db'
}
$env:PYTHONPATH = @((Join-Path $checkout 'v3\src'), (Join-Path $checkout 'src')) -join [IO.Path]::PathSeparator
$env:PYTHONUNBUFFERED = '1'
$env:ANIMA_PROMPT_ASSISTANT_DIR = Join-Path $qaState 'prompt-assistant'
$web = Join-Path $checkout 'v3\web'
Set-Location -LiteralPath $web
npm.cmd run build -- --emptyOutDir false
if ($LASTEXITCODE -ne 0) { throw 'Web build failed' }
& $python -m anima_prompt_studio_v3.tools.run_api --reference-db $reference --frontend-dist (Join-Path $web 'dist') --workspace-db $workspaceDb --without-runtime
```

`--emptyOutDir false` 是本机已验证的构建参数，绕开下文记录的默认输出目录清理异常；产物仍是 Vite 默认压缩的 `web/dist`。最后一行以绝对 Python 解释器执行隔离工作区的源码，并显式读取原目录中已有的参考数据库。启动后打开命令输出的一次性 `bootstrap_url`，而不是固定端口地址。`--without-runtime` 允许标签与本地工作台读写，但不提供生成；日常标签操作无需 PostgreSQL 或 Docker 常驻。用户库、完整导出、备份与 QA 截图均不进入 Git。

## 真实迁移与数据位置

来源是 `pg-local/postgres` 的 `public.sys_tags` 和 `public.sys_categories`。2026-09-29 的只读事务导出得到 11,473 条标签、174 个分类，与此前计数一致。原 PostgreSQL 未写入，也未因迁移删除。

| 项目 | 本机位置或结果 |
| --- | --- |
| 正式个人标签库 | `D:/soft/提示词辅助工具2/v3/.local/state/personal-tags.db` |
| 导入前 SQLite 备份 | `D:/soft/提示词辅助工具2/v3/.local/state/personal-tags-backups/personal-tags-20260929T093059841156Z.db` |
| 只读源导出 | `D:/soft/提示词辅助工具2/v3/.local/state/personal-tags-migration/legacy-20260929.json` |
| 全量新格式导出 | 同目录 `personal-tags-20260929.json` |
| 正式导入报告 | 同目录 `import-report-20260929.json` |
| 隔离验证库 | 工作区 `v3/.local/qa-personal-tags/library-validation.db` |
| 浏览器 QA 库 | 工作区 `v3/.local/qa-personal-tags/personal-tags.db`；对应 `workspaces.db` 是 QA 工作台库 |

独立验证库的首次预览和提交均为新增 11,647 条记录（标签 11,473＋分类 174）、无无效项；重复导入新增 0、已有 11,647，导出数据等价且库 revision 保持 1。逐条审计确认原文、显示名、全部别名、源 ID、旧权重元数据、默认新权重 1.0 和分类父子关系。正式个人库的导入报告也记录 11,473/174，并核对全部原始标签。

有 3,433 条原子分类未能唯一映射到直接子分类，保留在原根分类并留下旧分类文本供复核；其中 3,349 条使用旧默认 `General`，84 条为其他文本。相似规范化检测得到 225 组、226 个额外变体，均未合并。91 条是片段候选提示，需人工判定。362 条旧权重非默认值，其中 8 条超出新系统 0.1–2.0 范围；旧值保留在源元数据，新默认权重统一为 1.0，没有截断或钳制。一个 419 字符别名已完整保留。迁移摘要、原始审计 JSON 与源库预检副本放在隔离工作区的 `v3/.local/qa-personal-tags/audit`；完整用户数据留在本机忽略目录。

## 验证状态

- 任务级检查采用各自当时的代码基线，不能代替最终集成测试；本次后端与前端原始日志副本保存在隔离工作区 `v3/.local/qa-personal-tags/audit`。
- 浏览器 QA 在 `127.0.0.1:63834/personal-tags` 的隔离副本完成：真实计数显示、原文变体独立选择、1.2 权重原样复制、组合保存与刷新、源标签编辑后快照保持、片段原文、回收恢复、分类移动、无效 JSON 导入反馈，以及从词库到工作台的追加预览。取消没有写入工作台且选词仍在；再次确认后产生持久回执，刷新没有重复追加。复制保留权重、空格、换行和 LoRA 片段；撤销后刷新仍为空提示词、回执保持已撤销，没有再次追加。整个验收没有触发生成。
- 最终界面检查覆盖 1440px 浅色／深色、390px 展开的组合控件及管理编辑视图；分类树滚动范围已收敛，控件无观察到的裁剪、重叠或横向溢出。截图与操作记录保存在忽略的 `v3/.local/qa-personal-tags/audit`，包括 `personal-tags-desktop.png`、`personal-tags-dark.png`、`personal-tags-narrow.png` 和 `personal-tags-management.png`。这个临时预览地址不是正式库入口。
- 集成后端精确选择：**209 项通过、1 项失败**。失败项为 `tests/test_reference_examples.py::test_bundled_install_is_explicit_and_preserves_notes`：内置参考样例安装返回 422 `bundled_examples_install_failed`，与功能开发前基线日志中的同一失败一致。另有一项 Starlette/AnyIO 弃用警告。
- 前端完整 `npm test -- --maxWorkers=2` 在修复前集成提交 `d142a69` 上为 **55 个文件、489 项通过**。后续工作台加载重试修复 `b3e3ba7` 的受影响范围复测为 **4 个文件、95 项通过**；未重跑完整套件。修复后的 `npm run typecheck` 通过。
- 标准 `npm run build` 在当前 Windows 环境完成 4,667 个模块转换后异常退出，停止 QA 服务重试仍失败；同目录使用 `npm run build -- --emptyOutDir false` 则完整通过，生成默认 Oxc 压缩的 `web/dist`（只有大块提示）。隔离目录诊断构建也通过，因此故障集中在默认输出目录清理环节；目前仍未确认底层 Windows 失败机制。启动示例采用已验证的参数，标准裸命令的失败如实保留。
- 整分支独立审查覆盖 `ac157f2..7da095f`，发现 1 项 Important 和 3 项 Minor：完整导入缺少 `draft` 的校验、非 BMP Unicode 传递长度、仅负向选择反馈、空白快照渲染防御。本次已全部修复：缺少 `draft` 返回可读 422，显式 `null` 仍有效；渲染与传递共享码点计数；负向已选卡片显示反馈；空白检测不改写有效原文。
- 最终修复专项验证：后端导入、API 和工作台传递 **46 项通过**（既有 Starlette/AnyIO 警告仍在）；前端组合、传递库、传递组件、个人标签页面及草稿 hook **5 个文件、44 项通过**；`npm run typecheck` 与 `npm run build -- --emptyOutDir false` 均通过，构建转换 4,668 个模块，只有大块提示。没有重跑完整套件。原始命令、红绿回归输出及结果见本地审计目录 `final-fix-report.md`、`final-fix-*.log`；整分支记录为 `final-review.md`，提交后的专项复审记录为 `final-fix-review.md`，审查结论以该记录为准。

既有基线问题：独立工作区的受跟踪参考样例包字节与 manifest 校验值不一致，可使相关包校验测试失败；另有先于本功能的参考 ingest/config 失败。不要改动只读参考数据包来掩盖基线。最终检查若仍出现失败，应写明具体测试和本功能关联性。
