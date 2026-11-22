import {fireEvent, render, screen, waitFor} from "@testing-library/react";
import {MemoryRouter, Route, Routes, useLocation} from "react-router-dom";
import {beforeEach, expect, it, vi} from "vitest";
import {GenerationPage} from "./GenerationPage";

const run = {
  id: "run-1",
  prompt_job_id: "job-1",
  remote_profile_id: "remote-1",
  workflow_profile_id: "workflow-1",
  state: "running",
  progress: 0.5,
  status_message: "ComfyUI 正在生成",
  created_at: "2026-08-26T00:00:00+00:00",
  updated_at: "2026-08-26T00:01:00+00:00",
  completed_at: null,
  artifact_count: 0,
  available_actions: ["retry_check"],
  error: null,
};

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  sessionStorage.setItem("anima-v3-session", "session-token");
  vi.restoreAllMocks();
});

function Destination() { const location=useLocation(); return <h1>继续编辑：{location.pathname}{location.search}</h1>; }
function showPage(remoteEnabled = true) {
  return render(<MemoryRouter initialEntries={["/generate"]}><Routes>
    <Route path="/generate" element={<GenerationPage remoteEnabled={remoteEnabled} />} />
    <Route path="/workbench" element={<Destination />} />
    <Route path="/moss" element={<Destination />} />
  </Routes></MemoryRouter>);
}

const source = {workspace_revision:12,positive_prompt:"woman, blue coat, evening light",negative_prompt:"blurry",model_profile:"anima_base_v1",settings:{seed:"9223372036854775807"}};

it("renders generation progress and queues a recovery action", async () => {
  const recovered = {...run, status_message: "等待恢复远程任务", available_actions: []};
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [run]}), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify(recovered), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [recovered]}), {status: 200}));

  showPage();
  expect(await screen.findByText("ComfyUI 正在生成")).toBeInTheDocument();
  expect(screen.getByText("50%")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "重新检查远端"}));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({action: "retry_check"});
});

it("explains unavailable generation without internal runtime setup language", () => {
  showPage(false);
  expect(screen.getByRole("heading", {name: "远程生成尚未启用"})).toBeInTheDocument();
  expect(screen.getByText(/设置.*执行环境/)).toBeInTheDocument();
  expect(screen.queryByText(/V2|runtime|数据库|Windows 凭据/)).not.toBeInTheDocument();
});

it("leads task cards with their source prompt and revision and keeps IDs in technical details", async () => {
  vi.spyOn(globalThis,"fetch").mockResolvedValue(new Response(JSON.stringify({items:[{...run,state:"completed",available_actions:[],source}]})));
  showPage();
  expect(await screen.findByRole("heading",{name:source.positive_prompt})).toBeInTheDocument();
  expect(screen.getByText("来源修订 12")).toBeInTheDocument();
  const details=screen.getByText("技术详情").closest("details")!;
  expect(details).not.toHaveAttribute("open");
  expect(details).toContainElement(screen.getByText("run-1"));
  expect(details).toContainElement(screen.getByText("remote-1"));
});

it.each([["anima_base_v1","/workbench"],["moss_image_sft_int8","/moss"]])("continues to the %s workspace only after its creation receipt", async (model,pathname) => {
  let finish: ((value:Response)=>void) | undefined;
  const fetchMock=vi.spyOn(globalThis,"fetch").mockImplementation(async(input,init)=>{
    if(!init?.method)return new Response(JSON.stringify({items:[{...run,state:"completed",available_actions:[],source}]}));
    expect(String(input)).toBe("/api/v3/generation-runs/run-1/workspace");
    expect(init.method).toBe("POST");expect(JSON.parse(String(init.body))).toEqual({});
    expect(new Headers(init.headers).get("Idempotency-Key")).toBeTruthy();
    return new Promise<Response>(resolve=>{finish=resolve;});
  });
  showPage();
  fireEvent.click(await screen.findByRole("button",{name:"从这次生成继续"}));
  fireEvent.click(screen.getByRole("button",{name:"正在打开…"}));
  await waitFor(()=>expect(finish).toBeDefined());
  expect(screen.queryByRole("heading",{name:/继续编辑/})).not.toBeInTheDocument();
  expect(screen.getByRole("button",{name:"正在打开…"})).toBeDisabled();
  finish!(new Response(JSON.stringify({id:"workspace_continued",revision:1,draft:{model_profile:model}}),{status:201}));
  expect(await screen.findByRole("heading",{name:`继续编辑：${pathname}?workspace=workspace_continued`})).toBeInTheDocument();
  expect(fetchMock.mock.calls.filter(([,init])=>init?.method==="POST")).toHaveLength(1);
});

it("stays on the task when the confirmed workspace has an unsupported model",async()=>{
  vi.spyOn(globalThis,"fetch").mockImplementation(async(_input,init)=>new Response(JSON.stringify(!init?.method
    ?{items:[{...run,state:"completed",available_actions:[],source}]}:{id:"workspace_unknown",revision:1,draft:{model_profile:"unrecognized_model"}})));
  showPage();fireEvent.click(await screen.findByRole("button",{name:"从这次生成继续"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("unrecognized_model");
  expect(screen.getByRole("button",{name:"从这次生成继续"})).toBeEnabled();
  expect(screen.queryByRole("heading",{name:/继续编辑/})).not.toBeInTheDocument();
});

it("keeps an incomplete continuation receipt recoverable without leaving the task page", async () => {
  const fetchMock=vi.spyOn(globalThis,"fetch").mockImplementation(async(_input,init)=>new Response(JSON.stringify(!init?.method
    ?{items:[{...run,state:"completed",available_actions:[],source}]}:{id:"workspace_incomplete"}),{status:200}));
  showPage();fireEvent.click(await screen.findByRole("button",{name:"从这次生成继续"}));
  expect(await screen.findByText(/创作回执不完整/)).toBeInTheDocument();
  expect(screen.queryByRole("heading",{name:/继续编辑/})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"从这次生成继续"}));
  await waitFor(()=>expect(fetchMock.mock.calls.filter(([,init])=>init?.method==="POST")).toHaveLength(2));
  const posts=fetchMock.mock.calls.filter(([,init])=>init?.method==="POST");
  expect(new Headers(posts[0][1]?.headers).get("Idempotency-Key")).toBe(new Headers(posts[1][1]?.headers).get("Idempotency-Key"));
});

it("preserves the same continuation key and body after a lost response and page remount", async () => {
  const fetchMock=vi.spyOn(globalThis,"fetch").mockImplementation(async(input,init)=>{
    if(!init?.method)return new Response(JSON.stringify({items:[{...run,state:"completed",available_actions:[],source}]}));
    expect(String(input)).toBe("/api/v3/generation-runs/run-1/workspace");
    throw new TypeError("response lost");
  });
  const page=showPage();
  fireEvent.click(await screen.findByRole("button",{name:"从这次生成继续"}));
  expect(await screen.findByText(/无法连接本地服务/)).toBeInTheDocument();
  expect(screen.queryByRole("heading",{name:/继续编辑/})).not.toBeInTheDocument();
  page.unmount();
  fetchMock.mockImplementation(async(_input,init)=>!init?.method
    ?new Response(JSON.stringify({items:[{...run,state:"completed",available_actions:[],source}]}))
    :new Response(JSON.stringify({id:"workspace_continued",revision:1,draft:{model_profile:"anima_base_v1"}}),{status:201}));
  showPage();fireEvent.click(await screen.findByRole("button",{name:"从这次生成继续"}));
  expect(await screen.findByRole("heading",{name:/继续编辑/})).toBeInTheDocument();
  const posts=fetchMock.mock.calls.filter(([,init])=>init?.method==="POST");expect(posts).toHaveLength(2);
  expect(new Headers(posts[0][1]?.headers).get("Idempotency-Key")).toBe(new Headers(posts[1][1]?.headers).get("Idempotency-Key"));
  expect(posts[0][1]?.body).toBe(posts[1][1]?.body);
});

it("loads established artifact thumbnails once while refreshing task status", async () => {
  const completed={...run,state:"completed",artifact_count:1,available_actions:[],source};
  const fetchMock=vi.spyOn(globalThis,"fetch").mockImplementation(async input=>new Response(JSON.stringify(String(input).endsWith("/artifacts")
    ?{items:[{id:"image-1",thumbnail_url:"/api/v3/gallery/assets/thumbnail?path=result.png",content_url:"/api/v3/gallery/assets/content?path=result.png",removed:false}]}
    :{items:[completed]})));
  showPage();
  expect(await screen.findByRole("img",{name:"这次生成的结果预览"})).toHaveAttribute("src","/api/v3/gallery/assets/thumbnail?path=result.png");
  fireEvent.click(screen.getByRole("button",{name:"刷新状态"}));
  await waitFor(()=>expect(fetchMock.mock.calls.filter(([input])=>String(input).includes("generation-runs?"))).toHaveLength(2));
  expect(fetchMock.mock.calls.filter(([input])=>String(input).endsWith("/artifacts"))).toHaveLength(1);
});
