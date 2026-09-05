from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path

from ..api import LocalApiServer
from ..data import DataPackManager


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the loopback-only ANIMA V3 API.")
    data_source = parser.add_mutually_exclusive_group(required=True)
    data_source.add_argument("--reference-db", type=Path)
    data_source.add_argument(
        "--data-root",
        type=Path,
        help="Managed data-pack root; uses the atomically selected active version.",
    )
    parser.add_argument(
        "--frontend-dist",
        type=Path,
        help="Optional built V3 web directory. Enables same-origin SPA serving.",
    )
    parser.add_argument(
        "--workspace-db",
        type=Path,
        default=Path(".local/state/workspaces.db"),
        help="Mutable workspace state database (default: .local/state/workspaces.db).",
    )
    parser.add_argument(
        "--v2-database",
        type=Path,
        help="Optional existing V2 database; enables remote generation with its profiles and workflows.",
    )
    args = parser.parse_args(argv)
    try:
        reference_db = (
            DataPackManager(args.data_root).active_reference_db()
            if args.data_root is not None
            else args.reference_db.resolve()
        )
        frontend_dist = args.frontend_dist.resolve() if args.frontend_dist is not None else None
        if args.v2_database is not None:
            from ..adapters.v2 import ensure_packaged_workflow_profiles

            imported_workflows = ensure_packaged_workflow_profiles(args.v2_database.resolve())
            if imported_workflows:
                print(f"已导入 {imported_workflows} 个内置验证工作流。", flush=True)
        with LocalApiServer(
            reference_db,
            frontend_dist=frontend_dist,
            workspace_db=args.workspace_db.resolve(),
            v2_database=args.v2_database.resolve() if args.v2_database is not None else None,
        ) as server:
            print(
                json.dumps(
                    {"base_url": server.base_url, "bootstrap_url": server.bootstrap_url},
                    ensure_ascii=False,
                ),
                flush=True,
            )
            threading.Event().wait()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
