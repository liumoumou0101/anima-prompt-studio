"""Versioned writing guidance, separate from sampling and scene requirements."""
from .profiles import ModelProfileRegistry, ModelVariant


PROMPT_GUIDANCE_VERSION = "anima-scene-guidance/2"
# Official card checked 2026-09-26. Variant advice is not inferred from filenames.
PROMPT_GUIDANCE_SOURCE = (
    "https://huggingface.co/circlestone-labs/Anima/blob/"
    "f973fc41ec7545364ac9776c2440285f43ff2a30/README.md"
)

REWRITE_GOALS = {
    "faithful": "根据现有要求、已审核提示词和本次修改，准确整理完整英文提示词；保留全部明确内容，不自行补充画面设计。",
    "expand": (
        "请根据现有要求和已审核提示词适度扩写画面：在保留全部明确约束的前提下，"
        "具体设计尚未指定且有助于画面的受光关系、姿态或环境细节，把有用的新增内容写进正向提示词。"
        "若本次修改限定只改某处，就只处理该处。不要仅重排或翻译原文；"
        "优先完善已有元素的关系，不额外添加人物、动物或道具。"
        "positive 和 negative 必须使用英文；warnings 用简短中文说明实际写入的全部新增内容，"
        "不把这些设计假装成用户原始要求。返回前逐项核对所有分层要求，"
        "主体、人数、景别、画风、光影和排除项都不能因扩写而遗漏；锁定层不补新的属性。"
    ),
}

PROMPT_EXPRESSION_RULES = """
Anima accepts tags, natural language, and a mixture. Use concise tags for stable
concepts such as count, hair and clothing; use coherent English sentences when
needed to connect actions, ownership, light sources and spatial relationships.
Do not flatten a meaningful relationship into disconnected adjectives. Prefer
specific visible descriptions over repeated quality words. Do not pad to a fixed
length or repeat every fact once as tags and again as prose. For newly written
Danbooru tags use lowercase and spaces, except score_*; preserve supplied names,
manual tags, trigger words and literal locks as required above.
model_guidance describes the selected image model, not additional scene facts.
Its optional_positive_prefix is configuration advice, never an instruction to
append tags. Use quality tags only when requested; avoid adding terms listed in
avoid_adding to either prompt. Do not delete reviewed or locked wording merely
to conform to guidance: preserve it and briefly flag any actual incompatibility.
Preserve reviewed negatives and explicit exclusions even when the selected model's
default negative mode is disabled; mention the limitation instead of erasing intent.
Do not change generation settings, models or LoRAs.
"""

FAITHFUL_RULES = """
FAITHFUL: translate and organize only explicit facts and compatible reviewed text.
Use natural language to preserve their relationships, but do not invent lighting,
pose, gaze, composition, texture, expression or style to make the picture prettier.
Missing creative choices remain unspecified. Do not run the expansion process.
"""

EXPANSION_RULES = """
EXPANSION: develop the picture, not just translate or reorder its words. The user
selected this mode to receive useful visual elaboration. When the scene leaves
room, choose a small set of specific, compatible additions and write them into
positive: for example, a light-to-surface relationship or a meaningful spatial or
material detail. A reordered list of the same tags is not an expanded result.
Even with empty delta, expand the saved requirements in this mode. Do not treat
empty delta as faithful mode; it prohibits layer_updates, not prompt elaboration.
This is not permission to replace explicit choices, reviewed details or locked layers.
Locks also constrain positive, not just layer_updates: do not add new pose, gaze,
material or appearance attributes to a locked subject. Unlocked lighting may still
illuminate that subject without changing those attributes.
Respect a narrow delta such as 'only change the light': do not use expansion mode
to redesign unrelated parts. Keep identities, counts, clothing, main actions,
ownership, time of day, mood, medium and style unless the user asks to change them.

Consider the scene as a whole, selecting only the dimensions that help this image:
- What should attract attention, and which parts should be visible? Framing,
  body orientation and gaze are distinct choices; full body does not mean front view.
- Where does the light originate, what does it illuminate, and how does it separate
  subject and environment while preserving the requested time and atmosphere?
- Which restrained pose, spatial or environmental detail makes the existing scene
  clearer? Preserve the main action and each person's attribute ownership.
- Which fabric, hair or surface detail fits the medium? Flat color, minimalist,
  silhouette and graphic styles do not require realistic texture or complex shading.
  If the user requests pure color blocks, keep discrete colors instead of adding
  gradients, glossy reflections or realistic surface texture. Preserve monochrome
  and other palette restrictions when describing light and atmosphere.

You may choose compatible pose, gaze, lighting or composition details where neither
user text, current reviewed prompt nor selected controls specifies them. Do not
force front view, eye contact, bright faces, dramatic lighting or dense detail onto
every subject. For a night portrait, light reaching the face or collar may help if
readability suits the intent; a requested backlit silhouette should retain its dark
face and outline. Do not turn night into day to make details visible. These are
reasoning examples, not phrases to copy into unrelated scenes.

When constraints leave no useful room for elaboration, preserve the scene and
briefly explain that in warnings instead of forcing details or changing its intent.
Keep additions modest and avoid inventing subjects, artists, media or quality-tag
boilerplate. Prefer relationships between existing elements over decorating the
scene with extra people, animals or props. Put creative additions in English
positive and explain each briefly in Chinese
warnings, grouped where useful. Warnings must describe additions actually present
in positive, not planned changes. Do not promote your own additions into persistent
user requirements or write read-only scene controls; layer_updates stores explicit
user requests only. Preserve compatible additions from reviewed text unless asked
to change them, but do not restore a choice the user has removed. With empty delta,
touched_layers=[] and layer_updates={} even when positive gains useful detail.
Before returning, check positive against EVERY populated requirement layer and
selected control, not just subject.text. Carry framing/shot size and medium/style
through to the final prompt along with counts, ownership, actions and light. Check
explicit exclusions and reviewed negative text too. Elaboration must not displace
any of these facts. Check each warning against what is actually written in positive.
"""


def model_prompt_guidance(profile_id: str, profiles: ModelProfileRegistry) -> dict:
    """Build contextual hints from the actual registered profile; unknown is generic."""
    try:
        profile = profiles.get(profile_id)
    except KeyError:
        return {
            "version": PROMPT_GUIDANCE_VERSION, "profile_id": profile_id,
            "variant": "unknown", "optional_positive_prefix": [], "avoid_adding": [],
            "notes": "No verified variant-specific advice. Use general scene-description principles only.",
        }
    notes = {
        ModelVariant.BASE: "Quality prefixes are optional; specific scene descriptions remain important.",
        ModelVariant.AESTHETIC: (
            "Quality prefixes can be omitted. masterpiece and best quality are optional; "
            "the author advises against score tags in both positive and negative prompts."
        ),
        ModelVariant.TURBO: (
            "Use the general Anima writing conventions. The author does not give Turbo "
            "a separate quality-tag rule; do not apply Aesthetic's score-tag restriction."
        ),
        ModelVariant.COMMUNITY: (
            "No verified variant-specific writing advice here. Use general scene-description "
            "principles and preserve the user's supplied style and trigger words."
        ),
    }
    return {
        "version": PROMPT_GUIDANCE_VERSION, "profile_id": profile.id,
        "display_name": profile.display_name, "variant": profile.variant.value,
        "optional_positive_prefix": list(profile.positive_prefix),
        "avoid_adding": ["score_*"] if profile.variant == ModelVariant.AESTHETIC else [],
        "negative_prompt_mode": profile.negative_prompt_mode.value,
        "notes": notes[profile.variant],
        "source": PROMPT_GUIDANCE_SOURCE if profile.variant != ModelVariant.COMMUNITY else None,
    }
