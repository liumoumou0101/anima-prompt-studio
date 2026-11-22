"""Versioned writing guidance, separate from sampling and scene requirements."""
from .profiles import ModelProfileRegistry, ModelVariant


PROMPT_GUIDANCE_VERSION = "anima-scene-guidance/3"
# Official card checked 2026-09-26. Variant advice is not inferred from filenames.
PROMPT_GUIDANCE_SOURCE = (
    "https://huggingface.co/circlestone-labs/Anima/blob/"
    "f973fc41ec7545364ac9776c2440285f43ff2a30/README.md"
)

REWRITE_GOALS = {
    "faithful": (
        "根据现有要求、已审核提示词和本次修改，完整翻译并整理英文正负向提示词；"
        "保留全部明确事实及兼容的已审核内容，不附回中文原文，不自行补充画面设计。"
    ),
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
For Anima, positive and negative must be entirely in English. Chinese scene
descriptions are source meaning to translate, not text to copy into the prompts.
Do not append the Chinese source text or parenthesized translations after English
phrases. Translate existing Chinese prompt descriptions too; keep their compatible
facts rather than their Chinese wording. layer_updates and warnings may remain in Chinese.
Anima accepts tags, natural language, and a mixture. Use concise tags for stable
concepts such as count, hair and clothing; use coherent English sentences when
needed to connect actions, ownership, light sources and spatial relationships.
Do not flatten a meaningful relationship into disconnected adjectives. Prefer
specific visible descriptions over repeated quality words. Do not pad to a fixed
length or repeat every fact once as tags and again as prose. For newly written
Danbooru tags use lowercase and spaces, except score_*; preserve supplied names,
manual tags, trigger words and literal locks as required above. If a required
literal conflicts with English-only prompts, report the conflict; do not silently
translate, omit or alter the protected text.
model_guidance describes the selected image model, not additional scene facts.
Its optional_positive_prefix is configuration advice, never an instruction to
append tags. Use quality tags only when requested; avoid adding terms listed in
avoid_adding to either prompt. Preserve compatible reviewed facts and locked
wording; briefly flag any actual incompatibility.
Preserve reviewed negatives and explicit exclusions even when the selected model's
default negative mode is disabled; mention the limitation instead of erasing intent.
Do not change generation settings, models or LoRAs.
"""

FAITHFUL_RULES = """
FAITHFUL: Translate every explicit fact into complete English positive and negative
prompts, including older Chinese requirement and prompt descriptions. This is
semantic preservation and complete translation, not verbatim copying of Chinese.
Keep compatible reviewed facts, counts, attribute ownership, relationships and local exclusions.
Do not leave Chinese source clauses in the prompts, including parenthetical echoes
after an English translation. Keep layer_updates in the user's language and use
warnings for review notes, not as part of either prompt.
Use natural language where needed to preserve who does what to whom, but do not
invent lighting, pose, gaze, composition, texture, expression or style to make
the picture prettier. Missing creative choices remain unspecified. Do not run
the expansion process.
"""

EDIT_EXISTING_RULES = """
EDIT_EXISTING: revise the current reviewed picture within the latest delta's scope.
This is an edit operation, not a general expansion pass. Apply each requested
change AND its necessary consequences wherever the old fact occurs, including
other unlocked layers, both prompt fields and descriptions of related objects.
A narrow edit protects unrelated choices; it does not preserve a detail that
the edit has made impossible. Day-to-dusk retires explicit midday sunlight or
noon shadows even in background prose. Soft light and an airy atmosphere can
remain at dusk; dusk alone does not require darkness or a different mood.
A full-body edit replaces incompatible cropping even where only the face was
previously described. Keep the face and its features. Check ownership, spatial
relationships, local/global exclusions and framing in the same way. Update
affected unlocked prose in the same result, preserving its compatible facts.
Retire the old relationship that the edit REPLACES: when she sits ON the existing
bench, that same bench is no longer BESIDE her; a prop moved from a bag to her hand
must not still be inside that bag. Preserve unrelated image-left/right positions.
Keep an explicitly requested local ABSENCE explicit in the final positive or
scoped negative. 'No hats on the left woman' cannot become merely 'no red hat on
the left woman' or omission of the hat mention. Removing a red hat alone does not
imply a ban on all hats; a later explicit 'still bareheaded' DOES require no hat.
Do not add unrequested lighting, weather, expressions, hair length, hand poses,
props, scenery or material/color details. Don't add details merely because the
selected mode is expand. 'Other content unchanged' closes all unrelated choices.
If a prompt field is explicitly unchanged, copy it EXACTLY, including whitespace.
Faithful makes all necessary dependent edits without inventing other design
choices. Expand also develops the affected visual relationships (e.g. where
the new light falls on existing objects). If the user explicitly opens the
whole scene, its wider design may be developed. Never require an unrelated
addition to prove expansion.
Use complete English prompts; requirement prose and warnings may stay Chinese.
The final requirement ledger describes reviewed facts and the actual requested
edit, not newly invented details. Explain a genuine fixed-control conflict rather
than returning mutually contradictory text. Return the existing TurnOutput schema.
If the user names a prompt field, keep each edit in that field. In "negative:
remove fog, keep lettering, and add motion blur", all three operations target
negative; motion blur is unwanted, not a new visible action. The other field
must remain exact when protected. exact_fields lists those literal strings.
"""

BOLD_REWRITE_RULES = """
BOLD_REWRITE: Create one visibly distinct alternative treatment of the existing
scene for the user to compare. This one-time action opens visual design even
with an empty delta, independently of the saved faithful/expand mode. Use the
creative_brief as the source scene. Retain its explicit facts, subjects, count,
actions, relationships, style, exclusions and any specified framing. Respect
the latest delta when it replaces a fact, including all dependent descriptions.
A narrower instruction such as "only change the lighting" limits this action too.
For open choices, intentionally reorganize camera, staging, visual hierarchy,
light relationships or background treatment where this strengthens the same
scene. Develop a coherent new reading rather than reordering the same words.
If an earlier design is specifically opened for revision, it can be replaced;
never guess that an explicitly written fact is disposable. User-selected shot,
controls, character/artist tags, artist preset, locks and trigger words remain
binding. Integrate a fixed literal in its natural occurrence; do not append a
second copy just to demonstrate compliance. Keep repetitions explicitly required
by the source. Preserve the negative prompt exactly unless the user's edit changes it
or an English translation is required. If no meaningful variation is possible,
keep the prompt and briefly explain why in warnings.
Put new aesthetic decisions in the positive prompt; summarize the actual changes
briefly in Chinese warnings. Keep layer_updates for user facts or aligning stale
unlocked prose with the reviewed source plus the delta. An empty delta may still
require that alignment. Never persist a newly imagined camera, pose, atmosphere
or background as a user requirement merely because it appears in this proposal.
"""

BOLD_REQUIREMENTS_SYSTEM = """
Reconcile persistent requirements ONLY from the original reviewed prompt and
what the user explicitly specifies in delta. You are reading the sources before
the creative redesign. Do not design an image. Authorizing you to choose a camera
or colors specifies neither a low angle nor any particular light/color. For an
open design request, keep those source requirements unchanged unless the user
explicitly releases a prior incompatible choice. When given a concrete change
(e.g. "set the time to dusk"), align the affected unlocked fields and preserve
their other compatible facts. An EMPTY field stays empty unless the latest
delta gives a concrete new value. Do not populate it by copying the old reviewed
camera or light, or by recording the instruction to redesign them as a fact.
Keep selected controls, tags, artists and locks untouched.
Return JSON {"layer_updates":{},"evidence":{}}; omit unchanged fields. For EVERY
updated field, evidence[layer][field] must be a verbatim quote from delta or the
original reviewed positive/negative that actually supports the new fact.
For a previously empty field quote the specific new fact from delta. Use its
shortest literal concrete phrase, in the user's language.
Example: for "把时间改成傍晚", layer_updates={"lighting":{"text":"傍晚"}} and
evidence={"lighting":{"text":"把时间改成傍晚"}}. No new factual value means both
objects are empty. Do not use permission to choose as evidence for a choice.
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
An explicit 'everything else unchanged' closes all other dimensions to expansion.
An explicit unchanged positive/negative prompt stays byte-for-byte unchanged.
Do not disguise a scope violation as 'the main subject is unchanged'.

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
layer_updates={} even when positive gains useful detail.
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
