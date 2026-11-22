"""Build a manifest for a locally curated pack; never fetch or modify images."""
import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path

from ..core.requirements import dump
from ..storage.official_examples import ExamplesManifest, OfficialPack, safe_path


def build_manifest(source: Path, pack_id: str):
    source = Path(source).resolve(strict=True)
    manifest_path = source / "examples-pack.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        raise ValueError("Manifest already exists; use a new source directory for a new version")
    catalog_path = safe_path(source, "catalog.json")
    if catalog_path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Catalog too large")
    catalog = json.loads(catalog_path.read_bytes())
    if not isinstance(catalog, list):
        raise ValueError("Catalog must be an array")
    inventory = []
    total = 0
    for path in sorted(source.rglob("*")):
        # No links or junctions in a distributable pack, even to files inside it.
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError("Pack must contain ordinary files and directories")
        raw = path.relative_to(source).as_posix()
        resolved = safe_path(source, raw)
        if resolved.is_dir():
            continue
        if not resolved.is_file():
            raise ValueError("Invalid pack file")
        if not (raw in {"catalog.json", "NOTICE.txt"}
                or raw.startswith(("LICENSES/", "media/", "SOURCES/"))):
            raise ValueError("Unexpected file in pack source")
        size = resolved.stat().st_size
        total += size
        if size > 21 * 1024 * 1024 or total > 500 * 1024 * 1024 or len(inventory) >= 3000:
            raise ValueError("Pack exceeds size or file count limit")
        data = resolved.read_bytes()
        if len(data) != size:
            raise ValueError("Pack source changed during build")
        inventory.append({"path": raw, "size": size, "sha256": sha256(data).hexdigest()})
    manifest = ExamplesManifest.model_validate({
        "contract": "anima-v3-examples/1", "pack_id": pack_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "counts": {"examples": len(catalog), "files": len(inventory)}, "files": inventory,
    })
    # Exclusive creation protects a pre-existing manifest, including concurrent builds.
    with manifest_path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(dump(manifest), ensure_ascii=False, indent=2) + "\n")
    try:
        OfficialPack.validate(source)
    except Exception:
        manifest_path.unlink()
        raise
    return manifest


def main():
    parser = argparse.ArgumentParser(description="为本地精选参考图生成并校验 manifest；不下载图片，不修改原图，不覆盖既有 manifest。")
    parser.add_argument("source", type=Path)
    parser.add_argument("--pack-id", required=True)
    args = parser.parse_args()
    try:
        manifest = build_manifest(args.source, args.pack_id)
    except (ValueError, OSError):
        parser.exit(1, "参考包构建失败：请检查源目录、图片和许可文件；已有 manifest 不会被覆盖。\n")
    print(f"已校验 {manifest.pack_id}：{manifest.counts.examples} 张图片，{manifest.counts.files} 个文件。尚未安装或激活。")


if __name__ == "__main__":
    main()
