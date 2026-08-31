# V3 Tools

此目录只放 V3 自有的开发、数据导入、数据校验和基准报告工具。

无许可证的 `danbooru-tag-pipeline` 不复制到这里。它只能在外部环境运行，再把产物交给 V3 自有导入器。

当前构建命令由 Python 包提供：

```powershell
anima-v3-build-data --config <build-config.json>
```

上游文件获取与 V3 数据包构建是两个独立步骤。日常开发优先使用锁定 commit 的现成数据；只有需要重建或更新源数据时，才在仓库外部运行 pipeline。
