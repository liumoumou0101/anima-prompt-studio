"""Fill under-served categories: hair/eyes/lighting/weather/shot/emotion/nature/food."""
from __future__ import annotations

import json
from pathlib import Path

CFG = Path(__file__).resolve().parents[1] / "src" / "anima_prompt_studio" / "configs"


def load(n):
    return json.loads((CFG / n).read_text(encoding="utf-8"))


def save(n, data):
    (CFG / n).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def R(rid, triggers, canonical, tags, category, pri, phrase):
    return {
        "id": rid, "triggers": triggers, "canonical_en": canonical, "tags": tags,
        "category": category, "priority": pri,
        "ensure_en": list(dict.fromkeys([canonical] + tags)),
        "ensure_phrase": phrase,
    }


def main():
    by_id = {x["id"]: x for x in load("concept_mappings.json")}
    rows = [
        # Hair colours / styles
        ("HAIR_AQUA", ["水色发", "浅蓝色头发", "水色头发"], "aqua hair", ["aqua hair"], "hair", 88, "Aqua hair."),
        ("HAIR_ORANGE", ["橙发", "橙色头发"], "orange hair", ["orange hair"], "hair", 88, "Orange hair."),
        ("HAIR_LIGHT_BROWN", ["浅棕发", "茶色头发"], "light brown hair", ["light brown hair"], "hair", 86, "Light brown hair."),
        ("HAIR_TWO_TONE", ["双色发", "两色头发"], "two-tone hair", ["two-tone hair", "multicolored hair"], "style", 90, "Two-tone hair."),
        ("HAIR_STREAKED", ["挑染", "发片挑染"], "streaked hair", ["streaked hair"], "style", 88, "Streaked hair."),
        ("HAIR_GRADIENT", ["渐变发色", "染发渐变"], "gradient hair", ["gradient hair"], "style", 88, "Gradient hair."),
        ("HAIR_DRILLS", ["钻头卷", "双螺旋卷"], "drill hair", ["drill hair"], "style", 90, "Drill hair."),
        ("HAIR_HIME", ["姬发式", "公主切"], "hime cut", ["hime cut"], "style", 90, "Hime cut."),
        ("HAIR_BOB", ["波波头", "齐肩短发"], "bob cut", ["bob cut", "short hair"], "style", 88, "Bob cut."),
        ("HAIR_PIXIE", ["精灵短发", "超短发"], "pixie cut", ["pixie cut", "short hair"], "style", 88, "Pixie cut."),
        ("HAIR_SIDE_LOCKS", ["鬓角长发", "侧锁"], "sidelocks", ["sidelocks"], "style", 85, "Sidelocks."),
        ("HAIR_BUN", ["发髻", "丸子头", "单髻"], "hair bun", ["hair bun"], "style", 88, "Hair bun."),
        ("HAIR_DOUBLE_BUN", ["双丸子", "双髻"], "double bun", ["double bun"], "style", 90, "Double buns."),
        ("HAIR_PONTAIL_HIGH", ["高马尾"], "high ponytail", ["high ponytail", "ponytail"], "style", 90, "High ponytail."),
        ("HAIR_LOW_TWIN", ["低双马尾"], "low twintails", ["low twintails", "twintails"], "style", 90, "Low twintails."),
        ("HAIR_CURRY", ["卷发", "微卷"], "curly hair", ["curly hair"], "style", 85, "Curly hair."),
        ("HAIR_STRAIGHT", ["直发"], "straight hair", ["straight hair"], "style", 80, "Straight hair."),
        ("HAIR_OVER_ONE_EYE", ["遮眼刘海", "一眼被遮"], "hair over one eye", ["hair over one eye"], "style", 90, "Hair over one eye."),
        # Eyes
        ("EYES_AQUA", ["水色瞳", "浅蓝色眼睛"], "aqua eyes", ["aqua eyes"], "eyes", 88, "Aqua eyes."),
        ("EYES_ORANGE", ["橙瞳", "橙色眼睛"], "orange eyes", ["orange eyes"], "eyes", 88, "Orange eyes."),
        ("EYES_PINK", ["粉瞳", "粉色眼睛"], "pink eyes", ["pink eyes"], "eyes", 88, "Pink eyes."),
        ("EYES_YELLOW", ["黄瞳", "金色竖瞳"], "yellow eyes", ["yellow eyes"], "eyes", 86, "Yellow eyes."),
        ("EYES_SLIT", ["竖瞳", "猫瞳"], "slit pupils", ["slit pupils"], "eyes", 90, "Slit pupils."),
        ("EYES_SYMBOL", ["符号瞳", "特殊瞳孔"], "symbol-shaped pupils", ["symbol-shaped pupils"], "eyes", 88, "Symbol-shaped pupils."),
        ("EYES_EMPTY", ["空洞眼神", "无高光眼睛"], "empty eyes", ["empty eyes"], "eyes", 88, "Empty eyes."),
        ("EYES_SHINE", ["星星眼", "闪亮的眼睛"], "sparkling eyes", ["sparkle", "shiny eyes"], "eyes", 85, "Sparkling eyes."),
        # Lighting / weather / time
        ("LIGHT_RIM", ["轮廓光", "边缘光", "逆光轮廓"], "rim lighting", ["rim lighting"], "scene", 90, "Rim lighting."),
        ("LIGHT_VOLUMETRIC", ["体积光", "丁达尔光", "光束"], "volumetric lighting", ["volumetric lighting", "god rays"], "scene", 90, "Volumetric lighting."),
        ("LIGHT_NEON", ["霓虹光", "霓虹灯照"], "neon lights", ["neon lights"], "scene", 88, "Neon lights."),
        ("LIGHT_CANDLE", ["烛光照明", "烛火"], "candlelight", ["candlelight"], "scene", 88, "Candlelight."),
        ("LIGHT_MOON", ["月光照", "清冷月光"], "moonlight", ["moonlight"], "scene", 88, "Moonlight."),
        ("LIGHT_SUNSET_GOLD", ["金色夕阳", "夕照"], "golden hour", ["sunset", "golden hour"], "scene", 88, "Golden hour light."),
        ("LIGHT_OVERCAST", ["阴天光", "柔和阴天"], "overcast", ["overcast"], "scene", 82, "Overcast light."),
        ("LIGHT_SPOT", ["追光", "聚光灯"], "spotlight", ["spotlight"], "scene", 85, "Spotlight."),
        ("WEATHER_SNOW", ["下雪", "飘雪", "雪花"], "snowing", ["snow", "snowing"], "scene", 88, "Snowing."),
        ("WEATHER_FOG", ["雾", "薄雾", "雾气"], "fog", ["fog", "mist"], "scene", 85, "Fog."),
        ("WEATHER_STORM", ["暴风雨", "雷雨"], "storm", ["storm", "rain"], "scene", 88, "Storm."),
        ("WEATHER_CLEAR", ["晴天", "万里无云"], "blue sky", ["blue sky", "daylight"], "scene", 85, "Clear blue sky."),
        ("TIME_DAWN", ["黎明", "破晓"], "dawn", ["dawn"], "scene", 88, "Dawn."),
        ("TIME_DUSK", ["薄暮", "日暮"], "dusk", ["dusk", "sunset"], "scene", 88, "Dusk."),
        ("TIME_MIDNIGHT", ["午夜", "深夜"], "midnight", ["night", "midnight"], "scene", 85, "Midnight."),
        # Composition helpers as tags inspiration
        ("SHOT_COWBOY", ["牛仔镜头", "膝上景别"], "cowboy shot", ["cowboy shot"], "pose", 85, "Cowboy shot."),
        ("SHOT_FROM_SIDE", ["侧脸特写", "侧面脸"], "profile", ["profile", "side view"], "pose", 88, "Profile view."),
        ("SHOT_DUTCH", ["倾斜构图", "荷兰角"], "dutch angle", ["dutch angle"], "pose", 85, "Dutch angle."),
        ("SHOT_FISHEYE", ["鱼眼", "广角畸变"], "fisheye", ["fisheye"], "pose", 85, "Fisheye."),
        ("GAZE_TO_SIDE", ["看向一侧", "目光侧视"], "looking to the side", ["looking to the side"], "pose", 85, "Looking to the side."),
        ("GAZE_UP", ["仰视看", "抬头看"], "looking up", ["looking up"], "pose", 85, "Looking up."),
        ("GAZE_DOWN", ["低头看", "俯视下方"], "looking down", ["looking down"], "pose", 85, "Looking down."),
        # Soft emotions / everyday
        ("EMO_SHY_SMILE", ["羞涩微笑", "腼腆笑"], "shy smile", ["smile", "blush"], "expression", 88, "Shy smile."),
        ("EMO_GENTLE", ["温柔表情", "柔和神情"], "gentle smile", ["smile"], "expression", 85, "Gentle expression."),
        ("EMO_SERIOUS", ["认真脸", "严肃"], "serious", ["serious"], "expression", 85, "Serious expression."),
        ("EMO_SURPRISED", ["惊讶", "吃惊", "睁大眼睛"], "surprised", ["surprised"], "expression", 88, "Surprised."),
        ("EMO_CONFUSED", ["困惑", "疑惑"], "confused", ["confused"], "expression", 85, "Confused."),
        ("EMO_SLEEPY", ["困倦", "睡眼惺忪", "打哈欠"], "sleepy", ["sleepy"], "expression", 88, "Sleepy."),
        ("EMO_CRY_SMILE", ["含泪微笑", "笑着哭"], "tearing up", ["tears", "smile"], "expression", 88, "Tearing up while smiling."),
        # Nature / food / furniture props (inspiration)
        ("NAT_PETALS", ["花瓣", "飘落花瓣"], "petals", ["petals", "flower"], "scene", 85, "Petals."),
        ("NAT_LEAVES", ["落叶", "枫叶"], "falling leaves", ["leaf", "autumn"], "scene", 85, "Falling leaves."),
        ("NAT_FIREFLIES", ["萤火虫"], "fireflies", ["fireflies"], "scene", 88, "Fireflies."),
        ("NAT_STARS", ["星空", "满天星"], "starry sky", ["starry sky", "night"], "scene", 88, "Starry sky."),
        ("NAT_OCEAN", ["大海", "海面", "波涛"], "ocean", ["ocean", "sea"], "scene", 85, "Ocean."),
        ("NAT_MOUNTAIN", ["远山", "群山"], "mountain", ["mountain"], "scene", 82, "Mountains."),
        ("FOOD_TEA", ["茶杯", "喝茶", "红茶"], "teacup", ["teacup", "tea"], "state", 85, "Teacup."),
        ("FOOD_CAKE", ["蛋糕", "甜点"], "cake", ["cake"], "state", 82, "Cake."),
        ("FOOD_RAMEN", ["拉面", "吃面"], "ramen", ["ramen", "noodles"], "state", 85, "Ramen."),
        ("FOOD_BENTO", ["便当", "午餐盒"], "bento", ["bento"], "state", 85, "Bento."),
        ("FOOD_ICE_CREAM", ["冰淇淋", "冰棍"], "ice cream", ["ice cream"], "state", 85, "Ice cream."),
        ("FURN_SOFA", ["沙发", "坐在沙发上"], "sofa", ["sofa", "couch"], "scene", 85, "Sofa."),
        ("FURN_DESK", ["书桌", "办公桌"], "desk", ["desk"], "scene", 82, "Desk."),
        ("FURN_SCHOOL_DESK", ["课桌"], "school desk", ["school desk"], "scene", 85, "School desk."),
        ("FURN_CHAIR", ["椅子", "坐在椅子上"], "chair", ["chair"], "scene", 80, "Chair."),
        ("FURN_BALCONY", ["阳台", "露台"], "balcony", ["balcony"], "scene", 85, "Balcony."),
        # Extra clothing everyday
        ("CLOTH_CARDIGAN", ["开衫", "针织开衫"], "cardigan", ["cardigan"], "clothing", 85, "Cardigan."),
        ("CLOTH_SCARF_WINTER", ["冬日围巾", "厚围巾"], "scarf", ["scarf"], "clothing", 85, "Scarf."),
        ("CLOTH_GLOVES_WINTER", ["手套保暖", "毛线手套"], "gloves", ["gloves"], "clothing", 82, "Gloves."),
        ("CLOTH_BERET_FASHION", ["画家帽", "贝雷"], "beret", ["beret"], "clothing", 85, "Beret."),
        ("CLOTH_GLASSES_HALF", ["半框眼镜", "细框眼镜"], "glasses", ["glasses"], "clothing", 82, "Glasses."),
        ("CLOTH_MASK_SURGICAL", ["口罩", "医用口罩"], "mouth mask", ["mouth mask"], "clothing", 85, "Mouth mask."),
        ("CLOTH_HOOD_UP", ["戴着兜帽", "兜帽遮脸"], "hood up", ["hood", "hoodie"], "clothing", 88, "Hood up."),
        ("CLOTH_APRON_KITCHEN", ["厨房围裙", "家居围裙"], "apron", ["apron"], "clothing", 85, "Apron."),
        # More fantasy race
        ("RACE_MERMAID", ["人鱼", "美人鱼"], "mermaid", ["mermaid"], "race", 92, "Mermaid."),
        ("RACE_FAIRY", ["妖精", "小仙子"], "fairy", ["fairy", "wings"], "race", 90, "Fairy."),
        ("RACE_WEREWOLF", ["狼人", "女狼人"], "werewolf", ["werewolf"], "race", 88, "Werewolf."),
        ("RACE_GHOST", ["幽灵", "鬼魂", "灵体"], "ghost", ["ghost"], "race", 88, "Ghost."),
        ("RACE_DOLL", ["人偶", "洋娃娃般"], "doll", ["doll joints", "doll"], "race", 88, "Doll-like."),
    ]
    rule_rows = [R(*item) if isinstance(item, tuple) else item for item in rows]
    for r in rule_rows:
        by_id[r["id"]] = r
    merged = sorted(by_id.values(), key=lambda x: (-x.get("priority", 0), x["id"]))
    save("concept_mappings.json", merged)

    by_tag = {x["tag"]: x for x in load("tags.json")}
    zh_en = dict(load("builtin_lexicon_extra.json").get("zh_en") or {})

    def add_tag(tag, cat, zh, en=None):
        by_tag[tag] = {"tag": tag, "category": cat, "zh": zh, "en": en or [tag]}

    for r in rule_rows:
        for z in r["triggers"]:
            zh_en[z] = r["canonical_en"]
        for tag in r["tags"]:
            if tag not in by_tag:
                add_tag(tag, r["category"], r["triggers"][:3], [tag, r["canonical_en"]])

    extras = [
        ("aqua hair", "hair", ["水色发", "浅蓝色头发"], ["aqua hair"]),
        ("orange hair", "hair", ["橙发"], ["orange hair"]),
        ("two-tone hair", "style", ["双色发"], ["two-tone hair"]),
        ("drill hair", "style", ["钻头卷"], ["drill hair"]),
        ("hime cut", "style", ["姬发式", "公主切"], ["hime cut"]),
        ("bob cut", "style", ["波波头"], ["bob cut"]),
        ("hair bun", "style", ["发髻", "丸子头"], ["hair bun"]),
        ("double bun", "style", ["双丸子"], ["double bun"]),
        ("high ponytail", "style", ["高马尾"], ["high ponytail"]),
        ("hair over one eye", "style", ["遮眼刘海"], ["hair over one eye"]),
        ("aqua eyes", "eyes", ["水色瞳"], ["aqua eyes"]),
        ("pink eyes", "eyes", ["粉瞳"], ["pink eyes"]),
        ("slit pupils", "eyes", ["竖瞳", "猫瞳"], ["slit pupils"]),
        ("rim lighting", "lighting", ["轮廓光", "边缘光"], ["rim lighting"]),
        ("volumetric lighting", "lighting", ["体积光", "丁达尔光"], ["volumetric lighting", "god rays"]),
        ("spotlight", "lighting", ["聚光灯", "追光"], ["spotlight"]),
        ("snowing", "weather", ["下雪", "飘雪"], ["snowing", "snow"]),
        ("fog", "weather", ["雾", "薄雾"], ["fog", "mist"]),
        ("dawn", "time", ["黎明", "破晓"], ["dawn"]),
        ("dusk", "time", ["薄暮", "日暮"], ["dusk"]),
        ("cowboy shot", "shot", ["牛仔镜头", "膝上景别"], ["cowboy shot"]),
        ("dutch angle", "camera", ["倾斜构图", "荷兰角"], ["dutch angle"]),
        ("looking up", "gaze", ["抬头看", "仰视看"], ["looking up"]),
        ("looking down", "gaze", ["低头看"], ["looking down"]),
        ("looking to the side", "gaze", ["看向一侧"], ["looking to the side"]),
        ("petals", "scene", ["花瓣", "飘落花瓣"], ["petals"]),
        ("fireflies", "scene", ["萤火虫"], ["fireflies"]),
        ("starry sky", "scene", ["星空", "满天星"], ["starry sky"]),
        ("teacup", "state", ["茶杯", "喝茶"], ["teacup", "tea"]),
        ("bento", "state", ["便当"], ["bento"]),
        ("sofa", "scene", ["沙发"], ["sofa", "couch"]),
        ("balcony", "scene", ["阳台", "露台"], ["balcony"]),
        ("mermaid", "race", ["人鱼", "美人鱼"], ["mermaid"]),
        ("fairy", "race", ["妖精", "小仙子"], ["fairy"]),
        ("ghost", "race", ["幽灵", "鬼魂"], ["ghost"]),
        ("hood up", "clothing", ["戴着兜帽"], ["hood up"]),
        ("cardigan", "clothing", ["开衫"], ["cardigan"]),
    ]
    for tag, cat, zh, en in extras:
        add_tag(tag, cat, zh, en)
        for z in zh:
            zh_en[z] = tag

    save("tags.json", list(by_tag.values()))
    save("builtin_lexicon_extra.json", {"zh_en": zh_en})
    print(f"concepts={len(merged)} tags={len(by_tag)} lexicon={len(zh_en)}")


if __name__ == "__main__":
    main()
