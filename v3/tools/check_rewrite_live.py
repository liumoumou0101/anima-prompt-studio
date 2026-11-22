"""Opt-in synthetic rewrite probe through production services; never submit images.

Without --live this command only lists the planned cases. Live runs require an
explicit copied-config source and a fresh private output directory. Accepted
service responses remain pending independent semantic review: transport success
and literal assertions are not proof that every natural-language fact survived.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
CASES_FILE = Path(__file__).with_name("rewrite_live_cases.json")


def load_cases() -> list[dict]:
    return json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="call the configured real LLM services")
    parser.add_argument("--config-source", type=Path, help="copy this assistant config into the private output directory")
    parser.add_argument("--output-dir", type=Path, help="fresh private directory for synthetic workspaces and results")
    parser.add_argument("--case", action="append", default=[], help="only run this case id; may be repeated")
    parser.add_argument("--mode", action="append", default=[], help="only run this mode; may be repeated")
    parser.add_argument("--trace-responses", action="store_true", help="retain only synthetic LLM response text for diagnosing rejected cases")
    parser.add_argument("--concurrency", type=int, choices=(1, 2), default=2)
    parser.add_argument("--timeout-s", type=int, choices=range(30, 181), metavar="30..180", default=180)
    parser.add_argument("--overall-timeout-s", type=int, choices=range(60, 3601), metavar="60..3600", default=1800)
    return parser.parse_args(argv)


def exact_checks(case: dict, before: dict, output: dict) -> list[dict]:
    """Only assert constraints that really specify literal equality."""
    checks = []
    exact = case.get("exact", {})
    if exact.get("positive_unchanged"):
        checks.append({"check": "positive_unchanged", "passed": output["positive"] == before["positive"]})
    if exact.get("negative_unchanged"):
        checks.append({"check": "negative_unchanged", "passed": output["negative"] == before["negative"]})
    if "positive" in exact:
        checks.append({"check": "positive_exact", "passed": output["positive"] == exact["positive"]})
    if "negative" in exact:
        checks.append({"check": "negative_exact", "passed": output["negative"] == exact["negative"]})
    return checks


def summarize(results: list[dict]) -> dict:
    counts = Counter(item["status"] for item in results)
    return {**counts, "completed": len(results),
            "literal_assertion_failures": sum(not check["passed"] for item in results for check in item.get("exact_checks", [])),
            "semantic_review_pending": sum(item.get("semantic_review") == "pending" for item in results)}


def selected_groups(cases: list[dict], args) -> list[tuple[dict, str]]:
    available = {case["id"] for case in cases}
    unknown = set(args.case) - available
    if unknown:
        raise ValueError("Unknown synthetic case id")
    return [(case, mode) for case in cases if not args.case or case["id"] in args.case
            for mode in case["modes"] if not args.mode or mode in args.mode]


def merge_dict(target: dict, patch: dict) -> dict:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge_dict(target[key], value)
        else:
            target[key] = deepcopy(value)
    return target


async def run_live(args, groups: list[tuple[dict, str]]) -> dict:
    if args.config_source is None or args.output_dir is None:
        raise ValueError("Live execution requires --config-source and --output-dir")
    source, directory = args.config_source.resolve(), args.output_dir.resolve()
    if not source.is_dir() or directory == source or source in directory.parents:
        raise ValueError("Use an existing configuration source and a separate fresh output directory")
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Output directory must be empty; existing audit results are never overwritten")
    directory.mkdir(parents=True, exist_ok=True)
    private = directory / "private-prompt-assistant"
    shutil.copytree(source, private)
    os.environ["ANIMA_PROMPT_ASSISTANT_DIR"] = str(private)
    for path in (ROOT / "src", ROOT / "v3/src"):
        sys.path.insert(0, str(path))
    # Import after the isolated config is bound, never during dry-run/list mode.
    from anima_prompt_studio_v3.api.conversation import ConversationService, TurnRequest
    from anima_prompt_studio_v3.api.workspace_store import WorkspaceStore
    from anima_prompt_studio_v3.api.moss import MossPromptAssistRequest, assist_prompt
    from anima_prompt_studio_v3.core.requirements import Requirements, WorkbenchError, dump
    from anima_prompt_studio_v3.runtime.generation import CandidateToPromptJobAdapter
    from anima_prompt_studio_v3.runtime.packaged_workflows import packaged_workflow_profiles
    from anima_prompt_studio_v3.core.workflow_compiler import V3WorkflowCompiler
    from anima_prompt_studio.domain.execution_models import RemoteProfile
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService

    trace_context = ContextVar('synthetic_llm_responses', default=None)
    original_completion = LLMService.complete
    if args.trace_responses:
        async def traced_completion(**kwargs):
            result = await original_completion(**kwargs)
            trace = trace_context.get()
            if trace is not None:
                trace.append({'task': kwargs.get('task'),
                              'text': result.get('text') if isinstance(result, dict) else None})
            return result
        LLMService.complete = staticmethod(traced_completion)

    store = WorkspaceStore(directory / "synthetic-workspaces.db")
    service = ConversationService(store)
    semaphore = asyncio.Semaphore(args.concurrency)
    started = time.monotonic()
    results = []
    planned = sum(len(case.get("steps", [None])) for case, _ in groups)
    metadata = {"created_at": datetime.now(timezone.utc).isoformat(),
                "synthetic_only": True, "image_generation_requests": 0,
                "real_service_planned": sum(len(c.get("steps", [None])) for c, _ in groups if c["kind"] != "raw"),
                "raw_preparation_controls": sum(c["kind"] == "raw" for c, _ in groups),
                "planned_steps": planned, "case_count": len({c["id"] for c, _ in groups}),
                "concurrency": args.concurrency, "case_timeout_s": args.timeout_s,
                "overall_timeout_s": args.overall_timeout_s,
                "semantic_review": "Independent review is required; production semantic-review acceptance is not this test's oracle."}

    def persist():
        report = {"metadata": metadata, "elapsed_s": round(time.monotonic()-started, 2),
                  "summary": summarize(results), "results": results}
        partial = directory / "results.partial.json"
        partial.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(partial, directory / "results.json")
        return report

    async def evaluate(case, mode):
        async with semaphore:
            record = None
            if case["kind"] == "anima":
                req = dump(Requirements.empty())
                req["layers"]["subject"]["text"] = "以已审核英文提示词中的人物和场景为准。"
                merge_dict(req, case.get("requirements_patch", {}))
                initial = {"model_profile": case.get("model_profile", "anima_aesthetic_v1_1"), "mode": mode}
                if case["before"].strip():
                    initial.update(
                        requirements_edit={key: req[key] for key in ("layers", "loras", "prompt_locks")},
                        prompt_edit={"positive": case["before"], "negative": case.get("negative", "")})
                # A first scene starts without compiled text. An explicit empty
                # PromptEdit is not a valid replacement for an absent prompt.
                record = store.create("synthetic live " + case["id"] + " " + mode, initial)
            for index, step in enumerate(case.get("steps", [{"delta": case.get("delta", "")}]), 1):
                began = time.monotonic()
                before = ({key: record["draft"]["compiled"][key] for key in ("positive", "negative")}
                          if record and record["draft"].get("compiled") else
                          {"positive": case["before"], "negative": case.get("negative", "")})
                item = {"case": case["id"], "kind": case["kind"], "label": case["label"],
                        "mode": mode, "step": index, "before": before, "delta": step.get("delta", ""),
                        "requirements_before": deepcopy(record["draft"].get("requirements")) if record else None,
                        "expected_outcome": case.get("expected_outcome", "accepted"),
                        "expected_facts": step.get("expected_facts", case["expected_facts"]),
                        "forbidden_changes": step.get("forbidden_changes", case["forbidden_changes"]),
                        "semantic_review": "pending"}
                if args.trace_responses:
                    item['llm_responses'] = []
                    trace_context.set(item['llm_responses'])
                try:
                    if case["kind"] == "anima":
                        response = await asyncio.wait_for(service.turn(TurnRequest(
                            workspace_id=record["id"], revision=record["revision"], mode=mode,
                            delta={"text": step["delta"]},
                            **({"compiled": before} if before["positive"].strip() else {}))), timeout=args.timeout_s)
                        output = {key: response[key] for key in ("positive", "negative")}
                        item.update(status="accepted", final_candidate=output,
                                    requirements=response["draft"].get("requirements"),
                                    warnings=response.get("warnings", []), changed_layers=response.get("changed_layers", []),
                                    unchanged=response.get("unchanged"), message=response.get("message"))
                        record = response
                    elif case["kind"] == "moss":
                        response = await asyncio.wait_for(assist_prompt(MossPromptAssistRequest(
                            source_text=before["positive"], negative_prompt=before["negative"], mode=mode)), timeout=args.timeout_s)
                        output = {key: response[key] for key in ("positive", "negative")}
                        item.update(status="accepted", final_candidate=output, warnings=response.get("warnings", []),
                                    changes=response.get("changes", []))
                    else:
                        # Real production raw preparation and workflow compilation,
                        # no self-returned fixture and no remote queue/submission.
                        prepared = CandidateToPromptJobAdapter().prepare_direct(
                            positive_prompt=before["positive"], negative_prompt=before["negative"],
                            model_profile_id="moss_image_sft_int8")
                        workflow = next(w for w in packaged_workflow_profiles() if w.id == "v3_moss_image_sft_int8")
                        graph = V3WorkflowCompiler().render(prepared.job, workflow,
                            RemoteProfile(id="synthetic-raw", display_name="synthetic-raw", ssh_host="localhost", ssh_user="synthetic"),
                            "moss_image_sft_int8", "synthetic-audit").workflow
                        output = {"positive": graph["4"]["inputs"]["text"], "negative": graph["5"]["inputs"]["text"]}
                        item.update(status="raw_prepared", final_candidate=output,
                                    preparation="CandidateToPromptJobAdapter.prepare_direct -> V3WorkflowCompiler.render; no submission")
                    item["exact_checks"] = exact_checks({**case, "exact": {**case.get("exact", {}), **step.get("exact", {})}}, before, output)
                except WorkbenchError as exc:
                    # Only the application's bounded error code/message is public.
                    item.update(status="rejected", code=exc.code, message=str(exc))
                except asyncio.TimeoutError:
                    item.update(status="timeout")
                except asyncio.CancelledError:
                    item.update(status="cancelled_overall_deadline")
                    item["elapsed_s"] = round(time.monotonic()-began, 2)
                    results.append(item)
                    persist()
                    raise
                except Exception as exc:
                    # Never serialize provider exception messages, URLs or headers.
                    item.update(status="service_error", error_type=type(exc).__name__,
                                status_code=getattr(getattr(exc, "response", None), "status_code", None))
                item["elapsed_s"] = round(time.monotonic()-began, 2)
                results.append(item)
                persist()
                print(json.dumps({"case": item["case"], "mode": mode, "step": index, "status": item["status"],
                                  "completed": len(results), "planned": planned}, ensure_ascii=False), flush=True)
                if item["status"] not in {"accepted", "raw_prepared"}:
                    break

    async def safe_evaluate(case, mode):
        try:
            await evaluate(case, mode)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # A fixture/setup failure must not silently discard unrelated cases.
            results.append({"case": case["id"], "kind": case["kind"], "mode": mode,
                            "status": "setup_error", "error_type": type(exc).__name__,
                            "semantic_review": "pending"})
            persist()

    tasks = [asyncio.create_task(safe_evaluate(case, mode)) for case, mode in groups]
    persist()
    try:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=args.overall_timeout_s)
    except asyncio.TimeoutError:
        metadata["overall_deadline_reached"] = True
    finally:
        if args.trace_responses:
            LLMService.complete = staticmethod(original_completion)
    return persist()


def main(argv=None):
    args = parse_args(argv)
    groups = selected_groups(load_cases(), args)
    if not args.live:
        print(json.dumps({"live": False, "requests": 0, "image_generation_requests": 0,
            "distinct_cases": len({c["id"] for c, _ in groups}),
            "planned_steps": sum(len(c.get("steps", [None])) for c, _ in groups),
            "cases": [{"id": c["id"], "kind": c["kind"], "mode": m,
                       "steps": len(c.get("steps", [None])), "expected_facts": c["expected_facts"],
                       "forbidden_changes": c["forbidden_changes"]} for c, m in groups]}, ensure_ascii=False, indent=2))
        return 0
    try:
        report = asyncio.run(run_live(args, groups))
    except (ValueError, FileNotFoundError) as exc:
        print(json.dumps({"error_type": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 2
    except Exception as exc:
        print(json.dumps({"error_type": type(exc).__name__}, ensure_ascii=False))
        return 2
    print(json.dumps({"summary": report["summary"], "semantic_review": "pending", "image_generation_requests": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
