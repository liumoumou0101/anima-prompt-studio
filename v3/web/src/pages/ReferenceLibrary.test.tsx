import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {ReferenceLibrary} from "./ReferenceLibrary";
import {emptyRequirements} from "../lib/conversation";
import type {ConversationRecord} from "../lib/conversation";

const requirements = emptyRequirements();
requirements.layers.style.text = "水彩";
const example = {id: "ex_a", title: "水彩参考", revision: 2, source_version: "2", requirements_valid: true,
  requirements, ingest_state: "ready", notes: {external_prompt: "外部文本", user_notes: "", source_url: ""}};
const record = {id: "workspace_a", revision: 1, draft: {requirements}} as ConversationRecord;
let requests: {url: string; init?: RequestInit}[];
beforeEach(() => {
  sessionStorage.setItem("anima-v3-session", "test"); requests = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input); requests.push({url, init});
    if (init?.method === "DELETE") return new Response(null, {status: 204});
    return new Response(JSON.stringify(init?.method === "POST" ? {...example, warnings: []} : {
      items: [example], next_cursor: null, official_pack: {ready: false}}));
  });
});
afterEach(() => {cleanup(); vi.restoreAllMocks();});

async function open(disabled = false) {
  const onPin = vi.fn(async () => {});
  const rendered = render(<ReferenceLibrary record={record} disabled={disabled} onPin={onPin} onUnpin={async () => {}} />);
  const details = rendered.container.querySelector("details")!;
  details.open = true; fireEvent(details, new Event("toggle"));
  fireEvent.click(await screen.findByRole("button", {name: /水彩参考/}));
  return onPin;
}

it("shows overwrite preview and pins only on explicit action", async () => {
  const onPin = await open();
  expect(screen.getByText(/将覆盖：风格/)).toBeTruthy();
  expect(onPin).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", {name: "复制并钉选"}));
  await waitFor(() => expect(onPin).toHaveBeenCalledWith(example, "style"));
});

it("installs bundled examples only on click and refreshes without losing edits", async () => {
  await open();
  fireEvent.change(screen.getByLabelText("我的笔记"), {target: {value: "未保存的笔记"}});
  expect(requests.some(item => item.url.endsWith("/install-bundled"))).toBe(false);
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    requests.push({url: String(input), init});
    return new Response(JSON.stringify(init?.method === "POST" ? {ready: true, count: 3} : {
      items: [example], next_cursor: null, official_pack: {ready: true}}));
  });
  fireEvent.click(screen.getByRole("button", {name: "安装内置样例"}));
  await screen.findByText("内置样例已就绪，可以选择参考并复制风格要求。");
  expect(screen.queryByRole("button", {name: "安装内置样例"})).toBeNull();
  expect(screen.getByLabelText("我的笔记")).toHaveValue("未保存的笔记");
  expect(requests.filter(item => item.url.endsWith("/install-bundled"))).toHaveLength(1);
});

it("keeps install retry available after a failure", async () => {
  await open();
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({error: {
    code: "bundled_examples_missing", message: "当前安装缺少内置样例文件"}}), {status: 422}));
  fireEvent.click(screen.getByRole("button", {name: "安装内置样例"}));
  await screen.findByRole("status");
  expect(screen.getByRole("button", {name: "安装内置样例"})).toBeEnabled();
});

it("blocks pin while the workspace contains unsent edits", async () => {
  const onPin = await open(true);
  expect((screen.getByRole("button", {name: "复制并钉选"}) as HTMLButtonElement).disabled).toBe(true);
  expect(onPin).not.toHaveBeenCalled();
});

it("does not send external notes by default and accepts a 204 delete", async () => {
  await open();
  fireEvent.click(screen.getByText("辅助：读图建议"));
  fireEvent.click(screen.getByRole("button", {name: /分析图片/}));
  await waitFor(() => expect(requests.some(item => item.url.endsWith("/ingest"))).toBe(true));
  expect(JSON.parse(String(requests.find(item => item.url.endsWith("/ingest"))!.init!.body))).toEqual({revision: 2, use_external_prompt_notes: false});
  await screen.findByText("读图建议已生成，仅供参考，请核对和修正后再钉选。");
  fireEvent.click(screen.getByLabelText("移除此收藏"));
  fireEvent.click(screen.getByRole("button", {name: "确认移除收藏"}));
  await waitFor(() => expect(requests.some(item => item.init?.method === "DELETE")).toBe(true));
  await waitFor(() => expect(screen.queryByRole("button", {name: "确认移除收藏"})).toBeNull());
});

it("extracts saved prompt text explicitly and blocks unsaved note edits", async () => {
  await open();
  const button = screen.getByRole("button", {name: "从提示词提取要求（不发送图片）"});
  expect(requests.some(item => item.url.endsWith("/ingest"))).toBe(false);
  fireEvent.change(screen.getByLabelText("外部提示词"), {target: {value: "new text"}});
  expect(button).toBeDisabled();
  fireEvent.change(screen.getByLabelText("外部提示词"), {target: {value: "外部文本"}});
  expect(button).toBeEnabled();
  fireEvent.click(button);
  await waitFor(() => expect(requests.some(item => item.url.endsWith("/ingest"))).toBe(true));
  expect(JSON.parse(String(requests.find(item => item.url.endsWith("/ingest"))!.init!.body)))
    .toEqual({revision: 2, source: "prompt"});
});

it("uploads multipart bytes without a JSON content type", async () => {
  await open();
  fireEvent.change(screen.getByLabelText("图片标题"), {target: {value: "新参考"}});
  fireEvent.change(screen.getByLabelText("参考图片"), {target: {files: [new File(["test"], "a.png", {type: "image/png"})]}});
  fireEvent.click(screen.getByRole("button", {name: "保存参考图"}));
  await waitFor(() => expect(requests.some(item => item.init?.body instanceof FormData)).toBe(true));
  const upload = requests.find(item => item.init?.body instanceof FormData)!;
  expect(new Headers(upload.init!.headers).has("Content-Type")).toBe(false);
});

it("requires saving edited reference requirements and strips server fields", async () => {
  await open();
  fireEvent.click(screen.getByText("编辑参考要求与 LoRA"));
  fireEvent.change(screen.getByLabelText("风格内容"), {target: {value: "炭笔"}});
  expect((screen.getByRole("button", {name: "复制并钉选"}) as HTMLButtonElement).disabled).toBe(true);
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    requests.push({url:String(input),init});
    return new Response(JSON.stringify(init?.method === "PATCH" ? {...example,revision:3,source_version:"3",
      requirements:{...requirements,contract:"anima-requirements/1",revision:3,layers:{...requirements.layers,style:{...requirements.layers.style,text:"炭笔"}}}}
      : {items:[example],next_cursor:null,official_pack:{ready:false}}));
  });
  fireEvent.click(screen.getByRole("button", {name: "保存参考要求"}));
  await waitFor(() => expect((screen.getByRole("button", {name: "复制并钉选"}) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.change(screen.getByLabelText("风格内容"), {target: {value: "铅笔"}});
  fireEvent.click(screen.getByRole("button", {name: "保存参考要求"}));
  await waitFor(() => expect(requests.filter(item => item.init?.method === "PATCH").length).toBe(2));
  const sent = JSON.parse(String(requests.filter(item => item.init?.method === "PATCH")[1].init!.body));
  expect(Object.keys(sent.requirements_edit).sort()).toEqual(["layers","loras"]);
});

it("official cards offer copying and notes without modifying pack content", async () => {
  const official = {...example,id:"off_one",origin:"official",revision:null,source_version:"pack:hash",override_revision:0};
  vi.mocked(fetch).mockImplementation(async (input,init) => {
    requests.push({url:String(input),init});
    return new Response(JSON.stringify(init?.method === "PATCH" ? {...official,override_revision:1}
      : {items:[official],next_cursor:null,official_pack:{ready:true,id:"pack",count:1}}));
  });
  await open();
  expect(screen.queryByRole("button", {name:/分析图片/})).toBeNull();
  expect(screen.queryByText("编辑参考要求与 LoRA")).toBeNull();
  expect(screen.getByRole("button", {name:"复制为我的参考"})).toBeTruthy();
  fireEvent.change(screen.getByLabelText("我的笔记"), {target:{value:"my note"}});
  fireEvent.click(screen.getByRole("button", {name:"保存我的笔记"}));
  await waitFor(() => expect(requests.some(item => item.url.endsWith("off_one/notes"))).toBe(true));
  const sent = JSON.parse(String(requests.find(item => item.init?.method === "PATCH")!.init!.body));
  expect(sent.override_revision).toBe(0);
  expect(sent.title).toBeUndefined();
});
