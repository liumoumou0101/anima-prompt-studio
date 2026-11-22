"""A bold rework is an isolated proposal until the user adopts it."""
import json

import pytest

from anima_prompt_studio_v3.core.requirements import Requirements, dump
from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
from test_api import reference_db
from test_conversation import conversation_client, turn


VISIBLE = {"positive": "  a ceramic owl on an oak desk,\nfull body  ", "negative": "  text, people\n"}
REWORKED = "a ceramic owl on an oak desk, full body, low viewpoint with a soft pool of light around the owl"


def create_scene(client, artists=None):
    requirements = dump(Requirements.empty())
    requirements["layers"]["subject"]["text"] = "橡木桌上的陶瓷猫头鹰"
    requirements["layers"]["style"]["artists"] = artists or []
    requirements["layers"]["composition"]["design"] = {"shot": {"value": "全身", "source": "user"}}
    response = client.post("/api/v3/workspaces", json={"draft": {
        "mode": "expand", "model_profile": "anima_base_v1", "prompt_edit": VISIBLE,
        "requirements_edit": {"layers": requirements["layers"], "loras": [],
                              "prompt_locks": [{"target": "positive", "text": "ceramic owl"}]},
    }})
    assert response.status_code == 201, response.text
    return response.json()


def reply(monkeypatch, positive, updates=None):
    seen = []

    async def complete(**kwargs):
        seen.append(kwargs)
        return {"text": json.dumps({"positive": positive, "negative": VISIBLE["negative"],
                                    "layer_updates": updates or {}, "warnings": []})}

    monkeypatch.setattr(LLMService, "complete", complete)
    return seen


@pytest.mark.parametrize("accept", [False, True])
def test_bold_only_creates_preview_and_preserves_persistent_mode(conversation_client, monkeypatch, accept):
    client, _ = conversation_client
    record = create_scene(client)
    path = f"/api/v3/workspaces/{record['id']}"
    seen = reply(monkeypatch, REWORKED)
    # The action itself must be safe even if a client forgets the preview flag.
    response = turn(client, record, task="bold_rewrite", compiled=VISIBLE)
    assert response.status_code == 200, response.text
    candidate = response.json()
    assert candidate["task"] == "bold_rewrite"
    assert candidate["positive"] == REWORKED
    assert candidate["negative"] == VISIBLE["negative"]
    assert candidate["draft"]["mode"] == "expand"
    assert candidate["draft"]["requirements"] == record["draft"]["requirements"]
    assert client.get(path).json() == record
    assert client.get(path + "/proposal").json()["proposal"]["task"] == "bold_rewrite"
    context = json.loads(seen[0]["messages"][1]["content"])
    assert context["rewrite_goal"]["operation"] == "bold_rewrite"
    assert context["delta"]["text"] == ""
    assert context["compiled"]["positive"] == VISIBLE["positive"]
    sources = context["preservation_sources"]
    assert {"path": "compiled.positive", "value": VISIBLE["positive"]} in sources["creative_brief"]
    assert {"path": "compiled.negative", "value": VISIBLE["negative"]} in sources["required"]
    assert any(item["path"].endswith("design.shot") for item in sources["required"])
    assert any(item["path"].startswith("requirements.prompt_locks") for item in sources["required"])
    proposal_path = f"{path}/proposals/{candidate['id']}"
    if accept:
        saved = client.post(proposal_path + "/accept", json={"revision": record["revision"]}).json()
        assert saved["revision"] == record["revision"] + 1
        assert saved["draft"]["compiled"]["positive"] == REWORKED
        assert saved["draft"]["mode"] == "expand"
    else:
        assert client.request("DELETE", proposal_path, json={"revision": record["revision"]}).is_success
        assert client.get(path).json() == record


def test_bold_without_existing_prompt_does_not_call_model(conversation_client):
    client, captured = conversation_client
    record = client.post("/api/v3/workspaces", json={"draft": {}}).json()
    response = turn(client, record, task="bold_rewrite", delta={"text": "重构构图"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "empty_prompt"
    assert captured == []


def test_bold_honors_locked_prompt_and_returns_no_candidate_on_conflict(conversation_client, monkeypatch):
    client, _ = conversation_client
    record = create_scene(client)
    reply(monkeypatch, "a paper bird in another room")
    response = turn(client, record, task="bold_rewrite", compiled=VISIBLE)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "protected_prompt_changed"
    assert client.get(f"/api/v3/workspaces/{record['id']}").json() == record


def test_bold_with_no_actual_change_does_not_create_a_proposal(conversation_client, monkeypatch):
    client, _ = conversation_client
    record = create_scene(client)
    reply(monkeypatch, VISIBLE["positive"])
    response = turn(client, record, task="bold_rewrite", compiled=VISIBLE)
    assert response.status_code == 200, response.text
    assert response.json()["unchanged"] is True
    path = f"/api/v3/workspaces/{record['id']}"
    assert client.get(path).json() == record
    assert client.app.state.workspace_store.get_proposal(record["id"]) is None


def test_bold_cannot_remove_a_selected_artist_through_an_ordinary_layer_update(conversation_client, monkeypatch):
    client, _ = conversation_client
    record = create_scene(client, artists=["owl_painter"])
    reply(monkeypatch, REWORKED, {"style": {"artists": []}})
    response = turn(client, record, task="bold_rewrite", delta={"text": "重构受光关系"}, compiled=VISIBLE)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "scene_design_conflict"
    assert client.get(f"/api/v3/workspaces/{record['id']}").json() == record
    assert client.app.state.workspace_store.get_proposal(record["id"]) is None


def test_bold_can_use_the_saved_fresh_prompt_with_no_direction(conversation_client, monkeypatch):
    client, _ = conversation_client
    record = create_scene(client)
    reply(monkeypatch, VISIBLE["positive"])
    saved = turn(client, record, mode="expand", compiled=VISIBLE, delta={"text": "保留陶瓷猫头鹰"}).json()
    assert saved["draft"]["compile_state"] == "fresh"
    seen = reply(monkeypatch, REWORKED)
    response = turn(client, saved, task="bold_rewrite")
    assert response.status_code == 200, response.text
    assert response.json()["positive"] == REWORKED
    context = json.loads(seen[0]["messages"][1]["content"])
    assert context["preservation_sources"]["creative_brief"] == [{"path": "compiled.positive", "value": VISIBLE["positive"]}]
    assert client.get(f"/api/v3/workspaces/{record['id']}").json()["revision"] == saved["revision"]


@pytest.mark.parametrize("explicit", [False, True])
def test_bold_sources_stored_facts_independently_of_its_creative_candidate(conversation_client, monkeypatch, explicit):
    client, _ = conversation_client
    record = create_scene(client)
    chosen_lighting = "冷蓝光从右后方照亮桌面"
    staged = []
    async def complete(**kwargs):
        messages = kwargs["messages"]
        if json.loads(messages[1]["content"]).get("task") == "resolve_bold_requirements":
            staged.append(messages[1]["content"])
            value = {"layer_updates": {}, "evidence": {}}
            if explicit:
                value = {"layer_updates": {"lighting": {"text": "傍晚"}},
                         "evidence": {"lighting": {"text": "把时间改成傍晚"}}}
            return {"text": json.dumps(value)}
        return {"text": json.dumps({"positive": REWORKED, "negative": VISIBLE["negative"],
                                    "layer_updates": {"lighting": {"text": chosen_lighting},
                                                      "composition": {"text": "低视点，桌面向远处延伸"}}})}
    monkeypatch.setattr(LLMService, "complete", complete)
    direction = "镜位和光色由你大胆重构。" + ("把时间改成傍晚。" if explicit else "")
    response = turn(client, record, task="bold_rewrite", compiled=VISIBLE, delta={"text": direction})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["changed_layers"] == (["lighting"] if explicit else [])
    assert result["draft"]["requirements"]["layers"]["lighting"]["text"] == ("傍晚" if explicit else "")
    assert result["draft"]["requirements"]["layers"]["composition"]["text"] == ""
    assert result["positive"] == REWORKED
    assert len(staged) == 1
    assert chosen_lighting not in staged[0] and REWORKED not in staged[0]


@pytest.mark.parametrize(("delta", "protected"), [
    ("正向提示词逐字不变。负向移除雾，保留文字，并加入运动模糊。", True),
    ("不要求保持正向不变。请重新设计灯光。", False),
    ("既要改正向也要改负向，请重写两段。", False),
])
def test_only_unambiguous_literal_field_directives_freeze_reviewed_text(conversation_client, monkeypatch, delta, protected):
    client, _ = conversation_client
    record = create_scene(client)
    generated = VISIBLE["positive"] + ", motion blur"
    reply(monkeypatch, generated)
    response = turn(client, record, compiled=VISIBLE, delta={"text": delta})
    assert response.status_code == 200, response.text
    assert response.json()["positive"] == (VISIBLE["positive"] if protected else generated)


@pytest.mark.parametrize("fault", ["invalid-json", "unfounded", "timeout"])
def test_unverified_bold_facts_keep_original_requirements_and_offer_preview(conversation_client, monkeypatch, fault):
    client, _ = conversation_client
    record = create_scene(client)
    async def complete(**kwargs):
        if json.loads(kwargs["messages"][1]["content"]).get("task") == "resolve_bold_requirements":
            if fault == "timeout":
                raise TimeoutError
            if fault == "invalid-json":
                return {"text": "not JSON"}
            return {"text": json.dumps({"layer_updates": {"lighting": {"text": "冷逆光"}},
                                        "evidence": {"lighting": {"text": "用户并没有提供这句话"}}})}
        return {"text": json.dumps({"positive": REWORKED, "negative": VISIBLE["negative"],
                                    "layer_updates": {"lighting": {"text": "冷逆光"}}})}
    monkeypatch.setattr(LLMService, "complete", complete)
    response = turn(client, record, task="bold_rewrite", compiled=VISIBLE, delta={"text": "大胆重构光色"})
    assert response.status_code == 200, response.text
    proposal = response.json()
    assert proposal["review_status"] == "needs_review"
    assert any("画面要求未能核实" in warning for warning in proposal["warnings"])
    assert proposal["draft"]["requirements"] == record["draft"]["requirements"]
    assert proposal["positive"] == REWORKED
    assert client.get(f"/api/v3/workspaces/{record['id']}").json() == record


def test_open_design_does_not_backfill_empty_layers_from_old_view_or_permission(conversation_client, monkeypatch):
    client, _ = conversation_client
    record = create_scene(client)
    reviewed = {**VISIBLE, "positive": VISIBLE["positive"] + ", simple overhead view"}
    low_view = REWORKED + ", cool rim light"
    async def complete(**kwargs):
        if json.loads(kwargs["messages"][1]["content"]).get("task") == "resolve_bold_requirements":
            return {"text": json.dumps({"layer_updates": {"composition": {"shot": "俯视"},
                                                          "lighting": {"text": "光色大胆重构"}},
                                        "evidence": {"composition": {"shot": "simple overhead view"},
                                                     "lighting": {"text": "光色大胆重构"}}})}
        return {"text": json.dumps({"positive": low_view, "negative": VISIBLE["negative"],
                                    "layer_updates": {"composition": {"shot": "低视点"}}})}
    monkeypatch.setattr(LLMService, "complete", complete)
    response = turn(client, record, task="bold_rewrite", compiled=reviewed,
                    delta={"text": "把镜位和光色大胆重构，保留猫头鹰和橡木桌。"})
    assert response.status_code == 200, response.text
    assert response.json()["draft"]["requirements"] == record["draft"]["requirements"]
    assert response.json()["positive"] == low_view


@pytest.mark.real_rewrite_review
def test_review_can_retract_only_proposed_layer_fields_to_the_original_value(conversation_client, monkeypatch):
    client, _ = conversation_client
    record = create_scene(client)
    stages = []
    async def complete(**kwargs):
        context = json.loads(kwargs["messages"][1]["content"])
        if kwargs["task"] == "rewrite_review":
            stages.append("review")
            lighting = context["candidate"]["requirements"]["layers"]["lighting"]["text"]
            return {"text": json.dumps({"issues": [], "layer_corrections": {"lighting": {"text": ""}} if lighting else {}})}
        if context.get("task") == "resolve_bold_requirements":
            stages.append("resolve")
            return {"text": json.dumps({"layer_updates": {"lighting": {"text": "冷光"}},
                                        "evidence": {"lighting": {"text": "冷光"}}})}
        stages.append("rewrite")
        return {"text": json.dumps({"positive": REWORKED, "negative": VISIBLE["negative"],
                                    "layer_updates": {"lighting": {"text": "冷逆光"}}})}
    monkeypatch.setattr(LLMService, "complete", complete)
    response = turn(client, record, task="bold_rewrite", compiled=VISIBLE, delta={"text": "冷光只是可选思路。"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert stages == ["rewrite", "resolve", "review", "review"]
    assert result.get("review_status") != "needs_review"
    assert result["draft"]["requirements"] == record["draft"]["requirements"]
