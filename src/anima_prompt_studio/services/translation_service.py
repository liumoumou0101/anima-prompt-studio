from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Protocol

from .negation import phrase_all_negated_zh, phrase_has_unnegated_zh


class TranslationEngine(Protocol):
    name: str
    def zh_to_en(self, text: str) -> str: ...
    def en_to_zh(self, text: str) -> str: ...


def marian_runtime_available() -> bool:
    """Return whether the optional local-model runtime is actually installed."""
    return all(importlib.util.find_spec(name) is not None for name in ("torch", "transformers", "sentencepiece"))


class LocalMarianEngine:
    """Loads user-supplied local Hugging Face/Marian directories; never downloads."""

    name = "本地 Marian"

    def __init__(self, zh_en_path: Path, en_zh_path: Path) -> None:
        if not zh_en_path.is_dir() or not en_zh_path.is_dir():
            raise FileNotFoundError("翻译模型未安装或路径无效。")
        try:
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError("使用 Marian 模型需要安装 translation 可选依赖。") from exc
        self._tokenizers = [AutoTokenizer.from_pretrained(str(p), local_files_only=True) for p in (zh_en_path, en_zh_path)]
        self._models = [AutoModelForSeq2SeqLM.from_pretrained(str(p), local_files_only=True) for p in (zh_en_path, en_zh_path)]

    def _run(self, text: str, index: int) -> str:
        tokenizer, model = self._tokenizers[index], self._models[index]
        batch = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
        output = model.generate(**batch, max_new_tokens=512, num_beams=4)
        return tokenizer.decode(output[0], skip_special_tokens=True)

    def zh_to_en(self, text: str) -> str:
        return self._run(text, 0)

    def en_to_zh(self, text: str) -> str:
        return self._run(text, 1)


class LazyLocalMarianEngine:
    """Defers the ~20 second model initialization until the first translation."""

    name = "本地 Marian（按需加载）"

    def __init__(self, zh_en_path: Path, en_zh_path: Path) -> None:
        if not (zh_en_path / "config.json").is_file() or not (en_zh_path / "config.json").is_file():
            raise FileNotFoundError("翻译模型未安装或路径无效。")
        self.zh_en_path = zh_en_path
        self.en_zh_path = en_zh_path
        self._engine: LocalMarianEngine | None = None

    def _get(self) -> LocalMarianEngine:
        if self._engine is None:
            self._engine = LocalMarianEngine(self.zh_en_path, self.en_zh_path)
        return self._engine

    def zh_to_en(self, text: str) -> str:
        return self._get().zh_to_en(text)

    def en_to_zh(self, text: str) -> str:
        return self._get().en_to_zh(text)


def _load_extra_lexicon() -> dict[str, str]:
    path = Path(__file__).resolve().parent.parent / "configs" / "builtin_lexicon_extra.json"
    if not path.is_file():
        return {}
    try:
        import json
        data = json.loads(path.read_text(encoding="utf-8"))
        return dict(data.get("zh_en") or {})
    except (OSError, ValueError, TypeError):
        return {}


class BuiltinOfflineEngine:
    """Deterministic offline fallback; core phrases + expanded lexicon config."""

    name = "内置离线基础翻译"
    _zh_en_core = {
        "一个女孩": "one girl", "一名女孩": "one girl", "一个": "one ", "一名": "one ", "女孩": "girl", "男孩": "boy",
        "两个女孩": "two girls", "三个女孩": "three girls", "白色头发": "white hair", "白发": "white hair",
        "黑色头发": "black hair", "黑发": "black hair", "金色头发": "blonde hair", "金发": "blonde hair",
        "非常长的头发": "very long hair", "超长发": "very long hair", "长发": "long hair", "短发": "short hair",
        "金色眼睛": "golden eyes", "金瞳": "golden eyes", "蓝色眼睛": "blue eyes", "蓝瞳": "blue eyes",
        "红色眼睛": "red eyes", "红瞳": "red eyes", "微笑": "smiling", "看着镜头": "looking at the camera",
        "看镜头": "looking at the camera", "不看镜头": "looking away from the camera", "室内": "indoors",
        "室外": "outdoors", "房间": "room", "旅店": "inn", "窗边": "by the window", "窗户": "window",
        "坐在桌子边缘": "sitting on the edge of the table", "坐在桌边": "sitting on the edge of the table",
        "双腿垂下": "both legs dangling", "脚不着地": "feet off the ground", "撩头发": "touching her hair",
        "把头发拨到耳后": "tucking a strand behind her ear", "低头看镜头": "looking down at the camera",
        "靠墙站立": "standing against the wall", "抱膝坐着": "sitting while hugging her knees", "回头看": "looking back",
        "探出窗外": "leaning out of the window", "靠在窗边": "leaning by the window", "清晨": "early morning",
        "雨夜": "rainy night", "雨天": "rainy day", "下雨": "raining", "黄昏": "sunset", "夕阳": "sunset",
        "夜晚": "night", "月光": "moonlight", "右手": "right hand", "左手": "left hand", "拿着": "holding",
        "穿着": "wearing", "裙子": "dress", "短裙": "miniskirt", "衬衫": "shirt", "外套": "coat",
        "全身": "full body", "半身": "upper body", "侧面": "side view", "背面": "back view",
        "在左边": "on the left", "在右边": "on the right", "在中间": "in the center", "和": " and ", "的": " ", "里": " ",
        "比基尼": "bikini", "黑色内衣": "black lingerie", "内衣": "lingerie", "内裤": "panties",
        "丁字裤": "thong", "吊带袜": "thighhighs", "长筒袜": "thighhighs", "过膝袜": "thighhighs",
        "黑丝": "black thighhighs", "丝袜": "stockings", "吊袜带": "garter belt",
        "乳沟": "cleavage", "低胸礼服": "low-cut dress", "低胸": "low-cut",
        "露脐短上衣": "crop top", "露脐装": "crop top", "露脐": "navel", "热裤": "short shorts",
        "湿透的白衬衫": "wet white shirt", "湿衬衫": "wet shirt", "湿透的衬衫": "wet shirt",
        "透过衣服能看到内衣轮廓": "see-through clothes showing lingerie outline",
        "裸体": "nude", "全裸": "nude", "赤裸上身": "topless", "一丝不挂": "completely nude",
        "乳头": "nipples", "胸部": "breasts", "臀部特写": "ass focus",
        "从背后拍摄": "from behind", "从背后": "from behind",
        "做爱": "having sex", "性交": "sex", "性爱": "sex", "男上位": "missionary position",
        "口交": "fellatio", "阿嘿颜": "ahegao", "啊嘿颜": "ahegao", "高潮中": "orgasm", "高潮": "orgasm",
        "舌头伸出": "tongue out", "眼睛上翻": "rolling eyes",
        "被绳子捆绑": "bound with rope", "捆绑": "bound", "绳缚": "bondage",
        "眼睛被布蒙住": "blindfolded", "蒙住眼睛": "blindfolded", "蒙眼": "blindfold",
        "一对男女": "a man and a woman", "一男一女": "a man and a woman", "一女一男": "a woman and a man",
        "看向画外": "looking away",
        "双腿交叠": "legs crossed", "跪着": "kneeling", "浴室": "bathroom", "沙滩": "beach",
        "床单": "bed sheet", "床上": "on bed", "宴会厅": "banquet hall",
    }
    _en_zh = {
        "one girl": "一个女孩", "two girls": "两个女孩", "three girls": "三个女孩", "white hair": "白发",
        "black hair": "黑发", "blonde hair": "金发", "very long hair": "非常长的头发", "long hair": "长发",
        "short hair": "短发", "golden eyes": "金色眼睛", "blue eyes": "蓝色眼睛", "red eyes": "红色眼睛",
        "looking at the camera": "看着镜头", "looking away from the camera": "不看镜头", "indoors": "室内",
        "outdoors": "室外", "sitting on the edge of the table": "坐在桌子边缘", "both legs dangling": "双腿垂下",
        "touching her hair": "撩头发", "tucking her hair": "把头发拨到耳后", "looking down at the camera": "低头看镜头", "standing against the wall": "靠墙站立",
        "looking back": "回头看", "early morning": "清晨", "rainy night": "雨夜", "sunset": "黄昏",
        "moonlight": "月光", "right hand": "右手", "left hand": "左手", "holding": "拿着", "wearing": "穿着",
        "full body": "全身", "upper body": "半身", "side view": "侧面", "back view": "背面",
        "bikini": "比基尼", "lingerie": "内衣", "panties": "内裤", "thong": "丁字裤",
        "thighhighs": "吊带袜", "garter belt": "吊袜带", "cleavage": "乳沟", "crop top": "露脐短上衣",
        "nude": "裸体", "topless": "赤裸上身", "nipples": "乳头", "breasts": "胸部",
        "having sex": "做爱", "sex": "性爱", "missionary position": "男上位", "fellatio": "口交",
        "ahegao": "阿嘿颜", "orgasm": "高潮", "bound with rope": "被绳子捆绑", "blindfold": "蒙眼",
        "looking away": "看向画外", "a man and a woman": "一对男女",
        "cowgirl position": "女上位", "doggy style": "后入", "large breasts": "巨乳", "school uniform": "校服",
        "maid outfit": "女仆装", "yuri": "百合", "twintails": "双马尾",
    }

    def __init__(self) -> None:
        # Extra lexicon overrides core on key collision so curated expansions win.
        self._zh_en = {**self._zh_en_core, **_load_extra_lexicon()}

    @staticmethod
    def _replace_longest(text: str, mapping: dict[str, str]) -> str:
        for source in sorted(mapping, key=len, reverse=True):
            replacement = mapping[source]
            # Chinese source phrases are often adjacent (女孩穿着比基尼).  Pad
            # Chinese -> Latin replacements before the next phrase is replaced,
            # otherwise the resulting English tokens collapse into
            # "girlwearingbikini" and can no longer be matched reliably.
            if re.search(r"[\u4e00-\u9fff]", source) and re.search(r"[A-Za-z0-9]", replacement):
                replacement = f" {replacement.strip()} "
            text = text.replace(source, replacement)
        text = re.sub(r"(?<=[\u4e00-\u9fff])(?=[A-Za-z0-9_@])", " ", text)
        text = re.sub(r"(?<=[A-Za-z0-9_])(?=[\u4e00-\u9fff])", " ", text)
        text = re.sub(r"\s+([,.;!?])", r"\1", text)
        return re.sub(r"[ \t]+", " ", text).strip(" ,")

    def zh_to_en(self, text: str) -> str:
        # Keep unknown CJK visible instead of silently deleting user intent.  A
        # configured Marian model can translate those spans; the builtin engine
        # cannot, so retaining them is safer and makes the gap editable.
        translated = self._replace_longest(text, self._zh_en)
        translated = translated.translate(str.maketrans({"，": ", ", "。": ". ", "；": "; ", "：": ": ", "！": "! ", "？": "? "}))
        translated = re.sub(r"\s+([,.;!?])", r"\1", translated)
        translated = re.sub(r"\s{2,}", " ", translated)
        return translated.strip(" ,.;")

    def en_to_zh(self, text: str) -> str:
        # Prefer reverse map from zh_en plus curated en_zh overrides.
        reverse = {v: k for k, v in self._zh_en.items() if v and not v.endswith(" ")}
        reverse.update(self._en_zh)
        return self._replace_longest(text, reverse)


class TranslationService:
    def __init__(self, engine: TranslationEngine | None = None) -> None:
        self.engine = engine or BuiltinOfflineEngine()

    @property
    def engine_name(self) -> str:
        return self.engine.name

    def zh_to_en(self, text: str) -> str:
        if not text.strip():
            return ""
        try:
            translated = self.engine.zh_to_en(text)
            translated = self._guard_visual_terms(text, translated)
            translated = self._guard_artist_intent(text, translated)
            return self._sanitize(translated)
        except Exception as exc:
            raise RuntimeError(f"{self.engine_name} 中译英失败：{exc}") from exc

    @staticmethod
    def _guard_visual_terms(source: str, translated: str) -> str:
        """Correct common high-impact OPUS drift without inventing attributes."""
        if "女孩" in source and not re.search(r"[两二三四五六七八九十\d][个名位].{0,8}女孩", source):
            translated = re.sub(r"^Girls\b", "A girl", translated, flags=re.I)
        if "男孩" in source and not re.search(r"[两二三四五六七八九十\d][个名位].{0,8}男孩", source):
            translated = re.sub(r"^Boys\b", "A boy", translated, flags=re.I)
        hair_colours = {
            "白发": "white", "白色头发": "white", "黑发": "black", "黑色头发": "black",
            "金发": "blonde", "金色头发": "blonde", "红发": "red", "红色头发": "red",
            "蓝发": "blue", "蓝色头发": "blue", "蓝色长发": "blue", "蓝色短发": "blue", "粉发": "pink", "粉色头发": "pink",
            "黑色长发": "black", "黑色短发": "black", "白色长发": "white", "白色短发": "white",
            "紫发": "purple", "紫色头发": "purple", "银发": "silver", "银色头发": "silver",
        }
        eye_colours = {
            "金瞳": "golden", "金色眼睛": "golden", "蓝瞳": "blue", "蓝色眼睛": "blue",
            "红瞳": "red", "红色眼睛": "red", "绿瞳": "green", "绿色眼睛": "green",
            "紫瞳": "purple", "紫色眼睛": "purple", "棕瞳": "brown", "棕色眼睛": "brown",
        }
        hair_candidates = [(source.rfind(key), value) for key, value in hair_colours.items() if key in source]
        expected_hair = max(hair_candidates)[1] if hair_candidates else None
        if expected_hair:
            pattern = r"\b(?:blonde|blond|white|black|red|blue|green|pink|purple|brown|silver|grey|gray)(?:-haired| hair)?\b"
            if re.search(pattern, translated, flags=re.I):
                translated = re.sub(pattern, f"{expected_hair}-haired", translated, count=1, flags=re.I)
            elif not re.search(rf"\b{re.escape(expected_hair)}\b", translated, flags=re.I):
                translated = translated.rstrip(". ") + f". The character has {expected_hair} hair."
            translated = re.sub(
                rf"({re.escape(expected_hair)}-haired\s+\w+)\s+with\s+{re.escape(expected_hair)}\s+hair",
                r"\1", translated, flags=re.I,
            )
            # Remove a second, hallucinated hair-colour adjective left beside
            # the noun (for example "white-haired blonde girl").
            other_colours = {"blonde", "blond", "white", "black", "red", "blue", "green", "pink", "purple", "brown", "silver", "grey", "gray"} - {expected_hair}
            if other_colours:
                translated = re.sub(
                    rf"(?<=\b{re.escape(expected_hair)}-haired\s)(?:{'|'.join(sorted(other_colours, key=len, reverse=True))})\s+(?=(?:girl|woman|boy|man|character)\b)",
                    "", translated, flags=re.I,
                )
        eye_candidates = [(source.rfind(key), value) for key, value in eye_colours.items() if key in source]
        expected_eyes = max(eye_candidates)[1] if eye_candidates else None
        if expected_eyes:
            eye_pattern = r"\b(?:golden|gold|blue|red|green|pink|purple|brown|silver|grey|gray) eyes?\b"
            if re.search(eye_pattern, translated, flags=re.I):
                translated = re.sub(eye_pattern, f"{expected_eyes} eyes", translated, count=1, flags=re.I)
            elif not re.search(rf"\b{re.escape(expected_eyes)} eyes?\b", translated, flags=re.I):
                translated = translated.rstrip(". ") + f". The character has {expected_eyes} eyes."
        # OPUS sometimes turns 瞳 (pupil/eyes) into a skin attribute. Skin
        # colour is only retained when the Chinese source explicitly mentions it.
        if expected_eyes and not any(token in source for token in ("皮肤", "肤色", "红皮", "蓝皮", "黑皮")):
            translated = re.sub(r"\b(?:red|blue|green|golden|purple)-skinned\s*", "", translated, flags=re.I)
            translated = re.sub(r",\s+(?=(?:girl|woman|boy|man|character)\b)", " ", translated, flags=re.I)
        if "脚不着地" in source:
            translated = re.sub(
                r"(?:,?\s*and\s+|,?\s*)(?:she\s+)?(?:doesn't|does not|didn't|did not) have (?:a |any )?(?:foot|feet)",
                ", with her feet off the ground", translated, flags=re.I,
            )
        translated = TranslationService._guard_spaghetti_strap_dress(source, translated)
        translated = TranslationService._guard_hand_scope(source, translated)
        translated = TranslationService._guard_nsfw_and_composition_terms(source, translated)
        return translated

    @staticmethod
    def _guard_spaghetti_strap_dress(source: str, translated: str) -> str:
        """Keep 吊带裙 as a strap dress instead of OPUS's hosiery ``garter``."""
        long_dress_terms = ("吊带长裙", "细肩带长裙", "细吊带长裙")
        dress_terms = ("吊带裙", "吊带连衣裙", "细肩带连衣裙", "细吊带连衣裙")
        is_long_dress = any(term in source for term in long_dress_terms)
        is_strap_dress = is_long_dress or any(term in source for term in dress_terms)
        if not is_strap_dress:
            return translated

        canonical = "long spaghetti-strap dress" if is_long_dress else "spaghetti-strap dress"
        # Apply only when the Chinese source names the complete dress concept;
        # standalone 吊带袜/吊袜带 must keep their legitimate garter meaning.
        bad_patterns = (
            r"\b(?:a\s+)?long\s+garters?(?:['’]s)?(?:\s+dress)?\b"
            if is_long_dress else r"\b(?:a\s+)?garters?(?:['’]s)?\s+dress\b",
            r"\b(?:a\s+)?(?:long\s+)?suspender\s+dress\b",
            r"\b(?:a\s+)?long\s+skirt\s+with\s+(?:a\s+)?straps?\s+on\s+(?:her|his|the)\s+shoulders?\b",
            r"\b(?:a\s+)?hanging\s+dress\b",
        )
        for pattern in bad_patterns:
            translated = re.sub(pattern, f"a {canonical}", translated, flags=re.I)

        translated = re.sub(
            r"\b(wearing|wears|in)\s+(?!(?:a|an|the)\s)((?:long\s+)?spaghetti[- ]strap dress)\b",
            r"\1 a \2",
            translated,
            flags=re.I,
        )

        has_strap_dress = bool(re.search(
            r"\bspaghetti[- ]straps?\b.{0,24}\bdress\b|\bdress\b.{0,24}\bspaghetti[- ]straps?\b",
            translated,
            flags=re.I,
        ))
        if not has_strap_dress:
            translated = translated.rstrip(". ") + f". Wearing a {canonical}."
        return translated

    @staticmethod
    def _guard_hand_scope(source: str, translated: str) -> str:
        """Keep explicit left/right/both-hand scope grounded in the source.

        Statistical translation commonly turns one specified hand into plural
        ``hands``.  That changes the requested action and makes hand-object
        interactions unnecessarily difficult for the image model.
        """
        has_right = "右手" in source
        has_left = "左手" in source
        explicit_both = any(token in source for token in ("双手", "两只手", "两手"))

        if has_right and has_left:
            return TranslationService._guard_split_hand_roles(source, translated)

        if explicit_both:
            # Correct a singular hand only when the source explicitly says both.
            if not re.search(r"\bboth\s+(?:of\s+)?(?:(?:her|his|their)\s+)?hands\b", translated, flags=re.I):
                translated = re.sub(
                    r"\b(?:her|his|their)\s+(?:left\s+|right\s+)?hand\b",
                    "both hands",
                    translated,
                    count=1,
                    flags=re.I,
                )
            return translated

        if not (has_right or has_left):
            return translated

        side = "right" if has_right else "left"
        possessive = "her" if any(token in source for token in ("女孩", "女人", "女性", "少女", "她")) else (
            "his" if any(token in source for token in ("男孩", "男人", "男性", "少年", "他")) else "their"
        )
        scoped_hand = f"{possessive} {side} hand"

        # Replace plural or wrongly-sided forms while retaining the sentence's
        # verb and object.  The possessive is source-derived, not MT-derived.
        hand_phrase = r"(?:both\s+(?:of\s+)?)?(?:her|his|their)\s+(?:left\s+|right\s+)?hands?"
        translated, count = re.subn(hand_phrase, scoped_hand, translated, flags=re.I)
        if not count:
            translated, count = re.subn(r"\bboth\s+hands\b|\b(?:left|right)\s+hand\b|\bhands\b", scoped_hand, translated, count=1, flags=re.I)

        if not re.search(rf"\b{re.escape(side)}\s+hand\b", translated, flags=re.I):
            subject = "She" if possessive == "her" else "He" if possessive == "his" else "The character"
            translated = translated.rstrip(". ") + f". {subject} uses {scoped_hand} for this action."
        return translated

    @staticmethod
    def _guard_split_hand_roles(source: str, translated: str) -> str:
        """Stop Marian from copying one hand's object onto the other hand."""
        from anima_prompt_studio.services.enhancer import parse_hand_roles

        roles = parse_hand_roles(source)
        if not roles:
            return translated
        for side, role in roles.items():
            object_en = str(role["object_en"])
            if not object_en:
                continue
            other = "left" if side == "right" else "right"
            other_role = roles[other]
            if other_role["object_key"] == role["object_key"]:
                continue
            noun = re.escape(object_en.split()[-1])
            translated = re.sub(
                rf"(?:and |, )?(?:a |an |the |her |his |their )?{noun}s? "
                rf"(?:on|in|with) (?:her |his |their )?{other} hand",
                "",
                translated,
                flags=re.I,
            )
            translated = re.sub(
                rf"(?:her |his |their )?{other} hand (?:holds|holding|with|on) "
                rf"(?:a |an |the |her |his |their )?{noun}s?",
                f"her {other} hand hangs empty",
                translated,
                flags=re.I,
            )
        for side, role in roles.items():
            if not role["hanging"]:
                continue
            translated = re.sub(
                rf"((?:her|his|their)\s+{side}\s+(?:hand|arm))\s+"
                rf"(?:fell|falls|fallen|falling)\s+(?:down|on her side|at her side|by her side)?",
                rf"\1 hangs empty at her side",
                translated,
                flags=re.I,
            )
            if not re.search(rf"\b{side} hand hangs\b", translated, flags=re.I):
                translated = translated.rstrip(". ") + f" Her {side} hand hangs empty at her side."
        translated = re.sub(r"\s{2,}", " ", translated)
        translated = re.sub(r"\s+,", ",", translated)
        translated = re.sub(r",\s*,+", ",", translated)
        return translated.strip(" ,.")

    @staticmethod
    def _guard_nsfw_and_composition_terms(source: str, translated: str) -> str:
        """Fix high-impact NSFW and composition mistranslations without inventing intent."""
        # Canonicalize recurring Marian mistranslations before the fallback
        # phrases below are considered.  Replacing the bad token keeps the
        # sentence cleaner than appending a duplicate concept at the end.
        if any(token in source for token in ("微型比基尼", "极小比基尼", "线比基尼")):
            translated = re.sub(r"\bminiature\s+bikini\b|\bmini\s+bikini\b", "micro bikini", translated, flags=re.I)
        if any(token in source for token in ("乳胶", "乳胶衣", "胶衣")):
            translated = re.sub(r"\bemulsions?\b|\bemulsion\s+suit\b", "latex", translated, flags=re.I)
        if any(token in source for token in ("反骑乘", "反向女上位", "背向女上位")):
            translated = re.sub(
                r"\bbackriding\b|\bback[- ]riding\b|\bbackward\s+riding\b",
                "reverse cowgirl",
                translated,
                flags=re.I,
            )
        # 画外 is off-screen / away from viewer, never a painting object.
        if any(token in source for token in ("看向画外", "不看镜头", "看向远方", "眺望远方")):
            translated = re.sub(
                r"\blooking outside the painting\b|\blooks outside the painting\b|"
                r"\blooking out of the painting\b|\boutside the painting\b",
                "looking away",
                translated,
                flags=re.I,
            )
            translated = re.sub(r"\bthe painting\b", "off-screen", translated, flags=re.I)
        # Crop-top / navel drift (OPUS often emits "umbilical").
        if any(token in source for token in ("露脐", "露脐装", "露脐短上衣")):
            translated = re.sub(r"\bumbilical(?:\s+top)?\b", "crop top", translated, flags=re.I)
            if not re.search(r"\b(?:crop top|navel|midriff)\b", translated, flags=re.I):
                translated = translated.rstrip(". ") + " Wearing a crop top with navel visible."
        # Stocking / garter duplication drift.
        if any(token in source for token in ("吊带袜", "长筒袜", "过膝袜", "黑丝", "丝袜")):
            translated = re.sub(r"\bgarters and garters\b", "thighhighs and a garter belt", translated, flags=re.I)
            if not re.search(r"\b(?:thighhighs?|stockings?|pantyhose)\b", translated, flags=re.I):
                translated = translated.rstrip(". ") + " Wearing thighhighs."
        # Cleavage phrasing.
        if any(token in source for token in ("乳沟", "低胸")):
            translated = re.sub(r"\blow-breast\b", "low-cut", translated, flags=re.I)
            translated = re.sub(r"\bshowing her breasts\b", "showing cleavage", translated, flags=re.I)
            if not re.search(r"\bcleavage\b", translated, flags=re.I):
                translated = translated.rstrip(". ") + " Showing cleavage."
        # Ahegao / climax expression blackspeech.
        if any(token in source for token in ("阿嘿颜", "啊嘿颜")):
            translated = re.sub(r"\bshowed a face\b|\ba face\b", "an ahegao expression", translated, flags=re.I)
            if not re.search(r"\bahegao\b", translated, flags=re.I):
                translated = translated.rstrip(". ") + " Ahegao expression, tongue out, rolling eyes."
        if "眼睛上翻" in source:
            translated = re.sub(r"\ban eye out\b|\beye out\b", "rolling eyes", translated, flags=re.I)
            if not any(token in source for token in ("倒立", "倒置", "上下颠倒")):
                translated = re.sub(
                    r"\b(?:her |his |their )?eyes? (?:are |is )?(?:upside[- ]down|inverted)\b",
                    "rolling eyes",
                    translated,
                    flags=re.I,
                )
                translated = re.sub(r"\bupside[- ]down\b", "rolling eyes", translated, flags=re.I)
            if not re.search(r"\brolling eyes\b", translated, flags=re.I):
                translated = translated.rstrip(". ") + " Rolling eyes."
        # Couple phrasing for 一对男女 style inputs.
        if any(token in source for token in ("一对男女", "一男一女", "一女一男")):
            if not re.search(r"\b(?:man and a woman|woman and a man|couple|1boy|a boy)\b", translated, flags=re.I):
                translated = re.sub(r"\bA couple\b", "A man and a woman", translated, count=1, flags=re.I)
                if not re.search(r"\b(?:man and a woman|couple)\b", translated, flags=re.I):
                    translated = translated.rstrip(". ") + " A man and a woman."
        # 全身 is a shot size. Marian often emits "all over her body/face",
        # which the image model treats as a smear instead of a full figure.
        if "全身" in source:
            translated = re.sub(
                r"\ball over (?:her |his |the |their )?(?:body|face|head)\b",
                "full body",
                translated,
                flags=re.I,
            )
            # Marian often dumps a bare "all over" for 全身 after the sentence.
            translated = re.sub(r",?\s*\ball over\b", "", translated, flags=re.I)
            translated = re.sub(r"\s{2,}", " ", translated).strip(" ,.")
            if not re.search(r"\bfull body\b", translated, flags=re.I):
                translated = translated.rstrip(". ") + " Full body."
        if any(token in source for token in ("垂下", "垂在身侧", "自然垂")) and not any(
            token in source for token in ("摔倒", "倒下", "坠落", "跌倒", "掉下去")
        ):
            translated = re.sub(
                r"\b((?:her|his|their)\s+(?:left|right)\s+(?:hand|arm))\s+"
                r"(?:fell|falls|fallen|falling)\s+(?:down|on her side|at her side|by her side)\b",
                r"\1 hangs naturally at her side",
                translated,
                flags=re.I,
            )
            translated = re.sub(
                r"\b(?:fell|falls|fallen|falling)\s+(?:down|on her side|at her side)\b",
                "hangs at her side",
                translated,
                flags=re.I,
            )
        if phrase_all_negated_zh(source, "抱膝") or phrase_all_negated_zh(source, "抱着膝盖"):
            # Image models treat "not hugging her knees" as the forbidden pose.
            # Delete the concept; keep the positive alternative when the source
            # already says the hands stay at her sides.
            translated = re.sub(
                r",?\s*\b(?:not |without )?(?:hugging|hugs|hug) (?:her |his |their )?(?:own )?(?:knees|legs)\b",
                "",
                translated,
                flags=re.I,
            )
            translated = re.sub(
                r",?\s*\bno knees\b|,?\s*\bwithout knees\b|,?\s*\b(?:does not|doesn't|don't) have knees\b",
                "",
                translated,
                flags=re.I,
            )
            translated = re.sub(r"\s{2,}", " ", translated)
            translated = re.sub(r",\s*,+", ",", translated).strip(" ,.")
            if any(token in source for token in ("双手放在身侧", "双手在身侧", "手在身侧", "垂在身侧")):
                if not re.search(r"\bhands? (?:at|on|by) (?:her |his |their )?sid", translated, flags=re.I):
                    translated = translated.rstrip(". ") + " Hands at her sides."
        if (
            phrase_all_negated_zh(source, "裸体")
            or any(token in source for token in ("穿着完整", "完整的校服", "完整校服"))
        ) and not phrase_has_unnegated_zh(source, "裸体"):
            translated = re.sub(
                r",?\s*\b(?:not |without )?(?:completely )?nude\b",
                "",
                translated,
                flags=re.I,
            )
            translated = re.sub(r",?\s*\b(?:not |without )?naked\b", "", translated, flags=re.I)
            translated = re.sub(r"\s{2,}", " ", translated)
            translated = re.sub(r",\s*,+", ",", translated).strip(" ,.")
            if not re.search(r"\b(?:fully clothed|fully dressed)\b", translated, flags=re.I):
                translated = translated.rstrip(". ") + " Fully clothed."
        if any(token in source for token in ("马克杯", "杯子", "茶杯", "咖啡杯")):
            translated = re.sub(r"\bmarquees?\b", "mug", translated, flags=re.I)
            singular_cup = not re.search(
                r"[两二三四五六七八九十\d][只个].{0,6}(?:杯子|马克杯|茶杯|咖啡杯)", source
            )
            if singular_cup:
                translated = re.sub(r"\bwhite cups\b", "a mug", translated, flags=re.I)
                translated = re.sub(r"\bcups\b", "mug", translated, count=1, flags=re.I)
            if "马克杯" in source and not re.search(r"\bmug\b", translated, flags=re.I):
                translated = translated.rstrip(". ") + " Holding a mug."
        if re.search(r"看书|一本书|拿着书|手里的书|拿着一本", source) and not re.search(
            r"[两二三四五六七八九十\d][本册]书", source
        ):
            translated = re.sub(r"\btwo books\b|\bbooks\b", "a book", translated, flags=re.I)
            if "双手" not in source and not (("左手" in source) and ("右手" in source) and source.count("书") >= 2):
                translated = re.sub(
                    r"\b(?:a |the )?book (?:on|in|with) her (?:left|right) hand and (?:a |the )?book\b",
                    "a book",
                    translated,
                    flags=re.I,
                )
        if any(token in source for token in (
            "闭合的雨伞", "闭合的伞", "收起的雨伞", "收起的伞", "合上的雨伞", "合上的伞",
        )):
            translated = re.sub(
                r"\b(?:an |the )?(?:open(?:ed)?|unfolded)\s+(?:umbrella|parasol)\b",
                "a closed umbrella",
                translated,
                flags=re.I,
            )
            if not re.search(r"\bclosed (?:umbrella|parasol)\b", translated, flags=re.I):
                translated = translated.rstrip(". ") + " Holding a closed umbrella."
        if "男上位" in source and not re.search(r"\bmissionary\b", translated, flags=re.I):
            translated = re.sub(r"\ba man in top\b|\bman on top\b", "missionary position", translated, flags=re.I)
            if not re.search(r"\bmissionary\b", translated, flags=re.I):
                translated = translated.rstrip(". ") + " Missionary position."
        reverse_cowgirl = any(token in source for token in ("反骑乘", "反向女上位", "背向女上位"))
        if reverse_cowgirl:
            translated = re.sub(
                r"\brides? back(?: and backs?)?(?: to the boy)?\b",
                "sits with her back to the boy",
                translated,
                flags=re.I,
            )
            translated = re.sub(
                r"\b(?:backs to the boy|facing away from the boy)\b",
                "with her back to the boy",
                translated,
                flags=re.I,
            )
            if "背对" in source and not re.search(r"\bback to the boy\b", translated, flags=re.I):
                translated = translated.rstrip(". ") + " With her back to the boy."
        if (
            any(token in source for token in ("女上位", "骑乘位"))
            and not reverse_cowgirl
            and not re.search(r"\bcowgirl\b", translated, flags=re.I)
        ):
            translated = translated.rstrip(". ") + " Cowgirl position."
        if any(token in source for token in ("后入", "后入式")) and not re.search(r"\bdoggy\b", translated, flags=re.I):
            translated = translated.rstrip(". ") + " Doggy style."
        if any(token in source for token in ("巨乳", "丰满胸部", "大胸部")) and not re.search(
            r"\b(?:large|big|huge) breasts\b", translated, flags=re.I
        ):
            translated = translated.rstrip(". ") + " Large breasts."
        if any(token in source for token in ("贫乳", "小胸部")) and not re.search(r"\bsmall breasts\b", translated, flags=re.I):
            translated = translated.rstrip(". ") + " Small breasts."
        if any(token in source for token in ("张开双腿", "张腿", "双腿张开", "M字开腿")) and not re.search(
            r"\bspread legs\b", translated, flags=re.I
        ):
            translated = translated.rstrip(". ") + " Spread legs."
        if "跪着" in source and not re.search(r"\bkneel", translated, flags=re.I):
            translated = re.sub(r"\bon her knees\b", "kneeling", translated, flags=re.I)
            if not re.search(r"\bkneel", translated, flags=re.I):
                translated = translated.rstrip(". ") + " Kneeling."
        # 火车便当 is sex-position slang; Marian often emits "train lunch" / bento.
        if "火车便当" in source:
            translated = re.sub(r"\btrain lunches?\b", "full nelson", translated, flags=re.I)
            translated = re.sub(r"\blunch boxes?\b", "full nelson", translated, flags=re.I)
            translated = re.sub(r"\bbento\b", "", translated, flags=re.I)
            translated = re.sub(r"\btrain interior\b", "", translated, flags=re.I)
            translated = re.sub(r"\bcrowd\b", "", translated, flags=re.I)
            translated = re.sub(r"\s{2,}", " ", translated).strip(" ,.")
            if not re.search(r"\bfull nelson\b", translated, flags=re.I):
                translated = translated.rstrip(". ") + " Full nelson."
        # Cold / slang positions that Marian often fails to map.
        slang_positions = (
            (("反骑乘", "反向女上位", "背向女上位"), r"\breverse cowgirl\b", "Reverse cowgirl."),
            (("架腿位", "打桩位", "压腿位"), r"\bmating press\b", "Mating press."),
            (("火车便当", "全尼尔森"), r"\bfull nelson\b", "Full nelson."),
            (("俯卧位", "趴着后入"), r"\bprone bone\b", "Prone bone."),
            (("六九式", "六九"), r"\b(?:69|sixty-?nine)\b", "69 position."),
            (("坐脸", "颜面骑乘", "骑脸"), r"\bfacesitting\b|\bface sitting\b", "Facesitting."),
            (("肛交", "后庭"), r"\banal\b", "Anal."),
            (("微型比基尼", "极小比基尼", "线比基尼"), r"\bmicro bikini\b", "Wearing a micro bikini."),
            (("乳胶", "乳胶衣", "胶衣"), r"\blatex\b", "Wearing latex."),
            (("处男杀手毛衣", "露背毛衣"), r"\bvirgin killer sweater\b", "Wearing a virgin killer sweater."),
            (("开档", "开裆内裤", "开档连裤袜"), r"\bcrotchless\b", "Crotchless clothing."),
            (("巫女服", "巫女装", "巫女"), r"\bmiko\b", "Wearing a miko outfit."),
            (("布鲁马", "体操服短裤"), r"\bburuma\b", "Wearing buruma."),
            (("飞机场", "平板"), r"\bflat chest\b", "Flat chest."),
            (("欧派", "大欧派"), r"\b(?:large|huge|big) breasts\b", "Large breasts."),
            (("晒痕", "泳装晒痕"), r"\btanlines\b", "Tanlines."),
            (("野战", "公开做爱"), r"\bpublic (?:sex|indecency)\b", "Public sex."),
            (("只穿围裙", "裸体围裙"), r"\bnaked apron\b", "Naked apron."),
            (("内裤拨到一边", "内裤拉开"), r"\bpanties aside\b", "Panties aside."),
            (("肩带滑落", "吊带滑落", "一边掉肩"), r"\bstrap slip\b", "Strap slip."),
            (("衬衫半解", "扣子解开", "领口拉开"), r"\bunbuttoned\b|\bclothes pull\b", "Unbuttoned / open shirt."),
            (("口水丝", "津液拉丝", "唾液拉丝"), r"\bsaliva\b", "Saliva trail."),
            (("含手指", "吮手指"), r"\bfinger to mouth\b|\bfinger in (?:her )?mouth\b", "Finger to mouth."),
            (("从身后环抱", "背后抱住"), r"\bhug from behind\b", "Hug from behind."),
            (("膝枕",), r"\blap pillow\b", "Lap pillow."),
            (("绳艺", "龟甲缚"), r"\bshibari\b", "Shibari."),
            (("自拍",), r"\bselfie\b", "Selfie."),
            (("OL", "职业女性", "女职员"), r"\boffice lady\b", "Office lady."),
            (("正坐", "正座"), r"\bseiza\b", "Seiza."),
            (("泪痣",), r"\bmole under eye\b", "Mole under eye."),
            (("虎牙",), r"\bfangs?\b", "Fangs."),
        )
        for triggers, pattern, phrase in slang_positions:
            if any(token in source for token in triggers) and not re.search(pattern, translated, flags=re.I):
                translated = translated.rstrip(". ") + f" {phrase}"
        return translated

    @staticmethod
    def _guard_artist_intent(source: str, translated: str) -> str:
        if not any(word in source for word in ("画风", "风格")) or "@" not in translated:
            return translated
        translated = re.sub(r"(?:with |using |in )?(?:the )?wind (?:of|from)\s+(@[\w.-]+)", r"in the style of \1", translated, flags=re.I)
        artist = re.search(r"@[\w.-]+", translated)
        if artist and not re.search(r"\bstyle\b", translated, flags=re.I):
            translated = translated.rstrip(". ") + f" in the style of {artist.group(0)}."
        return translated

    @classmethod
    def guard_artist_intent(cls, source: str, translated: str) -> str:
        """Re-apply the artist guard after protected @handles are restored."""
        return cls._sanitize(cls._guard_artist_intent(source, translated))

    @staticmethod
    def _sanitize(text: str) -> str:
        text = text.replace("♪", "").replace("♫", "").replace("�", "")
        # Do not erase residual CJK: with the builtin engine it represents an
        # untranslated user concept, and preserving it is safer than silently
        # changing the prompt's meaning.
        text = text.translate(str.maketrans({"，": ", ", "。": ". ", "；": "; ", "：": ": ", "！": "! ", "？": "? "}))
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\s+([,.;!?])", r"\1", text)
        return text.strip(" ,.;")

    def en_to_zh(self, text: str) -> str:
        if not text.strip():
            return ""
        try:
            return self.engine.en_to_zh(text)
        except Exception as exc:
            raise RuntimeError(f"{self.engine_name} 英译中失败：{exc}") from exc
