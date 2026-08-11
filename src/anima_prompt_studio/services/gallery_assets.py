from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
TRASH_DIR_NAME = ".trash"


def is_in_gallery_trash(path: Path, output_root: Path) -> bool:
    try:
        return path.resolve().is_relative_to((output_root / TRASH_DIR_NAME).resolve())
    except (OSError, ValueError):
        return False


def resolve_gallery_image(relative_path: str, output_root: Path) -> Path | None:
    """Resolve a relative gallery path without allowing traversal or trash access."""
    root = output_root.expanduser().resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if is_in_gallery_trash(candidate, root):
        return None
    if candidate.suffix.casefold() not in IMAGE_SUFFIXES or not candidate.is_file():
        return None
    return candidate


def move_images_to_trash(
    paths: list[Path],
    output_root: Path,
) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Move images under the configured root to a recoverable, ignored trash folder."""
    root = output_root.expanduser().resolve()
    trash_dir = root / TRASH_DIR_NAME / datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    moved: list[Path] = []
    failed: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for raw_path in paths:
        source = Path(raw_path)
        try:
            resolved = source.resolve()
            key = str(resolved).casefold()
            if key in seen:
                continue
            seen.add(key)
            relative = resolved.relative_to(root)
            if relative.parts and relative.parts[0] == TRASH_DIR_NAME:
                failed.append((source, "图片已经在回收站中"))
                continue
            if resolved.suffix.casefold() not in IMAGE_SUFFIXES or not resolved.is_file():
                failed.append((source, "文件不存在或不是受支持的图片"))
                continue
        except (OSError, ValueError):
            failed.append((source, "图片不在当前图片保存目录内"))
            continue

        destination = trash_dir / relative
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                stem = destination.stem
                suffix = destination.suffix
                index = 2
                while destination.exists():
                    destination = destination.with_name(f"{stem} ({index}){suffix}")
                    index += 1
            shutil.move(str(resolved), str(destination))
            moved.append(destination)
        except (OSError, shutil.Error) as exc:
            failed.append((source, str(exc)))
    return moved, failed
