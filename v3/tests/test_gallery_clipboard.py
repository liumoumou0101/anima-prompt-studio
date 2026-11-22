from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from anima_prompt_studio_v3.adapters.v2 import V2GalleryReadService
from anima_prompt_studio_v3.api import create_api_runtime
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
from test_api import ORIGIN, reference_db  # noqa: F401


@pytest.fixture
def clipboard_api(reference_db, tmp_path, monkeypatch):
    from anima_prompt_studio_v3.runtime import image_clipboard

    root = tmp_path / "gallery"
    image = root / "中文目录" / "原图 1.png"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (24, 32), "blue").save(image)
    outside = tmp_path / "outside.png"
    Image.new("RGB", (10, 10), "red").save(outside)
    database = tmp_path / "runtime.db"
    SQLiteRepository(database).close()
    runtime = create_api_runtime(reference_db, gallery_service=V2GalleryReadService(database, root))
    copied = []
    monkeypatch.setattr(image_clipboard, "copy_image_file", copied.append)
    with TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        session = client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token}, headers={"Origin": ORIGIN})
        headers = {"Origin": ORIGIN, "X-Anima-Session": session.json()["session_token"]}
        yield client, headers, copied, image, runtime.app


def test_copies_the_resolved_original_file_without_modifying_it(clipboard_api):
    client, headers, copied, image, _ = clipboard_api
    before = image.read_bytes()
    response = client.post("/api/v3/gallery/assets/clipboard", json={"path": "中文目录/原图 1.png"}, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"copied": True, "file_name": "原图 1.png"}
    assert copied == [image.resolve()]
    assert image.read_bytes() == before


@pytest.mark.parametrize("path", ["../outside.png", "missing.png", ".trash/deleted.png"])
def test_rejects_missing_or_outside_images_before_touching_clipboard(clipboard_api, path):
    client, headers, copied, _, _ = clipboard_api
    response = client.post("/api/v3/gallery/assets/clipboard", json={"path": path}, headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "gallery_asset_not_found"
    assert copied == []


def test_requires_write_session_and_same_origin_even_with_gallery_cookie(clipboard_api):
    client, headers, copied, _, _ = clipboard_api
    endpoint = "/api/v3/gallery/assets/clipboard"
    payload = {"path": "中文目录/原图 1.png"}
    assert client.post(endpoint, json=payload, headers={"Origin": ORIGIN}).status_code == 401
    assert client.post(endpoint, json=payload, headers={**headers, "Origin": "https://untrusted.example"}).status_code == 403
    assert client.post(endpoint, json=payload, headers={"X-Anima-Session": headers["X-Anima-Session"]}).status_code == 403
    assert copied == []


def test_returns_actionable_error_when_native_clipboard_fails(clipboard_api, monkeypatch):
    from anima_prompt_studio_v3.runtime import image_clipboard

    client, headers, _, _, _ = clipboard_api
    def fail(_path):
        raise image_clipboard.ClipboardWriteError("剪贴板正忙，请稍后重试。")
    monkeypatch.setattr(image_clipboard, "copy_image_file", fail)
    response = client.post("/api/v3/gallery/assets/clipboard", json={"path": "中文目录/原图 1.png"}, headers=headers)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "clipboard_write_failed"
    assert "剪贴板" in response.json()["error"]["message"]


def test_reports_unsupported_platform_without_claiming_success(clipboard_api, monkeypatch):
    from anima_prompt_studio_v3.runtime import image_clipboard

    client, headers, _, _, _ = clipboard_api
    def unsupported(_path):
        raise image_clipboard.ClipboardUnsupportedError("当前系统暂不支持复制图片文件。")
    monkeypatch.setattr(image_clipboard, "copy_image_file", unsupported)
    response = client.post("/api/v3/gallery/assets/clipboard", json={"path": "中文目录/原图 1.png"}, headers=headers)
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "clipboard_not_supported"


def test_missing_gallery_does_not_touch_clipboard(clipboard_api):
    client, headers, copied, _, app = clipboard_api
    app.state.gallery_service = None
    response = client.post("/api/v3/gallery/assets/clipboard", json={"path": "中文目录/原图 1.png"}, headers=headers)
    assert response.status_code == 503
    assert copied == []
