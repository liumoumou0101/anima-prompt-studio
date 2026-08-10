"""Expand cold slang (positions/clothing) + quality dropdown presets + lexicon."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "src" / "anima_prompt_studio" / "configs"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def put_concept(by_id: dict, rule: dict) -> None:
    by_id[rule["id"]] = rule


def expand_concepts() -> int:
    by_id = {x["id"]: x for x in load(CFG / "concept_mappings.json")}

    # --- Cold / slang sex positions ---
    positions = [
        ("ACT_REVERSE_COWGIRL", ["反骑乘", "反向女上位", "背向女上位"], "reverse cowgirl", ["reverse cowgirl", "sex"], 96),
        ("ACT_MATING_PRESS", ["架腿位", "打桩位", "压腿位", "mating press"], "mating press", ["mating press", "sex"], 96),
        ("ACT_FULL_NELSON", ["火车便当", "全尼尔森", "full nelson"], "full nelson", ["full nelson", "sex"], 95),
        ("ACT_AMAZON", ["女战士位", "亚马逊位", "amazon position"], "amazon position", ["amazon position", "sex"], 94),
        ("ACT_LOTUS", ["莲花坐位", "对面坐位", "盘腿抱坐"], "lotus position", ["lotus position", "sex"], 92),
        ("ACT_PRONE_BONE", ["俯卧位", "趴着后入", "prone bone"], "prone bone", ["prone bone", "sex", "from behind"], 95),
        ("ACT_STANDING_DOGGY", ["站立后入", "站着后入"], "standing doggy style", ["standing sex", "doggy style", "sex"], 94),
        ("ACT_LEGGLOCK", ["锁腿", "腿锁位"], "leg lock", ["leg lock", "sex"], 90),
        ("ACT_HAPPY_MATRESS", ["快乐垫子", "枕头垫臀"], "pillow grab", ["sex"], 85),
        ("ACT_FACEDOWN_ASSUP", ["跪趴", "塌腰抬臀", "face down ass up"], "face down ass up", ["all fours", "from behind", "sex"], 94),
        ("ACT_ALL_FOURS", ["四肢着地", "趴跪"], "all fours", ["all fours"], 90),
        ("ACT_SIXTY_NINE", ["六九式", "69", "六九"], "69", ["69", "oral"], 95),
        ("ACT_FACESITTING", ["坐脸", "颜面骑乘"], "facesitting", ["facesitting"], 94),
        ("ACT_IRRUMATIO", ["深喉抽插", "强制口交"], "irrumatio", ["irrumatio", "fellatio"], 92),
        ("ACT_RIMJOB", ["舔肛", "毒龙"], "rimming", ["rimming"], 90),
        ("ACT_ANAL", ["肛交", "后庭", "菊花"], "anal", ["anal"], 94),
        ("ACT_VAGINAL", ["阴道插入", "抽插"], "vaginal", ["vaginal", "sex"], 88),
        ("ACT_GAPE", ["扩张", "张合"], "gaping", ["gaping"], 85),
        ("ACT_CREAMPIE_VISIBLE", ["精液流出", "中出流出"], "cumdrip", ["cumdrip", "cum"], 90),
        ("ACT_BUKKAKE", ["群射", "群射脸上", "颜面射精"], "bukkake", ["bukkake", "cum"], 92),
        ("ACT_PUBLIC_SEX", ["公开做爱", "室外做爱", "野战"], "public sex", ["public indecency", "sex", "outdoors"], 90),
        ("ACT_CLOTHED_SEX", ["穿衣做爱", "半脱做爱"], "clothed sex", ["clothed sex", "sex"], 90),
        ("ACT_QUICKIE", ["快餐式", "速战"], "quickie", ["sex"], 80),
        ("ACT_NETORARE", ["NTR", "绿帽", "寝取"], "netorare", ["netorare"], 88),
        ("ACT_NETORI", ["寝取对方"], "netori", ["netori"], 85),
        ("ACT_CHEATING", ["出轨", "偷情"], "cheating", ["netorare"], 85),
        ("ACT_MIND_CONTROL", ["洗脑", "精神控制", "催眠做爱"], "mind control", ["mind control"], 88),
        ("ACT_DRUGGED", ["下药", "迷奸"], "drugged", ["drugged"], 85),
        ("ACT_SLEEPING_SEX", ["睡奸", "趁睡"], "sleeping", ["sleeping", "sex"], 88),
        ("ACT_RAPE_PLAY", ["强制", "非合意", "凌辱"], "rape", ["rape"], 85),
        ("ACT_AFTERCARE", ["事后温存", "事后拥抱"], "after sex", ["after sex"], 80),
        ("ACT_PRESENTING", ["呈现私处", "掰开展示", "主动展示"], "presenting", ["presenting"], 90),
        ("ACT_SPREAD_PUSSY", ["掰开小穴", "掰穴"], "spread pussy", ["spread pussy"], 92),
        ("ACT_SPREAD_ASS", ["掰开臀部", "掰臀"], "spread ass", ["spread ass"], 90),
        ("ACT_CAMELTOE", ["骆驼趾", "勒出形状"], "cameltoe", ["cameltoe"], 88),
        ("ACT_PANTIE_SHOT", ["裙底", "绝对领域偷拍感", "pantyshot"], "pantyshot", ["pantyshot", "upskirt"], 90),
        ("ACT_UPSKIRT", ["掀裙", "走光裙底"], "upskirt", ["upskirt"], 90),
        ("ACT_DOWNBLOUSE", ["俯视领口", "downblouse"], "downblouse", ["downblouse"], 88),
        ("ACT_SKETCHY_PEEK", ["走光", "不小心露出"], "flashing", ["flashing"], 85),
    ]
    for rid, triggers, canonical, tags, pri in positions:
        put_concept(by_id, {
            "id": rid, "triggers": triggers, "canonical_en": canonical, "tags": tags,
            "category": "act", "priority": pri,
            "ensure_en": [canonical] + tags,
            "ensure_phrase": f"{canonical}.",
        })

    # --- Clothing slang / niche outfits ---
    clothing = [
        ("CLOTHING_JK", ["JK制服", "JK"], "school uniform", ["school uniform"], 93),
        ("CLOTHING_SEIFUKU", ["制服裙", "女子高中生制服"], "seifuku", ["school uniform"], 92),
        ("CLOTHING_BLOOMERS", ["布鲁马", "体操服短裤"], "buruma", ["buruma", "gym uniform"], 92),
        ("CLOTHING_GYM_UNIFORM", ["体操服", "体育服"], "gym uniform", ["gym uniform"], 90),
        ("CLOTHING_BLOUSE", ["衬衫校服", "白上衣"], "blouse", ["blouse"], 80),
        ("CLOTHING_SERAFUKU", ["水手校服"], "serafuku", ["serafuku", "school uniform"], 92),
        ("CLOTHING_LOLI_FASHION", ["洛丽塔", "Lolita装"], "lolita fashion", ["lolita fashion"], 90),
        ("CLOTHING_GOTH_LOLI", ["哥特洛丽塔", "哥特萝莉"], "gothic lolita", ["gothic lolita"], 90),
        ("CLOTHING_QIPAO_SLIT", ["高开叉旗袍", "开叉旗袍"], "china dress", ["china dress", "thighhighs"], 93),
        ("CLOTHING_HANFU", ["汉服"], "hanfu", ["hanfu"], 88),
        ("CLOTHING_MIKO", ["巫女服", "巫女装"], "miko", ["miko"], 92),
        ("CLOTHING_SHRINE", ["神社巫女"], "miko", ["miko"], 90),
        ("CLOTHING_KIMONO_OPEN", ["和服半解", "浴衣半脱"], "open kimono", ["kimono", "open clothes"], 92),
        ("CLOTHING_YUKATA", ["夏日浴衣"], "yukata", ["yukata", "kimono"], 90),
        ("CLOTHING_TAIMANIN", ["对魔忍装", "忍装束"], "kunoichi", ["kunoichi", "ninja"], 88),
        ("CLOTHING_SHINOBI", ["女忍者装"], "kunoichi", ["kunoichi"], 88),
        ("CLOTHING_BONDAGE_OUTFIT", ["束缚装", "皮革束缚衣"], "bondage outfit", ["bondage outfit", "latex"], 92),
        ("CLOTHING_LATEX", ["乳胶衣", "胶衣", "乳胶"], "latex", ["latex"], 92),
        ("CLOTHING_LEATHER", ["皮衣", "皮革装"], "leather", ["leather"], 88),
        ("CLOTHING_BUNNY_REVERSE", ["反兔女郎", "露背兔女郎"], "reverse bunnysuit", ["playboy bunny", "bare back"], 93),
        ("CLOTHING_MICRO_BIKINI", ["微型比基尼", "极小比基尼", "线比基尼"], "micro bikini", ["micro bikini", "bikini"], 94),
        ("CLOTHING_SLINGSHOT", ["吊带泳装", "S型泳装"], "slingshot swimsuit", ["slingshot swimsuit"], 92),
        ("CLOTHING_SHELL_BIKINI", ["贝壳比基尼"], "shell bikini", ["shell bikini", "bikini"], 88),
        ("CLOTHING_SARASHI", ["缠胸布", "抹胸布"], "sarashi", ["sarashi"], 90),
        ("CLOTHING_FUNDOshi", ["兜裆布", "六尺褌"], "fundoshi", ["fundoshi"], 88),
        ("CLOTHING_LOINCLOTH", ["缠腰布"], "loincloth", ["loincloth"], 85),
        ("CLOTHING_PASTIES", ["乳贴", "星形乳贴"], "pasties", ["pasties"], 92),
        ("CLOTHING_CROTCHLESS", ["开档", "开裆内裤", "开档丝袜"], "crotchless", ["crotchless"], 94),
        ("CLOTHING_CROTCHLESS_PANTYHOSE", ["开档连裤袜"], "crotchless pantyhose", ["crotchless pantyhose", "pantyhose"], 94),
        ("CLOTHING_PEARL_THONG", ["珍珠丁字裤"], "pearl thong", ["thong"], 90),
        ("CLOTHING_G_STRING", ["G弦裤", "细带丁字裤"], "g-string", ["g-string", "thong"], 90),
        ("CLOTHING_BOYSHORTS", ["平角内裤", "安全裤"], "boyshorts", ["boyshorts"], 85),
        ("CLOTHING_BLOOMER_OLD", ["灯笼裤"], "bloomers", ["bloomers"], 80),
        ("CLOTHING_SUSPENDERS", ["背带"], "suspenders", ["suspenders"], 80),
        ("CLOTHING_GARTER_STRAPS", ["吊袜夹", "袜带"], "garter straps", ["garter straps"], 90),
        ("CLOTHING_OVER_KNEE", ["过膝袜", "长筒过膝"], "thighhighs", ["thighhighs"], 90),
        ("CLOTHING_SINGLE_THIGHHIGH", ["单边过膝袜", "一边穿袜"], "single thighhigh", ["single thighhigh", "thighhighs"], 90),
        ("CLOTHING_ASYMM_LEGWEAR", ["不对称袜"], "asymmetrical legwear", ["asymmetrical legwear"], 88),
        ("CLOTHING_TABI", ["足袋"], "tabi", ["tabi"], 80),
        ("CLOTHING_GETA", ["木屐"], "geta", ["geta"], 80),
        ("CLOTHING_PLATFORM", ["厚底鞋", "松糕鞋"], "platform footwear", ["platform footwear"], 82),
        ("CLOTHING_ANKLE_LACE", ["绑带高跟"], "ankle lace-up", ["high heels"], 82),
        ("CLOTHING_CHASTITY", ["贞操带"], "chastity belt", ["chastity belt"], 88),
        ("CLOTHING_NIPPLE_PIERCE", ["乳钉", "乳头环"], "nipple piercing", ["nipple piercing"], 90),
        ("CLOTHING_NAVEL_PIERCE", ["脐环", "肚脐钉"], "navel piercing", ["navel piercing"], 88),
        ("CLOTHING_COLLAR_BELL", ["铃铛项圈"], "bell collar", ["collar", "bell"], 88),
        ("CLOTHING_MAID_HEADDRESS", ["女仆头饰", "女仆发带"], "maid headdress", ["maid headdress", "maid"], 90),
        ("CLOTHING_FRILLY", ["荷叶边", "多层花边"], "frills", ["frills"], 80),
        ("CLOTHING_SEE_THROUGH_SILK", ["薄纱", "丝绸透视"], "sheer clothes", ["see-through", "silk"], 90),
        ("CLOTHING_WET_TRANSPARENT", ["湿透透视", "湿衣透视"], "wet see-through", ["wet clothes", "see-through"], 93),
        ("CLOTHING_HALTERNECK", ["绕颈装", "挂脖"], "halterneck", ["halterneck"], 85),
        ("CLOTHING_BACKLESS_DRESS", ["露背裙", "露背礼服"], "backless dress", ["backless dress", "dress"], 90),
        ("CLOTHING_SIDE_SLIT", ["侧开叉", "高开叉裙"], "side slit", ["side slit", "dress"], 88),
        ("CLOTHING_OFF_SHOULDER", ["露肩", "一字肩"], "off shoulder", ["off shoulder"], 88),
        ("CLOTHING_VIRGIN_KILLER", ["处男杀手毛衣", "露背毛衣"], "virgin killer sweater", ["virgin killer sweater"], 92),
        ("CLOTHING_OVERSIZED_SHIRT", ["男友衬衫", "宽大衬衫"], "oversized shirt", ["oversized shirt", "shirt"], 88),
        ("CLOTHING_ONLY_SHIRT", ["只穿衬衫"], "shirt only", ["shirt", "no pants"], 90),
        ("CLOTHING_LAUNDRY", ["衣物半挂", "衣服挂在手臂"], "clothes around waist", ["clothes around waist"], 82),
        ("CLOTHING_STRIPPING", ["正在脱衣", "半脱"], "undressing", ["undressing"], 88),
        ("CLOTHING_DISHEVELED", ["衣衫不整", "凌乱衣服"], "disheveled clothes", ["disheveled"], 85),
        ("CLOTHING_AFTER_SEX_CLOTHES", ["事后凌乱着装"], "after sex", ["disheveled", "sweat"], 85),
    ]
    for rid, triggers, canonical, tags, pri in clothing:
        put_concept(by_id, {
            "id": rid, "triggers": triggers, "canonical_en": canonical, "tags": tags,
            "category": "clothing", "priority": pri,
            "ensure_en": [canonical] + tags,
            "ensure_phrase": f"Wearing {canonical}.",
        })

    # Body slang
    body = [
        ("STATE_OPPAI", ["欧派", "大欧派"], "large breasts", ["large breasts"], 93),
        ("STATE_DEKAI", ["超大的胸", "夸张巨乳"], "huge breasts", ["huge breasts"], 94),
        ("STATE_FLAT", ["平板", "飞机场"], "flat chest", ["flat chest"], 93),
        ("STATE_INNIE", ["内陷脐"], "innie navel", ["navel"], 80),
        ("STATE_OUTIE", ["凸肚脐"], "outie navel", ["navel"], 80),
        ("STATE_THICK_THIGHS", ["粗腿", "肉感大腿"], "thick thighs", ["thick thighs"], 90),
        ("STATE_WIDE_HIPS", ["宽髋", "丰胯"], "wide hips", ["wide hips"], 88),
        ("STATE_NARROW_WAIST", ["蜂腰", "纤腰"], "narrow waist", ["narrow waist"], 88),
        ("STATE_SHINY_SKIN", ["油光皮肤", "发亮皮肤", "油腻皮肤"], "shiny skin", ["shiny skin"], 88),
        ("STATE_OILED", ["涂油", "全身油光"], "oiled", ["oiled", "shiny skin"], 90),
        ("STATE_TANLINES", ["晒痕", "泳装晒痕"], "tanlines", ["tanlines"], 90),
        ("STATE_DARK_SKIN", ["黑皮", "深色皮肤"], "dark skin", ["dark skin"], 90),
        ("STATE_PALE", ["苍白皮肤", "白皙"], "pale skin", ["pale skin"], 85),
        ("STATE_FRECKLES", ["雀斑"], "freckles", ["freckles"], 85),
        ("STATE_PUBIC", ["阴毛", "耻毛"], "pubic hair", ["pubic hair"], 88),
        ("STATE_SHAVE", ["剃光", "白虎"], "shaved", ["shaved"], 88),
    ]
    for rid, triggers, canonical, tags, pri in body:
        put_concept(by_id, {
            "id": rid, "triggers": triggers, "canonical_en": canonical, "tags": tags,
            "category": "state", "priority": pri,
            "ensure_en": [canonical] + tags,
            "ensure_phrase": f"{canonical}.",
        })

    merged = sorted(by_id.values(), key=lambda x: (-x.get("priority", 0), x["id"]))
    save(CFG / "concept_mappings.json", merged)
    return len(merged)


def expand_tags() -> int:
    by_tag = {x["tag"]: x for x in load(CFG / "tags.json")}

    def put(tag, category, zh, en):
        by_tag[tag] = {"tag": tag, "category": category, "zh": zh, "en": en}

    rows = [
        ("reverse cowgirl", "act", ["反骑乘", "反向女上位"], ["reverse cowgirl"]),
        ("mating press", "act", ["架腿位", "打桩位", "压腿位"], ["mating press"]),
        ("full nelson", "act", ["火车便当", "全尼尔森"], ["full nelson"]),
        ("amazon position", "act", ["女战士位", "亚马逊位"], ["amazon position"]),
        ("lotus position", "act", ["莲花坐位", "对面坐位"], ["lotus position"]),
        ("prone bone", "act", ["俯卧位", "趴着后入"], ["prone bone"]),
        ("all fours", "pose", ["四肢着地", "跪趴"], ["all fours", "on all fours"]),
        ("69", "act", ["六九式", "69", "六九"], ["69", "sixty-nine"]),
        ("facesitting", "act", ["坐脸", "颜面骑乘"], ["facesitting", "face sitting"]),
        ("anal", "act", ["肛交", "后庭"], ["anal"]),
        ("bukkake", "act", ["群射"], ["bukkake"]),
        ("cumdrip", "act", ["精液流出"], ["cumdrip", "cum dripping"]),
        ("clothed sex", "act", ["穿衣做爱"], ["clothed sex"]),
        ("public indecency", "act", ["公开做爱", "野战"], ["public indecency", "public sex"]),
        ("presenting", "act", ["呈现私处", "主动展示"], ["presenting"]),
        ("spread pussy", "act", ["掰开小穴", "掰穴"], ["spread pussy"]),
        ("spread ass", "act", ["掰开臀部"], ["spread ass"]),
        ("cameltoe", "act", ["骆驼趾"], ["cameltoe"]),
        ("pantyshot", "act", ["裙底", "pantyshot"], ["pantyshot", "panty shot"]),
        ("upskirt", "act", ["掀裙", "走光裙底"], ["upskirt"]),
        ("downblouse", "act", ["俯视领口"], ["downblouse"]),
        ("netorare", "act", ["NTR", "绿帽", "寝取"], ["netorare", "ntr"]),
        ("buruma", "clothing", ["布鲁马", "体操服短裤"], ["buruma", "bloomers"]),
        ("gym uniform", "clothing", ["体操服", "体育服"], ["gym uniform"]),
        ("serafuku", "clothing", ["水手校服", "水手服"], ["serafuku"]),
        ("lolita fashion", "clothing", ["洛丽塔"], ["lolita fashion", "lolita"]),
        ("gothic lolita", "clothing", ["哥特洛丽塔"], ["gothic lolita"]),
        ("miko", "clothing", ["巫女服", "巫女装"], ["miko", "shrine maiden"]),
        ("hanfu", "clothing", ["汉服"], ["hanfu"]),
        ("latex", "clothing", ["乳胶衣", "胶衣", "乳胶"], ["latex", "latex suit"]),
        ("micro bikini", "clothing", ["微型比基尼", "极小比基尼"], ["micro bikini"]),
        ("slingshot swimsuit", "clothing", ["吊带泳装"], ["slingshot swimsuit"]),
        ("sarashi", "clothing", ["缠胸布"], ["sarashi"]),
        ("fundoshi", "clothing", ["兜裆布"], ["fundoshi"]),
        ("crotchless", "clothing", ["开档", "开裆内裤"], ["crotchless"]),
        ("crotchless pantyhose", "clothing", ["开档连裤袜"], ["crotchless pantyhose"]),
        ("g-string", "clothing", ["G弦裤"], ["g-string"]),
        ("pasties", "clothing", ["乳贴"], ["pasties"]),
        ("virgin killer sweater", "clothing", ["处男杀手毛衣", "露背毛衣"], ["virgin killer sweater"]),
        ("halterneck", "clothing", ["挂脖", "绕颈装"], ["halterneck"]),
        ("off shoulder", "clothing", ["露肩", "一字肩"], ["off shoulder", "off-shoulder"]),
        ("side slit", "clothing", ["侧开叉", "高开叉"], ["side slit"]),
        ("backless dress", "clothing", ["露背裙"], ["backless dress"]),
        ("undressing", "act", ["正在脱衣", "半脱"], ["undressing", "clothes being removed"]),
        ("huge breasts", "state", ["超大的胸", "夸张巨乳"], ["huge breasts"]),
        ("flat chest", "state", ["平板", "飞机场"], ["flat chest"]),
        ("thick thighs", "state", ["粗腿", "肉感大腿"], ["thick thighs"]),
        ("wide hips", "state", ["宽髋", "丰胯"], ["wide hips"]),
        ("shiny skin", "state", ["油光皮肤", "发亮皮肤"], ["shiny skin"]),
        ("oiled", "state", ["涂油", "全身油光"], ["oiled"]),
        ("tanlines", "state", ["晒痕", "泳装晒痕"], ["tanlines"]),
        ("dark skin", "state", ["黑皮", "深色皮肤"], ["dark skin"]),
        ("pale skin", "state", ["苍白皮肤", "白皙"], ["pale skin"]),
        ("pubic hair", "state", ["阴毛"], ["pubic hair"]),
        ("nipple piercing", "clothing", ["乳钉"], ["nipple piercing"]),
        ("navel piercing", "clothing", ["脐环"], ["navel piercing"]),
        ("single thighhigh", "clothing", ["单边过膝袜"], ["single thighhigh"]),
    ]
    for tag, category, zh, en in rows:
        put(tag, category, zh, en)
    out = list(by_tag.values())
    save(CFG / "tags.json", out)
    return len(out)


def expand_lexicon() -> int:
    path = CFG / "builtin_lexicon_extra.json"
    data = load(path) if path.is_file() else {"zh_en": {}}
    zh_en = dict(data.get("zh_en") or {})
    extra = {
        "反骑乘": "reverse cowgirl", "反向女上位": "reverse cowgirl", "背向女上位": "reverse cowgirl",
        "架腿位": "mating press", "打桩位": "mating press", "压腿位": "mating press",
        "火车便当": "full nelson", "全尼尔森": "full nelson",
        "女战士位": "amazon position", "亚马逊位": "amazon position",
        "莲花坐位": "lotus position", "对面坐位": "lotus position",
        "俯卧位": "prone bone", "趴着后入": "prone bone",
        "站立后入": "standing doggy style", "跪趴": "face down ass up", "塌腰抬臀": "face down ass up",
        "四肢着地": "on all fours", "六九式": "69", "六九": "69",
        "坐脸": "facesitting", "颜面骑乘": "facesitting",
        "肛交": "anal", "后庭": "anal", "深喉抽插": "irrumatio",
        "舔肛": "rimming", "精液流出": "cumdrip", "群射": "bukkake",
        "野战": "public sex", "公开做爱": "public sex", "穿衣做爱": "clothed sex",
        "NTR": "netorare", "绿帽": "netorare", "寝取": "netorare",
        "掰穴": "spread pussy", "掰开小穴": "spread pussy", "骆驼趾": "cameltoe",
        "裙底": "pantyshot", "掀裙": "upskirt", "走光": "flashing",
        "JK制服": "school uniform", "JK": "high school girl",
        "布鲁马": "buruma", "体操服": "gym uniform", "水手校服": "serafuku",
        "洛丽塔": "lolita fashion", "哥特洛丽塔": "gothic lolita",
        "巫女服": "miko outfit", "汉服": "hanfu",
        "乳胶衣": "latex suit", "胶衣": "latex", "乳胶": "latex",
        "微型比基尼": "micro bikini", "极小比基尼": "micro bikini", "线比基尼": "micro bikini",
        "吊带泳装": "slingshot swimsuit", "缠胸布": "sarashi", "兜裆布": "fundoshi",
        "开档": "crotchless", "开裆内裤": "crotchless panties", "开档连裤袜": "crotchless pantyhose",
        "G弦裤": "g-string", "乳贴": "pasties",
        "处男杀手毛衣": "virgin killer sweater", "露背毛衣": "virgin killer sweater",
        "挂脖": "halterneck", "露肩": "off shoulder", "一字肩": "off shoulder",
        "侧开叉": "side slit", "高开叉": "side slit", "露背裙": "backless dress",
        "男友衬衫": "oversized shirt", "只穿衬衫": "wearing only a shirt",
        "正在脱衣": "undressing", "半脱": "half-undressed", "衣衫不整": "disheveled clothes",
        "欧派": "breasts", "大欧派": "large breasts", "飞机场": "flat chest", "平板": "flat chest",
        "粗腿": "thick thighs", "肉感大腿": "thick thighs", "蜂腰": "narrow waist",
        "油光皮肤": "shiny skin", "涂油": "oiled body", "晒痕": "tanlines", "泳装晒痕": "tanlines",
        "黑皮": "dark skin", "深色皮肤": "dark skin", "白虎": "shaved",
        "阴毛": "pubic hair", "乳钉": "nipple piercings", "脐环": "navel piercing",
        "单边过膝袜": "single thighhigh", "不对称袜": "asymmetrical legwear",
        "铃铛项圈": "bell collar", "女仆头饰": "maid headdress",
        "薄纱": "sheer fabric", "湿透透视": "wet see-through clothes",
        "呈现私处": "presenting", "主动展示": "presenting",
        "银发": "silver hair", "紫发": "purple hair", "粉发": "pink hair", "蓝发": "blue hair",
        "站在": "standing in", "坐在": "sitting on", "躺在": "lying on",
        "看着": "looking at", "带着": "with", "没有": "without",
        "非常": "very", "稍微": "slightly", "轻轻": "gently",
        "正在": "", "一个": "a ", "一名": "a ",
    }
    zh_en.update(extra)
    save(path, {"zh_en": zh_en})
    return len(zh_en)


def expand_quality_profiles() -> int:
    """Same dropdown as before (质量预设), more enhancement-oriented packs."""
    profiles = [
        {"id": "draft", "display_name": "草稿", "base_quality_tags": ["safe"]},
        {
            "id": "standard", "display_name": "标准",
            "base_quality_tags": ["masterpiece", "best quality", "safe"],
        },
        {
            "id": "portrait_detail", "display_name": "精致人物",
            "base_quality_tags": ["masterpiece", "best quality", "safe"],
            "rendering_style_tags": ["anime illustration"],
            "detail_tags": ["delicate details", "detailed face", "detailed eyes", "detailed hair"],
        },
        {
            "id": "ornate_illustration", "display_name": "华丽插画",
            "base_quality_tags": ["masterpiece", "best quality", "safe"],
            "rendering_style_tags": ["anime illustration", "vivid colors"],
            "detail_tags": ["beautiful lighting", "delicate details"],
        },
        {
            "id": "atmospheric", "display_name": "氛围叙事",
            "base_quality_tags": ["masterpiece", "best quality", "safe"],
            "rendering_style_tags": ["anime illustration"],
            "atmosphere_tags": ["atmospheric lighting", "moody atmosphere"],
        },
        {
            "id": "soft_sensual", "display_name": "柔感氛围",
            "base_quality_tags": ["masterpiece", "best quality", "safe"],
            "rendering_style_tags": ["anime illustration", "soft focus"],
            "detail_tags": ["detailed skin", "soft lighting"],
            "atmosphere_tags": ["romantic atmosphere", "warm lighting"],
        },
        {
            "id": "body_detail", "display_name": "身体细节",
            "base_quality_tags": ["masterpiece", "best quality", "safe"],
            "rendering_style_tags": ["anime illustration"],
            "detail_tags": [
                "detailed skin", "shiny skin", "detailed breasts", "detailed navel",
                "detailed legs", "detailed fingers",
            ],
        },
        {
            "id": "glossy_wet", "display_name": "水光汗湿",
            "base_quality_tags": ["masterpiece", "best quality", "safe"],
            "rendering_style_tags": ["anime illustration"],
            "detail_tags": ["wet skin", "shiny skin", "sweat", "glistening"],
            "atmosphere_tags": ["dramatic lighting"],
        },
        {
            "id": "night_neon", "display_name": "夜景霓虹",
            "base_quality_tags": ["masterpiece", "best quality", "safe"],
            "rendering_style_tags": ["anime illustration", "vivid colors"],
            "atmosphere_tags": ["neon lights", "night", "cyberpunk atmosphere", "rim lighting"],
        },
        {
            "id": "dramatic_light", "display_name": "戏剧光影",
            "base_quality_tags": ["masterpiece", "best quality", "safe"],
            "rendering_style_tags": ["anime illustration"],
            "detail_tags": ["high contrast", "volumetric lighting"],
            "atmosphere_tags": ["dramatic lighting", "cinematic lighting", "god rays"],
        },
        {
            "id": "cinematic", "display_name": "电影质感",
            "base_quality_tags": ["masterpiece", "best quality", "safe"],
            "rendering_style_tags": ["cinematic", "anime illustration"],
            "detail_tags": ["film grain", "depth of field"],
            "atmosphere_tags": ["cinematic lighting", "atmospheric perspective"],
        },
        {
            "id": "sharp_focus", "display_name": "锐利清晰",
            "base_quality_tags": ["masterpiece", "best quality", "safe"],
            "rendering_style_tags": ["anime illustration"],
            "detail_tags": ["sharp focus", "highly detailed", "crisp lines", "clean lineart"],
        },
        {
            "id": "painterly", "display_name": "厚涂绘画",
            "base_quality_tags": ["masterpiece", "best quality", "safe"],
            "rendering_style_tags": ["painterly", "illustration"],
            "detail_tags": ["brush strokes", "textured skin", "rich colors"],
            "atmosphere_tags": ["artistic lighting"],
        },
        {
            "id": "flat_color", "display_name": "赛璐璐平涂",
            "base_quality_tags": ["masterpiece", "best quality", "safe"],
            "rendering_style_tags": ["cel shading", "anime coloring", "flat color"],
            "detail_tags": ["clean lineart", "vibrant colors"],
        },
        {
            "id": "dark_moody", "display_name": "暗黑情绪",
            "base_quality_tags": ["masterpiece", "best quality", "safe"],
            "rendering_style_tags": ["anime illustration"],
            "atmosphere_tags": ["dark atmosphere", "moody lighting", "low key lighting", "shadows"],
        },
        {
            "id": "sunrise_warm", "display_name": "暖金晨光",
            "base_quality_tags": ["masterpiece", "best quality", "safe"],
            "rendering_style_tags": ["anime illustration"],
            "detail_tags": ["golden hour", "warm highlights"],
            "atmosphere_tags": ["warm lighting", "soft morning light", "lens flare"],
        },
        {
            "id": "lingerie_focus", "display_name": "服饰质感",
            "base_quality_tags": ["masterpiece", "best quality", "safe"],
            "rendering_style_tags": ["anime illustration"],
            "detail_tags": [
                "detailed clothes", "fabric folds", "lace details", "sheer fabric",
                "clothing texture",
            ],
        },
        {
            "id": "action_dynamic", "display_name": "动态冲击",
            "base_quality_tags": ["masterpiece", "best quality", "safe"],
            "rendering_style_tags": ["anime illustration", "dynamic angle"],
            "detail_tags": ["motion lines", "speed lines", "dynamic pose"],
            "composition_tags": ["action shot"],
        },
        {
            "id": "intimate_close", "display_name": "亲密近景",
            "base_quality_tags": ["masterpiece", "best quality", "safe"],
            "rendering_style_tags": ["anime illustration"],
            "detail_tags": ["detailed face", "detailed eyes", "detailed skin", "shallow depth of field"],
            "atmosphere_tags": ["intimate atmosphere", "soft lighting"],
        },
        {
            "id": "uncensored_detail", "display_name": "无修正细节",
            "base_quality_tags": ["masterpiece", "best quality"],
            "rendering_style_tags": ["anime illustration"],
            "detail_tags": ["uncensored", "detailed skin", "anatomical detail"],
        },
    ]
    save(CFG / "quality_profiles.json", profiles)
    return len(profiles)


def main() -> None:
    n1 = expand_concepts()
    n2 = expand_tags()
    n3 = expand_lexicon()
    n4 = expand_quality_profiles()
    print(f"concepts={n1} tags={n2} lexicon={n3} quality_profiles={n4}")


if __name__ == "__main__":
    main()
