from __future__ import annotations

from pathlib import Path
from typing import Any


def infer_workflow_model_profiles(
    workflow: dict[str, Any],
    source_name: str = "",
) -> list[str]:
    """Infer the app model profile for known ANIMA text-to-image workflows.

    Compshare's numbered workflows are stable identifiers. Model filenames are
    also inspected so imported or derived copies keep working after renaming.
    An empty result means that the workflow is genuinely unknown and should not
    be restricted automatically.
    """
    name = Path(source_name).stem.casefold()
    if name.startswith("23_"):
        return ["anima_turbo_v1_1"]
    if name.startswith("24_"):
        return ["animayume_v1_0_final"]
    if name.startswith("25_"):
        return ["miaomiao_harem_anima_v1_6"]
    if name.startswith("26_"):
        return ["anima_turbo_v1_1"]
    if name.startswith("27_"):
        return ["animayume_v1_0_final"]
    if name.startswith("28_"):
        return ["miaomiao_harem_anima_v1_6"]
    if name.startswith(("21_", "22_")):
        return ["anima_aesthetic_v1"]
    if name.startswith(("01_", "04_")):
        return ["anima_base_v1"]
    if name.startswith(("02_", "05_")):
        return ["anima_turbo_v1"]

    values = " ".join(_string_values(workflow)).casefold()
    if "anima-turbo-v1.1" in values or "anima_turbo_v1_1" in values:
        return ["anima_turbo_v1_1"]
    if "animayume" in values:
        return ["animayume_v1_0_final"]
    if "miaomiao" in values:
        return ["miaomiao_harem_anima_v1_6"]
    if "anima-aesthetic" in values or "anima_aesthetic" in values:
        return ["anima_aesthetic_v1"]
    # DMDX is the distilled, low-step graph even when its underlying UNet is Base.
    if "dmdx" in name or "dmdx" in values or "anima-turbo" in values or "anima_turbo" in values:
        return ["anima_turbo_v1"]
    if "anima-base" in values or "anima_base" in values:
        return ["anima_base_v1"]
    return []


def _string_values(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _string_values(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _string_values(item)
