from __future__ import annotations

import re

from anima_prompt_studio.domain.models import ItemState, PromptJob, SubjectMode


class CanonicalProseBuilder:
    """Produces the one natural-language block consumed by PromptCompiler."""

    _history_markers = ("原本", "本次改成", "这次改成", "后来又改成", "后来改成")

    @staticmethod
    def _pluralize(text: str, people_count: int) -> str:
        if people_count <= 1:
            return text
        text = re.sub(r"\bShe has\b", "They have", text)
        text = re.sub(r"\bShe\b", "They", text)
        text = re.sub(r"\bshe\b", "they", text)
        text = re.sub(r"\bher\b", "them", text)
        return text

    @staticmethod
    def _final_attribute_sentence(job: PromptJob) -> str:
        attrs = job.semantic_frame.final_attributes
        hair_colour = attrs.get("hair_color")
        hair_length = attrs.get("hair_length")
        eye_colour = attrs.get("eye_color")
        pieces = []
        if hair_colour and hair_length:
            pieces.append(f"{hair_length} {hair_colour} hair")
        elif hair_colour:
            pieces.append(f"{hair_colour} hair")
        elif hair_length:
            pieces.append(f"{hair_length} hair")
        if eye_colour:
            pieces.append(f"{eye_colour} eyes")
        if not pieces:
            return ""
        subject = "The character" if "角色" in (job.normalized_zh or job.original_zh) else "The girl"
        return subject + " has " + " and ".join(pieces) + "."

    @staticmethod
    def _clean(text: str) -> str:
        text = text.replace("♪", "").replace("♫", "").replace("�", "")
        text = re.sub(r"\bshort\s+([a-z]+)-haired\b", r"short \1 hair", text, flags=re.I)
        text = re.sub(r"\blong\s+([a-z]+)-haired\b", r"long \1 hair", text, flags=re.I)
        text = re.sub(r"\bin the moon(?:light)?\b", "under the moonlight", text, flags=re.I)
        text = re.sub(r"\s+,", ",", text)
        text = re.sub(r"\s+([.!?])", r"\1", text)
        text = re.sub(r",\s*,+", ",", text)
        text = re.sub(r"\s{2,}", " ", text)
        text = re.sub(r",\s*([.!?])", r"\1", text)
        text = re.sub(r"\b(?:with|and)\s*([.!?])", r"\1", text, flags=re.I)
        return text.strip(" ,")

    @staticmethod
    def _sentences(parts: list[str]) -> str:
        seen: set[str] = set()
        result: list[str] = []
        for part in parts:
            for sentence in re.split(r"(?<=[.!?])\s+", part.strip()):
                clean = sentence.strip().rstrip(".")
                key = re.sub(r"\s+", " ", clean).casefold()
                if re.fullmatch(r"(?:the girl|the character|a girl)", key):
                    continue
                if clean and key not in seen:
                    seen.add(key)
                    result.append(clean + ".")
        return " ".join(result)

    def build(self, job: PromptJob) -> str:
        source = job.normalized_zh or job.original_zh
        auto = job.translation_state == ItemState.AUTO
        raw = job.translated_en.strip()
        skip_enhancements: set[str] = set()
        if auto and re.fullmatch(r"(?:A girl|Girls?)\.?", raw, flags=re.I):
            raw = ""

        if auto:
            for item in job.enhancements:
                if not item.enabled:
                    continue
                for pattern in item.suppress_patterns:
                    replacement = "sitting" if pattern.startswith("sitting") else ""
                    raw = re.sub(pattern, replacement, raw, flags=re.I)

            if any(marker in source for marker in self._history_markers):
                attribute_sentence = self._final_attribute_sentence(job)
                if attribute_sentence:
                    raw = attribute_sentence
            elif "不在室外" in source and "室内" in source:
                raw = "A girl is indoors rather than outside."
            elif "场景不是白天" in source and "夜晚" in source:
                raw = "A moonlit night scene."
            elif any(x in source for x in ("倚着窗户看向远方", "倚在窗边看向远方", "靠在窗边看向远方")):
                raw = ""
            elif any(x in source for x in ("手指穿过发丝", "手指穿过头发")):
                raw = ""
            elif "回头看向镜头" in source:
                raw = "She looks back over her shoulder toward the camera."

            if any(item.enabled and item.id == "hug_knees" for item in job.enhancements):
                raw = re.sub(
                    r"\bsits? on (?:her )?knees\b",
                    "sits with her knees drawn close, both arms wrapped around her knees",
                    raw, flags=re.I,
                )

            if any(item.enabled and item.replaces_translation for item in job.enhancements):
                raw = ""

            enabled_ids = {item.id for item in job.enhancements if item.enabled}
            if {"table_dangling", "sitting_table_edge"}.issubset(enabled_ids):
                raw = "She sits on the edge of the table with both legs dangling freely, her feet off the ground."
                skip_enhancements.update({"table_dangling", "sitting_table_edge"})
            elif "hair_tuck" in enabled_ids and any(x in source for x in ("把头发拨到耳后", "拨到耳后", "将发丝别到耳后", "别到耳后")):
                if "右手" in source:
                    raw = "She gently tucks a strand of hair behind her ear with her right hand."
                    skip_enhancements.add("hair_tuck")
                elif "左手" in source:
                    raw = "She gently tucks a strand of hair behind her ear with her left hand."
                    skip_enhancements.add("hair_tuck")
                else:
                    raw = ""
            if job.composition.people_count == 1:
                def singular_standing(match: re.Match) -> str:
                    adjective = match.group(1)
                    article = "An" if adjective[:1].casefold() in "aeiou" else "A"
                    return f"{article} {adjective.casefold()} girl stands"
                raw = re.sub(r"\b([A-Z][a-z]+) girls standing\b", singular_standing, raw)

        parts = [self._clean(raw)] if raw else []
        for item in job.enhancements:
            if not item.enabled or not item.content.strip():
                continue
            if item.id in skip_enhancements:
                continue
            if auto and item.id == "looking_back" and "回头看向镜头" in source:
                continue
            if auto and item.canonical_phrases and any(x.casefold() in raw.casefold() for x in item.canonical_phrases):
                continue
            content = self._pluralize(item.content, job.composition.people_count)
            parts.append(self._clean(content))

        prose = self._sentences(parts)
        if job.effective_subject_mode() == SubjectMode.SCENE:
            prose = re.sub(r"\b(?:She|Her|The girl|A girl)\b[^.]*\.\s*", "", prose).strip()
        job.canonical_prose = prose
        job.canonical_prose_ready = True
        return prose
