"""Conversation contracts and pure transitions; no transport, storage or UI imports."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator


Mode = Literal["faithful", "expand"]
LayerName = Literal["subject", "style", "lighting", "composition", "exclusions"]
PinRole = Literal["style", "lighting", "composition", "whole_scene"]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
COMPILER_CONTRACT = "anima-rewrite/1"


class WorkbenchError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class TextContent(ContractModel):
    text: str = Field(max_length=10_000)


class StyleContent(TextContent):
    medium: str = Field(max_length=200)
    artists: list[ShortText] = Field(max_length=32)

    @field_validator("artists")
    @classmethod
    def canonical_artists(cls, values: list[str]) -> list[str]:
        if any(name.startswith("@") for name in values) or len(set(values)) != len(values):
            raise ValueError("画师名称必须唯一且不含 @ 前缀。")
        return values


class CompositionContent(TextContent):
    shot: str = Field(max_length=200)


class ScopedExclusion(ContractModel):
    target: ShortText
    concept: ShortText


class ExclusionsContent(ContractModel):
    global_: list[ShortText] = Field(alias="global", max_length=100)
    scoped: list[ScopedExclusion] = Field(max_length=100)


class TextLayer(TextContent):
    text: str = Field(default="", max_length=10_000)
    locked: bool = False


class StyleLayer(StyleContent):
    text: str = Field(default="", max_length=10_000)
    medium: str = Field(default="", max_length=200)
    artists: list[ShortText] = Field(default_factory=list, max_length=32)
    locked: bool = False


class LightingLayer(TextLayer):
    include_with_style_pin: bool = False


class CompositionLayer(CompositionContent):
    text: str = Field(default="", max_length=10_000)
    shot: str = Field(default="", max_length=200)
    locked: bool = False
    include_with_style_pin: bool = False


class ExclusionsLayer(ExclusionsContent):
    global_: list[ShortText] = Field(default_factory=list, alias="global", max_length=100)
    scoped: list[ScopedExclusion] = Field(default_factory=list, max_length=100)
    locked: bool = False


class RequirementLayers(ContractModel):
    subject: TextLayer
    style: StyleLayer
    lighting: LightingLayer
    composition: CompositionLayer
    exclusions: ExclusionsLayer

    @classmethod
    def empty(cls) -> RequirementLayers:
        return cls(subject=TextLayer(), style=StyleLayer(), lighting=LightingLayer(),
                   composition=CompositionLayer(), exclusions=ExclusionsLayer())


class LoraSource(ContractModel):
    kind: Literal["user", "civitai", "huggingface", "official", "run"] = "user"
    model_version_id: str | None = Field(default=None, max_length=200)


class RequirementLora(ContractModel):
    logical_id: ShortText
    file_name: str = Field(min_length=1, max_length=1000)
    weight: float = Field(default=1.0, ge=-2, le=2)
    trigger_words: list[ShortText] = Field(default_factory=list, max_length=32)
    required: bool = True
    source: LoraSource = Field(default_factory=LoraSource)


class RequirementsEdit(ContractModel):
    layers: RequirementLayers
    loras: list[RequirementLora] = Field(max_length=16)

    @field_validator("loras")
    @classmethod
    def unique_resources(cls, values: list[RequirementLora]) -> list[RequirementLora]:
        if len({item.logical_id for item in values}) != len(values):
            raise ValueError("LoRA logical_id 必须唯一。")
        return values


class Requirements(RequirementsEdit):
    contract: Literal["anima-requirements/1"] = "anima-requirements/1"
    revision: int = Field(default=1, ge=1)

    @classmethod
    def empty(cls) -> Requirements:
        return cls(layers=RequirementLayers.empty(), loras=[])


class PromptEdit(ContractModel):
    positive: str = Field(min_length=1, max_length=20_000)
    negative: str = Field(max_length=20_000)


class CompiledPrompt(PromptEdit):
    mode: Mode
    source: Literal["llm", "user"]
    compiled_token: str = Field(pattern=r"^cmp_[a-f0-9]{32}$")
    inputs_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    prompt_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    compiler_contract: Literal["anima-rewrite/1"] = COMPILER_CONTRACT


class ReferenceCompat(ContractModel):
    model_profiles: list[ShortText] = Field(default_factory=list, max_length=32)
    workflow_kinds: list[ShortText] = Field(default_factory=list, max_length=32)
    workflow_snapshot_ref: str | None = Field(default=None, max_length=200)


class ReferenceSnapshot(ContractModel):
    requirements: Requirements
    compat: ReferenceCompat = Field(default_factory=ReferenceCompat)


class ReferencePin(ContractModel):
    example_id: str = Field(pattern=r"^(ex_[a-f0-9]+|off_[A-Za-z0-9_]+)$")
    source_version: str = Field(min_length=1, max_length=200)
    role: PinRole
    pinned_at: str = Field(min_length=1, max_length=50)
    source_snapshot: ReferenceSnapshot


class ConversationEvent(ContractModel):
    id: str = Field(pattern=r"^evt_[a-f0-9]{32}$")
    delta: str = Field(max_length=4000)
    changed_layers: list[LayerName] = Field(max_length=5)
    warnings: list[str] = Field(max_length=20)
    before_revision: int = Field(ge=1)
    after_revision: int = Field(ge=2)
    created_at: str = Field(max_length=50)


class SessionPreview(ContractModel):
    run_id: str = Field(min_length=1, max_length=200)
    path: str = Field(min_length=1, max_length=2000)
    created_at: str = Field(max_length=50)


class GenerationSource(ContractModel):
    run_id: str
    remote_profile_id: str
    workflow_profile_id: str
    model_profile: str


class ConversationFields(ContractModel):
    mode: Mode = "faithful"
    requirements: Requirements | None = None
    compiled: CompiledPrompt | None = None
    reference_pin: ReferencePin | None = None
    generation_source: GenerationSource | None = None
    reference_preset_id: str | None = None
    conversation_events: list[ConversationEvent] = Field(default_factory=list, max_length=100)
    session_previews: list[SessionPreview] = Field(default_factory=list, max_length=100)
    compile_state: Literal["missing", "fresh", "stale"] = "missing"


class ConversationWriteFields(ConversationFields):
    requirements_edit: RequirementsEdit | None = None
    prompt_edit: PromptEdit | None = None


def dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", by_alias=True)


def digest(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def inputs_fingerprint(draft: dict[str, Any]) -> str:
    raw = draft.get("requirements")
    requirements = dump(Requirements.model_validate(raw)) if raw is not None else None
    if requirements is not None:
        requirements.pop("revision")
    return digest({"requirements": requirements, "mode": draft.get("mode", "faithful"),
                   "model_profile": draft.get("model_profile", "anima_aesthetic_v1"),
                   "compiler_contract": COMPILER_CONTRACT})


def compile_state(draft: dict[str, Any]) -> Literal["missing", "fresh", "stale"]:
    compiled = draft.get("compiled")
    if compiled is None:
        return "missing"
    return "fresh" if compiled["inputs_fingerprint"] == inputs_fingerprint(draft) else "stale"


def compile_prompt(draft: dict[str, Any], prompt: PromptEdit, *, source: Literal["llm", "user"]) -> dict:
    return dump(CompiledPrompt(**dump(prompt), mode=draft.get("mode", "faithful"), source=source,
                               compiled_token=f"cmp_{uuid4().hex}",
                               inputs_fingerprint=inputs_fingerprint(draft),
                               prompt_fingerprint=digest(dump(prompt))))


def replace_requirements(current: Requirements | None, edit: RequirementsEdit) -> Requirements:
    content = dump(edit)
    if current is not None:
        previous = {key: value for key, value in dump(current).items() if key in content}
        revision = current.revision + (previous != content)
    else:
        revision = 1
    return Requirements(**content, revision=revision)


CONTENT_MODELS = {"subject": TextContent, "style": StyleContent, "lighting": TextContent,
                  "composition": CompositionContent, "exclusions": ExclusionsContent}


def apply_layer_updates(canonical: Requirements, touched_layers: list[str],
                        layer_updates: dict[str, Any]) -> Requirements:
    if len(set(touched_layers)) != len(touched_layers) or set(touched_layers) != set(layer_updates):
        raise WorkbenchError("invalid_layer_updates", "修改层列表与内容不一致。")
    result = dump(canonical)
    for name in touched_layers:
        if name not in CONTENT_MODELS or result["layers"][name]["locked"]:
            raise WorkbenchError("invalid_layer_updates", "不能自动修改未知层或锁定层。")
        try:
            update = dump(CONTENT_MODELS[name].model_validate(layer_updates[name]))
        except ValidationError as exc:
            raise WorkbenchError("invalid_layer_updates", "层内容不完整或包含不可编辑的控制字段。") from exc
        result["layers"][name].update(update)
    return replace_requirements(canonical, RequirementsEdit.model_validate(
        {"layers": result["layers"], "loras": result["loras"]}))


def apply_pin(canonical: Requirements, source: Requirements, role: PinRole) -> Requirements:
    target, origin = dump(canonical), dump(source)
    names = list(CONTENT_MODELS) if role == "whole_scene" else [role]
    if role == "style":
        names += [name for name in ("lighting", "composition")
                  if origin["layers"][name]["include_with_style_pin"]]
    for name in names:
        if target["layers"][name]["locked"]:
            continue
        for key, value in origin["layers"][name].items():
            if key not in ("locked", "include_with_style_pin"):
                target["layers"][name][key] = deepcopy(value)
    target["loras"] = [item for item in origin["loras"] if item["required"]]
    return replace_requirements(canonical, RequirementsEdit.model_validate(
        {"layers": target["layers"], "loras": target["loras"]}))


def project_conversation(draft: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(draft)
    from .seeds import display_seed
    settings = result.get("generation_settings")
    if isinstance(settings, dict) and isinstance(settings.get("seed"), int):
        settings["seed"] = display_seed(settings["seed"])
    try:
        state = ConversationFields.model_validate(
            {key: value for key, value in draft.items() if key in ConversationFields.model_fields})
    except ValidationError:
        raise WorkbenchError("workspace_contract_unsupported", "会话数据版本或结构不兼容；原数据未重置。") from None
    result.update(dump(state))
    pin = result["reference_pin"]
    result["reference_preset_id"] = pin["example_id"] if pin else None
    result["compile_state"] = compile_state(result)
    return result


def apply_workspace_edit(current: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
    """Run inside the workspace CAS transaction, never merge an earlier read."""
    existing = project_conversation(current or {})
    fields = ConversationWriteFields.model_fields
    protected = set(ConversationFields.model_fields) - {"mode", "session_previews", "compile_state"}
    for key in protected & incoming.keys():
        if current is None or incoming[key] != existing[key]:
            raise WorkbenchError("read_only_field", f"{key} 是服务端维护的字段。")
    result = {key: deepcopy(value) for key, value in incoming.items() if key not in fields}
    result.update({key: existing[key] for key in ConversationFields.model_fields
                   if key not in ("reference_preset_id", "session_previews", "compile_state")})
    if "mode" in incoming:
        result["mode"] = incoming["mode"]
    if "requirements_edit" in incoming:
        edit = incoming["requirements_edit"]
        if edit is None:
            raise WorkbenchError("invalid_workspace_edit", "清除会话请使用重置操作。")
        before = Requirements.model_validate(existing["requirements"]) if existing["requirements"] else None
        result["requirements"] = dump(replace_requirements(before, RequirementsEdit.model_validate(edit)))
    if "prompt_edit" in incoming:
        if incoming["prompt_edit"] is None:
            raise WorkbenchError("invalid_workspace_edit", "提示词编辑不能为空。")
        prompt = PromptEdit.model_validate(incoming["prompt_edit"])
        if current is None or result["compiled"] is None or compile_state(result) != "fresh":
            raise WorkbenchError("invalid_workspace_edit", "请先根据当前要求编译，再编辑提示词。")
        if any(result["compiled"][key] != value for key, value in dump(prompt).items()):
            result["compiled"] = compile_prompt(result, prompt, source="user")
    return result
