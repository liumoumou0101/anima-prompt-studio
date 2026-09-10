"""Bounded, non-retrying structured completion transport for workbench tasks.

Legacy expansion keeps its existing transport. This path never logs upstream
response bodies or retries a possibly chargeable request automatically.
"""
from __future__ import annotations

import asyncio
import base64
from copy import deepcopy
import json
import httpx
from urllib.parse import urlsplit

from .core import HTTPClientPool
from .openai_base import OpenAICompatibleService
from .thinking_control import build_thinking_suppression, should_append_no_thinking_instruction, requires_glm_thinking
from .thinking_filter import postprocess_model_output
from ...core.requirements import WorkbenchError


class CompletionError(RuntimeError):
    def __init__(self, message: str, *, reason: str = "invalid_response", upstream_status: int | None = None):
        super().__init__(message)
        self.reason = reason if reason in {"thinking_disable_unsupported", "upstream_http_error", "transport_error", "invalid_response", "response_too_large", "incomplete_response", "empty_response"} else "invalid_response"
        self.upstream_status = upstream_status if type(upstream_status) is int and 100 <= upstream_status <= 599 else None

    @property
    def safe_details(self):
        return {"reason": self.reason, **({"upstream_status": self.upstream_status} if self.upstream_status else {})}


async def complete(config, service, *, messages, images=None, disable_thinking=True,
                   timeout_s=120.0, task="rewrite"):
    if task not in {"rewrite", "ingest", "prompt_ingest", "probe"} or not 0 < timeout_s <= 120:
        raise ValueError("无效的 LLM 任务或超时。")
    if not messages or any(message.get("role") not in {"system", "user", "assistant"}
                           or not isinstance(message.get("content"), str) for message in messages):
        raise ValueError("complete 只接收文本消息与独立 images。")
    vision = bool(service.get("supports_vision", False))
    if images and (task != "ingest" or not vision):
        raise ValueError("当前任务或服务不支持图像输入。")
    if images and (len(images) != 1 or not isinstance(images[0], bytes)
                   or len(images[0]) > 20 * 1024 * 1024 or not images[0].startswith(b"\xff\xd8")):
        raise ValueError("图像必须是预处理后的单张 JPEG。")
    disabled = True if task in {"rewrite", "prompt_ingest", "probe"} else not service.get("ingest_enable_thinking", False)
    # The task owns the override; caller flags cannot enable reasoning on rewrite.
    provider, model, base = config.get("provider", ""), config.get("model", ""), config.get("base_url", "").rstrip("/")
    if not model or not base:
        raise CompletionError("请先配置 LLM 服务和模型。")
    if disabled and requires_glm_thinking(model):
        raise WorkbenchError("thinking_disable_unsupported",
                             "GLM-5.3 / 5.3-Flash 不支持关闭思考，请为文字任务选择其他模型；可选读图需先启用思考。")
    native = service.get("type") == "ollama" and not base.endswith("/v1") and "/v1/" not in base
    controls = build_thinking_suppression("ollama" if native else provider, model, disable_thinking=disabled) or {}
    wire = deepcopy(messages)
    if should_append_no_thinking_instruction("ollama" if native else provider, model, disabled):
        wire.insert(0, {"role": "system", "content": "Return the requested result only, without reasoning or think tags."})
    if images:
        user = next((message for message in reversed(wire) if message["role"] == "user"), None)
        if user is None:
            raise ValueError("图像需要 user 消息。")
        encoded = base64.b64encode(images[0]).decode("ascii")
        if native:
            user["images"] = [encoded]
        else:
            user["content"] = [{"type": "text", "text": user["content"]},
                               {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}}]
    payload = {"model": model, "messages": wire, "stream": True, **controls}
    if service.get("enable_advanced_params", False):
        advanced = {"temperature": config.get("temperature", 0.7), "top_p": config.get("top_p", 0.9),
                    "num_predict" if native else "max_tokens": config.get("max_tokens", 2000)}
        if native:
            payload["options"] = advanced
        else:
            payload.update(advanced)
    headers = {"Content-Type": "application/json"}
    if config.get("api_key"):
        headers["Authorization"] = f"Bearer {config['api_key']}"
    if urlsplit(base).hostname == "opencode.ai":
        headers.update({"User-Agent": "AnimaPromptStudio/0.1",
                        "x-opencode-session": OpenAICompatibleService._opencode_session})
    url = base + "/api/chat" if native else OpenAICompatibleService.parse_api_url(base)

    async def request():
        client = HTTPClientPool.get_client(provider=provider, base_url=base, timeout=timeout_s)
        async with client.stream("POST", url, json=payload, headers=headers, timeout=timeout_s) as response:
            if not response.is_success:
                if response.status_code == 400:
                    # Classify known proxy aliases without returning private upstream text.
                    error_data = bytearray()
                    async for chunk in response.aiter_bytes():
                        error_data.extend(chunk[:max(0, 16384 - len(error_data))])
                        if len(error_data) >= 16384:
                            break
                    error_text = error_data.decode("utf-8", errors="replace").lower()
                    if "thinking-only model" in error_text and "disabling thinking" in error_text and "not supported" in error_text:
                        raise CompletionError("上游实际模型不支持关闭思考，请更换文字模型；草稿未修改。",
                                              reason="thinking_disable_unsupported", upstream_status=400)
                raise CompletionError("LLM 请求失败，请检查服务配置与网络。", reason="upstream_http_error", upstream_status=response.status_code)
            data = bytearray()
            line_start = 0
            stream_done = False
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 2 * 1024 * 1024:
                    raise CompletionError("LLM 返回内容超过限制。", reason="response_too_large")
                # SSE completion does not require the upstream TCP connection to close.
                # Scan complete lines only: the sentinel can straddle network chunks.
                while (line_end := data.find(b"\n", line_start)) >= 0:
                    line = bytes(data[line_start:line_end]).strip()
                    line_start = line_end + 1
                    if line.startswith(b"data:") and line[5:].strip() == b"[DONE]":
                        del data[line_start:]
                        stream_done = True
                        break
                if stream_done:
                    break
            raw = data.decode("utf-8")
            content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type or raw.lstrip().startswith("data:"):
            records = [json.loads(line[5:].strip()) for line in raw.splitlines()
                       if line.startswith("data:") and line[5:].strip() not in {"", "[DONE]"}]
        elif native and "\n" in raw.strip():
            records = [json.loads(line) for line in raw.splitlines() if line.strip()]
        else:
            records = [json.loads(raw)]
        parts = []
        for record in records:
            if record.get("error"):
                raise CompletionError("LLM 未完成请求。", reason="incomplete_response")
            if native:
                fragment = record.get("message", {}).get("content", "")
            else:
                choices = record.get("choices", [])
                choice = choices[0] if choices else {}
                fragment = choice.get("delta", choice.get("message", {})).get("content", "")
                if choice.get("finish_reason") in {"length", "content_filter"}:
                    raise CompletionError("LLM 返回被截断或未完成。", reason="incomplete_response")
            if fragment is not None:
                if not isinstance(fragment, str):
                    raise CompletionError("LLM 返回格式不受支持。")
                parts.append(fragment)
        valid, text = postprocess_model_output("".join(parts), filter_thinking_output=True)
        if not valid or not text.strip():
            raise CompletionError("LLM 未返回有效内容。", reason="empty_response")
        return {"text": text, "capabilities": {"vision": vision, "thinking_control": bool(controls)}}

    try:
        return await asyncio.wait_for(request(), timeout=timeout_s)
    except (TimeoutError, asyncio.CancelledError):
        raise
    except httpx.TimeoutException:
        raise TimeoutError("LLM 请求超时。") from None
    except CompletionError:
        raise
    except httpx.TransportError:
        raise CompletionError("LLM 网络连接失败。", reason="transport_error") from None
    except Exception:
        # Deliberately break the chain: exceptions can contain auth or entire prompts.
        raise CompletionError("LLM 请求失败或返回格式无效。") from None
