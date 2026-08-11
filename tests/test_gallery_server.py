from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from PySide6.QtGui import QImage

from anima_prompt_studio.repositories import SQLiteRepository
from anima_prompt_studio.services.gallery_server import GalleryServer


def test_bundled_gallery_index_references_existing_assets():
    static_root = Path(__file__).resolve().parents[1] / "src" / "anima_prompt_studio" / "web_gallery" / "dist"
    index = (static_root / "index.html").read_text(encoding="utf-8")
    asset_paths = re.findall(r'(?:src|href)="\./([^"]+)"', index)

    assert asset_paths
    assert all((static_root / path).is_file() for path in asset_paths)


def _read_json(url: str) -> dict:
    with urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(url: str, payload: dict) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
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
    server = GalleryServer(repository, root, static)

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
    server = GalleryServer(repository, root, tmp_path / "static")

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


def test_gallery_server_uses_real_dimensions_thumbnails_and_persistent_state(tmp_path):
    root = tmp_path / "images"
    image_path = root / "外部图片" / "wide.png"
    image_path.parent.mkdir(parents=True)
    image = QImage(320, 180, QImage.Format_RGB32)
    image.fill(0x446688)
    assert image.save(str(image_path))
    repository = SQLiteRepository(tmp_path / "gallery-state.db")
    server = GalleryServer(repository, root, tmp_path / "static")

    try:
        server.start()
        payload = _read_json(server.url + "api/gallery")
        asset = payload["assets"][0]
        assert (asset["width"], asset["height"]) == (320, 180)
        assert asset["source"] == "external"
        result = _post_json(
            server.url + "api/gallery/state",
            {"paths": [asset["path"]], "state": "kept"},
        )
        assert result["state"] == "kept"
        assert _read_json(server.url + "api/gallery")["assets"][0]["state"] == "kept"
        with urlopen(server.url + asset["thumbnail"].lstrip("/"), timeout=5) as response:
            thumbnail = QImage.fromData(response.read())
        assert not thumbnail.isNull()
        assert thumbnail.width() <= 720 and thumbnail.height() <= 720
    finally:
        server.stop()
        repository.close()


def test_gallery_server_can_restore_and_permanently_delete_trash(tmp_path):
    root = tmp_path / "images"
    image_path = root / "项目" / "one.png"
    image_path.parent.mkdir(parents=True)
    image = QImage(32, 24, QImage.Format_RGB32)
    image.fill(0x224466)
    assert image.save(str(image_path))
    repository = SQLiteRepository(tmp_path / "gallery-restore.db")
    server = GalleryServer(repository, root, tmp_path / "static")

    try:
        server.start()
        _post_json(server.url + "api/gallery/trash", {"paths": ["项目/one.png"]})
        trash_asset = _read_json(server.url + "api/gallery/trash")["assets"][0]
        restored = _post_json(server.url + "api/gallery/restore", {"paths": [trash_asset["path"]]})
        assert restored["restored"] == ["项目/one.png"]
        assert image_path.is_file()

        _post_json(server.url + "api/gallery/trash", {"paths": ["项目/one.png"]})
        trash_asset = _read_json(server.url + "api/gallery/trash")["assets"][0]
        deleted = _post_json(server.url + "api/gallery/delete", {"paths": [trash_asset["path"]]})
        assert deleted["deleted"] == [trash_asset["path"]]
        assert _read_json(server.url + "api/gallery/trash")["assets"] == []
    finally:
        server.stop()
        repository.close()
