"""Versioned editable parameters; bindings are explicit node inputs, never paths."""
from __future__ import annotations

from copy import deepcopy
import math
import re

from anima_prompt_studio.domain.execution_models import HIRES_FIX_WORKFLOW_KIND

BASE_FIELDS = {
    "width": ("宽度", "integer", 896, 64, 8192, 8, "common"),
    "height": ("高度", "integer", 1152, 64, 8192, 8, "common"),
    "steps": ("Steps", "integer", 35, 1, 200, 1, "sampling"),
    "cfg": ("CFG", "number", 4.5, 0, 30, .1, "sampling"),
    "sampler": ("Sampler", "string", "euler", None, None, None, "sampling"),
    "scheduler": ("Scheduler", "string", "normal", None, None, None, "sampling"),
    "seed": ("Seed", "seed", "-1", "-1", "9223372036854775807", None, "common"),
    "batch_size": ("张数", "integer", 1, 1, 100, 1, "common"),
}
REFINER_FIELDS = {
    "refiner_steps": ("精修 Steps", "integer", 18, 1, 200, 1, "workflow"),
    "refiner_cfg": ("精修 CFG", "number", 4.5, 0, 30, .1, "workflow"),
    "refiner_sampler": ("精修 Sampler", "string", "euler", None, None, None, "workflow"),
    "refiner_scheduler": ("精修 Scheduler", "string", "normal", None, None, None, "workflow"),
    "refiner_denoise": ("精修降噪", "number", .35, 0, 1, .01, "workflow"),
    "upscale_factor": ("放大倍率", "number", 1.5, 1, 8, .1, "workflow"),
}
ALLOWED_FIELDS = {**BASE_FIELDS, **REFINER_FIELDS}


class ParameterValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("；".join(f"{key}: {value}" for key, value in errors.items()))


def build_workflow_parameter_schema(profile):
    from ..runtime.packaged_workflows import workflow_revision
    definitions = dict(BASE_FIELDS)
    if profile.workflow_kind == HIRES_FIX_WORKFLOW_KIND:
        definitions.update(REFINER_FIELDS)
    fields = []
    for key, (label, kind, default, minimum, maximum, step, group) in definitions.items():
        binding = profile.bindings.get(key)
        # Undeclared complex graph inputs remain template fixed and do not get controls.
        if binding is None:
            continue
        inputs = profile.api_workflow.get(binding.node_id, {}).get("inputs", {})
        if binding.input_name not in inputs:
            raise ParameterValidationError({key:"声明绑定的节点输入不存在"})
        value = inputs[binding.input_name]
        computed = isinstance(value, (list, dict, bool))
        fixed = computed and key not in {"width", "height"}
        if not computed:
            default = str(value) if kind == "seed" else value
        field = {"key":key,"label":label,"type":kind,"default":default,"group":group,
                 "binding":{"node_id":binding.node_id,"input_name":binding.input_name}}
        if minimum is not None:
            field.update(min=minimum, max=maximum)
        if step is not None:
            field["step"] = 16 if key in {"width", "height"} and "moss_image_sft_int8" in profile.compatible_model_profiles else step
        if fixed:
            field["readOnlyReason"] = "该输入由模板节点计算，需在高级 JSON 中修改"
        fields.append(field)
    result = {"version":1,"workflowId":profile.id,"templateRevision":profile.runtime_assets.get("binding_template_revision", workflow_revision(profile)),"fields":fields}
    if profile.workflow_kind == HIRES_FIX_WORKFLOW_KIND:
        result["seedDerivation"] = "第二阶段 Seed = (基础 Seed + 1) mod (2^63 − 1)，沿用派生规则。"
    return result


def resolve_workflow_parameters(schema, overrides):
    """Resolve from an immutable schema snapshot, preserving decimal Seed strings."""
    errors, values = {}, {}
    if schema.get("version") != 1:
        raise ParameterValidationError({"schema":"不支持的参数声明版本"})
    fields = schema.get("fields", [])
    keys = [field.get("key") for field in fields]
    if len(keys) != len(set(keys)) or any(key not in ALLOWED_FIELDS for key in keys):
        raise ParameterValidationError({"schema":"重复或未知参数声明"})
    for key in overrides:
        if key not in keys:
            errors[key] = "工作流未声明此参数"
    for field in fields:
        key, kind = field["key"], field["type"]
        value = overrides.get(key, field["default"])
        if field.get("readOnlyReason") and key in overrides and value != field["default"]:
            errors[key] = field["readOnlyReason"]
        if kind == "seed":
            if isinstance(value, bool) or not re.fullmatch(r"-?\d{1,19}", str(value)):
                errors[key] = "Seed 必须是十进制整数"
            elif not int(field.get("min", -1)) <= int(value) <= int(field.get("max", 2**63-1)):
                errors[key] = "Seed 超出允许范围"
            else:
                value = str(value)
        elif kind == "string":
            if not isinstance(value, str) or not value.strip():
                errors[key] = "必须是非空文本"
            elif field.get("enum") and value not in field["enum"]:
                errors[key] = "模板不支持此选项"
        elif kind in {"integer", "number"}:
            if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value):
                errors[key] = "必须是有效数值"
            elif kind == "integer" and int(value) != value:
                errors[key] = "必须是整数"
            elif value < float(field.get("min", -math.inf)) or value > float(field.get("max", math.inf)):
                errors[key] = "数值超出允许范围"
            elif kind == "integer":
                value = int(value)
        else:
            errors[key] = "不支持的参数类型"
        values[key] = value
    if errors:
        raise ParameterValidationError(errors)
    return {"schemaVersion":schema["version"],"workflowId":schema["workflowId"],"templateRevision":schema["templateRevision"],
            "values":values,"overrides":deepcopy(overrides),"schema":deepcopy(schema)}


def validate_schema_bindings(schema, profile):
    """Untrusted clients cannot redirect bindings or loosen template constraints."""
    expected = build_workflow_parameter_schema(profile)
    if schema != expected:
        raise ParameterValidationError({"schema":"参数声明与选定工作流版本不一致，请重新选择或使用已保存版本"})
    return expected


def resolve_generation_parameters(profile, params, overrides, *, requested_schema=None):
    """Use the same execution values for planning, acceptance, and graph rendering.

    Typed job parameters are the final core values, including a frozen Seed;
    overrides supply workflow-specific inputs such as refiner settings.
    """
    schema = (validate_schema_bindings(requested_schema, profile) if requested_schema
              else build_workflow_parameter_schema(profile))
    return resolve_workflow_parameters(schema, {
        **overrides,
        **{field["key"]: getattr(params, field["key"]) for field in schema["fields"]
           if hasattr(params, field["key"])},
    })
