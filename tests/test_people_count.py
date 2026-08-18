"""People-count and solo tags for pair scenes, yuri, and implied partners."""
from __future__ import annotations

from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio.services.pipeline import PromptPipeline
from anima_prompt_studio.services.semantic_frame import SemanticFrameResolver


def _pipeline(source: str) -> PromptJob:
    job = PromptJob(original_zh=source)
    PromptPipeline().translate(job)
    return job


def _head_tags(job: PromptJob) -> set[str]:
    return set(job.positive_prompt.partition("\n\n")[0].split(", "))


def test_modified_two_girls_counts_as_two_not_solo():
    frame = SemanticFrameResolver().resolve("两个裸体女孩在做爱，没有男孩，全身")
    assert frame.people_count == 2
    assert frame.final_attributes.get("people_mix") == "female"

    job = _pipeline("两个裸体女孩在做爱，没有男孩，全身")
    tags = _head_tags(job)
    assert job.composition.people_count == 2
    assert "2girls" in tags
    assert "solo" not in tags
    assert "1other" not in tags
    assert "1boy" not in tags
    assert "yuri" in tags or "sex" in tags


def test_cowgirl_with_boy_is_hetero_pair_not_solo():
    job = _pipeline("一个裸体女孩女上位骑在男孩身上，全身")
    tags = _head_tags(job)
    assert job.composition.people_count == 2
    assert {"1girl", "1boy"} <= tags
    assert "2girls" not in tags
    assert "solo" not in tags
    assert "1other" not in tags


def test_missionary_couple_is_one_girl_one_boy_not_three_people():
    job = _pipeline("一对男女在床上做爱，男上位，女孩张开双腿看着镜头，全身")
    tags = _head_tags(job)
    assert job.composition.people_count == 2
    assert {"1girl", "1boy"} <= tags
    assert "2girls" not in tags
    assert "solo" not in tags
    assert "hetero" in tags


def test_reverse_cowgirl_with_him_is_pair():
    job = _pipeline("一个裸体女孩反骑乘，背对男孩坐在他身上，全身")
    tags = _head_tags(job)
    assert job.composition.people_count == 2
    assert {"1girl", "1boy"} <= tags
    assert "solo" not in tags
    assert "reverse cowgirl" in tags
    assert "cowgirl position" not in tags
    assert "cowgirl" not in tags
    assert "facing away" not in tags
    assert "back to the boy" in (job.translated_en or "").lower()


def test_doggy_names_both_genders():
    job = _pipeline("后入式，男孩从背后进入裸体女孩，全身")
    tags = _head_tags(job)
    assert job.composition.people_count == 2
    assert {"1girl", "1boy"} <= tags
    assert "solo" not in tags


def test_oral_implies_partner_unless_solo():
    job = _pipeline("一个裸体女孩跪着做口交，抬头看镜头，嘴巴微张，全身")
    tags = _head_tags(job)
    assert job.composition.people_count == 2
    assert {"1girl", "1boy"} <= tags
    assert "solo" not in tags

    solo = _pipeline("一个裸体女孩独自躺在床上张开双腿，没有和其他人做爱，全身")
    solo_tags = _head_tags(solo)
    assert solo.composition.people_count == 1
    assert "solo" in solo_tags
    assert "1girl" in solo_tags
    assert "1boy" not in solo_tags


def test_two_modified_girls_translation_guard_keeps_plural():
    result = PromptPipeline().translation._guard_visual_terms(
        "两个裸体女孩在做爱，没有男孩",
        "Girls are having sex.",
    )
    assert not result.startswith("A girl")


def test_single_girl_still_gets_solo():
    job = _pipeline("一个女孩站在房间里")
    tags = _head_tags(job)
    assert job.composition.people_count == 1
    assert "1girl" in tags
    assert "solo" in tags
    assert "1boy" not in tags


def test_two_girls_and_one_boy_is_not_just_2girls():
    job = _pipeline("两个女孩和一个男孩站在一起")
    tags = _head_tags(job)
    assert job.composition.people_count == 3
    assert job.semantic_frame.final_attributes.get("people_mix") == "2f1m"
    assert {"2girls", "1boy"} <= tags
    assert "3people" not in tags
    assert "solo" not in tags


def test_two_boys_and_one_girl_split_tags():
    job = _pipeline("一个女孩和两个男孩在房间里")
    tags = _head_tags(job)
    assert job.composition.people_count == 3
    assert {"1girl", "2boys"} <= tags
    assert "3people" not in tags


def test_compact_two_female_one_male():
    job = _pipeline("两女一男在床上")
    tags = _head_tags(job)
    assert job.composition.people_count == 3
    assert {"2girls", "1boy"} <= tags


def test_yuri_oral_is_not_forced_hetero():
    job = _pipeline("一个女孩给另一个女孩口交")
    tags = _head_tags(job)
    assert job.composition.people_count == 2
    assert "2girls" in tags
    assert "1boy" not in tags
    assert "yuri" in tags or "fellatio" in tags or "oral" in tags

    slang = _pipeline("女女口交")
    slang_tags = _head_tags(slang)
    assert slang.composition.people_count == 2
    assert "2girls" in slang_tags
    assert "1boy" not in slang_tags


def test_named_pair_without_gender_words_is_two_people():
    job = _pipeline("艾莉丝和贝拉站在窗边")
    assert job.composition.people_count == 2
    tags = _head_tags(job)
    assert "solo" not in tags
    assert "1girl" not in tags
    assert "2people" in tags or "2girls" in tags
