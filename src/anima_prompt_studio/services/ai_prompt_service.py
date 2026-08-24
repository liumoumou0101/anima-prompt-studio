from __future__ import annotations

import json
import time
from enum import StrEnum
from typing import Any, Callable, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, field_validator


OPENCODE_GO_BASE_URL = "https://opencode.ai/zen/go/v1"

# OpenCode Go publishes one model catalog but routes models through three API
# shapes. Unknown/new models default to Chat Completions and can be overridden
# in settings. Source: https://opencode.ai/docs/go/
OPENCODE_GO_RESPONSES_MODELS = {
    "grok-4.5", "gpt-5.6-luna", "muse-spark-1.2-contributor",
}
OPENCODE_GO_MESSAGES_MODELS = {
    "minimax-m3", "minimax-m2.7", "minimax-m2.5", "qwen3.8-max",
    "qwen3.7-max", "qwen3.7-plus", "qwen3.6-plus", "qwen3.5-plus",
}
OPENCODE_GO_KNOWN_MODELS = [
    "ox-alpha-free", "mimo-v2.5", "mimo-v2.5-pro", "deepseek-v4-flash",
    "deepseek-v4-pro", "glm-5.2", "glm-5.1", "glm-5.3", "hy3",
    "kimi-k3", "kimi-k2.7-code", "kimi-k2.6", "grok-4.5", "gpt-5.6-luna",
    "minimax-m3", "minimax-m2.7", "qwen3.8-max", "qwen3.7-max",
    "qwen3.7-plus", "qwen3.6-plus", "muse-spark-1.2-contributor",
    "deepseek-v4-flash-vision-exp",
]

OPENCODE_GO_FREE_MODELS = frozenset({"ox-alpha-free"})
OPENCODE_GO_HIGH_CONSUMPTION_MODELS = frozenset({
    "kimi-k3", "grok-4.5", "qwen3.8-max", "glm-5.3", "qwen3.7-max",
    "glm-5.2", "glm-5.1",
})
RETRYABLE_HTTP_CODES = frozenset({429, 502, 503, 504})


def opencode_go_model_label(model_id: str) -> str:
    """Return a user-facing model label without changing the API model ID."""
    if model_id in OPENCODE_GO_FREE_MODELS:
        return f"★ 限时免费 · {model_id}"
    if model_id in OPENCODE_GO_HIGH_CONSUMPTION_MODELS:
        return f"⚠ 较贵 / 高消耗 · {model_id}"
    return model_id


class AIAPIError(RuntimeError):
    pass


class AIAPIStyle(StrEnum):
    AUTO = "auto"
    CHAT_COMPLETIONS = "chat_completions"
    RESPONSES = "responses"
    MESSAGES = "messages"


class AIEngineConfig(BaseModel):
    provider_id: Literal["opencode_go", "openai_compatible"] = "opencode_go"
    base_url: str = OPENCODE_GO_BASE_URL
    model: str = "mimo-v2.5"
    api_style: AIAPIStyle = AIAPIStyle.AUTO
    timeout_seconds: int = Field(default=60, ge=10, le=600)
    thinking_enabled: bool = False

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("API Base URL 必须是完整的 http/https 地址。")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("远程 AI API 必须使用 HTTPS；本机 localhost 接口可以使用 HTTP。")
        return normalized

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("请填写 API 模型名称。")
        return normalized

    def resolved_style(self) -> AIAPIStyle:
        if self.api_style != AIAPIStyle.AUTO:
            return self.api_style
        endpoint_path = urlparse(self.base_url).path.rstrip("/")
        if endpoint_path.endswith("/responses"):
            return AIAPIStyle.RESPONSES
        if endpoint_path.endswith("/messages"):
            return AIAPIStyle.MESSAGES
        if endpoint_path.endswith("/chat/completions"):
            return AIAPIStyle.CHAT_COMPLETIONS
        if self.provider_id == "opencode_go":
            if self.model in OPENCODE_GO_RESPONSES_MODELS:
                return AIAPIStyle.RESPONSES
            if self.model in OPENCODE_GO_MESSAGES_MODELS:
                return AIAPIStyle.MESSAGES
        return AIAPIStyle.CHAT_COMPLETIONS

    def endpoint(self) -> str:
        style = self.resolved_style()
        suffixes = {
            AIAPIStyle.CHAT_COMPLETIONS: "/chat/completions",
            AIAPIStyle.RESPONSES: "/responses",
            AIAPIStyle.MESSAGES: "/messages",
        }
        if any(self.base_url.endswith(suffix) for suffix in suffixes.values()):
            return self.base_url
        return self.base_url + suffixes[style]

    def models_endpoint(self) -> str:
        parsed = urlparse(self.base_url)
        path = parsed.path.rstrip("/")
        for suffix in ("/chat/completions", "/responses", "/messages"):
            if path.endswith(suffix):
                path = path[: -len(suffix)]
                break
        return parsed._replace(path=path + "/models", query="", fragment="").geturl()


class AIClient:
    """Minimal OpenCode Go / OpenAI-compatible JSON client for auxiliary tasks."""

    def __init__(
        self,
        config: AIEngineConfig,
        api_key: str,
        opener: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        if not api_key.strip():
            raise AIAPIError("请先配置 AI API Key。")
        self.config = config
        self.api_key = api_key.strip()
        self._opener = opener or urlopen
        self._sleep = sleeper or time.sleep

    @property
    def name(self) -> str:
        provider = "OpenCode Go" if self.config.provider_id == "opencode_go" else "AI API"
        return f"{provider} · {self.config.model}"

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        """Run a structured AI task and reject ambiguous non-JSON output."""
        content = self._complete(system, user)
        try:
            return self._extract_json_object(content)
        except AIAPIError as exc:
            raise AIAPIError("AI 没有按要求返回结构化 JSON，请关闭思考或换一个更稳定的模型重试。") from exc

    def list_models(self) -> list[str]:
        request = Request(self.config.models_endpoint(), headers=self._headers(), method="GET")
        payload = self._request_json(request)
        models = payload.get("data", []) if isinstance(payload, dict) else []
        return sorted({
            str(item.get("id", "")).strip()
            for item in models if isinstance(item, dict) and item.get("id")
        })

    def _complete(self, system: str, user: str) -> str:
        style = self.config.resolved_style()
        thinking = {"type": "enabled" if self.config.thinking_enabled else "disabled"}
        if style == AIAPIStyle.RESPONSES:
            body: dict[str, Any] = {
                "model": self.config.model,
                "input": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "reasoning": {"effort": "medium" if self.config.thinking_enabled else "none"},
            }
        elif style == AIAPIStyle.MESSAGES:
            body = {
                "model": self.config.model,
                "max_tokens": 2048,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
        else:
            body = {
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "thinking": thinking,
            }
            if not self.config.thinking_enabled:
                body["temperature"] = 0.1
        request = Request(
            self.config.endpoint(),
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        return self._response_text(self._request_json(request), style)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ANIMA-Prompt-Studio/2",
        }

    def _request_json(self, request: Request, retries: int = 2) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                with self._opener(request, timeout=self.config.timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:800]
                last_error = AIAPIError(f"AI API 请求失败（HTTP {exc.code}）：{detail}")
                if exc.code in RETRYABLE_HTTP_CODES and attempt < retries:
                    self._sleep(1.5 * (attempt + 1))
                    continue
                raise last_error from exc
            except URLError as exc:
                last_error = AIAPIError(f"无法连接 AI API：{exc.reason}")
                if attempt < retries:
                    self._sleep(1.5 * (attempt + 1))
                    continue
                raise last_error from exc
            except TimeoutError as exc:
                raise AIAPIError("AI API 请求超时，请检查网络、关闭思考或增大超时时间。") from exc
            except json.JSONDecodeError as exc:
                raise AIAPIError("AI API 返回的响应不是有效 JSON。") from exc
            except OSError as exc:
                last_error = AIAPIError(f"AI API 网络请求失败：{exc}")
                if attempt < retries:
                    self._sleep(1.5 * (attempt + 1))
                    continue
                raise last_error from exc
        raise last_error or AIAPIError("AI API 请求失败。")

    @staticmethod
    def _response_text(payload: dict[str, Any], style: AIAPIStyle) -> str:
        if style == AIAPIStyle.CHAT_COMPLETIONS:
            try:
                message = payload["choices"][0]["message"]
            except (KeyError, IndexError, TypeError) as exc:
                raise AIAPIError(f"Chat Completions 响应缺少文本：{payload.get('error', payload)}") from exc
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str) and content.strip():
                return content
            if isinstance(content, list):
                text = "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
                if text.strip():
                    return text
            for key in ("reasoning_content", "reasoning"):
                value = message.get(key) if isinstance(message, dict) else None
                if isinstance(value, str) and value.strip():
                    return value
        elif style == AIAPIStyle.RESPONSES:
            if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
                return payload["output_text"]
            parts = []
            for output in payload.get("output", []):
                if not isinstance(output, dict):
                    continue
                for item in output.get("content", []):
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        parts.append(item["text"])
            if parts:
                return "".join(parts)
        else:
            parts = [
                item["text"] for item in payload.get("content", [])
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ]
            if parts:
                return "".join(parts)
        raise AIAPIError(f"AI API 响应缺少可用文本：{payload.get('error', payload)}")

    @staticmethod
    def _extract_json_object(content: str) -> dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        decoder = json.JSONDecoder()
        for index, character in enumerate(text):
            if character != "{":
                continue
            try:
                value, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        raise AIAPIError("AI 没有返回可解析的 JSON 对象。")
