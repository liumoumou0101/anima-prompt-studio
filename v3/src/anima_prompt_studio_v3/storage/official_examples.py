"""Validated immutable official packs with an atomic active-version pointer."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import shutil
from uuid import uuid4

from pydantic import Field

from ..core.requirements import ContractModel, ReferenceCompat, Requirements, digest, dump
from .reference_examples import ExampleNotes, fail, inspect_image


class PackFile(ContractModel):
    path: str = Field(min_length=1, max_length=500)
    size: int = Field(ge=0, le=21 * 1024 * 1024)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class PackCounts(ContractModel):
    examples: int = Field(ge=1, le=1000)
    files: int = Field(ge=3, le=3000)


class ExamplesManifest(ContractModel):
    contract: str = Field(pattern=r"^anima-v3-examples/1$")
    pack_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
    generated_at: str = Field(min_length=1, max_length=80)
    counts: PackCounts
    files: list[PackFile] = Field(max_length=3000)


class OfficialExample(ContractModel):
    id: str = Field(pattern=r"^off_[A-Za-z0-9_]+$", max_length=100)
    title: str = Field(min_length=1, max_length=200)
    requirements: Requirements
    compat: ReferenceCompat = Field(default_factory=ReferenceCompat)
    media: str = Field(min_length=1, max_length=500)


def safe_path(root, raw):
    relative = PurePosixPath(raw)
    if (not raw or "\\" in raw or ":" in raw or relative.is_absolute()
            or any(part in {"", ".", ".."} for part in raw.split("/"))):
        raise ValueError("Invalid pack path")
    path = root.joinpath(*relative.parts).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Pack path escapes root")
    return path


class OfficialPack:
    def __init__(self, root):
        self.root = Path(root)
        self._cached = None

    @staticmethod
    def stamps(path, manifest):
        result = []
        for raw in ["examples-pack.json"] + [item.path for item in manifest.files]:
            resolved = safe_path(path, raw)
            stat = resolved.stat()
            result.append((str(resolved), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
        return tuple(result)

    @staticmethod
    def validate(directory):
        directory = Path(directory)
        manifest_path = safe_path(directory, "examples-pack.json")
        if manifest_path.stat().st_size > 1024 * 1024:
            raise ValueError("Manifest too large")
        manifest = ExamplesManifest.model_validate_json(manifest_path.read_bytes())
        paths = {item.path for item in manifest.files}
        if (len(paths) != len(manifest.files) or len(paths) != manifest.counts.files
                or not {"catalog.json", "NOTICE.txt"} <= paths
                or not any(path.startswith("LICENSES/") for path in paths)
                or "examples-pack.json" in paths
                or sum(item.size for item in manifest.files) > 500 * 1024 * 1024):
            raise ValueError("Invalid pack file inventory")
        for item in manifest.files:
            path = safe_path(directory, item.path)
            if path.stat().st_size != item.size or sha256(path.read_bytes()).hexdigest() != item.sha256:
                raise ValueError("Pack file checksum mismatch")
        catalog_path = safe_path(directory, "catalog.json")
        if catalog_path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Catalog too large")
        raw = json.loads(catalog_path.read_bytes())
        if not isinstance(raw, list) or len(raw) != manifest.counts.examples:
            raise ValueError("Invalid catalog count")
        entries = [OfficialExample.model_validate(item) for item in raw]
        if len({item.id for item in entries}) != len(entries):
            raise ValueError("Duplicate official id")
        for item in entries:
            if item.media != f"media/{item.id}/original.webp" or item.media not in paths:
                raise ValueError("Unregistered official media")
            inspect_image(safe_path(directory, item.media).read_bytes(), "image/webp")
        return manifest, entries

    def install(self, source):
        manifest, _ = self.validate(source)
        self.root.mkdir(parents=True, exist_ok=True)
        # Never replace a directory that existing requests may still be reading.
        destination = self.root / manifest.pack_id
        staging = self.root / (".install-" + uuid4().hex)
        staging.mkdir()
        try:
            for raw in ["examples-pack.json"] + [item.path for item in manifest.files]:
                target = safe_path(staging, raw)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(safe_path(Path(source), raw), target)
            copied, _ = self.validate(staging)
            if dump(copied) != dump(manifest):
                raise ValueError("Pack changed during install")
            if destination.exists():
                installed, _ = self.validate(destination)
                if dump(installed) != dump(manifest):
                    raise ValueError("Pack id already belongs to different content")
            else:
                staging.rename(destination)
            pointer = self.root / (".current-" + uuid4().hex + ".json")
            try:
                pointer.write_text(json.dumps({"pack_id": manifest.pack_id}), encoding="utf-8")
                pointer.replace(self.root / "current.json")
            finally:
                pointer.unlink(missing_ok=True)
        finally:
            # Remove only the files from this invocation's verified inventory.
            if staging.exists():
                for path in sorted(staging.rglob("*"), key=lambda item: len(item.parts), reverse=True):
                    if not path.resolve().is_relative_to(staging.resolve()):
                        raise ValueError("Unexpected install path")
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        path.rmdir()
                staging.rmdir()
        return {"id": manifest.pack_id, "ready": True, "count": manifest.counts.examples}

    def current(self):
        try:
            pointer = self.root / "current.json"
            if pointer.stat().st_size > 1000:
                raise ValueError("Invalid pointer")
            pack_id = json.loads(pointer.read_bytes())["pack_id"]
            path = safe_path(self.root, pack_id)
            if self._cached is not None:
                cached_path, cached_manifest, cached_entries, stamps = self._cached
                if path == cached_path and self.stamps(path, cached_manifest) == stamps:
                    return path, cached_manifest, cached_entries
            # Every changed installation is validated in full; unchanged immutable packs
            # only need filesystem stamps, avoiding repeated image decoding per card.
            before_manifest, _ = self.validate(path)
            before = self.stamps(path, before_manifest)
            manifest, entries = self.validate(path)
            after = self.stamps(path, manifest)
            if manifest.pack_id != pack_id or before != after:
                raise ValueError("Invalid active pack")
            self._cached = (path, manifest, entries, after)
            return path, manifest, entries
        except (OSError, ValueError, KeyError, TypeError):
            self._cached = None
            return None

    def get(self, example_id, source_version=None):
        current = self.current()
        if current:
            path, manifest, entries = current
            entry = next((item for item in entries if item.id == example_id), None)
            if entry:
                version = manifest.pack_id + ":" + digest(dump(entry))
                if source_version is not None and source_version != version:
                    fail("reference_version_conflict", "官方参考包已更新，请刷新后重试。")
                return self.record(path, manifest, entry)
        fail("reference_preset_not_found", "官方参考图不存在或参考包未通过校验。")

    @staticmethod
    def record(path, manifest, entry):
        return {"id": entry.id, "title": entry.title, "source_version": manifest.pack_id + ":" + digest(dump(entry)),
            "requirements": dump(entry.requirements), "requirements_valid": True,
            "compat": dump(entry.compat), "notes": dump(ExampleNotes()), "origin": "official",
            "provenance": None, "ingest_state": "ready", "revision": None,
            "media_path": safe_path(path, entry.media)}
