"""Disposable, bounded thumbnail cache; originals remain the only authority."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import re
from threading import RLock
from uuid import uuid4

from PIL import Image, ImageOps


class ReferenceThumbnailCache:
    def __init__(self, root: Path, *, max_bytes=256 * 1024 * 1024):
        self.root = Path(root)
        self.max_bytes = max_bytes
        self.lock = RLock()

    @staticmethod
    def render(data: bytes, size: int) -> bytes:
        with Image.open(BytesIO(data)) as picture:
            # Files may have changed since upload validation. Bound decoding again.
            if (picture.format not in {"PNG", "JPEG", "WEBP"}
                    or getattr(picture, "n_frames", 1) != 1
                    or picture.width * picture.height > 40_000_000):
                raise ValueError("Invalid reference image")
            picture = ImageOps.exif_transpose(picture).convert("RGB")
            picture.thumbnail((size, size))
            output = BytesIO()
            picture.save(output, "JPEG", quality=85)
            return output.getvalue()

    def get(self, example_id: str, data: bytes, size: int) -> bytes:
        if type(size) is not int or not 64 <= size <= 2048:
            raise ValueError("Invalid thumbnail size")
        # Include the renderer contract so future encoding changes invalidate old caches.
        key = sha256(f"reference-jpeg/1:{example_id}:{sha256(data).hexdigest()}:{size}".encode()).hexdigest()
        target = self.root / (key + ".jpg")
        with self.lock:
            if target.resolve().is_relative_to(self.root.resolve()):
                try:
                    if target.stat().st_size > 16 * 1024 * 1024:
                        raise ValueError("Oversized thumbnail")
                    cached = target.read_bytes()
                    with Image.open(BytesIO(cached)) as image:
                        if image.format != "JPEG" or max(image.size) > size:
                            raise ValueError("Invalid cached thumbnail")
                        image.load()
                    os.utime(target, None)
                    return cached
                except (OSError, ValueError):
                    pass
            result = self.render(data, size)
            # A full/unwritable cache must not make the reference image unavailable.
            temporary = self.root / (".thumb-" + uuid4().hex)
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                if not target.resolve().is_relative_to(self.root.resolve()):
                    return result
                temporary.write_bytes(result)
                temporary.replace(target)
                self.prune()
            except OSError:
                pass
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            return result

    def prune(self):
        """Evict only our own direct cache files; never traverse reference media."""
        entries = []
        for path in self.root.iterdir():
            if re.fullmatch(r"[a-f0-9]{64}\.jpg", path.name) and path.is_file() and not path.is_symlink():
                if path.resolve().is_relative_to(self.root.resolve()):
                    stat = path.stat()
                    entries.append((stat.st_mtime_ns, stat.st_size, path))
        total = sum(size for _, size, _ in entries)
        for _, size, path in sorted(entries):
            if total <= self.max_bytes:
                break
            path.unlink(missing_ok=True)
            total -= size
