import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {consumeDirectImport, resetDirectImportForTests} from "../lib/directPrompt";
import {DirectPromptPage} from "./DirectPromptPage";

const preview = {
  positive_prompt: "maid, full body, black hair ribbons",
  negative_prompt: "low quality",
  positive_tokens: [
    {original: "maid", zh: "女仆", matched: true, canonical_tag: "maid", render_name: "maid", cn_name: "女仆", category_name: "general"},
    {original: "full body", zh: "全身", matched: true, canonical_tag: "full_body", render_name: "full body", cn_name: "全身", category_name: "general"},
    {original: "black hair ribbons", zh: "black hair ribbons", matched: false, canonical_tag: null, render_name: null, cn_name: null, category_name: null},
  ],
  negative_tokens: [
    {original: "low quality", zh: "低画质", matched: false, canonical_tag: null, render_name: null, cn_name: null, category_name: null},
  ],
  chinese_positive: "女仆，全身，black hair ribbons",
  chinese_negative: "低画质",
  matched_count: 2,
  unmatched_count: 2,
  translation_engine: "",
  algorithm: "direct-passthrough-v1",
};

beforeEach(() => {
  localStorage.clear();
  sessionStorage.setItem("anima-v3-session", "session-token");
  resetDirectImportForTests();
  vi.restoreAllMocks();
});

afterEach(() => {
  cleanup();
});

it("matches whole comma tokens and sends the Chinese gloss to the workbench", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(preview), {status: 200}));

  render(<MemoryRouter><DirectPromptPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("正向提示词（英文，原样发送）"), {target: {value: "maid, full body, black hair ribbons"}});
  fireEvent.change(screen.getByLabelText("反向提示词（可选）"), {target: {value: "low quality"}});
  fireEvent.click(screen.getByRole("button", {name: "匹配并回译中文"}));

  expect(await screen.findByText("女仆，全身，black hair ribbons")).toBeInTheDocument();
  expect(screen.getAllByText("未匹配，保留原词").length).toBeGreaterThan(0);
  const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
  expect(body.positive_prompt).toBe("maid, full body, black hair ribbons");

  fireEvent.click(screen.getByRole("button", {name: "送到工作台修改"}));
  expect(consumeDirectImport()?.positive_text).toBe("女仆，全身，black hair ribbons");
  expect(consumeDirectImport()?.excluded_text).toBe("低画质");
});

it("submits the original English prompt without compiling", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({
      items: [{
        remote_profile_id: "remote-1",
        remote_display_name: "测试云主机",
        workflow_profile_id: "workflow-1",
        workflow_display_name: "基础工作流",
        workflow_kind: "txt2img_basic",
        workflow_notes: "实验工作流说明",
        compatible_model_profiles: ["anima_aesthetic_v1"],
        host_fingerprint_ready: true,
        auth_type: "agent",
        private_key_passphrase_configured: false,
        default_recipe_id: "stable_baseline",
        generation_recipes: [{id: "stable_baseline", display_name: "稳定基线", objective: "baseline", parameters: {steps: 30, cfg: 4, sampler: "er_sde", scheduler: "simple"}, notes: "工作流模板基线。", evidence: "workflow_template"}],
        parameter_capabilities: {
          steps: {mode: "editable", value: 30, minimum: 30, maximum: 50, options: [], reason: "验证范围"},
          cfg: {mode: "editable", value: 4, minimum: 4, maximum: 5, options: [], reason: "验证范围"},
          sampler: {mode: "editable", value: "er_sde", options: ["er_sde", "euler"], reason: "风格取向"},
          scheduler: {mode: "fixed", value: "simple", options: [], reason: "工作流固定"},
        },
      }],
    }), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({id: "run-1", state: "draft"}), {status: 202}));

  render(<MemoryRouter><DirectPromptPage remoteEnabled /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("正向提示词（英文，原样发送）"), {target: {value: "1girl, finger to lips, clean delicate lineart"}});
  expect(await screen.findByRole("option", {name: "测试云主机"})).toBeInTheDocument();
  await waitFor(() => expect(screen.getByLabelText("云主机连接")).toHaveValue("remote-1"));
  expect(screen.getByText("实验工作流说明")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "按原文生图"}));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  expect(String(fetchMock.mock.calls[1][0])).toContain("/api/v3/direct-prompt/runs");
  const body = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
  expect(body.positive_prompt).toBe("1girl, finger to lips, clean delicate lineart");
  expect(body.settings).toMatchObject({preset_id: "stable_baseline", steps: 30, cfg: 4, sampler: "er_sde", scheduler: "simple"});
  expect(await screen.findByText(/已按原文提交远程队列/)).toBeInTheDocument();
});
