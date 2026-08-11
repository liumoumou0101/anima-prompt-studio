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


def resolve_gallery_trash_image(relative_path: str, output_root: Path) -> Path | None:
    """Resolve a relative path inside the private gallery trash directory."""
    trash_root = (output_root.expanduser().resolve() / TRASH_DIR_NAME).resolve()
    candidate = (trash_root / relative_path).resolve()
    try:
        candidate.relative_to(trash_root)
    except ValueError:
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


def restore_images_from_trash(
    paths: list[Path],
    output_root: Path,
) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Restore images from a timestamped gallery-trash batch."""
    root = output_root.expanduser().resolve()
    trash_root = (root / TRASH_DIR_NAME).resolve()
    restored: list[Path] = []
    failed: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for raw_path in paths:
        source = Path(raw_path)
        try:
            resolved = source.resolve()
            relative = resolved.relative_to(trash_root)
            if len(relative.parts) < 2:
                raise ValueError
            key = str(resolved).casefold()
            if key in seen:
                continue
            seen.add(key)
            if resolved.suffix.casefold() not in IMAGE_SUFFIXES or not resolved.is_file():
                failed.append((source, "回收站图片不存在"))
                continue
            destination = root.joinpath(*relative.parts[1:])
        except (OSError, ValueError):
            failed.append((source, "图片不在画廊回收站内"))
            continue

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                stem, suffix, index = destination.stem, destination.suffix, 2
                while destination.exists():
                    destination = destination.with_name(f"{stem}（已恢复 {index}）{suffix}")
                    index += 1
            shutil.move(str(resolved), str(destination))
            restored.append(destination)
        except (OSError, shutil.Error) as exc:
            failed.append((source, str(exc)))
    _remove_empty_trash_dirs(trash_root)
    return restored, failed


def delete_images_permanently(
    paths: list[Path],
    output_root: Path,
) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Permanently delete only files already contained in gallery trash."""
    trash_root = (output_root.expanduser().resolve() / TRASH_DIR_NAME).resolve()
    deleted: list[Path] = []
    failed: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for raw_path in paths:
        path = Path(raw_path)
        try:
            resolved = path.resolve()
            resolved.relative_to(trash_root)
            key = str(resolved).casefold()
            if key in seen:
                continue
            seen.add(key)
            if resolved.suffix.casefold() not in IMAGE_SUFFIXES or not resolved.is_file():
                failed.append((path, "回收站图片不存在"))
                continue
            resolved.unlink()
            deleted.append(resolved)
        except (OSError, ValueError) as exc:
            failed.append((path, str(exc) or "图片不在画廊回收站内"))
    _remove_empty_trash_dirs(trash_root)
    return deleted, failed


def _remove_empty_trash_dirs(trash_root: Path) -> None:
    if not trash_root.is_dir():
        return
    for directory in sorted(
        (path for path in trash_root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            pass
