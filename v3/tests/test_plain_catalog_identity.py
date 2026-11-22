"""Learned gateway identities apply to plain imported URL clients and probes."""
import asyncio
from types import SimpleNamespace

import pytest

from anima_prompt_studio_v3.remote.comfy_client import ComfyUIClient
from anima_prompt_studio_v3.remote.connections import read_runtime_identity
from anima_prompt_studio_v3.remote.preparation_budget import DirectPreparationBudget, DirectPreparationTimeout
from anima_prompt_studio_v3.remote.runtime_identity import bind_runtime_identity, confirm_runtime_identity
from anima_prompt_studio_v3.runtime.environment_probe import EnvironmentProbe
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
from test_cloud_submission_mapping import inspected_catalog
from test_http_runtime_identity import Session, profile


@pytest.mark.parametrize("changed", [False, True])
def test_probe_uses_plain_urls_learned_catalog_identity(inspected_catalog, changed):
    state = inspected_catalog
    state.manager.inspect(state.remote.id)
    session = Session("replacement-runtime" if changed else "catalog-runtime")
    probe = EnvironmentProbe(state.database,
        transport_factory=lambda *args, **kwargs: SimpleNamespace(
            base_url=state.remote.http_base_url, open=lambda *args: None, close=lambda: None),
        client_factory=lambda url, **kwargs: ComfyUIClient(url, session=session, **kwargs))
    candidate = {"id": state.remote.id, "profile": state.remote, "epoch": 0, "signature": "catalog-identity"}
    try:
        result = asyncio.run(probe(candidate, probe.clock() + 5, 0))
    finally:
        probe.close()
    assert any(url.endswith("/_moss/info") for url in session.calls)
    repository = SQLiteRepository(state.database)
    try:
        authority = repository.get_setting("http_runtime_identity:" + state.remote.id)
        assert authority["runtime_id"] == "catalog-runtime"
        assert bool(authority.get("conflicted")) == changed
        assert repository.get_remote_profile(state.remote.id) == state.remote
        if changed:
            assert result.reason_codes == ["instance_changed"]
            assert repository.get_setting("environment_epoch:" + state.remote.id) == 1
        else:
            assert result.connection_state == "online" and result.capabilities_state == "ready"
            assert result.identity_strength == "strong" and result.instance_identity == "catalog-runtime"
            assert repository.get_setting("environment_epoch:" + state.remote.id, 0) == 0
    finally:
        repository.close()


@pytest.mark.parametrize("plain", [False, True])
def test_real_info_reader_preserves_direct_preparation_timeout(tmp_path, plain):
    database = tmp_path / "runtime.db"
    remote = profile(None, False) if plain else profile()
    repository = SQLiteRepository(database)
    repository.save_remote_profile(remote)
    repository.close()
    confirm_runtime_identity(database, remote, "runtime-1")
    session = Session("runtime-1")
    client = ComfyUIClient(remote.http_base_url, session=session)
    bind_runtime_identity(client, remote, database)
    with DirectPreparationBudget(seconds=-1):
        with pytest.raises(DirectPreparationTimeout):
            read_runtime_identity(client, remote)
    assert session.calls == []
