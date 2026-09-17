"""Background synchronization for one explicitly located local reference collection."""
from __future__ import annotations

from collections.abc import Callable
import json
import os
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Literal
from uuid import uuid4

from .reference_examples import ExampleStore, now
from .reference_import import import_collection


SyncStatus = Literal["idle", "scanning", "ready", "missing", "error"]
SourceLocator = Path | None | Callable[[], Path | None]
_EMPTY_COUNTS = {"created": 0, "updated": 0, "unchanged": 0, "deleted_preserved": 0}


class LocalReferenceSync:
    def __init__(self, store: ExampleStore, source: SourceLocator):
        self.store = store
        self.source = source
        self._lock = Lock()
        self._thread: Thread | None = None
        self._stop = Event()
        self._closed = False
        self._snapshot = {
            "status": "idle", "run_id": 0, "counts": dict(_EMPTY_COUNTS),
            "total": 0, "message": "尚未扫描本地参考案例。", "completed_at": None,
        }

    def start(self) -> dict:
        with self._lock:
            if self._closed:
                raise RuntimeError("本地参考案例同步器已关闭。")
            if self._thread is not None and self._thread.is_alive():
                return self._copy_snapshot()
            run_id = self._snapshot["run_id"] + 1
            self._stop.clear()
            self._snapshot = {
                "status": "scanning", "run_id": run_id, "counts": dict(_EMPTY_COUNTS),
                "total": 0, "message": "正在同步本地参考案例。", "completed_at": None,
            }
            self._thread = Thread(
                target=self._run, args=(run_id,), name="local-reference-sync", daemon=False
            )
            self._thread.start()
            return self._copy_snapshot()

    def status(self) -> dict:
        with self._lock:
            return self._copy_snapshot()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._stop.set()
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join()

    def _copy_snapshot(self) -> dict:
        value = dict(self._snapshot)
        value["counts"] = dict(value["counts"])
        return value

    def _finish(self, run_id: int, status: SyncStatus, *, counts=None, total=0, message: str) -> None:
        with self._lock:
            if self._snapshot["run_id"] != run_id:
                return
            self._snapshot = {
                "status": status, "run_id": run_id,
                "counts": dict(counts or _EMPTY_COUNTS), "total": total,
                "message": message, "completed_at": now(),
            }

    def _run(self, run_id: int) -> None:
        try:
            selected = self.source() if callable(self.source) else self.source
            if selected is None or not Path(selected).is_dir():
                self._finish(run_id, "missing", message="未找到本地参考案例集合。")
                return
            receipt = import_collection(self.store, Path(selected), cancelled=self._stop.is_set)
            self._write_receipt(receipt)
            counts = {key: int(receipt["counts"].get(key, 0)) for key in _EMPTY_COUNTS}
            self._finish(
                run_id, "ready", counts=counts, total=sum(counts.values()),
                message="本地参考案例同步完成。",
            )
        except Exception:
            self._finish(
                run_id, "error",
                message="本地参考案例同步失败，可能已有部分案例写入；可以安全重试。",
            )

    def _write_receipt(self, receipt: dict) -> None:
        target = self.store.path.parent / "reference-sync-receipt.json"
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
