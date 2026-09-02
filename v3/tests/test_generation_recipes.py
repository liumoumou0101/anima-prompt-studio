from __future__ import annotations

import pytest

from anima_prompt_studio.domain.execution_models import WorkflowBinding, WorkflowProfile
from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio_v3.core.generation_recipes import (
    build_workflow_recipe_contract,
    validate_job_recipe,
)


def workflow(
    *,
    workflow_id: str = "01___Base_Quality_T2I",
    kind: str = "txt2img_basic",
    model: str = "anima_base_v1",
    steps: int = 30,
    cfg: float = 4,
) -> WorkflowProfile:
    api = {
        "3": {"class_type": "KSampler", "inputs": {"steps": steps, "cfg": cfg, "sampler_name": "er_sde", "scheduler": "simple"}},
        "4": {"class_type": "KSampler", "inputs": {"steps": 18, "cfg": 4.5, "sampler_name": "er_sde", "scheduler": "simple", "denoise": 0.35}},
        "5": {"class_type": "LatentUpscale", "inputs": {"upscale_factor": 1.5}},
    }
    fields = {
        "steps": ("3", "steps"), "cfg": ("3", "cfg"),
        "sampler": ("3", "sampler_name"), "scheduler": ("3", "scheduler"),
    }
    if kind == "txt2img_hiresfix_1_5x":
        fields.update({
            "refiner_steps": ("4", "steps"), "refiner_cfg": ("4", "cfg"),
            "refiner_sampler": ("4", "sampler_name"), "refiner_scheduler": ("4", "scheduler"),
            "refiner_denoise": ("4", "denoise"), "upscale_factor": ("5", "upscale_factor"),
        })
    return WorkflowProfile(
        id=workflow_id,
        display_name=workflow_id,
        api_workflow=api,
        bindings={name: WorkflowBinding(node_id=node, input=input_name) for name, (node, input_name) in fields.items()},
        workflow_kind=kind,
        compatible_model_profiles=[model],
    )


def test_base_recipes_keep_template_baseline_and_separate_style_from_detail() -> None:
    contract = build_workflow_recipe_contract(workflow())

    recipes = {item["id"]: item for item in contract["generation_recipes"]}
    assert contract["default_recipe_id"] == "stable_baseline"
    assert recipes["stable_baseline"]["parameters"] == {"steps": 30, "cfg": 4.0, "sampler": "er_sde", "scheduler": "simple"}
    assert recipes["creative_euler"]["objective"] == "creative"
    assert recipes["detail_study"]["evidence"] == "experimental"
    assert contract["parameter_capabilities"]["scheduler"]["mode"] == "fixed"


def test_dmdx_recipe_is_fixed_to_the_saved_four_step_workflow() -> None:
    target = workflow(
        workflow_id="05__DMDX__4_Step_DMDX_Distill",
        model="anima_turbo_v1",
        steps=4,
        cfg=1,
    )
    contract = build_workflow_recipe_contract(target)

    assert contract["default_recipe_id"] == "dmdx_4step"
    assert len(contract["generation_recipes"]) == 1
    assert all(item["mode"] == "fixed" for item in contract["parameter_capabilities"].values())

    job = PromptJob(model_profile_id="anima_turbo_v1", generation_preset_id="custom")
    job.generation_params.steps = 10
    job.generation_params.cfg = 1
    job.generation_params.sampler = "er_sde"
    job.generation_params.scheduler = "simple"
    with pytest.raises(ValueError, match="steps 必须为 4"):
        validate_job_recipe(job, target)


def test_turbo_uses_standard_recipe_as_default_instead_of_fastest_preview() -> None:
    contract = build_workflow_recipe_contract(workflow(
        workflow_id="02___Turbo_Fast_T2I",
        model="anima_turbo_v1",
        steps=12,
        cfg=1,
    ))

    assert contract["default_recipe_id"] == "turbo_standard"


def test_hires_contract_exposes_both_effective_stages() -> None:
    contract = build_workflow_recipe_contract(workflow(kind="txt2img_hiresfix_1_5x", steps=34, cfg=4.5))

    assert contract["default_recipe_id"] == "hires_template"
    assert contract["stages"] == [
        {"id": "base", "display_name": "基础生成", "steps": 34, "cfg": 4.5, "sampler": "er_sde", "scheduler": "simple"},
        {"id": "refiner", "display_name": "精修阶段", "steps": 18, "cfg": 4.5, "sampler": "er_sde", "scheduler": "simple", "denoise": 0.35, "upscale_factor": 1.5},
    ]
