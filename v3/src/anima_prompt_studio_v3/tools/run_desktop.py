from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import webbrowser
from pathlib import Path

from ..api import LocalApiServer
from ..data import DataContractError, DataPackManager, DataPackManifest


def default_app_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    return base / "AnimaPromptStudio"


def bundled_path(relative: str) -> Path | None:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root is None:
        return None
    return Path(bundle_root) / relative


def select_pack_source(source_root: Path) -> Path:
    candidates: list[tuple[object, str, Path]] = []
    if source_root.is_dir():
        for path in source_root.iterdir():
            if not path.is_dir() or not (path / "data-pack.json").is_file():
                continue
            try:
                manifest = DataPackManifest.load(path / "data-pack.json")
            except DataContractError:
                continue
            candidates.append((manifest.generated_at, manifest.pack_id, path))
    if not candidates:
        raise DataContractError(f"没有找到可安装的 V3 数据包：{source_root}")
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


def ensure_active_pack(manager: DataPackManager, source_root: Path | None) -> Path:
    try:
        return manager.active_reference_db()
    except DataContractError:
        if source_root is None:
            raise DataContractError("尚未启用数据包，也没有配置首次安装来源。") from None
    source = select_pack_source(source_root)
    print(f"首次启动：正在校验并安装数据包 {source.name}，请稍候……", flush=True)
    return manager.install(source).reference_db


def run(
    *,
    data_root: Path,
    frontend_dist: Path,
    workspace_db: Path,
    pack_source_root: Path | None = None,
    v2_database: Path | None = None,
    open_browser: bool = True,
    wait_event: threading.Event | None = None,
) -> int:
    frontend_dist = frontend_dist.resolve()
    if not (frontend_dist / "index.html").is_file():
        raise DataContractError(f"V3 网页尚未构建：{frontend_dist / 'index.html'}")
    manager = DataPackManager(data_root)
    reference_db = ensure_active_pack(manager, pack_source_root.resolve() if pack_source_root else None)
    selected_v2_database = v2_database.resolve() if v2_database and v2_database.is_file() else None
    with LocalApiServer(
        reference_db,
        frontend_dist=frontend_dist,
        workspace_db=workspace_db.resolve(),
        v2_database=selected_v2_database,
    ) as server:
        print(
            json.dumps(
                {
                    "status": "ready",
                    "url": server.bootstrap_url,
                    "data_pack": reference_db.parent.name,
                    "v2_integration": selected_v2_database is not None,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        print("ANIMA V3 已启动。关闭此窗口即可停止本地服务。", flush=True)
        if open_browser and not webbrowser.open(server.bootstrap_url, new=1):
            print(f"未能自动打开浏览器，请手动访问：{server.bootstrap_url}", flush=True)
        (wait_event or threading.Event()).wait()
    return 0


def main(argv: list[str] | None = None) -> int:
    app_data = default_app_data_dir()
    bundled_frontend = bundled_path("anima_prompt_studio_v3/web/dist")
    bundled_packs = bundled_path("data-packs")
    parser = argparse.ArgumentParser(description="Launch the local ANIMA V3 web desktop experience.")
    parser.add_argument("--data-root", type=Path, default=app_data / "v3" / "data")
    parser.add_argument("--pack-source-root", type=Path, default=bundled_packs)
    parser.add_argument("--frontend-dist", type=Path, default=bundled_frontend)
    parser.add_argument("--workspace-db", type=Path, default=app_data / "v3" / "workspaces.db")
    parser.add_argument("--v2-database", type=Path, default=app_data / "anima_prompt_studio.db")
    parser.add_argument("--without-v2", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--exit-after-startup",
        action="store_true",
        help="Start and stop immediately after readiness checks; intended for release smoke tests.",
    )
    args = parser.parse_args(argv)
    try:
        if args.frontend_dist is None:
            raise DataContractError("未指定 V3 Web 构建目录，且当前运行包没有内置网页。")
        wait_event = None
        if args.exit_after_startup:
            wait_event = threading.Event()
            wait_event.set()
        return run(
            data_root=args.data_root,
            frontend_dist=args.frontend_dist,
            workspace_db=args.workspace_db,
            pack_source_root=args.pack_source_root,
            v2_database=None if args.without_v2 else args.v2_database,
            open_browser=not args.no_browser,
            wait_event=wait_event,
        )
    except KeyboardInterrupt:
        return 0
    except (DataContractError, OSError, RuntimeError) as exc:
        print(f"启动失败：{exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
