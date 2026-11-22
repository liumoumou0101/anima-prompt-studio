# AutoDL 五模型私有镜像（2026-09-20）

## 状态

- 镜像名称：`ANIMA5-ComfyUI035-20260920`
- 镜像 UUID：`image-b8a765a7a7`
- 来源实例：`34c3488c03-e73db3b2`，西北 B 区 192 机，RTX 3080 Ti 12GB。
- 实例已关机；2026-09-20 00:10:54 提交保存镜像，目前等待平台完成。
- 保存过程中页面显示镜像大小 22.47GB；最终状态与账户容量尚待确认。
- 关机后账户显示余额 8.33 元；相对本次充值的 10 元已使用约 1.67 元，未超过预算。GPU 运行数量为 0。
- 用户要求今天到此为止，让平台自行保存，明天再继续；已停止主动检查。最后观察到的进度为 3.12%，当时仍是“保存中”，不能视为保存完成。
- 下次继续时：先在 AutoDL 镜像列表核对 `image-b8a765a7a7` 已保存成功、实际大小和账户总容量，再决定是否加入 2.9B；无需重复安装五模型或重复已完成的出图验收。尚未做从该镜像创建新实例的恢复验证。

## 内容和验收

ComfyUI 0.35.0；Python 3.12；PyTorch/torchaudio 2.8.0+cu128；torchvision 0.23.0+cu128。依赖检查 `pip check` 通过。

| 模型 | 基础出图验收 | 耗时 |
|---|---|---:|
| Anima Base v1.0 | 512×512，通过 | 10.065 秒 |
| Anima Turbo v1.1 | 512×512，通过 | 6.035 秒 |
| Anima Aesthetic v1.1 | 512×512，通过 | 6.039 秒 |
| MiaoMiao Harem ANIMA v1.6 | 512×512，通过 | 10.032 秒 |
| AnimaYume v1.5 Base | 512×512，通过 | 10.038 秒 |

Base 另完成 896×1152、35 步、CFG 4.5、er_sde/normal、shift 3 的正常参数验收，耗时 40.387 秒。其他四个模型的正常参数工作流已导出，但未做同等分辨率的完整生成测试。以上时间包括轮询和加载，不应作为模型速度排名。

七个独立权重共 22,357,057,638 字节，大小与 SHA-256 全部通过校验。MiaoMiao 的编码器别名使用硬链接复用共享 Qwen 编码器。所有验收 PNG 均有工作流元数据，五个模型的权重引用已核对。

关机前生成队列为空；系统盘、模型及兼容目录均已检查。五份顶层编号工作流符合现有提示词工具的扫描目录、文件名和 `prompt` 包装要求；这是路径和格式检查，未做提示词工具桌面端的端到端连接验收。

## 使用

在 AutoDL 创建实例时选择“我的镜像”中的上述镜像。SSH 地址、端口和密码以该实例控制台显示的值为准，不要沿用旧平台端口。

每次开机后，通过 SSH 或 JupyterLab 终端执行：

```bash
bash /root/start_comfyui.sh
```

当前采用手动启动，没有配置开机自启。ComfyUI 监听服务器的 `127.0.0.1:8188`。提示词工具使用 SSH 连接，远程 ComfyUI 主机填 `127.0.0.1`、端口填 `8188`。

| 用途 | 服务器路径 |
|---|---|
| ComfyUI | `/root/ComfyUI` |
| 旧工具兼容目录 | `/workspace/ComfyUI`，链接至 `/root/ComfyUI` |
| 五份正常参数工作流 | `/root/ComfyUI/user/default/workflows/01_` 至 `05_` 开头的 JSON |
| 使用说明 | `/root/README-AutoDL-Anima.md` |
| 日志与验收记录 | `/root/autodl-build` |

运行环境、模型、工作流与启动脚本都在系统盘，随镜像保存。`/root/autodl-tmp` 是数据盘，未包含在镜像中。停止使用后需在控制台关机，断开 SSH 不会停止 GPU 计费。

## 2.9B 空间评估

按用户决定，目前不安装 Anima 2.9B，先保存五模型镜像。

关机前系统盘实际总量 32,212,254,720 字节，使用 24,122,204,160 字节，剩余 8,090,050,560 字节。已有来源记录中的 `Anima-2.9B-preview-v1.safetensors` 为 5,843,204,206 字节；若复用共享编码器和 VAE，增加后预计剩余 2,246,846,354 字节（约 2.09GiB）。可以容纳权重，但后续更新、输出图片和下载缓存的余量偏紧。

平台显示的 GB 与本报告按字节计算的十进制 GB 不应混用。镜像最终容量以及加入 2.9B 后的容量以平台显示为准。免费额度按账户全部镜像合计计算，不能将每一份镜像都视为独享 30GB；保留五模型旧镜像并再保存六模型新镜像会增加总量。

## 证据

本机原始文件位于项目 `.local/autodl-build-20260919/evidence/`：`smoke-results.json`、`normal-base-result.json`、`environment-result.json`、`models-verified.json`、`workflow-export.log`、`system-stats.json` 和六张验收 PNG。

官方说明：[保存镜像](https://www.autodl.com/docs/image/)、[计费规则](https://www.autodl.com/docs/price/)、[系统盘和数据盘](https://www.autodl.com/docs/env/)。
