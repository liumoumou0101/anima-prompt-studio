import {act,cleanup, fireEvent, render, screen, waitFor, within} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {ConversationWorkbenchPage} from "./ConversationWorkbenchPage";
import {editableRequirements, emptyRequirements} from "../lib/conversation";
import type {ConversationRecord} from "../lib/conversation";
import {defaultGenerationSettings} from "../lib/generationSettings";
import {conversationDraftKey, getConversationTabId, readConversationDraft} from "../lib/conversationDrafts";
import * as editorHistoryStorage from "../lib/editorHistoryStore";
import type {EditorBundle} from "../lib/editorHistoryStore";

vi.mock("../components/ArtistRecommendations", () => ({ArtistRecommendations: () => null}));
vi.mock("../components/ManualIdentityTags", () => ({ManualIdentityTags: () => null}));
vi.mock("../components/SceneDesignControls", () => ({SceneDesignControls: () => null}));
let workspace: ConversationRecord;
let proposal: Record<string, unknown> | null;
let history: ConversationRecord[];
let calls: {url: string; body: any; method: string}[];
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear(); sessionStorage.setItem("anima-v3-session", "test");
  const requirements = emptyRequirements(); requirements.layers.subject.text = "蓝色外套";
  workspace = {id: "workspace_ux", title: "颜色测试", revision: 3, created_at: "2026-09-18", updated_at: "2026-09-18",
    draft: {positive_text: "", excluded_text: "", model_profile: "anima_base_v1", mode: "faithful",
      requirements: {...requirements, contract: "anima-requirements/1", revision: 1},
      generation_settings: defaultGenerationSettings(), compiled: {positive: "woman, blue coat", negative: "", source: "llm", compiled_token: "cmp_3"},
      compile_state: "fresh", conversation_events: []}};
  localStorage.setItem("anima-conversation-active", JSON.stringify(workspace.id));
  history = [structuredClone(workspace)]; proposal = null; calls = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input), method = init?.method || "GET", body = init?.body ? JSON.parse(String(init.body)) : null;
    if (method !== "GET"&&!url.includes("/checkpoints")) calls.push({url, body, method});
    let response: unknown = {items: []};
    if (url.endsWith("/llm/settings")) response = {current: {service: "test", model: "small", workbench_enable_thinking: false,
      thinking: {mode: "switchable", message: ""}}, services: []};
    else if (url.includes("/workspaces?")) response = {items: [workspace]};
    else if (url.includes("/versions?")) response = {items: history};
    else if (url.endsWith("/proposal")) response = {proposal};
    else if(url.endsWith("/editor-context")&&method==="POST")response={token:"context-ux"};
    else if(url.endsWith("/editor-restore")&&method==="POST"){
      workspace={...workspace,revision:workspace.revision+1,draft:{...workspace.draft,model_profile:body.draft.model_profile,mode:body.draft.mode,generation_settings:body.draft.generation_settings,requirements:{...body.draft.requirements_edit,contract:"anima-requirements/1",revision:2},compiled:{...workspace.draft.compiled!,...body.draft.prompt_edit}}};
      history.unshift(structuredClone(workspace));response=workspace;
    }
    else if (url.endsWith("/workbench/turns")) {
      const candidate = structuredClone(workspace.draft);
      candidate.compiled!.positive = "woman, red coat";
      candidate.requirements!.layers.subject.text = "红色外套";
      candidate.conversation_events = [...candidate.conversation_events, {id: "event", delta: body.delta.text,
        before_revision: workspace.revision, after_revision: workspace.revision + 1, changed_layers: ["subject"], warnings: [], created_at: "2026-09-18"}];
      if (body.task === "sync_requirements") {candidate.compiled!.requirements_synced = true; candidate.compiled!.positive = body.compiled.positive;}
      proposal = {id: "proposal_ux", workspace_id: workspace.id, base_revision: workspace.revision, draft: candidate,
        changed_layers: ["subject"], warnings: ["只调整服装颜色"], created_at: "2026-09-18"};
      if (body.preview) response = proposal;
      else {workspace = {...workspace, revision: workspace.revision + 1, draft: candidate}; history.unshift(structuredClone(workspace)); proposal = null; response = workspace;}
    } else if (url.endsWith("/proposals/proposal_ux/accept")) {
      workspace = {...workspace, revision: workspace.revision + 1, draft: proposal!.draft as ConversationRecord["draft"]};
      history.unshift(structuredClone(workspace)); proposal = null; response = workspace;
    } else if (url.endsWith("/proposals/proposal_ux") && method === "DELETE") {proposal = null; response = {ok: true};}
    else if (url.endsWith("/restore")) {
      const snapshot = history.find(item => item.revision === body.source_revision)!;
      workspace = {...structuredClone(snapshot), revision: workspace.revision + 1}; history.unshift(structuredClone(workspace)); response = workspace;
    } else if (url.endsWith(`/workspaces/${workspace.id}`)) {
      if (method === "PUT") {
        workspace = {...workspace, revision: workspace.revision + 1, draft: {...workspace.draft,
          generation_settings: body.draft.generation_settings, requirements: {...body.draft.requirements_edit, contract: "anima-requirements/1", revision: 2},
          ...(body.draft.prompt_edit ? {compiled: {...workspace.draft.compiled!, ...body.draft.prompt_edit, source: "user" as const}} : {})}};
        history.unshift(structuredClone(workspace));
      }
      response = workspace;
    }
    return new Response(JSON.stringify(response), {status: 200});
  });
});
afterEach(() => {cleanup(); vi.restoreAllMocks();});
function openSection(name: string | RegExp) {
  if(name==="分层画面要求与锁定")fireEvent.click(screen.getByRole("button",{name:"分层要求"}));
  const summary = screen.queryByText(name, {selector: "summary"});
  if(!summary){if(name==="更多创作工具")return;throw new Error(`Missing section: ${name}`);}
  if (!(summary.parentElement as HTMLDetailsElement).open) fireEvent.click(summary);
}
async function openRecovery() {
  if (!screen.queryByRole("button", {name: "找回本地草稿"})) fireEvent.click(screen.getByRole("button", {name: "创作记录"}));
  fireEvent.click(await screen.findByRole("button", {name: "找回本地草稿"}));
}
function legacyProposal() {
  const candidate = structuredClone(workspace.draft); candidate.compiled!.positive = "woman, red coat";
  return {id: "proposal_ux", workspace_id: workspace.id, base_revision: workspace.revision, draft: candidate,
    changed_layers: ["subject"], warnings: [], created_at: "2026-09-18"};
}
async function mount() {
  render(<MemoryRouter><ConversationWorkbenchPage /></MemoryRouter>);
  await screen.findByLabelText("正向提示词");
  await screen.findByText("small", {selector: ".conversation-thinking-model"});
  openSection("更多创作工具");
  openSection("分层画面要求与锁定");
  openSection(/^改词模型/);
}
it("previews another local draft before restoring it and keeps the displaced edits recoverable", async () => {
  await mount();
  fireEvent.change(screen.getByLabelText("正向提示词"), {target: {value: "woman, yellow coat"}});
  const savedBase = {baseRevision: 3, delta: "", requirements: editableRequirements(workspace), mode: "faithful",
    positive: "woman, blue coat", negative: "", model: workspace.draft.model_profile, settings: defaultGenerationSettings()};
  localStorage.setItem(conversationDraftKey(workspace.id, "closed-window"), JSON.stringify({version: 1,
    workspaceId: workspace.id, tabId: "closed-window", savedAt: Date.now() - 3600000,
    local: {...savedBase, positive: "woman, green coat", delta: "保留花束"}, base: savedBase}));
  await openRecovery();
  const recovery = await screen.findByRole("region", {name: "本地草稿恢复"});
  fireEvent.change(within(recovery).getByLabelText("选择本地草稿"), {target: {value: conversationDraftKey(workspace.id, "closed-window")}});
  expect(within(recovery).getByText("woman, green coat")).toBeVisible();
  expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, yellow coat");
  fireEvent.click(within(recovery).getByRole("button", {name: "恢复到编辑区"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, green coat");
  expect(screen.getByLabelText("这次想怎么改？")).toHaveValue("保留花束");
  expect(workspace.revision).toBe(3);
  expect(calls).toEqual([]);
  await openRecovery();
  const nextRecovery = await screen.findByRole("region", {name: "本地草稿恢复"});
  const select = within(nextRecovery).getByLabelText("选择本地草稿") as HTMLSelectElement;
  const preserved = [...select.options].find(option => option.textContent?.includes("yellow coat"));
  expect(preserved).toBeDefined();
  fireEvent.change(select, {target: {value: preserved!.value}});
  fireEvent.click(within(nextRecovery).getByRole("button", {name: "恢复到编辑区"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, yellow coat");
});

it("keeps the current editor when preserving it before draft recovery fails", async () => {
  await mount();
  const draft = readConversationDraft(workspace.id)!;
  localStorage.setItem(conversationDraftKey(workspace.id, "older-window"), JSON.stringify({version: 1,
    workspaceId: workspace.id, tabId: "older-window", savedAt: Date.now() - 3600000,
    local: {...draft.local, positive: "woman, green coat"}, base: draft.base}));
  await openRecovery();
  const recovery = await screen.findByRole("region", {name: "本地草稿恢复"});
  fireEvent.change(within(recovery).getByLabelText("选择本地草稿"), {target: {value: conversationDraftKey(workspace.id, "older-window")}});
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {throw new DOMException("quota", "QuotaExceededError");});
  fireEvent.click(within(recovery).getByRole("button", {name: "恢复到编辑区"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, blue coat");
  expect(calls).toEqual([]);
  expect(await screen.findByText(/无法.*保留|无法.*备份|无法.*保存/)).toBeVisible();
});

it("requires conflict resolution when a recovered draft was based on an older server version", async () => {
  await mount();
  const draft = readConversationDraft(workspace.id)!;
  localStorage.setItem(conversationDraftKey(workspace.id, "older-revision"), JSON.stringify({version: 1,
    workspaceId: workspace.id, tabId: "older-revision", savedAt: Date.now() - 3600000,
    local: {...draft.local, baseRevision: 2, positive: "woman, green coat"}, base: null}));
  await openRecovery();
  const recovery = await screen.findByRole("region", {name: "本地草稿恢复"});
  fireEvent.change(within(recovery).getByLabelText("选择本地草稿"), {target: {value: conversationDraftKey(workspace.id, "older-revision")}});
  fireEvent.click(within(recovery).getByRole("button", {name: "恢复到编辑区"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, green coat");
  expect(screen.getByRole("button", {name: "保存当前版本"})).toBeDisabled();
  expect(screen.getByRole("button", {name: "将本窗口草稿另存为新会话"})).toBeVisible();
  expect(calls).toEqual([]);
});

it("does not overwrite an unreadable local draft during opening and permits explicit recovery later", async () => {
  await mount();
  fireEvent.change(screen.getByLabelText("正向提示词"), {target: {value: "woman, turquoise coat"}});
  const key = conversationDraftKey(workspace.id, getConversationTabId());
  const originalDraft = localStorage.getItem(key);
  cleanup();
  const originalGet = Storage.prototype.getItem;
  let failed = false;
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(function (this: Storage, requestedKey) {
    if (this === localStorage && requestedKey === key && !failed) {failed = true; throw new DOMException("temporarily blocked", "SecurityError");}
    return originalGet.call(this, requestedKey);
  });
  await mount();
  expect(failed).toBe(true);
  expect(localStorage.getItem(key)).toBe(originalDraft);
  expect(screen.getByText(/原草稿未被覆盖/)).toBeVisible();
  await openRecovery();
  const recovery = await screen.findByRole("region", {name: "本地草稿恢复"});
  fireEvent.change(within(recovery).getByLabelText("选择本地草稿"), {target: {value: key}});
  fireEvent.click(within(recovery).getByRole("button", {name: "恢复到编辑区"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, turquoise coat");
  expect(calls).toEqual([]);
});
it("saves manually edited prompt independently of GPU availability", async () => {
  await mount();
  fireEvent.change(screen.getByLabelText("正向提示词"), {target: {value: "woman, red coat"}});
  fireEvent.click(screen.getByRole("button", {name: "保存当前版本"}));
  await waitFor(() => expect(workspace.draft.compiled?.positive).toBe("woman, red coat"));
  expect(calls[0].body.draft.prompt_edit).toEqual({positive: "woman, red coat", negative: ""});
  expect(calls.some(call => call.url.includes("/runs"))).toBe(false);
});
it.each(["woman, scarlet coat", "  woman, scarlet coat\n"])("previews Chinese requirement sync without rewriting the manual prompt %j", async positive => {
  await mount();
  fireEvent.change(screen.getByLabelText("正向提示词"), {target: {value: positive}});
  fireEvent.click(screen.getByRole("button", {name: "按手工提示词同步画面要求"}));
  const review = await screen.findByRole("region", {name: "待确认的修改"});
  const request = calls.find(call => call.url.endsWith("/turns"))!;
  expect(request.body).toMatchObject({task: "sync_requirements", preview: true, delta: {text: ""}, compiled: {positive, negative: ""}});
  expect(workspace.draft.requirements!.layers.subject.text).toBe("蓝色外套");
  expect(screen.getByLabelText("正向提示词")).toHaveValue(positive);
  expect(within(review).getByRole("button", {name: "采用修改"})).toBeEnabled();
  fireEvent.click(within(review).getByRole("button", {name: "采用修改"}));
  await waitFor(() => expect(workspace.draft.compiled!.requirements_synced).toBe(true));
  expect(screen.queryByRole("button", {name: "按手工提示词同步画面要求"})).not.toBeInTheDocument();
  expect(screen.getByLabelText("正向提示词")).toHaveValue(positive);
});
it("does not discard unsent requests when syncing manual prompts", async () => {
  await mount();
  fireEvent.change(screen.getByLabelText("正向提示词"), {target: {value: "woman, scarlet coat"}});
  fireEvent.change(screen.getByLabelText("这次想怎么改？"), {target: {value: "还有要补充的要求"}});
  expect(screen.getByRole("button", {name: "按手工提示词同步画面要求"})).toBeDisabled();
});
it("applies updates directly while retaining highlighted changes and an undo action", async () => {
  await mount();
  fireEvent.change(screen.getByLabelText("这次想怎么改？"), {target: {value: "只改红色"}});
  fireEvent.click(screen.getByRole("button", {name: "更新提示词"}));
  await waitFor(() => expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, red coat"));
  openSection("查看本次文字变化");
  expect(document.querySelector(".conversation-diff ins")).toHaveTextContent("red");
  expect(document.querySelector(".conversation-diff del")).toHaveTextContent("blue");
  expect(screen.queryByRole("region", {name: "待确认的修改"})).not.toBeInTheDocument();
  expect(workspace.revision).toBe(4);
  expect(calls.find(call => call.url.endsWith("/turns"))!.body.preview).toBe(false);
  fireEvent.click(screen.getByRole("button", {name: "撤销"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, blue coat");
});
it("discards a recovered legacy candidate while retaining original prompt and modification request", async () => {
  proposal = legacyProposal();
  await mount();
  fireEvent.change(screen.getByLabelText("这次想怎么改？"), {target: {value: "只改红色"}});
  openSection("上次未处理的提示词草案");
  fireEvent.click(await screen.findByRole("button", {name: "不采用"}));
  await waitFor(() => expect(screen.queryByRole("region", {name: "待确认的修改"})).not.toBeInTheDocument());
  expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, blue coat");
  expect(screen.getByLabelText("这次想怎么改？")).toHaveValue("只改红色");
  expect(workspace.revision).toBe(3);
});
it("restores an earlier saved version into the editor without deleting later history", async () => {
  const older = structuredClone(workspace); older.revision = 2; older.draft.compiled!.positive = "woman, green coat";
  history.push(older);
  await mount();
  fireEvent.click(screen.getByRole("button", {name: "创作记录"}));
  const card = (await screen.findByText("woman, green coat")).closest("article")!;
  const restore = within(card).getByRole("button", {name: "用此版本继续编辑"});
  fireEvent.click(restore);
  await waitFor(() => expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, green coat"));
  await waitFor(()=>expect(workspace.revision).toBe(4));
  expect(history.map(item => item.revision)).toEqual([4,3, 2]);
  fireEvent.click(screen.getByRole("button", {name: "撤销"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, blue coat");
});
it("forks a historical version with an idempotent request and exposes its parent", async () => {
  const older = structuredClone(workspace); older.revision = 2; older.draft.compiled!.positive = "woman, green coat"; history.push(older);
  const original = vi.mocked(fetch).getMockImplementation()!;
  let forkKey = "";
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith("/versions/2/fork")) {
      forkKey = new Headers(init?.headers).get("Idempotency-Key") || "";
      return new Response(JSON.stringify({...structuredClone(older), id:"workspace_branch", title:"历史分支", revision:1,
        draft:{...older.draft, workspace_origin:{workspace_id:workspace.id, revision:2, run_id:null}}}));
    }
    return original(input, init);
  });
  await mount();
  fireEvent.click(screen.getByRole("button", {name: "创作记录"}));
  for (const summary of await screen.findAllByText("更多操作", {selector: "summary"})) fireEvent.click(summary);
  fireEvent.click(await screen.findByRole("button", {name:"从版本 2 另开会话"}));
  await screen.findByRole("heading", {name:"历史分支", level:1});
  expect(forkKey).not.toBe("");
  expect(workspace.revision).toBe(3);
  expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, green coat");
  fireEvent.click(screen.getByRole("button",{name:"分层要求"}));
  expect(screen.getByRole("button", {name:"打开来源会话"})).toBeEnabled();
  expect(screen.getByLabelText("打开已有会话")).toHaveValue("workspace_branch");
});
it("retries failed requirement sync with the same task instead of rewriting English", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  let attempts = 0;
  const tasks: unknown[] = [];
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith("/workbench/turns")) {
      tasks.push(JSON.parse(String(init!.body)).task);
      if (++attempts === 1) return new Response(JSON.stringify({error:{code:"llm_upstream_error", message:"模型暂时失败"}}), {status:502});
    }
    return original(input, init);
  });
  await mount();
  fireEvent.change(screen.getByLabelText("正向提示词"), {target:{value:"woman, scarlet coat"}});
  fireEvent.click(screen.getByRole("button", {name:"按手工提示词同步画面要求"}));
  fireEvent.click(await screen.findByRole("button", {name:"重试整理"}));
  await screen.findByRole("region", {name:"待确认的修改"});
  expect(tasks).toEqual(["sync_requirements", "sync_requirements"]);
});
it("recovers an applied server update when its response is lost without submitting another request", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const response = await original(input, init);
    if (String(input).endsWith("/workbench/turns")) throw new TypeError("lost response");
    return response;
  });
  await mount();
  fireEvent.change(screen.getByLabelText("这次想怎么改？"), {target: {value: "改红色"}});
  fireEvent.click(screen.getByRole("button", {name: "更新提示词"}));
  await waitFor(() => expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, red coat"));
  expect(screen.queryByRole("region", {name: "待确认的修改"})).not.toBeInTheDocument();
  expect(workspace.revision).toBe(4);
  expect(calls.filter(call => call.url.endsWith("/turns"))).toHaveLength(1);
});
it("merges edits to different fields after a revision conflict", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  let conflictOnce = true;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith("/workspaces/workspace_ux") && init?.method === "PUT" && conflictOnce) {
      conflictOnce = false; workspace.revision = 4; workspace.draft.requirements!.layers.lighting.text = "清晨";
      return new Response(JSON.stringify({error: {code: "workspace_revision_conflict", message: "已有更新"}}), {status: 409});
    }
    return original(input, init);
  });
  await mount(); openSection("分层画面要求与锁定");
  fireEvent.change(screen.getByLabelText("构图要求"), {target: {value: "居中"}});
  fireEvent.click(screen.getByRole("button", {name: "保存当前版本"}));
  fireEvent.click(await screen.findByRole("button", {name: "合并双方修改"}));
  expect(screen.getByLabelText("光影要求")).toHaveValue("清晨");
  expect(screen.getByLabelText("构图要求")).toHaveValue("居中");
  expect(screen.getByRole("button", {name: "撤销"})).toBeDisabled();
  fireEvent.change(screen.getByLabelText("构图要求"), {target: {value: "靠左"}});
  fireEvent.click(screen.getByRole("button", {name: "撤销"}));
  expect(screen.getByLabelText("光影要求")).toHaveValue("清晨");
  expect(screen.getByLabelText("构图要求")).toHaveValue("居中");
  fireEvent.click(screen.getByRole("button", {name: "保存当前版本"}));
  await waitFor(() => expect(workspace.revision).toBe(5));
  expect(workspace.draft.requirements!.layers.lighting.text).toBe("清晨");
  expect(workspace.draft.requirements!.layers.composition.text).toBe("居中");
});
it("recovers a pending candidate after reopening without replacing current prompt", async () => {
  proposal = legacyProposal();
  await mount();
  openSection("上次未处理的提示词草案");
  await screen.findByRole("region", {name: "待确认的修改"});
  cleanup(); await mount();
  openSection("上次未处理的提示词草案");
  await screen.findByRole("region", {name: "待确认的修改"});
  expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, blue coat");
  fireEvent.click(screen.getByRole("button", {name: "采用修改"}));
  await waitFor(() => expect(workspace.revision).toBe(4));
});
it("can undo and redo a manual prompt edit before saving", async () => {
  await mount();
  fireEvent.change(screen.getByLabelText("正向提示词"), {target: {value: "woman, white coat"}});
  fireEvent.click(screen.getByRole("button", {name: "撤销"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, blue coat");
  fireEvent.click(screen.getByRole("button", {name: "重做"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, white coat");
  expect(calls).toHaveLength(0);
});

it("recovers the persisted undo and redo cursor in a new document",async()=>{
 await mount();fireEvent.change(screen.getByLabelText("正向提示词"),{target:{value:"woman, white coat"}});
 cleanup();await mount();expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, white coat");
 fireEvent.click(screen.getByRole("button",{name:"撤销"}));expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, blue coat");
 cleanup();await mount();expect(screen.getByRole("button",{name:"重做"})).toBeEnabled();
 fireEvent.click(screen.getByRole("button",{name:"重做"}));expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, white coat");
});

it("preserves own-save undo but archives the shortcut chain when a remote baseline advances",async()=>{
 await mount();fireEvent.change(screen.getByLabelText("正向提示词"),{target:{value:"woman, white coat"}});
 fireEvent.click(screen.getByRole("button",{name:"保存当前版本"}));await waitFor(()=>expect(workspace.revision).toBe(4));
 expect(screen.getByRole("button",{name:"撤销"})).toBeEnabled();cleanup();
 workspace={...workspace,revision:5,draft:{...workspace.draft,compiled:{...workspace.draft.compiled!,positive:"remote green coat"}}};history.unshift(structuredClone(workspace));
 await mount();expect(screen.getByLabelText("正向提示词")).toHaveValue("remote green coat");expect(screen.getByRole("button",{name:"撤销"})).toBeDisabled();expect(screen.getByRole("button",{name:"重做"})).toBeDisabled();
 const recovered=readConversationDraft(workspace.id)!;expect(recovered.editorJournal?.archived.some(operation=>operation.snapshot.positive==="woman, white coat")).toBe(true);expect(recovered.editorJournal?.cursor).toBe(0);
});

it("continuing an old content version keeps current parameters and clears newer semantic requirements",async()=>{
 workspace.draft.generation_settings={...defaultGenerationSettings(),steps:22,cfg:3.2};
 workspace.draft.requirements!.layers.subject.text="newer requirement";
 const older=structuredClone(workspace);older.revision=2;older.draft.compiled!.positive="old content";older.draft.requirements!.layers.subject.text="old requirement";older.draft.generation_settings={...defaultGenerationSettings(),steps:35,cfg:4.5};history.push(older);
 await mount();fireEvent.click(screen.getByRole("button",{name:"创作记录"}));const card=(await screen.findByText("old content")).closest("article")!;
 fireEvent.click(within(card).getByRole("button",{name:"用此版本继续编辑"}));
 await waitFor(()=>expect(workspace.revision).toBe(4));expect(workspace.draft.generation_settings?.steps).toBe(22);expect(workspace.draft.generation_settings?.cfg).toBe(3.2);expect(workspace.draft.requirements?.layers.subject.text).toBe("old requirement");
});

it("a delayed restore acknowledgement cannot overwrite a newer undo",async()=>{
 const older=structuredClone(workspace);older.revision=2;older.draft.compiled!.positive="old content";history.push(older);
 const original=vi.mocked(fetch).getMockImplementation()!;let finish!:(response:Response)=>void;
 vi.mocked(fetch).mockImplementation(async(input,init)=>String(input).endsWith("/editor-restore")?new Promise(resolve=>{finish=resolve;}):original(input,init));
 await mount();fireEvent.click(screen.getByRole("button",{name:"创作记录"}));const card=(await screen.findByText("old content")).closest("article")!;
 fireEvent.click(within(card).getByRole("button",{name:"用此版本继续编辑"}));fireEvent.click(screen.getByRole("button",{name:"撤销"}));
 const restored={...workspace,revision:4,draft:{...older.draft,generation_settings:workspace.draft.generation_settings}};
 await act(async()=>finish(new Response(JSON.stringify(restored))));
 expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, blue coat");
});

it("recovers a newer IndexedDB draft after localStorage quota failure before adopting server text",async()=>{
 const bundles=new Map<string,EditorBundle>();let timestamp=1700000000000;vi.spyOn(Date,"now").mockImplementation(()=>++timestamp);
 vi.stubGlobal("indexedDB",{});
 vi.spyOn(editorHistoryStorage,"saveEditorBundle").mockImplementation(async bundle=>{bundles.set(`${bundle.workspaceId}:${bundle.documentId}`,structuredClone(bundle));});
 vi.spyOn(editorHistoryStorage,"readLatestEditorBundle").mockImplementation(async(workspaceId,documentIds)=>{
   for(const id of documentIds){const bundle=bundles.get(`${workspaceId}:${id}`);if(bundle)return structuredClone(bundle);}return null;
 });
 try{
   await mount();const previous=readConversationDraft(workspace.id)!;
   const originalSetItem=Storage.prototype.setItem;
   vi.spyOn(Storage.prototype,"setItem").mockImplementation(function(this:Storage,key,value){
     if(this===localStorage&&key.startsWith("anima-conversation-draft:v1:"))throw new DOMException("quota","QuotaExceededError");originalSetItem.call(this,key,value);
   });
   fireEvent.change(screen.getByLabelText("正向提示词"),{target:{value:"newer IndexedDB coat"}});
   fireEvent.change(screen.getByLabelText("这次想怎么改？"),{target:{value:"opinion backed up only in IndexedDB"}});
   const slot=`${workspace.id}:${getConversationTabId()}`;
   await waitFor(()=>expect(bundles.get(slot)?.local.delta).toBe("opinion backed up only in IndexedDB"));
   expect(bundles.get(slot)?.savedAt).toBeGreaterThan(previous.savedAt!);expect(readConversationDraft(workspace.id)?.local?.positive).toBe("woman, blue coat");
   expect(bundles.get(slot)?.journal.entries).toHaveLength(1);cleanup();
   await mount();expect(screen.getByLabelText("正向提示词")).toHaveValue("newer IndexedDB coat");expect(screen.getByLabelText("这次想怎么改？")).toHaveValue("opinion backed up only in IndexedDB");
   expect(bundles.get(slot)?.local.positive).toBe("newer IndexedDB coat");expect(screen.getByRole("button",{name:"撤销"})).toBeEnabled();
   fireEvent.click(screen.getByRole("button",{name:"撤销"}));expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, blue coat");expect(screen.getByLabelText("这次想怎么改？")).toHaveValue("opinion backed up only in IndexedDB");expect(screen.getByRole("button",{name:"重做"})).toBeEnabled();
 }finally{cleanup();vi.unstubAllGlobals();}
});

it("keeps a newer pending restore when an older restore receipt arrives first",async()=>{
 const first=structuredClone(workspace),second=structuredClone(workspace);first.revision=2;first.draft.compiled!.positive="first historical restore";second.revision=1;second.draft.compiled!.positive="second historical restore";history.push(first,second);
 const original=vi.mocked(fetch).getMockImplementation()!;const restores:{body:any;finish:(response:Response)=>void}[]=[];
 vi.mocked(fetch).mockImplementation((input,init)=>String(input).endsWith("/editor-restore")?new Promise(resolve=>{restores.push({body:JSON.parse(String(init?.body)),finish:resolve});}):original(input,init));
 await mount();fireEvent.click(screen.getByRole("button",{name:"创作记录"}));let card=(await screen.findByText("first historical restore")).closest("article")!;fireEvent.click(within(card).getByRole("button",{name:"用此版本继续编辑"}));
 fireEvent.click(screen.getByRole("button",{name:"创作记录"}));card=(await screen.findByText("second historical restore")).closest("article")!;fireEvent.click(within(card).getByRole("button",{name:"用此版本继续编辑"}));
 expect(restores).toHaveLength(2);const newerOperation=restores[1].body.operation_id;expect(newerOperation).not.toBe(restores[0].body.operation_id);
 expect(readConversationDraft(workspace.id)?.editorJournal?.pendingRestore?.operationId).toBe(newerOperation);
 workspace={...workspace,revision:4,draft:{...first.draft}};
 await act(async()=>restores[0].finish(new Response(JSON.stringify(workspace))));
 expect(screen.getByLabelText("正向提示词")).toHaveValue("second historical restore");expect(readConversationDraft(workspace.id)?.editorJournal?.pendingRestore?.operationId).toBe(newerOperation);
 expect(calls.some(call=>call.method==="PUT")).toBe(false);
 await act(async()=>restores[1].finish(new Response(JSON.stringify({error:{code:"workspace_revision_conflict",message:"another restore already saved"}}),{status:409})));
 expect(screen.getByLabelText("正向提示词")).toHaveValue("second historical restore");expect(await screen.findByText("其他窗口已保存了更新，你的编辑仍在这里。")).toBeInTheDocument();
});

it.each(["merge","server"] as const)("finishes a rejected restore after an explicit %s decision and permits saving",async decision=>{
 const older=structuredClone(workspace);older.revision=2;older.draft.compiled!.positive="rejected historical content";history.push(older);
 const original=vi.mocked(fetch).getMockImplementation()!;const restoreRequests:any[]=[];
 vi.mocked(fetch).mockImplementation(async(input,init)=>{
   const url=String(input);if(url.endsWith("/checkpoints")&&init?.method==="POST")throw new TypeError("checkpoint sync offline");
   if(url.endsWith("/editor-restore")){restoreRequests.push(JSON.parse(String(init?.body)));workspace={...workspace,revision:4,draft:{...workspace.draft,requirements:{...workspace.draft.requirements!,layers:{...workspace.draft.requirements!.layers,lighting:{...workspace.draft.requirements!.layers.lighting,text:"remote morning"}}}}};return new Response(JSON.stringify({error:{code:"workspace_revision_conflict",message:"restore rejected"}}),{status:409});}
   return original(input,init);
 });
 await mount();fireEvent.click(screen.getByRole("button",{name:"创作记录"}));const card=(await screen.findByText("rejected historical content")).closest("article")!;fireEvent.click(within(card).getByRole("button",{name:"用此版本继续编辑"}));
 await screen.findByText("其他窗口已保存了更新，你的编辑仍在这里。");const operationId=restoreRequests[0].operation_id;
 fireEvent.click(screen.getByRole("button",{name:decision==="merge"?"合并双方修改":"采用服务端版本"}));
 expect(readConversationDraft(workspace.id)?.editorJournal?.pendingRestore).toBeUndefined();
 const journal=readConversationDraft(workspace.id)?.editorJournal;expect(journal?.archived.some(operation=>operation.id===operationId)).toBe(true);expect(journal?.outbox.some(operation=>operation.id===operationId)).toBe(true);
 if(decision==="server")fireEvent.change(screen.getByLabelText("正向提示词"),{target:{value:"edited after choosing server"}});
 fireEvent.click(screen.getByRole("button",{name:"保存当前版本"}));await waitFor(()=>expect(workspace.revision).toBe(5));
 expect(restoreRequests).toHaveLength(1);expect(workspace.draft.compiled?.positive).toBe(decision==="merge"?"rejected historical content":"edited after choosing server");
});

it("retains an uncertain restore and retries exactly the same operation after a network failure",async()=>{
 const older=structuredClone(workspace);older.revision=2;older.draft.compiled!.positive="uncertain historical content";history.push(older);
 const original=vi.mocked(fetch).getMockImplementation()!;const bodies:string[]=[];
 vi.mocked(fetch).mockImplementation(async(input,init)=>{if(String(input).endsWith("/editor-restore")){bodies.push(String(init?.body));if(bodies.length===1)throw new TypeError("response unavailable");}return original(input,init);});
 await mount();fireEvent.click(screen.getByRole("button",{name:"创作记录"}));const card=(await screen.findByText("uncertain historical content")).closest("article")!;fireEvent.click(within(card).getByRole("button",{name:"用此版本继续编辑"}));
 await screen.findByText(/无法连接本地服务/);expect(readConversationDraft(workspace.id)?.editorJournal?.pendingRestore?.body).toBe(bodies[0]);expect(screen.queryByRole("button",{name:"采用服务端版本"})).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole("button",{name:"保存当前版本"}));await waitFor(()=>expect(workspace.revision).toBe(4));expect(bodies).toHaveLength(2);expect(bodies[1]).toBe(bodies[0]);expect(readConversationDraft(workspace.id)?.editorJournal?.pendingRestore).toBeUndefined();
});

it("keeps an unpersisted modification request in the current conversation", async () => {
  const originalFetch = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => String(input).includes("/runs?limit=")
    ? new Response(JSON.stringify({items: [{id: "run_previous", state: "completed", artifact_count: 0, status_message: "完成", created_at: "2026-09-18"}]}))
    : originalFetch(input, init));
  await mount();
  openSection("更多图片操作");
  await screen.findByRole("button", {name: "沿用本次条件，新建会话"});
  const originalSetItem = Storage.prototype.setItem;
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(function(this: Storage, key, value) {
    if (this === localStorage && key.startsWith("anima-conversation-draft:")) throw new DOMException("full", "QuotaExceededError");
    originalSetItem.call(this, key, value);
  });
  fireEvent.change(screen.getByLabelText("这次想怎么改？"), {target: {value: "这段意见还没有保存"}});
  expect(screen.getByRole("alert")).toHaveTextContent("当前草稿无法保留");
  expect(screen.getByRole("button", {name: "新会话"})).toBeDisabled();
  expect(screen.getByLabelText("打开已有会话")).toBeDisabled();
  expect(screen.getByRole("button", {name: "沿用本次条件，新建会话"})).toBeDisabled();
  expect(screen.getByLabelText("这次想怎么改？")).toHaveValue("这段意见还没有保存");
});

it("opens a linked conversation when persistent storage access is denied", async () => {
  const blocked = vi.spyOn(window, "localStorage", "get").mockImplementation(() => {throw new DOMException("blocked", "SecurityError");});
  try {
    render(<MemoryRouter initialEntries={["/workbench?workspace=workspace_ux"]}><ConversationWorkbenchPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByLabelText("正向提示词")).toBeEnabled());
    expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, blue coat");
    expect(screen.getAllByRole("alert").some(item => item.textContent?.includes("已暂停自动保存"))).toBe(true);
    expect(screen.getByText(/原草稿未被覆盖/)).toBeVisible();
  } finally {blocked.mockRestore();}
});

it("isolates a blocked corrupt draft from another conversation", async () => {
  sessionStorage.setItem("anima-conversation-tab-id", "ux-tab");
  const corruptKey = conversationDraftKey(workspace.id, getConversationTabId());
  localStorage.setItem(corruptKey, "{damaged draft");
  const other = {...structuredClone(workspace), id: "workspace_other", title: "另一会话"};
  const originalFetch = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.includes("/workspaces?")) return new Response(JSON.stringify({items: [workspace, other]}));
    if (url.endsWith("/workspaces/workspace_other")) return new Response(JSON.stringify(other));
    return originalFetch(input, init);
  });
  const originalSetItem = Storage.prototype.setItem;
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(function(this: Storage, key, value) {
    if (key.startsWith("anima-conversation-draft-invalid:")) throw new DOMException("full", "QuotaExceededError");
    originalSetItem.call(this, key, value);
  });
  await mount();
  expect(screen.getByRole("alert")).toHaveTextContent("无法保留副本");
  expect(localStorage.getItem(corruptKey)).toBe("{damaged draft");
  fireEvent.change(screen.getByLabelText("打开已有会话"), {target: {value: other.id}});
  await screen.findByRole("heading", {name: "另一会话", level: 1});
  await waitFor(() => expect(screen.getByLabelText("正向提示词")).toBeEnabled());
  fireEvent.change(screen.getByLabelText("正向提示词"), {target: {value: "other conversation draft"}});
  expect(readConversationDraft(other.id)?.local?.positive).toBe("other conversation draft");
  expect(localStorage.getItem(corruptKey)).toBe("{damaged draft");
  expect(screen.queryByRole("button", {name: "导出原始草稿"})).not.toBeInTheDocument();
});

it("blocks accepting an outdated candidate while keeping it available to discard", async () => {
  const candidate = structuredClone(workspace.draft); candidate.compiled!.positive = "outdated candidate";
  proposal = {id: "proposal_ux", workspace_id: workspace.id, base_revision: 2, draft: candidate,
    changed_layers: [], warnings: [], created_at: "2026-09-18"};
  await mount();
  const review = await screen.findByRole("region", {name: "待确认的修改"});
  expect(within(review).getByRole("button", {name: "采用修改"})).toBeDisabled();
  expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, blue coat");
  fireEvent.click(within(review).getByRole("button", {name: "不采用"}));
  await waitFor(() => expect(screen.queryByRole("region", {name: "待确认的修改"})).not.toBeInTheDocument());
  expect(workspace.revision).toBe(3);
});

it("restores history with an unsent request and recovers that request through undo", async () => {
  const older = structuredClone(workspace); older.revision = 2; older.draft.compiled!.positive = "woman, green coat"; history.push(older);
  await mount();
  fireEvent.change(screen.getByLabelText("这次想怎么改？"), {target: {value: "保留这段未发送意见"}});
  fireEvent.click(screen.getByRole("button", {name: "创作记录"}));
  const card = (await screen.findByText("woman, green coat")).closest("article")!;
  fireEvent.click(within(card).getByRole("button", {name: "用此版本继续编辑"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, green coat");
  fireEvent.click(screen.getByRole("button", {name: "撤销"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, blue coat");
  expect(screen.getByLabelText("这次想怎么改？")).toHaveValue("保留这段未发送意见");
  expect(workspace.revision).toBe(4);
});
