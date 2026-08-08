from anima_prompt_studio.domain.models import (
    EnhancementItem, ExcludedConcept, LoRASelection, MatchedTag, PromptJob, SubjectMode,
)
from anima_prompt_studio.tools.semantic_audit import evaluate


def test_audit_accepts_required_expression_from_enabled_enhancement():
    job = PromptJob(translated_en="A girl sits.", enhancements=[
        EnhancementItem(id="pose", type="动作", source_rule="pose", content="She is hugging her knees.")
    ])
    assert evaluate({"require_en_any": [["hugging her knees"]]}, job) == []


def test_audit_rejects_forbidden_positive_tag():
    job = PromptJob(translated_en="A girl without a hat.", matched_tags=[MatchedTag(tag="hat")])
    assert evaluate({"forbid_tags": ["hat"]}, job) == ["出现禁止标签：hat"]


def test_audit_checks_people_artist_and_composition_contracts():
    job = PromptJob()
    job.composition.people_count = 2
    job.composition.angle = "背面"
    job.artist_selection = ["@rurudo"]
    assert evaluate({
        "expect_people_count": 2,
        "expect_artists": ["@rurudo"],
        "expect_composition": {"angle": "背面"},
    }, job) == []


def test_audit_checks_structured_semantic_outputs():
    job = PromptJob(canonical_prose="A night scene.", negative_prompt="hat")
    job.semantic_frame.subject_mode = SubjectMode.SCENE
    job.semantic_frame.excluded_concepts = [ExcludedConcept(concept_id="hat", canonical_tag="hat")]
    job.lora_selection = [LoRASelection(logical_id="style", file_name="style.safetensors", weight=.8)]
    assert evaluate({
        "require_negative": ["hat"],
        "require_excluded_concepts": ["hat"],
        "expect_subject_mode": "scene",
        "expect_loras": [{"logical_id": "style", "file_name": "style.safetensors", "weight": .8}],
    }, job) == []
