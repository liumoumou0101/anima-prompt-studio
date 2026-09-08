"""Deterministic scene rendering shared by generation and validation.

Evidence tags describe what the index understood; they are not permission to
replace the rest of a user's sentence. Keep that distinction explicit here.
"""
from __future__ import annotations

import re

from ..domain import CandidateTag, IntentDocument
from .profiles import ModelProfile


def has_local_scene(intent: IntentDocument) -> bool:
    return bool(intent.scene_plan_en) and any(
        {"local_prose_baseline", "local_partial_prose_evidence"} & set(element.notes)
        for element in intent.graph.elements
    )


def contains_phrase(text: str, phrase: str) -> bool:
    pattern = re.escape(phrase).replace(r"\ ", r"[ _]+")
    return bool(re.search(r"(?<!\w)" + pattern + r"(?!\w)", text, re.I))


def render_scene(intent: IntentDocument, profile: ModelProfile, tags: list[CandidateTag]) -> str:
    scene = (intent.scene_plan_en or "").strip()
    blocked = [*intent.scene_negative_en, *intent.scene_suppressed_en]
    for phrase in sorted(blocked, key=len, reverse=True):
        pattern = re.escape(phrase).replace(r"\ ", r"[ _]+")
        scene = re.sub(r"(?<!\w)" + pattern + r"(?!\w)", "", scene, flags=re.I)
    scene = re.sub(r"\s+", " ", scene).strip(" ,;.")
    # Indexed REQUIRED facts are evidence, not an additional prompt. Explicit
    # user selections still take effect, without echoing facts already present.
    additions = [
        tag.rendered for tag in tags
        if tag.state.value in {"user_selected", "locked"}
        and not contains_phrase(scene, tag.rendered)
    ]
    prefixes = [part for part in profile.positive_prefix if not contains_phrase(scene, part)]
    return profile.tag_separator.join(dict.fromkeys(part for part in [*prefixes, scene, *additions] if part))


def negative_defaults(intent: IntentDocument, profile: ModelProfile) -> list[str]:
    """Only relax defaults for an explicit positive effect; user exclusions win."""
    positive = (intent.scene_plan_en or "") + " " + " ".join(
        element.canonical_tag or element.original_text
        for element in intent.graph.elements if element.state.value != "excluded"
    )
    relax = set()
    if re.search(r"\b(?:bokeh|depth[ _]of[ _]field|soft[ _]focus|blurred foreground|foreground blur)\b", positive, re.I):
        relax.add("blurry")
    if re.search(r"\b(?:chromatic[ _]aberration|prismatic light|prism light)\b", positive, re.I):
        relax.add("chromatic aberration")
    return [part for part in profile.negative_prompt if part not in relax]
