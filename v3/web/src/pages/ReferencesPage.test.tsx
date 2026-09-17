import {fireEvent, render, screen, waitFor} from "@testing-library/react";
import {MemoryRouter, Route, Routes} from "react-router-dom";
import {beforeEach, expect, it, vi} from "vitest";
import {ReferencesPage} from "./ReferencesPage";
import {emptyRequirements} from "../lib/conversation";
import {AppearanceControls} from "../components/AppearanceControls";

const example = {id: "ex_a", title: "雨夜案例", revision: 1, source_version: "1", requirements_valid: true, requirements: emptyRequirements(),
  origin: "session_pin", notes: {external_prompt: "rain", user_notes: "", source_url: ""}, provenance: {run_id: "run1", positive: "rain", settings: {seed: "8798399215689017476"}}};
beforeEach(() => {vi.restoreAllMocks(); sessionStorage.setItem("anima-v3-session", "token"); localStorage.clear();});
function mount() {render(<MemoryRouter initialEntries={["/references?example=ex_a"]}><Routes><Route path="/references" element={<ReferencesPage />} /><Route path="/workbench" element={<p>新会话已打开</p>} /></Routes></MemoryRouter>);}
it("opens a case directly and starts a new workspace without touching an existing draft", async () => {
  localStorage.setItem("anima-conversation-draft:workspace_old", "unsaved draft");
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async url => new Response(JSON.stringify(String(url).endsWith("/workspace") ? {id: "workspace_new"} : String(url).includes("?") ? {items: [example], next_cursor: null, official_pack: {ready: true}} : example)));
  mount();
  await screen.findByRole("button", {name: "沿用生成条件，新建会话"});
  fireEvent.click(screen.getByText("原图提示词与参数"));
  expect(screen.getByText("8798399215689017476")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "沿用生成条件，新建会话"}));
  expect(await screen.findByText("新会话已打开")).toBeInTheDocument();
  const call = fetchMock.mock.calls.find(call => String(call[0]).endsWith("/workspace"));
  expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({mode: "generation", source_version: "1"});
  expect(localStorage.getItem("anima-conversation-draft:workspace_old")).toBe("unsaved draft");
});
it("blocks starting a new workspace while case notes have unsaved changes", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async url => new Response(JSON.stringify(String(url).includes("?") ? {items: [example], next_cursor: null, official_pack: {ready: true}} : example)));
  mount();
  const notes = await screen.findByLabelText("我的笔记");
  fireEvent.change(notes, {target: {value: "未保存"}});
  await waitFor(() => expect(screen.getByRole("button", {name: "借用要求，新建会话"})).toBeDisabled());
  expect(screen.getByRole("button", {name: "沿用生成条件，新建会话"})).toBeDisabled();
});

it("borrows original prompt without requiring analyzed requirements and copies its exact text", async () => {
  const original = "@sample_artist, watercolor\nblue sky";
  const research = {...example, requirements_valid: false, requirements: null, provenance: {positive: original, negative: "", model_profile: "anima_2_9b_preview_v1"}};
  const copy = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {configurable: true, value: {writeText: copy}});
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async url => new Response(JSON.stringify(String(url).endsWith("/workspace") ? {id: "workspace_new"} : String(url).includes("?") ? {items: [research], next_cursor: null, official_pack: {ready: true}} : research)));
  mount();
  await screen.findByRole("button", {name: "借用原提示词，新建会话"});
  expect(screen.getByRole("button", {name: "借用要求，新建会话"})).toBeDisabled();
  fireEvent.click(screen.getByText("原图提示词与参数"));
  fireEvent.click(screen.getByRole("button", {name: "复制原始正向提示词"}));
  await waitFor(() => expect(copy).toHaveBeenCalledWith(original));
  await waitFor(() => expect(screen.getByRole("button", {name: "借用原提示词，新建会话"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button", {name: "借用原提示词，新建会话"}));
  expect(await screen.findByText("新会话已打开")).toBeInTheDocument();
  const call = fetchMock.mock.calls.find(call => String(call[0]).endsWith("/workspace"));
  expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({mode: "prompt", source_version: "1"});
  expect(fetchMock.mock.calls.some(call => String(call[0]).endsWith("/ingest"))).toBe(false);
});

it("auto-applies all five selects and clears them without a search click", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async url => new Response(JSON.stringify(String(url).endsWith("/facets") ? {models: ["anima-base-v1.0"], artists: ["sample_artist"]} : String(url).includes("?") ? {items: [example], next_cursor: null, official_pack: {ready: true}} : example)));
  mount();
  await screen.findByRole("option", {name: "@sample_artist"});
  fireEvent.change(screen.getByLabelText("案例来源"), {target: {value: "research_import"}});
  fireEvent.change(screen.getByLabelText("参考模型"), {target: {value: "anima-base-v1.0"}});
  fireEvent.change(screen.getByLabelText("参考画师"), {target: {value: "sample_artist"}});
  fireEvent.change(screen.getByLabelText("LoRA 依赖"), {target: {value: "unknown"}});
  fireEvent.change(screen.getByLabelText("内容标记"), {target: {value: "safe"}});
  await waitFor(() => expect(fetchMock.mock.calls.some(call => String(call[0]).includes("origin=research_import&model=anima-base-v1.0&artist=sample_artist&lora_dependency=unknown&content=safe"))).toBe(true));
  fireEvent.click(screen.getByRole("button", {name: "清除筛选"}));
  await waitFor(() => {
    const listCalls = fetchMock.mock.calls.map(call => String(call[0])).filter(url => url.includes("reference-examples?"));
    expect(listCalls.at(-1)).not.toMatch(/origin=|model=|artist=|lora_dependency=|content=/);
  });
  for (const label of ["案例来源", "参考模型", "参考画师", "LoRA 依赖", "内容标记"]) expect(screen.getByLabelText(label)).toHaveValue("");
});

it("debounces typed search but Enter applies it immediately", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async url => new Response(JSON.stringify(String(url).endsWith("/facets") ? {models: [], artists: []} : String(url).includes("?") ? {items: [example], next_cursor: null, official_pack: {ready: true}, total: 1} : example)));
  mount();
  await screen.findByText("已载入 1 / 1 条参考");
  const before = fetchMock.mock.calls.length;
  const search = screen.getByLabelText("搜索收藏");
  fireEvent.change(search, {target: {value: "rain night"}});
  expect(fetchMock.mock.calls).toHaveLength(before);
  fireEvent.keyDown(search, {key: "Enter"});
  await waitFor(() => expect(fetchMock.mock.calls.some(call => String(call[0]).includes("q=rain+night"))).toBe(true));
});

it("keeps selected unsaved edits while an automatic filter request is pending and after it resolves", async () => {
  let resolveFiltered!: (response: Response) => void;
  const filtered = new Promise<Response>(resolve => {resolveFiltered = resolve;});
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async url => {
    const value = String(url);
    if (value.endsWith("/facets")) return new Response(JSON.stringify({models: [], artists: []}));
    if (value.includes("origin=research_import")) return filtered;
    if (value.includes("?")) return new Response(JSON.stringify({items: [example], next_cursor: null, official_pack: {ready: true}, total: 1}));
    return new Response(JSON.stringify(example));
  });
  mount();
  const notes = await screen.findByLabelText("我的笔记");
  fireEvent.change(notes, {target: {value: "筛选期间未保存"}});
  fireEvent.change(screen.getByLabelText("案例来源"), {target: {value: "research_import"}});
  await waitFor(() => expect(fetchMock.mock.calls.some(call => String(call[0]).includes("origin=research_import"))).toBe(true));
  expect(notes).toHaveValue("筛选期间未保存");
  resolveFiltered(new Response(JSON.stringify({items: [], next_cursor: null, official_pack: {ready: true}, total: 0})));
  await screen.findByText("没有符合当前筛选的案例。");
  expect(screen.getByLabelText("我的笔记")).toHaveValue("筛选期间未保存");
  expect(screen.getByRole("heading", {name: "雨夜案例"})).toBeInTheDocument();
});

it("keeps unsaved notes, selected reference and original image URL while changing all four appearance modes", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async url => new Response(JSON.stringify(String(url).includes("?") ? {items: [example], next_cursor: null, official_pack: {ready: true}} : example)));
  render(<MemoryRouter initialEntries={["/references?example=ex_a"]}><AppearanceControls /><ReferencesPage /></MemoryRouter>);
  const notes = await screen.findByLabelText("我的笔记");
  fireEvent.change(notes, {target: {value: "切换外观前还未保存"}});
  const preview = screen.getByRole("button", {name: "预览案例原图"}).querySelector("img")!;
  const source = preview.getAttribute("src");
  const requestCount = fetchMock.mock.calls.length;
  const layout = screen.getByLabelText("界面布局") as HTMLSelectElement;
  const theme = screen.getByLabelText("明暗主题") as HTMLSelectElement;
  const previous = {layout: layout.value, theme: theme.value};
  for (const value of ["studio", "editorial"]) {
    fireEvent.change(layout, {target: {value}});
    for (const mode of ["light", "dark"]) {
      fireEvent.change(theme, {target: {value: mode}});
      expect(notes).toHaveValue("切换外观前还未保存");
      expect(preview).toHaveAttribute("src", source);
      expect(screen.getByRole("button", {name: "关闭详情"})).toBeDisabled();
      expect(screen.getByRole("button", {name: "沿用生成条件，新建会话"})).toBeDisabled();
    }
  }
  expect(fetchMock).toHaveBeenCalledTimes(requestCount);
  fireEvent.change(layout, {target: {value: previous.layout}});
  fireEvent.change(theme, {target: {value: previous.theme}});
});
