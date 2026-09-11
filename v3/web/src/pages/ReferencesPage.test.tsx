import {fireEvent, render, screen, waitFor} from "@testing-library/react";
import {MemoryRouter, Route, Routes} from "react-router-dom";
import {beforeEach, expect, it, vi} from "vitest";
import {ReferencesPage} from "./ReferencesPage";
import {emptyRequirements} from "../lib/conversation";

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
