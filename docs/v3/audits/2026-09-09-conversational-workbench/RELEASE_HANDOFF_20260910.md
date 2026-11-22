# 发行与人工测试交接验收

日期：2026-09-10。用户要求完成后续步骤，再开始人工测试。产物版本为 `3.0.0-alpha.1`，未上传或发布。

## 安装与卸载

使用 [Inno Setup 官方渠道](https://jrsoftware.org/isdl.php) 提供的 6.7.3，通过 winget 安装编译器。现有 installer_v3.iss 编译成功；构建脚本补充识别当前用户目录中的编译器，避免今后误报缺失。

Setup 安装到项目 `.local/installed-v3-acceptance` 隔离路径，未建立桌面/开始菜单快捷方式。实际启动安装后的 EXE，通过 HTTP 检查网页资源、内置样例安装、缩略图、笔记保存和工作台重启恢复。再次覆盖安装与卸载均成功；测试程序已移除，工作台与参考库数据库 SHA-256 保持不变。仅验证同版本重装，不声称所有历史版本升级通过。

证据：`.local/setup-acceptance.json`、`.local/frozen-http-20260910-234013/report.json`、`.local/inno-build-20260910.log`。

## 打包环境真实生图

使用现有远端配置的隔离数据库副本，删除副本中历史任务并将输出定向到测试目录。没有修改用户原数据库。EXE 完整加载运行时，通过实际 HTTP 提交会话生成，复用此前已核对的赛璐璐提示词，没有新增 LLM 调用。

- Aesthetic v1.1，768×1024，seed 20260912，1 张。
- run `111ce8e8-27ba-4222-b67c-c298132d9227`，completed，产物下载成功。
- 同 idempotency key 重放返回同回执；图片内容哈希匹配登记值，尺寸正确。
- 已查看原图：咖啡馆、樱花、双手持白杯的主体画面成立，仅作为执行链路与产物可读性证据。
- 结束后通过 SSH 隧道读取 ComfyUI，running=0、pending=0。测试 EXE 与隧道均已关闭；未关闭用户云实例。

证据：`.local/release-runtime-check/generation.json`、`result.png`、`queue-after.json`。

## 静态基准修正

原 `v3-static-v1` 在当前数据包首次运行失败，仅因要求必有 conservative lane。实际 required=8/8，排除与受保护类别泄漏=0，validator 错误=0；查询证实当前 maid/twintails 共现结果无标签达到 count≥20、score≥0.1 的已有阈值。生成器在无合格建议时不创建空增强候选是既有合法行为。

将套件版本改为 `v3-static-v1.1`，仅移除该例对 conservative lane 的强制要求；原词保留、排除、受保护类别、artist 与显式 hybrid 关系要求不变。新增无共现结果时的基准回归。原失败记录保留在 `.local/release-static-benchmark.log`；修正套件通过，记录在 `.local/release-static-benchmark-v1.1.log`。该改动不涉及生成算法或已冻结二进制。

## 产物

最终回归：V3 全量 436 项（0 failure/error/skip），V2 全量回归通过；Web 最近全量 74 项与 TypeScript/生产构建通过，本轮未修改前端。基准相关 20 项与 Windows 构建相关 5 项通过；PowerShell 语法及 git diff --check 通过。V3 全量机器报告在 `.local/release-v3-tests.xml`。仅余既有依赖弃用、大 JS chunk 和 Inno x64 别名弃用提醒，不影响本轮成功结果。

| 文件 | 字节 | SHA-256 |
| --- | ---: | --- |
| Portable ZIP | 286810508 | `5F05082F95BEBDD7FD25D77552B965FA6D6C6C4032E951E9E2F53B5BA0DB6B1A` |
| Setup EXE | 180451791 | `A3CD4CD2EE8BD22FE5724B7168FF3CF92AA245E01A7C3BC801236CEA0BDCDCD2` |

文件位于 `release/`。便携 ZIP 的 977 个条目 CRC 已验证。用户测试步骤见 [人工测试清单](../../MANUAL_TEST_20260910.md)。
