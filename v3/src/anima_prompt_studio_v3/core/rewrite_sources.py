"""Explicit provenance list for generator rewrites, without scene inference."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .manual_tags import declared_tags
from .scene_design import declared_scene_choices


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
    ordinary_fields = {
        "subject": ("text",),
        "style": ("text", "medium"),
        "lighting": ("text",),
        "composition": ("text", "shot"),
        "exclusions": ("global", "scoped"),
    }
    for layer_name, fields in ordinary_fields.items():
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
        add("required", f"requirements.loras[{index}].trigger_words",
            lora.get("trigger_words"))
    for index, lock in enumerate(requirements.get("prompt_locks") or []):
        add("required", f"requirements.prompt_locks[{index}]", lock)

    if current_prompt:
        bucket = "required" if visible_prompt else "previous_context"
        for field in ("positive", "negative"):
            add(bucket, f"compiled.{field}", current_prompt.get(field))
        current_controls = declared_scene_choices(requirements)
        for key, old_value in (current_prompt.get("scene_intent") or {}).items():
            if _has_content(old_value) and old_value != current_controls.get(key):
                add("superseded", f"compiled.scene_intent.{key}", old_value)

    current_tags = set(declared_tags(requirements))
    for index, tag in enumerate(previous_manual_tags):
        if tag not in current_tags:
            add("superseded", f"previous_manual_tags[{index}]", tag)
    return result
