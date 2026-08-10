"""Ad-hoc NSFW compatibility probe for ANIMA Prompt Studio.

Runs representative soft/hard NSFW Chinese prompts through the full pipeline
(with Marian if available, else builtin) and reports crash / filter / quality
signals. Not part of the permanent pytest suite unless promoted later.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import traceback
from pathlib import Path

# Ensure src is importable when run as script
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio.services.pipeline import PromptPipeline
from anima_prompt_studio.services.resource_manager import ResourceManager
from anima_prompt_studio.services.translation_service import (
    BuiltinOfflineEngine,
    LazyLocalMarianEngine,
    TranslationService,
    marian_runtime_available,
)

# Soft / fashion-adjacent NSFW (common anime prompt vocab)
SOFT_CASES = [
    {
        "id": "bikini_beach",
        "input": "一个金发蓝瞳的女孩穿着比基尼站在沙滩上，看镜头微笑",
        "expect_en_any": [["bikini"], ["swimsuit"]],
        "expect_tags_any": [["bikini"], ["swimsuit"]],
        "level": "soft",
    },
    {
        "id": "lingerie_indoors",
        "input": "一个黑发红瞳女孩穿着黑色内衣躺在床上，看镜头",
        "expect_en_any": [["lingerie"], ["underwear"], ["bra"], ["panties"], ["black lingerie"]],
        "expect_tags_any": [["lingerie"], ["underwear"], ["bra"], ["panties"]],
        "level": "soft",
    },
    {
        "id": "stockings_garter",
        "input": "一个银发女孩穿着吊带袜和吊袜带坐在窗边，双腿交叠",
        "expect_en_any": [["stockings"], ["garter"], ["thighhighs"], ["thighhigh"]],
        "expect_tags_any": [["stockings"], ["garter straps"], ["thighhighs"], ["garter belt"]],
        "level": "soft",
    },
    {
        "id": "cleavage_dress",
        "input": "一个紫发女孩穿着低胸礼服，露出乳沟，站在宴会厅",
        "expect_en_any": [["cleavage"], ["low-cut"], ["plunging"], ["low cut"]],
        "expect_tags_any": [["cleavage"], ["dress"]],
        "level": "soft",
    },
    {
        "id": "wet_shirt",
        "input": "一个蓝发女孩穿着湿透的白衬衫，透过衣服能看到内衣轮廓",
        "expect_en_any": [["wet"], ["see-through"], ["transparent"], ["soaked"]],
        "expect_tags_any": [["wet clothes"], ["see-through"], ["wet shirt"]],
        "level": "soft",
    },
    {
        "id": "navel_crop_top",
        "input": "一个粉发女孩穿着露脐短上衣和热裤，侧身站立",
        "expect_en_any": [["navel"], ["midriff"], ["crop top"], ["hot pants"], ["shorts"]],
        "expect_tags_any": [["navel"], ["midriff"], ["crop top"]],
        "level": "soft",
    },
]

# Explicit anatomical / nude (Danbooru-style tags commonly used offline)
HARD_CASES = [
    {
        "id": "nude_standing",
        "input": "一个裸体的女孩站在浴室里，长发遮住胸口，看向画外",
        "expect_en_any": [["nude"], ["naked"], ["bare"]],
        "expect_tags_any": [["nude"], ["completely nude"], ["naked"]],
        "level": "hard",
    },
    {
        "id": "topless_from_side",
        "input": "一个赤裸上身的女孩侧面坐在床边，只穿着内裤",
        "expect_en_any": [["topless"], ["bare breasts"], ["naked"], ["nude"], ["panties"], ["underwear"]],
        "expect_tags_any": [["topless"], ["nude"], ["panties"], ["bare breasts"]],
        "level": "hard",
    },
    {
        "id": "breasts_nipples",
        "input": "一个白发女孩全裸躺在床单上，胸部和乳头清晰可见",
        "expect_en_any": [["breast"], ["nipple"], ["nude"], ["naked"]],
        "expect_tags_any": [["breasts"], ["nipples"], ["nude"], ["lying"]],
        "level": "hard",
    },
    {
        "id": "ass_from_behind",
        "input": "从背后拍摄一个只穿着丁字裤的女孩，臀部特写",
        "expect_en_any": [["ass"], ["butt"], ["thong"], ["from behind"], ["rear"]],
        "expect_tags_any": [["ass"], ["from behind"], ["thong"], ["panties"]],
        "level": "hard",
    },
    {
        "id": "sex_missionary",
        "input": "一对男女在床上做爱，男上位，女孩张腿看着镜头",
        "expect_en_any": [["sex"], ["intercourse"], ["missionary"], ["making love"], ["having sex"]],
        "expect_tags_any": [["sex"], ["hetero"], ["missionary"], ["1boy"], ["1girl"]],
        "level": "hard",
    },
    {
        "id": "oral_suggestive",
        "input": "一个跪着的女孩正要做口交，抬头看镜头，嘴巴微张",
        "expect_en_any": [["oral"], ["fellatio"], ["blowjob"], ["kneeling"]],
        "expect_tags_any": [["oral"], ["fellatio"], ["kneeling"], ["open mouth"]],
        "level": "hard",
    },
    {
        "id": "ahegao_expression",
        "input": "一个高潮中的女孩露出阿嘿颜表情，舌头伸出，眼睛上翻",
        "expect_en_any": [["ahegao"], ["orgasm"], ["tongue"], ["rolling eyes"], ["ecstasy"]],
        "expect_tags_any": [["ahegao"], ["tongue out"], ["rolling eyes"], ["orgasm"]],
        "level": "hard",
    },
    {
        "id": "bondage_rope",
        "input": "一个被绳子捆绑的女孩坐在椅子上，眼睛被布蒙住",
        "expect_en_any": [["bound"], ["bondage"], ["rope"], ["tied"], ["blindfold"]],
        "expect_tags_any": [["bound"], ["bondage"], ["rope"], ["blindfold"]],
        "level": "hard",
    },
]

# Edge: English authority path with NSFW tags typed directly
ENGLISH_CASES = [
    {
        "id": "en_direct_nude_tags",
        "input_zh": "一个女孩",  # seed
        "english": "1girl, nude, medium breasts, nipples, standing, looking at viewer, indoors, bathroom",
        "expect_tags_any": [["nude"], ["nipples"], ["breasts"], ["looking at viewer"]],
        "level": "english",
    },
    {
        "id": "en_direct_sex_tags",
        "input_zh": "两个角色",
        "english": "1girl, 1boy, sex, hetero, missionary, nude, open mouth, looking at viewer, on bed",
        "expect_tags_any": [["sex"], ["hetero"], ["missionary"], ["1boy"], ["1girl"]],
        "level": "english",
    },
]


def _any_in(text: str, groups: list[list[str]]) -> bool:
    lower = text.lower()
    return any(any(token.lower() in lower for token in group) for group in groups)


def _tag_names(job: PromptJob) -> list[str]:
    return [t.tag for t in job.matched_tags]


def _tags_blob(job: PromptJob) -> str:
    return ", ".join(_tag_names(job)).lower()


def inspect_tag_db() -> dict:
    path = ResourceManager().tag_db_path
    result = {"available": path.is_file(), "path": str(path), "probes": {}}
    if not path.is_file():
        return result
    probes = [
        "nude", "completely_nude", "topless", "breasts", "nipples", "pussy", "penis",
        "sex", "hetero", "missionary", "fellatio", "oral", "ahegao", "bondage",
        "bound", "bikini", "lingerie", "panties", "cleavage", "navel", "ass",
        "thighhighs", "stockings", "see-through", "wet_clothes", "thong", "blindfold",
        "orgasm", "cum", "uncensored", "rating_explicit", "explicit",
    ]
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        total = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        result["total_tags"] = total
        for name in probes:
            row = conn.execute(
                "SELECT name, output_name, category, post_count, is_deprecated FROM tags WHERE name=?",
                (name,),
            ).fetchone()
            result["probes"][name] = {
                "found": row is not None,
                "output": row[1] if row else None,
                "category": row[2] if row else None,
                "post_count": row[3] if row else None,
                "deprecated": bool(row[4]) if row else None,
            }
        # Search for explicit-ish high post_count tags
        sample = conn.execute(
            "SELECT name, post_count FROM tags WHERE name IN "
            "('nude','sex','breasts','nipples','pussy','penis','fellatio','ahegao','bondage','bikini') "
            "ORDER BY post_count DESC"
        ).fetchall()
        result["sample_counts"] = sample
    finally:
        conn.close()
    return result


def make_pipeline(use_marian: bool) -> tuple[PromptPipeline, str]:
    if use_marian and marian_runtime_available() and ResourceManager().models_available():
        rm = ResourceManager()
        engine = LazyLocalMarianEngine(rm.model_path("zh_en"), rm.model_path("en_zh"))
        return PromptPipeline(translation=TranslationService(engine)), engine.name
    return PromptPipeline(translation=TranslationService(BuiltinOfflineEngine())), BuiltinOfflineEngine.name


def run_case(pipeline: PromptPipeline, case: dict) -> dict:
    out = {
        "id": case["id"],
        "level": case["level"],
        "input": case.get("input") or case.get("english"),
        "ok": False,
        "crashed": False,
        "error": None,
        "translated_en": None,
        "back_zh": None,
        "tags": [],
        "positive_head": None,
        "negative": None,
        "subject_mode": None,
        "composition": {},
        "warnings": [],
        "en_hit": None,
        "tag_hit": None,
        "filtered_empty": False,
    }
    try:
        job = PromptJob(original_zh=case.get("input") or case.get("input_zh", ""))
        pipeline.compiler.apply_model_defaults(job)
        pipeline.translate(job)
        if "english" in case:
            pipeline.update_english(job, case["english"])

        out["translated_en"] = job.translated_en
        out["back_zh"] = job.back_translated_zh
        out["tags"] = _tag_names(job)
        head = job.positive_prompt.split("\n", 1)[0] if job.positive_prompt else ""
        out["positive_head"] = head[:500]
        out["negative"] = (job.negative_prompt or "")[:300]
        out["subject_mode"] = str(job.effective_subject_mode())
        out["composition"] = {
            "shot": job.composition.shot,
            "angle": job.composition.angle,
            "gaze": job.composition.gaze,
            "aspect": job.composition.aspect,
            "people_count": job.composition.people_count,
        }
        out["warnings"] = [
            {"level": str(w.level), "message": w.message}
            for w in (job.semantic_warnings or [])
        ][:8]
        out["filtered_empty"] = not bool(job.translated_en and job.translated_en.strip())

        if case.get("expect_en_any"):
            out["en_hit"] = _any_in(job.translated_en or "", case["expect_en_any"])
        if case.get("expect_tags_any"):
            blob = _tags_blob(job) + " | " + (job.positive_prompt or "").lower()
            out["tag_hit"] = _any_in(blob, case["expect_tags_any"])

        # Success criteria for compatibility: no crash, content not wiped, pipeline completes
        content_preserved = not out["filtered_empty"]
        if "english" in case:
            content_preserved = content_preserved and case["english"].split(",")[0].strip().lower() in (
                job.translated_en or ""
            ).lower()
        out["ok"] = content_preserved and not out["crashed"]
    except Exception as exc:
        out["crashed"] = True
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["traceback"] = traceback.format_exc(limit=4)
        out["ok"] = False
    return out


def main() -> int:
    print("=" * 72)
    print("ANIMA NSFW Compatibility Probe")
    print("=" * 72)

    tag_info = inspect_tag_db()
    print(f"\n[Tag DB] available={tag_info['available']} total={tag_info.get('total_tags')}")
    if tag_info.get("sample_counts"):
        print("  sample NSFW/related tag post_counts:")
        for name, count in tag_info["sample_counts"]:
            print(f"    {name}: {count}")
    missing = [k for k, v in tag_info.get("probes", {}).items() if not v["found"]]
    if missing:
        print(f"  missing probes: {', '.join(missing)}")
    else:
        print("  all probe tags found in DB")

    use_marian = "--builtin-only" not in sys.argv
    pipeline, engine_name = make_pipeline(use_marian=use_marian)
    print(f"\n[Engine] {engine_name}")

    all_cases = SOFT_CASES + HARD_CASES
    results = []
    print("\n--- Chinese pipeline cases ---")
    for case in all_cases:
        r = run_case(pipeline, case)
        results.append(r)
        status = "PASS" if r["ok"] else ("CRASH" if r["crashed"] else "FAIL")
        en_s = {True: "Y", False: "N", None: "-"}[r["en_hit"]]
        tag_s = {True: "Y", False: "N", None: "-"}[r["tag_hit"]]
        print(f"[{status}] {r['id']:24} level={r['level']:6} en_hit={en_s} tag_hit={tag_s}")
        if r["crashed"]:
            print(f"         ERROR: {r['error']}")
        else:
            print(f"         EN: {(r['translated_en'] or '')[:160]}")
            print(f"         TAGS({len(r['tags'])}): {', '.join(r['tags'][:12])}")
            print(f"         COMP: {r['composition']}")

    print("\n--- English-authority cases ---")
    for case in ENGLISH_CASES:
        r = run_case(pipeline, case)
        results.append(r)
        status = "PASS" if r["ok"] else ("CRASH" if r["crashed"] else "FAIL")
        tag_s = {True: "Y", False: "N", None: "-"}[r["tag_hit"]]
        print(f"[{status}] {r['id']:24} tag_hit={tag_s}")
        if r["crashed"]:
            print(f"         ERROR: {r['error']}")
        else:
            print(f"         EN: {(r['translated_en'] or '')[:160]}")
            print(f"         TAGS({len(r['tags'])}): {', '.join(r['tags'][:14])}")

    # Summary
    total = len(results)
    ok = sum(1 for r in results if r["ok"])
    crash = sum(1 for r in results if r["crashed"])
    empty = sum(1 for r in results if r.get("filtered_empty"))
    en_hits = [r for r in results if r["en_hit"] is not None]
    tag_hits = [r for r in results if r["tag_hit"] is not None]
    en_rate = sum(1 for r in en_hits if r["en_hit"]) / len(en_hits) if en_hits else 0
    tag_rate = sum(1 for r in tag_hits if r["tag_hit"]) / len(tag_hits) if tag_hits else 0

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"  cases:           {total}")
    print(f"  pipeline ok:     {ok}/{total}  (no crash, content not wiped)")
    print(f"  crashes:         {crash}")
    print(f"  wiped/empty EN:  {empty}")
    print(f"  EN semantic hit: {sum(1 for r in en_hits if r['en_hit'])}/{len(en_hits)} ({en_rate:.0%})")
    print(f"  tag hit:         {sum(1 for r in tag_hits if r['tag_hit'])}/{len(tag_hits)} ({tag_rate:.0%})")
    print(f"  engine:          {engine_name}")
    print(f"  tag DB:          {tag_info.get('total_tags')} tags")

    # Compatibility conclusion signals
    print("\nCOMPATIBILITY SIGNALS")
    has_filter = empty > 0 or any(
        r.get("translated_en") and "cannot" in (r["translated_en"] or "").lower()
        for r in results
    )
    print(f"  content filter / refuse: {'YES — content wiped or refused' if has_filter else 'NO — pipeline accepts NSFW text'}")
    print(f"  crash on NSFW:          {'YES' if crash else 'NO'}")
    print(f"  tag vocab has NSFW:     {'YES' if tag_info.get('probes', {}).get('nude', {}).get('found') else 'NO/UNKNOWN'}")
    print(f"  EN quality on soft:     {sum(1 for r in results if r['level']=='soft' and r['en_hit'])}/{sum(1 for r in results if r['level']=='soft')}")
    print(f"  EN quality on hard:     {sum(1 for r in results if r['level']=='hard' and r['en_hit'])}/{sum(1 for r in results if r['level']=='hard')}")
    print(f"  tag quality on soft:    {sum(1 for r in results if r['level']=='soft' and r['tag_hit'])}/{sum(1 for r in results if r['level']=='soft')}")
    print(f"  tag quality on hard:    {sum(1 for r in results if r['level']=='hard' and r['tag_hit'])}/{sum(1 for r in results if r['level']=='hard')}")
    print(f"  english authority tags: {sum(1 for r in results if r['level']=='english' and r['tag_hit'])}/{sum(1 for r in results if r['level']=='english')}")

    out_dir = ROOT / "reports" / "nsfw_compat_probe"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "engine": engine_name,
        "tag_db": tag_info,
        "results": results,
        "summary": {
            "total": total,
            "ok": ok,
            "crash": crash,
            "empty": empty,
            "en_rate": en_rate,
            "tag_rate": tag_rate,
        },
    }
    path = out_dir / "nsfw_compat_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {path}")
    return 0 if crash == 0 and empty == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
