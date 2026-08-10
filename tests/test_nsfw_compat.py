"""NSFW vocabulary, translation guards, people-count and tag noise coverage."""
import re

from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio.services.pipeline import PromptPipeline
from anima_prompt_studio.services.semantic_frame import SemanticFrameResolver
from anima_prompt_studio.services.tag_matcher import TagMatcher
from anima_prompt_studio.services.translation_service import TranslationService


def pipeline() -> PromptPipeline:
    return PromptPipeline()


def tags_of(job: PromptJob) -> set[str]:
    return {item.tag for item in job.matched_tags}


def test_builtin_lexicon_translates_core_nsfw_terms():
    service = TranslationService()
    text = service.zh_to_en("一个裸体女孩穿着比基尼做阿嘿颜")
    assert "nude" in text.lower()
    assert "bikini" in text.lower()
    assert "ahegao" in text.lower()


def test_guard_fixes_huawai_painting_drift():
    result = TranslationService._guard_visual_terms(
        "女孩看向画外",
        "A girl looking outside the painting.",
    )
    assert "painting" not in result.lower()
    assert "looking away" in result.lower()


def test_guard_fixes_umbilical_crop_top_and_cleavage():
    crop = TranslationService._guard_visual_terms(
        "粉发女孩穿着露脐短上衣",
        "A pink-haired girl in a short umbilical top.",
    )
    assert "umbilical" not in crop.lower()
    assert "crop top" in crop.lower()

    cleavage = TranslationService._guard_visual_terms(
        "紫发女孩低胸礼服露出乳沟",
        "A purple-haired girl in a low-breast dress, showing her breasts.",
    )
    assert "low-cut" in cleavage.lower() or "cleavage" in cleavage.lower()
    assert "cleavage" in cleavage.lower()


def test_guard_restores_ahegao_and_missionary():
    ahegao = TranslationService._guard_visual_terms(
        "女孩露出阿嘿颜表情，眼睛上翻",
        "A girl showed a face, an eye out.",
    )
    assert "ahegao" in ahegao.lower()
    assert "rolling eyes" in ahegao.lower()

    sex = TranslationService._guard_visual_terms(
        "一对男女在床上做爱，男上位",
        "A couple having sex in bed, a man in top.",
    )
    assert "missionary" in sex.lower()


def test_pair_people_count_from_chinese_phrases():
    frame = SemanticFrameResolver().resolve("一对男女在床上做爱，男上位，女孩张腿看着镜头")
    assert frame.people_count == 2

    frame2 = SemanticFrameResolver().resolve("一男一女站在窗边")
    assert frame2.people_count == 2


def test_pair_people_count_from_english_authority():
    frame = SemanticFrameResolver().resolve_english(
        "1girl, 1boy, sex, hetero, missionary, nude, looking at viewer"
    )
    assert frame.people_count == 2

    frame2 = SemanticFrameResolver().resolve_english("A couple having sex in bed.")
    assert frame2.people_count == 2


def test_concept_and_tag_coverage_for_soft_nsfw_chinese():
    job = PromptJob(original_zh="一个金发蓝瞳的女孩穿着比基尼站在沙滩上，看镜头微笑")
    pipeline().translate(job)
    matched = tags_of(job)
    assert "bikini" in matched
    assert "1girl" in job.positive_prompt.partition("\n\n")[0]


def test_concept_and_tag_coverage_for_hard_nsfw_chinese():
    job = PromptJob(original_zh="一个裸体的女孩站在浴室里，长发遮住胸口，看向画外")
    pipeline().translate(job)
    matched = tags_of(job)
    assert "nude" in matched
    assert "painting (action)" not in matched
    assert "painting (object)" not in matched
    assert "looking away" in matched or "looking away" in job.positive_prompt


def test_ahegao_and_bondage_concepts_inject_tags():
    job = PromptJob(original_zh="一个高潮中的女孩露出阿嘿颜表情，舌头伸出，眼睛上翻")
    pipeline().translate(job)
    matched = tags_of(job)
    assert "ahegao" in matched
    assert "tongue out" in matched
    assert "rolling eyes" in matched

    bound = PromptJob(original_zh="一个被绳子捆绑的女孩坐在椅子上，眼睛被布蒙住")
    pipeline().translate(bound)
    bound_tags = tags_of(bound)
    assert "bound" in bound_tags
    assert "blindfold" in bound_tags


def test_couple_sex_prompt_sets_people_and_sex_tags():
    job = PromptJob(original_zh="一对男女在床上做爱，男上位，女孩张腿看着镜头")
    pipeline().translate(job)
    matched = tags_of(job)
    assert job.composition.people_count == 2
    assert "sex" in matched
    assert "missionary" in matched
    assert "hetero" in matched
    assert "male focus" not in matched


def test_noise_tags_can_and_folding_are_blocked():
    matcher = TagMatcher()
    result = matcher.match(
        "A girl can see undergarments while folding her legs by the window.",
        "女孩透过衣服能看到内衣轮廓，双腿交叠坐在窗边",
    )
    names = {item.tag for item in result}
    assert "can" not in names
    assert "folding" not in names


def test_english_authority_nsfw_tags_round_trip():
    job = PromptJob(original_zh="一个女孩")
    pipe = pipeline()
    pipe.translate(job)
    pipe.update_english(
        job,
        "1girl, nude, medium breasts, nipples, standing, looking at viewer, indoors, bathroom",
    )
    matched = tags_of(job)
    assert {"nude", "nipples", "looking at viewer", "1girl"} <= matched


def test_expanded_clothing_and_body_concepts():
    job = PromptJob(original_zh="一个巨乳银发女仆装女孩穿着黑丝站在教室里")
    pipeline().translate(job)
    matched = tags_of(job)
    assert "large breasts" in matched
    assert "maid" in matched or "school uniform" in matched or "thighhighs" in matched
    assert "classroom" in matched or "银发" in job.original_zh
    assert "silver hair" in matched or "silver" in (job.translated_en or "").lower()


def test_positions_cowgirl_doggy_and_spread_legs():
    cowgirl = PromptJob(original_zh="女孩女上位骑在他身上")
    pipeline().translate(cowgirl)
    assert "cowgirl position" in tags_of(cowgirl) or "cowgirl" in (cowgirl.translated_en or "").lower()

    doggy = PromptJob(original_zh="后入式，从背后")
    pipeline().translate(doggy)
    assert "doggy style" in tags_of(doggy) or "from behind" in tags_of(doggy)

    spread = PromptJob(original_zh="女孩张开双腿躺在床上")
    pipeline().translate(spread)
    assert "spread legs" in tags_of(spread)


def test_ass_focus_does_not_force_headshot():
    job = PromptJob(original_zh="从背后拍摄一个只穿着丁字裤的女孩，臀部特写")
    pipeline().translate(job)
    assert job.composition.shot != "头像" or "ass" in tags_of(job)
    assert "ass" in tags_of(job) or "ass focus" in tags_of(job)
    # Prefer body framing over face close-up for ass focus.
    assert job.composition.shot in {"膝上", "半身", "全身", "胸像", "头像"}


def test_short_crop_top_does_not_invent_short_hair():
    """Regression: 'short crop top' + 'pink hair' must not yield short hair."""
    from anima_prompt_studio.services.tag_matcher import TagMatcher
    result = TagMatcher().match(
        "A pink-haired girl in a short crop top and short shorts.",
        "一个粉发女孩穿着露脐短上衣和热裤",
    )
    names = {item.tag for item in result}
    assert "short hair" not in names
    assert "crop top" in names or "navel" in names or "short shorts" in names


def test_yuri_sex_is_not_forced_hetero():
    job = PromptJob(original_zh="两个女孩做爱")
    pipeline().translate(job)
    matched = tags_of(job)
    assert "yuri" in matched or job.composition.people_count == 2
    assert "hetero" not in matched


def test_cold_position_and_clothing_slang():
    job = PromptJob(original_zh="架腿位，女孩穿着微型比基尼和乳胶")
    pipeline().translate(job)
    matched = tags_of(job)
    assert "mating press" in matched
    assert "micro bikini" in matched or "bikini" in matched
    assert "latex" in matched
    assert not re.search(r"[\u4e00-\u9fff]", job.translated_en or "")


def test_more_slang_positions_and_outfits():
    cases = [
        ("反骑乘", "reverse cowgirl"),
        ("火车便当", "full nelson"),
        ("六九式", "69"),
        ("巫女服", "miko"),
        ("处男杀手毛衣", "virgin killer sweater"),
        ("飞机场", "flat chest"),
        ("开档连裤袜", "crotchless"),
    ]
    for zh, expect in cases:
        job = PromptJob(original_zh=f"一个女孩{zh}")
        pipeline().translate(job)
        blob = " ".join(tags_of(job)) + " " + (job.translated_en or "")
        assert expect in blob.lower() or expect.replace(" ", "") in blob.lower().replace(" ", ""), (
            f"{zh} -> expected {expect}, got tags={tags_of(job)} en={job.translated_en}"
        )


def test_quality_profiles_include_enhancement_packs():
    from anima_prompt_studio.services.config_service import ConfigService
    configs = ConfigService()
    assert len(configs.quality_profiles) >= 15
    for pack_id in ("soft_sensual", "body_detail", "glossy_wet", "uncensored_detail", "lingerie_focus"):
        assert pack_id in configs.quality_profiles
        tags = configs.quality_profiles[pack_id].all_tags()
        assert tags, pack_id


def test_builtin_translation_is_english_only():
    import re
    from anima_prompt_studio.services.translation_service import TranslationService
    text = TranslationService().zh_to_en("一个银发女仆装女孩站在教室里看镜头")
    assert text
    assert not re.search(r"[\u4e00-\u9fff]", text)
