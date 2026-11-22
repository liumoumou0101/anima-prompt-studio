import {act, cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {GenerationComparison} from "./GenerationComparison";
import {resetGalleryStoreForTests} from "../lib/galleryStore";
import type {GalleryAsset, GenerationRunRecord} from "../lib/types";

function run(id: string, settings: Record<string, string | number> = {}): GenerationRunRecord {
  return {id, prompt_job_id: id, remote_profile_id: "server1", workflow_profile_id: "workflow1", state: "completed",
    progress: 1, status_message: "完成", created_at: "2026-09-18T03:00:00Z", updated_at: "2026-09-18T03:00:00Z",
    completed_at: "2026-09-18T03:00:00Z", artifact_count: 2, available_actions: [], error: null,
    source: {workspace_revision: 2, positive_prompt: id, negative_prompt: "", model_profile: "anima_base_v1",
      settings: {width: 896, height: 1152, steps: 28, cfg: 4.5, sampler: "euler", scheduler: "normal", seed: -1, ...settings}}};
}
function asset(batch: string, image: number, seed: string | number, width = 896): GalleryAsset {
  return {id: `${batch}-${image}`, path: `${batch}/${image}.png`, name: `${batch} 图片 ${image}`, project: "test",
    model_profile: "anima_base_v1", batch_id: batch, batch_title: batch, created_at: "2026-09-18", positive_prompt: batch,
    negative_prompt: "", width, height: 1152, byte_size: 10, generation_params: {seed}, source: "generated", state: "",
    candidate: {id: "", lane: "", versions: {}}, content_url: `/images/${batch}/${image}.png`, thumbnail_url: `/thumb/${batch}/${image}.png`};
}
let runs: GenerationRunRecord[];
let assets: GalleryAsset[];
let unavailable = false;
beforeEach(() => {
  localStorage.clear();
  sessionStorage.setItem("anima-v3-session", "test"); resetGalleryStoreForTests();
  runs = [run("current", {steps: 35}), run("baseline", {seed: "8798399215689017476"}), run("next")];
  assets = [asset("current", 1, -1), asset("current", 2, 22, 1024),
    asset("baseline", 1, 11), asset("baseline", 2, "8798399215689017476"), asset("next", 1, 33)];
  unavailable = false;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    expect(init?.method || "GET").toBe("GET");
    const url = String(input);
    if (url.includes("/gallery/assets?")) return new Response(JSON.stringify({items: assets, projects: [], models: [], root: "", trash_count: 0}));
    const id = /generation-runs\/([^/]+)\/artifacts/.exec(url)?.[1];
    if (id) {
      if (id === "baseline" && unavailable) return new Response(JSON.stringify({error: {code: "request_failed", message: "暂时无法读取"}}), {status: 503});
      return new Response(JSON.stringify({items: assets.filter(item => item.batch_id === id).map(item => ({id: item.id,
        path: item.path, removed: false, content_url: item.content_url, thumbnail_url: item.thumbnail_url}))}));
    }
    const runId = /generation-runs\/([^/]+)$/.exec(url)?.[1];
    if (runId) {
      const result = runs.find(item => item.id === runId);
      return result ? new Response(JSON.stringify(result))
        : new Response(JSON.stringify({error: {code: "generation_run_not_found", message: "生成任务不存在。"}}), {status: 404});
    }
    throw new Error(`Unexpected read: ${url}`);
  });
});
afterEach(() => {cleanup(); vi.restoreAllMocks(); resetGalleryStoreForTests();});

async function chooseBaseline() {
  fireEvent.click(screen.getByText("固定图片对比", {selector: "summary"}));
  fireEvent.change(screen.getByLabelText("选择基准批次"), {target: {value: "baseline"}});
  await waitFor(() => expect(screen.getByLabelText("选择基准图片").querySelectorAll("option")).toHaveLength(2));
  fireEvent.change(screen.getByLabelText("选择基准图片"), {target: {value: "baseline-2"}});
  fireEvent.click(screen.getByRole("button", {name: "固定为对比基准"}));
  await screen.findByRole("table", {name: "生成参数对比"});
}

it("pins the selected single image and shows actual output dimensions and changed records", async () => {
  render(<GenerationComparison currentRun={runs[0]} runs={runs} />);
  await chooseBaseline();
  fireEvent.change(screen.getByLabelText("选择当前图片"), {target: {value: "current-2"}});
  expect(screen.getByAltText("固定基准：baseline 图片 2")).toHaveAttribute("src", "/images/baseline/2.png");
  expect(screen.getByAltText("当前图片：current 图片 2")).toHaveAttribute("src", "/images/current/2.png");
  const dimensions = screen.getByRole("row", {name: /输出图像尺寸/});
  expect(dimensions).toHaveTextContent("896 × 1152"); expect(dimensions).toHaveTextContent("1024 × 1152");
  expect(dimensions).toHaveTextContent("不同");
  const steps = screen.getByRole("row", {name: /步数/});
  expect(steps).toHaveTextContent("28"); expect(steps).toHaveTextContent("35"); expect(steps).toHaveTextContent("不同");
  expect(screen.getByRole("row", {name: /图片批次记录种子/})).toHaveTextContent("8798399215689017476");
});

it("keeps the pinned image when current batch and available-run list change", async () => {
  const {rerender} = render(<GenerationComparison currentRun={runs[0]} runs={runs} />);
  await chooseBaseline();
  rerender(<GenerationComparison currentRun={runs[2]} runs={[runs[2]]} />);
  expect(screen.getByAltText("固定基准：baseline 图片 2")).toHaveAttribute("src", "/images/baseline/2.png");
  await screen.findByAltText("当前图片：next 图片 1");
});

it("marks missing and random seed evidence unknown instead of claiming exact same-seed comparison", async () => {
  runs[0].source = null;
  assets = assets.filter(item => item.batch_id !== "current");
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => String(input).includes("/current/artifacts")
    ? new Response(JSON.stringify({items: [{id: "current-unknown", path: "current/unknown.png", removed: false,
      content_url: "/images/current/unknown.png", thumbnail_url: null}]})) : original(input, init));
  render(<GenerationComparison currentRun={runs[0]} runs={runs} />);
  await chooseBaseline();
  expect(screen.getByRole("row", {name: /图片批次记录种子/})).toHaveTextContent("未知");
  expect(screen.getByRole("row", {name: /步数/})).toHaveTextContent("未知");
  expect(screen.getByText(/不能据此确认逐图实际种子/)).toBeInTheDocument();
});

it("does not treat unsafe numeric seeds as exact integers", async () => {
  assets.find(item => item.id === "current-1")!.generation_params!.seed = 8798399215689017476;
  render(<GenerationComparison currentRun={runs[0]} runs={runs} />);
  await chooseBaseline();
  expect(screen.getByRole("row", {name: /图片批次记录种子/})).toHaveTextContent("未知");
});

it("compares equivalent numeric parameter strings without false differences", async () => {
  delete runs[0].source!.settings.cfg;
  assets.find(item => item.id === "current-1")!.generation_params!.cfg = "4.500";
  render(<GenerationComparison currentRun={runs[0]} runs={runs} />);
  await chooseBaseline();
  expect(screen.getByRole("row", {name: /CFG/})).toHaveTextContent("记录一致");
});

it("can retry a failed baseline read without losing the selected batch", async () => {
  unavailable = true;
  render(<GenerationComparison currentRun={runs[0]} runs={runs} />);
  fireEvent.click(screen.getByText("固定图片对比", {selector: "summary"}));
  fireEvent.change(screen.getByLabelText("选择基准批次"), {target: {value: "baseline"}});
  await screen.findByText("暂时无法读取");
  expect(screen.getByRole("button", {name: "固定为对比基准"})).toBeDisabled();
  unavailable = false;
  fireEvent.click(screen.getByRole("button", {name: "重新读取基准图片"}));
  await waitFor(() => expect(screen.getByRole("button", {name: "固定为对比基准"})).toBeEnabled());
  expect(screen.getByLabelText("选择基准批次")).toHaveValue("baseline");
});

it("reuses the pinned image record only through the caller's explicit action", async () => {
  const reuse = vi.fn();
  render(<GenerationComparison currentRun={runs[0]} runs={runs} onReuseSettings={reuse} />);
  await chooseBaseline();
  expect(reuse).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", {name: "沿用基准图片的记录参数"}));
  expect(reuse).toHaveBeenCalledWith(runs[1], assets.find(item => item.id === "baseline-2"));
});

const savedKey = "anima-v3-comparison-baseline:workspace-one";
function savedBaseline() {
  localStorage.setItem(savedKey, JSON.stringify({version: 1, workspaceId: "workspace-one", runId: "baseline", artifactId: "baseline-2"}));
}
function openComparison() {
  fireEvent.click(screen.getByText("固定图片对比", {selector: "summary"}));
}

it("restores the exact pinned image after reopening even when its batch is outside recent runs", async () => {
  const first = render(<GenerationComparison workspaceId="workspace-one" currentRun={runs[0]} runs={runs} />);
  await chooseBaseline();
  expect(JSON.parse(localStorage.getItem(savedKey)!)).toEqual({version: 1, workspaceId: "workspace-one", runId: "baseline", artifactId: "baseline-2"});
  first.unmount();
  render(<GenerationComparison workspaceId="workspace-one" currentRun={runs[2]} runs={[runs[2]]} />);
  openComparison();
  expect(await screen.findByAltText("固定基准：baseline 图片 2")).toHaveAttribute("src", "/images/baseline/2.png");
  expect(screen.getByLabelText("选择基准批次")).toHaveValue("baseline");
});

it("isolates pinned baselines when switching workspaces and restores each workspace independently", async () => {
  const {rerender} = render(<GenerationComparison workspaceId="workspace-one" currentRun={runs[0]} runs={runs} />);
  await chooseBaseline();
  rerender(<GenerationComparison workspaceId="workspace-two" currentRun={runs[0]} runs={runs} />);
  expect(screen.queryByAltText("固定基准：baseline 图片 2")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "清除对比基准"})).not.toBeInTheDocument();
  rerender(<GenerationComparison workspaceId="workspace-one" currentRun={runs[0]} runs={runs} />);
  openComparison();
  expect(await screen.findByAltText("固定基准：baseline 图片 2")).toBeInTheDocument();
});

it("removes the saved baseline when cleared so it cannot return after reopening", async () => {
  const first = render(<GenerationComparison workspaceId="workspace-one" currentRun={runs[0]} runs={runs} />);
  await chooseBaseline();
  expect(localStorage.getItem(savedKey)).not.toBeNull();
  fireEvent.click(screen.getByRole("button", {name: "清除对比基准"}));
  expect(localStorage.getItem(savedKey)).toBeNull();
  first.unmount();
  render(<GenerationComparison workspaceId="workspace-one" currentRun={runs[0]} runs={runs} />);
  openComparison();
  expect(screen.queryByAltText("固定基准：baseline 图片 2")).not.toBeInTheDocument();
});

it.each(["{broken", JSON.stringify({version: 1, workspaceId: "workspace-two", runId: "baseline", artifactId: "baseline-2"}),
  JSON.stringify({version: 1, workspaceId: "workspace-one", runId: {}, artifactId: "baseline-2"})])
("ignores corrupt or mismatched saved IDs with a visible warning: %s", async stored => {
  localStorage.setItem(savedKey, stored);
  render(<GenerationComparison workspaceId="workspace-one" currentRun={runs[0]} runs={runs} />);
  openComparison();
  expect(await screen.findByText(/保存的对比基准记录无效/)).toBeInTheDocument();
  expect(screen.queryByAltText("固定基准：baseline 图片 2")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("选择基准批次"), {target: {value: "baseline"}});
  await waitFor(() => expect(screen.getByRole("button", {name: "固定为对比基准"})).toBeEnabled());
});

it("keeps comparison usable and explains that blocked browser storage prevents persistence", async () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(function (this: Storage, key) {
    if (this === localStorage) throw new DOMException("blocked", "SecurityError");
    return key === "anima-v3-session" ? "test" : null;
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {throw new DOMException("full", "QuotaExceededError");});
  render(<GenerationComparison workspaceId="workspace-one" currentRun={runs[0]} runs={runs} />);
  expect(screen.getByText(/无法读取本机保存的对比基准/)).toBeInTheDocument();
  await chooseBaseline();
  expect(screen.getByAltText("固定基准：baseline 图片 2")).toBeInTheDocument();
  expect(screen.getByText(/无法保存对比基准/)).toBeInTheDocument();
});

it("reports failed removal instead of claiming the saved baseline was cleared permanently", async () => {
  render(<GenerationComparison workspaceId="workspace-one" currentRun={runs[0]} runs={runs} />);
  await chooseBaseline();
  vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {throw new DOMException("blocked", "SecurityError");});
  fireEvent.click(screen.getByRole("button", {name: "清除对比基准"}));
  expect(screen.queryByAltText("固定基准：baseline 图片 2")).not.toBeInTheDocument();
  expect(screen.getByText(/无法清除已保存的对比基准/)).toBeInTheDocument();
});

it("does not silently substitute another image when the saved image was deleted", async () => {
  savedBaseline();
  assets = assets.filter(item => item.id !== "baseline-2");
  render(<GenerationComparison workspaceId="workspace-one" currentRun={runs[0]} runs={runs} />);
  openComparison();
  expect(await screen.findByText(/保存的对比基准已不可用/)).toBeInTheDocument();
  expect(screen.queryByAltText(/固定基准：/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "清除对比基准"}));
  expect(localStorage.getItem(savedKey)).toBeNull();
});

it("retains saved identifiers after a temporary failure and restores on retry", async () => {
  savedBaseline(); unavailable = true;
  render(<GenerationComparison workspaceId="workspace-one" currentRun={runs[0]} runs={runs} />);
  openComparison();
  expect(await screen.findByText(/无法恢复保存的对比基准/)).toBeInTheDocument();
  expect(localStorage.getItem(savedKey)).not.toBeNull();
  unavailable = false;
  fireEvent.click(screen.getByRole("button", {name: "重新恢复对比基准"}));
  expect(await screen.findByAltText("固定基准：baseline 图片 2")).toBeInTheDocument();
});

it("explains a missing saved batch and lets the user remove its saved identifiers", async () => {
  savedBaseline(); runs = runs.filter(item => item.id !== "baseline");
  render(<GenerationComparison workspaceId="workspace-one" currentRun={runs[0]} runs={runs} />);
  openComparison();
  expect(await screen.findByText(/保存的对比基准已不可用，生成批次可能已删除/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "清除对比基准"}));
  expect(localStorage.getItem(savedKey)).toBeNull();
});

it.each(["clear", "switch"])("ignores a late restore response after %s", async action => {
  savedBaseline();
  let release!: (response: Response) => void;
  const deferred = new Promise<Response>(resolve => { release = resolve; });
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation((input, init) => String(input) === "/api/v3/generation-runs/baseline"
    ? deferred : original(input, init));
  const {rerender} = render(<GenerationComparison workspaceId="workspace-one" currentRun={runs[0]} runs={runs} />);
  openComparison();
  await screen.findByText("正在恢复保存的对比基准…");
  if (action === "clear") fireEvent.click(screen.getByRole("button", {name: "清除对比基准"}));
  else rerender(<GenerationComparison workspaceId="workspace-two" currentRun={runs[0]} runs={runs} />);
  await act(async () => {release(new Response(JSON.stringify(runs[1]))); await deferred;});
  expect(screen.queryByAltText(/固定基准：/)).not.toBeInTheDocument();
  expect(screen.queryByText("正在恢复保存的对比基准…")).not.toBeInTheDocument();
  expect(localStorage.getItem("anima-v3-comparison-baseline:workspace-two")).toBeNull();
});

it.each([
  ["固定基准：baseline 图片 2", "重新加载基准图片", "/images/baseline/2.png"],
  ["当前图片：current 图片 2", "重新加载当前图片", "/images/current/2.png"],
])("retries a failed %s without changing the selected artifact or persisted baseline", async (alt, retry, src) => {
  render(<GenerationComparison workspaceId="workspace-one" currentRun={runs[0]} runs={runs} />);
  await chooseBaseline();
  fireEvent.change(screen.getByLabelText("选择当前图片"), {target: {value: "current-2"}});
  const saved = localStorage.getItem(savedKey);
  const failedImage = screen.getByAltText(alt);
  fireEvent.error(failedImage);
  expect(screen.queryByAltText(alt)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: retry}));
  const reloadedImage = screen.getByAltText(alt);
  expect(reloadedImage).toHaveAttribute("src", src);
  expect(reloadedImage).not.toBe(failedImage);
  expect(screen.getByLabelText("选择当前图片")).toHaveValue("current-2");
  expect(screen.getByLabelText("选择基准图片")).toHaveValue("baseline-2");
  expect(localStorage.getItem(savedKey)).toBe(saved);
  expect(screen.getByRole("table", {name: "生成参数对比"})).toBeInTheDocument();
});
