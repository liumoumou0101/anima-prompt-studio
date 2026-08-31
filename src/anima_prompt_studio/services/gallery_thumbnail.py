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
