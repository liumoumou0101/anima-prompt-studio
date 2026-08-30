from __future__ import annotations

import sqlite3
import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from anima_prompt_studio_v3.data import (
    DataContractError,
    DataPackFile,
    DataPackManifest,
    DataPackSnapshot,
    ReferenceBuildInputs,
    ReferenceDatabaseBuilder,
    ReferenceDataStore,
    UpstreamSource,
)
from anima_prompt_studio_v3.tools.build_reference_data import run


FIXTURES = Path(__file__).parent / "fixtures"
CURRENT = FIXTURES / "upstream_current"
SEARCH_COMMIT = "0636f762694fc436b4ac472cf59b85d172eaaac4"
PIPELINE_COMMIT = "a5a2d0ef085748eaa4a67e77eecee37a6680f776"


def snapshot() -> DataPackSnapshot:
    return DataPackSnapshot(
        target_cutoff=date(2025, 9, 30),
        cutoff_mode="approximate",
        source_observed_at=date(2026, 8, 25),
        corpus_size=100_000,
        corpus_size_mode="estimated",
    )


def sources() -> list[UpstreamSource]:
    return [
        UpstreamSource(
            name="DanbooruSearchOnline",
            repository="https://github.com/SuzumiyaAkizuki/DanbooruSearchOnline",
            commit=SEARCH_COMMIT,
            license="GPL-3.0",
        ),
        UpstreamSource(
            name="danbooru-tag-pipeline",
            repository="https://github.com/SuzumiyaAkizuki/danbooru-tag-pipeline",
            commit=PIPELINE_COMMIT,
            license="NO-LICENSE-EXTERNAL-TOOL",
        ),
    ]


def builder(artist_path: Path | None = None) -> ReferenceDatabaseBuilder:
    return ReferenceDatabaseBuilder(
        ReferenceBuildInputs(
            tags=CURRENT / "tags_enhanced.csv",
            aliases=CURRENT / "tag_aliases.csv",
            tag_cooccurrence=CURRENT / "cooccurrence_clean.csv",
            artist_cooccurrence=artist_path or CURRENT / "tag_artist_cooc.csv",
            tag_groups=CURRENT / "tag_groups.json",
        ),
        pack_id="anima-v3-test-r1",
        snapshot=snapshot(),
        sources=sources(),
    )


def test_manifest_rejects_unsafe_paths_and_inconsistent_exact_snapshot() -> None:
    with pytest.raises(ValidationError):
        DataPackFile(path="../reference.db", size=1, sha256="0" * 64)
    with pytest.raises(ValidationError):
        DataPackSnapshot(
            target_cutoff=date(2025, 9, 30),
            cutoff_mode="exact",
            source_observed_at=date(2025, 9, 30),
            corpus_size=100_000,
            corpus_size_mode="estimated",
        )


def test_build_query_and_verify_reference_pack(tmp_path: Path) -> None:
    database = tmp_path / "reference.db"
    manifest_path = tmp_path / "data-pack.json"
    manifest = builder().build(database, manifest_path)

    assert manifest.counts.model_dump() == {
        "tags": 7,
        "artists": 2,
        "aliases": 2,
        "tag_edges": 6,
        "artist_edges": 3,
    }
    loaded = DataPackManifest.load(manifest_path)
    loaded.verify_files(tmp_path)
    assert loaded.pack_id == "anima-v3-test-r1"

    with ReferenceDataStore(database) as store:
        assert store.pack_id == loaded.pack_id
        assert store.search("女佣")[0]["name"] == "maid"
        maid = store.get_tag("maid_uniform")
        assert maid is not None
        assert maid["name"] == "maid"
        assert maid["aliases"] == ["maid_uniform"]
        assert maid["groups"] == [{"id": "tag_group:attire", "name": "attire", "cn_name": "服装"}]
        related = store.related_tags(["maid"])
        assert [item["name"] for item in related[:2]] == ["frilled_apron", "twintails"]
        assert related[0]["sources"] == ["maid"]
        assert store.related_tags(["maid"], excluded={"frilled_apron"})[0]["name"] == "twintails"

        artists = store.recommend_artists(["maid", "twin_tails"])
        assert artists[0]["name"] == "sample_artist_a"
        assert artists[0]["render_name"] == "@sample artist a"
        assert artists[0]["hit_count"] == 2

        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            store.connection.execute("INSERT INTO metadata VALUES('bad','write')")


def test_wrong_upstream_schema_is_rejected_without_partial_pack(tmp_path: Path) -> None:
    database = tmp_path / "reference.db"
    manifest_path = tmp_path / "data-pack.json"
    wrong = FIXTURES / "upstream_wrong_schema" / "tag_artist_cooc.csv"

    with pytest.raises(DataContractError, match="artist_post_count"):
        builder(wrong).build(database, manifest_path)

    assert not database.exists()
    assert not manifest_path.exists()


def test_existing_pack_is_not_overwritten_by_default(tmp_path: Path) -> None:
    database = tmp_path / "reference.db"
    manifest_path = tmp_path / "data-pack.json"
    builder().build(database, manifest_path)
    original_hash = DataPackManifest.load(manifest_path).files[0].sha256

    with pytest.raises(DataContractError, match="拒绝覆盖"):
        builder().build(database, manifest_path)

    assert DataPackManifest.load(manifest_path).files[0].sha256 == original_hash


def test_build_cli_config_returns_structured_report(tmp_path: Path) -> None:
    config = {
        "pack_id": "anima-v3-cli-test-r1",
        "snapshot": snapshot().model_dump(mode="json"),
        "sources": [item.model_dump(mode="json") for item in sources()],
        "inputs": {
            "tags": str(CURRENT / "tags_enhanced.csv"),
            "aliases": str(CURRENT / "tag_aliases.csv"),
            "tag_cooccurrence": str(CURRENT / "cooccurrence_clean.csv"),
            "artist_cooccurrence": str(CURRENT / "tag_artist_cooc.csv"),
            "tag_groups": str(CURRENT / "tag_groups.json"),
        },
        "output_dir": "pack",
    }
    config_path = tmp_path / "build.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    report = run(config_path)

    assert report["status"] == "ok"
    assert report["manifest"]["counts"]["artists"] == 2
    assert (tmp_path / "pack" / "reference.db").is_file()
