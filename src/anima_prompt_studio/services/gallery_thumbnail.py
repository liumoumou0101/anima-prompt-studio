from __future__ import annotations

import hashlib
import threading
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImageReader


def gallery_image_dimensions(source: Path, fallback_width: int = 0, fallback_height: int = 0) -> tuple[int, int]:
    size = QImageReader(str(source)).size()
    if size.isValid():
        return size.width(), size.height()
    return fallback_width, fallback_height


class GalleryThumbnailCache:
    """Create deterministic WebP thumbnails for a trusted local source image."""

    def __init__(self, cache_root: Path) -> None:
        self.cache_root = Path(cache_root).expanduser().resolve()
        self._lock = threading.Lock()

    def thumbnail(self, source: Path, size: int) -> Path | None:
        source = Path(source).expanduser().resolve()
        size = max(160, min(int(size), 1440))
        try:
            stat = source.stat()
        except OSError:
            return None
        digest = hashlib.sha256(
            f"{source}|{stat.st_mtime_ns}|{stat.st_size}|{size}".encode("utf-8")
        ).hexdigest()
        target = self.cache_root / digest[:2] / f"{digest}.webp"
        if target.is_file():
            return target
        with self._lock:
            if target.is_file():
                return target
            reader = QImageReader(str(source))
            reader.setAutoTransform(True)
            image = reader.read()
            if image.isNull():
                return source
            scaled = image.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(".tmp")
            if not scaled.save(str(temporary), "WEBP", 82):
                return source
            temporary.replace(target)
        return target

    def purge(self, source: Path, *, aliases: tuple[Path, ...] = ()) -> int:
        """Remove every cached size for a source before its image is permanently deleted."""
        source = Path(source).expanduser().resolve()
        try:
            stat = source.stat()
        except OSError:
            return 0
        removed = 0
        identities = (source, *(Path(alias).expanduser().resolve() for alias in aliases))
        with self._lock:
            for identity in identities:
                for size in range(160, 1441):
                    digest = hashlib.sha256(
                        f"{identity}|{stat.st_mtime_ns}|{stat.st_size}|{size}".encode("utf-8")
                    ).hexdigest()
                    target = self.cache_root / digest[:2] / f"{digest}.webp"
                    try:
                        target.unlink()
                        removed += 1
                    except FileNotFoundError:
                        continue
                    except OSError:
                        continue
            if self.cache_root.is_dir():
                for directory in self.cache_root.iterdir():
                    try:
                        directory.rmdir()
                    except OSError:
                        pass
        return removed
