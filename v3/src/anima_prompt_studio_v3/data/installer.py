from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError

from .contracts import DataContractError, DataPackManifest
from .store import ReferenceDataStore


STATE_FILE = "active.json"
MANIFEST_FILE = "data-pack.json"
NOTICE_FILE = "NOTICE.txt"


class DataPackState(BaseModel):
    version: Literal[1] = 1
    active_pack_id: str = Field(pattern=r"^[a-zA-Z0-9._-]+$")
    previous_pack_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9._-]+$")
    updated_at: datetime


class InstalledDataPack(BaseModel):
    pack_id: str
    path: Path
    reference_db: Path
    active: bool


class DataPackManager:
    """Install immutable reference packs and atomically switch a small state pointer."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.packs_dir = self.root / "packs"
        self.downloads_dir = self.root / "downloads"
        self.state_path = self.root / STATE_FILE
        self.lock_path = self.root / ".update.lock"

    def install(self, source: Path, *, activate: bool = True) -> InstalledDataPack:
        source = source.resolve()
        manifest, reference_db = self._validate_pack(source)
        self._ensure_layout()
        with _UpdateLock(self.lock_path):
            target = self.packs_dir / manifest.pack_id
            if target.exists():
                installed_manifest, installed_db = self._validate_pack(target)
                if installed_manifest != manifest:
                    raise DataContractError(f"数据包 ID 已存在但内容不同：{manifest.pack_id}")
                reference_db = installed_db
            else:
                staging = self.downloads_dir / f".install-{manifest.pack_id}-{uuid4().hex}"
                try:
                    self._copy_pack(source, staging, manifest)
                    staged_manifest, _ = self._validate_pack(staging)
                    if staged_manifest != manifest:
                        raise DataContractError("复制后的 manifest 与源数据包不一致。")
                    try:
                        os.replace(staging, target)
                    except OSError as exc:
                        raise DataContractError(f"无法原子安装数据包：{exc}") from exc
                finally:
                    if staging.exists():
                        shutil.rmtree(staging, ignore_errors=True)
                reference_db = target / "reference.db"
            if activate:
                self._activate_locked(manifest.pack_id)
            state = self.state()
            return InstalledDataPack(
                pack_id=manifest.pack_id,
                path=target,
                reference_db=reference_db,
                active=state is not None and state.active_pack_id == manifest.pack_id,
            )

    def activate(self, pack_id: str) -> DataPackState:
        self._ensure_layout()
        with _UpdateLock(self.lock_path):
            return self._activate_locked(pack_id)

    def rollback(self) -> DataPackState:
        self._ensure_layout()
        with _UpdateLock(self.lock_path):
            current = self.state()
            if current is None or current.previous_pack_id is None:
                raise DataContractError("没有可回滚的数据包版本。")
            previous = current.previous_pack_id
            self._validate_pack(self.packs_dir / previous)
            rolled_back = DataPackState(
                active_pack_id=previous,
                previous_pack_id=current.active_pack_id,
                updated_at=datetime.now(timezone.utc),
            )
            self._write_state(rolled_back)
            return rolled_back

    def state(self) -> DataPackState | None:
        if not self.state_path.is_file():
            return None
        try:
            return DataPackState.model_validate_json(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            raise DataContractError(f"数据包活动状态损坏：{exc}") from exc

    def active_reference_db(self, *, verify: bool = False) -> Path:
        state = self.state()
        if state is None:
            raise DataContractError("尚未安装并启用参考数据包。")
        pack_dir = self.packs_dir / state.active_pack_id
        if verify:
            _, reference_db = self._validate_pack(pack_dir)
            return reference_db
        reference_db = pack_dir / "reference.db"
        if not reference_db.is_file():
            raise DataContractError(f"活动数据包缺少 reference.db：{state.active_pack_id}")
        return reference_db

    def installed(self) -> list[InstalledDataPack]:
        state = self.state()
        active_id = state.active_pack_id if state is not None else None
        if not self.packs_dir.is_dir():
            return []
        result: list[InstalledDataPack] = []
        for path in sorted(self.packs_dir.iterdir(), key=lambda item: item.name):
            if not path.is_dir():
                continue
            try:
                manifest = DataPackManifest.load(path / MANIFEST_FILE)
            except DataContractError:
                continue
            result.append(
                InstalledDataPack(
                    pack_id=manifest.pack_id,
                    path=path,
                    reference_db=path / "reference.db",
                    active=manifest.pack_id == active_id,
                )
            )
        return result

    def _activate_locked(self, pack_id: str) -> DataPackState:
        if not pack_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in pack_id):
            raise DataContractError("数据包 ID 非法。")
        manifest, _ = self._validate_pack(self.packs_dir / pack_id)
        if manifest.pack_id != pack_id:
            raise DataContractError("目录名与数据包 ID 不一致。")
        current = self.state()
        if current is not None and current.active_pack_id == pack_id:
            return current
        next_state = DataPackState(
            active_pack_id=pack_id,
            previous_pack_id=current.active_pack_id if current is not None else None,
            updated_at=datetime.now(timezone.utc),
        )
        self._write_state(next_state)
        return next_state

    def _validate_pack(self, root: Path) -> tuple[DataPackManifest, Path]:
        if not root.is_dir():
            raise DataContractError(f"数据包目录不存在：{root}")
        manifest = DataPackManifest.load(root / MANIFEST_FILE)
        manifest.verify_files(root)
        if "reference.db" not in {item.path for item in manifest.files}:
            raise DataContractError("数据包 manifest 必须包含根目录 reference.db。")
        reference_db = root / "reference.db"
        try:
            connection = sqlite3.connect(f"file:{reference_db.as_posix()}?mode=ro", uri=True)
            try:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()
                if integrity is None or integrity[0] != "ok":
                    raise DataContractError(f"reference.db 完整性检查失败：{integrity!r}")
                counts = {
                    "tags": connection.execute("SELECT COUNT(*) FROM tags").fetchone()[0],
                    "artists": connection.execute("SELECT COUNT(*) FROM artists").fetchone()[0],
                    "aliases": connection.execute("SELECT COUNT(*) FROM tag_aliases").fetchone()[0],
                    "tag_edges": connection.execute("SELECT COUNT(*) FROM tag_cooccurrence").fetchone()[0],
                    "artist_edges": connection.execute("SELECT COUNT(*) FROM artist_tag_cooccurrence").fetchone()[0],
                }
            finally:
                connection.close()
            if counts != manifest.counts.model_dump():
                raise DataContractError(f"reference.db 记录数与 manifest 不一致：{counts}")
            with ReferenceDataStore(reference_db) as store:
                if store.pack_id != manifest.pack_id:
                    raise DataContractError("reference.db 的 pack_id 与 manifest 不一致。")
                store.search("health_check", limit=1)
        except sqlite3.Error as exc:
            raise DataContractError(f"reference.db 健康检查失败：{exc}") from exc
        return manifest, reference_db

    def _copy_pack(self, source: Path, target: Path, manifest: DataPackManifest) -> None:
        target.mkdir(parents=True, exist_ok=False)
        for item in manifest.files:
            source_file = source / item.path
            target_file = target / item.path
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_file)
        shutil.copy2(source / MANIFEST_FILE, target / MANIFEST_FILE)
        notice = source / NOTICE_FILE
        if notice.is_file():
            shutil.copy2(notice, target / NOTICE_FILE)

    def _write_state(self, state: DataPackState) -> None:
        temporary = self.root / f".{STATE_FILE}.{uuid4().hex}.tmp"
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(state.model_dump(mode="json"), stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.replace(temporary, self.state_path)
            except OSError as exc:
                raise DataContractError(f"无法原子切换活动数据包：{exc}") from exc
        finally:
            temporary.unlink(missing_ok=True)

    def _ensure_layout(self) -> None:
        self.packs_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)


class _UpdateLock(AbstractContextManager["_UpdateLock"]):
    def __init__(self, path: Path, *, timeout: float = 5.0) -> None:
        self.path = path
        self.timeout = timeout
        self._stream = None

    def __enter__(self) -> "_UpdateLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = self.path.open("a+b")
        self._stream.seek(0, os.SEEK_END)
        if self._stream.tell() == 0:
            self._stream.write(b"\0")
            self._stream.flush()
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self._lock()
                return self
            except OSError as exc:
                if time.monotonic() >= deadline:
                    self._stream.close()
                    self._stream = None
                    raise DataContractError("另一个数据包更新正在进行。") from exc
                time.sleep(0.05)

    def __exit__(self, *_args: object) -> None:
        if self._stream is not None:
            try:
                self._unlock()
            finally:
                self._stream.close()
                self._stream = None

    def _lock(self) -> None:
        assert self._stream is not None
        self._stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(self) -> None:
        assert self._stream is not None
        self._stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
