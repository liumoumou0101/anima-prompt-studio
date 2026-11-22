from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient
import pytest

from test_api import reference_db
from anima_prompt_studio_v3.api import create_api_runtime
from anima_prompt_studio_v3.data.store import ReferenceDataStore
from anima_prompt_studio_v3.storage.identity_preferences import IdentityPreferences


@pytest.fixture
def identity_db(reference_db):
    with sqlite3.connect(reference_db) as db:
        db.execute("UPDATE tags SET cn_terms=? WHERE name='touhou'", ('["博丽灵梦"]',))
        db.execute("INSERT INTO tag_search(term,canonical) VALUES('博丽灵梦','touhou')")
        db.execute("INSERT INTO tag_aliases(alias,tag_id,source,status) SELECT 'はくれいれいむ',id,'fixture_verified','active' FROM tags WHERE name='hakurei_reimu'")
        db.execute("INSERT INTO tag_search(term,canonical) VALUES('はくれいれいむ','hakurei_reimu')")
        db.execute("INSERT INTO tag_aliases(alias,tag_id,source,status) SELECT 'obsolete_reimu',id,'fixture','deleted' FROM tags WHERE name='hakurei_reimu'")
        db.execute("INSERT INTO tag_cooccurrence(tag_id,related_tag_id,cooc_count,pmi,npmi,rank,score_version) SELECT a.id,b.id,100,1,0.5,1,'fixture' FROM tags a,tags b WHERE a.name='hakurei_reimu' AND b.name='touhou'")
    return reference_db


@pytest.fixture
def identity_client(identity_db, tmp_path):
    runtime = create_api_runtime(identity_db, workspace_db=tmp_path / "workspaces.db")
    with TestClient(runtime.app, base_url="http://127.0.0.1") as client:
        client.headers["Origin"] = "http://127.0.0.1"
        token = client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token}).json()["session_token"]
        client.headers["X-Anima-Session"] = token
        yield client


def test_classification_and_verified_names_precede_associated_terms(identity_db):
    with ReferenceDataStore(identity_db) as store:
        result = store.search_identities("博丽灵梦", category="character")
        assert result[0]["name"] == "hakurei_reimu"
        assert result[0]["match_kind"] == "cn_name"
        assert store.search("博丽灵梦")[0]["name"] == "hakurei_reimu"
        assert store.search_identities("博丽灵梦", category="copyright")[0]["match_kind"] == "related_term"
        assert store.search_identities("hakurei reimu", category="character")[0]["match_rank"] == 0
        assert store.search_identities("はくれい", category="character")[0]["match_kind"] == "alias"
        assert store.search("はくれい")[0]["name"] == "hakurei_reimu"
        assert store.search_identities("obsolete_reimu", category="character") == []
        assert store.search_identities("%", category="character") == []


def test_artists_are_searched_even_when_absent_from_tags(identity_db):
    with sqlite3.connect(identity_db) as db:
        db.execute("INSERT INTO artists(name,render_name,post_count) VALUES('standalone_artist','@standalone artist',30)")
    with ReferenceDataStore(identity_db) as store:
        assert store.get_tag("standalone_artist") is None
        result = store.search_identities("@standalone", category="artist")
        assert result[0]["name"] == "standalone_artist"
        assert result[0]["match_kind"] == "canonical"


def test_identity_lookup_reports_unknown_model_knowledge_and_only_suggests_series(identity_client):
    result = identity_client.get("/api/v3/identities/search", params={"kind": "character", "q": "博丽灵梦", "model_profile_id": "animayume_v1_5_base"})
    assert result.status_code == 200, result.text
    item = result.json()["items"][0]
    assert item["knowledge"]["status"] == "unknown"
    assert item["knowledge"]["model_profile_id"] == "animayume_v1_5_base"
    assert item["related_series"][0]["name"] == "touhou"
    assert item["related_series"][0]["source"] == "data_pack_cooccurrence"
    assert identity_client.app.state.workspace_store.list() == []


def test_favorites_recent_aliases_persist_without_mutating_reference(identity_client, identity_db):
    original = identity_db.read_bytes()
    client = identity_client
    assert client.put("/api/v3/identities/favorite", json={"kind": "character", "name": "hakurei_reimu", "enabled": True}).status_code == 200
    assert client.post("/api/v3/identities/used", json={"kind": "character", "names": ["hakurei_reimu", "unlisted_hero"]}).status_code == 200
    assert client.put("/api/v3/identities/alias", json={"kind": "character", "name": "hakurei_reimu", "alias": "私のれいむ"}).status_code == 200
    item = client.get("/api/v3/identities/search", params={"kind": "character", "q": "私のれ"}).json()["items"][0]
    assert item["name"] == "hakurei_reimu"
    assert item["match_source"] == "user"
    assert item["favorite"]
    reopened = IdentityPreferences(client.app.state.identity_preferences.path).list("character")
    assert {item["name"] for item in reopened["recent"]} == {"hakurei_reimu", "unlisted_hero"}
    assert reopened["aliases"][0]["alias"] == "私のれいむ"
    assert identity_db.read_bytes() == original
    assert client.request("DELETE", "/api/v3/identities/alias", json={"kind": "character", "alias": "私のれいむ"}).status_code == 200
    assert client.get("/api/v3/identities/search", params={"kind": "character", "q": "私のれ"}).json()["items"] == []


def test_alias_conflicts_and_wrong_categories_are_explicit(identity_client):
    client = identity_client
    assert client.put("/api/v3/identities/alias", json={"kind": "artist", "name": "first", "alias": "same"}).status_code == 200
    conflict = client.put("/api/v3/identities/alias", json={"kind": "artist", "name": "second", "alias": "same"})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "identity_alias_conflict"
    assert client.put("/api/v3/identities/favorite", json={"kind": "character", "name": "touhou", "enabled": True}).status_code == 422
    assert client.get("/api/v3/identities/search", params={"kind": "general", "q": "maid"}).status_code == 422
    assert client.post("/api/v3/identities/used", json={"kind": "artist", "names": ["@"]}).status_code == 422


def test_identity_preferences_require_session_and_same_origin(identity_client):
    client = identity_client
    assert client.put("/api/v3/identities/favorite", json={"kind": "artist", "name": "foo", "enabled": True},
                      headers={"Origin": "https://example.org"}).status_code == 403
    client.headers.pop("X-Anima-Session")
    assert client.get("/api/v3/identities/search", params={"kind": "artist", "q": "foo"}).status_code == 401
