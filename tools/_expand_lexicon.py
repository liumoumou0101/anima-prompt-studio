"""One-shot builder: expand concept_mappings + tags.json + builtin lexicon fragment."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "src" / "anima_prompt_studio" / "configs"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def expand_concepts() -> int:
    base = load_json(CFG / "concept_mappings.json")
    by_id = {item["id"]: item for item in base}

    def put(rule: dict) -> None:
        by_id[rule["id"]] = rule

    # Narrow ass-focus triggers (avoid bare 臀部).
    put({
        "id": "POSE_ASS_FOCUS",
        "triggers": ["臀部特写", "翘臀特写", "屁股特写", "臀部焦点", "丰臀特写"],
        "canonical_en": "ass focus",
        "tags": ["ass", "ass focus"],
        "category": "pose",
        "priority": 92,
        "ensure_en": ["ass focus", "hip focus", "ass"],
        "ensure_phrase": "Ass focus.",
    })
    put({
        "id": "STATE_ASS",
        "triggers": ["翘臀", "丰满臀部", "巨臀"],
        "canonical_en": "ass",
        "tags": ["ass"],
        "category": "state",
        "priority": 82,
        "ensure_en": ["ass", "butt"],
        "ensure_phrase": "Prominent ass.",
    })

    clothing_rows = [
        ("CLOTHING_SCHOOL_UNIFORM", ["校服", "学生装"], "school uniform", ["school uniform"], 90),
        ("CLOTHING_SAILOR", ["水手服"], "sailor senshi uniform", ["sailor senshi uniform", "school uniform"], 92),
        ("CLOTHING_CHINA_DRESS", ["旗袍"], "china dress", ["china dress"], 92),
        ("CLOTHING_KIMONO", ["和服", "浴衣"], "kimono", ["kimono"], 90),
        ("CLOTHING_MAID", ["女仆装"], "maid", ["maid"], 92),
        ("CLOTHING_NUN", ["修女服", "修女服装"], "nun", ["nun"], 90),
        ("CLOTHING_WEDDING", ["婚纱", "婚礼礼服"], "wedding dress", ["wedding dress"], 90),
        ("CLOTHING_BODYSUIT", ["紧身衣", "连体紧身衣"], "bodysuit", ["bodysuit"], 88),
        ("CLOTHING_MINISKIRT", ["短裙", "迷你裙"], "miniskirt", ["miniskirt", "skirt"], 90),
        ("CLOTHING_PLEATED", ["百褶裙"], "pleated skirt", ["pleated skirt", "skirt"], 88),
        ("CLOTHING_MICROSKIRT", ["超短裙"], "microskirt", ["microskirt", "miniskirt"], 90),
        ("CLOTHING_WHITE_SHIRT", ["白衬衫"], "white shirt", ["white shirt", "shirt"], 85),
        ("CLOTHING_OPEN_SHIRT", ["敞开的衬衫", "衬衫敞开", "敞开衬衫"], "open shirt", ["open shirt", "shirt"], 90),
        ("CLOTHING_SWEATER", ["毛衣"], "sweater", ["sweater"], 80),
        ("CLOTHING_COAT", ["外套", "大衣"], "coat", ["coat"], 75),
        ("CLOTHING_JACKET", ["夹克"], "jacket", ["jacket"], 75),
        ("CLOTHING_SUIT", ["西装"], "suit", ["suit"], 80),
        ("CLOTHING_NECKTIE", ["领带"], "necktie", ["necktie"], 80),
        ("CLOTHING_SCARF", ["围巾"], "scarf", ["scarf"], 80),
        ("CLOTHING_GLOVES", ["手套"], "gloves", ["gloves"], 80),
        ("CLOTHING_ELBOW_GLOVES", ["长手套"], "elbow gloves", ["elbow gloves", "gloves"], 85),
        ("CLOTHING_BERET", ["贝雷帽"], "beret", ["beret", "hat"], 85),
        ("CLOTHING_CAT_EARS", ["猫耳", "猫耳发饰"], "cat ears", ["cat ears"], 90),
        ("CLOTHING_BUNNY_EARS", ["兔耳", "兔耳发饰"], "bunny ears", ["bunny ears"], 90),
        ("CLOTHING_FOX_EARS", ["狐狸耳朵"], "fox ears", ["fox ears"], 90),
        ("CLOTHING_HORNS", ["头上长角", "恶魔角"], "horns", ["horns"], 80),
        ("CLOTHING_TAIL", ["尾巴", "有尾巴"], "tail", ["tail"], 80),
        ("CLOTHING_GLASSES", ["眼镜"], "glasses", ["glasses"], 85),
        ("CLOTHING_SUNGLASSES", ["太阳镜", "墨镜"], "sunglasses", ["sunglasses"], 85),
        ("CLOTHING_COLLAR", ["项圈"], "collar", ["collar"], 85),
        ("CLOTHING_CHOKER", ["颈环", "锁骨链"], "choker", ["choker"], 85),
        ("CLOTHING_NECKLACE", ["项链"], "necklace", ["necklace"], 80),
        ("CLOTHING_EARRINGS", ["耳环", "耳饰"], "earrings", ["earrings"], 80),
        ("CLOTHING_HIGH_HEELS", ["高跟鞋"], "high heels", ["high heels"], 85),
        ("CLOTHING_BOOTS", ["靴子"], "boots", ["boots"], 80),
        ("CLOTHING_THIGH_BOOTS", ["过膝靴"], "thigh boots", ["thigh boots", "boots"], 88),
        ("CLOTHING_BAREFOOT", ["赤脚", "光脚", "光着脚"], "barefoot", ["barefoot"], 90),
        ("CLOTHING_PAJAMAS", ["睡衣"], "pajamas", ["pajamas"], 85),
        ("CLOTHING_NIGHTGOWN", ["睡裙"], "nightgown", ["nightgown"], 85),
        ("CLOTHING_BATHROBE", ["浴袍"], "bathrobe", ["bathrobe"], 85),
        ("CLOTHING_TOWEL", ["浴巾", "裹着浴巾", "只裹着浴巾", "只围着浴巾"], "towel", ["towel"], 90),
        ("CLOTHING_SWIMSUIT", ["泳装", "泳衣"], "swimsuit", ["swimsuit"], 90),
        ("CLOTHING_SCHOOL_SWIM", ["死库水", "学校泳装"], "school swimsuit", ["school swimsuit", "swimsuit"], 92),
        ("CLOTHING_BRA", ["胸罩", "文胸"], "bra", ["bra"], 90),
        ("CLOTHING_NO_BRA", ["无胸罩", "不穿胸罩", "没穿胸罩"], "no bra", ["no bra"], 92),
        ("CLOTHING_CAMISOLE", ["吊带背心", "吊带衫"], "camisole", ["camisole"], 85),
        ("CLOTHING_TANK", ["背心"], "tank top", ["tank top"], 80),
        ("CLOTHING_TSHIRT", ["T恤", "t恤"], "t-shirt", ["t-shirt"], 75),
        ("CLOTHING_HOODIE", ["卫衣"], "hoodie", ["hoodie"], 80),
        ("CLOTHING_JEANS", ["牛仔裤"], "jeans", ["jeans"], 80),
        ("CLOTHING_SHORTS", ["短裤"], "shorts", ["shorts"], 80),
        ("CLOTHING_LEGGINGS", ["紧身裤", "瑜伽裤"], "leggings", ["leggings"], 80),
        ("CLOTHING_FISHNETS", ["渔网袜"], "fishnets", ["fishnets"], 90),
        ("CLOTHING_PANTYHOSE", ["连裤袜", "裤袜", "肉丝"], "pantyhose", ["pantyhose"], 90),
        ("CLOTHING_WHITE_THIGHHIGHS", ["白丝"], "white thighhighs", ["white thighhighs", "thighhighs"], 90),
        ("CLOTHING_TORN", ["撕裂的衣服", "衣服破烂", "破衣"], "torn clothes", ["torn clothes"], 88),
        ("CLOTHING_TORN_PANTYHOSE", ["撕裂的丝袜", "破损丝袜"], "torn pantyhose", ["torn pantyhose", "pantyhose"], 88),
        ("CLOTHING_SWEAT", ["出汗", "满身是汗", "汗湿"], "sweat", ["sweat"], 85),
        ("CLOTHING_WET_BODY", ["湿身", "浑身湿透"], "wet", ["wet", "wet clothes"], 88),
        ("CLOTHING_SEE_THROUGH_GEAR", ["透明衣服", "半透明衣服"], "see-through", ["see-through"], 90),
        ("CLOTHING_PANTIES_ONLY", ["只穿着内裤"], "panties only", ["panties"], 92),
        ("CLOTHING_PLAYBOY_BUNNY", ["兔女郎"], "playboy bunny", ["playboy bunny"], 95),
        ("CLOTHING_SUCCUBUS", ["魅魔"], "succubus", ["succubus"], 90),
        ("CLOTHING_NURSE", ["护士装", "护士服"], "nurse", ["nurse"], 90),
        ("CLOTHING_POLICE", ["警察制服"], "police uniform", ["police uniform"], 88),
        ("CLOTHING_MILITARY", ["军装"], "military uniform", ["military uniform"], 85),
        ("CLOTHING_ARMOR", ["盔甲", "铠甲"], "armor", ["armor"], 85),
        ("CLOTHING_WITCH", ["女巫", "魔女"], "witch", ["witch"], 85),
    ]
    for rid, triggers, canonical, tags, priority in clothing_rows:
        put({
            "id": rid,
            "triggers": triggers,
            "canonical_en": canonical,
            "tags": tags,
            "category": "clothing",
            "priority": priority,
            "ensure_en": [canonical] + tags,
            "ensure_phrase": f"Wearing {canonical}.",
        })

    state_rows = [
        ("STATE_LARGE_BREASTS", ["巨乳", "丰满胸部", "大胸部"], "large breasts", ["large breasts"], 95),
        ("STATE_SMALL_BREASTS", ["贫乳", "小胸部", "平坦胸部"], "small breasts", ["small breasts"], 95),
        ("STATE_MEDIUM_BREASTS", ["中等胸部", "普通胸部"], "medium breasts", ["medium breasts"], 90),
        ("STATE_LONG_LEGS", ["长腿", "美腿"], "long legs", ["long legs"], 85),
        ("STATE_THIGHS", ["大腿"], "thighs", ["thighs"], 75),
        ("STATE_COLLARBONE", ["锁骨"], "collarbone", ["collarbone"], 80),
        ("STATE_ABS", ["腹肌"], "abs", ["abs"], 85),
        ("STATE_NAVEL", ["肚脐"], "navel", ["navel"], 85),
        ("STATE_ARMPITS", ["腋下", "腋窝"], "armpits", ["armpits"], 80),
        ("STATE_BOTTOMLESS", ["赤裸下身", "下身赤裸", "不穿裤子"], "bottomless", ["bottomless"], 95),
        ("STATE_PARTIALLY_NUDE", ["半裸"], "partially nude", ["nude"], 90),
        ("STATE_COMPLETELY_NUDE", ["完全裸体"], "completely nude", ["completely nude", "nude"], 97),
        ("STATE_COVERING_BREASTS", ["遮住胸部", "用手遮住胸部", "遮胸", "双手遮胸"], "covering breasts", ["covering breasts"], 92),
        ("STATE_COVERING_CROTCH", ["遮住私处", "遮住下体"], "covering crotch", ["covering crotch"], 90),
        ("STATE_SIDEBOOB", ["侧乳"], "sideboob", ["sideboob"], 90),
        ("STATE_UNDERBOOB", ["下乳"], "underboob", ["underboob"], 90),
        ("STATE_BACKLESS", ["露背", "后背裸体"], "backless outfit", ["backless outfit"], 85),
        ("STATE_ZETTAI", ["绝对领域"], "zettai ryouiki", ["zettai ryouiki"], 90),
    ]
    for rid, triggers, canonical, tags, priority in state_rows:
        put({
            "id": rid,
            "triggers": triggers,
            "canonical_en": canonical,
            "tags": tags,
            "category": "state",
            "priority": priority,
            "ensure_en": [canonical] + tags,
            "ensure_phrase": f"{canonical}.",
        })

    act_rows = [
        ("ACT_COWGIRL", ["女上位", "骑乘位"], "cowgirl position", ["cowgirl position", "sex"], 96),
        ("ACT_DOGGY", ["后入", "后入式", "从后面进入"], "doggy style", ["doggy style", "sex", "from behind"], 96),
        ("ACT_SPOONING", ["侧位"], "spooning", ["spooning", "sex"], 90),
        ("ACT_STANDING_SEX", ["站立位", "站着做爱"], "standing sex", ["standing sex", "sex"], 92),
        ("ACT_FACIAL", ["颜射"], "facial", ["facial", "cum"], 94),
        ("ACT_CUM_IN_PUSSY", ["内射", "中出"], "cum in pussy", ["cum in pussy", "cum"], 94),
        ("ACT_CUM_IN_MOUTH", ["吞精"], "cum in mouth", ["cum in mouth", "cum"], 92),
        ("ACT_CUM_ON_BODY", ["射在身上", "射在胸口"], "cum on body", ["cum on body", "cum"], 90),
        ("ACT_CUM", ["精液", "沾着精液"], "cum", ["cum"], 88),
        ("ACT_PUSSY_JUICE", ["爱液", "淫水"], "pussy juice", ["pussy juice"], 85),
        ("ACT_SQUIRT", ["潮吹"], "female ejaculation", ["female ejaculation"], 90),
        ("ACT_MASTURBATION", ["自慰", "手淫"], "masturbation", ["masturbation"], 94),
        ("ACT_FINGERING", ["手指插入", "用手指插入"], "fingering", ["fingering"], 90),
        ("ACT_PAIZURI", ["乳交"], "paizuri", ["paizuri"], 94),
        ("ACT_FOOTJOB", ["足交"], "footjob", ["footjob"], 90),
        ("ACT_KISS", ["接吻", "亲吻"], "kiss", ["kiss"], 90),
        ("ACT_FRENCH_KISS", ["深吻", "法式接吻"], "french kiss", ["french kiss", "kiss"], 90),
        ("ACT_HUG", ["拥抱"], "hug", ["hug"], 80),
        ("ACT_HOLDING_HANDS", ["牵手"], "holding hands", ["holding hands"], 85),
        ("ACT_WALL_SLAM", ["壁咚"], "against wall", ["against wall"], 88),
        ("ACT_PRINCESS_CARRY", ["公主抱"], "princess carry", ["princess carry"], 88),
        ("ACT_SITTING_ON_LAP", ["跨坐", "坐在腿上"], "sitting on lap", ["sitting on lap"], 90),
        ("ACT_SPREAD_LEGS", ["张开双腿", "张腿", "双腿张开", "M字开腿"], "spread legs", ["spread legs"], 93),
        ("ACT_ARCHED_BACK", ["弓背", "后仰"], "arched back", ["arched back"], 85),
        ("ACT_ON_STOMACH", ["趴着", "俯卧"], "on stomach", ["on stomach"], 85),
        ("ACT_ON_BACK", ["仰躺", "仰卧"], "on back", ["on back"], 85),
        ("ACT_ON_SIDE", ["侧躺"], "on side", ["on side"], 85),
        ("ACT_BENT_OVER", ["弯腰", "趴在桌上"], "bent over", ["bent over"], 88),
        ("ACT_ARMS_BEHIND", ["双手背后", "反剪双手"], "arms behind back", ["arms behind back"], 88),
        ("ACT_ARMS_UP", ["举手", "双手举起"], "arms up", ["arms up"], 85),
        ("ACT_BITE_LIP", ["咬嘴唇", "咬着嘴唇"], "biting own lip", ["biting own lip"], 85),
        ("ACT_OPEN_MOUTH", ["张开嘴", "微张着嘴", "嘴巴微张", "张嘴"], "open mouth", ["open mouth"], 85),
        ("ACT_DROOLING", ["流口水"], "drooling", ["drooling"], 85),
        ("ACT_TEARS", ["眼泪", "含泪", "眼角含泪"], "tears", ["tears"], 85),
        ("ACT_CRYING", ["哭泣", "流泪"], "crying", ["crying"], 85),
        ("ACT_BLUSH", ["脸红", "红着脸", "害羞脸红"], "blush", ["blush"], 88),
        ("ACT_EMBARRASSED", ["害羞", "羞涩"], "embarrassed", ["blush"], 80),
        ("ACT_SEDUCTIVE", ["诱惑", "魅惑", "勾人"], "seductive smile", ["seductive smile"], 85),
        ("ACT_ANGRY", ["生气", "愤怒"], "angry", ["angry"], 85),
        ("ACT_SAD", ["悲伤", "难过"], "sad", ["sad"], 85),
        ("ACT_HAPPY", ["开心", "高兴"], "happy", ["happy"], 80),
        ("ACT_SMILE", ["微笑"], "smile", ["smile"], 80),
        ("ACT_HEAVY_BREATHING", ["喘气", "喘息"], "heavy breathing", ["heavy breathing"], 85),
        ("ACT_HEART_PUPILS", ["心形瞳孔", "爱心瞳", "爱心眼"], "heart-shaped pupils", ["heart-shaped pupils"], 90),
        ("ACT_YURI", ["百合", "女女"], "yuri", ["yuri"], 90),
        ("ACT_YURI_KISS", ["两个女孩亲吻", "女女亲吻"], "yuri", ["yuri", "kiss", "2girls"], 95),
        ("ACT_YURI_SEX", ["两个女孩做爱", "女女做爱", "百合做爱"], "yuri", ["yuri", "sex", "2girls"], 97),
        ("ACT_TENTACLES", ["触手"], "tentacles", ["tentacles"], 90),
        ("ACT_PREGNANT", ["怀孕", "孕肚"], "pregnant", ["pregnant"], 90),
        ("ACT_HANDCUFFS", ["手铐"], "handcuffs", ["handcuffs"], 88),
        ("ACT_BALL_GAG", ["口球", "塞口球"], "ball gag", ["ball gag"], 90),
        ("ACT_LEASH", ["项圈牵引", "牵着项圈", "狗链"], "leash", ["leash"], 88),
        ("ACT_EXHIBITIONISM", ["露出玩法", "在室外露出"], "exhibitionism", ["exhibitionism"], 85),
        ("ACT_CUNNILINGUS", ["舔阴", "口阴"], "cunnilingus", ["cunnilingus", "oral"], 94),
        ("ACT_HANDJOB", ["手交"], "handjob", ["handjob"], 92),
        ("ACT_DEEPTHROAT", ["深喉"], "deepthroat", ["deepthroat", "fellatio"], 92),
        ("ACT_DOUBLE_V", ["双V", "双插"], "double penetration", ["double penetration"], 90),
        ("ACT_GROUP", ["群交", "3P", "三人行"], "group sex", ["group sex"], 90),
    ]
    for rid, triggers, canonical, tags, priority in act_rows:
        put({
            "id": rid,
            "triggers": triggers,
            "canonical_en": canonical,
            "tags": tags,
            "category": "act",
            "priority": priority,
            "ensure_en": [canonical] + tags,
            "ensure_phrase": f"{canonical}.",
        })

    scene_rows = [
        ("SCENE_BEDROOM", ["卧室"], "bedroom", ["bedroom"], 80),
        ("SCENE_CLASSROOM", ["教室"], "classroom", ["classroom"], 85),
        ("SCENE_LIBRARY", ["图书馆"], "library", ["library"], 80),
        ("SCENE_OFFICE", ["办公室"], "office", ["office"], 80),
        ("SCENE_CHANGING", ["更衣室"], "changing room", ["changing room"], 85),
        ("SCENE_ONSEN", ["温泉", "浴场"], "onsen", ["onsen"], 85),
        ("SCENE_POOL", ["泳池", "游泳池"], "pool", ["pool"], 85),
        ("SCENE_STREET", ["街道", "街上"], "street", ["street"], 75),
        ("SCENE_ROOFTOP", ["屋顶", "天台"], "rooftop", ["rooftop"], 80),
        ("SCENE_TRAIN", ["火车", "列车车厢"], "train interior", ["train interior"], 85),
        ("SCENE_CAFE", ["咖啡馆"], "cafe", ["cafe"], 80),
        ("SCENE_BAR", ["酒吧"], "bar", ["bar"], 75),
        ("SCENE_HOSPITAL", ["医院", "病房"], "hospital", ["hospital"], 80),
        ("SCENE_CHURCH", ["教堂"], "church", ["church"], 80),
        ("SCENE_CHERRY", ["樱花", "樱花树下"], "cherry blossoms", ["cherry blossoms"], 85),
        ("SCENE_NEON", ["霓虹灯"], "neon lights", ["neon lights"], 80),
        ("SCENE_CANDLE", ["烛光"], "candlelight", ["candlelight"], 80),
        ("SCENE_BACKLIGHT", ["逆光"], "backlighting", ["backlighting"], 85),
    ]
    for rid, triggers, canonical, tags, priority in scene_rows:
        put({
            "id": rid,
            "triggers": triggers,
            "canonical_en": canonical,
            "tags": tags,
            "category": "scene",
            "priority": priority,
            "ensure_en": [canonical] + tags,
            "ensure_phrase": f"In a {canonical}." if "light" not in canonical else f"{canonical}.",
        })

    appearance_rows = [
        ("HAIR_RED", ["红发", "红色头发"], "red hair", ["red hair"], "hair", 90),
        ("HAIR_GREEN", ["绿发", "绿色头发"], "green hair", ["green hair"], "hair", 90),
        ("HAIR_BROWN", ["棕发", "棕色头发", "褐色头发"], "brown hair", ["brown hair"], "hair", 90),
        ("HAIR_GREY", ["灰发", "灰色头发"], "grey hair", ["grey hair"], "hair", 90),
        ("STYLE_TWINTAILS", ["双马尾"], "twintails", ["twintails"], "style", 90),
        ("STYLE_PONYTAIL", ["单马尾", "马尾"], "ponytail", ["ponytail"], "style", 88),
        ("STYLE_SIDE_PONY", ["侧马尾"], "side ponytail", ["side ponytail"], "style", 90),
        ("STYLE_BRAID", ["辫子", "麻花辫"], "braid", ["braid"], "style", 85),
        ("STYLE_TWIN_BRAIDS", ["双辫"], "twin braids", ["twin braids"], "style", 88),
        ("STYLE_BANGS", ["刘海"], "bangs", ["bangs"], "style", 80),
        ("STYLE_BLUNT_BANGS", ["齐刘海"], "blunt bangs", ["blunt bangs"], "style", 85),
        ("STYLE_AHOGE", ["呆毛"], "ahoge", ["ahoge"], "style", 85),
        ("STYLE_WET_HAIR", ["头发湿漉漉", "湿发"], "wet hair", ["wet hair"], "style", 88),
        ("EYES_BROWN", ["棕瞳", "棕色眼睛"], "brown eyes", ["brown eyes"], "eyes", 90),
        ("EYES_HETERO", ["异色瞳"], "heterochromia", ["heterochromia"], "eyes", 92),
        ("EYES_CLOSED", ["闭眼", "闭着眼睛"], "closed eyes", ["closed eyes"], "eyes", 88),
        ("EYES_HALF", ["半闭眼"], "half-closed eyes", ["half-closed eyes"], "eyes", 88),
    ]
    for rid, triggers, canonical, tags, category, priority in appearance_rows:
        phrase = f"The character has {canonical}." if category in {"hair", "eyes"} else f"{canonical}."
        put({
            "id": rid,
            "triggers": triggers,
            "canonical_en": canonical,
            "tags": tags,
            "category": category,
            "priority": priority,
            "ensure_en": [canonical] + tags,
            "ensure_phrase": phrase,
        })

    # Keep original high-value NSFW entries intact (already in file) and merge.
    # Sort: race/body first-ish by priority then id for stability.
    merged = sorted(by_id.values(), key=lambda x: (-x.get("priority", 0), x["id"]))
    save_json(CFG / "concept_mappings.json", merged)
    return len(merged)


def expand_tags() -> int:
    tags = load_json(CFG / "tags.json")
    by_tag = {item["tag"]: item for item in tags}

    def put(tag: str, category: str, zh: list[str], en: list[str]) -> None:
        by_tag[tag] = {"tag": tag, "category": category, "zh": zh, "en": en}

    extras = [
        ("school uniform", "clothing", ["校服", "学生装"], ["school uniform"]),
        ("maid", "clothing", ["女仆装"], ["maid", "maid outfit"]),
        ("kimono", "clothing", ["和服", "浴衣"], ["kimono"]),
        ("china dress", "clothing", ["旗袍"], ["china dress", "cheongsam"]),
        ("miniskirt", "clothing", ["短裙", "迷你裙"], ["miniskirt", "mini skirt"]),
        ("skirt", "clothing", ["裙子"], ["skirt"]),
        ("white shirt", "clothing", ["白衬衫"], ["white shirt"]),
        ("open shirt", "clothing", ["敞开的衬衫", "衬衫敞开"], ["open shirt"]),
        ("bra", "clothing", ["胸罩", "文胸"], ["bra"]),
        ("no bra", "clothing", ["无胸罩", "不穿胸罩"], ["no bra"]),
        ("pantyhose", "clothing", ["连裤袜", "裤袜", "肉丝"], ["pantyhose"]),
        ("fishnets", "clothing", ["渔网袜"], ["fishnets", "fishnet"]),
        ("high heels", "clothing", ["高跟鞋"], ["high heels"]),
        ("boots", "clothing", ["靴子"], ["boots"]),
        ("barefoot", "clothing", ["赤脚", "光脚"], ["barefoot"]),
        ("gloves", "clothing", ["手套"], ["gloves"]),
        ("choker", "clothing", ["颈环"], ["choker"]),
        ("collar", "clothing", ["项圈"], ["collar"]),
        ("glasses", "clothing", ["眼镜"], ["glasses"]),
        ("cat ears", "clothing", ["猫耳"], ["cat ears"]),
        ("bunny ears", "clothing", ["兔耳"], ["bunny ears"]),
        ("tail", "clothing", ["尾巴"], ["tail"]),
        ("horns", "clothing", ["角", "恶魔角"], ["horns"]),
        ("swimsuit", "clothing", ["泳装", "泳衣"], ["swimsuit"]),
        ("school swimsuit", "clothing", ["死库水", "学校泳装"], ["school swimsuit"]),
        ("playboy bunny", "clothing", ["兔女郎"], ["playboy bunny", "bunny girl"]),
        ("towel", "clothing", ["浴巾", "裹着浴巾"], ["towel"]),
        ("pajamas", "clothing", ["睡衣"], ["pajamas"]),
        ("nightgown", "clothing", ["睡裙"], ["nightgown"]),
        ("torn clothes", "clothing", ["撕裂的衣服", "破衣"], ["torn clothes"]),
        ("sweat", "state", ["出汗", "汗湿"], ["sweat", "sweating"]),
        ("large breasts", "state", ["巨乳", "丰满胸部", "大胸部"], ["large breasts", "big breasts"]),
        ("small breasts", "state", ["贫乳", "小胸部"], ["small breasts"]),
        ("medium breasts", "state", ["中等胸部"], ["medium breasts"]),
        ("sideboob", "state", ["侧乳"], ["sideboob", "side boob"]),
        ("underboob", "state", ["下乳"], ["underboob"]),
        ("bottomless", "state", ["赤裸下身", "下身赤裸"], ["bottomless"]),
        ("completely nude", "state", ["完全裸体", "一丝不挂"], ["completely nude"]),
        ("covering breasts", "state", ["遮住胸部", "双手遮胸"], ["covering breasts"]),
        ("covering crotch", "state", ["遮住私处", "遮住下体"], ["covering crotch"]),
        ("navel", "state", ["肚脐"], ["navel"]),
        ("collarbone", "state", ["锁骨"], ["collarbone"]),
        ("armpits", "state", ["腋下", "腋窝"], ["armpits"]),
        ("long legs", "state", ["长腿", "美腿"], ["long legs"]),
        ("thighs", "state", ["大腿"], ["thighs"]),
        ("cowgirl position", "act", ["女上位", "骑乘位"], ["cowgirl position", "cowgirl"]),
        ("doggy style", "act", ["后入", "后入式"], ["doggy style", "doggystyle"]),
        ("spread legs", "act", ["张开双腿", "张腿", "双腿张开"], ["spread legs"]),
        ("open mouth", "expression", ["张开嘴", "嘴巴微张", "张嘴"], ["open mouth"]),
        ("blush", "expression", ["脸红", "红着脸"], ["blush", "blushing"]),
        ("tears", "expression", ["眼泪", "含泪"], ["tears"]),
        ("crying", "expression", ["哭泣", "流泪"], ["crying"]),
        ("angry", "expression", ["生气", "愤怒"], ["angry"]),
        ("sad", "expression", ["悲伤", "难过"], ["sad"]),
        ("happy", "expression", ["开心", "高兴"], ["happy"]),
        ("kiss", "act", ["接吻", "亲吻"], ["kiss", "kissing"]),
        ("hug", "act", ["拥抱"], ["hug", "hugging"]),
        ("holding hands", "act", ["牵手"], ["holding hands"]),
        ("against wall", "pose", ["壁咚", "靠墙"], ["against wall", "against the wall"]),
        ("bent over", "pose", ["弯腰", "趴在桌上"], ["bent over"]),
        ("on back", "pose", ["仰躺", "仰卧"], ["on back", "lying on back"]),
        ("on stomach", "pose", ["趴着", "俯卧"], ["on stomach"]),
        ("arched back", "pose", ["弓背", "后仰"], ["arched back"]),
        ("arms up", "pose", ["举手", "双手举起"], ["arms up"]),
        ("arms behind back", "pose", ["双手背后"], ["arms behind back"]),
        ("masturbation", "act", ["自慰", "手淫"], ["masturbation"]),
        ("fingering", "act", ["手指插入"], ["fingering"]),
        ("paizuri", "act", ["乳交"], ["paizuri", "titjob"]),
        ("handjob", "act", ["手交"], ["handjob"]),
        ("cunnilingus", "act", ["舔阴"], ["cunnilingus"]),
        ("facial", "act", ["颜射"], ["facial"]),
        ("cum", "act", ["精液"], ["cum", "semen"]),
        ("yuri", "act", ["百合", "女女"], ["yuri"]),
        ("tentacles", "act", ["触手"], ["tentacles"]),
        ("pregnant", "state", ["怀孕", "孕肚"], ["pregnant"]),
        ("handcuffs", "act", ["手铐"], ["handcuffs"]),
        ("leash", "act", ["狗链", "牵着项圈"], ["leash"]),
        ("ball gag", "act", ["口球"], ["ball gag"]),
        ("twintails", "style", ["双马尾"], ["twintails"]),
        ("ponytail", "style", ["马尾", "单马尾"], ["ponytail"]),
        ("braid", "style", ["辫子"], ["braid"]),
        ("ahoge", "style", ["呆毛"], ["ahoge"]),
        ("bangs", "style", ["刘海"], ["bangs"]),
        ("red hair", "hair", ["红发", "红色头发"], ["red hair"]),
        ("green hair", "hair", ["绿发", "绿色头发"], ["green hair"]),
        ("brown hair", "hair", ["棕发", "棕色头发"], ["brown hair"]),
        ("purple hair", "hair", ["紫发", "紫色头发"], ["purple hair"]),
        ("pink hair", "hair", ["粉发", "粉色头发"], ["pink hair"]),
        ("silver hair", "hair", ["银发", "银色头发"], ["silver hair"]),
        ("blue hair", "hair", ["蓝发", "蓝色头发"], ["blue hair"]),
        ("brown eyes", "eyes", ["棕瞳", "棕色眼睛"], ["brown eyes"]),
        ("green eyes", "eyes", ["绿瞳", "绿色眼睛"], ["green eyes"]),
        ("purple eyes", "eyes", ["紫瞳", "紫色眼睛"], ["purple eyes"]),
        ("closed eyes", "eyes", ["闭眼", "闭着眼睛"], ["closed eyes"]),
        ("heterochromia", "eyes", ["异色瞳"], ["heterochromia"]),
        ("bedroom", "scene", ["卧室"], ["bedroom"]),
        ("classroom", "scene", ["教室"], ["classroom"]),
        ("library", "scene", ["图书馆"], ["library"]),
        ("office", "scene", ["办公室"], ["office"]),
        ("pool", "scene", ["泳池", "游泳池"], ["pool"]),
        ("onsen", "scene", ["温泉"], ["onsen"]),
        ("rooftop", "scene", ["屋顶", "天台"], ["rooftop"]),
        ("street", "scene", ["街道", "街上"], ["street"]),
        ("cherry blossoms", "scene", ["樱花", "樱花树下"], ["cherry blossoms"]),
        ("sweat", "state", ["出汗"], ["sweat"]),
        ("wet", "state", ["湿身"], ["wet"]),
        ("seductive smile", "expression", ["诱惑", "魅惑"], ["seductive smile"]),
        ("heavy breathing", "expression", ["喘气", "喘息"], ["heavy breathing"]),
        ("heart-shaped pupils", "expression", ["心形瞳孔", "爱心瞳"], ["heart-shaped pupils"]),
        ("biting own lip", "expression", ["咬嘴唇"], ["biting own lip"]),
        ("drooling", "expression", ["流口水"], ["drooling"]),
    ]
    for tag, category, zh, en in extras:
        put(tag, category, zh, en)

    # Prefer longer zh phrases first implicitly by matcher; keep list stable.
    out = list(by_tag.values())
    save_json(CFG / "tags.json", out)
    return len(out)


def builtin_lexicon_fragment() -> dict[str, str]:
    """Return additional zh->en pairs for BuiltinOfflineEngine."""
    pairs = {
        "校服": "school uniform", "水手服": "sailor uniform", "女仆装": "maid outfit",
        "旗袍": "china dress", "和服": "kimono", "浴衣": "yukata", "婚纱": "wedding dress",
        "短裙": "miniskirt", "迷你裙": "miniskirt", "超短裙": "microskirt", "百褶裙": "pleated skirt",
        "白衬衫": "white shirt", "敞开的衬衫": "open shirt", "衬衫敞开": "open shirt",
        "毛衣": "sweater", "外套": "coat", "夹克": "jacket", "西装": "suit",
        "领带": "necktie", "围巾": "scarf", "手套": "gloves", "长手套": "elbow gloves",
        "贝雷帽": "beret", "猫耳": "cat ears", "兔耳": "bunny ears", "狐狸耳朵": "fox ears",
        "眼镜": "glasses", "太阳镜": "sunglasses", "墨镜": "sunglasses",
        "项圈": "collar", "颈环": "choker", "项链": "necklace", "耳环": "earrings",
        "高跟鞋": "high heels", "靴子": "boots", "过膝靴": "thigh boots",
        "赤脚": "barefoot", "光脚": "barefoot", "睡衣": "pajamas", "睡裙": "nightgown",
        "浴袍": "bathrobe", "浴巾": "towel", "裹着浴巾": "wrapped in a towel",
        "泳装": "swimsuit", "泳衣": "swimsuit", "死库水": "school swimsuit",
        "胸罩": "bra", "文胸": "bra", "无胸罩": "no bra", "不穿胸罩": "no bra",
        "吊带背心": "camisole", "T恤": "t-shirt", "卫衣": "hoodie",
        "牛仔裤": "jeans", "短裤": "shorts", "紧身裤": "leggings",
        "渔网袜": "fishnets", "连裤袜": "pantyhose", "裤袜": "pantyhose", "肉丝": "pantyhose",
        "白丝": "white thighhighs", "撕裂的衣服": "torn clothes", "破衣": "torn clothes",
        "湿身": "wet body", "浑身湿透": "soaking wet", "出汗": "sweating", "汗湿": "sweaty",
        "透明衣服": "see-through clothes", "兔女郎": "playboy bunny", "魅魔": "succubus",
        "护士装": "nurse outfit", "警察制服": "police uniform", "军装": "military uniform",
        "盔甲": "armor", "女巫": "witch", "魔女": "witch",
        "巨乳": "large breasts", "丰满胸部": "large breasts", "大胸部": "large breasts",
        "贫乳": "small breasts", "小胸部": "small breasts", "中等胸部": "medium breasts",
        "侧乳": "sideboob", "下乳": "underboob", "赤裸下身": "bottomless", "下身赤裸": "bottomless",
        "半裸": "partially nude", "完全裸体": "completely nude",
        "遮住胸部": "covering her breasts", "双手遮胸": "covering her breasts with both hands",
        "遮住私处": "covering her crotch", "锁骨": "collarbone", "腹肌": "abs", "肚脐": "navel",
        "腋下": "armpits", "长腿": "long legs", "美腿": "beautiful long legs", "大腿": "thighs",
        "翘臀": "large ass", "丰满臀部": "plump ass",
        "女上位": "cowgirl position", "骑乘位": "cowgirl position",
        "后入": "doggy style", "后入式": "doggy style", "侧位": "spooning",
        "站立位": "standing sex", "颜射": "facial", "内射": "creampie", "中出": "creampie",
        "吞精": "cum in mouth", "精液": "cum", "爱液": "pussy juice", "潮吹": "squirting",
        "自慰": "masturbation", "手淫": "masturbation", "手指插入": "fingering",
        "乳交": "paizuri", "足交": "footjob", "手交": "handjob", "深喉": "deepthroat",
        "舔阴": "cunnilingus", "接吻": "kissing", "亲吻": "kissing", "深吻": "french kiss",
        "拥抱": "hugging", "牵手": "holding hands", "壁咚": "pinned against the wall",
        "公主抱": "princess carry", "跨坐": "sitting on lap", "坐在腿上": "sitting on lap",
        "张开双腿": "spread legs", "张腿": "spread legs", "双腿张开": "spread legs",
        "弓背": "arched back", "趴着": "lying on her stomach", "仰躺": "lying on her back",
        "侧躺": "lying on her side", "弯腰": "bent over", "双手背后": "arms behind back",
        "举手": "arms up", "咬嘴唇": "biting her lip", "张开嘴": "open mouth",
        "嘴巴微张": "slightly open mouth", "流口水": "drooling", "眼泪": "tears",
        "含泪": "teary eyes", "哭泣": "crying", "脸红": "blushing", "红着脸": "blushing",
        "害羞": "embarrassed", "诱惑": "seductive", "喘气": "heavy breathing", "喘息": "panting",
        "心形瞳孔": "heart-shaped pupils", "爱心瞳": "heart-shaped pupils",
        "百合": "yuri", "女女": "yuri", "触手": "tentacles", "怀孕": "pregnant", "孕肚": "pregnant belly",
        "手铐": "handcuffs", "口球": "ball gag", "狗链": "leash", "牵着项圈": "leash",
        "卧室": "bedroom", "教室": "classroom", "图书馆": "library", "办公室": "office",
        "更衣室": "changing room", "温泉": "onsen", "泳池": "pool", "游泳池": "swimming pool",
        "街道": "street", "屋顶": "rooftop", "天台": "rooftop", "咖啡馆": "cafe",
        "酒吧": "bar", "医院": "hospital", "教堂": "church", "樱花": "cherry blossoms",
        "霓虹灯": "neon lights", "烛光": "candlelight", "逆光": "backlit",
        "红发": "red hair", "绿发": "green hair", "棕发": "brown hair", "灰发": "grey hair",
        "双马尾": "twintails", "马尾": "ponytail", "侧马尾": "side ponytail",
        "辫子": "braid", "双辫": "twin braids", "刘海": "bangs", "齐刘海": "blunt bangs",
        "呆毛": "ahoge", "湿发": "wet hair", "棕瞳": "brown eyes", "异色瞳": "heterochromia",
        "闭眼": "closed eyes", "半闭眼": "half-closed eyes",
        "只穿着内裤": "wearing only panties", "只穿着内衣": "wearing only lingerie",
        "几乎全裸": "nearly nude", "群交": "group sex", "3P": "threesome",
        "两个女孩做爱": "two girls having sex", "女女做爱": "two girls having sex",
        "两个女孩亲吻": "two girls kissing",
    }
    return pairs


def main() -> None:
    n_concepts = expand_concepts()
    n_tags = expand_tags()
    lex = builtin_lexicon_fragment()
    out = CFG / "builtin_lexicon_extra.json"
    save_json(out, {"zh_en": lex})
    print(f"concepts={n_concepts} tags={n_tags} lexicon_extra={len(lex)} -> {out}")


if __name__ == "__main__":
    main()
