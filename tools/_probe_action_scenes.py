"""Compile a broad set of action scenes and score whether key relations survive."""
from __future__ import annotations

import json
from pathlib import Path

from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio.services.pipeline import PromptPipeline
from anima_prompt_studio.services.translation_service import (
    TranslationService,
    marian_runtime_available,
)

CASES = [
    {
        "id": "figure_four",
        "family": "腿部接触",
        "zh": "一个女孩坐着，右脚踝搭在左膝上，左脚踩地，右脚尖朝下",
        "must": ["right", "left", "knee", "ankle"],
        "nice": ["planted", "floor", "toes"],
        "forbid": ["happy expression"],
        "note": "已有专用编译",
    },
    {
        "id": "both_feet_planted",
        "family": "支撑",
        "zh": "一个女孩坐在高脚凳上，两只脚都踩在地面上，正面全身",
        "must": ["feet", "floor"],
        "nice": ["both", "stool", "full body"],
        "forbid": [],
        "note": "支撑关系，无左右交叉",
    },
    {
        "id": "legs_dangling",
        "family": "支撑",
        "zh": "一个女孩坐在桌沿上，双腿自然垂下，脚没有碰到地面",
        "must": ["dangling", "feet"],
        "nice": ["table", "not touching", "off the ground"],
        "forbid": ["planted"],
        "note": "和踩地相反的支撑",
    },
    {
        "id": "one_foot_stand",
        "family": "支撑",
        "zh": "一个女孩单脚站立，右脚踩地，左腿屈膝抬起",
        "must": ["right", "left"],
        "nice": ["standing on one", "raised", "planted"],
        "forbid": [],
        "note": "单侧支撑",
    },
    {
        "id": "ordinary_crossed_legs",
        "family": "腿部接触",
        "zh": "一个女孩坐着双腿交叠，没有把脚踝搭到膝盖上",
        "must": ["crossed"],
        "nice": ["sitting"],
        "forbid": ["figure-four", "ankle resting across"],
        "note": "普通交叉腿，不应被编译成四字腿",
    },
    {
        "id": "kneeling",
        "family": "姿态",
        "zh": "一个女孩双膝跪在地上，上身挺直，双手放在大腿上",
        "must": ["kneel"],
        "nice": ["both", "thigh"],
        "forbid": ["sitting on"],
        "note": "跪姿",
    },
    {
        "id": "side_lie_hands",
        "family": "躺姿左右",
        "zh": "一个女孩向右侧躺在床上，双膝微弯，右手垫在脸颊下，左手放在腰前",
        "must": ["right", "left"],
        "nice": ["cheek", "waist", "side"],
        "forbid": ["on her back"],
        "note": "侧躺+左右手分工",
    },
    {
        "id": "hug_knees",
        "family": "姿态",
        "zh": "一个女孩坐在窗边抱膝，下巴搁在膝盖上",
        "must": ["knee"],
        "nice": ["hug", "window", "chin"],
        "forbid": [],
        "note": "抱膝",
    },
    {
        "id": "right_hand_mug",
        "family": "手物接触",
        "zh": "一个女孩站着，右手握住白色马克杯的杯柄，左手自然垂下",
        "must": ["right hand", "mug"],
        "nice": ["handle", "left", "hang"],
        "forbid": ["both hands wrap"],
        "note": "单手持物",
    },
    {
        "id": "both_hands_mug",
        "family": "手物接触",
        "zh": "一个女孩坐在桌边，双手从左右两侧包住桌面上冒着热气的白色马克杯",
        "must": ["both hands", "mug"],
        "nice": ["steam", "table"],
        "forbid": [],
        "note": "双手同一物体",
    },
    {
        "id": "pour_tea",
        "family": "手物接触",
        "zh": "一个女孩用右手提起白色茶壶，把茶倒进左手拿着的蓝色杯子里",
        "must": ["right", "left", "teapot", "cup"],
        "nice": ["pour"],
        "forbid": ["both hands hold the teapot"],
        "note": "左右手不同道具",
    },
    {
        "id": "chin_in_right_hand",
        "family": "手部姿态",
        "zh": "一个女孩用右手托着下巴，左手放在桌面上",
        "must": ["right", "chin", "left"],
        "nice": ["rest"],
        "forbid": [],
        "note": "托腮",
    },
    {
        "id": "arms_crossed",
        "family": "手部姿态",
        "zh": "一个女孩双臂交叉抱在胸前站着",
        "must": ["crossed"],
        "nice": ["arms", "chest"],
        "forbid": [],
        "note": "抱胸",
    },
    {
        "id": "hands_in_pockets",
        "family": "手部姿态",
        "zh": "一个女孩双手插在外套口袋里站着",
        "must": ["pocket"],
        "nice": ["both", "hands"],
        "forbid": [],
        "note": "插手",
    },
    {
        "id": "look_down_phone",
        "family": "手物+视线",
        "zh": "一个女孩低着头看右手里的手机，左手自然垂下",
        "must": ["phone", "right"],
        "nice": ["looking down", "left"],
        "forbid": ["looking at viewer"],
        "note": "看手中物",
    },
    {
        "id": "pointing_right",
        "family": "手部姿态",
        "zh": "一个女孩用右手食指指向画面右侧，左手垂在身侧",
        "must": ["right", "point"],
        "nice": ["left", "index"],
        "forbid": [],
        "note": "指向",
    },
    {
        "id": "walk_left_gait",
        "family": "移动",
        "zh": "一个女孩沿着人行道向左走，左脚在前，右脚在后，侧面全身",
        "must": ["left", "walk"],
        "nice": ["right", "forward", "behind"],
        "forbid": ["running"],
        "note": "行走腿序",
    },
    {
        "id": "run_look_back",
        "family": "移动+视线",
        "zh": "一个女孩向左奔跑，身体前倾，但头转向右后方回头看",
        "must": ["run", "left", "look"],
        "nice": ["back", "right"],
        "forbid": [],
        "note": "身体与视线反向",
    },
    {
        "id": "descend_stairs",
        "family": "移动+支撑",
        "zh": "一个女孩走下石阶，左脚踩在较低一级，右脚仍在较高一级，右手扶栏杆，左手提着合上的伞",
        "must": ["left", "right", "stair"],
        "nice": ["railing", "umbrella", "lower", "higher"],
        "forbid": ["going up"],
        "note": "下楼左右脚高度",
    },
    {
        "id": "lean_against_wall",
        "family": "接触",
        "zh": "一个女孩背靠灰色砖墙站着，双手垂在身侧，没有穿过墙",
        "must": ["wall"],
        "nice": ["against", "lean"],
        "forbid": ["through the wall", "stuck"],
        "note": "靠墙，不是穿墙",
    },
    {
        "id": "two_people_sides",
        "family": "双人",
        "zh": "两个女孩并肩站立，黑发女孩在左，金发女孩在右，两人都全身可见",
        "must": ["black", "blonde", "left", "right"],
        "nice": ["two", "2girls"],
        "forbid": ["1girl"],
        "note": "左右身份",
    },
    {
        "id": "pull_up_wrist",
        "family": "双人接触",
        "zh": "站着的黑发女孩在左侧，用右手握住坐在地上的金发女孩的左手腕，把她拉起来",
        "must": ["right", "left", "wrist"],
        "nice": ["standing", "sitting", "pull"],
        "forbid": [],
        "note": "施力/接触手",
    },
    {
        "id": "hug_from_behind",
        "family": "双人接触",
        "zh": "一个男孩从身后环抱住女孩，双手搭在她的腰上",
        "must": ["behind", "hug"],
        "nice": ["waist"],
        "forbid": [],
        "note": "背后抱",
    },
    {
        "id": "full_body_frame",
        "family": "构图",
        "zh": "一个女孩正面站立，完整全身，从头顶到鞋底都在画面内，头顶上方和脚下留白",
        "must": ["full body"],
        "nice": ["head", "feet"],
        "forbid": ["portrait only"],
        "note": "全身入镜",
    },
    {
        "id": "look_at_viewer",
        "family": "视线",
        "zh": "一个女孩坐着，看着镜头微笑",
        "must": ["looking at"],
        "nice": ["viewer", "smile"],
        "forbid": ["looking away"],
        "note": "看镜头",
    },
]


def blob_of(job: PromptJob) -> str:
    tags = ", ".join(item.tag for item in job.matched_tags)
    return " ".join([
        job.translated_en or "",
        job.canonical_prose or "",
        job.positive_prompt or "",
        tags,
    ]).lower()


def score(case: dict, job: PromptJob) -> dict:
    blob = blob_of(job)
    missing = [token for token in case["must"] if token.lower() not in blob]
    nice_hit = [token for token in case["nice"] if token.lower() in blob]
    forbidden_hit = [token for token in case["forbid"] if token.lower() in blob]
    return {
        "id": case["id"],
        "family": case["family"],
        "note": case["note"],
        "ok": not missing and not forbidden_hit,
        "missing": missing,
        "nice_hit": nice_hit,
        "forbidden_hit": forbidden_hit,
        "slots": job.semantic_frame.visual_slots,
        "tags": [item.tag for item in job.matched_tags][:18],
        "en": job.translated_en,
        "prose": (job.canonical_prose or "")[:240],
        "warnings": [item.message for item in job.semantic_warnings[:4]],
    }


def main() -> None:
    engine = "marian" if marian_runtime_available() else "builtin"
    pipe = PromptPipeline(translation=TranslationService())
    results = [score(case, _translate(pipe, case["zh"])) for case in CASES]
    passed = sum(1 for item in results if item["ok"])
    report = {
        "engine": engine,
        "passed": passed,
        "total": len(results),
        "results": results,
    }
    out = Path("reports") / "action_scene_prompt_probe.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"engine={engine} {passed}/{len(results)}")
    for item in results:
        mark = "OK " if item["ok"] else "FAIL"
        print(f"{mark} {item['family']:8} {item['id']:22} miss={item['missing']} bad={item['forbidden_hit']} slots={list(item['slots'])}")
        print(f"     EN: {item['en']}")


def _translate(pipe: PromptPipeline, source: str) -> PromptJob:
    job = PromptJob(original_zh=source)
    pipe.compiler.apply_model_defaults(job)
    return pipe.translate(job)


if __name__ == "__main__":
    main()
