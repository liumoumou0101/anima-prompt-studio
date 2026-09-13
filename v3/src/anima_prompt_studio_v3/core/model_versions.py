"""Explicit model versions; the unsuffixed Aesthetic ID is legacy data only."""
import re

LEGACY_AESTHETIC = "anima_aesthetic_v1"
AESTHETIC_VERSIONS = {"anima_aesthetic_v1_0", "anima_aesthetic_v1_1"}
COMMUNITY_VERSIONS = {"anima_2_9b_preview_v1", "animayume_v1_5_base", "animayume_v1_0_final"}


def community_checkpoint_version(filename: str) -> str | None:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1].lower()
    aliases = {
        "anima-2.9b-preview-v1.safetensors": "anima_2_9b_preview_v1",
        "animayume_v15_base.safetensors": "animayume_v1_5_base",
        "animayume_v15base.safetensors": "animayume_v1_5_base",
        "animayume_v10basefinal.safetensors": "animayume_v1_0_final",
        "animayume_v10_final_base.safetensors": "animayume_v1_0_final",
    }
    return aliases.get(name)


def requires_expanded_anima(profile) -> bool:
    return "anima_2_9b_preview_v1" in workflow_models(profile)


def expanded_anima_version_error(version: str | None) -> str | None:
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)(?:\D|$)", version or "")
    if not match:
        return "未取得 ComfyUI 版本，请重新检测；Anima 2.9B 需要 ComfyUI 0.33.1 或更新版本的原生 40 层支持。"
    if tuple(map(int, match.groups())) < (0, 33, 1):
        return "Anima 2.9B 需要 ComfyUI 0.33.1 或更新版本；旧版可能只加载 28 层，请更新后重新检测。"
    return None


def aesthetic_checkpoint_version(filename: str) -> str | None:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1].lower()
    match = re.fullmatch(r"anima[-_]aesthetic[-_]v1[._]([01])\.safetensors", name)
    return f"anima_aesthetic_v1_{match[1]}" if match else None


def workflow_models(profile) -> list[str]:
    declared = list(profile.compatible_model_profiles)
    binding = profile.bindings.get("checkpoint")
    value = profile.api_workflow.get(binding.node_id, {}).get("inputs", {}).get(binding.input_name) if binding else None
    version = aesthetic_checkpoint_version(value) if isinstance(value, str) else None
    community_version = community_checkpoint_version(value) if isinstance(value, str) else None
    if community_version and any(item != community_version for item in declared):
        return []
    if version and COMMUNITY_VERSIONS.intersection(declared):
        return []
    if LEGACY_AESTHETIC in declared and version:
        declared = [version if item == LEGACY_AESTHETIC else item for item in declared]
    # A declared version must not silently point at the other known weight.
    if version and any(item in AESTHETIC_VERSIONS and item != version for item in declared):
        return []
    return list(dict.fromkeys(declared))


def model_matches_workflow(model: str, profile) -> bool:
    models = workflow_models(profile)
    # Historical frozen jobs may retain the family ID; their graph fixes the weight.
    return model in models or (model == LEGACY_AESTHETIC and bool(AESTHETIC_VERSIONS.intersection(models)))


def matches_model_declaration(model: str, declared) -> bool:
    """Legacy reference compatibility declared the family, not a concrete weight."""
    return model in declared or (model in AESTHETIC_VERSIONS and LEGACY_AESTHETIC in declared)
