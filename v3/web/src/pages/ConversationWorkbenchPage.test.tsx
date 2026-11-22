import {act, cleanup, fireEvent, render, screen, waitFor, within} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {ConversationWorkbenchPage} from "./ConversationWorkbenchPage";
import {transferUrl} from "../lib/contentTransfer";
import {editableRequirements, emptyRequirements, hasUncompiledInputs} from "../lib/conversation";
import type {ConversationRecord} from "../lib/conversation";
import {readConversationDraft, recoverConversationPending} from "../lib/conversationDrafts";
import {defaultGenerationSettings} from "../lib/generationSettings";
import {basicWorkflowSchema} from "../lib/workflowParameterSchema";
import {LEGACY_AESTHETIC} from "../lib/modelProfiles";
const isSubmission=(url:string)=>url.endsWith("/direct-prompt/runs")||url.endsWith("/generation-intents");
const sourceOf=(body:Record<string,unknown>)=>(body.source||body) as Record<string,unknown>;

function personalTransfer(positive = " Blue_Sky,\n(Cat:1.2) ", negative = "bad_hands") {
  const id = "personal-test";
  localStorage.setItem("anima-personal-prompt-transfer:" + id, JSON.stringify({version: 1, id, positive, negative}));
  return "/workbench?personal_transfer=" + id;
}
function personalServer() {
  const original = vi.mocked(fetch).getMockImplementation()!;
  let saved: {id: string; workspace_id: string; result_revision: number; state: "applied" | "undone"; can_undo: boolean; undo_revision: number | null} | null = null;
  let before: ConversationRecord["draft"]["compiled"] = null;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input);
    if (!url.includes("/personal-prompt-transfers")) return original(input, init);
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    if (body) writes.push({url, method: init?.method || "GET", body, key: null});
    if (!body && !saved) return new Response(JSON.stringify({error: {code: "personal_prompt_transfer_not_found", message: "未找到回执"}}), {status: 404});
    if (url.endsWith("/undo") && saved) {
      workspace = {...workspace, revision: workspace.revision + 1, draft: {...workspace.draft, compiled: before}};
      saved = {...saved, state: "undone", can_undo: false, undo_revision: workspace.revision};
    } else if (body && !saved) {
      before = workspace.draft.compiled;
      workspace = {...workspace, revision: workspace.revision + 1, draft: {...workspace.draft, compiled: {
        positive: (before?.positive && body.positive ? before.positive + "\n" : before?.positive || "") + body.positive,
        negative: (before?.negative && body.negative ? before.negative + "\n" : before?.negative || "") + body.negative,
        source: "user", compiled_token: "personal-token"}}};
      saved = {id: body.transfer_id, workspace_id: workspace.id, result_revision: workspace.revision, state: "applied", can_undo: true, undo_revision: null};
    }
    return new Response(JSON.stringify({workspace, receipt: saved, replayed: !body}));
  });
}
async function confirmPersonal() {
  await waitFor(() => expect(screen.getByRole("button", {name: "确认追加原文"})).toBeEnabled(), {timeout: 3000});
  fireEvent.click(screen.getByRole("button", {name: "确认追加原文"}));
}
it("retries opening the existing workspace after load failure without creating a replacement", async () => {
  personalServer();
  const original = vi.mocked(fetch).getMockImplementation()!;
  let unavailable = true;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (unavailable && String(input).endsWith("/workspaces/workspace_test")) throw new TypeError("offline");
    return original(input, init);
  });
  render(<MemoryRouter initialEntries={[personalTransfer()]}><ConversationWorkbenchPage /></MemoryRouter>);
  await screen.findByText(/无法连接本地服务/);
  unavailable = false;
  fireEvent.click(screen.getByRole("button", {name: "保存并重新预览"}));
  await screen.findByLabelText("追加后正向提示词");
  expect(screen.getByLabelText("追加前正向提示词")).toHaveValue("cat");
  expect(writes).toHaveLength(0);
});
it("reloads unresolved proposal state before retrying personal preview with a dirty recovered draft", async () => {
  personalServer();
  pendingProposal = {id: "proposal_test", workspace_id: workspace.id, base_revision: 3, draft: workspace.draft,
    changed_layers: [], warnings: [], created_at: "2026-09-29"};
  localStorage.setItem("anima-conversation-draft:workspace_test", JSON.stringify({baseRevision: 3, delta: "keep idea",
    mode: "faithful", requirements: editableRequirements(workspace), positive: "unsaved local cat", negative: "",
    model: "anima_base_v1", settings: workspace.draft.generation_settings}));
  const original = vi.mocked(fetch).getMockImplementation()!;
  let proposalReads = 0;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith("/proposal") && ++proposalReads === 1) throw new TypeError("proposal temporarily unavailable");
    return original(input, init);
  });
  render(<MemoryRouter initialEntries={[personalTransfer()]}><ConversationWorkbenchPage /></MemoryRouter>);
  await screen.findByText(/无法连接本地服务/);
  expect(screen.getByLabelText("正向提示词")).toHaveValue("unsaved local cat");
  fireEvent.click(screen.getByRole("button", {name: "保存并重新预览"}));
  await screen.findByText("请先接受或放弃待处理的提示词草案。");
  expect(proposalReads).toBe(2);
  expect(writes).toHaveLength(0);
  expect(screen.getByLabelText("正向提示词")).toHaveValue("unsaved local cat");
  expect(screen.getByLabelText("这次想怎么改？")).toHaveValue("keep idea");
  expect(screen.getByRole("button", {name: "确认追加原文"})).toBeDisabled();
  expect(localStorage.getItem("anima-personal-prompt-transfer:personal-test")).not.toBeNull();
});
it("does not consume a transfer for a malformed success without a durable receipt", async () => {
  personalServer();
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => String(input).endsWith("/personal-prompt-transfers") && init?.method === "POST"
    ? new Response(JSON.stringify({workspace, replayed: false})) : original(input, init));
  render(<MemoryRouter initialEntries={[personalTransfer()]}><ConversationWorkbenchPage /></MemoryRouter>);
  await confirmPersonal();
  await screen.findByText("追加回执未确认，请重试查询。");
  expect(localStorage.getItem("anima-personal-prompt-transfer:personal-test")).not.toBeNull();
  expect(screen.getByLabelText("正向提示词")).toHaveValue("cat");
});
it("recovers a lost personal append response without overwriting later server changes", async () => {
  personalServer(); const url = personalTransfer();
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const response = await original(input, init);
    if (String(input).endsWith("/personal-prompt-transfers") && init?.method === "POST") {
      workspace = {...workspace, revision: workspace.revision + 1, draft: {...workspace.draft, compiled: {...workspace.draft.compiled!, positive: "later remote cat"}}};
      throw new TypeError("lost");
    }
    return response;
  });
  const view = render(<MemoryRouter initialEntries={[url]}><ConversationWorkbenchPage /></MemoryRouter>);
  await confirmPersonal();
  await screen.findByText(/无法连接本地服务/);
  expect(localStorage.getItem("anima-personal-prompt-transfer:personal-test")).not.toBeNull();
  view.unmount();
  render(<MemoryRouter initialEntries={[url]}><ConversationWorkbenchPage /></MemoryRouter>);
  await screen.findByRole("button", {name: "撤销本次追加"});
  expect(screen.getByLabelText("正向提示词")).toHaveValue("later remote cat");
  expect(localStorage.getItem("anima-personal-prompt-transfer:personal-test")).toBeNull();
  expect(writes).toHaveLength(1);
});
it("late personal replay preserves new local prompt edits through the conflict workflow", async () => {
  personalServer(); const url = personalTransfer();
  const original = vi.mocked(fetch).getMockImplementation()!;
  let release!: () => void;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const response = await original(input, init);
    if (String(input).endsWith("/personal-prompt-transfers") && init?.method === "POST") {
      await new Promise<void>(resolve => {release = resolve;});
      return new Response(JSON.stringify({...await response.json(), replayed: true}));
    }
    return response;
  });
  render(<MemoryRouter initialEntries={[url]}><ConversationWorkbenchPage /></MemoryRouter>);
  await confirmPersonal();
  await waitFor(() => expect(release).toBeTypeOf("function"));
  expect(screen.getByRole("button", {name: "确认追加原文"})).toBeDisabled();
  // An editor event queued before the request lock settles must not be lost to a late response.
  fireEvent.change(screen.getByLabelText("正向提示词"), {target: {value: "new local cat"}});
  await act(async () => release());
  await screen.findByText("其他窗口已保存了更新，你的编辑仍在这里。");
  expect(screen.getByLabelText("正向提示词")).toHaveValue("new local cat");
  expect(screen.getByRole("button", {name: "撤销本次追加"})).toBeDisabled();
  expect(localStorage.getItem("anima-personal-prompt-transfer:personal-test")).toBeNull();
});
it.each(["workspace_busy", "workspace_proposal_pending", "workspace_revision_conflict"])("keeps personal preview and transfer after %s", async code => {
  personalServer();
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => String(input).endsWith("/personal-prompt-transfers") && init?.method === "POST"
    ? new Response(JSON.stringify({error: {code, message: "暂不能追加"}}), {status: 409}) : original(input, init));
  render(<MemoryRouter initialEntries={[personalTransfer()]}><ConversationWorkbenchPage /></MemoryRouter>);
  await confirmPersonal(); await screen.findByText("暂不能追加");
  expect(screen.getByLabelText("追加后正向提示词")).toHaveValue("cat\n Blue_Sky,\n(Cat:1.2) ");
  expect(localStorage.getItem("anima-personal-prompt-transfer:personal-test")).not.toBeNull();
  expect(screen.getByLabelText("正向提示词")).toHaveValue("cat");
});
it("keeps a pending proposal and does not flush or append personal text", async () => {
  personalServer();
  pendingProposal = {id: "proposal_test", workspace_id: workspace.id, base_revision: 3, draft: workspace.draft, changed_layers: [], warnings: [], created_at: "2026-09-29"};
  render(<MemoryRouter initialEntries={[personalTransfer()]}><ConversationWorkbenchPage /></MemoryRouter>);
  await screen.findByText("请先接受或放弃待处理的提示词草案。");
  expect(screen.getByRole("button", {name: "确认追加原文"})).toBeDisabled();
  expect(writes).toHaveLength(0);
  expect(localStorage.getItem("anima-personal-prompt-transfer:personal-test")).not.toBeNull();
});
it("retries personal workspace creation with the same frozen body and transfer-derived key", async () => {
  personalServer(); localStorage.removeItem("anima-conversation-active");
  const original = vi.mocked(fetch).getMockImplementation()!;
  let lost = true;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const response = await original(input, init);
    if (String(input) === "/api/v3/workspaces" && init?.method === "POST" && lost) {lost = false; throw new TypeError("lost");}
    return response;
  });
  render(<MemoryRouter initialEntries={[personalTransfer()]}><ConversationWorkbenchPage /></MemoryRouter>);
  await screen.findByText(/无法连接本地服务/);
  fireEvent.click(screen.getByRole("button", {name: "保存并重新预览"}));
  await screen.findByLabelText("追加后正向提示词");
  const created = writes.filter(item => item.url === "/api/v3/workspaces");
  expect(created).toHaveLength(2);
  expect(created[0].key).toBe("personal-prompt:personal-test");
  expect(created[1].key).toBe(created[0].key);
  expect(created[1].body).toEqual(created[0].body);
  expect(localStorage.getItem("anima-personal-prompt-transfer:personal-test")).not.toBeNull();
});
it("disables snapshot undo after local prompt edits and keeps those edits", async () => {
  personalServer();
  render(<MemoryRouter initialEntries={[personalTransfer()]}><ConversationWorkbenchPage /></MemoryRouter>);
  await confirmPersonal();
  await waitFor(() => expect(screen.getByRole("button", {name: "撤销本次追加"})).toBeEnabled());
  fireEvent.change(screen.getByLabelText("正向提示词"), {target: {value: "later local cat"}});
  expect(screen.getByRole("button", {name: "撤销本次追加"})).toBeDisabled();
  expect(screen.getByText("追加后已继续编辑，请在提示词中手动移除")).toBeInTheDocument();
  expect(writes).toHaveLength(1);
});
it("previews_cancels_and_recovers_personal_transfer", async () => {
  personalServer(); const url = personalTransfer();
  const view = render(<MemoryRouter initialEntries={[url]}><ConversationWorkbenchPage /></MemoryRouter>);
  await screen.findByLabelText("追加后正向提示词");
  expect(screen.getByLabelText("追加后正向提示词")).toHaveValue("cat\n Blue_Sky,\n(Cat:1.2) ");
  expect(writes).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", {name: "取消追加"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("cat");
  expect(localStorage.getItem("anima-personal-prompt-transfer:personal-test")).not.toBeNull();
  view.unmount();
  const remount = render(<MemoryRouter initialEntries={[url]}><ConversationWorkbenchPage /></MemoryRouter>);
  await waitFor(() => expect(screen.getByRole("button", {name: "确认追加原文"})).toBeEnabled(), {timeout: 3000});
  fireEvent.click(screen.getByRole("button", {name: "确认追加原文"}));
  await screen.findByRole("button", {name: "撤销本次追加"});
  expect(screen.getByLabelText("正向提示词")).toHaveValue("cat\n Blue_Sky,\n(Cat:1.2) ");
  expect(localStorage.getItem("anima-personal-prompt-transfer:personal-test")).toBeNull();
  expect(writes).toHaveLength(1);
  expect(writes[0].body).toEqual({transfer_id: "personal-test", revision: 3, positive: " Blue_Sky,\n(Cat:1.2) ", negative: "bad_hands"});
  remount.unmount();
  render(<MemoryRouter initialEntries={[url]}><ConversationWorkbenchPage /></MemoryRouter>);
  await waitFor(() => expect(screen.getByRole("button", {name: "撤销本次追加"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button", {name: "撤销本次追加"}));
  await waitFor(() => expect(screen.getByLabelText("正向提示词")).toHaveValue("cat"));
  expect(writes).toHaveLength(2);
  expect(writes.every(item => !item.url.includes("/turns") && !item.url.includes("/runs"))).toBe(true);
},10000);
it("flushes workbench edits before showing the preview and preserves unsent ideas and settings", async () => {
  personalServer(); const url = personalTransfer();
  localStorage.setItem("anima-conversation-draft:workspace_test", JSON.stringify({baseRevision: 3, delta: "keep idea", mode: "faithful", requirements: editableRequirements(workspace), positive: "local cat", negative: "local bad", model: "anima_base_v1", settings: {...workspace.draft.generation_settings, cfg: 7}}));
  render(<MemoryRouter initialEntries={[url]}><ConversationWorkbenchPage /></MemoryRouter>);
  await screen.findByLabelText("追加后正向提示词");
  expect(writes).toHaveLength(1);
  expect(writes[0].method).toBe("PUT");
  expect(writes[0].body.draft).toMatchObject({prompt_edit: {positive: "local cat", negative: "local bad"}, generation_settings: {cfg: 7}});
  expect(screen.getByLabelText("追加前正向提示词")).toHaveValue("local cat");
  await waitFor(() => expect(screen.getByRole("button", {name: "确认追加原文"})).toBeEnabled(), {timeout: 3000});
  fireEvent.click(screen.getByRole("button", {name: "确认追加原文"}));
  await screen.findByRole("button", {name: "撤销本次追加"});
  expect(screen.getByLabelText("这次想怎么改？")).toHaveValue("keep idea");
  expect(workspace.draft.generation_settings?.cfg).toBe(7);
});
it("keeps_transfer_on_save_failure", async () => {
  personalServer(); const url = personalTransfer();
  localStorage.setItem("anima-conversation-draft:workspace_test", JSON.stringify({baseRevision: 3, delta: "", mode: "faithful", requirements: editableRequirements(workspace), positive: "local cat", negative: "", model: "anima_base_v1", settings: workspace.draft.generation_settings}));
  failure = "conflict";
  render(<MemoryRouter initialEntries={[url]}><ConversationWorkbenchPage /></MemoryRouter>);
  await screen.findByText("已有更新");
  expect(localStorage.getItem("anima-personal-prompt-transfer:personal-test")).not.toBeNull();
  expect(screen.getByLabelText("正向提示词")).toHaveValue("local cat");
  expect(writes.some(item => item.url.endsWith("/personal-prompt-transfers"))).toBe(false);
});
it("negative_only_empty_target_is_not_false_success", async () => {
  personalServer(); workspace.draft.compiled = null;
  render(<MemoryRouter initialEntries={[personalTransfer("", "bad_hands")]}><ConversationWorkbenchPage /></MemoryRouter>);
  await screen.findByText("请先在工作台填写正向提示词，再追加这段负向内容");
  expect(screen.getByRole("button", {name: "确认追加原文"})).toBeDisabled();
  expect(writes).toHaveLength(0);
  expect(localStorage.getItem("anima-personal-prompt-transfer:personal-test")).not.toBeNull();
});
it("undo restores an originally empty compiled prompt without fabricating positive text", async () => {
  personalServer(); workspace.draft.compiled = null;
  render(<MemoryRouter initialEntries={[personalTransfer("cat", "bad")]}><ConversationWorkbenchPage /></MemoryRouter>);
  await waitFor(() => expect(screen.getByRole("button", {name: "确认追加原文"})).toBeEnabled(), {timeout: 3000});
  fireEvent.click(screen.getByRole("button", {name: "确认追加原文"}));
  await waitFor(() => expect(screen.getByRole("button", {name: "撤销本次追加"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button", {name: "撤销本次追加"}));
  await waitFor(() => expect(screen.getByLabelText("正向提示词")).toHaveValue(""));
  expect(workspace.draft.compiled).toBeNull();
});

let workspace: ConversationRecord;
let pendingProposal: {id: string; task?: string; review_status?: "needs_review"; workspace_id: string; base_revision: number; draft: ConversationRecord["draft"]; changed_layers: string[]; warnings: string[]; created_at: string} | null;
let writes: {url: string; method: string; body: Record<string, unknown>; key: string | null}[];
let failure: "" | "conflict" | "network" | "turn";
let acceptedRun: Record<string, unknown> | null;
let llmSettings: {current: {service: string; model: string; workbench_enable_thinking: boolean; thinking: {mode: string; message: string}}; services: object[]};
const target = {remote_profile_id: "cloud", workflow_profile_id: "workflow", remote_display_name: "测试服务器",
  workflow_display_name: "测试工作流", compatible_model_profiles: ["anima_base_v1"], availability: "ready"};
beforeEach(() => {
  localStorage.clear(); sessionStorage.setItem("anima-v3-session", "test-session");
  const requirements = emptyRequirements(); requirements.layers.subject.text = "一只猫";
  workspace = {id: "workspace_test", title: "会话测试", revision: 3, created_at: "2026-09-10", updated_at: "2026-09-10",
    draft: {positive_text: "", excluded_text: "", model_profile: "anima_base_v1", mode: "faithful",
      generation_settings: {...defaultGenerationSettings(), remote_profile_id: "cloud", workflow_profile_id: "workflow", execution_policy: {mode: "auto", preferredEnvironmentIds: ["cloud"]}},
      requirements: {...requirements, contract: "anima-requirements/1", revision: 1},
      compiled: {positive: "cat", negative: "", compiled_token: "cmp_test", source: "llm"}, compile_state: "fresh", conversation_events: []}};
  localStorage.setItem("anima-conversation-active", JSON.stringify(workspace.id));
  writes = []; failure = ""; pendingProposal = null; acceptedRun = null;
  llmSettings = {current: {service: "opencode_go", model: "mimo-v2.5", workbench_enable_thinking: false,
    thinking: {mode: "switchable", message: "支持切换深度思考。"}}, services: [{id: "opencode_go", name: "OpenCode Go",
      type: "openai_compatible", base_url: "https://opencode.ai/zen/go/v1", api_key_exists: true, api_key_masked: "saved",
      llm_models: [{name: "minimax-m3", display_name: "MiniMax", is_default: true}, {name: "mimo-v2.5", display_name: "MiMo", is_default: false}]}]};
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input), body = init?.body ? JSON.parse(String(init.body)) : null;
    if (body&&!url.includes("/checkpoints")&&!url.includes("/editor-context")) writes.push({url, method: init?.method || "GET", body, key: new Headers(init?.headers).get("Idempotency-Key")});
    let response: unknown = {items: []};
    if (url.endsWith("/llm/settings")) {
      if (init?.method === "PUT") llmSettings.current = {...llmSettings.current, service: body.service_id, model: body.model_name,
        workbench_enable_thinking: body.workbench_enable_thinking ?? llmSettings.current.workbench_enable_thinking};
      response = llmSettings;
    }
    else if (url.startsWith("/api/v3/workspaces?")) response = {items: [workspace]};
    // An accepted run is persisted and must remain visible to background polling.
    else if (url.includes("/runs?limit=")) response = {items: acceptedRun ? [acceptedRun] : []};
    else if (url === "/api/v3/workspaces" && init?.method === "POST") {
      workspace = {...workspace, id: "workspace_new", revision: 1, title: body.title,
        draft: {...workspace.draft, ...body.draft, requirements: body.draft.requirements_edit ? {...body.draft.requirements_edit, contract: "anima-requirements/1", revision: 1} : null, compiled: null, compile_state: "missing", conversation_events: []}};
      response = workspace;
    }
    else if (url.endsWith("/generation-targets")) response = {items: [target]};
    else if(url.endsWith("/editor-context"))response={token:"test-context"};
    else if (url.includes("/identities/preferences?")) response = {recent: [], favorites: [], aliases: []};
    else if (url.includes("/workbench/availability")) response = {availability: "ready"};
    else if (isSubmission(url)) {
      if (failure === "network") throw new TypeError("offline");
      const source=sourceOf(body);
      workspace = {...workspace, revision: workspace.revision + 1, draft: {...workspace.draft, compiled: {...workspace.draft.compiled!, positive: String(source.positive_prompt), compiled_token: "cmp_new"}}};
      acceptedRun = {id: "run_test", state: "draft", artifact_count: 0, status_message: "已接受", workspace_revision: workspace.revision, compiled_token: "cmp_new"};
      response = body.source?{id:"intent_test",state:"accepted",response:acceptedRun,run_id:"run_test",candidate_progress:{},retryable:false,reason:null}:acceptedRun;
    } else if (url.endsWith("/proposals/proposal_test/accept")) {
      workspace = {...workspace, revision: workspace.revision + 1, draft: pendingProposal!.draft}; pendingProposal = null; response = workspace;
    } else if (url.endsWith("/proposals/proposal_test") && init?.method === "DELETE") {
      pendingProposal = null; response = {ok: true};
    } else if (url.endsWith("/proposal")) response = {proposal: pendingProposal};
    else if (url.endsWith("/workbench/turns")) {
      if (failure === "turn") return new Response(JSON.stringify({error: {message: "模型分析失败", code: "llm_generation_failed"}}), {status: 502});
      const candidate: ConversationRecord = {...workspace, revision: workspace.revision + 1, draft: {...workspace.draft, mode: body.mode,
        compiled: {...workspace.draft.compiled!, positive: "cat in rain", compiled_token: "cmp_rewrite"},
        conversation_events: [{id: "event_1", delta: body.delta.text, changed_layers: ["lighting"], warnings: [], created_at: "2026-09-10"}]}};
      if (body.preview) {
        pendingProposal = {id: "proposal_test", task: body.task, workspace_id: workspace.id, base_revision: workspace.revision, draft: candidate.draft,
          changed_layers: ["lighting"], warnings: [], created_at: "2026-09-18"}; response = pendingProposal;
      } else {workspace = candidate; response = workspace;}
    } else if (url.endsWith(`/workspaces/${workspace.id}`)) {
      if (init?.method === "PUT") {
        if (failure === "conflict") {
          workspace = {...workspace, revision: 5};
          return new Response(JSON.stringify({error: {code: "workspace_revision_conflict", message: "已有更新"}}), {status: 409});
        }
        const stale = hasUncompiledInputs(workspace, {model: body.draft.model_profile, mode: body.draft.mode, requirements: body.draft.requirements_edit} as Parameters<typeof hasUncompiledInputs>[1]);
        workspace = {...workspace, revision: workspace.revision + 1, draft: {...workspace.draft,
          ...body.draft, generation_settings: Object.fromEntries(Object.entries(body.draft.generation_settings).sort(([a], [b]) => a.localeCompare(b))),
          ...(body.draft.prompt_edit ? {compiled: {...workspace.draft.compiled!, ...body.draft.prompt_edit, compiled_token: "cmp_saved", source: "user" as const}} : {}),
          requirements: {...body.draft.requirements_edit, contract: "anima-requirements/1", revision: 2}, compile_state: stale ? "stale" : workspace.draft.compile_state}};
      }
      response = workspace;
    }
    return new Response(JSON.stringify(response), {status: 200});
  });
});
afterEach(() => {cleanup(); vi.restoreAllMocks();});
function openTool(name: string) {
  const dialog=screen.queryByRole("dialog",{name:"创作辅助"});
  if(dialog)fireEvent.click(within(dialog).getByRole("tab",{name}));
  else fireEvent.click(screen.getByRole("button",{name:new RegExp("^"+name)}));
}
function openSection(name: string | RegExp) {
  if(name==="更多创作工具")return;
  if(name==="角色、画师与画面设计"){openTool("角色与画师");return;}
  if(name==="分层画面要求与锁定")openTool("分层要求");
  if(name instanceof RegExp&&name.source.includes("尺寸、采样与 LoRA")){fireEvent.click(screen.getByRole("button",{name:"生成参数"}));return;}
  const summary = screen.getByText(name, {selector: "summary"});
  if (!(summary.parentElement as HTMLDetailsElement).open) fireEvent.click(summary);
}
async function mount() {
  render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
  await waitFor(() => expect(screen.getByRole("button", {name: "生成图片"})).toBeEnabled(), {timeout: 3000});
  openSection("更多创作工具");
  openSection("角色、画师与画面设计");
  openSection("分层画面要求与锁定");
  openSection(/^改词模型/);
  openSection(/^负向提示词/);
}

it("persists the thinking preference for the current service and exact model without changing the draft", async () => {
  await mount();
  const toggle = await screen.findByRole("switch", {name: "深度思考"});
  expect(toggle).toHaveAttribute("aria-checked", "false");
  expect(screen.getByText("mimo-v2.5", {selector: "span.conversation-thinking-model"})).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("这次想怎么改？"), {target: {value: "我的未保存想法"}});
  fireEvent.click(toggle);
  await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({url: "/api/v3/llm/settings", method: "PUT", body: {
    service_id: "opencode_go", model_name: "mimo-v2.5", workbench_enable_thinking: true,
  }});
  expect(writes[0].body).not.toHaveProperty("api_key");
  expect(screen.getByLabelText("这次想怎么改？")).toHaveValue("我的未保存想法");
  expect(screen.getByLabelText("正向提示词")).toHaveValue("cat");
  expect(screen.getByRole("button", {name: "保存当前版本"})).toBeDisabled();
});

it("applies and replaces artist presets as separate persistent undo steps without deleting the subject", async () => {
  const original=vi.mocked(fetch).getMockImplementation()!;
  const common={revision:1,negative:"",model_family:"anima",model_label:"Anima Base",syntax:"comfy",source_url:"",source_author:"",notes:"",favorite:false,content_hash:"a".repeat(64),created_at:"today",updated_at:"today",samples:[],ready:false};
  vi.mocked(fetch).mockImplementation(async(input,init)=>String(input)==="/api/v3/artist-presets"?new Response(JSON.stringify({items:[{...common,id:"p1",name:"甲画师串",positive:"(@a:1.2), @b"},{...common,id:"p2",name:"乙画师串",positive:"@c, @d"}]})):original(input,init));
  await mount();
  openSection("角色、画师与画面设计");
  const picker=within(screen.getByRole("region",{name:"画师串调用"}));
  fireEvent.click(picker.getByRole("button",{name:"选择画师串"}));
  fireEvent.click(await picker.findByRole("button",{name:/甲画师串/}));
  fireEvent.click(picker.getByRole("button",{name:"应用这组画师串"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("cat\n\n(@a:1.2), @b");
  fireEvent.click(picker.getByRole("button",{name:"更换画师串"}));
  fireEvent.click(await picker.findByRole("button",{name:/乙画师串/}));
  fireEvent.click(picker.getByRole("button",{name:"替换当前画师串"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("cat\n\n@c, @d");
  fireEvent.click(screen.getByRole("button",{name:"返回提示词"}));
  fireEvent.click(screen.getByRole("button",{name:"撤销"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("cat\n\n(@a:1.2), @b");
  fireEvent.click(screen.getByRole("button",{name:"撤销"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("cat");
  fireEvent.click(screen.getByRole("button",{name:"重做"}));
  expect(readConversationDraft(workspace.id)?.local?.requirements.layers.style.artist_preset?.id).toBe("p1");
  fireEvent.change(screen.getByLabelText("正向提示词"),{target:{value:"cat\n\n(@a:1.3), @b"}});
  expect(screen.getByText(/甲画师串.*已自定义/, {selector:".studio-preset-summary"})).toBeInTheDocument();
  expect(picker.queryByText("移除画师串",{selector:"button"})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await waitFor(()=>expect(writes.some(item=>isSubmission(item.url))).toBe(true));
  expect(sourceOf(writes.find(item=>isSubmission(item.url))!.body).positive_prompt).toBe("cat\n\n(@a:1.3), @b");
  expect(readConversationDraft(workspace.id)?.local?.requirements.layers.style.artist_preset).toBeUndefined();
});

it("keeps the previous preference and local edits when saving thinking fails", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => String(input).endsWith("/llm/settings") && init?.method === "PUT"
    ? new Response(JSON.stringify({error: {code: "write_failed", message: "设置保存失败"}}), {status: 500}) : original(input, init));
  await mount();
  fireEvent.change(screen.getByLabelText("正向提示词"), {target: {value: "my edited prompt"}});
  fireEvent.click(await screen.findByRole("switch", {name: "深度思考"}));
  await screen.findByText(/设置保存失败/);
  expect(screen.getByRole("switch", {name: "深度思考"})).toHaveAttribute("aria-checked", "false");
  expect(screen.getByLabelText("正向提示词")).toHaveValue("my edited prompt");
  expect(screen.getByRole("button", {name: "生成图片"})).toBeEnabled();
});

it("reloads the saved thinking state when the server saves but its response is lost", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const response = await original(input, init);
    if (String(input).endsWith("/llm/settings") && init?.method === "PUT") throw new TypeError("response lost after saving");
    return response;
  });
  await mount();
  fireEvent.click(screen.getByRole("switch", {name: "深度思考"}));
  await waitFor(() => expect(screen.getByRole("switch", {name: "深度思考"})).toHaveAttribute("aria-checked", "true"));
  expect(screen.getByRole("alert")).toHaveTextContent("保存结果未确认");
  expect(screen.getByRole("alert")).toHaveTextContent("已重新读取");
  openTool("画面设计");
  expect(screen.getByRole("button", {name: "给我建议"})).toBeEnabled();
});

it("blocks text requests if both the save response and authoritative thinking reload fail", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  let saved = false;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith("/llm/settings")) {
      if (init?.method === "PUT") {await original(input, init); saved = true; throw new TypeError("response lost after saving");}
      if (saved) throw new TypeError("reload unavailable");
    }
    return original(input, init);
  });
  await mount();
  fireEvent.change(screen.getByLabelText("正向提示词"), {target: {value: "my retained edit"}});
  fireEvent.click(screen.getByRole("switch", {name: "深度思考"}));
  await waitFor(() => expect(screen.getByRole("switch", {name: "深度思考"})).toHaveTextContent("状态未读取"));
  expect(screen.getByRole("switch", {name: "深度思考"})).toBeDisabled();
  expect(screen.getByRole("alert")).toHaveTextContent("保存结果未确认");
  expect(screen.getByRole("alert")).toHaveTextContent("无法读取");
  openTool("画面设计");
  expect(screen.getByRole("button", {name: "给我建议"})).toBeDisabled();
  expect(screen.getByRole("button", {name: "生成图片"})).toBeEnabled();
  expect(screen.getByLabelText("正向提示词")).toHaveValue("my retained edit");
  fireEvent.change(screen.getByLabelText("这次想怎么改？"), {target: {value: "下雨"}});
  expect(screen.getByRole("button", {name: "更新提示词"})).toBeDisabled();
});

it("labels enabled thinking as unverified when its model capability has not been confirmed", async () => {
  llmSettings.current = {...llmSettings.current, workbench_enable_thinking: true,
    thinking: {mode: "unverified", message: "服务商可能忽略此设置。"}};
  await mount();
  expect(screen.getByRole("switch", {name: "深度思考"})).toHaveTextContent("开（待确认）");
});

it("does not present a failed settings load as disabled thinking or block image generation", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => String(input).endsWith("/llm/settings")
    ? new Response(JSON.stringify({error: {code: "settings_unavailable", message: "配置读取失败"}}), {status: 500}) : original(input, init));
  await mount();
  fireEvent.change(screen.getByLabelText("正向提示词"), {target: {value: "my prompt"}});
  expect(await screen.findByRole("switch", {name: "深度思考"})).toBeDisabled();
  expect(screen.getByRole("switch", {name: "深度思考"})).toHaveTextContent("状态未读取");
  openTool("画面设计");
  expect(screen.getByRole("button", {name: "给我建议"})).toBeDisabled();
  expect(screen.getByRole("button", {name: "生成图片"})).toBeEnabled();
  fireEvent.change(screen.getByLabelText("这次想怎么改？"), {target: {value: "下雨"}});
  expect(screen.getByRole("button", {name: "更新提示词"})).toBeDisabled();
});

it("requires an explicit opt-in for mandatory-thinking models while keeping manual editing available", async () => {
  llmSettings.current = {...llmSettings.current, model: "glm-5.3", thinking: {mode: "required", message: "该模型必须开启深度思考。"}};
  await mount();
  expect(screen.getByRole("switch", {name: "深度思考"})).toHaveTextContent("关（需开启）");
  fireEvent.change(screen.getByLabelText("这次想怎么改？"), {target: {value: "下雨"}});
  expect(screen.getByRole("button", {name: "更新提示词"})).toBeDisabled();
  openTool("画面设计");
  expect(screen.getByRole("button", {name: "给我建议"})).toBeDisabled();
  expect(screen.getByRole("combobox", {name: "景别"})).toBeEnabled();
  expect(screen.getAllByText(/开启深度思考或更换模型/).length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole("switch", {name: "深度思考"}));
  await waitFor(() => expect(screen.getByRole("button", {name: "更新提示词"})).toBeEnabled());
  openTool("画面设计");
  expect(screen.getByRole("button", {name: "给我建议"})).toBeEnabled();
});

it("refreshes the visible model and thinking capability after settings are saved", async () => {
  await mount();
  fireEvent.click(screen.getByRole("button", {name: "LLM 设置"}));
  fireEvent.change(await screen.findByLabelText("模型名称"), {target: {value: "minimax-m3"}});
  fireEvent.click(screen.getByRole("button", {name: "保存配置"}));
  await screen.findByText("minimax-m3", {selector: "span.conversation-thinking-model"});
  await waitFor(() => expect(screen.getByRole("switch", {name: "深度思考"})).toBeEnabled());
  fireEvent.click(screen.getByRole("switch", {name: "深度思考"}));
  await waitFor(() => expect(screen.getByRole("switch", {name: "深度思考"})).toHaveAttribute("aria-checked", "true"));
  expect(writes.at(-1)?.body).toMatchObject({service_id: "opencode_go", model_name: "minimax-m3", workbench_enable_thinking: true});
});

it("locks model and thinking changes until an advice request finishes even if the draft changes", async () => {
  let finish!: (value: Response) => void;
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => String(input).endsWith("/scene-advice")
    ? new Promise(resolve => {finish = resolve;}) : original(input, init));
  await mount();
  fireEvent.click(screen.getByRole("button", {name: "LLM 设置"}));
  await screen.findByLabelText("模型名称");
  openTool("画面设计");
  fireEvent.click(screen.getByRole("button", {name: "给我建议"}));
  expect(screen.getByRole("switch", {name: "深度思考"})).toBeDisabled();
  expect(screen.getByLabelText("模型名称")).toBeDisabled();
  fireEvent.change(screen.getByLabelText("这次想怎么改？"), {target: {value: "更新后的要求"}});
  expect(screen.getByRole("switch", {name: "深度思考"})).toBeDisabled();
  expect(screen.getByRole("button", {name: "更新提示词"})).toBeDisabled();
  await act(async () => finish(new Response(JSON.stringify({suggestions: [{title: "旧方向", reason: "旧内容", choices: {layout: {value: "居中构图"}}}], extracted: []}))));
  expect(screen.queryByText("助手建议 · 旧方向")).not.toBeInTheDocument();
  expect(screen.getByRole("switch", {name: "深度思考"})).toBeEnabled();
  expect(screen.getByLabelText("模型名称")).toBeEnabled();
});

it("keeps text requests disabled while a thinking preference is being saved", async () => {
  let finish!: () => void;
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith("/llm/settings") && init?.method === "PUT") await new Promise<void>(resolve => {finish = resolve;});
    return original(input, init);
  });
  await mount();
  fireEvent.change(screen.getByLabelText("这次想怎么改？"), {target: {value: "下雨"}});
  fireEvent.click(screen.getByRole("switch", {name: "深度思考"}));
  expect(screen.getByRole("switch", {name: "深度思考"})).toBeDisabled();
  openTool("画面设计");
  expect(screen.getByRole("button", {name: "给我建议"})).toBeDisabled();
  expect(screen.getByRole("button", {name: "更新提示词"})).toBeDisabled();
  await act(async () => finish());
  expect(screen.getByRole("switch", {name: "深度思考"})).toHaveAttribute("aria-checked", "true");
});

it("saves manual identity tags and preserves them in the local workspace draft", async () => {
  await mount();
  openTool("角色与画师");
  await waitFor(() => expect(screen.getByLabelText("角色 tag（每行一个）").closest("details")).toHaveAttribute("open"));
  fireEvent.change(screen.getByLabelText("角色 tag（每行一个）"), {target: {value: "Unknown_Hero_(Game)"}});
  fireEvent.change(screen.getByLabelText("作品 tag（动画／游戏，每行一个）"), {target: {value: "Example_Game"}});
  fireEvent.change(screen.getByLabelText("画师 tag（每行一个，可带 @）"), {target: {value: "@Sample_Artist"}});
  expect(screen.getByLabelText("正向提示词")).toHaveValue("@sample artist, example game, unknown hero \\(game\\), cat");
  fireEvent.click(screen.getByRole("button", {name: "保存当前版本"}));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0].body.draft).toMatchObject({requirements_edit: {layers: {
    subject: {character_tags: ["unknown hero (game)"], series_tags: ["example game"]},
    style: {manual_artist_tags: ["sample artist"]},
  }}});
  expect(readConversationDraft("workspace_test")!.local!.requirements.layers.subject.character_tags).toEqual(["Unknown_Hero_(Game)"]);
  expect(screen.getByRole("button", {name: "生成图片"})).toBeEnabled();
});

it("saves a pasted large seed without rounding", async () => {
  await mount();
  openSection(/^尺寸、采样与 LoRA/);
  fireEvent.change(screen.getByLabelText("种子模式"),{target:{value:"fixed"}});
  fireEvent.change(screen.getByLabelText("Seed"), {target: {value: "8798399215689017476"}});
  fireEvent.click(screen.getByRole("button",{name:"确认应用参数"}));
  fireEvent.click(screen.getByRole("button", {name: "保存当前版本"}));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0].body.draft).toMatchObject({generation_settings: {seed: "8798399215689017476"}});
  expect(screen.getByLabelText("Seed")).toHaveValue("8798399215689017476");
});

it("uses each community model's own recipe after leaving a customized model", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  const community = [
    ["anima_2_9b_preview_v1", "anima29_creator", 4, "euler", "sgm_uniform"],
    ["animayume_v1_5_base", "yume15_creator", 5.5, "euler_ancestral", "normal"],
  ].map(([model, recipe, cfg, sampler, scheduler]) => ({...target, workflow_profile_id: model,
    compatible_model_profiles: [model], default_recipe_id: recipe,
    generation_recipes: [{id: recipe, display_name: recipe, parameters: {steps: 30, cfg, sampler, scheduler}}]}));
  vi.mocked(fetch).mockImplementation(async (input, init) => String(input).endsWith("/generation-targets")
    ? new Response(JSON.stringify({items: [target, ...community]})) : original(input, init));
  await mount();
  openSection(/^尺寸、采样与 LoRA/);
  for (const item of community) {
    fireEvent.change(screen.getByLabelText("CFG"), {target: {value: "7"}});
    fireEvent.click(screen.getByRole("button",{name:"确认应用参数"}));
    fireEvent.change(screen.getByLabelText("模型"), {target: {value: item.compatible_model_profiles[0]}});
    expect(screen.getByLabelText("创作工作流")).toHaveValue(item.workflow_profile_id);
    const recipe=item.generation_recipes[0].parameters;
    expect(screen.getByLabelText("CFG")).toHaveValue(String(recipe.cfg));
    expect(screen.getByLabelText("Sampler")).toHaveValue(recipe.sampler);
    expect(screen.getByLabelText("Scheduler")).toHaveValue(recipe.scheduler);
    expect(screen.getByLabelText("Steps")).toHaveValue(String(recipe.steps));
    expect(screen.getByLabelText("负向提示词")).toHaveValue("");
  }
});

it.each(["flat", "configured", "frozen"])("preserves a %s legacy Aesthetic workspace when its catalog binding identifies v1.1", async kind => {
  const model = "anima_aesthetic_v1_1", workflow = "old-workflow", seed = "9223372036854775807";
  const bound = {...target, workflow_profile_id: workflow, compatible_model_profiles:[model], template_revision:"current"};
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation((input, init) => String(input).endsWith("/generation-targets")
    ? Promise.resolve(new Response(JSON.stringify({items:[bound]}))) : original(input, init));
  const schema = basicWorkflowSchema(workflow,"old-revision");
  const configuration = {modelProfile:LEGACY_AESTHETIC, workflow:{id:workflow,revision:"old-revision"}, baseRecipeId:"saved",
    recipeValues:{steps:30},parameterOverrides:{steps:22,seed},resourceRequirements:[],seedMode:"fixed" as const};
  const lora = {logical_id:"saved-style",file_name:"saved.safetensors",weight:0.7,trigger_words:[],required:true,source:{kind:"user" as const}};
  workspace.draft.model_profile = LEGACY_AESTHETIC;
  workspace.draft.requirements!.loras = [lora];
  workspace.draft.generation_settings = {...workspace.draft.generation_settings!,workflow_profile_id:kind==="configured"?"obsolete-cache":workflow,
    steps:22,seed,parameter_schema:schema,...(kind==="flat"?{}:{creation_configuration:configuration})};
  if(kind==="frozen")workspace.draft.generation_source={run_id:"frozen-run",model_profile:LEGACY_AESTHETIC,remote_profile_id:"cloud",workflow_profile_id:workflow};
  const expectedModel = kind==="frozen"?LEGACY_AESTHETIC:model;
  const renderPage = () => render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled/></MemoryRouter>);
  const view = renderPage();
  await screen.findByLabelText("正向提示词");
  await waitFor(()=>expect(screen.getByLabelText("模型")).toHaveValue(expectedModel));
  fireEvent.click(screen.getByRole("button",{name:"生成参数"}));
  expect(screen.getByLabelText("Steps")).toHaveValue("22");
  expect(screen.getByLabelText("Seed")).toHaveValue(seed);
  if(kind==="frozen"){
    fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
    await waitFor(()=>expect(writes.find(item=>isSubmission(item.url))?.body).toMatchObject({
      creationConfiguration:{modelProfile:LEGACY_AESTHETIC,workflow:{id:workflow,revision:"old-revision"}},
      source:{model_profile:LEGACY_AESTHETIC,workflow_snapshot_run_id:"frozen-run"}}));
    return;
  }
  fireEvent.click(screen.getByRole("button",{name:"保存当前版本"}));
  await screen.findByText("当前内容已保存。");
  expect(workspace.draft.model_profile).toBe(model);
  expect(workspace.draft.requirements!.loras).toEqual([lora]);
  expect(workspace.draft.generation_settings).toMatchObject({steps:22,seed,creation_configuration:{
    modelProfile:model,workflow:{id:workflow},parameterOverrides:{steps:22,seed},resourceRequirements:[lora]}});
  expect(workspace.draft.generation_settings!.model_configurations?.[LEGACY_AESTHETIC]).toBeUndefined();
  view.unmount();localStorage.clear();localStorage.setItem("anima-conversation-active",JSON.stringify(workspace.id));
  renderPage();await screen.findByLabelText("正向提示词");
  fireEvent.click(screen.getByRole("button",{name:"生成参数"}));
  expect(screen.getByLabelText("模型")).toHaveValue(model);
  expect(screen.getByLabelText("Steps")).toHaveValue("22");
  expect(screen.getByLabelText("Seed")).toHaveValue(seed);
});

it("opens a case workspace from its link and preserves the previous local draft", async () => {
  localStorage.setItem("anima-conversation-active", JSON.stringify("workspace_old"));
  localStorage.setItem("anima-conversation-draft:workspace_old", "keep my unfinished idea");
  render(<MemoryRouter initialEntries={["/workbench?workspace=workspace_test"]}><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
  await waitFor(() => expect(screen.getByLabelText("打开已有会话")).toHaveValue("workspace_test"));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("cat");
  expect(localStorage.getItem("anima-conversation-draft:workspace_old")).toBe("keep my unfinished idea");
  expect(localStorage.getItem("anima-conversation-active")).toBe(JSON.stringify("workspace_test"));
});

it("submits a case with its frozen workflow source while allowing model and target changes", async () => {
  workspace.draft.generation_source = {run_id: "source_run", model_profile: "anima_base_v1", remote_profile_id: "cloud", workflow_profile_id: "workflow"};
  await mount();
  openSection(/^尺寸、采样与 LoRA/);
  expect(screen.getByLabelText("模型")).toBeEnabled();
  expect(screen.getByLabelText("创作工作流")).toBeEnabled();
  fireEvent.click(screen.getByRole("button", {name: "生成图片"}));
  await waitFor(() => expect(writes.some(item => isSubmission(item.url))).toBe(true));
  expect(sourceOf(writes.find(item => isSubmission(item.url))!.body).workflow_snapshot_run_id).toBe("source_run");
});

it("only adds negative guidance on click and submits the visible text", async () => {
  await mount();
  expect(screen.getByLabelText("负向提示词")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("负向提示词"), {target: {value: "text"}});
  fireEvent.click(screen.getByRole("button", {name: "补充模型负向建议"}));
  const negative = (screen.getByLabelText("负向提示词") as HTMLTextAreaElement).value;
  expect(negative).toMatch(/^text, worst quality/);
  fireEvent.click(screen.getByRole("button", {name: "生成图片"}));
  await waitFor(() => expect(writes.some(item => isSubmission(item.url))).toBe(true));
  expect(sourceOf(writes.find(item => isSubmission(item.url))!.body).negative_prompt).toBe(negative);
});

it("rewrites without generating, then explicitly submits the current token and edited prompt", async () => {
  await mount();
  fireEvent.change(screen.getByLabelText("这次想怎么改？"), {target: {value: "下雨"}});
  expect(screen.getByRole("button", {name: "生成图片"})).toBeEnabled();
  fireEvent.click(screen.getByRole("button", {name: "更新提示词"}));
  for (const name of ["更新提示词", "保存当前版本", "生成图片"]) expect(screen.getByRole("button", {name})).toBeDisabled();
  await waitFor(() => expect(screen.getByLabelText("这次想怎么改？")).toHaveValue(""));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("cat in rain");
  expect(screen.queryByRole("button", {name: "采用修改"})).not.toBeInTheDocument();
  expect(writes.some(item => item.url.includes("/direct-prompt/"))).toBe(false);
  fireEvent.change(screen.getByLabelText("正向提示词"), {target: {value: "hand edited cat"}});
  await waitFor(() => expect(screen.getByRole("button", {name: "生成图片"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button", {name: "生成图片"}));
  await screen.findAllByText("已接受");
  const submission = writes.find(item => isSubmission(item.url))!;
  expect(sourceOf(submission.body)).toMatchObject({submission_kind: "conversational", workspace_id: workspace.id,
    compiled_token: "cmp_saved", positive_prompt: "hand edited cat", workspace_revision: 5, use_current_prompt: true});
  expect(sourceOf(submission.body)).not.toHaveProperty("lora_selection");
});

it("marks requirement edits unsaved and preserves them on revision conflict", async () => {
  await mount();
  openSection("分层画面要求与锁定");
  fireEvent.change(screen.getByLabelText("主体要求"), {target: {value: "本地的狐狸"}});
  expect(screen.getByRole("button", {name: "生成图片"})).toBeEnabled();
  failure = "conflict";
  fireEvent.click(screen.getByRole("button", {name: "保存当前版本"}));
  await screen.findByText("其他窗口已保存了更新，你的编辑仍在这里。");
  expect(screen.getByLabelText("主体要求")).toHaveValue("本地的狐狸");
  for (const name of ["更新提示词", "保存当前版本", "生成图片"]) expect(screen.getByRole("button", {name})).toBeDisabled();
});

it("opens older workspaces with absent generation settings without a false unsaved warning", async () => {
  workspace.draft.generation_settings = undefined;
  render(<MemoryRouter><ConversationWorkbenchPage /></MemoryRouter>);
  await screen.findByLabelText("正向提示词");
  openSection("更多创作工具");
  expect(screen.getByRole("button", {name: "保存当前版本"})).toBeDisabled();
  expect(screen.queryByText("要求尚未保存")).not.toBeInTheDocument();
  openSection(/^尺寸、采样与 LoRA/);
  fireEvent.change(screen.getByLabelText("宽度"), {target: {value: "1024"}});
  fireEvent.click(screen.getByRole("button",{name:"确认应用参数"}));
  expect(screen.getByRole("button", {name: "保存当前版本"})).toBeEnabled();
});

it("keeps edited prompts while closing and reopening the tools Sheet and copies without submitting", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator", {...navigator, clipboard: {writeText}});
  try {
    await mount();
    fireEvent.change(screen.getByLabelText("正向提示词"), {target: {value: "edited coffee scene"}});
    fireEvent.click(screen.getByRole("button", {name: "关闭辅助设置"}));
    expect(screen.queryByRole("dialog", {name: "创作辅助"})).not.toBeInTheDocument();
    openSection("角色、画师与画面设计");
    expect(screen.getByLabelText("正向提示词")).toHaveValue("edited coffee scene");
    fireEvent.click(screen.getByRole("button", {name: "返回提示词"}));
    fireEvent.click(screen.getByRole("button", {name: "复制正向提示词"}));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("edited coffee scene"));
    expect(writes).toHaveLength(0);
  } finally {vi.unstubAllGlobals();}
});

it("switches inspector parameters while retaining the same edited prompt node", async () => {
  await mount();
  const prompt = screen.getByLabelText("正向提示词");
  fireEvent.change(prompt, {target: {value: "my prompt before checking settings"}});
  const settings = document.querySelector(".conversation-studio__settings") as HTMLElement;
  openSection(/^尺寸、采样与 LoRA/);
  expect(settings).not.toHaveAttribute("hidden");
  expect(screen.getByLabelText("正向提示词")).toBe(prompt);
  expect(prompt).toHaveValue("my prompt before checking settings");
  expect(screen.getByLabelText("负向提示词")).toHaveValue("");
  fireEvent.click(screen.getByRole("button",{name:/^结果$/}));
  expect(settings).toHaveAttribute("hidden");
  openSection(/^尺寸、采样与 LoRA/);
  await waitFor(() => expect(settings).not.toHaveAttribute("hidden"));
  expect(screen.getByLabelText("正向提示词")).toBe(prompt);
  expect(prompt).toHaveValue("my prompt before checking settings");
  expect(writes).toHaveLength(0);
});

it.each(["faithful", "expand"] as const)("creates a new workspace in %s mode and rewrites the initial idea without generating", async mode => {
  localStorage.removeItem("anima-conversation-active");
  render(<MemoryRouter><ConversationWorkbenchPage /></MemoryRouter>);
  expect(screen.getByRole("radio", {name: "忠实还原"})).toBeChecked();
  fireEvent.click(screen.getByRole("radio", {name: mode === "expand" ? "适度扩写" : "忠实还原"}));
  expect(writes).toHaveLength(0);
  fireEvent.change(screen.getByLabelText("创作想法"), {target: {value: "双手捧花的魔女"}});
  await waitFor(() => expect(screen.getByRole("button", {name: "开始整理想法"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button", {name: "开始整理想法"}));
  await waitFor(() => expect(screen.getByLabelText("正向提示词")).toHaveValue("cat in rain"));
  expect(screen.queryByRole("region", {name: "待确认的修改"})).not.toBeInTheDocument();
  expect(writes).toHaveLength(2);
  expect(writes[0].url).toBe("/api/v3/workspaces");
  expect(writes[0].body.title).toBe("双手捧花的魔女");
  expect(writes[0].body.draft).toMatchObject({mode});
  expect(writes[1].body.mode).toBe(mode);
  expect(writes[1].body.preview).toBe(false);
  expect(screen.getByRole("radio", {name: mode === "expand" ? "适度扩写" : "忠实还原"})).toBeChecked();
  expect(writes.some(item => item.url.endsWith("/runs"))).toBe(false);
  expect(readConversationDraft("workspace_new")!.local!.delta).toBe("");
});

it("saves custom sampling parameters without silently changing the selected image aspect", async () => {
  await mount();
  openSection(/^尺寸、采样与 LoRA/);
  fireEvent.change(screen.getByLabelText("Sampler"), {target: {value: "er_sde"}});
  fireEvent.change(screen.getByLabelText("CFG"), {target: {value: "5.5"}});
  fireEvent.click(screen.getByRole("button",{name:"确认应用参数"}));
  fireEvent.click(screen.getByRole("button", {name: "保存当前版本"}));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0].body.draft).toMatchObject({generation_settings: {sampler: "er_sde", cfg: 5.5, preset_id: "stable_baseline", aspect: "portrait",creation_configuration:{baseRecipeId:"stable_baseline",parameterOverrides:{sampler:"er_sde",cfg:5.5}}}});
  await waitFor(() => expect(screen.getByRole("button", {name: "保存当前版本"})).toBeDisabled());
  await waitFor(() => expect(screen.getByRole("button", {name: "生成图片"})).toBeEnabled());
  expect(screen.getByLabelText("正向提示词")).toHaveValue("cat");
  expect(writes.some(item => item.url.endsWith("/workbench/turns"))).toBe(false);
});

it("retains the exact idempotency key and payload after a lost acceptance response", async () => {
  await mount(); failure = "network";
  fireEvent.click(screen.getByRole("button", {name: "生成图片"}));
  await screen.findByText("查询本次提交");
  await waitFor(() => expect(screen.getByRole("button", {name: "查询本次提交"})).toBeEnabled());
  for (const name of ["更新提示词", "保存当前版本", "生成图片"]) expect(screen.getByRole("button", {name})).toBeDisabled();
  failure = "";
  fireEvent.click(screen.getByRole("button", {name: "查询本次提交"}));
  await screen.findAllByText("已接受");
  const requests = writes.filter(item => isSubmission(item.url));
  expect(requests).toHaveLength(2);
  expect(requests[0].body).toEqual(requests[1].body);
  expect(requests[0].key).toBe(requests[1].key);
});

it("keeps a tentative mode local if the model fails", async () => {
  await mount(); failure = "turn";
  fireEvent.click(screen.getByRole("radio", {name: "适度扩写"}));
  fireEvent.click(screen.getByRole("button", {name: "更新提示词"}));
  await screen.findByText("模型分析失败");
  expect(writes).toHaveLength(1);
  expect(writes[0].body.mode).toBe("expand");
  expect(workspace.draft.mode).toBe("faithful");
  expect(screen.getByRole("radio", {name: "适度扩写"})).toBeChecked();
});

it("keeps rewrite choices visible and restores a locally selected mode without calling the model", async () => {
  render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
  await screen.findByLabelText("正向提示词");
  const expand = screen.getByRole("radio", {name: "适度扩写"});
  expect(expand.closest("details")).toBeNull();
  expect(screen.getByRole("radio", {name: "忠实还原"})).toBeChecked();
  fireEvent.click(expand);
  expect(readConversationDraft(workspace.id)!.local!.mode).toBe("expand");
  expect(screen.getByLabelText("正向提示词")).toHaveValue("cat");
  expect(writes).toHaveLength(0);
  cleanup();
  render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
  await screen.findByLabelText("正向提示词");
  expect(screen.getByRole("radio", {name: "适度扩写"})).toBeChecked();
  expect(writes).toHaveLength(0);
  fireEvent.click(screen.getByRole("radio", {name: "忠实还原"}));
  expect(readConversationDraft(workspace.id)!.local!.mode).toBe("faithful");
});

it("restores unsent text on reopen without overwriting it with the server copy", async () => {
  await mount();
  fireEvent.change(screen.getByLabelText("这次想怎么改？"), {target: {value: "尚未发送的要求"}});
  cleanup();
  render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
  await waitFor(() => expect(screen.getByLabelText("这次想怎么改？")).toHaveValue("尚未发送的要求"));
  expect(readConversationDraft(workspace.id)!.local!.delta).toBe("尚未发送的要求");
});


it("saves changed requirements then compiles once and directly applies prompt changes without generating", async () => {
  await mount();
  openSection("分层画面要求与锁定");
  fireEvent.change(screen.getByLabelText("主体要求"), {target: {value: "雨中的猫"}});
  fireEvent.click(screen.getByRole("button", {name: "更新提示词"}));
  await waitFor(() => expect(screen.getByLabelText("正向提示词")).toHaveValue("cat in rain"));
  expect(writes.map(item => item.url)).toEqual(["/api/v3/workspaces/workspace_test", "/api/v3/workbench/turns"]);
  expect(writes[1].body.revision).toBe(4);
  expect(writes[1].body.delta).toEqual({text: ""});
  expect(screen.queryByRole("region", {name: "待确认的修改"})).not.toBeInTheDocument();
  openSection("查看本次文字变化");
  expect(document.querySelector(".conversation-diff ins")).toHaveTextContent("in rain");
});

it("keeps local requirements and delta when save-and-compile fails", async () => {
  await mount(); failure = "turn";
  fireEvent.change(screen.getByLabelText("这次想怎么改？"), {target: {value: "柔和灯光"}});
  openSection("分层画面要求与锁定");
  fireEvent.change(screen.getByLabelText("主体要求"), {target: {value: "雨中的猫"}});
  fireEvent.click(screen.getByRole("button", {name: "更新提示词"}));
  await screen.findByText("模型分析失败");
  expect(screen.getByLabelText("主体要求")).toHaveValue("雨中的猫");
  expect(screen.getByLabelText("这次想怎么改？")).toHaveValue("柔和灯光");
  expect(writes.some(item => isSubmission(item.url))).toBe(false);
});

it("does not automatically recompile a fresh prompt but allows an explicit update", async () => {
  await mount();
  expect(screen.getByRole("button", {name: "更新提示词"})).toBeEnabled();
  expect(screen.getAllByRole("button", {name: "更新提示词"})).toHaveLength(1);
  expect(writes).toHaveLength(0);
});


it("continues the selected historical batch in a new workspace and leaves the old draft intact", async () => {
  const base = vi.mocked(fetch).getMockImplementation()!;
  const calls: string[] = [];
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input); calls.push(url);
    if (url.includes("/workspaces/workspace_test/runs")) return new Response(JSON.stringify({items: [
      {id: "run_recent", state: "completed", status_message: "最近批次", artifact_count: 0},
      {id: "run_old", state: "completed", status_message: "历史批次", artifact_count: 0},
    ]}));
    if (url === "/api/v3/generation-runs/run_old/workspace") return new Response(JSON.stringify({...workspace, id: "workspace_continued", title: "继续历史批次"}));
    return base(input, init);
  });
  await mount();
  fireEvent.change(screen.getByLabelText("这次想怎么改？"), {target: {value: "还没发送的草稿"}});
  const batches = await screen.findByRole("combobox", {name: "查看生成批次"});
  fireEvent.change(batches, {target: {value: "run_old"}});
  openSection("更多图片操作");
  fireEvent.click(screen.getByRole("button", {name: "沿用本次条件，新建会话"}));
  await waitFor(() => expect(screen.getByLabelText("打开已有会话")).toHaveValue("workspace_continued"));
  expect(readConversationDraft("workspace_test")!.local!.delta).toBe("还没发送的草稿");
  expect(calls).toContain("/api/v3/generation-runs/run_old/workspace");
  expect(calls.some(url => url.includes("reference-examples") || isSubmission(url))).toBe(false);
});


it("can compile manually entered requirements in a new empty workspace", async () => {
  workspace.draft.requirements = null; workspace.draft.compiled = null; workspace.draft.compile_state = "missing";
  render(<MemoryRouter><ConversationWorkbenchPage /></MemoryRouter>);
  await screen.findByLabelText("正向提示词");
  openSection("更多创作工具");
  openSection("分层画面要求与锁定");
  fireEvent.change(screen.getByLabelText("主体要求"), {target: {value: "一只猫"}});
  fireEvent.click(screen.getByRole("button", {name: "更新提示词"}));
  await waitFor(() => expect(screen.getByLabelText("正向提示词")).toHaveValue("cat in rain"));
  expect(writes.map(item => item.url)).toEqual(["/api/v3/workspaces/workspace_test", "/api/v3/workbench/turns"]);
});


it("adds a recommended artist to the visible prompt locally without an LLM rewrite or generation", async () => {
  const base = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith("/artist-ranking")) return new Response(JSON.stringify({ranking: "tag_fit"}));
    if (String(input).endsWith("/artists/recommend")) return new Response(JSON.stringify({items: [{name: "artist_test", render_name: "@artist test", post_count: 500, hit_count: 1, sources: ["cat"]}]}));
    return base(input, init);
  });
  await mount();
  fireEvent.change(screen.getByLabelText("这次想怎么改？"), {target: {value: "保留未发送内容"}});
  openSection("角色、画师与画面设计");
  fireEvent.click(screen.getByRole("button", {name: "画师推荐（可选）"}));
  fireEvent.click(screen.getByRole("button", {name: "刷新画师推荐"}));
  fireEvent.click(await screen.findByRole("button", {name: "加入画面要求"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("@artist test, cat");
  expect(screen.getByLabelText("这次想怎么改？")).toHaveValue("保留未发送内容");
  expect(readConversationDraft("workspace_test")!.local!.requirements.layers.style.artists).toEqual(["artist_test"]);
  expect(writes).toHaveLength(0);
});

it("receives typed tags once while retaining unsent edits, and undo leaves later edits intact", async () => {
  localStorage.setItem("anima-conversation-draft:workspace_test", JSON.stringify({
    baseRevision: 3, delta: "尚未发送的想法", mode: "faithful", requirements: workspace.draft.requirements,
    positive: "my edited cat", negative: "my negative", model: "anima_base_v1", settings: workspace.draft.generation_settings,
  }));
  const url = transferUrl([{name: "hatsune_miku", category: "character"}, {name: "blue_sky", category: "general"}]);
  const view = render(<MemoryRouter initialEntries={[url]}><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
  await screen.findByRole("button", {name: "撤销本次带入"});
  expect(screen.getByLabelText("正向提示词")).toHaveValue("hatsune miku, blue sky, my edited cat");
  fireEvent.click(await screen.findByRole("button", {name: "撤销本次带入"}));
  expect(screen.getByLabelText("这次想怎么改？")).toHaveValue("尚未发送的想法");
  expect(screen.getByLabelText("正向提示词")).toHaveValue("my edited cat");
  const draft = readConversationDraft("workspace_test")!.local!;
  expect(draft.requirements.layers.subject.character_tags).toBeUndefined();
  expect(draft.requirements.layers.subject.general_tags).toBeUndefined();
  expect(writes).toHaveLength(0);
  view.unmount();
  render(<MemoryRouter initialEntries={[url]}><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
  await screen.findByText(/这批内容已带入或已过期/);
  expect(screen.queryByRole("button", {name: "撤销本次带入"})).not.toBeInTheDocument();
});
it("creates a new typed selection workspace without overwriting the prior draft or calling a model", async () => {
  const oldDraft = JSON.stringify({delta: "旧草稿保留"});
  // An unrelated draft remains untouched when choosing a new destination.
  localStorage.setItem("anima-conversation-draft:unrelated", oldDraft);
  const url = transferUrl([{name: "hatsune_miku", category: "character"}, {name: "vocaloid", category: "copyright"}, {name: "@sample_artist", category: "artist"}], "new");
  render(<MemoryRouter initialEntries={[url]}><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
  await screen.findByRole("button", {name: "撤销本次带入"});
  expect(screen.getByLabelText("正向提示词")).toHaveValue("hatsune miku, vocaloid, @sample artist");
  const created = writes.find(item => item.url === "/api/v3/workspaces");
  expect(created?.body.draft).toMatchObject({requirements_edit: {layers: {subject: {character_tags: ["hatsune miku"], series_tags: ["vocaloid"]}, style: {manual_artist_tags: ["sample artist"]}}}});
  expect(localStorage.getItem("anima-conversation-draft:unrelated")).toBe(oldDraft);
  expect(writes.every(item => !item.url.includes("/turns") && !item.url.includes("/runs"))).toBe(true);
});

it("does not consume current-destination tags when the existing workspace cannot be loaded", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  let unavailable = true;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (unavailable && String(input).endsWith("/workspaces/workspace_test")) throw new TypeError("offline");
    return original(input, init);
  });
  const url = transferUrl([{name: "hatsune_miku", category: "character"}]);
  render(<MemoryRouter initialEntries={[url]}><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
  await screen.findByRole("button", {name: "重试带入"});
  expect(writes).toHaveLength(0);
  expect(localStorage.getItem("anima-content-transfer:" + new URL(url, "http://localhost").searchParams.get("transfer"))).not.toBeNull();
  unavailable = false;
  fireEvent.click(screen.getByRole("button", {name: "重试带入"}));
  await screen.findByRole("button", {name: "撤销本次带入"});
  expect(writes).toHaveLength(0);
});
it("retries a lost create response with the same frozen body and idempotency key", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  let lost = true;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const response = await original(input, init);
    if (String(input) === "/api/v3/workspaces" && init?.method === "POST" && lost) {lost = false; throw new TypeError("lost response");}
    return response;
  });
  const url = transferUrl([{name: "hatsune_miku", category: "character"}], "new");
  render(<MemoryRouter initialEntries={[url]}><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
  await waitFor(() => expect(screen.getByRole("button", {name: "重试带入"})).toBeEnabled(), {timeout: 3000});
  fireEvent.click(screen.getByRole("button", {name: "重试带入"}));
  await waitFor(() => expect(screen.getByRole("button", {name: "撤销本次带入"})).toBeEnabled(), {timeout: 3000});
  const created = writes.filter(item => item.url === "/api/v3/workspaces");
  expect(created).toHaveLength(2);
  expect(created[0].key).toBeTruthy();
  expect(created[0].key).toBe(created[1].key);
  expect(created[0].body).toEqual(created[1].body);
});

it.each([
  {code: "remote_not_configured", status: 503},
  {code: "idempotency_conflict", status: 409},
  {code: "invalid_request", status: 422},
])("retains the unconfirmed generation request when its retry returns $code", async ({code, status}) => {
  await mount();
  const original = vi.mocked(fetch).getMockImplementation()!;
  const submissions: {key: string | null; body: string}[] = [];
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (isSubmission(String(input))) {
      submissions.push({key: new Headers(init?.headers).get("Idempotency-Key"), body: String(init?.body)});
      if (submissions.length === 1) throw new TypeError("accepted response lost");
      if (submissions.length === 2) return new Response(JSON.stringify({error: {code, message: "无法确认原请求"}}), {status});
    }
    return original(input, init);
  });
  fireEvent.click(screen.getByRole("button", {name: "生成图片"}));
  fireEvent.click(await screen.findByRole("button", {name: "查询本次提交"}));
  await screen.findByText("无法确认原请求");
  expect(screen.getByRole("button", {name: "查询本次提交"})).toBeEnabled();
  expect(screen.getByRole("button", {name: "生成图片"})).toBeDisabled();
  expect(recoverConversationPending(workspace.id)).toEqual(submissions[0]);
  cleanup();
  render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
  const retryButton = await screen.findByRole("button", {name: "查询本次提交"});
  await waitFor(() => expect(retryButton).toBeEnabled());
  expect(submissions).toHaveLength(2);
  fireEvent.click(retryButton);
  await screen.findAllByText("已接受");
  expect(submissions).toHaveLength(3);
  expect(submissions[1]).toEqual(submissions[0]);
  expect(submissions[2]).toEqual(submissions[0]);
  expect(recoverConversationPending(workspace.id)).toBeNull();
});

it.each(["idempotency_conflict", "request_failed"])("retains a new generation request after the non-definitive error %s", async code => {
  await mount();
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => isSubmission(String(input))
    ? new Response(JSON.stringify({error: {code, message: "结果未能确认"}}), {status: 500}) : original(input, init));
  fireEvent.click(screen.getByRole("button", {name: "生成图片"}));
  await screen.findByText("结果未能确认");
  expect(screen.getByRole("button", {name: "查询本次提交"})).toBeEnabled();
  expect(recoverConversationPending(workspace.id)?.key).toBeTruthy();
  expect(screen.getByRole("button", {name: "生成图片"})).toBeDisabled();
});

it("retains the accepted request if its completion marker cannot be saved without automatically submitting again", async () => {
  await mount();
  const save = Storage.prototype.setItem;
  const storageWrite = vi.spyOn(Storage.prototype, "setItem").mockImplementation(function(this: Storage, key, value) {
    if (key.startsWith("anima-conversation-submission-done:")) throw new DOMException("quota", "QuotaExceededError");
    save.call(this, key, value);
  });
  fireEvent.click(screen.getByRole("button", {name: "生成图片"}));
  await screen.findByText(/无法保存完成记录/);
  expect(screen.getByRole("button", {name: "查询本次提交"})).toBeEnabled();
  expect(screen.getByRole("button", {name: "生成图片"})).toBeDisabled();
  const saved = recoverConversationPending(workspace.id);
  expect(saved?.key).toBe(writes.find(item => isSubmission(item.url))?.key);
  cleanup();
  storageWrite.mockRestore();
  render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
  const query = await screen.findByRole("button", {name: "查询本次提交"});
  expect(writes.filter(item => isSubmission(item.url))).toHaveLength(1);
  fireEvent.click(query);
  await screen.findAllByText("已接受");
  const submissions = writes.filter(item => isSubmission(item.url));
  expect(submissions).toHaveLength(2);
  expect(submissions[1].key).toBe(submissions[0].key);
  expect(submissions[1].body).toEqual(submissions[0].body);
  expect(recoverConversationPending(workspace.id)).toBeNull();
});

it("clears a new generation request after an explicit validation rejection before acceptance", async () => {
  await mount();
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => isSubmission(String(input))
    ? new Response(JSON.stringify({error: {code: "invalid_request", message: "参数未通过校验"}}), {status: 422}) : original(input, init));
  fireEvent.click(screen.getByRole("button", {name: "生成图片"}));
  await screen.findByText("参数未通过校验");
  expect(screen.queryByRole("button", {name: "查询本次提交"})).not.toBeInTheDocument();
  expect(screen.getByRole("button", {name: "生成图片"})).toBeEnabled();
  expect(recoverConversationPending(workspace.id)).toBeNull();
});

it.each([false,true])("preserves the request and stops combined generation when English is unchanged (server unchanged=%s)",async unchanged=>{
  await mount();
  const original=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    if(!String(input).endsWith("/workbench/turns"))return original(input,init);
    workspace={...workspace,revision:workspace.revision+1,draft:{...workspace.draft,
      requirements:{...workspace.draft.requirements!,layers:{...workspace.draft.requirements!.layers,
        composition:{...workspace.draft.requirements!.layers.composition,text:"全身像"}}}}};
    return new Response(JSON.stringify({...workspace,unchanged,message:"已是全身描述，请补充希望调整的取景范围。"}));
  });
  fireEvent.change(screen.getByLabelText("这次想怎么改？"),{target:{value:"改成全身像"}});
  fireEvent.click(screen.getByRole("button",{name:"更新并生图"}));
  await screen.findByText(/已是全身描述，请补充希望调整的取景范围/);
  expect(screen.getByLabelText("这次想怎么改？")).toHaveValue("改成全身像");
  expect(screen.getByLabelText("正向提示词")).toHaveValue("cat");
  expect(writes.some(item=>isSubmission(item.url))).toBe(false);
  expect(screen.getByRole("button",{name:"生成图片"})).toBeEnabled();
  expect(readConversationDraft(workspace.id)!.local!.delta).toBe("改成全身像");
});

it("keeps a newer request typed while an unchanged reply is pending",async()=>{
  await mount();
  let finish!:(response:Response)=>void;
  const original=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,init)=>String(input).endsWith("/workbench/turns")
    ? new Promise(resolve=>{finish=resolve;}) : original(input,init));
  fireEvent.change(screen.getByLabelText("这次想怎么改？"),{target:{value:"改成全身像"}});
  fireEvent.click(screen.getByRole("button",{name:"更新提示词"}));
  await waitFor(()=>expect(finish).toBeTypeOf("function"));
  fireEvent.change(screen.getByLabelText("这次想怎么改？"),{target:{value:"镜头拉远，头脚完整入画"}});
  await act(async()=>finish(new Response(JSON.stringify({...workspace,unchanged:true,message:"本次英文未变化。"}))));
  expect(screen.getByLabelText("这次想怎么改？")).toHaveValue("镜头拉远，头脚完整入画");
  expect(writes.some(item=>isSubmission(item.url))).toBe(false);
});

it("passes both reviewed prompt fields verbatim into a rewrite even if the workspace save echoes other text",async()=>{
  await mount();
  const original=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    const response=await original(input,init);
    if(String(input).endsWith(`/workspaces/${workspace.id}`)&&init?.method==="PUT"){
      workspace={...workspace,draft:{...workspace.draft,compiled:{...workspace.draft.compiled!,positive:"unexpected saved tag",negative:"unexpected saved negative"}}};
      return new Response(JSON.stringify(workspace));
    }
    return response;
  });
  const positive="  adult traveler,\n  (@Artist:1.25)  ",negative="  (blur:1.1),\n watermark  ";
  fireEvent.change(screen.getByLabelText("正向提示词"),{target:{value:positive}});
  fireEvent.change(screen.getByLabelText("负向提示词"),{target:{value:negative}});
  fireEvent.change(screen.getByLabelText("这次想怎么改？"),{target:{value:"改成夜晚"}});
  fireEvent.click(screen.getByRole("button",{name:"更新提示词"}));
  await waitFor(()=>expect(writes.some(item=>item.url.endsWith("/workbench/turns"))).toBe(true));
  expect(writes.find(item=>item.url.endsWith("/workbench/turns"))!.body).toMatchObject({
    compiled:{positive,negative},delta:{text:"改成夜晚"},revision:4,
  });
});

it("does not rewrite a manually cleared stored prompt from the previous version",async()=>{
  await mount();
  fireEvent.change(screen.getByLabelText("正向提示词"),{target:{value:""}});
  fireEvent.change(screen.getByLabelText("负向提示词"),{target:{value:"new negative only"}});
  fireEvent.change(screen.getByLabelText("这次想怎么改？"),{target:{value:"改成夜晚"}});
  expect(screen.getByRole("button",{name:"更新提示词"})).toBeDisabled();
  expect(screen.getByRole("button",{name:"更新并生图"})).toBeDisabled();
  expect(readConversationDraft(workspace.id)?.local).toMatchObject({positive:"",negative:"new negative only",delta:"改成夜晚"});
  expect(writes).toEqual([]);
});

it("starts a new turn from the saved empty prompt after removing the final selected tag",async()=>{
  workspace.draft.requirements!.layers.subject.character_tags=["shana"];
  workspace.draft.compiled={...workspace.draft.compiled!,positive:"shana",negative:"retain negative"};
  const original=vi.mocked(fetch).getMockImplementation()!;
  let turnBase:ConversationRecord["draft"]["compiled"];
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    const path=String(input);
    if(path.endsWith("/workbench/turns"))turnBase=workspace.draft.compiled;
    const result=await original(input,init);
    if(path.endsWith(workspace.id)&&init?.method==="PUT") {
      workspace={...workspace,draft:{...workspace.draft,compiled:{...workspace.draft.compiled!,positive:"",compiled_token:"empty-tag-receipt"}}};
      return new Response(JSON.stringify(workspace));
    }
    return result;
  });
  await mount();openTool("角色与画师");
  fireEvent.click(screen.getByRole("button",{name:"移除角色 shana"}));
  fireEvent.click(screen.getByRole("button",{name:"返回提示词"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("这次想怎么改？"),{target:{value:"描绘一名成人在雨中散步"}});
  fireEvent.click(screen.getByRole("button",{name:"更新提示词"}));
  await waitFor(()=>expect(writes.some(item=>item.url.endsWith("/workbench/turns"))).toBe(true));
  expect(turnBase!).toMatchObject({positive:"",negative:"retain negative"});
  expect(writes.find(item=>item.url.endsWith("/workbench/turns"))?.body.compiled).toBeUndefined();
});

it("keeps a protected prompt edit local if the workspace rejects removal of its lock",async()=>{
  workspace.draft.compiled!.positive="adult traveler, closed book";
  workspace.draft.requirements!.prompt_locks=[{target:"positive",text:"closed book"}];
  const original=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,init)=>String(input).endsWith(workspace.id)&&init?.method==="PUT"
    ? new Response(JSON.stringify({error:{code:"protected_prompt_changed",message:"请先解除固定片段 closed book。"}}),{status:422}) : original(input,init));
  await mount();
  fireEvent.change(screen.getByLabelText("正向提示词"),{target:{value:"adult traveler"}});
  fireEvent.click(screen.getByRole("button",{name:"生成图片"}));
  await screen.findByText("请先解除固定片段 closed book。");
  expect(screen.getByLabelText("正向提示词")).toHaveValue("adult traveler");
  expect(readConversationDraft(workspace.id)?.local?.positive).toBe("adult traveler");
  expect(writes.some(item=>isSubmission(item.url))).toBe(false);
});

it.each([true,false])("only offers a review when manual prompt synchronization returns a proposal (unchanged=%s)",async unchanged=>{
  const original=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async(input,init)=>{
    if(!String(input).endsWith("/workbench/turns"))return original(input,init);
    const body=JSON.parse(String(init?.body));
    expect(body).toMatchObject({preview:true,task:"sync_requirements",compiled:{positive:"hand-edited traveler",negative:""}});
    return new Response(JSON.stringify(unchanged ? {...workspace,workspace_id:workspace.id,unchanged:true,changed_layers:[],warnings:[],message:"画面要求与当前提示词一致。"}
      : {id:"proposal_sync",workspace_id:workspace.id,base_revision:workspace.revision,draft:workspace.draft,changed_layers:["subject"],warnings:[],unchanged:false}));
  });
  await mount();
  fireEvent.change(screen.getByLabelText("正向提示词"),{target:{value:"hand-edited traveler"}});
  fireEvent.click(screen.getByRole("button",{name:"按手工提示词同步画面要求"}));
  if(unchanged){
    await screen.findByText("画面要求与当前提示词一致。");
    expect(screen.queryByText("上次未处理的提示词草案")).toBeNull();
    expect(screen.getByRole("button",{name:"更新提示词"})).toBeEnabled();
  }else{
    await screen.findByText("上次未处理的提示词草案");
    expect(screen.getByRole("button",{name:"更新提示词"})).toBeDisabled();
  }
  expect(screen.getByLabelText("正向提示词")).toHaveValue("hand-edited traveler");
});

it("previews a bold rewrite of the exact editor text and only applies it on explicit acceptance", async () => {
  await mount();
  const positive = "  cat,\n  window  ", negative = "  watermark\n";
  fireEvent.change(screen.getByLabelText("正向提示词"), {target: {value: positive}});
  fireEvent.change(screen.getByLabelText("负向提示词"), {target: {value: negative}});
  fireEvent.change(screen.getByLabelText("这次想怎么改？"), {target: {value: "强调窗边光线"}});
  fireEvent.click(screen.getByRole("button", {name: "大胆重构"}));
  const review = await screen.findByRole("region", {name: "大胆重构预览"});
  expect(writes.find(item => item.url.endsWith("/workbench/turns"))?.body).toMatchObject({
    task: "bold_rewrite", preview: true, mode: "faithful", delta: {text: "强调窗边光线"}, compiled: {positive, negative},
  });
  expect(screen.getByLabelText("正向提示词")).toHaveValue(positive);
  expect(review.querySelector("ins")).toBeInTheDocument();
  expect(screen.getByRole("button", {name: "生成图片"})).toBeDisabled();
  fireEvent.click(within(review).getByRole("button", {name: "采用修改"}));
  await waitFor(() => expect(screen.getByLabelText("正向提示词")).toHaveValue("cat in rain"));
  expect(screen.getByLabelText("负向提示词")).toHaveValue(negative);
  expect(screen.getByRole("radio", {name: "忠实还原"})).toBeChecked();
  expect(screen.getByLabelText("这次想怎么改？")).toHaveValue("");
  expect(writes.some(item => isSubmission(item.url))).toBe(false);
  fireEvent.click(screen.getByRole("button", {name: "撤销"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue(positive);
  expect(screen.getByLabelText("负向提示词")).toHaveValue(negative);
});

it("recovers the bold preview after reload and protects later edits on discard", async () => {
  await mount();
  fireEvent.click(screen.getByRole("button", {name: "大胆重构"}));
  await screen.findByRole("region", {name: "大胆重构预览"});
  expect(writes.find(item => item.url.endsWith("/workbench/turns"))?.body.delta).toEqual({text: ""});
  cleanup();
  render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
  const review = await screen.findByRole("region", {name: "大胆重构预览"});
  expect(workspace.revision).toBe(3);
  fireEvent.change(screen.getByLabelText("这次想怎么改？"), {target: {value: "换一个角度"}});
  expect(within(review).getByRole("button", {name: "采用修改"})).toBeDisabled();
  fireEvent.change(screen.getByLabelText("这次想怎么改？"), {target: {value: ""}});
  expect(within(review).getByRole("button", {name: "采用修改"})).toBeEnabled();
  fireEvent.change(screen.getByLabelText("正向提示词"), {target: {value: "my later text"}});
  expect(within(review).getByRole("button", {name: "采用修改"})).toBeDisabled();
  fireEvent.change(screen.getByLabelText("这次想怎么改？"), {target: {value: "新的修改意见"}});
  fireEvent.click(within(review).getByRole("button", {name: "不采用"}));
  await waitFor(() => expect(screen.queryByRole("region", {name: "大胆重构预览"})).toBeNull());
  expect(workspace.revision).toBe(3);
  expect(screen.getByLabelText("正向提示词")).toHaveValue("my later text");
  expect(screen.getByLabelText("这次想怎么改？")).toHaveValue("新的修改意见");
  expect(writes.some(item => isSubmission(item.url))).toBe(false);
});

it("recovers a bold preview receipt without submitting a second rewrite or an image", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const result = await original(input, init);
    if (String(input).endsWith("/workbench/turns")) throw new TypeError("preview response lost");
    return result;
  });
  await mount();
  fireEvent.click(screen.getByRole("button", {name:"大胆重构"}));
  await screen.findByRole("region", {name:"大胆重构预览"});
  expect(writes.filter(item => item.url.endsWith("/workbench/turns"))).toHaveLength(1);
  expect(screen.getByLabelText("正向提示词")).toHaveValue("cat");
  expect(writes.some(item => isSubmission(item.url))).toBe(false);
});

it("retries a bold preview as preview-only and releases the editor on an unchanged receipt", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  const turns: Record<string, unknown>[] = [];
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (!String(input).endsWith("/workbench/turns")) return original(input, init);
    turns.push(JSON.parse(String(init?.body)));
    const ok = turns.length === 2;
    return new Response(JSON.stringify(ok ? {...workspace, unchanged:true, message:"当前构图已满足意见。"}
      : {error:{code:"llm_generation_failed",message:"模型暂时无响应。"}}), {status:ok ? 200 : 502});
  });
  await mount();
  const button=screen.getByRole("button", {name:"大胆重构"});
  fireEvent.change(screen.getByLabelText("正向提示词"), {target:{value:"  "}});
  expect(button).toBeDisabled();
  fireEvent.change(screen.getByLabelText("正向提示词"), {target:{value:"cat"}});
  fireEvent.click(button);
  fireEvent.click(await screen.findByRole("button", {name:"重试大胆重构"}));
  await screen.findByText("当前构图已满足意见。");
  expect(turns).toHaveLength(2);
  for (const turn of turns) expect(turn).toMatchObject({task:"bold_rewrite", preview:true});
  expect(screen.queryByRole("region", {name:"大胆重构预览"})).toBeNull();
  expect(screen.getByRole("button", {name:"生成图片"})).toBeEnabled();
});

it.each(["更新提示词","更新并生图"])("keeps an uncertain ordinary rewrite available for review instead of automatically applying %s", async buttonName => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (!String(input).endsWith("/workbench/turns")) return original(input,init);
    const body=JSON.parse(String(init?.body));
    expect(body.preview).toBe(false);
    const candidate=structuredClone(workspace.draft);
    candidate.compiled!.positive="cat near the window in late light";
    candidate.requirements!.layers.lighting.text="傍晚的窗光";
    candidate.conversation_events.push({id:"uncertain",delta:body.delta.text,changed_layers:["lighting"],warnings:[],created_at:"today"});
    pendingProposal={id:"proposal_test",task:"rewrite",review_status:"needs_review",workspace_id:workspace.id,base_revision:workspace.revision,
      draft:candidate,changed_layers:["lighting"],warnings:["请核对通透感是否符合你的预期。"],created_at:"today"};
    return new Response(JSON.stringify(pendingProposal));
  });
  await mount();
  fireEvent.change(screen.getByLabelText("这次想怎么改？"), {target:{value:"把窗光改成傍晚"}});
  fireEvent.click(screen.getByRole("button",{name:buttonName}));
  const review=await screen.findByRole("region",{name:"待核对候选"});
  expect(within(review).getByText("请核对通透感是否符合你的预期。")).toBeVisible();
  expect(screen.getByLabelText("正向提示词")).toHaveValue("cat");
  expect(workspace.revision).toBe(3);
  expect(screen.getByRole("button",{name:"生成图片"})).toBeDisabled();
  if(buttonName==="更新提示词"){
    fireEvent.click(within(review).getByRole("button",{name:"带入草稿继续编辑"}));
    await waitFor(()=>expect(screen.queryByRole("region",{name:"待核对候选"})).toBeNull());
    expect(readConversationDraft(workspace.id)?.local?.requirements.layers.lighting.text).toBe("傍晚的窗光");
    expect(workspace.revision).toBe(3);
    expect(screen.getByLabelText("这次想怎么改？")).toHaveValue("把窗光改成傍晚");
    expect(writes.some(call=>call.url.endsWith("/accept"))).toBe(false);
    fireEvent.change(screen.getByLabelText("正向提示词"),{target:{value:"my own twilight edit"}});
    expect(readConversationDraft(workspace.id)?.local?.positive).toBe("my own twilight edit");
  }else{
    cleanup();
    render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
    const recovered=await screen.findByRole("region",{name:"待核对候选"});
    fireEvent.click(within(recovered).getByRole("button",{name:"采用修改"}));
    await waitFor(()=>expect(screen.getByLabelText("正向提示词")).toHaveValue("cat near the window in late light"));
    expect(workspace.revision).toBe(4);
  }
  expect(writes.some(call=>isSubmission(call.url))).toBe(false);
});
