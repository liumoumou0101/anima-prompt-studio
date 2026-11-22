from io import BytesIO
import json
from pathlib import Path
from threading import Barrier, Event, Lock, Thread
import time

from PIL import Image

from anima_prompt_studio_v3.storage.reference_examples import ExampleNotes, ExamplePatch, ExampleStore
from anima_prompt_studio_v3.storage.reference_import import import_collection
from anima_prompt_studio_v3.storage.reference_sync import LocalReferenceSync


EMPTY_COUNTS = {"created": 0, "updated": 0, "unchanged": 0, "deleted_preserved": 0}


def make_collection(root: Path, ids=("123",)) -> Path:
    source = root / "anima-ref"
    (source / "batches").mkdir(parents=True)
    (source / "images").mkdir()
    rows = []
    for index, source_id in enumerate(ids):
        image = BytesIO()
        Image.new("RGB", (32, 48), (index * 40, 20, 120)).save(image, "PNG")
        name = f"{source_id}.png"
        (source / "images" / name).write_bytes(image.getvalue())
        rows.append({
            "id": f"civitai:{source_id}", "title": f"参考 {source_id}",
            "image_file": f"images/{name}", "checkpoint": "anima-base-v1.0",
            "artist_tag": "", "lora": "", "prompt": f"prompt {source_id}",
            "negative": "", "nsfw": False, "unet_pure": True,
            "source_url": f"https://civitai.com/images/{source_id}",
        })
    (source / "batches" / "01.json").write_text(
        json.dumps(rows, ensure_ascii=False), encoding="utf-8"
    )
    return source


def wait_for(sync: LocalReferenceSync, wanted: str, timeout=3) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = sync.status()
        if snapshot["status"] == wanted:
            return snapshot
        time.sleep(0.01)
    raise AssertionError(f"sync did not reach {wanted}: {sync.status()}")


def test_sync_adds_new_records_deduplicates_and_writes_atomic_receipt(tmp_path):
    source = make_collection(tmp_path, ("123",))
    store = ExampleStore(tmp_path / "state" / "examples.db")
    sync = LocalReferenceSync(store, source)

    assert sync.start() == {
        "status": "scanning", "run_id": 1, "counts": EMPTY_COUNTS,
        "total": 0, "message": "正在同步本地参考案例。", "completed_at": None,
    }
    first = wait_for(sync, "ready")
    assert first["counts"] == {**EMPTY_COUNTS, "created": 1}
    assert first["total"] == 1 and first["completed_at"]
    receipt_path = store.path.parent / "reference-sync-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["counts"]["created"] == 1
    assert not receipt_path.with_suffix(".tmp").exists()

    assert sync.start()["run_id"] == 2
    second = wait_for(sync, "ready")
    assert second["counts"] == {**EMPTY_COUNTS, "unchanged": 1}

    extra = make_collection(tmp_path / "replacement", ("123", "456"))
    sync.close()
    sync = LocalReferenceSync(store, extra)
    sync.start()
    third = wait_for(sync, "ready")
    assert third["counts"] == {**EMPTY_COUNTS, "created": 1, "unchanged": 1}
    assert third["total"] == 2
    sync.close()


def test_sync_preserves_user_edits_and_deleted_records(tmp_path):
    source = make_collection(tmp_path, ("123", "456"))
    store = ExampleStore(tmp_path / "state" / "examples.db")
    sync = LocalReferenceSync(store, source)
    sync.start()
    wait_for(sync, "ready")
    items = {item["origin_ref"]: item for item in store.list(limit=10)["items"]}
    edited = store.patch(items["civitai:123"]["id"], ExamplePatch(
        revision=items["civitai:123"]["revision"], title="我的标题",
        notes=ExampleNotes(user_notes="我的笔记"),
    ))
    store.delete(items["civitai:456"]["id"], items["civitai:456"]["revision"])

    rows = json.loads((source / "batches" / "01.json").read_text(encoding="utf-8"))
    rows[0]["why"] = "来源补充"
    (source / "batches" / "01.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    sync.start()
    result = wait_for(sync, "ready")

    assert result["counts"] == {**EMPTY_COUNTS, "updated": 1, "deleted_preserved": 1}
    current = store.get(edited["id"])
    assert current["title"] == "我的标题"
    assert current["notes"]["user_notes"] == "我的笔记"
    sync.close()


def test_missing_source_and_failed_partial_import_can_be_retried(tmp_path, monkeypatch):
    store = ExampleStore(tmp_path / "state" / "examples.db")
    missing = LocalReferenceSync(store, None)
    missing.start()
    assert wait_for(missing, "missing") == {
        "status": "missing", "run_id": 1, "counts": EMPTY_COUNTS, "total": 0,
        "message": "未找到本地参考案例集合。", "completed_at": wait_for(missing, "missing")["completed_at"],
    }
    missing.close()

    source = make_collection(tmp_path, ("123", "456"))
    sync = LocalReferenceSync(store, source)
    original_create = store.create
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("secret path and disk failure")
        return original_create(*args, **kwargs)

    monkeypatch.setattr(store, "create", fail_second)
    sync.start()
    failed = wait_for(sync, "error")
    assert failed["counts"] == EMPTY_COUNTS and failed["total"] == 0
    assert failed["message"] == "本地参考案例同步失败，可能已有部分案例写入；可以安全重试。"
    assert "secret" not in failed["message"] and str(tmp_path) not in failed["message"]
    assert len(store.list(limit=10)["items"]) == 1

    monkeypatch.setattr(store, "create", original_create)
    sync.start()
    recovered = wait_for(sync, "ready")
    assert recovered["counts"] == {**EMPTY_COUNTS, "created": 1, "unchanged": 1}
    assert recovered["total"] == 2
    sync.close()


def test_start_is_singleflight(tmp_path, monkeypatch):
    source = make_collection(tmp_path)
    store = ExampleStore(tmp_path / "state" / "examples.db")
    entered, release = Event(), Event()

    def blocked_import(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return import_collection(*args, **kwargs)

    monkeypatch.setattr("anima_prompt_studio_v3.storage.reference_sync.import_collection", blocked_import)
    sync = LocalReferenceSync(store, source)
    first = sync.start()
    assert entered.wait(1)
    second = sync.start()
    assert first["run_id"] == second["run_id"] == 1
    assert second["status"] == "scanning"
    release.set()
    assert wait_for(sync, "ready")["run_id"] == 1
    sync.close()


def test_source_callable_is_resolved_for_each_run(tmp_path):
    store = ExampleStore(tmp_path / "state" / "examples.db")
    selected = None

    def locate():
        return selected

    sync = LocalReferenceSync(store, locate)
    sync.start()
    assert wait_for(sync, "missing")["run_id"] == 1

    selected = make_collection(tmp_path)
    sync.start()
    ready = wait_for(sync, "ready")
    assert ready["run_id"] == 2
    assert ready["counts"] == {**EMPTY_COUNTS, "created": 1}
    sync.close()


def test_import_collection_serializes_concurrent_writers(tmp_path, monkeypatch):
    source = make_collection(tmp_path)
    store = ExampleStore(tmp_path / "state" / "examples.db")
    import_module = __import__(
        "anima_prompt_studio_v3.storage.reference_import", fromlist=["prepare_collection"]
    )
    original_prepare = import_module.prepare_collection
    guard = Lock()
    active = maximum_active = 0

    def slow_prepare(root):
        nonlocal active, maximum_active
        with guard:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.1)
        try:
            return original_prepare(root)
        finally:
            with guard:
                active -= 1

    monkeypatch.setattr(import_module, "prepare_collection", slow_prepare)
    barrier = Barrier(3)
    results, errors = [], []

    def run():
        barrier.wait()
        try:
            results.append(import_collection(store, source)["counts"])
        except BaseException as exc:
            errors.append(exc)

    threads = [Thread(target=run), Thread(target=run)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(3)

    assert not errors
    assert maximum_active == 1
    assert {result["created"] for result in results} == {0, 1}
    assert {result["unchanged"] for result in results} == {0, 1}


def test_close_cancels_sync_between_records(tmp_path, monkeypatch):
    source = make_collection(tmp_path, ("123", "456", "789"))
    store = ExampleStore(tmp_path / "state" / "examples.db")
    original_create = store.create
    first_started, release_first = Event(), Event()

    def slow_first(*args, **kwargs):
        if not first_started.is_set():
            first_started.set()
            assert release_first.wait(2)
        return original_create(*args, **kwargs)

    monkeypatch.setattr(store, "create", slow_first)
    sync = LocalReferenceSync(store, source)
    sync.start()
    assert first_started.wait(1)
    closed = Event()
    closer = Thread(target=lambda: (sync.close(), closed.set()))
    closer.start()
    release_first.set()
    assert closed.wait(2)
    closer.join()
    assert len(store.list(limit=10)["items"]) == 1
    assert sync.status()["status"] == "error"


def test_close_cancels_during_collection_preflight(tmp_path, monkeypatch):
    source = make_collection(tmp_path, ("123", "456", "789"))
    store = ExampleStore(tmp_path / "state" / "examples.db")
    import_module = __import__(
        "anima_prompt_studio_v3.storage.reference_import", fromlist=["inspect_image"]
    )
    original_inspect = import_module.inspect_image
    first_started, release_first = Event(), Event()
    inspected = 0

    def slow_first(*args, **kwargs):
        nonlocal inspected
        inspected += 1
        if inspected == 1:
            first_started.set()
            assert release_first.wait(2)
        return original_inspect(*args, **kwargs)

    monkeypatch.setattr(import_module, "inspect_image", slow_first)
    sync = LocalReferenceSync(store, source)
    sync.start()
    assert first_started.wait(1)
    closed = Event()
    closer = Thread(target=lambda: (sync.close(), closed.set()))
    closer.start()
    release_first.set()
    assert closed.wait(2)
    closer.join()

    assert inspected == 1
    assert store.list(limit=10)["items"] == []
    assert sync.status()["status"] == "error"
