from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol


class TranslationEngine(Protocol):
    name: str
    def zh_to_en(self, text: str) -> str: ...
    def en_to_zh(self, text: str) -> str: ...


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


class BuiltinOfflineEngine:
    """Small deterministic fallback so the app remains useful before model setup."""

    name = "内置离线基础翻译"
    _zh_en = {
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
        "穿着": "wearing", "裙子": "dress", "短裙": "short skirt", "衬衫": "shirt", "外套": "coat",
        "全身": "full body", "半身": "upper body", "侧面": "side view", "背面": "back view",
        "在左边": "on the left", "在右边": "on the right", "在中间": "in the center", "和": " and ", "的": " ",
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
    }

    @staticmethod
    def _replace_longest(text: str, mapping: dict[str, str]) -> str:
        for source in sorted(mapping, key=len, reverse=True):
            text = text.replace(source, mapping[source])
        text = re.sub(r"(?<=[\u4e00-\u9fff])(?=[A-Za-z0-9_@])", " ", text)
        text = re.sub(r"(?<=[A-Za-z0-9_])(?=[\u4e00-\u9fff])", " ", text)
        text = re.sub(r"\s+([,.;!?])", r"\1", text)
        return re.sub(r"[ \t]+", " ", text).strip(" ,")

    def zh_to_en(self, text: str) -> str:
        return self._replace_longest(text, self._zh_en)

    def en_to_zh(self, text: str) -> str:
        return self._replace_longest(text, self._en_zh)


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
            raise RuntimeError(f"本地中译英失败：{exc}") from exc

    @staticmethod
    def _guard_visual_terms(source: str, translated: str) -> str:
        """Correct common high-impact OPUS drift without inventing attributes."""
        if "女孩" in source and not any(token in source for token in ("两个女孩", "两名女孩", "三个女孩", "三名女孩")):
            translated = re.sub(r"^Girls\b", "A girl", translated, flags=re.I)
        if "男孩" in source and not any(token in source for token in ("两个男孩", "两名男孩", "三个男孩", "三名男孩")):
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
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\s+([,.;!?])", r"\1", text)
        return text.strip()

    def en_to_zh(self, text: str) -> str:
        if not text.strip():
            return ""
        try:
            return self.engine.en_to_zh(text)
        except Exception as exc:
            raise RuntimeError(f"本地英译中失败：{exc}") from exc
