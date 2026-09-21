import {cleanup, fireEvent, render, screen, waitFor, within} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {ConversationWorkbenchPage} from "./ConversationWorkbenchPage";
import {editableRequirements, emptyRequirements} from "../lib/conversation";
import type {ConversationRecord} from "../lib/conversation";
import {defaultGenerationSettings} from "../lib/generationSettings";
import {conversationDraftKey, getConversationTabId, readConversationDraft} from "../lib/conversationDrafts";

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
    if (method !== "GET") calls.push({url, body, method});
    let response: unknown = {items: []};
    if (url.endsWith("/llm/settings")) response = {current: {service: "test", model: "small", workbench_enable_thinking: false,
      thinking: {mode: "switchable", message: ""}}, services: []};
    else if (url.includes("/workspaces?")) response = {items: [workspace]};
    else if (url.includes("/versions?")) response = {items: history};
    else if (url.endsWith("/proposal")) response = {proposal};
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
  const summary = screen.getByText(name, {selector: "summary"});
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
  const restore = within(card).getByRole("button", {name: "恢复到这里"});
  fireEvent.click(restore);
  await waitFor(() => expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, green coat"));
  expect(workspace.revision).toBe(3);
  expect(history.map(item => item.revision)).toEqual([3, 2]);
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
  fireEvent.click(within(card).getByRole("button", {name: "恢复到这里"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, green coat");
  fireEvent.click(screen.getByRole("button", {name: "撤销"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("woman, blue coat");
  expect(screen.getByLabelText("这次想怎么改？")).toHaveValue("保留这段未发送意见");
  expect(workspace.revision).toBe(3);
});
