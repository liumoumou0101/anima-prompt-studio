import {readFileSync} from "node:fs";
import {resolve} from "node:path";
import {expect,it} from "vitest";
import {configurationFromSettings,configurationToGenerationPayload,resolveConfiguration,setParameter,settingsFromConfiguration} from "./creationConfiguration";
import {changeGenerationModel,defaultGenerationSettings} from "./generationSettings";
import type {GenerationTarget,WorkbenchGenerationSettings} from "./types";

type Entry={model:string;workflow:string;origin:string;localErrors:string[];target:GenerationTarget};
// Sanitized schema/recipe contracts from every runtime-visible workflow in the
// production catalog. No prompts, connection addresses or credentials are used.
const entries=JSON.parse(readFileSync(resolve("src/test/fixtures/workflowParameterCatalog.json"),"utf8")) as Entry[];
const usable=entries.filter(entry=>!entry.localErrors.length);
const core=["width","height","steps","cfg","sampler","scheduler","seed","batch_size"];
const freshEntries=JSON.parse(readFileSync(resolve("src/test/fixtures/freshModelParameters.json"),"utf8")) as {model:string;settings:WorkbenchGenerationSettings}[];
function initialize(entry:Entry){return configurationFromSettings(defaultGenerationSettings(),entry.model,entry.target,{initialize:true});}

it("covers every usable catalog model/workflow pair and retains malformed imports in the audit",()=>{
  expect(new Set(entries.map(item=>item.workflow)).size).toBe(28);
  expect(new Set(entries.map(item=>item.model)).size).toBe(11);
  expect(entries.filter(item=>item.localErrors.length).length).toBe(9);
});

it.each(usable)("initializes $model / $workflow from its own recipe and keeps a random seed",entry=>{
  const config=initialize(entry),schema=entry.target.parameter_schema!;
  const recipe=entry.target.generation_recipes!.find(item=>item.id===entry.target.default_recipe_id)!;
  const values=resolveConfiguration(config,schema);
  expect(values.errors).toEqual({});
  expect(values.values).toMatchObject(recipe.parameters);
  expect(config.baseRecipeId).toBe(recipe.id);
  expect(config.parameterOverrides).toEqual({});
  expect(config.seedMode).toBe("random");
  expect(values.values.seed).toBe("-1");
  expect(values.values.batch_size).toBe(1);
});

it.each(usable)("round-trips actual payload values for every field in $workflow",entry=>{
  const schema=entry.target.parameter_schema!;
  let config=initialize(entry);
  config={...config,seedMode:"fixed"};
  config=setParameter(config,"seed","9223372036854775807");
  config=setParameter(config,"batch_size",3);
  const persisted=settingsFromConfiguration(config,defaultGenerationSettings(),schema);
  expect(persisted.workflow_parameter_overrides).toEqual({seed:"9223372036854775807",batch_size:3});
  const restored=configurationFromSettings(JSON.parse(JSON.stringify(persisted)),entry.model,entry.target);
  const payload=configurationToGenerationPayload(restored,schema);
  for(const key of core)expect((persisted as unknown as Record<string,unknown>)[key]).toBe((payload as Record<string,unknown>)[key]);
  expect(Object.keys(payload.workflow_parameter_overrides).sort()).toEqual(schema.fields.map(field=>field.key).sort());
});

it.each(usable)("does not change $workflow values when only environment or catalog revision changes",entry=>{
  const config=setParameter(initialize(entry),"batch_size",2);
  const settings=settingsFromConfiguration(config,defaultGenerationSettings(),entry.target.parameter_schema!);
  const other={...entry.target,remote_profile_id:"other-environment",template_revision:"new-catalog-version"};
  const next=configurationFromSettings({...settings,remote_profile_id:other.remote_profile_id},entry.model,other);
  expect(next).toEqual({...config,workflow:{...config.workflow,revision:"new-catalog-version"}});
  expect(resolveConfiguration(next,entry.target.parameter_schema!).values).toEqual(resolveConfiguration(config,entry.target.parameter_schema!).values);
  expect(configurationFromSettings(settings,entry.model,other,{preserveSnapshot:true})).toBe(config);
});

it("uses independent model settings for every ordered transition between usable catalog entries",()=>{
  for(const source of usable)for(const destination of usable){
    if(source.model===destination.model&&source.workflow===destination.workflow)continue;
    const config=setParameter(initialize(source),"seed","9223372036854775807");
    config.resourceRequirements=[{logical_id:"source-only",file_name:"source-only.safetensors",weight:0.8,trigger_words:[],required:true,source:{kind:"user"}}];
    const settings=settingsFromConfiguration(config,defaultGenerationSettings(),source.target.parameter_schema!);
    const next=changeGenerationModel(settings,destination.target,destination.model);
    const switched=next.creation_configuration!;
    const resolved=resolveConfiguration(switched,destination.target.parameter_schema!);
    const recipe=destination.target.generation_recipes!.find(item=>item.id===destination.target.default_recipe_id)!;
    const transition=`${source.model}/${source.workflow} → ${destination.model}/${destination.workflow}`;
    const sameModel=source.model===destination.model;
    expect(resolved.errors,transition).toEqual({});
    expect(resolved.values).toMatchObject(recipe.parameters);
    expect(resolved.values.seed,transition).toBe(sameModel?"9223372036854775807":"-1");
    expect(switched.resourceRequirements,transition).toEqual(sameModel?config.resourceRequirements:[]);
    expect(switched.baseRecipeId).toBe(recipe.id);
    expect(switched.workflow.id).toBe(destination.workflow);
    if(!sameModel){
      const edited=setParameter(switched,"seed","73");
      const submitted=configurationToGenerationPayload(edited,destination.target.parameter_schema!);
      expect(submitted.seed,transition).toBe("73");
      expect(submitted).not.toHaveProperty("model_configurations");
      const destinationSettings=settingsFromConfiguration(edited,next,destination.target.parameter_schema!);
      const back=changeGenerationModel(JSON.parse(JSON.stringify(destinationSettings)),source.target,source.model);
      expect(back.creation_configuration,transition).toEqual(config);
      expect(changeGenerationModel(back,destination.target,destination.model).creation_configuration,transition).toEqual(edited);
    }
  }
});

it.each(usable)("preserves a frozen $workflow snapshot against another currently selected target",entry=>{
  const config=setParameter(initialize(entry),"steps",47);
  const saved=settingsFromConfiguration(config,defaultGenerationSettings(),entry.target.parameter_schema!);
  const other=usable.find(item=>item.workflow!==entry.workflow)!;
  expect(configurationFromSettings(saved,entry.model,other.target,{preserveSnapshot:true})).toEqual(config);
});

it.each(freshEntries)("keeps backend-created $model defaults distinct from manual values across model changes",entry=>{
  expect(entry.settings.creation_configuration?.modelProfile).toBe(entry.model);
  expect(entry.settings.creation_configuration?.parameterOverrides).toEqual({});
  expect(entry.settings.creation_configuration?.seedMode).toBe("random");
  for(const destination of usable){
    const config=changeGenerationModel(entry.settings,destination.target,destination.model).creation_configuration!;
    const resolved=resolveConfiguration(config,destination.target.parameter_schema!);
    const recipe=destination.target.generation_recipes!.find(item=>item.id===destination.target.default_recipe_id)!;
    expect(resolved.values,`${entry.model} -> ${destination.workflow}`).toMatchObject(recipe.parameters);
    expect(resolved.values.seed).toBe("-1");
    expect(config.parameterOverrides).toEqual({});
  }
});
