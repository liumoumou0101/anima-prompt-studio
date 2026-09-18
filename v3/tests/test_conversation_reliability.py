"""Regression coverage for reviewable turns and strict model-format recovery."""
import asyncio
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from anima_prompt_studio_v3.api.conversation import ConversationService, TurnRequest
from anima_prompt_studio_v3.api.llm_workbench import test_connection as connection_test
from anima_prompt_studio_v3.api.models import WorkspaceUpdateRequest
from anima_prompt_studio_v3.api.workspace_store import WorkspaceStore
from anima_prompt_studio_v3.core.requirements import (
    PromptEdit, Requirements, WorkbenchError, apply_layer_updates,
    apply_workspace_edit, compile_prompt, compile_state, digest, dump, inputs_fingerprint,
)
from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
from test_generation_submissions import harness, payload, submit, workspace_payload


def prepared(tmp_path):
    store = WorkspaceStore(tmp_path / "turns.db")
    requirements = dump(Requirements.empty())
    requirements["layers"]["subject"]["text"] = "蓝外套侦探"
    record = store.create("侦探", {"requirements_edit": {
        "layers": requirements["layers"], "loras": [],
    }})
    return store, record


def output(**changes):
    return {"touched_layers": [], "layer_updates": {}, "positive": "detective, blue coat",
            "negative": "", "warnings": [], **changes}


def mock_results(monkeypatch, *responses):
    calls = []
    async def complete(**kwargs):
        calls.append(deepcopy(kwargs))
        response = responses[min(len(calls) - 1, len(responses) - 1)]
        return {"text": json.dumps(response) if isinstance(response, dict) else response}
    monkeypatch.setattr(LLMService, "complete", complete)
    return calls


def rewrite(store, record, **changes):
    request = TurnRequest(workspace_id=record["id"], revision=record["revision"],
                          delta={"text": "只修改外套颜色"}, **changes)
    return asyncio.run(ConversationService(store).turn(request))


@pytest.mark.parametrize("wrap", [
    lambda value: "```json\n" + json.dumps(value) + "\n```",
    lambda value: json.dumps({"result": value}),
    lambda value: json.dumps({"data": {"output": value}}),
])
def test_wrapped_structured_output_is_accepted_without_extra_model_call(tmp_path, monkeypatch, wrap):
    store, record = prepared(tmp_path)
    calls = mock_results(monkeypatch, wrap(output()))
    result = rewrite(store, record)
    assert result["positive"] == "detective, blue coat"
    assert len(calls) == 1


def test_partial_content_update_preserves_other_content_and_manual_tags():
    canonical = Requirements.empty()
    canonical.layers.style.medium = "水彩"
    canonical.layers.style.artists = ["someone"]
    canonical.layers.style.manual_artist_tags = ["custom artist"]
    canonical.layers.composition.shot = "半身"
    canonical.layers.exclusions.global_ = ["文字"]
    revised = apply_layer_updates(canonical, ["style", "composition", "exclusions"], {
        "style": {"text": "柔和"}, "composition": {"text": "居中"}, "exclusions": {"scoped": []},
    })
    assert revised.layers.style.medium == "水彩"
    assert revised.layers.style.artists == ["someone"]
    assert revised.layers.style.manual_artist_tags == ["custom artist"]
    assert revised.layers.composition.shot == "半身"
    assert revised.layers.exclusions.global_ == ["文字"]


@pytest.mark.parametrize("name,patch,locked", [
    ("subject", {"text": "red coat"}, True),
    ("subject", {"text": "red coat", "locked": False}, False),
    ("subject", {"character_tags": ["invented"]}, False),
    ("style", {"manual_artist_tags": ["invented"]}, False),
    ("lighting", {"text": "sunlight", "include_with_style_pin": True}, False),
    ("composition", {"design": {}}, False),
])
def test_partial_updates_never_edit_locked_content_or_control_fields(name, patch, locked):
    canonical = Requirements.empty()
    getattr(canonical.layers, name).locked = locked
    before = dump(canonical)
    with pytest.raises(WorkbenchError):
        apply_layer_updates(canonical, [name], {name: patch})
    assert dump(canonical) == before


def test_invalid_result_gets_one_bounded_repair_and_preserves_original_context(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    calls = mock_results(monkeypatch, "Here is the requested prompt: blue coat", output())
    result = rewrite(store, record)
    assert result["revision"] == record["revision"] + 1
    assert len(calls) == 2
    assert calls[1]["messages"][:2] == calls[0]["messages"]
    assert "positive" in calls[1]["messages"][-1]["content"]
    assert calls[1]["timeout_s"] <= 30


def test_invalid_repair_remains_atomic_and_never_adopts_arbitrary_text(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    calls = mock_results(monkeypatch, "Bearer SECRET private prompt", "still unstructured")
    with pytest.raises(WorkbenchError) as error:
        rewrite(store, record)
    assert "SECRET" not in str(error.value)
    assert len(calls) == 2
    assert store.get(record["id"]) == record


@pytest.mark.parametrize("raw", [
    '{"touched_layers":[],"layer_updates":{},"positive":"first","positive":"hidden change","negative":""}',
    'Explanation before ' + json.dumps(output()),
    json.dumps({"result": output(), "locked": False}),
])
def test_ambiguous_or_prose_wrappers_never_get_silently_unwrapped(tmp_path, monkeypatch, raw):
    store, record = prepared(tmp_path)
    calls = mock_results(monkeypatch, raw)
    with pytest.raises(WorkbenchError):
        rewrite(store, record)
    assert len(calls) == 2
    assert store.get(record["id"]) == record


@pytest.mark.parametrize("preview", [False, True])
def test_identical_result_does_not_make_a_revision_event_or_proposal(tmp_path, monkeypatch, preview):
    store, record = prepared(tmp_path)
    mock_results(monkeypatch, output())
    first = rewrite(store, record)
    before = store.get(record["id"])
    result = rewrite(store, first, preview=preview)
    assert result["unchanged"] is True
    assert "未改变" in result["message"]
    assert result["changed_layers"] == []
    assert store.get(record["id"]) == before
    assert store.get_proposal(record["id"]) is None


def test_preview_keeps_current_workspace_until_explicit_accept(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    mock_results(monkeypatch, output(touched_layers=["subject"],
        layer_updates={"subject": {"text": "红外套侦探"}}, positive="detective, red coat"))
    result = rewrite(store, record, preview=True)
    assert result["workspace_id"] == record["id"]
    assert result["base_revision"] == record["revision"]
    assert result["draft"]["compiled"]["positive"] == "detective, red coat"
    assert result["changed_layers"] == ["subject"]
    assert store.get(record["id"]) == record
    assert store.get_proposal(record["id"])["id"] == result["id"]


def test_mixed_requirements_and_manual_prompt_save_stays_stale_then_feeds_preview(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    mock_results(monkeypatch, output())
    first = rewrite(store, record)
    edit = deepcopy(first["draft"]["requirements"])
    edit["layers"]["subject"]["text"] = "红外套侦探"
    manual = {"positive": "detective, red coat, embroidery", "negative": "text"}
    saved = store.update(first["id"], expected_revision=first["revision"], title=first["title"], draft={
        "requirements_edit": {"layers": edit["layers"], "loras": []}, "prompt_edit": manual})
    compiled = saved["draft"]["compiled"]
    assert saved["draft"]["requirements"]["layers"]["subject"]["text"] == "红外套侦探"
    assert {key: compiled[key] for key in manual} == manual
    assert compiled["source"] == "user"
    assert compiled["compiled_token"] != first["draft"]["compiled"]["compiled_token"]
    assert compiled["inputs_fingerprint"] == first["draft"]["compiled"]["inputs_fingerprint"]
    assert saved["draft"]["compile_state"] == "stale"
    calls = mock_results(monkeypatch, output(**manual))
    request = TurnRequest(workspace_id=saved["id"], revision=saved["revision"], delta={"text": ""}, preview=True)
    proposal = asyncio.run(ConversationService(store).turn(request))
    context = json.loads(calls[0]["messages"][1]["content"])
    assert context["compiled"] == manual
    assert context["requirements"]["layers"]["subject"]["text"] == "红外套侦探"
    assert proposal["draft"]["compile_state"] == "fresh"
    assert store.get(saved["id"]) == saved


@pytest.mark.parametrize("with_requirements", [False, True])
def test_initial_manual_prompt_can_be_saved_but_is_not_a_compilation(tmp_path, with_requirements):
    store, prepared_record = prepared(tmp_path)
    record = prepared_record if with_requirements else store.create("手工提示词", {})
    manual = {"positive": "my exact prompt", "negative": "my exclusion"}
    saved = store.update(record["id"], expected_revision=record["revision"], title=record["title"],
                         draft={"prompt_edit": manual})
    assert saved["draft"]["compiled"]["positive"] == manual["positive"]
    assert saved["draft"]["compiled"]["negative"] == manual["negative"]
    assert saved["draft"]["compiled"]["source"] == "user"
    assert saved["draft"]["compile_state"] == "stale"
    assert store.get(saved["id"])["draft"]["compile_state"] == "stale"


@pytest.mark.parametrize("previously_compiled", [False, True])
def test_saved_stale_manual_prompt_cannot_bypass_generation_validation(harness, previously_compiled):
    store, start, _, executed, _, _ = harness
    _, service = start()
    if previously_compiled:
        record, _ = workspace_payload(store)
        requirements = deepcopy(record["draft"]["requirements"])
        requirements["layers"]["subject"]["text"] = "红外套侦探"
        draft = {"requirements_edit": {"layers": requirements["layers"], "loras": []}}
    else:
        record = store.create("手写草稿", {"model_profile": "anima_base_v1"})
        draft = {}
    draft.update(model_profile="anima_base_v1", prompt_edit={"positive": "red coat detective", "negative": ""})
    saved = store.update(record["id"], expected_revision=record["revision"], title=record["title"], draft=draft)
    request = payload(submission_kind="conversational", workspace_id=saved["id"],
        workspace_revision=saved["revision"], compiled_token=saved["draft"]["compiled"]["compiled_token"])
    with pytest.raises(WorkbenchError) as error:
        submit(service, request)
    assert error.value.code == "stale_compiled_prompt"
    assert not executed and not service.store.list()
    assert store.get(saved["id"]) == saved


def test_disconnect_before_repair_does_not_retry_or_write(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    calls = mock_results(monkeypatch, "invalid", output())
    async def disconnected():
        return bool(calls)
    request = TurnRequest(workspace_id=record["id"], revision=record["revision"],
                          delta={"text": "改红色"}, preview=True)
    service = ConversationService(store)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(service.turn(request, disconnected))
    assert len(calls) == 1
    assert not service.active
    assert store.get(record["id"]) == record


def test_disconnect_cancels_pending_model_and_releases_slot_without_a_proposal(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    service = ConversationService(store)
    async def run():
        started, lost_connection, upstream_cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def pending(**kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                upstream_cancelled.set()
                raise
        async def disconnected():
            return lost_connection.is_set()
        monkeypatch.setattr(LLMService, "complete", pending)
        request = TurnRequest(workspace_id=record["id"], revision=record["revision"],
                              delta={"text": "外套改红色"}, preview=True)
        task = asyncio.create_task(service.turn(request, disconnected))
        await started.wait()
        lost_connection.set()
        # asyncio.wait observes without cancelling the task for us: completion
        # must come from the disconnect monitor rather than this test's timeout.
        done, _ = await asyncio.wait({task}, timeout=1)
        try:
            assert task in done, "Disconnected turn kept waiting on its model"
            with pytest.raises(asyncio.CancelledError):
                await task
            assert upstream_cancelled.is_set()
            assert not service.active
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())
    assert store.get(record["id"]) == record
    assert store.get_proposal(record["id"]) is None


def test_locked_layer_violation_is_rejected_without_repair_or_proposal(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    record = store.transform(record["id"], expected_revision=record["revision"], operation=lambda draft: {
        **draft, "requirements": {**draft["requirements"], "layers": {
            **draft["requirements"]["layers"], "subject": {
                **draft["requirements"]["layers"]["subject"], "locked": True}}}})
    calls = mock_results(monkeypatch, output(touched_layers=["subject"],
        layer_updates={"subject": {"text": "红外套"}}), output())
    with pytest.raises(WorkbenchError):
        rewrite(store, record, preview=True)
    assert len(calls) == 1
    assert store.get(record["id"]) == record


def test_control_only_changes_keep_prompt_fresh_but_content_changes_do_not():
    draft = {"requirements": dump(Requirements.empty()), "mode": "faithful"}
    draft["compiled"] = compile_prompt(draft, PromptEdit(positive="detective", negative=""), source="llm")
    expected = inputs_fingerprint(draft)
    for layer in draft["requirements"]["layers"].values():
        layer["locked"] = True
        if "include_with_style_pin" in layer:
            layer["include_with_style_pin"] = True
    assert inputs_fingerprint(draft) == expected
    assert compile_state(draft) == "fresh"
    draft["requirements"]["layers"]["subject"]["text"] = "红外套"
    assert compile_state(draft) == "stale"


def test_historical_locked_prompt_stays_fresh_when_unlocking_without_recompile():
    raw = dump(Requirements.empty())
    raw["layers"]["subject"].update(text="侦探", locked=True)
    draft = {"requirements": raw, "mode": "faithful"}
    draft["compiled"] = compile_prompt(draft, PromptEdit(positive="detective", negative=""), source="llm")
    # Reconstruct the old fingerprint, including protection switches.
    historical = deepcopy(raw)
    historical.pop("revision")
    historical.pop("prompt_locks", None)
    for name in ("character_tags", "series_tags", "general_tags"):
        historical["layers"]["subject"].pop(name)
    historical["layers"]["style"].pop("manual_artist_tags")
    historical["layers"]["composition"].pop("design")
    historical["layers"]["lighting"].pop("mood")
    draft["compiled"]["inputs_fingerprint"] = digest({"requirements": historical,
        "mode": "faithful", "model_profile": "anima_aesthetic_v1", "compiler_contract": "anima-rewrite/1"})
    assert compile_state(draft) == "fresh"
    edit = deepcopy(raw)
    edit["layers"]["subject"]["locked"] = False
    saved = apply_workspace_edit(draft, {"requirements_edit": {"layers": edit["layers"], "loras": []}})
    assert compile_state(saved) == "fresh"
    assert saved["compiled"]["compiled_token"] == draft["compiled"]["compiled_token"]
    edit["layers"]["subject"]["text"] = "红外套侦探"
    changed = apply_workspace_edit(draft, {"requirements_edit": {"layers": edit["layers"], "loras": []}})
    assert compile_state(changed) == "stale"


def test_reviewed_negative_is_preserved_after_exclusion_lock_change(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    mock_results(monkeypatch, output(negative="my reviewed exclusion"))
    first = rewrite(store, record)
    edit = deepcopy(first["draft"]["requirements"])
    edit["layers"]["exclusions"]["locked"] = True
    edit["layers"]["lighting"]["text"] = "清晨"
    saved = store.update(first["id"], expected_revision=first["revision"], title=first["title"],
        draft={"requirements_edit": {"layers": edit["layers"], "loras": []}})
    mock_results(monkeypatch, output(positive="detective, blue coat, morning", negative="invented exclusion"))
    request = TurnRequest(workspace_id=saved["id"], revision=saved["revision"], delta={"text": ""})
    revised = asyncio.run(ConversationService(store).turn(request))
    assert revised["negative"] == "my reviewed exclusion"


@pytest.mark.parametrize("raw,compatible", [(output(), True), ("OK", False)])
def test_connection_distinguishes_transport_from_workbench_compatibility(monkeypatch, raw, compatible):
    calls = mock_results(monkeypatch, raw)
    result = asyncio.run(connection_test())
    assert result["ok"] is True
    assert result["workbench_compatible"] is compatible
    assert "touched_layers" in calls[0]["messages"][0]["content"]
    assert len(calls) == 1


def test_sync_requirements_preserves_authoritative_manual_prompt_and_only_proposes(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    record = store.transform(record["id"], expected_revision=record["revision"], operation=lambda draft: {
        **draft, "requirements": {**draft["requirements"], "layers": {
            **draft["requirements"]["layers"], "subject": {
                **draft["requirements"]["layers"]["subject"], "character_tags": ["custom identity"]}}}})
    manual = {"positive": "detective, red coat, custom embroidery, custom identity", "negative": "text, my reviewed exclusion"}
    mock_results(monkeypatch, output(touched_layers=["subject"],
        layer_updates={"subject": {"text": "红外套侦探，定制刺绣"}},
        positive="model attempted to replace user wording", negative=""))
    result = asyncio.run(ConversationService(store).turn(TurnRequest(
        workspace_id=record["id"], revision=record["revision"], task="sync_requirements",
        delta={"text": ""}, compiled=manual)))
    assert result["draft"]["requirements"]["layers"]["subject"]["text"] == "红外套侦探，定制刺绣"
    assert {key: result["draft"]["compiled"][key] for key in manual} == manual
    assert result["draft"]["compile_state"] == "fresh"
    assert result["draft"]["compiled"]["source"] == "user"
    assert result["draft"]["compiled"]["requirements_synced"] is True
    assert result["draft"]["requirements"]["layers"]["subject"]["character_tags"] == ["custom identity"]
    assert store.get(record["id"]) == record
    assert store.get_proposal(record["id"])["id"] == result["id"]


def test_sync_requirements_can_use_saved_prompt_without_any_prior_requirements(tmp_path, monkeypatch):
    store = WorkspaceStore(tmp_path / "sync.db")
    record = store.create("手工英文", {"prompt_edit": {"positive": "red coat detective", "negative": "text"}})
    mock_results(monkeypatch, output(touched_layers=["subject", "exclusions"],
        layer_updates={"subject": {"text": "红外套侦探"}, "exclusions": {"global": ["文字"]}}))
    result = asyncio.run(ConversationService(store).turn(TurnRequest(
        workspace_id=record["id"], revision=record["revision"], task="sync_requirements", delta={"text": ""})))
    assert result["positive"] == "red coat detective"
    assert result["negative"] == "text"
    assert result["draft"]["requirements"]["layers"]["subject"]["text"] == "红外套侦探"
    assert store.get(record["id"]) == record


def test_sync_requirements_without_prompt_is_rejected_before_calling_model(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    calls = mock_results(monkeypatch, output())
    with pytest.raises(WorkbenchError) as error:
        asyncio.run(ConversationService(store).turn(TurnRequest(
            workspace_id=record["id"], revision=record["revision"], task="sync_requirements", delta={"text": ""})))
    assert error.value.code == "empty_prompt"
    assert calls == []
    assert store.get(record["id"]) == record


@pytest.mark.parametrize("patch,locked", [({"text": "红外套侦探"}, True),
    ({"text": "红外套侦探", "locked": False}, False), ({"character_tags": ["invented"]}, False)])
def test_sync_requirements_cannot_overwrite_locked_requirements_or_control_fields(tmp_path, monkeypatch, patch, locked):
    store, record = prepared(tmp_path)
    record = store.transform(record["id"], expected_revision=record["revision"], operation=lambda draft: {
        **draft, "requirements": {**draft["requirements"], "layers": {
            **draft["requirements"]["layers"], "subject": {
                **draft["requirements"]["layers"]["subject"], "locked": locked}}}})
    mock_results(monkeypatch, output(touched_layers=["subject"], layer_updates={"subject": patch}))
    with pytest.raises(WorkbenchError) as error:
        asyncio.run(ConversationService(store).turn(TurnRequest(
            workspace_id=record["id"], revision=record["revision"], task="sync_requirements", delta={"text": ""},
            compiled={"positive": "detective, red coat", "negative": ""})))
    assert error.value.code == "invalid_layer_updates"
    assert store.get(record["id"]) == record
    assert store.get_proposal(record["id"]) is None


def test_sync_requirements_no_change_does_not_create_proposal_or_version(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    mock_results(monkeypatch, output())
    record = rewrite(store, record)
    before = store.get(record["id"])
    result = asyncio.run(ConversationService(store).turn(TurnRequest(
        workspace_id=record["id"], revision=record["revision"], task="sync_requirements", delta={"text": ""})))
    assert result["unchanged"] is True
    assert store.get(record["id"]) == before
    assert store.get_proposal(record["id"]) is None


def test_sync_matching_manual_prompt_still_proposes_confirmation_then_becomes_noop(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    record = store.update(record["id"], expected_revision=record["revision"], title=record["title"],
                          draft={"prompt_edit": {"positive": "detective, blue coat", "negative": ""}})
    mock_results(monkeypatch, output())
    service = ConversationService(store)
    proposal = asyncio.run(service.turn(TurnRequest(workspace_id=record["id"], revision=record["revision"],
        task="sync_requirements", delta={"text": ""})))
    assert proposal["unchanged"] is False
    assert proposal["draft"]["compiled"]["requirements_synced"] is True
    assert store.get(record["id"]) == record
    adopted = store.accept_proposal(record["id"], proposal["id"], expected_revision=record["revision"])
    result = asyncio.run(service.turn(TurnRequest(workspace_id=adopted["id"], revision=adopted["revision"],
        task="sync_requirements", delta={"text": ""})))
    assert result["unchanged"] is True
    assert store.get(record["id"]) == adopted


@pytest.mark.parametrize("contains_lock", [True, False])
def test_sync_preserves_literal_prompt_locks_or_rejects_the_candidate(tmp_path, monkeypatch, contains_lock):
    store, record = prepared(tmp_path)
    locks = [{"target": "positive", "text": "detective"}, {"target": "negative", "text": "watermark"}]
    record = store.transform(record["id"], expected_revision=record["revision"], operation=lambda draft: {
        **draft, "requirements": {**draft["requirements"], "prompt_locks": locks}})
    mock_results(monkeypatch, output(touched_layers=["subject"], layer_updates={"subject": {"text": "红外套侦探"}}))
    request = TurnRequest(workspace_id=record["id"], revision=record["revision"], task="sync_requirements",
        delta={"text": ""}, compiled={"positive": "detective, red coat", "negative": "watermark" if contains_lock else "text"})
    if contains_lock:
        proposal = asyncio.run(ConversationService(store).turn(request))
        assert proposal["draft"]["requirements"]["prompt_locks"] == locks
        assert proposal["negative"] == "watermark"
    else:
        with pytest.raises(WorkbenchError) as error:
            asyncio.run(ConversationService(store).turn(request))
        assert error.value.code == "protected_prompt_changed"
        assert store.get_proposal(record["id"]) is None
    assert store.get(record["id"]) == record


def test_sync_protected_conflict_is_not_saved_or_marked_synchronized(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    mock_results(monkeypatch, output(conflicts=["英文提示词与锁定身份冲突"]))
    with pytest.raises(WorkbenchError) as error:
        asyncio.run(ConversationService(store).turn(TurnRequest(
            workspace_id=record["id"], revision=record["revision"], task="sync_requirements", delta={"text": ""},
            compiled={"positive": "different identity, red coat", "negative": ""})))
    assert error.value.code == "scene_design_conflict"
    assert store.get(record["id"]) == record
    assert store.get_proposal(record["id"]) is None


@pytest.mark.parametrize("break_prompt", [False, True])
def test_api_validated_legacy_save_preserves_omitted_prompt_locks(tmp_path, monkeypatch, break_prompt):
    store, record = prepared(tmp_path)
    mock_results(monkeypatch, output())
    record = rewrite(store, record)
    locks = [{"target": "positive", "text": "detective"}]
    record = store.transform(record["id"], expected_revision=record["revision"], operation=lambda draft: {
        **draft, "requirements": {**draft["requirements"], "prompt_locks": locks}})
    draft = {"model_profile": record["draft"].get("model_profile", "anima_aesthetic_v1"),
             "requirements_edit": {"layers": record["draft"]["requirements"]["layers"], "loras": []}}
    if break_prompt:
        draft["prompt_edit"] = {"positive": "different person, blue coat", "negative": ""}
    payload = WorkspaceUpdateRequest.model_validate({"title": record["title"], "revision": record["revision"], "draft": draft})
    if break_prompt:
        with pytest.raises(WorkbenchError) as error:
            store.update(record["id"], expected_revision=payload.revision, title=payload.title,
                         draft=payload.draft.persistence_payload())
        assert error.value.code == "protected_prompt_changed"
        assert store.get(record["id"]) == record
    else:
        saved = store.update(record["id"], expected_revision=payload.revision, title=payload.title,
                             draft=payload.draft.persistence_payload())
        assert saved["draft"]["requirements"]["prompt_locks"] == locks


@pytest.mark.parametrize("change_content", [False, True])
def test_sync_confirmation_invalidates_on_requirement_content_edits_only(tmp_path, monkeypatch, change_content):
    store, record = prepared(tmp_path)
    mock_results(monkeypatch, output())
    proposal = asyncio.run(ConversationService(store).turn(TurnRequest(
        workspace_id=record["id"], revision=record["revision"], task="sync_requirements", delta={"text": ""},
        compiled={"positive": "detective, blue coat", "negative": ""})))
    record = store.accept_proposal(record["id"], proposal["id"], expected_revision=record["revision"])
    edit = deepcopy(record["draft"]["requirements"])
    edit["layers"]["subject"]["text" if change_content else "locked"] = "绿外套侦探" if change_content else True
    saved = store.update(record["id"], expected_revision=record["revision"], title=record["title"], draft={
        "model_profile": record["draft"].get("model_profile", "anima_aesthetic_v1"),
        "requirements_edit": {"layers": edit["layers"], "loras": []}})
    assert saved["draft"]["compiled"]["requirements_synced"] is (not change_content)
    assert saved["draft"]["compile_state"] == ("stale" if change_content else "fresh")


def test_internal_requirement_replacement_also_invalidates_sync_confirmation(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    mock_results(monkeypatch, output())
    proposal = asyncio.run(ConversationService(store).turn(TurnRequest(
        workspace_id=record["id"], revision=record["revision"], task="sync_requirements", delta={"text": ""},
        compiled={"positive": "detective, blue coat", "negative": ""})))
    record = store.accept_proposal(record["id"], proposal["id"], expected_revision=record["revision"])
    def replace_from_reference(draft):
        draft["requirements"]["layers"]["style"]["medium"] = "炭笔"
        return draft
    saved = store.transform(record["id"], expected_revision=record["revision"], operation=replace_from_reference)
    assert saved["draft"]["compile_state"] == "stale"
    assert saved["draft"]["compiled"]["requirements_synced"] is False


def test_api_manual_save_preserves_prompt_whitespace_through_persistence_and_reload(tmp_path):
    store, record = prepared(tmp_path)
    manual = {"positive": "  detective,\nred coat\n", "negative": " watermark  \n"}
    payload = WorkspaceUpdateRequest.model_validate_json(json.dumps({"title": record["title"],
        "revision": record["revision"], "draft": {"prompt_edit": manual}}))
    saved = store.update(record["id"], expected_revision=payload.revision, title=payload.title,
                         draft=payload.draft.persistence_payload())
    reopened = WorkspaceStore(tmp_path / "turns.db").get(record["id"])
    for value in (saved, reopened):
        assert {key: value["draft"]["compiled"][key] for key in manual} == manual


def test_sync_candidate_acceptance_preserves_prompt_whitespace_exactly(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    manual = {"positive": "  detective,\nred coat\n", "negative": " watermark  \n"}
    mock_results(monkeypatch, output(touched_layers=["subject"], layer_updates={"subject": {"text": "红外套侦探"}}))
    request = TurnRequest.model_validate_json(json.dumps({"workspace_id": record["id"],
        "revision": record["revision"], "task": "sync_requirements", "delta": {"text": ""}, "compiled": manual}))
    proposal = asyncio.run(ConversationService(store).turn(request))
    assert store.get(record["id"]) == record
    pending = WorkspaceStore(tmp_path / "turns.db").get_proposal(record["id"])
    accepted = store.accept_proposal(record["id"], proposal["id"], expected_revision=record["revision"])
    reopened = WorkspaceStore(tmp_path / "turns.db").get(record["id"])
    for value in (proposal, pending, accepted, reopened):
        assert {key: value["draft"]["compiled"][key] for key in manual} == manual
        assert value["draft"]["compile_state"] == "fresh"
        assert value["draft"]["compiled"]["requirements_synced"] is True


@pytest.mark.parametrize("positive", ["", " ", "\n\t  \r\n", "　"])
def test_preserving_prompt_whitespace_does_not_allow_blank_positive(positive):
    with pytest.raises(ValidationError):
        PromptEdit(positive=positive, negative=" \n")
