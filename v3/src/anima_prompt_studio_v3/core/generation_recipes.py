from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from anima_prompt_studio.domain.execution_models import HIRES_FIX_WORKFLOW_KIND, WorkflowProfile
from anima_prompt_studio.domain.models import PromptJob


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

    Values that define a distilled or multi-stage workflow remain fixed.  The
    contract is derived from the actual saved template so V3 never invents a
    second, drifting copy of those values.
    """

    template = _template_parameters(workflow)
    model_profiles = set(workflow.compatible_model_profiles)
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
                "基础阶段与精修阶段使用当前工作流已保存的成套参数；切换普通工作流可进行单阶段调参。",
                "workflow_template",
            )
        ]
        fixed_reason = "这是分阶段工作流的组成参数，必须整套使用，避免界面值与实际节点不一致。"
        capabilities = {
            field: ParameterCapability(mode="fixed", value=getattr(template, field), reason=fixed_reason)
            for field in ("steps", "cfg", "sampler", "scheduler")
        }
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
                "四步蒸馏工作流；步数、CFG、采样器和调度器均由模板锁定。",
                "workflow_template",
            )
        ]
        fixed_reason = "DMDX 蒸馏依赖这组固定参数，普通 Turbo 预设不能覆盖它。"
        capabilities = {
            field: ParameterCapability(mode="fixed", value=getattr(template, field), reason=fixed_reason)
            for field in ("steps", "cfg", "sampler", "scheduler")
        }
        stages = [{"id": "base", "display_name": "蒸馏生成", **template.model_dump(mode="json")}]
    elif is_yume:
        default_recipe_id = "yume_creator"
        creator = RecipeParameters(steps=30, cfg=5.5, sampler="euler_ancestral", scheduler="normal")
        community = RecipeParameters(steps=30, cfg=4.0, sampler="er_sde", scheduler="simple")
        recipes = [
            _recipe("yume_creator", "作者参数基线", "baseline", creator, "30 步、CFG 5.5、Euler a + normal。", "model_guidance"),
            _recipe("yume_community", "社区工作流对照", "creative", community, "用于与现有 ANIMA 社区图做固定 Seed 对照。", "experimental"),
        ]
        capabilities = {
            "steps": ParameterCapability(mode="editable", value=30, minimum=25, maximum=40, reason="模型作者建议 25–40 步。"),
            "cfg": ParameterCapability(mode="editable", value=5.5, minimum=4, maximum=7, reason="模型作者建议 CFG 4–7。"),
            "sampler": ParameterCapability(mode="editable", value="euler_ancestral", options=["euler_ancestral", "euler", "er_sde"], reason="先验证作者配方，再与社区图对照。"),
            "scheduler": ParameterCapability(mode="editable", value="normal", options=["normal", "simple"], reason="调度器与采样器作为成套配方验证。"),
        }
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
        capabilities = {
            "steps": ParameterCapability(mode="fixed", value=30, reason="首轮验证固定 30 步，避免同时改变过多变量。"),
            "cfg": ParameterCapability(mode="editable", value=4.5, minimum=4, maximum=5, reason="模型作者建议 CFG 4–5。"),
            "sampler": ParameterCapability(mode="editable", value="euler", options=["euler", "euler_ancestral", "er_sde"], reason="Euler、Euler a 与社区链分别做固定 Seed 对照。"),
            "scheduler": ParameterCapability(mode="editable", value="normal", options=["normal", "simple"], reason="调度器与采样器作为成套配方验证。"),
        }
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
        capabilities = {
            "steps": ParameterCapability(mode="editable", value=10, minimum=8, maximum=12, reason="Turbo v1.1 推荐范围为 8–12 步。"),
            "cfg": ParameterCapability(mode="fixed", value=1.0, reason="Turbo v1.1 使用 CFG 1。"),
            "sampler": ParameterCapability(mode="editable", value="er_sde", options=["er_sde", "euler"], reason="首轮只比较两套明确配方。"),
            "scheduler": ParameterCapability(mode="editable", value="simple", options=["simple", "normal"], reason="调度器必须与配方同步切换。"),
        }
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
        capabilities = {
            "steps": ParameterCapability(mode="editable", value=10, minimum=8, maximum=12, reason="Turbo 推荐范围为 8–12 步。"),
            "cfg": ParameterCapability(mode="fixed", value=1.0, reason="Turbo 蒸馏模型使用 CFG 1。"),
            "sampler": ParameterCapability(mode="editable", value=template.sampler, options=["er_sde", "euler", "euler_ancestral", "dpmpp_2m_sde_gpu"], reason="采样器代表风格取向，不作为质量等级。"),
            "scheduler": ParameterCapability(mode="fixed", value=template.scheduler, reason="沿用当前已保存工作流的调度器。"),
        }
        stages = [{"id": "base", "display_name": "Turbo 生成", **template.model_dump(mode="json")}]
    else:
        default_recipe_id = "stable_baseline"
        stable = template
        creative = template.model_copy(update={"sampler": "euler"})
        detail = template.model_copy(update={"steps": min(40, max(30, template.steps + 10)), "cfg": 4.5})
        recipes = [
            _recipe("stable_baseline", "稳定基线", "baseline", stable, "忠实使用当前工作流模板，作为可复现基线。", "workflow_template"),
            _recipe("creative_euler", "创意变化", "creative", creative, "Euler 会改变画面取向；它是风格方案，不是更高质量档。", "model_guidance"),
            _recipe("detail_study", "细节实验", "detail_study", detail, "40 步细节实验；需通过固定 Seed 对照后再决定是否升为稳定配方。", "experimental"),
        ]
        capabilities = {
            "steps": ParameterCapability(mode="editable", value=template.steps, minimum=30, maximum=50, reason="Base/Aesthetic 的建议验证范围。"),
            "cfg": ParameterCapability(mode="editable", value=template.cfg, minimum=4, maximum=5, reason="Base/Aesthetic 的建议验证范围。"),
            "sampler": ParameterCapability(mode="editable", value=template.sampler, options=["er_sde", "euler", "euler_ancestral", "dpmpp_2m_sde_gpu"], reason="采样器代表风格取向，不作为质量等级。"),
            "scheduler": ParameterCapability(mode="fixed", value=template.scheduler, reason="沿用当前已保存工作流的调度器。"),
        }
        stages = [{"id": "base", "display_name": "单阶段生成", **template.model_dump(mode="json")}]

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
    contract = build_workflow_recipe_contract(workflow)
    recipes = {item["id"]: item for item in contract["generation_recipes"]}
    recipe_id = job.generation_preset_id
    params = job.generation_params
    requested = {
        "steps": params.steps,
        "cfg": params.cfg,
        "sampler": params.sampler,
        "scheduler": params.scheduler,
    }

    # Old saved workspaces remain loadable, but their V2 tier name has no
    # authority over a V3 workflow.  They are treated as a custom request.
    legacy_or_custom = recipe_id in {"fast", "balanced", "quality", "custom"}
    recipe = recipes.get(recipe_id)
    if recipe is None and not legacy_or_custom:
        raise ValueError(f"配方 {recipe_id} 不适用于工作流 {workflow.display_name}。")
    if recipe is not None and requested != recipe["parameters"]:
        raise ValueError("生成参数已偏离所选配方；请保存为自定义参数后再提交。")

    for field, capability in contract["parameter_capabilities"].items():
        value = requested[field]
        if capability["mode"] == "fixed" and value != capability["value"]:
            raise ValueError(f"工作流固定参数 {field} 必须为 {capability['value']}。")
        minimum = capability.get("minimum")
        maximum = capability.get("maximum")
        if minimum is not None and float(value) < float(minimum):
            raise ValueError(f"参数 {field} 不能低于 {minimum}。")
        if maximum is not None and float(value) > float(maximum):
            raise ValueError(f"参数 {field} 不能高于 {maximum}。")
        options = capability.get("options") or []
        if options and value not in options:
            raise ValueError(f"参数 {field} 不在工作流允许值中。")
