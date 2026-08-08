import pytest

from anima_prompt_studio.domain.models import MatchedTag, PromptJob
from anima_prompt_studio.services.composition_context import CompositionContextExtractor
from anima_prompt_studio.services.config_service import ConfigService
from anima_prompt_studio.services.pipeline import PromptPipeline
from anima_prompt_studio.services.prompt_compiler import PromptCompiler
from anima_prompt_studio.services.tag_matcher import TagMatcher
from anima_prompt_studio.services.translation_service import TranslationService


MUSHROOM = "一个暗精灵小女孩蹲在森林里采蘑菇，低头仔细寻找草丛中的蘑菇"
ANGEL = "一名天使从云层中缓缓降落，巨大的白色羽翼完全展开，身体悬浮在空中"
RUNNING = "一个女孩向画面右侧快速奔跑，身体微微前倾，长发和围巾在身后飘扬"


class KnownBadEngine:
    name = "known-bad"
    outputs = {
        MUSHROOM: "A little dark elf girl sits in the woods and picks mushrooms and looks down for mushrooms in the grass.",
        ANGEL: "An angel fell slowly from the clouds, and the giant white wing was fully spread and the body was suspended in the air.",
        RUNNING: "A girl running fast on the right side of the picture, leaning slightly forward, long hairs and scarfs running behind her back.",
    }
    def zh_to_en(self, text):
        if "暗精灵" in text: return self.outputs[MUSHROOM]
        if "天使" in text: return self.outputs[ANGEL]
        if "奔跑" in text: return self.outputs[RUNNING]
        return text
    def en_to_zh(self, text): return text


def build(text):
    pipeline = PromptPipeline(translation=TranslationService(KnownBadEngine()))
    job = PromptJob(original_zh=text)
    pipeline.compiler.apply_model_defaults(job); pipeline.translate(job)
    return job


def test_crouching_mushroom_sentence_is_canonicalized():
    job = build(MUSHROOM)
    prose = job.positive_prompt.partition("\n\n")[2].lower()
    tags = set(job.positive_prompt.partition("\n\n")[0].split(", "))
    assert "dark dark elf" not in prose
    assert "crouches" in prose and "sits" not in prose
    assert prose.count("mushrooms") == 1
    assert "crouching" in tags and "sitting" not in tags


def test_descending_angel_sentence_and_tags_are_canonicalized():
    job = build(ANGEL)
    prose = job.positive_prompt.partition("\n\n")[2].lower()
    tags = set(job.positive_prompt.partition("\n\n")[0].split(", "))
    assert "slowly descends" in prose
    assert "white wings fully spread" in prose and "floating in midair" in prose
    assert not {"giant", "suspension", "looking at viewer"} & tags
    assert {"white wings", "floating", "full body", "from below"} <= tags


def test_directional_running_separates_motion_from_position():
    job = build(RUNNING)
    c, context = job.composition, job.composition_context
    assert context.movement_direction == "right" and context.explicit_subject_position == "none"
    assert (c.subject_position, c.angle, c.gaze, c.aspect) == ("左", "侧面", "看向画外", "横图")
    tags = job.positive_prompt.partition("\n\n")[0].split(", ")
    assert "photo (object)" not in tags and "back" not in tags and "looking at viewer" not in tags
    assert sum(PromptCompiler._exclusive_group(tag) == "angle" for tag in tags) == 1
    prose = job.positive_prompt.partition("\n\n")[2].lower()
    assert "runs quickly toward the right" in prose
    assert "long hairs" not in prose and "scarfs" not in prose and "behind her back" not in prose


@pytest.mark.parametrize("text,movement,position", [
    ("女孩向画面右侧奔跑", "right", "none"),
    ("女孩向画面左侧快速移动", "left", "none"),
    ("女孩往画面右边跑去", "right", "none"),
    ("女孩朝画面左边冲去", "left", "none"),
    ("女孩站在画面右侧", "none", "right"),
    ("女孩坐在画面左侧", "none", "left"),
    ("画面左侧站着一个女孩", "none", "left"),
    ("画面右边坐着一个女孩", "none", "right"),
])
def test_movement_and_subject_position_are_distinct(text, movement, position):
    job = PromptJob(original_zh=text, normalized_zh=text)
    context = CompositionContextExtractor().extract(job)
    assert context.movement_direction == movement
    assert context.explicit_subject_position == position


def test_flowing_behind_is_relation_but_from_behind_is_angle():
    extractor = CompositionContextExtractor()
    relation = extractor.extract(PromptJob(original_zh="围巾在她身后飘扬", normalized_zh="围巾在她身后飘扬"))
    angle = PromptJob(original_zh="从背后拍摄她", normalized_zh="从背后拍摄她")
    assert relation.motion_relation_spans
    pipeline = PromptPipeline(translation=TranslationService(KnownBadEngine()))
    pipeline.recommend_composition(angle)
    assert angle.composition.angle == "背面"


def test_possessive_flowing_behind_is_also_a_motion_relation():
    text = "她的长发在她身后飘扬"
    context = CompositionContextExtractor().extract(
        PromptJob(original_zh=text, normalized_zh=text)
    )
    assert context.motion_relation_spans


@pytest.mark.parametrize("text", [
    "女孩纵身跳过水沟",
    "少女从高台跃下",
    "人物在空中高速飞行",
])
def test_generic_dynamic_action_does_not_default_to_viewer_gaze(text):
    job = PromptJob(original_zh=text, normalized_zh=text)
    PromptPipeline(translation=TranslationService(KnownBadEngine())).recommend_composition(job)
    assert job.composition_context.dynamic_action
    assert job.composition.gaze == "看向画外"


def test_compiler_keeps_only_selected_main_angle():
    compiler = PromptCompiler(ConfigService())
    job = PromptJob(translated_en="A running girl.", matched_tags=[
        MatchedTag(tag="from side"), MatchedTag(tag="back"), MatchedTag(tag="front view")
    ])
    job.composition.angle = "三分之四"
    compiler.apply_model_defaults(job); compiler.compile(job)
    tags = job.positive_prompt.partition("\n\n")[0].split(", ")
    angles = [tag for tag in tags if compiler._exclusive_group(tag) == "angle"]
    assert angles == ["three-quarter view"]


class PollutingDatabase:
    available = True
    def match_english(self, _text):
        return [
            {"name":"picture","output_name":"photo (object)","category":0,"post_count":100},
            {"name":"side","output_name":"from side","category":0,"post_count":100},
            {"name":"back","output_name":"back","category":0,"post_count":100},
        ]


def test_composition_meta_and_motion_relation_filter_external_tags():
    matcher = TagMatcher(); matcher.database = PollutingDatabase()
    source = "女孩向画面右侧奔跑，围巾在她身后飘扬"
    job = PromptJob(original_zh=source, normalized_zh=source)
    context = CompositionContextExtractor().extract(job)
    result = matcher.match("A girl runs on the right side of the picture, her scarf flowing behind her back.", source, context=context)
    assert not {"photo (object)", "from side", "back"} & {item.tag for item in result}


def test_real_photo_is_not_globally_banned():
    matcher = TagMatcher(); matcher.database = PollutingDatabase()
    source = "女孩手里拿着一张照片"
    job = PromptJob(original_zh=source, normalized_zh=source)
    result = matcher.match("A girl holds a picture.", source, context=CompositionContextExtractor().extract(job))
    assert "photo (object)" in {item.tag for item in result}
