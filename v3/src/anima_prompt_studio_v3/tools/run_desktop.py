from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

from ..api import LocalApiServer
from ..data import DataContractError, DataPackManager, DataPackManifest
from .desktop_single_instance import (
    DesktopInstanceLease,
    read_instance_state,
    save_instance_state,
    wait_for_existing_instance,
)


COMFY_ACCESS_URL = "http://127.0.0.1:18188"
PORT_STATE_SCHEMA = "anima-local-api-port/1"


def desktop_port_state_path(workspace_db: Path) -> Path:
    workspace_db = workspace_db.resolve()
    return workspace_db.with_name(workspace_db.name + ".local-api.json")


def read_desktop_port(workspace_db: Path) -> int:
    current = read_instance_state(workspace_db)
    if current:
        return int(current["port"])
    try:
        state = json.loads(desktop_port_state_path(workspace_db).read_text(encoding="utf-8"))
        if not isinstance(state, dict) or state.get("schema") != PORT_STATE_SCHEMA:
            return 0
        port = state.get("port")
        return port if isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535 else 0
    except (OSError, ValueError, UnicodeError):
        return 0


def save_desktop_port(workspace_db: Path, port: int) -> None:
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("保存的本地端口必须为 1–65535 的整数。")
    state_path = desktop_port_state_path(workspace_db)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=state_path.parent,
                                         prefix=state_path.name + ".", suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            json.dump({"schema": PORT_STATE_SCHEMA, "port": port}, file)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, state_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


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
    verify_runtime: bool = False,
) -> int:
    if verify_runtime and (v2_database is None or v2_database.exists()):
        raise DataContractError("运行时烟测必须使用尚不存在的独立数据库路径。")
    frontend_dist = frontend_dist.resolve()
    if not (frontend_dist / "index.html").is_file():
        raise DataContractError(f"V3 网页尚未构建：{frontend_dist / 'index.html'}")
    workspace_db = workspace_db.resolve()
    lease = DesktopInstanceLease(workspace_db)
    if not lease.acquire():
        existing_url = wait_for_existing_instance(workspace_db, lease=lease)
        if existing_url:
            print(f"ANIMA V3 已在运行，正在打开现有窗口：{existing_url}", flush=True)
            if open_browser and not webbrowser.open(existing_url, new=1):
                print(f"未能自动打开浏览器，请手动访问：{existing_url}", flush=True)
            return 0
        if not lease.held:
            raise RuntimeError("已有 ANIMA V3 正在启动，但未能确认其本地地址。")
    instance_id = uuid4().hex
    try:
        manager = DataPackManager(data_root)
        reference_db = ensure_active_pack(manager, pack_source_root.resolve() if pack_source_root else None)
        # A new installation has no legacy database yet. Passing a runtime path
        # means initialize it; only an explicit None disables generation services.
        selected_v2_database = v2_database.resolve() if v2_database is not None else None
        preferred_port = read_desktop_port(workspace_db)
        if selected_v2_database is not None:
            from ..runtime.packaged_workflows import migrate_packaged_workflow_ownership
            migrate_packaged_workflow_ownership(selected_v2_database)
        with LocalApiServer(
            reference_db,
            frontend_dist=frontend_dist,
            workspace_db=workspace_db,
            v2_database=selected_v2_database,
            preferred_port=preferred_port,
            allow_local_sessions=True,
            desktop_instance_id=instance_id,
        ) as server:
            if preferred_port and server.port != preferred_port:
                print(f"上次本地端口 {preferred_port} 已被占用或不可用；本地地址已改为 {server.base_url}。"
                      "浏览器草稿和偏好按地址分别保存。", flush=True)
            try:
                save_instance_state(workspace_db, server.port, instance_id)
            except OSError as exc:
                raise RuntimeError("未能发布本地实例地址，启动已安全停止；请重试。") from exc
            if verify_runtime:
                verify_first_connection(server)
            print(
                json.dumps(
                    {
                        "status": "ready",
                        "url": server.base_url + "/",
                        "data_pack": reference_db.parent.name,
                        "v2_integration": selected_v2_database is not None,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            print("ANIMA V3 已启动。关闭此窗口即可停止本地服务。", flush=True)
            if selected_v2_database is not None:
                print(f"ComfyUI 网页维护入口：{COMFY_ACCESS_URL}（后台安全隧道连接中）", flush=True)
            clean_url = server.base_url + "/"
            if open_browser and not webbrowser.open(clean_url, new=1):
                print(f"未能自动打开浏览器，请手动访问：{clean_url}", flush=True)
            (wait_event or threading.Event()).wait()
        return 0
    finally:
        lease.close()


def verify_first_connection(server: LocalApiServer) -> None:
    """Exercise real packaged API/auth/settings on an explicitly fresh store."""
    token = ""

    def request(path: str, payload: dict | None = None) -> dict:
        headers = {"Origin": server.base_url}
        if token:
            headers["X-Anima-Session"] = token
        if payload is not None:
            headers["Content-Type"] = "application/json"
        req = Request(server.base_url + path, headers=headers,
                      data=json.dumps(payload).encode() if payload is not None else None)
        with urlopen(req, timeout=10) as response:
            return json.loads(response.read())

    token = request("/api/v3/session/exchange", {"bootstrap_token": server.runtime.bootstrap_token})["session_token"]
    if not request("/api/v3/bootstrap")["features"]["remote_generation"]:
        raise RuntimeError("空目录运行时未启用生成服务。")
    if request("/api/v3/settings/remote-profiles")["items"]:
        raise RuntimeError("运行时烟测拒绝修改已有连接。")
    created = request("/api/v3/settings/remote-profiles", {
        "display_name": "First-install smoke (disabled)", "connection_type": "local", "enabled": False,
    })
    if not created.get("id") or created.get("enabled") is not False:
        raise RuntimeError("新用户首个连接未能创建。")
    print("空目录运行时烟测通过：已启用生成服务，并通过 API 建立首个禁用的本地连接。", flush=True)


def main(argv: list[str] | None = None) -> int:
    app_data = default_app_data_dir()
    bundled_frontend = bundled_path("anima_prompt_studio_v3/web/dist")
    bundled_packs = bundled_path("data-packs")
    parser = argparse.ArgumentParser(description="Launch the local ANIMA V3 web desktop experience.")
    parser.add_argument("--data-root", type=Path, default=app_data / "v3" / "data")
    parser.add_argument("--pack-source-root", type=Path, default=bundled_packs)
    parser.add_argument("--frontend-dist", type=Path, default=bundled_frontend)
    parser.add_argument("--workspace-db", type=Path, default=app_data / "v3" / "workspaces.db")
    parser.add_argument("--runtime-database", "--v2-database", dest="v2_database",
                        type=Path, default=app_data / "anima_prompt_studio.db")
    parser.add_argument("--without-runtime", "--without-v2", dest="without_v2", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--verify-runtime", action="store_true",
                        help="仅发布烟测：在全新运行库验证 API 创建首个连接，须同时指定 --exit-after-startup --no-browser")
    parser.add_argument("--install-bundled-examples", action="store_true",
                        help="安装内置参考样例到所选工作台目录后退出，不启动浏览器或生图服务")
    parser.add_argument(
        "--exit-after-startup",
        action="store_true",
        help="Start and stop immediately after readiness checks; intended for release smoke tests.",
    )
    args = parser.parse_args(argv)
    if args.verify_runtime and (not args.exit_after_startup or not args.no_browser or args.without_v2):
        parser.error("--verify-runtime 要求 --exit-after-startup --no-browser，并启用运行时。")
    try:
        if args.install_bundled_examples:
            from ..storage.bundled_examples import install_bundled_examples
            try:
                result = install_bundled_examples(args.workspace_db.resolve().parent / "official-examples")
            except ValueError as exc:
                raise DataContractError("内置参考包校验失败，原激活指针未被替换。") from exc
            print(f"已启用 {result['id']}，{result['count']} 个官方参考。", flush=True)
            return 0
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
            verify_runtime=args.verify_runtime,
        )
    except KeyboardInterrupt:
        return 0
    except (DataContractError, OSError, RuntimeError) as exc:
        print(f"启动失败：{exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
