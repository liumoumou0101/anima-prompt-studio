"""Theme-blind expansion: A clothing-state, B expression/fluids, C props/scenes/jobs."""
from __future__ import annotations

import json
from pathlib import Path

CFG = Path(__file__).resolve().parents[1] / "src" / "anima_prompt_studio" / "configs"


def load(name: str):
    return json.loads((CFG / name).read_text(encoding="utf-8"))


def save(name: str, data) -> None:
    (CFG / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def put(by_id: dict, rule: dict) -> None:
    by_id[rule["id"]] = rule


def rule(rid, triggers, canonical, tags, category, pri, phrase):
    return {
        "id": rid,
        "triggers": triggers,
        "canonical_en": canonical,
        "tags": tags,
        "category": category,
        "priority": pri,
        "ensure_en": list(dict.fromkeys([canonical] + tags)),
        "ensure_phrase": phrase,
    }


def main() -> None:
    by_id = {x["id"]: x for x in load("concept_mappings.json")}
    rows: list[dict] = []

    # ========== A: 半脱 / 走光 / 衣态 ==========
    a = [
        ("CLOTH_ONE_SHOULDER_OFF", ["一边掉肩", "一边露肩", "单肩滑落"], "off shoulder", ["off shoulder"], "clothing", 92, "One shoulder slipped off."),
        ("CLOTH_BOTH_SHOULDERS", ["双肩滑落", "两边肩带都掉了"], "strap slip", ["strap slip", "off shoulder"], "clothing", 93, "Both straps slipped."),
        ("CLOTH_COLLAR_PULLED", ["领口拉开", "扯开领口", "拉开衣领"], "clothes pull", ["clothes pull", "open clothes"], "clothing", 93, "Collar pulled open."),
        ("CLOTH_BREASTS_OUT", ["胸口敞开", "胸前敞开", "袒胸"], "open clothes", ["open clothes", "cleavage"], "clothing", 90, "Chest area open."),
        ("CLOTH_SOCKS_HALF", ["袜子褪到一半", "丝袜褪到小腿", "袜子半脱"], "socks removed", ["socks", "partially undressed"], "clothing", 90, "Socks half-off."),
        ("CLOTH_THIGHHIGHS_SLIDE", ["过膝袜滑落", "长筒袜褪下"], "thighhighs", ["thighhighs", "disheveled"], "clothing", 88, "Thighhighs sliding down."),
        ("CLOTH_ONE_SHOE", ["只穿一只鞋", "单脚穿鞋", "鞋子只穿一只"], "single shoe", ["single shoe", "barefoot"], "clothing", 90, "Wearing only one shoe."),
        ("CLOTH_BAREFOOT_ONE", ["一只脚赤脚"], "barefoot", ["barefoot"], "clothing", 85, "One foot barefoot."),
        ("CLOTH_PANTS_DOWN", ["裤子褪到膝盖", "裤子半脱", "裤子拉到大腿"], "pants down", ["pants down", "undressing"], "clothing", 94, "Pants pulled down."),
        ("CLOTH_SKIRT_AROUND_WAIST", ["裙子堆在腰间", "裙子卷到腰上"], "skirt around waist", ["skirt around waist", "upskirt"], "clothing", 93, "Skirt around waist."),
        ("CLOTH_BRA_SLIP", ["胸罩滑落", "内衣滑落", "文胸半脱"], "bra lift", ["bra lift", "bra"], "clothing", 92, "Bra slipping."),
        ("CLOTH_BRA_REMOVED", ["脱掉胸罩", "没穿文胸只剩外套"], "no bra", ["no bra"], "clothing", 90, "No bra."),
        ("CLOTH_PANTIES_ASIDE", ["内裤拨到一边", "丁字裤拨开", "内裤拉开"], "panties aside", ["panties aside"], "clothing", 95, "Panties aside."),
        ("CLOTH_PANTIES_DOWN", ["内裤褪到膝盖", "内裤半脱"], "panties around ankles", ["panties", "undressing"], "clothing", 93, "Panties pulled down."),
        ("CLOTH_DRESS_SLIP", ["连衣裙滑落", "裙子滑到肩下"], "dress", ["dress", "strap slip"], "clothing", 88, "Dress slipping off shoulders."),
        ("CLOTH_TOWEL_SLIP", ["浴巾滑落", "浴巾要掉了"], "towel slip", ["towel", "almost nude"], "clothing", 92, "Towel slipping."),
        ("CLOTH_SHEET_COVER", ["用床单遮挡", "被子遮胸", "被单裹身"], "covered by blanket", ["sheet grab", "under covers"], "clothing", 88, "Covered by a sheet."),
        ("CLOTH_HAND_COVER_ONLY", ["仅用手遮挡", "只好用手挡"], "covering", ["covering breasts", "covering crotch"], "state", 90, "Covering with hands only."),
        ("CLOTH_WET_SHIRT_CLING", ["衬衫紧贴身体", "湿衣贴身"], "wet shirt", ["wet clothes", "see-through"], "clothing", 91, "Wet shirt clinging to body."),
        ("CLOTH_TRANSPARENT_RAIN", ["雨中衣服透明", "被雨打湿透视"], "wet see-through", ["wet clothes", "see-through", "rain"], "clothing", 92, "Rain-soaked see-through clothes."),
        ("CLOTH_WIND_LIFT", ["被风吹起裙子", "裙摆被吹起"], "wind lift", ["skirt lift", "wind"], "clothing", 90, "Skirt lifted by wind."),
        ("CLOTH_ACCIDENTAL_FLASH", ["不小心走光", "不慎走光", "意外走光"], "flashing", ["flashing", " pantyshot"], "act", 90, "Accidental flashing."),
        ("CLOTH_BUTTON_GAP", ["扣子间的缝隙", "没扣好走光"], "unbuttoned", ["unbuttoned shirt", "cleavage"], "clothing", 88, "Buttons left open."),
        ("CLOTH_ZIPPER_STUCK", ["拉链卡住半开"], "partially unzipped", ["open zipper"], "clothing", 86, "Partially unzipped."),
        ("CLOTH_SLEEVE_SLIP", ["袖子滑落", "衣袖褪下"], "bare shoulders", ["off shoulder"], "clothing", 85, "Sleeves slipped down."),
        ("CLOTH_GLOVES_PARTIAL", ["手套咬着脱", "用嘴脱手套"], "glove biting", ["gloves", "teeth"], "act", 88, "Pulling gloves with teeth."),
        ("CLOTH_STOCKING_TEAR", ["丝袜破了", "丝袜勾丝", "袜子弹丝"], "torn pantyhose", ["torn pantyhose", "pantyhose"], "clothing", 90, "Torn stockings."),
        ("CLOTH_ONLY_SOCKS", ["只穿袜子", "除了袜子什么都没穿"], "socks only", ["socks", "nude"], "clothing", 92, "Wearing only socks."),
        ("CLOTH_ONLY_THIGHHIGHS", ["只穿过膝袜", "只剩过膝袜"], "thighhighs only", ["thighhighs", "nude"], "clothing", 93, "Wearing only thighhighs."),
        ("CLOTH_ONLY_GLOVES", ["只戴手套"], "gloves only", ["gloves", "nude"], "clothing", 90, "Wearing only gloves."),
        ("CLOTH_ONLY_TIE", ["只系领带", "裸体打领带"], "necktie", ["necktie", "nude"], "clothing", 90, "Wearing only a necktie."),
        ("CLOTH_OPEN_COAT_NUDE", ["敞开大衣里面真空", "风衣真空"], "open coat", ["open coat", "nude"], "clothing", 92, "Open coat with nothing underneath."),
        ("CLOTH_APRON_ONLY", ["只穿围裙", "裸体围裙"], "naked apron", ["naked apron"], "clothing", 94, "Naked apron."),
        ("CLOTH_BATHROBE_OPEN", ["浴袍敞开"], "open bathrobe", ["bathrobe", "open clothes"], "clothing", 90, "Open bathrobe."),
        ("CLOTH_YUKATA_LOOSE", ["浴衣凌乱", "浴衣半解"], "open yukata", ["yukata", "open clothes"], "clothing", 91, "Loose open yukata."),
        ("CLOTH_SCHOOL_SWIM_PULL", ["死库水拉到一边", "泳装拨开"], "swimsuit aside", ["school swimsuit", "clothes aside"], "clothing", 93, "Swimsuit pulled aside."),
        ("CLOTH_BIKINI_UNTIE", ["比基尼绳结解开", "泳装带子松了"], "untied bikini", ["bikini", "untied"], "clothing", 92, "Untied bikini."),
        ("CLOTH_MISMATCH_SHOES", ["左右脚鞋子不同"], "mismatched footwear", ["shoes"], "clothing", 80, "Mismatched shoes."),
        ("CLOTH_INSIDE_OUT", ["衣服穿反"], "clothes", ["disheveled"], "clothing", 75, "Clothes inside out."),
        ("CLOTH_RECENTLY_STRIPPED", ["刚脱完衣服", "衣服丢在地上"], "removed clothes", ["clothes on floor", "nude"], "clothing", 88, "Clothes removed, discarded nearby."),
    ]
    for item in a:
        rows.append(rule(*item))

    # ========== B: 表情 / 体液 / 状态 ==========
    b = [
        ("EXPR_SEDUCTIVE_EYES", ["媚眼", "抛媚眼", "色气眼神"], "seductive smile", ["seductive smile", "bedroom eyes"], "expression", 90, "Seductive gaze."),
        ("EXPR_BEDROOM_EYES", ["迷离眼神", "半睁眼色气"], "bedroom eyes", ["bedroom eyes", "half-closed eyes"], "expression", 90, "Bedroom eyes."),
        ("EXPR_SMUG", ["得意脸", "得意笑", "坏笑"], "smug", ["smug"], "expression", 88, "Smug expression."),
        ("EXPR_TSUNDERE", ["傲娇", "别扭表情"], "tsundere", ["blush", "angry"], "expression", 85, "Tsundere expression."),
        ("EXPR_Pouting", ["嘟嘴", "鼓嘴", "撇嘴"], "pout", ["pout"], "expression", 88, "Pouting."),
        ("EXPR_LICK_LIPS", ["舔嘴唇", "舔唇"], "licking lips", ["licking lips", "tongue"], "expression", 90, "Licking lips."),
        ("EXPR_FINGER_IN_MOUTH", ["含手指", "吮手指", "手指含在嘴里"], "finger to mouth", ["finger to mouth", "oral invitation"], "expression", 92, "Finger in mouth."),
        ("EXPR_BITE_GLOVE", ["咬手套"], "glove biting", ["gloves", "teeth"], "expression", 88, "Biting a glove."),
        ("EXPR_BITE_NAIL", ["咬指甲"], "nail biting", ["nervous"], "expression", 80, "Biting nails."),
        ("EXPR_COVER_MOUTH", ["捂嘴", "手捂着嘴"], "hand over own mouth", ["hand over own mouth"], "expression", 88, "Covering mouth with hand."),
        ("EXPR_PEEK", ["从指缝看", "偷瞄"], "peeking", ["peeking", "looking at viewer"], "expression", 85, "Peeking."),
        ("EXPR_WILD_EYES", ["血丝眼", "疯狂眼神"], "crazy eyes", ["crazy eyes"], "expression", 85, "Wild eyes."),
        ("EXPR_HEART_EYES", ["爱心眼", "心动眼"], "heart-shaped pupils", ["heart-shaped pupils"], "expression", 90, "Heart-shaped pupils."),
        ("EXPR_SPIRAL_EYES", ["螺旋眼", "催眠眼"], "spiral eyes", ["spiral eyes", "mind control"], "expression", 90, "Spiral eyes."),
        ("EXPR_X_X", ["晕厥眼", "XX眼", "昏过去的表情"], "x-shaped eyes", ["x eyes", "unconscious"], "expression", 88, "X eyes / knocked out look."),
        ("EXPR_SALIVA", ["口水丝", "津液拉丝", "唾液拉丝", "流着口水丝"], "saliva trail", ["saliva", "drooling"], "expression", 92, "Saliva trail."),
        ("EXPR_SALIVA_DROOL", ["挂着口水", "嘴角口水"], "drooling", ["drooling", "saliva"], "expression", 90, "Drooling."),
        ("EXPR_SWEAT_DROP", ["冷汗", "额角汗滴", "尴尬汗"], "sweatdrop", ["sweatdrop"], "expression", 85, "Sweatdrop."),
        ("EXPR_SWEAT_BEADS", ["汗珠", "满头大汗", "汗水滑落"], "sweat", ["sweat"], "expression", 88, "Sweat beads."),
        ("EXPR_TEAR_STREAK", ["泪痕", "哭花的妆", "泪水流下"], "tears", ["tears", "streaming tears"], "expression", 90, "Tear streaks."),
        ("EXPR_RUNNY_MAKEUP", ["妆花了", "眼线晕开"], "makeup", ["running makeup", "tears"], "expression", 88, "Running makeup."),
        ("EXPR_NOSEBLEED", ["流鼻血", "鼻血"], "nosebleed", ["nosebleed"], "expression", 88, "Nosebleed."),
        ("EXPR_STEAM", ["脸冒热气", "害羞冒烟"], "steam", ["blush", "steam"], "expression", 85, "Steam from embarrassment."),
        ("FLUID_SWEAT_SHINE", ["汗湿反光", "汗水油光"], "sweat", ["sweat", "shiny skin"], "state", 88, "Sweaty shiny skin."),
        ("FLUID_BODY_SWEAT", ["香汗淋漓", "大汗淋漓"], "heavy sweating", ["sweat"], "state", 88, "Heavily sweating."),
        ("FLUID_VAGINAL", ["爱液拉丝", "淫水拉丝", "黏液"], "pussy juice", ["pussy juice"], "state", 90, "Pussy juice."),
        ("FLUID_CUM_DRIP", ["精液滴落", "白浊滴下"], "cumdrip", ["cumdrip", "cum"], "state", 92, "Cum dripping."),
        ("FLUID_CUM_STRING", ["精液丝", "白丝拉丝"], "cum", ["cum", "sticky"], "state", 88, "Cum strings."),
        ("FLUID_ON_FACE", ["脸上沾着", "脸部白浊", "颜射痕迹"], "facial", ["facial", "cum on face"], "state", 93, "Cum on face."),
        ("FLUID_ON_TONGUE", ["舌头上有精液", "伸舌展示精液"], "cum on tongue", ["cum on tongue", "tongue out"], "state", 92, "Cum on tongue."),
        ("FLUID_ON_CHEST", ["胸口沾着精液", "乳上白浊"], "cum on breasts", ["cum on breasts", "cum"], "state", 92, "Cum on breasts."),
        ("FLUID_ON_ASS", ["臀部沾着精液"], "cum on ass", ["cum on ass", "cum"], "state", 90, "Cum on ass."),
        ("FLUID_INSIDE_DRIP", ["从里面流出", "事后流出"], "after sex", ["cumdrip", "after sex"], "state", 90, "Fluids dripping after sex."),
        ("FLUID_BLOOD", ["少量血迹", "破处血"], "blood", ["blood"], "state", 80, "Blood."),
        ("FLUID_MILK", ["乳汁", "溢奶"], "lactation", ["lactation", "breast milk"], "state", 90, "Breast milk."),
        ("STATE_AFTERGLOW", ["事后余韵", "高潮余韵", "脱力"], "after sex", ["after sex", "exhausted"], "state", 88, "Afterglow / exhausted."),
        ("STATE_TREMBLING", ["身体发抖", "双腿发软", "颤抖"], "trembling", ["trembling"], "state", 88, "Trembling."),
        ("STATE_ARCH_ORGASM", ["弓身高潮", "反弓高潮"], "orgasm", ["orgasm", "arched back"], "state", 92, "Orgasm with arched back."),
        ("STATE_LIMP", ["瘫软", "软倒", "没力气"], "limp", ["limp", "exhausted"], "state", 85, "Limp / exhausted."),
        ("STATE_MIND_BREAK", ["精神崩溃", "玩坏了", "失神高潮"], "mind break", ["ahegao", "empty eyes"], "expression", 92, "Mind break expression."),
        ("STATE_DRUNK", ["醉酒", "喝醉", "微醺"], "drunk", ["drunk", "blush"], "state", 88, "Drunk."),
        ("STATE_FEVERISH", ["发烧般潮红", "情热"], "fever", ["blush", "sweat"], "state", 85, "Feverish flush."),
        ("STATE_HICKEY", ["吻痕", "草莓印"], "hickey", ["hickey", "love bite"], "state", 90, "Hickeys."),
        ("STATE_SCRATCH", ["抓痕", "背上抓痕"], "scratch", ["scratch marks"], "state", 85, "Scratch marks."),
        ("STATE_BITE_MARK", ["咬痕"], "bite mark", ["bite mark"], "state", 88, "Bite mark."),
        ("STATE_RESTRAINED_MARK", ["绳痕", "捆绑红痕"], "restraint", ["bound", "red marks"], "state", 88, "Restraint marks."),
        ("STATE_WET_HAIR_STICK", ["湿发贴脸", "刘海湿贴"], "wet hair", ["wet hair", "hair on face"], "style", 88, "Wet hair sticking to face."),
        ("STATE_MESSY_HAIR", ["头发凌乱", "乱发", "刚睡醒头发"], "messy hair", ["messy hair"], "style", 88, "Messy hair."),
        ("STATE_GLOWING_EYES", ["发光的眼睛", "眼中闪着光"], "glowing eyes", ["glowing eyes"], "eyes", 85, "Glowing eyes."),
    ]
    for item in b:
        # fix accidental space in pantyshot tag above in A - handled separately
        rows.append(rule(*item))

    # ========== C: 道具 / 场景 / 职业装 ==========
    c = [
        ("PROP_MOTORCYCLE", ["摩托车", "机车", "骑着摩托"], "motorcycle", ["motorcycle"], "scene", 90, "Motorcycle."),
        ("PROP_BICYCLE", ["自行车", "单车"], "bicycle", ["bicycle"], "scene", 85, "Bicycle."),
        ("PROP_SWORD", ["刀剑", "长剑", "握着剑", "武士刀"], "sword", ["sword", "katana"], "state", 88, "Holding a sword."),
        ("PROP_KATANA", ["武士刀", "太刀", "日本刀"], "katana", ["katana", "sword"], "state", 90, "Katana."),
        ("PROP_DAGGER", ["匕首", "短刀"], "dagger", ["dagger"], "state", 85, "Dagger."),
        ("PROP_GUN", ["手枪", "拿枪", "持枪"], "gun", ["gun", "handgun"], "state", 88, "Holding a gun."),
        ("PROP_UMBRELLA", ["伞", "撑伞", "雨伞", "阳伞"], "umbrella", ["umbrella"], "state", 88, "Umbrella."),
        ("PROP_PHONE", ["手机", "看手机", "玩手机"], "cellphone", ["cellphone", "phone"], "state", 88, "Cellphone."),
        ("PROP_SELFIE", ["自拍", "举着手机自拍"], "selfie", ["selfie", "cellphone"], "act", 90, "Taking a selfie."),
        ("PROP_CAMERA", ["手持相机", "拿着相机", "单反"], "camera", ["camera"], "state", 85, "Holding a camera."),
        ("PROP_BOOK", ["书", "捧着书", "翻书"], "book", ["book"], "state", 80, "Book."),
        ("PROP_WINE", ["红酒杯", "酒杯", "香槟"], "wine glass", ["wine glass", "drinking"], "state", 85, "Wine glass."),
        ("PROP_CIGARETTE", ["香烟", "抽烟", "衔着烟"], "cigarette", ["cigarette", "smoking"], "state", 88, "Cigarette."),
        ("PROP_LOLLIPOP", ["棒棒糖", "舔棒棒糖"], "lollipop", ["lollipop"], "state", 85, "Lollipop."),
        ("PROP_MICROPHONE", ["麦克风", "话筒", "唱歌"], "microphone", ["microphone", "singing"], "state", 85, "Microphone."),
        ("PROP_HEADPHONES", ["耳机", "头戴耳机"], "headphones", ["headphones"], "state", 85, "Headphones."),
        ("PROP_BAG", ["手提包", "书包", "挎包"], "bag", ["bag", "handbag"], "state", 80, "Bag."),
        ("PROP_LEASH_PULL", ["拽着绳子", "拉着牵引绳"], "leash pull", ["leash", "collar"], "act", 90, "Leash pull."),
        ("PROP_CHAIN", ["铁链", "锁链"], "chain", ["chain", "bound"], "state", 88, "Chains."),
        ("PROP_HANDCUFFS_ON", ["戴着手铐", "铐着"], "handcuffs", ["handcuffs"], "state", 90, "Handcuffs."),
        ("PROP_BLINDFOLD_ON", ["蒙着眼", "戴着眼罩"], "blindfold", ["blindfold"], "state", 90, "Blindfold."),
        ("PROP_BALL_GAG_ON", ["塞着口球"], "ball gag", ["ball gag"], "state", 92, "Ball gag."),
        ("PROP_VIBRATOR", ["跳蛋", "振动棒", "按摩棒"], "vibrator", ["vibrator", "sex toy"], "state", 92, "Vibrator."),
        ("PROP_DILDO", ["假阳具", "阳具玩具"], "dildo", ["dildo", "sex toy"], "state", 90, "Dildo."),
        ("PROP_ROPE_SHIBARI", ["绳艺", "龟甲缚", "繁复绳缚"], "shibari", ["shibari", "bondage", "rope"], "act", 94, "Shibari bondage."),
        ("PROP_CANDLE", ["蜡烛", "烛台"], "candle", ["candle", "candlelight"], "scene", 85, "Candle."),
        ("PROP_MIRROR", ["镜子", "对着镜子", "镜中"], "mirror", ["mirror"], "scene", 88, "Mirror."),
        ("PROP_BED_SHEETS", ["凌乱床单", "抓着床单"], "bed sheet", ["bed sheet", "sheet grab"], "scene", 88, "Bed sheets."),
        ("SCENE_CLASSROOM_AFTER", ["放学后教室", "空教室"], "classroom", ["classroom", "after school"], "scene", 88, "Empty classroom."),
        ("SCENE_ROOFTOP_SCHOOL", ["学校天台", "教学楼顶"], "rooftop", ["rooftop", "school"], "scene", 88, "School rooftop."),
        ("SCENE_CLUB", ["社团室", "活动室"], "clubroom", ["clubroom"], "scene", 85, "Clubroom."),
        ("SCENE_NURSE_OFFICE", ["保健室", "校医室"], "nurse's office", ["infirmary"], "scene", 88, "Nurse office."),
        ("SCENE_LOCKER", ["更衣室柜子", "储物柜前"], "locker", ["locker room"], "scene", 85, "Lockers."),
        ("SCENE_SHOWER", ["淋浴间", "花洒下", "洗澡"], "shower", ["shower", "wet"], "scene", 90, "Shower."),
        ("SCENE_BATHTUB", ["浴缸", "泡澡", "浴池"], "bathtub", ["bathtub", "bath"], "scene", 90, "Bathtub."),
        ("SCENE_HOT_SPRING", ["露天温泉", "混浴"], "onsen", ["onsen", "outdoors"], "scene", 90, "Open-air onsen."),
        ("SCENE_BEACH_NIGHT", ["夜晚沙滩", "夜海滩"], "beach", ["beach", "night"], "scene", 88, "Night beach."),
        ("SCENE_FERRIS", ["摩天轮"], "ferris wheel", ["ferris wheel"], "scene", 85, "Ferris wheel."),
        ("SCENE_FESTIVAL", ["祭典", "夏日祭", "烟火大会"], "festival", ["festival", "fireworks"], "scene", 88, "Festival."),
        ("SCENE_SHRINE", ["神社", "鸟居"], "shrine", ["shrine", "torii"], "scene", 88, "Shrine."),
        ("SCENE_ALLEY", ["小巷", "巷子里", "暗巷"], "alley", ["alley", "night"], "scene", 85, "Alley."),
        ("SCENE_HOTEL", ["酒店房间", "宾馆", "旅馆房间"], "hotel room", ["hotel", "indoors"], "scene", 88, "Hotel room."),
        ("SCENE_LOVE_HOTEL", ["情人旅馆", "爱情旅馆"], "love hotel", ["love hotel"], "scene", 90, "Love hotel."),
        ("SCENE_OFFICE_NIGHT", ["加班办公室", "夜里办公室"], "office", ["office", "night"], "scene", 88, "Office at night."),
        ("SCENE_TRAIN_CROWD", ["电车通勤", "拥挤电车"], "train", ["train interior", "crowd"], "scene", 88, "Crowded train."),
        ("SCENE_ELEVATOR", ["电梯里", "电梯间"], "elevator", ["elevator"], "scene", 85, "Elevator."),
        ("SCENE_PARKING", ["停车场", "地库"], "parking lot", ["parking lot"], "scene", 82, "Parking lot."),
        ("SCENE_LIBRARY_QUIET", ["安静的图书馆", "书架之间"], "library", ["library"], "scene", 85, "Library."),
        ("SCENE_GYM", ["健身房", "训练馆"], "gym", ["gym"], "scene", 85, "Gym."),
        ("SCENE_POOLSIDE", ["泳池边", "泳池畔"], "poolside", ["pool"], "scene", 88, "Poolside."),
        ("SCENE_CHERRY_NIGHT", ["夜樱", "樱花夜"], "cherry blossoms", ["cherry blossoms", "night"], "scene", 88, "Cherry blossoms at night."),
        ("SCENE_SNOW_STREET", ["雪街", "雪中街道"], "snow", ["snow", "street"], "scene", 85, "Snowy street."),
        ("JOB_OL", ["OL", "职业女性", "上班族女性", "女职员"], "office lady", ["office lady", "business suit"], "clothing", 90, "Office lady."),
        ("JOB_TEACHER", ["女教师", "老师装", "教师"], "teacher", ["teacher", "glasses"], "clothing", 88, "Teacher."),
        ("JOB_NURSE", ["护士", "护士小姐"], "nurse", ["nurse"], "clothing", 90, "Nurse."),
        ("JOB_DOCTOR", ["女医生", "白大褂"], "doctor", ["lab coat", "doctor"], "clothing", 88, "Doctor."),
        ("JOB_POLICE", ["女警", "警察"], "police", ["police uniform"], "clothing", 88, "Police."),
        ("JOB_WAITRESS", ["女服务员", "餐厅服务员", "女仆咖啡"], "waitress", ["waitress", "apron"], "clothing", 88, "Waitress."),
        ("JOB_IDOL", ["偶像", "偶像装", "舞台服"], "idol", ["idol", "stage"], "clothing", 88, "Idol."),
        ("JOB_RACE_QUEEN", ["赛车女郎", "展场女模"], "race queen", ["race queen"], "clothing", 90, "Race queen."),
        ("JOB_CHEERLEADER", ["啦啦队", "拉拉队服"], "cheerleader", ["cheerleader"], "clothing", 90, "Cheerleader."),
        ("JOB_SECRETARY", ["秘书", "女秘书"], "secretary", ["secretary", "office lady"], "clothing", 88, "Secretary."),
        ("JOB_MAID_CAFE", ["女仆咖啡厅", "咖啡馆女仆"], "maid", ["maid", "cafe"], "clothing", 90, "Maid cafe."),
        ("JOB_SHRINE_MAIDEN", ["巫女", "神社巫女"], "miko", ["miko"], "clothing", 90, "Shrine maiden."),
        ("JOB_NUN", ["修女"], "nun", ["nun"], "clothing", 88, "Nun."),
        ("JOB_KNIGHT", ["女骑士", "骑士铠甲"], "knight", ["armor", "knight"], "clothing", 88, "Knight."),
        ("JOB_MAGE", ["魔法师", "魔女袍"], "wizard", ["wizard hat", "robe"], "clothing", 85, "Mage."),
        ("JOB_SCIENTIST", ["女科学家", "研究员"], "scientist", ["lab coat"], "clothing", 85, "Scientist."),
        ("JOB_PILOT", ["女飞行员", "空姐", "乘务员"], "flight attendant", ["flight attendant"], "clothing", 88, "Flight attendant."),
        ("JOB_SOLDIER", ["女军人", "迷彩服"], "soldier", ["military uniform", "camouflage"], "clothing", 85, "Soldier."),
        ("JOB_DETECTIVE", ["女侦探", "侦探大衣"], "detective", ["coat", "detective"], "clothing", 85, "Detective."),
        ("JOB_BARTENDER", ["调酒师", "女酒保"], "bartender", ["bartender"], "clothing", 85, "Bartender."),
        ("JOB_DANCER", ["舞者", "舞娘", "钢管舞"], "dancer", ["dancer", "stage"], "clothing", 88, "Dancer."),
        ("REL_FROM_BEHIND_HUG", ["从身后环抱", "背后抱住", "后背拥抱"], "hug from behind", ["hug from behind", "embrace"], "act", 94, "Hug from behind."),
        ("REL_CHIN_REST", ["托腮", "手托着下巴"], "chin rest", ["hand on own chin"], "pose", 88, "Chin rest."),
        ("REL_HEADPAT", ["摸头", "抚摸头发"], "headpat", ["headpat"], "act", 85, "Headpat."),
        ("REL_LAP_PILLOW", ["膝枕"], "lap pillow", ["lap pillow"], "act", 90, "Lap pillow."),
        ("REL_PIGGYBACK", ["背着", "背负"], "piggyback", ["piggyback"], "act", 88, "Piggyback."),
        ("REL_HAND_HOLD_BEHIND", ["背后牵手"], "holding hands", ["holding hands", "from behind"], "act", 85, "Holding hands behind back."),
        ("REL_WALL_KISS", ["壁咚接吻", "压在墙上接吻"], "kiss", ["kiss", "against wall"], "act", 92, "Kiss against wall."),
        ("REL_EAR_BITE", ["咬耳朵", "耳边低语"], "whisper", ["biting", "ear"], "act", 88, "Whispering / ear play."),
        ("REL_NECK_KISS", ["吻脖", "吻颈部", "舔脖子"], "necking", ["kissing", "neck"], "act", 90, "Kissing neck."),
    ]
    for item in c:
        rows.append(rule(*item))

    for r in rows:
        # clean accidental bad tag
        r["tags"] = [t.strip() for t in r["tags"] if t.strip() and " pantyshot" not in t]
        if r["id"] == "CLOTH_ACCIDENTAL_FLASH":
            r["tags"] = ["flashing", "pantyshot"]
            r["ensure_en"] = ["flashing", "pantyshot"]
        put(by_id, r)

    merged = sorted(by_id.values(), key=lambda x: (-x.get("priority", 0), x["id"]))
    save("concept_mappings.json", merged)

    # tags + lexicon from all new rules
    by_tag = {x["tag"]: x for x in load("tags.json")}
    zh_en = dict(load("builtin_lexicon_extra.json").get("zh_en") or {})

    def add_tag(tag: str, cat: str, zh: list[str], en: list[str] | None = None):
        by_tag[tag] = {"tag": tag, "category": cat, "zh": zh, "en": en or [tag]}

    for r in rows:
        for zh_t in r["triggers"]:
            zh_en[zh_t] = r["canonical_en"]
        for tag in r["tags"]:
            if tag not in by_tag:
                add_tag(tag, r["category"], r["triggers"][:3], [tag, r["canonical_en"]])

    # explicit important tags with clean zh
    extras = [
        ("naked apron", "clothing", ["只穿围裙", "裸体围裙"], ["naked apron"]),
        ("panties aside", "clothing", ["内裤拨到一边"], ["panties aside"]),
        ("skirt around waist", "clothing", ["裙子堆在腰间"], ["skirt around waist"]),
        ("clothes pull", "clothing", ["领口拉开", "扯开领口"], ["clothes pull"]),
        ("towel slip", "clothing", ["浴巾滑落"], ["towel slip"]),
        ("single shoe", "clothing", ["只穿一只鞋"], ["single shoe"]),
        ("socks only", "clothing", ["只穿袜子"], ["socks only"]),
        ("thighhighs only", "clothing", ["只穿过膝袜"], ["thighhighs only"]),
        ("bedroom eyes", "expression", ["迷离眼神", "媚眼"], ["bedroom eyes"]),
        ("pout", "expression", ["嘟嘴", "鼓嘴"], ["pout", "pouting"]),
        ("smug", "expression", ["得意脸", "坏笑"], ["smug"]),
        ("finger to mouth", "expression", ["含手指"], ["finger to mouth"]),
        ("saliva", "expression", ["口水丝", "津液拉丝"], ["saliva", "saliva trail"]),
        ("nosebleed", "expression", ["流鼻血"], ["nosebleed"]),
        ("mind break", "expression", ["精神崩溃", "玩坏了"], ["mind break"]),
        ("hickey", "state", ["吻痕", "草莓印"], ["hickey"]),
        ("trembling", "state", ["身体发抖", "颤抖"], ["trembling"]),
        ("motorcycle", "scene", ["摩托车", "机车"], ["motorcycle"]),
        ("katana", "state", ["武士刀", "日本刀"], ["katana"]),
        ("cellphone", "state", ["手机"], ["cellphone", "phone"]),
        ("selfie", "act", ["自拍"], ["selfie"]),
        ("umbrella", "state", ["伞", "撑伞"], ["umbrella"]),
        ("shibari", "act", ["绳艺", "龟甲缚"], ["shibari"]),
        ("vibrator", "state", ["跳蛋", "振动棒"], ["vibrator"]),
        ("shower", "scene", ["淋浴间", "洗澡"], ["shower"]),
        ("bathtub", "scene", ["浴缸", "泡澡"], ["bathtub"]),
        ("love hotel", "scene", ["情人旅馆"], ["love hotel"]),
        ("office lady", "clothing", ["OL", "职业女性"], ["office lady"]),
        ("cheerleader", "clothing", ["啦啦队"], ["cheerleader"]),
        ("race queen", "clothing", ["赛车女郎"], ["race queen"]),
        ("hug from behind", "act", ["从身后环抱", "背后抱住"], ["hug from behind"]),
        ("lap pillow", "act", ["膝枕"], ["lap pillow"]),
        ("chin rest", "pose", ["托腮"], ["chin rest", "hand on own chin"]),
    ]
    for tag, cat, zh, en in extras:
        add_tag(tag, cat, zh, en)
        for z in zh:
            zh_en[z] = tag

    save("tags.json", list(by_tag.values()))
    save("builtin_lexicon_extra.json", {"zh_en": zh_en})

    # enhancement rules append
    enh_path = CFG / "enhancement_rules" / "actions.json"
    enh = json.loads(enh_path.read_text(encoding="utf-8"))
    ids = {x["id"] for x in enh}
    new_enh = [
        {"id": "naked_apron", "type": "服装", "priority": 94, "triggers": ["只穿围裙", "裸体围裙"], "content": "Wearing only a naked apron.", "canonical_phrases": ["naked apron"], "emit_tags_when_canonical": True, "tags": ["naked apron"]},
        {"id": "panties_aside", "type": "服装", "priority": 95, "triggers": ["内裤拨到一边", "内裤拉开"], "content": "Panties pulled aside.", "canonical_phrases": ["panties aside"], "emit_tags_when_canonical": True, "tags": ["panties aside"]},
        {"id": "strap_slip_enh", "type": "服装", "priority": 93, "triggers": ["肩带滑落", "吊带滑落", "一边掉肩"], "content": "Strap slip.", "canonical_phrases": ["strap slip"], "emit_tags_when_canonical": True, "tags": ["strap slip"]},
        {"id": "unbuttoned_shirt_enh", "type": "服装", "priority": 92, "triggers": ["衬衫半解", "扣子解开", "领口拉开"], "content": "Shirt unbuttoned / pulled open.", "canonical_phrases": ["unbuttoned", "clothes pull"], "emit_tags_when_canonical": True, "tags": ["unbuttoned shirt", "open shirt"]},
        {"id": "saliva_trail", "type": "表情", "priority": 90, "triggers": ["口水丝", "津液拉丝", "唾液拉丝"], "content": "Saliva trail from the mouth.", "canonical_phrases": ["saliva"], "emit_tags_when_canonical": True, "tags": ["saliva", "drooling"]},
        {"id": "finger_in_mouth", "type": "表情", "priority": 91, "triggers": ["含手指", "吮手指"], "content": "Finger held to her mouth.", "canonical_phrases": ["finger to mouth"], "emit_tags_when_canonical": True, "tags": ["finger to mouth"]},
        {"id": "mind_break_expr", "type": "表情", "priority": 93, "triggers": ["精神崩溃", "玩坏了", "失神高潮"], "content": "Mind-break expression.", "canonical_phrases": ["mind break"], "emit_tags_when_canonical": True, "tags": ["mind break", "ahegao"]},
        {"id": "hug_from_behind", "type": "关系", "priority": 94, "triggers": ["从身后环抱", "背后抱住", "后背拥抱"], "content": "Hug from behind.", "canonical_phrases": ["hug from behind"], "emit_tags_when_canonical": True, "tags": ["hug from behind"]},
        {"id": "lap_pillow", "type": "关系", "priority": 90, "triggers": ["膝枕"], "content": "Lap pillow.", "canonical_phrases": ["lap pillow"], "emit_tags_when_canonical": True, "tags": ["lap pillow"]},
        {"id": "selfie_pose", "type": "动作", "priority": 88, "triggers": ["自拍", "举着手机自拍"], "content": "Taking a selfie.", "canonical_phrases": ["selfie"], "emit_tags_when_canonical": True, "tags": ["selfie", "cellphone"]},
        {"id": "shibari_pose", "type": "动作", "priority": 94, "triggers": ["绳艺", "龟甲缚"], "content": "Shibari rope bondage.", "canonical_phrases": ["shibari"], "emit_tags_when_canonical": True, "tags": ["shibari", "bondage", "rope"]},
        {"id": "shower_scene", "type": "场景", "priority": 88, "triggers": ["淋浴间", "花洒下", "洗澡"], "content": "In the shower, wet.", "canonical_phrases": ["shower"], "emit_tags_when_canonical": True, "tags": ["shower", "wet"]},
        {"id": "ol_outfit", "type": "服装", "priority": 88, "triggers": ["OL", "职业女性", "女职员"], "content": "Office lady outfit.", "canonical_phrases": ["office lady"], "emit_tags_when_canonical": True, "tags": ["office lady"]},
    ]
    for item in new_enh:
        if item["id"] not in ids:
            enh.append(item)
            ids.add(item["id"])
    enh_path.write_text(json.dumps(enh, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"concepts={len(merged)} tags={len(by_tag)} lexicon={len(zh_en)} enhancements={len(enh)} new_rules={len(rows)}")


if __name__ == "__main__":
    main()
