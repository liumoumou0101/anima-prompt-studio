"""Resolve declared LoRAs to exact remote enum values and explicit graph slots."""
from __future__ import annotations

from pydantic import Field
from anima_prompt_studio.domain.execution_models import LoRASlotBinding, WorkflowProfile

from .requirements import ContractModel, RequirementLora, ShortText, digest, dump


class ResourceUnavailable(ValueError):
    def __init__(self, availability, message, *, resources=None):
        self.availability = availability
        self.code = "lora_not_installed" if availability == "missing_lora" else "reference_preset_unavailable"
        self.details = {"availability": availability, "resources": resources or []}
        super().__init__(message)


class MappingConflict(ValueError):
    pass


class LoraBinding(ContractModel):
    logical_id: ShortText
    resource_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    slot_key: str = Field(min_length=1, max_length=300)
    remote_file_name: str = Field(min_length=1, max_length=1000)


class LoraBindingsRequest(ContractModel):
    mapping_revision: int = Field(ge=0)
    workflow_revision: str = Field(min_length=1, max_length=64)
    remote_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    bindings: list[LoraBinding] = Field(max_length=16)


def resource_digest(resource: RequirementLora) -> str:
    if resource.sha256:
        return resource.sha256
    value = dump(resource)
    return digest({key: value[key] for key in ("file_name", "source", "trigger_words")})


def materialize_lora_stack(profile: WorkflowProfile, resources: list[RequirementLora]) -> WorkflowProfile:
    extension = profile._lora_extension
    if extension is None or not resources:
        return profile
    if profile.lora_slots:
        raise ResourceUnavailable("incompatible_workflow", "动态 LoRA 模板包含固定插槽。")
    profile = profile.model_copy(deep=True)
    profile._lora_extension = None
    graph = profile.api_workflow
    model = list(extension.model_source)
    clip = list(extension.clip_source) if extension.clip_source is not None else None
    dual = extension.loader == "LoraLoader"
    if dual != bool(clip and extension.clip_targets):
        raise ResourceUnavailable("incompatible_workflow", "LoRA 文本编码扩展点声明不完整。")
    for targets, source in ((extension.model_targets, model), (extension.clip_targets, clip)):
        for target in targets:
            if graph.get(target.node_id, {}).get("inputs", {}).get(target.input_name) != source:
                raise ResourceUnavailable("incompatible_workflow", "LoRA 扩展点与工作流原接线不匹配。")
    for index, resource in enumerate(resources, 1):
        node_id = f"anima_lora_{index}"
        if node_id in graph:
            raise ResourceUnavailable("incompatible_workflow", "LoRA 扩展节点与工作流原节点冲突。")
        inputs = {"model": model, "lora_name": resource.file_name, "strength_model": resource.weight}
        if dual:
            inputs.update(clip=clip, strength_clip=resource.weight if resource.clip_weight is None else resource.clip_weight)
            clip = [node_id, 1]
        graph[node_id] = {"class_type": extension.loader, "inputs": inputs}
        profile.lora_slots.append(LoRASlotBinding(node_id=node_id, clip_strength_input="strength_clip" if dual else None))
        model = [node_id, 0]
    for targets, source in ((extension.model_targets, model), (extension.clip_targets, clip)):
        for target in targets:
            graph[target.node_id]["inputs"][target.input_name] = source
    profile.runtime_assets["lora_stack"] = "ordered/1"
    return profile


def apply_slot(slot, graph, filename=None, weight=0.0, clip_weight=None):
    inputs = graph[slot.node_id]["inputs"]
    if filename is not None:
        inputs[slot.name_input] = filename
    inputs[slot.model_strength_input] = weight
    if slot.clip_strength_input is not None:
        inputs[slot.clip_strength_input] = weight if clip_weight is None else clip_weight


def slot_choices(profile, info) -> dict[str, list[str]]:
    result = {}
    for slot in profile.lora_slots:
        key = f"{slot.node_id}.{slot.name_input}"
        if key in result:
            raise ResourceUnavailable("incompatible_workflow", "工作流声明了重复 LoRA 插槽。")
        node = profile.api_workflow.get(slot.node_id, {})
        groups = info.get(node.get("class_type"), {}).get("input", {})
        spec = {**groups.get("required", {}), **groups.get("optional", {})}.get(slot.name_input, [])
        values = spec[0] if spec and isinstance(spec[0], list) else []
        result[key] = [value for value in values if isinstance(value, str)]
    return result


def resolve_loras(resources: list[RequirementLora], profile, info, bindings=(), *, mapping_current=True):
    resources = [r for r in resources if r.enabled]
    choices = slot_choices(profile, info)
    if len(resources) > len(choices):
        raise ResourceUnavailable("incompatible_workflow", "所选 LoRA 数量超过工作流插槽数。",
                                  resources=[r.logical_id for r in resources])
    if len({r.logical_id for r in resources}) != len(resources):
        raise ResourceUnavailable("lora_unmapped", "LoRA logical_id 必须唯一。")
    # Even stale explicit bindings must not silently fall back to a default file.
    if resources and bindings and not mapping_current:
        raise ResourceUnavailable("lora_unmapped", "连接或工作流已改变，请重新确认 LoRA 映射。")
    explicit = {(b.logical_id, b.resource_digest): b for b in bindings}
    if len(explicit) != len(bindings):
        raise ResourceUnavailable("lora_unmapped", "LoRA 资源绑定重复。")
    selected, used = {}, set()
    # Reserve ALL explicit slots before assigning automatic ones.
    for resource in resources:
        binding = explicit.get((resource.logical_id, resource_digest(resource)))
        if binding:
            if binding.slot_key not in choices or binding.slot_key in used:
                raise ResourceUnavailable("lora_unmapped", "映射指向不存在或重复占用的插槽。")
            if binding.remote_file_name not in choices[binding.slot_key]:
                raise ResourceUnavailable("missing_lora", "映射文件已不在远端资源列表中。", resources=[resource.logical_id])
            if resource.sha256 and binding.remote_file_name != resource.file_name:
                raise ResourceUnavailable("lora_unmapped", "库 LoRA 的映射文件与声明的 SHA-256 不一致。")
            selected[resource.logical_id] = (binding.slot_key, binding.remote_file_name)
            used.add(binding.slot_key)
    for resource in resources:
        if resource.logical_id in selected:
            continue
        key = next((key for key, files in choices.items() if key not in used and resource.file_name in files), None)
        if key is None:
            state = "lora_unmapped" if any(resource.file_name in files for files in choices.values()) else "missing_lora"
            raise ResourceUnavailable(state, "无法将声明的 LoRA 精确绑定到可用插槽。",
                                      resources=[{"logical_id": resource.logical_id, "resource_digest": resource_digest(resource)}])
        selected[resource.logical_id] = (key, resource.file_name)
        used.add(key)
    result = []
    dual_slots = {f"{slot.node_id}.{slot.name_input}" for slot in profile.lora_slots if slot.clip_strength_input}
    for resource in resources:
        key, file = selected[resource.logical_id]
        item = {"logical_id": resource.logical_id, "resource_digest": resource_digest(resource),
                "slot_key": key, "remote_file_name": file, "weight": resource.weight,
                "trigger_words": resource.trigger_words}
        if resource.sha256:
            item["sha256"] = resource.sha256
        if resource.clip_weight is not None and key in dual_slots:
            item["clip_weight"] = resource.clip_weight
        result.append(item)
    return sorted(result, key=lambda b: list(choices).index(b["slot_key"]))
