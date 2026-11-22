import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  act,
} from "@testing-library/react";
import { Link, MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MossWorkbenchPage } from "./MossWorkbenchPage";
import { modelProfileChoices } from "../lib/modelProfiles";
import {basicWorkflowSchema} from "../lib/workflowParameterSchema";
import {defaultGenerationSettings} from "../lib/generationSettings";
import {emptyRequirements,type ConversationRecord} from "../lib/conversation";
const profiles = [
  {
    id: "moss_image_sft_int8",
    family: "moss",
    display_name: "MOSS INT8",
    variant: "moss",
  },
];
const suggestion = {
  positive: "少女手持写着“春天”的卡片，柔和光线",
  negative: "不要水印",
  changes: ["整理顺序"],
  warnings: [],
  mode: "polish",
  engine: "test",
};
let requests: { url: string; body: any }[];
beforeEach(() => {
  localStorage.clear();
  requests = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url, options) => {
    requests.push({
      url: String(url),
      body: options?.body ? JSON.parse(String(options.body)) : null,
    });
    return new Response(
      JSON.stringify(
        String(url).includes("prompt-assist") ? suggestion : { items: [] },
      ),
    );
  });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
function mount() {
  return render(
    <MemoryRouter>
      <MossWorkbenchPage modelProfiles={profiles} />
    </MemoryRouter>,
  );
}
function source() {
  fireEvent.change(screen.getByLabelText("原文"), {
    target: { value: "少女手持写着“春天”的卡片" },
  });
  const negative = screen.getByRole("button",{name:/负向提示词（可选）/});
  if (negative.getAttribute("aria-expanded") !== "true") fireEvent.click(negative);
  fireEvent.change(screen.getByRole("textbox",{name:"负向提示词"}), {
    target: { value: "不要水印" },
  });
}

const mossId="moss_image_sft_int8";
const mossFlow="v3_moss_image_sft_int8";
function sourceRecord(id:string,frozen=false):ConversationRecord {
  const flow=frozen?"retired-moss":mossFlow,revision=frozen?"frozen-v1":"live-v2";
  const schema=basicWorkflowSchema(flow,revision);
  const params={width:768,height:1024,steps:14,cfg:3,sampler:"er_sde",scheduler:"simple",seed:"9223372036854775806",batch_size:1};
  return {id,title:"继续 · "+id,revision:7,draft:{model_profile:mossId,mode:"faithful",compiled:{positive:"  成年旅人\n  站在车站。  ",negative:"  不要文字  ",compiled_token:"source-token",source:"user"},
    generation_settings:{...defaultGenerationSettings(),...params,preset_id:"custom",aspect:"custom",remote_profile_id:"cloud",workflow_profile_id:flow,parameter_schema:schema,
      creation_configuration:{modelProfile:mossId,workflow:{id:flow,revision},baseRecipeId:"custom",recipeValues:params,parameterOverrides:params,seedMode:"fixed",resourceRequirements:[]}},
    generation_source:frozen?{run_id:"historical-run",model_profile:mossId,workflow_profile_id:flow,remote_profile_id:"cloud"}:null,
  }} as unknown as ConversationRecord;
}
function LocationText(){const location=useLocation();return <output>{location.pathname+location.search}</output>;}
function mountSource(id:string){
  return render(<MemoryRouter initialEntries={["/moss?workspace="+id]}><Link to="/moss">独立草稿</Link><Link to="/moss?workspace=workspace_a">来源 A</Link><Link to="/moss?workspace=workspace_b">来源 B</Link>
    <Routes><Route path="/moss" element={<MossWorkbenchPage modelProfiles={profiles} remoteEnabled/>}/><Route path="/workbench" element={<LocationText/>}/></Routes></MemoryRouter>);
}
function sourceResponses(records:Record<string,ConversationRecord>,posts:{path:string;body:any}[],advanceOnAccept=false){
  vi.mocked(fetch).mockImplementation(async(url,options)=>{
    const path=String(url),method=options?.method||"GET";
    const record=records[path.split("/").at(-1)!];
    if(path.includes("/workspaces/")&&record){
      if(method==="PUT"){
        const payload=JSON.parse(String(options?.body)),update=payload.draft;
        if(payload.revision!==record.revision)return new Response("{}",{status:409});
        record.revision++;
        if(update.detach_generation_source===true)record.draft.generation_source=null;
        record.draft.generation_settings=update.generation_settings;
        if(update.requirements_edit)record.draft.requirements={...record.draft.requirements,...update.requirements_edit};
        record.draft.compiled={...record.draft.compiled!,...update.prompt_edit,compiled_token:"saved-token"};
      }
      return new Response(JSON.stringify(record));
    }
    if(path.endsWith("/generation-targets"))return new Response(JSON.stringify({items:[{remote_profile_id:"cloud",remote_display_name:"测试云",
      workflow_profile_id:mossFlow,compatible_model_profiles:[mossId],template_revision:"live-v2"}]}));
    if(path.endsWith("/generation-intents")||path.endsWith("/direct-prompt/runs")){
      const body=JSON.parse(String(options?.body)),saved=records[(body.source||body).workspace_id];
      posts.push({path,body});
      if(advanceOnAccept && saved){
        if((body.source||body).workspace_revision!==saved.revision)return new Response("{}",{status:409});
        saved.revision++;
        saved.draft.compiled!.compiled_token="accepted-"+saved.revision;
      }
      const accepted={id:"direct-run",state:"draft",workspace_id:saved?.id,workspace_revision:saved?.revision,compiled_token:saved?.draft.compiled?.compiled_token};
      return new Response(JSON.stringify(path.endsWith("/generation-intents")?{...receipt("accepted"),response:accepted}:accepted));
    }
    return new Response(JSON.stringify({items:[]}));
  });
}
it.each(["standalone", "historical"])("starts a fresh MOSS workspace from %s and preserves the previous draft", async origin => {
  const previous = sourceRecord("workspace_a", true);
  const oldKey = origin === "standalone" ? "moss-workbench-v1" : "moss-workbench-v1:workspace:workspace_a";
  const oldLora = {logical_id:"old-style",file_name:"old-style.safetensors",weight:.6,trigger_words:["old trigger"],required:true,source:{kind:"user"}};
  const oldDraft = {source:"原来的中文草稿",negative:"原来的排除内容",mode:"raw",output:"",adopted:false,
    environment:"cloud",workspaceRevision:previous.revision,unconfirmed:[{clientRequestId:"old-unconfirmed",protocol:"direct-v1",body:{}}],
    configuration:{...previous.draft.generation_settings!.creation_configuration!,resourceRequirements:[oldLora]}};
  localStorage.setItem(oldKey,JSON.stringify(oldDraft));
  sourceResponses({workspace_a:previous},[]);
  const originalFetch=vi.mocked(fetch).getMockImplementation()!;
  let created:ConversationRecord|undefined;
  let requestBody:any;
  let requestKey:string|null=null;
  vi.mocked(fetch).mockImplementation(async(input,options)=>{
    const path=String(input);
    if(path==="/api/v3/workspaces" && options?.method==="POST") {
      requestBody=JSON.parse(String(options.body));
      requestKey=new Headers(options.headers).get("Idempotency-Key");
      created={id:"fresh-moss",revision:1,title:requestBody.title,draft:{...requestBody.draft,requirements:emptyRequirements(),compiled:null}} as ConversationRecord;
      return Response.json(created);
    }
    if(path==="/api/v3/workspaces/fresh-moss")return Response.json(created);
    return originalFetch(input,options);
  });
  render(<MemoryRouter initialEntries={[origin==="standalone"?"/moss":"/moss?workspace=workspace_a"]}>
    <Routes><Route path="/moss" element={<><MossWorkbenchPage modelProfiles={profiles} remoteEnabled/><LocationText/></>}/></Routes>
  </MemoryRouter>);
  await waitFor(()=>expect(screen.getByLabelText("原文")).toHaveValue(oldDraft.source));
  fireEvent.click(screen.getByRole("button",{name:"新建创作"}));
  await screen.findByText("/moss?workspace=fresh-moss");
  await waitFor(()=>expect(screen.getByLabelText("原文")).toHaveValue(""));
  expect(requestKey).toBeTruthy();
  expect(requestBody.draft).toMatchObject({model_profile:mossId,generation_settings:{
    width:1024,height:1024,steps:25,cfg:2.5,seed:"-1",remote_profile_id:null,execution_policy:{mode:"auto",preferredEnvironmentIds:[]},
    creation_configuration:{workflow:{id:mossFlow,revision:""},parameterOverrides:{},resourceRequirements:[],seedMode:"random"},
  }});
  expect(requestBody.draft).not.toHaveProperty("generation_source");
  expect(screen.getByLabelText("Seed",{exact:true})).toHaveValue("-1");
  expect(screen.queryByText(/历史工作流快照/)).not.toBeInTheDocument();
  expect(screen.queryByRole("checkbox",{name:"启用 old-style.safetensors"})).not.toBeInTheDocument();
  expect(JSON.parse(localStorage.getItem(oldKey)!)).toMatchObject(oldDraft);
});
it("retries new MOSS workspace creation with the same request after a lost response",async()=>{
  const posts:{key:string|null;body:string}[]=[];
  vi.mocked(fetch).mockImplementation(async(input,options)=>{
    if(String(input)==="/api/v3/workspaces" && options?.method==="POST") {
      posts.push({key:new Headers(options.headers).get("Idempotency-Key"),body:String(options.body)});
      throw new TypeError("Failed to fetch");
    }
    return Response.json({items:[]});
  });
  const view=mount();source();
  fireEvent.click(screen.getByRole("button",{name:"新建创作"}));
  await waitFor(()=>expect(screen.getByRole("button",{name:"新建创作"})).toBeEnabled());
  expect(posts).toHaveLength(1);
  expect(screen.getByLabelText("原文")).toHaveValue("少女手持写着“春天”的卡片");
  view.unmount();mount();
  fireEvent.click(screen.getByRole("button",{name:"新建创作"}));
  await waitFor(()=>expect(posts).toHaveLength(2));
  expect(posts[0].key).toBeTruthy();
  expect(posts[1]).toEqual(posts[0]);
});
it("ignores a new MOSS workspace response after leaving the editor and keeps its retry receipt",async()=>{
  let finish!:(response:Response)=>void;
  let posts=0;
  vi.mocked(fetch).mockImplementation(async(input,options)=>{
    if(String(input)==="/api/v3/workspaces" && options?.method==="POST") {
      posts++;return new Promise<Response>(resolve=>{finish=resolve;});
    }
    return Response.json({items:[]});
  });
  render(<MemoryRouter initialEntries={["/moss"]}><Link to="/elsewhere">离开页面</Link><Routes>
    <Route path="/moss" element={<MossWorkbenchPage modelProfiles={profiles}/>}/>
    <Route path="/elsewhere" element={<LocationText/>}/>
  </Routes></MemoryRouter>);
  const create=screen.getByRole("button",{name:"新建创作"});
  fireEvent.click(create);fireEvent.click(create);
  expect(posts).toBe(1);
  expect(screen.getByRole("button",{name:"正在新建…"})).toBeDisabled();
  fireEvent.click(screen.getByRole("link",{name:"离开页面"}));
  await act(async()=>finish(Response.json({id:"late-moss",revision:1,draft:{model_profile:mossId}})));
  expect(screen.getByText("/elsewhere")).toBeInTheDocument();
  expect(JSON.parse(localStorage.getItem("moss-workbench-v1:new-workspace")!).key).toBeTruthy();
});
it("confirms historical MOSS parameters locally and preserves the frozen source when generating after reload",async()=>{
  const original=sourceRecord("workspace_a",true),posts:{path:string;body:any}[]=[];
  sourceResponses({workspace_a:original},posts);
  let view=mountSource(original.id);
  await waitFor(()=>expect(screen.getByLabelText("原文")).toHaveValue(original.draft.compiled!.positive));
  const oldSettings=structuredClone(original.draft.generation_settings);
  fireEvent.click(screen.getByRole("button",{name:/^生成参数/}));
  fireEvent.change(screen.getByLabelText("Steps",{exact:true}),{target:{value:"33"}});
  fireEvent.change(screen.getByLabelText("Seed",{exact:true}),{target:{value:"8798399215689017476"}});
  expect(screen.getByRole("button",{name:"生成图像"})).toBeDisabled();
  expect(JSON.parse(localStorage.getItem("moss-workbench-v1:workspace:workspace_a")!).configuration.parameterOverrides.steps).toBe(14);
  fireEvent.click(screen.getByRole("button",{name:"确认应用参数"}));
  expect(screen.getByRole("button",{name:"生成图像"})).toBeEnabled();
  expect(original.revision).toBe(7);
  expect(original.draft.generation_settings).toEqual(oldSettings);
  expect(posts).toEqual([]);
  view.unmount();
  view=mountSource(original.id);
  await waitFor(()=>expect(screen.getByRole("button",{name:"生成图像"})).toBeEnabled());
  expect(screen.getByLabelText("Steps",{exact:true})).toHaveValue("33");
  expect(screen.getByLabelText("Seed",{exact:true})).toHaveValue("8798399215689017476");
  fireEvent.click(screen.getByRole("button",{name:"生成图像"}));
  await waitFor(()=>expect(posts).toHaveLength(1));
  expect(posts[0]).toMatchObject({path:"/api/v3/generation-intents",body:{
    source:{workflow_snapshot_run_id:"historical-run",workspace_id:original.id,workspace_revision:8,
      positive_prompt:"  成年旅人\n  站在车站。  ",negative_prompt:"  不要文字  ",
      settings:{width:768,height:1024,steps:33,cfg:3,seed:"8798399215689017476",workflow_parameter_overrides:{steps:33,seed:"8798399215689017476"}}},
    creationConfiguration:{workflow:{id:"retired-moss",revision:"frozen-v1"},parameterOverrides:{steps:33,seed:"8798399215689017476"}},
  }});
  expect(original.draft.generation_source?.run_id).toBe("historical-run");
});
it("opens a frozen MOSS workspace without replaying a request and submits its exact text, seed, workflow and revision",async()=>{
  const original=sourceRecord("workspace_a",true),posts:{path:string;body:any}[]=[];
  sourceResponses({workspace_a:original},posts);
  mountSource(original.id);
  await waitFor(()=>expect(screen.getByLabelText("原文")).toHaveValue("  成年旅人\n  站在车站。  "));
  expect(screen.getByLabelText("Seed",{exact:true})).toHaveValue("9223372036854775806");
  expect(posts).toHaveLength(0);
  fireEvent.click(screen.getByRole("button",{name:"生成图像"}));
  await waitFor(()=>expect(posts).toHaveLength(1));
  expect(posts[0]).toMatchObject({path:"/api/v3/generation-intents",body:{source:{submission_kind:"conversational",use_current_prompt:true,workspace_id:original.id,
    workspace_revision:original.revision,compiled_token:original.draft.compiled!.compiled_token,workflow_snapshot_run_id:"historical-run",
    positive_prompt:"  成年旅人\n  站在车站。  ",negative_prompt:"  不要文字  ",settings:{width:768,steps:14,seed:"9223372036854775806",parameter_schema:{workflowId:"retired-moss",templateRevision:"frozen-v1"}}},
    creationConfiguration:{workflow:{id:"retired-moss",revision:"frozen-v1"}},executionPolicy:{mode:"pinned",environmentId:"cloud"}}});
});
it("keeps standalone editing and other workspace drafts separate",async()=>{
  const independent=render(<MemoryRouter><MossWorkbenchPage modelProfiles={profiles}/></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("原文"),{target:{value:"独立草稿文字"}});
  independent.unmount();
  const standalone=localStorage.getItem("moss-workbench-v1"), a=sourceRecord("workspace_a"),b=sourceRecord("workspace_b"),posts:{path:string;body:any}[]=[];
  b.draft.compiled!.positive="B 的中文原文";
  sourceResponses({workspace_a:a,workspace_b:b},posts);
  mountSource(a.id);
  await waitFor(()=>expect(screen.getByLabelText("原文")).toHaveValue(a.draft.compiled!.positive));
  fireEvent.change(screen.getByLabelText("原文"),{target:{value:"A 的本地编辑"}});
  fireEvent.click(screen.getByRole("link",{name:"来源 B"}));
  await waitFor(()=>expect(screen.getByLabelText("原文")).toHaveValue(b.draft.compiled!.positive));
  expect(localStorage.getItem("moss-workbench-v1")).toBe(standalone);
  fireEvent.click(screen.getByRole("link",{name:"来源 A"}));
  await waitFor(()=>expect(screen.getByLabelText("原文")).toHaveValue("A 的本地编辑"));
  fireEvent.click(screen.getByRole("link",{name:"独立草稿"}));
  expect(screen.getByLabelText("原文")).toHaveValue("独立草稿文字");
  expect(posts).toEqual([]);
});

it.each(["retired-moss",mossFlow])("detaches a MOSS snapshot (%s) in the LoRA section, persists the live template and submits its edited stack",async historicalFlow=>{
  const record=sourceRecord("workspace_a",true),posts:{path:string;body:any}[]=[];
  const stored=record.draft.generation_settings!;
  stored.workflow_profile_id=historicalFlow;
  stored.creation_configuration!.workflow.id=historicalFlow;
  stored.parameter_schema!.workflowId=historicalFlow;
  record.draft.generation_source!.workflow_profile_id=historicalFlow;
  const kept={logical_id:"old-style",file_name:"old-style.safetensors",weight:.4,required:true,trigger_words:[],source:{kind:"user" as const}};
  record.draft.requirements={...emptyRequirements(),revision:1,contract:"anima-requirements/1",loras:[kept]};
  sourceResponses({workspace_a:record},posts);
  const api=vi.mocked(fetch).getMockImplementation()!, sha="c".repeat(64);
  const asset={id:sha,sha256:sha,name:"新纹理",family:"moss",file_name:`anima_library/${sha}.safetensors`,relative_path:"test.safetensors",
    size_bytes:1024,model_profiles:[mossId],trigger_words:["texture"],weight:.6,clip_weight:null,present:true,valid:true,error:""};
  vi.mocked(fetch).mockImplementation(async(input,options)=>{
    const path=String(input);
    if(historicalFlow===mossFlow && path.endsWith("/generation-targets"))
      return Response.json({items:[{remote_profile_id:"cloud",workflow_profile_id:mossFlow,compatible_model_profiles:[mossId],template_revision:"live-v2",availability:"stale"}]});
    if(path.endsWith("/loras"))return Response.json({items:[asset],root_path:"loras"});
    if(path.endsWith("/cloud/sync"))return Response.json({id:"ready",state:"completed",environment_signature:"same",results:[{sha256:sha,installed:true}]});
    if(path.endsWith("/cloud/identity"))return Response.json({signature:"same"});
    return api(input,options);
  });
  const view=mountSource(record.id);
  await waitFor(()=>expect(screen.getByLabelText("原文")).toHaveValue("  成年旅人\n  站在车站。  "));
  fireEvent.change(screen.getByLabelText("原文"),{target:{value:"  保留这个正文\n  和空格。  "}});
  fireEvent.click(screen.getByRole("button",{name:/^生成参数/}));
  expect(screen.getByRole("button",{name:"从库中选择"})).toBeDisabled();
  fireEvent.click(await screen.findByRole("button",{name:"切换模板并编辑 LoRA"}));
  await waitFor(()=>expect(record.draft.generation_settings?.creation_configuration?.workflow).toEqual({id:mossFlow,revision:"live-v2"}));
  expect(record.draft.generation_source).toBeNull();
  expect(record.draft.requirements?.loras).toEqual([kept]);
  expect(record.draft.compiled).toMatchObject({positive:"  保留这个正文\n  和空格。  ",negative:"  不要文字  "});
  view.unmount();localStorage.clear();
  mountSource(record.id);
  await waitFor(()=>expect(screen.getByLabelText("原文")).toHaveValue("  保留这个正文\n  和空格。  "));
  fireEvent.click(screen.getByRole("button",{name:/^生成参数/}));
  expect(screen.queryByRole("button",{name:"切换模板并编辑 LoRA"})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"从库中选择"}));
  fireEvent.click(await screen.findByRole("button",{name:"添加 新纹理"}));
  fireEvent.click(screen.getByRole("button",{name:"返回提示词"}));
  await waitFor(()=>expect(screen.getByRole("button",{name:"生成图像"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button",{name:"生成图像"}));
  await waitFor(()=>expect(posts).toHaveLength(1));
  const payload=posts[0].body;
  expect(posts[0].path).toBe("/api/v3/direct-prompt/runs");
  expect(payload).toMatchObject({workspace_revision:record.revision,compiled_token:"saved-token",workflow_profile_id:mossFlow,
    positive_prompt:"  保留这个正文\n  和空格。  ",negative_prompt:"  不要文字  ",settings:{width:768,steps:14,seed:"9223372036854775806",
    parameter_schema:{workflowId:mossFlow,templateRevision:"live-v2"}}});
  expect(payload).not.toHaveProperty("workflow_snapshot_run_id");
  expect(record.draft.requirements?.loras.map(r=>r.logical_id)).toEqual(["old-style","library:"+sha]);
},15000);
it("discards unconfirmed parameters when detaching a snapshot with the same live workflow identity",async()=>{
  const record=sourceRecord("workspace_a"),posts:{path:string;body:any}[]=[];
  record.draft.generation_source={run_id:"same-template-history",model_profile:mossId,workflow_profile_id:mossFlow,remote_profile_id:"cloud"};
  const schema=record.draft.generation_settings!.parameter_schema!;
  record.draft.generation_settings!.creation_configuration!.recipeValues=Object.fromEntries(schema.fields.map(field=>[field.key,field.default]));
  sourceResponses({workspace_a:record},posts);
  const api=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,options)=>String(input).endsWith("/generation-targets")
    ? Response.json({items:[{remote_profile_id:"cloud",workflow_profile_id:mossFlow,compatible_model_profiles:[mossId],template_revision:"live-v2",parameter_schema:schema}]})
    : api(input,options));
  mountSource(record.id);
  await screen.findByLabelText("原文");
  fireEvent.click(screen.getByRole("button",{name:/^生成参数/}));
  fireEvent.change(screen.getByLabelText("Steps",{exact:true}),{target:{value:"41"}});
  expect(screen.getByRole("button",{name:"生成图像"})).toBeDisabled();
  fireEvent.click(await screen.findByRole("button",{name:"切换模板并编辑 LoRA"}));
  await waitFor(()=>expect(record.draft.generation_source).toBeNull());
  await waitFor(()=>expect(screen.queryByRole("button",{name:"确认生成参数"})).toBeNull());
  expect(screen.getByLabelText("Steps",{exact:true})).toHaveValue("14");
  expect(screen.getByRole("button",{name:"确认应用参数"})).toBeDisabled();
  expect(screen.getByRole("button",{name:"生成图像"})).toBeEnabled();
  expect(posts).toEqual([]);
});
it("keeps the historical source on a conflicting switch and blocks parameter edits until the CAS returns",async()=>{
  const record=sourceRecord("workspace_a",true),posts:{path:string;body:any}[]=[];
  sourceResponses({workspace_a:record},posts);
  const api=vi.mocked(fetch).getMockImplementation()!;
  let release:()=>void=()=>{},rejectSave=true;
  const waitForDetach=new Promise<void>(resolve=>{release=resolve;});
  vi.mocked(fetch).mockImplementation(async(input,options)=>{
    if(options?.method==="PUT" && rejectSave){
      await waitForDetach;
      record.revision++;
      record.title="另一窗口的新标题";
      return Response.json({error:{code:"workspace_revision_conflict",message:"另一窗口已修改记录，请重新打开。"}},{status:409});
    }
    return api(input,options);
  });
  const view=mountSource(record.id);
  await screen.findByLabelText("原文");
  fireEvent.change(screen.getByLabelText("原文"),{target:{value:"  新正文  "}});
  fireEvent.click(screen.getByRole("button",{name:/^生成参数/}));
  const toggle=await screen.findByRole("button",{name:"切换模板并编辑 LoRA"});
  await waitFor(()=>expect(toggle).toBeEnabled());
  fireEvent.click(toggle);
  expect(toggle).toBeDisabled();
  expect(screen.getByLabelText("Seed",{exact:true})).toBeDisabled();
  await act(async()=>{release();});
  await screen.findByText(/另一窗口已修改记录/);
  expect(record.draft.generation_source?.run_id).toBe("historical-run");
  expect(record.draft.generation_settings?.workflow_profile_id).toBe("retired-moss");
  expect(screen.getByLabelText("原文")).toHaveValue("  新正文  ");
  expect(record.revision).toBe(8);
  expect(posts).toHaveLength(0);
  view.unmount();
  rejectSave=false;
  mountSource(record.id);
  await screen.findByLabelText("原文");
  fireEvent.click(screen.getByRole("button",{name:/^生成参数/}));
  const retry=await screen.findByRole("button",{name:"切换模板并编辑 LoRA"});
  await waitFor(()=>expect(retry).toBeEnabled());
  fireEvent.click(retry);
  await waitFor(()=>expect(record.draft.generation_source).toBeNull());
  expect(record.revision).toBe(9);
  expect(record.title).toBe("另一窗口的新标题");
});
it("retains the MOSS snapshot when the pinned environment has no usable live template",async()=>{
  const record=sourceRecord("workspace_a",true);
  sourceResponses({workspace_a:record},[]);
  const api=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,options)=>String(input).endsWith("/generation-targets")
    ? Response.json({items:[{remote_profile_id:"other-cloud",compatible_model_profiles:[mossId],workflow_profile_id:mossFlow,template_revision:"live"}]})
    : api(input,options));
  mountSource(record.id);
  await screen.findByLabelText("原文");
  fireEvent.click(screen.getByRole("button",{name:/^生成参数/}));
  expect(await screen.findByRole("button",{name:"切换模板并编辑 LoRA"})).toBeDisabled();
  expect(screen.getByText(/没有可用的兼容模板/)).toBeInTheDocument();
  expect(record.draft.generation_source?.run_id).toBe("historical-run");
});
it("submits edited Chinese and the saved workspace revision through the pinned direct endpoint",async()=>{
  const original=sourceRecord("workspace_a"),posts:{path:string;body:any}[]=[];
  sourceResponses({workspace_a:original},posts);
  mountSource(original.id);
  await waitFor(()=>expect(screen.getByLabelText("原文")).toHaveValue(original.draft.compiled!.positive));
  fireEvent.change(screen.getByLabelText("原文"),{target:{value:"  修改后的中文\n保持两个空格  "}});
  await waitFor(()=>expect(screen.getByRole("button",{name:"生成图像"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button",{name:"生成图像"}));
  await screen.findByText(/direct-run/);
  expect(posts).toHaveLength(1);
  expect(posts[0]).toMatchObject({path:"/api/v3/direct-prompt/runs",body:{submission_kind:"conversational",use_current_prompt:true,
    workspace_id:original.id,workspace_revision:8,compiled_token:"saved-token",positive_prompt:"  修改后的中文\n保持两个空格  ",negative_prompt:"  不要文字  ",
    workflow_profile_id:mossFlow,remote_profile_id:"cloud",settings:{seed:"9223372036854775806",steps:14}}});
  expect(original.draft.generation_settings?.execution_policy).toEqual({mode:"pinned",environmentId:"cloud"});
});
it("preserves automatic routing and its preferences in a source workspace",async()=>{
  const original=sourceRecord("workspace_a"),posts:{path:string;body:any}[]=[];
  original.draft.generation_settings!.execution_policy={mode:"auto",preferredEnvironmentIds:["cloud"]};
  sourceResponses({workspace_a:original},posts);
  mountSource(original.id);
  await waitFor(()=>expect(screen.getByRole("combobox",{name:"执行环境"})).toHaveValue("auto"));
  await waitFor(()=>expect(screen.getByRole("button",{name:"生成图像"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button",{name:"生成图像"}));
  await waitFor(()=>expect(posts).toHaveLength(1));
  expect(posts[0]).toMatchObject({path:"/api/v3/generation-intents",body:{source:{workspace_id:original.id,positive_prompt:original.draft.compiled!.positive},
    executionPolicy:{mode:"auto",preferredEnvironmentIds:["cloud"]},creationConfiguration:{workflow:{id:mossFlow,revision:"live-v2"}}}});
});
it("makes borrowed reference requirements editable as Chinese text before the first generation",async()=>{
  const record=sourceRecord("workspace_a"),posts:{path:string;body:any}[]=[];
  const req=emptyRequirements();
  req.layers.subject.text="成年人站在花园里";
  req.layers.subject.character_tags=["已选角色"];
  req.layers.style.text="厚涂";req.layers.composition.design={shot:{value:"全身",source:"user"}};
  req.layers.exclusions.global=["水印"];req.layers.exclusions.scoped=[{target:"外套",concept:"文字"}];
  record.draft.compiled=null;
  record.draft.reference_pin={example_id:"reference",source_version:"v1",role:"all"};
  record.draft.requirements={...req,contract:"requirements/1",revision:1};
  sourceResponses({workspace_a:record},posts);
  mountSource(record.id);
  const field=await screen.findByRole("textbox",{name:"原文"});
  for(const text of ["成年人站在花园里","已选角色","厚涂","全身"])expect((field as HTMLTextAreaElement).value).toContain(text);
  expect(screen.getByText(/原文来自参考案例/)).toBeVisible();
  expect(posts).toHaveLength(0);
  await waitFor(()=>expect(screen.getByRole("button",{name:"生成图像"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button",{name:"生成图像"}));
  await waitFor(()=>expect(posts).toHaveLength(1));
  expect(posts[0].body.positive_prompt).toBe((field as HTMLTextAreaElement).value);
  expect(posts[0].body.negative_prompt).toContain("水印");
  expect(posts[0].body.negative_prompt).toContain("外套");
  expect(posts[0].body.negative_prompt).toContain("文字");
});
it("preserves a compiled reference prompt verbatim when reference layers are also present",async()=>{
  const record=sourceRecord("workspace_a"),req=emptyRequirements();
  req.layers.subject.text="不能替换编译原文";
  record.draft.reference_pin={example_id:"reference",source_version:"v1",role:"all"};
  record.draft.requirements={...req,contract:"requirements/1",revision:1};
  sourceResponses({workspace_a:record},[]);
  mountSource(record.id);
  await waitFor(()=>expect(screen.getByLabelText("原文")).toHaveValue(record.draft.compiled!.positive));
  expect(screen.queryByText(/原文来自参考案例/)).toBeNull();
});
it("uses the accepted revision on a second explicit submission of a frozen workspace",async()=>{
  const original=sourceRecord("workspace_a",true),posts:{path:string;body:any}[]=[];
  sourceResponses({workspace_a:original},posts,true);
  mountSource(original.id);
  await waitFor(()=>expect(screen.getByRole("button",{name:"生成图像"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button",{name:"生成图像"}));
  await screen.findByText(/任务已接受：poll-run/);
  await waitFor(()=>expect(screen.getByRole("button",{name:"生成图像"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button",{name:"生成图像"}));
  await waitFor(()=>expect(posts).toHaveLength(2));
  expect(posts.map(item=>[item.body.source.workspace_revision,item.body.source.compiled_token,item.body.source.workflow_snapshot_run_id]))
    .toEqual([[7,"source-token","historical-run"],[8,"accepted-8","historical-run"]]);
});
it("does not substitute a live template when a historical workflow declaration is missing",async()=>{
  const original=sourceRecord("workspace_a",true),posts:{path:string;body:any}[]=[];
  delete original.draft.generation_settings!.parameter_schema;
  sourceResponses({workspace_a:original},posts);
  mountSource(original.id);
  expect(await screen.findByText(/原任务缺少匹配的工作流版本或参数声明/)).toBeVisible();
  expect(screen.getByRole("button",{name:"生成图像"})).toBeDisabled();
  expect(posts).toEqual([]);
});
it("corrects an ANIMA workspace URL and stops on an unknown workspace model",async()=>{
  const original=sourceRecord("workspace_a");
  original.draft.model_profile="anima_base_v1";
  sourceResponses({workspace_a:original},[]);
  const view=mountSource(original.id);
  await screen.findByText("/workbench?workspace=workspace_a");
  expect(screen.queryByLabelText("原文")).toBeNull();
  view.unmount();
  original.draft.model_profile="future-family";
  mountSource(original.id);
  expect(await screen.findByRole("alert")).toHaveTextContent("future-family");
  expect(screen.queryByLabelText("原文")).toBeNull();
});
it("ignores a late workspace response after navigation to another MOSS workspace",async()=>{
  const a=sourceRecord("workspace_a"),b=sourceRecord("workspace_b");
  b.draft.compiled!.positive="先显示 B，不被 A 覆盖";
  let finish!:(r:Response)=>void;
  vi.mocked(fetch).mockImplementation(async url=>String(url).endsWith(a.id)?new Promise(resolve=>{finish=resolve;}):
    new Response(JSON.stringify(String(url).endsWith(b.id)?b:{items:[]})));
  mountSource(a.id);
  fireEvent.click(screen.getByRole("link",{name:"来源 B"}));
  await waitFor(()=>expect(screen.getByLabelText("原文")).toHaveValue(b.draft.compiled!.positive));
  await act(async()=>finish(new Response(JSON.stringify(a))));
  expect(screen.getByLabelText("原文")).toHaveValue(b.draft.compiled!.positive);
});
it("keeps a late generation receipt in its originating workspace and does not post it again on return",async()=>{
  const a=sourceRecord("workspace_a"),b=sourceRecord("workspace_b");
  b.draft.compiled!.positive="B 的独立来源";
  let finish!:(r:Response)=>void,posts=0;
  const target={remote_profile_id:"cloud",remote_display_name:"测试云",workflow_profile_id:mossFlow,compatible_model_profiles:[mossId],template_revision:"live-v2"};
  vi.mocked(fetch).mockImplementation(async url=>{
    const path=String(url);
    if(path.endsWith("/direct-prompt/runs")){posts++;return new Promise(resolve=>{finish=resolve;});}
    return new Response(JSON.stringify(path.endsWith(a.id)?a:path.endsWith(b.id)?b:{items:[target]}));
  });
  mountSource(a.id);
  await waitFor(()=>expect(screen.getByRole("button",{name:"生成图像"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button",{name:"生成图像"}));
  await waitFor(()=>expect(posts).toBe(1));
  fireEvent.click(screen.getByRole("link",{name:"来源 B"}));
  await waitFor(()=>expect(screen.getByLabelText("原文")).toHaveValue(b.draft.compiled!.positive));
  await act(async()=>finish(new Response(JSON.stringify({id:"old-A-receipt",state:"draft"}))));
  expect(screen.queryByText(/old-A-receipt/)).toBeNull();
  expect(screen.queryByRole("button",{name:"查询上次提交"})).toBeNull();
  fireEvent.click(screen.getByRole("link",{name:"来源 A"}));
  await screen.findByRole("button",{name:"查询上次提交"});
  expect(posts).toBe(1);
});
function directResponses(respond: (url: string, options?: RequestInit) => Response | Promise<Response>) {
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    const path = String(url);
    if (path.endsWith("/generation-targets")) return new Response(JSON.stringify({items: ["cloud", "replacement"].map(id => ({
      remote_profile_id: id, remote_display_name: id === "cloud" ? "测试云" : "新链接",
      workflow_profile_id: "v3_moss_image_sft_int8", workflow_display_name: "MOSS",
      compatible_model_profiles: ["moss_image_sft_int8"], template_revision: "rev-1",
    }))}));
    if (path.endsWith("/direct-prompt/runs") || path.includes("/generation-submissions/by-key?")) return respond(path, options);
    if (path.endsWith("/generation-intents")) return new Response(JSON.stringify(receipt("blocked")));
    return new Response(JSON.stringify({status: "unavailable", items: []}));
  });
}
async function mountRemote() {
  const view = render(<MemoryRouter><MossWorkbenchPage modelProfiles={profiles} remoteEnabled /></MemoryRouter>);
  source();
  await screen.findByRole("option", {name: "测试云"});
  fireEvent.change(screen.getByRole("combobox", {name: "执行环境"}), {target: {value: "cloud"}});
  return view;
}
it("submits a prepared local LoRA on standalone MOSS without rewriting the raw prompt",async()=>{
  let submitted:any;
  directResponses((_url,opts)=>{submitted=JSON.parse(String(opts?.body));return Response.json({id:"moss-library-run",state:"draft"});});
  const original=vi.mocked(fetch).getMockImplementation()!;
  const sha="e".repeat(64),asset={id:sha,sha256:sha,name:"纹理",family:"moss",relative_path:"纹理.safetensors",file_name:`anima_library/${sha}.safetensors`,
    size_bytes:1024,model_profiles:[mossId],trigger_words:["texture"],weight:.6,clip_weight:null,present:true,valid:true,error:""};
  let finish:((response:Response)=>void)|undefined;
  let instance="first",syncAttempts=0;
  vi.mocked(fetch).mockImplementation(async(input,options)=>{
    const url=String(input);
    if(url.endsWith("/loras"))return Response.json({items:[asset],root_path:"loras"});
    if(url.endsWith("/cloud/sync")){syncAttempts++;return new Promise(resolve=>{finish=resolve;});}
    if(url.endsWith("/cloud/identity"))return Response.json({signature:instance});
    return original(input,options);
  });
  await mountRemote();
  fireEvent.click(screen.getByRole("button",{name:/^生成参数/}));
  fireEvent.click(screen.getByRole("button",{name:"从库中选择"}));
  fireEvent.click(await screen.findByRole("button",{name:"添加 纹理"}));
  fireEvent.click(screen.getByRole("button",{name:"返回提示词"}));
  expect(screen.getByRole("button",{name:"生成图像"})).toBeDisabled();
  await waitFor(()=>expect(finish).toBeDefined());
  const done=()=>Response.json({id:"ready",state:"completed",environment_signature:instance,results:[{sha256:sha,installed:true,cached:true}]});
  await act(async()=>{finish!(done());});
  await waitFor(()=>expect(screen.getByRole("button",{name:"生成图像"})).toBeEnabled());
  instance="same-profile-new-runtime";
  fireEvent.click(screen.getByRole("button",{name:"生成图像"}));
  await waitFor(()=>expect(syncAttempts).toBe(2));
  expect(submitted).toBeUndefined();
  expect(screen.getByRole("button",{name:"生成图像"})).toBeDisabled();
  await act(async()=>{finish!(done());});
  await waitFor(()=>expect(screen.getByRole("button",{name:"生成图像"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button",{name:"生成图像"}));
  await waitFor(()=>expect(submitted?.lora_selection).toEqual([{logical_id:"library:"+sha,sha256:sha,file_name:asset.file_name,weight:.6,clip_weight:null,enabled:true,trigger_words:["texture"]}]));
  expect(submitted.positive_prompt).toBe("少女手持写着“春天”的卡片");
},15000);
it.each(["pinned", "auto"] as const)("submits fresh MOSS parameters and request keys after an explicit %s rejection", async policy => {
  const posted: {path: string; key: string; body: any}[] = [];
  const record = sourceRecord("workspace_a");
  const storageKey = `moss-workbench-v1:workspace:${record.id}`;
  const parameters = {width: 1024, height: 1024, steps: 25, cfg: 2.5, sampler: "er_sde", scheduler: "simple", seed: "-1", batch_size: 1};
  record.draft.generation_settings = {...record.draft.generation_settings!, ...parameters,
    execution_policy: policy === "auto" ? {mode: "auto", preferredEnvironmentIds: ["cloud"]} : {mode: "pinned", environmentId: "cloud"},
    creation_configuration: {modelProfile: mossId, workflow: {id: mossFlow, revision: "live-v2"}, baseRecipeId: "custom",
      recipeValues: parameters, parameterOverrides: {}, seedMode: "random", resourceRequirements: []}};
  sourceResponses({workspace_a: record}, []);
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, options) => {
    const path = String(input);
    if (path.endsWith("/direct-prompt/runs") || path.endsWith("/generation-intents")) {
      posted.push({path, key: new Headers(options?.headers).get("Idempotency-Key")!, body: JSON.parse(String(options?.body))});
      if (posted.length === 2) return new Response(JSON.stringify({error: {
        code: "invalid_request", message: "本次请求明确未接受，请修改后重新提交。", details: {accepted: false},
      }}), {status: 422});
      const run = {id: `steps-run-${posted.length}`, state: "draft", status_message: "已接受"};
      return new Response(JSON.stringify(policy === "auto"
        ? {...receipt("accepted"), id: `steps-intent-${posted.length}`, response: run} : run));
    }
    return original(input, options);
  });
  mountSource(record.id);
  await waitFor(() => expect(screen.getByRole("button", {name: "生成图像"})).toBeEnabled());
  fireEvent.change(screen.getByLabelText("原文"), {target: {value: "一把陶瓷茶壶放在橡木桌上。"}});
  fireEvent.click(screen.getByRole("button", {name: "生成图像"}));
  await waitFor(() => expect(posted).toHaveLength(1));
  await waitFor(() => expect(JSON.parse(localStorage.getItem(storageKey)!).pending).toBeUndefined());
  await waitFor(() => expect(screen.getByRole("button", {name: "生成图像"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button", {name: /^生成参数/}));
  fireEvent.change(screen.getByLabelText("Steps", {exact: true}), {target: {value: "35"}});
  fireEvent.click(screen.getByRole("button", {name: "确认应用参数"}));
  fireEvent.click(screen.getByRole("button", {name: "返回提示词"}));
  fireEvent.click(screen.getByRole("button", {name: "生成图像"}));
  await waitFor(() => expect(posted).toHaveLength(2));
  await screen.findByText("本次请求明确未接受，请修改后重新提交。");
  expect(screen.getByRole("button", {name: "生成图像"})).toBeEnabled();
  expect(screen.queryByRole("button", {name: "继续原请求"})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: /^生成参数/}));
  fireEvent.change(screen.getByLabelText("Steps", {exact: true}), {target: {value: "37"}});
  fireEvent.click(screen.getByRole("button", {name: "确认应用参数"}));
  fireEvent.click(screen.getByRole("button", {name: "返回提示词"}));
  fireEvent.click(screen.getByRole("button", {name: "生成图像"}));
  await waitFor(() => expect(posted).toHaveLength(3));
  await waitFor(() => expect(JSON.parse(localStorage.getItem(storageKey)!).pending).toBeUndefined());
  expect(new Set(posted.map(item => item.key)).size).toBe(3);
  expect(posted.every(item => item.key)).toBe(true);
  expect(posted.map(item => (item.body.source || item.body).settings.steps)).toEqual([25, 35, 37]);
  for (const [index, item] of posted.entries()) {
    const source = item.body.source || item.body;
    expect(item.path).toBe(policy === "auto" ? "/api/v3/generation-intents" : "/api/v3/direct-prompt/runs");
    expect(source.settings).toMatchObject({width: 1024, height: 1024, cfg: 2.5, sampler: "er_sde", scheduler: "simple",
      workflow_parameter_overrides: {steps: [25, 35, 37][index]}});
    expect(source.positive_prompt).toBe("一把陶瓷茶壶放在橡木桌上。");
  }
  if (policy === "auto") expect(posted.map(item => item.body.creationConfiguration.parameterOverrides.steps)).toEqual([undefined, 35, 37]);
});

it("submits a manually entered -1 and blocks unfinished seed input without reusing the old fixed value",async()=>{
  const bodies:any[]=[];
  directResponses((_url,options)=>{
    bodies.push(JSON.parse(String(options?.body)));
    return new Response(JSON.stringify({id:"manual-random-moss",state:"draft",status_message:"已接受"}));
  });
  await mountRemote();
  fireEvent.click(screen.getByRole("button",{name:/^生成参数/}));
  const seed=screen.getByLabelText("Seed",{exact:true});
  expect(seed).toBeEnabled();
  fireEvent.change(seed,{target:{value:"8798399215689017476"}});
  fireEvent.change(seed,{target:{value:"-"}});
  expect(seed).toHaveValue("-");
  expect(screen.getByRole("button",{name:"生成图像"})).toBeDisabled();
  expect(bodies).toEqual([]);
  fireEvent.change(seed,{target:{value:"-1"}});
  expect(seed).toHaveValue("-1");
  expect(screen.getByRole("button",{name:"生成图像"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button",{name:"确认应用参数"}));
  fireEvent.click(screen.getByRole("button",{name:"返回提示词"}));
  expect(screen.getByRole("button",{name:"生成图像"})).toBeEnabled();
  fireEvent.click(screen.getByRole("button",{name:"生成图像"}));
  await screen.findByText(/manual-random-moss/);
  expect(bodies).toHaveLength(1);
  expect(bodies[0]).toMatchObject({model_profile:"moss_image_sft_int8",settings:{seed:"-1",workflow_parameter_overrides:{seed:"-1"}}});
  expect(JSON.parse(localStorage.getItem("moss-workbench-v1")!).configuration).toMatchObject({seedMode:"random",parameterOverrides:{seed:"-1"}});
});
it("accepts a saved MOSS fixed-mode -1 draft immediately after reload",async()=>{
  const bodies:any[]=[];
  directResponses((_url,options)=>{
    bodies.push(JSON.parse(String(options?.body)));
    return new Response(JSON.stringify({id:"saved-random-moss",state:"draft",status_message:"已接受"}));
  });
  const first=await mountRemote();
  first.unmount();
  const saved=JSON.parse(localStorage.getItem("moss-workbench-v1")!);
  saved.configuration.seedMode="fixed";
  saved.configuration.parameterOverrides.seed="-1";
  localStorage.setItem("moss-workbench-v1",JSON.stringify(saved));
  await mountRemote();
  expect(screen.getByLabelText("Seed",{exact:true})).toHaveValue("-1");
  expect(screen.getByText(/-1 表示每次新生成随机/)).toBeInTheDocument();
  expect(screen.getByRole("button",{name:"生成图像"})).toBeEnabled();
  fireEvent.click(screen.getByRole("button",{name:"生成图像"}));
  await screen.findByText(/saved-random-moss/);
  expect(bodies).toHaveLength(1);
  expect(bodies[0].settings.seed).toBe("-1");
});
it.each([["Steps","0"],["宽度","1025"]])("opens hidden invalid MOSS parameter %s without changing text or submitting",async(field,value)=>{
  const bodies:any[]=[];
  directResponses((_url,options)=>{
    bodies.push(JSON.parse(String(options?.body)));
    return new Response(JSON.stringify({id:"must-not-submit",state:"draft"}));
  });
  await mountRemote();
  fireEvent.click(screen.getByRole("button",{name:/^生成参数/}));
  fireEvent.change(screen.getByLabelText(field,{exact:true}),{target:{value}});
  fireEvent.click(screen.getByRole("button",{name:"返回提示词"}));
  expect(screen.queryByRole("dialog",{name:"创作辅助"})).not.toBeInTheDocument();
  const saved=localStorage.getItem("moss-workbench-v1");
  expect(screen.getByRole("button",{name:"生成图像"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button",{name:"确认生成参数"}));
  expect(screen.getByRole("dialog",{name:"创作辅助"})).toBeVisible();
  expect(screen.getByRole("tab",{name:"生成参数"})).toHaveAttribute("aria-selected","true");
  expect(screen.getByLabelText(field,{exact:true})).toBeVisible();
  expect(screen.getByLabelText(field,{exact:true})).toHaveValue(value);
  expect(screen.getByRole("button",{name:"确认应用参数"})).toBeDisabled();
  expect(screen.getByLabelText("原文")).toHaveValue("少女手持写着“春天”的卡片");
  expect(screen.getByLabelText("本次出图文本")).toHaveValue("少女手持写着“春天”的卡片");
  expect(localStorage.getItem("moss-workbench-v1")).toBe(saved);
  expect(bodies).toEqual([]);
});
it("raw preserves Chinese without LLM and keeps its independent draft", () => {
  localStorage.setItem("anima-v3-direct-prompt-draft", "untouched");
  mount();
  source();
  expect(screen.getByLabelText("本次出图文本")).toHaveValue(
    "少女手持写着“春天”的卡片",
  );
  expect(requests.some((r) => r.url.includes("prompt-assist"))).toBe(false);
  expect(localStorage.getItem("anima-v3-direct-prompt-draft")).toBe(
    "untouched",
  );
  expect(
    JSON.parse(localStorage.getItem("moss-workbench-v1")!).source,
  ).toContain("春天");
});
it.each(["polish", "expand"])(
  "reviews %s without implicit adoption or generation",
  async (mode) => {
    mount();
    source();
    fireEvent.click(
      screen.getByLabelText(mode === "polish" ? "只整理润色" : "创意扩写"),
    );
    fireEvent.click(screen.getByRole("button", { name: "获取建议" }));
    await screen.findByLabelText("建议文本");
    expect(requests.find((r) => r.url.includes("prompt-assist"))?.body).toEqual(
      {
        source_text: "少女手持写着“春天”的卡片",
        negative_prompt: "不要水印",
        mode,
      },
    );
    expect(screen.getByLabelText("本次出图文本")).toHaveValue("");
    expect(requests.some((r) => r.url.includes("generation-intents"))).toBe(
      false,
    );
    fireEvent.click(await screen.findByRole("button", { name: "采用建议" }));
    expect(screen.getByLabelText("本次出图文本")).toHaveValue(
      suggestion.positive,
    );
    fireEvent.change(screen.getByLabelText("原文"), {
      target: { value: "新的原文" },
    });
    expect(screen.getByLabelText("本次出图文本")).toHaveValue("");
  },
);
it("discards late assistance after source or mode edits", async () => {
  let finish!: (value: Response) => void;
  vi.mocked(fetch).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  mount();
  source();
  fireEvent.click(screen.getByLabelText("只整理润色"));
  fireEvent.click(screen.getByRole("button", { name: "获取建议" }));
  fireEvent.change(screen.getByLabelText("原文"), {
    target: { value: "新的原文" },
  });
  fireEvent.click(screen.getByLabelText("创意扩写"));
  finish(new Response(JSON.stringify(suggestion)));
  await waitFor(() =>
    expect(screen.queryByLabelText("建议文本")).not.toBeInTheDocument(),
  );
  expect(screen.getByLabelText("原文")).toHaveValue("新的原文");
});
it("keeps source on assistance errors", async () => {
  vi.mocked(fetch).mockResolvedValue(
    new Response(JSON.stringify({ message: "失败" }), { status: 500 }),
  );
  mount();
  source();
  fireEvent.click(screen.getByLabelText("只整理润色"));
  fireEvent.click(screen.getByRole("button", { name: "获取建议" }));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("原文")).toHaveValue("少女手持写着“春天”的卡片");
});
it("shows a safe semantic assistance error without misreporting a settings problem",async()=>{
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({error:{code:"moss_assistance_failed",message:"辅助结果未保留人物要求，请重试。"}}),{status:502}));
  mount();source();
  fireEvent.click(screen.getByLabelText("只整理润色"));
  fireEvent.click(screen.getByRole("button",{name:"获取建议"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("辅助结果未保留人物要求，请重试。");
  expect(screen.getByRole("alert")).not.toHaveTextContent("设置");
});
it.each(["failure","success"])("preserves manually edited adopted output while requesting a replacement suggestion: %s",async result=>{
  mount();source();
  fireEvent.click(screen.getByLabelText("只整理润色"));
  fireEvent.click(screen.getByRole("button",{name:"获取建议"}));
  await screen.findByLabelText("建议文本");
  fireEvent.click(await screen.findByRole("button",{name:"采用建议"}));
  fireEvent.change(screen.getByLabelText("本次出图文本"),{target:{value:"手工确认的全身像，保持这版"}});
  let finish!:(response:Response)=>void;
  vi.mocked(fetch).mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));
  fireEvent.click(screen.getByRole("button",{name:"获取建议"}));
  expect(screen.getByLabelText("本次出图文本")).toHaveValue("手工确认的全身像，保持这版");
  const response=result==="failure"
    ?new Response(JSON.stringify({message:"失败"}),{status:500})
    :new Response(JSON.stringify({...suggestion,positive:"新的待审建议"}));
  await act(async()=>finish(response));
  await waitFor(()=>expect(screen.getByRole("button",{name:"获取建议"})).toBeEnabled());
  expect(screen.getByLabelText("本次出图文本")).toHaveValue("手工确认的全身像，保持这版");
  expect(JSON.parse(localStorage.getItem("moss-workbench-v1")!).output).toBe("手工确认的全身像，保持这版");
  expect(JSON.parse(localStorage.getItem("moss-workbench-v1")!).adopted).toBe(true);
  if(result==="success"){
    expect(screen.getByLabelText("建议文本")).toHaveValue("新的待审建议");
    fireEvent.change(screen.getByLabelText("建议文本"),{target:{value:"审阅后的新建议"}});
    expect(screen.getByLabelText("本次出图文本")).toHaveValue("手工确认的全身像，保持这版");
    fireEvent.click(screen.getByRole("button",{name:"采用建议"}));
    expect(screen.getByLabelText("本次出图文本")).toHaveValue("审阅后的新建议");
  }
});
it("recognizes known historical ANIMA models without family metadata and excludes unknown models", () => {
  expect(
    modelProfileChoices([
      ...profiles,
      { id: "anima_base_v1", display_name: "Old", variant: "base" },
      { id: "unknown", display_name: "Unknown", variant: "base" },
    ]).map((x) => x.id),
  ).toEqual(["anima_base_v1"]);
});
it("submits MOSS directly and explicitly recovers an uncertain response without blocking new work", async () => {
  const keys: string[] = [];
  const bodies: any[] = [];
  const queries: string[] = [];
  const target = {
    remote_profile_id: "cloud",
    remote_display_name: "测试云",
    workflow_profile_id: "v3_moss_image_sft_int8",
    workflow_display_name: "MOSS",
    compatible_model_profiles: ["moss_image_sft_int8"],
    template_revision: "rev-1",
  };
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    if (String(url).endsWith("/generation-targets"))
      return new Response(JSON.stringify({ items: [target] }));
    if (String(url).endsWith("/generation-intents"))
      return new Response(JSON.stringify(receipt("blocked")));
    if (String(url).endsWith("/direct-prompt/runs")) {
      keys.push(new Headers(options?.headers).get("Idempotency-Key")!);
      bodies.push(JSON.parse(String(options?.body)));
      throw new TypeError("network");
    }
    if (String(url).includes("/generation-submissions/by-key?")) {
      expect(options?.method || "GET").toBe("GET");
      queries.push(String(url));
      return new Response(
        JSON.stringify({
          found: true,
          response: {
          id: "moss-run",
          state: "draft",
          status_message: "已接受，等待入队",
          },
        }),
      );
    }
    return new Response(
      JSON.stringify({
        status: "unavailable",
        remote_profile_id: "cloud",
        items: [],
      }),
    );
  });
  render(
    <MemoryRouter>
      <MossWorkbenchPage modelProfiles={profiles} remoteEnabled />
    </MemoryRouter>,
  );
  source();
  await screen.findByRole("option", { name: "测试云" });
  fireEvent.change(screen.getByRole("combobox", { name: "执行环境" }), {
    target: { value: "cloud" },
  });
  fireEvent.click(screen.getByRole("button", { name: "生成图像" }));
  await waitFor(() => expect(keys).toHaveLength(1));
  await screen.findByRole("alert");
  expect(screen.getByRole("button", { name: "生成图像" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "新建创作" })).toBeEnabled();
  expect(screen.getByRole("combobox", { name: "执行环境" })).toBeEnabled();
  fireEvent.change(screen.getByLabelText("原文"), {
    target: { value: "后续编辑，不可替换原请求" },
  });
  fireEvent.click(screen.getByRole("button", { name: "查询上次提交" }));
  await screen.findByText(/任务已接受/);
  expect(keys).toHaveLength(1);
  expect(queries).toEqual([`/api/v3/generation-submissions/by-key?key=${encodeURIComponent(keys[0])}`]);
  expect(bodies[0].positive_prompt).toBe("少女手持写着“春天”的卡片");
  expect(bodies[0].negative_prompt).toBe("不要水印");
  expect(bodies[0].settings.preset_id).toBe("moss_baseline");
  expect(bodies[0].settings).toMatchObject({
    width: 1024,
    height: 1024,
    steps: 25,
    cfg: 2.5,
    sampler: "er_sde",
    scheduler: "simple",
  });
  expect(bodies[0]).toMatchObject({
    remote_profile_id: "cloud",
    workflow_profile_id: "v3_moss_image_sft_int8",
  });
  expect(JSON.parse(localStorage.getItem("moss-workbench-v1")!).pending).toBeUndefined();
  expect(JSON.parse(localStorage.getItem("moss-workbench-v1")!).unconfirmed).toEqual([]);
  expect(screen.getByText(/moss-run/)).toHaveTextContent("已接受，等待入队");
});
it("keeps edited suggestion when an older assistance request finishes", async () => {
  mount();
  source();
  fireEvent.click(screen.getByLabelText("只整理润色"));
  fireEvent.click(screen.getByRole("button", { name: "获取建议" }));
  await screen.findByLabelText("建议文本");
  let finish!: (value: Response) => void;
  vi.mocked(fetch).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  fireEvent.click(screen.getByRole("button", { name: "获取建议" }));
  fireEvent.change(screen.getByLabelText("建议文本"), {
    target: { value: "我审阅后的建议" },
  });
  finish(new Response(JSON.stringify(suggestion)));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "获取建议" })).toBeEnabled(),
  );
  expect(screen.getByLabelText("建议文本")).toHaveValue("我审阅后的建议");
});
it.each(["direct_preparation_timeout", "invalid_request", "rate_limited"])("allows a new link and new task immediately after explicit %s rejection", async code => {
  const submitted: {key: string; body: any}[] = [];
  directResponses((_url, options) => {
    submitted.push({key: new Headers(options?.headers).get("Idempotency-Key")!, body: JSON.parse(String(options?.body))});
    return submitted.length === 1
      ? new Response(JSON.stringify({error: {code, message: "当前连接不可用，任务未接受"}}), {status: 422})
      : new Response(JSON.stringify({id: "replacement-run", state: "draft", status_message: "已接受"}));
  });
  await mountRemote();
  fireEvent.click(screen.getByRole("button", {name: /^生成参数/}));
  fireEvent.change(screen.getByLabelText("种子模式"), {target: {value: "fixed"}});
  fireEvent.change(screen.getByLabelText("Seed", {exact: true}), {target: {value: "8798399215689017476"}});
  fireEvent.change(screen.getByLabelText("Steps", {exact: true}), {target: {value: "28"}});
  fireEvent.click(screen.getByRole("button", {name: "确认应用参数"}));
  fireEvent.click(screen.getByRole("button", {name: "返回提示词"}));
  fireEvent.click(screen.getByRole("button", {name: "生成图像"}));
  await screen.findByText("当前连接不可用，任务未接受");
  expect(screen.getByRole("button", {name: "生成图像"})).toBeEnabled();
  expect(screen.queryByRole("button", {name: "查询上次提交"})).not.toBeInTheDocument();
  expect(JSON.parse(localStorage.getItem("moss-workbench-v1")!).pending).toBeUndefined();
  fireEvent.change(screen.getByRole("combobox", {name: "执行环境"}), {target: {value: "replacement"}});
  fireEvent.click(screen.getByRole("button", {name: "生成图像"}));
  await screen.findByText(/replacement-run/);
  expect(submitted).toHaveLength(2);
  expect(submitted[1].key).not.toBe(submitted[0].key);
  expect(submitted[1].body).toMatchObject({positive_prompt: "少女手持写着“春天”的卡片", negative_prompt: "不要水印", remote_profile_id: "replacement",
    settings: {seed: "8798399215689017476", steps: 28, width: 1024, height: 1024}});
  expect(screen.getByLabelText("原文")).toHaveValue("少女手持写着“春天”的卡片");
});
it("keeps uncertain recovery optional while a new link succeeds and a read-only query finds nothing yet", async () => {
  const submitted: {key: string; body: any}[] = [];
  const queried: string[] = [];
  directResponses((url, options) => {
    if (url.includes("/generation-submissions/by-key?")) {
      queried.push(url);
      return new Response(JSON.stringify({found: false, response: null}));
    }
    submitted.push({key: new Headers(options?.headers).get("Idempotency-Key")!, body: JSON.parse(String(options?.body))});
    if (submitted.length === 1) throw new TypeError("response lost");
    return new Response(JSON.stringify({id: "new-link-run", state: "draft", status_message: "已接受"}));
  });
  const view = await mountRemote();
  fireEvent.click(screen.getByRole("button", {name: "生成图像"}));
  await screen.findByRole("button", {name: "查询上次提交"});
  fireEvent.change(screen.getByRole("combobox", {name: "执行环境"}), {target: {value: "replacement"}});
  fireEvent.click(screen.getByRole("button", {name: "生成图像"}));
  await screen.findByText(/new-link-run/);
  expect(submitted[1].body.remote_profile_id).toBe("replacement");
  expect(submitted[1].key).not.toBe(submitted[0].key);
  view.unmount();
  render(<MemoryRouter><MossWorkbenchPage modelProfiles={profiles} remoteEnabled /></MemoryRouter>);
  await screen.findByRole("option", {name: "新链接"});
  expect(submitted).toHaveLength(2);
  expect(queried).toEqual([]);
  expect(screen.getByRole("button", {name: "生成图像"})).toBeEnabled();
  fireEvent.click(screen.getByRole("button", {name: /^生成参数/}));
  fireEvent.change(screen.getByLabelText("Steps", {exact:true}), {target:{value:"35"}});
  fireEvent.click(screen.getByRole("button", {name:"返回提示词"}));
  expect(screen.getByRole("button", {name:"生成图像"})).toBeDisabled();
  expect(screen.getByRole("button", {name:"查询上次提交"})).toBeEnabled();
  fireEvent.click(screen.getByRole("button", {name: "查询上次提交"}));
  await screen.findByText(/暂未找到已接受任务/);
  expect(queried).toEqual([`/api/v3/generation-submissions/by-key?key=${encodeURIComponent(submitted[0].key)}`]);
  expect(submitted).toHaveLength(2);
  expect(screen.getByRole("button", {name:"生成图像"})).toBeDisabled();
  expect(screen.getByRole("button", {name:"确认生成参数"})).toBeEnabled();
  expect(JSON.parse(localStorage.getItem("moss-workbench-v1")!).unconfirmed[0].clientRequestId).toBe(submitted[0].key);
  fireEvent.click(screen.getByRole("button", {name: "关闭这条记录"}));
  expect(screen.queryByRole("button", {name: "查询上次提交"})).not.toBeInTheDocument();
});
it("archives a persisted direct request on reopen without automatically submitting it", async () => {
  let finish!: (value: Response) => void;
  let posts = 0;
  directResponses((url) => {
    if (url.includes("/generation-submissions/by-key?")) return new Response(JSON.stringify({found: true, response: {id: "old-direct-run", state: "draft", status_message: "已接受"}}));
    posts++;
    return new Promise(resolve => {finish = resolve;});
  });
  const view = await mountRemote();
  fireEvent.click(screen.getByRole("button", {name: "生成图像"}));
  const frozen = JSON.parse(localStorage.getItem("moss-workbench-v1")!).pending;
  expect(frozen.protocol).toBe("direct-v1");
  view.unmount();
  render(<MemoryRouter><MossWorkbenchPage modelProfiles={profiles} remoteEnabled /></MemoryRouter>);
  await screen.findByRole("option", {name: "测试云"});
  expect(posts).toBe(1);
  expect(screen.getByRole("button", {name: "生成图像"})).toBeEnabled();
  const recovered = JSON.parse(localStorage.getItem("moss-workbench-v1")!);
  expect(recovered.pending).toBeUndefined();
  expect(recovered.unconfirmed).toEqual([frozen]);
  await act(async () => finish(new Response(JSON.stringify({id: "ignored-after-unmount", state: "draft"}))));
  expect(JSON.parse(localStorage.getItem("moss-workbench-v1")!).unconfirmed).toEqual([frozen]);
  fireEvent.click(screen.getByRole("button", {name: "查询上次提交"}));
  await screen.findByText(/old-direct-run/);
  expect(posts).toBe(1);
  await waitFor(() => expect(JSON.parse(localStorage.getItem("moss-workbench-v1")!).unconfirmed).toEqual([]));
});
it("clears the previous acceptance when the next direct submission is rejected", async () => {
  let posts = 0;
  directResponses(() => ++posts === 1
    ? new Response(JSON.stringify({id: "previous-run", state: "draft", status_message: "已接受"}))
    : new Response(JSON.stringify({error: {code: "workflow_incompatible", message: "新连接任务未接受"}}), {status: 422}));
  await mountRemote();
  fireEvent.click(screen.getByRole("button", {name: "生成图像"}));
  await screen.findByText(/previous-run/);
  fireEvent.change(screen.getByRole("combobox", {name: "执行环境"}), {target: {value: "replacement"}});
  fireEvent.click(screen.getByRole("button", {name: "生成图像"}));
  await screen.findByText("新连接任务未接受");
  expect(screen.queryByText(/previous-run/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", {name: "生成图像"})).toBeEnabled();
});
it("unlocks after a local response timeout and keeps the original request as uncertain without retrying it", async () => {
  let posts = 0;
  directResponses((_url, options) => {
    posts++;
    return new Promise((_resolve, reject) => options?.signal?.addEventListener("abort", () => reject(new DOMException("request timed out", "AbortError"))));
  });
  await mountRemote();
  vi.useFakeTimers();
  try {
    await act(async () => {
      fireEvent.click(screen.getByRole("button", {name: "生成图像"}));
      await vi.advanceTimersByTimeAsync(15000);
    });
    expect(screen.getByText(/本次提交结果尚未确认/)).toBeInTheDocument();
    expect(screen.getByRole("button", {name: "生成图像"})).toBeEnabled();
    expect(screen.getByRole("combobox", {name: "执行环境"})).toBeEnabled();
    expect(screen.getByRole("button", {name: "查询上次提交"})).toBeEnabled();
    expect(JSON.parse(localStorage.getItem("moss-workbench-v1")!).unconfirmed).toHaveLength(1);
    expect(JSON.parse(localStorage.getItem("moss-workbench-v1")!).pending).toBeUndefined();
    await act(async () => {await vi.advanceTimersByTimeAsync(30000);});
    expect(posts).toBe(1);
  } finally {
    vi.useRealTimers();
  }
});
it.each([
  ["submit", {}], ["submit", {id: "", state: "draft"}], ["submit", {id: "bad-run", state: "accepted"}],
  ["query", {}], ["query", {id: "", state: "draft"}], ["query", {id: "bad-run", state: "accepted"}],
] as const)("retains uncertain recovery after a malformed direct %s receipt %j", async (action, response) => {
  directResponses((url) => {
    if (url.includes("/generation-submissions/by-key?")) return new Response(JSON.stringify({found: true, response}));
    if (action === "query") throw new TypeError("accepted response lost");
    return new Response(JSON.stringify(response));
  });
  await mountRemote();
  fireEvent.click(screen.getByRole("button", {name: "生成图像"}));
  if (action === "query") {
    fireEvent.click(await screen.findByRole("button", {name: "查询上次提交"}));
  }
  await waitFor(() => expect(screen.getByRole("button", {name: "生成图像"})).toBeEnabled());
  expect(screen.getByRole("button", {name: "查询上次提交"})).toBeEnabled();
  expect(screen.queryByText(/任务已接受/)).not.toBeInTheDocument();
  const saved = JSON.parse(localStorage.getItem("moss-workbench-v1")!);
  expect(saved.pending).toBeUndefined();
  expect(saved.unconfirmed).toHaveLength(1);
});
function seedPendingIntent() {
  localStorage.setItem(
    "moss-workbench-v1",
    JSON.stringify({
      configuration: {
        modelProfile: "moss_image_sft_int8",
        workflow: { id: "v3_moss_image_sft_int8", revision: "" },
        baseRecipeId: "",
        recipeValues: {},
        parameterOverrides: {},
        resourceRequirements: [],
        seedMode: "random",
      },
      pending: {
        protocol: "intent-v1",
        clientRequestId: "frozen-key",
        body: {
          source: { positive_prompt: "冻结中文" },
          creationConfiguration: {
            workflow: {
              id: "v3_moss_image_sft_int8",
              revision: "frozen-revision",
            },
          },
          executionPolicy: { mode: "pinned", environmentId: "cloud" },
        },
      },
    }),
  );
}
it("keeps an existing automatic intent after a rejected status query", async () => {
  seedPendingIntent();
  const saved = JSON.parse(localStorage.getItem("moss-workbench-v1")!);
  saved.pending.intentId = "existing-intent";
  localStorage.setItem("moss-workbench-v1", JSON.stringify(saved));
  const calls: {path: string; method: string}[] = [];
  vi.mocked(fetch).mockImplementation(async (input, options) => {
    calls.push({path: String(input), method: options?.method || "GET"});
    return new Response(JSON.stringify({error: {code: "invalid_request", message: "查询失败", details: {accepted: false}}}), {status: 422});
  });
  mount();
  expect(screen.getByRole("button",{name:"新建创作"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button", {name: "继续原请求"}));
  await screen.findByText("尚未确认本次请求状态，请继续原请求，避免重复提交。");
  expect(JSON.parse(localStorage.getItem("moss-workbench-v1")!).pending).toEqual(saved.pending);
  expect(calls).toEqual([{path: "/api/v3/generation-intents/existing-intent", method: "GET"}]);
  expect(screen.getByRole("button", {name: "继续原请求"})).toBeEnabled();
  expect(screen.getByRole("button",{name:"新建创作"})).toBeDisabled();
});
it("recovers an uncertain automatic creation with its frozen parameters and request key", async () => {
  seedPendingIntent();
  const frozen = JSON.parse(localStorage.getItem("moss-workbench-v1")!).pending;
  frozen.body.source = {settings: {steps: 35, cfg: 2.5}};
  localStorage.setItem("moss-workbench-v1", JSON.stringify({pending: frozen}));
  const calls: {key: string; body: unknown}[] = [];
  vi.mocked(fetch).mockImplementation(async (_input, options) => {
    calls.push({key: new Headers(options?.headers).get("Idempotency-Key")!, body: JSON.parse(String(options?.body))});
    if (calls.length === 1) throw new TypeError("connection lost");
    return new Response(JSON.stringify(receipt("accepted")));
  });
  mount();
  fireEvent.click(screen.getByRole("button", {name: "继续原请求"}));
  await screen.findByText("尚未确认本次请求状态，请继续原请求，避免重复提交。");
  expect(JSON.parse(localStorage.getItem("moss-workbench-v1")!).pending).toEqual(frozen);
  fireEvent.click(screen.getByRole("button", {name: "继续原请求"}));
  await screen.findByText(/任务已接受/);
  await waitFor(() => expect(JSON.parse(localStorage.getItem("moss-workbench-v1")!).pending).toBeUndefined());
  expect(calls).toEqual([{key: frozen.clientRequestId, body: frozen.body}, {key: frozen.clientRequestId, body: frozen.body}]);
});

function receipt(state: "resolving" | "blocked" | "accepted") {
  return {
    id: "poll-intent",
    state,
    retryable: true,
    reason: state === "blocked" ? "resource_identity_unconfirmed" : null,
    candidate_progress: {
      checked:
        state === "blocked"
          ? {
              cloud: {
                eligible: false,
                reasons: ["resource_identity_unconfirmed"],
                probe: { checked_at: 0 },
              },
            }
          : {},
    },
    resolved_target: { id: "cloud" },
    run_id: state === "accepted" ? "poll-run" : null,
    response: null,
  };
}
it('serializes deferred cancellation and recovery of a frozen receipt', async () => {
  seedPendingIntent();
  let finish!: (value: Response) => void;
  let cancels = 0;
  let recoveries = 0;
  vi.mocked(fetch).mockImplementation(async (url) => {
    if (String(url).endsWith('/cancel')) {
      cancels++;
      return new Promise(resolve => { finish = resolve; });
    }
    recoveries++;
    return new Response(JSON.stringify(receipt('blocked')));
  });
  mount();
  fireEvent.click(screen.getByRole('button', {name: '继续原请求'}));
  const cancel = await screen.findByRole('button', {name: '取消本次生成'});
  act(() => {
    fireEvent.click(cancel);
    fireEvent.click(cancel);
    fireEvent.click(screen.getByRole('button', {name: '继续原请求'}));
  });
  expect(cancel).toBeDisabled();
  expect(cancels).toBe(1);
  expect(recoveries).toBe(1);
  expect(JSON.parse(localStorage.getItem('moss-workbench-v1')!).pending.clientRequestId).toBe('frozen-key');
  await act(async () => finish(new Response(JSON.stringify({...receipt('blocked'), state: 'canceled'}))));
  await screen.findByRole('button', {name: '生成图像'});
  expect(JSON.parse(localStorage.getItem('moss-workbench-v1')!).pending).toBeUndefined();
});
it('ignores deferred receipt actions after unmount', async () => {
  seedPendingIntent();
  let finish!: (value: Response) => void;
  vi.mocked(fetch).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const view = mount();
  fireEvent.click(screen.getByRole('button', {name: '继续原请求'}));
  view.unmount();
  const saved = localStorage.getItem('moss-workbench-v1');
  await act(async () => finish(new Response(JSON.stringify(receipt('accepted')))));
  expect(localStorage.getItem('moss-workbench-v1')).toBe(saved);
});
it('keeps a newer uncertain request when an older resolving response arrives', async () => {
  seedPendingIntent();
  let oldResponse!: (value: Response) => void;
  let newResponse!: (value: Response) => void;
  let oldReads = 0;
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    const path = String(url);
    if (path.endsWith('/generation-targets')) return new Response(JSON.stringify({items: [{
      remote_profile_id: 'cloud', remote_display_name: '测试云',
      workflow_profile_id: 'v3_moss_image_sft_int8', compatible_model_profiles: ['moss_image_sft_int8'], template_revision: 'rev-1',
    }]}));
    if (path.endsWith('/cancel')) return new Response(JSON.stringify({...receipt('blocked'), state: 'canceled'}));
    if (path.endsWith('/poll-intent')) {
      oldReads++;
      return new Promise(resolve => { oldResponse = resolve; });
    }
    if (path.endsWith('/generation-intents')) {
      if (new Headers(options?.headers).get('Idempotency-Key') === 'frozen-key')
        return new Response(JSON.stringify(receipt('resolving')));
    }
    if (path.endsWith('/direct-prompt/runs')) return new Promise(resolve => { newResponse = resolve; });
    return new Response(JSON.stringify({items: []}));
  });
  render(<MemoryRouter><MossWorkbenchPage modelProfiles={profiles} remoteEnabled /></MemoryRouter>);
  await screen.findByRole('option', {name: '测试云'});
  fireEvent.change(screen.getByRole('combobox', {name: '执行环境'}), {target: {value: 'cloud'}});
  fireEvent.click(screen.getByRole('button', {name: '继续原请求'}));
  await waitFor(() => expect(oldReads).toBe(1), {timeout: 2000});
  fireEvent.click(screen.getByRole('button', {name: '取消本次生成'}));
  await screen.findByRole('button', {name: '生成图像'});
  source();
  fireEvent.click(screen.getByRole('button', {name: '生成图像'}));
  const frozen = JSON.parse(localStorage.getItem('moss-workbench-v1')!).pending;
  expect(frozen.clientRequestId).not.toBe('frozen-key');
  await act(async () => oldResponse(new Response(JSON.stringify(receipt('accepted')))));
  expect(JSON.parse(localStorage.getItem('moss-workbench-v1')!).pending).toEqual(frozen);
  expect(screen.getByRole('button', {name: '生成图像'})).toBeDisabled();
  await act(async () => newResponse(new Response('{}', {status: 500})));
  expect(screen.getByRole('button', {name: '生成图像'})).toBeEnabled();
  expect(screen.getByRole('button', {name: '查询上次提交'})).toBeEnabled();
  expect(JSON.parse(localStorage.getItem('moss-workbench-v1')!).pending).toBeUndefined();
  expect(JSON.parse(localStorage.getItem('moss-workbench-v1')!).unconfirmed).toEqual([frozen]);
});
it.each(["blocked", "accepted"] as const)(
  "polls a resolving receipt to %s using GET only",
  async (state) => {
    seedPendingIntent();
    const calls: { url: string; method: string }[] = [];
    vi.mocked(fetch).mockImplementation(async (url, options) => {
      calls.push({ url: String(url), method: options?.method || "GET" });
      return new Response(
        JSON.stringify(
          options?.method === "POST" ? receipt("resolving") : receipt(state),
        ),
      );
    });
    mount();
    fireEvent.click(screen.getByRole("button", { name: "继续原请求" }));
    await screen.findByText(/正在检查环境/);
    if (state === "accepted") {
      await screen.findByText(/任务已接受/);
      expect(
        JSON.parse(localStorage.getItem("moss-workbench-v1")!).pending,
      ).toBeUndefined();
    } else {
      await screen.findByRole("button", { name: "确认当前环境资源映射" });
      expect(
        JSON.parse(localStorage.getItem("moss-workbench-v1")!).pending
          .clientRequestId,
      ).toBe("frozen-key");
    }
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
    expect(calls.filter((c) => c.method === "GET")).toEqual([
      { url: "/api/v3/generation-intents/poll-intent", method: "GET" },
    ]);
  },
);
it("ignores polling after unmount and after a newer terminal receipt", async () => {
  seedPendingIntent();
  let finish!: (value: Response) => void;
  let reads = 0;
  vi.mocked(fetch).mockImplementation(async (_url, options) => {
    if (options?.method === "POST")
      return new Response(JSON.stringify(receipt("resolving")));
    if (++reads === 1)
      return new Promise((resolve) => {
        finish = resolve;
      });
    return new Response(JSON.stringify(receipt("accepted")));
  });
  const view = mount();
  fireEvent.click(screen.getByRole("button", { name: "继续原请求" }));
  await waitFor(() => expect(reads).toBe(1), { timeout: 2000 });
  fireEvent.click(screen.getByRole("button", { name: "继续原请求" }));
  await screen.findByText(/任务已接受/);
  finish(new Response(JSON.stringify(receipt("blocked"))));
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: "确认当前环境资源映射" }),
    ).not.toBeInTheDocument(),
  );
  expect(
    JSON.parse(localStorage.getItem("moss-workbench-v1")!).pending,
  ).toBeUndefined();
  view.unmount();
  seedPendingIntent();
  reads = 0;
  const second = mount();
  fireEvent.click(screen.getByRole("button", { name: "继续原请求" }));
  await waitFor(() => expect(reads).toBe(1), { timeout: 2000 });
  second.unmount();
  const saved = localStorage.getItem("moss-workbench-v1");
  finish(new Response(JSON.stringify(receipt("accepted"))));
  await new Promise((resolve) => setTimeout(resolve, 30));
  expect(localStorage.getItem("moss-workbench-v1")).toBe(saved);
});
