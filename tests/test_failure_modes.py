from pathlib import Path

import pytest

from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio.repositories.tag_database import TagDatabase
from anima_prompt_studio.services.config_service import ConfigService
from anima_prompt_studio.services.pipeline import PromptPipeline
from anima_prompt_studio.services.prompt_compiler import PromptCompiler
from anima_prompt_studio.services.translation_service import TranslationService


class BrokenEngine:
    name = "broken"
    def zh_to_en(self, text): raise OSError("model unavailable")
    def en_to_zh(self, text): raise OSError("model unavailable")


def test_missing_tag_database_degrades_to_curated_tags(tmp_path):
    pipeline = PromptPipeline()
    pipeline.matcher.database = TagDatabase(tmp_path / "missing.db")
    job = PromptJob(original_zh="白发女孩")
    pipeline.compiler.apply_model_defaults(job); pipeline.translate(job)
    assert "white hair" in {x.tag for x in job.matched_tags}


def test_translation_failure_becomes_user_readable_error():
    service = TranslationService(BrokenEngine())
    with pytest.raises(RuntimeError, match="中译英失败"):
        service.zh_to_en("测试")


def test_missing_config_directory_loads_defaults(tmp_path):
    service = ConfigService(tmp_path / "missing-config")
    assert service.model_profiles


def test_unimplemented_model_family_cannot_silently_use_anima_compiler():
    configs = ConfigService()
    configs.model_profiles["pony_future"] = configs.get_model("anima_base_v1").model_copy(
        update={"id": "pony_future", "display_name": "Pony（预留）", "family": "pony"}
    )
    with pytest.raises(NotImplementedError, match="不会套用 ANIMA 规则"):
        PromptCompiler(configs).compile(PromptJob(model_profile_id="pony_future"))
