import {cleanup, fireEvent, render, screen, waitFor, within} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import type {PromptCandidate, SceneDraft, WorkbenchResponse} from "../lib/types";
import {resetDirectImportForTests, storeDirectImport} from "../lib/directPrompt";
import {WorkbenchPage} from "./WorkbenchPage";

const candidate: PromptCandidate = {
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

const baseRecipeContract = {
  default_recipe_id: "stable_baseline",
  generation_recipes: [
    {id: "stable_baseline", display_name: "稳定基线", objective: "baseline", parameters: {steps: 30, cfg: 4, sampler: "er_sde", scheduler: "simple"}, notes: "工作流模板基线。", evidence: "workflow_template"},
    {id: "detail_study", display_name: "细节实验", objective: "detail_study", parameters: {steps: 40, cfg: 4.5, sampler: "er_sde", scheduler: "simple"}, notes: "固定 Seed 对照实验。", evidence: "experimental"},
  ],
  parameter_capabilities: {
    steps: {mode: "editable", value: 30, minimum: 30, maximum: 50, options: [], reason: "验证范围"},
    cfg: {mode: "editable", value: 4, minimum: 4, maximum: 5, options: [], reason: "验证范围"},
    sampler: {mode: "editable", value: "er_sde", options: ["er_sde", "euler", "dpmpp_2m_sde_gpu"], reason: "风格取向"},
    scheduler: {mode: "fixed", value: "simple", options: [], reason: "工作流固定"},
  },
};

beforeEach(() => {
  localStorage.clear();
  sessionStorage.setItem("anima-v3-session", "session-token");
  resetDirectImportForTests();
  vi.restoreAllMocks();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

it("imports selected supermarket tags into the structured draft", () => {
  render(<MemoryRouter initialEntries={["/workbench?tag=maid&tag=twintails&tag=maid"]}><WorkbenchPage /></MemoryRouter>);

  expect(screen.getByLabelText("希望画面中出现")).toHaveValue("maid，twintails");
  expect(screen.getByText("2 个正向概念")).toBeInTheDocument();
});

it("imports a Chinese gloss from the English passthrough page", () => {
  storeDirectImport({
    positive_text: "女仆，全身，看向观众",
    excluded_text: "低画质",
    english_positive: "maid, full body, looking at viewer",
    english_negative: "low quality",
  });
  render(<MemoryRouter initialEntries={["/workbench?from=direct"]}><WorkbenchPage /></MemoryRouter>);

  expect(screen.getByLabelText("希望画面中出现")).toHaveValue("女仆，全身，看向观众");
  expect(screen.getByLabelText("明确排除")).toHaveValue("低画质");
  expect(screen.getByText(/已从英文直出导入中文对照/)).toBeInTheDocument();
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
  expect(screen.getByText("结构检查通过")).toBeInTheDocument();
  expect(screen.getByText(/语义仍需人工确认/)).toBeInTheDocument();

  const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
  expect(body.elements).toEqual([
    {id: "e_positive_1", text: "女仆", state: "locked"},
    {id: "e_positive_2", text: "双马尾", state: "required"},
    {id: "e_excluded_1", text: "金发", state: "excluded"},
  ]);
});

it("compiles natural language through local translation without calling the V2 AI extractor", async () => {
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
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    intent,
    candidates: [{...candidate, id: "candidate_hybrid", lane: "hybrid", title: "画面计划混合表达", positive_prompt: "score_7, white hair. A white-haired girl holds an umbrella on a rainy street"}],
    validation: {valid: true, error_count: 0},
    data_pack_id: "pack-r1",
    local_translation: {translated_text: "A white-haired girl holds an umbrella on a rainy street", engine: "内置离线基础翻译", local_only: true},
  }), {status: 200}));

  render(<MemoryRouter><WorkbenchPage naturalLanguageEnabled /></MemoryRouter>);
  fireEvent.click(screen.getByRole("tab", {name: "自然语言描述"}));
  fireEvent.change(screen.getByLabelText("描述你想生成的画面"), {target: {value: intent.source_text}});
  fireEvent.click(screen.getByRole("button", {name: "编译并生成候选"}));

  expect(await screen.findByText("已整理 2 项画面证据")).toBeInTheDocument();
  expect(screen.getByRole("heading", {name: "画面计划混合表达"})).toBeInTheDocument();
  expect(fetchMock.mock.calls.map((call) => call[0])).toEqual(["/api/v3/local-natural/candidates"]);
  const candidateRequest = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
  expect(candidateRequest.source_text).toBe(intent.source_text);
  expect(candidateRequest.model_profile).toBe("anima_aesthetic_v1");
});

it("keeps local mapping suggestions out of candidates until the user selects one", async () => {
  const sceneDraft = {
    source_text: "一位未知角色站在雨中",
    translated_text: "An unknown character stands in the rain",
    confirmed: [],
    exclusions: [],
    suggestions: [{id: "s_local_translation_1", text: "rain", canonical_tag: "rain", source: "translation_exact", reason: "译文精确命中", source_start: null, source_end: null}],
    ambiguous: [{text: "雨", options: [
      {canonical_tag: "rain", render_name: "rain", cn_name: "雨", match_kind: "cn_name", post_count: 100},
      {canonical_tag: "rainy_day", render_name: "rainy day", cn_name: "雨天", match_kind: "cn_term", post_count: 50},
    ]}],
    unresolved: [{id: "u_local_scene", text: "一位未知角色站在雨中", canonical_tag: null, source: "unresolved", reason: "保留译文", source_start: null, source_end: null}],
    risk_notes: ["动作和构图仍需人工检查。"],
  } as const;
  const first = {
    intent: {source_text: sceneDraft.source_text, source_language: "zh", translated_text: sceneDraft.translated_text, scene_plan_en: sceneDraft.translated_text, scene_negative_en: [], graph: {elements: [{id: "e_local_scene", original_text: "local scene description", type: "scene", state: "required", confidence: 1, notes: ["local_prose_baseline"]}], edges: []}, warnings: []},
    candidates: [{...candidate, positive_prompt: sceneDraft.translated_text, tags: [], preserved_element_ids: ["e_local_scene"], score_breakdown: {mapped_elements: 0, prose_baseline: 1}}],
    validation: {valid: true, error_count: 0}, data_pack_id: "pack-r1", scene_draft: sceneDraft, tag_suggestions: [],
    local_translation: {translated_text: sceneDraft.translated_text, engine: "内置离线基础翻译", local_only: true},
  };
  const second = {
    ...first,
    intent: {...first.intent, graph: {elements: [{id: "e_local_selected_1", original_text: "rain", type: "other", state: "user_selected", confidence: 1, notes: []}], edges: []}},
    candidates: [{...candidate, positive_prompt: "rain", tags: [{name: "rain", rendered: "rain", state: "user_selected", source: "exact", source_element_ids: ["e_local_selected_1"], reason: "用户确认", raw_score: null, display_score: null, removable: true}], preserved_element_ids: ["e_local_selected_1"]}],
    scene_draft: {...sceneDraft, confirmed: [{id: "e_local_selected_1", text: "rain", canonical_tag: "rain", source: "user_selected", reason: "用户从建议池确认加入", source_start: null, source_end: null}], suggestions: []},
    local_translation: {translated_text: sceneDraft.translated_text, engine: "当前工作台译文", local_only: true},
  };
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify(first), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify(second), {status: 200}));

  render(<MemoryRouter><WorkbenchPage naturalLanguageEnabled /></MemoryRouter>);
  fireEvent.click(screen.getByRole("tab", {name: "自然语言描述"}));
  fireEvent.change(screen.getByLabelText("描述你想生成的画面"), {target: {value: sceneDraft.source_text}});
  fireEvent.click(screen.getByRole("button", {name: "编译并生成候选"}));

  const review = await screen.findByRole("region", {name: "Scene Draft"});
  expect(review).toBeInTheDocument();
  expect(screen.getAllByRole("button", {name: /^雨rain$/})).toHaveLength(1);
    expect(within(review).getByText(sceneDraft.translated_text)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: /^雨rain$/}));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  const recompileRequest = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
  expect(recompileRequest).toEqual({
    source_text: sceneDraft.source_text,
    excluded_text: "",
    translated_text: sceneDraft.translated_text,
    model_profile: "anima_aesthetic_v1",
    selected_tags: ["rain"],
  });
  expect(await screen.findByText("用户从建议池确认加入")).toBeInTheDocument();
});

it("keeps character identity matches out of candidates until the user confirms the English tag", async () => {
  const sceneDraft = {
    source_text: "博丽灵梦穿女仆装",
    translated_text: "Hakurei Reimu wears a maid outfit",
    confirmed: [{id: "e_local_confirmed_1", text: "女仆", canonical_tag: "maid", source: "source_exact", fact_type: "clothing", reason: "中文原文精确匹配", source_start: 4, source_end: 6}],
    exclusions: [],
    suggestions: [{id: "s_local_identity_1", text: "博丽灵梦", canonical_tag: "hakurei_reimu", source: "identity_candidate", fact_type: "character", reason: "匹配到角色或作品标签", source_start: 0, source_end: 4, cn_name: "博丽灵梦"}],
    unresolved: [],
    risk_notes: ["发现疑似角色或作品标签，不会自动加入提示词。"],
  } as const;
  const first = {
    intent: {source_text: sceneDraft.source_text, source_language: "zh", graph: {elements: []}},
    candidates: [{...candidate, positive_prompt: "maid", tags: [{name: "maid", rendered: "maid", state: "required", source: "exact", source_element_ids: ["e_local_confirmed_1"], reason: "中文精确映射", raw_score: null, display_score: null, removable: true}]}],
    validation: {valid: true, error_count: 0},
    data_pack_id: "pack-r1",
    scene_draft: sceneDraft,
    tag_suggestions: [],
    local_translation: {translated_text: sceneDraft.translated_text, engine: "内置离线基础翻译", local_only: true},
  };
  const second = {
    ...first,
    candidates: [{...candidate, positive_prompt: "maid, hakurei reimu", tags: [
      {name: "maid", rendered: "maid", state: "required", source: "exact", source_element_ids: ["e_local_confirmed_1"], reason: "中文精确映射", raw_score: null, display_score: null, removable: true},
      {name: "hakurei_reimu", rendered: "hakurei reimu", state: "user_selected", source: "exact", source_element_ids: ["e_local_selected_1"], reason: "用户确认", raw_score: null, display_score: null, removable: true},
    ]}],
    scene_draft: {
      ...sceneDraft,
      confirmed: [
        ...sceneDraft.confirmed,
        {id: "e_local_selected_1", text: "博丽灵梦", canonical_tag: "hakurei_reimu", source: "user_selected", fact_type: "character", reason: "用户从建议池确认加入", source_start: null, source_end: null, cn_name: "博丽灵梦"},
      ],
      suggestions: [],
    },
  };
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify(first), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify(second), {status: 200}));

  render(<MemoryRouter><WorkbenchPage naturalLanguageEnabled /></MemoryRouter>);
  fireEvent.click(screen.getByRole("tab", {name: "自然语言描述"}));
  fireEvent.change(screen.getByLabelText("描述你想生成的画面"), {target: {value: sceneDraft.source_text}});
  fireEvent.click(screen.getByRole("button", {name: "编译并生成候选"}));

  expect(await screen.findByText("疑似角色/作品，需确认")).toBeInTheDocument();
  expect(screen.getByRole("button", {name: /博丽灵梦/})).toBeInTheDocument();
  expect(screen.queryByText("maid, hakurei reimu")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: /博丽灵梦/}));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  const recompileRequest = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
  expect(recompileRequest.selected_tags).toEqual(["hakurei_reimu"]);
  expect(await screen.findByText("maid, hakurei reimu")).toBeInTheDocument();
});

it("keeps excluded character identity out of the negative prompt until the user confirms the English tag", async () => {
  const sceneDraft = {
    source_text: "女仆，不要博丽灵梦",
    translated_text: "A maid",
    confirmed: [{id: "e_local_confirmed_1", text: "女仆", canonical_tag: "maid", source: "source_exact" as const, fact_type: "clothing" as const, reason: "中文原文精确匹配", source_start: 0, source_end: 2}],
    exclusions: [],
    suggestions: [{id: "s_local_identity_exclusion_1", text: "博丽灵梦", canonical_tag: "hakurei_reimu", source: "identity_exclusion" as const, fact_type: "character" as const, reason: "匹配到角色或作品标签", source_start: 3, source_end: 7, cn_name: "博丽灵梦"}],
    unresolved: [],
    risk_notes: ["发现要从画面中排除的疑似角色或作品，不会自动写入负向提示词。"],
  };
  const first = {
    intent: {source_text: sceneDraft.source_text, source_language: "zh", graph: {elements: []}},
    candidates: [{...candidate, positive_prompt: "maid", negative_prompt: ""}],
    validation: {valid: true, error_count: 0},
    data_pack_id: "pack-r1",
    scene_draft: sceneDraft,
    tag_suggestions: [],
    local_translation: {translated_text: sceneDraft.translated_text, engine: "内置离线基础翻译", local_only: true},
  };
  const second = {
    ...first,
    candidates: [{...candidate, positive_prompt: "maid", negative_prompt: "hakurei reimu"}],
    scene_draft: {
      ...sceneDraft,
      exclusions: [{id: "e_local_excluded_1", text: "hakurei_reimu", canonical_tag: "hakurei_reimu", source: "source_excluded" as const, fact_type: "character" as const, reason: "用户明确排除", source_start: null, source_end: null, cn_name: "博丽灵梦"}],
      suggestions: [],
    },
  };
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify(first), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify(second), {status: 200}));

  render(<MemoryRouter><WorkbenchPage naturalLanguageEnabled /></MemoryRouter>);
  fireEvent.click(screen.getByRole("tab", {name: "自然语言描述"}));
  fireEvent.change(screen.getByLabelText("描述你想生成的画面"), {target: {value: sceneDraft.source_text}});
  fireEvent.click(screen.getByRole("button", {name: "编译并生成候选"}));

  expect(await screen.findByText("疑似要排除的角色/作品，需确认")).toBeInTheDocument();
  expect(screen.queryByText("Negative")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: /博丽灵梦/}));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  const recompileRequest = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
  expect(recompileRequest.excluded_text).toBe("hakurei_reimu");
  expect(recompileRequest.selected_tags).toEqual([]);
  expect(await screen.findByText("Negative")).toBeInTheDocument();
  const review = screen.getByRole("region", {name: "Scene Draft"});
  expect(within(review).getByText("明确排除")).toBeInTheDocument();
  expect(within(review).getByText("博丽灵梦")).toBeInTheDocument();
});

it("applies a composition preset to chips without replacing the page", async () => {
  const palette = [
    {axis: "shot" as const, canonical_tag: "cowboy_shot", label_zh: "膝上", render_name: "cowboy shot", state: "available" as const, side: "positive" as const, reason: "膝上大约裁到大腿，是改框最明显的景别。"},
    {axis: "gaze" as const, canonical_tag: "looking_at_viewer", label_zh: "看镜头", render_name: "looking at viewer", state: "available" as const, side: "positive" as const, reason: "模型常见默认。"},
    {axis: "gaze" as const, canonical_tag: "looking_away", label_zh: "看向画外", render_name: "looking away", state: "available" as const, side: "positive" as const, reason: "把视线拧开。"},
  ];
  const presets = [
    {id: "none", label_zh: "不套预设", tags: [] as string[], note: "不写入构图标签。未指定视线时模型仍可能看镜头。", group_zh: "基础"},
    {id: "cowboy_viewer", label_zh: "膝上立绘", tags: ["cowboy_shot", "looking_at_viewer"], note: "常见人物肖像：膝上并看镜头。", group_zh: "常用立绘"},
  ];
  const first = {
    intent: {source_text: "女仆", source_language: "zh", graph: {elements: []}},
    candidates: [{...candidate, positive_prompt: "maid"}],
    validation: {valid: true, error_count: 0},
    data_pack_id: "pack-r1",
    scene_draft: {
      source_text: "女仆",
      translated_text: "A maid",
      confirmed: [{id: "e_maid", text: "女仆", canonical_tag: "maid", source: "source_exact", fact_type: "clothing", reason: "中文原文精确匹配", source_start: 0, source_end: 2}],
      exclusions: [],
      suggestions: [],
      unresolved: [],
      composition_palette: palette,
      composition_presets: presets,
      risk_notes: [],
    },
    tag_suggestions: [],
    local_translation: {translated_text: "A maid", engine: "内置离线基础翻译", local_only: true},
  };
  const second = {
    ...first,
    candidates: [{...candidate, positive_prompt: "maid, cowboy shot, looking at viewer"}],
    scene_draft: {
      ...first.scene_draft,
      composition_palette: palette.map((item) => item.canonical_tag === "cowboy_shot" || item.canonical_tag === "looking_at_viewer" ? {...item, state: "selected" as const} : item),
    },
  };
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify(first), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify(second), {status: 200}));

  render(<MemoryRouter><WorkbenchPage naturalLanguageEnabled /></MemoryRouter>);
  fireEvent.click(screen.getByRole("tab", {name: "自然语言描述"}));
  fireEvent.change(screen.getByLabelText("描述你想生成的画面"), {target: {value: "女仆"}});
  fireEvent.click(screen.getByRole("button", {name: "编译并生成候选"}));

  const review = await screen.findByRole("region", {name: "Scene Draft"});
  const presetSelect = within(review).getByLabelText("快速构图") as HTMLSelectElement;
  expect(presetSelect).toHaveValue("none");
  fireEvent.change(presetSelect, {target: {value: "cowboy_viewer"}});
  expect(within(review).getByRole("button", {name: /膝上/})).toHaveAttribute("aria-pressed", "true");
  expect(within(review).getByRole("button", {name: /看镜头/})).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("heading", {name: "高保真基准"})).toBeInTheDocument();
  expect(screen.queryByText("正在映射标签、计算推荐并验证候选…")).not.toBeInTheDocument();
  expect(presetSelect).toHaveValue("cowboy_viewer");

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2), {timeout: 1500});
  expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body)).selected_tags).toEqual(["cowboy_shot", "looking_at_viewer"]);
});

it("lets the user pick composition chips immediately without replacing the page", async () => {
  const palette = [
    {axis: "shot" as const, canonical_tag: "cowboy_shot", label_zh: "膝上", render_name: "cowboy shot", state: "available" as const, side: "positive" as const, reason: "膝上大约裁到大腿，是改框最明显的景别。", notes: {available: "膝上大约裁到大腿，是改框最明显的景别。", selected: "已选用膝上。裁切大约到大腿，会明显改框，不一定是全身。"}},
    {axis: "gaze" as const, canonical_tag: "looking_away", label_zh: "看向画外", render_name: "looking away", state: "suggested" as const, side: "positive" as const, reason: "仅把「看镜头」放进负向通常打不破先验，请点选「看向画外」。", notes: {suggested: "仅把「看镜头」放进负向通常打不破先验，请点选「看向画外」。", selected: "已选用看向画外，并排除 looking at viewer。仅放进负向通常打不破看镜头。"}},
    {axis: "gaze" as const, canonical_tag: "looking_at_viewer", label_zh: "看镜头", render_name: "looking at viewer", state: "excluded" as const, side: "excluded" as const, reason: "已排除看镜头，写入负向。仅负向通常不够，请再点选「看向画外」。"},
  ];
  const first = {
    intent: {source_text: "女仆，不要看镜头", source_language: "zh", graph: {elements: []}},
    candidates: [{...candidate, positive_prompt: "maid", negative_prompt: "looking at viewer"}],
    validation: {valid: true, error_count: 0},
    data_pack_id: "pack-r1",
    scene_draft: {
      source_text: "女仆，不要看镜头",
      translated_text: "A maid",
      confirmed: [{id: "e_maid", text: "女仆", canonical_tag: "maid", source: "source_exact", fact_type: "clothing", reason: "中文原文精确匹配", source_start: 0, source_end: 2}],
      exclusions: [{id: "e_gaze", text: "看镜头", canonical_tag: "looking_at_viewer", source: "source_excluded", fact_type: "composition", reason: "用户明确排除", source_start: 3, source_end: 6}],
      suggestions: [],
      unresolved: [],
      composition_palette: palette,
      risk_notes: ["仅把「看镜头」放进负向通常打不破先验，请点选「看向画外」。"],
    },
    tag_suggestions: [],
    local_translation: {translated_text: "A maid", engine: "内置离线基础翻译", local_only: true},
  };
  const secondPalette = palette.map((item) => {
    if (item.canonical_tag === "looking_away") return {...item, state: "selected" as const, reason: item.notes?.selected || item.reason};
    if (item.canonical_tag === "cowboy_shot") return {...item, state: "selected" as const, reason: item.notes?.selected || item.reason};
    return item;
  });
  const second = {
    ...first,
    candidates: [{...candidate, positive_prompt: "maid, cowboy shot, looking away", negative_prompt: "looking at viewer"}],
    scene_draft: {...first.scene_draft, composition_palette: secondPalette},
  };
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify(first), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify(second), {status: 200}));

  render(<MemoryRouter><WorkbenchPage naturalLanguageEnabled /></MemoryRouter>);
  fireEvent.click(screen.getByRole("tab", {name: "自然语言描述"}));
  fireEvent.change(screen.getByLabelText("描述你想生成的画面"), {target: {value: "女仆，不要看镜头"}});
  fireEvent.click(screen.getByRole("button", {name: "编译并生成候选"}));

  const review = await screen.findByRole("region", {name: "Scene Draft"});
  expect(within(review).getByText("构图镜头")).toBeInTheDocument();
  expect(within(review).getByRole("list", {name: "当前构图注意"})).toHaveTextContent("请点选「看向画外」");
  expect(screen.getByRole("heading", {name: "高保真基准"})).toBeInTheDocument();

  fireEvent.click(within(review).getByRole("button", {name: /看向画外/}));
  fireEvent.click(within(review).getByRole("button", {name: /膝上/}));
  expect(within(review).getByRole("button", {name: /看向画外/})).toHaveAttribute("aria-pressed", "true");
  expect(within(review).getByRole("button", {name: /膝上/})).toHaveAttribute("aria-pressed", "true");
  expect(within(review).getByRole("button", {name: /看向画外/})).not.toBeDisabled();
  expect(screen.getByRole("heading", {name: "高保真基准"})).toBeInTheDocument();
  expect(screen.queryByText("正在映射标签、计算推荐并验证候选…")).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2), {timeout: 1500});
  expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body)).selected_tags).toEqual(["looking_away", "cowboy_shot"]);
  expect(await screen.findByText("maid, cowboy shot, looking away")).toBeInTheDocument();
});

it("keeps exclusions separate and reapplies an edited scene plan without translation", async () => {
  const sceneDraft = {
    source_text: "女仆，不要金发",
    translated_text: "A maid",
    confirmed: [{id: "e_local_confirmed_1", text: "女仆", canonical_tag: "maid", source: "source_exact", fact_type: "clothing", reason: "中文原文精确匹配", source_start: 0, source_end: 2}],
    exclusions: [{id: "e_local_excluded_1", text: "金发", canonical_tag: "blonde_hair", source: "source_excluded", fact_type: "appearance", reason: "用户明确排除", source_start: 5, source_end: 7}],
    suggestions: [],
    unresolved: [],
    risk_notes: ["动作和构图仍需人工检查。"],
  } as const;
  const makeResponse = (translatedText: string) => ({
    intent: {
      source_text: sceneDraft.source_text,
      source_language: "zh",
      translated_text: translatedText,
      scene_plan_en: translatedText,
      scene_negative_en: ["blonde hair"],
      graph: {elements: [
        {id: "e_local_confirmed_1", original_text: "女仆", type: "other", state: "required", confidence: 1, notes: []},
        {id: "e_local_excluded_1", original_text: "金发", type: "other", state: "excluded", confidence: 1, notes: []},
      ], edges: []},
      warnings: [],
    },
    candidates: [{...candidate, positive_prompt: `maid. ${translatedText}`, negative_prompt: "blonde hair"}],
    validation: {valid: true, error_count: 0},
    data_pack_id: "pack-r1",
    scene_draft: {...sceneDraft, translated_text: translatedText},
    tag_suggestions: [],
    local_translation: {translated_text: translatedText, engine: translatedText === "A maid" ? "内置离线基础翻译" : "当前工作台译文", local_only: true},
  });
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify(makeResponse("A maid")), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify(makeResponse("A maid descending from the sky")), {status: 200}));

  render(<MemoryRouter><WorkbenchPage naturalLanguageEnabled /></MemoryRouter>);
  fireEvent.click(screen.getByRole("tab", {name: "自然语言描述"}));
  fireEvent.change(screen.getByLabelText("描述你想生成的画面"), {target: {value: sceneDraft.source_text}});
  fireEvent.change(screen.getByLabelText("明确排除（可选）"), {target: {value: "内衣"}});
  fireEvent.click(screen.getByRole("button", {name: "编译并生成候选"}));

  const review = await screen.findByRole("region", {name: "Scene Draft"});
  expect(within(review).getByText("已确认画面事实")).toBeInTheDocument();
  expect(within(review).getByText("服装配饰")).toBeInTheDocument();
  expect(within(review).getByText("明确排除")).toBeInTheDocument();
  expect(within(review).getByText("金发")).toBeInTheDocument();
  expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({excluded_text: "内衣"});

  fireEvent.change(within(review).getByLabelText("可编辑画面计划"), {target: {value: "A maid descending from the sky"}});
  fireEvent.click(within(review).getByRole("button", {name: "应用译文修改"}));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({
    source_text: sceneDraft.source_text,
    excluded_text: "内衣",
    translated_text: "A maid descending from the sky",
    model_profile: "anima_aesthetic_v1",
    selected_tags: [],
  });
  expect(await within(review).findByDisplayValue("A maid descending from the sky")).toBeInTheDocument();
});

it("keeps ownership and wearing relations separate until the user confirms each step", async () => {
  const entityId = "entity_local_confirmed_1";
  const sourceText = "博丽灵梦穿女仆装";
  const translatedText = "Hakurei Reimu wears a maid outfit";
  const makeResponse = (stage: "unowned" | "owned" | "related"): WorkbenchResponse & {local_translation: {translated_text: string; engine: string; local_only: true}} => ({
    intent: {
      source_text: sourceText,
      source_language: "zh",
      translated_text: translatedText,
      scene_plan_en: translatedText,
      scene_negative_en: [],
      graph: {elements: [
        {id: "e_local_confirmed_1", original_text: "博丽灵梦", type: "character", state: "required", confidence: 1, notes: []},
        {id: "e_local_confirmed_2", original_text: "女仆装", type: "clothing", state: "required", confidence: 1, notes: []},
      ], edges: stage === "related" ? [{id: "c_local_relation_1", source_element_id: "e_local_confirmed_1", target_element_id: "e_local_confirmed_2", kind: "relation", relation: "wearing", reason: "用户确认"}] : []},
      warnings: [],
    },
    candidates: [
      {...candidate, positive_prompt: "hakurei reimu, maid"},
      ...(stage === "related" ? [{...candidate, id: "candidate_hybrid", lane: "hybrid" as const, title: "画面计划混合表达", positive_prompt: "hakurei reimu, maid. Hakurei Reimu wears a maid outfit; hakurei reimu wearing maid"}] : []),
    ],
    validation: {valid: true, error_count: 0},
    data_pack_id: "pack-r1",
    scene_draft: {
      source_text: sourceText,
      translated_text: translatedText,
      entities: [{id: entityId, label: "博丽灵梦", canonical_tag: "hakurei_reimu", source_element_id: "e_local_confirmed_1", source_start: 0, source_end: 4}],
      confirmed: [
        {id: "e_local_confirmed_1", text: "博丽灵梦", canonical_tag: "hakurei_reimu", source: "source_exact", fact_type: "character", reason: "中文原文精确匹配", source_start: 0, source_end: 4},
        {id: "e_local_confirmed_2", text: "女仆装", canonical_tag: "maid", source: "source_exact", fact_type: "clothing", owner_entity_id: stage === "unowned" ? null : entityId, suggested_owner_entity_id: stage === "unowned" ? entityId : null, reason: "中文原文精确匹配", source_start: 5, source_end: 8},
      ],
      relations: stage === "unowned" ? [] : [{id: "c_local_relation_1", source_entity_id: entityId, target_element_id: "e_local_confirmed_2", relation: "wearing", state: stage === "related" ? "confirmed" : "suggested", phrase: "hakurei reimu wearing maid", reason: stage === "related" ? "用户已确认实体与服装归属，并进一步确认穿着关系" : "已确认服装归属；穿着关系仍需单独确认"}],
      exclusions: [], suggestions: [], unresolved: [], risk_notes: [],
    },
    tag_suggestions: [],
    local_translation: {translated_text: translatedText, engine: "当前工作台译文", local_only: true},
  });
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify(makeResponse("unowned")), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify(makeResponse("owned")), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify(makeResponse("related")), {status: 200}));

  render(<MemoryRouter><WorkbenchPage naturalLanguageEnabled /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("描述你想生成的画面"), {target: {value: sourceText}});
  fireEvent.click(screen.getByRole("button", {name: "编译并生成候选"}));

  const review = await screen.findByRole("region", {name: "Scene Draft"});
  expect(within(review).getByText("实体与属性归属")).toBeInTheDocument();
  expect(within(review).getByText("建议归属：博丽灵梦")).toBeInTheDocument();
  const owner = within(review).getByLabelText("女仆装 的归属");
  expect(owner).toHaveValue("");
  fireEvent.change(owner, {target: {value: entityId}});

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({
    source_text: sourceText,
    excluded_text: "",
    translated_text: translatedText,
    model_profile: "anima_aesthetic_v1",
    selected_tags: [],
    fact_owners: {e_local_confirmed_2: entityId},
  });
  expect(await within(review).findByLabelText("女仆装 的归属")).toHaveValue(entityId);
  expect(screen.getAllByText("hakurei reimu, maid").length).toBeGreaterThan(0);
  expect(within(review).getByText("显式关系")).toBeInTheDocument();
  expect(within(review).getByText("hakurei reimu wearing maid")).toBeInTheDocument();
  fireEvent.click(within(review).getByRole("button", {name: "确认关系"}));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toEqual({
    source_text: sourceText,
    excluded_text: "",
    translated_text: translatedText,
    model_profile: "anima_aesthetic_v1",
    selected_tags: [],
    fact_owners: {e_local_confirmed_2: entityId},
    confirmed_relations: [{source_entity_id: entityId, target_element_id: "e_local_confirmed_2", relation: "wearing"}],
  });
  expect(await within(review).findByRole("button", {name: "取消确认"})).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText("hakurei reimu, maid. Hakurei Reimu wears a maid outfit; hakurei reimu wearing maid")).toBeInTheDocument();
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
  fireEvent.click(screen.getByRole("button", {name: "展开本地翻译"}));
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

it("shows the artist comparison pool without injecting artists into candidates", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    intent: {source_text: "女仆装", graph: {elements: []}},
    candidates: [candidate], validation: {valid: true, error_count: 0}, data_pack_id: "pack-r1",
    artist_suggestions: [
      {name: "artist_a", render_name: "@artist a", post_count: 300, raw_score: .8, display_score: 1, cooc_count: 80, sources: ["maid"], hit_count: 1, algorithm_version: "artist-v1", data_pack_id: "pack-r1"},
      {name: "artist_b", render_name: "@artist b", post_count: 200, raw_score: .4, display_score: .5, cooc_count: 40, sources: ["twintails"], hit_count: 1, algorithm_version: "artist-v1", data_pack_id: "pack-r1"},
    ],
  }), {status: 200}));

  render(<MemoryRouter><WorkbenchPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("希望画面中出现"), {target: {value: "女仆装"}});
  fireEvent.click(screen.getByRole("button", {name: "生成候选"}));

  fireEvent.click(await screen.findByRole("button", {name: "展开画师对照"}));
  expect(await screen.findByRole("region", {name: "画师对照"})).toBeInTheDocument();
  expect(screen.getByText("@artist a")).toBeInTheDocument();
  expect(screen.getByText(/匹配 .*maid · 1 项证据 · 共现 80/)).toBeInTheDocument();
  expect(screen.getByText("当前证据偏弱，分数只是相对排序，不代表完整场景匹配。")).toBeInTheDocument();
  expect(candidate.artists).toEqual([]);
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
  await waitFor(() => {
    const recovered = JSON.parse(String(localStorage.getItem("anima-v3-workbench-recovery")));
    expect(recovered.workspace).toMatchObject({id: "workspace_1", revision: 1, title: "女仆测试"});
  });

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
    scene_draft: {
      source_text: "女仆",
      translated_text: "A maid",
      entities: [],
      relations: [{id: "c_relation_1", source_entity_id: "entity_subject", target_element_id: "e_maid", relation: "wearing" as const, state: "confirmed" as const, phrase: "subject wearing maid", reason: "用户确认"}],
      confirmed: [], exclusions: [], suggestions: [], unresolved: [], risk_notes: [],
    },
    local_translation: {translated_text: "A maid", engine: "当前工作台译文", local_only: true},
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
  expect(saveRequest.candidate_snapshot).not.toHaveProperty("local_translation");
  expect(saveRequest.candidate_snapshot.scene_draft.relations[0].state).toBe("confirmed");
});

it("restores Scene Draft review when opening a saved candidate snapshot", async () => {
  const translatedText = "A maid standing in the rain";
  const sceneDraft = {
    source_text: "雨中的女仆",
    translated_text: translatedText,
    confirmed: [{id: "e_maid", text: "女仆", canonical_tag: "maid", source: "source_exact", reason: "中文精确匹配", source_start: 3, source_end: 5}],
    exclusions: [], suggestions: [], unresolved: [], risk_notes: ["动作仍需确认。"],
  };
  const snapshot = {
    intent: {source_text: sceneDraft.source_text, source_language: "zh", translated_text: translatedText, scene_plan_en: translatedText, scene_negative_en: [], graph: {elements: [{id: "e_maid", original_text: "女仆", type: "other", state: "required", confidence: 1, notes: []}], edges: []}, warnings: []},
    candidates: [candidate], validation: {valid: true, error_count: 0}, data_pack_id: "pack-r1", scene_draft: sceneDraft,
  };
  const record = {
    id: "workspace_scene", title: "雨夜女仆", draft: {positive_text: "", excluded_text: "", model_profile: "anima_aesthetic_v1", input_mode: "natural", natural_text: sceneDraft.source_text, selected_tags: []},
    candidate_snapshot: snapshot, revision: 1, created_at: "2026-08-30T00:00:00+00:00", updated_at: "2026-08-30T00:00:00+00:00",
  };
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({items: [record]}), {status: 200}));

  render(<MemoryRouter><WorkbenchPage naturalLanguageEnabled /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", {name: "打开"}));
  fireEvent.click(await screen.findByRole("button", {name: /雨夜女仆/}));

  expect(await screen.findByRole("region", {name: "Scene Draft"})).toBeInTheDocument();
  expect(screen.getByLabelText("可编辑画面计划")).toHaveValue(translatedText);
  expect(screen.getByText("已整理 1 项画面证据")).toBeInTheDocument();
});

it("keeps same-named connections distinct and submits to the selected cloud host", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [{
      remote_profile_id: "remote-1",
      remote_display_name: "测试云主机",
      remote_ssh_host: "203.0.113.10",
      remote_ssh_port: 23,
      workflow_profile_id: "workflow-1",
      workflow_display_name: "ANIMA Base",
      workflow_kind: "txt2img_basic",
      compatible_model_profiles: ["anima_base_v1", "anima_aesthetic_v1"],
      host_fingerprint_ready: true,
      auth_type: "agent",
      private_key_passphrase_configured: false,
      ...baseRecipeContract,
    }, {
      remote_profile_id: "remote-2",
      remote_display_name: "测试云主机",
      remote_ssh_host: "203.0.113.10",
      remote_ssh_port: 23,
      workflow_profile_id: "workflow-1",
      workflow_display_name: "ANIMA Base",
      workflow_kind: "txt2img_basic",
      compatible_model_profiles: ["anima_base_v1", "anima_aesthetic_v1"],
      host_fingerprint_ready: true,
      auth_type: "agent",
      private_key_passphrase_configured: false,
      ...baseRecipeContract,
    }, {
      remote_profile_id: "remote-3",
      remote_display_name: "新云显卡",
      remote_ssh_host: "203.0.113.12",
      remote_ssh_port: 23,
      workflow_profile_id: "workflow-1",
      workflow_display_name: "ANIMA Base",
      workflow_kind: "txt2img_basic",
      compatible_model_profiles: ["anima_base_v1", "anima_aesthetic_v1"],
      host_fingerprint_ready: false,
      auth_type: "agent",
      private_key_passphrase_configured: false,
      ...baseRecipeContract,
    }]}), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      intent: {source_text: "女仆", source_language: "zh", graph: {elements: []}},
      candidates: [candidate], validation: {valid: true, error_count: 0}, data_pack_id: "pack-r1",
    }), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({remote_profile_id: "remote-2"}), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      id: "run-1", state: "draft", progress: 0, available_actions: ["cancel_queued"],
    }), {status: 202}));

  render(<MemoryRouter><WorkbenchPage remoteEnabled /></MemoryRouter>);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  fireEvent.change(screen.getByLabelText("希望画面中出现"), {target: {value: "女仆"}});
  fireEvent.click(screen.getByRole("button", {name: "生成候选"}));
  await screen.findByRole("heading", {name: "高保真基准"});
  const connectionSelect = screen.getByLabelText("云主机连接") as HTMLSelectElement;
  expect(connectionSelect.options).toHaveLength(3);
  expect(connectionSelect).toHaveTextContent("203.0.113.10:23 · 连接 remote-1");
  expect(connectionSelect).toHaveTextContent("203.0.113.10:23 · 连接 remote-2");
  expect(connectionSelect).toHaveTextContent("新云显卡 · 203.0.113.12:23 · 待确认指纹");
  fireEvent.change(connectionSelect, {target: {value: "remote-2"}});
  expect(screen.getByLabelText("远程工作流")).toHaveValue("workflow-1");
  fireEvent.click(screen.getByRole("button", {name: "远程生图"}));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
  expect(fetchMock.mock.calls[2][0]).toBe("/api/v3/settings/default-remote-profile");
  expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toEqual({remote_profile_id: "remote-2"});
  const request = JSON.parse(String(fetchMock.mock.calls[3][1]?.body));
  expect(request.remote_profile_id).toBe("remote-2");
  expect(request.workflow_profile_id).toBe("workflow-1");
  expect(request.candidate.id).toBe("candidate_literal");
  expect(request.settings).toEqual({preset_id: "stable_baseline", width: 896, height: 1152, steps: 30, cfg: 4, sampler: "er_sde", scheduler: "simple", seed: -1, batch_size: 1});
  expect(new Headers(fetchMock.mock.calls[3][1]?.headers).get("Idempotency-Key")).toMatch(/^web-/);
});

it("keeps the database-preferred cloud host while changing model workflows", async () => {
  localStorage.setItem("anima-v3-generation-target", "remote-1::aesthetic");
  const target = (remote: string, workflow: string, model: string) => ({
    remote_profile_id: remote,
    remote_display_name: remote === "remote-2" ? "固定云显卡" : "旧云显卡",
    remote_ssh_host: remote === "remote-2" ? "203.0.113.12" : "203.0.113.10",
    remote_ssh_port: 23,
    workflow_profile_id: workflow,
    workflow_display_name: workflow,
    workflow_kind: "txt2img_basic",
    compatible_model_profiles: [model],
    host_fingerprint_ready: true,
    auth_type: "agent",
    private_key_passphrase_configured: false,
  });
  const targets = [
    target("remote-1", "aesthetic", "anima_aesthetic_v1"),
    target("remote-1", "base", "anima_base_v1"),
    target("remote-2", "aesthetic", "anima_aesthetic_v1"),
    target("remote-2", "base", "anima_base_v1"),
  ];
  const response = new Response(JSON.stringify({
    intent: {source_text: "女仆", source_language: "zh", graph: {elements: []}},
    candidates: [candidate], validation: {valid: true, error_count: 0}, data_pack_id: "pack-r1",
  }), {status: 200});
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({items: targets, preferred_remote_profile_id: "remote-2"}), {status: 200}))
    .mockResolvedValueOnce(response)
    .mockResolvedValueOnce(response.clone());

  render(<MemoryRouter><WorkbenchPage remoteEnabled /></MemoryRouter>);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  fireEvent.change(screen.getByLabelText("希望画面中出现"), {target: {value: "女仆"}});
  fireEvent.click(screen.getByRole("button", {name: "生成候选"}));
  await screen.findByRole("heading", {name: "高保真基准"});
  expect(screen.getByLabelText("云主机连接")).toHaveValue("remote-2");
  expect(screen.getByLabelText("远程工作流")).toHaveValue("aesthetic");

  fireEvent.change(screen.getByLabelText("模型配置"), {target: {value: "anima_base_v1"}});
  fireEvent.click(screen.getByRole("button", {name: "生成候选"}));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  expect(screen.getByLabelText("云主机连接")).toHaveValue("remote-2");
  expect(screen.getByLabelText("远程工作流")).toHaveValue("base");
});

it("locks one candidate and submits separate fixed-seed jobs for selected artists", async () => {
  const artists = [
    {name: "artist_a", render_name: "@artist a", post_count: 300, raw_score: .8, display_score: 1, cooc_count: 80, sources: ["maid"], hit_count: 1, algorithm_version: "artist-v1", data_pack_id: "pack-r1"},
    {name: "artist_b", render_name: "@artist b", post_count: 200, raw_score: .4, display_score: .5, cooc_count: 40, sources: ["twintails"], hit_count: 1, algorithm_version: "artist-v1", data_pack_id: "pack-r1"},
  ];
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [{
      remote_profile_id: "remote-1", remote_display_name: "测试云主机", workflow_profile_id: "workflow-1", workflow_display_name: "ANIMA Base", workflow_kind: "txt2img_basic", compatible_model_profiles: ["anima_base_v1", "anima_aesthetic_v1"], host_fingerprint_ready: true, auth_type: "agent", private_key_passphrase_configured: false, ...baseRecipeContract,
    }]}), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      intent: {source_text: "女仆", source_language: "zh", graph: {elements: []}}, candidates: [candidate], validation: {valid: true, error_count: 0}, data_pack_id: "pack-r1", artist_suggestions: artists,
    }), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({items: artists}), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      comparison_id: "comparison_abcdef012345", project_name: "画师批量对照 · abcdef01", seed: 123, requested_count: 2, submitted: [{artist: "@artist a", run: {id: "run-a"}}, {artist: "@artist b", run: {id: "run-b"}}], failed: [],
    }), {status: 202}));

  render(<MemoryRouter><WorkbenchPage remoteEnabled /></MemoryRouter>);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  fireEvent.change(screen.getByLabelText("希望画面中出现"), {target: {value: "女仆"}});
  fireEvent.click(screen.getByRole("button", {name: "生成候选"}));
  await screen.findByRole("heading", {name: "高保真基准"});
  fireEvent.click(screen.getByRole("button", {name: "设为画师对照基准"}));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  fireEvent.change(screen.getByLabelText("固定 Seed"), {target: {value: "123"}});
  const artistButtons = screen.getAllByRole("button", {name: "选入对照"});
  fireEvent.click(artistButtons[0]);
  fireEvent.click(artistButtons[1]);
  fireEvent.click(screen.getByRole("button", {name: /提交 2 位画师对照/}));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
  expect(fetchMock.mock.calls[3][0]).toBe("/api/v3/artist-comparisons");
  const request = JSON.parse(String(fetchMock.mock.calls[3][1]?.body));
  expect(request.artist_names).toEqual(["artist_a", "artist_b"]);
  expect(request.settings).toEqual({preset_id: "stable_baseline", width: 896, height: 1152, steps: 30, cfg: 4, sampler: "er_sde", scheduler: "simple", seed: 123, batch_size: 1});
  expect(request.candidate.id).toBe("candidate_literal");
  expect(new Headers(fetchMock.mock.calls[3][1]?.headers).get("Idempotency-Key")).toMatch(/^artist-comparison-/);
});

it("sends an encrypted-key passphrase separately before the generation request", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [{
      remote_profile_id: "remote-key",
      remote_display_name: "私钥云主机",
      workflow_profile_id: "workflow-1",
      workflow_display_name: "ANIMA Base",
      workflow_kind: "txt2img_basic",
      compatible_model_profiles: ["anima_base_v1", "anima_aesthetic_v1"],
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

it("annotates English scene plans with Chinese back-translation and lets users delete a confirmed character", async () => {
  const sourceText = "博丽灵梦穿女仆装";
  const translatedText = "Hakurei Reimu wears a maid outfit";
  const sceneDraft: SceneDraft = {
    source_text: sourceText,
    translated_text: translatedText,
    confirmed: [
      {id: "e_local_confirmed_1", text: "博丽灵梦", canonical_tag: "hakurei_reimu", source: "source_exact", fact_type: "character", reason: "中文原文精确匹配", source_start: 0, source_end: 4},
      {id: "e_local_confirmed_2", text: "女仆", canonical_tag: "maid", source: "source_exact", fact_type: "clothing", reason: "中文原文精确匹配", source_start: 5, source_end: 7},
    ],
    exclusions: [],
    suggestions: [],
    unresolved: [],
    suppressed: [],
    back_translation: {text: "博丽灵梦穿着女仆装", engine: "内置离线基础翻译", segments: [{en: translatedText, zh: "博丽灵梦穿着女仆装"}], negative_text: "最差画质"},
    risk_notes: [],
  };
  const makeResponse = (draft: SceneDraft, prompt: string) => ({
    intent: {source_text: sourceText, source_language: "zh", translated_text: translatedText, scene_plan_en: translatedText, scene_negative_en: [], graph: {elements: [], edges: []}, warnings: []},
    candidates: [{...candidate, positive_prompt: prompt, tags: draft.confirmed.flatMap((item) => item.canonical_tag ? [{name: item.canonical_tag, rendered: item.canonical_tag.replaceAll("_", " "), state: "required" as const, source: "exact" as const, source_element_ids: [item.id], reason: item.reason, raw_score: null, display_score: null, removable: true}] : [])}],
    validation: {valid: true, error_count: 0},
    data_pack_id: "pack-r1",
    scene_draft: draft,
    local_translation: {translated_text: translatedText, engine: "当前工作台译文", local_only: true},
  });
  const after: SceneDraft = {
    ...sceneDraft,
    confirmed: [sceneDraft.confirmed[1]],
    suppressed: [{id: "e_local_suppressed_1", text: "博丽灵梦", canonical_tag: "hakurei_reimu", source: "suppressed", reason: "用户已移除；重编译不会自动恢复", source_start: null, source_end: null}],
    risk_notes: ["已移除的标签仍出现在英文画面计划中：hakurei_reimu。请直接改英文，否则 Hybrid 仍可能带上它们。"],
  };
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify(makeResponse(sceneDraft, "hakurei reimu, maid")), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify(makeResponse(after, "maid")), {status: 200}));

  render(<MemoryRouter><WorkbenchPage naturalLanguageEnabled /></MemoryRouter>);
  fireEvent.click(screen.getByRole("tab", {name: "自然语言描述"}));
  fireEvent.change(screen.getByLabelText("描述你想生成的画面"), {target: {value: sourceText}});
  fireEvent.click(screen.getByRole("button", {name: "编译并生成候选"}));

  const review = await screen.findByRole("region", {name: "Scene Draft"});
  expect(within(review).getByRole("region", {name: "英文画面计划的中文回译对照"})).toBeInTheDocument();
  expect(within(review).getAllByText("博丽灵梦穿着女仆装").length).toBeGreaterThan(0);
  fireEvent.click(within(review).getByRole("button", {name: "移除 博丽灵梦"}));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body)).suppressed_tags).toEqual(["hakurei_reimu"]);
  expect(await screen.findByRole("button", {name: "恢复 博丽灵梦"})).toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "移除 博丽灵梦"})).not.toBeInTheDocument();
});

it("writes the visible generation spec into the remote request", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [{
      remote_profile_id: "remote-1", remote_display_name: "测试云主机", workflow_profile_id: "workflow-1", workflow_display_name: "ANIMA Aesthetic", workflow_kind: "txt2img_basic", compatible_model_profiles: ["anima_aesthetic_v1"], host_fingerprint_ready: true, auth_type: "agent", private_key_passphrase_configured: false, ...baseRecipeContract,
    }]}), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      intent: {source_text: "女仆", source_language: "zh", graph: {elements: []}}, candidates: [candidate], validation: {valid: true, error_count: 0}, data_pack_id: "pack-r1",
    }), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({id: "run-1", state: "draft", progress: 0, available_actions: ["cancel_queued"]}), {status: 202}));

  render(<MemoryRouter><WorkbenchPage remoteEnabled /></MemoryRouter>);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  fireEvent.change(screen.getByLabelText("画幅"), {target: {value: "landscape"}});
  fireEvent.change(screen.getByLabelText("生成配方"), {target: {value: "detail_study"}});
  fireEvent.change(screen.getByLabelText("采样步数 Steps"), {target: {value: "46"}});
  fireEvent.change(screen.getByLabelText("CFG"), {target: {value: "4.2"}});
  fireEvent.change(screen.getByLabelText("采样器 Sampler"), {target: {value: "dpmpp_2m_sde_gpu"}});
  fireEvent.change(screen.getByLabelText("Seed"), {target: {value: "42"}});
  fireEvent.change(screen.getByLabelText("希望画面中出现"), {target: {value: "女仆"}});
  fireEvent.click(screen.getByRole("button", {name: "生成候选"}));
  await screen.findByRole("heading", {name: "高保真基准"});
  fireEvent.click(screen.getByRole("button", {name: "远程生图"}));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body)).settings).toEqual({preset_id: "custom", width: 1152, height: 896, steps: 46, cfg: 4.2, sampler: "dpmpp_2m_sde_gpu", scheduler: "simple", seed: 42, batch_size: 1});
});

it("keeps English structured tags bilingual and suppressed after recompiling", async () => {
  const initialDraft: SceneDraft = {
    source_text: "maid，hakurei_reimu",
    translated_text: "maid，hakurei_reimu",
    scene_plan_enabled: false,
    confirmed: [
      {id: "e_local_confirmed_1", text: "maid", canonical_tag: "maid", cn_name: "女仆", source: "source_exact", fact_type: "clothing", reason: "英文 canonical 命中", source_start: 0, source_end: 4},
      {id: "e_local_confirmed_2", text: "hakurei_reimu", canonical_tag: "hakurei_reimu", cn_name: "博丽灵梦", source: "source_exact", fact_type: "character", reason: "英文 canonical 命中", source_start: 5, source_end: 19},
    ],
    exclusions: [], suggestions: [], unresolved: [], suppressed: [], ambiguous: [],
    back_translation: {text: "", engine: "", segments: [], negative_text: ""},
    risk_notes: [],
  };
  const initialCandidate: PromptCandidate = {
    ...candidate,
    positive_prompt: "maid, hakurei reimu",
    tags: [
      {...candidate.tags[1], name: "maid", rendered: "maid", cn_name: "女仆", source_element_ids: ["e_local_confirmed_1"]},
      {...candidate.tags[1], name: "hakurei_reimu", rendered: "hakurei reimu", cn_name: "博丽灵梦", source_element_ids: ["e_local_confirmed_2"]},
    ],
  };
  const removedDraft: SceneDraft = {
    ...initialDraft,
    confirmed: [initialDraft.confirmed[1]],
    suppressed: [{id: "e_local_suppressed_1", text: "maid", canonical_tag: "maid", cn_name: "女仆", source: "suppressed", reason: "用户已移除；重编译不会自动恢复", source_start: 0, source_end: 4}],
  };
  const response = (draft: SceneDraft, prompt: string, tags: PromptCandidate["tags"]): WorkbenchResponse => ({
    intent: {source_text: draft.source_text, source_language: "en", translated_text: draft.translated_text, scene_plan_en: null, scene_negative_en: [], graph: {elements: [], edges: []}, warnings: []},
    candidates: [{...initialCandidate, positive_prompt: prompt, tags}],
    validation: {valid: true, error_count: 0},
    data_pack_id: "pack-r1",
    scene_draft: draft,
    tag_suggestions: [],
    artist_suggestions: [],
  });
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify(response(initialDraft, initialCandidate.positive_prompt, initialCandidate.tags)), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify(response(removedDraft, "hakurei reimu", [initialCandidate.tags[1]])), {status: 200}));

  render(<MemoryRouter><WorkbenchPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("希望画面中出现"), {target: {value: "maid, hakurei_reimu"}});
  fireEvent.click(screen.getByRole("button", {name: "生成候选"}));

  expect(await screen.findByRole("button", {name: "移除 女仆 maid"})).toBeInTheDocument();
  expect(screen.queryByRole("textbox", {name: "可编辑画面计划"})).not.toBeInTheDocument();
  expect(screen.getByRole("list", {name: "Positive 中文对照"})).toHaveTextContent("博丽灵梦");
  fireEvent.click(screen.getByRole("button", {name: /^移除 女仆$/}));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body)).suppressed_tags).toEqual(["maid"]);
  expect(await screen.findByRole("button", {name: "恢复 maid"})).toBeInTheDocument();
  expect(screen.getByText("hakurei reimu", {selector: ".prompt-block > code"})).toBeInTheDocument();
  expect(screen.queryByText("maid, hakurei reimu", {selector: ".prompt-block > code"})).not.toBeInTheDocument();
});
