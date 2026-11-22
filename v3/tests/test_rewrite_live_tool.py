"""The opt-in live probe must stay read-only until explicitly executed."""
import importlib.util
from pathlib import Path


def load_tool():
    path = Path(__file__).parents[1] / "tools" / "check_rewrite_live.py"
    spec = importlib.util.spec_from_file_location("rewrite_live_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_live_matrix_has_independent_explicit_expectations():
    tool = load_tool()
    cases = tool.load_cases()
    assert len(cases) >= 40
    assert len({case["id"] for case in cases}) == len(cases)
    assert 60 <= sum(len(case["modes"]) * len(case.get("steps", [None])) for case in cases) <= 100
    assert all(case["expected_facts"] and case["forbidden_changes"] for case in cases)
    assert {case["kind"] for case in cases} == {"anima", "moss", "raw"}


def test_live_parser_defaults_to_no_requests_or_config_access():
    args = load_tool().parse_args([])
    assert args.live is False
    assert args.config_source is None
    assert args.output_dir is None
    assert args.concurrency == 2
    assert args.timeout_s == 180


def test_exact_checks_do_not_pretend_to_validate_semantics():
    tool = load_tool()
    case = {"exact": {"positive_unchanged": True, "negative": "watermark"}}
    before = {"positive": "one adult woman on the left", "negative": "watermark, blurry"}
    result = tool.exact_checks(case, before, {"positive": before["positive"], "negative": "watermark"})
    assert result == [{"check": "positive_unchanged", "passed": True}, {"check": "negative_exact", "passed": True}]
    changed = tool.exact_checks(case, before, {"positive": "woman, lighting added", "negative": "watermark"})
    assert changed[0]["passed"] is False


def test_summary_keeps_accepted_outputs_pending_human_semantic_review():
    tool = load_tool()
    result = tool.summarize([{"status": "accepted", "exact_checks": [], "semantic_review": "pending"},
                             {"status": "rejected", "semantic_review": "pending"}])
    assert result["accepted"] == 1
    assert result["semantic_review_pending"] == 2
    assert "passed" not in result
