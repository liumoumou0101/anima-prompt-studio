"""Compare current compiler output against yesterday's recorded three-batch prompts."""
from __future__ import annotations

import json
from pathlib import Path

from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio.services.pipeline import PromptPipeline
from anima_prompt_studio.services.resource_manager import ResourceManager
from anima_prompt_studio.services.translation_service import (
    LazyLocalMarianEngine,
    TranslationService,
)

import importlib.util

_VERIFY = Path(__file__).with_name("_generate_action_verify.py")
_SPEC = importlib.util.spec_from_file_location("generate_action_verify", _VERIFY)
_MOD = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_MOD)
CASES = _MOD.CASES


def tags_of(prompt: str) -> set[str]:
    return {item.strip() for item in prompt.partition("\n\n")[0].split(",") if item.strip()}


def main() -> None:
    old_by_id = {}
    for name in ("action_scene_wave1.json", "action_scene_wave2.json", "action_scene_wave_nsfw.json"):
        payload = json.loads(Path("reports", name).read_text(encoding="utf-8"))
        for item in payload:
            old_by_id[item["id"]] = item

    resources = ResourceManager()
    pipe = PromptPipeline(
        translation=TranslationService(
            LazyLocalMarianEngine(resources.model_path("zh_en"), resources.model_path("en_zh"))
        )
    )
    print(f"ENGINE {pipe.translation.engine_name}", flush=True)
    rows = []
    for case in CASES:
        job = PromptJob(
            original_zh=case["zh"],
            project_name="规则对照",
            model_profile_id="anima_base_v1",
            generation_preset_id="quality",
            quality_profile_id="ultimate_general",
        )
        pipe.compiler.apply_model_defaults(job)
        pipe.translate(job)
        current_tags = tags_of(job.positive_prompt)
        old = old_by_id.get(case["id"])
        old_tags = tags_of(old["prompt"]) if old else set()
        added = sorted(current_tags - old_tags)
        removed = sorted(old_tags - current_tags)
        row = {
            "id": case["id"],
            "check": case["check"],
            "had_old_image": bool(old),
            "people": job.composition.people_count,
            "gaze": job.composition.gaze,
            "current_tags": sorted(current_tags),
            "added": added,
            "removed": removed,
            "en": job.translated_en,
            "prompt": job.positive_prompt,
        }
        rows.append(row)
        print(
            f"{case['id']:22} people={job.composition.people_count} gaze={job.composition.gaze}"
            f" +{added} -{removed}",
            flush=True,
        )
        print(f"  EN {job.translated_en}", flush=True)
        print(f"  TG {', '.join(sorted(current_tags))}", flush=True)

    out = Path("reports") / "rule_regression_prompt_compare.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE {out}", flush=True)


if __name__ == "__main__":
    main()
