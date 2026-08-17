from anima_prompt_studio.services.tag_matcher import TagMatcher


def tags(result):
    return [x.tag for x in result]


def test_direct_and_chinese_synonym_matching():
    result = TagMatcher().match("a girl with white hair", "一个白发女孩")
    assert "white hair" in tags(result)
    assert next(x for x in result if x.tag == "white hair").source_type == "direct"


def test_white_hair_without_length_never_invents_colour_or_length():
    result = TagMatcher().match("a girl with white hair", "一个白发女孩")
    matched = set(tags(result))
    assert "white hair" in matched
    assert matched.isdisjoint({"blonde hair", "black hair", "brown hair", "short hair", "long hair", "very long hair"})


def test_excluded_tag_does_not_return():
    result = TagMatcher().match("white hair", excluded={"white hair"})
    assert "white hair" not in tags(result)


def test_locked_tag_always_returns():
    result = TagMatcher().match("", locked={"custom tag"})
    assert "custom tag" in tags(result)


def test_last_conflicting_hair_colour_wins():
    result = TagMatcher().match("white hair, but now black hair")
    assert "black hair" in tags(result)
    assert "white hair" not in tags(result)


def test_view_angle_does_not_match_horns():
    assert "horns" not in tags(TagMatcher().match("front three-quarter view", "全身侧前方视角"))


def test_explicit_horns_still_match():
    assert "horns" in tags(TagMatcher().match("a woman with horns", "头上长角的女人"))


def test_reverse_cowgirl_does_not_also_match_cowgirl():
    result = TagMatcher().match(
        "A nude girl sits on him reverse cowgirl.",
        "一个裸体女孩反骑乘，背对男孩坐在他身上",
    )
    matched = set(tags(result))
    assert "reverse cowgirl" in matched
    assert "cowgirl position" not in matched


def test_plain_cowgirl_still_matches():
    result = TagMatcher().match(
        "A nude girl in cowgirl position.",
        "一个裸体女孩女上位骑在男孩身上",
    )
    assert "cowgirl position" in tags(result)


def test_hanging_hand_does_not_match_fallen_down():
    result = TagMatcher().match(
        "A girl raised her skirt and her left hand fell down.",
        "一个女孩右手掀裙，左手自然垂下",
    )
    assert "fallen down" not in tags(result)
