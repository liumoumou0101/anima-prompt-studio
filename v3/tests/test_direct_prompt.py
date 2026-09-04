from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from anima_prompt_studio.domain.execution_models import GenerationRun, GenerationRunState
from anima_prompt_studio_v3.adapters.v2 import CandidateToV2PromptJobAdapter
from anima_prompt_studio_v3.api import create_api_runtime
from anima_prompt_studio_v3.core.direct_prompt import inspect_direct_prompt, split_prompt_tokens
from anima_prompt_studio_v3.data import (
    DataPackSnapshot,
    ReferenceBuildInputs,
    ReferenceDatabaseBuilder,
    ReferenceDataStore,
    UpstreamSource,
)

FIXTURES = Path(__file__).parent / "fixtures" / "upstream_current"
SEARCH_COMMIT = "0636f762694fc436b4ac472cf59b85d172eaaac4"
ORIGIN = "http://127.0.0.1"


def _reference_db(tmp_path: Path) -> Path:
    database = tmp_path / "reference.db"
    ReferenceDatabaseBuilder(
        ReferenceBuildInputs(
            tags=FIXTURES / "tags_enhanced.csv",
            aliases=FIXTURES / "tag_aliases.csv",
            tag_cooccurrence=FIXTURES / "cooccurrence_clean.csv",
            artist_cooccurrence=FIXTURES / "tag_artist_cooc.csv",
            tag_groups=FIXTURES / "tag_groups.json",
        ),
        pack_id="anima-v3-direct-test-r1",
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
                commit=SEARCH_COMMIT,
                license="GPL-3.0",
            )
        ],
    ).build(database, tmp_path / "data-pack.json")
    return database


def test_split_keeps_comma_tokens_intact() -> None:
    assert split_prompt_tokens("maid, full body, black hair ribbons") == [
        "maid",
        "full body",
        "black hair ribbons",
    ]


def test_inspect_matches_whole_tokens_and_does_not_n_gram_split(tmp_path: Path) -> None:
    database = _reference_db(tmp_path)
    with ReferenceDataStore(database) as store:
        inspection = inspect_direct_prompt(
            store,
            positive_prompt="maid, full body, black hair ribbons, looking at viewer",
            negative_prompt="blonde hair",
        )

    by_original = {token.original: token for token in inspection.positive_tokens}
    assert by_original["maid"].canonical_tag == "maid"
    assert by_original["maid"].zh == "女仆"
    assert by_original["full body"].canonical_tag == "full_body"
    assert by_original["looking at viewer"].canonical_tag == "looking_at_viewer"
    assert by_original["black hair ribbons"].matched is False
    assert "black_hair" not in {token.canonical_tag for token in inspection.positive_tokens}
    assert inspection.negative_tokens[0].canonical_tag == "blonde_hair"
    assert inspection.positive_prompt == "maid, full body, black hair ribbons, looking at viewer"


def test_prepare_direct_sends_pasted_english_unchanged() -> None:
    prompt = "1girl, lavender hair, finger to lips, clean delicate lineart"
    prepared = CandidateToV2PromptJobAdapter().prepare_direct(
        positive_prompt=prompt,
        negative_prompt="worst quality",
        model_profile_id="anima_aesthetic_v1",
        project_name="直出对照",
    )
    assert prepared.job.positive_prompt == prompt
    assert prepared.job.negative_prompt == "worst quality"
    assert prepared.job.prompt_origin == "user_edited"
    assert prepared.job.compiled_prompt_state.value == "locked"
    assert prepared.job.integration_metadata["origin"] == "direct_prompt"
    assert prepared.checkpoint_logical_name == "anima_aesthetic_v1"


@pytest.mark.parametrize("model_profile", [
    "animayume_v1_0_final",
    "miaomiao_harem_anima_v1_6",
])
def test_prepare_direct_supports_community_model_profiles(model_profile: str) -> None:
    prepared = CandidateToV2PromptJobAdapter().prepare_direct(
        positive_prompt="1girl, solo, portrait",
        model_profile_id=model_profile,
    )

    assert prepared.job.model_profile_id == model_profile
    assert prepared.checkpoint_logical_name == model_profile
    assert prepared.job.positive_prompt == "1girl, solo, portrait"


def test_direct_prompt_preview_and_run_api_do_not_compile(tmp_path: Path) -> None:
    database = _reference_db(tmp_path)
    queue = _StubQueue()
    runtime = create_api_runtime(database, generation_queue=queue)
    client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
    token = client.post(
        "/api/v3/session/exchange",
        json={"bootstrap_token": runtime.bootstrap_token},
        headers={"Origin": ORIGIN},
    ).json()["session_token"]
    headers = {"X-Anima-Session": token, "Origin": ORIGIN}
    prompt = "maid, full body, black hair ribbons"

    preview = client.post(
        "/api/v3/direct-prompt/preview",
        json={"positive_prompt": prompt, "negative_prompt": "blonde hair"},
        headers=headers,
    )
    assert preview.status_code == 200
    payload = preview.json()
    assert payload["positive_prompt"] == prompt
    assert {item["original"]: item["matched"] for item in payload["positive_tokens"]}["black hair ribbons"] is False
    assert payload["chinese_positive"].startswith("女仆")

    submitted = client.post(
        "/api/v3/direct-prompt/runs",
        json={
            "positive_prompt": prompt,
            "negative_prompt": "blonde hair",
            "model_profile": "anima_base_v1",
            "remote_profile_id": "remote-1",
            "workflow_profile_id": "workflow-1",
        },
        headers={**headers, "Idempotency-Key": "direct-1"},
    )
    assert submitted.status_code == 202
    job = queue.runs[submitted.json()["id"]].request_json["prompt_job"]
    assert job["positive_prompt"] == prompt
    assert job["prompt_origin"] == "user_edited"
    assert job["integration_metadata"]["origin"] == "direct_prompt"


class _StubQueue:
    def __init__(self) -> None:
        self.runs: dict[str, GenerationRun] = {}
        self.keys: dict[str, str] = {}

    def submit(self, prepared, *, remote_profile_id, workflow_profile_id, idempotency_key):
        if idempotency_key in self.keys:
            return self.runs[self.keys[idempotency_key]].model_copy(deep=True)
        run = GenerationRun(
            prompt_job_id=prepared.job.id,
            remote_profile_id=remote_profile_id,
            workflow_profile_id=workflow_profile_id,
            status_message="等待本地生成队列",
            request_json={"prompt_job": prepared.job.model_dump(mode="json")},
        )
        self.runs[run.id] = run
        self.keys[idempotency_key] = run.id
        return run.model_copy(deep=True)

    def get(self, run_id):
        return self.runs[run_id].model_copy(deep=True)

    def artifacts(self, _run_id):
        return []

    def list(self, *, limit=100):
        return list(self.runs.values())[:limit]

    def available_actions(self, run_id):
        return ["cancel_queued"] if self.runs[run_id].state == GenerationRunState.DRAFT else []
