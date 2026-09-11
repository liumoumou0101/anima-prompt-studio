"""V3 runtime defaults. Legacy transport DTOs do not own generation policy."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeProfile:
    id: str
    steps: int
    cfg: float
    sampler: str
    scheduler: str
    default_width: int = 896
    default_height: int = 1152

    @property
    def checkpoint_logical_name(self) -> str:
        return self.id

    @property
    def workflow_template_id(self) -> str:
        return "v3:" + self.id


class V3RuntimeProfiles:
    def __init__(self) -> None:
        self.profiles = {
            p.id: p for p in (
                RuntimeProfile("anima_base_v1", 35, 4.5, "er_sde", "normal"),
                RuntimeProfile("anima_aesthetic_v1", 35, 4.5, "euler", "normal"),
                RuntimeProfile("anima_aesthetic_v1_0", 35, 4.5, "euler", "normal"),
                RuntimeProfile("anima_aesthetic_v1_1", 35, 4.5, "euler", "normal"),
                RuntimeProfile("anima_turbo_v1", 10, 1, "er_sde", "simple"),
                RuntimeProfile("anima_turbo_v1_1", 10, 1, "er_sde", "simple"),
                RuntimeProfile("animayume_v1_0_final", 30, 5.5, "euler_ancestral", "normal"),
                RuntimeProfile("miaomiao_harem_anima_v1_6", 30, 4.5, "euler", "normal"),
            )
        }

    def get_model(self, model_id: str) -> RuntimeProfile:
        try:
            return self.profiles[model_id]
        except KeyError as exc:
            raise ValueError(f"未知 V3 模型：{model_id}") from exc

    def get_generation_preset(self, model_id: str, preset_id: str) -> RuntimeProfile:
        # Historical names are provenance only. Missing fields use V3 defaults.
        return self.get_model(model_id)
