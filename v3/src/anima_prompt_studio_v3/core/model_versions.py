"""Explicit model versions; the unsuffixed Aesthetic ID is legacy data only."""
import re

LEGACY_AESTHETIC = "anima_aesthetic_v1"
AESTHETIC_VERSIONS = {"anima_aesthetic_v1_0", "anima_aesthetic_v1_1"}


def aesthetic_checkpoint_version(filename: str) -> str | None:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1].lower()
    match = re.fullmatch(r"anima[-_]aesthetic[-_]v1[._]([01])\.safetensors", name)
    return f"anima_aesthetic_v1_{match[1]}" if match else None


def workflow_models(profile) -> list[str]:
    declared = list(profile.compatible_model_profiles)
    binding = profile.bindings.get("checkpoint")
    value = profile.api_workflow.get(binding.node_id, {}).get("inputs", {}).get(binding.input_name) if binding else None
    version = aesthetic_checkpoint_version(value) if isinstance(value, str) else None
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
