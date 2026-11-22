"""Explicit provenance list for generator rewrites, without scene inference."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .manual_tags import declared_tags
from .scene_design import declared_scene_choices


ORDINARY_UNLOCKED_FIELDS = {
    "subject": ("text",),
    "style": ("text", "medium"),
    "lighting": ("text",),
    "composition": ("text", "shot"),
    "exclusions": ("global", "scoped"),
}


def scene_choices_without_evidence(choices: dict | None) -> dict | None:
    """Copy selected values without historical prose used to establish them."""
    if choices is None:
        return None
    result = deepcopy(choices)
    for choice in result.values():
        if isinstance(choice, dict):
            choice.pop("evidence", None)
    return result


def prompt_edit_requirements(requirements: dict, *, inherited: dict | None = None) -> dict:
    """Project requirements for an authoritative prompt without changing stored data.

    A candidate may include new ordinary fields; with ``inherited``, only its
    unchanged inherited prose is masked. Locked content and selected controls
    remain available in both projections.
    """
    result = deepcopy(requirements)
    layers = result.get("layers") or {}
    inherited_layers = (inherited or {}).get("layers") or {}
    for layer_name, fields in ORDINARY_UNLOCKED_FIELDS.items():
        layer = layers.get(layer_name) or {}
        if layer.get("locked"):
            continue
        previous = inherited_layers.get(layer_name) or {}
        for field in fields:
            if field not in layer:
                continue
            if inherited is not None and (field not in previous or layer[field] != previous[field]):
                continue
            layer[field] = [] if layer_name == "exclusions" else ""

    composition = layers.get("composition") or {}
    if isinstance(composition.get("design"), dict):
        composition["design"] = scene_choices_without_evidence(composition["design"])
    lighting = layers.get("lighting") or {}
    if isinstance(lighting.get("mood"), dict):
        lighting["mood"].pop("evidence", None)
    return result


def _has_content(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def build_rewrite_sources(
    requirements: dict,
    current_prompt: dict | None,
    *,
    visible_prompt: bool,
    previous_manual_tags: list[str],
    bold_rewrite: bool = False,
) -> dict:
    """Classify explicit inputs by authority; keep their original values intact.

    This list describes provenance for a generator. It does not decide whether
    arbitrary wording in a candidate prompt satisfies a semantic constraint.
    """
    result: dict[str, Any] = {
        "authority": "visible_prompt" if visible_prompt else "requirements",
        "required": [],
        "previous_context": [],
        "superseded": [],
    }

    def add(bucket: str, path: str, value: Any) -> None:
        if _has_content(value):
            result[bucket].append({"path": path, "value": deepcopy(value)})

    layers = requirements.get("layers") or {}
    for layer_name, fields in ORDINARY_UNLOCKED_FIELDS.items():
        layer = layers.get(layer_name) or {}
        bucket = "previous_context" if visible_prompt and not layer.get("locked") else "required"
        for field in fields:
            add(bucket, f"requirements.layers.{layer_name}.{field}", layer.get(field))

    manual_fields = {
        "subject": ("character_tags", "series_tags", "general_tags"),
        "style": ("artists", "manual_artist_tags"),
    }
    for layer_name, fields in manual_fields.items():
        layer = layers.get(layer_name) or {}
        for field in fields:
            add("required", f"requirements.layers.{layer_name}.{field}", layer.get(field))

    design = (layers.get("composition") or {}).get("design") or {}
    for key, value in design.items():
        add("required", f"requirements.layers.composition.design.{key}", value)
    add("required", "requirements.layers.lighting.mood",
        (layers.get("lighting") or {}).get("mood"))

    for index, lora in enumerate(requirements.get("loras") or []):
        if not lora.get("enabled", True):
            continue
        add("required", f"requirements.loras[{index}].trigger_words",
            lora.get("trigger_words"))
    for index, lock in enumerate(requirements.get("prompt_locks") or []):
        add("required", f"requirements.prompt_locks[{index}]", lock)

    if current_prompt:
        bucket = "required" if visible_prompt else "previous_context"
        if bold_rewrite:
            # The reviewed positive is the design brief. Its explicit facts still
            # matter, while its unspecified presentation is open for the preview.
            result["creative_brief"] = []
        for field in ("positive", "negative"):
            add("creative_brief" if bold_rewrite and field == "positive" else bucket,
                f"compiled.{field}", current_prompt.get(field))
        current_controls = declared_scene_choices(requirements)
        for key, old_value in (current_prompt.get("scene_intent") or {}).items():
            if _has_content(old_value) and old_value != current_controls.get(key):
                add("superseded", f"compiled.scene_intent.{key}", old_value)

    current_tags = set(declared_tags(requirements))
    for index, tag in enumerate(previous_manual_tags):
        if tag not in current_tags:
            add("superseded", f"previous_manual_tags[{index}]", tag)
    return result
