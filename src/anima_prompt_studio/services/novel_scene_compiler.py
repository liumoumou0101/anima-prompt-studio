from __future__ import annotations

import re

from anima_prompt_studio.domain.models import ItemState, PromptJob
from anima_prompt_studio.services.ai_extract_service import ExtractedPrompt
from anima_prompt_studio.services.prompt_compiler import PromptCompiler


_STRUCTURAL_NEGATIVES = (
    "looking at viewer",
    "split screen",
    "comic panels",
    "character sheet",
    "multiple views",
    "duplicated character",
    "merged bodies",
    "extra limbs",
    "floating limbs",
    "wrong character attributes",
)


class NovelSceneCompiler:
    """Compile the novel helper's frozen scene plan without the legacy MT path."""

    _CAMERA = {
        "portrait": ("single coherent scene",),
        "interaction": (
            "single coherent scene", "wide shot", "full body", "dynamic composition",
        ),
        "action": (
            "single coherent scene", "wide shot", "full body", "dynamic action composition",
            "side view",
        ),
        "group": (
            "single coherent scene", "wide shot", "ensemble composition",
            "deep depth of field", "lateral opposing composition",
        ),
    }

    @staticmethod
    def _unique(values) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            clean = re.sub(r"\s+", " ", str(value or "")).strip(" ,.")
            key = clean.casefold()
            if clean and key not in seen:
                seen.add(key)
                result.append(clean)
        return result

    @staticmethod
    def _people_tags(result: ExtractedPrompt) -> list[str]:
        if result.scene_type == "group":
            return ["multiple people", "crowd"]
        characters = result.selected_characters()
        female = sum("女" in character.identity for character in characters)
        male = sum("男" in character.identity for character in characters)
        tags: list[str] = []
        if female:
            tags.append(f"{female}girl" + ("s" if female > 1 else ""))
        if male:
            tags.append(f"{male}boy" + ("s" if male > 1 else ""))
        if not tags and characters:
            tags.append(f"{len(characters)}people")
        return tags

    def compile(
        self,
        job: PromptJob,
        result: ExtractedPrompt,
        compiler: PromptCompiler,
    ) -> PromptJob:
        scene_prompt = result.direct_anima_prompt()
        if not scene_prompt:
            raise ValueError("AI 没有返回复杂场景英文计划，不能绕过旧翻译链路编译。")

        # A positive viewer-gaze phrase from the planner would conflict with the
        # helper's default. Keep it only when the source extraction explicitly asks for it.
        explicit_viewer = any(
            "镜头" in character.gaze and not character.gaze.startswith(("不", "没有"))
            for character in result.selected_characters()
        )
        if not explicit_viewer:
            scene_prompt = re.sub(
                r"\bNo one is looking at (?:the )?(?:viewer|camera)\b[,.]?",
                "Every visible subject looks toward the action and away from the camera,",
                scene_prompt,
                flags=re.I,
            )
            scene_prompt = re.sub(
                r"\b(?:looking|looks?) at (?:the )?(?:viewer|camera)\b[,.]?",
                "looking away from the viewer,",
                scene_prompt,
                flags=re.I,
            )

        compiler.apply_model_defaults(job)
        profile = compiler.configs.get_model(job.model_profile_id)
        common = self._unique(
            compiler.effective_quality_tags(job)
            + ["anime illustration"]
            + self._people_tags(result)
            + list(self._CAMERA[result.scene_type])
        )
        job.original_zh = result.to_compiler_brief()
        job.normalized_zh = job.original_zh
        job.translated_en = scene_prompt
        job.canonical_prose = scene_prompt
        job.canonical_prose_ready = True
        job.positive_prompt = ", ".join(common) + "\n\n" + scene_prompt.rstrip(".") + "."
        negative = list(profile.negative_prompt)
        negative.extend(_STRUCTURAL_NEGATIVES)
        negative.extend(result.anima_negative_en)
        if result.scene_type == "action":
            negative.extend(("romantic couple pose", "dancing", "holding hands"))
        if result.scene_type == "group":
            negative.extend(("team portrait", "ceremonial lineup", "identical uniforms on both factions"))
        job.negative_prompt = ", ".join(self._unique(negative))
        job.compiled_prompt_state = ItemState.AUTO
        job.prompt_origin = "ai_generated"
        job.workflow_template_id = profile.workflow_template_id
        job.touch()
        return job
