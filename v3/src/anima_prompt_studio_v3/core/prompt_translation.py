"""Local prompt translation with immutable domain anchors and clause provenance.

This is a literal translator, not a creative rewriter. Unknown spans remain the
translation engine's responsibility and are explicitly marked for review.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from collections.abc import Callable


# Deliberately small domain vocabulary, independent of the reference tag index.
# Phrase types prevent 'rim light' becoming an outline and pinafores becoming
# harnesses when the index only knows a shorter substring.
TERM_GROUPS = {
    "subject": {
        "一个女孩": "1girl", "一位女孩": "1girl", "一个少女": "1girl", "一名少女": "1girl",
        "两个女孩": "2girls", "两位女孩": "2girls", "三个女孩": "3girls",
        "一个男孩": "1boy", "两个男孩": "2boys", "一个非二元角色": "1other",
        "单人": "solo", "双人": "two people",
    },
    "style": {
        "动画上色": "anime coloring", "赛璐璐上色": "cel shading", "水彩绘画": "watercolor",
        "水彩画": "watercolor", "水彩": "watercolor", "油画": "oil painting",
        "厚重色彩": "heavy colors", "渐变调色": "color gradation", "印象主义": "impressionism",
        "35毫米胶片摄影": "35mm film photography", "胶片摄影": "film photography",
        "电影照片": "cinematic photograph", "官方宣传插画": "official promotional illustration",
        "铅笔素描": "pencil drawing", "墨线": "ink lines", "像素画": "pixel art",
    },
    "effect": {
        "浅景深散景": "shallow depth of field, bokeh", "浅景深": "shallow depth of field",
        "景深": "depth of field", "散景": "bokeh", "前景虚化": "blurred foreground",
        "背景虚化": "blurred background", "胶片颗粒": "film grain", "柔焦": "soft focus",
        "镜头光晕": "lens flare", "镜头耀斑": "lens flare", "棱镜光": "prismatic light",
        "棱镜耀光": "prismatic lens flare", "轮廓光": "rim light", "色差": "chromatic aberration",
        "电影光照": "cinematic lighting", "现场光": "ambient light", "背景光": "background lighting",
        "情绪化光照": "moody lighting", "柔和光照": "soft lighting", "斑驳的暖阳": "dappled warm sunlight",
    },
    "clothing": {
        "女仆装": "maid", "女仆": "maid", "双马尾": "twintails",
        "背带裙": "pinafore dress", "翻领衬衫": "collared shirt", "休闲连衣裙": "casual dress",
        "连衣裙": "dress", "百褶裙": "pleated skirt", "及膝袜": "knee socks",
        "乐福鞋": "loafers", "校服西装外套": "school uniform blazer", "校服": "school uniform",
        "发带": "hairband", "发饰": "hair ornament", "短袖": "short sleeves",
        "常盘台校服": "tokiwadai school uniform",
    },
    "appearance": {
        "金色长发": "long blonde hair", "金发": "blonde hair", "白发": "white hair",
        "蓝眼睛": "blue eyes", "绿眼睛": "green eyes", "猫耳": "cat ears",
        "人偶关节": "doll joints", "尖锐指甲": "sharp fingernails", "鬓发": "sidelocks",
        "刘海": "bangs", "发髻": "hair bun", "蓝色指甲油": "blue nail polish",
        "凌乱头发": "messy hair", "凌乱的": "messy", "长卷发": "long curly hair",
        "嘴唇微张": "parted lips", "淡淡红晕": "light blush",
        "更少的手指": "fewer digits",
    },
    "action": {
        "蹲伏": "crouching", "弹奏": "playing", "看向观众": "looking at viewer",
        "双臂交叉抱在胸前": "crossed arms", "抬起手臂": "raised arms",
        "举到脸旁": "held beside the face", "举起相机": "holding up a camera",
        "手提着书包": "holding a school bag", "施展电能力": "electrokinesis",
    },
    "object": {"胶片相机": "film camera", "相机": "camera", "吉他": "guitar", "书包": "school bag", "肩带": "shoulder strap"},
    "composition": {
        "上半身特写": "upper body close-up", "全身": "full body", "侧面视角": "from side",
        "倾斜的动态角度": "dynamic dutch angle", "动态姿势": "dynamic pose",
    },
    "quality": {"杰作": "masterpiece", "最佳质量": "best quality", "安全内容": "safe", "超高分辨率": "absurdres",
        "非常有美感": "very aesthetic", "完美构图": "perfect composition", "丰富细节": "rich details"},
}
TERMS = {zh: (en, kind) for kind, entries in TERM_GROUPS.items() for zh, en in entries.items()}
_CJK = re.compile(r"[\u3400-\u9fff]")
_OPAQUE = re.compile(r"\([^()\r\n]+:\s*\d+(?:\.\d+)?\)|@[A-Za-z0-9_.-]+|[A-Za-z][A-Za-z0-9_'.-]*(?:[ ]+[A-Za-z][A-Za-z0-9_'.-]*)*")


@dataclass(frozen=True)
class Anchor:
    start: int
    end: int
    source: str
    english: str
    kind: str


def anchors_for(text: str, extra_terms: dict[str, str] | None = None) -> list[Anchor]:
    terms = {**TERMS, **{key: (value, "identity") for key, value in (extra_terms or {}).items()}}
    candidates = [Anchor(m.start(), m.end(), m.group(), en, kind)
                  for zh, (en, kind) in terms.items() for m in re.finditer(re.escape(zh), text)]
    candidates += [Anchor(m.start(), m.end(), m.group(), m.group(), "verbatim") for m in _OPAQUE.finditer(text)]
    candidates += [Anchor(m.start(), m.end(), m.group(), f"score_{m.group(1)}", "quality")
                   for m in re.finditer(r"评分\s*(\d+)", text)]
    for match in re.finditer(r"(?:强调)?([^，,。；;（）()]+)[（(]权重\s*(\d+(?:\.\d+)?)[）)]", text):
        phrase = match.group(1).removeprefix("强调").strip()
        if phrase in terms:
            candidates.append(Anchor(match.start(), match.end(), match.group(),
                f"({terms[phrase][0]}:{match.group(2)})", "weight"))
    chosen: list[Anchor] = []
    for item in sorted(candidates, key=lambda a: (-(a.end-a.start), a.start)):
        if not any(item.start < old.end and old.start < item.end for old in chosen):
            chosen.append(item)
    return sorted(chosen, key=lambda a: a.start)


def domain_conflict(text: str, start: int | None, end: int | None, canonical: str) -> bool:
    """Do not confirm a shorter index tag inside a typed, longer domain phrase."""
    if start is None or end is None:
        return False
    for anchor in anchors_for(text):
        if anchor.start <= start and end <= anchor.end:
            expected = anchor.english.lower().replace(" ", "_")
            if canonical != expected and anchor.kind not in {"verbatim", "quality"}:
                return True
    return False


def source_clauses(text: str):
    """Keep weighted/quoted expressions intact and preserve exact source offsets."""
    start, depth = 0, 0
    quote = None
    for index, char in enumerate(text):
        if quote:
            if char == quote:
                quote = None
            continue
        if char in {'"', '“'}:
            quote = '”' if char == '“' else char
        elif char in '(（[':
            depth += 1
        elif char in ')）]':
            depth = max(0, depth-1)
        elif char in '，,。；;\n' and not depth:
            raw = text[start:index]
            if raw.strip():
                offset = start + len(raw) - len(raw.lstrip())
                yield offset, raw.strip()
            start = index+1
    raw = text[start:]
    if raw.strip():
        yield start + len(raw) - len(raw.lstrip()), raw.strip()


def translate_prompt(text: str, translate: Callable[[str], str], *, extra_terms: dict[str, str] | None = None) -> tuple[str, list[dict]]:
    """Translate clauses with opaque placeholders; reject missing/duplicate anchors.

    Engines unable to copy a placeholder fall back to translating unknown spans
    separately. This preserves anchors without pretending the fallback is fluent.
    """
    clauses: list[dict] = []
    for source_start, source in source_clauses(text):
        # Bound each engine call independently; never silently truncate a long
        # Chinese paragraph at the model tokenizer limit.
        limit = 120 if _CJK.search(source) else max(120, len(source))
        for offset in range(0, len(source), limit):
            chunk = source[offset:offset+limit]
            anchors = anchors_for(chunk, extra_terms)
            parts: list[str] = []
            cursor = 0
            for i, anchor in enumerate(anchors):
                parts.extend([chunk[cursor:anchor.start], f"ZXQ{i}ZXQ"])
                cursor = anchor.end
            parts.append(chunk[cursor:])
            masked = "".join(parts)
            unknown = _CJK.search(re.sub(r"ZXQ\d+ZXQ", "", masked))
            status = "protected"
            if not unknown:
                rendered = masked
            else:
                rendered = translate(masked) if anchors else translate(chunk)
                status = "machine_review"
            if anchors and (any(rendered.count(f"ZXQ{i}ZXQ") != 1 for i in range(len(anchors)))
                            or len(re.findall(r"ZXQ\d+ZXQ", rendered)) != len(anchors)):
                fragments: list[str] = []
                cursor = 0
                for anchor in anchors:
                    gap = chunk[cursor:anchor.start].strip()
                    if gap:
                        fragments.append(translate(gap) if _CJK.search(gap) else gap)
                    fragments.append(anchor.english)
                    cursor = anchor.end
                gap = chunk[cursor:].strip()
                if gap:
                    fragments.append(translate(gap) if _CJK.search(gap) else gap)
                rendered = " ".join(fragments)
                status = "fragment_review"
            else:
                for i, anchor in enumerate(anchors):
                    rendered = rendered.replace(f"ZXQ{i}ZXQ", " " + anchor.english + " ")
            rendered = re.sub(r"\s+", " ", rendered).strip()
            rendered = rendered.replace("、", ", ")
            if not rendered.strip():
                rendered, status = chunk, "untranslated"
            if _CJK.search(rendered):
                status = "untranslated"
            clauses.append({"source": chunk, "english": rendered.strip(),
                "start": source_start + offset, "end": source_start + offset + len(chunk),
                "status": status, "anchors": [a.__dict__ for a in anchors]})
    return ", ".join(item["english"] for item in clauses), clauses


def review_translation(source: str, translated: str) -> dict:
    normalized = translated.lower().replace("_", " ")
    missing = [a for a in anchors_for(source) if a.english.lower().replace("_", " ") not in normalized]
    return {"missing_anchors": [{"source": a.source, "expected": a.english, "type": a.kind} for a in missing],
            "requires_review": bool(missing or _CJK.search(translated)),
            "note": "检查领域锚点，不代表已验证全部语义；请核对人物、动作关系和风格。"}
