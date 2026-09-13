"""Explicit scene-design intent. No tag expansion or legacy composition presets."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SceneField = Literal["shot", "layout", "camera", "gaze", "mood"]


def declared_scene_choices(requirements: dict | None) -> dict:
    layers = (requirements or {}).get("layers", {})
    result = {key: value for key, value in (layers.get("composition", {}).get("design") or {}).items() if value}
    mood = layers.get("lighting", {}).get("mood")
    if mood:
        result["mood"] = mood
    return result


class SceneChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    value: str = Field(min_length=1, max_length=400)
    source: Literal["user", "extracted", "suggestion"] = "user"
    target: str = Field(default="", max_length=200)
    evidence: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def extraction_has_evidence(self):
        if self.source == "extracted" and not self.evidence:
            raise ValueError("原文提取必须保留原句。")
        return self


class SceneDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shot: SceneChoice | None = None
    layout: SceneChoice | None = None
    camera: SceneChoice | None = None
    gaze: SceneChoice | None = None

    @model_validator(mode="after")
    def gaze_has_target(self):
        if self.gaze is not None and not self.gaze.target:
            raise ValueError("请明确视线作用的人物，例如：左侧女孩。")
        return self


SCENE_DESIGN_COMPILER_RULES = """
Scene-design controls are semantic creative requirements, never a fixed tag template.
composition.design contains shot (framing), layout (spatial composition), camera
(camera position/angle), and gaze (person's gaze with an explicit target).
lighting.mood is the requested atmosphere. Missing/null values mean unspecified.
These fields are read-only in layer_updates. Do not copy them into layer text or
composition.shot: doing so would leave obsolete text when the user clears a control.
source=user is an explicit choice; source=extracted preserves the quoted evidence;
source=suggestion is a suggestion that the user has explicitly adopted. Unadopted
suggestions are never requirements. Respect targets; never assign one person's gaze
to all people. Camera angle is not head pose; looking into the distance is not merely
looking away from the viewer. Express intent together with the WHOLE scene, preserve
all compatible text, identities, counts, ownership, locks and manual tags.
Current controls replace older control values, not independently written requirements.
If a control contradicts independently written text or locked requirements, do not
silently choose a side: return conflicts as a brief string array describing the exact
conflict for the user to resolve. Otherwise conflicts=[]. The server rejects conflicts.
Do not infer missing scene controls, quality phrases, artists, LoRAs or negative tags.
Clearing a control removes its prior request; do not recover it from compiled text.
compiled.scene_intent records the controls used by the previous compilation. Compare
it with current controls to remove superseded/cleared control intent while retaining
independently written user text. It is provenance, not an additional requirement.
Preserve reviewed negative text unless explicitly requested otherwise.
"""
