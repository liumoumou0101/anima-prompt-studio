"""Closed-set composition chips and ANIMA-prior notes for Scene Draft.

Empty composition is not neutral on ANIMA: the reliable prior is looking at
the viewer. Chips are never auto-checked. Notes are Chinese product copy so
the user does not have to remember GPU caveats.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain import IntentElementType


COMPOSITION_WEAK_META_TERMS = frozenset({"构图", "镜头", "景别", "机位"})
SHOT_TAGS = frozenset({"full_body", "upper_body", "cowboy_shot", "close-up"})
GAZE_TAGS = frozenset({"looking_at_viewer", "looking_away"})
HEIGHT_TAGS = frozenset({"from_above", "from_below"})
ANGLE_TAGS = frozenset({"profile", "from_behind"})
COMPOSITION_CHIP_TAGS = SHOT_TAGS | GAZE_TAGS | HEIGHT_TAGS | ANGLE_TAGS
UNTRUSTED_COMPOSITION_TAGS = frozenset({"under_shot"})
CROP_RISK_TAGS = frozenset({
    "thighhighs", "white_thighhighs", "black_thighhighs",
    "kneehighs", "pantyhose", "zettai_ryouiki",
    "boots", "knee_boots", "loafers",
    "skirt", "miniskirt", "pleated_skirt", "long_skirt",
})
GAZE_EXCLUDE_PHRASES = ("看向镜头", "看向观众", "看镜头")
GAZE_LOCAL_EXCLUDE_PHRASES = ("不看镜头", "别看镜头")
POSITIVE_HINTS: tuple[tuple[str, str], ...] = (
    ("看向镜头", "looking_at_viewer"),
    ("看向观众", "looking_at_viewer"),
    ("看镜头", "looking_at_viewer"),
    ("看向画外", "looking_away"),
    ("膝上构图", "cowboy_shot"),
    ("膝上", "cowboy_shot"),
    ("半身", "upper_body"),
    ("俯拍", "from_above"),
    ("仰拍", "from_below"),
    ("从背后", "from_behind"),
    ("背面", "from_behind"),
)
NOTE_PRIOR = "未指定视线时，ANIMA 往往会看镜头；可在构图镜头里改。"
NOTE_NEGATIVE_NOT_ENOUGH = "仅把「看镜头」放进负向通常打不破先验，请点选「看向画外」。"
NOTE_CROP = "已确认下装或鞋靴，但还没有景别。点选「膝上」最能改框；「全身」也可以。不是因为原文写了全身。"
NOTE_CANVAS = "竖图/横图只改生成尺寸，不会写成提示词。"
NOTE_EMPTY = "不点选则 Literal 不含构图标签；模型仍可能看镜头。"


@dataclass(frozen=True)
class CompositionChip:
    axis: str
    canonical_tag: str
    label_zh: str
    render_name: str
    note_available: str
    note_selected: str


CHIPS: tuple[CompositionChip, ...] = (
    CompositionChip(
        "shot", "full_body", "全身", "full body",
        "不点选时不一定裁半身；过膝袜等下装有时仍能看见。点选可明确撑开全身。",
        "已选用全身。鞋和袜子更容易入画，但背景有时会被拍扁。",
    ),
    CompositionChip(
        "shot", "upper_body", "上半身", "upper body",
        "上半身更容易裁掉过膝袜和鞋。",
        "已选用上半身。过膝袜和鞋更容易被裁掉。",
    ),
    CompositionChip(
        "shot", "cowboy_shot", "膝上", "cowboy shot",
        "膝上大约裁到大腿，是改框最明显的景别。",
        "已选用膝上。裁切大约到大腿，会明显改框，不一定是全身。",
    ),
    CompositionChip(
        "shot", "close-up", "特写", "close-up",
        "特写只表示景别，不会带上臀部特写一类焦点标签。",
        "已选用特写。这是景别，不是 ass focus 一类焦点标签。",
    ),
    CompositionChip(
        "gaze", "looking_at_viewer", "看镜头", "looking at viewer",
        "模型常见默认。不点选时画面也往往会看镜头。",
        "已选用看镜头。这是模型常见默认，不点选时也经常这样。",
    ),
    CompositionChip(
        "gaze", "looking_away", "看向画外", "looking away",
        "这是把视线拧开的有效方式。只放进负向通常不够。",
        "已选用看向画外，并排除 looking at viewer。仅放进负向通常打不破看镜头。",
    ),
    CompositionChip(
        "camera_height", "from_above", "俯视", "from above",
        "从上往下看。原文「俯视」还可能对应「向下看」，请核对。",
        "已选用俯视（从上往下）。若其实想要人物低头，那是向下看，不是这个芯片。",
    ),
    CompositionChip(
        "camera_height", "from_below", "仰视", "from below",
        "从下往上看。原文只写「仰视」时不会自动勾选，以免当成抬头。",
        "已选用仰视机位（从下往上看）。这不是「抬头」。",
    ),
    CompositionChip(
        "angle", "profile", "侧面", "profile",
        "侧面轮廓。",
        "已选用侧面。",
    ),
    CompositionChip(
        "angle", "from_behind", "背面", "from behind",
        "从后方看。原文「背后」可能是站在谁后面，不会自动勾选。",
        "已选用背面。",
    ),
)
CHIP_BY_TAG = {chip.canonical_tag: chip for chip in CHIPS}
AXIS_TAGS = {
    "shot": SHOT_TAGS,
    "gaze": GAZE_TAGS,
    "camera_height": HEIGHT_TAGS,
    "angle": ANGLE_TAGS,
}


@dataclass(frozen=True)
class CompositionPreset:
    id: str
    label_zh: str
    tags: tuple[str, ...]
    note: str
    group_zh: str


COMPOSITION_PRESETS: tuple[CompositionPreset, ...] = (
    CompositionPreset("none", "不套预设", (), "不写入构图标签。未指定视线时模型仍可能看镜头。", "基础"),
    CompositionPreset("cowboy", "膝上", ("cowboy_shot",), "大约裁到大腿，是改框最明显的景别。", "景别"),
    CompositionPreset("upper", "上半身", ("upper_body",), "更容易裁掉过膝袜和鞋。", "景别"),
    CompositionPreset("full", "全身", ("full_body",), "鞋和袜子更容易入画，背景有时会被拍扁。", "景别"),
    CompositionPreset("closeup", "特写", ("close-up",), "景别特写，不含臀部特写一类焦点标签。", "景别"),
    CompositionPreset("look_away", "看向画外", ("looking_away",), "把视线拧开。只把看镜头放进负向通常不够。", "视线"),
    CompositionPreset("look_viewer", "看镜头", ("looking_at_viewer",), "显式写出模型常见默认。", "视线"),
    CompositionPreset("cowboy_viewer", "膝上立绘", ("cowboy_shot", "looking_at_viewer"), "常见人物肖像：膝上并看镜头。", "常用立绘"),
    CompositionPreset("upper_viewer", "上半身立绘", ("upper_body", "looking_at_viewer"), "半身肖像，看镜头。过膝袜和鞋更容易被裁掉。", "常用立绘"),
    CompositionPreset("full_viewer", "全身立绘", ("full_body", "looking_at_viewer"), "全身看镜头。背景有时会被拍扁。", "常用立绘"),
    CompositionPreset("closeup_viewer", "特写表情", ("close-up", "looking_at_viewer"), "脸部特写并看镜头。", "常用立绘"),
    CompositionPreset("cowboy_away", "膝上看向画外", ("cowboy_shot", "looking_away"), "膝上景别，视线离开镜头。", "朝向与机位"),
    CompositionPreset("full_away", "全身看向画外", ("full_body", "looking_away"), "全身，视线离开镜头。", "朝向与机位"),
    CompositionPreset("profile", "侧面", ("cowboy_shot", "profile"), "膝上侧面轮廓。", "朝向与机位"),
    CompositionPreset("back", "背影", ("full_body", "from_behind", "looking_away"), "背面全身，视线离开镜头。", "朝向与机位"),
    CompositionPreset("low_hero", "仰拍全身", ("full_body", "from_below"), "从下往上拍全身，强调身高气势。", "朝向与机位"),
    CompositionPreset("high", "俯视全身", ("full_body", "from_above"), "从上往下看全身。", "朝向与机位"),
)


@dataclass(frozen=True)
class CompositionSpan:
    text: str
    start: int | None
    end: int | None
    canonical_tag: str
    role: str


def axis_of(tag: str) -> str | None:
    for axis, tags in AXIS_TAGS.items():
        if tag in tags:
            return axis
    return None


def composition_fact_type(tag: str, fallback: IntentElementType) -> IntentElementType:
    return IntentElementType.COMPOSITION if tag in COMPOSITION_CHIP_TAGS else fallback


def filter_weak_meta_matches(matches: list) -> list:
    return [match for match in matches if getattr(match, "text", "") not in COMPOSITION_WEAK_META_TERMS]


def divert_untrusted_composition_matches(matches: list) -> tuple[list, list]:
    kept: list = []
    diverted: list = []
    for match in matches:
        if (
            match.canonical_tag in UNTRUSTED_COMPOSITION_TAGS
            and match.match_kind not in {"canonical", "render"}
        ):
            diverted.append(match)
        else:
            kept.append(match)
    return kept, diverted


def _overlaps(start: int, end: int, used: list[tuple[int, int]]) -> bool:
    return any(start < existing_end and end > existing_start for existing_start, existing_end in used)


def _collect_phrase_hits(text: str, phrases: tuple[str, ...], offset: int = 0) -> list[tuple[str, int, int]]:
    hits: list[tuple[str, int, int]] = []
    used: list[tuple[int, int]] = []
    for phrase in sorted(phrases, key=len, reverse=True):
        cursor = 0
        while True:
            index = text.find(phrase, cursor)
            if index < 0:
                break
            start, end = offset + index, offset + index + len(phrase)
            if not _overlaps(start, end, used):
                hits.append((phrase, start, end))
                used.append((start, end))
            cursor = index + 1
    return hits


def composition_phrase_occupiers(source_text: str, exclusion_spans: list[tuple[str, int, int]]) -> list[CompositionSpan]:
    """Occupy phrase spans so nested 镜头/构图 junk cannot win. Do not confirm."""
    occupiers: list[CompositionSpan] = []
    positive_phrases = tuple(phrase for phrase, _tag in POSITIVE_HINTS) + GAZE_LOCAL_EXCLUDE_PHRASES
    for phrase, start, end in _collect_phrase_hits(source_text, positive_phrases):
        occupiers.append(CompositionSpan(phrase, start, end, "", "occupier"))
    for text, offset, _end in exclusion_spans:
        for phrase, start, end in _collect_phrase_hits(text, GAZE_EXCLUDE_PHRASES, offset):
            occupiers.append(CompositionSpan(phrase, start, end, "looking_at_viewer", "occupier"))
    return occupiers


def auto_exclude_gaze_spans(source_text: str, exclusion_spans: list[tuple[str, int, int]]) -> list[CompositionSpan]:
    spans: list[CompositionSpan] = []
    for text, offset, _end in exclusion_spans:
        for phrase, start, end in _collect_phrase_hits(text, GAZE_EXCLUDE_PHRASES, offset):
            spans.append(CompositionSpan(phrase, start, end, "looking_at_viewer", "auto_exclude"))
    for phrase, start, end in _collect_phrase_hits(source_text, GAZE_LOCAL_EXCLUDE_PHRASES):
        spans.append(CompositionSpan(phrase, start, end, "looking_at_viewer", "auto_exclude"))
    return spans


def positive_composition_hints(source_text: str, excluded_tags: set[str], confirmed_tags: set[str]) -> dict[str, str]:
    """Map phrase → chip tag for palette suggested state. Never writes Literal."""
    hinted: dict[str, str] = {}
    if "looking_at_viewer" in excluded_tags:
        hinted["looking_away"] = "gaze"
        return hinted
    occupied_axes = {axis_of(tag) for tag in confirmed_tags if axis_of(tag)}
    for phrase, tag in POSITIVE_HINTS:
        axis = axis_of(tag)
        if axis in occupied_axes or tag in excluded_tags or tag in hinted:
            continue
        if phrase in source_text:
            hinted[tag] = axis or ""
            occupied_axes.add(axis)
    return hinted


def is_focus_leftover(canonical_tag: str, group_names: set[str]) -> bool:
    if canonical_tag in COMPOSITION_CHIP_TAGS:
        return False
    if "focus_tags" in group_names:
        return True
    return canonical_tag.endswith("_focus")


def strip_focus_leftover_tags(
    primary: str | None,
    leftover_tags: list[str],
    groups_for: dict[str, set[str]],
) -> list[str]:
    remaining = [
        tag for tag in leftover_tags
        if not is_focus_leftover(tag, groups_for.get(tag, set()))
    ]
    if primary == "close-up":
        return []
    return remaining


def clothing_crop_needed(positive_tags: set[str]) -> bool:
    if positive_tags & SHOT_TAGS:
        return False
    return bool(positive_tags & CROP_RISK_TAGS)


def coerce_selected_composition(selected_tags: list[str]) -> list[str]:
    last_by_axis: dict[str, str] = {}
    kept: list[str] = []
    for tag in selected_tags:
        axis = axis_of(tag)
        if axis is None:
            kept.append(tag)
            continue
        last_by_axis[axis] = tag
    seen_axes: set[str] = set()
    result: list[str] = []
    for tag in reversed(selected_tags):
        axis = axis_of(tag)
        if axis is None:
            continue
        if axis in seen_axes:
            continue
        if last_by_axis.get(axis) == tag:
            result.append(tag)
            seen_axes.add(axis)
    non_chip = [tag for tag in selected_tags if tag not in COMPOSITION_CHIP_TAGS]
    return [*non_chip, *reversed(result)]


def filter_composition_related(names: list[str]) -> list[str]:
    return [name for name in names if name not in COMPOSITION_CHIP_TAGS]


def composition_prose_conflicts(translated_text: str, positive: set[str], excluded: set[str]) -> list[str]:
    haystack = translated_text.lower()
    notes: list[str] = []
    gaze_needles = (
        "looking at viewer",
        "looking at the camera",
        "looks at the camera",
        "looks at the viewer",
    )
    if any(needle in haystack for needle in gaze_needles):
        if "looking_away" in positive or "looking_at_viewer" in excluded:
            notes.append("英文画面计划里仍有 looking at the camera / looking at viewer。请直接改英文，否则 Hybrid 可能继续看镜头。")
    for chip in CHIPS:
        if chip.render_name.lower() in haystack and chip.canonical_tag not in positive:
            if chip.axis == "shot" and (positive & SHOT_TAGS):
                notes.append(f"英文画面计划里仍有 {chip.render_name}，与当前景别不一致。请直接改英文。")
                break
    return notes


def prior_risk_notes(
    *,
    gaze_present: bool,
    looking_away: bool,
    looking_at_viewer_excluded: bool,
    crop_needed: bool,
) -> list[str]:
    notes: list[str] = []
    if not gaze_present and not looking_at_viewer_excluded:
        notes.append(NOTE_PRIOR)
    if looking_at_viewer_excluded and not looking_away:
        notes.append(NOTE_NEGATIVE_NOT_ENOUGH)
    if crop_needed:
        notes.append(NOTE_CROP)
    return notes


def chip_note(tag: str, state: str, side: str = "positive", *, crop_hint: bool = False) -> str:
    chip = CHIP_BY_TAG.get(tag)
    if chip is None:
        return "可选构图芯片，不会自动勾选。"
    if state == "excluded" or side == "excluded":
        if tag == "looking_at_viewer":
            return "已排除看镜头，写入负向。仅负向通常不够，请再点选「看向画外」。"
        return f"已排除 {chip.label_zh}，写入负向。"
    if state == "suggested":
        if tag == "looking_away":
            return NOTE_NEGATIVE_NOT_ENOUGH
        if crop_hint and tag in {"full_body", "cowboy_shot"}:
            return NOTE_CROP
        if tag == "looking_at_viewer":
            return "原文提到看镜头，确认后才会加入。"
        if tag == "from_below":
            return "原文写了仰拍。点选后使用从下往上的机位，不是抬头。"
        return f"原文提到{chip.label_zh}，确认后才会加入。{chip.note_available}"
    if state in {"selected", "confirmed"}:
        return chip.note_selected
    if tag == "looking_at_viewer":
        return "模型常见默认。不点选时画面也往往会看镜头。"
    return chip.note_available


def build_composition_palette(
    *,
    confirmed_tags: set[str],
    selected_tags: list[str],
    excluded_tags: set[str],
    hinted_tags: set[str],
    crop_needed: bool,
) -> list[dict[str, object]]:
    selected_set = set(selected_tags)
    items: list[dict[str, object]] = []
    for chip in CHIPS:
        tag = chip.canonical_tag
        side = "positive"
        crop_hint = False
        if tag in excluded_tags:
            state = "excluded"
            side = "excluded"
        elif tag in confirmed_tags:
            state = "confirmed"
        elif tag in selected_set:
            state = "selected"
        elif tag == "looking_away" and "looking_at_viewer" in excluded_tags:
            state = "suggested"
        elif tag in hinted_tags or (crop_needed and tag in {"full_body", "cowboy_shot"}):
            state = "suggested"
            crop_hint = crop_needed and tag in {"full_body", "cowboy_shot"} and tag not in hinted_tags
        else:
            state = "available"
        notes = {
            "available": chip_note(tag, "available", crop_hint=crop_hint),
            "suggested": chip_note(tag, "suggested", crop_hint=crop_hint),
            "selected": chip_note(tag, "selected"),
            "confirmed": chip_note(tag, "confirmed"),
            "excluded": chip_note(tag, "excluded", "excluded"),
        }
        items.append({
            "axis": chip.axis,
            "canonical_tag": tag,
            "label_zh": chip.label_zh,
            "render_name": chip.render_name,
            "state": state,
            "side": side,
            "reason": notes[state],
            "notes": notes,
        })
    return items


def composition_preset_snapshots() -> list[dict[str, object]]:
    return [
        {
            "id": preset.id,
            "label_zh": preset.label_zh,
            "tags": list(preset.tags),
            "note": preset.note,
            "group_zh": preset.group_zh,
        }
        for preset in COMPOSITION_PRESETS
    ]


def match_composition_preset(active_tags: set[str]) -> str:
    normalized = {tag for tag in active_tags if tag in COMPOSITION_CHIP_TAGS}
    for preset in COMPOSITION_PRESETS:
        if preset.id == "none":
            continue
        if set(preset.tags) == normalized:
            return preset.id
    return "none" if not normalized else "custom"
