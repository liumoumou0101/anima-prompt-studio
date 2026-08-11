from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from anima_prompt_studio.repositories import SQLiteRepository
from anima_prompt_studio.services.gallery_server import GalleryServer


def _read_json(url: str) -> dict:
    with urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_gallery_server_serves_static_data_and_blocks_path_traversal(tmp_path):
    root = tmp_path / "images"
    image = root / "项目" / "批次" / "one.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"fake-png")
    (tmp_path / "outside.png").write_bytes(b"outside")
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<h1>gallery</h1>", encoding="utf-8")
    repository = SQLiteRepository(tmp_path / "gallery.db")
    server = GalleryServer(repository, lambda: root, static)

    try:
        base_url = server.start()
        assert _read_json(base_url + "api/health") == {"ok": True}
        payload = _read_json(base_url + "api/gallery")
        assert len(payload["assets"]) == 1
        assert payload["assets"][0]["project"] == "项目"
        with urlopen(base_url + "api/image?path=" + quote("项目/批次/one.png", safe=""), timeout=5) as response:
            assert response.read() == b"fake-png"
        try:
            urlopen(base_url + "api/image?path=" + quote("../outside.png", safe=""), timeout=5)
        except HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError("path traversal should be rejected")
    finally:
        server.stop()
        repository.close()


def test_gallery_server_batch_trash_removes_assets_from_index(tmp_path):
    root = tmp_path / "images"
    first = root / "项目" / "批次" / "one.png"
    second = root / "项目" / "批次" / "two.png"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    repository = SQLiteRepository(tmp_path / "gallery-trash.db")
    server = GalleryServer(repository, lambda: root, tmp_path / "static")

    try:
        server.start()
        request = Request(
            server.url + "api/gallery/trash",
            data=json.dumps({"paths": ["项目/批次/one.png", "项目/批次/two.png"]}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            result = json.loads(response.read().decode("utf-8"))
        assert len(result["moved"]) == 2
        assert not first.exists() and not second.exists()
        assert _read_json(server.url + "api/gallery")["assets"] == []
        assert list((root / ".trash").rglob("*.png"))
    finally:
        server.stop()
        repository.close()
