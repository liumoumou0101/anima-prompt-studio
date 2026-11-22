import {expect,it} from "vitest";
import {cloudSuggestionPreview} from "./cloudModelCatalog";
import {configurationFromSettings, configurationToGenerationPayload, setParameter, settingsFromConfiguration} from "./creationConfiguration";
import {defaultGenerationSettings} from "./generationSettings";
import {basicWorkflowSchema} from "./workflowParameterSchema";
import type {CreationConfiguration, GenerationTarget} from "./types";

const configuration:CreationConfiguration={modelProfile:"wai_anima_v1_0",workflow:{id:"flow",revision:"rev1"},baseRecipeId:"custom",recipeValues:{steps:22,cfg:3,sampler:"euler",scheduler:"normal",width:768,height:1024,seed:"9223372036854775807",batch_size:2},parameterOverrides:{width:768},resourceRequirements:[],seedMode:"fixed"};
it("rejects suggestions when the current schema describes another workflow or revision",()=>{
  for(const schema of [basicWorkflowSchema("other","rev1"),basicWorkflowSchema("flow","old"),basicWorkflowSchema("","")]) {
    const result=cloudSuggestionPreview({steps:28},configuration,schema);
    expect(result.errors.length).toBeGreaterThan(0);
    expect(result.changes).toEqual([]);
  }
});
it("applies only sampling suggestions as a custom baseline while retaining other creative state",()=>{
  const schema=basicWorkflowSchema("flow","rev1");
  const result=cloudSuggestionPreview({steps:28,width:2048,seed:"-1",batch_size:9} as never,configuration,schema);
  expect(result.errors).toEqual([]);
  expect(result.configuration).toEqual({...configuration,recipeValues:{...configuration.recipeValues,steps:28},parameterOverrides:{width:768}});
});
it("accepts server enum-checked suggestions with the current template schema that has no enum declaration",()=>{
  const result=cloudSuggestionPreview({sampler:"euler_ancestral",scheduler:"normal"},configuration,basicWorkflowSchema("flow","rev1"));
  expect(result.errors).toEqual([]);
  expect(result.configuration.recipeValues).toMatchObject({sampler:"euler_ancestral",scheduler:"normal"});
  expect(result.configuration.parameterOverrides).toEqual({width:768});
});
it("replaces only explicitly adopted suggestion fields and clears their old manual overrides",()=>{
  const source={...configuration,baseRecipeId:"old-recipe",parameterOverrides:{width:768,height:1280,seed:"9223372036854775807",batch_size:3,steps:19,cfg:6}};
  const result=cloudSuggestionPreview({steps:28},source,basicWorkflowSchema("flow","rev1"));
  expect(result.configuration).toMatchObject({baseRecipeId:"custom",recipeValues:{steps:28,cfg:3},parameterOverrides:{width:768,height:1280,seed:"9223372036854775807",batch_size:3,cfg:6}});
  expect(result.configuration.parameterOverrides).not.toHaveProperty("steps");
  expect(source.parameterOverrides.steps).toBe(19);
});

function targetFor(workflow:string, steps:number, cfg:number, sampler:string, scheduler:string):GenerationTarget {
  return {workflow_profile_id:workflow,template_revision:`${workflow}-v1`,default_recipe_id:`${workflow}-base`,
    generation_recipes:[{id:`${workflow}-base`,parameters:{steps,cfg,sampler,scheduler}}],
    parameter_schema:basicWorkflowSchema(workflow,`${workflow}-v1`)} as GenerationTarget;
}
it.each(["model","workflow"])("replaces model-specific cloud defaults when switching %s", (change) => {
  const aesthetic=targetFor("aesthetic",35,4.5,"euler","normal");
  const turbo=targetFor("turbo",10,1,"er_sde","simple");
  const initial=configurationFromSettings(defaultGenerationSettings(),"aesthetic",aesthetic);
  const cloud=cloudSuggestionPreview({steps:30,cfg:4.5,sampler:"euler",scheduler:"normal"},initial,aesthetic.parameter_schema!).configuration;
  const settings=settingsFromConfiguration(cloud,defaultGenerationSettings(),aesthetic.parameter_schema!);
  const switched=configurationFromSettings(settings,change==="model"?"turbo":"aesthetic",turbo);
  const final=configurationToGenerationPayload(switched,turbo.parameter_schema!);
  expect(switched.recipeValues).toMatchObject({steps:10,cfg:1});
  expect(final).toMatchObject({steps:10,cfg:1,sampler:"er_sde",scheduler:"simple"});
});

it("keeps adopted cloud suggestions and later hand edits with their own model",()=>{
  const first=targetFor("aesthetic",35,4.5,"euler","normal");
  const next=targetFor("turbo",10,1,"er_sde","simple");
  const initial=configurationFromSettings(defaultGenerationSettings(),"aesthetic",first);
  initial.seedMode="fixed";
  initial.parameterOverrides={width:768,height:1280,seed:"9223372036854775807",batch_size:3,steps:19};
  const adopted=cloudSuggestionPreview({steps:30,cfg:4.5,sampler:"euler",scheduler:"normal"},initial,first.parameter_schema!).configuration;
  const manual=setParameter(adopted,"steps",17);
  const settings=settingsFromConfiguration(manual,defaultGenerationSettings(),first.parameter_schema!);
  const switched=configurationFromSettings(settings,"turbo",next);
  expect(configurationToGenerationPayload(switched,next.parameter_schema!)).toMatchObject({
    width:896,height:1152,seed:"-1",batch_size:1,steps:10,cfg:1,sampler:"er_sde",scheduler:"simple"});
  const turbo=settingsFromConfiguration(switched,settings,next.parameter_schema!);
  const restored=configurationFromSettings(turbo,"aesthetic",first);
  expect(restored.recipeValues.steps).toBe(30);
  expect(configurationToGenerationPayload(restored,first.parameter_schema!)).toMatchObject({
    width:768,height:1280,seed:"9223372036854775807",batch_size:3,steps:17,cfg:4.5});
});

it("retains an adopted cloud baseline when only the execution environment changes",()=>{
  const target=targetFor("aesthetic",35,4.5,"euler","normal");
  const initial=configurationFromSettings(defaultGenerationSettings(),"aesthetic",target);
  const adopted=cloudSuggestionPreview({steps:30},initial,target.parameter_schema!).configuration;
  const settings=settingsFromConfiguration(adopted,defaultGenerationSettings(),target.parameter_schema!);
  const moved=configurationFromSettings(settings,"aesthetic",{...target,remote_profile_id:"another"});
  expect(moved).toBe(adopted);
  expect(moved.recipeValues.steps).toBe(30);
  expect(moved.parameterOverrides).not.toHaveProperty("steps");
});
