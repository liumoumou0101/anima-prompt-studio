"""Pure request/response adapters for structured completion protocols."""
from __future__ import annotations

from copy import deepcopy
import json
import re

from .thinking_filter import postprocess_model_output


_TERMINAL_EVENTS = {
    "responses": {"response.completed", "response.failed", "response.incomplete", "error"},
    "messages": {"message_stop", "error"},
}


class ProtocolError(RuntimeError):
    """Safe error for the transport to translate without exposing upstream data."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def _invalid():
    raise ProtocolError("invalid_response", "LLM 协议格式不受支持。")


def _incomplete():
    raise ProtocolError("incomplete_response", "LLM 返回被截断或未完成。")


def _text(value):
    if not isinstance(value, str):
        _invalid()
    return value


def _index(record, key="index"):
    value = record.get(key, 0)
    if type(value) is not int or value < 0:
        _invalid()
    return value


def _blocks(content):
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if not isinstance(content, list) or any(not isinstance(part, dict) for part in content):
        _invalid()
    return content


def _image_url(part):
    image = part.get("image_url")
    if not isinstance(image, dict) or not isinstance(image.get("url"), str):
        _invalid()
    return image


def _message_content(content):
    result = []
    for part in _blocks(content):
        if part.get("type") == "text":
            result.append({"type": "text", "text": _text(part.get("text"))})
        elif part.get("type") == "image_url":
            url = _image_url(part)["url"]
            match = re.fullmatch(r"data:(image/(?:jpeg|png|gif|webp));base64,([A-Za-z0-9+/]+={0,2})", url)
            if match:
                source = {"type": "base64", "media_type": match[1], "data": match[2]}
            elif url.startswith(("https://", "http://")):
                source = {"type": "url", "url": url}
            else:
                _invalid()
            result.append({"type": "image", "source": source})
        else:
            _invalid()
    return result


def _response_content(content, role):
    result = []
    for part in _blocks(content):
        if part.get("type") == "text":
            result.append({"type": "output_text" if role == "assistant" else "input_text",
                           "text": _text(part.get("text"))})
        elif part.get("type") == "image_url" and role == "user":
            image = _image_url(part)
            result.append({"type": "input_image", "image_url": image["url"],
                           **({"detail": image["detail"]} if "detail" in image else {})})
        else:
            _invalid()
    return result


def _token_limit(advanced, key):
    value = next((advanced[name] for name in (key, "max_completion_tokens", "max_tokens")
                  if advanced.get(name) is not None), 8192)
    if type(value) is not int or value <= 0:
        _invalid()
    return value


def build_protocol_payload(protocol, model, wire_messages, controls, advanced):
    """Convert the existing Chat-style wire messages without changing the inputs.

    Controls must already use the selected protocol's field names. Responses
    callers currently target reasoning models, so optional sampling is omitted.
    """
    if protocol not in {"chat", "messages", "responses"}:
        _invalid()
    payload = deepcopy(controls)
    payload.update({"model": model, "stream": True})
    if protocol == "chat":
        payload["messages"] = deepcopy(wire_messages)
        payload.update({key: advanced[key] for key in ("temperature", "top_p", "max_tokens", "max_completion_tokens")
                        if key in advanced})
        return payload
    converted, system = [], []
    for message in wire_messages:
        role = message.get("role")
        if role not in {"system", "user", "assistant"}:
            _invalid()
        if protocol == "messages" and role == "system":
            parts = _blocks(message.get("content"))
            if any(part.get("type") != "text" for part in parts):
                _invalid()
            system.append("\n".join(_text(part.get("text")) for part in parts))
            continue
        content = (_message_content(message.get("content")) if protocol == "messages"
                   else _response_content(message.get("content"), role))
        converted.append({"role": role, "content": content})
    if protocol == "responses":
        payload.update({"input": converted, "max_output_tokens": _token_limit(advanced, "max_output_tokens")})
    else:
        payload.update({"messages": converted, "max_tokens": _token_limit(advanced, "max_tokens")})
        if system:
            payload["system"] = "\n\n".join(system)
        payload.update({key: advanced[key] for key in ("temperature", "top_p") if key in advanced})
        thinking = payload.get("thinking", {})
        if isinstance(thinking, dict) and thinking.get("type") == "enabled":
            thinking.setdefault("budget_tokens", min(2048, payload["max_tokens"] - 1))
            budget = thinking["budget_tokens"]
            if type(budget) is not int or not 1024 <= budget < payload["max_tokens"]:
                raise ProtocolError("invalid_response", "思考预算必须至少为 1024，且低于最大输出 token 数。")
    return payload


def _response_output(output):
    if not isinstance(output, list):
        _invalid()
    parts = []
    for item in output:
        if not isinstance(item, dict):
            _invalid()
        if item.get("type") != "message" or item.get("role", "assistant") != "assistant":
            continue
        if item.get("status") in {"incomplete", "failed", "in_progress"}:
            _incomplete()
        for part in _blocks(item.get("content", [])):
            if part.get("type") == "output_text":
                parts.append(_text(part.get("text")))
    return "".join(parts)


def _check_response(response):
    if not isinstance(response, dict):
        _invalid()
    if response.get("error") or response.get("status") in {"failed", "incomplete", "cancelled"}:
        _incomplete()
    if response.get("incomplete_details"):
        _incomplete()


def _parse_responses(records):
    deltas, snapshots = {}, {}
    completed = False
    final_text = ""
    for record in records:
        kind = record.get("type", "")
        if record.get("error") or kind in {"error", "response.failed", "response.incomplete"}:
            _incomplete()
        if kind == "response.output_text.delta":
            key = (_index(record, "output_index"), _index(record, "content_index"))
            deltas.setdefault(key, []).append(_text(record.get("delta")))
        elif kind == "response.output_text.done":
            key = (_index(record, "output_index"), _index(record, "content_index"))
            snapshots[key] = _text(record.get("text"))
        elif kind == "response.output_item.done":
            item, index = record.get("item"), _index(record, "output_index")
            _response_output([item])
            if item.get("type") == "message" and item.get("role", "assistant") == "assistant":
                for content_index, part in enumerate(item.get("content", [])):
                    if part.get("type") == "output_text":
                        snapshots[(index, content_index)] = _text(part.get("text"))
        elif kind == "response.completed":
            response = record.get("response", {})
            _check_response(response)
            if response.get("status", "completed") != "completed":
                _incomplete()
            final_text = _response_output(response.get("output", []))
            completed = True
        elif record.get("object") == "response" or ("status" in record and "output" in record):
            _check_response(record)
            if record.get("status") != "completed":
                _incomplete()
            final_text = _response_output(record.get("output", []))
            completed = True
    if not completed:
        _incomplete()
    # The terminal snapshot is authoritative; deltas and *_done are alternatives.
    if final_text:
        return final_text
    return "".join(snapshots[key] if key in snapshots else "".join(deltas[key])
                   for key in sorted(deltas.keys() | snapshots.keys()))


def _check_stop(reason):
    if reason is not None and reason not in {"end_turn", "stop_sequence", "stop"}:
        _incomplete()


def _parse_messages(records):
    seeds, starts, deltas, block_types = {}, {}, {}, {}
    completed = False
    final_text = None
    for record in records:
        kind = record.get("type", "")
        if record.get("error") or kind == "error":
            _incomplete()
        if kind == "message":
            _check_stop(record.get("stop_reason"))
            if not record.get("stop_reason"):
                _incomplete()
            final_text = "".join(_text(part.get("text")) for part in _blocks(record.get("content", []))
                                 if part.get("type") == "text")
            completed = True
        elif kind == "message_start":
            message = record.get("message", {})
            if not isinstance(message, dict):
                _invalid()
            _check_stop(message.get("stop_reason"))
            for index, part in enumerate(_blocks(message.get("content", []))):
                block_types[index] = part.get("type")
                if part.get("type") == "text":
                    seeds[index] = _text(part.get("text"))
        elif kind == "content_block_start":
            index, block = _index(record), record.get("content_block", {})
            if not isinstance(block, dict):
                _invalid()
            block_types[index] = block.get("type")
            if block.get("type") == "text":
                starts[index] = _text(block.get("text", ""))
        elif kind == "content_block_delta":
            index, delta = _index(record), record.get("delta", {})
            if not isinstance(delta, dict):
                _invalid()
            if delta.get("type") == "text_delta" and block_types.get(index, "text") == "text":
                deltas.setdefault(index, []).append(_text(delta.get("text")))
        elif kind == "message_delta":
            delta = record.get("delta", {})
            if not isinstance(delta, dict):
                _invalid()
            _check_stop(delta.get("stop_reason"))
        elif kind == "message_stop":
            completed = True
    if not completed:
        _incomplete()
    if final_text is not None:
        return final_text
    return "".join(starts.get(index, "") + "".join(deltas[index]) if index in deltas
                   else starts.get(index, seeds.get(index, ""))
                   for index in sorted(seeds.keys() | starts.keys() | deltas.keys()))


def _parse_chat(records):
    parts, completed = [], False
    for record in records:
        if record.get("error"):
            _incomplete()
        choices = record.get("choices", [])
        if not isinstance(choices, list):
            _invalid()
        if not choices:
            continue
        choice = choices[0]
        if not isinstance(choice, dict):
            _invalid()
        reason = choice.get("finish_reason")
        _check_stop(reason)
        completed = completed or reason == "stop"
        message = choice.get("delta", choice.get("message", {}))
        if not isinstance(message, dict):
            _invalid()
        if message.get("content") is not None:
            parts.append(_text(message["content"]))
    if not completed:
        _incomplete()
    return "".join(parts)


def parse_protocol_records(protocol, records):
    """Read decoded JSON bodies/SSE data records, requiring explicit completion.

    Only answer text is read. Provider errors are replaced with fixed messages,
    and reasoning blocks, summaries, signatures, and metadata are never returned.
    """
    if isinstance(records, dict):
        records = [records]
    records = list(records)
    if any(not isinstance(record, dict) for record in records):
        _invalid()
    parser = {"responses": _parse_responses, "messages": _parse_messages, "chat": _parse_chat}.get(protocol)
    if parser is None:
        _invalid()
    valid, text = postprocess_model_output(parser(records), filter_thinking_output=True)
    if not valid:
        raise ProtocolError("empty_response", "LLM 未返回有效内容。")
    return text


def stream_is_done_line(line: bytes, protocol: str) -> bool:
    """Inspect one reassembled SSE data line, never the preceding event header."""
    line = line.strip()
    if not line.startswith(b"data:"):
        return False
    data = line[5:].strip()
    if protocol == "chat":
        return data == b"[DONE]"
    try:
        record = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return False
    return isinstance(record, dict) and record.get("type") in _TERMINAL_EVENTS.get(protocol, set())
