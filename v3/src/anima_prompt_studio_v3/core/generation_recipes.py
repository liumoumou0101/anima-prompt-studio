from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from anima_prompt_studio.domain.execution_models import HIRES_FIX_WORKFLOW_KIND, WorkflowProfile
from anima_prompt_studio.domain.models import PromptJob
from .runtime_profiles import V3RuntimeProfiles
from .model_versions import workflow_models


class RecipeParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    steps: int = Field(ge=1, le=200)
    cfg: float = Field(ge=0, le=30)
    sampler: str = Field(min_length=1, max_length=100)
    scheduler: str = Field(min_length=1, max_length=100)


class GenerationRecipe(BaseModel):
    """One outcome-oriented recipe for one concrete workflow."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    display_name: str = Field(min_length=1, max_length=100)
    objective: Literal["baseline", "creative", "detail_study", "speed", "hires"]
    parameters: RecipeParameters
    notes: str = Field(default="", max_length=500)
    evidence: Literal["workflow_template", "model_guidance", "experimental"]


class ParameterCapability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["editable", "fixed"]
    value: int | float | str
    reason: str = Field(default="", max_length=300)
    minimum: float | None = None
    maximum: float | None = None
    options: list[str] = Field(default_factory=list)


def _binding_value(workflow: WorkflowProfile, field_name: str, fallback: Any) -> Any:
    binding = workflow.bindings.get(field_name)
    if binding is None:
        return fallback
    return (
        workflow.api_workflow.get(binding.node_id, {})
        .get("inputs", {})
        .get(binding.input_name, fallback)
    )


def _template_parameters(workflow: WorkflowProfile) -> RecipeParameters:
    return RecipeParameters(
        steps=int(_binding_value(workflow, "steps", 30)),
        cfg=float(_binding_value(workflow, "cfg", 4.0)),
        sampler=str(_binding_value(workflow, "sampler", "er_sde")),
        scheduler=str(_binding_value(workflow, "scheduler", "simple")),
    )


def _recipe(
    recipe_id: str,
    display_name: str,
    objective: Literal["baseline", "creative", "detail_study", "speed", "hires"],
    parameters: RecipeParameters,
    notes: str,
    evidence: Literal["workflow_template", "model_guidance", "experimental"],
) -> GenerationRecipe:
    return GenerationRecipe(
        id=recipe_id,
        display_name=display_name,
        objective=objective,
        parameters=parameters,
        notes=notes,
        evidence=evidence,
    )


def build_workflow_recipe_contract(workflow: WorkflowProfile) -> dict[str, object]:
    """Describe effective parameters and compatible recipes for a saved workflow.

    Templates provide structural defaults. Recipes are recommendations;
    every exposed sampling parameter may be explicitly overridden.
    """

    template = _template_parameters(workflow)
    model_profiles = set(workflow_models(workflow))
    workflow_label = f"{workflow.id} {workflow.display_name}".lower()
    is_turbo_v11 = "anima_turbo_v1_1" in model_profiles
    is_yume = "animayume_v1_0_final" in model_profiles
    is_miaomiao = "miaomiao_harem_anima_v1_6" in model_profiles
    is_turbo = bool(model_profiles & {"anima_turbo_v1", "anima_turbo_v1_1"})
    is_dmdx = "dmdx" in workflow_label or (
        "anima_turbo_v1" in model_profiles and template.steps <= 4
    )

    if workflow.workflow_kind == HIRES_FIX_WORKFLOW_KIND:
        default_recipe_id = "hires_template"
        recipes = [
            _recipe(
                "hires_template",
                "1.5× 分阶段精修",
                "hires",
                template,
                "默认使用工作流的分阶段配方；高级参数修改基础阶段，精修阶段沿用模板。",
                "workflow_template",
            )
        ]
        stages = [
            {"id": "base", "display_name": "基础生成", **template.model_dump(mode="json")},
            {
                "id": "refiner",
                "display_name": "精修阶段",
                "steps": int(_binding_value(workflow, "refiner_steps", 18)),
                "cfg": float(_binding_value(workflow, "refiner_cfg", template.cfg)),
                "sampler": str(_binding_value(workflow, "refiner_sampler", template.sampler)),
                "scheduler": str(_binding_value(workflow, "refiner_scheduler", template.scheduler)),
                "denoise": float(_binding_value(workflow, "refiner_denoise", 0.35)),
                "upscale_factor": float(_binding_value(workflow, "upscale_factor", 1.5)),
            },
        ]
    elif is_dmdx:
        default_recipe_id = "dmdx_4step"
        recipes = [
            _recipe(
                "dmdx_4step",
                "DMDX 四步蒸馏",
                "speed",
                template,
                "四步蒸馏工作流；步数、CFG、采样器和调度器默认来自模板，允许手动修改。",
                "workflow_template",
            )
        ]
        stages = [{"id": "base", "display_name": "蒸馏生成", **template.model_dump(mode="json")}]
    elif is_yume:
        default_recipe_id = "yume_creator"
        creator = RecipeParameters(steps=30, cfg=5.5, sampler="euler_ancestral", scheduler="normal")
        community = RecipeParameters(steps=30, cfg=4.0, sampler="er_sde", scheduler="simple")
        recipes = [
            _recipe("yume_creator", "作者参数基线", "baseline", creator, "30 步、CFG 5.5、Euler a + normal。", "model_guidance"),
            _recipe("yume_community", "社区工作流对照", "creative", community, "用于与现有 ANIMA 社区图做固定 Seed 对照。", "experimental"),
        ]
        stages = [{"id": "base", "display_name": "AnimaYume 单阶段", **creator.model_dump(mode="json")}]
    elif is_miaomiao:
        default_recipe_id = "miaomiao_creator"
        creator = RecipeParameters(steps=30, cfg=4.5, sampler="euler", scheduler="normal")
        euler_a = creator.model_copy(update={"sampler": "euler_ancestral"})
        community = creator.model_copy(update={"sampler": "er_sde", "scheduler": "simple"})
        recipes = [
            _recipe("miaomiao_creator", "作者参数基线", "baseline", creator, "shift 3、30 步、CFG 4.5、Euler + normal，并使用专用文本编码器。", "model_guidance"),
            _recipe("miaomiao_euler_a", "Euler a 对照", "creative", euler_a, "作者建议的另一采样器对照。", "model_guidance"),
            _recipe("miaomiao_community", "社区工作流对照", "detail_study", community, "用于确认现有社区采样链是否更适合该模型。", "experimental"),
        ]
        stages = [{"id": "base", "display_name": "MiaoMiao 单阶段", **creator.model_dump(mode="json")}]
    elif is_turbo_v11:
        default_recipe_id = "turbo_v11_baseline"
        baseline = RecipeParameters(steps=10, cfg=1.0, sampler="er_sde", scheduler="simple")
        euler = RecipeParameters(steps=10, cfg=1.0, sampler="euler", scheduler="normal")
        recipes = [
            _recipe("turbo_v11_preview", "Turbo v1.1 快速预览", "speed", baseline.model_copy(update={"steps": 8}), "8 步快速构图预览。", "model_guidance"),
            _recipe("turbo_v11_baseline", "Turbo v1.1 稳定基线", "baseline", baseline, "完整 v1.1 模型，不叠加旧 Turbo LoRA。", "workflow_template"),
            _recipe("turbo_v11_euler", "Euler 对照", "creative", euler, "与 Euler + normal 做固定 Seed 对照。", "experimental"),
            _recipe("turbo_v11_upper", "Turbo v1.1 步数上沿", "detail_study", baseline.model_copy(update={"steps": 12}), "推荐区间上沿。", "model_guidance"),
        ]
        stages = [{"id": "base", "display_name": "Turbo v1.1 单阶段", **baseline.model_dump(mode="json")}]
    elif is_turbo:
        default_recipe_id = "turbo_standard"
        def turbo(steps: int) -> RecipeParameters:
            return template.model_copy(update={"steps": steps, "cfg": 1.0})

        recipes = [
            _recipe("turbo_preview", "Turbo 快速预览", "speed", turbo(8), "8 步快速构图预览。", "model_guidance"),
            _recipe("turbo_standard", "Turbo 标准", "baseline", turbo(10), "10 步标准生成。", "model_guidance"),
            _recipe("turbo_upper", "Turbo 步数上沿", "detail_study", turbo(12), "12 步是推荐区间上沿，不承诺等同于高质量精修。", "model_guidance"),
        ]
        stages = [{"id": "base", "display_name": "Turbo 生成", **template.model_dump(mode="json")}]
    else:
        default_recipe_id = "stable_baseline"
        model_id = next(iter(model_profiles), "")
        if model_id in {"anima_base_v1", "anima_aesthetic_v1", "anima_aesthetic_v1_0", "anima_aesthetic_v1_1"}:
            defaults = V3RuntimeProfiles().get_model(model_id)
            stable = RecipeParameters(steps=defaults.steps, cfg=defaults.cfg, sampler=defaults.sampler, scheduler=defaults.scheduler)
        else:
            stable = template
        creative = stable.model_copy(update={"sampler": "euler"})
        detail = stable.model_copy(update={"steps": min(40, max(30, stable.steps + 10)), "cfg": 4.5})
        recipes = [
            _recipe("stable_baseline", "稳定基线", "baseline", stable, "V3 模型默认配方；手动修改参数后按修改值提交。", "workflow_template"),
            _recipe("creative_euler", "创意变化", "creative", creative, "Euler 会改变画面取向；它是风格方案，不是更高质量档。", "model_guidance"),
            _recipe("detail_study", "细节实验", "detail_study", detail, "40 步细节实验；需通过固定 Seed 对照后再决定是否升为稳定配方。", "experimental"),
        ]
        stages = [{"id": "base", "display_name": "单阶段生成", **stable.model_dump(mode="json")}]

    # Recommended recipe values never constrain explicit user edits.
    defaults = next(r.parameters for r in recipes if r.id == default_recipe_id)
    capabilities = {
        name: ParameterCapability(
            mode="editable", value=getattr(defaults, name),
            minimum=1 if name == "steps" else 0 if name == "cfg" else None,
            maximum=200 if name == "steps" else 30 if name == "cfg" else None,
            options=list(dict.fromkeys([getattr(defaults, name), *(
                ["er_sde", "euler", "euler_ancestral", "dpmpp_2m_sde_gpu"] if name == "sampler"
                else ["normal", "simple", "karras", "exponential", "sgm_uniform", "ddim_uniform", "beta"] if name == "scheduler"
                else []
            )])) if name in {"sampler", "scheduler"} else [],
            reason="配方提供默认值；手动参数优先，服务器校验实际支持情况。",
        ) for name in ("steps", "cfg", "sampler", "scheduler")
    }

    return {
        "default_recipe_id": default_recipe_id,
        "generation_recipes": [item.model_dump(mode="json") for item in recipes],
        "parameter_capabilities": {
            field: capability.model_dump(mode="json")
            for field, capability in capabilities.items()
        },
        "stages": stages,
    }


def validate_job_recipe(job: PromptJob, workflow: WorkflowProfile) -> None:
    # Historical and current recipe labels are provenance, not authority.
    RecipeParameters(
        steps=job.generation_params.steps, cfg=job.generation_params.cfg,
        sampler=job.generation_params.sampler, scheduler=job.generation_params.scheduler,
    )
