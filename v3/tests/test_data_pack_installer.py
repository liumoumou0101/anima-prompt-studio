from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from anima_prompt_studio_v3.data import (
    DataContractError,
    DataPackManager,
    DataPackSnapshot,
    ReferenceBuildInputs,
    ReferenceDatabaseBuilder,
    ReferenceDataStore,
    UpstreamSource,
)
from anima_prompt_studio_v3.data import installer as installer_module
from anima_prompt_studio_v3.tools import run_api, run_desktop
from anima_prompt_studio_v3.tools.manage_data_pack import run


FIXTURES = Path(__file__).parent / "fixtures" / "upstream_current"


def build_pack(root: Path, pack_id: str) -> Path:
    pack = root / pack_id
    builder = ReferenceDatabaseBuilder(
        ReferenceBuildInputs(
            tags=FIXTURES / "tags_enhanced.csv",
            aliases=FIXTURES / "tag_aliases.csv",
            tag_cooccurrence=FIXTURES / "cooccurrence_clean.csv",
            artist_cooccurrence=FIXTURES / "tag_artist_cooc.csv",
            tag_groups=FIXTURES / "tag_groups.json",
        ),
        pack_id=pack_id,
        snapshot=DataPackSnapshot(
            target_cutoff=date(2025, 9, 30),
            cutoff_mode="approximate",
            source_observed_at=date(2026, 8, 25),
            corpus_size=100_000,
            corpus_size_mode="estimated",
        ),
        sources=[
            UpstreamSource(
                name="DanbooruSearchOnline",
                repository="https://github.com/SuzumiyaAkizuki/DanbooruSearchOnline",
                commit="0636f762694fc436b4ac472cf59b85d172eaaac4",
                license="GPL-3.0",
            )
        ],
    )
    builder.build(pack / "reference.db", pack / "data-pack.json")
    return pack


def test_install_activate_and_rollback_without_replacing_open_database(tmp_path: Path) -> None:
    source = tmp_path / "source"
    first = build_pack(source, "pack-r1")
    second = build_pack(source, "pack-r2")
    manager = DataPackManager(tmp_path / "managed")

    installed = manager.install(first)
    assert installed.active is True
    assert manager.state().active_pack_id == "pack-r1"  # type: ignore[union-attr]
    assert manager.install(first).path == installed.path

    with ReferenceDataStore(manager.active_reference_db()) as old_store:
        assert old_store.pack_id == "pack-r1"
        manager.install(second, activate=False)
        assert manager.state().active_pack_id == "pack-r1"  # type: ignore[union-attr]
        state = manager.activate("pack-r2")
        assert state.previous_pack_id == "pack-r1"
        assert old_store.search("maid")[0]["name"] == "maid"

    assert manager.active_reference_db(verify=True).parent.name == "pack-r2"
    rolled_back = manager.rollback()
    assert rolled_back.active_pack_id == "pack-r1"
    assert rolled_back.previous_pack_id == "pack-r2"


def test_tampered_pack_is_rejected_without_changing_active_state(tmp_path: Path) -> None:
    source = tmp_path / "source"
    good = build_pack(source, "pack-good")
    bad = build_pack(source, "pack-bad")
    manager = DataPackManager(tmp_path / "managed")
    manager.install(good)
    original_state = manager.state_path.read_bytes()
    with (bad / "reference.db").open("ab") as stream:
        stream.write(b"tampered")

    with pytest.raises(DataContractError, match="大小不匹配"):
        manager.install(bad)

    assert manager.state_path.read_bytes() == original_state
    assert not (manager.packs_dir / "pack-bad").exists()


def test_atomic_pointer_failure_preserves_old_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    first = build_pack(source, "pack-r1")
    second = build_pack(source, "pack-r2")
    manager = DataPackManager(tmp_path / "managed")
    manager.install(first)
    manager.install(second, activate=False)
    original_state = manager.state_path.read_bytes()
    real_replace = installer_module.os.replace

    def fail_state_replace(source_path: Path, target_path: Path) -> None:
        if Path(target_path) == manager.state_path:
            raise PermissionError("simulated Windows sharing violation")
        real_replace(source_path, target_path)

    monkeypatch.setattr(installer_module.os, "replace", fail_state_replace)
    with pytest.raises(DataContractError, match="无法原子切换"):
        manager.activate("pack-r2")

    assert manager.state_path.read_bytes() == original_state
    assert not list(manager.root.glob(".active.json.*.tmp"))


def test_status_cli_and_missing_rollback(tmp_path: Path) -> None:
    pack = build_pack(tmp_path / "source", "pack-r1")
    root = tmp_path / "managed"
    report = run(root, "install", source=pack)
    assert report["pack"]["pack_id"] == "pack-r1"
    status = run(root, "status")
    assert status["state"]["active_pack_id"] == "pack-r1"
    assert status["installed"][0]["active"] is True
    assert run(root, "resolve")["reference_db"].endswith("reference.db")

    with pytest.raises(DataContractError, match="没有可回滚"):
        DataPackManager(root).rollback()


def test_corrupt_state_and_pack_id_collision_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    pack = build_pack(source, "pack-r1")
    manager = DataPackManager(tmp_path / "managed")
    manager.install(pack)

    manifest_path = pack / "data-pack.json"
    changed = json.loads(manifest_path.read_text(encoding="utf-8"))
    changed["algorithms"]["search_index"] = "fts5-v2"
    manifest_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(DataContractError, match="内容不同"):
        manager.install(pack)

    manager.state_path.write_text("{broken", encoding="utf-8")
    with pytest.raises(DataContractError, match="活动状态损坏"):
        manager.state()


def test_api_data_root_resolves_pointer_without_repeating_full_pack_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference_db = tmp_path / "reference.db"
    calls: list[bool] = []

    class FakeManager:
        def __init__(self, root: Path) -> None:
            assert root == tmp_path / "managed"

        def active_reference_db(self, *, verify: bool = False) -> Path:
            calls.append(verify)
            return reference_db

    class FakeServer:
        base_url = "http://127.0.0.1:12345"
        bootstrap_url = "http://127.0.0.1:12345/?bootstrap=test"

        def __init__(self, selected_db: Path, **_kwargs: object) -> None:
            assert selected_db == reference_db

        def __enter__(self) -> "FakeServer":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    class FakeEvent:
        def wait(self) -> None:
            return None

    monkeypatch.setattr(run_api, "DataPackManager", FakeManager)
    monkeypatch.setattr(run_api, "LocalApiServer", FakeServer)
    monkeypatch.setattr(run_api.threading, "Event", FakeEvent)

    assert run_api.main(["--data-root", str(tmp_path / "managed")]) == 0
    assert calls == [False]


def test_desktop_launcher_first_run_installs_pack_and_starts_local_app(tmp_path: Path) -> None:
    source_root = tmp_path / "bundled-packs"
    build_pack(source_root, "pack-r1")
    frontend = tmp_path / "web" / "dist"
    frontend.mkdir(parents=True)
    (frontend / "index.html").write_text("<!doctype html><title>ANIMA V3</title>", encoding="utf-8")
    wait_event = run_desktop.threading.Event()
    wait_event.set()

    assert run_desktop.run(
        data_root=tmp_path / "managed",
        frontend_dist=frontend,
        workspace_db=tmp_path / "state" / "workspaces.db",
        pack_source_root=source_root,
        v2_database=None,
        open_browser=False,
        wait_event=wait_event,
    ) == 0
    assert DataPackManager(tmp_path / "managed").state().active_pack_id == "pack-r1"  # type: ignore[union-attr]


def test_repository_has_double_click_launcher_wired_to_v3_desktop() -> None:
    root = Path(__file__).parents[2]
    launcher = (root / "启动 ANIMA V3.cmd").read_text(encoding="utf-8")
    powershell = (root / "tools" / "start_anima_v3.ps1").read_text(encoding="utf-8")
    assert launcher.isascii()
    assert "start_anima_v3.ps1" in launcher
    assert '"v3\\src"' in powershell
    assert '"src"' in powershell
    assert "anima_prompt_studio_v3.tools.run_desktop" in powershell
    assert '"--pack-source-root"' in powershell
    assert '"--frontend-dist"' in powershell
