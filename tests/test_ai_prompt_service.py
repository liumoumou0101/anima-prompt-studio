import io
import json
from email.message import Message
from urllib.error import HTTPError

import pytest

from anima_prompt_studio.services.ai_extract_service import AIExtractService, ExtractedPrompt
from anima_prompt_studio.services.ai_prompt_service import (
    AIAPIStyle,
    AIClient,
    AIEngineConfig,
    OPENCODE_GO_BASE_URL,
    opencode_go_model_label,
)
from anima_prompt_studio.services.multi_scope import MultiScopeService
from anima_prompt_studio.services.config_service import ConfigService
from anima_prompt_studio.services.novel_scene_compiler import NovelSceneCompiler
from anima_prompt_studio.services.prompt_compiler import PromptCompiler
from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio.services.remote.credential_store import CredentialStore, MemoryCredentialBackend


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def extracted_payload() -> dict:
    return {
        "summary_zh": "雨夜街道上的白发少女",
        "people_count": 1,
        "subject_mode": "character",
        "characters": [{
            "label": "少女",
            "identity": "",
            "appearance": ["白发", "红眼"],
            "body": [],
            "clothing": ["黑色风衣"],
            "expression": "微笑",
            "gaze": "看向镜头",
            "pose": "站立",
            "action": "右手撑伞，左脚踩在水坑边",
        }],
        "scene": {
            "location": "雨夜街道",
            "time": "夜晚",
            "weather": "下雨",
            "objects": ["霓虹灯", "水坑"],
            "lighting": "霓虹倒影",
            "atmosphere": "",
        },
        "camera": {
            "shot": "全身",
            "angle": "三分之四",
            "camera_height": "平视",
            "subject_position": "居中",
        },
        "negatives": ["文字"],
        "notes": [],
    }


@pytest.mark.parametrize(("model", "style", "suffix"), [
    ("mimo-v2.5", AIAPIStyle.CHAT_COMPLETIONS, "/chat/completions"),
    ("kimi-k3", AIAPIStyle.CHAT_COMPLETIONS, "/chat/completions"),
    ("grok-4.5", AIAPIStyle.RESPONSES, "/responses"),
    ("minimax-m3", AIAPIStyle.MESSAGES, "/messages"),
])
def test_opencode_go_auto_selects_each_official_api_shape(model, style, suffix):
    config = AIEngineConfig(provider_id="opencode_go", base_url=OPENCODE_GO_BASE_URL, model=model)
    assert config.resolved_style() == style
    assert config.endpoint() == OPENCODE_GO_BASE_URL + suffix


def test_chat_completions_thinking_is_off_by_default_and_can_be_enabled():
    captured = []

    def opener(request, timeout):
        captured.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse({"choices": [{"message": {"content": json.dumps(extracted_payload(), ensure_ascii=False)}}]})

    off_config = AIEngineConfig(provider_id="openai_compatible", base_url="https://example.test/v1", model="mimo-v2.5")
    AIClient(off_config, "secret", opener).complete_json("sys", "user")
    assert captured[0]["thinking"] == {"type": "disabled"}
    assert captured[0]["temperature"] == 0.1

    on_config = off_config.model_copy(update={"thinking_enabled": True})
    AIClient(on_config, "secret", opener).complete_json("sys", "user")
    assert captured[1]["thinking"] == {"type": "enabled"}
    assert "temperature" not in captured[1]


def test_responses_api_output_is_supported():
    payload = {
        "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(extracted_payload(), ensure_ascii=False)}]}]
    }
    client = AIClient(
        AIEngineConfig(provider_id="opencode_go", model="grok-4.5"),
        "key",
        lambda *_args, **_kwargs: FakeResponse(payload),
    )
    assert client.complete_json("sys", "user")["summary_zh"] == "雨夜街道上的白发少女"


def test_empty_content_falls_back_to_reasoning_content():
    payload = {
        "choices": [{
            "message": {
                "content": "",
                "reasoning_content": json.dumps(extracted_payload(), ensure_ascii=False),
            }
        }]
    }
    client = AIClient(
        AIEngineConfig(provider_id="opencode_go", model="mimo-v2.5"),
        "key",
        lambda *_args, **_kwargs: FakeResponse(payload),
    )
    assert client.complete_json("sys", "user")["people_count"] == 1


def test_opencode_go_model_catalog_can_refresh_from_models_endpoint():
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.method
        return FakeResponse({"object": "list", "data": [{"id": "mimo-v2.5"}, {"id": "glm-5.3"}]})

    client = AIClient(AIEngineConfig(model="mimo-v2.5"), "key", opener)
    assert client.list_models() == ["glm-5.3", "mimo-v2.5"]
    assert captured == {"url": OPENCODE_GO_BASE_URL + "/models", "method": "GET"}


def test_503_is_retried_then_succeeds():
    attempts = {"count": 0}
    sleeps = []

    def opener(request, timeout):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise HTTPError(
                "https://example.test/v1/chat/completions",
                503,
                "busy",
                hdrs=Message(),
                fp=io.BytesIO(b"busy"),
            )
        return FakeResponse({"choices": [{"message": {"content": json.dumps(extracted_payload(), ensure_ascii=False)}}]})

    client = AIClient(
        AIEngineConfig(provider_id="openai_compatible", base_url="https://example.test/v1", model="mimo-v2.5"),
        "key",
        opener,
        sleeper=sleeps.append,
    )
    assert client.complete_json("sys", "user")["summary_zh"].startswith("雨夜")
    assert attempts["count"] == 2
    assert sleeps == [1.5]


def test_remote_api_rejects_plain_http_but_local_api_is_allowed():
    with pytest.raises(ValueError, match="HTTPS"):
        AIEngineConfig(base_url="http://example.test/v1", model="example-model")
    config = AIEngineConfig(
        provider_id="openai_compatible",
        base_url="http://127.0.0.1:11434/v1",
        model="local-model",
    )
    assert config.endpoint() == "http://127.0.0.1:11434/v1/chat/completions"


def test_ai_api_key_uses_credential_backend_instead_of_sqlite():
    store = CredentialStore(MemoryCredentialBackend())
    store.save_ai_api_key("secret", "opencode_go")
    assert store.read_ai_api_key("opencode_go") == "secret"
    store.delete_ai_api_key("opencode_go")
    assert store.read_ai_api_key("opencode_go") == ""


def test_opencode_go_model_labels_distinguish_free_and_high_consumption_models():
    assert opencode_go_model_label("ox-alpha-free") == "★ 限时免费 · ox-alpha-free"
    assert opencode_go_model_label("kimi-k3") == "⚠ 较贵 / 高消耗 · kimi-k3"
    assert opencode_go_model_label("mimo-v2.5") == "mimo-v2.5"


class FakeStructuredAI:
    def __init__(self, payload):
        self.payload = payload
        self.request = None

    def complete_json(self, system, user):
        self.request = (system, json.loads(user))
        return self.payload


def test_extract_service_builds_compiler_friendly_chinese_brief():
    client = FakeStructuredAI(extracted_payload())
    result = AIExtractService().extract("小说里写：白发红眼少女撑着伞站在雨夜街道。", client)
    brief = result.to_chinese_brief()
    assert "白发" in brief and "右手撑伞" in brief
    assert "场景：雨夜街道" in brief
    assert "构图：全身" in brief
    assert "不要：文字" in brief
    assert "masterpiece" not in brief
    assert client.request[1]["source_text"].startswith("小说里写")


def test_extract_service_omits_unchecked_characters_from_brief():
    result = ExtractedPrompt.model_validate(extracted_payload())
    result.characters[0].included = False
    result.include_negatives = False
    brief = result.to_chinese_brief()
    assert "右手撑伞" not in brief
    assert "不要" not in brief
    assert "雨夜街道" in brief


def test_ai_extract_compiler_brief_is_compact_scoped_and_deduplicated():
    payload = extracted_payload()
    payload["summary_zh"] = "白发红眼少女在雨夜街道撑伞，右手撑伞，左脚踩水坑。"
    payload["characters"].append({
        "label": "后方男性",
        "identity": "男性",
        "appearance": ["未知发色", "未知眼色"],
        "body": [],
        "clothing": ["未指定"],
        "expression": "不明",
        "gaze": "视线不明",
        "pose": "站立",
        "action": "双手抱住少女腰部，抱住少女腰部，右手抬起她的左腿，站立",
    })
    payload["people_count"] = 2
    result = ExtractedPrompt.model_validate(payload)

    review = result.to_chinese_brief()
    compiler = result.to_compiler_brief()

    assert payload["summary_zh"] in review
    assert payload["summary_zh"] not in compiler
    assert compiler.startswith("两人。\n角色A：")
    assert "\n角色B：" in compiler
    assert "未知" not in compiler and "未指定" not in compiler and "不明" not in compiler
    assert compiler.count("抱住角色A腰部") == 1
    assert len(compiler) < len(review)


def test_ai_extract_compiler_brief_bounds_complex_three_character_scene():
    payload = extracted_payload()
    payload["characters"] = []
    for index in range(3):
        payload["characters"].append({
            "label": f"人物{index + 1}",
            "identity": "成年人物",
            "appearance": [f"特征{item}" for item in range(8)],
            "body": [f"体态{item}" for item in range(5)],
            "clothing": [f"服装{item}" for item in range(5)],
            "expression": "紧张",
            "gaze": "看向左侧",
            "pose": "站立",
            "action": "右手抓住木杖，左手扶住同伴肩膀，左脚踩住石阶，身体向前倾斜",
        })
    payload["people_count"] = 3
    result = ExtractedPrompt.model_validate(payload)

    compiler = result.to_compiler_brief()

    assert compiler.startswith("三人。")
    assert all(marker in compiler for marker in ("角色A：", "角色B：", "角色C："))
    assert len(compiler) <= 500


def test_ai_extract_compiler_brief_drops_pure_names_but_keeps_visual_roles():
    payload = extracted_payload()
    payload["characters"] = [
        {
            "label": "仁", "identity": "仁", "appearance": [], "body": [], "clothing": [],
            "expression": "", "gaze": "看向安雅", "pose": "站立", "action": "",
        },
        {
            "label": "安雅", "identity": "精灵女性", "appearance": ["长耳朵"], "body": [],
            "clothing": [], "expression": "", "gaze": "看向仁", "pose": "站立", "action": "",
        },
    ]
    payload["people_count"] = 2
    result = ExtractedPrompt.model_validate(payload)

    compiler = result.to_compiler_brief()

    assert "仁" not in compiler and "安雅" not in compiler
    assert "精灵女性" in compiler
    assert "看向角色B" in compiler and "看向角色A" in compiler
    assert "两人看向彼此。" in compiler
    assert compiler.startswith("两人。")
    assert MultiScopeService().build(compiler, 2) is None


def test_ai_extract_compiler_brief_preserves_balanced_role_parentheses():
    payload = extracted_payload()
    payload["characters"] = [{
        "label": "女魔导师（魅魔）",
        "identity": "女魔导师",
        "appearance": ["深红色长发"],
        "body": [],
        "clothing": ["长袍"],
        "expression": "",
        "gaze": "",
        "pose": "站立",
        "action": "双手抱树干",
    }]
    result = ExtractedPrompt.model_validate(payload)

    compiler = result.to_compiler_brief()

    assert "女魔导师（魅魔）" in compiler
    assert compiler.count("（") == compiler.count("）")


def test_ai_extract_explicit_rating_survives_compact_handoff():
    payload = extracted_payload()
    payload["content_rating"] = "explicit"
    result = ExtractedPrompt.model_validate(payload)

    compiler = result.to_compiler_brief()

    assert "内容：露骨性爱。" in compiler


def test_ai_extract_compiler_brief_normalizes_common_interior_scene_terms():
    payload = extracted_payload()
    payload["scene"]["location"] = "旅馆"
    payload["scene"]["lighting"] = "光暗"
    result = ExtractedPrompt.model_validate(payload)

    compiler = result.to_compiler_brief()

    assert "场景：旅馆室内" in compiler
    assert "昏暗光线" in compiler


def test_ai_extract_compiler_brief_avoids_legacy_window_for_outdoor_morning():
    payload = extracted_payload()
    payload["scene"]["location"] = "山谷瀑布旁断桥"
    payload["scene"]["time"] = "清晨时分"
    payload["scene"]["objects"] = ["瀑布", "水雾"]
    result = ExtractedPrompt.model_validate(payload)

    compiler = result.to_compiler_brief()

    assert "黎明" in compiler
    assert "清晨" not in compiler


def test_ai_extract_compiler_brief_turns_camera_negative_into_direct_gaze_rule():
    payload = extracted_payload()
    payload["negatives"] = ["文字", "水印", "人物看镜头"]
    result = ExtractedPrompt.model_validate(payload)

    compiler = result.to_compiler_brief()

    assert "不看镜头。" in compiler
    assert "不要：文字，水印。" in compiler
    assert "人物看镜头" not in compiler


def test_ai_extract_compiler_brief_binds_relative_person_aliases_to_roles():
    payload = extracted_payload()
    payload["characters"] = [
        {
            "label": "左侧游侠", "identity": "成年女性游侠", "appearance": [], "body": [],
            "clothing": [], "expression": "", "gaze": "看向右侧桥下人物", "pose": "单膝跪地",
            "action": "右手抓住右侧人物右手腕，用力后仰",
        },
        {
            "label": "右侧旅行者", "identity": "成年男性旅行者", "appearance": [], "body": [],
            "clothing": [], "expression": "", "gaze": "看向左侧人物", "pose": "双脚悬空",
            "action": "左手抓住断裂石沿",
        },
    ]
    payload["people_count"] = 2
    result = ExtractedPrompt.model_validate(payload)

    compiler = result.to_compiler_brief()

    assert "抓住角色B右手腕" in compiler
    assert "看向角色B" in compiler and "看向角色A" in compiler
    assert "右侧人物" not in compiler and "左侧人物" not in compiler


def test_ai_extract_compiler_brief_preserves_one_explicit_interaction_sentence():
    payload = extracted_payload()
    payload["characters"] = [
        {
            "label": "左侧游侠", "identity": "成年女性游侠", "appearance": [], "body": [],
            "clothing": [], "expression": "", "gaze": "", "pose": "单膝跪地", "action": "用力后仰",
        },
        {
            "label": "右侧旅行者", "identity": "成年男性旅行者", "appearance": [], "body": [],
            "clothing": [], "expression": "", "gaze": "", "pose": "双脚悬空", "action": "抓住石沿",
        },
    ]
    payload["people_count"] = 2
    payload["interaction_zh"] = "左侧游侠右手抓住右侧旅行者的右手腕并向上拉"
    result = ExtractedPrompt.model_validate(payload)

    compiler = result.to_compiler_brief()

    role_a = next(line for line in compiler.splitlines() if line.startswith("角色A："))
    assert "右手抓住角色B的右手腕并向上拉" in role_a
    assert "互动：" not in compiler


def test_ai_extract_compiler_brief_makes_ambiguous_hanging_pose_explicit():
    payload = extracted_payload()
    payload["characters"][0]["pose"] = "双脚悬在瀑布水雾上方"
    result = ExtractedPrompt.model_validate(payload)

    compiler = result.to_compiler_brief()

    assert "身体悬空" in compiler
    assert "双脚离开支撑面" in compiler


def test_ai_extract_compiler_brief_splits_nested_spatial_interaction_by_role():
    payload = extracted_payload()
    payload["characters"] = [
        {"label": "左侧游侠", "identity": "成年女性游侠", "action": "用力后仰"},
        {"label": "右侧旅行者", "identity": "成年男性旅行者", "pose": "双脚悬空"},
    ]
    payload["people_count"] = 2
    payload["interaction_zh"] = "左侧游侠右手抓住悬挂在桥下的右侧旅行者右手腕并向上拉"
    result = ExtractedPrompt.model_validate(payload)

    compiler = result.to_compiler_brief()

    role_a = next(line for line in compiler.splitlines() if line.startswith("角色A："))
    role_b = next(line for line in compiler.splitlines() if line.startswith("角色B："))
    assert "右手抓住角色B右手腕并向上拉" in role_a
    assert "悬挂在桥下" in role_b
    assert "抓住悬挂在桥下的角色B" not in compiler


def test_ai_extract_compiler_brief_removes_time_leaked_into_location():
    payload = extracted_payload()
    payload["scene"]["location"] = "清晨山谷瀑布旁断裂石桥"
    payload["scene"]["time"] = "清晨"
    result = ExtractedPrompt.model_validate(payload)

    compiler = result.to_compiler_brief()

    assert "场景：山谷瀑布旁断裂石桥，黎明" in compiler
    assert "清晨" not in compiler


def test_ai_extract_compiler_brief_keeps_atomic_landmark_inside_location():
    payload = extracted_payload()
    payload["scene"]["location"] = "山谷瀑布旁断裂石桥横跨深涧"
    payload["scene"]["objects"] = ["断裂石桥", "深涧", "瀑布", "水雾"]
    result = ExtractedPrompt.model_validate(payload)

    scene_line = next(
        line for line in result.to_compiler_brief().splitlines() if line.startswith("场景：")
    )

    assert scene_line.count("瀑布") == 2
    role_a = next(
        line for line in result.to_compiler_brief().splitlines() if line.startswith("中间人物：")
    )
    assert "背景是巨大瀑布" in role_a


def test_novel_assistant_reclassifies_accessory_and_recovers_explicit_footwear():
    payload = extracted_payload()
    payload["characters"][0]["clothing"] = [
        "洁白长裙", "复杂精致花纹", "银叶雕纹手镯"
    ]
    payload["characters"][0]["appearance"] = ["淡粉长发", "洁白皮肤"]
    payload["characters"][0]["gaze"] = ""
    payload["scene"]["lighting"] = "圣光笼罩"
    result = AIExtractService().extract(
        "公主穿洁白长裙，戴银叶雕纹手镯，高跟鞋踩在木地板上。",
        FakeStructuredAI(payload),
    )

    character = result.characters[0]
    compiler = result.to_compiler_brief()

    assert character.clothing == ["洁白长裙", "复杂精致花纹"]
    assert character.accessories == ["银叶雕纹手镯"]
    assert character.footwear == ["高跟鞋"]
    assert "粉色长发" in compiler and "淡粉" not in compiler
    assert "银叶雕纹手镯" in compiler and "高跟鞋" in compiler
    assert "柔和圣洁光芒" in compiler and "圣光笼罩" not in compiler
    assert "构图：全身" in compiler
    assert "不看镜头。" in compiler


def test_novel_assistant_keeps_explicit_viewer_gaze_and_camera_shot():
    payload = extracted_payload()
    payload["characters"][0]["footwear"] = ["高跟鞋"]
    payload["characters"][0]["gaze"] = "看向镜头"
    payload["camera"]["shot"] = "胸像"
    result = ExtractedPrompt.model_validate(payload)

    compiler = result.to_compiler_brief()

    assert "构图：胸像" in compiler
    assert "构图：全身" not in compiler
    assert "不看镜头" not in compiler


def test_novel_scene_direct_compiler_keeps_spatial_roles_out_of_legacy_mt():
    payload = extracted_payload()
    payload.update({
        "scene_type": "group",
        "key_event_zh": "左右两军隔着通道对峙",
        "spatial_layout_zh": "左侧银甲守卫，中间白发男子，右侧红袍士兵",
        "anima_prompt_en": (
            "A wide palace hall with two opposing armies across an open aisle. "
            "On the left, silver-armored guards face right. In the center, one tall "
            "white-haired man stands alone. On the right, red-robed soldiers face left. "
            "No one is looking at the viewer."
        ),
        "anima_negative_en": ["mixed faction colors"],
    })
    payload["characters"][0]["gaze"] = ""
    result = ExtractedPrompt.model_validate(payload)
    job = PromptJob(
        model_profile_id="anima_base_v1",
        generation_preset_id="quality",
        quality_profile_id="ornate_illustration",
    )

    NovelSceneCompiler().compile(job, result, PromptCompiler(ConfigService()))

    assert "lateral opposing composition" in job.positive_prompt
    assert "silver-armored guards face right" in job.positive_prompt
    assert "red-robed soldiers face left" in job.positive_prompt
    assert "looking at the viewer" not in job.positive_prompt.casefold()
    assert "team portrait" in job.negative_prompt
    assert "mixed faction colors" in job.negative_prompt
    assert job.prompt_origin == "ai_generated"
