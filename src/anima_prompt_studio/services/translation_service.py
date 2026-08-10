from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Protocol


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
        "在左边": "on the left", "在右边": "on the right", "在中间": "in the center", "和": " and ", "的": " ",
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
            text = text.replace(source, mapping[source])
        text = re.sub(r"(?<=[\u4e00-\u9fff])(?=[A-Za-z0-9_@])", " ", text)
        text = re.sub(r"(?<=[A-Za-z0-9_])(?=[\u4e00-\u9fff])", " ", text)
        text = re.sub(r"\s+([,.;!?])", r"\1", text)
        return re.sub(r"[ \t]+", " ", text).strip(" ,")

    def zh_to_en(self, text: str) -> str:
        # Longest-phrase replace, then drop residual CJK so English field stays pure English.
        # Semantics for unmatched Chinese are recovered later via concept ensure + tags.
        translated = self._replace_longest(text, self._zh_en)
        translated = re.sub(r"[\u4e00-\u9fff]+", " ", translated)
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
        translated = TranslationService._guard_nsfw_and_composition_terms(source, translated)
        return translated

    @staticmethod
    def _guard_nsfw_and_composition_terms(source: str, translated: str) -> str:
        """Fix high-impact NSFW and composition mistranslations without inventing intent."""
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
        # Couple phrasing for 一对男女 style inputs.
        if any(token in source for token in ("一对男女", "一男一女", "一女一男")):
            if not re.search(r"\b(?:man and a woman|woman and a man|couple|1boy|a boy)\b", translated, flags=re.I):
                translated = re.sub(r"\bA couple\b", "A man and a woman", translated, count=1, flags=re.I)
                if not re.search(r"\b(?:man and a woman|couple)\b", translated, flags=re.I):
                    translated = translated.rstrip(". ") + " A man and a woman."
        if "男上位" in source and not re.search(r"\bmissionary\b", translated, flags=re.I):
            translated = re.sub(r"\ba man in top\b|\bman on top\b", "missionary position", translated, flags=re.I)
            if not re.search(r"\bmissionary\b", translated, flags=re.I):
                translated = translated.rstrip(". ") + " Missionary position."
        if any(token in source for token in ("女上位", "骑乘位")) and not re.search(r"\bcowgirl\b", translated, flags=re.I):
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
            (("乳胶衣", "胶衣"), r"\blatex\b", "Wearing latex."),
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
        # Keep translated_en English-only; leftover CJK is recovered via concepts/tags.
        text = re.sub(r"[\u4e00-\u9fff]+", " ", text)
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\s+([,.;!?])", r"\1", text)
        return text.strip(" ,.;")

    def en_to_zh(self, text: str) -> str:
        if not text.strip():
            return ""
        try:
            return self.engine.en_to_zh(text)
        except Exception as exc:
            raise RuntimeError(f"本地英译中失败：{exc}") from exc
