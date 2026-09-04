from __future__ import annotations

from anima_prompt_studio_v3.api.app import (
    _LocalExclusionEvidence,
    _LocalIndexMatch,
    _split_local_natural_evidence,
)
from anima_prompt_studio_v3.core.composition import (
    CHIP_BY_TAG,
    COMPOSITION_PRESETS,
    auto_exclude_gaze_spans,
    axis_of,
    build_composition_palette,
    chip_note,
    clothing_crop_needed,
    coerce_selected_composition,
    composition_phrase_occupiers,
    composition_preset_snapshots,
    filter_weak_meta_matches,
    match_composition_preset,
    positive_composition_hints,
    prior_risk_notes,
    strip_focus_leftover_tags,
)


def test_splitter_turns_do_not_look_at_camera_into_exclusion_content() -> None:
    evidence = _split_local_natural_evidence("女仆，不要看镜头")
    assert evidence.exclusions[0].text == "看镜头"
    spans = auto_exclude_gaze_spans("女仆，不要看镜头", [(item.text, item.start, item.end) for item in evidence.exclusions])
    assert [item.canonical_tag for item in spans] == ["looking_at_viewer"]


def test_weak_meta_matches_are_dropped() -> None:
    matches = [
        _LocalIndexMatch("构图", "source", "watermark", "cn_term", 10, 2, 4),
        _LocalIndexMatch("全身", "source", "full_body", "cn_name", 100, 0, 2),
    ]
    kept = filter_weak_meta_matches(matches)
    assert [item.canonical_tag for item in kept] == ["full_body"]


def test_close_up_strips_pussy_focus_and_drops_headshot() -> None:
    leftover = ["pussy_focus", "ass_focus", "headshot", "clear_insertion"]
    groups = {
        "pussy_focus": set(),
        "ass_focus": {"focus_tags"},
        "headshot": set(),
        "clear_insertion": set(),
    }
    assert strip_focus_leftover_tags("close-up", leftover, groups) == []


def test_from_above_still_keeps_looking_down() -> None:
    leftover = ["looking_down"]
    kept = strip_focus_leftover_tags("from_above", leftover, {"looking_down": set()})
    assert kept == ["looking_down"]


def test_clothing_crop_and_gaze_prior_notes() -> None:
    assert clothing_crop_needed({"white_thighhighs", "maid"}) is True
    assert clothing_crop_needed({"white_thighhighs", "full_body"}) is False
    notes = prior_risk_notes(
        gaze_present=False,
        looking_away=False,
        looking_at_viewer_excluded=True,
        crop_needed=True,
    )
    assert any("看向画外" in note for note in notes)
    assert any("下装" in note or "膝上" in note for note in notes)


def test_palette_does_not_mark_source_exact_as_selected_tags() -> None:
    palette = build_composition_palette(
        confirmed_tags={"full_body"},
        selected_tags=[],
        excluded_tags={"looking_at_viewer"},
        hinted_tags=set(),
        crop_needed=False,
    )
    by_tag = {item["canonical_tag"]: item for item in palette}
    assert by_tag["full_body"]["state"] == "confirmed"
    assert by_tag["looking_at_viewer"]["state"] == "excluded"
    assert by_tag["looking_away"]["state"] == "suggested"
    assert "仅把" in by_tag["looking_away"]["reason"] or "打不破" in by_tag["looking_away"]["reason"]


def test_selected_chip_note_is_chinese_and_specific() -> None:
    assert "大腿" in chip_note("cowboy_shot", "selected")
    assert "拍扁" in chip_note("full_body", "selected")
    assert "打不破" in chip_note("looking_away", "selected")


def test_coerce_keeps_last_shot_tag() -> None:
    assert coerce_selected_composition(["maid", "full_body", "cowboy_shot"]) == ["maid", "cowboy_shot"]


def test_composition_presets_are_closed_set_and_one_tag_per_axis() -> None:
    ids = [preset.id for preset in COMPOSITION_PRESETS]
    assert ids[0] == "none"
    assert COMPOSITION_PRESETS[0].tags == ()
    assert len(ids) == len(set(ids))
    for preset in COMPOSITION_PRESETS:
        axes = [axis_of(tag) for tag in preset.tags]
        assert all(tag in CHIP_BY_TAG for tag in preset.tags)
        assert None not in axes
        assert len(axes) == len(set(axes))
    snapshots = composition_preset_snapshots()
    assert any(item["id"] == "cowboy_viewer" and item["tags"] == ["cowboy_shot", "looking_at_viewer"] for item in snapshots)
    assert match_composition_preset({"cowboy_shot", "looking_at_viewer"}) == "cowboy_viewer"
    assert match_composition_preset(set()) == "none"
    assert match_composition_preset({"cowboy_shot", "from_behind"}) == "custom"


def test_positive_look_at_camera_is_hint_not_exclude() -> None:
    hinted = positive_composition_hints("女仆看镜头", set(), set())
    assert hinted["looking_at_viewer"] == "gaze"
    occupiers = composition_phrase_occupiers("女仆看镜头", [])
    assert any(item.text == "看镜头" for item in occupiers)
