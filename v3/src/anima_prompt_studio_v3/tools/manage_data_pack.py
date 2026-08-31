from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..data import DataContractError, DataPackManager


def run(
    root: Path,
    action: str,
    *,
    source: Path | None = None,
    pack_id: str | None = None,
    activate: bool = True,
) -> dict[str, Any]:
    manager = DataPackManager(root)
    if action == "install":
        if source is None:
            raise DataContractError("install 必须提供数据包源目录。")
        result = manager.install(source, activate=activate)
        return {"status": "ok", "action": action, "pack": result.model_dump(mode="json")}
    if action == "activate":
        if pack_id is None:
            raise DataContractError("activate 必须提供数据包 ID。")
        state = manager.activate(pack_id)
        return {"status": "ok", "action": action, "state": state.model_dump(mode="json")}
    if action == "rollback":
        state = manager.rollback()
        return {"status": "ok", "action": action, "state": state.model_dump(mode="json")}
    if action == "status":
        state = manager.state()
        return {
            "status": "ok",
            "action": action,
            "state": state.model_dump(mode="json") if state is not None else None,
            "installed": [item.model_dump(mode="json") for item in manager.installed()],
        }
    if action == "resolve":
        return {
            "status": "ok",
            "action": action,
            "reference_db": str(manager.active_reference_db(verify=True)),
        }
    raise DataContractError(f"未知数据包操作：{action}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install, activate, inspect, or roll back ANIMA V3 data packs.")
    parser.add_argument("--root", type=Path, required=True, help="Managed data root containing packs and active.json.")
    subparsers = parser.add_subparsers(dest="action", required=True)

    install_parser = subparsers.add_parser("install", help="Validate and install a local unpacked data pack.")
    install_parser.add_argument("--source", type=Path, required=True)
    install_parser.add_argument("--no-activate", action="store_true")

    activate_parser = subparsers.add_parser("activate", help="Atomically activate an installed pack.")
    activate_parser.add_argument("pack_id")
    subparsers.add_parser("rollback", help="Atomically switch back to the previous active pack.")
    subparsers.add_parser("status", help="Show installed and active packs.")
    subparsers.add_parser("resolve", help="Verify and print the active reference.db path.")

    args = parser.parse_args(argv)
    try:
        report = run(
            args.root,
            args.action,
            source=getattr(args, "source", None),
            pack_id=getattr(args, "pack_id", None),
            activate=not getattr(args, "no_activate", False),
        )
    except DataContractError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
