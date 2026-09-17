from __future__ import annotations

from copy import deepcopy
import json

import pytest

from anima_prompt_studio_v3.prompt_assistant.services.completion_protocols import (
    ProtocolError,
    build_protocol_payload,
    parse_protocol_records,
    stream_is_done_line,
)


def response_message(text):
    return {"id": "msg_1", "type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}]}


def test_responses_payload_preserves_roles_images_and_output_limit_without_sampling():
    wire = [
        {"role": "system", "content": "Return JSON."},
        {"role": "assistant", "content": "Previous answer"},
        {"role": "user", "content": [{"type": "text", "text": "Describe"},
         {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,/9g=", "detail": "low"}}]},
    ]
    before = deepcopy(wire)
    payload = build_protocol_payload("responses", "gpt-5.6-luna", wire,
                                     {"reasoning": {"effort": "none"}},
                                     {"max_tokens": 4096, "temperature": 0.7, "top_p": 0.9})
    assert payload["input"] == [
        {"role": "system", "content": [{"type": "input_text", "text": "Return JSON."}]},
        {"role": "assistant", "content": [{"type": "output_text", "text": "Previous answer"}]},
        {"role": "user", "content": [{"type": "input_text", "text": "Describe"},
         {"type": "input_image", "image_url": "data:image/jpeg;base64,/9g=", "detail": "low"}]},
    ]
    assert payload["max_output_tokens"] == 4096
    assert payload["reasoning"] == {"effort": "none"}
    assert payload["model"] == "gpt-5.6-luna" and payload["stream"] is True
    assert not {"messages", "max_tokens", "temperature", "top_p"} & payload.keys()
    assert wire == before


def test_messages_payload_merges_system_and_converts_jpeg_without_mutating_controls():
    controls = {"thinking": {"type": "enabled"}}
    payload = build_protocol_payload("messages", "union-alpha", [
        {"role": "system", "content": "First rule"},
        {"role": "user", "content": [{"type": "text", "text": "Image"},
         {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,/9g="}}]},
        {"role": "system", "content": "Second rule"},
    ], controls, {})
    assert payload["system"] == "First rule\n\nSecond rule"
    assert payload["messages"] == [{"role": "user", "content": [
        {"type": "text", "text": "Image"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "/9g="}},
    ]}]
    assert payload["max_tokens"] == 8192
    assert payload["thinking"] == {"type": "enabled", "budget_tokens": 2048}
    assert controls == {"thinking": {"type": "enabled"}}


def test_messages_adaptive_does_not_receive_a_budget_and_honors_explicit_limit():
    payload = build_protocol_payload("messages", "minimax-m3", [{"role": "user", "content": "Hi"}],
                                     {"thinking": {"type": "adaptive"}}, {"max_tokens": 3000})
    assert payload["thinking"] == {"type": "adaptive"}
    assert payload["max_tokens"] == 3000


def test_responses_default_output_limit():
    assert build_protocol_payload("responses", "grok-4.6", [{"role": "user", "content": "Hi"}], {}, {})["max_output_tokens"] == 8192


def test_messages_rejects_unusable_image_instead_of_silently_dropping_it():
    with pytest.raises(ProtocolError):
        build_protocol_payload("messages", "union-alpha", [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "not-an-image"}},
        ]}], {}, {})


def test_responses_completed_snapshot_is_not_appended_to_streamed_text():
    records = [
        {"type": "response.created", "response": {"id": "resp_1", "status": "in_progress", "output": []}},
        {"type": "response.reasoning_summary_text.delta", "delta": "PRIVATE"},
        {"type": "response.output_text.delta", "output_index": 1, "content_index": 0, "delta": "Hello "},
        {"type": "response.output_text.delta", "output_index": 1, "content_index": 0, "delta": "world"},
        {"type": "response.output_text.done", "output_index": 1, "content_index": 0, "text": "Hello world"},
        {"type": "response.completed", "response": {"status": "completed", "error": None,
         "output": [{"type": "reasoning", "summary": [{"type": "summary_text", "text": "PRIVATE"}]},
                    response_message("Hello world")] }},
    ]
    assert parse_protocol_records("responses", records) == "Hello world"


def test_responses_non_streaming_json_reads_only_assistant_output_text():
    record = {"id": "resp_1", "object": "response", "status": "completed", "error": None,
              "output": [{"type": "reasoning", "content": [{"type": "reasoning_text", "text": "PRIVATE"}]},
                         response_message('<think>PRIVATE</think>{"ok":true}') ]}
    assert parse_protocol_records("responses", [record]) == '{"ok":true}'


def test_responses_delta_only_stream_requires_and_accepts_completed_event():
    records = [{"type": "response.output_text.delta", "output_index": 0, "content_index": 0, "delta": "OK"},
               {"type": "response.completed", "response": {"status": "completed", "output": []}}]
    assert parse_protocol_records("responses", records) == "OK"
    with pytest.raises(ProtocolError, match="未完成") as error:
        parse_protocol_records("responses", records[:-1])
    assert error.value.reason == "incomplete_response"


def test_responses_item_done_can_supply_text_without_delta_or_terminal_output_snapshot():
    records = [
        {"type": "response.output_item.done", "output_index": 0, "item": response_message("OK")},
        {"type": "response.completed", "response": {"status": "completed"}},
    ]
    assert parse_protocol_records("responses", records) == "OK"


@pytest.mark.parametrize("protocol,records", [
    ("responses", [{"type": "response.output_text.delta", "output_index": [], "delta": "SECRET"},
                   {"type": "response.completed", "response": {"status": "completed", "output": []}}]),
    ("messages", [{"type": "content_block_delta", "index": [], "delta": {"type": "text_delta", "text": "SECRET"}},
                  {"type": "message_stop"}]),
])
def test_malformed_event_indexes_raise_safe_protocol_errors(protocol, records):
    with pytest.raises(ProtocolError) as error:
        parse_protocol_records(protocol, records)
    assert error.value.reason == "invalid_response"
    assert "SECRET" not in str(error.value)


@pytest.mark.parametrize("record", [
    {"type": "response.failed", "response": {"status": "failed", "error": {"message": "SECRET"}}},
    {"type": "response.incomplete", "response": {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}},
    {"object": "response", "status": "incomplete", "incomplete_details": {"reason": "content_filter"}, "output": [response_message("partial")]},
    {"type": "error", "message": "SECRET", "code": "server_error"},
])
def test_responses_failed_or_incomplete_never_returns_partial_text_or_private_errors(record):
    with pytest.raises(ProtocolError) as error:
        parse_protocol_records("responses", [record])
    assert error.value.reason == "incomplete_response"
    assert "SECRET" not in str(error.value)


def test_messages_stream_ignores_thinking_and_does_not_duplicate_start_snapshot():
    records = [
        {"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant",
         "content": [{"type": "thinking", "thinking": "PRIVATE"}, {"type": "text", "text": "OK"}], "stop_reason": None}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "PRIVATE"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "PRIVATE"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "O"}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "K"}},
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 12}},
        {"type": "message_stop"},
    ]
    assert parse_protocol_records("messages", records) == "OK"
    with pytest.raises(ProtocolError) as error:
        parse_protocol_records("messages", records[:-1])
    assert error.value.reason == "incomplete_response"


def test_messages_content_block_start_prefix_is_kept_once():
    records = [
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": "Hello "}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "world"}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
        {"type": "message_stop"},
    ]
    assert parse_protocol_records("messages", records) == "Hello world"


def test_messages_non_streaming_json_ignores_reasoning_blocks():
    record = {"type": "message", "role": "assistant", "stop_reason": "end_turn", "content": [
        {"type": "thinking", "thinking": "PRIVATE"}, {"type": "text", "text": "OK"},
    ]}
    assert parse_protocol_records("messages", [record]) == "OK"


@pytest.mark.parametrize("stop_reason", ["max_tokens", "content_filter", "tool_use", "pause_turn", "refusal"])
def test_messages_truncated_or_non_final_stop_reason_fails(stop_reason):
    records = [{"type": "message", "role": "assistant", "stop_reason": stop_reason,
                "content": [{"type": "text", "text": "partial"}]}]
    with pytest.raises(ProtocolError) as error:
        parse_protocol_records("messages", records)
    assert error.value.reason == "incomplete_response"


@pytest.mark.parametrize("protocol,record", [
    ("messages", {"type": "error", "error": {"type": "overloaded_error", "message": "SECRET"}}),
    ("responses", {"type": "response.completed", "response": {"status": "completed", "output": []}}),
    ("messages", {"type": "message", "role": "assistant", "content": [{"type": "thinking", "thinking": "PRIVATE"}], "stop_reason": "end_turn"}),
])
def test_errors_and_thinking_only_output_never_become_success(protocol, record):
    with pytest.raises(ProtocolError) as error:
        parse_protocol_records(protocol, [record])
    assert "SECRET" not in str(error.value) and "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("protocol,event", [
    ("responses", "response.completed"), ("responses", "response.failed"),
    ("responses", "response.incomplete"), ("responses", "error"),
    ("messages", "message_stop"), ("messages", "error"),
])
def test_terminal_sse_data_is_detected_only_after_a_split_line_is_reassembled(protocol, event):
    line = b"data: " + json.dumps({"type": event}).encode() + b"\r\n"
    chunks = [line[:12], line[12:21], line[21:]]
    assert not stream_is_done_line(chunks[0], protocol)
    assert not stream_is_done_line(b"event: " + event.encode(), protocol)
    assert stream_is_done_line(b"".join(chunks), protocol)


@pytest.mark.parametrize("protocol", ["messages", "responses"])
def test_non_terminal_and_done_sentinel_cannot_replace_required_protocol_termination(protocol):
    assert not stream_is_done_line(b'data: {"type":"ping"}', protocol)
    assert not stream_is_done_line(b"data: [DONE]", protocol)
    assert not stream_is_done_line(b'data: {"type":', protocol)


def test_chat_compatibility_reads_content_but_not_reasoning():
    assert stream_is_done_line(b"data: [DONE]", "chat")
    assert parse_protocol_records("chat", [{"choices": [{"message": {"content": "OK", "reasoning": "PRIVATE"},
                                                               "finish_reason": "stop"}]}]) == "OK"
