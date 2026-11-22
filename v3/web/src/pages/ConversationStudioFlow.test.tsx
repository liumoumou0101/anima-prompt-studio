import {act, cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {MemoryRouter, Route, Routes} from "react-router-dom";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {ConversationWorkbenchPage} from "./ConversationWorkbenchPage";
import {emptyRequirements, type ConversationRecord} from "../lib/conversation";
import {basicWorkflowSchema} from "../lib/workflowParameterSchema";
import {defaultGenerationSettings} from "../lib/generationSettings";
import {clearConversationPending, getConversationPendingKey, listConversationDraftCandidates, readConversationDraft, recoverConversationPending, saveConversationPending} from "../lib/conversationDrafts";

vi.mock("../components/ArtistRecommendations", () => ({ArtistRecommendations: () => null}));
vi.mock("../components/ManualIdentityTags", () => ({ManualIdentityTags: () => null}));
vi.mock("../components/SceneDesignControls", () => ({SceneDesignControls: () => null}));
let workspace: ConversationRecord;
let writes: {url:string; body:any; key:string|null}[];
let failTurn: boolean;
let failGenerate: boolean;
const target = {remote_profile_id:"cloud",workflow_profile_id:"workflow",remote_display_name:"测试服务器",workflow_display_name:"基础工作流",compatible_model_profiles:["anima_base_v1","anima_turbo_v1_1"],availability:"ready",template_revision:"revision",parameter_schema:basicWorkflowSchema("workflow","revision")};
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear(); sessionStorage.setItem("anima-v3-session","test");
  const requirements=emptyRequirements(); requirements.layers.subject.text="蓝外套人物";
  workspace={id:"studio",title:"创作流程",revision:3,created_at:"2026-09-21",updated_at:"2026-09-21",draft:{positive_text:"",excluded_text:"",model_profile:"anima_base_v1",mode:"faithful",requirements:{...requirements,contract:"anima-requirements/1",revision:1},generation_settings:{...defaultGenerationSettings(),remote_profile_id:"cloud",workflow_profile_id:"workflow",execution_policy:{mode:"auto",preferredEnvironmentIds:["cloud"]}},compiled:{positive:"woman, blue coat",negative:"blurry",source:"llm",compiled_token:"cmp3"},compile_state:"fresh",conversation_events:[]}};
  localStorage.setItem("anima-conversation-active",JSON.stringify(workspace.id)); writes=[]; failTurn=false; failGenerate=false;
  vi.spyOn(globalThis,"fetch").mockImplementation(async(input,init)=>{
    const url=String(input),body=init?.body?JSON.parse(String(init.body)):null;
    if(body) writes.push({url,body,key:new Headers(init?.headers).get("Idempotency-Key")});
    let response:unknown={items:[]};
    if(url.endsWith("/llm/settings")) response={current:{service:"test",model:"small",workbench_enable_thinking:false,thinking:{mode:"switchable",message:""}},services:[]};
    else if(url.includes("/workspaces?")) response={items:[workspace]};
    else if(url.endsWith("/generation-targets")) response={items:[target]};
    else if(url.includes("/availability")) response={availability:"ready",template_revision:"revision",parameter_schema:basicWorkflowSchema("workflow","revision")};
    else if(url.endsWith("/proposal")) response={proposal:null};
    else if(url.includes("/versions?")) response={items:[workspace]};
    else if(url.endsWith("/editor-restore")) {
      workspace={...workspace,revision:workspace.revision+1,draft:{...workspace.draft,model_profile:body.draft.model_profile,mode:body.draft.mode,
        generation_settings:body.draft.generation_settings,requirements:{...body.draft.requirements_edit,contract:"anima-requirements/1",revision:2},
        ...(body.draft.prompt_edit?{compiled:{...workspace.draft.compiled!,...body.draft.prompt_edit,source:"user" as const,compiled_token:"cmp-restored"}}:{})}};
      response=workspace;
    }
    else if(url.endsWith("/workbench/turns")) {
      if(failTurn)return new Response(JSON.stringify({error:{code:"llm_generation_failed",message:"更新失败"}}),{status:502});
      const next={...workspace,revision:workspace.revision+1,draft:{...workspace.draft,compiled:{...workspace.draft.compiled!,positive:"woman, red coat",compiled_token:"cmp-updated"},conversation_events:[{id:"event",delta:body.delta.text,changed_layers:[],warnings:[],created_at:"2026-09-21"}]}};
      if(body.preview) response={id:"proposal",workspace_id:"studio",base_revision:workspace.revision,draft:next.draft,changed_layers:[],warnings:[],created_at:"2026-09-21"};
      else {workspace=next;response=workspace;}
    } else if(url.endsWith("/generation-intents")) {
      if(failGenerate) throw new TypeError("lost response");
      workspace={...workspace,revision:workspace.revision+1,draft:{...workspace.draft,compiled:{...workspace.draft.compiled!,positive:body.source.positive_prompt,negative:body.source.negative_prompt,compiled_token:"cmp-generated"},compile_state:"fresh"}};
      response={id:"intent-new",state:"accepted",retryable:false,reason:null,candidate_progress:{},resolved_target:{id:"cloud",display_name:"测试服务器"},submission_id:"sub-new",run_id:"run-new",response:{id:"run-new",state:"draft",artifact_count:0,status_message:"已接受",workspace_revision:workspace.revision,compiled_token:"cmp-generated"}};
    } else if(url.endsWith("/workspaces/studio")) {
      if(init?.method==="PUT") workspace={...workspace,revision:workspace.revision+1,draft:{...workspace.draft,model_profile:body.draft.model_profile,mode:body.draft.mode,generation_settings:body.draft.generation_settings,requirements:{...body.draft.requirements_edit,contract:"anima-requirements/1",revision:2},...(body.draft.prompt_edit?{compiled:{...workspace.draft.compiled!,...body.draft.prompt_edit,source:"user" as const,compiled_token:"cmp-saved"}}:{})}};
      response=workspace;
    }
    return new Response(JSON.stringify(response));
  });
});
afterEach(()=>{cleanup();vi.restoreAllMocks();});
async function mount(){render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);await screen.findByLabelText("正向提示词");await waitFor(()=>expect(screen.getByRole("button",{name:"生成图片"})).toBeEnabled());}
const delta=()=>screen.getByLabelText(/这次想怎么改|继续追加要求/);
it("applies a rewrite directly and undoes it as one operation",async()=>{
  await mount();fireEvent.change(delta(),{target:{value:"外套换红色"}});fireEvent.click(screen.getByRole("button",{name:"更新提示词"}));
  await waitFor(()=>expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, red coat"));
  expect(writes.find(x=>x.url.endsWith("/turns"))?.body.preview).toBe(false);
  expect(screen.queryByRole("button",{name:"采用修改"})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:/^撤销(编辑)?$/}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, blue coat");expect(delta()).toHaveValue("外套换红色");
});
it("generates visible manual text and current settings while retaining pending instructions",async()=>{
  await mount();fireEvent.change(screen.getByLabelText("正向提示词"),{target:{value:"woman, green coat"}});
  fireEvent.change(delta(),{target:{value:"尚未应用的月夜意见"}});
  fireEvent.change(screen.getByLabelText("模型",{exact:true}),{target:{value:"anima_turbo_v1_1"}});
  fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await waitFor(()=>expect(writes.some(x=>x.url.endsWith("/generation-intents"))).toBe(true));
  expect(writes.find(x=>x.url.endsWith("/generation-intents"))?.body.source).toMatchObject({positive_prompt:"woman, green coat",model_profile:"anima_turbo_v1_1",use_current_prompt:true});
  expect(writes.some(x=>x.url.endsWith("/turns"))).toBe(false);
  await waitFor(()=>expect(delta()).toHaveValue("尚未应用的月夜意见"));
});
it("combined update submits the updated prompt once",async()=>{
  await mount();fireEvent.change(delta(),{target:{value:"外套换红色"}});fireEvent.click(screen.getByRole("button",{name:"更新并生图"}));
  await waitFor(()=>expect(writes.some(x=>x.url.endsWith("/generation-intents"))).toBe(true));
  expect(writes.filter(x=>x.url.endsWith("/turns"))).toHaveLength(1);
  expect(writes.filter(x=>x.url.endsWith("/generation-intents"))).toHaveLength(1);
  expect(writes.find(x=>x.url.endsWith("/generation-intents"))?.body.source.positive_prompt).toBe("woman, red coat");
});
it("does not generate if the combined update fails",async()=>{
  failTurn=true;await mount();fireEvent.change(delta(),{target:{value:"外套换红色"}});fireEvent.click(screen.getByRole("button",{name:"更新并生图"}));
  await screen.findByText(/更新失败/);expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, blue coat");expect(delta()).toHaveValue("外套换红色");expect(writes.some(x=>x.url.endsWith("/generation-intents"))).toBe(false);
});
it("reuses a frozen submission after an unknown acceptance result",async()=>{
  failGenerate=true;await mount();fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await screen.findByRole("button",{name:"查询本次提交"});
  expect(recoverConversationPending("studio")?.key).toBe(writes.find(x=>x.url.endsWith("/generation-intents"))?.key);
  expect(screen.getByRole("button",{name:"生成图片"})).toBeDisabled();
  failGenerate=false;
  fireEvent.click(screen.getByRole("button",{name:"查询本次提交"}));
  await waitFor(()=>expect(writes.filter(x=>x.url.endsWith("/generation-intents"))).toHaveLength(2));
  const calls=writes.filter(x=>x.url.endsWith("/generation-intents"));expect(calls[1].key).toBe(calls[0].key);expect(calls[1].body).toEqual(calls[0].body);
});
it("reconciles a request settled in another page without resubmitting or losing the draft",async()=>{
  failGenerate=true;await mount();
  fireEvent.change(screen.getByLabelText("正向提示词"),{target:{value:"my manual prompt"}});
  fireEvent.change(delta(),{target:{value:"未提交的意见"}});
  fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await screen.findByRole("button",{name:"查询本次提交"});
  clearConversationPending("studio",recoverConversationPending("studio")!);
  fireEvent.click(screen.getByRole("button",{name:"查询本次提交"}));
  await screen.findByText(/这次请求已完成.*全部任务/);
  expect(screen.queryByRole("button",{name:"查询本次提交"})).not.toBeInTheDocument();
  expect(screen.getByRole("button",{name:"生成图片"})).toBeEnabled();
  expect(screen.getByLabelText("正向提示词")).toHaveValue("my manual prompt");expect(delta()).toHaveValue("未提交的意见");
  expect(writes.filter(x=>x.url.endsWith("/generation-intents"))).toHaveLength(1);
  expect(recoverConversationPending("studio")).toBeNull();
});
it("keeps a different unresolved request when reconciling a settled request",async()=>{
  failGenerate=true;await mount();fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await screen.findByRole("button",{name:"查询本次提交"});
  const previous=recoverConversationPending("studio")!;
  clearConversationPending("studio",previous);
  const unresolved={...previous,key:"another-unresolved-request"};saveConversationPending("studio",unresolved);
  fireEvent.click(screen.getByRole("button",{name:"查询本次提交"}));
  await screen.findByText(/这次请求已完成.*全部任务/);
  expect(screen.getByRole("button",{name:"查询本次提交"})).toBeEnabled();
  expect(screen.getByRole("button",{name:"生成图片"})).toBeDisabled();
  expect(recoverConversationPending("studio")).toEqual(unresolved);
  expect(writes.filter(x=>x.url.endsWith("/generation-intents"))).toHaveLength(1);
  fireEvent.click(screen.getByRole("button",{name:"查询本次提交"}));
  await waitFor(()=>expect(writes.filter(x=>x.url.endsWith("/generation-intents"))).toHaveLength(2));
  expect(writes.filter(x=>x.url.endsWith("/generation-intents"))[1].key).toBe(unresolved.key);
});
it("blocks new submissions if recovery fails after another page settles the displayed request",async()=>{
  failGenerate=true;await mount();fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await screen.findByRole("button",{name:"查询本次提交"});
  clearConversationPending("studio",recoverConversationPending("studio")!);
  localStorage.setItem(getConversationPendingKey("studio"),"{broken");
  fireEvent.click(screen.getByRole("button",{name:"查询本次提交"}));
  await screen.findByText(/上次生成请求的恢复记录无法读取或迁移/);
  expect(screen.queryByRole("button",{name:"查询本次提交"})).not.toBeInTheDocument();
  expect(screen.getByRole("button",{name:"生成图片"})).toBeDisabled();
  expect(writes.filter(x=>x.url.endsWith("/generation-intents"))).toHaveLength(1);
  expect(localStorage.getItem(getConversationPendingKey("studio"))).toBe("{broken");
});
it("keeps a blocked intent frozen until cancellation allows editing missing resources",async()=>{
  const original=vi.mocked(fetch).getMockImplementation()!;
  const blocked={id:"intent-blocked",state:"blocked",retryable:true,reason:"no_eligible_environment",candidate_progress:{input_error:{message:"缺少指定 LoRA"}},resolved_target:null,response:null,run_id:null,submission_id:null};
  vi.mocked(fetch).mockImplementation(async(input,init)=>String(input).endsWith("/generation-intents")?new Response(JSON.stringify(blocked))
    :String(input).endsWith("/intent-blocked/cancel")?new Response(JSON.stringify({...blocked,state:"canceled"})):original(input,init));
  await mount();fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await screen.findByText("缺少指定 LoRA");expect(screen.getByLabelText("模型")).toBeDisabled();
  fireEvent.click(screen.getByRole("button",{name:"取消本次生成"}));
  await waitFor(()=>expect(screen.queryByRole("button",{name:"查询本次提交"})).not.toBeInTheDocument());expect(screen.getByLabelText("模型")).toBeEnabled();
});
it("does not auto-generate another window's update after a lost rewrite response",async()=>{
  const original=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    if(String(input).endsWith("/turns")){
      const before=workspace.revision,body=JSON.parse(String(init?.body));
      workspace={...workspace,revision:before+2,draft:{...workspace.draft,compiled:{...workspace.draft.compiled!,positive:"other window prompt"},conversation_events:[{id:"event",delta:body.delta.text,changed_layers:[],warnings:[],created_at:"2026-09-21",before_revision:before,after_revision:before+1}]}};
      throw new TypeError("lost response");
    }return original(input,init);
  });
  await mount();fireEvent.change(delta(),{target:{value:"外套换红色"}});fireEvent.click(screen.getByRole("button",{name:"更新并生图"}));
  await screen.findByText(/其他窗口.*保存了.*修改|其他窗口已保存了更新/);expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, blue coat");expect(writes.some(x=>x.url.endsWith("/generation-intents"))).toBe(false);
});
it("keeps an accepted generation as the merge base when a later server edit appears",async()=>{
  const original=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    const response=await original(input,init);
    if(String(input).endsWith("/generation-intents")) workspace={...workspace,revision:workspace.revision+1,draft:{...workspace.draft,compiled:{...workspace.draft.compiled!,positive:"another window saved this"}}};
    return response;
  });
  await mount();fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await screen.findByText(/其他窗口已保存了更新/, {selector:"strong"});expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, blue coat");expect(screen.getByRole("button",{name:"生成图片"})).toBeDisabled();
});
function withOldImage(model="anima_base_v1",positive="woman, red coat"){
  const original=vi.mocked(fetch).getMockImplementation()!;
  const version=structuredClone(workspace);version.revision=2;version.draft.compiled!.positive="woman, red coat";
  const run={id:"old-image",state:"completed",artifact_count:0,created_at:"2026-09-20",status_message:"完成",remote_profile_id:"cloud",workflow_profile_id:"workflow",source:{workspace_revision:2,positive_prompt:positive,negative_prompt:"blurry",model_profile:model,settings:{...defaultGenerationSettings(),seed:42}}};
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    const url=String(input);
    if(url.includes("/workspaces/studio/runs?"))return new Response(JSON.stringify({items:[run]}));
    if(url.includes("/versions?"))return new Response(JSON.stringify({items:[workspace,version]}));
    return original(input,init);
  });
}
it("continues a MOSS result from ANIMA history in a separate workspace and keeps the current edits",async()=>{
  withOldImage("moss_image_sft_int8","清晨的书房\n一盏台灯");
  const original=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    if(String(input)==="/api/v3/generation-runs/old-image/workspace"){
      return new Response(JSON.stringify({...workspace,id:"workspace_moss",draft:{...workspace.draft,model_profile:"moss_image_sft_int8"}}));
    }
    return original(input,init);
  });
  render(<MemoryRouter initialEntries={["/workbench"]}><Routes>
    <Route path="/workbench" element={<ConversationWorkbenchPage remoteEnabled/>}/>
    <Route path="/moss" element={<p>MOSS 来源会话</p>}/>
  </Routes></MemoryRouter>);
  fireEvent.change(await screen.findByLabelText("正向提示词"),{target:{value:"an independent ANIMA draft"}});
  fireEvent.click(await screen.findByRole("button",{name:"从这张继续"}));
  await screen.findByText("MOSS 来源会话");
  expect(readConversationDraft("studio")!.local!.positive).toBe("an independent ANIMA draft");
  expect(workspace.draft.model_profile).toBe("anima_base_v1");
  expect(writes.some(item=>item.url.endsWith("/editor-restore")||item.url.endsWith("/generation-intents"))).toBe(false);
});
it("restores an old image in place and can undo back to the displaced draft",async()=>{
  withOldImage();await mount();fireEvent.change(screen.getByLabelText("模型"),{target:{value:"anima_turbo_v1_1"}});
  fireEvent.click(screen.getByRole("button",{name:"生成参数"}));
  fireEvent.change(screen.getByLabelText("Steps"),{target:{value:"12"}});
  fireEvent.click(screen.getByRole("button",{name:"确认应用参数"}));
  fireEvent.click(screen.getByRole("button",{name:"结果"}));
  fireEvent.change(screen.getByLabelText("正向提示词"),{target:{value:"my unsaved prompt"}});fireEvent.change(delta(),{target:{value:"还没提交的意见"}});
  fireEvent.click(await screen.findByRole("button",{name:"从这张继续"}));
  await waitFor(()=>expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, red coat"));expect(screen.getByLabelText("模型")).toHaveValue("anima_base_v1");expect(delta()).toHaveValue("");
  const restored=readConversationDraft("studio")!.local!.settings;
  expect(restored.model_configurations?.anima_turbo_v1_1.parameterOverrides.steps).toBe(12);
  expect(restored.model_configurations).not.toHaveProperty("anima_base_v1");
  fireEvent.click(screen.getByRole("button",{name:"撤销"}));expect(screen.getByLabelText("正向提示词")).toHaveValue("my unsaved prompt");expect(screen.getByLabelText("模型")).toHaveValue("anima_turbo_v1_1");expect(delta()).toHaveValue("还没提交的意见");expect(writes.some(item=>item.url.endsWith("/generation-intents")||item.url.endsWith("/turns"))).toBe(false);
});
it("only using image text keeps current resources and explicitly clears obsolete prompt locks",async()=>{
  workspace.draft.model_profile="anima_turbo_v1_1";
  workspace.draft.requirements!.prompt_locks=[{target:"positive",text:"blue coat"}];
  workspace.draft.requirements!.loras=[{logical_id:"my-lora",file_name:"mine.safetensors",weight:1,trigger_words:[],required:true,source:{kind:"user"}}];
  withOldImage("moss_image_sft_int8","清晨的书房\n一盏台灯");await mount();
  fireEvent.click(await screen.findByRole("button",{name:"只用提示词"}));
  expect(screen.getByLabelText("模型")).toHaveValue("anima_turbo_v1_1");
  expect(screen.getByLabelText("正向提示词")).toHaveValue("清晨的书房\n一盏台灯");
  await waitFor(()=>expect(screen.getByRole("button",{name:"生成图片"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await waitFor(()=>expect(writes.some(x=>x.url.endsWith("/generation-intents"))).toBe(true));
  const saved=writes.find(x=>x.url.endsWith("/editor-restore"))!.body.draft;
  expect(saved.requirements_edit.prompt_locks).toEqual([]);expect(saved.requirements_edit.loras[0].logical_id).toBe("my-lora");expect(saved.model_profile).toBe("anima_turbo_v1_1");
});

it("recovers the frozen intent after lost response then cancels a missing LoRA block before editing", async () => {
  failGenerate = true;
  const original = vi.mocked(fetch).getMockImplementation()!;
  const submitted: {key: string | null; body: string}[] = [];
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith("/generation-intents")) {
      submitted.push({key: new Headers(init?.headers).get("Idempotency-Key"), body: String(init?.body)});
      if (submitted.length === 2) return new Response(JSON.stringify({id:"intent-blocked",state:"blocked",retryable:true,reason:"no_eligible_environment",
        candidate_progress:{input_error:{message:"指定 LoRA 尚未安装"}},resolved_target:null,response:null,run_id:null,submission_id:null}));
    }
    if(String(input).endsWith("/intent-blocked/cancel"))return new Response(JSON.stringify({id:"intent-blocked",state:"canceled",retryable:false,candidate_progress:{},resolved_target:null,response:null,run_id:null,submission_id:null}));
    return original(input, init);
  });
  await mount();
  fireEvent.click(screen.getByRole("button", {name: "生成图片"}));
  const query = await screen.findByRole("button", {name: "查询本次提交"});
  expect(screen.getByLabelText("模型")).toBeDisabled();
  expect(recoverConversationPending("studio")?.key).toBe(submitted[0].key);
  fireEvent.click(query);
  await screen.findByText("指定 LoRA 尚未安装");
  expect(submitted).toHaveLength(2);
  expect(submitted[1]).toEqual(submitted[0]);
  expect(screen.getByLabelText("模型")).toBeDisabled();
  fireEvent.click(screen.getByRole("button",{name:"取消本次生成"}));
  await waitFor(()=>expect(screen.queryByRole("button", {name: "查询本次提交"})).not.toBeInTheDocument());
  expect(recoverConversationPending("studio")).toBeNull();
  expect(screen.getByLabelText("模型")).toBeEnabled();
  fireEvent.change(screen.getByLabelText("模型"), {target: {value: "anima_turbo_v1_1"}});
  expect(screen.getByLabelText("模型")).toHaveValue("anima_turbo_v1_1");
  expect(screen.getByRole("button", {name: "生成图片"})).toBeEnabled();
});

it("forks a saved history step while preserving the current manual prompt and unsent request", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  const older = structuredClone(workspace); older.revision = 2; older.draft.compiled!.positive = "woman, red coat";
  const forkRequests: {key: string | null; body: string}[] = [];
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.includes("/versions?")) return new Response(JSON.stringify({items: [workspace, older]}));
    if (url.endsWith("/workspaces/studio/versions/2/fork")) {
      forkRequests.push({key: new Headers(init?.headers).get("Idempotency-Key"), body: String(init?.body)});
      return new Response(JSON.stringify({...older, id: "studio-fork", title: "红外套分支", revision: 1,
        draft: {...older.draft, workspace_origin: {workspace_id: "studio", revision: 2, run_id: null}}}));
    }
    return original(input, init);
  });
  await mount();
  fireEvent.change(screen.getByLabelText("正向提示词"), {target: {value: "my manually edited blue scene"}});
  fireEvent.change(delta(), {target: {value: "这段月夜修改还没发送"}});
  fireEvent.click(screen.getByRole("button", {name: "创作记录"}));
  for (const summary of await screen.findAllByText("更多操作", {selector: "summary"})) fireEvent.click(summary);
  fireEvent.click(screen.getByRole("button", {name: "从版本 2 另开会话"}));
  await waitFor(() => expect(screen.getByLabelText("打开已有会话")).toHaveValue("studio-fork"));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, red coat");
  expect(forkRequests).toHaveLength(1);
  expect(forkRequests[0].key).toBeTruthy();
  expect(readConversationDraft("studio")?.local).toMatchObject({positive: "my manually edited blue scene", delta: "这段月夜修改还没发送"});
  expect(listConversationDraftCandidates("studio").candidates.some(item => item.kind === "snapshot"
    && item.local?.positive === "my manually edited blue scene" && item.local.delta === "这段月夜修改还没发送")).toBe(true);
  expect(workspace.revision).toBe(3);
  expect(writes.some(item => item.url.endsWith("/turns") || item.url.endsWith("/generation-intents"))).toBe(false);
});

it("keeps the accepted image preview when an earlier runs-list request returns an empty result late", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  let releaseList!: (response: Response) => void;
  let listRequests = 0;
  vi.mocked(fetch).mockImplementation((input, init) => {
    if (String(input).includes("/workspaces/studio/runs?") && ++listRequests === 1) {
      return new Promise(resolve => {releaseList = resolve;});
    }
    return original(input, init);
  });
  await mount();
  expect(listRequests).toBe(1);
  fireEvent.click(screen.getByRole("button", {name: "生成图片"}));
  await screen.findByText("已接受");
  await waitFor(() => expect(screen.getByRole("button", {name: "生成图片"})).toBeEnabled());
  await act(async () => {releaseList(new Response(JSON.stringify({items: []})));});
  expect(screen.getByText("已接受")).toBeVisible();
  expect(screen.queryByText("图片会出现在这里")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "查询本次提交"})).not.toBeInTheDocument();
  expect(recoverConversationPending("studio")).toBeNull();
  expect(writes.filter(item => item.url.endsWith("/generation-intents"))).toHaveLength(1);
});

it("replays a pre-upgrade legacy pending request with its unchanged protocol, key and body", async () => {
  const original=vi.mocked(fetch).getMockImplementation()!;
  const legacy={key:"legacy-before-upgrade",body:JSON.stringify({submission_kind:"conversational",workspace_id:"studio",workspace_revision:3,
    compiled_token:"cmp3",positive_prompt:"frozen legacy cat",negative_prompt:"blurry",model_profile:"anima_base_v1",
    remote_profile_id:"cloud",workflow_profile_id:"workflow",settings:{seed:"8798399215689017476"}})};
  saveConversationPending("studio",legacy);
  const replay:{key:string|null;body:string}[]=[];
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    if(String(input).endsWith("/direct-prompt/runs")){
      replay.push({key:new Headers(init?.headers).get("Idempotency-Key"),body:String(init?.body)});
      return new Response(JSON.stringify({id:"legacy-run",state:"draft",artifact_count:0,status_message:"旧提交已确认",workspace_revision:3,compiled_token:"cmp3"}));
    }
    return original(input,init);
  });
  render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button",{name:"查询本次提交"}));
  await screen.findByText("旧提交已确认");
  expect(replay).toEqual([{key:legacy.key,body:legacy.body}]);
  expect(writes.some(item=>item.url.endsWith("/generation-intents"))).toBe(false);
  expect(recoverConversationPending("studio")).toBeNull();
});
