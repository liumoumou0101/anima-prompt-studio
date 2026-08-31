from anima_prompt_studio.domain.models import CharacterCard, CharacterSlot, PromptJob
from anima_prompt_studio.repositories.tag_database import TagDatabase
from anima_prompt_studio.services.character_resolution import CharacterRecognitionService, CharacterResolver
from anima_prompt_studio.services.pipeline import PromptPipeline

from test_tag_database import make_database


def keqing_card() -> CharacterCard:
    return CharacterCard(
        id="keqing",
        display_name="刻晴",
        aliases=["玉衡星", "Keqing"],
        entity_type="known_character",
        gender_tag="1girl",
        anima_character_tag="keqing_(genshin_impact)",
        copyright_tag="genshin_impact",
    )


def test_saved_chinese_alias_resolves_offline_and_replaces_name_in_translation():
    resolver = CharacterResolver()
    resolved = resolver.resolve("原神中的刻晴站在港口", [keqing_card()])
    assert len(resolved) == 1
    assert resolved[0].source_text == "刻晴"
    assert resolved[0].character_tag == "keqing_(genshin_impact)"
    assert resolver.replace_source_names("刻晴 is standing.", resolved) == "Keqing is standing."


def test_pipeline_emits_offline_character_and_series_tags_in_official_order():
    job = PromptJob(original_zh="刻晴站在璃月港")
    PromptPipeline().translate(job, character_cards=[keqing_card()])
    prompt = job.positive_prompt
    assert "1girl" in prompt
    assert "keqing (genshin impact)" in prompt
    assert "genshin impact" in prompt
    assert prompt.index("1girl") < prompt.index("keqing (genshin impact)") < prompt.index("genshin impact")
    assert "刻晴" not in job.translated_en


def test_selected_character_card_is_injected_during_recompile_without_retranslation():
    pipeline = PromptPipeline()
    pipeline.set_character_cards([keqing_card()])
    job = PromptJob(
        original_zh="一个女孩站在港口",
        translated_en="A girl stands at a harbor.",
        character_slots=[CharacterSlot(character_id="keqing", display_name="刻晴", gender_tag="1girl")],
    )
    pipeline.compile_current_state(job)
    assert "keqing (genshin impact)" in job.positive_prompt
    assert "genshin impact" in job.positive_prompt


class FakeAIClient:
    def complete_json(self, system: str, user: str):
        return {
            "characters": [{
                "source_text": "刻晴",
                "name_en": "Keqing",
                "series_en": "Genshin Impact",
                "gender": "girl",
            }]
        }


def test_ai_name_is_only_returned_with_locally_validated_tag_candidates(tmp_path):
    path = tmp_path / "tags.db"
    make_database(path)
    suggestions = CharacterRecognitionService(TagDatabase(path)).recognize("刻晴在微笑", FakeAIClient())
    assert len(suggestions) == 1
    assert suggestions[0].character_candidates[0].canonical_name == "keqing_(genshin_impact)"
    assert suggestions[0].copyright_candidates[0].canonical_name == "genshin_impact"


class HallucinatingAIClient:
    def complete_json(self, system: str, user: str):
        return {"characters": [{"source_text": "不存在的名字", "name_en": "Keqing"}]}


def test_ai_mentions_not_copied_from_source_are_rejected(tmp_path):
    path = tmp_path / "tags.db"
    make_database(path)
    suggestions = CharacterRecognitionService(TagDatabase(path)).recognize("一个女孩在微笑", HallucinatingAIClient())
    assert suggestions == []
