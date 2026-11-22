"""Literal prompt protection must not silently change unrelated scene content."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from anima_prompt_studio_v3.core.requirements import (
    PromptEdit, Requirements, RequirementsEdit, WorkbenchError,
    apply_workspace_edit, compile_prompt, compile_state, dump, inputs_fingerprint,
)


def draft_with_locks(locks):
    requirements = dump(Requirements.empty())
    requirements["layers"]["subject"]["text"] = "黑色短发人物，蓝外套"
    requirements["prompt_locks"] = locks
    return {"requirements": dump(Requirements.model_validate(requirements)), "mode": "faithful",
            "model_profile": "anima_base_v1"}


def test_locked_identity_survives_while_clothing_can_change():
    draft = draft_with_locks([{"target": "positive", "text": "short black hair"}])
    compiled = compile_prompt(draft, PromptEdit(positive="short black hair, red coat", negative=""), source="llm")
    assert compiled["positive"] == "short black hair, red coat"
    with pytest.raises(WorkbenchError, match="short black hair"):
        compile_prompt(draft, PromptEdit(positive="long blonde hair, red coat", negative=""), source="llm")


def test_negative_lock_cannot_be_satisfied_by_positive_text():
    draft = draft_with_locks([{"target": "negative", "text": "extra fingers"}])
    with pytest.raises(WorkbenchError):
        compile_prompt(draft, PromptEdit(positive="extra fingers", negative="blur"), source="llm")
    assert compile_prompt(draft, PromptEdit(positive="portrait", negative="blur, extra fingers"), source="llm")["negative"] == "blur, extra fingers"


def test_lock_only_save_keeps_prompt_fresh_and_token_unchanged():
    draft = draft_with_locks([])
    draft["compiled"] = compile_prompt(draft, PromptEdit(positive="short black hair, blue coat", negative=""), source="llm")
    edit = {"layers": deepcopy(draft["requirements"]["layers"]), "loras": [],
            "prompt_locks": [{"target": "positive", "text": "short black hair"}]}
    result = apply_workspace_edit(draft, {"model_profile": "anima_base_v1", "requirements_edit": edit})
    assert compile_state(result) == "fresh"
    assert result["compiled"]["compiled_token"] == draft["compiled"]["compiled_token"]
    assert inputs_fingerprint(result) == inputs_fingerprint(draft)
    assert result["requirements"]["prompt_locks"] == edit["prompt_locks"]


def test_cannot_save_protection_for_text_missing_from_current_prompt():
    draft = draft_with_locks([])
    draft["compiled"] = compile_prompt(draft, PromptEdit(positive="blue coat", negative=""), source="llm")
    edit = {"layers": draft["requirements"]["layers"], "loras": [],
            "prompt_locks": [{"target": "positive", "text": "red coat"}]}
    with pytest.raises(WorkbenchError):
        apply_workspace_edit(draft, {"requirements_edit": edit})


def test_user_can_unlock_and_edit_in_one_save_but_cannot_accidentally_break_lock():
    draft = draft_with_locks([{"target": "positive", "text": "short black hair"}])
    draft["compiled"] = compile_prompt(draft, PromptEdit(positive="short black hair, blue coat", negative=""), source="llm")
    with pytest.raises(WorkbenchError):
        apply_workspace_edit(draft, {"prompt_edit": {"positive": "blonde hair, blue coat", "negative": ""}})
    result = apply_workspace_edit(draft, {"model_profile": "anima_base_v1", "requirements_edit": {
        "layers": draft["requirements"]["layers"], "loras": [], "prompt_locks": []},
        "prompt_edit": {"positive": "blonde hair, blue coat", "negative": ""}})
    assert result["compiled"]["positive"] == "blonde hair, blue coat"


@pytest.mark.parametrize("lock", [{"target": "system", "text": "x"}, {"target": "positive", "text": " "}])
def test_malformed_prompt_locks_are_rejected(lock):
    with pytest.raises(ValidationError):
        RequirementsEdit.model_validate({"layers": dump(Requirements.empty())["layers"], "loras": [], "prompt_locks": [lock]})


def test_legacy_requirements_still_load_without_prompt_locks():
    raw = dump(Requirements.empty())
    raw.pop("prompt_locks", None)
    assert dump(Requirements.model_validate(raw))["prompt_locks"] == []


def test_older_client_cannot_silently_clear_existing_locks():
    draft = draft_with_locks([{"target": "positive", "text": "short black hair"}])
    draft["compiled"] = compile_prompt(draft, PromptEdit(positive="short black hair, blue coat", negative=""), source="llm")
    edit = {"layers": deepcopy(draft["requirements"]["layers"]), "loras": []}
    result = apply_workspace_edit(draft, {"model_profile": "anima_base_v1", "requirements_edit": edit})
    assert result["requirements"]["prompt_locks"] == draft["requirements"]["prompt_locks"]
    with pytest.raises(WorkbenchError):
        apply_workspace_edit(draft, {"requirements_edit": edit,
            "prompt_edit": {"positive": "blonde hair, blue coat", "negative": ""}})
