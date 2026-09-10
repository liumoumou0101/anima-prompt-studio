"""Resolve declared LoRAs to exact remote enum values and explicit graph slots."""
from __future__ import annotations

from pydantic import Field

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
    value = dump(resource)
    return digest({key: value[key] for key in ("file_name", "source", "trigger_words")})


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
    for resource in resources:
        key, file = selected[resource.logical_id]
        result.append({"logical_id": resource.logical_id, "resource_digest": resource_digest(resource),
                       "slot_key": key, "remote_file_name": file, "weight": resource.weight,
                       "trigger_words": resource.trigger_words})
    return sorted(result, key=lambda b: list(choices).index(b["slot_key"]))
