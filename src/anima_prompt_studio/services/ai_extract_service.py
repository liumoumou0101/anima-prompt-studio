from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from anima_prompt_studio.services.ai_prompt_service import AIClient


MAX_SOURCE_CHARS = 8000
MAX_COMPILER_CHARACTERS = 3
MAX_CHARACTER_FACTS = 10
MAX_CHARACTER_CHARS = 120
MAX_SCENE_FACTS = 7
MAX_SCENE_CHARS = 90

_EMPTY_VISUAL_FACTS = frozenset({
    "无", "无动作", "无主动动作", "无话", "不明", "未知", "未指定", "不确定",
    "未知发色", "未知眼色", "光线不明", "自然光不明", "日间不明", "夜晚或日间不明",
})
_FACT_SPLIT_RE = re.compile(r"[，,、；;。！？!?\n]+")
_VISUAL_LABEL_TOKENS = (
    "男", "女", "人类", "精灵", "魅魔", "魔导师", "法师", "战士", "骑士", "老板",
    "少女", "少年", "成人", "成年", "人物", "角色", "公主", "王子", "游侠", "旅行者",
    "祭司", "牧师", "侍女", "女仆", "钟表匠",
)
_ACCESSORY_TOKENS = (
    "手镯", "手链", "项链", "吊坠", "耳环", "耳坠", "戒指", "发饰", "头饰", "王冠",
    "眼镜", "墨镜", "护目镜",
)
_FOOTWEAR_TOKENS = (
    "高跟鞋", "过膝靴", "长靴", "短靴", "靴子", "鞋子", "鞋", "赤脚", "光脚",
)
_EXPLICIT_SOURCE_TOKENS = (
    "性交", "性爱", "交合", "插入", "抽插", "阴茎", "阴道", "肛门", "乳交", "口交",
    "射精", "精液", "高潮", "自慰", "肉棒", "肉穴", "龟头",
)
_RELATION_TARGET_RE = re.compile(
    r"(?P<verb>抬头看向|抬头看|看向|看着|打量|凝视|注视|望向)"
    r"(?P<target>[\u4e00-\u9fff]{1,6})"
)
_NESTED_SPATIAL_ROLE_RE = re.compile(
    r"(?P<state>(?:身体)?(?:悬挂|悬吊|吊挂|站立|站|躺|跪|坐)在[^的，。；]{1,18})"
    r"的(?P<role>角色[A-C])"
)
_NON_PERSON_TARGETS = frozenset({
    "镜头", "左侧", "右侧", "前方", "后方", "远处", "天空", "地面", "窗外",
    "左边人物", "中间人物", "右边人物", "角色A", "角色B", "角色C",
})
_OUTDOOR_SCENE_TOKENS = (
    "室外", "户外", "街道", "森林", "草地", "草丛", "山谷", "瀑布", "河", "湖",
    "海边", "桥", "深涧", "悬崖", "天空", "广场", "田野", "雪原",
)

EXTRACT_SYSTEM = """You extract still-image visual facts from long narrative or setting text for ANIMA Prompt Studio.
This is NOT translation and NOT prompt rewriting. Do not output English Danbooru tags, quality words, LoRA names, or artist handles.

Rules:
1. Extract only what can be drawn in one still frame. Ignore plot, dialogue, inner thoughts, time skips, and abstract emotion unless they describe a visible state.
2. Do not invent hair, eyes, body, clothing, pose, props, location, lighting, or camera that the source does not support.
3. Keep people separate. Never move colors, clothes, objects, poses, or actions between subjects.
4. For actions and poses, prefer Chinese facts with left/right limbs, contact object, contact point, and body support when the text allows it.
5. If several scenes exist, extract ONLY the last fully described tableau, unless the user marked another moment. Never blend people or actions from earlier tableaux into it.
6. negatives are only explicit unwanted visuals (不要/没有/禁止).
7. Use empty strings/lists for unknown facts. Never write placeholders such as 未知、不明、未指定 or 无.
8. Put each visible fact in exactly one field. clothing is only garments; accessories is jewelry, glasses and head ornaments; footwear is shoes, boots or bare feet. Never drop a visible accessory or footwear merely because clothing already has several items. Keep action to at most three short, atomic clauses.
9. Camera fields must be empty unless the source explicitly supports them. Do not invent a shot or angle.
10. label is only a short UI name or position. identity must be a drawable role/gender/species such as 男性、成年女性、精灵女性 or 女魔导师 when the source supports it; never repeat a proper name as identity.
11. In gaze/action, refer to another subject by relative role (另一人、左边人物、右边人物), never by proper name.
12. Do not censor or euphemize adult sexual/violent facts. When they are visible in the selected still, action must preserve the primary anatomical contact or interaction before secondary motion. Set content_rating from the SELECTED still only, not from earlier text.
13. When two or more people physically interact, interaction_zh must be one short subject-object sentence using character labels, contact point, direction, and any critical spatial state (悬挂在桥下/站在对方身后/躺在地面). Example: “左侧游侠右手抓住悬挂在断桥下方的右侧旅行者右手腕并向上拉”. Do not use names. Leave it empty when there is no interaction.
14. A person mentioned only in dialogue, a voice, memory, narration, or off-screen action is NOT a visible character. Do not include them in people_count or characters.
15. For combat/rescue, freeze the decisive instant rather than the aftermath. key_event_zh must preserve actor, weapon or limb, target, contact/near-miss, direction, and body support. Never reduce a weapon fight to “two people falling”.
16. scene_type is portrait, interaction, action, or group. spatial_layout_zh must state foreground/background and left/center/right placement when two roles, factions, or depth layers matter.
17. anima_prompt_en is a literal 80-180 word diffusion prompt for ONE coherent still image. Describe scene and camera first, then each spatial role/faction separately, then the decisive event. Repeat ownership of distinctive colors, clothing, weapons, hair, and actions so they cannot drift to another role. Use concrete English; no proper names, quality tags, artist names, style handles, plot, dialogue, alternatives, or explanations. It may mention ONLY bodies present in characters; an off-screen speaker or weapon thrower stays off-screen and is represented only by the visible projectile trajectory. NEVER fill unknown hair, clothing, armor, expression, or body details with plausible defaults. Omit them. For group scenes describe formations as groups, not three representative individuals. End with “No one is looking at the viewer.” unless the source explicitly says otherwise.
18. anima_negative_en contains only likely structural mistakes to prevent, such as split screen, character sheet, duplicated people, merged bodies, wrong role colors, or looking at viewer. Do not negate anything explicitly required by the source.
19. Write extracted facts in Chinese and anima prompt fields in English. Return exactly one JSON object, no Markdown:

{
  "summary_zh": "...",
  "people_count": 1,
  "subject_mode": "character|scene|mixed",
  "content_rating": "safe|suggestive|explicit",
  "scene_type": "portrait|interaction|action|group",
  "key_event_zh": "",
  "spatial_layout_zh": "",
  "anima_prompt_en": "",
  "anima_negative_en": [],
  "interaction_zh": "",
  "characters": [
    {
      "label": "左侧少女",
      "identity": "",
      "appearance": ["白发", "红眼"],
      "body": [],
      "clothing": ["黑色风衣"],
      "accessories": ["银叶手镯"],
      "footwear": ["高跟鞋"],
      "expression": "微笑",
      "gaze": "看向镜头",
      "pose": "站立",
      "action": "右手撑伞，左脚踩在水坑边"
    }
  ],
  "scene": {
    "location": "雨夜街道",
    "time": "夜晚",
    "weather": "下雨",
    "objects": ["霓虹灯", "水坑"],
    "lighting": "霓虹倒影",
    "atmosphere": ""
  },
  "camera": {
    "shot": "全身",
    "angle": "三分之四",
    "camera_height": "平视",
    "subject_position": "居中"
  },
  "negatives": [],
  "notes": []
}
"""


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,，、\n]", value) if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _clean_visual_fact(value: Any) -> str:
    text = re.sub(r"\s+", "", str(value or "")).strip("，,、；;。！？!?：: ")
    if not text or text.casefold() in _EMPTY_VISUAL_FACTS:
        return ""
    if text.startswith(("未知", "未指定", "不明")) or text.endswith("不明") or "未指定" in text:
        return ""
    return text


def _visual_label_fact(value: Any) -> str:
    label = _clean_visual_fact(value)
    if not label or not any(token in label for token in _VISUAL_LABEL_TOKENS):
        return ""
    return label


def _replace_character_names(value: Any, references: dict[str, str] | None) -> str:
    text = _clean_visual_fact(value)
    for name, scope in sorted((references or {}).items(), key=lambda item: len(item[0]), reverse=True):
        if name:
            text = text.replace(name, scope)
    return text


def _replace_other_person_aliases(value: Any, other_scope: str | None) -> str:
    text = _clean_visual_fact(value)
    if not text or not other_scope:
        return text
    aliases = (
        "右侧桥下人物", "左侧桥下人物", "右边人物", "左边人物",
        "右侧人物", "左侧人物", "另一名人物", "另一个人", "另一人", "对方",
    )
    for alias in aliases:
        text = text.replace(alias, other_scope)
    return text


def _replace_two_person_relation_target(value: Any, other_scope: str | None) -> str:
    text = _clean_visual_fact(value)
    if not text or not other_scope:
        return text
    if other_scope in text:
        return text

    def replace(match: re.Match[str]) -> str:
        target = match.group("target")
        if "人物" in target or target in _NON_PERSON_TARGETS:
            return match.group(0)
        return match.group("verb") + other_scope

    return _RELATION_TARGET_RE.sub(replace, text)


def _compiler_scene_location(value: Any) -> str:
    location = _clean_visual_fact(value)
    location = re.sub(r"^(?:清晨|早晨|黎明)(?:时分)?", "", location)
    if location and "室内" not in location and any(
        token in location for token in ("旅馆", "旅店", "酒馆", "房间", "卧室", "客厅")
    ):
        location += "室内"
    return location


def _is_outdoor_scene(location: Any, objects: list[str]) -> bool:
    text = "，".join([_clean_visual_fact(location), *(_clean_visual_fact(x) for x in objects)])
    return any(token in text for token in _OUTDOOR_SCENE_TOKENS)


def _compiler_scene_time(value: Any, *, outdoors: bool) -> str:
    time_text = _clean_visual_fact(value)
    if outdoors and any(token in time_text for token in ("清晨", "早晨")):
        # The legacy morning enhancement invents an indoor window. "黎明" is
        # already supported by the deterministic vocabulary without that side effect.
        return "黎明"
    return time_text


def _compiler_lighting(value: Any) -> str:
    lighting = _clean_visual_fact(value)
    if lighting in {"圣光", "圣光笼罩", "沐浴在圣光中", "仿佛沐浴在圣光中"}:
        return "柔和圣洁光芒"
    return "昏暗光线" if lighting in {"光暗", "暗", "昏暗"} else lighting


def _compiler_appearance(value: Any) -> str:
    fact = _clean_visual_fact(value)
    for source, target in (
        ("淡粉色", "粉色"), ("浅粉色", "粉色"), ("淡粉", "粉色"), ("浅粉", "粉色"),
    ):
        fact = fact.replace(source, target)
    return fact


def _compiler_pose(value: Any) -> str:
    pose = _clean_visual_fact(value)
    if re.search(r"双脚悬(?:在|于).+上方", pose) and "悬空" not in pose:
        return "身体悬空，双脚离开支撑面"
    return pose


def _split_nested_interaction_states(value: Any) -> tuple[str, dict[str, str]]:
    states: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        state = _clean_visual_fact(match.group("state"))
        role = match.group("role")
        if state:
            states.setdefault(role, state)
        return role

    return _NESTED_SPATIAL_ROLE_RE.sub(replace, _clean_visual_fact(value)), states


def _fact_chunks(value: Any, *, limit: int | None = None) -> list[str]:
    chunks = [_clean_visual_fact(item) for item in _FACT_SPLIT_RE.split(str(value or ""))]
    result = _dedupe_facts(item for item in chunks if item)
    return result if limit is None else result[:limit]


def _dedupe_facts(values: Any) -> list[str]:
    """Keep the most specific form of repeated/contained short facts."""
    result: list[str] = []
    for value in values:
        fact = _clean_visual_fact(value)
        if not fact:
            continue
        normalized = fact.casefold()
        replaced = False
        for index, current in enumerate(result):
            current_normalized = current.casefold()
            if normalized == current_normalized or normalized in current_normalized:
                replaced = True
                break
            if current_normalized in normalized:
                result[index] = fact
                replaced = True
                break
        if not replaced:
            result.append(fact)
    return result


def _bounded_facts(values: list[str], *, max_items: int, max_chars: int) -> list[str]:
    result: list[str] = []
    used = 0
    for fact in _dedupe_facts(values):
        added = len(fact) + (1 if result else 0)
        if result and (len(result) >= max_items or used + added > max_chars):
            break
        if not result and len(fact) > max_chars:
            fact = fact[:max_chars].rstrip("，,、；;。 ")
            added = len(fact)
        if fact:
            result.append(fact)
            used += added
    return result


def _bounded_scene_facts(values: list[str], *, max_items: int, max_chars: int) -> list[str]:
    """Keep atomic scene objects even when the location phrase contains them."""
    result: list[str] = []
    seen: set[str] = set()
    used = 0
    for value in values:
        fact = _clean_visual_fact(value)
        normalized = fact.casefold()
        if not fact or normalized in seen:
            continue
        added = len(fact) + (1 if result else 0)
        if result and (len(result) >= max_items or used + added > max_chars):
            break
        if not result and len(fact) > max_chars:
            fact = fact[:max_chars].rstrip("，,、；;。 ")
            normalized = fact.casefold()
            added = len(fact)
        if fact:
            result.append(fact)
            seen.add(normalized)
            used += added
    return result


class ExtractedCharacter(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str = ""
    identity: str = ""
    appearance: list[str] = Field(default_factory=list)
    body: list[str] = Field(default_factory=list)
    clothing: list[str] = Field(default_factory=list)
    accessories: list[str] = Field(default_factory=list)
    footwear: list[str] = Field(default_factory=list)
    expression: str = ""
    gaze: str = ""
    pose: str = ""
    action: str = ""
    included: bool = True

    @field_validator("appearance", "body", "clothing", "accessories", "footwear", mode="before")
    @classmethod
    def coerce_string_lists(cls, value: Any) -> list[str]:
        return _string_list(value)

    def visible_facts(self) -> list[str]:
        facts = []
        if self.identity.strip():
            facts.append(self.identity.strip())
        facts.extend(self.appearance)
        facts.extend(self.body)
        facts.extend(self.clothing)
        facts.extend(self.accessories)
        facts.extend(self.footwear)
        for value in (self.expression, self.gaze, self.pose, self.action):
            if value.strip():
                facts.append(value.strip())
        return facts

    def to_clause(self) -> str:
        chunks = []
        if self.label.strip():
            chunks.append(self.label.strip())
        chunks.extend(self.visible_facts())
        text = "，".join(chunks)
        return text + "。" if text and not text.endswith(("。", "！", "？")) else text

    def compiler_facts(
        self,
        references: dict[str, str] | None = None,
        other_scope: str | None = None,
        interaction_fact: str | None = None,
    ) -> list[str]:
        """Return compact, atomic facts suitable for the deterministic compiler."""
        raw_identity = _clean_visual_fact(self.identity)
        identity = [] if raw_identity in (references or {}) else _fact_chunks(
            _replace_character_names(raw_identity, references), limit=1
        )
        appearance = _dedupe_facts(
            _compiler_appearance(_replace_character_names(value, references)) for value in self.appearance
        )[:3]
        body = _dedupe_facts(
            _replace_character_names(value, references) for value in self.body
        )[:1]
        clothing = _dedupe_facts(
            _replace_character_names(value, references) for value in self.clothing
        )[:3]
        accessories = _dedupe_facts(
            _replace_character_names(value, references) for value in self.accessories
        )[:2]
        footwear = _dedupe_facts(
            _replace_character_names(value, references) for value in self.footwear
        )[:1]
        state = _dedupe_facts([
            _replace_character_names(self.expression, references),
            _replace_two_person_relation_target(
                _replace_other_person_aliases(
                    _replace_character_names(self.gaze, references), other_scope
                ),
                other_scope,
            ),
            _compiler_pose(_replace_other_person_aliases(
                _replace_character_names(self.pose, references), other_scope
            )),
        ])
        actions = _fact_chunks(
            _replace_two_person_relation_target(
                _replace_other_person_aliases(
                    _replace_character_names(self.action, references), other_scope
                ),
                other_scope,
            ),
            limit=3,
        )
        interaction = _clean_visual_fact(interaction_fact)
        if interaction:
            limb = next(
                (prefix for prefix in ("左手", "右手", "双手", "左臂", "右臂", "双臂") if interaction.startswith(prefix)),
                "",
            )
            if limb:
                actions = [item for item in actions if not item.startswith(limb)]
            actions.insert(0, interaction)
        # Actions carry the most important pose/contact facts. Put them before
        # optional state so the character budget cannot truncate them away.
        facts = identity + appearance + body + clothing + accessories + footwear + actions + state
        return _bounded_facts(
            facts,
            max_items=MAX_CHARACTER_FACTS,
            max_chars=MAX_CHARACTER_CHARS,
        )

    def to_compiler_clause(
        self,
        scope: str,
        references: dict[str, str] | None = None,
        other_scope: str | None = None,
        interaction_fact: str | None = None,
    ) -> str:
        label = _visual_label_fact(self.label)
        facts = self.compiler_facts(references, other_scope, interaction_fact)
        if label and not any(label.casefold() in fact.casefold() for fact in facts):
            facts.insert(0, label)
        facts = _bounded_facts(
            facts,
            max_items=MAX_CHARACTER_FACTS,
            max_chars=MAX_CHARACTER_CHARS,
        )
        if not facts:
            return ""
        return f"{scope}：" + "，".join(facts) + "。"

    def needs_full_body(self) -> bool:
        if any(_clean_visual_fact(value) for value in self.footwear):
            return True
        motion = "，".join((self.pose, self.action))
        return any(token in motion for token in ("双脚", "左脚", "右脚", "脚踝", "鞋", "靴"))


class ExtractedScene(BaseModel):
    model_config = ConfigDict(extra="ignore")

    location: str = ""
    time: str = ""
    weather: str = ""
    objects: list[str] = Field(default_factory=list)
    lighting: str = ""
    atmosphere: str = ""
    included: bool = True

    @field_validator("objects", mode="before")
    @classmethod
    def coerce_objects(cls, value: Any) -> list[str]:
        return _string_list(value)

    def visible_facts(self) -> list[str]:
        facts = []
        for value in (self.location, self.time, self.weather, self.lighting, self.atmosphere):
            if value.strip():
                facts.append(value.strip())
        facts.extend(item.strip() for item in self.objects if item.strip())
        return facts

    def to_clause(self) -> str:
        facts = self.visible_facts()
        if not facts:
            return ""
        text = "场景：" + "，".join(facts)
        return text + "。" if not text.endswith(("。", "！", "？")) else text

    def to_compiler_clause(self) -> str:
        outdoors = _is_outdoor_scene(self.location, self.objects)
        facts = [
            _compiler_scene_location(self.location),
            _compiler_scene_time(self.time, outdoors=outdoors),
            _clean_visual_fact(self.weather),
            _compiler_lighting(self.lighting),
            *_dedupe_facts(self.objects)[:4],
            _clean_visual_fact(self.atmosphere),
        ]
        facts = _bounded_scene_facts(
            facts,
            max_items=MAX_SCENE_FACTS,
            max_chars=MAX_SCENE_CHARS,
        )
        return "场景：" + "，".join(facts) + "。" if facts else ""

    def compiler_background_fact(self) -> str:
        location = _compiler_scene_location(self.location)
        if not location:
            return ""
        scene_text = "，".join([location, *(_clean_visual_fact(item) for item in self.objects)])
        if "瀑布" in scene_text:
            return "背景是巨大瀑布"
        landmarks = [
            token for token in _OUTDOOR_SCENE_TOKENS
            if token not in {"室外", "户外"} and token in location
        ]
        if landmarks:
            location = "".join(landmarks[:2])
        return "背景是" + location[:20]


class ExtractedCamera(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shot: str = ""
    angle: str = ""
    camera_height: str = ""
    subject_position: str = ""
    included: bool = True

    def visible_facts(self) -> list[str]:
        return [
            value.strip()
            for value in (self.shot, self.angle, self.camera_height, self.subject_position)
            if value.strip()
        ]

    def to_clause(self) -> str:
        facts = self.visible_facts()
        if not facts:
            return ""
        text = "构图：" + "，".join(facts)
        return text + "。" if not text.endswith(("。", "！", "？")) else text

    def to_compiler_clause(self, *, force_full_body: bool = False) -> str:
        values = self.visible_facts()
        if force_full_body and not self.shot.strip():
            values.insert(0, "全身")
        facts = _bounded_facts(values, max_items=3, max_chars=40)
        return "构图：" + "，".join(facts) + "。" if facts else ""


class ExtractedPrompt(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary_zh: str = ""
    people_count: int = 1
    subject_mode: Literal["character", "scene", "mixed"] = "character"
    content_rating: Literal["safe", "suggestive", "explicit"] = "safe"
    scene_type: Literal["portrait", "interaction", "action", "group"] = "portrait"
    key_event_zh: str = ""
    spatial_layout_zh: str = ""
    anima_prompt_en: str = ""
    anima_negative_en: list[str] = Field(default_factory=list)
    interaction_zh: str = ""
    characters: list[ExtractedCharacter] = Field(default_factory=list)
    scene: ExtractedScene = Field(default_factory=ExtractedScene)
    camera: ExtractedCamera = Field(default_factory=ExtractedCamera)
    negatives: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    include_summary: bool = True
    include_negatives: bool = True
    truncated_source: bool = False

    @field_validator("negatives", "notes", "anima_negative_en", mode="before")
    @classmethod
    def coerce_notes(cls, value: Any) -> list[str]:
        return _string_list(value)

    @field_validator("people_count", mode="before")
    @classmethod
    def clamp_people(cls, value: Any) -> int:
        try:
            count = int(value)
        except (TypeError, ValueError):
            return 1
        return max(0, min(count, 8))

    def selected_characters(self) -> list[ExtractedCharacter]:
        return [item for item in self.characters if item.included and item.visible_facts()]

    def to_chinese_brief(self) -> str:
        parts: list[str] = []
        if self.include_summary and self.summary_zh.strip():
            parts.append(self.summary_zh.strip())
        for character in self.selected_characters():
            clause = character.to_clause()
            if clause:
                parts.append(clause)
        if self.interaction_zh.strip():
            parts.append("互动：" + _clean_visual_fact(self.interaction_zh) + "。")
        if self.key_event_zh.strip():
            parts.append("决定性瞬间：" + _clean_visual_fact(self.key_event_zh) + "。")
        if self.spatial_layout_zh.strip():
            parts.append("空间布局：" + _clean_visual_fact(self.spatial_layout_zh) + "。")
        if self.scene.included:
            clause = self.scene.to_clause()
            if clause:
                parts.append(clause)
        if self.camera.included:
            clause = self.camera.to_clause()
            if clause:
                parts.append(clause)
        if self.include_negatives and self.negatives:
            parts.append("不要：" + "，".join(self.negatives) + "。")
        return "\n".join(parts).strip()

    def direct_anima_prompt(self) -> str:
        """Return the novel-assistant-owned English scene plan, if available."""
        text = re.sub(r"\s+", " ", self.anima_prompt_en).strip(" ,.")
        return text[:2400]

    def to_compiler_brief(self) -> str:
        """Build a compact AI-assist-only handoff for the existing local pipeline.

        The review brief deliberately remains lossless and verbose. This handoff
        omits the duplicated summary, filters unknown placeholders, bounds prompt
        size, and scopes up to three characters so Marian/ANIMA receive facts
        instead of narrative prose.
        """
        parts: list[str] = []
        characters = self.selected_characters()[:MAX_COMPILER_CHARACTERS]
        scopes = {
            1: ["中间人物"],
            2: ["角色A", "角色B"],
            3: ["角色A", "角色B", "角色C"],
        }.get(len(characters), [])
        if characters:
            count_label = {1: "一人", 2: "两人", 3: "三人"}[len(characters)]
            parts.append(count_label + "。")
            references = {
                _clean_visual_fact(character.label): scope
                for scope, character in zip(scopes, characters)
                if _clean_visual_fact(character.label)
            }
            interaction = _clean_visual_fact(self.interaction_zh)
            if interaction:
                for name, role in sorted(references.items(), key=lambda item: len(item[0]), reverse=True):
                    interaction = interaction.replace(name, role)
                positional_roles = {
                    "左侧桥下人物": scopes[0], "左侧人物": scopes[0], "左边人物": scopes[0],
                    "右侧桥下人物": scopes[-1], "右侧人物": scopes[-1], "右边人物": scopes[-1],
                }
                if len(scopes) == 3:
                    positional_roles.update({"中间人物": scopes[1], "中央人物": scopes[1]})
                for alias, role in positional_roles.items():
                    interaction = interaction.replace(alias, role)
                interaction = _clean_visual_fact(interaction)[:100]
                interaction, interaction_states = _split_nested_interaction_states(interaction)
            else:
                interaction_states = {}
            character_clauses: list[str] = []
            for scope, character in zip(scopes, characters):
                other_scope = scopes[1 - scopes.index(scope)] if len(scopes) == 2 else None
                interaction_fact = ""
                if interaction.startswith(scope):
                    interaction_fact = interaction[len(scope):].lstrip("：:，, ")
                elif scope in interaction_states:
                    interaction_fact = interaction_states[scope]
                clause = character.to_compiler_clause(
                    scope, references, other_scope, interaction_fact
                )
                if clause and scope == scopes[0] and self.scene.included:
                    background = self.scene.compiler_background_fact()
                    if background:
                        clause = clause.rstrip("。") + "，" + background + "。"
                if clause:
                    parts.append(clause)
                    character_clauses.append(clause)
            if len(character_clauses) == 2:
                relation_verbs = ("看向", "看着", "打量", "凝视", "注视", "望向")
                left_to_right = scopes[1] in character_clauses[0] and any(
                    verb in character_clauses[0] for verb in relation_verbs
                )
                right_to_left = scopes[0] in character_clauses[1] and any(
                    verb in character_clauses[1] for verb in relation_verbs
                )
                if left_to_right and right_to_left:
                    parts.append("两人看向彼此。")
        if self.content_rating == "explicit":
            parts.append("内容：露骨性爱。")
        if self.scene.included:
            clause = self.scene.to_compiler_clause()
            if clause:
                parts.append(clause)
        if self.camera.included:
            clause = self.camera.to_compiler_clause(
                force_full_body=any(character.needs_full_body() for character in characters)
            )
            if clause:
                parts.append(clause)
        if characters:
            explicit_viewer = any(
                "镜头" in _clean_visual_fact(character.gaze)
                and not _clean_visual_fact(character.gaze).startswith(("不", "没有"))
                for character in characters
            )
            gaze_away = not explicit_viewer
        else:
            gaze_away = False
        if self.include_negatives and self.negatives:
            gaze_away = gaze_away or any(
                "看镜头" in _clean_visual_fact(value) for value in self.negatives
            )
            negatives = _bounded_facts(
                [value for value in self.negatives if "看镜头" not in _clean_visual_fact(value)],
                max_items=8,
                max_chars=80,
            )
            if gaze_away:
                parts.append("不看镜头。")
            if negatives:
                parts.append("不要：" + "，".join(negatives) + "。")
        elif gaze_away:
            parts.append("不看镜头。")
        return "\n".join(parts).strip()

    def has_visual_facts(self) -> bool:
        return bool(self.to_chinese_brief())


class AIExtractService:
    """Turn long source text into a local-compiler-friendly Chinese visual brief."""

    def extract(self, source_text: str, client: AIClient) -> ExtractedPrompt:
        text = source_text.strip()
        if not text:
            raise ValueError("请先粘贴小说、设定或长描述。")
        truncated = len(text) > MAX_SOURCE_CHARS
        if truncated:
            text = text[:MAX_SOURCE_CHARS]
        payload = {
            "source_text": text,
            "truncated": truncated,
            "task": "extract_still_image_visual_facts",
        }
        raw = client.complete_json(EXTRACT_SYSTEM, json.dumps(payload, ensure_ascii=False))
        result = ExtractedPrompt.model_validate(raw)
        self._normalize_wearables(result, text)
        if result.content_rating == "explicit" and not any(
            token in text for token in _EXPLICIT_SOURCE_TOKENS
        ):
            # Violence alone is not an explicit-sex quality mode. Misclassifying
            # it replaces ANIMA's safe tag with explicit and changes the image domain.
            result.content_rating = "safe"
        result.truncated_source = truncated
        if not result.people_count:
            result.people_count = len(result.selected_characters())
        if not result.has_visual_facts():
            raise ValueError("这段文本里没有提取到可画的人物、姿势或场景。请换一段更具体的描写。")
        return result

    @staticmethod
    def _normalize_wearables(result: ExtractedPrompt, source_text: str) -> None:
        characters = result.selected_characters()
        for character in characters:
            clothing: list[str] = []
            for value in character.clothing:
                fact = _clean_visual_fact(value)
                if any(token in fact for token in _FOOTWEAR_TOKENS):
                    character.footwear.append(fact)
                elif any(token in fact for token in _ACCESSORY_TOKENS):
                    character.accessories.append(fact)
                else:
                    clothing.append(fact)
            character.clothing = _dedupe_facts(clothing)
            character.accessories = _dedupe_facts(character.accessories)
            character.footwear = _dedupe_facts(character.footwear)

        # A single-subject paragraph is unambiguous enough to recover explicit
        # footwear that a cheap extraction model occasionally overlooks.
        if len(characters) == 1:
            character = characters[0]
            for token in _FOOTWEAR_TOKENS:
                if token in source_text and not any(token in value for value in character.footwear):
                    character.footwear.append(token)
                    break
