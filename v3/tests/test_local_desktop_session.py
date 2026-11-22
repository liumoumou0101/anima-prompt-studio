from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anima_prompt_studio_v3.api import LocalApiServer, create_api_runtime


ORIGIN = "http://127.0.0.1:9534"
LOCAL_HEADERS = {"Origin": ORIGIN, "X-Anima-Local": "1", "Sec-Fetch-Site": "same-origin"}


def desktop_client(tmp_path, **kwargs):
    runtime = create_api_runtime(tmp_path / "missing.db", allow_local_sessions=True, **kwargs)
    return TestClient(runtime.app, base_url=ORIGIN, client=("127.0.0.1", 1234))


def test_fresh_browser_can_create_session_but_business_api_still_requires_it(tmp_path: Path):
    client = desktop_client(tmp_path)
    assert client.get("/api/v3/bootstrap").status_code == 401
    created = client.post("/api/v3/session/local", json={}, headers=LOCAL_HEADERS)
    assert created.status_code == 200
    assert created.headers["cache-control"] == "no-store"
    token = created.json()["session_token"]
    assert created.json()["recovery_token"] != token
    assert client.get("/api/v3/bootstrap", headers={"X-Anima-Session": token}).status_code == 200
    assert client.get("/api/v3/bootstrap").status_code == 401


def test_desktop_page_cannot_be_embedded_by_another_website(tmp_path: Path):
    frontend = tmp_path / "web"
    frontend.mkdir()
    (frontend / "index.html").write_text("<!doctype html><title>ANIMA</title>", encoding="utf-8")
    response = desktop_client(tmp_path, frontend_dist=frontend).get("/settings")
    assert response.status_code == 200
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("content-security-policy") == "frame-ancestors 'none'"


def test_restarted_desktop_accepts_fresh_local_session_after_old_recovery_expires(tmp_path: Path):
    first = desktop_client(tmp_path)
    old = first.post("/api/v3/session/local", json={}, headers=LOCAL_HEADERS).json()
    second = desktop_client(tmp_path)
    assert second.post("/api/v3/session/restore", json={}, headers={
        **LOCAL_HEADERS, "X-Anima-Recovery": old["recovery_token"],
    }).status_code == 401
    current = second.post("/api/v3/session/local", json={}, headers=LOCAL_HEADERS)
    assert current.status_code == 200
    assert current.json()["session_token"] != old["session_token"]


@pytest.mark.parametrize("endpoint", ["session/local", "desktop/instance"])
def test_direct_api_does_not_enable_desktop_session_creation(tmp_path: Path, endpoint: str):
    runtime = create_api_runtime(tmp_path / "missing.db")
    client = TestClient(runtime.app, base_url=ORIGIN, client=("127.0.0.1", 1234))
    response = client.post(f"/api/v3/{endpoint}", json={}, headers=LOCAL_HEADERS)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "local_session_unavailable"


@pytest.mark.parametrize("changed", [
    {"Origin": None}, {"Origin": "null"}, {"Origin": "https://evil.example"},
    {"Origin": "http://127.0.0.1:9535"}, {"Origin": "http://localhost:9534"},
    {"X-Anima-Local": None}, {"X-Anima-Local": "0"},
    {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"},
    {"Sec-Fetch-Site": "none"}, {"Sec-Fetch-Site": ""},
])
@pytest.mark.parametrize("endpoint", ["session/local", "desktop/instance"])
def test_browser_session_endpoints_reject_foreign_or_non_api_requests(tmp_path: Path, changed, endpoint):
    client = desktop_client(tmp_path, desktop_instance_id="test-instance")
    headers = {key: value for key, value in {**LOCAL_HEADERS, **changed}.items() if value is not None}
    response = client.post(f"/api/v3/{endpoint}", json={}, headers=headers)
    assert response.status_code == 403
    assert "session_token" not in response.text
    assert "test-instance" not in response.text


@pytest.mark.parametrize("body", [[], {"unexpected": True}, "", None])
def test_local_session_requires_an_empty_object(tmp_path: Path, body):
    response = desktop_client(tmp_path).post("/api/v3/session/local", json=body, headers=LOCAL_HEADERS)
    assert response.status_code in {415, 422}


def test_local_session_rejects_forms_foreign_hosts_and_cross_origin_preflight(tmp_path: Path):
    client = desktop_client(tmp_path)
    assert client.post("/api/v3/session/local", data={}, headers=LOCAL_HEADERS).status_code == 415
    assert client.post("/api/v3/session/local", json={}, headers={**LOCAL_HEADERS, "Host": "evil.example"}).status_code == 400
    response = client.options("/api/v3/session/local", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-anima-local",
    })
    assert response.status_code == 405
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("host", [
    "user@127.0.0.1:9534", "127.0.0.1:bad", "127.0.0.1:70000",
    "127.0.0.1:9534/path", "127.0.0.1:9534?query", "127.0.0.1:9534#fragment",
])
def test_local_service_rejects_malformed_host_authorities(tmp_path: Path, host: str):
    client = desktop_client(tmp_path)
    response = client.post("/api/v3/session/local", json={}, headers={**LOCAL_HEADERS, "Host": host})
    assert response.status_code == 400


def test_local_session_rejects_non_loopback_peers_even_with_spoofed_forwarding(tmp_path: Path):
    runtime = create_api_runtime(tmp_path / "missing.db", allow_local_sessions=True)
    client = TestClient(runtime.app, base_url=ORIGIN, client=("192.0.2.5", 1234))
    response = client.post("/api/v3/session/local", json={}, headers={
        **LOCAL_HEADERS, "X-Forwarded-For": "127.0.0.1", "Forwarded": "for=127.0.0.1",
    })
    assert response.status_code == 403


def test_custom_allowed_hosts_cannot_expand_desktop_session_trust(tmp_path: Path):
    runtime = create_api_runtime(tmp_path / "missing.db", allow_local_sessions=True, allowed_hosts={"evil.example"})
    client = TestClient(runtime.app, base_url="http://evil.example", client=("127.0.0.1", 1234))
    response = client.post("/api/v3/session/local", json={}, headers={**LOCAL_HEADERS, "Origin": "http://evil.example"})
    assert response.status_code == 403


def test_desktop_probe_returns_only_instance_identity_without_credentials(tmp_path: Path):
    client = desktop_client(tmp_path, desktop_instance_id="test-instance")
    response = client.post("/api/v3/desktop/instance", json={}, headers={
        "Origin": ORIGIN, "X-Anima-Local": "1",
    })
    assert response.status_code == 200
    assert response.json() == {"instance_id": "test-instance"}
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    assert client.get("/api/v3/bootstrap").status_code == 401


def test_live_loopback_server_exposes_local_session_only_when_enabled(tmp_path: Path):
    from urllib.request import ProxyHandler, Request, build_opener
    import json

    with LocalApiServer(tmp_path / "missing.db", allow_local_sessions=True, desktop_instance_id="live") as server:
        opener = build_opener(ProxyHandler({}))
        request = Request(server.base_url + "/api/v3/session/local", data=b"{}", headers={
            "Content-Type": "application/json", "Origin": server.base_url, "X-Anima-Local": "1",
            "X-Forwarded-For": "192.0.2.5", "X-Forwarded-Proto": "https",
        })
        with opener.open(request, timeout=5) as response:
            token = json.load(response)["session_token"]
        with opener.open(Request(server.base_url + "/api/v3/bootstrap", headers={"X-Anima-Session": token}), timeout=5) as response:
            assert response.status == 200
