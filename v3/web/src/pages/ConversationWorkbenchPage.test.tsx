import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {ConversationWorkbenchPage} from "./ConversationWorkbenchPage";
import {emptyRequirements} from "../lib/conversation";
import type {ConversationRecord} from "../lib/conversation";
import {defaultGenerationSettings} from "../lib/generationSettings";

let workspace: ConversationRecord;
let writes: {url: string; method: string; body: Record<string, unknown>; key: string | null}[];
let failure: "" | "conflict" | "network" | "turn";
const target = {remote_profile_id: "cloud", workflow_profile_id: "workflow", remote_display_name: "测试服务器",
  workflow_display_name: "测试工作流", compatible_model_profiles: ["anima_base_v1"], availability: "ready"};
beforeEach(() => {
  localStorage.clear(); sessionStorage.setItem("anima-v3-session", "test-session");
  const requirements = emptyRequirements(); requirements.layers.subject.text = "一只猫";
  workspace = {id: "workspace_test", title: "会话测试", revision: 3, created_at: "2026-09-10", updated_at: "2026-09-10",
    draft: {positive_text: "", excluded_text: "", model_profile: "anima_base_v1", mode: "faithful",
      generation_settings: {...defaultGenerationSettings(), remote_profile_id: "cloud", workflow_profile_id: "workflow"},
      requirements: {...requirements, contract: "anima-requirements/1", revision: 1},
      compiled: {positive: "cat", negative: "", compiled_token: "cmp_test", source: "llm"}, compile_state: "fresh", conversation_events: []}};
  localStorage.setItem("anima-conversation-active", JSON.stringify(workspace.id));
  writes = []; failure = "";
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input), body = init?.body ? JSON.parse(String(init.body)) : null;
    if (body) writes.push({url, method: init?.method || "GET", body, key: new Headers(init?.headers).get("Idempotency-Key")});
    let response: unknown = {items: []};
    if (url.startsWith("/api/v3/workspaces?")) response = {items: [workspace]};
    else if (url === "/api/v3/workspaces" && init?.method === "POST") {
      workspace = {...workspace, id: "workspace_new", revision: 1, title: body.title,
        draft: {...workspace.draft, ...body.draft, requirements: null, compiled: null, compile_state: "missing", conversation_events: []}};
      response = workspace;
    }
    else if (url.endsWith("/generation-targets")) response = {items: [target]};
    else if (url.includes("/workbench/availability")) response = {availability: "ready"};
    else if (url.endsWith("/direct-prompt/runs")) {
      if (failure === "network") throw new TypeError("offline");
      workspace = {...workspace, revision: 4, draft: {...workspace.draft, compiled: {...workspace.draft.compiled!, positive: body.positive_prompt, compiled_token: "cmp_new"}}};
      response = {id: "run_test", state: "draft", artifact_count: 0, status_message: "已接受", workspace_revision: 4, compiled_token: "cmp_new"};
    } else if (url.endsWith("/workbench/turns")) {
      if (failure === "turn") return new Response(JSON.stringify({error: {message: "模型分析失败", code: "llm_generation_failed"}}), {status: 502});
      workspace = {...workspace, revision: workspace.revision + 1, draft: {...workspace.draft, mode: body.mode,
        compiled: {...workspace.draft.compiled!, positive: "cat in rain", compiled_token: "cmp_rewrite"},
        conversation_events: [{id: "event_1", delta: body.delta.text, changed_layers: ["lighting"], warnings: [], created_at: "2026-09-10"}]}};
      response = workspace;
    } else if (url.endsWith(`/workspaces/${workspace.id}`)) {
      if (init?.method === "PUT") {
        if (failure === "conflict") {
          workspace = {...workspace, revision: 5};
          return new Response(JSON.stringify({error: {code: "workspace_revision_conflict", message: "已有更新"}}), {status: 409});
        }
        workspace = {...workspace, revision: workspace.revision + 1, draft: {...workspace.draft,
          ...body.draft, generation_settings: Object.fromEntries(Object.entries(body.draft.generation_settings).sort(([a], [b]) => a.localeCompare(b))),
          requirements: {...body.draft.requirements_edit, contract: "anima-requirements/1", revision: 2}, compile_state: "stale"}};
      }
      response = workspace;
    }
    return new Response(JSON.stringify(response), {status: 200});
  });
});
afterEach(() => {cleanup(); vi.restoreAllMocks();});
async function mount() {
  render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
  await waitFor(() => expect(screen.getByRole("button", {name: "生成图片"})).toBeEnabled());
}

it("rewrites without generating, then explicitly submits the current token and edited prompt", async () => {
  await mount();
  fireEvent.change(screen.getByLabelText("继续追加要求"), {target: {value: "下雨"}});
  expect(screen.getByRole("button", {name: "生成图片"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button", {name: "发送修改"}));
  await screen.findByText("已更新：光影");
  expect(writes.some(item => item.url.includes("/direct-prompt/"))).toBe(false);
  fireEvent.change(screen.getByLabelText("正向提示词"), {target: {value: "hand edited cat"}});
  await waitFor(() => expect(screen.getByRole("button", {name: "生成图片"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button", {name: "生成图片"}));
  await screen.findAllByText("已接受");
  const submission = writes.find(item => item.url.endsWith("/direct-prompt/runs"))!;
  expect(submission.body).toMatchObject({submission_kind: "conversational", workspace_id: workspace.id,
    compiled_token: "cmp_rewrite", positive_prompt: "hand edited cat", workspace_revision: 4});
  expect(submission.body).not.toHaveProperty("lora_selection");
});

it("marks requirement edits unsaved and preserves them on revision conflict", async () => {
  await mount();
  fireEvent.click(screen.getByRole("tab", {name: "画面要求"}));
  fireEvent.change(screen.getByLabelText("主体要求"), {target: {value: "本地的狐狸"}});
  expect(screen.getByRole("button", {name: "生成图片"})).toBeDisabled();
  failure = "conflict";
  fireEvent.click(screen.getByRole("button", {name: "保存要求与设置"}));
  await screen.findByText("服务端已有更新，你未提交的输入仍在这里。");
  expect(screen.getByLabelText("主体要求")).toHaveValue("本地的狐狸");
  expect(screen.getByRole("button", {name: "生成图片"})).toBeDisabled();
});

it("opens older workspaces with absent generation settings without a false unsaved warning", async () => {
  workspace.draft.generation_settings = undefined;
  render(<MemoryRouter><ConversationWorkbenchPage /></MemoryRouter>);
  await screen.findByText("已编译");
  expect(screen.getByRole("button", {name: "保存要求与设置"})).toBeDisabled();
  expect(screen.queryByText("要求尚未保存")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", {name: "生成设置"}));
  fireEvent.change(screen.getByLabelText("宽度"), {target: {value: "1024"}});
  expect(screen.getByRole("button", {name: "保存要求与设置"})).toBeEnabled();
});

it("keeps edited prompts across keyboard tab navigation and copies the current text without submitting", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator", {...navigator, clipboard: {writeText}});
  try {
    await mount();
    fireEvent.change(screen.getByLabelText("正向提示词"), {target: {value: "edited coffee scene"}});
    fireEvent.keyDown(screen.getByRole("tab", {name: "提示词"}), {key: "ArrowRight"});
    expect(screen.getByRole("tab", {name: "画面要求"})).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", {name: "画面要求"})).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("tab", {name: "画面要求"}), {key: "Home"});
    expect(screen.getByLabelText("正向提示词")).toHaveValue("edited coffee scene");
    fireEvent.click(screen.getByRole("button", {name: "复制正向提示词"}));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("edited coffee scene"));
    expect(writes).toHaveLength(0);
  } finally {vi.unstubAllGlobals();}
});

it("carries a starting idea into a new local draft without an LLM or generation call", async () => {
  localStorage.removeItem("anima-conversation-active");
  render(<MemoryRouter><ConversationWorkbenchPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("创作想法"), {target: {value: "双手捧花的魔女"}});
  fireEvent.click(screen.getByRole("button", {name: "创建会话"}));
  await waitFor(() => expect(screen.getByLabelText("描述你想画的内容")).toHaveValue("双手捧花的魔女"));
  expect(writes).toHaveLength(1);
  expect(writes[0].url).toBe("/api/v3/workspaces");
  expect(JSON.parse(localStorage.getItem("anima-conversation-draft:workspace_new")!).delta).toBe("双手捧花的魔女");
});

it("saves custom sampling parameters without silently changing the selected image aspect", async () => {
  await mount();
  fireEvent.click(screen.getByRole("tab", {name: "生成设置"}));
  fireEvent.change(screen.getByLabelText("采样器"), {target: {value: "er_sde"}});
  fireEvent.change(screen.getByLabelText("CFG"), {target: {value: "5.5"}});
  fireEvent.click(screen.getByRole("button", {name: "保存要求与设置"}));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0].body.draft).toMatchObject({generation_settings: {sampler: "er_sde", cfg: 5.5, preset_id: "custom", aspect: "portrait"}});
  await waitFor(() => expect(screen.getByRole("button", {name: "保存要求与设置"})).toBeDisabled());
  expect(screen.getByText("需要重新编译")).toBeInTheDocument();
});

it("retains the exact idempotency key and payload after a lost acceptance response", async () => {
  await mount(); failure = "network";
  fireEvent.click(screen.getByRole("button", {name: "生成图片"}));
  await screen.findByText("查询本次提交");
  await waitFor(() => expect(screen.getByRole("button", {name: "查询本次提交"})).toBeEnabled());
  failure = "";
  fireEvent.click(screen.getByRole("button", {name: "查询本次提交"}));
  await screen.findAllByText("已接受");
  const requests = writes.filter(item => item.url.endsWith("/direct-prompt/runs"));
  expect(requests).toHaveLength(2);
  expect(requests[0].body).toEqual(requests[1].body);
  expect(requests[0].key).toBe(requests[1].key);
});

it("keeps a tentative mode local if the model fails", async () => {
  await mount(); failure = "turn";
  fireEvent.change(screen.getByLabelText("改写方式"), {target: {value: "expand"}});
  fireEvent.click(screen.getByRole("button", {name: "重新编译"}));
  await screen.findByText("模型分析失败");
  expect(writes).toHaveLength(1);
  expect(writes[0].body.mode).toBe("expand");
  expect(workspace.draft.mode).toBe("faithful");
});

it("restores unsent text on reopen without overwriting it with the server copy", async () => {
  await mount();
  fireEvent.change(screen.getByLabelText("继续追加要求"), {target: {value: "尚未发送的要求"}});
  cleanup();
  render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
  await waitFor(() => expect(screen.getByLabelText("继续追加要求")).toHaveValue("尚未发送的要求"));
  expect(JSON.parse(localStorage.getItem(`anima-conversation-draft:${workspace.id}`)!).delta).toBe("尚未发送的要求");
});
