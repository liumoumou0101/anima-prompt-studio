import {act, cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
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
afterEach(() => {cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals();});

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
  fireEvent.click(screen.getByText("添加参考图"));
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

it("defers a completed local scan refresh while edits are unsaved", async () => {
  let syncReads = 0;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input); requests.push({url, init});
    if (url.endsWith("/local-sync")) {
      syncReads += 1;
      return new Response(JSON.stringify(syncReads === 1
        ? {status:"scanning",run_id:9,counts:{created:0,updated:0,unchanged:0,deleted_preserved:0},total:0,message:"",completed_at:null}
        : {status:"ready",run_id:9,counts:{created:1,updated:0,unchanged:1,deleted_preserved:0},total:2,message:"",completed_at:"2026-09-17T08:00:00Z"}));
    }
    if (url.endsWith("/facets")) return new Response(JSON.stringify({models: [], artists: []}));
    if (url.includes("?")) return new Response(JSON.stringify({items:[example],next_cursor:null,official_pack:{ready:true}}));
    return new Response(JSON.stringify(example));
  });
  render(<ReferenceLibrary standalone exampleId="ex_a" onStart={async () => {}} />);
  const notes = await screen.findByLabelText("我的笔记");
  fireEvent.change(notes, {target: {value: "扫描期间未保存"}});
  const listRequestsBefore = requests.filter(item => item.url.includes("reference-examples?")).length;
  expect(await screen.findByRole("button", {name: "刷新案例列表"}, {timeout: 1800})).toBeInTheDocument();
  expect(screen.getByLabelText("我的笔记")).toHaveValue("扫描期间未保存");
  expect(requests.filter(item => item.url.includes("reference-examples?")).length).toBe(listRequestsBefore);
});

it("refreshes list, facets, and a clean selected record after a local scan", async () => {
  let syncReads = 0;
  let detailReads = 0;
  const refreshed = {...example, revision: 3, source_version: "3", provenance: {reference_metadata: {why: "扫描后的新说明"}}};
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input); requests.push({url, init});
    if (url.endsWith("/local-sync")) {
      syncReads += 1;
      return new Response(JSON.stringify(syncReads === 1
        ? {status:"scanning",run_id:10,counts:{created:0,updated:0,unchanged:0,deleted_preserved:0},total:0,message:"",completed_at:null}
        : {status:"ready",run_id:10,counts:{created:1,updated:0,unchanged:1,deleted_preserved:0},total:2,message:"",completed_at:"2026-09-17T08:00:00Z"}));
    }
    if (init?.method === "PATCH") {
      const body = JSON.parse(String(init.body));
      return new Response(JSON.stringify({...refreshed, title: body.title, notes: body.notes}));
    }
    if (url.endsWith("/facets")) return new Response(JSON.stringify({models: [], artists: []}));
    if (url.includes("?")) return new Response(JSON.stringify({items:[example],next_cursor:null,official_pack:{ready:true}}));
    detailReads += 1;
    return new Response(JSON.stringify(detailReads === 1 ? example : refreshed));
  });
  render(<ReferenceLibrary standalone exampleId="ex_a" onStart={async () => {}} />);
  const notes = await screen.findByLabelText("我的笔记");
  const listRequestsBefore = requests.filter(item => item.url.includes("reference-examples?")).length;
  const facetRequestsBefore = requests.filter(item => item.url.endsWith("/facets")).length;
  await waitFor(() => expect(requests.filter(item => item.url.includes("reference-examples?")).length).toBeGreaterThan(listRequestsBefore), {timeout: 1800});
  expect(requests.filter(item => item.url.endsWith("/facets")).length).toBeGreaterThan(facetRequestsBefore);
  expect(notes).toHaveValue("");
  expect(screen.getByRole("heading", {name: "水彩参考"})).toBeInTheDocument();
  expect(screen.getByText("扫描后的新说明")).toBeInTheDocument();
  fireEvent.change(notes, {target: {value: "基于新版本的笔记"}});
  fireEvent.click(screen.getByRole("button", {name: "保存标题与笔记"}));
  await waitFor(() => expect(requests.some(item => item.init?.method === "PATCH")).toBe(true));
  expect(JSON.parse(String(requests.find(item => item.init?.method === "PATCH")!.init!.body)).revision).toBe(3);
});

it("defers a completed local scan while changed filters have not been applied", async () => {
  let syncReads = 0;
  let resolveSearch!: (response: Response) => void;
  const pendingSearch = new Promise<Response>(resolve => {resolveSearch = resolve;});
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input); requests.push({url, init});
    if (url.endsWith("/local-sync")) {
      syncReads += 1;
      return new Response(JSON.stringify(syncReads === 1
        ? {status:"scanning",run_id:11,counts:{created:0,updated:0,unchanged:0,deleted_preserved:0},total:0,message:"",completed_at:null}
        : {status:"ready",run_id:11,counts:{created:0,updated:0,unchanged:1,deleted_preserved:0},total:1,message:"",completed_at:"2026-09-17T08:00:00Z"}));
    }
    if (url.endsWith("/facets")) return new Response(JSON.stringify({models: [], artists: []}));
    if (url.includes("q=%E5%B0%9A%E6%9C%AA%E5%BA%94%E7%94%A8%E7%9A%84%E7%AD%9B%E9%80%89")) return pendingSearch;
    if (url.includes("?")) return new Response(JSON.stringify({items:[example],next_cursor:null,official_pack:{ready:true}}));
    return new Response(JSON.stringify(example));
  });
  render(<ReferenceLibrary standalone onStart={async () => {}} />);
  await screen.findByText("已载入 1 / 1 条参考");
  fireEvent.change(screen.getByLabelText("搜索收藏"), {target: {value: "尚未应用的筛选"}});
  const listRequestsBefore = requests.filter(item => item.url.includes("reference-examples?")).length;
  expect(await screen.findByRole("button", {name: "刷新案例列表"}, {timeout: 1800})).toBeInTheDocument();
  expect(screen.getByLabelText("搜索收藏")).toHaveValue("尚未应用的筛选");
  expect(requests.filter(item => item.url.includes("reference-examples?")).length).toBe(listRequestsBefore + 1);
  resolveSearch(new Response(JSON.stringify({items:[example],next_cursor:null,official_pack:{ready:true},total:1})));
});

it("loads the next page once for repeated observer notifications, deduplicates, and stops at the end", async () => {
  let observerCallback!: IntersectionObserverCallback;
  let observerOptions: IntersectionObserverInit | undefined;
  vi.stubGlobal("IntersectionObserver", class {
    constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {observerCallback = callback; observerOptions = options;}
    observe() {} disconnect() {} unobserve() {} takeRecords() {return [];}
    readonly root = null; readonly rootMargin = ""; readonly thresholds = [];
  });
  let resolveNext!: (response: Response) => void;
  const nextPage = new Promise<Response>(resolve => {resolveNext = resolve;});
  const second = {...example, id: "ex_b", title: "炭笔参考"};
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input); requests.push({url, init});
    if (url.endsWith("/local-sync")) return new Response(JSON.stringify({status:"idle",run_id:0,counts:{created:0,updated:0,unchanged:0,deleted_preserved:0},total:0,message:"",completed_at:null}));
    if (url.endsWith("/facets")) return new Response(JSON.stringify({models: [], artists: []}));
    if (url.includes("cursor=")) return nextPage;
    return new Response(JSON.stringify({items:[example],next_cursor:"next",official_pack:{ready:true},total:2}));
  });
  render(<ReferenceLibrary standalone onStart={async () => {}} />);
  await screen.findByRole("button", {name: "加载更多"});
  expect(observerOptions).toMatchObject({root: null, rootMargin: "300px 0px"});
  act(() => {
    const entry = {isIntersecting: true} as IntersectionObserverEntry;
    observerCallback([entry], {} as IntersectionObserver);
    observerCallback([entry], {} as IntersectionObserver);
  });
  await waitFor(() => expect(requests.filter(item => item.url.includes("cursor=")).length).toBe(1));
  await act(async () => resolveNext(new Response(JSON.stringify({items:[example, second],next_cursor:null,official_pack:{ready:true},total:2}))));
  expect(await screen.findByText("已载入 2 / 2 条参考")).toBeInTheDocument();
  expect(screen.getByText("炭笔参考")).toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "加载更多"})).not.toBeInTheDocument();
  expect(screen.getByText("已显示全部结果。")).toBeInTheDocument();
});

it("does not apply a clean autosync detail response after the user starts editing", async () => {
  let syncReads = 0; let detailReads = 0;
  let resolveRefresh!: (response: Response) => void;
  let resolveManual!: (response: Response) => void;
  const refreshDetail = new Promise<Response>(resolve => {resolveRefresh = resolve;});
  const manualDetail = new Promise<Response>(resolve => {resolveManual = resolve;});
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input); requests.push({url, init});
    if (url.endsWith("/local-sync")) {
      syncReads += 1;
      return new Response(JSON.stringify(syncReads === 1
        ? {status:"scanning",run_id:12,counts:{created:0,updated:0,unchanged:0,deleted_preserved:0},total:0,message:"",completed_at:null}
        : {status:"ready",run_id:12,counts:{created:0,updated:1,unchanged:0,deleted_preserved:0},total:1,message:"",completed_at:"2026-09-17T08:00:00Z"}));
    }
    if (url.endsWith("/facets")) return new Response(JSON.stringify({models: [], artists: []}));
    if (url.includes("?")) return new Response(JSON.stringify({items:[example],next_cursor:null,official_pack:{ready:true},total:1}));
    detailReads += 1;
    return detailReads === 1 ? new Response(JSON.stringify(example)) : detailReads === 2 ? refreshDetail : manualDetail;
  });
  render(<ReferenceLibrary standalone exampleId="ex_a" onStart={async () => {}} />);
  const notes = await screen.findByLabelText("我的笔记");
  await waitFor(() => expect(detailReads).toBe(2), {timeout: 1800});
  fireEvent.change(notes, {target: {value: "详情请求期间编辑"}});
  resolveRefresh(new Response(JSON.stringify({...example, revision: 99, notes: {...example.notes, user_notes: "服务器覆盖"}})));
  await waitFor(() => expect(screen.getByLabelText("我的笔记")).toHaveValue("详情请求期间编辑"));
  const refreshButton = screen.getByRole("button", {name: "刷新案例列表"});
  fireEvent.change(screen.getByLabelText("我的笔记"), {target: {value: ""}});
  fireEvent.click(refreshButton);
  await waitFor(() => expect(detailReads).toBe(3));
  fireEvent.change(screen.getByLabelText("我的笔记"), {target: {value: "手动刷新期间再次编辑"}});
  resolveManual(new Response(JSON.stringify({...example, revision: 100, notes: {...example.notes, user_notes: "再次覆盖"}})));
  await waitFor(() => expect(screen.getByLabelText("我的笔记")).toHaveValue("手动刷新期间再次编辑"));
  expect(screen.getByRole("button", {name: "刷新案例列表"})).toBeInTheDocument();
});
