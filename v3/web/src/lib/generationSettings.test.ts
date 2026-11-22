import {expect, it} from "vitest";
import {changeGenerationModel, defaultGenerationSettings, seedInput, validSeed} from "./generationSettings";
import {applyRecipe,configurationFromSettings,configurationToGenerationPayload,setParameter,settingsFromConfiguration} from "./creationConfiguration";
import {basicWorkflowSchema} from "./workflowParameterSchema";
import type {GenerationTarget,WorkbenchGenerationSettings} from "./types";

function editSettings(settings:WorkbenchGenerationSettings,patch:Record<string,number|string>){
  let config=settings.creation_configuration || configurationFromSettings(settings,"anima");
  for(const [key,value] of Object.entries(patch))config=setParameter(config,key,value);
  return settingsFromConfiguration(config,settings,settings.parameter_schema||basicWorkflowSchema(""));
}

function requestFromSaved(settings:WorkbenchGenerationSettings){
  const config=configurationFromSettings(settings,settings.creation_configuration?.modelProfile||"anima",undefined,{preserveSnapshot:true});
  return configurationToGenerationPayload(config,settings.parameter_schema||basicWorkflowSchema(config.workflow.id,config.workflow.revision));
}

const target = {
  remote_profile_id: "remote", workflow_profile_id: "workflow", default_recipe_id: "new",
  compatible_model_profiles: ["anima"],
  generation_recipes: [{id: "new", parameters: {steps: 10, cfg: 1, sampler: "er_sde", scheduler: "simple"}}],
} as GenerationTarget;

it("preserves pasted 64-bit seed through settings and request JSON", () => {
  const seed = "8798399215689017476";
  const settings = {...defaultGenerationSettings(), seed: seedInput(seed)};
  expect(JSON.parse(JSON.stringify(requestFromSaved(settings))).seed).toBe(seed);
  expect(seedInput("20260912")).toBe(20260912);
  expect(seedInput("-1")).toBe(-1);
});

it("validates fixed comparison seeds without using floating point", () => {
  expect(validSeed("8798399215689017476", false)).toBe(true);
  expect(validSeed("9223372036854775808", false)).toBe(false);
  expect(validSeed(9007199254740992, false)).toBe(false);
  expect(validSeed("-1", false)).toBe(false);
  expect(validSeed("-1")).toBe(true);
  expect(validSeed("1e9")).toBe(false);
});

it("keeps manual edits when a target is resolved or changed", () => {
  const settings = editSettings(defaultGenerationSettings(), {steps: 47, cfg: 6.25, scheduler: "normal"});
  expect(requestFromSaved(changeGenerationModel(settings, target))).toMatchObject({steps: 47, cfg: 6.25, scheduler: "normal"});
});

it("preserves edits even when an older client left the baseline recipe label", () => {
  const settings = {...defaultGenerationSettings(), steps: 22, cfg: 3.2, seed: "8798399215689017476"};
  expect(changeGenerationModel(settings, target)).toMatchObject({steps: 22, cfg: 3.2, seed: "8798399215689017476"});
});

it("uses recipe values when the user explicitly selects a recipe", () => {
  const settings = editSettings(defaultGenerationSettings(), {steps: 47});
  expect(settingsFromConfiguration(applyRecipe(configurationFromSettings(settings,"anima",target),{id:"new",parameters:{steps:10,cfg:1,sampler:"er_sde",scheduler:"simple"}}),settings,basicWorkflowSchema("workflow"))).toMatchObject({preset_id: "new", steps: 10, cfg: 1});
});

it("preserves saved parameters under an obsolete recipe label", () => {
  const settings = {...defaultGenerationSettings(), preset_id: "quality", workflow_profile_id: "old", steps: 47, cfg: 6.25};
  expect(changeGenerationModel(settings, target)).toMatchObject({steps: 47, cfg: 6.25});
});

it("initializes a fresh target with its V3 default recipe", () => {
  expect(changeGenerationModel(defaultGenerationSettings(), target)).toMatchObject({preset_id: "new", steps: 10, cfg: 1});
});
it("keeps the selected environment when the catalog offers the same workflow elsewhere",()=>{
  const settings=changeGenerationModel(defaultGenerationSettings(),target,"anima");
  const changed=changeGenerationModel(settings,{...target,remote_profile_id:"another"},"anima");
  expect(changed).toEqual(settings);
  expect(changed.creation_configuration).toBe(settings.creation_configuration);
});

it("starts untouched model defaults from the target schema and default recipe",()=>{
  const schema=basicWorkflowSchema("workflow","new");
  schema.fields=schema.fields.map(field=>field.key==="width"?{...field,default:768}:field);
  const settings=changeGenerationModel(defaultGenerationSettings(),{...target,parameter_schema:schema});
  expect(settings).toMatchObject({preset_id:"new",width:768,height:1152,steps:10,cfg:1,sampler:"er_sde",scheduler:"simple",workflow_profile_id:"workflow"});
  expect(requestFromSaved(settings)).toMatchObject({width:768,height:1152,steps:10,cfg:1});
});

it("does not reinitialize default-looking historical settings with saved workflow provenance",()=>{
  const previous={...defaultGenerationSettings(),parameter_schema:basicWorkflowSchema("historical","v1")};
  expect(changeGenerationModel(previous,target)).toMatchObject({steps:35,cfg:4.5,sampler:"euler",scheduler:"normal"});
  expect(changeGenerationModel(previous,target)).toMatchObject({steps:35,cfg:4.5});
});

it("removes the old workflow schema while a changed model has no target",()=>{
  const previous={...defaultGenerationSettings(),workflow_profile_id:"old",parameter_schema:basicWorkflowSchema("old","v1"),workflow_parameter_overrides:{refiner_steps:24}};
  const changed=changeGenerationModel(previous);
  expect(changed.workflow_profile_id).toBeNull();
  expect(changed.parameter_schema).toBeUndefined();
  expect(changed.workflow_parameter_overrides).toMatchObject({refiner_steps:24});
});

it("sends fully resolved workflow values without persisting the baseline as manual overrides",()=>{
  const schema=basicWorkflowSchema("flow","v1");
  schema.fields.push({key:"refiner_steps",label:"精修",type:"integer",default:12,min:1,max:100,group:"workflow"});
  const config=configurationFromSettings(defaultGenerationSettings(),"anima");
  config.recipeValues.refiner_steps=18;
  config.parameterOverrides={height:1280,seed:"9223372036854775807"};
  config.seedMode="fixed";
  const settings=settingsFromConfiguration(config,defaultGenerationSettings(),schema);
  const payload=JSON.parse(JSON.stringify(requestFromSaved(settings)));
  expect(settings.workflow_parameter_overrides).toEqual({height:1280,seed:"9223372036854775807"});
  expect(payload).toMatchObject({width:896,height:1280,seed:"9223372036854775807",workflow_parameter_overrides:{width:896,height:1280,steps:35,cfg:4.5,refiner_steps:18,seed:"9223372036854775807"}});
  const comparison=configurationToGenerationPayload(setParameter(setParameter(config,"seed","8798399215689017476"),"batch_size",2),schema);
  expect(comparison).toMatchObject({seed:"8798399215689017476",batch_size:2,workflow_parameter_overrides:{seed:"8798399215689017476",batch_size:2,refiner_steps:18}});
});

it("keeps legacy model initialization random when the template has seed zero",()=>{
  const schema=basicWorkflowSchema("workflow","new");
  schema.fields=schema.fields.map(field=>field.key==="seed"?{...field,default:"0"}:field);
  const settings=changeGenerationModel(defaultGenerationSettings(),{...target,parameter_schema:schema});
  expect(String(settings.seed)).toBe("-1");
  expect(settings).toMatchObject({batch_size:1,creation_configuration:{seedMode:"random"}});
});

it("reinitializes defaults across workflows within one model while preserving later manual edits",()=>{
  const other={...target,workflow_profile_id:"other",default_recipe_id:"other",generation_recipes:[{id:"other",parameters:{steps:25,cfg:3,sampler:"euler",scheduler:"normal"}}]} as GenerationTarget;
  const first=changeGenerationModel(defaultGenerationSettings(),target);
  const second=changeGenerationModel(first,other);
  expect(second).toMatchObject({steps:25,cfg:3,sampler:"euler",scheduler:"normal"});
  const manual=editSettings(second,{steps:22,seed:"9223372036854775807",batch_size:3});
  const third=changeGenerationModel(manual,target);
  expect(third).toMatchObject({steps:22,cfg:1,sampler:"er_sde",scheduler:"simple",seed:"9223372036854775807",batch_size:3});
});

it("keeps explicit size, seed and batch edits across workflows of the same model",()=>{
  const first=changeGenerationModel(defaultGenerationSettings(),target);
  const manual=editSettings(first,{width:768,height:1280,seed:"9223372036854775807",batch_size:3});
  const other={...target,workflow_profile_id:"other",default_recipe_id:"other",generation_recipes:[{id:"other",parameters:{steps:25,cfg:3,sampler:"euler",scheduler:"normal"}}]} as GenerationTarget;
  const changed=changeGenerationModel(manual,other);
  expect(changed).toMatchObject({width:768,height:1280,seed:"9223372036854775807",batch_size:3,steps:25,cfg:3,
    creation_configuration:{seedMode:"fixed",parameterOverrides:{width:768,height:1280,seed:"9223372036854775807",batch_size:3}}});
});

it("leaves a recorded legacy configuration unbound until a new model target arrives",()=>{
  const first=changeGenerationModel(defaultGenerationSettings(),target);
  const unbound=changeGenerationModel(first);
  expect(unbound.creation_configuration?.workflow).toEqual({id:"",revision:""});
  expect(unbound.parameter_schema).toBeUndefined();
  const other={...target,workflow_profile_id:"other",default_recipe_id:"other",generation_recipes:[{id:"other",parameters:{steps:25,cfg:3,sampler:"euler",scheduler:"normal"}}]} as GenerationTarget;
  expect(changeGenerationModel(unbound,other)).toMatchObject({steps:25,cfg:3,creation_configuration:{workflow:{id:"other"}}});
});

it("rebases a recorded legacy workflow selection while retaining manual edits and the new workflow declaration",()=>{
  const first=changeGenerationModel(defaultGenerationSettings(),target);
  const manual=editSettings(first,{steps:22,seed:"9223372036854775807",batch_size:3});
  const schema=basicWorkflowSchema("workflow-b","b-v1");
  schema.fields.push({key:"refiner_steps",label:"精修",type:"integer",default:18,min:1,max:100,group:"workflow"});
  const other={...target,workflow_profile_id:"workflow-b",template_revision:"b-v1",parameter_schema:schema,default_recipe_id:"b-default",generation_recipes:[{id:"b-default",parameters:{steps:25,cfg:3,sampler:"euler",scheduler:"normal"}}]} as GenerationTarget;
  const changed=changeGenerationModel(manual,other);
  expect(changed).toMatchObject({workflow_profile_id:"workflow-b",steps:22,cfg:3,seed:"9223372036854775807",batch_size:3,
    parameter_schema:{workflowId:"workflow-b",templateRevision:"b-v1"},creation_configuration:{workflow:{id:"workflow-b",revision:"b-v1"},recipeValues:{refiner_steps:18},parameterOverrides:{steps:22,seed:"9223372036854775807",batch_size:3}}});
  expect(requestFromSaved(changed)).toMatchObject({parameter_schema:{workflowId:"workflow-b"},workflow_parameter_overrides:{steps:22,cfg:3,refiner_steps:18,seed:"9223372036854775807",batch_size:3}});
});

it("does not rebase a recorded configuration when a workflow moves to another execution environment",()=>{
  const first=changeGenerationModel(defaultGenerationSettings(),target);
  const manual=editSettings(first,{steps:22,seed:"9223372036854775807",batch_size:3});
  const changed=changeGenerationModel(manual,{...target,remote_profile_id:"another"});
  expect(changed.creation_configuration).toBe(manual.creation_configuration);
  expect(changed.parameter_schema).toBe(manual.parameter_schema);
  expect(changed).toMatchObject({steps:22,seed:"9223372036854775807",batch_size:3});
});

it("does not send the previous schema after an unknown legacy workflow selection",()=>{
  const previous={...defaultGenerationSettings(),workflow_profile_id:"workflow-a",parameter_schema:basicWorkflowSchema("workflow-a","a-v1"),workflow_parameter_overrides:{obsolete_stage:0.4},steps:22};
  const changed=changeGenerationModel(previous,target);
  expect(changed).toMatchObject({steps:22,cfg:4.5,workflow_profile_id:"workflow",parameter_schema:{workflowId:"workflow"},workflow_parameter_overrides:{obsolete_stage:0.4}});
  // Keep the old draft for repair, but do not submit an unsupported parameter.
  expect(()=>requestFromSaved(changed)).toThrow("当前工作流未声明此参数");
});

it("submits the visible configuration when legacy flat caches disagree",()=>{
  const schema=basicWorkflowSchema("flow","v1");
  const config=configurationFromSettings(defaultGenerationSettings(),"anima");
  config.recipeValues={...config.recipeValues,steps:10,cfg:1,width:768,height:1280};
  config.parameterOverrides={seed:"9223372036854775807"};config.seedMode="fixed";
  const settings={...settingsFromConfiguration(config,defaultGenerationSettings(),schema),
    steps:35,cfg:4.5,width:896,height:1152,aspect:"portrait" as const,seed:42,
    workflow_parameter_overrides:{steps:35,cfg:4.5,seed:42}};
  expect(requestFromSaved(settings)).toMatchObject({steps:10,cfg:1,width:768,height:1280,
    seed:"9223372036854775807",workflow_parameter_overrides:{steps:10,cfg:1,width:768,height:1280,seed:"9223372036854775807"}});
});

it("rejects invalid controlled configuration instead of submitting a previous valid flat cache",()=>{
  const schema=basicWorkflowSchema("flow","v1");
  const config=configurationFromSettings(defaultGenerationSettings(),"anima");
  config.parameterOverrides.steps="";
  const settings=settingsFromConfiguration(config,defaultGenerationSettings(),schema);
  expect(settings.steps).toBe(35);
  expect(()=>requestFromSaved(settings)).toThrow("请输入数值");
});

it("does not turn a stale flat cache into manual values during a model switch",()=>{
  const first=changeGenerationModel(defaultGenerationSettings(),target);
  const stale={...first,steps:47,cfg:8,seed:123};
  const other={...target,workflow_profile_id:"other",default_recipe_id:"other",generation_recipes:[{id:"other",parameters:{steps:25,cfg:3,sampler:"euler",scheduler:"normal"}}]} as GenerationTarget;
  const changed=changeGenerationModel(stale,other);
  expect(changed).toMatchObject({steps:25,cfg:3,seed:"-1"});
  expect(changed.creation_configuration?.parameterOverrides).toEqual({});
});

it("keeps independent configurations while moving between models and revisiting after a JSON save",()=>{
  const turboTarget={...target,compatible_model_profiles:["turbo"]};
  const baseTarget={...target,workflow_profile_id:"base-flow",default_recipe_id:"base-recipe",
    compatible_model_profiles:["base"],generation_recipes:[{id:"base-recipe",parameters:{steps:35,cfg:4.5,sampler:"euler",scheduler:"normal"}}]} as GenerationTarget;
  const base=editSettings(changeGenerationModel(defaultGenerationSettings(),baseTarget,"base"),{
    steps:48,cfg:8,width:1344,height:768,batch_size:3,seed:"9223372036854775807",
  });
  const lora={logical_id:"base-lora",file_name:"base.safetensors",weight:0.8,trigger_words:[],required:true,source:{kind:"user" as const}};
  const active={...base,remote_profile_id:"mine",execution_policy:{mode:"pinned" as const,environmentId:"mine"},
    creation_configuration:{...base.creation_configuration!,resourceRequirements:[lora]}};
  const turbo=changeGenerationModel(active,turboTarget,"turbo");
  expect(turbo).toMatchObject({steps:10,cfg:1,width:896,height:1152,batch_size:1,seed:"-1",remote_profile_id:"mine",
    execution_policy:active.execution_policy,creation_configuration:{modelProfile:"turbo",baseRecipeId:"new",seedMode:"random"}});
  expect(turbo.creation_configuration!.parameterOverrides).toEqual({});
  expect(turbo.creation_configuration!.resourceRequirements).toEqual([]);
  expect(turbo.model_configurations).toEqual({base:active.creation_configuration});
  const editedTurbo=editSettings(turbo,{steps:8,batch_size:2});
  const restored=changeGenerationModel(JSON.parse(JSON.stringify(editedTurbo)),baseTarget,"base");
  expect(restored.creation_configuration).toEqual(active.creation_configuration);
  expect(restored.model_configurations).toEqual({turbo:editedTurbo.creation_configuration});
  expect(restored).toMatchObject({steps:48,cfg:8,width:1344,height:768,batch_size:3,seed:"9223372036854775807"});
  const backToTurbo=changeGenerationModel(restored,turboTarget,"turbo");
  expect(backToTurbo.creation_configuration).toEqual(editedTurbo.creation_configuration);
  expect(backToTurbo.model_configurations).toEqual({base:active.creation_configuration});
});

it("assigns an old flat draft to its explicit source model before switching",()=>{
  const legacy={...defaultGenerationSettings(),workflow_profile_id:"old-base-flow",steps:49,seed:"9223372036854775807",batch_size:4};
  const changed=changeGenerationModel(legacy,{...target,compatible_model_profiles:["turbo"]},"turbo","base");
  expect(changed).toMatchObject({steps:10,seed:"-1",batch_size:1,creation_configuration:{modelProfile:"turbo"}});
  expect(changed.model_configurations?.base).toMatchObject({modelProfile:"base",workflow:{id:"old-base-flow"},
    seedMode:"fixed",parameterOverrides:{steps:49,seed:"9223372036854775807",batch_size:4}});
});

it("restores a previously used model's workflow and adopted recipe when its catalog is temporarily unavailable",()=>{
  const savedTarget={...target,workflow_profile_id:"chosen-flow",compatible_model_profiles:["base"]};
  const turboTarget={...target,workflow_profile_id:"turbo-flow",compatible_model_profiles:["turbo"]};
  const initial=changeGenerationModel(defaultGenerationSettings(),savedTarget,"base");
  const adopted=applyRecipe(initial.creation_configuration!,{id:"cloud-suggestion",parameters:{steps:30}});
  const base=settingsFromConfiguration(adopted,initial,initial.parameter_schema!);
  const turbo=changeGenerationModel(base,turboTarget,"turbo","base");
  const offline=changeGenerationModel(turbo,undefined,"base","turbo");
  expect(offline.creation_configuration).toEqual(adopted);
  expect(offline.workflow_profile_id).toBe("chosen-flow");
  expect(offline.parameter_schema).toBeUndefined();
  const restored=changeGenerationModel(offline,savedTarget,"base");
  expect(restored).toMatchObject({workflow_profile_id:"chosen-flow",steps:30,creation_configuration:{
    baseRecipeId:"cloud-suggestion",parameterOverrides:{},recipeValues:{steps:30}}});
});
