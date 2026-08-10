"""Fill high-value Marian-path gaps: fantasy, face, sits, clothing state, light acts."""
from __future__ import annotations

import json
from pathlib import Path

CFG = Path(__file__).resolve().parents[1] / "src" / "anima_prompt_studio" / "configs"


def load(name: str):
    return json.loads((CFG / name).read_text(encoding="utf-8"))


def save(name: str, data) -> None:
    (CFG / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def put_concept(by_id: dict, rule: dict) -> None:
    by_id[rule["id"]] = rule


def main() -> None:
    by_id = {x["id"]: x for x in load("concept_mappings.json")}

    rows = [
        ("RACE_ANGEL", ["天使", "天使女孩"], "angel", ["angel"], "race", 90, "She is an angel."),
        ("RACE_DEMON", ["恶魔", "恶魔女孩", "女恶魔"], "demon girl", ["demon girl"], "race", 90, "She is a demon girl."),
        ("RACE_VAMPIRE", ["吸血鬼", "女吸血鬼"], "vampire", ["vampire"], "race", 88, "She is a vampire."),
        ("FEAT_WINGS", ["翅膀", "有翅膀", "展开翅膀"], "wings", ["wings"], "state", 88, "Wings."),
        ("FEAT_HALO", ["光环", "头顶光环"], "halo", ["halo"], "state", 90, "Halo."),
        ("FEAT_POINTED_EARS", ["尖耳", "精灵耳", "尖耳朵"], "pointy ears", ["pointy ears"], "state", 90, "Pointy ears."),
        ("FEAT_ANIMAL_EARS", ["兽耳", "动物耳朵", "耳朵竖起"], "animal ears", ["animal ears"], "state", 92, "Animal ears."),
        ("FEAT_KEMONOMIMI", ["兽化", "兽人化", "半兽"], "kemonomimi", ["kemonomimi", "animal ears"], "state", 90, "Kemonomimi."),
        ("FEAT_TAIL_FLUFFY", ["毛茸茸的尾巴", "蓬松尾巴"], "fluffy tail", ["fluffy tail", "tail"], "state", 88, "Fluffy tail."),
        ("STATE_FUTANARI", ["扶她", "futa", "双性"], "futanari", ["futanari"], "state", 95, "Futanari."),
        ("STATE_SLIME", ["史莱姆", "史莱姆化", "凝胶身体"], "slime", ["slime", "slime girl"], "state", 90, "Slime."),
        ("STATE_CYBORG", ["机械改造", "义体", "赛博", "赛博格", "义肢"], "cyborg", ["cyborg"], "state", 90, "Cyborg."),
        ("STATE_ANDROID", ["机器人女孩", "仿生人", "机械少女"], "android", ["android", "robot girl"], "state", 90, "Android."),
        ("FACE_TEARDROP", ["泪痣", "眼下痣"], "mole under eye", ["mole under eye"], "expression", 90, "Mole under eye."),
        ("FACE_FANGS", ["虎牙", "露出虎牙", "尖牙"], "fang", ["fang", "fangs"], "expression", 90, "Fangs."),
        ("FACE_TONGUE_PIERCE", ["舌钉"], "tongue piercing", ["tongue piercing"], "expression", 88, "Tongue piercing."),
        ("FACE_FACE_MARK", ["面部纹样", "面纹"], "facial mark", ["facial mark"], "expression", 85, "Facial mark."),
        ("POSE_SEIZA", ["正坐", "正座"], "seiza", ["seiza"], "pose", 94, "Sitting seiza."),
        ("POSE_KNEEL_SIT", ["跪坐"], "kneeling", ["kneeling", "seiza"], "pose", 90, "Kneeling sit."),
        ("POSE_WARIZA", ["鸭子坐", "跪坐开腿"], "wariza", ["wariza", "sitting"], "pose", 92, "Wariza sitting."),
        ("POSE_SQUAT", ["蹲踞", "蹲着", "半蹲"], "squatting", ["squatting", "crouching"], "pose", 90, "Squatting."),
        ("POSE_INDIAN_SIT", ["盘腿", "盘腿坐"], "indian style", ["indian style", "sitting"], "pose", 88, "Sitting cross-legged."),
        ("POSE_YOKOZUWARI", ["侧坐", "侧身坐"], "yokozuwari", ["sitting"], "pose", 85, "Sitting sideways."),
        ("CLOTH_OPEN_SHIRT_HALF", ["衬衫半解", "衬衫解开", "扣子解开", "解开扣子"], "unbuttoned shirt", ["unbuttoned shirt", "open shirt"], "clothing", 93, "Unbuttoned shirt."),
        ("CLOTH_STRAP_SLIP", ["肩带滑落", "肩带掉了", "吊带滑落"], "strap slip", ["strap slip"], "clothing", 94, "Strap slip."),
        ("CLOTH_ZIPPER", ["拉链拉开", "拉开拉链", "拉链开着"], "open zipper", ["open zipper"], "clothing", 92, "Open zipper."),
        ("CLOTH_CLOTHES_LIFT", ["掀起衣服", "撩起衣服", "把衣服掀起来"], "clothes lift", ["clothes lift"], "clothing", 92, "Clothes lift."),
        ("CLOTH_SKIRT_LIFT", ["掀裙", "撩起裙子", "把裙子掀起来"], "skirt lift", ["skirt lift", "upskirt"], "clothing", 93, "Skirt lift."),
        ("CLOTH_THROUGH", ["隔着衣服", "隔布", "隔着布"], "through clothes", ["through clothes"], "act", 92, "Through clothes."),
        ("CLOTH_WET_SEE", ["湿身透视", "湿透能看到"], "wet see-through", ["wet clothes", "see-through"], "clothing", 93, "Wet see-through clothes."),
        ("ACT_GRINDING", ["蹭", "磨蹭", "隔着衣服蹭"], "grinding", ["grinding", "clothed sex"], "act", 88, "Grinding."),
        ("ACT_FACESIT_ALIAS", ["骑脸"], "facesitting", ["facesitting"], "act", 95, "Facesitting."),
        ("ACT_CUM_OUTSIDE", ["外射", "射在外面", "体外射精"], "cum on body", ["cum on body", "cum"], "act", 92, "Cum outside / cum on body."),
        ("ACT_CUMSHOT", ["射精", "射出"], "ejaculation", ["ejaculation", "cum"], "act", 88, "Ejaculation."),
        ("ACT_LACTATION", ["喷奶", "泌乳", "母乳"], "lactation", ["lactation"], "act", 90, "Lactation."),
        ("SCENE_INDOORS", ["室内", "房间里", "屋内"], "indoors", ["indoors"], "scene", 80, "Indoors."),
        ("SCENE_OUTDOORS", ["室外", "户外", "屋外"], "outdoors", ["outdoors"], "scene", 80, "Outdoors."),
        ("SCENE_RAINY_NIGHT", ["雨夜"], "rainy night", ["rain", "night"], "scene", 90, "Rainy night."),
        ("SCENE_BY_WINDOW", ["窗边", "靠窗", "在窗边"], "window", ["window", "indoors"], "scene", 85, "By the window."),
        ("GAZE_VIEWER", ["看镜头", "看向镜头", "注视镜头"], "looking at viewer", ["looking at viewer"], "pose", 95, "Looking at viewer."),
        ("SHOT_UPPER", ["半身", "上半身"], "upper body", ["upper body"], "pose", 85, "Upper body shot."),
        ("SHOT_FULL", ["全身", "全貌"], "full body", ["full body"], "pose", 85, "Full body."),
    ]

    for rid, triggers, canonical, tags, category, pri, phrase in rows:
        put_concept(by_id, {
            "id": rid,
            "triggers": triggers,
            "canonical_en": canonical,
            "tags": tags,
            "category": category,
            "priority": pri,
            "ensure_en": [canonical] + tags,
            "ensure_phrase": phrase,
        })

    # crouching concept shouldn't fight POSE_SQUAT - enhancement already has crouching
    merged = sorted(by_id.values(), key=lambda x: (-x.get("priority", 0), x["id"]))
    save("concept_mappings.json", merged)

    by_tag = {x["tag"]: x for x in load("tags.json")}

    def t(tag, cat, zh, en):
        by_tag[tag] = {"tag": tag, "category": cat, "zh": zh, "en": en}

    for tag, cat, zh, en in [
        ("angel", "race", ["天使"], ["angel"]),
        ("demon girl", "race", ["恶魔", "恶魔女孩"], ["demon girl", "demon"]),
        ("wings", "state", ["翅膀"], ["wings"]),
        ("halo", "state", ["光环"], ["halo"]),
        ("pointy ears", "state", ["尖耳", "精灵耳"], ["pointy ears", "pointed ears"]),
        ("animal ears", "state", ["兽耳"], ["animal ears"]),
        ("kemonomimi", "state", ["兽化", "半兽"], ["kemonomimi"]),
        ("futanari", "state", ["扶她", "futa"], ["futanari", "futa"]),
        ("slime", "state", ["史莱姆"], ["slime", "slime girl"]),
        ("cyborg", "state", ["机械改造", "义体", "赛博"], ["cyborg"]),
        ("android", "state", ["机器人女孩", "仿生人"], ["android", "robot girl"]),
        ("mole under eye", "expression", ["泪痣"], ["mole under eye", "teardrop mole"]),
        ("fang", "expression", ["虎牙", "尖牙"], ["fang", "fangs"]),
        ("seiza", "pose", ["正坐", "正座"], ["seiza"]),
        ("wariza", "pose", ["鸭子坐"], ["wariza"]),
        ("squatting", "pose", ["蹲踞", "蹲着"], ["squatting"]),
        ("indian style", "pose", ["盘腿", "盘腿坐"], ["indian style", "cross-legged"]),
        ("unbuttoned shirt", "clothing", ["衬衫半解", "扣子解开"], ["unbuttoned shirt", "unbuttoned"]),
        ("strap slip", "clothing", ["肩带滑落", "吊带滑落"], ["strap slip", "slipped strap"]),
        ("open zipper", "clothing", ["拉链拉开", "拉链开着"], ["open zipper", "unzipped"]),
        ("clothes lift", "clothing", ["掀起衣服", "撩起衣服"], ["clothes lift"]),
        ("skirt lift", "clothing", ["掀裙", "撩起裙子"], ["skirt lift"]),
        ("through clothes", "act", ["隔着衣服", "隔布"], ["through clothes"]),
        ("grinding", "act", ["蹭", "磨蹭"], ["grinding"]),
        ("ejaculation", "act", ["射精"], ["ejaculation"]),
        ("lactation", "act", ["喷奶", "泌乳"], ["lactation"]),
        ("indoors", "scene", ["室内", "房间里"], ["indoors"]),
        ("outdoors", "scene", ["室外", "户外"], ["outdoors"]),
        ("rainy night", "scene", ["雨夜"], ["rainy night"]),
        ("window", "scene", ["窗边", "窗户"], ["window", "by the window"]),
    ]:
        t(tag, cat, zh, en)
    save("tags.json", list(by_tag.values()))

    lex = load("builtin_lexicon_extra.json")
    zh_en = dict(lex.get("zh_en") or {})
    zh_en.update({
        "天使": "angel", "恶魔": "demon girl", "翅膀": "wings", "光环": "halo",
        "尖耳": "pointy ears", "精灵耳": "pointy ears", "兽耳": "animal ears", "兽化": "kemonomimi",
        "扶她": "futanari", "史莱姆": "slime", "机械改造": "cyborg", "义体": "cyborg", "赛博": "cyberpunk",
        "泪痣": "mole under eye", "虎牙": "fangs", "正坐": "seiza", "正座": "seiza",
        "鸭子坐": "wariza", "盘腿": "sitting cross-legged", "蹲踞": "squatting",
        "衬衫半解": "unbuttoned shirt", "扣子解开": "unbuttoned", "肩带滑落": "strap slip",
        "拉链拉开": "open zipper", "掀起衣服": "clothes lift", "隔着衣服": "through clothes",
        "蹭": "grinding", "骑脸": "facesitting", "外射": "cum on body", "射精": "ejaculation",
        "喷奶": "lactation", "室内": "indoors", "室外": "outdoors", "雨夜": "rainy night",
        "窗边": "by the window",
    })
    save("builtin_lexicon_extra.json", {"zh_en": zh_en})
    print(f"concepts={len(merged)} tags={len(by_tag)} lexicon={len(zh_en)}")


if __name__ == "__main__":
    main()
