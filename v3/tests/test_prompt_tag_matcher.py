import sqlite3

from test_api import reference_db, client_and_session
from anima_prompt_studio_v3.core.prompt_tag_matcher import prompt_tag_matches
from anima_prompt_studio_v3.data.store import ReferenceDataStore


def add_tags(database, names):
    with sqlite3.connect(database) as connection:
        connection.executemany("INSERT INTO tags(name,render_name,category,category_name,post_count) VALUES(?,?,0,'general',100)",
            [(name, name.replace("_", " ")) for name in names])


def test_natural_english_uses_longest_boundary_phrases_and_active_aliases(reference_db):
    add_tags(reference_db, ["hair", "watercolor_(medium)"])
    with ReferenceDataStore(reference_db) as store:
        result = prompt_tag_matches(store, r"A maid uniform with blonde hair, soft watercolor \(medium\). Blonde hair and twin tails.")
    assert result["tags"] == ["maid", "blonde_hair", "watercolor_(medium)", "twintails"]
    assert result["matches"][0]["match_kind"] == "alias"
    assert result["matches"][1]["match_kind"] == "canonical"
    assert result["method"] == "dictionary_phrases"
    assert result["data_pack_id"] == "anima-v3-api-test-r1"


def test_excludes_artists_lora_associated_terms_and_substrings(reference_db):
    with sqlite3.connect(reference_db) as connection:
        connection.execute("UPDATE tags SET cn_terms='[\"associated_concept\"]' WHERE name='maid'")
        connection.execute("INSERT INTO tag_aliases SELECT 'former_uniform',id,'danbooru','deleted' FROM tags WHERE name='maid'")
    with ReferenceDataStore(reference_db) as store:
        result = prompt_tag_matches(store, "maidenhood, 女仆, associated concept, former uniform, @maid, <LoRA:blonde_hair:1>, sample_a, sample_artist_a")
        weighted = prompt_tag_matches(store, "(blonde hair:1.2), <lora:maid:1>, full_body")
    assert result["tags"] == []
    assert weighted["tags"] == ["blonde_hair", "full_body"]


def test_limits_to_fifty_distinct_tags_and_reports_truncation(reference_db):
    names = [f"topic_{index:02}" for index in range(55)]
    add_tags(reference_db, names)
    with ReferenceDataStore(reference_db) as store:
        result = prompt_tag_matches(store, ", ".join(names), limit=100)
    assert result["tags"] == names[:50]
    assert result["truncated"] is True


def test_recognition_api_uses_session_and_validates_limits(reference_db):
    client, token = client_and_session(reference_db)
    with client:
        client.headers["Origin"] = "http://127.0.0.1"
        endpoint = "/api/v3/tags/from-prompt"
        assert client.post(endpoint, json={"prompt": "blonde hair"}).status_code == 401
        response = client.post(endpoint, headers={"X-Anima-Session": token}, json={"prompt": "A maid uniform with blonde hair"})
        assert response.status_code == 200, response.text
        assert response.json()["tags"] == ["maid", "blonde_hair"]
        assert client.post(endpoint, headers={"X-Anima-Session": token}, json={"prompt": "maid", "limit": 51}).status_code == 422
