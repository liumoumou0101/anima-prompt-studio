import {expect, it} from "vitest";
import {applyRecipe, configurationFromSettings, recipeDifferences, resetParameter, resolveConfiguration, settingsFromConfiguration} from "./creationConfiguration";
import {defaultGenerationSettings} from "./generationSettings";
import {basicWorkflowSchema, validateParameter} from "./workflowParameterSchema";
import type {GenerationTarget} from "./types";

const schema = basicWorkflowSchema("flow", "v1");
it("keeps base recipe provenance and field overrides independently of environment policy", () => {
  const config = configurationFromSettings({...defaultGenerationSettings(), steps:22, cfg:3.2}, "anima");
  expect(config.baseRecipeId).toBe("stable_baseline");
  expect(resolveConfiguration(config, schema).values.steps).toBe(22);
  expect(resetParameter(config, "steps").parameterOverrides.steps).toBeUndefined();
});
it("previews recipe differences and applies them as one immutable configuration", () => {
  const config = configurationFromSettings({...defaultGenerationSettings(), steps:22}, "anima");
  const recipe = {id:"fast", parameters:{steps:10,cfg:1,sampler:"euler",scheduler:"normal"}};
  const applied = applyRecipe(config, recipe);
  expect(applied.baseRecipeId).toBe("fast");
  expect(resolveConfiguration(applied,schema).values.steps).toBe(10);
  expect(config.parameterOverrides.steps).toBe(22);
});
it("retains incompatible values for explicit resolution instead of silently replacing", () => {
  const config = configurationFromSettings({...defaultGenerationSettings(), steps:222}, "anima");
  expect(resolveConfiguration(config,schema).errors.steps).toBeTruthy();
  expect(config.parameterOverrides.steps).toBe(222);
});
it("applies only previewed recipe fields while preserving the rest of the baseline and overrides", () => {
  const config = configurationFromSettings(defaultGenerationSettings(), "anima");
  config.recipeValues = {...config.recipeValues,width:1024,height:1024,batch_size:3,seed:"9223372036854775807"};
  config.seedMode = "fixed";
  config.parameterOverrides = {steps:22,height:1280};
  const recipe = {id:"fast",parameters:{steps:10,cfg:1,sampler:"euler",scheduler:"normal"}};
  const before = resolveConfiguration(config,schema).values;
  const differences = recipeDifferences(config,recipe,schema);
  const applied = applyRecipe(config,recipe);
  const after = resolveConfiguration(applied,schema).values;
  expect(Object.keys(after).filter(key=>after[key]!==before[key]).sort()).toEqual(differences.map(item=>item.key).sort());
  expect(after).toMatchObject({width:1024,height:1280,batch_size:3,seed:"9223372036854775807",steps:10,cfg:1});
  expect(applied.parameterOverrides).toEqual({height:1280});
  expect(config.parameterOverrides).toEqual({steps:22,height:1280});
});
it("rejects empty, nonfinite and out of range inputs while keeping decimal seed exact", () => {
  const fields = Object.fromEntries(schema.fields.map(field=>[field.key,field]));
  expect(validateParameter(fields.steps, "")).toBeTruthy();
  expect(validateParameter(fields.steps, NaN)).toBeTruthy();
  expect(validateParameter(fields.steps, 201)).toBeTruthy();
  expect(validateParameter(fields.seed, "9223372036854775807")).toBeUndefined();
  expect(validateParameter(fields.seed, "9223372036854775808")).toBeTruthy();
});
it("keeps invalid drafts without corrupting valid typed settings or execution policy",()=>{
  const previous = {...defaultGenerationSettings(),remote_profile_id:"old",execution_policy:{mode:"pinned" as const,environmentId:"old"}};
  const config = configurationFromSettings(previous,"anima");
  config.parameterOverrides.steps = "";
  const settings = settingsFromConfiguration(config,previous,schema);
  expect(settings.steps).toBe(35);
  expect(settings.creation_configuration?.parameterOverrides.steps).toBe("");
  expect(settings.execution_policy).toEqual(previous.execution_policy);
  expect(settings.remote_profile_id).toBe("old");
});

const turboTarget = {
  remote_profile_id:"turbo-remote", workflow_profile_id:"turbo-flow", template_revision:"turbo-v1",
  default_recipe_id:"turbo-default",
  generation_recipes:[{id:"turbo-default",parameters:{steps:9,cfg:1,sampler:"euler_ancestral",scheduler:"simple"}}],
  parameter_schema:{...basicWorkflowSchema("turbo-flow","turbo-v1"),fields:[
    ...basicWorkflowSchema("turbo-flow","turbo-v1").fields.map(field=>field.key==="width"?{...field,default:768}:field),
    {key:"refiner_steps",label:"精修 Steps",type:"integer",default:12,min:1,max:100,group:"workflow"},
  ]},
} as GenerationTarget;

it("starts an unvisited model with its own defaults even when reading a mismatched active configuration",()=>{
  const previous = defaultGenerationSettings();
  const source = configurationFromSettings(previous,"aesthetic");
  source.parameterOverrides={height:1280,seed:"9223372036854775807",batch_size:3};
  source.seedMode="fixed";
  const config = configurationFromSettings({...previous,creation_configuration:source},"turbo",turboTarget);
  expect(config).toMatchObject({modelProfile:"turbo",workflow:{id:"turbo-flow",revision:"turbo-v1"},baseRecipeId:"turbo-default"});
  expect(config.parameterOverrides).toEqual({});
  expect(resolveConfiguration(config,turboTarget.parameter_schema!).values).toMatchObject({width:768,height:1152,steps:9,cfg:1,sampler:"euler_ancestral",scheduler:"simple",refiner_steps:12,seed:"-1",batch_size:1});
  expect(source.modelProfile).toBe("aesthetic");
  expect(source.recipeValues.steps).toBe(35);
});

it("reads the requested model's own configuration from an opened or imported draft",()=>{
  const previous=defaultGenerationSettings();
  const aesthetic=configurationFromSettings(previous,"aesthetic");
  aesthetic.parameterOverrides={steps:222,cfg:""};
  const turbo=configurationFromSettings(previous,"turbo",turboTarget);
  turbo.parameterOverrides={steps:8};
  const settings={...previous,creation_configuration:aesthetic,model_configurations:{turbo}};
  const config=configurationFromSettings(settings,"turbo",turboTarget);
  expect(config).toBe(turbo);
  expect(configurationFromSettings(settings,"turbo",turboTarget,{preserveSnapshot:true})).toBe(turbo);
  expect(resolveConfiguration(config,turboTarget.parameter_schema!)).toMatchObject({valid:true,values:{steps:8,cfg:1}});
  const mislabeled={...settings,model_configurations:{turbo:aesthetic}};
  expect(configurationFromSettings(mislabeled,"turbo",turboTarget,{preserveSnapshot:true})).toMatchObject({
    modelProfile:"turbo",baseRecipeId:"turbo-default",parameterOverrides:{},seedMode:"random",
  });
});

it("replaces the workflow baseline for the same model without losing incompatible manual values",()=>{
  const previous = defaultGenerationSettings();
  const source = configurationFromSettings(previous,"turbo");
  source.parameterOverrides={steps:222,obsolete_stage:0.4};
  const config = configurationFromSettings({...previous,creation_configuration:source},"turbo",turboTarget);
  const resolved=resolveConfiguration(config,turboTarget.parameter_schema!);
  expect(config.baseRecipeId).toBe("turbo-default");
  expect(config.recipeValues).toMatchObject({steps:9,cfg:1,refiner_steps:12});
  expect(config.parameterOverrides).toEqual({steps:222,obsolete_stage:0.4});
  expect(resolved.valid).toBe(false);
  expect(resolved.errors.steps).toBeTruthy();
  expect(resolved.errors.obsolete_stage).toBeTruthy();
});

it("updates an ordinary workflow revision while keeping its provenance and values on catalog refresh",()=>{
  const source={...configurationFromSettings(defaultGenerationSettings(),"turbo"),workflow:{id:"turbo-flow",revision:"saved-v0"},baseRecipeId:"saved-recipe",recipeValues:{steps:17,cfg:2,sampler:"euler",scheduler:"normal"},parameterOverrides:{width:1024}};
  const settings={...defaultGenerationSettings(),creation_configuration:source};
  const refreshed=configurationFromSettings(settings,"turbo",{...turboTarget,remote_profile_id:"another-remote"});
  expect(refreshed).toEqual({...source,workflow:{id:"turbo-flow",revision:"turbo-v1"}});
  expect(source.workflow.revision).toBe("saved-v0");
  expect(configurationFromSettings(settings,"turbo",turboTarget,{preserveSnapshot:true})).toBe(source);
});

it("updates a legacy ordinary draft to the current declaration while preserving its saved sampling values",()=>{
  const settings={...defaultGenerationSettings(),workflow_profile_id:"turbo-flow",steps:27,cfg:2.5,
    parameter_schema:{...turboTarget.parameter_schema!,templateRevision:"saved-v0"}};
  const current=configurationFromSettings(settings,"turbo",turboTarget);
  expect(current.workflow).toEqual({id:"turbo-flow",revision:"turbo-v1"});
  expect(resolveConfiguration(current,turboTarget.parameter_schema!).values).toMatchObject({steps:27,cfg:2.5});
  expect(configurationFromSettings(settings,"turbo",turboTarget,{preserveSnapshot:true}).workflow.revision).toBe("saved-v0");
});

it("persists only explicit workflow overrides while keeping resolved values in typed settings",()=>{
  const previous=defaultGenerationSettings();
  const config=configurationFromSettings(previous,"anima");
  config.parameterOverrides={steps:22};
  const settings=settingsFromConfiguration(config,previous,schema);
  expect(settings.workflow_parameter_overrides).toEqual({steps:22});
  expect(settings).toMatchObject({steps:22,cfg:4.5,width:896,height:1152});
});

it("does not carry an old workflow baseline into a model without an available target",()=>{
  const source={...configurationFromSettings(defaultGenerationSettings(),"turbo"),workflow:{id:"turbo-flow",revision:"turbo-v1"},recipeValues:{steps:9,cfg:1,refiner_steps:12},parameterOverrides:{seed:"9223372036854775807"},seedMode:"fixed" as const};
  const oldSettings={...defaultGenerationSettings(),workflow_profile_id:"turbo-flow",creation_configuration:source,parameter_schema:turboTarget.parameter_schema};
  const config=configurationFromSettings(oldSettings,"another-model");
  expect(config.workflow).toEqual({id:"",revision:""});
  expect(config.baseRecipeId).toBe("custom");
  expect(config.recipeValues).not.toHaveProperty("refiner_steps");
  const settings=settingsFromConfiguration(config,oldSettings,basicWorkflowSchema(""));
  expect(settings.parameter_schema?.workflowId).toBe("");
  expect(settings.workflow_parameter_overrides).toEqual({});
});

it("initializes untouched defaults from the target schema and its default recipe",()=>{
  const config=configurationFromSettings(defaultGenerationSettings(),"turbo",turboTarget);
  expect(config.baseRecipeId).toBe("turbo-default");
  expect(config.parameterOverrides).toEqual({});
  expect(resolveConfiguration(config,turboTarget.parameter_schema!).values).toMatchObject({width:768,steps:9,cfg:1,sampler:"euler_ancestral",scheduler:"simple",refiner_steps:12});
});

it("initializes a known new draft with an execution preference without guessing from historical values",()=>{
  const settings={...defaultGenerationSettings(),execution_policy:{mode:"auto" as const,preferredEnvironmentIds:[]}};
  const config=configurationFromSettings(settings,"turbo",turboTarget,{initialize:true});
  expect(config.baseRecipeId).toBe("turbo-default");
  expect(config.parameterOverrides).toEqual({});
  expect(config.recipeValues.steps).toBe(9);
});

it("preserves every unknown legacy value even if it matches today's defaults or recipe",()=>{
  const settings={...defaultGenerationSettings(),workflow_profile_id:"turbo-flow",parameter_schema:turboTarget.parameter_schema,workflow_parameter_overrides:{refiner_steps:12}};
  const config=configurationFromSettings(settings,"turbo",turboTarget);
  expect(config.baseRecipeId).toBe("stable_baseline");
  expect(config.parameterOverrides).toMatchObject({width:896,height:1152,steps:35,cfg:4.5,sampler:"euler",scheduler:"normal",seed:-1,batch_size:1,refiner_steps:12});
  expect(config.recipeValues.steps).toBe(35);
  expect(resolveConfiguration(config,turboTarget.parameter_schema!).values).toMatchObject({steps:35,cfg:4.5,refiner_steps:12});
});

it("does not treat a saved custom draft with default-looking values as a new configuration",()=>{
  const config=configurationFromSettings({...defaultGenerationSettings(),preset_id:"custom"},"turbo",turboTarget);
  expect(config.baseRecipeId).toBe("custom");
  expect(config.parameterOverrides).toMatchObject({steps:35,cfg:4.5,width:896,height:1152});
});

it("keeps an exact saved configuration when history requests its frozen snapshot",()=>{
  const source={...configurationFromSettings(defaultGenerationSettings(),"anima"),workflow:{id:"historical-flow",revision:"old"},recipeValues:{steps:24,cfg:3.2,refiner_steps:18},parameterOverrides:{batch_size:2}};
  const config=configurationFromSettings({...defaultGenerationSettings(),creation_configuration:source},"anima",turboTarget,{preserveSnapshot:true});
  expect(config).toBe(source);
});

it("recovers legacy snapshot values from its saved schema without adopting current target provenance",()=>{
  const savedSchema={...basicWorkflowSchema("historical-flow","old"),fields:[...schema.fields,{key:"refiner_steps",label:"精修",type:"integer" as const,default:18,group:"workflow" as const}]};
  const settings={...defaultGenerationSettings(),workflow_profile_id:"historical-flow",parameter_schema:savedSchema,workflow_parameter_overrides:{refiner_steps:24}};
  const config=configurationFromSettings(settings,"anima",turboTarget,{preserveSnapshot:true});
  expect(config.workflow).toEqual({id:"historical-flow",revision:"old"});
  expect(config.parameterOverrides).toMatchObject({steps:35,cfg:4.5,refiner_steps:24});
  expect(config.recipeValues.refiner_steps).toBe(18);
});

it("switches the Aesthetic default to the named Turbo v1.1 baseline rather than the first preview recipe",()=>{
  const target={...turboTarget,default_recipe_id:"turbo_v11_baseline",generation_recipes:[
    {id:"turbo_v11_preview",parameters:{steps:8,cfg:1,sampler:"er_sde",scheduler:"simple"}},
    {id:"turbo_v11_baseline",parameters:{steps:10,cfg:1,sampler:"er_sde",scheduler:"simple"}},
  ]} as GenerationTarget;
  const source=configurationFromSettings(defaultGenerationSettings(),"anima_aesthetic_v1_1");
  const saved=JSON.parse(JSON.stringify(settingsFromConfiguration(source,defaultGenerationSettings(),schema)));
  const config=configurationFromSettings(saved,"anima_turbo_v1_1",target);
  const settings=settingsFromConfiguration(config,saved,target.parameter_schema!);
  expect(config.baseRecipeId).toBe("turbo_v11_baseline");
  expect(config.parameterOverrides).toEqual({});
  expect(settings).toMatchObject({steps:10,cfg:1,sampler:"er_sde",scheduler:"simple"});
});

it("keeps a saved Turbo task whose explicit steps differ from its recipe baseline",()=>{
  const source={...configurationFromSettings(defaultGenerationSettings(),"anima_turbo_v1_1"),workflow:{id:"turbo-flow",revision:"saved-v1"},recipeValues:{steps:25,cfg:4.5},parameterOverrides:{steps:35,cfg:4.5}};
  const config=configurationFromSettings({...defaultGenerationSettings(),creation_configuration:source},"anima_turbo_v1_1",turboTarget);
  expect(config).toEqual({...source,workflow:{id:"turbo-flow",revision:"turbo-v1"}});
  expect(resolveConfiguration(config,turboTarget.parameter_schema!).values).toMatchObject({steps:35,cfg:4.5});
});

it("keeps a new random seed and batch intent when the workflow template defaults to a fixed seed",()=>{
  const target={...turboTarget,parameter_schema:{...turboTarget.parameter_schema!,fields:turboTarget.parameter_schema!.fields.map(field=>field.key==="seed"?{...field,default:"0"}:field.key==="batch_size"?{...field,default:2}:field)}};
  const config=configurationFromSettings(defaultGenerationSettings(),"turbo",target,{initialize:true});
  expect(config.seedMode).toBe("random");
  expect(resolveConfiguration(config,target.parameter_schema).values).toMatchObject({seed:"-1",batch_size:1});
});

it("keeps an explicitly supplied fixed 64-bit seed and batch in a newly initialized draft",()=>{
  const target={...turboTarget,parameter_schema:{...turboTarget.parameter_schema!,fields:turboTarget.parameter_schema!.fields.map(field=>field.key==="seed"?{...field,default:"0"}:field)}};
  const config=configurationFromSettings({...defaultGenerationSettings(),seed:"9223372036854775807",batch_size:3},"turbo",target,{initialize:true});
  expect(config.seedMode).toBe("fixed");
  expect(config.parameterOverrides).toMatchObject({seed:"9223372036854775807",batch_size:3});
  expect(resolveConfiguration(config,target.parameter_schema).values).toMatchObject({seed:"9223372036854775807",batch_size:3});
});
