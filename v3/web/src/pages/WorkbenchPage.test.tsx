import {fireEvent, render, screen, waitFor} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {beforeEach, expect, it, vi} from "vitest";
import {WorkbenchPage} from "./WorkbenchPage";

const candidate = {
  id: "candidate_literal",
  lane: "literal",
  title: "高保真基准",
  positive_prompt: "score_7, maid, twintails",
  negative_prompt: "blonde hair",
  artists: [],
  tags: [
    {name: "maid", rendered: "maid", state: "locked", source: "alias", source_element_ids: ["e_positive_1"], reason: "别名映射", raw_score: null, display_score: null, removable: false},
    {name: "twintails", rendered: "twintails", state: "required", source: "exact", source_element_ids: ["e_positive_2"], reason: "中文精确映射", raw_score: null, display_score: null, removable: true},
  ],
  preserved_element_ids: ["e_positive_1", "e_positive_2"],
  unresolved_element_ids: [],
  warnings: [],
  score_breakdown: {mapped_elements: 2},
  versions: {data_pack: "pack-r1", algorithm: "literal-v1", templates: "renderer-v1", model_profile: "anima_base_v1"},
};

beforeEach(() => {
  sessionStorage.setItem("anima-v3-session", "session-token");
  vi.restoreAllMocks();
});

it("submits structured required, locked and excluded concepts and renders candidates", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    intent: {source_text: "女仆装，双马尾，不要 金发", graph: {elements: []}},
    candidates: [candidate],
    validation: {valid: true, error_count: 0},
    data_pack_id: "pack-r1",
  }), {status: 200}));

  render(<MemoryRouter><WorkbenchPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("希望画面中出现"), {target: {value: "!女仆，双马尾"}});
  fireEvent.change(screen.getByLabelText("明确排除"), {target: {value: "金发"}});
  fireEvent.click(screen.getByRole("button", {name: "生成候选"}));

  expect(await screen.findByRole("heading", {name: "高保真基准"})).toBeInTheDocument();
  expect(screen.getByText("score_7, maid, twintails")).toBeInTheDocument();
  expect(screen.getByText("安全校验通过")).toBeInTheDocument();

  const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
  expect(body.elements).toEqual([
    {id: "e_positive_1", text: "女仆", state: "locked"},
    {id: "e_positive_2", text: "双马尾", state: "required"},
    {id: "e_excluded_1", text: "金发", state: "excluded"},
  ]);
});

it("extracts natural language through V2 and generates candidates through V3", async () => {
  const intent = {
    source_text: "白发少女在雨夜街道撑伞。",
    source_language: "zh",
    translated_text: null,
    scene_plan_en: "A white-haired girl holds an umbrella on a rainy street",
    scene_negative_en: ["text"],
    graph: {
      elements: [
        {id: "e_ai_1", original_text: "白发", type: "appearance", state: "required", confidence: .85, notes: ["scope:少女"]},
        {id: "e_ai_2", original_text: "文字", type: "other", state: "excluded", confidence: .95, notes: []},
      ],
      edges: [],
    },
    warnings: [{code: "ai_extraction_requires_review", message: "请检查", element_ids: []}],
  };
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({
      intent,
      extraction: {summary_zh: "雨夜撑伞少女", people_count: 1, subject_mode: "character", content_rating: "safe", scene_type: "portrait", truncated_source: false},
      parser: {name: "V2 AI Extract · test", source: "v2_ai_extract"},
    }), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      intent,
      candidates: [{...candidate, id: "candidate_hybrid", lane: "hybrid", title: "画面计划混合表达", positive_prompt: "score_7, white hair. A white-haired girl holds an umbrella on a rainy street"}],
      validation: {valid: true, error_count: 0},
      data_pack_id: "pack-r1",
    }), {status: 200}));

  render(<MemoryRouter><WorkbenchPage naturalLanguageEnabled /></MemoryRouter>);
  fireEvent.click(screen.getByRole("tab", {name: "自然语言描述"}));
  fireEvent.change(screen.getByLabelText("描述你想生成的画面"), {target: {value: intent.source_text}});
  fireEvent.click(screen.getByRole("button", {name: "解析并生成候选"}));

  expect(await screen.findByText("已抽取 2 项画面事实")).toBeInTheDocument();
  expect(screen.getByRole("heading", {name: "画面计划混合表达"})).toBeInTheDocument();
  expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
    "/api/v3/intent/parse",
    "/api/v3/prompt-candidates",
  ]);
  const candidateRequest = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
  expect(candidateRequest.intent.scene_plan_en).toContain("white-haired girl");
  expect(candidateRequest.model_profile).toBe("anima_base_v1");
});

it("previews V2 local translation without compiling it into candidates", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    translated_text: "one girl, white hair",
    direction: "zh_en",
    engine: "内置离线基础翻译",
    local_only: true,
    model_ready: false,
  }), {status: 200}));

  render(<MemoryRouter><WorkbenchPage localTranslationEnabled /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("希望画面中出现"), {target: {value: "一个女孩，白发"}});
  fireEvent.click(screen.getByRole("button", {name: "翻译当前输入"}));

  expect(await screen.findByText("one girl, white hair")).toBeInTheDocument();
  expect(screen.getByText("独立工具，不参与 V3 候选编译")).toBeInTheDocument();
  expect(fetchMock.mock.calls[0][0]).toBe("/api/v3/translation");
});

it("copies the selected prompt", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    intent: {source_text: "女仆装", graph: {elements: []}},
    candidates: [candidate], validation: {valid: true, error_count: 0}, data_pack_id: "pack-r1",
  }), {status: 200}));
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {value: {writeText}, configurable: true});

  render(<MemoryRouter><WorkbenchPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("希望画面中出现"), {target: {value: "女仆装"}});
  fireEvent.click(screen.getByRole("button", {name: "生成候选"}));
  await screen.findByRole("heading", {name: "高保真基准"});
  fireEvent.click(screen.getAllByRole("button", {name: "复制"})[0]);

  await waitFor(() => expect(writeText).toHaveBeenCalledWith("score_7, maid, twintails"));
  expect(screen.getByRole("button", {name: "已复制"})).toBeInTheDocument();
});

it("undoes and restores draft edits", () => {
  render(<MemoryRouter><WorkbenchPage /></MemoryRouter>);
  const input = screen.getByLabelText("希望画面中出现");

  fireEvent.change(input, {target: {value: "女仆"}});
  expect(input).toHaveValue("女仆");
  fireEvent.click(screen.getByRole("button", {name: "撤销"}));
  expect(input).toHaveValue("");
  fireEvent.click(screen.getByRole("button", {name: "恢复"}));
  expect(input).toHaveValue("女仆");
});

it("saves and restores a revisioned workspace", async () => {
  const record = {
    id: "workspace_1",
    title: "女仆测试",
    draft: {positive_text: "女仆，双马尾", excluded_text: "金发", model_profile: "anima_base_v1"},
    revision: 1,
    created_at: "2026-08-26T00:00:00+00:00",
    updated_at: "2026-08-26T00:00:00+00:00",
  };
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify(record), {status: 201}))
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [record]}), {status: 200}));

  render(<MemoryRouter><WorkbenchPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("工作台名称"), {target: {value: "女仆测试"}});
  fireEvent.change(screen.getByLabelText("希望画面中出现"), {target: {value: "女仆，双马尾"}});
  fireEvent.change(screen.getByLabelText("明确排除"), {target: {value: "金发"}});
  fireEvent.click(screen.getByRole("button", {name: "保存工作台"}));

  expect(await screen.findByText("已保存 revision 1")).toBeInTheDocument();
  const saveBody = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
  expect(saveBody.draft.positive_text).toBe("女仆，双马尾");

  fireEvent.click(screen.getByRole("button", {name: "打开"}));
  fireEvent.click(await screen.findByRole("button", {name: /女仆测试/}));
  expect(screen.getByLabelText("希望画面中出现")).toHaveValue("女仆，双马尾");
  expect(screen.getByText("已打开 revision 1")).toBeInTheDocument();
});

it("persists the last validated candidate snapshot with the workspace", async () => {
  const generated = {
    intent: {source_text: "女仆", source_language: "zh", translated_text: null, scene_plan_en: null, scene_negative_en: [], graph: {elements: [], edges: []}, warnings: []},
    candidates: [candidate],
    validation: {valid: true, candidate_reports: [{candidate_id: "candidate_literal", valid: true, issues: []}], issues: []},
    data_pack_id: "pack-r1",
  };
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify(generated), {status: 200}))
    .mockImplementationOnce(async (_input, init) => new Response(JSON.stringify({
      id: "workspace_snapshot", title: "候选快照", draft: JSON.parse(String(init?.body)).draft,
      candidate_snapshot: generated, revision: 1,
      created_at: "2026-08-26T00:00:00+00:00", updated_at: "2026-08-26T00:00:00+00:00",
    }), {status: 201}));

  render(<MemoryRouter><WorkbenchPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("工作台名称"), {target: {value: "候选快照"}});
  fireEvent.change(screen.getByLabelText("希望画面中出现"), {target: {value: "女仆"}});
  fireEvent.click(screen.getByRole("button", {name: "生成候选"}));
  await screen.findByRole("heading", {name: "高保真基准"});
  fireEvent.click(screen.getByRole("button", {name: "保存工作台"}));
  await screen.findByText("已保存 revision 1");

  const saveRequest = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
  expect(saveRequest.candidate_snapshot.candidates[0].positive_prompt).toBe("score_7, maid, twintails");
  expect(saveRequest.candidate_snapshot.data_pack_id).toBe("pack-r1");
});

it("submits a validated candidate to a compatible reused V2 target", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [{
      remote_profile_id: "remote-1",
      remote_display_name: "测试云主机",
      workflow_profile_id: "workflow-1",
      workflow_display_name: "ANIMA Base",
      workflow_kind: "txt2img_basic",
      compatible_model_profiles: ["anima_base_v1"],
      host_fingerprint_ready: true,
      auth_type: "agent",
      private_key_passphrase_configured: false,
    }]}), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      intent: {source_text: "女仆", source_language: "zh", graph: {elements: []}},
      candidates: [candidate], validation: {valid: true, error_count: 0}, data_pack_id: "pack-r1",
    }), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      id: "run-1", state: "draft", progress: 0, available_actions: ["cancel_queued"],
    }), {status: 202}));

  render(<MemoryRouter><WorkbenchPage remoteEnabled /></MemoryRouter>);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  fireEvent.change(screen.getByLabelText("希望画面中出现"), {target: {value: "女仆"}});
  fireEvent.click(screen.getByRole("button", {name: "生成候选"}));
  await screen.findByRole("heading", {name: "高保真基准"});
  fireEvent.click(screen.getByRole("button", {name: "远程生图"}));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  const request = JSON.parse(String(fetchMock.mock.calls[2][1]?.body));
  expect(request.remote_profile_id).toBe("remote-1");
  expect(request.workflow_profile_id).toBe("workflow-1");
  expect(request.candidate.id).toBe("candidate_literal");
  expect(new Headers(fetchMock.mock.calls[2][1]?.headers).get("Idempotency-Key")).toMatch(/^web-/);
});

it("sends an encrypted-key passphrase separately before the generation request", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [{
      remote_profile_id: "remote-key",
      remote_display_name: "私钥云主机",
      workflow_profile_id: "workflow-1",
      workflow_display_name: "ANIMA Base",
      workflow_kind: "txt2img_basic",
      compatible_model_profiles: ["anima_base_v1"],
      host_fingerprint_ready: true,
      auth_type: "private_key",
      private_key_passphrase_configured: false,
    }]}), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      intent: {source_text: "女仆", source_language: "zh", graph: {elements: []}},
      candidates: [candidate], validation: {valid: true, error_count: 0}, data_pack_id: "pack-r1",
    }), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({configured: true}), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      id: "run-key", state: "draft", progress: 0, available_actions: ["cancel_queued"],
    }), {status: 202}));

  render(<MemoryRouter><WorkbenchPage remoteEnabled /></MemoryRouter>);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  fireEvent.change(screen.getByLabelText("希望画面中出现"), {target: {value: "女仆"}});
  fireEvent.click(screen.getByRole("button", {name: "生成候选"}));
  await screen.findByRole("heading", {name: "高保真基准"});
  fireEvent.change(screen.getByLabelText("私钥口令（可选，仅本次运行内存）"), {target: {value: "memory-secret"}});
  fireEvent.click(screen.getByRole("button", {name: "远程生图"}));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
  expect(fetchMock.mock.calls[2][0]).toBe("/api/v3/generation-credentials/private-key-passphrase");
  expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toEqual({remote_profile_id: "remote-key", passphrase: "memory-secret"});
  expect(fetchMock.mock.calls[3][0]).toBe("/api/v3/generation-runs");
  expect(String(fetchMock.mock.calls[3][1]?.body)).not.toContain("memory-secret");
});
