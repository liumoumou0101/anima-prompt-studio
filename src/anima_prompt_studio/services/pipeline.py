from __future__ import annotations

import re

from anima_prompt_studio.domain.models import (
    CompositionFieldState, ItemState, LoRAProfile, PromptJob, SemanticWarning, SubjectMode, WarningLevel,
)
from .canonical_prose import CanonicalProseBuilder
from .config_service import ConfigService
from .concept_resolver import ConceptResolver
from .composition_recommender import CompositionRecommendationService
from .composition_context import CompositionContextExtractor
from .enhancer import PromptEnhancer
from .entity_protector import EntityProtector
from .input_preprocessor import InputPreprocessor
from .final_consistency import FinalConsistencyService
from .lora_resolver import LoRAResolver
from .multi_scope import MultiScopeService
from .prompt_compiler import MODEL_DEPENDENT_FIELDS, PromptCompiler
from .prompt_complexity import PromptComplexityService
from .semantic_diff import SemanticDiffService
from .semantic_frame import SemanticFrameResolver
from .tag_matcher import TagMatcher
from .translation_service import TranslationService
from .visual_semantics import VisualSemanticNormalizer


class PromptPipeline:
    def __init__(self, translation: TranslationService | None = None, configs: ConfigService | None = None,
                 lora_profiles: list[LoRAProfile] | None = None) -> None:
        self.configs = configs or ConfigService()
        self.translation = translation or TranslationService()
        self.preprocessor = InputPreprocessor()
        self.semantic_frames = SemanticFrameResolver()
        self.visual_semantics = VisualSemanticNormalizer()
        self.protector = EntityProtector()
        self.concepts = ConceptResolver()
        self.composition_context = CompositionContextExtractor()
        self.composition_recommender = CompositionRecommendationService(self.configs)
        self.matcher = TagMatcher()
        self.multi_scope = MultiScopeService()
        self.enhancer = PromptEnhancer()
        self.prose_builder = CanonicalProseBuilder()
        self.lora_resolver = LoRAResolver(lora_profiles)
        self.final_consistency = FinalConsistencyService()
        self.diff = SemanticDiffService()
        self.compiler = PromptCompiler(self.configs)
        self.prompt_complexity = PromptComplexityService()

    def translate(self, job: PromptJob, known_entities: list[tuple[str, str]] | None = None) -> PromptJob:
        if job.translation_state == ItemState.LOCKED and job.translated_en:
            return self.recompile(job)
        job.translation_state = ItemState.AUTO
        job.normalized_zh = self.preprocessor.normalize(job.original_zh)
        job.composition_context = self.composition_context.extract(job)
        job.resolved_concepts = self.concepts.resolve(job.normalized_zh)
        protected, job.protected_entities = self.protector.protect(job.normalized_zh, known_entities or [])
        job.semantic_frame = self.semantic_frames.resolve(job.normalized_zh, job.protected_entities)
        job.semantic_frame = self.visual_semantics.enrich(job.semantic_frame, job.normalized_zh)
        job.composition.people_count = job.semantic_frame.people_count if job.semantic_frame.people_count is not None else 1
        extracted_artists = job.semantic_frame.artist_mentions
        self._replace_text_derived_artists(job, extracted_artists)
        job.lora_selection, unresolved = self.lora_resolver.resolve(job.semantic_frame.lora_mentions, job.lora_selection)
        job.semantic_frame.unresolved_lora_mentions = unresolved
        translation_input = self._strip_control_directives(protected, job.protected_entities)
        translation_input, visual_replacements = self.visual_semantics.protect(translation_input, job.semantic_frame)
        translated = self.translation.zh_to_en(translation_input)
        translated = self.visual_semantics.restore(translated, visual_replacements)
        job.translated_en = self.protector.restore(translated, job.protected_entities)
        job.translated_en = self.visual_semantics.ensure_translation(job.translated_en, job.semantic_frame)
        job.translated_en = self.translation.guard_artist_intent(job.normalized_zh, job.translated_en)
        job.translated_en = self.concepts.apply_translation(job.normalized_zh, job.translated_en, job.resolved_concepts)
        job.translated_en = self.enhancer.normalize_translation(job.normalized_zh, job.translated_en)
        job.translation_state = ItemState.AUTO
        return self.recompile(job)

    def update_english(self, job: PromptJob, english: str) -> PromptJob:
        job.translated_en = english.strip()
        job.translation_state = ItemState.USER_EDITED
        return self.recompile(job)

    def recompile(self, job: PromptJob, people_count_override: int | None = None) -> PromptJob:
        protected, entities = self.protector.protect(job.translated_en, [(x.original, x.entity_type) for x in job.protected_entities])
        job.back_translated_zh = self.protector.restore(self.translation.en_to_zh(protected), entities)
        source_zh = job.normalized_zh or job.original_zh
        english_authority = job.uses_english_authority()
        job.composition_context = self.composition_context.extract(job)
        job.semantic_frame = (
            self.semantic_frames.resolve_english(job.translated_en, entities)
            if english_authority
            else self.semantic_frames.resolve(source_zh, job.protected_entities)
        )
        if not english_authority:
            job.semantic_frame = self.visual_semantics.enrich(job.semantic_frame, source_zh)
        if english_authority:
            job.semantic_frame.lora_mentions = list(dict.fromkeys(
                job.semantic_frame.lora_mentions + self.lora_resolver.mentions_in_text(job.translated_en)
            ))
        if people_count_override is not None and job.effective_subject_mode() != SubjectMode.SCENE:
            job.composition.people_count = max(1, people_count_override)
        elif job.semantic_frame.people_count is not None:
            job.composition.people_count = job.semantic_frame.people_count
        self._replace_text_derived_artists(job, job.semantic_frame.artist_mentions)
        job.lora_selection, unresolved = self.lora_resolver.resolve(job.semantic_frame.lora_mentions, job.lora_selection)
        job.semantic_frame.unresolved_lora_mentions = unresolved
        if not job.resolved_concepts and job.translation_state == ItemState.AUTO:
            job.resolved_concepts = self.concepts.resolve(source_zh)
        previous = {item.id: item for item in job.enhancements}
        if english_authority:
            generated = [
                item.model_copy(deep=True) for item in previous.values()
                if item.state in (ItemState.USER_EDITED, ItemState.LOCKED)
            ]
        else:
            generated = self.enhancer.enhance(source_zh, job.translated_en, job.semantic_frame)
            scoped_slots = self.multi_scope.extract_slots(source_zh, job.composition.people_count)
            if scoped_slots:
                self._merge_auto_character_slots(job, scoped_slots)
            multi_scope = self.multi_scope.build(source_zh, job.composition.people_count)
            if multi_scope:
                if scoped_slots:
                    multi_scope.content = ""
                generated.append(multi_scope)
        for item in generated:
            if item.id in previous:
                item.enabled = previous[item.id].enabled
                item.state = previous[item.id].state
                if previous[item.id].state in (ItemState.USER_EDITED, ItemState.LOCKED):
                    item.content = previous[item.id].content
        generated_ids = {item.id for item in generated}
        generated.extend(
            item for item in previous.values()
            if item.id not in generated_ids and item.state in (ItemState.USER_EDITED, ItemState.LOCKED)
        )
        job.enhancements = generated
        self.prose_builder.build(job)
        matching_chinese = source_zh if not english_authority else ""
        semantic_exclusions = {x.canonical_tag for x in job.semantic_frame.excluded_concepts}
        job.matched_tags = self.matcher.match(
            job.canonical_prose or job.translated_en, matching_chinese, context=job.composition_context,
            excluded=set(job.excluded_tags) | semantic_exclusions, locked=set(job.locked_tags),
        )
        if job.translation_state == ItemState.AUTO:
            suppress = {tag for concept in job.resolved_concepts for tag in concept.suppresses_tags}
            concept_tags = self.concepts.as_tags(job.resolved_concepts)
            job.matched_tags = [x for x in job.matched_tags if x.tag not in suppress and x.tag not in {y.tag for y in concept_tags}]
            excluded_now = set(job.excluded_tags) | semantic_exclusions
            job.matched_tags.extend(x for x in concept_tags if x.tag not in excluded_now)
            job.matched_tags = self.visual_semantics.merge_tags(
                job.matched_tags, job.semantic_frame, excluded_now, set(job.locked_tags),
            )
        self.composition_recommender.recommend(job)
        self.compiler.compile(job)
        diff_source = job.back_translated_zh if english_authority else source_zh
        job.semantic_warnings = self.diff.compare(diff_source, job.positive_prompt, job.back_translated_zh)
        consistency, cleanliness = self.final_consistency.validate(job)
        job.semantic_warnings.extend(
            SemanticWarning(level=WarningLevel.RED, concept="最终一致性", message=message)
            for message in consistency
        )
        job.semantic_warnings.extend(
            SemanticWarning(level=WarningLevel.YELLOW, concept="英文清洁性", message=message)
            for message in cleanliness
        )
        job.semantic_warnings.extend(
            SemanticWarning(
                level=WarningLevel.YELLOW,
                concept="多人作用域",
                message=message + "；最终 ANIMA Prompt 已优先采用中文分区事实。",
            )
            for message in self.multi_scope.translation_scope_failures(
                job.translated_en,
                job.character_slots[:job.composition.people_count],
            )
            if any(item.id == "multi_scope" and item.enabled for item in job.enhancements)
        )
        complexity_warning = self.prompt_complexity.analyze(source_zh)
        if complexity_warning:
            job.semantic_warnings.append(complexity_warning)
        job.semantic_warnings.extend(
            self.prompt_complexity.analyze_model_fit(job.model_profile_id, job.semantic_frame)
        )
        return job

    def set_lora_profiles(self, profiles: list[LoRAProfile]) -> None:
        self.lora_resolver.set_profiles(profiles)

    @staticmethod
    def _merge_auto_character_slots(job: PromptJob, scoped_slots) -> None:
        for index, candidate in enumerate(scoped_slots):
            if index >= len(job.character_slots):
                job.character_slots.append(candidate)
                continue
            current = job.character_slots[index]
            has_user_content = bool(
                current.display_name or current.identity_tags or current.appearance_tags
                or current.clothing_tags or current.action_text
            )
            if current.locked and has_user_content:
                continue
            candidate.id = current.id
            job.character_slots[index] = candidate

    @staticmethod
    def _replace_text_derived_artists(job: PromptJob, mentions: list[str]) -> None:
        preserved = [
            artist for artist in job.artist_selection
            if job.artist_selection_sources.get(artist, "manual") != "text_derived"
        ]
        sources = {
            artist: job.artist_selection_sources.get(artist, "manual")
            for artist in preserved
        }
        for artist in mentions:
            if artist not in preserved:
                preserved.append(artist)
                sources[artist] = "text_derived"
        job.artist_selection = preserved
        job.artist_selection_sources = sources

    def recommend_composition(self, job: PromptJob, alternative_index: int = 0) -> PromptJob:
        self.composition_recommender.recommend(job, alternative_index=alternative_index)
        return self._compile_preserving_authored_prompt(job)

    @staticmethod
    def _infer_people_count(job: PromptJob, entities=()) -> None:
        text = job.normalized_zh or job.original_zh
        if job.composition.people_count != 1:
            return
        if any(token in text for token in ("三个女孩", "三名女孩", "三个人", "三人")):
            job.composition.people_count = 3
        elif any(token in text for token in (
            "两个女孩", "两名女孩", "两个人", "两人",
            "一个女孩和一个男孩", "一个男孩和一个女孩",
            "一对男女", "一对情侣", "一男一女", "一女一男", "男女在",
        )):
            job.composition.people_count = 2
        else:
            character_count = len({x.original for x in entities if x.entity_type == "character"})
            if character_count > 1:
                job.composition.people_count = character_count

    @staticmethod
    def _strip_control_directives(text: str, entities) -> str:
        """Remove artist/LoRA control prose before MT; both compile structurally."""
        result = text
        for entity in entities:
            handle = re.escape(entity.placeholder)
            if entity.entity_type == "artist":
                result = re.sub(rf"(?:使用|采用|以)\s*{handle}\s*(?:的)?(?:画风|风格)", "", result)
                result = re.sub(rf"用\s*{handle}\s*(?:的)?(?:画风|风格)\s*(?:画|绘制)?", "", result)
            elif entity.entity_type == "lora":
                result = re.sub(rf"(?:使用|采用|加载)?\s*{handle}\s*(?:LoRA)?\s*(?:绘制|画)?", "", result, flags=re.I)
        result = re.sub(r"^(?:画|绘制)\s*", "", result.strip(" ,，。"))
        return result or "人物"

    def switch_model(self, job: PromptJob, model_profile_id: str) -> PromptJob:
        job.model_profile_id = model_profile_id
        self.compiler.apply_model_defaults(job, reset_user_selected_fields=MODEL_DEPENDENT_FIELDS)
        self.composition_recommender.apply_aspect_dimensions(job)
        return self._compile_preserving_authored_prompt(job)

    def apply_generation_preset(self, job: PromptJob, preset_id: str) -> PromptJob:
        self.compiler.apply_generation_preset(job, preset_id)
        self.composition_recommender.apply_aspect_dimensions(job)
        return self._compile_preserving_authored_prompt(job)

    def apply_composition_preset(self, job: PromptJob, preset_id: str) -> PromptJob:
        preset = self.configs.get_composition_preset(preset_id)
        for field, value in preset.values.items():
            decision = job.composition.decision(field)
            if decision.state == CompositionFieldState.LOCKED:
                continue
            setattr(job.composition, field, value)
            decision.state = CompositionFieldState.USER_SELECTED
            decision.reason = f"构图预设：{preset.display_name}"
            decision.source_rule_ids = [f"preset_{preset.id}"]
            decision.score = 1000
        job.composition.mode = "mixed"
        self.composition_recommender.apply_aspect_dimensions(job)
        return self._compile_preserving_authored_prompt(job)

    def compile_current_state(self, job: PromptJob) -> PromptJob:
        """Compile UI-owned state without translation or semantic re-analysis."""
        return self._compile_preserving_authored_prompt(job)

    def _compile_preserving_authored_prompt(self, job: PromptJob) -> PromptJob:
        preserve = job.compiled_prompt_state in {ItemState.USER_EDITED, ItemState.LOCKED}
        positive, negative, origin = job.positive_prompt, job.negative_prompt, job.prompt_origin
        self.compiler.compile(job)
        if preserve:
            job.positive_prompt = positive
            job.negative_prompt = negative
            job.prompt_origin = origin
        return job
