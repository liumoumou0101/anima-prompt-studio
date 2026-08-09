from __future__ import annotations

from dataclasses import dataclass

from anima_prompt_studio.domain.execution_models import RemoteAuthType


@dataclass(frozen=True)
class ProviderPreset:
    id: str
    display_name: str
    ssh_port: int
    ssh_user: str
    auth_type: RemoteAuthType
    comfy_host: str = "127.0.0.1"
    comfy_port: int = 8188
    notes: str = ""


DEFAULT_PROVIDER_PRESET_ID = "compshare_container"

PROVIDER_PRESETS = (
    ProviderPreset(
        id="compshare_container",
        display_name="优云智算 · 容器/社区镜像（默认）",
        ssh_port=23,
        ssh_user="root",
        auth_type=RemoteAuthType.PASSWORD,
        notes="优云智算基础镜像和社区镜像：root、SSH 端口 23、控制台密码。",
    ),
    ProviderPreset(
        id="compshare_ubuntu",
        display_name="优云智算 · Ubuntu 系统镜像",
        ssh_port=22,
        ssh_user="ubuntu",
        auth_type=RemoteAuthType.PASSWORD,
        notes="优云智算 Ubuntu 系统镜像：ubuntu、SSH 端口 22、控制台密码。",
    ),
    ProviderPreset(
        id="custom",
        display_name="其他云主机 / 自定义",
        ssh_port=22,
        ssh_user="root",
        auth_type=RemoteAuthType.PRIVATE_KEY,
        notes="通用 SSH 默认值；请按云服务商提供的信息修改。",
    ),
)

PROVIDER_PRESETS_BY_ID = {preset.id: preset for preset in PROVIDER_PRESETS}


def get_provider_preset(preset_id: str) -> ProviderPreset:
    return PROVIDER_PRESETS_BY_ID.get(preset_id, PROVIDER_PRESETS_BY_ID["custom"])
