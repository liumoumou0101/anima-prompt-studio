/// <reference types="node" />
import {cleanup,render,screen,waitFor} from "@testing-library/react";
import {MemoryRouter,useLocation} from "react-router-dom";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {webcrypto} from "node:crypto";
import App from "./App";
import {resetApiClientForTests} from "./lib/api";
import {DIRECT_IMPORT_KEY,DIRECT_MIGRATION_RECEIPT_KEY,LEGACY_DIRECT_DRAFT_KEY,storeDirectImport} from "./lib/directPrompt";
import {emptyRequirements,type ConversationRecord} from "./lib/conversation";
import {defaultGenerationSettings} from "./lib/generationSettings";
vi.mock("./components/ArtistRecommendations",()=>({ArtistRecommendations:()=>null}));
vi.mock("./components/ManualIdentityTags",()=>({ManualIdentityTags:()=>null}));
vi.mock("./components/SceneDesignControls",()=>({SceneDesignControls:()=>null}));
let calls:{url:string;method:string;body:any;key:string|null}[];
let imported:ConversationRecord;
beforeEach(()=>{
 vi.stubGlobal("crypto",webcrypto);
 localStorage.clear();sessionStorage.clear();resetApiClientForTests();sessionStorage.setItem("anima-v3-session","test");localStorage.setItem("anima-v3-session-recovery","test");calls=[];
 imported={id:"workspace_directtest",title:"原文",revision:1,created_at:"2026-10-25",updated_at:"2026-10-25",draft:{positive_text:"人物",excluded_text:"模糊",model_profile:"anima_base_v1",mode:"faithful",requirements:{...emptyRequirements(),contract:"anima-requirements/1",revision:1},compiled:{positive:"",negative:"",compiled_token:"direct",source:"user"},compile_state:"fresh",conversation_events:[],generation_settings:defaultGenerationSettings()}};
 vi.spyOn(globalThis,"fetch").mockImplementation(async(input,init)=>{
  const url=String(input),method=init?.method||"GET",body=init?.body?JSON.parse(String(init.body)):null;calls.push({url,method,body,key:new Headers(init?.headers).get("Idempotency-Key")});
  let result:unknown={items:[]};
  if(url.endsWith("/bootstrap"))result={app_version:"test",data_pack:{id:"test",ready:true},features:{remote_generation:false,gallery:false},model_profile_options:[{id:"anima_base_v1",display_name:"ANIMA Base",family:"anima"},{id:"moss_image_sft_int8",display_name:"MOSS Image",family:"moss"}]};
  else if(url.endsWith("/llm/settings"))result={current:null,services:[]};
  else if(url.endsWith("/workspaces")&&method==="POST"){imported={...imported,title:body.title,draft:{...imported.draft,...body.draft,compiled:{...imported.draft.compiled!,...body.draft.prompt_edit}}};result=imported;}
  else if(url.endsWith("/proposal"))result={proposal:null};
  else if(url.endsWith(`/workspaces/${imported.id}`))result=imported;
  return new Response(JSON.stringify(result),{status:200});
 });
});
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.unstubAllGlobals();});
it("actual App /workbench route durably consumes original English once without an LLM or image request",async()=>{
 const english="  1girl, original_word\nblue coat  ";
 storeDirectImport({positive_text:"人物，蓝色外套",excluded_text:"模糊",english_positive:english,english_negative:"low quality"});
 const view=render(<MemoryRouter initialEntries={["/workbench?from=direct"]}><App/></MemoryRouter>);
 await waitFor(()=>expect(screen.getByLabelText("正向提示词")).toHaveValue(english));
 expect(screen.getByLabelText("负向提示词")).toHaveValue("low quality");
 await waitFor(()=>expect(sessionStorage.getItem(DIRECT_IMPORT_KEY)).toBeNull());
 const creates=calls.filter(call=>call.method==="POST"&&call.url.endsWith("/workspaces"));expect(creates).toHaveLength(1);expect(creates[0].key).toMatch(/^direct-import:/);expect(creates[0].body.draft.positive_text).toBe("人物，蓝色外套");
 expect(calls.some(call=>/workbench\/turns|\/runs$/.test(call.url))).toBe(false);
 view.unmount();render(<MemoryRouter initialEntries={["/workbench?from=direct"]}><App/></MemoryRouter>);
 await screen.findByLabelText("正向提示词");expect(calls.filter(call=>call.method==="POST"&&call.url.endsWith("/workspaces"))).toHaveLength(1);
});
it("retains a damaged direct handoff for recovery instead of consuming it",async()=>{
 const raw=JSON.stringify({positive_text:"人物",english_positive:42});sessionStorage.setItem(DIRECT_IMPORT_KEY,raw);
 render(<MemoryRouter initialEntries={["/workbench?from=direct"]}><App/></MemoryRouter>);
 await screen.findByText(/原文导入记录不完整/);expect(sessionStorage.getItem(DIRECT_IMPORT_KEY)).toBe(raw);
 expect(calls.some(call=>call.method==="POST"&&call.url.endsWith("/workspaces"))).toBe(false);
});

it("/direct migrates its legacy draft through the unified consumer with original metadata",async()=>{
 const settings={...defaultGenerationSettings(),steps:22,cfg:3.2,seed:"8798399215689017476",remote_profile_id:"old-remote",workflow_profile_id:"old-workflow"};
 const raw=JSON.stringify({project_name:"保留的项目名",positive_prompt:"  original raw words  ",negative_prompt:"bad text",model_profile:"anima_base_v1",generation_settings:settings,chinese_positive:"原有中文对照"});
 localStorage.setItem("anima-v3-direct-prompt-draft",raw);
 render(<MemoryRouter initialEntries={["/direct"]}><App/></MemoryRouter>);
 await waitFor(()=>expect(screen.getByLabelText("正向提示词")).toHaveValue("  original raw words  "));
 const create=calls.find(call=>call.method==="POST"&&call.url.endsWith("/workspaces"))!;
 expect(create.body.title).toBe("保留的项目名");expect(create.body.draft.model_profile).toBe("anima_base_v1");expect(create.body.draft.generation_settings.steps).toBe(22);expect(create.body.draft.generation_settings.seed).toBe("8798399215689017476");expect(create.body.draft.generation_settings.execution_policy).toEqual({mode:"pinned",environmentId:"old-remote"});
 expect(localStorage.getItem("anima-v3-direct-prompt-draft")).toBe(raw);expect(calls.some(call=>/workbench\/turns|\/runs$/.test(call.url))).toBe(false);
});

it("/direct preserves a malformed legacy draft and offers recovery instead of replacing it",async()=>{
 const raw="{broken legacy draft";localStorage.setItem("anima-v3-direct-prompt-draft",raw);
 render(<MemoryRouter initialEntries={["/direct"]}><App/></MemoryRouter>);
 await screen.findByText(/旧版原文草稿.*损坏/);expect(localStorage.getItem("anima-v3-direct-prompt-draft")).toBe(raw);
 expect(calls.some(call=>call.method==="POST"&&call.url.endsWith("/workspaces"))).toBe(false);
});

it("/direct exposes an unresolved stored legacy submission without creating or resubmitting",async()=>{
 const request=JSON.stringify({key:"direct-old-request",body:"frozen request"});localStorage.setItem("anima-v3-direct-prompt-submission",request);
 render(<MemoryRouter initialEntries={["/direct"]}><App/></MemoryRouter>);
 await screen.findByText(/旧版原文生成请求.*尚未确认/);expect(screen.getByRole("link",{name:"打开任务记录核对"})).toHaveAttribute("href","/generate");expect(localStorage.getItem("anima-v3-direct-prompt-submission")).toBe(request);
 expect(calls.some(call=>call.method==="POST"&&/\/workspaces$|\/runs$/.test(call.url))).toBe(false);
});

it("retries legacy migration after losing its session with the same idempotency key",async()=>{
 const raw=JSON.stringify({project_name:"stable legacy",positive_prompt:"legacy original",negative_prompt:"",model_profile:"anima_base_v1",generation_settings:defaultGenerationSettings()});localStorage.setItem("anima-v3-direct-prompt-draft",raw);
 const original=vi.mocked(fetch).getMockImplementation()!;let lost=true;
 vi.mocked(fetch).mockImplementation(async(input,init)=>{const response=await original(input,init);if(lost&&String(input).endsWith("/workspaces")&&init?.method==="POST"){lost=false;throw new TypeError("acceptance response lost");}return response;});
 const view=render(<MemoryRouter initialEntries={["/direct"]}><App/></MemoryRouter>);await screen.findByText(/无法连接本地服务/);
 const first=calls.find(call=>call.method==="POST"&&call.url.endsWith("/workspaces"))!;view.unmount();sessionStorage.removeItem(DIRECT_IMPORT_KEY);
 render(<MemoryRouter initialEntries={["/direct"]}><App/></MemoryRouter>);await waitFor(()=>expect(screen.getByLabelText("正向提示词")).toHaveValue("legacy original"));
 const requests=calls.filter(call=>call.method==="POST"&&call.url.endsWith("/workspaces"));expect(requests).toHaveLength(2);expect(requests[1].key).toBe(first.key);expect(requests[1].body).toEqual(first.body);expect(localStorage.getItem("anima-v3-direct-prompt-draft")).toBe(raw);
});

function LocationProbe(){const location=useLocation();return <output data-testid="current-location">{location.pathname}{location.search}</output>;}
it.each([["/workbench","moss_image_sft_int8","/moss"],["/direct","moss_image_sft_int8","/moss"],["/moss","anima_base_v1","/workbench"]])("corrects an explicit %s bookmark using the stored %s model",async(entry,model,destination)=>{
  imported.draft.model_profile=model;
  imported.draft.compiled!.positive="adult reading in a garden";
  if(entry==="/direct") localStorage.setItem("anima-v3-direct-prompt-submission","older request");
  render(<MemoryRouter initialEntries={[`${entry}?workspace=${imported.id}`]}><LocationProbe/><App/></MemoryRouter>);
  await waitFor(()=>expect(screen.getByTestId("current-location").textContent).toBe(`${destination}?workspace=${imported.id}`));
  expect(calls.some(call=>call.url.endsWith("/workspaces")&&call.method==="POST")).toBe(false);
  expect(calls.some(call=>call.url.includes("generation-intents")||call.url.includes("/turns"))).toBe(false);
  if(entry==="/direct") expect(localStorage.getItem("anima-v3-direct-prompt-submission")).toBe("older request");
});

it("ignores an old MOSS active pointer when entering the ordinary ANIMA workbench",async()=>{
  imported.draft.model_profile="moss_image_sft_int8";
  localStorage.setItem("anima-conversation-active",JSON.stringify(imported.id));
  render(<MemoryRouter initialEntries={["/workbench"]}><LocationProbe/><App/></MemoryRouter>);
  await waitFor(()=>expect(calls.some(call=>call.url.endsWith(`/workspaces/${imported.id}`))).toBe(true));
  expect(await screen.findByRole("button",{name:"直接编写提示词"})).toBeEnabled();
  expect(screen.getByTestId("current-location").textContent).toBe("/workbench");
  expect(screen.queryByLabelText("正向提示词")).not.toBeInTheDocument();
  expect(calls.some(call=>call.url.endsWith("/workspaces")&&call.method==="POST")).toBe(false);
});

it("routes an explicitly modeled original-text import to MOSS after preserving its exact prompt",async()=>{
  const positive="  一名成年人在花园读书。\n保留原文空格  ",negative=" 模糊 ";
  storeDirectImport({model_profile:"moss_image_sft_int8",positive_text:"",excluded_text:"",english_positive:positive,english_negative:negative});
  render(<MemoryRouter initialEntries={["/workbench?from=direct"]}><LocationProbe/><App/></MemoryRouter>);
  await waitFor(()=>expect(screen.getByTestId("current-location").textContent).toBe(`/moss?workspace=${imported.id}`));
  const creation=calls.filter(call=>call.url.endsWith("/workspaces")&&call.method==="POST");
  expect(creation).toHaveLength(1);
  expect(creation[0].body.draft).toMatchObject({model_profile:"moss_image_sft_int8",prompt_edit:{positive,negative}});
  expect(sessionStorage.getItem(DIRECT_IMPORT_KEY)).toBeNull();
  expect(calls.some(call=>call.url.includes("generation-intents")||call.url.endsWith("/turns"))).toBe(false);
});

it.each([undefined,{steps:19,seed:"8798399215689017476"}])("migrates an old MOSS draft with settings %j once, preserving both original text and the previous ANIMA session",async(settings)=>{
  const positive="  一位成年女性在花园读书。\n  右下角写着『晨光』  ",negative="  避免模糊\n保留行距  ";
  const previous={...structuredClone(imported),id:"workspace_previous",title:"前一个 ANIMA 会话"};
  previous.draft.generation_settings={...defaultGenerationSettings(),width:768,height:1280,steps:42,cfg:7,seed:"9223372036854775807"};
  localStorage.setItem("anima-conversation-active",JSON.stringify(previous.id));
  const original=vi.mocked(fetch).getMockImplementation()!;
  let previousOpened=false;
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    if(String(input).endsWith(`/workspaces/${previous.id}`)&&(init?.method||"GET")==="GET"){
      previousOpened=true;return new Response(JSON.stringify(previous));
    }
    return original(input,init);
  });
  const raw=JSON.stringify({model_profile:"moss_image_sft_int8",positive_prompt:positive,negative_prompt:negative,generation_settings:settings});
  localStorage.setItem(LEGACY_DIRECT_DRAFT_KEY,raw);
  const first=render(<MemoryRouter initialEntries={["/direct"]}><LocationProbe/><App/></MemoryRouter>);
  const destination=`/moss?workspace=${imported.id}`;
  await waitFor(()=>expect(screen.getByTestId("current-location").textContent).toBe(destination));
  expect(previousOpened).toBe(true);
  const creations=()=>calls.filter(call=>call.method==="POST"&&call.url.endsWith("/workspaces"));
  expect(creations()).toHaveLength(1);
  const draft=creations()[0].body.draft;
  expect(draft).toMatchObject({model_profile:"moss_image_sft_int8",prompt_edit:{positive,negative}});
  if(settings){
    expect(draft.generation_settings).toMatchObject(settings);
    for(const field of ["cfg","width","height","sampler","scheduler","creation_configuration"])expect(draft.generation_settings).not.toHaveProperty(field);
  }else expect(draft).not.toHaveProperty("generation_settings");
  expect(localStorage.getItem(LEGACY_DIRECT_DRAFT_KEY)).toBe(raw);
  expect(JSON.parse(localStorage.getItem(DIRECT_MIGRATION_RECEIPT_KEY)!)).toMatchObject({raw,workspaceId:imported.id});
  first.unmount();
  render(<MemoryRouter initialEntries={["/direct"]}><LocationProbe/><App/></MemoryRouter>);
  await waitFor(()=>expect(screen.getByTestId("current-location").textContent).toBe(destination));
  expect(creations()).toHaveLength(1);
  expect(calls.some(call=>call.url.endsWith(`/workspaces/${previous.id}`)&&call.method==="PUT")).toBe(false);
  expect(calls.some(call=>call.url.includes("generation-intents")||call.url.endsWith("/turns"))).toBe(false);
});

it("rejects an unknown model in an explicit workspace without opening an unrelated editor",async()=>{
  imported.draft.model_profile="unsupported_family";
  render(<MemoryRouter initialEntries={[`/workbench?workspace=${imported.id}`]}><LocationProbe/><App/></MemoryRouter>);
  expect(await screen.findByRole("alert")).toHaveTextContent("unsupported_family");
  expect(screen.queryByLabelText("正向提示词")).not.toBeInTheDocument();
  expect(screen.getByTestId("current-location").textContent).toBe(`/workbench?workspace=${imported.id}`);
  expect(calls.some(call=>call.method==="PUT"||call.url.endsWith("generation-intents"))).toBe(false);
});

it("raw entry retains an uncertain creation request and clears its query only after success",async()=>{
 const original=vi.mocked(fetch).getMockImplementation()!;let lost=true;
 vi.mocked(fetch).mockImplementation(async(input,init)=>{const response=await original(input,init);if(lost&&String(input).endsWith("/workspaces")&&init?.method==="POST"){lost=false;throw new TypeError("creation receipt lost");}return response;});
 const first=render(<MemoryRouter initialEntries={["/workbench?entry=raw"]}><LocationProbe/><App/></MemoryRouter>);
 await screen.findByText(/无法连接本地服务/);
 expect(screen.getByTestId("current-location")).toHaveTextContent("entry=raw");
 expect(screen.queryByText(/可直接输入英文提示词并生成图片/)).not.toBeInTheDocument();
 const before=calls.filter(call=>call.method==="POST"&&call.url.endsWith("/workspaces"));expect(before).toHaveLength(1);
 first.unmount();
 render(<MemoryRouter initialEntries={["/workbench?entry=raw"]}><LocationProbe/><App/></MemoryRouter>);
 await screen.findByLabelText("正向提示词");
 await waitFor(()=>expect(screen.getByTestId("current-location")).not.toHaveTextContent("entry=raw"));
 const requests=calls.filter(call=>call.method==="POST"&&call.url.endsWith("/workspaces"));expect(requests).toHaveLength(2);
 expect(requests[0].key).toMatch(/^raw-create:/);expect(requests[1].key).toBe(requests[0].key);expect(requests[1].body).toEqual(requests[0].body);
 expect(calls.some(call=>/workbench\/turns|\/runs$/.test(call.url))).toBe(false);
});

it("empty legacy drafts retain project, model and parameters without fabricating prompt text",async()=>{
 const settings={...defaultGenerationSettings(),steps:22,cfg:3.2,seed:"8798399215689017476",remote_profile_id:"old-remote",workflow_profile_id:"old-workflow"};
 const raw=JSON.stringify({project_name:"空白但配置完整",positive_prompt:"",negative_prompt:"bad text",model_profile:"anima_base_v1",generation_settings:settings});
 localStorage.setItem("anima-v3-direct-prompt-draft",raw);
 render(<MemoryRouter initialEntries={["/direct"]}><App/></MemoryRouter>);
 await screen.findByLabelText("正向提示词");
 expect(screen.getByLabelText("负向提示词")).toHaveValue("bad text");
 const create=calls.find(call=>call.method==="POST"&&call.url.endsWith("/workspaces"))!;
 expect(create.body.title).toBe("空白但配置完整");expect(create.body.draft.model_profile).toBe("anima_base_v1");
 expect(create.body.draft.generation_settings).toMatchObject({steps:22,cfg:3.2,seed:"8798399215689017476",execution_policy:{mode:"pinned",environmentId:"old-remote"}});
 expect(create.body.draft.prompt_edit).toBeUndefined();
 expect(localStorage.getItem("anima-v3-direct-prompt-draft")).toBe(raw);
 expect(calls.some(call=>/workbench\/turns|\/runs$/.test(call.url))).toBe(false);
});

it("raw entry keeps the current draft when its required backup cannot be written",async()=>{
 imported={...imported,draft:{...imported.draft,compiled:{...imported.draft.compiled!,positive:"keep the current draft"}}};
 localStorage.setItem("anima-conversation-active",JSON.stringify(imported.id));
 const write=Storage.prototype.setItem;
 vi.spyOn(Storage.prototype,"setItem").mockImplementation(function(this:Storage,key,value){
  if(key.startsWith("anima-conversation-draft-snapshot:"))throw new DOMException("backup unavailable","QuotaExceededError");
  write.call(this,key,value);
 });
 render(<MemoryRouter initialEntries={["/workbench?entry=raw"]}><LocationProbe/><App/></MemoryRouter>);
 await screen.findByText(/无法保留当前草稿的恢复副本/);
 expect(screen.getByLabelText("正向提示词")).toHaveValue("keep the current draft");
 expect(screen.getByTestId("current-location")).toHaveTextContent("entry=raw");
 expect(calls.filter(call=>call.method==="POST"&&call.url.endsWith("/workspaces"))).toHaveLength(0);
});
