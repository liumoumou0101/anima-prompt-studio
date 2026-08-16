from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from anima_prompt_studio.domain.models import MatchedTag, SemanticFrame


@dataclass(frozen=True)
class VisualReplacement:
    placeholder: str
    source: str
    canonical_en: str
    slot: str


class VisualSemanticNormalizer:
    """Resolve compositional visual concepts before statistical translation.

    ANIMA's tag catalog is the vocabulary source.  This class adds a small
    grammar over that vocabulary (colour + body part, modifier + race, gaze
    verb + target) and exposes one semantic frame to all downstream stages.
    """

    _CONFIG_ROOT = Path(__file__).resolve().parent.parent / "configs"
    _SINGLE_VALUE_CATEGORIES = {"hair", "eyes", "gaze", "race"}

    def __init__(self, config_dir: Path | None = None) -> None:
        root = config_dir or self._CONFIG_ROOT
        self.tags: list[dict] = json.loads((root / "tags.json").read_text(encoding="utf-8"))
        self.concepts: list[dict] = json.loads((root / "concept_mappings.json").read_text(encoding="utf-8"))
        self.rules: dict = json.loads((root / "visual_semantics.json").read_text(encoding="utf-8"))
        self.tag_categories = {item["tag"]: item.get("category", "general") for item in self.tags}
        self._direct_attribute_aliases = {
            category: {
                alias
                for item in self.tags if item.get("category") == category
                for alias in item.get("zh", [])
            }
            for category in ("hair", "eyes")
        }
        self._attribute_aliases = self._build_attribute_aliases()
        self._race_aliases = self._build_race_aliases()

    def enrich(self, frame: SemanticFrame, chinese: str) -> SemanticFrame:
        frame.visual_slots = {}
        frame.visual_tags = []
        frame.visual_spans = {}

        occupied: list[tuple[int, int]] = []
        for slot in ("hair", "eyes"):
            match = self._longest_alias(chinese, self._attribute_aliases[slot], occupied)
            if not match:
                continue
            start, end, source, canonical, tags = match
            self._store(frame, slot, source, canonical, tags)
            frame.final_attributes[slot] = canonical
            occupied.append((start, end))

        race = self._longest_race(chinese, occupied)
        if race:
            start, end, source, canonical, tags = race
            self._store(frame, "race", source, canonical, tags)
            occupied.append((start, end))

        emotion = self._match_emotion(chinese, occupied)
        if emotion:
            start, end, source, canonical, tags = emotion
            self._store(frame, "emotion", source, canonical, tags)
            occupied.append((start, end))

        gaze = self._match_gaze(chinese, occupied)
        if gaze:
            start, end, source, canonical, tags, intent = gaze
            self._store(frame, "gaze", source, canonical, tags)
            frame.gaze_intent = intent
            occupied.append((start, end))

        limb_relation = self._match_limb_relation(chinese, occupied)
        if limb_relation:
            start, end, source, canonical, tags = limb_relation
            self._store(frame, "limb_relation", source, canonical, tags)
            occupied.append((start, end))

        frame.visual_tags = list(dict.fromkeys(frame.visual_tags))
        return frame

    def protect(self, text: str, frame: SemanticFrame) -> tuple[str, list[VisualReplacement]]:
        replacements: list[VisualReplacement] = []
        protected = text
        candidates = [
            (slot, source, frame.visual_slots.get(slot, ""))
            for slot, source in frame.visual_spans.items()
            if source and frame.visual_slots.get(slot)
            and self._needs_translation_protection(slot, source)
        ]
        for slot, source, canonical in sorted(candidates, key=lambda item: len(item[1]), reverse=True):
            if source not in protected:
                continue
            # ZSQ9xxxQSZ was selected by a real local Marian round-trip.  The
            # V/Q shape used initially was split or gained zeroes; this form is
            # preserved even when several placeholders occur in one sentence.
            placeholder = f"ZSQ{9000 + len(replacements) + 1:04d}QSZ"
            protected = protected.replace(source, f" {placeholder} ", 1)
            protected = re.sub(r"[ \t]+", " ", protected).strip()
            replacements.append(VisualReplacement(placeholder, source, canonical, slot))
        return protected, replacements

    @staticmethod
    def restore(text: str, replacements: list[VisualReplacement]) -> str:
        result = text
        for item in replacements:
            result = re.sub(re.escape(item.placeholder), item.canonical_en, result, flags=re.I)
            digits = "".join(re.findall(r"\d", item.placeholder))
            if digits:
                numeric_id = str(int(digits))
                result = re.sub(
                    rf"ZSQ\s*0*{re.escape(numeric_id)}\s*Q?\s*S?\s*Z?",
                    item.canonical_en,
                    result,
                    flags=re.I,
                )
        return VisualSemanticNormalizer._clean_english(result)

    def ensure_translation(self, english: str, frame: SemanticFrame) -> str:
        """Restore any concept whose placeholder was unexpectedly dropped by MT."""
        text = self._clean_english(english)
        missing = {
            slot: value for slot, value in frame.visual_slots.items()
            if value and not self._canonical_present(value, text)
        }
        additions: list[str] = []
        attributes = [missing.pop(slot) for slot in ("hair", "eyes") if slot in missing]
        if attributes:
            additions.append(f"The character has {' and '.join(attributes)}.")
        if race := missing.pop("race", ""):
            article = "an" if race[:1].lower() in "aeiou" else "a"
            additions.append(f"The character is {article} {race}.")
        if emotion := missing.pop("emotion", ""):
            article = "an" if emotion[:1].lower() in "aeiou" else "a"
            additions.append(f"The character has {article} {emotion}.")
        if gaze := missing.pop("gaze", ""):
            additions.append(f"The character is {gaze}.")
        if relation := missing.pop("limb_relation", ""):
            additions.append(relation.rstrip(". ") + ".")
        if additions:
            text = f"{text.rstrip(' .')}. {' '.join(additions)}" if text else " ".join(additions)
        return self._clean_english(text)

    def as_tags(self, frame: SemanticFrame) -> list[MatchedTag]:
        items: list[MatchedTag] = []
        for tag in frame.visual_tags:
            category = self.tag_categories.get(tag, self._infer_category(tag, frame))
            source = frame.visual_spans.get(category, "")
            if category == "expression":
                source = frame.visual_spans.get("emotion", source)
            items.append(MatchedTag(
                tag=tag,
                category=category,
                source_type="derived",
                source_text=source,
                confidence=1.0,
            ))
        return items

    def merge_tags(self, current: list[MatchedTag], frame: SemanticFrame,
                   excluded: set[str], locked: set[str]) -> list[MatchedTag]:
        semantic = [item for item in self.as_tags(frame) if item.tag not in excluded]
        locked_categories = {
            item.category for item in current
            if item.tag in locked and item.category in self._SINGLE_VALUE_CATEGORIES
        }
        semantic = [
            item for item in semantic
            if item.category not in locked_categories or item.tag in locked
        ]
        authoritative_categories = {
            item.category for item in semantic if item.category in self._SINGLE_VALUE_CATEGORIES
        }
        semantic_names = {item.tag for item in semantic}
        merged = [
            item for item in current
            if item.tag not in semantic_names
            and not (item.category in authoritative_categories and item.tag not in locked)
        ]
        merged.extend(semantic)
        return merged

    def _build_attribute_aliases(self) -> dict[str, dict[str, tuple[str, list[str]]]]:
        result: dict[str, dict[str, tuple[str, list[str]]]] = {"hair": {}, "eyes": {}}
        for item in self.tags:
            category = item.get("category")
            tag = item.get("tag", "")
            if category not in result or not self._is_colour_attribute(category, tag):
                continue
            aliases = set(item.get("zh", []))
            stems: set[str] = set()
            endings = r"(?:色)?(?:头发|发)$" if category == "hair" else r"(?:色)?(?:眼睛|眼|瞳孔|瞳)$"
            for alias in aliases:
                stem = re.sub(endings, "", alias)
                if stem and not any(word in stem for word in ("闭", "异", "竖", "特殊", "闪亮", "发光")):
                    stems.add(stem)
            for stem in stems:
                if category == "hair":
                    aliases.update({f"{stem}发", f"{stem}色发", f"{stem}头发", f"{stem}色头发"})
                else:
                    aliases.update({
                        f"{stem}眼", f"{stem}眼睛", f"{stem}瞳", f"{stem}瞳孔",
                        f"{stem}色眼", f"{stem}色眼睛", f"{stem}色瞳", f"{stem}色瞳孔",
                    })
            for alias in aliases:
                result[category][alias] = (tag, [tag])
        return result

    def _needs_translation_protection(self, slot: str, source: str) -> bool:
        if slot in self._direct_attribute_aliases:
            return source not in self._direct_attribute_aliases[slot]
        if slot == "race":
            return source.startswith("半")
        # Relation grammar and expanded emotion families are deliberately
        # canonicalized because free-form MT commonly turns them into moods or
        # reverses their target.
        return slot in {"emotion", "gaze", "limb_relation"}

    @staticmethod
    def _canonical_present(canonical: str, text: str) -> bool:
        haystack = text.lower()
        value = canonical.lower()
        if value in haystack:
            return True
        variants = {value}
        if value.endswith(" hair"):
            colour = value.removesuffix(" hair")
            variants.update({f"{colour}-haired", f"{colour} haired"})
        elif value.endswith(" eyes"):
            colour = value.removesuffix(" eyes")
            variants.update({f"{colour}-eyed", f"{colour} eyed"})
        return any(variant in haystack for variant in variants)

    def _build_race_aliases(self) -> dict[str, tuple[str, list[str]]]:
        result: dict[str, tuple[str, list[str]]] = {}
        for item in self.tags:
            if item.get("category") != "race":
                continue
            for alias in item.get("zh", []):
                result[alias] = (item["tag"], [item["tag"]])
        for concept in self.concepts:
            if concept.get("category") != "race":
                continue
            canonical = concept.get("canonical_en", "")
            tags = concept.get("tags", [])
            for alias in concept.get("triggers", []):
                result[alias] = (canonical, tags)
        return result

    @staticmethod
    def _is_colour_attribute(category: str, tag: str) -> bool:
        suffix = " hair" if category == "hair" else " eyes"
        excluded = ("closed eyes", "glowing eyes", "shiny eyes")
        return tag.endswith(suffix) and tag not in excluded

    @staticmethod
    def _longest_alias(text: str, aliases: dict[str, tuple[str, list[str]]],
                       occupied: list[tuple[int, int]]):
        matches = []
        for alias, (canonical, tags) in aliases.items():
            for match in re.finditer(re.escape(alias), text):
                if not VisualSemanticNormalizer._overlaps(match.start(), match.end(), occupied):
                    matches.append((match.start(), match.end(), alias, canonical, tags))
        return max(matches, key=lambda item: (len(item[2]), -item[0]), default=None)

    def _longest_race(self, text: str, occupied: list[tuple[int, int]]):
        matches = []
        for alias, (canonical, tags) in self._race_aliases.items():
            pattern = rf"半?{re.escape(alias)}"
            for match in re.finditer(pattern, text):
                if self._overlaps(match.start(), match.end(), occupied):
                    continue
                source = match.group(0)
                natural = canonical
                if source.startswith("半"):
                    base = re.sub(r"\s+girl$", "", canonical, flags=re.I)
                    natural = f"half-{base}"
                matches.append((match.start(), match.end(), source, natural, tags))
        return max(matches, key=lambda item: (len(item[2]), -item[0]), default=None)

    def _match_emotion(self, text: str, occupied: list[tuple[int, int]]):
        matches = []
        for family in self.rules.get("emotions", []):
            canonical = re.sub(r"^(?:an?|the)\s+", "", family["canonical_en"], flags=re.I)
            for alias in family.get("aliases", []):
                pattern = rf"(?:(?:神色|神情|表情|眼神)(?:显得|看起来|有些|略显|十分|很)?)?{re.escape(alias)}"
                for match in re.finditer(pattern, text):
                    if not self._overlaps(match.start(), match.end(), occupied):
                        matches.append((match.start(), match.end(), match.group(0), canonical, [family["tag"]]))
        return max(matches, key=lambda item: (len(item[2]), -item[0]), default=None)

    def _match_gaze(self, text: str, occupied: list[tuple[int, int]]):
        verbs = sorted(self.rules.get("gaze", {}).get("verbs", []), key=len, reverse=True)
        if not verbs:
            return None
        verb_pattern = "|".join(map(re.escape, verbs))
        matches = []
        for target in self.rules.get("gaze", {}).get("targets", []):
            for alias in target.get("aliases", []):
                pattern = rf"(?:{verb_pattern})\s*(?:着|向)?\s*{re.escape(alias)}"
                for match in re.finditer(pattern, text):
                    if not self._overlaps(match.start(), match.end(), occupied):
                        matches.append((
                            match.start(), match.end(), match.group(0), target["canonical_en"],
                            [target["tag"]], target["intent"],
                        ))
        return max(matches, key=lambda item: (len(item[2]), -item[0]), default=None)

    @staticmethod
    def _sentence_span(text: str, start: int) -> tuple[int, int, str]:
        end_match = re.search(r"[。.;；！？!?]", text[start:])
        end = start + end_match.start() if end_match else len(text)
        return start, end, text[start:end].strip(" ，,")

    def _match_limb_relation(self, text: str, occupied: list[tuple[int, int]]):
        relation = re.search(
            r"([左右])(?:腿|脚|脚踝|小腿).{0,12}?(?:抬起|抬高|搭在|放在|跨在|架在).{0,10}?([左右])膝(?:盖)?上",
            text,
        )
        if not relation or relation.group(1) == relation.group(2):
            return None
        start, end, source = self._sentence_span(text, relation.start())
        if self._overlaps(start, end, occupied):
            return None

        side_names = {"左": "left", "右": "right"}
        raised = side_names[relation.group(1)]
        support = side_names[relation.group(2)]
        possessive = "her" if any(token in text for token in ("女孩", "女人", "女性", "少女", "她")) else (
            "his" if any(token in text for token in ("男孩", "男人", "男性", "少年", "他")) else "their"
        )
        canonical = f"The character sits with {possessive} {raised} ankle resting across {possessive} {support} knee in a figure-four pose"
        tags = ["crossed legs"]

        grounded = re.search(r"([左右])脚.{0,8}?(?:踩地|着地|踩在地上|踏在地面|放在地上)", source)
        if grounded:
            ground_side = side_names[grounded.group(1)]
            canonical += f", while the {ground_side} foot stays planted on the floor"
        if re.search(rf"{relation.group(1)}脚(?:的)?脚尖.{{0,5}}?(?:向下|朝下)", source):
            canonical += f" and the {raised} toes point downward"
        canonical += "."
        if any(token in source for token in ("手扶着抬起的膝", "手放在抬起的膝", "手搭在抬起的膝")):
            canonical += f" One hand rests on the raised {raised} knee."
        if any(token in source for token in ("后仰", "向后倾", "往后靠")):
            canonical += " The torso is slightly arched back."
            tags.append("arched back")
        if any(token in source for token in ("全身", "完整身体", "从头到脚")):
            canonical += " The complete head and face and the full figure from head to toe are visible, with clear space above the head and below the feet."
            tags.append("full body")
        if any(token in source for token in ("侧前方", "斜前方", "三分之四")):
            canonical += " The character is shown from a front three-quarter view."
            tags.append("three-quarter view")
        return start, end, source, canonical, tags

    @staticmethod
    def _store(frame: SemanticFrame, slot: str, source: str, canonical: str, tags: list[str]) -> None:
        frame.visual_slots[slot] = canonical
        frame.visual_spans[slot] = source
        frame.visual_tags.extend(tags)

    @staticmethod
    def _overlaps(start: int, end: int, occupied: list[tuple[int, int]]) -> bool:
        return any(start < other_end and end > other_start for other_start, other_end in occupied)

    @staticmethod
    def _infer_category(tag: str, frame: SemanticFrame) -> str:
        if tag in {"looking away", "looking at viewer"}:
            return "gaze"
        if tag in {"sad", "happy", "angry", "surprised", "confused", "sleepy", "nervous", "serious"}:
            return "expression"
        if tag in frame.visual_tags and "race" in frame.visual_slots:
            return "race"
        if tag in {"upper body", "full body"}:
            return "pose"
        if tag in {"three-quarter view"}:
            return "angle"
        if tag in {"crossed legs", "stuck", "through wall"}:
            return "pose"
        return "general"

    @staticmethod
    def _clean_english(text: str) -> str:
        text = re.sub(
            r"\b(?:is|was|are|were)\s+(?:trying|attempting)\s+(?=The character\b)",
            ". ", text, flags=re.I,
        )
        text = re.sub(r",\s*(?=The character\b)", ". ", text)
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\s+([,.;!?])", r"\1", text)
        text = re.sub(r"([,.;!?])(?:\s*[,.;!?])+", r"\1", text)
        text = re.sub(r"\b(a|an)\s+(a|an)\s+", r"\2 ", text, flags=re.I)
        return text.strip(" ,")
