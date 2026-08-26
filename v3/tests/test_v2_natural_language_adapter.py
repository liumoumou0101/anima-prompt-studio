from __future__ import annotations

from typing import Any

import pytest

from anima_prompt_studio_v3.adapters.v2 import (
    IntentParserUnavailableError,
    V2NaturalLanguageIntentAdapter,
)
from anima_prompt_studio_v3.domain import IntentElementType, IntentState, ProvenanceKind


class FakeExtractClient:
    name = "Fake V2 Extract"

    def complete_json(self, _system: str, _user: str) -> dict[str, Any]:
        return extraction_payload()


def extraction_payload() -> dict[str, Any]:
    return {
        "summary_zh": "雨夜街道上的白发少女",
        "people_count": 1,
        "subject_mode": "character",
        "content_rating": "safe",
        "scene_type": "portrait",
        "interaction_zh": "少女握住伞柄",
        "key_event_zh": "雨滴从伞沿落下",
        "spatial_layout_zh": "少女站在画面中央",
        "anima_prompt_en": "A white-haired girl stands beneath an umbrella on a neon-lit rainy street.",
        "anima_negative_en": ["text", "watermark"],
        "characters": [{
            "label": "少女",
            "identity": "年轻女性",
            "appearance": ["白发", "红眼"],
            "body": [],
            "clothing": ["黑色风衣", "银叶手镯", "高跟鞋"],
            "expression": "微笑",
            "gaze": "看向镜头",
            "pose": "站立",
            "action": "右手撑伞",
        }],
        "scene": {
            "location": "雨夜街道",
            "time": "夜晚",
            "weather": "下雨",
            "objects": ["霓虹灯", "水坑"],
            "lighting": "霓虹倒影",
            "atmosphere": "安静",
        },
        "camera": {
            "shot": "全身",
            "angle": "三分之四",
            "camera_height": "平视",
            "subject_position": "居中",
        },
        "negatives": ["文字"],
        "notes": ["请检查手部动作"],
    }


def test_v2_extraction_maps_to_reviewable_v3_intent_without_compiling_prompt() -> None:
    parsed = V2NaturalLanguageIntentAdapter(FakeExtractClient()).parse(
        "白发少女在雨夜街道撑伞，佩戴银叶手镯和高跟鞋。"
    )

    intent = parsed.intent
    by_text = {element.original_text: element for element in intent.graph.elements}
    assert by_text["年轻女性"].type == IntentElementType.CHARACTER
    assert by_text["白发"].type == IntentElementType.APPEARANCE
    assert by_text["黑色风衣"].type == IntentElementType.CLOTHING
    assert by_text["银叶手镯"].type == IntentElementType.CLOTHING
    assert by_text["高跟鞋"].type == IntentElementType.CLOTHING
    assert by_text["少女握住伞柄"].type == IntentElementType.RELATION
    assert by_text["雨夜街道"].type == IntentElementType.SCENE
    assert by_text["霓虹灯"].type == IntentElementType.OBJECT
    assert by_text["全身"].type == IntentElementType.COMPOSITION
    assert by_text["文字"].state == IntentState.EXCLUDED
    assert all(element.provenance.kind == ProvenanceKind.SEMANTIC for element in by_text.values())
    assert intent.scene_plan_en == (
        "A white-haired girl stands beneath an umbrella on a neon-lit rainy street"
    )
    assert intent.scene_negative_en == ["text", "watermark"]
    assert {warning.code for warning in intent.warnings} == {
        "ai_extraction_requires_review",
        "extractor_note",
    }
    assert parsed.parser_name == "Fake V2 Extract"


def test_unconfigured_v2_parser_fails_before_extraction() -> None:
    parser = V2NaturalLanguageIntentAdapter(None)
    assert parser.available is False
    with pytest.raises(IntentParserUnavailableError, match="API Key"):
        parser.parse("白发少女")
