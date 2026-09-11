import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {DirectPromptPage} from "./DirectPromptPage";
import {WorkbenchPage} from "./WorkbenchPage";

beforeEach(() => {
  localStorage.clear(); sessionStorage.setItem("anima-v3-session", "test");
  const targets = [
    ["anima_aesthetic_v1_0", "stable_baseline", 30, 4, "er_sde", "simple"],
    ["anima_aesthetic_v1_1", "stable_baseline", 35, 4.5, "euler", "normal"],
    ["anima_turbo_v1_1", "turbo_v11_baseline", 10, 1, "er_sde", "simple"],
    ["animayume_v1_0_final", "yume_creator", 30, 5.5, "euler_ancestral", "normal"],
  ].map(([model, recipe, steps, cfg, sampler, scheduler]) => ({
    remote_profile_id: "cloud", remote_display_name: "cloud", workflow_profile_id: model,
    workflow_display_name: model, compatible_model_profiles: [model], workflow_kind: "txt2img_basic",
    availability: "ready", host_fingerprint_ready: true, default_recipe_id: recipe,
    generation_recipes: [{id: recipe, display_name: recipe, parameters: {steps,cfg,sampler,scheduler}}],
  }));
  vi.spyOn(globalThis, "fetch").mockImplementation(async input => new Response(JSON.stringify(
    String(input).includes("generation-targets") ? {items:targets} :
    String(input).includes("llm/settings") ? {services:[],current:{service:"",model:""}} : {items:[]}
  )));
});
afterEach(() => {cleanup(); vi.restoreAllMocks();});

it.each([["direct", DirectPromptPage], ["classic", WorkbenchPage]] as const)("changes model-specific sampling in %s", async (_name, Page) => {
  render(<MemoryRouter><Page remoteEnabled naturalLanguageEnabled /></MemoryRouter>);
  await waitFor(() => expect(screen.getByLabelText("远程工作流")).toHaveValue("anima_aesthetic_v1_1"));
  fireEvent.change(screen.getByLabelText("模型配置"), {target:{value:"anima_turbo_v1_1"}});
  await waitFor(() => expect(screen.getByLabelText("CFG")).toHaveValue(1));
  expect(screen.getByLabelText("采样步数 Steps")).toHaveValue(10);
  fireEvent.change(screen.getByLabelText("模型配置"), {target:{value:"anima_aesthetic_v1_1"}});
  await waitFor(() => expect(screen.getByLabelText("CFG")).toHaveValue(4.5));
  expect(screen.getByLabelText("采样步数 Steps")).toHaveValue(35);
  fireEvent.change(screen.getByLabelText("模型配置"), {target:{value:"anima_aesthetic_v1_0"}});
  await waitFor(() => expect(screen.getByLabelText("远程工作流")).toHaveValue("anima_aesthetic_v1_0"));
  expect(screen.getByLabelText("CFG")).toHaveValue(4);
  expect(Array.from((screen.getByLabelText("远程工作流") as HTMLSelectElement).options).some(o => o.value === "anima_aesthetic_v1_1")).toBe(false);
  // Manual parameters belong to the current model too.
  fireEvent.change(screen.getByLabelText("CFG"), {target:{value:"7"}});
  fireEvent.change(screen.getByLabelText("模型配置"), {target:{value:"animayume_v1_0_final"}});
  await waitFor(() => expect(screen.getByLabelText("CFG")).toHaveValue(5.5));
  expect(screen.getByLabelText("采样步数 Steps")).toHaveValue(30);
});
