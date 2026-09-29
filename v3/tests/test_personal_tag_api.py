"""Protected HTTP contract for the independent personal library."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from anima_prompt_studio_v3.api import create_api_runtime
from anima_prompt_studio_v3.storage.personal_tag_import import export_bundle
from anima_prompt_studio_v3.storage.personal_tags import PersonalTagStore


BASE = "/api/v3/personal-tags"
ORIGIN = "http://127.0.0.1"


def client_and_headers(tmp_path: Path):
    workspace = tmp_path / "workspace.db"
    runtime = create_api_runtime(tmp_path / "missing-reference.db", workspace_db=workspace)
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
    response = client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token},
                           headers={"Origin": ORIGIN})
    assert response.status_code == 200
    return client, {"X-Anima-Session": response.json()["session_token"], "Origin": ORIGIN}, workspace.with_name("personal-tags.db")


def test_personal_api_works_without_reference_pack(tmp_path):
    client, headers, database = client_and_headers(tmp_path)
    created = client.post(BASE + "/tags", json={"display_name": "长发", "content": "long_hair",
                                                  "aliases": ["long hair"]}, headers=headers)
    assert created.status_code == 200, created.text
    tag = created.json()
    assert tag["content"] == "long_hair" and tag["revision"] == 1
    listed = client.get(BASE + "/tags", params={"q": "long hair"}, headers=headers)
    assert listed.status_code == 200 and listed.json()["items"][0]["id"] == tag["id"]
    assert client.get(BASE + "/tags/similar", params={"content": "LONG HAIR"}, headers=headers).json()[0]["id"] == tag["id"]
    assert client.get(BASE + "/tags/similar", params={"content": "long hair", "exclude_id": tag["id"]}, headers=headers).json() == []
    exported = client.get(BASE + "/export", headers=headers)
    assert exported.status_code == 200
    assert exported.json() == export_bundle(PersonalTagStore(database))
    assert "attachment" in exported.headers["content-disposition"]


def test_personal_routes_require_session(tmp_path):
    client, _, _ = client_and_headers(tmp_path)
    for method, path, kwargs in (("get", "/categories", {}), ("post", "/tags", {"json": {}}),
                                 ("get", "/draft", {}), ("post", "/imports/preview", {"json": {}}),
                                 ("get", "/export", {}), ("get", "/tags/similar", {})):
        response = getattr(client, method)(BASE + path, headers={"Origin": ORIGIN}, **kwargs)
        assert response.status_code == 401, (path, response.text)
        assert response.json()["error"]["code"] == "session_invalid"


def test_api_conflicts_preserve_existing_data(tmp_path):
    client, headers, _ = client_and_headers(tmp_path)
    category = client.post(BASE + "/categories", json={"name": "头发"}, headers=headers).json()
    created = client.post(BASE + "/tags", json={"display_name": "原名", "content": "original",
                                                       "category_id": category["id"]}, headers=headers).json()
    changed = client.put(BASE + "/tags/" + created["id"], json={"value": {"display_name": "新名", "content": "original",
                                                                                  "category_id": category["id"]},
                                                                      "expected_revision": 1}, headers=headers)
    assert changed.status_code == 200, changed.text
    stale = client.put(BASE + "/tags/" + created["id"], json={"value": {"display_name": "丢失", "content": "lost"},
                                                                    "expected_revision": 1}, headers=headers)
    assert stale.status_code == 409
    assert stale.json()["error"]["details"]["current_revision"] == 2
    assert client.get(BASE + "/tags/" + created["id"], headers=headers).json()["content"] == "original"
    deleted = client.delete(BASE + "/categories/" + category["id"], params={"expected_revision": 1},
                            headers={**headers, "Content-Type": "application/json"})
    assert deleted.status_code == 422
    assert client.get(BASE + "/categories", headers=headers).json()[0]["deleted_at"] is None


def test_composition_api_roundtrip_and_stale_draft_conflict(tmp_path):
    client, headers, _ = client_and_headers(tmp_path)
    item = {"id": "entry", "source_tag_id": None, "display_name": "片段", "content": "raw,\nCase_Name",
            "kind": "fragment", "polarity": "negative", "weight": 1.25}
    created = client.post(BASE + "/combinations", json={"name": "组合", "items": [item]}, headers=headers)
    assert created.status_code == 200, created.text
    combination = created.json()
    assert client.get(BASE + "/combinations/" + combination["id"], headers=headers).json()["items"][0]["content"] == item["content"]
    saved = client.put(BASE + "/draft", json={"items": [item], "expected_revision": 0}, headers=headers)
    assert saved.status_code == 200 and saved.json()["revision"] == 1
    stale = client.put(BASE + "/draft", json={"items": [], "expected_revision": 0}, headers=headers)
    assert stale.status_code == 409
    assert stale.json()["error"]["details"]["current_revision"] == 1
    assert stale.json()["error"]["details"]["current"]["items"][0]["content"] == item["content"]
    assert client.get(BASE + "/draft", headers=headers).json()["items"][0]["content"] == item["content"]


def test_category_tag_trash_bulk_move_and_validation(tmp_path):
    client, headers, _ = client_and_headers(tmp_path)
    a = client.post(BASE + "/categories", json={"name": "A"}, headers=headers).json()
    b = client.post(BASE + "/categories", json={"name": "B"}, headers=headers).json()
    tag = client.post(BASE + "/tags", json={"display_name": "T", "content": "One", "category_id": a["id"]},
                      headers=headers).json()
    stale = client.post(BASE + "/tags/bulk-move", json={"items": [{"id": tag["id"], "revision": 0}],
                                                        "category_id": b["id"]}, headers=headers)
    assert stale.status_code == 422
    moved = client.post(BASE + "/tags/bulk-move", json={"items": [{"id": tag["id"], "revision": 1}],
                                                        "category_id": b["id"]}, headers=headers)
    assert moved.status_code == 200 and moved.json()["moved"] == 1
    stale = client.post(BASE + "/tags/bulk-move", json={"items": [{"id": tag["id"], "revision": 1}],
                                                        "category_id": a["id"]}, headers=headers)
    assert stale.status_code == 409
    assert client.get(BASE + "/tags/" + tag["id"], headers=headers).json()["category_id"] == b["id"]
    deleted = client.delete(BASE + "/tags/" + tag["id"], params={"expected_revision": 2},
                            headers={**headers, "Content-Type": "application/json"})
    assert deleted.status_code == 200 and deleted.json()["deleted_at"]
    assert client.get(BASE + "/tags", headers=headers).json()["total"] == 0
    assert client.get(BASE + "/tags", params={"trash": True}, headers=headers).json()["total"] == 1
    restored = client.post(BASE + "/tags/" + tag["id"] + "/restore",
                           json={"expected_revision": 3}, headers=headers)
    assert restored.status_code == 200 and restored.json()["deleted_at"] is None
    assert client.get(BASE + "/tags/missing", headers=headers).status_code == 404
    assert client.post(BASE + "/tags", json={"display_name": "bad", "content": "ok",
                                                  "default_weight": 1.03}, headers=headers).status_code == 422
    assert client.post(BASE + "/tags", json={"display_name": "alias", "content": "ok",
                                                  "aliases": ["x" * 20_001]}, headers=headers).status_code == 422


def test_import_preview_commit_and_bounded_body(tmp_path):
    client, headers, database = client_and_headers(tmp_path)
    document = json.loads((Path(__file__).parent / "fixtures" / "personal_tags_legacy.json").read_text(encoding="utf-8"))
    payload = {"document": document, "options": {"fragment_ids": ["12"]}}
    preview = client.post(BASE + "/imports/preview", json=payload, headers=headers)
    assert preview.status_code == 200, preview.text
    result = client.post(BASE + "/imports/commit", json={**payload, "digest": preview.json()["digest"],
                                                      "expected_library_revision": preview.json()["library_revision"]},
                         headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["counts"]["new"] == 6
    assert client.get(BASE + "/export", headers=headers).json() == export_bundle(PersonalTagStore(database))
    stale = client.post(BASE + "/imports/commit", json={**payload, "digest": preview.json()["digest"],
                                                     "expected_library_revision": preview.json()["library_revision"]},
                        headers=headers)
    assert stale.status_code == 409
    assert stale.json()["error"]["details"]["current_revision"] == result.json()["library_revision"]
    assert client.post(BASE + "/imports/preview", content="{broken", headers={**headers,
        "Content-Type": "application/json"}).status_code == 422
    oversized = client.post(BASE + "/imports/preview", content=b"{}", headers={**headers,
        "Content-Type": "application/json", "Content-Length": str(50 * 1024 * 1024 + 1)})
    assert oversized.status_code == 413


def test_import_missing_draft_returns_readable_422_without_writes(tmp_path):
    client, headers, database = client_and_headers(tmp_path)
    created = client.post(BASE + "/tags", json={"display_name": "保留", "content": " Raw,\nText "}, headers=headers)
    assert created.status_code == 200
    store = PersonalTagStore(database)
    before = export_bundle(store)
    revision = store.library_revision
    document = {"format": "anima-personal-tags", "version": 1,
                "source_key": "personal-library", "categories": [], "tags": [], "combinations": []}
    response = client.post(BASE + "/imports/preview", json={"document": document}, headers=headers)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_request"
    assert "draft" in response.json()["error"]["message"]
    assert export_bundle(store) == before
    assert store.library_revision == revision
    accepted = client.post(BASE + "/imports/preview", json={"document": {**document, "draft": None}}, headers=headers)
    assert accepted.status_code == 200, accepted.text


def test_category_and_combination_restore_conflicts(tmp_path):
    client, headers, _ = client_and_headers(tmp_path)
    parent = client.post(BASE + "/categories", json={"name": "parent"}, headers=headers).json()
    child = client.post(BASE + "/categories", json={"name": "child", "parent_id": parent["id"]},
                        headers=headers).json()
    edited = client.put(BASE + "/categories/" + child["id"],
                        json={"value": {"name": "edited", "parent_id": parent["id"]},
                              "expected_revision": 1}, headers=headers)
    assert edited.status_code == 200
    stale = client.put(BASE + "/categories/" + child["id"],
                       json={"value": {"name": "stale"}, "expected_revision": 1}, headers=headers)
    assert stale.status_code == 409 and stale.json()["error"]["details"]["current"]["name"] == "edited"
    detached = client.put(BASE + "/categories/" + child["id"],
                          json={"value": {"name": "edited"}, "expected_revision": 2}, headers=headers).json()
    trashed_parent = client.delete(BASE + "/categories/" + parent["id"], params={"expected_revision": 1},
                                   headers={**headers, "Content-Type": "application/json"})
    assert trashed_parent.status_code == 200
    assert client.put(BASE + "/categories/" + child["id"],
                      json={"value": {"name": "edited", "parent_id": parent["id"]},
                            "expected_revision": detached["revision"]}, headers=headers).status_code == 422
    restored_parent = client.post(BASE + "/categories/" + parent["id"] + "/restore",
                                  json={"expected_revision": trashed_parent.json()["revision"]}, headers=headers)
    assert restored_parent.status_code == 200

    item = {"id": "snap", "source_tag_id": None, "display_name": "raw", "content": "RAW",
            "kind": "tag", "polarity": "positive", "weight": 1.0}
    combination = client.post(BASE + "/combinations", json={"name": "first", "items": [item]}, headers=headers).json()
    edited = client.put(BASE + "/combinations/" + combination["id"],
                        json={"value": {"name": "second", "items": [item]}, "expected_revision": 1},
                        headers=headers)
    assert edited.status_code == 200
    stale = client.put(BASE + "/combinations/" + combination["id"],
                       json={"value": {"name": "lost", "items": []}, "expected_revision": 1}, headers=headers)
    assert stale.status_code == 409
    assert stale.json()["error"]["details"]["current"]["items"][0]["content"] == "RAW"
    deleted = client.delete(BASE + "/combinations/" + combination["id"], params={"expected_revision": 2},
                            headers={**headers, "Content-Type": "application/json"})
    assert deleted.status_code == 200 and deleted.json()["deleted_at"]
    assert client.get(BASE + "/combinations", headers=headers).json() == []
    assert len(client.get(BASE + "/combinations", params={"trash": True}, headers=headers).json()) == 1
    restored = client.post(BASE + "/combinations/" + combination["id"] + "/restore",
                           json={"expected_revision": 3}, headers=headers)
    assert restored.status_code == 200 and restored.json()["deleted_at"] is None
