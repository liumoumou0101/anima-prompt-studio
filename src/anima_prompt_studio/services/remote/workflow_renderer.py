from __future__ import annotations

import copy
import secrets
from dataclasses import dataclass
from typing import Any

from anima_prompt_studio.domain.execution_models import RemoteProfile, WorkflowBinding, WorkflowProfile
from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio.services.remote.workflow_compatibility import infer_workflow_model_profiles


class WorkflowRenderError(ValueError):
    pass


@dataclass(frozen=True)
class WorkflowRenderResult:
    workflow: dict[str, Any]
    resolved_seed: int
    checkpoint_name: str


class WorkflowRenderer:
    CORE_BINDINGS = {
        "positive_prompt",
        "checkpoint",
        "seed",
        "steps",
        "cfg",
        "sampler",
        "scheduler",
        "width",
        "height",
        "batch_size",
        "filename_prefix",
    }

    def validate_profile(self, profile: WorkflowProfile) -> list[str]:
        errors: list[str] = []
        missing = sorted(self.CORE_BINDINGS - profile.bindings.keys())
        if missing:
            errors.append("缺少工作流绑定：" + ", ".join(missing))
        for field_name, binding in profile.bindings.items():
            node = profile.api_workflow.get(binding.node_id)
            if not isinstance(node, dict):
                errors.append(f"{field_name} 绑定的节点不存在：{binding.node_id}")
                continue
            inputs = node.get("inputs")
            if not isinstance(inputs, dict) or binding.input_name not in inputs:
                errors.append(f"{field_name} 绑定的输入不存在：{binding.node_id}.{binding.input_name}")
        for index, slot in enumerate(profile.lora_slots, 1):
            node = profile.api_workflow.get(slot.node_id)
            if not isinstance(node, dict):
                errors.append(f"LoRA 插槽 {index} 的节点不存在：{slot.node_id}")
                continue
            inputs = node.get("inputs", {})
            for input_name in (slot.name_input, slot.model_strength_input, slot.clip_strength_input):
                if input_name not in inputs:
                    errors.append(f"LoRA 插槽 {index} 的输入不存在：{slot.node_id}.{input_name}")
        return errors

    def render(
        self,
        job: PromptJob,
        workflow_profile: WorkflowProfile,
        remote_profile: RemoteProfile,
        checkpoint_logical_name: str,
        run_id: str,
    ) -> WorkflowRenderResult:
        errors = self.validate_profile(workflow_profile)
        if errors:
            raise WorkflowRenderError("；".join(errors))
        compatible_models = workflow_profile.compatible_model_profiles or infer_workflow_model_profiles(
            workflow_profile.api_workflow,
            workflow_profile.source_path or workflow_profile.display_name or workflow_profile.id,
        )
        if compatible_models and job.model_profile_id not in compatible_models:
            raise WorkflowRenderError(
                f"工作流 {workflow_profile.display_name} 不支持模型配置 {job.model_profile_id}。"
            )

        workflow = copy.deepcopy(workflow_profile.api_workflow)
        seed = job.generation_params.seed
        if seed < 0:
            seed = secrets.randbelow(2**63 - 1)
        checkpoint_binding = workflow_profile.bindings.get("checkpoint")
        template_checkpoint = ""
        if checkpoint_binding is not None:
            template_checkpoint = str(
                workflow.get(checkpoint_binding.node_id, {})
                .get("inputs", {})
                .get(checkpoint_binding.input_name, "")
            )
        checkpoint = remote_profile.model_aliases.get(
            checkpoint_logical_name,
            template_checkpoint or checkpoint_logical_name,
        )
        params = job.generation_params
        values: dict[str, Any] = {
            "positive_prompt": job.positive_prompt,
            "negative_prompt": job.negative_prompt,
            "checkpoint": checkpoint,
            "seed": seed,
            "steps": params.steps,
            "cfg": params.cfg,
            "sampler": params.sampler,
            "scheduler": params.scheduler,
            "width": params.width,
            "height": params.height,
            "batch_size": params.batch_size,
            "filename_prefix": f"Anima_{run_id[:8]}",
        }
        for field_name, value in values.items():
            binding = workflow_profile.bindings.get(field_name)
            if binding is not None:
                self._set_binding(workflow, binding, value)

        if len(job.lora_selection) > len(workflow_profile.lora_slots):
            raise WorkflowRenderError(
                f"当前任务选择了 {len(job.lora_selection)} 个 LoRA，但工作流只有 "
                f"{len(workflow_profile.lora_slots)} 个 LoRA 插槽。"
            )
        for index, slot in enumerate(workflow_profile.lora_slots):
            node_inputs = workflow[slot.node_id]["inputs"]
            if index < len(job.lora_selection):
                selection = job.lora_selection[index]
                lora_name = selection.file_name or selection.logical_id
                node_inputs[slot.name_input] = remote_profile.model_aliases.get(lora_name, lora_name)
                node_inputs[slot.model_strength_input] = selection.weight
                node_inputs[slot.clip_strength_input] = selection.weight
            else:
                # Keep the template's valid filename but neutralize an unused fixed slot.
                node_inputs[slot.model_strength_input] = 0.0
                node_inputs[slot.clip_strength_input] = 0.0

        return WorkflowRenderResult(workflow=workflow, resolved_seed=seed, checkpoint_name=checkpoint)

    @staticmethod
    def _set_binding(workflow: dict[str, Any], binding: WorkflowBinding, value: Any) -> None:
        workflow[binding.node_id]["inputs"][binding.input_name] = value
