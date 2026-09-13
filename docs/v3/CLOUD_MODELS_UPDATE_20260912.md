# 云端 ComfyUI 与 Anima 社区模型升级记录（2026-09-12）

目标实例：117.50.193.201。用户指定只安装到现有实例，不制作平台私有镜像。

## 完成状态

- ComfyUI 从 0.25.0（b910f4fa2ae3c816ca29bb99f8ebc5baee3387ae）更新为官方稳定版 0.35.0（40c4fcdf513a4523e39d54a9d391908af8df8171）。
- 前端 1.51.10，工作流模板 0.11.57；首页和前端静态资源返回 HTTP 200。
- PyTorch 2.11.0+cu128 切换为 2.11.0+cu130；torchvision 0.26.0+cu130、torchaudio 2.11.0+cu130。显卡 RTX 3080 Ti 12 GB，宿主驱动 595.80；CUDA BF16 矩阵运算通过。
- 直接使用 ComfyUI 原生模型识别：Anima-2.9B 为 40 层，Yume 1.5 与 Aesthetic 1.1 各 28 层。临时作者补丁已移出 custom_nodes，无额外补丁参与最终验证。
- 升级前后可用节点数 2772 → 2901。保存的 28 套工作流全部通过所需节点存在性检查；这不是 28 套工作流的完整生成验收。移除的是上游退役的第三方 API 节点，完整差异见本机验证记录。
- pip check 唯一报告为原来就存在的 decord 0.6.0 平台兼容提示，升级没有新增依赖冲突。
- 三张实际图片完成，结束时生成队列为空。没有关闭实例。

## 安装的权重

目录：`/workspace/ComfyUI/models/diffusion_models`，实际路径 `/workspace/proxy/ComfyUI/models/diffusion_models`。

- `Anima-2.9B-preview-v1.safetensors`：5843204206 字节；SHA-256 `0b3020d1b906155f7eb30667622723e87160632c8c7a5f1c93bdce685f2a346d`。
- `AnimaYume_v15_base.safetensors`：4182218328 字节；SHA-256 `16354589c360b1690842c4c4d04046c35ad4de4516b15a06ac7aa350dc3265f2`。

权重均来自原作者 Hugging Face 仓库的固定提交：2.9B 使用 `Gazingstars123/Anima-2.9B@9f9cb502dbae7a616c3cc5a530633427fe735665`；Yume 使用 `duongve/AnimaYume@e6d0f401dedb712a0a1b9620cd926ccf99c8ece3`。Yume 哈希亦与 Civitai 版本 3300637 的 BF16 文件一致。保留所有旧模型，复用原有 Qwen3 0.6B 文本编码器和 Qwen Image VAE。

## 实际生成验证

| 模型 | 耗时（含加载、等待与下载） | ComfyUI prompt_id |
|---|---|---|
| Anima-2.9B-preview-v1.safetensors | 84.0 秒 | 85c274b0-6cab-4f90-9227-53b7e4a789e3 |
| AnimaYume_v15_base.safetensors | 50.49 秒 | 17646dbe-041a-49e6-9ce6-6d6ea6ed4cd6 |
| anima-aesthetic-v1.1.safetensors | 46.75 秒 | 0f8b05f0-1872-423e-a68f-1356eeb12bff |

统一提示词为成人女性在日光咖啡馆中手持杯子的动漫插画，896×1152，种子 2026091201，30 步，不使用 LoRA。2.9B：Euler / sgm_uniform / CFG 4；Yume：Euler a / normal / CFG 5.5；Aesthetic：Euler / normal / CFG 4.5。负向为 `worst quality, low quality, blurry, jpeg artifacts`。这是安装和兼容性验收，不是模型审美排名或严格速度对比。

新模型的可导入 API 工作流存放于 `/workspace/ComfyUI/user/default/workflows/Anima_community_20260912/`。没有修改提示词工具中的既有模型配方或既有工作流参数。

## 备份与证据

- 旧版代码、启动配置、用户目录和完整 Python 环境：`/workspace/model-download-logs/anima-updates-20260912/comfyui-0.25.0-backup/`。
- 下载及升级记录：`/workspace/model-download-logs/anima-updates-20260912/`。
- 本机原始来源、固定版本、哈希、实际提交图、PNG、历史响应与验证：项目 `.local/model-research-20260912/`。PNG 中的实际 prompt 元数据已与提交图逐项核对。

## 研究结论

两者都是社区衍生模型。2.9B 的公开实测对细节和新知识有正面反馈，也有速度下降与画风变化的评价；Yume 1.5 刚发布，Civitai 本次版本统计为 2416 次下载、194 个赞，作者明确此版没有审美微调且还未全面测试。因此作为补充模型安装，不能宣称全面优于 Aesthetic。旧 Anima LoRA 在新模型上的表现需要重新验证。

来源：[2.9B 作者](https://huggingface.co/Gazingstars123/Anima-2.9B)、[Yume 作者](https://huggingface.co/duongve/AnimaYume)、[Yume 1.5 版本](https://civitai.com/models/2385278/animayume?modelVersionId=3300637)、[2.9B 同参数实测](https://note.com/akb428/n/n000c5d147a14)、[48 图对比](https://note.com/tasty_cougar8018/n/n66a83821e7b7)、[ComfyUI 0.35.0](https://github.com/Comfy-Org/ComfyUI/releases/tag/v0.35.0)、[PyTorch 官方安装表](https://pytorch.org/get-started/previous-versions/)。
