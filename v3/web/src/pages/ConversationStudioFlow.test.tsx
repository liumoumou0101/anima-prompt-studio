import {act, cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {ConversationWorkbenchPage} from "./ConversationWorkbenchPage";
import {emptyRequirements, type ConversationRecord} from "../lib/conversation";
import {defaultGenerationSettings} from "../lib/generationSettings";
import {listConversationDraftCandidates, readConversationDraft, recoverConversationPending} from "../lib/conversationDrafts";

vi.mock("../components/ArtistRecommendations", () => ({ArtistRecommendations: () => null}));
vi.mock("../components/ManualIdentityTags", () => ({ManualIdentityTags: () => null}));
vi.mock("../components/SceneDesignControls", () => ({SceneDesignControls: () => null}));
let workspace: ConversationRecord;
let writes: {url:string; body:any; key:string|null}[];
let failTurn: boolean;
let failGenerate: boolean;
const target = {remote_profile_id:"cloud",workflow_profile_id:"workflow",remote_display_name:"测试服务器",workflow_display_name:"基础工作流",compatible_model_profiles:["anima_base_v1","anima_turbo_v1_1"],availability:"ready"};
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear(); sessionStorage.setItem("anima-v3-session","test");
  const requirements=emptyRequirements(); requirements.layers.subject.text="蓝外套人物";
  workspace={id:"studio",title:"创作流程",revision:3,created_at:"2026-09-21",updated_at:"2026-09-21",draft:{positive_text:"",excluded_text:"",model_profile:"anima_base_v1",mode:"faithful",requirements:{...requirements,contract:"anima-requirements/1",revision:1},generation_settings:{...defaultGenerationSettings(),remote_profile_id:"cloud",workflow_profile_id:"workflow"},compiled:{positive:"woman, blue coat",negative:"blurry",source:"llm",compiled_token:"cmp3"},compile_state:"fresh",conversation_events:[]}};
  localStorage.setItem("anima-conversation-active",JSON.stringify(workspace.id)); writes=[]; failTurn=false; failGenerate=false;
  vi.spyOn(globalThis,"fetch").mockImplementation(async(input,init)=>{
    const url=String(input),body=init?.body?JSON.parse(String(init.body)):null;
    if(body) writes.push({url,body,key:new Headers(init?.headers).get("Idempotency-Key")});
    let response:unknown={items:[]};
    if(url.endsWith("/llm/settings")) response={current:{service:"test",model:"small",workbench_enable_thinking:false,thinking:{mode:"switchable",message:""}},services:[]};
    else if(url.includes("/workspaces?")) response={items:[workspace]};
    else if(url.endsWith("/generation-targets")) response={items:[target]};
    else if(url.includes("/availability")) response={availability:"ready"};
    else if(url.endsWith("/proposal")) response={proposal:null};
    else if(url.includes("/versions?")) response={items:[workspace]};
    else if(url.endsWith("/workbench/turns")) {
      if(failTurn)return new Response(JSON.stringify({error:{code:"llm_generation_failed",message:"更新失败"}}),{status:502});
      const next={...workspace,revision:workspace.revision+1,draft:{...workspace.draft,compiled:{...workspace.draft.compiled!,positive:"woman, red coat",compiled_token:"cmp-updated"},conversation_events:[{id:"event",delta:body.delta.text,changed_layers:[],warnings:[],created_at:"2026-09-21"}]}};
      if(body.preview) response={id:"proposal",workspace_id:"studio",base_revision:workspace.revision,draft:next.draft,changed_layers:[],warnings:[],created_at:"2026-09-21"};
      else {workspace=next;response=workspace;}
    } else if(url.endsWith("/direct-prompt/runs")) {
      if(failGenerate) throw new TypeError("lost response");
      workspace={...workspace,revision:workspace.revision+1,draft:{...workspace.draft,compiled:{...workspace.draft.compiled!,positive:body.positive_prompt,negative:body.negative_prompt,compiled_token:"cmp-generated"},compile_state:"fresh"}};
      response={id:"run-new",state:"draft",artifact_count:0,status_message:"已接受",workspace_revision:workspace.revision,compiled_token:"cmp-generated"};
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
  await waitFor(()=>expect(writes.some(x=>x.url.endsWith("/direct-prompt/runs"))).toBe(true));
  expect(writes.find(x=>x.url.endsWith("/direct-prompt/runs"))?.body).toMatchObject({positive_prompt:"woman, green coat",model_profile:"anima_turbo_v1_1",use_current_prompt:true});
  expect(writes.some(x=>x.url.endsWith("/turns"))).toBe(false);
  await waitFor(()=>expect(delta()).toHaveValue("尚未应用的月夜意见"));
});
it("combined update submits the updated prompt once",async()=>{
  await mount();fireEvent.change(delta(),{target:{value:"外套换红色"}});fireEvent.click(screen.getByRole("button",{name:"更新并生图"}));
  await waitFor(()=>expect(writes.some(x=>x.url.endsWith("/direct-prompt/runs"))).toBe(true));
  expect(writes.filter(x=>x.url.endsWith("/turns"))).toHaveLength(1);
  expect(writes.filter(x=>x.url.endsWith("/direct-prompt/runs"))).toHaveLength(1);
  expect(writes.find(x=>x.url.endsWith("/direct-prompt/runs"))?.body.positive_prompt).toBe("woman, red coat");
});
it("does not generate if the combined update fails",async()=>{
  failTurn=true;await mount();fireEvent.change(delta(),{target:{value:"外套换红色"}});fireEvent.click(screen.getByRole("button",{name:"更新并生图"}));
  await screen.findByText(/更新失败/);expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, blue coat");expect(delta()).toHaveValue("外套换红色");expect(writes.some(x=>x.url.endsWith("/direct-prompt/runs"))).toBe(false);
});
it("reuses a frozen submission after an unknown acceptance result",async()=>{
  failGenerate=true;await mount();fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await screen.findByRole("button",{name:"查询本次提交"});failGenerate=false;
  fireEvent.click(screen.getByRole("button",{name:"查询本次提交"}));
  await waitFor(()=>expect(writes.filter(x=>x.url.endsWith("/direct-prompt/runs"))).toHaveLength(2));
  const calls=writes.filter(x=>x.url.endsWith("/direct-prompt/runs"));expect(calls[1].key).toBe(calls[0].key);expect(calls[1].body).toEqual(calls[0].body);
});
it("leaves settings editable after a known missing resource rejection",async()=>{
  const original=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,init)=>String(input).endsWith("/direct-prompt/runs")?new Response(JSON.stringify({error:{code:"lora_not_installed",message:"缺少指定 LoRA"}}),{status:409}):original(input,init));
  await mount();fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await screen.findByText("缺少指定 LoRA");expect(screen.queryByRole("button",{name:"查询本次提交"})).not.toBeInTheDocument();expect(screen.getByLabelText("模型")).toBeEnabled();
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
  await screen.findByText(/其他窗口已保存了更新/);expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, blue coat");expect(writes.some(x=>x.url.endsWith("/direct-prompt/runs"))).toBe(false);
});
it("keeps an accepted generation as the merge base when a later server edit appears",async()=>{
  const original=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    const response=await original(input,init);
    if(String(input).endsWith("/direct-prompt/runs")) workspace={...workspace,revision:workspace.revision+1,draft:{...workspace.draft,compiled:{...workspace.draft.compiled!,positive:"another window saved this"}}};
    return response;
  });
  await mount();fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await screen.findByText(/其他窗口已保存了更新/);expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, blue coat");expect(screen.getByRole("button",{name:"生成图片"})).toBeDisabled();
});
function withOldImage(){
  const original=vi.mocked(fetch).getMockImplementation()!;
  const version=structuredClone(workspace);version.revision=2;version.draft.compiled!.positive="woman, red coat";
  const run={id:"old-image",state:"completed",artifact_count:0,created_at:"2026-09-20",status_message:"完成",remote_profile_id:"cloud",workflow_profile_id:"workflow",source:{workspace_revision:2,positive_prompt:"woman, red coat",negative_prompt:"blurry",model_profile:"anima_base_v1",settings:{...defaultGenerationSettings(),seed:42}}};
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    const url=String(input);
    if(url.includes("/workspaces/studio/runs?"))return new Response(JSON.stringify({items:[run]}));
    if(url.includes("/versions?"))return new Response(JSON.stringify({items:[workspace,version]}));
    return original(input,init);
  });
}
it("restores an old image in place and can undo back to the displaced draft",async()=>{
  withOldImage();await mount();fireEvent.change(screen.getByLabelText("模型"),{target:{value:"anima_turbo_v1_1"}});
  fireEvent.change(screen.getByLabelText("正向提示词"),{target:{value:"my unsaved prompt"}});fireEvent.change(delta(),{target:{value:"还没提交的意见"}});
  fireEvent.click(await screen.findByRole("button",{name:"从这张继续"}));
  await waitFor(()=>expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, red coat"));expect(screen.getByLabelText("模型")).toHaveValue("anima_base_v1");expect(delta()).toHaveValue("");
  fireEvent.click(screen.getByRole("button",{name:"撤销"}));expect(screen.getByLabelText("正向提示词")).toHaveValue("my unsaved prompt");expect(screen.getByLabelText("模型")).toHaveValue("anima_turbo_v1_1");expect(delta()).toHaveValue("还没提交的意见");expect(writes).toHaveLength(0);
});
it("only using image text keeps current resources and explicitly clears obsolete prompt locks",async()=>{
  workspace.draft.requirements!.prompt_locks=[{target:"positive",text:"blue coat"}];
  workspace.draft.requirements!.loras=[{logical_id:"my-lora",file_name:"mine.safetensors",weight:1,trigger_words:[],required:true,source:{kind:"user"}}];
  withOldImage();await mount();fireEvent.change(screen.getByLabelText("模型"),{target:{value:"anima_turbo_v1_1"}});
  fireEvent.click(await screen.findByRole("button",{name:"只用提示词"}));
  expect(screen.getByLabelText("模型")).toHaveValue("anima_turbo_v1_1");fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await waitFor(()=>expect(writes.some(x=>x.url.endsWith("/direct-prompt/runs"))).toBe(true));
  const saved=writes.find(x=>x.url.endsWith("/workspaces/studio"))!.body.draft;
  expect(saved.requirements_edit.prompt_locks).toEqual([]);expect(saved.requirements_edit.loras[0].logical_id).toBe("my-lora");expect(saved.model_profile).toBe("anima_turbo_v1_1");
});

it("unlocks settings after a lost submission is queried and definitively rejected for a missing LoRA", async () => {
  failGenerate = true;
  const original = vi.mocked(fetch).getMockImplementation()!;
  const submitted: {key: string | null; body: string}[] = [];
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith("/direct-prompt/runs")) {
      submitted.push({key: new Headers(init?.headers).get("Idempotency-Key"), body: String(init?.body)});
      if (submitted.length === 2) return new Response(JSON.stringify({error: {code: "lora_not_installed", message: "指定 LoRA 尚未安装"}}), {status: 409});
    }
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
  expect(screen.queryByRole("button", {name: "查询本次提交"})).not.toBeInTheDocument();
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
  expect(writes.some(item => item.url.endsWith("/turns") || item.url.endsWith("/direct-prompt/runs"))).toBe(false);
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
  expect(writes.filter(item => item.url.endsWith("/direct-prompt/runs"))).toHaveLength(1);
});
