from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from ..data import (
    DataContractError,
    DataPackSnapshot,
    ReferenceBuildInputs,
    ReferenceDatabaseBuilder,
    UpstreamSource,
)


class BuildInputsConfig(BaseModel):
    tags: str
    aliases: str | None = None
    tag_cooccurrence: str | None = None
    artist_cooccurrence: str | None = None
    tag_groups: str | None = None


class BuildConfig(BaseModel):
    pack_id: str
    snapshot: DataPackSnapshot
    sources: list[UpstreamSource]
    inputs: BuildInputsConfig
    output_dir: str
    algorithms: dict[str, str] | None = None


def _path(base: Path, value: str | None) -> Path | None:
    if value is None:
        return None
    candidate = Path(value)
    return candidate.resolve() if candidate.is_absolute() else (base / candidate).resolve()


def run(config_path: Path, *, overwrite: bool = False) -> dict[str, Any]:
    config_path = config_path.resolve()
    try:
        config = BuildConfig.model_validate_json(config_path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise DataContractError(f"无法读取构建配置：{exc}") from exc

    base = config_path.parent
    output_dir = _path(base, config.output_dir)
    assert output_dir is not None
    inputs = ReferenceBuildInputs(
        tags=_path(base, config.inputs.tags),
        aliases=_path(base, config.inputs.aliases),
        tag_cooccurrence=_path(base, config.inputs.tag_cooccurrence),
        artist_cooccurrence=_path(base, config.inputs.artist_cooccurrence),
        tag_groups=_path(base, config.inputs.tag_groups),
    )
    assert inputs.tags is not None
    builder = ReferenceDatabaseBuilder(
        inputs,
        pack_id=config.pack_id,
        snapshot=config.snapshot,
        sources=config.sources,
        algorithms=config.algorithms,
    )
    manifest = builder.build(
        output_dir / "reference.db",
        output_dir / "data-pack.json",
        overwrite=overwrite,
    )
    return {
        "status": "ok",
        "output_dir": str(output_dir),
        "manifest": manifest.model_dump(mode="json"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a versioned ANIMA V3 reference-data pack.")
    parser.add_argument("--config", type=Path, required=True, help="UTF-8 JSON build configuration")
    parser.add_argument("--overwrite", action="store_true", help="replace an existing output pack")
    args = parser.parse_args(argv)
    try:
        payload = run(args.config, overwrite=args.overwrite)
    except DataContractError as exc:
        payload = {"status": "error", "error": str(exc)}
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
