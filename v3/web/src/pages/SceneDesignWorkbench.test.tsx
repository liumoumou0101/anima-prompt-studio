import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {ConversationWorkbenchPage} from "./ConversationWorkbenchPage";
import {emptyRequirements, type ConversationRecord, type LocalConversation} from "../lib/conversation";
import {defaultGenerationSettings} from "../lib/generationSettings";

let workspace: ConversationRecord;
let writes: {url: string; body: Record<string, any>}[];
let failCompilation: boolean;
beforeEach(() => {
  localStorage.clear(); sessionStorage.setItem("anima-v3-session", "test-session");
  workspace = {id: "workspace_scene", title: "画面设计接入", revision: 1, created_at: "2026-09-12", updated_at: "2026-09-12",
    draft: {positive_text: "", excluded_text: "", model_profile: "anima_base_v1", mode: "faithful",
      generation_settings: defaultGenerationSettings(), requirements: {...emptyRequirements(), contract: "anima-requirements/1", revision: 1},
      compiled: {positive: "reviewed prompt", negative: "original exclusions", compiled_token: "cmp_scene", source: "user"},
      compile_state: "fresh", conversation_events: []}};
  localStorage.setItem("anima-conversation-active", JSON.stringify(workspace.id));
  writes = []; failCompilation = false;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input), body = init?.body ? JSON.parse(String(init.body)) : undefined;
    if (body) writes.push({url, body});
    let response: unknown = {items: []};
    if (url.startsWith("/api/v3/workspaces?")) response = {items: [workspace]};
    else if (url.includes("/identities/preferences?")) response = {recent: [], favorites: [], aliases: []};
    else if (url === `/api/v3/workspaces/${workspace.id}`) {
      if (init?.method === "PUT") {
        const requirements = structuredClone(body.draft.requirements_edit);
        // Exercise the optional defaults returned by the real model serializer.
        requirements.layers.composition.design ||= {};
        for (const field of ["shot", "layout", "camera", "gaze"]) {
          const choice = requirements.layers.composition.design[field];
          requirements.layers.composition.design[field] = choice ? {target: "", evidence: "", ...choice} : null;
        }
        requirements.layers.lighting.mood ||= null;
        workspace = {...workspace, revision: workspace.revision + 1, draft: {...workspace.draft, ...body.draft,
          requirements: {...requirements, contract: "anima-requirements/1", revision: 2}, compile_state: "stale"}};
      }
      response = workspace;
    } else if (url === "/api/v3/workbench/turns") {
      if (failCompilation) return new Response(JSON.stringify({error: {code: "llm_generation_failed", message: "这次整理失败"}}), {status: 502});
      workspace = {...workspace, revision: workspace.revision + 1, draft: {...workspace.draft, compile_state: "fresh",
        compiled: {positive: "compiled scene intent", negative: body.compiled?.negative || "", compiled_token: "cmp_scene_updated", source: "llm"}}};
      response = workspace;
    }
    return new Response(JSON.stringify(response), {status: 200});
  });
});
afterEach(() => {cleanup(); vi.restoreAllMocks();});
function draft(): LocalConversation {return JSON.parse(localStorage.getItem("anima-conversation-draft:workspace_scene")!);}
async function mount() {
  const view = render(<MemoryRouter><ConversationWorkbenchPage /></MemoryRouter>);
  await screen.findByRole("region", {name: "画面设计辅助"});
  await waitFor(() => expect(screen.getByRole("combobox", {name: "景别"})).toBeEnabled());
  return view;
}

it("keeps choices in the local draft, saves without an LLM call, and reopens without false unsaved state", async () => {
  const originalSettings = structuredClone(workspace.draft.generation_settings);
  const view = await mount();
  fireEvent.change(screen.getByRole("combobox", {name: "景别"}), {target: {value: "全身"}});
  expect(draft().requirements.layers.composition.design?.shot).toEqual({value: "全身", source: "user"});
  expect(draft().settings).toEqual(originalSettings);
  expect(screen.getByLabelText("正向提示词")).toHaveValue("reviewed prompt");
  expect(screen.getByLabelText("负向提示词")).toHaveValue("original exclusions");
  expect(writes).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", {name: "保存要求与设置"}));
  await waitFor(() => expect(screen.getByRole("button", {name: "保存要求与设置"})).toBeDisabled());
  expect(writes.map(item => item.url)).toEqual(["/api/v3/workspaces/workspace_scene"]);
  expect(writes[0].body.draft.requirements_edit.layers.composition.design.shot).toEqual({value: "全身", source: "user"});
  expect(screen.getByLabelText("负向提示词")).toHaveValue("original exclusions");
  view.unmount();
  await mount();
  expect(screen.getByRole("combobox", {name: "景别"})).toHaveValue("全身");
  expect(screen.getByRole("button", {name: "保存要求与设置"})).toBeDisabled();
  expect(screen.getByRole("button", {name: "更新提示词"})).toBeEnabled();
});

it("compiles an otherwise empty draft only after the explicit update action", async () => {
  workspace.draft.compiled = null; workspace.draft.compile_state = "missing";
  await mount();
  expect(screen.getByRole("button", {name: "更新提示词"})).toBeDisabled();
  fireEvent.change(screen.getByRole("combobox", {name: "氛围"}), {target: {value: "宁静日常"}});
  expect(screen.getByRole("button", {name: "更新提示词"})).toBeEnabled();
  expect(writes).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", {name: "更新提示词"}));
  await waitFor(() => expect(screen.getByLabelText("正向提示词")).toHaveValue("compiled scene intent"));
  expect(writes.map(item => item.url)).toEqual(["/api/v3/workspaces/workspace_scene", "/api/v3/workbench/turns"]);
  expect(writes[1].body).toMatchObject({revision: 2, delta: {text: ""}});
  expect(draft().requirements.layers.lighting.mood).toEqual({value: "宁静日常", source: "user"});
  expect(screen.getByLabelText("负向提示词")).toHaveValue("");
});

it("retains chosen intent and edited prompts when an explicit compilation fails", async () => {
  failCompilation = true;
  await mount();
  fireEvent.change(screen.getByRole("combobox", {name: "相机机位"}), {target: {value: "俯视"}});
  fireEvent.change(screen.getByLabelText("正向提示词"), {target: {value: "my edited scene"}});
  fireEvent.change(screen.getByLabelText("负向提示词"), {target: {value: "my exact exclusions"}});
  fireEvent.click(screen.getByRole("button", {name: "更新提示词"}));
  await screen.findByText("这次整理失败");
  expect(draft().requirements.layers.composition.design?.camera?.value).toBe("俯视");
  expect(screen.getByLabelText("正向提示词")).toHaveValue("my edited scene");
  expect(screen.getByLabelText("负向提示词")).toHaveValue("my exact exclusions");
  expect(writes[1].body.compiled).toEqual({positive: "my edited scene", negative: "my exact exclusions"});
  expect(writes.some(item => item.url.includes("/runs"))).toBe(false);
  expect(screen.getByRole("button", {name: "更新提示词"})).toBeEnabled();
});
