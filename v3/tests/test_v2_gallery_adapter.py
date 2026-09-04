from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from anima_prompt_studio.repositories import SQLiteRepository

from anima_prompt_studio_v3.adapters.v2 import V2GalleryReadService, build_v2_gallery_service
from anima_prompt_studio_v3.adapters.v2 import gallery as gallery_adapter


def make_gallery(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "images"
    image = root / "雨夜项目" / "anima_base_v1" / "batch-1" / "result.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"test-png-content")
    manifest = {
        "generation_run": {
            "id": "run-v3-1",
            "created_at": "2026-08-26T12:00:00+08:00",
            "completed_at": "2026-08-26T12:01:00+08:00",
            "request_json": {},
        },
        "prompt_job": {
            "project_name": "雨夜项目",
            "model_profile_id": "anima_base_v1",
            "positive_prompt": "score_7, white hair. A girl holding an umbrella.",
            "negative_prompt": "text, watermark",
            "generation_params": {"width": 1024, "height": 1536, "steps": 28, "cfg": 6.5, "seed": 42},
            "integration_metadata": {
                "schema": "v3-v2-generation-bridge/1",
                "candidate": {
                    "id": "candidate_hybrid",
                    "lane": "hybrid",
                    "versions": {"data_pack": "pack-r1", "algorithm": "hybrid-lane-v2"},
                },
                "artist_comparison": {
                    "id": "comparison-source",
                    "artist": "harusa1107",
                    "rendered_artist": "@harusa1107",
                    "position": 3,
                    "total": 10,
                    "seed": 42,
                },
            },
        },
        "artifacts": [{"local_path": str(image)}],
    }
    (image.parent / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    database = tmp_path / "v2.db"
    repository = SQLiteRepository(database)
    repository.set_setting("generation_output_root", str(root))
    repository.close()
    return database, root, image


def test_v2_gallery_adapter_indexes_manifest_and_preserves_v3_candidate_trace(
    tmp_path: Path,
) -> None:
    database, root, image = make_gallery(tmp_path)
    service = build_v2_gallery_service(database)

    payload = service.list_assets()
    assert payload["root"] == str(root.resolve())
    assert payload["projects"] == ["雨夜项目"]
    asset = payload["items"][0]
    assert asset["path"].endswith("result.png")
    assert asset["positive_prompt"].startswith("score_7, white hair")
    assert asset["negative_prompt"] == "text, watermark"
    assert asset["candidate"]["lane"] == "hybrid"
    assert asset["candidate"]["versions"]["data_pack"] == "pack-r1"
    assert asset["artist_comparison"]["rendered_artist"] == "@harusa1107"
    assert asset["generation_params"] == {"steps": 28, "cfg": 6.5, "seed": 42, "width": 1024, "height": 1536}
    assert service.resolve_content(asset["path"]) == image.resolve()
    assert service.shutdown(timeout=2) is True


def test_v2_gallery_adapter_blocks_outside_and_trash_paths(tmp_path: Path) -> None:
    database, root, _image = make_gallery(tmp_path)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    trash = root / ".trash" / "batch" / "removed.png"
    trash.parent.mkdir(parents=True)
    trash.write_bytes(b"removed")
    service = V2GalleryReadService(database, root)

    assert service.resolve_content("../outside.png") is None
    assert service.resolve_content(".trash/batch/removed.png") is None
    assert all(".trash" not in item["path"] for item in service.list_assets()["items"])


def test_gallery_snapshot_is_reused_until_an_explicit_refresh(tmp_path: Path) -> None:
    database, root, image = make_gallery(tmp_path)
    service = V2GalleryReadService(database, root)

    initial = service.list_assets()
    assert len(initial["items"]) == 1
    assert service._index_path.is_file()
    envelope = json.loads(service._index_path.read_text(encoding="utf-8"))
    assert envelope["schema"] == 2
    assert list(envelope["filesystem"]) == [image.relative_to(root).as_posix()]

    added = image.with_name("added-after-index.webp")
    added.write_bytes(b"second-image")
    assert len(service.list_assets()["items"]) == 1
    assert len(V2GalleryReadService(database, root).list_assets()["items"]) == 1

    refreshed = service.list_assets(refresh=True)
    assert {item["name"] for item in refreshed["items"]} == {"result.png", "added-after-index.webp"}


def test_incremental_refresh_rebuilds_only_a_changed_manifest_folder(tmp_path: Path, monkeypatch) -> None:
    database, root, image = make_gallery(tmp_path)
    service = V2GalleryReadService(database, root)
    service.list_assets()
    manifest_path = image.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["prompt_job"]["positive_prompt"] = "updated prompt from changed manifest"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def reject_full_scan(*_args, **_kwargs):
        raise AssertionError("incremental refresh unexpectedly used the full gallery loader")

    monkeypatch.setattr(gallery_adapter, "load_gallery_batches", reject_full_scan)
    refreshed = service.list_assets(refresh=True)

    assert refreshed["items"][0]["positive_prompt"] == "updated prompt from changed manifest"


def test_gallery_index_supports_an_explicit_full_rebuild(tmp_path: Path, monkeypatch) -> None:
    database, root, _image = make_gallery(tmp_path)
    service = V2GalleryReadService(database, root)
    service.list_assets()
    calls = 0
    original = gallery_adapter.load_gallery_batches

    def count_full_scan(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(gallery_adapter, "load_gallery_batches", count_full_scan)
    service.list_assets(rebuild=True)

    assert calls == 1


def test_gallery_state_and_recoverable_trash_respect_active_process_lock(tmp_path: Path) -> None:
    database, root, image = make_gallery(tmp_path)
    service = V2GalleryReadService(database, root)
    relative = image.relative_to(root).as_posix()
    assert service.set_state([relative, "../outside.png"], "kept") == {
        "updated": [relative],
        "state": "kept",
    }
    assert service.list_assets()["items"][0]["state"] == "kept"

    repository = SQLiteRepository(database)
    repository.save_gallery_process_job(
        root,
        "process-1",
        "running",
        0,
        datetime.now().astimezone(),
        {"id": "process-1", "sourcePath": relative, "state": "running"},
    )
    repository.close()
    blocked = service.move_to_trash([relative])
    assert blocked["moved"] == []
    assert "正在处理" in blocked["failed"][0]["error"]
    blocked_delete = service.delete_permanently([relative])
    assert blocked_delete["deleted"] == []
    assert "正在处理" in blocked_delete["failed"][0]["error"]
    assert image.is_file()

    repository = SQLiteRepository(database)
    repository.save_gallery_process_job(
        root,
        "process-1",
        "completed",
        0,
        datetime.now().astimezone(),
        {"id": "process-1", "sourcePath": relative, "state": "completed"},
    )
    repository.close()
    moved = service.move_to_trash([relative])
    assert moved["moved"] == [relative]
    assert not image.exists()
    assert service.list_assets()["items"] == []
    trash_path = moved["trash_paths"][0]
    assert service.list_trash()["items"][0]["path"] == trash_path

    restored = service.restore_from_trash([trash_path])
    assert restored["restored"] == [relative]
    assert image.is_file()
    assert service.list_trash()["items"] == []


def test_gallery_adapter_permanently_deletes_only_validated_trash_assets(tmp_path: Path) -> None:
    database, root, image = make_gallery(tmp_path)
    service = V2GalleryReadService(database, root)
    relative = image.relative_to(root).as_posix()
    moved = service.move_to_trash([relative])
    trash_path = moved["trash_paths"][0]

    deleted = service.delete_from_trash([trash_path, "../outside.png"])

    assert deleted["deleted"] == [trash_path]
    assert service.list_trash()["items"] == []
    assert not image.exists()


def test_gallery_adapter_batch_delete_removes_live_files_but_never_outside_paths(tmp_path: Path) -> None:
    database, root, image = make_gallery(tmp_path)
    second = image.with_name("second.webp")
    second.write_bytes(b"second-image")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    service = V2GalleryReadService(database, root)
    paths = [image.relative_to(root).as_posix(), second.relative_to(root).as_posix(), "../outside.png"]

    result = service.delete_permanently(paths)

    assert result["deleted"] == sorted(paths[:2])
    assert len(result["failed"]) == 1
    assert not image.exists()
    assert not second.exists()
    assert outside.is_file()


class FakeProcessManager:
    def __init__(self) -> None:
        self.submitted: list[tuple[str, str, int]] = []
        self.assets: list[dict] = []

    def configuration_payload(self):
        return {"available": True, "regenAvailable": True, "scale": 1.5}

    def list_jobs(self):
        return [{"id": "job-1", "state": "queued", "operation": "gallery_upscale_1_5x"}]

    def submit(self, _source, relative, _asset):
        self.submitted.append(("upscale", relative, 1))
        self.assets.append(_asset)
        return {"id": "job-upscale", "state": "queued", "operation": "gallery_upscale_1_5x"}

    def submit_regenerate(self, _source, relative, _asset, count):
        self.submitted.append(("regenerate", relative, count))
        self.assets.append(_asset)
        return {"id": "job-regen", "state": "queued", "operation": "gallery_txt2img_more"}

    def cancel(self, job_id):
        return {"id": job_id, "state": "canceled"}

    def retry(self, job_id):
        return {"id": job_id, "state": "queued"}

    def clear_completed(self):
        return 2

    def shutdown(self, **_kwargs):
        return True


def test_gallery_process_adapter_submits_both_reused_v2_operations(tmp_path: Path) -> None:
    database, root, image = make_gallery(tmp_path)
    manager = FakeProcessManager()
    service = V2GalleryReadService(database, root, process_manager=manager)  # type: ignore[arg-type]
    relative = image.relative_to(root).as_posix()

    assert service.process_configuration()["available"] is True
    assert service.list_process_jobs()["jobs"][0]["id"] == "job-1"
    assert service.submit_process([relative], "upscale")["jobs"][0]["id"] == "job-upscale"
    assert service.submit_process([relative], "regenerate", 3)["jobs"][0]["id"] == "job-regen"
    assert manager.submitted == [("upscale", relative, 1), ("regenerate", relative, 3)]
    assert manager.assets[1]["parameters"]["integration_metadata"]["candidate"]["id"] == "candidate_hybrid"
    assert manager.assets[1]["parameters"]["integration_metadata"]["artist_comparison"]["rendered_artist"] == "@harusa1107"
    assert manager.assets[1]["parameters"]["negative_prompt"] == "text, watermark"
    assert service.process_action("job-1", "cancel")["job"]["state"] == "canceled"
    assert service.process_action("job-1", "retry")["job"]["state"] == "queued"
    assert service.process_action("", "clear_completed") == {"cleared": 2}
