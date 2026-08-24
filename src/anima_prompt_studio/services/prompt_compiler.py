from __future__ import annotations

import re

from anima_prompt_studio.domain.models import (
    CharacterSlot, GenerationFieldState, MatchedTag, ModelProfile, PromptJob, SubjectMode,
)
from .config_service import ConfigService
from .negation import phrase_has_unnegated_zh
from .quality_guard import QualityTagGuard


COMPOSITION_MAP = {
    "shot": {"头像": "portrait", "胸像": "bust", "半身": "upper body", "膝上": "cowboy shot", "全身": "full body", "远景": "wide shot"},
    "camera_height": {"平视": "eye level", "高机位": "from above", "低机位": "from below"},
    "angle": {"正面": "front view", "侧面": "from side", "背面": "from behind", "三分之四": "three-quarter view"},
    "gaze": {"看镜头": "looking at viewer", "看人物": "looking at another", "看物体": "looking at object", "看向画外": "looking away"},
    "subject_position": {"左": "subject on left", "中": "centered", "右": "subject on right"},
}

CATEGORY_ORDER = {
    "count": 10, "identity": 20, "hair": 30, "hair_length": 31, "eyes": 32, "clothing": 40,
    "expression": 50, "gaze": 51, "pose": 60, "shot": 70, "camera": 71, "angle": 72,
    "scene": 80, "weather": 90, "time": 91, "lighting": 92, "general": 100,
}

PRESET_MANAGED_FIELDS = frozenset({"steps", "cfg", "sampler", "scheduler"})
MODEL_DEPENDENT_FIELDS = PRESET_MANAGED_FIELDS


class PromptCompiler:
    def __init__(self, configs: ConfigService) -> None:
        self.configs = configs
        self.quality_guard = QualityTagGuard()

    def effective_quality_tags(self, job: PromptJob) -> list[str]:
        profile = self.configs.get_model(job.model_profile_id)
        quality = self.configs.get_quality(job.quality_profile_id)
        tags = self.quality_guard.filter(job, profile.positive_prefix + quality.all_tags())
        if profile.family == "anima":
            official_order = {"masterpiece": 0, "best quality": 1, "score_7": 2, "safe": 3}
            tags = [
                value for _, value in sorted(
                    enumerate(tags),
                    key=lambda item: (official_order.get(item[1], 100), item[0]),
                )
            ]
        return tags

    @staticmethod
    def _unique(values: list[str], excluded: set[str] | None = None) -> list[str]:
        excluded = excluded or set()
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = value if (re.fullmatch(r"score_[1-9]", value.strip()) or value.strip().startswith("@")) else value.replace("_", " ")
            clean = re.sub(r"\s+", " ", normalized).strip(" ,.")
            key = clean.casefold()
            if clean and key not in seen and clean not in excluded:
                seen.add(key)
                result.append(clean)
        return result

    def apply_model_defaults(
        self, job: PromptJob, reset_user_selected_fields: frozenset[str] = frozenset(),
    ) -> None:
        profile = self.configs.get_model(job.model_profile_id)
        try:
            preset = self.configs.get_generation_preset(job.model_profile_id, job.generation_preset_id)
        except ValueError:
            job.generation_preset_id = "balanced"
            preset = self.configs.get_generation_preset(job.model_profile_id, "balanced")
        params = job.generation_params
        defaults = {
            "width": profile.default_width,
            "height": profile.default_height,
            "steps": preset.steps,
            "cfg": preset.cfg,
            "sampler": preset.sampler,
            "scheduler": preset.scheduler,
        }
        for field, value in defaults.items():
            if field in reset_user_selected_fields and params.state(field) == GenerationFieldState.USER_SELECTED:
                params.set_state(field, GenerationFieldState.AUTO)
            if params.is_automatic(field):
                setattr(params, field, value)
        job.workflow_template_id = profile.workflow_template_id

    def apply_generation_preset(self, job: PromptJob, preset_id: str) -> None:
        self.configs.get_generation_preset(job.model_profile_id, preset_id)
        job.generation_preset_id = preset_id
        self.apply_model_defaults(job, reset_user_selected_fields=PRESET_MANAGED_FIELDS)

    @staticmethod
    def _is_count_tag(tag: str) -> bool:
        return re.fullmatch(r"\d+(?:girls?|boys?|others?|people)|solo", tag.replace("_", " ").strip()) is not None

    @staticmethod
    def _gender_signals(job: PromptJob, source: str) -> tuple[bool, bool]:
        if job.uses_english_authority():
            female = bool(re.search(
                r"\b(?:\d+girls?|girls?|woman|women|female|maids?|princess(?:es)?)\b", source, re.I,
            ))
            male = bool(re.search(
                r"\b(?:\d+boys?|boys?|man|men|male|princes?)\b", source, re.I,
            ))
            return female, male
        female = any(phrase_has_unnegated_zh(source, token) for token in (
            "女孩", "女人", "女性", "少女", "女仆", "公主",
        ))
        male = any(phrase_has_unnegated_zh(source, token) for token in (
            "男孩", "男人", "男性", "少年", "王子",
        ))
        return female, male

    def _people_tags(self, job: PromptJob) -> list[str]:
        n = job.composition.people_count
        mix = job.semantic_frame.final_attributes.get("people_mix", "")
        genders = [slot.gender_tag for slot in job.character_slots[:n] if slot.gender_tag]
        source = job.authoritative_text() or job.translated_en
        female_source, male_source = self._gender_signals(job, source)
        if not mix:
            if female_source and male_source:
                mix = "hetero"
            elif female_source:
                mix = "female"
            elif male_source:
                mix = "male"
        if mix == "2f1m":
            return ["2girls", "1boy"]
        if mix == "1f2m":
            return ["1girl", "2boys"]
        if n == 1:
            if genders:
                return [genders[0]]
            if mix == "male" or (male_source and not female_source):
                return ["1boy"]
            if mix == "female" or (female_source and not male_source):
                return ["1girl"]
            return ["1other"]
        if n == 2:
            if len(genders) >= 2:
                if all(x == "1girl" for x in genders[:2]):
                    return ["2girls"]
                if all(x == "1boy" for x in genders[:2]):
                    return ["2boys"]
                if set(genders[:2]) == {"1girl", "1boy"}:
                    return ["1girl", "1boy"]
            if mix == "hetero":
                return ["1girl", "1boy"]
            if mix == "female":
                return ["2girls"]
            if mix == "male":
                return ["2boys"]
            if female_source and not male_source:
                return ["2girls"]
            if male_source and not female_source:
                return ["2boys"]
            return ["2people"]
        if len(genders) >= n and all(x == "1girl" for x in genders[:n]):
            return [f"{n}girls"]
        if len(genders) >= n and all(x == "1boy" for x in genders[:n]):
            return [f"{n}boys"]
        if genders and len(genders) >= n and all(x == "1other" for x in genders[:n]):
            return [f"{n}others"]
        if mix == "female" or (female_source and not male_source):
            return [f"{n}girls"]
        if mix == "male" or (male_source and not female_source):
            return [f"{n}boys"]
        return [f"{n}people"]

    def _people_tag(self, job: PromptJob) -> str:
        return self._people_tags(job)[0]

    @staticmethod
    def _attribute_category(tag: str) -> str | None:
        value = tag.lower().replace("_", " ")
        if value in {"long hair", "very long hair", "short hair", "medium hair"}:
            return "hair_length"
        if value.endswith(" hair") or value.endswith("-haired"):
            return "hair"
        if value.endswith(" eyes"):
            return "eyes"
        if value in {"dress", "shirt", "skirt", "short skirt", "coat", "school uniform", "shorts", "pants", "boots", "shoes", "hat"}:
            return "clothing"
        if value in {"elf", "dark elf", "fox girl", "cat girl", "dragon girl"}:
            return "race"
        return None

    @staticmethod
    def _explicit_natural_categories(job: PromptJob) -> set[str]:
        text = job.translated_en.lower()
        categories = set()
        if re.search(r"(?:look(?:s|ing)? (?:away|at|toward|towards|outside)|(?:does|do|did)(?:n't| not) look at (?:the )?camera)", text): categories.add("gaze")
        if re.search(r"\b(?:full body|upper body|portrait|wide shot)\b", text): categories.add("shot")
        if re.search(r"\b(?:from behind|from the side|side view|front view)\b", text): categories.add("angle")
        return categories

    @staticmethod
    def _exclusive_group(tag: str) -> str | None:
        value = tag.lower().replace("_", " ").strip()
        groups = {
            "shot": {"portrait", "bust", "upper body", "cowboy shot", "full body", "wide shot"},
            "camera": {"eye level", "from above", "high angle", "from below", "low angle"},
            "angle": {"front view", "side view", "from side", "back", "back view", "from behind", "three-quarter view"},
            "gaze": {"looking at viewer", "looking away", "looking at another", "looking at object", "looking forward", "looking down"},
            "position": {"subject on left", "centered", "subject on right"},
        }
        return next((group for group, values in groups.items() if value in values), None)

    @classmethod
    def _enforce_composition_exclusivity(
        cls, tags: list[str], job: PromptJob, suppressed_groups: set[str] | None = None,
    ) -> list[str]:
        suppressed_groups = suppressed_groups or set()
        selected = {
            "shot": COMPOSITION_MAP["shot"].get(job.composition.shot, ""),
            "camera": COMPOSITION_MAP["camera_height"].get(job.composition.camera_height, ""),
            "angle": COMPOSITION_MAP["angle"].get(job.composition.angle, ""),
            "gaze": COMPOSITION_MAP["gaze"].get(job.composition.gaze, ""),
            "position": COMPOSITION_MAP["subject_position"].get(job.composition.subject_position, ""),
        }
        emitted: set[str] = set()
        result: list[str] = []
        for tag in tags:
            group = cls._exclusive_group(tag)
            if group in suppressed_groups:
                continue
            if not group:
                result.append(tag)
                continue
            if group in emitted:
                continue
            canonical = selected[group]
            if canonical:
                result.append(canonical)
                emitted.add(group)
        return result

    @staticmethod
    def _clean_natural(job: PromptJob) -> str:
        if any(item.enabled and item.replaces_translation for item in job.enhancements):
            return ""
        text = job.translated_en.strip()
        text = text.replace("♪", "").replace("♫", "").replace("�", "")
        for item in job.enhancements:
            if not item.enabled:
                continue
            for pattern in item.suppress_patterns:
                replacement = "sitting" if pattern.startswith("sitting") else ""
                text = re.sub(pattern, replacement, text, flags=re.I)
        text = re.sub(r"\s+,", ",", text)
        text = re.sub(r",\s*,+", ",", text)
        text = re.sub(r"\s{2,}", " ", text)
        text = re.sub(r",\s*([.!?])", r"\1", text)
        text = re.sub(r"\b(?:with|and)\s*([.!?])", r"\1", text, flags=re.I)
        return text.strip(" ,")

    @staticmethod
    def _character_position_prefix(slot: CharacterSlot, index: int, count: int) -> str:
        position = slot.position.strip().casefold()
        known = {
            "left": "On the left", "左": "On the left",
            "center": "In the center", "centre": "In the center", "中": "In the center",
            "right": "On the right", "右": "On the right",
            "front": "In front", "foreground": "In the foreground", "前": "In front",
            "back": "In back", "background": "In the background", "后": "In back",
        }
        if position in known:
            return known[position]
        if slot.position.strip():
            custom = slot.position.strip().rstrip(",")
            return custom[:1].upper() + custom[1:]
        defaults = ["On the left", "On the right"] if count == 2 else ["On the left", "In the center", "On the right"]
        return defaults[index] if count in (2, 3) and index < len(defaults) else f"Character {index + 1}"

    def _character_paragraph(self, slot: CharacterSlot, index: int, count: int) -> str:
        prefix = self._character_position_prefix(slot, index, count)
        features = self._unique(
            ([slot.display_name] if slot.display_name else []) + slot.identity_tags + slot.appearance_tags + slot.clothing_tags
        )
        detail = ", ".join(features)
        action = slot.action_text.strip().rstrip(".")
        body = ", ".join(x for x in (detail, action) if x)
        return f"{prefix}, {body}." if body else ""

    @staticmethod
    def _has_mixed_character_gaze(job: PromptJob) -> bool:
        intents: set[str] = set()
        patterns = {
            "viewer": r"\b(?:looking at (?:the )?(?:viewer|camera)|looks? at (?:the )?camera)\b",
            "away": r"\b(?:looking away|looking forward|looks? outside|not looking at (?:the )?camera)\b",
            "person": r"\b(?:looking at (?:the )?(?:other|another)(?: person)?|looking at each other)\b",
            "object": r"\b(?:looking at|watching) (?:a |an |the )?(?!viewer|camera|other|another)[a-z]+",
        }
        for slot in job.character_slots[:job.composition.people_count]:
            text = slot.action_text.casefold()
            slot_intent = next((name for name, pattern in patterns.items() if re.search(pattern, text, re.I)), None)
            if slot_intent:
                intents.add(slot_intent)
        return len(intents) > 1

    @staticmethod
    def _natural_enhancement_content(content: str, people_count: int) -> str:
        if people_count <= 1:
            return content
        text = content
        text = re.sub(r"\bShe has\b", "They have", text)
        text = re.sub(r"\bShe\b", "They", text)
        text = re.sub(r"\bshe\b", "they", text)
        text = re.sub(r"\bher\b", "them", text)
        return text

    def compile(self, job: PromptJob) -> PromptJob:
        profile = self.configs.get_model(job.model_profile_id)
        if profile.family != "anima":
            raise NotImplementedError(
                f"{profile.family} 模型族尚未实现专用提示词编译器；不会套用 ANIMA 规则。"
            )
        return self._compile_anima(job, profile)

    def _compile_anima(self, job: PromptJob, profile: ModelProfile) -> PromptJob:
        quality = self.configs.get_quality(job.quality_profile_id)
        suppressed = {tag for concept in job.resolved_concepts for tag in concept.suppresses_tags}
        suppressed.update(tag for item in job.enhancements if item.enabled for tag in item.suppress_tags)
        excluded = set(job.excluded_tags) | suppressed | {
            item.canonical_tag for item in job.semantic_frame.excluded_concepts
        }
        matched = sorted(
            (x for x in job.matched_tags if x.state.value != "excluded" and x.tag not in excluded),
            key=lambda x: CATEGORY_ORDER.get(x.category, 100),
        )
        has_multi_scope = (
            job.composition.people_count > 1
            and any(x.id == "multi_scope" and x.enabled for x in job.enhancements)
        )
        scoped_character_gaze = has_multi_scope and any(
            re.search(r"\b(?:looking|looks?|watching)\b", slot.action_text, re.I)
            for slot in job.character_slots[:job.composition.people_count]
        )
        mixed_character_gaze = job.composition.people_count > 1 and self._has_mixed_character_gaze(job)
        if mixed_character_gaze or scoped_character_gaze:
            matched = [item for item in matched if self._exclusive_group(item.tag) != "gaze"]
        locked_slot_categories = {
            category
            for slot in job.character_slots[:max(1, job.composition.people_count)] if slot.locked
            for value in (slot.appearance_tags + slot.clothing_tags)
            if (category := self._attribute_category(value))
        }
        if locked_slot_categories:
            matched = [
                item for item in matched
                if item.category not in locked_slot_categories
                and self._attribute_category(item.tag) not in locked_slot_categories
            ]
        if has_multi_scope:
            matched = [x for x in matched if (x.category not in {"hair", "hair_length", "eyes", "clothing"}
                       and self._attribute_category(x.tag) not in {"hair", "hair_length", "eyes", "clothing"}
                       and x.tag.lower() not in {
                           "blue pupils", "red pupils", "golden pupils", "book", "flower", "apple", "umbrella",
                           "holding book", "holding flower", "holding apple", "holding umbrella",
                           "sitting", "standing", "lying", "waving",
                       })]
        quality_tags = self.effective_quality_tags(job)
        scene_mode = job.effective_subject_mode() == SubjectMode.SCENE
        tags = [] if scene_mode else list(self._people_tags(job))
        # Official ANIMA order puts artist tags before general visual tags.
        tags += [a if a.startswith("@") else f"@{a}" for a in job.artist_selection]
        source_text = job.authoritative_text()
        if job.uses_english_authority():
            positive_crowd = re.search(r"\b(?:crowd|group of people|background people)\b", source_text, re.I)
            negative_crowd = re.search(r"\b(?:no|without)\s+(?:other\s+)?(?:people|crowd)\b", source_text, re.I)
        else:
            positive_crowd = re.search(r"背景.{0,4}(?:人物|人群)|群体|人群", source_text)
            negative_crowd = re.search(r"背景.{0,6}(?:没有|没|无|不要).{0,4}(?:其他人|人物|人群)", source_text)
        if not scene_mode and job.composition.people_count == 1 and (not positive_crowd or negative_crowd):
            tags.append("solo")
        tags += [x.tag for x in matched if x.category != "count" and not self._is_count_tag(x.tag)]
        tags += [tag for item in job.enhancements if item.enabled for tag in item.tags]
        normalized = [tag.replace("_", " ") for tag in tags]
        if any(tag in {"reverse cowgirl", "reverse cowgirl position"} for tag in normalized):
            tags = [
                tag for tag in tags
                if tag.replace("_", " ") not in {
                    "cowgirl position", "cowgirl",
                    "multiple views", "reference sheet", "turnaround",
                    "character sheet", "comic", "2koma", "4koma",
                }
            ]
        explicit_natural = self._explicit_natural_categories(job)
        composition_category = {"shot":"shot", "camera_height":"camera", "angle":"angle", "gaze":"gaze", "subject_position":"position"}
        tags += [COMPOSITION_MAP[key].get(getattr(job.composition, key), "") for key in COMPOSITION_MAP
                 if composition_category[key] not in explicit_natural
                 and not ((mixed_character_gaze or scoped_character_gaze) and key == "gaze")
                 and (not scene_mode or key == "shot")]
        tags += [trigger for lora in job.lora_selection for trigger in lora.trigger_words]
        tags = self._enforce_composition_exclusivity(
            tags, job, suppressed_groups={"gaze"} if mixed_character_gaze else None,
        )
        common = self._unique(quality_tags + tags + job.locked_tags, excluded)

        paragraphs: list[str] = []
        if not scene_mode and job.composition.people_count > 1:
            for index, slot in enumerate(job.character_slots[:job.composition.people_count]):
                paragraph = self._character_paragraph(slot, index, job.composition.people_count)
                if paragraph:
                    paragraphs.append(paragraph)
        elif not scene_mode and job.character_slots:
            slot = job.character_slots[0]
            explicit_categories = {x.category for x in matched}
            explicit_categories.update(filter(None, (self._attribute_category(x.tag) for x in matched)))
            slot_values = slot.identity_tags + slot.appearance_tags + slot.clothing_tags
            slot_values = [value for value in slot_values if self._attribute_category(value) not in explicit_categories]
            common = self._unique(common + slot_values, excluded)
            if slot.action_text:
                paragraphs.append(slot.action_text.strip().rstrip(".") + ".")

        # A completed canonical pass means the builder has made an
        # intentional decision, including the valid decision to emit no prose
        # for a trivial sentence such as "A girl.".  Only legacy/direct
        # compiler callers without a frame should fall back to raw MT output.
        natural_prose = (
            job.canonical_prose.strip()
            if job.canonical_prose_ready
            else job.translated_en.strip()
        )
        if natural_prose:
            paragraphs.append(natural_prose)

        job.positive_prompt = ", ".join(common) + (("\n\n" + "\n".join(paragraphs)) if paragraphs else "")
        negative_tags = list(profile.negative_prompt)
        if profile.negative_prompt_mode != "disabled":
            negative_tags.extend(x.canonical_tag for x in job.semantic_frame.excluded_concepts)
        job.negative_prompt = ", ".join(self._unique(negative_tags)) if profile.negative_prompt_mode != "disabled" else ""
        job.workflow_template_id = profile.workflow_template_id
        job.touch()
        return job
