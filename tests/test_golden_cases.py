import json
from pathlib import Path

import pytest

from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio.services.pipeline import PromptPipeline


CASES = json.loads((Path(__file__).parent / "golden_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_golden_case(case):
    pipeline = PromptPipeline()
    job = PromptJob(original_zh=case["input"])
    pipeline.compiler.apply_model_defaults(job)
    pipeline.translate(job)
    actual_tags = {tag.tag for tag in job.matched_tags}
    assert set(case.get("tags", [])) <= actual_tags
    actual_enhancements = {item.id for item in job.enhancements}
    assert set(case.get("enhancements", [])) <= actual_enhancements
