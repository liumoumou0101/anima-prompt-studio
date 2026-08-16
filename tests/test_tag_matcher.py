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
