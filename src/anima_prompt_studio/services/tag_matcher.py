from __future__ import annotations

import json
import re
from pathlib import Path

from anima_prompt_studio.domain.models import CompositionContext, ItemState, MatchedTag
from anima_prompt_studio.repositories import TagDatabase
from .resource_manager import ResourceManager


class TagMatcher:
    def __init__(self, tags_path: Path | None = None, database_path: Path | None = None) -> None:
        path = tags_path or Path(__file__).resolve().parent.parent / "configs" / "tags.json"
        self.entries: list[dict] = json.loads(path.read_text(encoding="utf-8"))
        self.database = TagDatabase(database_path or ResourceManager().tag_db_path)

    @staticmethod
    def _contains(text: str, phrase: str) -> bool:
        if re.search(r"[\u4e00-\u9fff]", phrase):
            return phrase in text
        return re.search(rf"(?<!\w){re.escape(phrase.lower())}(?!\w)", text.lower()) is not None

    @staticmethod
    def _contains_words(text: str, phrase: str) -> bool:
        """Match nearby compositional phrases such as 'short black hair' -> 'short hair'.

        Words must appear in order within a small window so unrelated tokens
        (e.g. 'short crop top' + 'pink hair') do not falsely yield 'short hair'.
        """
        phrase_words = re.findall(r"[a-z0-9]+", phrase.lower())
        if not phrase_words:
            return False
        text_words = [
            "hair" if word == "haired" else word
            for word in re.findall(r"[a-z0-9]+", text.lower())
        ]
        if len(phrase_words) == 1:
            return phrase_words[0] in text_words
        # Exact adjacent multi-word span.
        n = len(phrase_words)
        for index in range(len(text_words) - n + 1):
            if text_words[index:index + n] == phrase_words:
                return True
        # Allow up to three intervening modifiers for two-word tags
        # ("short, slightly messy black hair").  Noun barriers prevent the
        # former false positive where "short crop top" plus "pink hair"
        # accidentally became "short hair".
        if n == 2:
            first, second = phrase_words
            noun_barriers = {
                "top", "skirt", "dress", "shorts", "shirt", "blouse", "sweater",
                "jacket", "coat", "pants", "trousers", "stockings", "boots", "shoes",
                "girl", "woman", "boy", "man", "person", "character",
            }
            for index, token in enumerate(text_words):
                if token != first:
                    continue
                end = min(len(text_words), index + 5)
                for target_index in range(index + 1, end):
                    if text_words[target_index] != second:
                        continue
                    between = text_words[index + 1:target_index]
                    if not noun_barriers.intersection(between):
                        return True
        return False

    @staticmethod
    def _negated_english(text: str, phrase: str) -> bool:
        words = re.findall(r"[a-z0-9]+", phrase.lower())
        if not words:
            return False
        target = words[-1]
        for match in re.finditer(rf"\b{re.escape(target)}\b", text.lower()):
            prefix = text.lower()[max(0, match.start() - 45):match.start()]
            if re.search(r"(?:\bwithout\b|\bno\b|\bnot\b|n't\b|\bnever\b|\binstead of\b)[^.!?,;]{0,35}$", prefix):
                return True
        return False

    @staticmethod
    def _negated_chinese(text: str, phrase: str) -> bool:
        start = text.find(phrase)
        while start >= 0:
            prefix = text[max(0, start - 7):start]
            if re.search(r"(?:不|没有|没|未|无|并非|不是)[^，。；！？]{0,5}$", prefix):
                return True
            start = text.find(phrase, start + 1)
        return False

    @classmethod
    def _context_allowed(
        cls,
        tag: str,
        english: str,
        chinese: str,
        context: CompositionContext | None,
        *,
        source_is_external: bool,
        name: str | None = None,
    ) -> bool:
        """Shared false-positive guards for builtin and external tags."""
        lower = english.lower()
        name = (name or tag).replace("_", " ")
        if tag == "camera":
            chinese_gaze = any(x in chinese for x in ("看镜头", "看向镜头", "俯视镜头", "低头看镜头"))
            english_gaze = bool(re.search(r"\b(?:looks?|looking)\s+(?:at|toward|towards)\s+(?:the )?camera\b", lower))
            explicit_object = any(x in chinese for x in ("相机", "摄像机", "手持相机", "拿着相机", "单反")) or bool(
                re.search(r"\b(?:holding|holds|carrying|carries|using|uses)\s+(?:a |the )?camera\b", lower)
            )
            if (chinese_gaze or english_gaze) and not explicit_object:
                return False
        if tag in {"painting (object)", "painting (action)", "painting"} and (
            "画外" in chinese or re.search(r"\blooking (?:away|outside)\b", lower)
        ) and not any(x in chinese for x in ("油画", "绘画", "作画", "画作", "在画画", "画笔")):
            return False
        if not source_is_external:
            return True
        # Remaining checks are external-DB specific.
        return cls._external_allowed_body(name, tag, english, chinese, context, lower)

    @staticmethod
    def _external_allowed(entry: dict, english: str, chinese: str, context: CompositionContext | None) -> bool:
        name, tag = entry["name"].replace("_", " "), entry["output_name"]
        lower = english.lower()
        if not TagMatcher._context_allowed(tag, english, chinese, context, source_is_external=True, name=name):
            return False
        return True

    @staticmethod
    def _external_allowed_body(
        name: str, tag: str, english: str, chinese: str, context: CompositionContext | None, lower: str,
    ) -> bool:
        # Function words and common MT debris that exist as rare Danbooru tags.
        if tag in {
            "no", "feet", "cast", "can", "folding", "will", "may", "must", "should",
            "could", "would", "has", "have", "had", "does", "did", "been", "being",
            "cuts", "outline", "through clothes", "and", "or", "with", "for", "from",
            "into", "over", "under", "about", "after", "before", "between", "during",
            "while", "where", "when", "what", "who", "which", "that", "this", "these",
            "those", "there", "here", "then", "than", "too", "very", "just", "also",
            "only", "even", "still", "already", "again", "once", "more", "most",
            "some", "any", "all", "each", "every", "other", "another", "such",
            "own", "same", "different", "new", "old", "good", "bad", "great",
            "little", "few", "many", "much", "lot", "bit", "kind", "type", "sort",
            "thing", "things", "stuff", "way", "time", "times", "day", "days",
            "get", "got", "gets", "getting", "make", "makes", "made", "making",
            "take", "takes", "took", "taking", "come", "comes", "came", "coming",
            "go", "goes", "went", "going", "see", "sees", "saw", "seeing",
            "look", "looks", "looking",  # bare verb without "at viewer" etc. is noise
            "use", "uses", "used", "using", "try", "tries", "tried", "trying",
            "let", "lets", "put", "puts", "keep", "keeps", "kept", "keeping",
            "seem", "seems", "seemed", "become", "becomes", "became",
            "start", "starts", "started", "begin", "begins", "began",
            "end", "ends", "ended", "stop", "stops", "stopped",
            "show", "shows", "showed", "shown", "showing",
            "give", "gives", "gave", "given", "giving",
            "find", "finds", "found", "finding",
            "want", "wants", "wanted", "need", "needs", "needed",
            "like", "likes", "liked", "love", "loves", "loved",
            "know", "knows", "knew", "known", "think", "thinks", "thought",
            "feel", "feels", "felt", "feeling",
            "able", "unable", "possible", "impossible",
            "yes", "yeah", "ok", "okay", "oh", "ah", "um", "uh",
            "re", "ve", "ll", "don", "doesn", "didn", "isn", "aren", "wasn", "weren",
            "won", "wouldn", "couldn", "shouldn", "haven", "hasn", "hadn",
            "in", "on", "at", "to", "of", "by", "as", "if", "so", "up", "out", "off",
            "down", "away", "back",  # bare "back" handled separately; keep list explicit
            "front", "side", "top", "bottom", "left", "right", "middle", "center",
            "high", "low", "big", "small", "large", "tiny", "huge",
            "open", "close", "closed", "empty", "full",
            "one", "two", "three", "four", "five", "first", "second", "third",
            "girl", "boy", "man", "woman", "person", "people", "character",
            "she", "he", "her", "his", "him", "they", "them", "their", "it", "its",
            "i", "me", "my", "we", "us", "our", "you", "your",
        }:
            return False
        # Single-character / ultra-short debris that occasionally exists as tags.
        if len(tag.replace(" ", "")) <= 2 and tag not in {"1girl", "1boy", "2girls", "3girls", "2boys", "3boys", "abs", "ai"}:
            if not re.search(r"\d", tag):
                return False
        # "low-cut dress" should not yield the standalone "cut"/"cuts" tag.
        if tag in {"cut", "cuts"} and re.search(r"\blow-?cut\b", lower):
            return False
        # "under covers" is often a false positive from "on bed" sex/bedroom scenes.
        if tag == "under covers" and not re.search(r"\bunder (?:the )?covers\b", lower) and "被子" not in chinese and "被窝" not in chinese:
            return False
        # Couple sex scenes are not "male focus" unless explicitly requested.
        if tag == "male focus" and re.search(r"\b(?:sex|couple|hetero|fellatio|missionary)\b", lower):
            return False
        if tag == "skinned" and not any(x in chinese for x in ("皮肤", "肤色", "红皮", "蓝皮", "黑皮")):
            return False
        if tag == "sitting on person" and not re.search(r"坐在.{0,5}(?:人|她|他)(?:的)?(?:身上|腿上|膝上|肩上)", chinese):
            return False
        if tag == "photo (object)" and ((context and context.composition_meta_spans) or "画外" in chinese) and not any(x in chinese for x in ("照片", "相片", "相纸")):
            return False
        if tag == "male focus" and any(x in chinese for x in ("女孩", "少女", "女")) and not any(
            x in chinese for x in ("男性为主", "男主视角", "以男性为主")
        ):
            return False
        if name == "side" and re.search(r"\b(?:left|right) side of (?:the )?(?:picture|image|frame)\b", lower):
            return False
        if name == "back" and ((context and context.motion_relation_spans) or re.search(r"\bbehind (?:her|his|their)(?: own)? back\b", lower)):
            return False
        if tag == "giant" and any(x in chinese for x in ("巨大翅膀", "巨大的白色羽翼", "巨大建筑")) and not any(x in chinese for x in ("巨人", "女巨人")):
            return False
        if tag == "suspension" and any(x in chinese for x in ("悬浮", "漂浮", "浮在空中")):
            return False
        if tag in {"front view", "from behind", "back view"} and re.search(r"(?:一个|一人).{0,8}前面.{0,15}(?:一个|一人).{0,8}后面", chinese) and not any(x in chinese for x in ("拍摄", "镜头", "视角", "正面", "背面", "背影")):
            return False
        return True

    def match(self, english: str, chinese: str = "", excluded: set[str] | None = None, locked: set[str] | None = None,
              context: CompositionContext | None = None) -> list[MatchedTag]:
        excluded, locked = excluded or set(), locked or set()
        result: list[MatchedTag] = []
        seen: set[str] = set()
        for entry in self.entries:
            tag = entry["tag"].replace("_", " ")
            if tag in excluded or tag in seen:
                continue
            exact = next((p for p in entry.get("en", []) if self._contains(english, p)), None)
            word_match = None if exact else next((p for p in entry.get("en", []) if self._contains_words(english, p)), None)
            zh_match = next((p for p in entry.get("zh", []) if self._contains(chinese, p)), None)
            if exact and self._negated_english(english, exact):
                exact = None
            if word_match and self._negated_english(english, word_match):
                word_match = None
            if zh_match and self._negated_chinese(chinese, zh_match):
                zh_match = None
            if exact or word_match or zh_match:
                # Builtin tags can still be context-false (e.g. "camera" from "looking at the camera").
                if not self._context_allowed(tag, english, chinese, context, source_is_external=False):
                    continue
                result.append(MatchedTag(
                    tag=tag, category=entry.get("category", "general"),
                    source_type="direct" if exact else "synonym", source_text=exact or word_match or zh_match or "",
                    confidence=1.0 if exact else (0.9 if word_match else 0.94),
                    state=ItemState.LOCKED if tag in locked else ItemState.AUTO,
                ))
                seen.add(tag)
        # Hair colour/length, eye colour and count are single-valued in V1. The
        # last explicit phrase wins, which mirrors normal Chinese corrections.
        single_value = {"count", "hair", "hair_length", "eyes"}
        for category in single_value:
            candidates = [x for x in result if x.category == category and x.state != ItemState.LOCKED]
            if len(candidates) > 1:
                def position(item: MatchedTag) -> int:
                    if item.source_text and self._contains(english, item.source_text):
                        en_pos = english.lower().rfind(item.source_text.lower())
                    else:
                        words = re.findall(r"[a-z0-9]+", item.source_text.lower())
                        en_pos = max((english.lower().rfind(word) for word in words), default=-1)
                    return max(en_pos, chinese.rfind(item.source_text))
                winner = max(candidates, key=lambda item: (item.confidence, len(item.source_text), position(item)))
                result = [x for x in result if x.category != category or x.state == ItemState.LOCKED or x is winner]
        for tag in sorted(locked - seen - excluded):
            result.append(MatchedTag(tag=tag, source_type="user_added", state=ItemState.LOCKED))
        category_names = {0: "general", 1: "artist", 3: "copyright", 4: "character", 5: "meta"}
        for entry in self.database.match_english(english):
            tag = entry["output_name"]
            if tag in seen or tag in excluded or entry["category"] in (1, 3, 4):
                continue
            if not self._external_allowed(entry, english, chinese, context):
                continue
            if self._negated_english(english, entry["name"].replace("_", " ")):
                continue
            words = set(tag.split())
            if any(words < set(existing.tag.split()) for existing in result):
                continue
            if (("eyes" in words and any(x.category == "eyes" for x in result)) or
                ("hair" in words and any(x.category in ("hair", "hair_length") for x in result))):
                continue
            result.append(MatchedTag(tag=tag, category=category_names.get(entry["category"], "general"),
                source_type="direct", source_text=entry["name"].replace("_", " "), confidence=.97))
            seen.add(tag)
        return result
