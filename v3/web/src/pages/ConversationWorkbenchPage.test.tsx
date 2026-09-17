import {act, cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {ConversationWorkbenchPage} from "./ConversationWorkbenchPage";
import {transferUrl} from "../lib/contentTransfer";
import {emptyRequirements, hasUncompiledInputs} from "../lib/conversation";
import type {ConversationRecord} from "../lib/conversation";
import {defaultGenerationSettings} from "../lib/generationSettings";

let workspace: ConversationRecord;
let writes: {url: string; method: string; body: Record<string, unknown>; key: string | null}[];
let failure: "" | "conflict" | "network" | "turn";
let llmSettings: {current: {service: string; model: string; workbench_enable_thinking: boolean; thinking: {mode: string; message: string}}; services: object[]};
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
  llmSettings = {current: {service: "opencode_go", model: "mimo-v2.5", workbench_enable_thinking: false,
    thinking: {mode: "switchable", message: "支持切换深度思考。"}}, services: [{id: "opencode_go", name: "OpenCode Go",
      type: "openai_compatible", base_url: "https://opencode.ai/zen/go/v1", api_key_exists: true, api_key_masked: "saved",
      llm_models: [{name: "minimax-m3", display_name: "MiniMax", is_default: true}, {name: "mimo-v2.5", display_name: "MiMo", is_default: false}]}]};
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input), body = init?.body ? JSON.parse(String(init.body)) : null;
    if (body) writes.push({url, method: init?.method || "GET", body, key: new Headers(init?.headers).get("Idempotency-Key")});
    let response: unknown = {items: []};
    if (url.endsWith("/llm/settings")) {
      if (init?.method === "PUT") llmSettings.current = {...llmSettings.current, service: body.service_id, model: body.model_name,
        workbench_enable_thinking: body.workbench_enable_thinking ?? llmSettings.current.workbench_enable_thinking};
      response = llmSettings;
    }
    else if (url.startsWith("/api/v3/workspaces?")) response = {items: [workspace]};
    else if (url === "/api/v3/workspaces" && init?.method === "POST") {
      workspace = {...workspace, id: "workspace_new", revision: 1, title: body.title,
        draft: {...workspace.draft, ...body.draft, requirements: body.draft.requirements_edit ? {...body.draft.requirements_edit, contract: "anima-requirements/1", revision: 1} : null, compiled: null, compile_state: "missing", conversation_events: []}};
      response = workspace;
    }
    else if (url.endsWith("/generation-targets")) response = {items: [target]};
    else if (url.includes("/identities/preferences?")) response = {recent: [], favorites: [], aliases: []};
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
        const stale = hasUncompiledInputs(workspace, {model: body.draft.model_profile, mode: body.draft.mode, requirements: body.draft.requirements_edit} as Parameters<typeof hasUncompiledInputs>[1]);
        workspace = {...workspace, revision: workspace.revision + 1, draft: {...workspace.draft,
          ...body.draft, generation_settings: Object.fromEntries(Object.entries(body.draft.generation_settings).sort(([a], [b]) => a.localeCompare(b))),
          requirements: {...body.draft.requirements_edit, contract: "anima-requirements/1", revision: 2}, compile_state: stale ? "stale" : workspace.draft.compile_state}};
      }
      response = workspace;
    }
    return new Response(JSON.stringify(response), {status: 200});
  });
});
afterEach(() => {cleanup(); vi.restoreAllMocks();});
async function mount() {
  render(<MemoryRouter><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
  await waitFor(() => expect(screen.getByRole("button", {name: "生成图片"})).toBeEnabled(), {timeout: 3000});
}

it("persists the thinking preference for the current service and exact model without changing the draft", async () => {
  await mount();
  const toggle = await screen.findByRole("switch", {name: "深度思考"});
  expect(toggle).toHaveAttribute("aria-checked", "false");
  expect(screen.getByText("mimo-v2.5", {selector: "span.conversation-thinking-model"})).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("继续追加要求"), {target: {value: "我的未保存想法"}});
  fireEvent.click(toggle);
  await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
  expect(writes).toHaveLength(1);
  expect(writes[0]).toMatchObject({url: "/api/v3/llm/settings", method: "PUT", body: {
    service_id: "opencode_go", model_name: "mimo-v2.5", workbench_enable_thinking: true,
  }});
  expect(writes[0].body).not.toHaveProperty("api_key");
  expect(screen.getByLabelText("继续追加要求")).toHaveValue("我的未保存想法");
  expect(screen.getByLabelText("正向提示词")).toHaveValue("cat");
  expect(screen.getByRole("button", {name: "保存要求与设置"})).toBeDisabled();
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
  expect(screen.getByRole("button", {name: "给我建议"})).toBeDisabled();
  expect(screen.getByRole("button", {name: "生成图片"})).toBeEnabled();
  expect(screen.getByLabelText("正向提示词")).toHaveValue("my retained edit");
  fireEvent.change(screen.getByLabelText("继续追加要求"), {target: {value: "下雨"}});
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
  expect(screen.getByRole("button", {name: "给我建议"})).toBeDisabled();
  expect(screen.getByRole("button", {name: "生成图片"})).toBeEnabled();
  fireEvent.change(screen.getByLabelText("继续追加要求"), {target: {value: "下雨"}});
  expect(screen.getByRole("button", {name: "更新提示词"})).toBeDisabled();
});

it("requires an explicit opt-in for mandatory-thinking models while keeping manual editing available", async () => {
  llmSettings.current = {...llmSettings.current, model: "glm-5.3", thinking: {mode: "required", message: "该模型必须开启深度思考。"}};
  await mount();
  expect(screen.getByRole("switch", {name: "深度思考"})).toHaveTextContent("关（需开启）");
  fireEvent.change(screen.getByLabelText("继续追加要求"), {target: {value: "下雨"}});
  expect(screen.getByRole("button", {name: "更新提示词"})).toBeDisabled();
  expect(screen.getByRole("button", {name: "给我建议"})).toBeDisabled();
  expect(screen.getByRole("combobox", {name: "景别"})).toBeEnabled();
  expect(screen.getAllByText(/开启深度思考或更换模型/).length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole("switch", {name: "深度思考"}));
  await waitFor(() => expect(screen.getByRole("button", {name: "更新提示词"})).toBeEnabled());
  expect(screen.getByRole("button", {name: "给我建议"})).toBeEnabled();
});

it("refreshes the visible model and thinking capability after settings are saved", async () => {
  await mount();
  fireEvent.click(screen.getByRole("button", {name: "LLM 设置"}));
  fireEvent.change(await screen.findByLabelText("模型名称"), {target: {value: "minimax-m3"}});
  fireEvent.click(screen.getByRole("button", {name: "保存配置"}));
  await screen.findByText("minimax-m3", {selector: "span.conversation-thinking-model"});
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
  fireEvent.click(screen.getByRole("button", {name: "给我建议"}));
  expect(screen.getByRole("switch", {name: "深度思考"})).toBeDisabled();
  expect(screen.getByLabelText("模型名称")).toBeDisabled();
  fireEvent.change(screen.getByLabelText("继续追加要求"), {target: {value: "更新后的要求"}});
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
  fireEvent.change(screen.getByLabelText("继续追加要求"), {target: {value: "下雨"}});
  fireEvent.click(screen.getByRole("switch", {name: "深度思考"}));
  expect(screen.getByRole("switch", {name: "深度思考"})).toBeDisabled();
  expect(screen.getByRole("button", {name: "给我建议"})).toBeDisabled();
  expect(screen.getByRole("button", {name: "更新提示词"})).toBeDisabled();
  await act(async () => finish());
  expect(screen.getByRole("switch", {name: "深度思考"})).toHaveAttribute("aria-checked", "true");
});

it("saves manual identity tags and preserves them in the local workspace draft", async () => {
  await mount();
  fireEvent.click(screen.getByRole("tab", {name: "画面要求"}));
  fireEvent.click(screen.getByText("角色、作品与画师", {selector: "summary strong"}));
  await waitFor(() => expect(screen.getByLabelText("角色 tag（每行一个）").closest("details")).toHaveAttribute("open"));
  fireEvent.change(screen.getByLabelText("角色 tag（每行一个）"), {target: {value: "Unknown_Hero_(Game)"}});
  fireEvent.change(screen.getByLabelText("作品 tag（动画／游戏，每行一个）"), {target: {value: "Example_Game"}});
  fireEvent.change(screen.getByLabelText("画师 tag（每行一个，可带 @）"), {target: {value: "@Sample_Artist"}});
  expect(screen.getByLabelText("正向提示词")).toHaveValue("cat");
  fireEvent.click(screen.getByRole("button", {name: "保存要求与设置"}));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0].body.draft).toMatchObject({requirements_edit: {layers: {
    subject: {character_tags: ["unknown hero (game)"], series_tags: ["example game"]},
    style: {manual_artist_tags: ["sample artist"]},
  }}});
  expect(JSON.parse(localStorage.getItem("anima-conversation-draft:workspace_test")!).requirements.layers.subject.character_tags).toEqual(["unknown hero (game)"]);
  expect(screen.getByRole("button", {name: "生成图片"})).toBeDisabled();
});

it("saves a pasted large seed without rounding", async () => {
  await mount();
  fireEvent.click(screen.getByRole("tab", {name: "生成设置"}));
  fireEvent.change(screen.getByLabelText("种子（-1 随机）"), {target: {value: "8798399215689017476"}});
  fireEvent.click(screen.getByRole("button", {name: "保存要求与设置"}));
  await waitFor(() => expect(writes).toHaveLength(1));
  expect(writes[0].body.draft).toMatchObject({generation_settings: {seed: "8798399215689017476"}});
  expect(screen.getByLabelText("种子（-1 随机）")).toHaveValue("8798399215689017476");
});

it("uses each community workflow's parameters after switching model and target", async () => {
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
  fireEvent.click(screen.getByRole("tab", {name: "生成设置"}));
  for (const item of community) {
    fireEvent.change(screen.getByLabelText("CFG"), {target: {value: "7"}});
    fireEvent.change(screen.getByLabelText("模型"), {target: {value: item.compatible_model_profiles[0]}});
    expect(screen.getByLabelText("执行目标")).toHaveValue(`cloud::${item.workflow_profile_id}`);
    expect(screen.getByLabelText("CFG")).toHaveValue(item.generation_recipes[0].parameters.cfg);
    expect(screen.getByLabelText("采样器")).toHaveValue(item.generation_recipes[0].parameters.sampler);
    expect(screen.getByLabelText("调度器")).toHaveValue(item.generation_recipes[0].parameters.scheduler);
    expect(screen.getByLabelText("步数")).toHaveValue(30);
    expect(screen.getByLabelText("负向提示词")).toHaveValue("");
  }
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

it("submits a case with its frozen workflow source and locks model and target choices", async () => {
  workspace.draft.generation_source = {run_id: "source_run", model_profile: "anima_base_v1", remote_profile_id: "cloud", workflow_profile_id: "workflow"};
  await mount();
  fireEvent.click(screen.getByRole("tab", {name: "生成设置"}));
  expect(screen.getByLabelText("模型")).toBeDisabled();
  expect(screen.getByLabelText("执行目标")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", {name: "生成图片"}));
  await waitFor(() => expect(writes.some(item => item.url.endsWith("/direct-prompt/runs"))).toBe(true));
  expect(writes.find(item => item.url.endsWith("/direct-prompt/runs"))!.body.workflow_snapshot_run_id).toBe("source_run");
});

it("only adds negative guidance on click and submits the visible text", async () => {
  await mount();
  expect(screen.getByLabelText("负向提示词")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("负向提示词"), {target: {value: "text"}});
  fireEvent.click(screen.getByRole("button", {name: "补充模型负向建议"}));
  const negative = (screen.getByLabelText("负向提示词") as HTMLTextAreaElement).value;
  expect(negative).toMatch(/^text, worst quality/);
  fireEvent.click(screen.getByRole("button", {name: "生成图片"}));
  await waitFor(() => expect(writes.some(item => item.url.endsWith("/direct-prompt/runs"))).toBe(true));
  expect(writes.find(item => item.url.endsWith("/direct-prompt/runs"))!.body.negative_prompt).toBe(negative);
});

it("rewrites without generating, then explicitly submits the current token and edited prompt", async () => {
  await mount();
  fireEvent.change(screen.getByLabelText("继续追加要求"), {target: {value: "下雨"}});
  expect(screen.getByRole("button", {name: "生成图片"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button", {name: "更新提示词"}));
  for (const name of ["更新提示词", "保存要求与设置", "生成图片"]) expect(screen.getByRole("button", {name})).toBeDisabled();
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
  for (const name of ["更新提示词", "保存要求与设置", "生成图片"]) expect(screen.getByRole("button", {name})).toBeDisabled();
});

it("opens older workspaces with absent generation settings without a false unsaved warning", async () => {
  workspace.draft.generation_settings = undefined;
  render(<MemoryRouter><ConversationWorkbenchPage /></MemoryRouter>);
  await screen.findByText("已就绪，可继续调整");
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

it("opens and scrolls to generation settings while retaining the same edited prompt node", async () => {
  await mount();
  const prompt = screen.getByLabelText("正向提示词");
  fireEvent.change(prompt, {target: {value: "my prompt before checking settings"}});
  const settings = document.getElementById("panel-settings") as HTMLDetailsElement;
  const scrollIntoView = vi.fn(); settings.scrollIntoView = scrollIntoView;
  fireEvent.click(screen.getByRole("tab", {name: "生成设置"}));
  await waitFor(() => expect(scrollIntoView).toHaveBeenCalledOnce());
  expect(settings).toHaveAttribute("open");
  expect(scrollIntoView.mock.calls[0][0]).toMatchObject({block: "start"});
  expect(screen.getByLabelText("正向提示词")).toBe(prompt);
  expect(prompt).toHaveValue("my prompt before checking settings");
  expect(screen.getByLabelText("负向提示词")).toHaveValue("");
  // Reopening from the dock must also work after the user collapses the same
  // settings panel without changing its selected inspector tab.
  fireEvent.click(settings.querySelector("summary")!);
  expect(settings).not.toHaveAttribute("open");
  scrollIntoView.mockClear();
  fireEvent.click(screen.getByRole("button", {name: "查看生成条件"}));
  await waitFor(() => expect(settings).toHaveAttribute("open"));
  expect(scrollIntoView).toHaveBeenCalledOnce();
  expect(screen.getByLabelText("正向提示词")).toBe(prompt);
  expect(prompt).toHaveValue("my prompt before checking settings");
  expect(writes).toHaveLength(0);
});

it("carries a starting idea into a new local draft without an LLM or generation call", async () => {
  localStorage.removeItem("anima-conversation-active");
  render(<MemoryRouter><ConversationWorkbenchPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("创作想法"), {target: {value: "双手捧花的魔女"}});
  fireEvent.click(screen.getByRole("button", {name: "创建会话"}));
  await waitFor(() => expect(screen.getByLabelText("描述你想画的内容")).toHaveValue("双手捧花的魔女"));
  expect(writes).toHaveLength(1);
  expect(writes[0].url).toBe("/api/v3/workspaces");
  expect(writes[0].body.title).toBe("双手捧花的魔女");
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
  await waitFor(() => expect(screen.getByRole("button", {name: "生成图片"})).toBeEnabled());
  expect(screen.getByLabelText("正向提示词")).toHaveValue("cat");
  expect(writes.some(item => item.url.endsWith("/workbench/turns"))).toBe(false);
});

it("retains the exact idempotency key and payload after a lost acceptance response", async () => {
  await mount(); failure = "network";
  fireEvent.click(screen.getByRole("button", {name: "生成图片"}));
  await screen.findByText("查询本次提交");
  await waitFor(() => expect(screen.getByRole("button", {name: "查询本次提交"})).toBeEnabled());
  for (const name of ["更新提示词", "保存要求与设置", "生成图片"]) expect(screen.getByRole("button", {name})).toBeDisabled();
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
  fireEvent.click(screen.getByRole("button", {name: "更新提示词"}));
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


it("saves changed requirements then compiles once and shows reviewed prompt changes without generating", async () => {
  await mount();
  fireEvent.click(screen.getByRole("tab", {name: "画面要求"}));
  fireEvent.change(screen.getByLabelText("主体要求"), {target: {value: "雨中的猫"}});
  fireEvent.click(screen.getByRole("button", {name: "更新提示词"}));
  await screen.findByText("查看本次提示词变化");
  expect(writes.map(item => item.url)).toEqual(["/api/v3/workspaces/workspace_test", "/api/v3/workbench/turns"]);
  expect(writes[1].body.revision).toBe(4);
  expect(writes[1].body.delta).toEqual({text: ""});
  expect(screen.getByRole("tab", {name: "提示词"})).toHaveAttribute("aria-selected", "true");
  fireEvent.click(screen.getByText("查看本次提示词变化"));
  expect(screen.getByText("cat", {selector: "pre"})).toBeInTheDocument();
  expect(screen.getByText("cat in rain", {selector: "pre"})).toBeInTheDocument();
});

it("keeps local requirements and delta when save-and-compile fails", async () => {
  await mount(); failure = "turn";
  fireEvent.change(screen.getByLabelText("继续追加要求"), {target: {value: "柔和灯光"}});
  fireEvent.click(screen.getByRole("tab", {name: "画面要求"}));
  fireEvent.change(screen.getByLabelText("主体要求"), {target: {value: "雨中的猫"}});
  fireEvent.click(screen.getByRole("button", {name: "更新提示词"}));
  await screen.findByText("模型分析失败");
  expect(screen.getByLabelText("主体要求")).toHaveValue("雨中的猫");
  expect(screen.getByLabelText("继续追加要求")).toHaveValue("柔和灯光");
  expect(writes.some(item => item.url.endsWith("/direct-prompt/runs"))).toBe(false);
});

it("does not offer unnecessary recompilation for a fresh prompt", async () => {
  await mount();
  expect(screen.getByRole("button", {name: "更新提示词"})).toBeDisabled();
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
  fireEvent.change(screen.getByLabelText("继续追加要求"), {target: {value: "还没发送的草稿"}});
  const batches = await screen.findByRole("combobox", {name: "查看生成批次"});
  fireEvent.change(batches, {target: {value: "run_old"}});
  fireEvent.click(screen.getByRole("button", {name: "沿用本次条件，新建会话"}));
  await waitFor(() => expect(screen.getByLabelText("打开已有会话")).toHaveValue("workspace_continued"));
  expect(JSON.parse(localStorage.getItem("anima-conversation-draft:workspace_test")!).delta).toBe("还没发送的草稿");
  expect(calls).toContain("/api/v3/generation-runs/run_old/workspace");
  expect(calls.some(url => url.includes("reference-examples") || url.endsWith("/direct-prompt/runs"))).toBe(false);
});


it("can compile manually entered requirements in a new empty workspace", async () => {
  workspace.draft.requirements = null; workspace.draft.compiled = null; workspace.draft.compile_state = "missing";
  render(<MemoryRouter><ConversationWorkbenchPage /></MemoryRouter>);
  await screen.findByRole("tab", {name: "画面要求"});
  fireEvent.click(screen.getByRole("tab", {name: "画面要求"}));
  fireEvent.change(screen.getByLabelText("主体要求"), {target: {value: "一只猫"}});
  fireEvent.click(screen.getByRole("button", {name: "更新提示词"}));
  await screen.findByText("查看本次提示词变化");
  expect(writes.map(item => item.url)).toEqual(["/api/v3/workspaces/workspace_test", "/api/v3/workbench/turns"]);
});


it("adds a recommended artist only to local requirements without rewriting or generating", async () => {
  const base = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith("/artist-ranking")) return new Response(JSON.stringify({ranking: "tag_fit"}));
    if (String(input).endsWith("/artists/recommend")) return new Response(JSON.stringify({items: [{name: "artist_test", render_name: "@artist test", post_count: 500, hit_count: 1, sources: ["cat"]}]}));
    return base(input, init);
  });
  await mount();
  fireEvent.change(screen.getByLabelText("继续追加要求"), {target: {value: "保留未发送内容"}});
  fireEvent.click(screen.getByRole("button", {name: "画师推荐（可选）"}));
  fireEvent.click(screen.getByRole("button", {name: "刷新画师推荐"}));
  fireEvent.click(await screen.findByRole("button", {name: "加入画面要求"}));
  expect(screen.getByLabelText("正向提示词")).toHaveValue("cat");
  expect(screen.getByLabelText("继续追加要求")).toHaveValue("保留未发送内容");
  expect(JSON.parse(localStorage.getItem("anima-conversation-draft:workspace_test")!).requirements.layers.style.artists).toEqual(["artist_test"]);
  expect(writes).toHaveLength(0);
});

it("receives typed tags once while retaining unsent edits, and undo leaves later edits intact", async () => {
  localStorage.setItem("anima-conversation-draft:workspace_test", JSON.stringify({
    baseRevision: 3, delta: "尚未发送的想法", mode: "faithful", requirements: workspace.draft.requirements,
    positive: "my edited cat", negative: "my negative", model: "anima_base_v1", settings: workspace.draft.generation_settings,
  }));
  const url = transferUrl([{name: "hatsune_miku", category: "character"}, {name: "blue_sky", category: "general"}]);
  const view = render(<MemoryRouter initialEntries={[url]}><ConversationWorkbenchPage remoteEnabled /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", {name: "撤销本次带入"}));
  expect(screen.getByLabelText("继续追加要求")).toHaveValue("尚未发送的想法");
  expect(screen.getByLabelText("正向提示词")).toHaveValue("my edited cat");
  const draft = JSON.parse(localStorage.getItem("anima-conversation-draft:workspace_test")!);
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
  fireEvent.click(await screen.findByRole("button", {name: "重试带入"}));
  await screen.findByRole("button", {name: "撤销本次带入"});
  const created = writes.filter(item => item.url === "/api/v3/workspaces");
  expect(created).toHaveLength(2);
  expect(created[0].key).toBeTruthy();
  expect(created[0].key).toBe(created[1].key);
  expect(created[0].body).toEqual(created[1].body);
});
