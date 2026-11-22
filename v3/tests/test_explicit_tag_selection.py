"""An explicit picker change updates the visible and submitted text without an LLM."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from anima_prompt_studio_v3.api.models import DirectPromptSubmitRequest
from anima_prompt_studio_v3.api.workspace_store import WorkspaceStore
from anima_prompt_studio_v3.core.requirements import PromptEdit, Requirements, dump
from test_artist_preset_prompts import snapshot
from test_generation_submissions import harness, submit
from test_workbench_direct_generation import current_prompt_request


def requirements(**changes):
    value = dump(Requirements.empty())
    for layer, fields in changes.items():
        value["layers"][layer].update(fields)
    return {"layers": value["layers"], "loras": []}


@pytest.mark.parametrize("model,positive", [
    ("anima_turbo_v1_1", "  adult woman, blue coat\nsoft daylight  "),
    ("moss_image_sft_int8", "  成年女性，蓝色外套\n柔和光线  "),
])
def test_explicit_selection_saves_and_reloads_tags_with_the_original_body(tmp_path, model, positive):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    first = store.create("test", {"model_profile": model, "prompt_edit": {"positive": positive, "negative": "  原有负向\n"}})
    edit = requirements(subject={"character_tags": ["Shana"], "series_tags": ["shakugan_no_shana"]},
                        style={"manual_artist_tags": ["@Sample_Artist"]})
    saved = store.update(first["id"], expected_revision=first["revision"], title="test", draft={
        "model_profile": model, "requirements_edit": edit})
    expected = "shana, shakugan no shana, @sample artist, " + positive
    assert saved["draft"]["compiled"]["positive"] == expected
    assert saved["draft"]["compiled"]["negative"] == "  原有负向\n"
    assert saved["draft"]["compiled"]["manual_tags"] == ["shana", "shakugan no shana", "@sample artist"]
    assert WorkspaceStore(store.path).get(saved["id"])["draft"]["compiled"] == saved["draft"]["compiled"]
    removed = store.update(saved["id"], expected_revision=saved["revision"], title="test", draft={
        "model_profile": model, "requirements_edit": requirements()})
    assert removed["draft"]["compiled"]["positive"] == positive
    assert removed["draft"]["compiled"]["negative"] == "  原有负向\n"


def test_unchanged_selection_does_not_reinsert_tags_after_an_explicit_prompt_edit(tmp_path):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    edit = requirements(subject={"character_tags": ["shana"]})
    first = store.create("test", {"requirements_edit": edit, "prompt_edit": {"positive": "shana, portrait", "negative": ""}})
    reviewed = "  my exact reviewed prose\nwithout an identity token  "
    saved = store.update(first["id"], expected_revision=first["revision"], title="test", draft={
        "requirements_edit": edit, "prompt_edit": {"positive": reviewed, "negative": " exact negative "}})
    assert saved["draft"]["compiled"]["positive"] == reviewed
    assert saved["draft"]["compiled"]["negative"] == " exact negative "


def test_removing_selected_tags_keeps_the_literal_preset_with_the_same_artist(tmp_path):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    preset = snapshot(positive="  (@same:0.8), blue lines\n", negative=" same negative ")
    edit = requirements(subject={"character_tags": ["shana"]},
                        style={"manual_artist_tags": ["same"], "artist_preset": preset})
    positive = "(shana:1.2), (@same:1.1), portrait\n\n" + preset["positive"]
    first = store.create("test", {"requirements_edit": edit,
        "prompt_edit": {"positive": positive, "negative": preset["negative"]}})
    assert first["draft"]["compiled"]["positive"] == positive
    changed = deepcopy(edit)
    changed["layers"]["subject"]["character_tags"] = []
    changed["layers"]["style"]["manual_artist_tags"] = []
    saved = store.update(first["id"], expected_revision=first["revision"], title="test", draft={"requirements_edit": changed})
    assert saved["draft"]["compiled"]["positive"] == "portrait\n\n" + preset["positive"]
    assert saved["draft"]["compiled"]["negative"] == preset["negative"]
    assert saved["draft"]["compiled"]["manual_tags"] == []


def test_removing_the_only_tag_clears_the_compiled_prompt_instead_of_leaving_the_old_tag(tmp_path):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    first = store.create("test", {"requirements_edit": requirements(subject={"character_tags": ["shana"]}),
        "prompt_edit": {"positive": "shana", "negative": "  blurry\n bad hands  "}})
    saved = store.update(first["id"], expected_revision=first["revision"], title="test", draft={"requirements_edit": requirements()})
    assert saved["draft"]["compiled"]["positive"] == ""
    assert saved["draft"]["compiled"]["negative"] == "  blurry\n bad hands  "
    assert saved["draft"]["compiled"]["compiled_token"] != first["draft"]["compiled"]["compiled_token"]
    assert saved["draft"]["compile_state"] == "missing"
    assert WorkspaceStore(store.path).get(saved["id"])["draft"]["compiled"] == saved["draft"]["compiled"]


def test_ordinary_empty_prompt_edits_and_generation_requests_are_still_rejected():
    with pytest.raises(ValidationError):
        PromptEdit(positive="", negative="blurry")
    with pytest.raises(ValidationError):
        DirectPromptSubmitRequest(positive_prompt="", model_profile="anima_base_v1",
                                  remote_profile_id="remote-1", workflow_profile_id="anima_base_api_v1")


@pytest.mark.parametrize("positive,want", [
    ("cat, shana, @a", "cat"),
    ("cat, shana, @a, garden", "cat, garden"),
    ("shana, @a, cat", "cat"),
])
def test_removing_consecutive_selected_tags_cleans_only_their_separators(tmp_path, positive, want):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    first = store.create("test", {"requirements_edit": requirements(subject={"character_tags": ["shana"]},
        style={"manual_artist_tags": ["a"]}), "prompt_edit": {"positive": positive, "negative": ""}})
    saved = store.update(first["id"], expected_revision=first["revision"], title="test", draft={"requirements_edit": requirements()})
    assert saved["draft"]["compiled"]["positive"] == want


def test_selecting_tags_before_any_text_has_a_reviewable_prompt(tmp_path):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    first = store.create("test", {"requirements_edit": requirements(subject={"character_tags": ["shana"]})})
    assert first["draft"]["compiled"]["positive"] == "shana"
    assert first["draft"]["compiled"]["source"] == "user"
    assert first["draft"]["compile_state"] == "stale"


def test_direct_current_prompt_dispatches_the_saved_selected_tags(harness):
    store, start, _, executed, finished, _ = harness
    before, request = current_prompt_request(store, first_manual=True)
    saved = store.update(before["id"], expected_revision=before["revision"], title=before["title"], draft={
        "model_profile": "anima_base_v1",
        "requirements_edit": requirements(subject={"character_tags": ["shana"]}, style={"manual_artist_tags": ["sample_artist"]})})
    compiled = saved["draft"]["compiled"]
    assert compiled["positive"] == "shana, @sample artist, woman, red coat"
    request = request.model_copy(update={"workspace_revision": saved["revision"], "compiled_token": compiled["compiled_token"],
        "positive_prompt": compiled["positive"], "negative_prompt": compiled["negative"]})
    _, service = start()
    submit(service, request)
    entry = service.store.lookup("key")
    assert entry["snapshot"]["job"]["positive_prompt"] == compiled["positive"]
    assert entry["snapshot"]["compiled"]["positive"] == compiled["positive"]
    service.dispatch_pending()
    assert finished.wait(2)
    assert executed[0][0].positive_prompt == compiled["positive"]
