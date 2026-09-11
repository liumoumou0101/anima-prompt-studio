import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {WorkbenchPage} from "./WorkbenchPage";
import {LlmSettingsPanel} from "../components/LlmSettingsPanel";
import {resetDirectImportForTests} from "../lib/directPrompt";

const settings = {services: [{id: "sample", name: "测试服务", type: "openai_compatible", base_url: "https://sample.example/v1", api_key_exists: true, api_key_masked: "***", llm_models: [{name: "sample-model", is_default: true}]}], current: {service: "sample", model: "sample-model"}};
const target = {
  remote_profile_id: "cloud", remote_display_name: "测试云主机", workflow_profile_id: "workflow", workflow_display_name: "测试工作流",
  workflow_kind: "txt2img_basic", compatible_model_profiles: ["anima_aesthetic_v1_1"], host_fingerprint_ready: true,
  auth_type: "agent", private_key_passphrase_configured: false, availability: "ready",
  default_recipe_id: "stable_baseline", generation_recipes: [{id: "stable_baseline", display_name: "稳定基准", objective: "baseline", parameters: {steps: 30, cfg: 4, sampler: "er_sde", scheduler: "simple"}, notes: "test", evidence: "workflow_template"}],
  parameter_capabilities: {
    steps: {mode: "editable", value: 30, minimum: 1, maximum: 100, options: [], reason: "测试"},
    cfg: {mode: "editable", value: 4, minimum: 1, maximum: 10, options: [], reason: "测试"},
    sampler: {mode: "editable", value: "er_sde", options: ["er_sde", "euler"], reason: "测试"},
    scheduler: {mode: "fixed", value: "simple", options: [], reason: "固定"},
  },
};
let requests: {url: string; body: Record<string, unknown>}[];
beforeEach(() => {
  localStorage.clear(); sessionStorage.setItem("anima-v3-session", "test-session"); resetDirectImportForTests();
  requests = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.body) requests.push({url, body: JSON.parse(String(init.body))});
    const data = url.endsWith("/llm/settings") ? settings : url.endsWith("/llm/test") ? {ok: true, message: "连接可用"}
      : url.endsWith("/workbench/prompt") ? {positive: "A white crane bird", negative: "text", warnings: ["请核对鸟类"], rule_id: "faithful"}
      : url.endsWith("/generation-targets") ? {items: [target]} : {items: []};
    return new Response(JSON.stringify(data), {status: 200});
  });
});
afterEach(() => {cleanup(); vi.restoreAllMocks();});

it("supports editable API URL/model and explicitly saves before the paid connection test", async () => {
  render(<LlmSettingsPanel />);
  await screen.findByLabelText("服务商");
  fireEvent.change(screen.getByLabelText("模型名称"), {target: {value: "custom-model"}});
  fireEvent.change(screen.getByLabelText("API 地址（Base URL）"), {target: {value: "https://custom.example/v1"}});
  fireEvent.change(screen.getByLabelText("API Key"), {target: {value: "fake-key"}});
  fireEvent.click(screen.getByText("保存并测试连接"));
  await screen.findByText("连接可用");
  expect(requests[0].body).toMatchObject({model_name: "custom-model", base_url: "https://custom.example/v1", api_key: "fake-key"});
  expect(requests[1]).toEqual({url: "/api/v3/llm/test", body: {}});
});

it("clears unsaved credentials when switching providers", async () => {
  render(<LlmSettingsPanel />);
  await screen.findByLabelText("API Key");
  fireEvent.change(screen.getByLabelText("API Key"), {target: {value: "provider-a-key"}});
  fireEvent.change(screen.getByLabelText("服务商"), {target: {value: "custom"}});
  expect(screen.getByLabelText("API Key")).toHaveValue("");
  expect(screen.getByLabelText("模型名称")).toHaveValue("");
});

it("sends exclusions, submits reviewed prompts with workflow/settings and blocks stale output", async () => {
  render(<MemoryRouter><WorkbenchPage remoteEnabled /></MemoryRouter>);
  await screen.findByLabelText("服务商");
  await waitFor(() => expect(screen.getByLabelText("远程工作流")).toHaveValue("workflow"));
  fireEvent.change(screen.getByLabelText("采样步数 Steps"), {target: {value: "37"}});
  fireEvent.change(screen.getByLabelText("CFG"), {target: {value: "4.5"}});
  fireEvent.change(screen.getByLabelText("Seed"), {target: {value: "20260907"}});
  fireEvent.change(screen.getByLabelText("采样器 Sampler"), {target: {value: "euler"}});
  fireEvent.change(screen.getByLabelText("描述你想生成的画面"), {target: {value: "水墨白鹤"}});
  fireEvent.change(screen.getByLabelText("明确排除（可选）"), {target: {value: "文字"}});
  fireEvent.click(screen.getByText("生成提示词（LLM 小助手内核）"));
  await screen.findByLabelText("最终负向提示词");
  expect(requests.find((r) => r.url.endsWith("/workbench/prompt"))?.body).toEqual({source_text: "水墨白鹤", excluded_text: "文字", mode: "faithful"});
  fireEvent.change(screen.getByLabelText("最终正向提示词"), {target: {value: "An ink painting of a white crane bird"}});
  fireEvent.change(screen.getByLabelText("最终负向提示词"), {target: {value: "text, watermark"}});
  fireEvent.click(screen.getByText("用此提示词远程生图"));
  await waitFor(() => expect(requests.some((r) => r.url.endsWith("/direct-prompt/runs"))).toBe(true));
  const body = requests.find((r) => r.url.endsWith("/direct-prompt/runs"))!.body;
  expect(body).toMatchObject({positive_prompt: "An ink painting of a white crane bird", negative_prompt: "text, watermark", remote_profile_id: "cloud", workflow_profile_id: "workflow", model_profile: "anima_aesthetic_v1_1"});
  expect(body.settings).toMatchObject({steps: 37, cfg: 4.5, seed: 20260907, sampler: "euler", scheduler: "simple"});
  fireEvent.change(screen.getByLabelText("明确排除（可选）"), {target: {value: "人物"}});
  expect(screen.getByText("用此提示词远程生图")).toBeDisabled();
  expect(screen.getByText(/输入、排除项或处理方式已改变/)).toBeInTheDocument();
});

it("uses expansion only when explicitly selected", async () => {
  render(<MemoryRouter><WorkbenchPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("描述你想生成的画面"), {target: {value: "花园"}});
  fireEvent.change(screen.getByLabelText("提示词处理方式"), {target: {value: "expand"}});
  fireEvent.click(screen.getByText("生成提示词（LLM 小助手内核）"));
  await screen.findByLabelText("最终正向提示词");
  expect(requests.find((r) => r.url.endsWith("/workbench/prompt"))?.body.mode).toBe("expand");
  fireEvent.change(screen.getByLabelText("最终正向提示词"), {target: {value: ""}});
  expect(screen.getByLabelText("最终正向提示词")).toBeInTheDocument();
});
