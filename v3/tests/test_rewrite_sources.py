"""Source provenance for a rewrite, independent of model interpretation."""

from copy import deepcopy

from anima_prompt_studio_v3.core.requirements import Requirements, dump
from anima_prompt_studio_v3.core.rewrite_sources import build_rewrite_sources


def empty_requirements():
    return dump(Requirements.empty())


def by_path(entries):
    return {item["path"]: item["value"] for item in entries}


def test_visible_prompt_is_required_and_unlocked_prose_is_previous_context():
    requirements = empty_requirements()
    requirements["layers"]["subject"]["text"] = "旧蓝外套"
    requirements["layers"]["exclusions"]["global"] = ["帽子"]
    current = {"positive": "person in a red coat", "negative": "no text"}

    result = build_rewrite_sources(requirements, current, visible_prompt=True,
                                   previous_manual_tags=[])

    assert result["authority"] == "visible_prompt"
    assert by_path(result["required"]) == {
        "compiled.positive": "person in a red coat",
        "compiled.negative": "no text",
    }
    assert by_path(result["previous_context"]) == {
        "requirements.layers.subject.text": "旧蓝外套",
        "requirements.layers.exclusions.global": ["帽子"],
    }
    assert result["superseded"] == []


def test_locked_content_stays_required_under_visible_prompt():
    requirements = empty_requirements()
    requirements["layers"]["style"].update({"text": "平涂", "medium": "插画", "locked": True})
    requirements["layers"]["composition"].update({"shot": "全身", "locked": True})
    requirements["layers"]["exclusions"].update({"global": ["帽子"], "locked": True})

    result = build_rewrite_sources(requirements, {"positive": "full body illustration"},
                                   visible_prompt=True, previous_manual_tags=[])
    required = by_path(result["required"])
    assert required["requirements.layers.style.text"] == "平涂"
    assert required["requirements.layers.style.medium"] == "插画"
    assert required["requirements.layers.composition.shot"] == "全身"
    assert required["requirements.layers.exclusions.global"] == ["帽子"]
    assert "requirements.layers.style.text" not in by_path(result["previous_context"])


def test_without_visible_prompt_all_current_content_is_required():
    requirements = empty_requirements()
    requirements["layers"]["subject"]["text"] = "两人"
    requirements["layers"]["lighting"]["text"] = "月光"
    requirements["layers"]["exclusions"]["scoped"] = [{"target": "左边人物", "concept": "帽子"}]
    current = {"positive": "two people in moonlight", "negative": ""}

    result = build_rewrite_sources(requirements, current, visible_prompt=False,
                                   previous_manual_tags=[])
    assert result["authority"] == "requirements"
    assert by_path(result["required"]) == {
        "requirements.layers.subject.text": "两人",
        "requirements.layers.lighting.text": "月光",
        "requirements.layers.exclusions.scoped": [{"target": "左边人物", "concept": "帽子"}],
    }
    assert by_path(result["previous_context"]) == {"compiled.positive": "two people in moonlight"}


def test_cleared_and_replaced_scene_controls_supersede_old_compilation():
    requirements = empty_requirements()
    requirements["layers"]["composition"]["design"] = {
        "shot": None, "camera": {"value": "俯视", "source": "user"},
    }
    requirements["layers"]["lighting"]["mood"] = None
    current = {"scene_intent": {
        "shot": {"value": "半身", "source": "user"},
        "camera": {"value": "平视", "source": "user"},
        "mood": {"value": "阴郁", "source": "user"},
    }}

    result = build_rewrite_sources(requirements, current, visible_prompt=False,
                                   previous_manual_tags=[])
    assert by_path(result["required"]) == {
        "requirements.layers.composition.design.camera": {"value": "俯视", "source": "user"},
    }
    assert by_path(result["superseded"]) == {
        "compiled.scene_intent.shot": {"value": "半身", "source": "user"},
        "compiled.scene_intent.camera": {"value": "平视", "source": "user"},
        "compiled.scene_intent.mood": {"value": "阴郁", "source": "user"},
    }


def test_previous_manual_tags_use_compiler_normalization_before_superseding():
    requirements = empty_requirements()
    requirements["layers"]["subject"]["general_tags"] = ["Foo(Bar)"]
    requirements["layers"]["style"]["manual_artist_tags"] = ["Artist_Name"]
    previous = ["foo\\(bar\\)", "@artist name", "removed tag"]

    result = build_rewrite_sources(requirements, None, visible_prompt=False,
                                   previous_manual_tags=previous)
    assert by_path(result["required"]) == {
        "requirements.layers.subject.general_tags": ["Foo(Bar)"],
        "requirements.layers.style.manual_artist_tags": ["Artist_Name"],
    }
    assert by_path(result["superseded"]) == {"previous_manual_tags[2]": "removed tag"}


def test_all_declared_sources_are_listed_without_rewriting_values():
    requirements = empty_requirements()
    layers = requirements["layers"]
    layers["subject"].update({"text": "不要人物", "character_tags": ["角色甲"],
                              "series_tags": ["系列甲"], "general_tags": ["hand_tag"]})
    layers["style"].update({"text": "平涂", "medium": "动漫", "artists": ["画师甲"],
                            "manual_artist_tags": ["@artist_b"]})
    layers["lighting"]["mood"] = {"value": "宁静", "source": "user"}
    layers["composition"]["design"] = {
        "shot": {"value": "全身", "source": "user"},
        "layout": {"value": "主体居中", "source": "user"},
        "camera": {"value": "俯视", "source": "user"},
        "gaze": {"value": "远方", "source": "user", "target": "角色甲"},
    }
    requirements["loras"] = [{"logical_id": "one", "file_name": "private.safetensors",
                              "trigger_words": ["magic word"]}]
    requirements["prompt_locks"] = [{"target": "negative", "text": "no watermark"}]
    before = deepcopy(requirements)

    result = build_rewrite_sources(requirements, None, visible_prompt=True,
                                   previous_manual_tags=[])
    required = by_path(result["required"])
    assert required == {
        "requirements.layers.subject.character_tags": ["角色甲"],
        "requirements.layers.subject.series_tags": ["系列甲"],
        "requirements.layers.subject.general_tags": ["hand_tag"],
        "requirements.layers.style.artists": ["画师甲"],
        "requirements.layers.style.manual_artist_tags": ["@artist_b"],
        "requirements.layers.lighting.mood": {"value": "宁静", "source": "user"},
        "requirements.layers.composition.design.shot": {"value": "全身", "source": "user"},
        "requirements.layers.composition.design.layout": {"value": "主体居中", "source": "user"},
        "requirements.layers.composition.design.camera": {"value": "俯视", "source": "user"},
        "requirements.layers.composition.design.gaze": {"value": "远方", "source": "user", "target": "角色甲"},
        "requirements.loras[0].trigger_words": ["magic word"],
        "requirements.prompt_locks[0]": {"target": "negative", "text": "no watermark"},
    }
    assert by_path(result["previous_context"]) == {
        "requirements.layers.subject.text": "不要人物",
        "requirements.layers.style.text": "平涂",
        "requirements.layers.style.medium": "动漫",
    }
    assert requirements == before
