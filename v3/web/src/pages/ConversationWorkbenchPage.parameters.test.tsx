import {act, cleanup, fireEvent, render, screen, waitFor, within} from "@testing-library/react";
import {MemoryRouter, useNavigate} from "react-router-dom";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {ConversationWorkbenchPage} from "./ConversationWorkbenchPage";
import {emptyRequirements, localFromRecord, type ConversationRecord} from "../lib/conversation";
import {readConversationDraft} from "../lib/conversationDrafts";
import * as conversationDrafts from "../lib/conversationDrafts";
import {configurationFromSettings, settingsFromConfiguration} from "../lib/creationConfiguration";
import {defaultGenerationSettings} from "../lib/generationSettings";
import {storeDirectImport} from "../lib/directPrompt";
import {basicWorkflowSchema} from "../lib/workflowParameterSchema";
import type {GenerationTarget, WorkbenchGenerationSettings} from "../lib/types";

function targetFor(model:string,id:string,steps:number,cfg:number):GenerationTarget {
  return {remote_profile_id:"cloud",remote_display_name:"测试环境",workflow_profile_id:id,workflow_display_name:id,
    compatible_model_profiles:[model],template_revision:`${id}-v1`,availability:"ready",default_recipe_id:`${id}-default`,
    generation_recipes:[{id:`${id}-default`,parameters:{steps,cfg,sampler:"er_sde",scheduler:"simple"}}],
    parameter_schema:basicWorkflowSchema(id,`${id}-v1`)} as GenerationTarget;
}
const aesthetic=targetFor("anima_aesthetic_v1_1","aesthetic",35,4.5);
const turbo=targetFor("anima_turbo_v1_1","turbo",10,1);
const alternate=targetFor("anima_aesthetic_v1_1","alternate",26,3);
let catalog:GenerationTarget[];
let workspace:ConversationRecord;
let writes:{url:string;body:Record<string,any>}[];
let finishTargets:((value:Response)=>void)|undefined;
let delayTargets:boolean;
let serverSavedPrompt:string|undefined;
function initialized(model:string,target:GenerationTarget):WorkbenchGenerationSettings {
  const defaults=defaultGenerationSettings();
  return settingsFromConfiguration(configurationFromSettings(defaults,model,target,{initialize:true}),defaults,target.parameter_schema!);
}
beforeEach(()=>{
  localStorage.clear();sessionStorage.clear();sessionStorage.setItem("anima-v3-session","parameter-test");
  catalog=[aesthetic,turbo,alternate];writes=[];delayTargets=false;finishTargets=undefined;serverSavedPrompt=undefined;
  workspace={id:"parameter-workspace",title:"参数测试",revision:1,created_at:"2026-10-29",updated_at:"2026-10-29",draft:{
    model_profile:"anima_aesthetic_v1_1",mode:"faithful",positive_text:"",excluded_text:"",
    generation_settings:initialized("anima_aesthetic_v1_1",aesthetic),
    requirements:{...emptyRequirements(),contract:"anima-requirements/1",revision:1},
    compiled:{positive:"cat",negative:"",compiled_token:"compiled",source:"user"},compile_state:"fresh",conversation_events:[],
  }};
  localStorage.setItem("anima-conversation-active",JSON.stringify(workspace.id));
  vi.spyOn(globalThis,"fetch").mockImplementation(async(input,init)=>{
    const url=String(input),body=init?.body?JSON.parse(String(init.body)):undefined;
    if(body&&!url.includes("/checkpoints")&&!url.includes("/editor-context"))writes.push({url,body});
    let response:unknown={items:[]};
    if(url.endsWith("/generation-targets")){
      if(delayTargets)return new Promise(resolve=>{finishTargets=resolve;});
      response={items:catalog};
    }else if(url.endsWith("/artists/recommend"))response={items:[{name:"sample_artist",render_name:"@sample artist",post_count:1234,sources:["cat"],hit_count:1}]};
    else if(url.endsWith("/llm/settings"))response={current:{service:"",model:"",thinking:{mode:"unavailable"}},services:[]};
    else if(url.startsWith("/api/v3/workspaces?"))response={items:[workspace]};
    else if(url.endsWith("/proposal"))response={proposal:null};
    else if(url.endsWith("/editor-context"))response={token:"parameter-context"};
    else if(url==="/api/v3/workspaces"&&init?.method==="POST"){
      workspace={...workspace,id:"new-parameter-workspace",revision:1,title:body.title,draft:{...workspace.draft,...body.draft,compiled:null}};
      response=workspace;
    }else if(url===`/api/v3/workspaces/${workspace.id}`){
      if(init?.method==="PUT")workspace={...workspace,revision:workspace.revision+1,draft:{...workspace.draft,...body.draft,
        ...(body.draft.requirements_edit?{requirements:{...workspace.draft.requirements,...body.draft.requirements_edit}}:{}),
        ...(body.draft.prompt_edit||serverSavedPrompt!==undefined?{compiled:{...workspace.draft.compiled!,...body.draft.prompt_edit,...(serverSavedPrompt!==undefined?{positive:serverSavedPrompt}:{})}}:{})}};
      response=workspace;
    }else if(url==="/api/v3/workbench/generation-source"&&init?.method==="DELETE"){
      workspace={...workspace,revision:workspace.revision+1,draft:{...workspace.draft,generation_source:null}};response=workspace;
    }else if(url.endsWith("/generation-intents"))response={id:"parameter-intent",state:"accepted",run_id:"parameter-run",candidate_progress:{},retryable:false,reason:null,
      response:{id:"parameter-run",state:"draft",workspace_revision:workspace.revision,compiled_token:"accepted"}};
    else if(url.endsWith("/direct-prompt/runs"))response={id:"parameter-run",state:"draft",workspace_revision:workspace.revision,compiled_token:"accepted"};
    return new Response(JSON.stringify(response));
  });
});
afterEach(()=>{cleanup();vi.restoreAllMocks();});
async function mount(workflowId="aesthetic"){
  const view=render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled/></MemoryRouter>);
  await screen.findByLabelText("正向提示词");
  await waitFor(()=>expect(screen.getByLabelText("创作工作流")).toHaveValue(workflowId));
  fireEvent.click(screen.getByRole("button",{name:"生成参数"}));
  return view;
}
function draft(){return readConversationDraft(workspace.id)!.local!;}

it("keeps a library LoRA on the workspace and waits for its environment before generating",async()=>{
  const sha="d".repeat(64),asset={id:sha,sha256:sha,name:"素描",family:"anima",relative_path:"sketch.safetensors",file_name:`anima_library/${sha}.safetensors`,
    size_bytes:1024,model_profiles:[],trigger_words:["sketch"],weight:.85,clip_weight:.2,present:true,valid:true,error:""};
  const original=vi.mocked(fetch).getMockImplementation()!;
  let finish:((r:Response)=>void)|undefined;
  let identityChecks=0;
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    const url=String(input);
    if(url.endsWith("/loras"))return Response.json({items:[asset],root_path:"loras"});
    if(url.endsWith("/cloud/sync"))return new Promise(resolve=>{finish=resolve;});
    if(url.endsWith("/cloud/identity")){identityChecks++;return Response.json({signature:"current"});}
    return original(input,init);
  });
  await mount();
  fireEvent.click(screen.getByRole("button",{name:"从库中选择"}));
  fireEvent.click(await screen.findByRole("button",{name:"添加 素描"}));
  await waitFor(()=>expect(finish).toBeDefined());
  expect(screen.getByRole("button",{name:"生成图片"})).toBeDisabled();
  await act(async()=>{finish!(Response.json({id:"ready",state:"completed",environment_signature:"current",results:[{sha256:sha,cached:true,installed:true}]}));});
  fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await waitFor(()=>expect(writes.some(w=>w.url.endsWith("/generation-intents"))).toBe(true));
  expect(workspace.draft.requirements!.loras[0]).toMatchObject({logical_id:"library:"+sha,weight:.85,clip_weight:.2,trigger_words:["sketch"]});
  const body=writes.find(w=>w.url.endsWith("/generation-intents"))!.body;
  expect(body.source.positive_prompt).toBe("cat");
  expect(body.source).not.toHaveProperty("lora_selection");
  expect(body.creationConfiguration.resourceRequirements).toEqual(workspace.draft.requirements!.loras);
  expect(identityChecks).toBeGreaterThan(0);
},15000);

it("preserves an old foreign-model browser draft without opening it in the ANIMA editor",async()=>{
  await conversationDrafts.initializeConversationTab();
  const original=localFromRecord(workspace);
  const foreign={...original,model:"moss_image_sft_int8",positive:"旧版草稿中的中文原文"};
  expect(conversationDrafts.saveConversationDraft(workspace.id,foreign,original).ok).toBe(true);
  await mount();
  expect(screen.getByLabelText("模型")).toHaveValue(original.model);
  expect(screen.getByLabelText("正向提示词")).toHaveValue(original.positive);
  const backups=conversationDrafts.listConversationDraftCandidates(workspace.id).candidates;
  expect(backups.some(item=>item.kind==="snapshot" && item.local?.positive===foreign.positive)).toBe(true);
});

it("creates model defaults for a direct import that specifies another model without settings",async()=>{
  workspace.draft.generation_settings!.creation_configuration!.parameterOverrides={steps:48,seed:"199"};
  storeDirectImport({positive_text:"",excluded_text:"",english_positive:"quiet garden",english_negative:"",model_profile:"anima_turbo_v1_1"});
  render(<MemoryRouter initialEntries={["/workbench?from=direct"]}><ConversationWorkbenchPage remoteEnabled/></MemoryRouter>);
  await waitFor(()=>expect(writes.some(item=>item.url==="/api/v3/workspaces")).toBe(true));
  const imported = writes.find(item=>item.url==="/api/v3/workspaces")!.body.draft.generation_settings;
  expect(imported.creation_configuration).toMatchObject({modelProfile:"anima_turbo_v1_1",parameterOverrides:{},seedMode:"random"});
  expect(screen.getByLabelText("模型")).toHaveValue("anima_turbo_v1_1");
  fireEvent.click(screen.getByRole("button",{name:"生成参数"}));
  expect(screen.getByLabelText("Steps")).toHaveValue("10");
});
function openIdentity(){fireEvent.click(screen.getByRole("button",{name:/^角色与画师/}));}
function frozenWorkspace(){
  const configuration=workspace.draft.generation_settings!.creation_configuration!;
  configuration.workflow.revision="historical-v1";
  configuration.parameterOverrides={steps:22,cfg:3.2,width:768,height:1024,seed:"9223372036854775807",batch_size:2};
  configuration.seedMode="fixed";
  workspace.draft.generation_settings=settingsFromConfiguration(configuration,{...defaultGenerationSettings(),remote_profile_id:"cloud",execution_policy:{mode:"auto",preferredEnvironmentIds:[]}},
    {...aesthetic.parameter_schema!,templateRevision:"historical-v1"});
  workspace.draft.generation_source={run_id:"historical-run",model_profile:"anima_aesthetic_v1_1",remote_profile_id:"cloud",workflow_profile_id:"aesthetic"};
}

it("uses the same configuration for the summary, validation, saved settings and submission despite stale flat caches",async()=>{
  const settings=workspace.draft.generation_settings!;
  settings.creation_configuration!.seedMode="fixed";
  settings.creation_configuration!.parameterOverrides={width:768,height:1280,batch_size:2,steps:13,seed:"9223372036854775807"};
  settings.seed="-";
  await mount();
  expect(screen.getByLabelText("Seed")).toHaveValue("9223372036854775807");
  expect(screen.getByLabelText("Steps")).toHaveValue("13");
  expect(screen.getByText(/768 × 1280 · 2 张/)).toBeVisible();
  expect(screen.getByRole("button",{name:"生成图片"})).toBeEnabled();
  fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await waitFor(()=>expect(writes.some(item=>item.url.endsWith("/generation-intents"))).toBe(true));
  const expected={width:768,height:1280,batch_size:2,steps:13,seed:"9223372036854775807"};
  expect(workspace.draft.generation_settings).toMatchObject(expected);
  expect(writes.find(item=>item.url.endsWith("/generation-intents"))!.body.source.settings).toMatchObject(expected);
});

it("saves the projected configuration and clears dirty state without keeping an obsolete cache",async()=>{
  workspace.draft.generation_settings!.creation_configuration!.parameterOverrides={width:768,height:1280,steps:13};
  await mount();
  fireEvent.change(screen.getByLabelText("正向提示词"),{target:{value:"adult woman reading a book"}});
  fireEvent.click(screen.getByRole("button",{name:"保存当前版本"}));
  await waitFor(()=>expect(workspace.draft.generation_settings).toMatchObject({width:768,height:1280,steps:13}));
  await waitFor(()=>expect(screen.getByRole("button",{name:"保存当前版本"})).toBeDisabled());
});

it("accepts the backend numeric seed receipt without leaving a saved configuration dirty",async()=>{
  const fetchOriginal=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    const response=await fetchOriginal(input,init);
    if(String(input)===`/api/v3/workspaces/${workspace.id}`&&init?.method==="PUT"){
      workspace.draft.generation_settings!.seed=Number(workspace.draft.generation_settings!.seed);
      return new Response(JSON.stringify(workspace));
    }
    return response;
  });
  const view=await mount();
  fireEvent.change(screen.getByLabelText("Seed"),{target:{value:"-1"}});
  fireEvent.change(screen.getByLabelText("正向提示词"),{target:{value:"adult woman reading a book"}});
  fireEvent.click(screen.getByRole("button",{name:"保存当前版本"}));
  await screen.findByText("当前内容已保存。");
  expect(workspace.draft.generation_settings!.seed).toBe(-1);
  expect(screen.getByRole("button",{name:"保存当前版本"})).toBeDisabled();
  expect(screen.getByLabelText("Seed")).toHaveValue("-1");
  view.unmount();await mount();
  expect(screen.getByRole("button",{name:"保存当前版本"})).toBeDisabled();
  expect(screen.getByLabelText("Seed")).toHaveValue("-1");
});

it("unlocks editing after a normalized save receipt instead of staying dirty or busy",async()=>{
  const fetchOriginal=vi.mocked(fetch).getMockImplementation()!;
  let finishSave:((response:Response)=>void)|undefined;
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    const response=await fetchOriginal(input,init);
    if(String(input)===`/api/v3/workspaces/${workspace.id}`&&init?.method==="PUT"){
      workspace.draft.generation_settings!.seed=Number(workspace.draft.generation_settings!.seed);
      return new Promise(resolve=>{finishSave=resolve;});
    }
    return response;
  });
  await mount();
  fireEvent.change(screen.getByLabelText("Seed"),{target:{value:"-1"}});
  fireEvent.change(screen.getByLabelText("正向提示词"),{target:{value:"adult woman reading a book"}});
  fireEvent.click(screen.getByRole("button",{name:"保存当前版本"}));
  await waitFor(()=>expect(finishSave).toBeDefined());
  expect(screen.getByLabelText("正向提示词")).toBeDisabled();
  await act(async()=>finishSave!(new Response(JSON.stringify(workspace))));
  await screen.findByText("当前内容已保存。");
  expect(screen.getByLabelText("正向提示词")).toHaveValue("adult woman reading a book");
  expect(screen.getByLabelText("正向提示词")).toBeEnabled();
  expect(screen.getByLabelText("Seed")).toBeEnabled();
  expect(draft().settings.seed).toBe(-1);
  expect(screen.getByRole("button",{name:"保存当前版本"})).toBeDisabled();
});

it("keeps the configured workflow when a legacy workflow-id cache disagrees",async()=>{
  workspace.draft.generation_settings!.workflow_profile_id="alternate";
  render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled/></MemoryRouter>);
  await screen.findByLabelText("正向提示词");
  await waitFor(()=>expect(screen.getByLabelText("创作工作流")).toHaveValue("aesthetic"));
  fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await waitFor(()=>expect(writes.some(item=>item.url.endsWith("/generation-intents"))).toBe(true));
  expect(writes.find(item=>item.url.endsWith("/generation-intents"))!.body.creationConfiguration.workflow.id).toBe("aesthetic");
});

it.each([null,"another-cloud"])("keeps execution environment %s when choosing a different workflow",async(environment)=>{
  workspace.draft.generation_settings!.remote_profile_id=environment;
  catalog.push({...aesthetic,remote_profile_id:"another-cloud",remote_display_name:"另一环境"},
    {...alternate,remote_profile_id:"another-cloud",remote_display_name:"另一环境"});
  await mount();
  expect(screen.getByRole("combobox",{name:"执行环境"})).toHaveValue(environment||"auto");
  fireEvent.change(screen.getByLabelText("创作工作流"),{target:{value:"alternate"}});
  expect(screen.getByRole("combobox",{name:"执行环境"})).toHaveValue(environment||"auto");
  fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  const endpoint=environment?"/direct-prompt/runs":"/generation-intents";
  await waitFor(()=>expect(writes.some(item=>item.url.endsWith(endpoint))).toBe(true));
  const request=writes.find(item=>item.url.endsWith(endpoint))!.body;
  expect(environment?request.remote_profile_id:request.executionPolicy.mode).toBe(environment||"auto");
});

it("submits a retained historical snapshot even when only its flat workflow cache is obsolete",async()=>{
  frozenWorkspace();
  workspace.draft.generation_settings!.workflow_profile_id="obsolete-cache";
  catalog=[];
  render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled/></MemoryRouter>);
  await screen.findByLabelText("正向提示词");
  expect(screen.getByRole("button",{name:"生成图片"})).toBeEnabled();
  fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await waitFor(()=>expect(writes.some(item=>item.url.endsWith("/generation-intents"))).toBe(true));
  expect(writes.find(item=>item.url.endsWith("/generation-intents"))!.body).toMatchObject({
    creationConfiguration:{workflow:{id:"aesthetic",revision:"historical-v1"}},source:{workflow_snapshot_run_id:"historical-run"}});
});

it("uses only confirmed parameter edits with the historical workflow",async()=>{
  frozenWorkspace();
  workspace.draft.generation_settings!.workflow_profile_id="obsolete-cache";
  await mount();
  fireEvent.change(screen.getByLabelText("Steps"),{target:{value:"23"}});
  expect(draft().settings.steps).toBe(22);
  fireEvent.click(screen.getByRole("button",{name:"结果"}));
  expect(screen.getByRole("button",{name:"生成图片"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button",{name:"确认生成参数"}));
  expect(screen.getAllByRole("region",{name:"生成参数"}).find(region=>region.classList.contains("conversation-studio__settings"))).toHaveFocus();
  expect(screen.getByLabelText("Steps")).toHaveValue("23");
  fireEvent.click(screen.getByRole("button",{name:"确认应用参数"}));
  expect(screen.getByRole("button",{name:"生成图片"})).toBeEnabled();
  expect(draft().workflowSnapshotRunId).toBe("historical-run");
  expect(draft().settings).toMatchObject({workflow_profile_id:"aesthetic",steps:23,
    creation_configuration:{workflow:{id:"aesthetic",revision:"historical-v1"}},
    parameter_schema:{workflowId:"aesthetic",templateRevision:"historical-v1"}});
  fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await waitFor(()=>expect(writes.some(item=>item.url.endsWith("/generation-intents"))).toBe(true));
  expect(writes.find(item=>item.url.endsWith("/generation-intents"))!.body.source).toMatchObject({
    workflow_snapshot_run_id:"historical-run",settings:{steps:23,parameter_schema:{templateRevision:"historical-v1"}}});
  expect(writes.some(item=>item.url==="/api/v3/workbench/generation-source")).toBe(false);
});

it("submits a manually entered random seed and blocks incomplete seed edits in ANIMA",async()=>{
  await mount();
  const seed=screen.getByLabelText("Seed");
  expect(seed).toBeEnabled();
  fireEvent.change(seed,{target:{value:"8798399215689017476"}});
  fireEvent.change(seed,{target:{value:"-"}});
  expect(seed).toHaveValue("-");
  expect(screen.getByRole("button",{name:"生成图片"})).toBeDisabled();
  expect(writes.some(item=>item.url.endsWith("/generation-intents"))).toBe(false);
  fireEvent.change(seed,{target:{value:"-1"}});
  fireEvent.blur(seed);
  expect(seed).toHaveValue("-1");
  fireEvent.click(screen.getByRole("button",{name:"确认应用参数"}));
  expect(draft().settings.creation_configuration).toMatchObject({seedMode:"random",parameterOverrides:{seed:"-1"}});
  expect(screen.getByRole("button",{name:"生成图片"})).toBeEnabled();
  fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await waitFor(()=>expect(writes.some(item=>item.url.endsWith("/generation-intents"))).toBe(true));
  expect(writes.find(item=>item.url.endsWith("/generation-intents"))!.body).toMatchObject({creationConfiguration:{seedMode:"random"},source:{settings:{seed:"-1"}}});
});

it("accepts an existing fixed-mode -1 draft on first load without requiring a seed edit",async()=>{
  const configuration=workspace.draft.generation_settings!.creation_configuration!;
  configuration.seedMode="fixed";
  configuration.parameterOverrides.seed="-1";
  await mount();
  expect(screen.getByLabelText("Seed")).toHaveValue("-1");
  expect(screen.getByText(/-1 表示每次新生成随机/)).toBeInTheDocument();
  expect(screen.getByRole("button",{name:"生成图片"})).toBeEnabled();
  fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await waitFor(()=>expect(writes.some(item=>item.url.endsWith("/generation-intents"))).toBe(true));
  expect(writes.find(item=>item.url.endsWith("/generation-intents"))!.body.source.settings.seed).toBe("-1");
});

it("opens hidden invalid generation parameters from the disabled generation action without editing or submitting",async()=>{
  workspace.draft.generation_settings!.creation_configuration!.parameterOverrides.steps="";
  await mount();
  const prompt=screen.getByLabelText("正向提示词");
  const originalDraft=JSON.stringify(draft());
  fireEvent.click(screen.getByRole("button",{name:"结果"}));
  expect(screen.getByLabelText("Steps")).not.toBeVisible();
  expect(screen.getByRole("button",{name:"生成图片"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button",{name:"查看无效参数"}));
  expect(screen.getByRole("button",{name:"生成参数"})).toHaveAttribute("aria-pressed","true");
  expect(screen.getByLabelText("Steps")).toBeVisible();
  expect(screen.getByLabelText("Steps")).toHaveValue("");
  expect(screen.getByLabelText("Steps")).toHaveAttribute("aria-invalid","true");
  expect(prompt).toHaveValue("cat");
  expect(JSON.stringify(draft())).toBe(originalDraft);
  expect(writes).toEqual([]);
  fireEvent.click(screen.getByRole("button",{name:"结果"}));
  fireEvent.click(screen.getByRole("button",{name:"查看无效参数"}));
  expect(screen.getByLabelText("Steps")).toBeVisible();
});

it("creates a new draft with its initial model's recipe before the POST",async()=>{
  localStorage.removeItem("anima-conversation-active");
  render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled modelProfiles={[{id:"anima_turbo_v1_1",display_name:"Turbo",variant:"turbo"}]}/></MemoryRouter>);
  await act(async()=>{});
  fireEvent.click(await screen.findByRole("button",{name:"直接编写提示词"}));
  await screen.findByLabelText("正向提示词");
  const creation=writes.find(item=>item.url==="/api/v3/workspaces")!;
  expect(creation.body.draft).toMatchObject({model_profile:"anima_turbo_v1_1",generation_settings:{steps:10,cfg:1,sampler:"er_sde",scheduler:"simple",creation_configuration:{baseRecipeId:"turbo-default",parameterOverrides:{}}}});
});

it("rebases the workflow recipe while retaining explicitly edited fields",async()=>{
  await mount();
  fireEvent.change(screen.getByLabelText("CFG"),{target:{value:"7"}});
  fireEvent.click(screen.getByRole("button",{name:"确认应用参数"}));
  fireEvent.change(screen.getByLabelText("创作工作流"),{target:{value:"alternate"}});
  expect(screen.getByLabelText("Steps")).toHaveValue("26");
  expect(screen.getByLabelText("CFG")).toHaveValue("7");
  expect(draft().settings.creation_configuration).toMatchObject({baseRecipeId:"alternate-default",recipeValues:{steps:26,cfg:3},parameterOverrides:{cfg:7}});
});

it("remembers each model's selected workflow, manual settings and LoRAs through save, reopen and submission",async()=>{
  const aModel="anima_aesthetic_v1_1",tModel="anima_turbo_v1_1";
  const alternateTurbo=targetFor(tModel,"turbo-custom",8,1.25);
  catalog.push(alternateTurbo);
  const aFields={宽度:"768",高度:"1280",张数:"3",Steps:"29",CFG:"7",Sampler:"dpmpp_2m",Scheduler:"karras",Seed:"8765432109876543210"};
  const tDefaults={宽度:"896",高度:"1152",张数:"1",Steps:"10",CFG:"1",Sampler:"er_sde",Scheduler:"simple",Seed:"-1"};
  const tFields={宽度:"704",高度:"1344",张数:"2",Steps:"9",CFG:"1.3",Sampler:"euler",Scheduler:"normal",Seed:"72"};
  const lora={logical_id:"aesthetic-only",file_name:"aesthetic-only.safetensors",weight:0.75,trigger_words:[],required:true,source:{kind:"user" as const}};
  const policy={mode:"auto" as const,preferredEnvironmentIds:["cloud"]};
  const positive="@studio painter, traveler, adult reading a book",negative="blur";
  workspace.draft.generation_settings!.execution_policy=policy;
  workspace.draft.requirements!.layers.subject.character_tags=["traveler"];
  workspace.draft.requirements!.layers.style.manual_artist_tags=["studio painter"];
  workspace.draft.requirements!.loras=[lora];
  workspace.draft.compiled={...workspace.draft.compiled!,positive,negative};
  const view=await mount();
  const change=(label:string,value:string)=>fireEvent.change(screen.getByLabelText(label),{target:{value}});
  const check=(fields:Record<string,string>)=>{for(const [label,value] of Object.entries(fields))expect(screen.getByLabelText(label),label).toHaveValue(value);};
  const sharedInputs=()=>{
    expect(screen.getByLabelText("正向提示词")).toHaveValue(positive);
    expect(screen.getByLabelText("负向提示词")).toHaveValue(negative);
    expect(draft().requirements.layers.subject.character_tags).toEqual(["traveler"]);
    expect(draft().requirements.layers.style.manual_artist_tags).toEqual(["studio painter"]);
    expect(draft().settings.execution_policy).toEqual(policy);
  };
  change("创作工作流","alternate");
  for(const [label,value] of Object.entries(aFields))change(label,value);
  fireEvent.click(screen.getByRole("button",{name:"确认应用参数"}));
  change("模型",tModel);
  check(tDefaults);
  expect(screen.getByLabelText("种子模式")).toHaveValue("random");
  expect(draft().requirements.loras).toEqual([]);
  sharedInputs();
  change("创作工作流",alternateTurbo.workflow_profile_id);
  for(const [label,value] of Object.entries(tFields))change(label,value);
  fireEvent.click(screen.getByRole("button",{name:"确认应用参数"}));
  change("模型",aModel);
  check(aFields);
  expect(screen.getByLabelText("创作工作流")).toHaveValue("alternate");
  expect(draft().requirements.loras).toEqual([lora]);
  change("模型",tModel);
  check(tFields);
  expect(screen.getByLabelText("创作工作流")).toHaveValue(alternateTurbo.workflow_profile_id);
  fireEvent.click(screen.getByRole("button",{name:"保存当前版本"}));
  await screen.findByText("当前内容已保存。");
  expect(workspace.draft.requirements!.loras).toEqual([]);
  // Reopen using only the workspace returned by the server.
  view.unmount();localStorage.clear();sessionStorage.clear();
  localStorage.setItem("anima-conversation-active",JSON.stringify(workspace.id));
  sessionStorage.setItem("anima-v3-session","parameter-test");
  await mount(alternateTurbo.workflow_profile_id);
  check(tFields);
  change("模型",aModel);
  check(aFields);
  expect(screen.getByLabelText("创作工作流")).toHaveValue("alternate");
  expect(draft().requirements.loras).toEqual([lora]);
  change("模型",tModel);
  check(tFields);
  sharedInputs();
  expect(draft().requirements.loras).toEqual([]);
  fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await waitFor(()=>expect(writes.some(item=>item.url.endsWith("/generation-intents"))).toBe(true));
  const request=writes.find(item=>item.url.endsWith("/generation-intents"))!.body;
  expect(request).toMatchObject({executionPolicy:policy,creationConfiguration:{modelProfile:tModel,workflow:{id:alternateTurbo.workflow_profile_id}},
    source:{model_profile:tModel,positive_prompt:positive,negative_prompt:negative,settings:{width:704,height:1344,batch_size:2,steps:9,cfg:1.3,sampler:"euler",scheduler:"normal",seed:"72"}}});
  const outgoing=JSON.stringify(request);
  for(const inactive of [aModel,"alternate-default",aFields.Seed,lora.file_name])expect(outgoing).not.toContain(inactive);
  expect(request.source.settings).not.toHaveProperty("model_configurations");
  expect(workspace.draft.requirements!.loras).toEqual([]);
},15000);

it("replaces adopted cloud sampling defaults with the new model's recipe in the final generation request",async()=>{
  const original=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,init)=>String(input).endsWith("/model-catalog")
    ?new Response(JSON.stringify({remote_profile_id:"cloud",session_id:"catalog-test",environment_epoch:1,status:"ready",checked_at:null,message:"",runtime_id:null,
      items:[{id:"anima_aesthetic_v1_1",display_name:"Aesthetic",family:"anima",supported:true,ready:true,selected_for_startup:false,
        suggested_defaults:{steps:30,cfg:4.5,sampler:"euler",scheduler:"normal"},assets:[],workflow_mappings:[]}]}))
    :original(input,init));
  await mount();
  fireEvent.change(screen.getByRole("combobox",{name:"执行环境"}),{target:{value:"cloud"}});
  const adopt=await screen.findByRole("button",{name:"应用云端建议参数"});
  await waitFor(()=>expect(adopt).toBeEnabled());
  fireEvent.click(adopt);
  expect(screen.getByLabelText("Steps")).toHaveValue("30");
  fireEvent.change(screen.getByLabelText("模型"),{target:{value:"anima_turbo_v1_1"}});
  expect(screen.getByLabelText("Steps")).toHaveValue("10");
  expect(screen.getByLabelText("CFG")).toHaveValue("1");
  fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await waitFor(()=>expect(writes.some(item=>item.url.endsWith("/direct-prompt/runs"))).toBe(true));
  expect(writes.find(item=>item.url.endsWith("/direct-prompt/runs"))!.body).toMatchObject({model_profile:"anima_turbo_v1_1",workflow_profile_id:"turbo",
    settings:{steps:10,cfg:1,sampler:"er_sde",scheduler:"simple"}});
});

it("creates an unbound baseline before the catalog arrives and adopts the later target without manual default pollution",async()=>{
  delayTargets=true;localStorage.removeItem("anima-conversation-active");
  render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled modelProfiles={[{id:"anima_turbo_v1_1",display_name:"Turbo",variant:"turbo"}]}/></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button",{name:"直接编写提示词"}));
  await screen.findByLabelText("正向提示词");
  const creation=writes.find(item=>item.url==="/api/v3/workspaces")!;
  expect(creation.body.draft.generation_settings.creation_configuration).toMatchObject({workflow:{id:"",revision:""},parameterOverrides:{}});
  await act(async()=>finishTargets!(new Response(JSON.stringify({items:catalog}))));
  fireEvent.click(screen.getByRole("button",{name:"生成参数"}));
  await waitFor(()=>expect(screen.getByLabelText("Steps")).toHaveValue("10"));
  fireEvent.change(screen.getByLabelText("CFG"),{target:{value:"2"}});
  fireEvent.click(screen.getByRole("button",{name:"确认应用参数"}));
  expect(draft().settings.creation_configuration?.parameterOverrides).toEqual({cfg:2});
});

it("reads a frozen saved configuration without rebasing it to an available binding",async()=>{
  const settings=workspace.draft.generation_settings!;
  settings.creation_configuration!.workflow={id:"historical-flow",revision:"historical-v1"};
  settings.creation_configuration!.recipeValues={...settings.creation_configuration!.recipeValues,steps:22,cfg:3.2};
  settings.parameter_schema={...aesthetic.parameter_schema!,workflowId:"historical-flow",templateRevision:"historical-v1"};
  settings.execution_policy={mode:"pinned",environmentId:"cloud"};
  workspace.draft.generation_source={run_id:"historical-run",model_profile:"anima_aesthetic_v1_1",remote_profile_id:"cloud",workflow_profile_id:"aesthetic"};
  await mount("historical-flow");
  expect(screen.getByLabelText("Steps")).toHaveValue("22");
  expect(screen.getByLabelText("CFG")).toHaveValue("3.2");
});

it("submits a historical image with its saved schema and exact sampling values",async()=>{
  const settings=workspace.draft.generation_settings!;
  settings.creation_configuration!.workflow.revision="historical-v1";
  settings.creation_configuration!.recipeValues={...settings.creation_configuration!.recipeValues,steps:22,cfg:3.2};
  settings.steps=22;settings.cfg=3.2;
  settings.parameter_schema={...aesthetic.parameter_schema!,templateRevision:"historical-v1"};
  settings.execution_policy={mode:"pinned",environmentId:"cloud"};
  workspace.draft.generation_source={run_id:"historical-run",model_profile:"anima_aesthetic_v1_1",remote_profile_id:"cloud",workflow_profile_id:"aesthetic"};
  await mount();
  fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await waitFor(()=>expect(writes.some(item=>item.url.endsWith("/generation-intents"))).toBe(true));
  const request=writes.find(item=>item.url.endsWith("/generation-intents"))!.body;
  expect(request).toMatchObject({executionPolicy:{mode:"pinned",environmentId:"cloud"},source:{workflow_snapshot_run_id:"historical-run",settings:{steps:22,cfg:3.2,parameter_schema:{workflowId:"aesthetic",templateRevision:"historical-v1"}}}});
});

it("keeps sampling values and provenance when only the execution environment changes",async()=>{
  catalog.push({...aesthetic,remote_profile_id:"another-cloud",remote_display_name:"另一环境"});
  await mount();
  fireEvent.change(screen.getByLabelText("Steps"),{target:{value:"22"}});
  fireEvent.click(screen.getByRole("button",{name:"确认应用参数"}));
  const before=structuredClone(draft().settings.creation_configuration);
  fireEvent.change(screen.getByRole("combobox",{name:"执行环境"}),{target:{value:"another-cloud"}});
  expect(draft().settings.creation_configuration).toEqual(before);
  expect(draft().settings.execution_policy).toEqual({mode:"pinned",environmentId:"another-cloud"});
  expect(screen.getByLabelText("Steps")).toHaveValue("22");
});

it("updates the current workflow revision without replacing the saved baseline or edits and submits a matching schema",async()=>{
  const view=await mount();
  fireEvent.change(screen.getByLabelText("CFG"),{target:{value:"7"}});
  fireEvent.click(screen.getByRole("button",{name:"确认应用参数"}));
  const before=structuredClone(draft().settings.creation_configuration);
  catalog=[{...aesthetic,template_revision:"aesthetic-v2",parameter_schema:{...aesthetic.parameter_schema!,templateRevision:"aesthetic-v2"},generation_recipes:[{...aesthetic.generation_recipes![0],parameters:{steps:18,cfg:2,sampler:"euler",scheduler:"normal"}}]},turbo,alternate];
  view.rerender(<MemoryRouter><ConversationWorkbenchPage remoteEnabled={false}/></MemoryRouter>);
  await act(async()=>{});
  view.rerender(<MemoryRouter><ConversationWorkbenchPage remoteEnabled/></MemoryRouter>);
  await act(async()=>{});
  expect(draft().settings.creation_configuration).toEqual(before);
  expect(screen.getByLabelText("Steps")).toHaveValue("35");
  expect(screen.getByLabelText("CFG")).toHaveValue("7");
  fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await waitFor(()=>expect(writes.some(item=>item.url.endsWith("/generation-intents"))).toBe(true));
  const request=writes.find(item=>item.url.endsWith("/generation-intents"))!.body;
  expect(request.creationConfiguration).toMatchObject({...before,workflow:{id:"aesthetic",revision:"aesthetic-v2"}});
  expect(request.source.settings).toMatchObject({steps:35,cfg:7,parameter_schema:{workflowId:"aesthetic",templateRevision:"aesthetic-v2"}});
  await waitFor(()=>expect(screen.getByRole("button",{name:"结果"})).toHaveAttribute("aria-pressed","true"));
});

it("does not restore an obsolete workflow when an earlier catalog request finishes after the current one",async()=>{
  delayTargets=true;
  const view=render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled/></MemoryRouter>);
  await screen.findByLabelText("正向提示词");
  await waitFor(()=>expect(finishTargets).toBeDefined());
  const finishEarlier=finishTargets!;
  view.rerender(<MemoryRouter><ConversationWorkbenchPage remoteEnabled={false}/></MemoryRouter>);
  await act(async()=>{});
  delayTargets=false;catalog=[turbo,alternate];
  view.rerender(<MemoryRouter><ConversationWorkbenchPage remoteEnabled/></MemoryRouter>);
  const workflow=screen.getByLabelText("创作工作流");
  await waitFor(()=>expect(Array.from((workflow as HTMLSelectElement).options).map(option=>option.value)).toEqual(["","alternate"]));
  await act(async()=>finishEarlier(new Response(JSON.stringify({items:[aesthetic,turbo,alternate]}))));
  expect(Array.from((workflow as HTMLSelectElement).options).map(option=>option.value)).toEqual(["","alternate"]);
});

it.each(["initialization","workspace list","workspace list error"])("ignores an obsolete %s after navigating to another workspace",async(stage)=>{
  const earlier=structuredClone(workspace);
  const later={...workspace,id:"later-workspace",title:"新会话",draft:{...workspace.draft,compiled:{...workspace.draft.compiled!,positive:"dog"}}};
  const fallback=vi.mocked(fetch).getMockImplementation()!;
  let finishEarlier:(()=>void)|undefined;
  let delayFirstList=stage!=="initialization";
  let oldWorkspaceOpens=0;
  if(stage==="initialization")vi.spyOn(conversationDrafts,"initializeConversationTab").mockImplementationOnce(()=>new Promise(resolve=>{finishEarlier=()=>resolve("obsolete-tab");}));
  vi.mocked(fetch).mockImplementation((input,init)=>{
    const url=String(input);
    if(url.startsWith("/api/v3/workspaces?")&&delayFirstList){
      delayFirstList=false;
      return new Promise(resolve=>{finishEarlier=()=>resolve(stage==="workspace list error"
        ?new Response(JSON.stringify({error:{code:"obsolete_workspace_list",message:"obsolete workspace list"}}),{status:400})
        :new Response(JSON.stringify({items:[earlier]})));});
    }
    if(url===`/api/v3/workspaces/${earlier.id}`){oldWorkspaceOpens++;return Promise.resolve(new Response(JSON.stringify(earlier)));}
    return fallback(input,init);
  });
  function NavigateToLater(){
    const navigate=useNavigate();
    return <button onClick={()=>navigate(`/workbench?workspace=${later.id}`)}>测试切换会话</button>;
  }
  render(<MemoryRouter initialEntries={[`/workbench?workspace=${earlier.id}`]}><NavigateToLater/><ConversationWorkbenchPage remoteEnabled/></MemoryRouter>);
  await waitFor(()=>expect(finishEarlier).toBeDefined());
  workspace=later;
  fireEvent.click(screen.getByRole("button",{name:"测试切换会话"}));
  await waitFor(()=>expect(screen.getByLabelText("正向提示词")).toHaveValue("dog"));
  await act(async()=>finishEarlier!());
  expect(screen.getByLabelText("正向提示词")).toHaveValue("dog");
  expect(oldWorkspaceOpens).toBe(0);
  expect(screen.queryByText("obsolete workspace list")).not.toBeInTheDocument();
});

it("retains a historical snapshot when the execution policy changes and submits it to the chosen environment",async()=>{
  frozenWorkspace();catalog.push({...aesthetic,remote_profile_id:"another-cloud",remote_display_name:"另一环境"});
  await mount();
  fireEvent.change(screen.getByRole("combobox",{name:"执行环境"}),{target:{value:"another-cloud"}});
  expect(draft().workflowSnapshotRunId).toBe("historical-run");
  expect(draft().settings.parameter_schema?.templateRevision).toBe("historical-v1");
  fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await waitFor(()=>expect(writes.some(item=>item.url.endsWith("/generation-intents"))).toBe(true));
  const request=writes.find(item=>item.url.endsWith("/generation-intents"))!.body;
  expect(request).toMatchObject({executionPolicy:{mode:"pinned",environmentId:"another-cloud"},creationConfiguration:{workflow:{revision:"historical-v1"}},
    source:{workflow_snapshot_run_id:"historical-run",settings:{steps:22,cfg:3.2,seed:"9223372036854775807",batch_size:2,parameter_schema:{templateRevision:"historical-v1"}}}});
  expect(writes.some(item=>item.url==="/api/v3/workbench/generation-source")).toBe(false);
});

it("adopts the current template from the LoRA panel while preserving historical parameters and resources",async()=>{
  frozenWorkspace();
  const retained={logical_id:"retained",file_name:"retained.safetensors",weight:.65,clip_weight:.2,enabled:false,trigger_words:[],required:true,source:{kind:"user" as const}};
  workspace.draft.requirements!.loras=[retained];
  workspace.draft.generation_settings!.creation_configuration!.resourceRequirements=[retained];
  await mount();
  const loras=screen.getByRole("region",{name:"LoRA 资源"});
  expect(within(loras).getByRole("button",{name:"从库中选择"})).toBeDisabled();
  fireEvent.click(within(loras).getByRole("button",{name:"切换模板并编辑 LoRA"}));
  expect(within(loras).getByRole("button",{name:"从库中选择"})).toBeEnabled();
  expect(draft().workflowSnapshotRunId).toBeNull();
  expect(draft().requirements.loras).toEqual([retained]);
  expect(draft().settings).toMatchObject({steps:22,cfg:3.2,seed:"9223372036854775807",batch_size:2,
    creation_configuration:{workflow:{id:"aesthetic",revision:"aesthetic-v1"},parameterOverrides:{steps:22,cfg:3.2,seed:"9223372036854775807",batch_size:2}},
    parameter_schema:{workflowId:"aesthetic",templateRevision:"aesthetic-v1"}});
  fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await waitFor(()=>expect(writes.some(item=>item.url.endsWith("/generation-intents"))).toBe(true));
  const request=writes.find(item=>item.url.endsWith("/generation-intents"))!.body;
  expect(request.creationConfiguration.workflow.revision).toBe("aesthetic-v1");
  expect(request.source).not.toHaveProperty("workflow_snapshot_run_id");
  expect(writes.filter(item=>item.url==="/api/v3/workbench/generation-source")).toHaveLength(1);
});

it("submits an archived historical workflow from its saved configuration without requiring a current catalog entry",async()=>{
  frozenWorkspace();catalog=[turbo,alternate];
  render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled/></MemoryRouter>);
  await screen.findByLabelText("正向提示词");
  fireEvent.click(screen.getByRole("button",{name:"生成参数"}));
  expect(screen.getByLabelText("Steps")).toHaveValue("22");
  expect(screen.getByRole("button",{name:"生成图片"})).toBeEnabled();
  fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await waitFor(()=>expect(writes.some(item=>item.url.endsWith("/generation-intents"))).toBe(true));
  expect(writes.find(item=>item.url.endsWith("/generation-intents"))!.body).toMatchObject({
    creationConfiguration:{workflow:{id:"aesthetic",revision:"historical-v1"}},
    source:{workflow_snapshot_run_id:"historical-run",settings:{seed:"9223372036854775807",steps:22,cfg:3.2}},
  });
});

it("keeps a removed ordinary workflow blocked until a current workflow is explicitly selected",async()=>{
  catalog=[turbo,alternate];
  render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled/></MemoryRouter>);
  await screen.findByLabelText("正向提示词");
  expect(screen.getByRole("button",{name:"生成图片"})).toBeDisabled();
  expect(writes.some(item=>item.url.endsWith("/generation-intents"))).toBe(false);
});

it("lets a historical workflow be explicitly replaced after its old catalog entry was removed",async()=>{
  frozenWorkspace();catalog=[turbo,alternate];
  render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled/></MemoryRouter>);
  await screen.findByLabelText("正向提示词");
  fireEvent.click(screen.getByRole("button",{name:"生成参数"}));
  fireEvent.click(within(screen.getByRole("region",{name:"LoRA 资源"})).getByRole("button",{name:"切换模板并编辑 LoRA"}));
  expect(draft().workflowSnapshotRunId).toBeNull();
  expect(draft().settings.creation_configuration?.workflow).toEqual({id:"alternate",revision:"alternate-v1"});
  expect(draft().settings).toMatchObject({steps:22,cfg:3.2,seed:"9223372036854775807"});
});

it.each([
  {availability:"disabled" as const},
  {lora_extension_supported:false,lora_slot_order:[]},
])("keeps the historical LoRA editor locked when the current template is unusable: %j",async unavailable=>{
  frozenWorkspace();catalog=[{...aesthetic,...unavailable},turbo];
  await mount();
  const loras=screen.getByRole("region",{name:"LoRA 资源"});
  expect(within(loras).getByRole("button",{name:"切换模板并编辑 LoRA"})).toBeDisabled();
  expect(within(loras).getByText(/没有可用的兼容模板/)).toBeVisible();
  expect(draft().workflowSnapshotRunId).toBe("historical-run");
});

it("allows editing LoRAs with a known unchecked template before the cloud reconnects",async()=>{
  frozenWorkspace();catalog=[{...aesthetic,availability:"unchecked" as GenerationTarget["availability"]},turbo];
  await mount();
  fireEvent.click(within(screen.getByRole("region",{name:"LoRA 资源"})).getByRole("button",{name:"切换模板并编辑 LoRA"}));
  expect(draft().workflowSnapshotRunId).toBeNull();
  expect(within(screen.getByRole("region",{name:"LoRA 资源"})).getByRole("button",{name:"从库中选择"})).toBeEnabled();
  expect(writes.some(item=>item.url.endsWith("/generation-intents"))).toBe(false);
});

it("recognizes a manually selected artist in recommendations instead of adding the same artist twice",async()=>{
  workspace.draft.requirements!.layers.style.manual_artist_tags=["Sample_Artist"];
  await mount();
  openIdentity();
  fireEvent.click(screen.getByRole("button",{name:"画师推荐（可选）"}));
  fireEvent.click(screen.getByRole("button",{name:"刷新画师推荐"}));
  expect(await screen.findByRole("button",{name:"已加入"})).toBeDisabled();
});

it("removes an artist from both manual and recommended selections when old data contains it in both",async()=>{
  workspace.draft.requirements!.layers.style.manual_artist_tags=["Sample_Artist"];
  workspace.draft.requirements!.layers.style.artists=["sample artist"];
  await mount();
  openIdentity();
  fireEvent.click(screen.getByLabelText("移除画师 sample artist"));
  expect(draft().requirements.layers.style.manual_artist_tags).toEqual([]);
  expect(draft().requirements.layers.style.artists).toEqual([]);
});

it("removes a duplicate manual artist when the recommended artist selection is removed",async()=>{
  workspace.draft.requirements!.layers.style.manual_artist_tags=["Sample_Artist"];
  workspace.draft.requirements!.layers.style.artists=["sample artist"];
  await mount();
  openIdentity();
  fireEvent.click(screen.getByRole("button",{name:"画师推荐（可选）"}));
  fireEvent.click(within(screen.getByLabelText("已选画师")).getByRole("button",{name:"移除画师 sample artist"}));
  expect(draft().requirements.layers.style.manual_artist_tags).toEqual([]);
  expect(draft().requirements.layers.style.artists).toEqual([]);
});

it("puts explicitly selected identity tags into the visible prompt and the direct generation body without an LLM turn",async()=>{
  await mount();
  openIdentity();
  fireEvent.change(screen.getByLabelText("角色 tag（每行一个）"),{target:{value:"Shana"}});
  fireEvent.change(screen.getByLabelText("作品 tag（动画／游戏，每行一个）"),{target:{value:"Shakugan_No_Shana"}});
  fireEvent.change(screen.getByLabelText("画师 tag（每行一个，可带 @）"),{target:{value:"@Sample_Artist"}});
  const prompt=screen.getByLabelText("正向提示词") as HTMLTextAreaElement;
  expect(prompt.value).toContain("shana");expect(prompt.value).toContain("shakugan no shana");expect(prompt.value).toContain("@sample artist");
  const shown=prompt.value;
  fireEvent.click(screen.getByRole("button",{name:"返回提示词"}));
  fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await waitFor(()=>expect(writes.some(item=>item.url.endsWith("/generation-intents"))).toBe(true));
  expect(writes.find(item=>item.url.endsWith("/generation-intents"))!.body.source.positive_prompt).toBe(shown);
  expect(writes.some(item=>item.url.endsWith("/turns"))).toBe(false);
});

it("keeps identity edits and exact live prompt across Sheet close and reopen without submitting",async()=>{
  await mount();
  const prompt=screen.getByLabelText("正向提示词");
  const trigger=screen.getByRole("button",{name:/^角色与画师/});
  fireEvent.click(trigger);
  expect(screen.getByRole("dialog",{name:"创作辅助"})).toBeVisible();
  const character=screen.getByLabelText("角色 tag（每行一个）");
  fireEvent.change(character,{target:{value:"Shana"}});
  fireEvent.change(screen.getByLabelText("画师 tag（每行一个，可带 @）"),{target:{value:"@Sample_Artist"}});
  expect(prompt).toHaveValue("@sample artist, shana, cat");
  fireEvent.click(screen.getByRole("button",{name:"关闭辅助设置"}));
  expect(screen.queryByRole("dialog",{name:"创作辅助"})).not.toBeInTheDocument();
  expect(screen.getByLabelText("正向提示词")).toBe(prompt);
  expect(character).not.toBeVisible();
  expect(document.body.style.overflow).not.toBe("hidden");
  fireEvent.click(trigger);
  expect(screen.getByLabelText("角色 tag（每行一个）")).toBe(character);
  expect(character).toHaveValue("Shana");
  fireEvent.change(screen.getByLabelText("画师 tag（每行一个，可带 @）"),{target:{value:""}});
  fireEvent.click(screen.getByRole("button",{name:"返回提示词"}));
  expect(prompt).toHaveValue("shana, cat");
  expect(writes).toEqual([]);
});

it.each(["auto","pinned"] as const)("submits the reviewed positive and negative verbatim over %s even if a save response differs",async mode=>{
  workspace.draft.generation_settings!.execution_policy=mode==="auto"?{mode,preferredEnvironmentIds:["cloud"]}:{mode,environmentId:"cloud"};
  workspace.draft.compiled!.negative="old negative";
  await mount();openIdentity();
  fireEvent.change(screen.getByLabelText("角色 tag（每行一个）"),{target:{value:"Shana"}});
  fireEvent.change(screen.getByLabelText("画师 tag（每行一个，可带 @）"),{target:{value:"@Sample_Artist"}});
  fireEvent.click(screen.getByRole("button",{name:"返回提示词"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("@sample artist, shana, cat");
  const positive="  (@Sample_Artist:1.25), adult traveler,\n  (closed book:1.10)  ";
  const negative=mode==="pinned"?"":"  watermark,\n  (blur:1.2)  ";
  fireEvent.change(screen.getByLabelText("正向提示词"),{target:{value:positive}});
  fireEvent.change(screen.getByLabelText("负向提示词"),{target:{value:negative}});
  expect(draft()).toMatchObject({positive,negative});
  serverSavedPrompt="shana, changed server response";
  fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  const endpoint=mode==="auto"?"/generation-intents":"/direct-prompt/runs";
  await waitFor(()=>expect(writes.some(item=>item.url.endsWith(endpoint))).toBe(true));
  const sent=writes.find(item=>item.url.endsWith(endpoint))!.body;
  expect(writes.find(item=>item.url.endsWith(workspace.id))!.body.draft.prompt_edit).toEqual({positive,negative});
  expect(sent.source || sent).toMatchObject({positive_prompt:positive,negative_prompt:negative,use_current_prompt:true});
  expect(screen.getByLabelText("正向提示词")).toHaveValue(positive);
  expect(screen.getByLabelText("负向提示词")).toHaveValue(negative);
  expect(draft()).toMatchObject({positive,negative});
});

it.each(["","   \n "])("keeps a manually cleared positive in the draft after a picker edit and never submits the previous text (%j)",async positive=>{
  const view=await mount();openIdentity();
  fireEvent.change(screen.getByLabelText("角色 tag（每行一个）"),{target:{value:"Shana"}});
  fireEvent.click(screen.getByRole("button",{name:"返回提示词"}));
  fireEvent.change(screen.getByLabelText("正向提示词"),{target:{value:positive}});
  expect(screen.getByRole("button",{name:"生成图片"})).toBeDisabled();
  expect(screen.getByRole("button",{name:"保存当前版本"})).toBeDisabled();
  expect(draft().positive).toBe(positive);
  view.unmount();await mount();
  expect(screen.getByLabelText("正向提示词")).toHaveValue(positive);
  expect(writes).toEqual([]);
});

it("does not offer retired model versions that have no active workflow while retaining the currently viewed historical model",async()=>{
  await mount();
  const models=within(screen.getByLabelText("模型"));
  expect(models.queryByRole("option",{name:"ANIMA Aesthetic v1.0"})).not.toBeInTheDocument();
  expect(models.queryByRole("option",{name:/^ANIMA Turbo$/})).not.toBeInTheDocument();
  expect(models.getByRole("option",{name:"ANIMA Turbo v1.1"})).toBeInTheDocument();
});

it("can replay a validated historical legacy model alias from its archived workflow",async()=>{
  frozenWorkspace();catalog=[turbo,alternate];
  workspace.draft.model_profile="anima_aesthetic_v1";
  workspace.draft.generation_settings!.creation_configuration!.modelProfile="anima_aesthetic_v1";
  workspace.draft.generation_source!.model_profile="anima_aesthetic_v1";
  render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled/></MemoryRouter>);
  await screen.findByLabelText("正向提示词");
  expect(screen.getByRole("button",{name:"生成图片"})).toBeEnabled();
  fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await waitFor(()=>expect(writes.some(item=>item.url.endsWith("/generation-intents"))).toBe(true));
  expect(writes.find(item=>item.url.endsWith("/generation-intents"))!.body.source).toMatchObject({model_profile:"anima_aesthetic_v1",workflow_snapshot_run_id:"historical-run"});
});

it("saves and reopens an explicitly cleared last identity tag without losing the negative prompt or restoring the old tag",async()=>{
  workspace.draft.requirements!.layers.subject.character_tags=["shana"];
  workspace.draft.compiled={...workspace.draft.compiled!,positive:"shana",negative:"keep this exact negative"};
  const view=await mount();
  openIdentity();
  fireEvent.click(screen.getByLabelText("移除角色 shana"));
  fireEvent.click(screen.getByRole("button",{name:"返回提示词"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("");
  expect(screen.getByRole("button",{name:"生成图片"})).toBeDisabled();
  serverSavedPrompt="";
  fireEvent.click(screen.getByText("保存当前版本"));
  await waitFor(()=>expect(writes.some(item=>item.url===`/api/v3/workspaces/${workspace.id}`)).toBe(true));
  expect(draft().positive).toBe("");
  expect(draft().negative).toBe("keep this exact negative");
  view.unmount();
  await mount();
  expect(screen.getByLabelText("正向提示词")).toHaveValue("");
  expect(screen.getByLabelText("负向提示词")).toHaveValue("keep this exact negative");
  expect(screen.getByRole("button",{name:"生成图片"})).toBeDisabled();
});

it("shows a manual-only artist in the shared selected artists list and removes its tag from the actual prompt",async()=>{
  workspace.draft.requirements!.layers.style.manual_artist_tags=["wlop"];
  workspace.draft.compiled={...workspace.draft.compiled!,positive:"@wlop, cat"};
  await mount();openIdentity();fireEvent.click(screen.getByRole("button",{name:"画师推荐（可选）"}));
  const selected=screen.getByLabelText("已选画师");
  expect(selected).toHaveTextContent("@wlop");
  expect(selected).not.toHaveTextContent("还没有选择画师");
  fireEvent.click(within(selected).getByRole("button",{name:"移除画师 wlop"}));
  expect(draft().requirements.layers.style.manual_artist_tags).toEqual([]);
  expect(screen.getByLabelText("正向提示词")).toHaveValue("cat");
});
