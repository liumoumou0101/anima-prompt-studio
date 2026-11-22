import pytest
from anima_prompt_studio_v3.core.workflow_parameters import build_workflow_parameter_schema, resolve_workflow_parameters, ParameterValidationError
from anima_prompt_studio_v3.runtime.packaged_workflows import packaged_workflow_profiles
from anima_prompt_studio.domain.execution_models import HIRES_FIX_WORKFLOW_KIND, WorkflowBinding, RemoteProfile
from anima_prompt_studio_v3.runtime.generation import CandidateToPromptJobAdapter, GenerationSettings
from anima_prompt_studio_v3.core.workflow_compiler import V3WorkflowCompiler
from anima_prompt_studio_v3.runtime.workflow_catalog import apply_mapping
from copy import deepcopy


def test_basic_declaration_has_only_declared_bindings_and_exact_seed():
    profile = next(p for p in packaged_workflow_profiles() if p.id == "v3_base_v1")
    schema = build_workflow_parameter_schema(profile)
    assert {f["key"] for f in schema["fields"]} == {"width","height","steps","cfg","sampler","scheduler","seed","batch_size"}
    result = resolve_workflow_parameters(schema, {"steps":22,"seed":"9223372036854775807"})
    assert result["values"]["seed"] == "9223372036854775807"
    assert result["values"]["steps"] == 22


@pytest.mark.parametrize("overrides", [{"steps":""},{"steps":True},{"steps":201},{"unknown":1},{"cfg":float("nan")},{"seed":"9223372036854775808"}])
def test_resolver_rejects_invalid_inputs(overrides):
    profile = next(p for p in packaged_workflow_profiles() if p.id == "v3_base_v1")
    with pytest.raises(ParameterValidationError):
        resolve_workflow_parameters(build_workflow_parameter_schema(profile), overrides)


def test_readonly_parameter_rejects_override():
    schema = {"version":1,"workflowId":"a","templateRevision":"v1","fields":[{"key":"steps","label":"Steps","type":"integer","default":10,"readOnlyReason":"模板固定"}]}
    with pytest.raises(ParameterValidationError):
        resolve_workflow_parameters(schema, {"steps":11})


def hires_profile():
    profile = next(p for p in packaged_workflow_profiles() if p.id == "v3_base_v1")
    profile.workflow_kind = HIRES_FIX_WORKFLOW_KIND
    profile.api_workflow["refiner"] = deepcopy(profile.api_workflow["7"])
    profile.api_workflow["refiner"]["inputs"].update(steps=18,cfg=4.5,denoise=.35)
    profile.api_workflow["scale"] = {"class_type":"LatentUpscaleBy","inputs":{"scale_by":1.5}}
    for key,name in {"refiner_steps":"steps","refiner_cfg":"cfg","refiner_sampler":"sampler_name","refiner_scheduler":"scheduler","refiner_denoise":"denoise","refiner_seed":"seed"}.items():
        profile.bindings[key] = WorkflowBinding(node_id="refiner",input_name=name)
    profile.bindings["upscale_factor"] = WorkflowBinding(node_id="scale",input_name="scale_by")
    return profile


def test_explicit_two_stage_parameters_reach_compiler_and_freeze_snapshot():
    profile = hires_profile()
    schema = build_workflow_parameter_schema(profile)
    assert len(schema["fields"]) == 14
    settings = GenerationSettings(seed=9223372036854775807,parameter_schema=schema,
        workflow_parameter_overrides={"refiner_steps":24,"refiner_cfg":3.2,"refiner_sampler":"euler","refiner_scheduler":"normal","refiner_denoise":.45,"upscale_factor":2})
    job = CandidateToPromptJobAdapter().prepare_direct(positive_prompt="garden",model_profile_id="anima_base_v1",settings=settings).job
    remote = RemoteProfile(id="test",display_name="test",ssh_host="localhost",ssh_user="test")
    result = V3WorkflowCompiler().render(job,profile,remote,"anima_base_v1","test")
    refiner = result.workflow["refiner"]["inputs"]
    assert (refiner["steps"],refiner["cfg"],refiner["denoise"],refiner["seed"]) == (24,3.2,.45,1)
    assert result.workflow["scale"]["inputs"]["scale_by"] == 2
    frozen = result.metadata["workflow_parameters"]
    assert frozen["values"]["seed"] == "9223372036854775807"
    profile.api_workflow["refiner"]["inputs"]["steps"] = 30
    assert frozen["values"]["refiner_steps"] == 24
    assert resolve_workflow_parameters(frozen["schema"],frozen["overrides"])["values"]["refiner_steps"] == 24


def test_binding_cannot_be_redirected_by_client_and_mapping_keeps_template_revision():
    from anima_prompt_studio_v3.core.workflow_parameters import validate_schema_bindings
    profile = hires_profile()
    schema = build_workflow_parameter_schema(profile)
    mapped = apply_mapping(profile,{})
    validate_schema_bindings(schema,mapped)
    forged = deepcopy(schema)
    forged["fields"][0]["binding"]["input_name"] = "different_input"
    with pytest.raises(ParameterValidationError):
        validate_schema_bindings(forged,mapped)


def test_accepted_parameters_and_rendered_graph_use_the_same_parameter_priority():
    from anima_prompt_studio_v3.core.workflow_parameters import resolve_generation_parameters
    profile = hires_profile()
    schema = build_workflow_parameter_schema(profile)
    overrides = {"steps": 45, "cfg": 9, "seed": "-1", "refiner_steps": 24, "refiner_denoise": .45}
    job = CandidateToPromptJobAdapter().prepare_direct(
        positive_prompt="garden", model_profile_id="anima_base_v1",
        settings=GenerationSettings(steps=22, cfg=3.2, seed=-1,
            parameter_schema=schema, workflow_parameter_overrides=overrides)).job
    before_acceptance = resolve_generation_parameters(profile, job.generation_params, overrides,
                                                      requested_schema=schema)
    assert before_acceptance["values"]["seed"] == "-1"
    # Acceptance freezes the random choice. An older raw -1 override must not undo it.
    job.generation_params.seed = 9223372036854775807
    accepted = resolve_generation_parameters(profile, job.generation_params, overrides,
                                            requested_schema=schema)
    assert accepted["values"]["steps"] == 22
    assert accepted["values"]["cfg"] == 3.2
    assert accepted["values"]["seed"] == "9223372036854775807"
    assert accepted["values"]["refiner_steps"] == 24
    remote = RemoteProfile(id="test", display_name="test", ssh_host="localhost", ssh_user="test")
    rendered = V3WorkflowCompiler().render(job, profile, remote, "anima_base_v1", "test")
    assert rendered.metadata["workflow_parameters"] == accepted
    assert rendered.workflow["7"]["inputs"]["steps"] == 22
    assert rendered.workflow["refiner"]["inputs"]["steps"] == 24
    assert rendered.resolved_seed == 9223372036854775807
    assert overrides["seed"] == "-1"


def test_shared_parameter_resolution_rejects_client_binding_changes():
    from anima_prompt_studio_v3.core.workflow_parameters import resolve_generation_parameters
    profile = hires_profile()
    job = CandidateToPromptJobAdapter().prepare_direct(positive_prompt="garden", model_profile_id="anima_base_v1").job
    schema = build_workflow_parameter_schema(profile)
    schema["fields"][0]["binding"]["input_name"] = "different_input"
    with pytest.raises(ParameterValidationError, match="参数声明与选定工作流版本不一致"):
        resolve_generation_parameters(profile, job.generation_params, {}, requested_schema=schema)


def test_creation_configuration_and_policy_survive_workspace_dto():
    from anima_prompt_studio_v3.api.models import WorkspaceDraft
    values = {"creation_configuration":{"modelProfile":"anima_base_v1","workflow":{"id":"v3_base_v1","revision":"v1"},"baseRecipeId":"stable_baseline","parameterOverrides":{"steps":""},"recipeValues":{"steps":35},"seedMode":"random","resourceRequirements":[]},
              "execution_policy":{"mode":"pinned","environmentId":"cloud-old"},"parameter_schema":{"version":1},"workflow_parameter_overrides":{"refiner_steps":24}}
    payload = WorkspaceDraft(generation_settings=values).persistence_payload()["generation_settings"]
    assert payload["creation_configuration"]["parameterOverrides"]["steps"] == ""
    assert payload["execution_policy"] == values["execution_policy"]
    assert payload["workflow_parameter_overrides"]["refiner_steps"] == 24


def _all_packaged_model_workflow_pairs():
    from anima_prompt_studio_v3.core.model_versions import workflow_models
    return [(profile, model) for profile in packaged_workflow_profiles() for model in workflow_models(profile)]


@pytest.mark.parametrize("profile,model", _all_packaged_model_workflow_pairs(),
                         ids=lambda item: item.id if hasattr(item, "api_workflow") else item)
def test_every_packaged_recipe_reaches_its_actual_workflow_bindings(profile, model):
    from anima_prompt_studio_v3.api.models import DirectPromptSubmitRequest
    from anima_prompt_studio_v3.core.generation_recipes import build_workflow_recipe_contract
    schema = build_workflow_parameter_schema(profile)
    contract = build_workflow_recipe_contract(profile)
    remote = RemoteProfile(id="matrix", display_name="matrix", ssh_host="localhost", ssh_user="test")
    for recipe in contract["generation_recipes"]:
        parameters = recipe["parameters"]
        values = {field["key"]: field["default"] for field in schema["fields"]}
        values.update(parameters, width=768, height=1024, batch_size=2, seed="9223372036854775807")
        request = DirectPromptSubmitRequest.model_validate({
            "positive_prompt": "garden", "model_profile": model,
            "remote_profile_id": "matrix", "workflow_profile_id": profile.id,
            "settings": {"preset_id": recipe["id"], **{key: values[key] for key in
                         ("width", "height", "steps", "cfg", "sampler", "scheduler", "seed", "batch_size")},
                         "parameter_schema": schema, "workflow_parameter_overrides": values},
        })
        settings = GenerationSettings(**request.settings.model_dump())
        job = CandidateToPromptJobAdapter().prepare_direct(positive_prompt="garden", model_profile_id=model,
                                                         settings=settings).job
        rendered = V3WorkflowCompiler().render(job, profile, remote, model, "matrix")
        resolved = rendered.metadata["workflow_parameters"]["values"]
        for field in schema["fields"]:
            if field["key"] == "refiner_seed":
                # Hi-res workflows intentionally derive this from the base seed.
                continue
            binding = field["binding"]
            actual = rendered.workflow[binding["node_id"]]["inputs"][binding["input_name"]]
            assert str(actual) == str(resolved[field["key"]]), (profile.id, model, recipe["id"], field["key"])
        assert rendered.resolved_seed == 9223372036854775807
        assert resolved["batch_size"] == 2
