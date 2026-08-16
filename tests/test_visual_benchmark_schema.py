from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "benchmarks" / "visual_semantics_v1.json"


def test_visual_semantics_benchmark_has_balanced_ladders():
    payload = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    cases = payload["cases"]

    assert len(cases) == 24
    assert len({case["id"] for case in cases}) == len(cases)
    family_counts = Counter(case["family"] for case in cases)
    assert len(family_counts) == 8
    assert set(family_counts.values()) == {3}

    for family in family_counts:
        assert {case["level"] for case in cases if case["family"] == family} == {1, 2, 3}


def test_visual_semantics_benchmark_cases_are_scorable_and_have_controls():
    cases = json.loads(BENCHMARK.read_text(encoding="utf-8"))["cases"]
    for case in cases:
        assert case["source_zh"].strip()
        assert case["control_en"].strip()
        assert len(case["required_facts"]) >= 3
        assert case["critical_facts"]
        assert case["forbidden_failures"]
