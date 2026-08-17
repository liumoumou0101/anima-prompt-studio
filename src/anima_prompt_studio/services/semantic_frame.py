from __future__ import annotations

import re
from collections.abc import Iterable

from anima_prompt_studio.domain.models import (
    ExcludedConcept, ProtectedEntity, SemanticFrame, SubjectMode,
)
from .negation import phrase_has_unnegated_zh


class SemanticFrameResolver:
    """Extracts a small set of high-confidence facts shared by prose, tags and audits."""

    _people = re.compile(
        r"女孩|男孩|女人|男人|少女|少年|人物|角色|天使|精灵|狐娘|猫娘|龙娘|女仆|骑士|公主|王子|人群|她|(?<!其)他"
    )
    _female_tokens = ("女孩", "女人", "女性", "少女", "女仆", "公主")
    _male_tokens = ("男孩", "男人", "男性", "少年", "王子")
    _solo_markers = ("独自", "单独一人", "没有和其他人", "没有别人")
    _pair_acts = (
        "女上位", "男上位", "后入", "反骑乘", "口交", "骑乘位", "传教士",
        "六九式", "六九", "架腿位", "做爱", "性交", "性爱",
    )
    _yuri_markers = ("百合", "女女", "两个女孩", "两名女孩", "两位女孩")
    _hetero_markers = ("一对男女", "一男一女", "一女一男", "男女在", "一对情侣")
    _count_prefixes = (
        ("十个", 10), ("十名", 10), ("十位", 10),
        ("九个", 9), ("八个", 8), ("七个", 7), ("六个", 6),
        ("五个", 5), ("五名", 5), ("五位", 5),
        ("四个", 4), ("四名", 4), ("四位", 4),
        ("三个", 3), ("三名", 3), ("三位", 3), ("三人", 3),
        ("两个", 2), ("两名", 2), ("两位", 2), ("两人", 2),
        ("一对", 2),
    )
    _person_nouns = (
        "女孩", "男孩", "女人", "男人", "少女", "少年", "女性", "男性",
        "人物", "角色", "人",
    )
    _scene = re.compile(
        r"场景|风景|城市|森林|房间|室内|室外|广场|海边|天空|山|河|夜晚|白天|月光|夕阳|清晨|雨|雪"
    )
    _hair = {
        "白发": "white", "白色头发": "white", "白色长发": "white", "白色短发": "white",
        "黑发": "black", "黑色头发": "black", "黑色长发": "black", "黑色短发": "black",
        "蓝发": "blue", "蓝色头发": "blue", "蓝色长发": "blue", "蓝色短发": "blue",
        "金发": "blonde", "红发": "red", "粉发": "pink", "紫发": "purple", "银发": "silver",
    }
    _eyes = {
        "金瞳": "golden", "蓝瞳": "blue", "红瞳": "red", "绿瞳": "green", "紫瞳": "purple",
    }
    _exclusions = (
        ("hat", "hat", ("没有戴帽子", "没戴帽子", "不戴帽子", "不要帽子")),
        ("sword", "sword", ("没有拿剑", "没拿剑", "不拿剑", "不要剑")),
        ("flower", "flower", ("没有拿花", "没拿花", "不拿花", "不要花")),
        ("shoes", "shoes", ("没有穿鞋", "没穿鞋", "不穿鞋")),
        ("outdoors", "outdoors", ("不在室外", "不是室外")),
        ("day", "day", ("不是白天", "并非白天")),
        ("sitting", "sitting", ("没有坐着", "没坐着", "不是坐着")),
        ("crowd", "crowd", ("背景没有其他人", "背景没其他人", "背景无人")),
        ("nude", "nude", ("没有裸体", "没裸体", "不裸体", "不要裸体", "并非裸体")),
        ("kneeling", "kneeling", ("没有跪着", "没跪着", "不是跪着", "不要跪着")),
        ("hug_knees", "hugging own legs", ("没有抱膝", "没抱膝", "不要抱膝", "并非抱膝")),
        ("sex", "sex", ("没有做爱", "没做爱", "不是做爱", "不要做爱")),
        (
            "looking_at_viewer",
            "looking at viewer",
            ("没有看镜头", "不看镜头", "不要看镜头", "别看镜头"),
        ),
        ("male_partner", "1boy", ("没有男孩", "没有男人", "没男孩", "不要男孩", "没有男性")),
    )

    @staticmethod
    def _last_value(text: str, mapping: dict[str, str]) -> str | None:
        values = [(text.rfind(token), value) for token, value in mapping.items() if token in text]
        return max(values, default=(-1, None))[1]

    def _gender_signals_zh(self, text: str) -> tuple[bool, bool]:
        female = any(phrase_has_unnegated_zh(text, token) for token in self._female_tokens)
        male = any(phrase_has_unnegated_zh(text, token) for token in self._male_tokens)
        if re.search(r"(?<!其)他(?:的)?(?:身上|怀里|腿上)", text):
            male = True
        return female, male

    def _counted_group_zh(self, text: str) -> tuple[int, str] | None:
        """Match 两个裸体女孩 / 三名男孩 / 五个人, allowing short modifiers."""
        noun_pattern = "|".join(map(re.escape, self._person_nouns))
        for prefix, count in self._count_prefixes:
            match = re.search(
                rf"{re.escape(prefix)}(?:[^，。；！？]{{0,8}}?)(?:{noun_pattern})",
                text,
            )
            if not match:
                continue
            span = match.group(0)
            if any(token in span for token in self._female_tokens) and not any(
                token in span for token in self._male_tokens
            ):
                return count, "female"
            if any(token in span for token in self._male_tokens) and not any(
                token in span for token in self._female_tokens
            ):
                return count, "male"
            if any(marker in span for marker in ("男女", "情侣")):
                return count, "hetero"
            return count, ""
        return None

    def _resolve_people_zh(
        self,
        text: str,
        *,
        has_person: bool,
        subject_mode: SubjectMode,
        character_entity_count: int,
    ) -> tuple[int | None, str]:
        female, male = self._gender_signals_zh(text)
        solo = any(marker in text for marker in self._solo_markers)
        yuri = any(marker in text for marker in self._yuri_markers)
        hetero_phrase = any(marker in text for marker in self._hetero_markers)
        pair_act = any(phrase_has_unnegated_zh(text, act) for act in self._pair_acts)

        counted = self._counted_group_zh(text)
        people_count: int | None = None
        mix = ""
        if any(token in text for token in ("3P", "三人行")):
            people_count = 3
        elif counted:
            people_count, mix = counted
        elif hetero_phrase or any(token in text for token in (
            "一个女孩和一个男孩", "一个男孩和一个女孩",
            "两个女孩亲吻", "两个女孩做爱",
        )):
            people_count = 2
        elif re.search(
            r"(?:一个|一名)(?:女孩|男孩|男人|女人|人物|角色|人)?.{1,80}"
            r"(?:另一个|另一名)(?:女孩|男孩|男人|女人|人物|角色|人)?",
            text,
        ):
            people_count = 2
        elif female and male:
            people_count = 2
        elif character_entity_count > 1:
            people_count = character_entity_count
        elif pair_act and not solo:
            people_count = 2
        elif has_person:
            people_count = 1
        elif subject_mode == SubjectMode.SCENE:
            people_count = 0

        if solo and (people_count is None or people_count <= 2) and not counted and not hetero_phrase:
            people_count = 1

        if not mix:
            if hetero_phrase or (female and male):
                mix = "hetero"
            elif yuri:
                mix = "female"
            elif people_count == 2 and pair_act and female and not male and not solo:
                mix = "hetero"
            elif people_count == 2 and female and not male:
                mix = "female"
            elif people_count == 2 and male and not female:
                mix = "male"
            elif female and not male:
                mix = "female"
            elif male and not female:
                mix = "male"
        return people_count, mix

    def resolve(self, text: str, entities: Iterable[ProtectedEntity] = ()) -> SemanticFrame:
        entities = list(entities)
        has_character_entity = any(x.entity_type == "character" for x in entities)
        has_person = bool(self._people.search(text)) or has_character_entity
        has_scene = bool(self._scene.search(text))
        subject_mode = SubjectMode.CHARACTER if has_person else SubjectMode.SCENE
        if has_person and re.search(r"人物与场景|角色与场景|人与环境同等|人物和风景同等", text):
            subject_mode = SubjectMode.MIXED

        character_entity_count = len({x.original for x in entities if x.entity_type == "character"})
        people_count, people_mix = self._resolve_people_zh(
            text, has_person=has_person, subject_mode=subject_mode,
            character_entity_count=character_entity_count,
        )
        frame = SemanticFrame(subject_mode=subject_mode, people_count=people_count)
        if people_mix:
            frame.final_attributes["people_mix"] = people_mix
        hair = self._last_value(text, self._hair)
        eyes = self._last_value(text, self._eyes)
        if hair:
            frame.final_attributes["hair_color"] = hair
        if "短发" in text:
            frame.final_attributes["hair_length"] = "short"
        elif "长发" in text:
            frame.final_attributes["hair_length"] = "long"
        if eyes:
            frame.final_attributes["eye_color"] = eyes

        if any(phrase_has_unnegated_zh(text, x) for x in (
            "看书", "看手机", "看向手中", "看着手中", "看手里", "看蘑菇",
        )):
            frame.gaze_intent = "object"
        elif any(phrase_has_unnegated_zh(text, x) for x in ("看向对方", "看着对方", "对视")):
            frame.gaze_intent = "person"
        elif any(x in text for x in (
            "没有看镜头", "不看镜头", "不要看镜头", "别看镜头",
            "看向画外", "看画外", "看向窗外", "看向远方", "眺望远方", "望向远方",
        )):
            frame.gaze_intent = "away"
        elif any(phrase_has_unnegated_zh(text, x) for x in (
            "看镜头", "看向镜头", "俯视镜头", "低头看镜头",
        )):
            frame.gaze_intent = "viewer"

        if any(x in text for x in ("从背后", "背面视角", "背影")):
            frame.angle_intent = "back"
        elif any(x in text for x in ("侧面", "侧视")):
            frame.angle_intent = "side"
        elif any(x in text for x in ("三分之四", "四分之三")):
            frame.angle_intent = "three_quarter"
        elif any(x in text for x in ("正面", "正面视角")):
            frame.angle_intent = "front"

        scene_map = {
            "室内": "indoors", "夜晚": "night", "月光": "moonlight", "夕阳": "sunset",
            "清晨": "morning", "雨": "rain", "雪": "snow", "森林": "forest", "海边": "seaside",
        }
        frame.scene_facts = list(dict.fromkeys(value for token, value in scene_map.items() if token in text))
        for concept_id, tag, triggers in self._exclusions:
            trigger = next((x for x in triggers if x in text), None)
            if trigger:
                frame.excluded_concepts.append(ExcludedConcept(
                    concept_id=concept_id, canonical_tag=tag, source_text=trigger,
                ))
        frame.artist_mentions = list(dict.fromkeys(x.original for x in entities if x.entity_type == "artist"))
        explicit_loras = re.findall(r"(?<!\w)([A-Za-z0-9_.-]+)\s+LoRA\b", text, flags=re.I)
        frame.lora_mentions = list(dict.fromkeys(
            [x.original for x in entities if x.entity_type == "lora"] + explicit_loras
        ))
        return frame

    def resolve_english(self, text: str, entities: Iterable[ProtectedEntity] = ()) -> SemanticFrame:
        """Resolve the V1 semantic contract from authoritative edited English."""
        entities = list(entities)
        lower = text.casefold()
        person_pattern = r"\b(?:girl|girls|boy|boys|woman|women|man|men|person|people|character|characters|she|he|they|angel|elf|maid|knight|princess|prince)\b"
        # Danbooru count tags are person signals even when "girl" is glued as 1girl.
        has_1girl = bool(re.search(r"\b1girl\b", lower))
        has_1boy = bool(re.search(r"\b1boy\b", lower))
        has_2girls = bool(re.search(r"\b2girls\b", lower))
        has_3girls = bool(re.search(r"\b3girls\b", lower))
        has_2boys = bool(re.search(r"\b2boys\b", lower))
        has_person = (
            bool(re.search(person_pattern, lower))
            or has_1girl or has_1boy or has_2girls or has_3girls or has_2boys
            or any(x.entity_type == "character" for x in entities)
        )
        scene_pattern = r"\b(?:scene|landscape|city|forest|room|indoors|outdoors|beach|sky|mountain|river|night|day|daylight|moonlight|sunset|dawn|rain|snow)\b"
        has_scene = bool(re.search(scene_pattern, lower))
        subject_mode = SubjectMode.CHARACTER if has_person else SubjectMode.SCENE
        if has_person and has_scene and re.search(r"\b(?:character and scene|person and environment)\b.*\b(?:equally|equal focus)\b", lower):
            subject_mode = SubjectMode.MIXED

        count_match = re.search(r"\b(one|two|three|four|\d+)\s+(?:girls?|boys?|women|men|people|persons?|characters?)\b", lower)
        number_words = {"one": 1, "two": 2, "three": 3, "four": 4}
        if count_match:
            token = count_match.group(1)
            people_count = number_words.get(token, int(token) if token.isdigit() else 1)
        elif has_3girls:
            people_count = 3
        elif has_2girls or has_2boys or re.search(
            r"\b(?:couple|a man and a (?:woman|girl)|a woman and a man|a girl and a boy|a boy and a girl|"
            r"one (?:girl|boy|woman|man|person|character).{1,100}another (?:girl|boy|woman|man|person|character))\b",
            lower,
        ):
            people_count = 2
        elif has_1girl and has_1boy:
            people_count = 2
        elif has_1girl or has_1boy:
            people_count = 1
        elif re.search(r"\b(?:a|an|the)\s+(?:girl|boy|woman|man|person|character|angel|elf|maid|knight|princess|prince)\b|\b(?:she|he)\b", lower):
            people_count = 1
        else:
            people_count = 1 if has_person else 0
        # Explicit dual count tags outrank a leading singular noun phrase.
        if has_1girl and has_1boy:
            people_count = max(people_count or 0, 2)
        two_girls = bool(re.search(r"\btwo\s+(?:(?:nude|naked|young|beautiful)\s+)?(?:girls|women)\b", lower))
        two_boys = bool(re.search(r"\btwo\s+(?:(?:nude|naked|young|handsome)\s+)?(?:boys|men)\b", lower))
        if two_girls:
            people_count = max(people_count or 0, 2)
        if two_boys:
            people_count = max(people_count or 0, 2)
        pair_act = bool(re.search(
            r"\b(?:cowgirl|doggy(?: style)?|missionary|fellatio|blowjob|reverse cowgirl|oral)\b",
            lower,
        ))
        solo = bool(re.search(r"\b(?:solo|alone|by herself|by himself|no one else)\b", lower))
        if pair_act and not solo and (people_count or 0) < 2:
            people_count = 2
        if solo and (people_count or 0) <= 2 and not has_2girls and not has_2boys and not two_girls and not two_boys:
            people_count = 1
        frame = SemanticFrame(subject_mode=subject_mode, people_count=people_count)
        if has_1girl and has_1boy:
            frame.final_attributes["people_mix"] = "hetero"
        elif has_2girls or two_girls:
            frame.final_attributes["people_mix"] = "female"
        elif has_2boys or two_boys:
            frame.final_attributes["people_mix"] = "male"
        elif pair_act and not solo and not re.search(r"\b(?:yuri|two girls)\b", lower):
            frame.final_attributes["people_mix"] = "hetero"
        elif re.search(r"\b(?:couple|a man and a (?:woman|girl)|a woman and a man)\b", lower):
            frame.final_attributes["people_mix"] = "hetero"

        colours = "white|black|blue|blonde|golden|red|pink|purple|silver|green|brown"
        hair_matches = list(re.finditer(rf"\b({colours})(?:[- ]haired|\s+hair)\b", lower))
        if hair_matches:
            value = hair_matches[-1].group(1)
            frame.final_attributes["hair_color"] = "blonde" if value == "golden" else value
        length_matches = list(re.finditer(r"\b(short|long|very long)(?:[- ][a-z]+)?\s*hair(?:ed)?\b|\b(short|long)[- ]haired\b", lower))
        if length_matches:
            frame.final_attributes["hair_length"] = next(x for x in length_matches[-1].groups() if x)
        eye_matches = list(re.finditer(rf"\b({colours})\s+eyes?\b", lower))
        if eye_matches:
            frame.final_attributes["eye_color"] = eye_matches[-1].group(1)

        if re.search(
            r"\b(?:looks?|looking|gazes?)\s+(?:at|toward|towards)\s+(?:the )?"
            r"(?:book|phone|object|mushrooms?|item)\b",
            lower,
        ):
            frame.gaze_intent = "object"
        elif re.search(r"\b(?:looks?|looking)\s+at\s+(?:the )?(?:other|another person|each other)\b", lower):
            frame.gaze_intent = "person"
        elif re.search(
            r"\b(?:looks?|looking)\s+(?:away|off[- ]?screen|outside|out (?:of )?the window|into the distance)\b"
            r"|\bnot looking at (?:the )?(?:viewer|camera)\b"
            r"|\b(?:does(?:n't| not)|do(?:n't| not)|did(?:n't| not)|never)\s+look at (?:the )?(?:viewer|camera)\b",
            lower,
        ):
            frame.gaze_intent = "away"
        elif re.search(r"\b(?:looks?|looking)\s+(?:at|toward|towards)\s+(?:the )?(?:viewer|camera)\b", lower):
            frame.gaze_intent = "viewer"

        if re.search(r"\b(?:from behind|back view|viewed from the back)\b", lower):
            frame.angle_intent = "back"
        elif re.search(r"\b(?:side view|from the side|profile view)\b", lower):
            frame.angle_intent = "side"
        elif re.search(r"\b(?:three-quarter|three quarter) view\b", lower):
            frame.angle_intent = "three_quarter"
        elif re.search(r"\b(?:front view|from the front)\b", lower):
            frame.angle_intent = "front"

        scenes = (
            ("indoors", ("indoors", "inside a room")), ("outdoors", ("outdoors",)),
            ("daylight", ("daylight", "daytime")), ("night", ("night", "nighttime")),
            ("moonlight", ("moonlight",)), ("sunset", ("sunset", "dusk")),
            ("morning", ("morning", "dawn")), ("rain", ("rain", "rainy")),
            ("snow", ("snow", "snowy")), ("forest", ("forest",)), ("seaside", ("seaside", "beach")),
        )
        for fact, phrases in scenes:
            if any(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", lower) for phrase in phrases):
                frame.scene_facts.append(fact)

        exclusions = (
            ("hat", "hat"), ("sword", "sword"), ("flower", "flower"), ("shoes", "shoes"),
            ("outdoors", "outdoors"), ("day", "day"), ("sitting", "sitting"), ("crowd", "crowd"),
            ("nude", "nude"), ("kneeling", "kneeling"), ("sex", "sex"),
        )
        for concept_id, tag in exclusions:
            match = re.search(rf"\b(?:without|no)\s+(?:a\s+|any\s+)?{re.escape(tag)}s?\b|\bnot\s+(?:wearing|holding|in|during)?\s*(?:a\s+|the\s+)?{re.escape(tag)}s?\b", lower)
            if match:
                frame.excluded_concepts.append(ExcludedConcept(
                    concept_id=concept_id, canonical_tag=tag, source_text=match.group(0),
                ))
        hug_match = re.search(
            r"\b(?:without|no|not)\s+(?:hugging (?:her |his |their )?(?:own )?(?:knees|legs)|hug(?:ging)? knees)\b",
            lower,
        )
        if hug_match:
            frame.excluded_concepts.append(ExcludedConcept(
                concept_id="hug_knees", canonical_tag="hugging own legs", source_text=hug_match.group(0),
            ))
        viewer_match = re.search(
            r"\b(?:not looking at|without looking at|(?:does|do|did)(?:n't| not) look at)\s+(?:the )?(?:viewer|camera)\b",
            lower,
        )
        if viewer_match:
            frame.excluded_concepts.append(ExcludedConcept(
                concept_id="looking_at_viewer", canonical_tag="looking at viewer",
                source_text=viewer_match.group(0),
            ))
        frame.artist_mentions = list(dict.fromkeys(x.original for x in entities if x.entity_type == "artist"))
        explicit_loras = re.findall(r"(?<!\w)([A-Za-z0-9_.-]+)\s+LoRA\b", text, flags=re.I)
        frame.lora_mentions = list(dict.fromkeys(
            [x.original for x in entities if x.entity_type == "lora"] + explicit_loras
        ))
        return frame
