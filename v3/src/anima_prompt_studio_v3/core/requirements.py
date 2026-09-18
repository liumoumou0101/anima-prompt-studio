"""Conversation contracts and pure transitions; no transport, storage or UI imports."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator
from .scene_design import SceneChoice, SceneDesign, SceneField, declared_scene_choices


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


class SubjectLayer(TextLayer):
    character_tags: list[ShortText] = Field(default_factory=list, max_length=32)
    series_tags: list[ShortText] = Field(default_factory=list, max_length=32)
    general_tags: list[ShortText] = Field(default_factory=list, max_length=64)

    @field_validator("character_tags", "series_tags", "general_tags")
    @classmethod
    def manual_tags(cls, values: list[str]) -> list[str]:
        from .manual_tags import normalize_tag
        result = []
        for value in values:
            if any(char in value for char in (",", "\n", "\r", "@", "<", ">")):
                raise ValueError("请每项填写一个 tag；画师请使用画师栏。")
            tag = normalize_tag(value)
            if tag not in result:
                result.append(tag)
        return result


class StyleLayer(StyleContent):
    text: str = Field(default="", max_length=10_000)
    medium: str = Field(default="", max_length=200)
    artists: list[ShortText] = Field(default_factory=list, max_length=32)
    manual_artist_tags: list[ShortText] = Field(default_factory=list, max_length=32)
    locked: bool = False

    @field_validator("manual_artist_tags")
    @classmethod
    def manual_artists(cls, values: list[str]) -> list[str]:
        from .manual_tags import normalize_tag
        result = []
        for value in values:
            tag = normalize_tag(value, artist=True)
            if not tag or any(char in tag for char in (",", "@", "<", ">")) or any(char in value for char in ("\n", "\r")):
                raise ValueError("画师请每项填写一个 tag，可带 @ 前缀。")
            if tag not in result:
                result.append(tag)
        return result


class LightingLayer(TextLayer):
    include_with_style_pin: bool = False
    mood: SceneChoice | None = None


class CompositionLayer(CompositionContent):
    text: str = Field(default="", max_length=10_000)
    shot: str = Field(default="", max_length=200)
    locked: bool = False
    include_with_style_pin: bool = False
    design: SceneDesign | None = None


class ExclusionsLayer(ExclusionsContent):
    global_: list[ShortText] = Field(default_factory=list, alias="global", max_length=100)
    scoped: list[ScopedExclusion] = Field(default_factory=list, max_length=100)
    locked: bool = False


class RequirementLayers(ContractModel):
    subject: SubjectLayer
    style: StyleLayer
    lighting: LightingLayer
    composition: CompositionLayer
    exclusions: ExclusionsLayer

    @classmethod
    def empty(cls) -> RequirementLayers:
        return cls(subject=SubjectLayer(), style=StyleLayer(), lighting=LightingLayer(),
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


class PromptLock(ContractModel):
    target: Literal["positive", "negative"]
    text: str = Field(min_length=1, max_length=1000)


class RequirementsEdit(ContractModel):
    layers: RequirementLayers
    loras: list[RequirementLora] = Field(max_length=16)
    prompt_locks: list[PromptLock] = Field(default_factory=list, max_length=32)

    @field_validator("prompt_locks")
    @classmethod
    def unique_prompt_locks(cls, values: list[PromptLock]) -> list[PromptLock]:
        return list({(item.target, item.text): item for item in values}.values())

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
    # Reviewed prompt text is also the browser's comparison baseline. Preserve
    # its exact whitespace on input and when CompiledPrompt reloads it later.
    model_config = ConfigDict(str_strip_whitespace=False)
    positive: str = Field(min_length=1, max_length=20_000)
    negative: str = Field(max_length=20_000)

    @field_validator("positive")
    @classmethod
    def positive_contains_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("正向提示词不能只有空白。")
        return value


class CompiledPrompt(PromptEdit):
    mode: Mode
    source: Literal["llm", "user"]
    requirements_synced: bool = False
    compiled_token: str = Field(pattern=r"^cmp_[a-f0-9]{32}$")
    inputs_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    prompt_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    compiler_contract: Literal["anima-rewrite/1"] = COMPILER_CONTRACT
    manual_tags: list[str] = Field(default_factory=list, max_length=192)
    scene_intent: dict[SceneField, SceneChoice] = Field(default_factory=dict, max_length=5)
    exclusions_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


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


class WorkspaceOrigin(ContractModel):
    workspace_id: str = Field(pattern=r"^workspace_[A-Za-z0-9]+$")
    revision: int = Field(ge=1)
    run_id: str | None = Field(default=None, min_length=1, max_length=200)


class ConversationFields(ContractModel):
    mode: Mode = "faithful"
    requirements: Requirements | None = None
    compiled: CompiledPrompt | None = None
    reference_pin: ReferencePin | None = None
    generation_source: GenerationSource | None = None
    workspace_origin: WorkspaceOrigin | None = None
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
    return _inputs_fingerprint(draft, include_edit_controls=False)


def _inputs_fingerprint(draft: dict[str, Any], *, include_edit_controls: bool) -> str:
    raw = draft.get("requirements")
    requirements = dump(Requirements.model_validate(raw)) if raw is not None else None
    if requirements is not None:
        requirements.pop("revision")
        # Literal protection affects allowed edits, not the reviewed image text.
        requirements.pop("prompt_locks", None)
        # Protection and reference-copy switches affect editing, not rendering.
        # Keep their default values in the hash for compatibility with prompts
        # compiled before this distinction was introduced.
        if not include_edit_controls:
            for layer in requirements["layers"].values():
                layer["locked"] = False
                if "include_with_style_pin" in layer:
                    layer["include_with_style_pin"] = False
        # Adding empty manual fields must not invalidate historical compiled
        # prompts or frozen submission fingerprints.
        for key in ("character_tags", "series_tags", "general_tags"):
            if not requirements["layers"]["subject"].get(key):
                requirements["layers"]["subject"].pop(key, None)
        if not requirements["layers"]["style"].get("manual_artist_tags"):
            requirements["layers"]["style"].pop("manual_artist_tags", None)
        if not requirements["layers"]["lighting"].get("mood"):
            requirements["layers"]["lighting"].pop("mood", None)
        composition = requirements["layers"]["composition"]
        design = {key: value for key, value in (composition.get("design") or {}).items() if value is not None}
        if design:
            composition["design"] = design
        else:
            composition.pop("design", None)
    return digest({"requirements": requirements, "mode": draft.get("mode", "faithful"),
                   "model_profile": draft.get("model_profile", "anima_aesthetic_v1"),
                   "compiler_contract": COMPILER_CONTRACT})


def compile_state(draft: dict[str, Any]) -> Literal["missing", "fresh", "stale"]:
    compiled = draft.get("compiled")
    if compiled is None:
        return "missing"
    fingerprint = compiled["inputs_fingerprint"]
    # Existing locked workspaces may carry the pre-normalization fingerprint.
    # Accept it only against the exact current inputs, never against changed text.
    return "fresh" if (fingerprint == inputs_fingerprint(draft)
                       or fingerprint == _inputs_fingerprint(draft, include_edit_controls=True)) else "stale"


def exclusions_fingerprint(requirements: dict[str, Any] | None) -> str:
    exclusions = (requirements or {}).get("layers", {}).get("exclusions")
    if exclusions is not None:
        exclusions = {**exclusions, "locked": False}
    return digest(exclusions)


def validate_prompt_locks(requirements: dict[str, Any] | None, prompt: dict[str, Any] | None) -> None:
    missing = [item for item in (requirements or {}).get("prompt_locks", [])
               if item["text"] not in (prompt or {}).get(item["target"], "")]
    if missing:
        fragments = "；".join(f'{"正向" if item["target"] == "positive" else "负向"}：{item["text"]}' for item in missing)
        raise WorkbenchError("protected_prompt_changed", "固定片段未保留，当前版本未修改：" + fragments
                             + "。请保留这些原文，或先解除对应片段的固定。")


def compile_prompt(draft: dict[str, Any], prompt: PromptEdit, *, source: Literal["llm", "user"]) -> dict:
    from .manual_tags import declared_tags, render_manual_tags
    previous = (draft.get("compiled") or {}).get("manual_tags", [])
    tags = declared_tags(draft.get("requirements")) if source == "llm" else previous
    if source == "llm" and (tags or previous):
        prompt = PromptEdit(positive=render_manual_tags(prompt.positive, tags, previous), negative=prompt.negative)
    validate_prompt_locks(draft.get("requirements"), dump(prompt))
    return dump(CompiledPrompt(**dump(prompt), mode=draft.get("mode", "faithful"), source=source,
                               manual_tags=tags,
                               scene_intent=declared_scene_choices(draft.get("requirements")),
                               exclusions_fingerprint=exclusions_fingerprint(draft.get("requirements")),
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
            raise WorkbenchError("invalid_layer_updates", "模型尝试修改锁定的要求或未知类别；当前版本未修改。请调整修改意见后重试。")
        model = CONTENT_MODELS[name]
        allowed = {field.alias or key for key, field in model.model_fields.items()}
        patch = layer_updates[name]
        if not isinstance(patch, dict) or not patch or not set(patch) <= allowed:
            raise WorkbenchError("invalid_layer_updates", "模型修改了不可自动编辑的字段，或未提供修改内容；当前版本未修改。请重试或更换模型。")
        try:
            # Only known content fields can be omitted and inherited. Control
            # fields, manual tags and scene-design choices are never writable.
            content = {key: result["layers"][name][key] for key in allowed}
            update = dump(model.model_validate({**content, **patch}))
        except ValidationError as exc:
            raise WorkbenchError("invalid_layer_updates", "模型返回的要求内容格式不正确；当前版本未修改。请重试或更换模型。") from exc
        result["layers"][name].update(update)
    return replace_requirements(canonical, RequirementsEdit.model_validate(
        {"layers": result["layers"], "loras": result["loras"], "prompt_locks": result.get("prompt_locks", [])}))


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
        {"layers": target["layers"], "loras": target["loras"], "prompt_locks": target.get("prompt_locks", [])}))


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
    if result["compile_state"] == "stale" and result["compiled"] is not None:
        # Internal replacements (for example adopting a reference's style) also
        # make a prior synchronization receipt obsolete.
        result["compiled"]["requirements_synced"] = False
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
        if "prompt_locks" not in edit and before is not None:
            edit = {**edit, "prompt_locks": dump(before)["prompt_locks"]}
        result["requirements"] = dump(replace_requirements(before, RequirementsEdit.model_validate(edit)))
    if (existing["compiled"] is not None
            and inputs_fingerprint(existing) != inputs_fingerprint(result)):
        # A previous synchronization describes the old requirements only.
        # Lock-only changes are excluded from the fingerprint and keep it valid.
        result["compiled"] = {**result["compiled"], "requirements_synced": False}
    if (current is not None and existing["compiled"] is not None
            and existing["compile_state"] == "fresh"
            and inputs_fingerprint(existing) == inputs_fingerprint(result)):
        # Rebase a validated historical fingerprint when only protection flags
        # change, without changing reviewed text, provenance or compiled token.
        result["compiled"] = {**result["compiled"], "inputs_fingerprint": inputs_fingerprint(result)}
    if (existing["compiled"] is not None
            and existing["compiled"].get("exclusions_fingerprint") in {
                exclusions_fingerprint(existing["requirements"]),
                digest((existing["requirements"] or {}).get("layers", {}).get("exclusions")),
            }
            and exclusions_fingerprint(existing["requirements"]) == exclusions_fingerprint(result["requirements"])):
        result["compiled"] = {**result["compiled"],
                              "exclusions_fingerprint": exclusions_fingerprint(result["requirements"])}
    if "prompt_edit" in incoming:
        if incoming["prompt_edit"] is None:
            raise WorkbenchError("invalid_workspace_edit", "提示词编辑不能为空。")
        prompt = PromptEdit.model_validate(incoming["prompt_edit"])
        previous = result["compiled"]
        if previous is None or any(previous[key] != value for key, value in dump(prompt).items()):
            was_fresh = compile_state(result) == "fresh"
            saved_prompt = compile_prompt(result, prompt, source="user")
            if not was_fresh:
                # Saving text is not validation against changed requirements.
                # Preserve the previous compilation's inputs, or an explicit
                # unmatched marker if this workspace has never been compiled.
                saved_prompt["inputs_fingerprint"] = (previous["inputs_fingerprint"] if previous is not None
                                                       else digest({"uncompiled_manual_prompt": True}))
            result["compiled"] = saved_prompt
    validate_prompt_locks(result.get("requirements"), result.get("compiled"))
    return result
