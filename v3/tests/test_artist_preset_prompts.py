from copy import deepcopy

import pytest
from pydantic import ValidationError

from anima_prompt_studio_v3.core.requirements import (
    Requirements, PromptEdit, WorkbenchError, apply_layer_updates,
    compile_prompt, dump, inputs_fingerprint,
)
from test_api import reference_db
from test_conversation import conversation_client, turn


def snapshot(**overrides):
    return {"id": "artist_test", "revision": 2, "name": "原文组合", "positive": r" (@a:1.2), @b \(name\)  ",
            "negative": "bad style", "model_family": "anima", "model_label": "Anima base v1",
            "syntax": "comfy", "source_url": "https://example.com/source", "content_hash": "a" * 64, **overrides}


def draft(preset=None):
    raw = dump(Requirements.empty())
    raw["layers"]["style"]["artist_preset"] = snapshot() if preset is None else preset
    return {"requirements": dump(Requirements.model_validate(raw))}


def test_snapshot_preserves_whitespace_and_survives_content_updates():
    original = draft()
    req = Requirements.model_validate(original["requirements"])
    assert dump(req)["layers"]["style"]["artist_preset"] == snapshot()
    changed = apply_layer_updates(req, {"style": {"text": "水彩"}})
    assert dump(changed)["layers"]["style"]["artist_preset"] == snapshot()
    with pytest.raises(WorkbenchError, match="不可自动编辑"):
        apply_layer_updates(req, {"style": {"artist_preset": None}})


def test_ai_omission_restores_literal_positive_and_negative():
    result = compile_prompt(draft(), PromptEdit(positive="girl, garden", negative="blurry"), source="llm")
    assert result["positive"] == "girl, garden\n\n" + snapshot()["positive"]
    assert result["negative"] == "blurry\n\n" + snapshot()["negative"]


def test_manual_tag_render_does_not_normalize_preserved_preset():
    value = draft()
    value["requirements"]["layers"]["subject"]["general_tags"] = ["blue sky"]
    raw = snapshot()["positive"]
    result = compile_prompt(value, PromptEdit(positive="girl\n\n" + raw, negative="bad style"), source="llm")
    assert raw in result["positive"]
    assert result["positive"].count(raw) == 1
    assert result["positive"].startswith("blue sky, girl")
    assert result["negative"] == "bad style"


def test_user_save_never_silently_reinserts_or_changes_reviewed_text():
    with pytest.raises(WorkbenchError) as caught:
        compile_prompt(draft(), PromptEdit(positive="girl", negative="bad style"), source="user")
    assert caught.value.code == "artist_preset_changed"
    raw = "girl\n\n" + snapshot()["positive"]
    result = compile_prompt(draft(), PromptEdit(positive=raw, negative="bad style"), source="user")
    assert result["positive"] == raw


def test_absent_preset_keeps_historical_shape_and_fingerprint():
    raw = dump(Requirements.empty())
    assert "artist_preset" not in raw["layers"]["style"]
    prior = inputs_fingerprint({"requirements": raw})
    raw["layers"]["style"]["artist_preset"] = None
    assert inputs_fingerprint({"requirements": raw}) == prior
    raw["layers"]["style"]["artist_preset"] = snapshot()
    assert inputs_fingerprint({"requirements": raw}) != prior


def test_snapshot_rejects_empty_content_and_unknown_extra_fields():
    with pytest.raises(ValidationError):
        draft(snapshot(positive=" ", negative=""))
    with pytest.raises(ValidationError):
        draft(snapshot(samples=[{"image_url": "anything"}]))


def test_output_length_is_checked_after_reinsertion():
    with pytest.raises(ValidationError):
        compile_prompt(draft(), PromptEdit(positive="x" * 20_000, negative=""), source="llm")


def test_raw_frozen_snapshot_is_not_mutated_by_compilation():
    value = draft()
    before = deepcopy(value)
    compile_prompt(value, PromptEdit(positive="girl", negative=""), source="llm")
    assert value == before


def test_http_user_save_ai_rewrite_and_reload_preserve_boundary_whitespace(conversation_client):
    client, _ = conversation_client
    preset = snapshot(positive="  (@a:1.2), @b \n", negative="  unwanted style \n")
    requirements = draft(preset)["requirements"]
    prompt = {"positive": "girl\n\n" + preset["positive"], "negative": preset["negative"]}
    response = client.post("/api/v3/workspaces", json={"draft": {
        "requirements_edit": {key: requirements[key] for key in ("layers", "loras")}, "prompt_edit": prompt}})
    assert response.status_code == 201, response.text
    created = response.json()
    assert {key: created["draft"]["compiled"][key] for key in prompt} == prompt
    rewritten = turn(client, created, delta={"text": "调整光影"})
    assert rewritten.status_code == 200, rewritten.text
    saved = rewritten.json()
    assert saved["draft"]["compiled"]["positive"].endswith(preset["positive"])
    assert saved["draft"]["compiled"]["negative"] == preset["negative"]
    reloaded = client.get("/api/v3/workspaces/" + created["id"]).json()
    assert reloaded["draft"]["requirements"]["layers"]["style"]["artist_preset"] == preset
    assert reloaded["draft"]["compiled"] == saved["draft"]["compiled"]
