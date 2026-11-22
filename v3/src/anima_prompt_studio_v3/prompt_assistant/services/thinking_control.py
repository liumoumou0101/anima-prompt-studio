"""
Thinking-control parameter registry.

This module only decides which request parameter should be sent to suppress
model reasoning. Transport, retry, and final output filtering live elsewhere.
Keep rules conservative: add a request parameter only when the provider/model
family has a known control surface. Unsupported parameters are removed by the
OpenAI-compatible degradation path.
"""

import re
from copy import deepcopy
from typing import Any, Dict, List
from urllib.parse import urlsplit


THINKING_CONTROL_RULES: List[Dict[str, Any]] = [
    {
        "name": "mimo_v25_thinking",
        "description": "MiMo V2.5 defaults to deep thinking; explicitly disable for prompt conversion",
        "patterns": [r"mimo[-_/.]v2\.5(?:$|[-_/])"],
        "params": {"thinking": {"type": "disabled"}},
        "sources": ["https://platform.xiaomimimo.com/docs/en-US/usage-guide/passing-back-reasoning_content"],
    },
    {
        "name": "minimax_m3_thinking",
        "description": "MiniMax M3 defaults to thinking; disable it for prompt conversion",
        "patterns": [r"(?:^|/)minimax[-_/.]m3(?:$|[-_/:])"],
        "params": {"thinking": {"type": "disabled"}},
        "sources": ["https://platform.minimax.io/docs/api-reference/text-openai-api"],
    },
    {
        "name": "zai_glm_thinking",
        "description": "GLM/Z.AI models with thinking.type control",
        "patterns": [
            r"glm[-_/.]?(4\.5|4\.6|4\.7|5)",
            r"glm[-_/.]?4\.5v",
        ],
        "params": {"thinking": {"type": "disabled"}},
        "sources": ["Z.AI Thinking Mode"],
    },
    {
        "name": "qwen_enable_thinking",
        "description": "Qwen3/Qwen-VL endpoints that accept enable_thinking",
        "patterns": [
            r"qwen[-_/.]?3(?!.*r1)",
            r"qwen.*[-_/.]?vl",
        ],
        "params": {"enable_thinking": False},
        "sources": ["Qwen/DashScope OpenAI-compatible API"],
    },
    {
        "name": "deepseek_thinking",
        "description": "DeepSeek endpoints that accept thinking.type",
        "patterns": [
            r"deepseek[-_/.]?(chat|v3)(?!.*r1)",
        ],
        "params": {"thinking": {"type": "disabled"}},
        "sources": ["DeepSeek thinking mode API"],
    },
    {
        "name": "gemini_flash_reasoning",
        "description": "Gemini Flash/Lite via OpenAI-compatible proxies",
        "patterns": [
            r"gemini[-_/.]?2\.(0|5)[-_/.]?(flash|lite)",
        ],
        "params": {"reasoning_effort": "none"},
        "sources": ["OpenAI-compatible Gemini proxies"],
    },
]


OLLAMA_NATIVE_RULES = {
    "parameter_name": "think",
    "disable_value": False,
    "enable_value": True,
    "supported_patterns": [
        r"deepseek.*(r1|v3)",
        r"qwen.*(3|r1|thinking|vl)",
        r".*thinking",
    ],
    "sources": ["Ollama /api/chat think parameter"],
}


OLLAMA_NATIVE_EXCLUDE_PATTERNS = [
    # Community abliterated/uncensored vision variants often expose Qwen names
    # but do not consistently follow Ollama's native thinking contract.
    r"abliterated",
    r"uncensored",
]


GLM_REQUIRED_THINKING_PATTERNS = [r"(?:^|[/])glm[-_/.]?5\.3(?:$|[-_/:])"]


EXCLUDE_PATTERNS = [
    # GLM-5.3/Flash require thinking; sending disabled is an API error.
    # https://docs.z.ai/guides/capabilities/thinking
    *GLM_REQUIRED_THINKING_PATTERNS,
    # Google states these cannot be fully disabled; final filtering is the fallback.
    r"gemini[-_/.]?2\.5[-_/.]?pro",
    r"gemini[-_/.]?3[-_/.]?pro",
    # xAI reasoning models currently do not expose a reliable off switch.
    r"grok.*reason",
    r"grok[-_/.]?4",
    # Ollama GPT-OSS accepts only low/medium/high and cannot be fully disabled.
    r"gpt[-_/.]?oss",
    # Reasoning-only families should not be forced with guessed parameters.
    r".*speciale",
]


def _matches(patterns: List[str], model_lower: str) -> bool:
    return any(re.search(pattern, model_lower) for pattern in patterns)


def requires_glm_thinking(model: str) -> bool:
    """Known GLM versions whose API rejects thinking.type=disabled."""
    return _matches(GLM_REQUIRED_THINKING_PATTERNS, model.strip().lower())


def opencode_go_base(base_url: str) -> str | None:
    """Match only the actual Go API, including explicitly saved endpoints."""
    endpoint = urlsplit(base_url)
    if (endpoint.scheme == "https" and endpoint.netloc.lower() == "opencode.ai"
            and not endpoint.query and not endpoint.fragment
            and endpoint.path.rstrip("/") in {
                "/zen/go/v1", "/zen/go/v1/chat/completions", "/zen/go/v1/messages", "/zen/go/v1/responses"}):
        return "https://opencode.ai/zen/go/v1"
    return None


# Exact Go IDs verified against its gateway on 2026-09-18. Native provider
# capabilities do not predict proxy routing (e.g. Go GLM 5.1/5.2 -> 5.3).
# Do not generalize these routes/fields to other hosts or newly named models.
GO_COMBINED_THINKING = {
    "minimax-m3", "mimo-v2.5", "mimo-v2.5-pro", "deepseek-v4-pro",
    "deepseek-flash", "deepseek-v4.1-flash", "deepseek-v4-flash-vision-exp",
}
GO_QWEN_THINKING = {"qwen3.7-max", "qwen3.8-max", "qwen3.8-flash", "qwen3.7-plus", "qwen3.6-plus"}
GO_REQUIRED_THINKING = {
    "glm-5.1", "glm-5.2", "glm-5.3", "glm-5.3-flash", "kimi-k3", "kimi-k2.7-code",
    "minimax-m2.5", "minimax-m2.7", "grok-4.6", "muse-spark-1.3-contributor", "muse-spark-1.2-contributor",
    "omen-alpha", "deepseek-v4-flash",
}
GO_RESPONSES = {"gpt-5.6-luna", "grok-4.6", "muse-spark-1.3-contributor", "muse-spark-1.2-contributor"}
GO_MESSAGES = {"minimax-m2.7", "union-alpha"}


def go_completion_protocol(model: str, base_url: str) -> str:
    if opencode_go_base(base_url):
        model = model.strip().lower()
        if model in GO_RESPONSES:
            return "responses"
        if model in GO_MESSAGES:
            return "messages"
    return "chat"


def _go_thinking_controls(model: str, enabled: bool) -> Dict[str, Any] | None:
    thinking = {"type": "enabled" if enabled else "disabled"}
    if model in GO_COMBINED_THINKING:
        if enabled and model == "minimax-m3":
            thinking = {"type": "adaptive"}
        return {"thinking": thinking, "reasoning": {"enabled": enabled}}
    if model in GO_QWEN_THINKING:
        return {"enable_thinking": enabled, "reasoning": {"enabled": enabled}}
    if model in {"hy3", "hy4-preview"}:
        return {"reasoning": {"enabled": enabled}}
    if model in GO_RESPONSES:
        return {"reasoning": {"effort": "medium" if enabled else "none"}}
    if model in {"kimi-k2.6", "glm-5.3-flash", "omen-alpha"}:
        return {"reasoning_effort": "medium" if enabled else "none"}
    if model in GO_REQUIRED_THINKING or model == "longcat-2.0":
        return {"thinking": thinking}
    if model == "union-alpha":
        # The anonymous route accepts Messages but its reasoning behavior is
        # unverified. Never guess gateway reasoning/effort parameters here.
        return {"thinking": {**thinking, **({"budget_tokens": 2048} if enabled else {})}}
    return None


def get_thinking_capability(provider: str, model: str, *, base_url: str = "") -> Dict[str, str]:
    model_lower = model.strip().lower()
    if opencode_go_base(base_url):
        if model_lower in GO_REQUIRED_THINKING:
            if model_lower in {"glm-5.1", "glm-5.2"}:
                message = "当前 Go 路由实际使用必须思考的 GLM-5.3；请开启深度思考或更换模型。"
            elif model_lower in {"omen-alpha", "deepseek-v4-flash"}:
                message = "当前 Go 路由实测无法可靠关闭思考；请开启深度思考或更换模型。"
            else:
                message = "此模型必须开启思考；请开启深度思考或更换模型。"
            return {"mode": "required", "message": message}
        if model_lower != "union-alpha" and _go_thinking_controls(model_lower, False) is not None:
            return {"mode": "switchable", "message": "已验证此 Go 模型的思考开关；开启通常更慢。"}
        return {"mode": "unverified", "message": "此 Go 模型的思考开关尚未验证，实际行为由上游决定。"}
    if requires_glm_thinking(model):
        return {"mode": "required", "message": "此模型必须开启思考；请开启深度思考或更换模型。"}
    if build_thinking_suppression(provider, model, base_url=base_url):
        return {"mode": "switchable", "message": "将发送该模型支持的思考开关；开启通常更慢。"}
    return {"mode": "unverified", "message": "此模型的思考开关尚未验证，实际行为由上游决定。"}


def build_workbench_thinking_controls(provider: str, model: str, *, enabled: bool, base_url: str = "") -> Dict[str, Any]:
    """Explicit on and off for user-controlled tasks; legacy suppression stays compatible."""
    model_lower = model.strip().lower()
    if opencode_go_base(base_url):
        params = _go_thinking_controls(model_lower, enabled)
        if params is not None:
            return params
    if not enabled or provider == "ollama":
        return build_thinking_suppression(provider, model, disable_thinking=not enabled, base_url=base_url)
    if requires_glm_thinking(model):
        return {"thinking": {"type": "enabled"}}
    params = build_thinking_suppression(provider, model, base_url=base_url)
    if "thinking" in params:
        params["thinking"] = {"type": "adaptive" if _matches([r"(?:^|/)minimax[-_/.]m3(?:$|[-_/:])"], model_lower) else "enabled"}
    if "enable_thinking" in params:
        params["enable_thinking"] = True
    if "reasoning_effort" in params:
        params["reasoning_effort"] = "medium"
    return params


def build_thinking_suppression(
    provider: str,
    model: str,
    disable_thinking: bool = True,
    *,
    base_url: str = "",
) -> Dict[str, Any]:
    """Return request parameters for thinking control, or an empty dict."""
    if not model:
        return {}

    model_lower = model.strip().lower()
    provider_lower = provider.strip().lower() if provider else ""

    if disable_thinking and opencode_go_base(base_url):
        params = _go_thinking_controls(model_lower, False)
        if params is not None:
            return params

    if _matches(EXCLUDE_PATTERNS, model_lower):
        return {}

    if provider_lower == "ollama":
        if _matches(OLLAMA_NATIVE_EXCLUDE_PATTERNS, model_lower):
            return {}
        if _matches(OLLAMA_NATIVE_RULES["supported_patterns"], model_lower):
            value = (
                OLLAMA_NATIVE_RULES["disable_value"]
                if disable_thinking
                else OLLAMA_NATIVE_RULES["enable_value"]
            )
            return {OLLAMA_NATIVE_RULES["parameter_name"]: value}
        return {}

    if not disable_thinking:
        return {}

    for rule in THINKING_CONTROL_RULES:
        if _matches(rule["patterns"], model_lower):
            params = deepcopy(rule["params"])
            return params

    return {}


def should_append_no_thinking_instruction(
    provider: str,
    model: str,
    disable_thinking: bool = True,
) -> bool:
    if not disable_thinking or not model:
        return False

    provider_lower = provider.strip().lower() if provider else ""
    model_lower = model.strip().lower()

    if provider_lower == "ollama" and _matches(OLLAMA_NATIVE_EXCLUDE_PATTERNS, model_lower):
        return False

    return True


def get_rule_info(provider: str, model: str) -> Dict[str, Any]:
    """Return matching rule details for diagnostics."""
    if not model:
        return {"matched": False}

    model_lower = model.strip().lower()
    provider_lower = provider.strip().lower() if provider else ""

    if _matches(EXCLUDE_PATTERNS, model_lower):
        return {
            "matched": True,
            "rule_name": "excluded",
            "description": "Known model family without a reliable disable parameter",
            "params": {},
            "sources": [],
        }

    if provider_lower == "ollama":
        if _matches(OLLAMA_NATIVE_EXCLUDE_PATTERNS, model_lower):
            return {
                "matched": True,
                "rule_name": "ollama_native_excluded",
                "description": "Community model variant without reliable native thinking control",
                "params": {},
                "sources": [],
            }
        if _matches(OLLAMA_NATIVE_RULES["supported_patterns"], model_lower):
            return {
                "matched": True,
                "rule_name": "ollama_native",
                "description": "Ollama native /api/chat thinking control",
                "params": {OLLAMA_NATIVE_RULES["parameter_name"]: OLLAMA_NATIVE_RULES["disable_value"]},
                "sources": OLLAMA_NATIVE_RULES["sources"],
            }
        return {"matched": False}

    for rule in THINKING_CONTROL_RULES:
        if _matches(rule["patterns"], model_lower):
            return {
                "matched": True,
                "rule_name": rule["name"],
                "description": rule["description"],
                "params": deepcopy(rule["params"]),
                "sources": rule.get("sources", []),
            }

    return {"matched": False}
