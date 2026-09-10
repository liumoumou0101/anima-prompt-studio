"""Locate the read-only shipped pack; activation remains an explicit operation."""
from pathlib import Path
import sys

from .official_examples import OfficialPack


PACK_ID = "cma-styles-20260910-v1"


def bundled_example_source() -> Path:
    package = Path(__file__).resolve().parents[1]
    packaged = package / "example_packs" / PACK_ID
    if packaged.exists():
        return packaged
    # Editable/source installs keep one canonical copy outside the Python package.
    project = package.parent.parent
    source = project / "example-packs" / PACK_ID
    if not getattr(sys, "frozen", False) and (project / "pyproject.toml").is_file() and source.is_dir():
        return source
    raise FileNotFoundError("当前安装不包含官方参考样例包。")


def install_bundled_examples(destination: Path):
    return OfficialPack(destination).install(bundled_example_source())
