from __future__ import annotations

import re
from collections.abc import Iterable

from anima_prompt_studio.domain.models import (
    ExcludedConcept, ProtectedEntity, SemanticFrame, SubjectMode,
)


class SemanticFrameResolver:
    """Extracts a small set of high-confidence facts shared by prose, tags and audits."""

    _people = re.compile(
        r"女孩|男孩|女人|男人|少女|少年|人物|角色|天使|精灵|狐娘|猫娘|龙娘|女仆|骑士|公主|王子|人群|她|(?<!其)他"
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
    )

    @staticmethod
    def _last_value(text: str, mapping: dict[str, str]) -> str | None:
        values = [(text.rfind(token), value) for token, value in mapping.items() if token in text]
        return max(values, default=(-1, None))[1]

    def resolve(self, text: str, entities: Iterable[ProtectedEntity] = ()) -> SemanticFrame:
        entities = list(entities)
        has_character_entity = any(x.entity_type == "character" for x in entities)
        has_person = bool(self._people.search(text)) or has_character_entity
        has_scene = bool(self._scene.search(text))
        subject_mode = SubjectMode.CHARACTER if has_person else SubjectMode.SCENE
        if has_person and re.search(r"人物与场景|角色与场景|人与环境同等|人物和风景同等", text):
            subject_mode = SubjectMode.MIXED

        people_count = None
        character_entity_count = len({x.original for x in entities if x.entity_type == "character"})
        if any(token in text for token in ("三个女孩", "三名女孩", "三个人", "三人")):
            people_count = 3
        elif any(token in text for token in ("3P", "三人行")):
            people_count = 3
        elif any(token in text for token in (
            "两个女孩", "两名女孩", "两个人", "两人", "两位女孩",
            "一个女孩和一个男孩", "一个男孩和一个女孩",
            "一对男女", "一对情侣", "一男一女", "一女一男", "男女在",
            "两个女孩亲吻", "两个女孩做爱",
        )):
            people_count = 2
        elif re.search(
            r"(?:一个|一名)(?:女孩|男孩|男人|女人|人物|角色|人)?.{1,80}"
            r"(?:另一个|另一名)(?:女孩|男孩|男人|女人|人物|角色|人)?",
            text,
        ):
            people_count = 2
        elif character_entity_count > 1:
            people_count = character_entity_count
        elif has_person:
            people_count = 1
        elif subject_mode == SubjectMode.SCENE:
            people_count = 0
        frame = SemanticFrame(subject_mode=subject_mode, people_count=people_count)
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

        if any(x in text for x in ("不看镜头", "看向画外", "看向窗外", "看向远方", "眺望远方", "望向远方")):
            frame.gaze_intent = "away"
        elif any(x in text for x in ("看镜头", "看向镜头", "俯视镜头", "低头看镜头")):
            frame.gaze_intent = "viewer"
        elif any(x in text for x in ("看书", "看向手中", "看着手中", "看蘑菇")):
            frame.gaze_intent = "object"
        elif any(x in text for x in ("看向对方", "看着对方", "对视")):
            frame.gaze_intent = "person"

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
        frame = SemanticFrame(subject_mode=subject_mode, people_count=people_count)

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

        if re.search(r"\b(?:looks?|looking)\s+(?:away|off[- ]?screen|outside|out (?:of )?the window|into the distance)\b|\bnot looking at (?:the )?(?:viewer|camera)\b", lower):
            frame.gaze_intent = "away"
        elif re.search(r"\b(?:looks?|looking)\s+(?:at|toward|towards)\s+(?:the )?(?:viewer|camera)\b", lower):
            frame.gaze_intent = "viewer"
        elif re.search(r"\b(?:looks?|looking|gazes?)\s+(?:at|toward|towards)\s+(?:the )?(?:book|object|mushrooms?|item)\b", lower):
            frame.gaze_intent = "object"
        elif re.search(r"\b(?:looks?|looking)\s+at\s+(?:the )?(?:other|another person|each other)\b", lower):
            frame.gaze_intent = "person"

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
        )
        for concept_id, tag in exclusions:
            match = re.search(rf"\b(?:without|no)\s+(?:a\s+|any\s+)?{re.escape(tag)}s?\b|\bnot\s+(?:wearing|holding|in|during)?\s*(?:a\s+|the\s+)?{re.escape(tag)}s?\b", lower)
            if match:
                frame.excluded_concepts.append(ExcludedConcept(
                    concept_id=concept_id, canonical_tag=tag, source_text=match.group(0),
                ))
        frame.artist_mentions = list(dict.fromkeys(x.original for x in entities if x.entity_type == "artist"))
        explicit_loras = re.findall(r"(?<!\w)([A-Za-z0-9_.-]+)\s+LoRA\b", text, flags=re.I)
        frame.lora_mentions = list(dict.fromkeys(
            [x.original for x in entities if x.entity_type == "lora"] + explicit_loras
        ))
        return frame
