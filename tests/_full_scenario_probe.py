"""Broad scenario probe for ANIMA Prompt Studio (Marian + builtin if available)."""
from __future__ import annotations

import json
import re
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from anima_prompt_studio.domain.models import ItemState, PromptJob, SubjectMode
from anima_prompt_studio.services.config_service import ConfigService
from anima_prompt_studio.services.pipeline import PromptPipeline
from anima_prompt_studio.services.resource_manager import ResourceManager
from anima_prompt_studio.services.translation_service import (
    BuiltinOfflineEngine,
    LazyLocalMarianEngine,
    TranslationService,
    marian_runtime_available,
)
from anima_prompt_studio.ui.tag_browser_dialog import TagBrowserDialog, category_display


SCENARIOS: list[dict] = [
    # --- Everyday / SFW ---
    {
        "id": "portrait_basic",
        "group": "sfw",
        "zh": "一个白发金瞳的女孩坐在窗边，看镜头微笑",
        "expect_tags_any": [["white hair"], ["looking at viewer"], ["smile"]],
        "expect_en_any": [["white"], ["girl"]],
        "expect_people": 1,
    },
    {
        "id": "rain_run",
        "group": "sfw",
        "zh": "一个黑发女孩在雨中奔跑，长发和围巾向后飘扬，横向构图",
        "expect_tags_any": [["running"], ["rain"], ["black hair"]],
        "expect_comp": {"aspect": "横图"},
    },
    {
        "id": "school_rooftop",
        "group": "sfw",
        "zh": "校服双马尾女孩站在学校天台，黄昏逆光",
        "expect_tags_any": [["school uniform"], ["twintails"], ["rooftop"]],
    },
    {
        "id": "maid_tea",
        "group": "sfw",
        "zh": "女仆装银发女孩端着茶杯站在咖啡馆",
        "expect_tags_any": [["maid"], ["silver hair"], ["teacup", "tea", "cafe"]],
    },
    {
        "id": "fox_girl_kimono",
        "group": "fantasy",
        "zh": "狐娘穿着和服站在神社鸟居前，兽耳和尾巴",
        "expect_tags_any": [["fox girl"], ["kimono", "miko"], ["animal ears", "tail", "shrine"]],
    },
    {
        "id": "angel_halo",
        "group": "fantasy",
        "zh": "天使女孩有光环和白色翅膀，从天而降",
        "expect_tags_any": [["angel"], ["halo"], ["wings", "white wings"]],
    },
    {
        "id": "mermaid_ocean",
        "group": "fantasy",
        "zh": "人鱼在月光下的海面",
        "expect_tags_any": [["mermaid"], ["ocean", "sea", "moonlight", "night"]],
    },
    # --- Soft NSFW / clothing ---
    {
        "id": "bikini_beach",
        "group": "soft",
        "zh": "金发蓝瞳女孩穿着比基尼站在沙滩上，看镜头",
        "expect_tags_any": [["bikini"], ["blonde hair"], ["beach"]],
    },
    {
        "id": "micro_bikini_latex",
        "group": "soft",
        "zh": "女孩穿着微型比基尼和乳胶",
        "expect_tags_any": [["micro bikini", "bikini"], ["latex"]],
    },
    {
        "id": "stockings_garter",
        "group": "soft",
        "zh": "银发女孩穿着吊带袜和吊袜带坐在窗边，双腿交叠",
        "expect_tags_any": [["thighhighs", "stockings"], ["garter belt", "garter"], ["legs crossed"]],
    },
    {
        "id": "naked_apron",
        "group": "soft",
        "zh": "女孩只穿围裙，肩带滑落",
        "expect_tags_any": [["naked apron"], ["strap slip"]],
    },
    {
        "id": "unbuttoned_strap",
        "group": "soft",
        "zh": "衬衫半解，扣子解开，肩带滑落",
        "expect_tags_any": [["unbuttoned shirt", "open shirt"], ["strap slip"]],
    },
    {
        "id": "panties_aside",
        "group": "soft",
        "zh": "内裤拨到一边，含手指",
        "expect_tags_any": [["panties aside"], ["finger to mouth"]],
    },
    {
        "id": "virgin_killer",
        "group": "soft",
        "zh": "处男杀手毛衣，露背",
        "expect_tags_any": [["virgin killer sweater"]],
    },
    {
        "id": "miko_wet",
        "group": "soft",
        "zh": "巫女服被雨打湿透视",
        "expect_tags_any": [["miko"], ["wet", "see-through", "rain"]],
    },
    # --- Hard / positions ---
    {
        "id": "nude_bathroom",
        "group": "hard",
        "zh": "一个裸体的女孩站在浴室里，看向画外",
        "expect_tags_any": [["nude"], ["bathroom"], ["looking away"]],
        "forbid_tags": ["painting (action)", "painting (object)", "camera"],
    },
    {
        "id": "missionary_couple",
        "group": "hard",
        "zh": "一对男女在床上做爱，男上位，女孩张腿看着镜头",
        "expect_tags_any": [["sex"], ["missionary"], ["hetero", "1boy"]],
        "expect_people": 2,
        "forbid_tags": ["male focus"],
    },
    {
        "id": "cowgirl_ahegao",
        "group": "hard",
        "zh": "女孩女上位，张开双腿，阿嘿颜，舌头伸出，眼睛上翻",
        "expect_tags_any": [["cowgirl position"], ["spread legs"], ["ahegao"], ["tongue out"]],
    },
    {
        "id": "mating_press",
        "group": "hard",
        "zh": "架腿位打桩",
        "expect_tags_any": [["mating press"]],
    },
    {
        "id": "full_nelson",
        "group": "hard",
        "zh": "火车便当",
        "expect_tags_any": [["full nelson"]],
        "forbid_tags": ["train interior"],
    },
    {
        "id": "doggy_prone",
        "group": "hard",
        "zh": "后入式，趴着后入",
        "expect_tags_any": [["doggy style", "prone bone"], ["sex", "from behind"]],
    },
    {
        "id": "sixtynine",
        "group": "hard",
        "zh": "六九式",
        "expect_tags_any": [["69"]],
    },
    {
        "id": "bondage_shibari",
        "group": "hard",
        "zh": "龟甲缚，蒙住眼睛，跳蛋",
        "expect_tags_any": [["shibari", "bondage", "rope"], ["blindfold"], ["vibrator"]],
    },
    {
        "id": "oral",
        "group": "hard",
        "zh": "跪着的女孩口交，抬头看镜头",
        "expect_tags_any": [["fellatio", "oral"], ["kneeling"], ["looking at viewer"]],
    },
    {
        "id": "ass_focus",
        "group": "hard",
        "zh": "从背后拍摄只穿着丁字裤的女孩，臀部特写",
        "expect_tags_any": [["from behind"], ["thong", "ass"], ["ass focus"]],
        "expect_comp_not": {"shot": "头像"},
    },
    {
        "id": "yuri_kiss",
        "group": "hard",
        "zh": "两个女孩亲吻，百合",
        "expect_tags_any": [["yuri"], ["kiss"], ["2girls"]],
        "expect_people": 2,
        "forbid_tags": ["hetero"],
    },
    {
        "id": "cum_facial",
        "group": "hard",
        "zh": "颜射，脸上沾着精液，伸舌头",
        "expect_tags_any": [["facial", "cum"], ["tongue out"]],
    },
    # --- Body / expression slang ---
    {
        "id": "large_breasts_ol",
        "group": "body",
        "zh": "巨乳OL女职员站在办公室",
        "expect_tags_any": [["large breasts"], ["office lady", "office"]],
    },
    {
        "id": "flat_chest",
        "group": "body",
        "zh": "飞机场平板身材",
        "expect_tags_any": [["flat chest"]],
    },
    {
        "id": "fang_mole_seiza",
        "group": "body",
        "zh": "泪痣虎牙正坐",
        "expect_tags_any": [["mole under eye"], ["fang", "fangs"], ["seiza"]],
    },
    {
        "id": "futanari_ears",
        "group": "body",
        "zh": "扶她兽耳",
        "expect_tags_any": [["futanari"], ["animal ears"]],
    },
    {
        "id": "cyborg_slime",
        "group": "body",
        "zh": "史莱姆赛博义体",
        "expect_tags_any": [["slime"], ["cyborg"]],
    },
    {
        "id": "mind_break",
        "group": "body",
        "zh": "精神崩溃玩坏了阿嘿颜",
        "expect_tags_any": [["mind break", "ahegao"]],
    },
    # --- Composition / multi ---
    {
        "id": "explicit_full_side",
        "group": "composition",
        "zh": "横图全身侧面，女孩在雨中",
        "expect_comp": {"shot": "全身", "angle": "侧面", "aspect": "横图"},
    },
    {
        "id": "from_behind_no_viewer",
        "group": "composition",
        "zh": "从背后拍摄她",
        "expect_tags_any": [["from behind", "looking away"]],
        "forbid_tags": ["looking at viewer", "camera"],
    },
    {
        "id": "look_at_camera_no_object",
        "group": "composition",
        "zh": "女孩回头看向镜头",
        "expect_tags_any": [["looking back"], ["looking at viewer"]],
        "forbid_tags": ["camera"],
    },
    {
        "id": "two_girls",
        "group": "composition",
        "zh": "两个女孩并肩站着",
        "expect_people": 2,
    },
    {
        "id": "scene_night_forest",
        "group": "composition",
        "zh": "夜晚月光下的森林",
        "expect_mode": "scene",
        "expect_people": 0,
        "forbid_tags": ["1girl", "solo", "looking at viewer"],
    },
    {
        "id": "hug_from_behind",
        "group": "relation",
        "zh": "从身后环抱，膝枕",
        "expect_tags_any": [["hug from behind"], ["lap pillow"]],
    },
    {
        "id": "selfie_phone",
        "group": "prop",
        "zh": "举着手机自拍",
        "expect_tags_any": [["selfie"], ["cellphone", "phone"]],
    },
    {
        "id": "motorcycle_katana_rain",
        "group": "prop",
        "zh": "骑着摩托车拿武士刀雨夜",
        "expect_tags_any": [["motorcycle"], ["katana", "sword"], ["rain", "night"]],
    },
    {
        "id": "shibari_vibrator",
        "group": "prop",
        "zh": "龟甲缚和跳蛋",
        "expect_tags_any": [["shibari", "bondage"], ["vibrator"]],
    },
    # --- Lighting / hair style ---
    {
        "id": "drill_hime",
        "group": "style",
        "zh": "钻头卷发姬发式粉瞳",
        "expect_tags_any": [["drill hair"], ["hime cut"], ["pink eyes"]],
    },
    {
        "id": "rim_light_neon",
        "group": "style",
        "zh": "轮廓光霓虹灯夜景",
        "expect_tags_any": [["rim lighting"], ["neon lights"]],
    },
    {
        "id": "starry_fireflies",
        "group": "style",
        "zh": "星空下萤火虫",
        "expect_tags_any": [["starry sky"], ["fireflies"]],
    },
]


def any_hit(blob: str, groups: list[list[str]] | None) -> bool | None:
    if not groups:
        return None
    low = blob.lower()
    return any(any(token.lower() in low for token in group) for group in groups)


def make_pipeline(use_marian: bool) -> tuple[PromptPipeline, str]:
    if use_marian and marian_runtime_available() and ResourceManager().models_available():
        rm = ResourceManager()
        engine = LazyLocalMarianEngine(rm.model_path("zh_en"), rm.model_path("en_zh"))
        return PromptPipeline(translation=TranslationService(engine)), engine.name
    return PromptPipeline(translation=TranslationService(BuiltinOfflineEngine())), BuiltinOfflineEngine.name


def run_case(pipeline: PromptPipeline, case: dict) -> dict:
    out = {
        "id": case["id"],
        "group": case.get("group", ""),
        "ok": False,
        "crashed": False,
        "tag_hit": None,
        "en_hit": None,
        "people_ok": None,
        "comp_ok": None,
        "mode_ok": None,
        "forbid_ok": None,
        "pure_en": None,
        "error": None,
        "tags": [],
        "en": "",
        "people": None,
        "shot": None,
        "notes": [],
    }
    try:
        job = PromptJob(original_zh=case["zh"])
        pipeline.compiler.apply_model_defaults(job)
        pipeline.translate(job)
        tags = [t.tag for t in job.matched_tags]
        tag_blob = ", ".join(tags) + " | " + (job.positive_prompt or "")
        en = job.translated_en or ""
        out["tags"] = tags
        out["en"] = en[:200]
        out["people"] = job.composition.people_count
        out["shot"] = job.composition.shot
        out["pure_en"] = not bool(re.search(r"[\u4e00-\u9fff]", en))
        out["tag_hit"] = any_hit(tag_blob, case.get("expect_tags_any"))
        out["en_hit"] = any_hit(en, case.get("expect_en_any"))
        if "expect_people" in case:
            out["people_ok"] = job.composition.people_count == case["expect_people"]
        if "expect_mode" in case:
            out["mode_ok"] = job.effective_subject_mode().value == case["expect_mode"] or str(
                job.effective_subject_mode()
            ).endswith(case["expect_mode"])
            # SubjectMode.SCENE value is "scene"
            out["mode_ok"] = job.effective_subject_mode() == SubjectMode.SCENE if case["expect_mode"] == "scene" else out["mode_ok"]
        if "expect_comp" in case:
            out["comp_ok"] = all(getattr(job.composition, k) == v for k, v in case["expect_comp"].items())
        if "expect_comp_not" in case:
            bad = any(getattr(job.composition, k) == v for k, v in case["expect_comp_not"].items())
            out["comp_ok"] = (out["comp_ok"] is not False) and (not bad)
            if out["comp_ok"] is None:
                out["comp_ok"] = not bad
        if "forbid_tags" in case:
            # Only check discrete tag tokens / tag-line entries, not prose
            # (e.g. "looking at the camera" must not trip forbid "camera").
            low_tags = {t.lower() for t in tags}
            tag_line = (job.positive_prompt or "").split("\n\n", 1)[0].lower()
            tag_tokens = {t.strip() for t in tag_line.split(",")}
            out["forbid_ok"] = not any(
                f.lower() in low_tags or f.lower() in tag_tokens for f in case["forbid_tags"]
            )

        checks = [out["tag_hit"], out["en_hit"], out["people_ok"], out["comp_ok"], out["mode_ok"], out["forbid_ok"]]
        relevant = [c for c in checks if c is not None]
        out["ok"] = bool(relevant) and all(relevant) and not out["crashed"]
        if not relevant:
            out["ok"] = not out["crashed"] and bool(en.strip())
    except Exception as exc:
        out["crashed"] = True
        out["ok"] = False
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["traceback"] = traceback.format_exc(limit=3)
    return out


def run_special_checks(pipeline: PromptPipeline) -> list[dict]:
    results = []

    # Quality profiles inject tags
    try:
        configs = ConfigService()
        job = PromptJob(original_zh="一个女孩看镜头", quality_profile_id="body_detail")
        pipeline.compiler.apply_model_defaults(job)
        pipeline.translate(job)
        head = job.positive_prompt.partition("\n\n")[0]
        ok = "detailed skin" in head or "shiny skin" in head
        results.append({"id": "quality_body_detail", "group": "system", "ok": ok, "notes": head[:120]})
    except Exception as exc:
        results.append({"id": "quality_body_detail", "group": "system", "ok": False, "error": str(exc)})

    # Excluded tag stays out even with concept inject
    try:
        job = PromptJob(original_zh="一个女孩看镜头", excluded_tags=["looking at viewer"])
        pipeline.compiler.apply_model_defaults(job)
        pipeline.translate(job)
        tags = {t.tag for t in job.matched_tags}
        ok = "looking at viewer" not in tags
        results.append({"id": "excluded_tag_respected", "group": "system", "ok": ok, "tags": list(tags)[:12]})
    except Exception as exc:
        results.append({"id": "excluded_tag_respected", "group": "system", "ok": False, "error": str(exc)})

    # English authority NSFW
    try:
        job = PromptJob(original_zh="一个女孩")
        pipeline.compiler.apply_model_defaults(job)
        pipeline.translate(job)
        pipeline.update_english(
            job,
            "1girl, 1boy, sex, hetero, missionary, nude, looking at viewer, on bed",
        )
        tags = {t.tag for t in job.matched_tags}
        ok = {"sex", "missionary", "1boy"}.issubset(tags) or (
            "sex" in tags and "missionary" in (job.positive_prompt or "")
        )
        results.append({"id": "english_authority_sex", "group": "system", "ok": ok, "tags": list(tags)[:15]})
    except Exception as exc:
        results.append({"id": "english_authority_sex", "group": "system", "ok": False, "error": str(exc)})

    # English lock not overwritten
    try:
        job = PromptJob(
            original_zh="一个白发女孩",
            translated_en="LOCKED ENGLISH ONLY.",
            translation_state=ItemState.LOCKED,
        )
        pipeline.compiler.apply_model_defaults(job)
        pipeline.translate(job)
        ok = job.translated_en == "LOCKED ENGLISH ONLY."
        results.append({"id": "locked_english", "group": "system", "ok": ok, "en": job.translated_en})
    except Exception as exc:
        results.append({"id": "locked_english", "group": "system", "ok": False, "error": str(exc)})

    # Tag browser data
    try:
        from PySide6.QtWidgets import QApplication
        import os

        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        dialog = TagBrowserDialog()
        ok = len(dialog.entries) >= 200 and dialog.category_combo.count() >= 8
        dialog.search_edit.setText("bikini")
        dialog.refresh_table()
        ok = ok and dialog.table.rowCount() >= 1
        results.append({
            "id": "tag_browser",
            "group": "system",
            "ok": ok,
            "entries": len(dialog.entries),
            "categories": dialog.category_combo.count(),
            "bikini_rows": dialog.table.rowCount(),
        })
    except Exception as exc:
        results.append({"id": "tag_browser", "group": "system", "ok": False, "error": str(exc)})

    # Config quality packs present
    try:
        configs = ConfigService()
        needed = {"soft_sensual", "body_detail", "uncensored_detail", "glossy_wet"}
        ok = needed.issubset(set(configs.quality_profiles))
        results.append({
            "id": "quality_packs_present",
            "group": "system",
            "ok": ok,
            "count": len(configs.quality_profiles),
        })
    except Exception as exc:
        results.append({"id": "quality_packs_present", "group": "system", "ok": False, "error": str(exc)})

    return results


def summarize(results: list[dict], engine: str) -> dict:
    total = len(results)
    ok = sum(1 for r in results if r.get("ok"))
    crash = sum(1 for r in results if r.get("crashed"))
    by_group: dict[str, list[bool]] = {}
    for r in results:
        by_group.setdefault(r.get("group", "?"), []).append(bool(r.get("ok")))
    group_rates = {g: f"{sum(v)}/{len(v)}" for g, v in sorted(by_group.items())}
    fails = [r for r in results if not r.get("ok")]
    return {
        "engine": engine,
        "total": total,
        "ok": ok,
        "fail": total - ok,
        "crash": crash,
        "rate": ok / total if total else 0,
        "by_group": group_rates,
        "failures": [
            {
                "id": r["id"],
                "group": r.get("group"),
                "tag_hit": r.get("tag_hit"),
                "people_ok": r.get("people_ok"),
                "comp_ok": r.get("comp_ok"),
                "forbid_ok": r.get("forbid_ok"),
                "error": r.get("error"),
                "tags": (r.get("tags") or [])[:12],
                "en": (r.get("en") or "")[:120],
            }
            for r in fails
        ],
    }


def main() -> int:
    print("=" * 72)
    print("ANIMA Full Scenario Probe")
    print("=" * 72)

    engines: list[bool] = [False]
    if marian_runtime_available() and ResourceManager().models_available():
        engines.append(True)

    all_reports = []
    for use_marian in engines:
        pipeline, name = make_pipeline(use_marian)
        print(f"\n>>> Engine: {name}")
        results = [run_case(pipeline, c) for c in SCENARIOS]
        results.extend(run_special_checks(pipeline))
        for r in results:
            status = "PASS" if r.get("ok") else ("CRASH" if r.get("crashed") else "FAIL")
            extra = ""
            if r.get("tag_hit") is not None:
                extra += f" tag={r['tag_hit']}"
            if r.get("people_ok") is not None:
                extra += f" people={r['people_ok']}"
            if r.get("comp_ok") is not None:
                extra += f" comp={r['comp_ok']}"
            if r.get("forbid_ok") is not None:
                extra += f" forbid={r['forbid_ok']}"
            print(f"  [{status}] {r['id']:28} {r.get('group',''):12}{extra}")
            if not r.get("ok") and r.get("tags") is not None:
                print(f"         tags: {', '.join((r.get('tags') or [])[:10])}")
                print(f"         en:   {(r.get('en') or '')[:100]}")
            if r.get("error"):
                print(f"         err:  {r['error']}")
        report = summarize(results, name)
        all_reports.append({"summary": report, "results": results})
        print(f"\n  SUMMARY {name}: {report['ok']}/{report['total']} ({report['rate']:.0%})")
        print(f"  by group: {report['by_group']}")
        if report["failures"]:
            print(f"  failures: {', '.join(f['id'] for f in report['failures'])}")

    out_dir = ROOT / "reports" / "full_scenario_probe"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "full_scenario_report.json"
    path.write_text(json.dumps(all_reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {path}")

    # exit 0 if best engine (prefer marian) >= 85% or builtin alone
    best = max(all_reports, key=lambda x: x["summary"]["rate"])
    rate = best["summary"]["rate"]
    print(f"Best engine rate: {best['summary']['engine']} {rate:.0%}")
    return 0 if rate >= 0.75 and best["summary"]["crash"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
