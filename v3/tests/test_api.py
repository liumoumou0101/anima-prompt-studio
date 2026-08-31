from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

import pytest
from fastapi.testclient import TestClient

from anima_prompt_studio.domain.execution_models import GenerationRun, GenerationRunState
from anima_prompt_studio.repositories import SQLiteRepository

from anima_prompt_studio_v3.adapters.v2 import (
    V2GalleryReadService,
    V2NaturalLanguageIntentAdapter,
    build_v2_local_translation_adapter,
)
from anima_prompt_studio_v3.api import LocalApiServer, SessionManager, create_api_runtime
from anima_prompt_studio_v3.api.app import (
    _LocalExclusionEvidence,
    _LocalIndexMatch,
    _back_translate_scene_plan,
    _confirmed_source_matches,
    _local_exclusion_concept_matches,
)
from anima_prompt_studio_v3.data import (
    DataPackSnapshot,
    ReferenceBuildInputs,
    ReferenceDatabaseBuilder,
    UpstreamSource,
)
from anima_prompt_studio_v3.data.contracts import sha256_file


FIXTURES = Path(__file__).parent / "fixtures" / "upstream_current"
SEARCH_COMMIT = "0636f762694fc436b4ac472cf59b85d172eaaac4"
ORIGIN = "http://127.0.0.1"


@pytest.fixture
def reference_db(tmp_path: Path) -> Path:
    database = tmp_path / "reference.db"
    ReferenceDatabaseBuilder(
        ReferenceBuildInputs(
            tags=FIXTURES / "tags_enhanced.csv",
            aliases=FIXTURES / "tag_aliases.csv",
            tag_cooccurrence=FIXTURES / "cooccurrence_clean.csv",
            artist_cooccurrence=FIXTURES / "tag_artist_cooc.csv",
            tag_groups=FIXTURES / "tag_groups.json",
        ),
        pack_id="anima-v3-api-test-r1",
        snapshot=DataPackSnapshot(
            target_cutoff=date(2025, 9, 30),
            cutoff_mode="approximate",
            source_observed_at=date(2026, 8, 25),
            corpus_size=100_000,
            corpus_size_mode="estimated",
        ),
        sources=[
            UpstreamSource(
                name="DanbooruSearchOnline",
                repository="https://github.com/SuzumiyaAkizuki/DanbooruSearchOnline",
                commit=SEARCH_COMMIT,
                license="GPL-3.0",
            )
        ],
    ).build(database, tmp_path / "data-pack.json")
    return database


def client_and_session(reference_db: Path) -> tuple[TestClient, str]:
    runtime = create_api_runtime(reference_db)
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
    response = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200
    return client, response.json()["session_token"]


def test_health_session_exchange_is_one_time_and_bootstrap_is_protected(reference_db: Path) -> None:
    runtime = create_api_runtime(reference_db, app_version="3.0.0-test")
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["data_pack_ready"] is True
    unauthorized = client.get("/api/v3/bootstrap")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "session_invalid"

    exchanged = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": ORIGIN},
    )
    assert exchanged.status_code == 200
    token = exchanged.json()["session_token"]
    reused = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": ORIGIN},
    )
    assert reused.status_code == 401

    bootstrap = client.get("/api/v3/bootstrap", headers={"X-Anima-Session": token})
    assert bootstrap.status_code == 200
    assert bootstrap.json()["app_version"] == "3.0.0-test"
    assert bootstrap.json()["data_pack"] == {
        "id": "anima-v3-api-test-r1",
        "ready": True,
        "cutoff_mode": "approximate",
    }
    assert "access-control-allow-origin" not in bootstrap.headers


def test_tag_search_detail_related_and_artist_endpoints_are_read_only(reference_db: Path) -> None:
    original_hash = sha256_file(reference_db)
    client, token = client_and_session(reference_db)
    auth = {"X-Anima-Session": token}
    write_auth = {**auth, "Origin": ORIGIN}

    search = client.get("/api/v3/tags/search", params={"q": "女仆"}, headers=auth)
    assert search.status_code == 200
    assert search.json()["items"][0]["name"] == "maid"
    assert search.json()["items"][0]["display_name"] == "maid"

    browse = client.get("/api/v3/tags/browse", headers=auth)
    assert browse.status_code == 200
    assert browse.json()["featured"][0]["name"] == "touhou"
    assert browse.json()["groups"][0]["name"] == "attire"
    assert [item["name"] for item in browse.json()["groups"][0]["items"]] == ["maid", "frilled_apron"]
    assert browse.json()["other_groups"] == [{
        "id": "tag_group:colors",
        "name": "colors",
        "cn_name": "颜色",
        "tag_count": 1,
    }]
    assert browse.json()["ungrouped"]["total"] == 4
    assert browse.json()["ungrouped"]["safe_count"] == 3
    assert browse.json()["ungrouped"]["nsfw_count"] == 1
    assert "underwear" not in {item["name"] for item in browse.json()["ungrouped"]["items"]}

    ungrouped = client.get(
        "/api/v3/tags/ungrouped",
        params={"category": "general", "safety": "safe", "limit": 10},
        headers=auth,
    )
    assert ungrouped.status_code == 200
    assert [item["name"] for item in ungrouped.json()["items"]] == ["twintails"]
    assert ungrouped.json()["summary"]["total"] == 4

    nsfw_only = client.get(
        "/api/v3/tags/ungrouped",
        params={"category": "general", "safety": "nsfw", "heat": "longtail"},
        headers=auth,
    )
    assert nsfw_only.status_code == 200
    assert [item["name"] for item in nsfw_only.json()["items"]] == ["underwear"]
    assert nsfw_only.json()["items"][0]["nsfw"] is True

    group = client.get("/api/v3/tag-groups/attire", params={"q": "apron", "limit": 1}, headers=auth)
    assert group.status_code == 200
    assert group.json()["group"]["title"] == "服装"
    assert group.json()["total"] == 1
    assert group.json()["items"][0]["name"] == "frilled_apron"
    assert group.json()["has_more"] is False

    detail = client.get("/api/v3/tags/maid_uniform", headers=auth)
    assert detail.status_code == 200
    assert detail.json()["name"] == "maid"
    assert detail.json()["aliases"] == ["maid_uniform"]
    assert detail.json()["related"][0]["name"] == "frilled_apron"

    related = client.post(
        "/api/v3/related-tags",
        json={"tags": ["maid"], "excluded": ["frilled_apron"], "categories": ["general"], "limit": 5},
        headers=write_auth,
    )
    assert related.status_code == 200
    assert related.json()["items"][0]["name"] == "twintails"

    artists = client.post(
        "/api/v3/artists/recommend",
        json={"tags": ["maid", "twintails"], "limit": 5},
        headers=write_auth,
    )
    assert artists.status_code == 200
    assert artists.json()["items"][0]["name"] == "sample_artist_a"

    artist_search = client.get(
        "/api/v3/artists/search",
        params={"q": "@sample artist a"},
        headers=auth,
    )
    assert artist_search.status_code == 200
    assert artist_search.json()["summary"] == {
        "artist_count": 2,
        "post_count": 1500,
        "association_count": 3,
    }
    assert [item["name"] for item in artist_search.json()["items"]] == ["sample_artist_a"]
    assert [item["name"] for item in artist_search.json()["items"][0]["preview_tags"]] == ["maid", "twintails"]

    artist_detail = client.get("/api/v3/artists/sample_artist_a", headers=auth)
    assert artist_detail.status_code == 200
    assert artist_detail.json()["render_name"] == "@sample artist a"
    assert [item["name"] for item in artist_detail.json()["contexts"]] == ["maid", "twintails"]
    assert artist_detail.json()["contexts"][0]["dimensions"] == ["appearance"]
    assert artist_detail.json()["contexts"][0]["coverage"] == pytest.approx(0.5714)
    assert artist_detail.json()["analysis_note"].endswith("不是 ANIMA 生成质量评分。")

    missing_artist = client.get("/api/v3/artists/missing_artist", headers=auth)
    assert missing_artist.status_code == 404
    assert missing_artist.json()["error"]["code"] == "artist_not_found"
    assert sha256_file(reference_db) == original_hash


def test_loopback_host_origin_content_type_and_error_contract_are_enforced(reference_db: Path) -> None:
    runtime = create_api_runtime(reference_db)
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)

    bad_origin = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": "https://evil.example"},
    )
    assert bad_origin.status_code == 403
    assert bad_origin.json()["error"]["code"] == "invalid_request"

    missing_content_type = client.post(
        "/api/v3/session/exchange",
        content="{}",
        headers={"Origin": ORIGIN, "Content-Type": "text/plain"},
    )
    assert missing_content_type.status_code == 415

    bad_host_client = TestClient(runtime.app, base_url="http://evil.example", raise_server_exceptions=False)
    bad_host = bad_host_client.get("/health")
    assert bad_host.status_code == 400
    error = bad_host.json()["error"]
    assert set(error) == {"code", "message", "details", "request_id", "retryable"}
    assert error["request_id"].startswith("req_")


def test_missing_data_pack_degrades_bootstrap_and_blocks_queries(tmp_path: Path) -> None:
    runtime = create_api_runtime(tmp_path / "missing.db")
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
    exchanged = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": ORIGIN},
    )
    token = exchanged.json()["session_token"]
    auth = {"X-Anima-Session": token}

    bootstrap = client.get("/api/v3/bootstrap", headers=auth)
    assert bootstrap.status_code == 200
    assert bootstrap.json()["data_pack"]["ready"] is False
    search = client.get("/api/v3/tags/search", params={"q": "maid"}, headers=auth)
    assert search.status_code == 503
    assert search.json()["error"]["code"] == "data_pack_missing"


def test_v3_settings_reuses_v2_remote_profile_store_without_exposing_credentials(
    reference_db: Path,
    tmp_path: Path,
) -> None:
    v2_database = tmp_path / "v2.db"
    repository = SQLiteRepository(v2_database)
    try:
        from anima_prompt_studio.domain.execution_models import RemoteAuthType, RemoteProfile

        repository.save_remote_profile(RemoteProfile(
            id="existing",
            display_name="旧云主机",
            ssh_host="old.example",
            ssh_user="root",
            auth_type=RemoteAuthType.PRIVATE_KEY,
            private_key_path="C:/keys/old",
            known_host_fingerprint="SHA256:old",
        ))
    finally:
        repository.close()
    runtime = create_api_runtime(reference_db, v2_database=v2_database)
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
    exchanged = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": ORIGIN},
    )
    write_auth = {"X-Anima-Session": exchanged.json()["session_token"], "Origin": ORIGIN}

    listed = client.get("/api/v3/settings/remote-profiles", headers=write_auth)
    assert listed.status_code == 200
    assert listed.json()["items"][0]["host_fingerprint_confirmed"] is True
    assert "known_host_fingerprint" not in listed.json()["items"][0]

    updated = client.put(
        "/api/v3/settings/remote-profiles/existing",
        json={
            "display_name": "新云主机",
            "ssh_host": "new.example",
            "ssh_port": 2222,
            "ssh_user": "root",
            "auth_type": "private_key",
            "private_key_path": "C:/keys/old",
            "enabled": True,
            "remember_password": True,
        },
        headers=write_auth,
    )
    assert updated.status_code == 200
    assert updated.json()["host_fingerprint_confirmed"] is False
    unavailable = client.post(
        "/api/v3/settings/remote-profiles/existing/test-connection",
        json={},
        headers=write_auth,
    )
    assert unavailable.status_code == 409
    assert unavailable.json()["error"]["code"] == "ssh_host_key_unconfirmed"
    created = client.post(
        "/api/v3/settings/remote-profiles",
        json={
            "display_name": "新增默认云主机",
            "ssh_host": "preferred.example",
            "ssh_port": 23,
            "ssh_user": "root",
            "auth_type": "agent",
            "enabled": True,
        },
        headers=write_auth,
    )
    assert created.status_code == 201
    repository = SQLiteRepository(v2_database)
    try:
        profile = repository.get_remote_profile("existing")
        assert profile.ssh_host == "new.example"
        assert profile.known_host_fingerprint == ""
        assert repository.get_setting("last_remote_profile_id") == created.json()["id"]
    finally:
        repository.close()

    selected = client.put(
        "/api/v3/settings/default-remote-profile",
        json={"remote_profile_id": "existing"},
        headers=write_auth,
    )
    assert selected.status_code == 200
    assert selected.json() == {"remote_profile_id": "existing"}
    repository = SQLiteRepository(v2_database)
    try:
        assert repository.get_setting("last_remote_profile_id") == "existing"
    finally:
        repository.close()


def test_v3_settings_can_test_ssh_tunnel_and_comfyui_without_v2_ui(
    reference_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from anima_prompt_studio.domain.execution_models import RemoteAuthType, RemoteProfile
    from anima_prompt_studio.services.remote import comfy_client, ssh_tunnel

    v2_database = tmp_path / "v2.db"
    repository = SQLiteRepository(v2_database)
    try:
        repository.save_remote_profile(RemoteProfile(
            id="v3-ready",
            display_name="V3 新连接",
            ssh_host="new.example",
            ssh_user="root",
            auth_type=RemoteAuthType.AGENT,
            known_host_fingerprint="SHA256:confirmed",
        ))
    finally:
        repository.close()

    events: list[str] = []

    class FakeTunnel:
        base_url = "http://127.0.0.1:45678"

        def __init__(self, profile) -> None:
            assert profile.id == "v3-ready"

        def open(self, credentials):
            events.append("ssh")
            return self

        def close(self) -> None:
            events.append("close")

    class FakeComfyClient:
        def __init__(self, base_url: str) -> None:
            assert base_url == FakeTunnel.base_url

        def validate_environment(self):
            events.append("comfy")
            return type("Report", (), {
                "devices": ["NVIDIA Test GPU"],
                "queue_running": 1,
                "queue_pending": 2,
            })()

    monkeypatch.setattr(ssh_tunnel, "SshTunnel", FakeTunnel)
    monkeypatch.setattr(comfy_client, "ComfyUIClient", FakeComfyClient)
    runtime = create_api_runtime(reference_db, v2_database=v2_database)
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
    exchanged = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": ORIGIN},
    )
    response = client.post(
        "/api/v3/settings/remote-profiles/v3-ready/test-connection",
        json={},
        headers={"X-Anima-Session": exchanged.json()["session_token"], "Origin": ORIGIN},
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "devices": ["NVIDIA Test GPU"],
        "queue_running": 1,
        "queue_pending": 2,
        "comfy_endpoint": "127.0.0.1:8188",
    }
    assert events == ["ssh", "comfy", "close"]


def test_session_manager_revoke_invalidates_token() -> None:
    manager = SessionManager()
    exchange = manager.exchange(manager.issue_bootstrap_token())
    assert manager.validate(exchange.token) is True
    manager.revoke(exchange.token)
    assert manager.validate(exchange.token) is False


def test_local_api_server_uses_random_loopback_port_and_stops(reference_db: Path) -> None:
    server = LocalApiServer(reference_db, app_version="3.0.0-test")
    with server:
        parsed = urlsplit(server.bootstrap_url)
        assert parsed.hostname == "127.0.0.1"
        assert parsed.port == server.port
        assert parse_qs(parsed.query)["bootstrap"] == [server.runtime.bootstrap_token]
        with urlopen(f"{server.base_url}/health", timeout=5) as response:
            assert json.loads(response.read())["status"] == "ok"

        payload = json.dumps({"bootstrap_token": server.runtime.bootstrap_token}).encode("utf-8")
        request = Request(
            f"{server.base_url}/api/v3/session/exchange",
            data=payload,
            headers={"Content-Type": "application/json", "Origin": server.base_url},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            session_token = json.loads(response.read())["session_token"]

        detail_request = Request(
            f"{server.base_url}/api/v3/tags/maid",
            headers={"X-Anima-Session": session_token},
        )
        with urlopen(detail_request, timeout=5) as response:
            assert json.loads(response.read())["name"] == "maid"
    with pytest.raises(RuntimeError, match="尚未启动"):
        _ = server.port


def test_frontend_dist_serves_assets_and_spa_without_masking_api_404(
    reference_db: Path,
    tmp_path: Path,
) -> None:
    frontend_dist = tmp_path / "dist"
    assets = frontend_dist / "assets"
    assets.mkdir(parents=True)
    (frontend_dist / "index.html").write_text("<main>ANIMA V3</main>", encoding="utf-8")
    (assets / "app.js").write_text("window.anima = true", encoding="utf-8")

    runtime = create_api_runtime(reference_db, frontend_dist=frontend_dist)
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)

    assert client.get("/").text == "<main>ANIMA V3</main>"
    assert client.get("/tags/maid").text == "<main>ANIMA V3</main>"
    assert client.get("/assets/app.js").text == "window.anima = true"

    missing_api = client.get("/api/v3/does-not-exist")
    assert missing_api.status_code == 404
    assert missing_api.json()["error"]["code"] == "not_found"


def test_workbench_candidate_endpoint_runs_validated_lanes(reference_db: Path) -> None:
    client, token = client_and_session(reference_db)
    response = client.post(
        "/api/v3/workbench/candidates",
        json={
            "source_text": "女仆装、双马尾，不要金发",
            "source_language": "zh",
            "model_profile": "anima_base_v1",
            "elements": [
                {"id": "e_maid", "text": "女仆装", "canonical_tag": "maid_uniform", "state": "locked"},
                {"id": "e_hair", "text": "双马尾", "state": "required"},
                {
                    "id": "e_excluded",
                    "text": "不要金发",
                    "canonical_tag": "blonde_hair",
                    "state": "excluded",
                },
            ],
        },
        headers={"X-Anima-Session": token, "Origin": ORIGIN},
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["lane"] for item in payload["candidates"]] == ["literal"]
    assert payload["tag_suggestions"]
    assert payload["candidates"][0]["positive_prompt"] == "score_7, maid, twintails"
    assert payload["candidates"][0]["negative_prompt"].endswith("blonde hair")
    assert payload["validation"]["valid"] is True
    assert [item["name"] for item in payload["artist_suggestions"]] == ["sample_artist_a"]
    assert all(not item["artists"] for item in payload["candidates"])
    assert payload["data_pack_id"] == "anima-v3-api-test-r1"


def test_natural_language_parse_endpoint_returns_v3_intent_and_reports_availability(
    reference_db: Path,
) -> None:
    class FakeExtractClient:
        name = "测试抽取器"

        def complete_json(self, _system: str, _user: str) -> dict[str, object]:
            return {
                "summary_zh": "白发少女在雨夜街道撑伞",
                "people_count": 1,
                "subject_mode": "character",
                "content_rating": "safe",
                "scene_type": "portrait",
                "anima_prompt_en": "A white-haired girl holding an umbrella on a rainy street.",
                "anima_negative_en": ["text"],
                "characters": [{
                    "label": "少女",
                    "identity": "年轻女性",
                    "appearance": ["白发"],
                    "action": "撑伞",
                }],
                "scene": {"location": "雨夜街道", "weather": "下雨"},
                "camera": {"shot": "全身"},
                "negatives": ["文字"],
            }

    runtime = create_api_runtime(
        reference_db,
        intent_parser=V2NaturalLanguageIntentAdapter(FakeExtractClient()),
    )
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
    exchanged = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": ORIGIN},
    )
    headers = {"X-Anima-Session": exchanged.json()["session_token"], "Origin": ORIGIN}

    bootstrap = client.get(
        "/api/v3/bootstrap",
        headers={"X-Anima-Session": headers["X-Anima-Session"]},
    )
    assert bootstrap.json()["features"]["natural_language_parse"] is True

    response = client.post(
        "/api/v3/intent/parse",
        json={"source_text": "白发少女在雨夜街道撑伞。", "source_language": "zh"},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["parser"] == {"name": "测试抽取器", "source": "v2_ai_extract"}
    assert payload["intent"]["scene_plan_en"].startswith("A white-haired girl")
    assert payload["intent"]["scene_negative_en"] == ["text"]
    assert {item["original_text"] for item in payload["intent"]["graph"]["elements"]} >= {
        "年轻女性",
        "白发",
        "撑伞",
        "雨夜街道",
        "文字",
    }

    candidates = client.post(
        "/api/v3/prompt-candidates",
        json={"intent": payload["intent"], "model_profile": "anima_base_v1"},
        headers=headers,
    )
    assert candidates.status_code == 200
    generated = candidates.json()
    assert generated["validation"]["valid"] is True
    assert generated["candidates"][-1]["lane"] == "hybrid"
    assert generated["candidates"][-1]["positive_prompt"].endswith(
        "A white-haired girl holding an umbrella on a rainy street"
    )

    unavailable_client, unavailable_token = client_and_session(reference_db)
    unavailable = unavailable_client.post(
        "/api/v3/intent/parse",
        json={"source_text": "白发少女"},
        headers={"X-Anima-Session": unavailable_token, "Origin": ORIGIN},
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "intent_parser_unavailable"


def test_local_natural_candidate_endpoint_uses_only_local_translation(
    reference_db: Path,
    tmp_path: Path,
) -> None:
    translator = build_v2_local_translation_adapter(tmp_path / "missing-resources")
    runtime = create_api_runtime(reference_db, translation_service=translator)
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
    exchange = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": ORIGIN},
    )
    headers = {"X-Anima-Session": exchange.json()["session_token"], "Origin": ORIGIN}

    response = client.post(
        "/api/v3/local-natural/candidates",
        json={"source_text": "女仆，双马尾", "model_profile": "anima_aesthetic_v1"},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["local_translation"]["local_only"] is True
    assert payload["candidates"][0]["positive_prompt"] == "maid, twintails"
    assert {item["canonical_tag"] for item in payload["intent"]["graph"]["elements"]} == {
        "maid",
        "twintails",
    }
    assert {item["canonical_tag"] for item in payload["scene_draft"]["confirmed"]} == {
        "maid",
        "twintails",
    }
    assert next(
        item for item in payload["scene_draft"]["confirmed"] if item["canonical_tag"] == "maid"
    )["fact_type"] == "clothing"


def test_local_natural_candidate_separates_inline_and_explicit_exclusions(
    reference_db: Path,
    tmp_path: Path,
) -> None:
    translator = build_v2_local_translation_adapter(tmp_path / "missing-resources")
    runtime = create_api_runtime(reference_db, translation_service=translator)
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
    exchange = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": ORIGIN},
    )
    headers = {"X-Anima-Session": exchange.json()["session_token"], "Origin": ORIGIN}

    response = client.post(
        "/api/v3/local-natural/candidates",
        json={
            "source_text": "女仆，不要金发",
            "excluded_text": "内衣",
            "model_profile": "anima_aesthetic_v1",
        },
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    literal = payload["candidates"][0]
    assert literal["positive_prompt"] == "maid"
    assert "blonde hair" in literal["negative_prompt"]
    assert "underwear" in literal["negative_prompt"]
    assert "blonde hair" not in literal["positive_prompt"]
    assert "underwear" not in literal["positive_prompt"]
    assert {item["canonical_tag"] for item in payload["scene_draft"]["exclusions"]} == {
        "blonde_hair",
        "underwear",
    }
    excluded_elements = [item for item in payload["intent"]["graph"]["elements"] if item["state"] == "excluded"]
    assert {item["canonical_tag"] for item in excluded_elements} == {"blonde_hair", "underwear"}
    assert "不要金发" not in payload["local_translation"]["translated_text"]


def test_local_natural_candidate_does_not_claim_partial_tag_coverage_is_complete(
    reference_db: Path,
    tmp_path: Path,
) -> None:
    translator = build_v2_local_translation_adapter(tmp_path / "missing-resources")
    runtime = create_api_runtime(reference_db, translation_service=translator)
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
    exchange = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": ORIGIN},
    )
    headers = {"X-Anima-Session": exchange.json()["session_token"], "Origin": ORIGIN}

    response = client.post(
        "/api/v3/local-natural/candidates",
        json={"source_text": "女仆在未知场景，双马尾", "model_profile": "anima_aesthetic_v1"},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert {item["canonical_tag"] for item in payload["scene_draft"]["confirmed"]} == {"maid", "twintails"}
    assert payload["scene_draft"]["unresolved"]
    assert "只有部分原文" in payload["scene_draft"]["unresolved"][0]["reason"]
    assert "e_local_unresolved_scene" in payload["candidates"][0]["unresolved_element_ids"]


def test_local_natural_candidate_requires_user_confirmation_for_fact_ownership(
    reference_db: Path,
    tmp_path: Path,
) -> None:
    translator = build_v2_local_translation_adapter(tmp_path / "missing-resources")
    runtime = create_api_runtime(reference_db, translation_service=translator)
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
    exchange = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": ORIGIN},
    )
    auth = {"X-Anima-Session": exchange.json()["session_token"], "Origin": ORIGIN}
    request = {
        "source_text": "博丽灵梦穿女仆装",
        "translated_text": "Hakurei Reimu wears a maid outfit",
        "model_profile": "anima_aesthetic_v1",
        "selected_tags": [],
    }

    first = client.post("/api/v3/local-natural/candidates", json=request, headers=auth)
    assert first.status_code == 200
    first_payload = first.json()
    entities = first_payload["scene_draft"]["entities"]
    assert [(item["label"], item["canonical_tag"]) for item in entities] == [("博丽灵梦", "hakurei_reimu")]
    maid = next(item for item in first_payload["scene_draft"]["confirmed"] if item["canonical_tag"] == "maid")
    assert maid["owner_entity_id"] is None
    assert maid["suggested_owner_entity_id"] == entities[0]["id"]
    assert first_payload["scene_draft"]["relations"] == []
    first_maid_element = next(item for item in first_payload["intent"]["graph"]["elements"] if item["id"] == maid["id"])
    assert first_maid_element["entity_id"] is None

    second = client.post(
        "/api/v3/local-natural/candidates",
        json={**request, "fact_owners": {maid["id"]: entities[0]["id"]}},
        headers=auth,
    )
    assert second.status_code == 200
    second_payload = second.json()
    confirmed_maid = next(item for item in second_payload["scene_draft"]["confirmed"] if item["canonical_tag"] == "maid")
    assert confirmed_maid["owner_entity_id"] == entities[0]["id"]
    assert confirmed_maid["suggested_owner_entity_id"] is None
    maid_element = next(item for item in second_payload["intent"]["graph"]["elements"] if item["id"] == maid["id"])
    assert maid_element["entity_id"] == entities[0]["id"]
    assert second_payload["intent"]["graph"]["edges"] == []
    assert second_payload["scene_draft"]["relations"] == [{
        "id": "c_local_relation_1",
        "source_entity_id": entities[0]["id"],
        "target_element_id": maid["id"],
        "relation": "wearing",
        "state": "suggested",
        "phrase": "hakurei reimu wearing maid",
        "reason": "已确认服装归属；穿着关系仍需单独确认",
    }]
    assert second_payload["candidates"][0]["positive_prompt"] == first_payload["candidates"][0]["positive_prompt"]

    third = client.post(
        "/api/v3/local-natural/candidates",
        json={
            **request,
            "fact_owners": {maid["id"]: entities[0]["id"]},
            "confirmed_relations": [{
                "source_entity_id": entities[0]["id"],
                "target_element_id": maid["id"],
                "relation": "wearing",
            }],
        },
        headers=auth,
    )
    assert third.status_code == 200
    third_payload = third.json()
    assert third_payload["scene_draft"]["relations"][0]["state"] == "confirmed"
    assert third_payload["intent"]["graph"]["edges"] == [{
        "id": "c_local_relation_1",
        "source_element_id": entities[0]["source_element_id"],
        "target_element_id": maid["id"],
        "kind": "relation",
        "relation": "wearing",
        "custom_relation": None,
        "reason": "用户在 Scene Draft 中确认穿着关系",
    }]
    literal = next(item for item in third_payload["candidates"] if item["lane"] == "literal")
    hybrid = next(item for item in third_payload["candidates"] if item["lane"] == "hybrid")
    assert literal["positive_prompt"] == first_payload["candidates"][0]["positive_prompt"]
    assert "hakurei reimu wearing maid" in hybrid["positive_prompt"]


def test_local_source_resolution_confirms_only_the_unique_primary_tag_for_ambiguous_cn_term() -> None:
    matches = [
        _LocalIndexMatch("天使", "source", "angel", "cn_name", 29_980, 1, 3),
        _LocalIndexMatch("天使", "source", "halo", "cn_term", 499_728, 1, 3),
        _LocalIndexMatch("天使", "source", "angel_statue", "cn_term", 359, 1, 3),
        _LocalIndexMatch("天使", "source", "tachibana_kanade", "cn_term", 2_897, 1, 3),
        _LocalIndexMatch("女性", "source", "assertive_female", "cn_term", 18_031, 6, 8),
        _LocalIndexMatch("女性", "source", "vaginal", "cn_term", 284_069, 6, 8),
    ]

    confirmed, ambiguous = _confirmed_source_matches(matches)

    assert [item.canonical_tag for item in confirmed] == ["angel"]
    assert ambiguous == ["天使", "女性"]


def test_local_source_resolution_prefers_longer_primary_phrase_over_nested_term() -> None:
    matches = [
        _LocalIndexMatch("堕天使", "source", "fallen_angel", "cn_name", 1_176, 0, 3),
        _LocalIndexMatch("天使", "source", "angel", "cn_name", 29_980, 1, 3),
    ]

    confirmed, _ambiguous = _confirmed_source_matches(matches)

    assert [item.canonical_tag for item in confirmed] == ["fallen_angel"]


def test_broad_text_exclusion_expands_transparently_instead_of_picking_one_ambiguous_tag() -> None:
    class Store:
        @staticmethod
        def get_tag(name: str) -> dict[str, object] | None:
            if name in {"english_text", "signature", "watermark"}:
                return {"post_count": 100}
            return None

    matches = _local_exclusion_concept_matches(
        Store(),  # type: ignore[arg-type]
        (_LocalExclusionEvidence("文字和水印", 10, 15),),
        "",
    )

    assert {item.canonical_tag for item in matches} == {"english_text", "signature", "watermark"}
    assert {item.match_kind for item in matches} == {"exclusion_concept"}
    assert {item.text for item in matches} == {"文字"}
    assert {(item.start, item.end) for item in matches} == {(10, 12)}


def test_structured_workbench_uses_the_same_local_mapping_and_preserves_exclusions(
    reference_db: Path,
    tmp_path: Path,
) -> None:
    translator = build_v2_local_translation_adapter(tmp_path / "missing-resources")
    runtime = create_api_runtime(reference_db, translation_service=translator)
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
    exchange = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": ORIGIN},
    )
    headers = {"X-Anima-Session": exchange.json()["session_token"], "Origin": ORIGIN}

    response = client.post(
        "/api/v3/workbench/candidates",
        json={
            "source_text": "女仆，双马尾，不要金发",
            "source_language": "mixed",
            "model_profile": "anima_aesthetic_v1",
            "elements": [
                {"id": "e_maid", "text": "女仆", "state": "required"},
                {"id": "e_twintails", "text": "双马尾", "state": "required"},
                {"id": "e_no_blonde", "text": "金发", "state": "excluded"},
            ],
        },
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["local_translation"]["local_only"] is True
    assert payload["scene_draft"] is not None
    literal = payload["candidates"][0]
    assert literal["positive_prompt"] == "maid, twintails"
    assert "blonde hair" in literal["negative_prompt"]


def test_structured_workbench_reuses_scene_draft_translation_when_selecting_tags(
    reference_db: Path,
    tmp_path: Path,
) -> None:
    translator = build_v2_local_translation_adapter(tmp_path / "missing-resources")
    runtime = create_api_runtime(reference_db, translation_service=translator)
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
    exchange = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": ORIGIN},
    )
    headers = {"X-Anima-Session": exchange.json()["session_token"], "Origin": ORIGIN}

    response = client.post(
        "/api/v3/workbench/candidates",
        json={
            "source_text": "未知场景",
            "model_profile": "anima_aesthetic_v1",
            "translated_text": "unmapped prose baseline",
            "selected_tags": ["maid"],
            "elements": [{"id": "e_scene", "text": "未知场景", "state": "required"}],
        },
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["local_translation"]["engine"] == "当前工作台译文"
    assert payload["candidates"][0]["positive_prompt"] == "maid"


def test_local_natural_candidate_keeps_a_prose_baseline_when_no_tag_is_confirmed(
    reference_db: Path,
    tmp_path: Path,
) -> None:
    translator = build_v2_local_translation_adapter(tmp_path / "missing-resources")
    runtime = create_api_runtime(reference_db, translation_service=translator)
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
    exchange = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": ORIGIN},
    )
    headers = {"X-Anima-Session": exchange.json()["session_token"], "Origin": ORIGIN}

    response = client.post(
        "/api/v3/local-natural/candidates",
        json={"source_text": "zzqvzxq", "model_profile": "anima_aesthetic_v1"},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    literal = payload["candidates"][0]
    assert literal["lane"] == "literal"
    assert literal["positive_prompt"] == payload["local_translation"]["translated_text"]
    assert literal["tags"] == []
    assert literal["unresolved_element_ids"] == []
    assert payload["scene_draft"]["confirmed"] == []
    assert payload["scene_draft"]["unresolved"]


def test_local_natural_candidate_applies_only_explicitly_selected_suggestions(
    reference_db: Path,
    tmp_path: Path,
) -> None:
    translator = build_v2_local_translation_adapter(tmp_path / "missing-resources")
    runtime = create_api_runtime(reference_db, translation_service=translator)
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
    exchange = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": ORIGIN},
    )
    headers = {"X-Anima-Session": exchange.json()["session_token"], "Origin": ORIGIN}

    response = client.post(
        "/api/v3/local-natural/candidates",
        json={
            "source_text": "zzqvzxq",
            "translated_text": "unmapped prose baseline",
            "selected_tags": ["maid"],
            "model_profile": "anima_aesthetic_v1",
        },
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["local_translation"]["engine"] == "当前工作台译文"
    assert payload["candidates"][0]["positive_prompt"] == "maid"
    assert [item["canonical_tag"] for item in payload["scene_draft"]["confirmed"]] == ["maid"]
    assert payload["scene_draft"]["confirmed"][0]["source"] == "user_selected"
    assert payload["intent"]["scene_plan_en"]
    assert "text" in payload["scene_draft"]["back_translation"]
    assert "segments" in payload["scene_draft"]["back_translation"]


def test_local_natural_candidate_keeps_suppressed_tags_from_returning(
    reference_db: Path,
    tmp_path: Path,
) -> None:
    translator = build_v2_local_translation_adapter(tmp_path / "missing-resources")
    runtime = create_api_runtime(reference_db, translation_service=translator)
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
    exchange = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": ORIGIN},
    )
    headers = {"X-Anima-Session": exchange.json()["session_token"], "Origin": ORIGIN}
    source_text = "博丽灵梦穿女仆装"

    first = client.post(
        "/api/v3/local-natural/candidates",
        json={"source_text": source_text, "model_profile": "anima_aesthetic_v1"},
        headers=headers,
    )
    assert first.status_code == 200
    first_payload = first.json()
    confirmed = [item["canonical_tag"] for item in first_payload["scene_draft"]["confirmed"]]
    assert "hakurei_reimu" in confirmed
    assert "maid" in confirmed
    assert first_payload["scene_draft"]["back_translation"]["segments"]

    removed = client.post(
        "/api/v3/local-natural/candidates",
        json={
            "source_text": source_text,
            "translated_text": first_payload["scene_draft"]["translated_text"],
            "suppressed_tags": ["hakurei_reimu"],
            "model_profile": "anima_aesthetic_v1",
        },
        headers=headers,
    )
    assert removed.status_code == 200
    removed_payload = removed.json()
    confirmed_after = [item["canonical_tag"] for item in removed_payload["scene_draft"]["confirmed"]]
    assert "hakurei_reimu" not in confirmed_after
    assert "maid" in confirmed_after
    assert [item["canonical_tag"] for item in removed_payload["scene_draft"]["suppressed"]] == ["hakurei_reimu"]
    assert "hakurei reimu" not in removed_payload["candidates"][0]["positive_prompt"]
    leftover_notes = [note for note in removed_payload["scene_draft"]["risk_notes"] if "已移除的标签仍出现" in note]
    assert leftover_notes


def test_structured_english_tags_use_bilingual_local_review_and_suppression(
    reference_db: Path,
    tmp_path: Path,
) -> None:
    translator = build_v2_local_translation_adapter(tmp_path / "missing-resources")
    runtime = create_api_runtime(reference_db, translation_service=translator)
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
    exchange = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": ORIGIN},
    )
    headers = {"X-Anima-Session": exchange.json()["session_token"], "Origin": ORIGIN}
    request = {
        "source_text": "maid，hakurei_reimu",
        "source_language": "mixed",
        "model_profile": "anima_aesthetic_v1",
        "elements": [
            {"id": "e_positive_1", "text": "maid", "state": "required"},
            {"id": "e_positive_2", "text": "hakurei_reimu", "state": "required"},
        ],
    }

    first = client.post("/api/v3/workbench/candidates", json=request, headers=headers)
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["scene_draft"]["translated_text"] == "maid，hakurei_reimu"
    assert first_payload["scene_draft"]["scene_plan_enabled"] is False
    assert first_payload["scene_draft"]["back_translation"]["segments"] == []
    assert first_payload["intent"]["scene_plan_en"] is None
    labels = {item["canonical_tag"]: item["cn_name"] for item in first_payload["scene_draft"]["confirmed"]}
    assert labels["maid"] == "女仆"
    assert labels["hakurei_reimu"] == "博丽灵梦"
    candidate_labels = {item["name"]: item["cn_name"] for item in first_payload["candidates"][0]["tags"]}
    assert candidate_labels["maid"] == "女仆"
    assert candidate_labels["hakurei_reimu"] == "博丽灵梦"

    removed = client.post(
        "/api/v3/workbench/candidates",
        json={**request, "translated_text": first_payload["scene_draft"]["translated_text"], "suppressed_tags": ["maid"]},
        headers=headers,
    )
    assert removed.status_code == 200
    removed_payload = removed.json()
    assert "maid" not in removed_payload["candidates"][0]["positive_prompt"]
    assert [item["canonical_tag"] for item in removed_payload["scene_draft"]["suppressed"]] == ["maid"]
    assert removed_payload["scene_draft"]["unresolved"] == []


def test_back_translation_uses_one_scene_call_instead_of_one_call_per_segment() -> None:
    class CountingTranslator:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def translate(self, text: str, *, direction: str):
            self.calls.append(text)
            return type("Translation", (), {"translated_text": f"中：{text}", "engine_name": "test"})()

    translator = CountingTranslator()
    payload = _back_translate_scene_plan(
        translator,
        "A mermaid swims. Blue light crosses the water. Wide angle composition.",
        negative="worst quality, blurry",
    )

    assert len(translator.calls) == 2
    assert payload["segments"] == [{
        "en": "A mermaid swims. Blue light crosses the water. Wide angle composition.",
        "zh": "中：A mermaid swims. Blue light crosses the water. Wide angle composition.",
    }]


def test_workbench_explicit_relation_adds_hybrid_and_bad_profile_is_stable(reference_db: Path) -> None:
    client, token = client_and_session(reference_db)
    headers = {"X-Anima-Session": token, "Origin": ORIGIN}
    request = {
        "source_text": "Hakurei Reimu wearing a maid outfit",
        "source_language": "en",
        "elements": [
            {"id": "e_reimu", "text": "Hakurei Reimu", "canonical_tag": "hakurei_reimu"},
            {"id": "e_maid", "text": "maid outfit", "canonical_tag": "maid"},
        ],
        "relations": [
            {
                "id": "c_wearing",
                "source_element_id": "e_reimu",
                "target_element_id": "e_maid",
                "relation": "wearing",
            }
        ],
    }

    response = client.post("/api/v3/workbench/candidates", json=request, headers=headers)
    assert response.status_code == 200
    assert response.json()["candidates"][-1]["lane"] == "hybrid"
    assert response.json()["candidates"][-1]["positive_prompt"].endswith("hakurei reimu wearing maid")

    request["model_profile"] = "missing_profile"
    bad_profile = client.post("/api/v3/workbench/candidates", json=request, headers=headers)
    assert bad_profile.status_code == 422
    assert bad_profile.json()["error"]["code"] == "model_profile_unknown"


def test_workspace_crud_persists_separately_and_rejects_stale_revision(
    reference_db: Path,
    tmp_path: Path,
) -> None:
    original_reference_hash = sha256_file(reference_db)
    workspace_db = tmp_path / "state" / "workspaces.db"
    runtime = create_api_runtime(reference_db, workspace_db=workspace_db)
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
    exchange = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": ORIGIN},
    )
    headers = {"X-Anima-Session": exchange.json()["session_token"], "Origin": ORIGIN}
    draft = {
        "positive_text": "女仆，双马尾",
        "excluded_text": "金发",
        "model_profile": "anima_base_v1",
        "input_mode": "concepts",
        "natural_text": "",
        "selected_tags": [],
    }
    generated_snapshot = client.post(
        "/api/v3/workbench/candidates",
        json={
            "source_text": "女仆，双马尾",
            "source_language": "zh",
            "model_profile": "anima_base_v1",
            "elements": [
                {"id": "e_maid", "text": "女仆", "canonical_tag": "maid"},
                {"id": "e_hair", "text": "双马尾", "canonical_tag": "twintails"},
            ],
        },
        headers=headers,
    ).json()

    created = client.post(
        "/api/v3/workspaces",
        json={"title": "女仆测试", "draft": draft, "candidate_snapshot": generated_snapshot},
        headers=headers,
    )
    assert created.status_code == 201
    workspace = created.json()
    assert workspace["revision"] == 1
    assert workspace["draft"]["positive_text"] == draft["positive_text"]
    assert workspace["draft"]["suppressed_tags"] == []
    assert workspace["draft"]["generation_settings"] == {
        "preset_id": "balanced",
        "aspect": "portrait",
        "seed": -1,
        "batch_size": 1,
    }
    assert workspace["candidate_snapshot"]["candidates"][0]["positive_prompt"] == "score_7, maid, twintails"
    assert workspace["candidate_snapshot"]["artist_suggestions"][0]["name"] == "sample_artist_a"
    assert workspace_db.is_file()

    listed = client.get("/api/v3/workspaces", headers={"X-Anima-Session": headers["X-Anima-Session"]})
    assert listed.json()["items"][0]["id"] == workspace["id"]

    updated = client.put(
        f"/api/v3/workspaces/{workspace['id']}",
        json={"title": "女仆测试 2", "draft": {**draft, "positive_text": "女仆"}, "revision": 1},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    assert updated.json()["candidate_snapshot"] is None

    stale = client.put(
        f"/api/v3/workspaces/{workspace['id']}",
        json={"title": "旧标签页", "draft": draft, "revision": 1},
        headers=headers,
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "workspace_revision_conflict"
    assert stale.json()["error"]["details"]["current_revision"] == 2

    deleted = client.request(
        "DELETE",
        f"/api/v3/workspaces/{workspace['id']}",
        json={"revision": 2},
        headers=headers,
    )
    assert deleted.status_code == 204
    assert client.get(
        f"/api/v3/workspaces/{workspace['id']}",
        headers={"X-Anima-Session": headers["X-Anima-Session"]},
    ).status_code == 404
    assert sha256_file(reference_db) == original_reference_hash


def test_generation_bridge_preview_converts_validated_candidate_without_submitting(reference_db: Path) -> None:
    client, token = client_and_session(reference_db)
    headers = {"X-Anima-Session": token, "Origin": ORIGIN}
    generated = client.post(
        "/api/v3/workbench/candidates",
        json={
            "source_text": "女仆装、双马尾，不要金发",
            "source_language": "zh",
            "model_profile": "anima_base_v1",
            "elements": [
                {"id": "e_maid", "text": "女仆装", "canonical_tag": "maid_uniform", "state": "locked"},
                {"id": "e_hair", "text": "双马尾"},
                {"id": "e_no_blonde", "text": "金发", "canonical_tag": "blonde_hair", "state": "excluded"},
            ],
        },
        headers=headers,
    ).json()

    preview = client.post(
        "/api/v3/generation-requests/preview",
        json={
            "candidate": generated["candidates"][0],
            "intent": generated["intent"],
            "project_name": "V3 API 桥接",
            "settings": {"preset_id": "balanced", "seed": 42, "batch_size": 2},
            "workspace_id": "workspace_1",
            "workspace_revision": 3,
        },
        headers=headers,
    )

    assert preview.status_code == 200
    payload = preview.json()
    assert payload["compatible"] is True
    assert payload["bridge_schema"] == "v3-v2-generation-bridge/1"
    assert payload["prompt_job"]["positive_prompt"] == "score_7, maid, twintails"
    assert payload["prompt_job"]["negative_prompt"].endswith("blonde hair")
    assert payload["prompt_job"]["generation_params"]["steps"] == 35
    assert payload["prompt_job"]["generation_params"]["batch_size"] == 2
    assert payload["checkpoint_logical_name"] == "anima_base_v1"
    assert payload["candidate_snapshot"]["versions"]["data_pack"] == "anima-v3-api-test-r1"


def test_generation_run_api_requires_idempotency_and_exposes_safe_status(reference_db: Path) -> None:
    queue = StubGenerationQueue()
    runtime = create_api_runtime(reference_db, generation_queue=queue)
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
    exchanged = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": ORIGIN},
    )
    headers = {"X-Anima-Session": exchanged.json()["session_token"], "Origin": ORIGIN}
    generated = client.post(
        "/api/v3/workbench/candidates",
        json={
            "source_text": "女仆",
            "source_language": "zh",
            "model_profile": "anima_base_v1",
            "elements": [{"id": "e_maid", "text": "女仆", "canonical_tag": "maid", "state": "locked"}],
        },
        headers=headers,
    ).json()
    request = {
        "candidate": generated["candidates"][0],
        "intent": generated["intent"],
        "project_name": "API 队列",
        "remote_profile_id": "remote-1",
        "workflow_profile_id": "workflow-1",
    }

    missing_key = client.post("/api/v3/generation-runs", json=request, headers=headers)
    assert missing_key.status_code == 422
    assert missing_key.json()["error"]["code"] == "invalid_request"

    submit_headers = {**headers, "Idempotency-Key": "workspace-1-revision-1-literal"}
    submitted = client.post("/api/v3/generation-runs", json=request, headers=submit_headers)
    duplicate = client.post("/api/v3/generation-runs", json=request, headers=submit_headers)
    assert submitted.status_code == 202
    assert duplicate.status_code == 202
    assert submitted.json()["id"] == duplicate.json()["id"]
    assert submitted.json()["state"] == "draft"
    assert "request_json" not in submitted.json()

    run_id = submitted.json()["id"]
    status = client.get(
        f"/api/v3/generation-runs/{run_id}",
        headers={"X-Anima-Session": headers["X-Anima-Session"]},
    )
    assert status.status_code == 200
    assert status.json()["artifact_count"] == 0
    assert status.json()["available_actions"] == ["cancel_queued"]

    listed = client.get(
        "/api/v3/generation-runs",
        headers={"X-Anima-Session": headers["X-Anima-Session"]},
    )
    assert listed.json()["items"][0]["id"] == run_id

    targets = client.get(
        "/api/v3/generation-targets",
        headers={"X-Anima-Session": headers["X-Anima-Session"]},
    )
    assert targets.json()["items"][0]["workflow_profile_id"] == "workflow-1"

    canceled = client.post(
        f"/api/v3/generation-runs/{run_id}/actions",
        json={"action": "cancel_queued"},
        headers=headers,
    )
    assert canceled.status_code == 200
    assert canceled.json()["state"] == "canceled"

    bootstrap = client.get(
        "/api/v3/bootstrap",
        headers={"X-Anima-Session": headers["X-Anima-Session"]},
    )
    assert bootstrap.json()["features"]["remote_generation"] is True


def test_artist_comparison_queues_one_fixed_seed_run_per_selected_artist(reference_db: Path) -> None:
    queue = StubGenerationQueue()
    runtime = create_api_runtime(reference_db, generation_queue=queue)
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
    exchanged = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": ORIGIN},
    )
    headers = {"X-Anima-Session": exchanged.json()["session_token"], "Origin": ORIGIN}
    generated = client.post(
        "/api/v3/workbench/candidates",
        json={
            "source_text": "女仆、荷叶边围裙",
            "source_language": "zh",
            "model_profile": "anima_base_v1",
            "elements": [
                {"id": "e_maid", "text": "女仆", "canonical_tag": "maid", "state": "locked"},
                {"id": "e_apron", "text": "荷叶边围裙", "canonical_tag": "frilled_apron", "state": "locked"},
            ],
        },
        headers=headers,
    ).json()
    request = {
        "comparison_id": "comparison_artist_batch_01",
        "candidate": generated["candidates"][0],
        "intent": generated["intent"],
        "artist_names": ["sample_artist_a", "sample_artist_b"],
        "project_name": "画师批量对照",
        "settings": {"seed": 424242, "batch_size": 1},
        "remote_profile_id": "remote-1",
        "workflow_profile_id": "workflow-1",
    }
    submit_headers = {**headers, "Idempotency-Key": "artist-batch-01"}

    submitted = client.post("/api/v3/artist-comparisons", json=request, headers=submit_headers)
    duplicate = client.post("/api/v3/artist-comparisons", json=request, headers=submit_headers)

    assert submitted.status_code == 202
    assert duplicate.status_code == 202
    payload = submitted.json()
    assert payload["comparison_id"] == "comparison_artist_batch_01"
    assert payload["seed"] == 424242
    assert payload["requested_count"] == 2
    assert payload["failed"] == []
    assert [item["artist"] for item in payload["submitted"]] == ["@sample artist a", "@sample artist b"]
    assert [item["run"]["id"] for item in duplicate.json()["submitted"]] == [
        item["run"]["id"] for item in payload["submitted"]
    ]
    prepared_jobs = [item.request_json["prompt_job"] for item in queue.runs.values()]
    assert {job["generation_params"]["seed"] for job in prepared_jobs} == {424242}
    assert {tuple(job["artist_selection"]) for job in prepared_jobs} == {
        ("sample_artist_a",),
        ("sample_artist_b",),
    }
    assert all(job["integration_metadata"]["artist_comparison"]["id"] == "comparison_artist_batch_01" for job in prepared_jobs)


def test_local_translation_and_ephemeral_passphrase_endpoints_do_not_echo_secrets(
    reference_db: Path,
    tmp_path: Path,
) -> None:
    queue = StubGenerationQueue()
    translator = build_v2_local_translation_adapter(tmp_path / "missing-resources")
    runtime = create_api_runtime(
        reference_db,
        generation_queue=queue,
        translation_service=translator,
    )
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
    exchanged = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": ORIGIN},
    )
    headers = {"X-Anima-Session": exchanged.json()["session_token"], "Origin": ORIGIN}

    translated = client.post(
        "/api/v3/translation",
        json={"source_text": "一个女孩，白发", "direction": "zh_en"},
        headers=headers,
    )
    assert translated.status_code == 200
    assert translated.json()["local_only"] is True
    assert "girl" in translated.json()["translated_text"].lower()

    secret = "do-not-persist-this-passphrase"
    configured = client.post(
        "/api/v3/generation-credentials/private-key-passphrase",
        json={"remote_profile_id": "remote-1", "passphrase": secret},
        headers=headers,
    )
    assert configured.status_code == 200
    assert configured.json() == {"configured": True}
    assert queue.passphrases == {"remote-1": secret}
    assert secret not in configured.text

    bootstrap = client.get("/api/v3/bootstrap", headers={"X-Anima-Session": headers["X-Anima-Session"]})
    assert bootstrap.json()["features"]["local_translation"] is True
    assert secret not in bootstrap.text


def test_gallery_api_lists_and_streams_only_files_inside_output_root(
    reference_db: Path,
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "gallery"
    image = output_root / "项目" / "batch" / "one.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"gallery-image")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    v2_database = tmp_path / "v2-gallery.db"
    repository = SQLiteRepository(v2_database)
    repository.close()
    runtime = create_api_runtime(
        reference_db,
        gallery_service=V2GalleryReadService(v2_database, output_root),
    )
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
    exchange = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": ORIGIN},
    )
    token = exchange.json()["session_token"]

    unauthorized_client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
    unauthorized_list = unauthorized_client.get("/api/v3/gallery/assets")
    assert unauthorized_list.status_code == 401
    listed = client.get("/api/v3/gallery/assets", headers={"X-Anima-Session": token})
    assert listed.status_code == 200
    asset = listed.json()["items"][0]
    assert asset["project"] == "项目"

    # The exchange cookie is scoped only to image content so native <img> requests work
    # without making the general API cookie-authenticated.
    content = client.get(asset["content_url"])
    assert content.status_code == 200
    assert content.content == b"gallery-image"
    thumbnail = client.get(asset["thumbnail_url"])
    assert thumbnail.status_code == 200
    assert thumbnail.content == b"gallery-image"
    write_headers = {"X-Anima-Session": token, "Origin": ORIGIN}
    state = client.post(
        "/api/v3/gallery/assets/state",
        json={"paths": [asset["path"]], "state": "kept"},
        headers=write_headers,
    )
    assert state.status_code == 200
    assert state.json()["updated"] == [asset["path"]]
    moved = client.post(
        "/api/v3/gallery/assets/trash",
        json={"paths": [asset["path"]]},
        headers=write_headers,
    )
    assert moved.status_code == 200
    assert moved.json()["moved"] == [asset["path"]]
    trash = client.get("/api/v3/gallery/trash", headers={"X-Anima-Session": token})
    assert trash.json()["trash_count"] == 1
    trash_asset = trash.json()["items"][0]
    assert client.get(trash_asset["content_url"]).content == b"gallery-image"
    assert client.get(trash_asset["thumbnail_url"]).status_code == 200
    restored = client.post(
        "/api/v3/gallery/trash/restore",
        json={"paths": [trash_asset["path"]]},
        headers=write_headers,
    )
    assert restored.status_code == 200
    assert restored.json()["restored"] == [asset["path"]]
    moved_again = client.post(
        "/api/v3/gallery/assets/trash",
        json={"paths": [asset["path"]]},
        headers=write_headers,
    )
    assert moved_again.status_code == 200
    deleted = client.post(
        "/api/v3/gallery/trash/delete",
        json={"paths": moved_again.json()["trash_paths"]},
        headers=write_headers,
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] == moved_again.json()["trash_paths"]
    assert not image.exists()
    process_status = client.get("/api/v3/gallery/process", headers={"X-Anima-Session": token})
    assert process_status.status_code == 200
    assert process_status.json()["processing"]["available"] is False
    unavailable_process = client.post(
        "/api/v3/gallery/process",
        json={"paths": [asset["path"]], "operation": "upscale", "count": 1},
        headers=write_headers,
    )
    assert unavailable_process.status_code == 422
    assert unavailable_process.json()["error"]["code"] == "gallery_process_unavailable"
    traversal = client.get(
        "/api/v3/gallery/assets/content",
        params={"path": "../outside.png"},
        headers={"X-Anima-Session": token},
    )
    assert traversal.status_code == 404
    assert traversal.json()["error"]["code"] == "gallery_asset_not_found"


class StubGenerationQueue:
    def __init__(self) -> None:
        self.runs: dict[str, GenerationRun] = {}
        self.keys: dict[str, str] = {}
        self.passphrases: dict[str, str] = {}

    def set_private_key_passphrase(self, remote_profile_id, passphrase):
        if passphrase:
            self.passphrases[remote_profile_id] = passphrase
        else:
            self.passphrases.pop(remote_profile_id, None)

    def submit(self, prepared, *, remote_profile_id, workflow_profile_id, idempotency_key):
        if idempotency_key in self.keys:
            return self.runs[self.keys[idempotency_key]].model_copy(deep=True)
        run = GenerationRun(
            prompt_job_id=prepared.job.id,
            remote_profile_id=remote_profile_id,
            workflow_profile_id=workflow_profile_id,
            status_message="等待本地生成队列",
            request_json={"prompt_job": prepared.job.model_dump(mode="json")},
        )
        self.runs[run.id] = run
        self.keys[idempotency_key] = run.id
        return run.model_copy(deep=True)

    def get(self, run_id):
        return self.runs[run_id].model_copy(deep=True)

    def artifacts(self, _run_id):
        return []

    def list(self, *, limit=100):
        return list(self.runs.values())[:limit]

    def targets(self):
        return [{
            "remote_profile_id": "remote-1",
            "remote_display_name": "测试云主机",
            "workflow_profile_id": "workflow-1",
            "workflow_display_name": "基础工作流",
            "workflow_kind": "txt2img_basic",
            "compatible_model_profiles": ["anima_base_v1"],
            "host_fingerprint_ready": True,
            "auth_type": "private_key",
            "private_key_passphrase_configured": bool(self.passphrases.get("remote-1")),
        }]

    def available_actions(self, run_id):
        return ["cancel_queued"] if self.runs[run_id].state == GenerationRunState.DRAFT else []

    def cancel_queued(self, run_id):
        run = self.runs[run_id]
        run.update_state(GenerationRunState.CANCELED, "已取消", 0)
        return run.model_copy(deep=True)
