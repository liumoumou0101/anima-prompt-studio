from anima_prompt_studio.services.enhancer import PromptEnhancer


def test_action_and_scene_enhancement():
    items = PromptEnhancer().enhance("清晨坐在桌边，双腿垂下")
    ids = {x.id for x in items}
    assert "table_dangling" in ids
    assert "morning" in ids


def test_strong_emotion_disables_weak_default():
    items = PromptEnhancer().enhance("她悲伤地坐在窗边")
    assert "weak_emotion" not in {x.id for x in items}

