import {act, cleanup, fireEvent, render, screen, within} from "@testing-library/react";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {WorkbenchHistory} from "./WorkbenchHistory";
import {WorkbenchImageResults} from "./WorkbenchImageResults";
import {emptyRequirements, localFromRecord, type ConversationRecord} from "../lib/conversation";
import type {GenerationRunRecord} from "../lib/types";

const record: ConversationRecord = {id: "history-test", title: "外套练习", revision: 3,
  created_at: "2026-09-21T10:00:00Z", updated_at: "2026-09-21T10:03:00Z", draft: {
    positive_text: "", excluded_text: "", model_profile: "anima", mode: "faithful",
    requirements: {...emptyRequirements(), contract: "anima-requirements/1", revision: 1},
    compiled: {positive: "red coat", negative: "", compiled_token: "cmp", source: "llm"}, compile_state: "fresh",
    conversation_events: [{id: "event-red", delta: "外套换成红色", changed_layers: ["subject"], warnings: [], created_at: "2026-09-21T10:01:00Z", after_revision: 2}]}};
const source = {workspace_revision: 3, positive_prompt: "red coat, actual submitted detail", negative_prompt: "blurry",
  model_profile: "anima", settings: {width: 640, height: 832, steps: 10, cfg: 1, sampler: "euler", scheduler: "normal", seed: -1, batch_size: 2}};
const first: GenerationRunRecord = {id: "run-first", prompt_job_id: "job", remote_profile_id: "server", workflow_profile_id: "workflow",
  state: "completed", progress: 1, status_message: "完成", created_at: "2026-09-21T10:02:00Z", updated_at: "2026-09-21T10:02:00Z",
  completed_at: "2026-09-21T10:02:00Z", artifact_count: 2, available_actions: [], error: null, source};
const second: GenerationRunRecord = {...first, id: "run-second", created_at: "2026-09-21T10:04:00Z",
  source: {...source, positive_prompt: "blue coat", settings: {...source.settings, seed: "8798399215689017476"}}};
const versions = [record, {...record, revision: 2}, {...record, revision: 1, draft: {...record.draft,
  compiled: {...record.draft.compiled!, positive: "blue coat"}, conversation_events: []}}];
beforeEach(() => {
  sessionStorage.setItem("anima-v3-session", "test");
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    expect(init?.method || "GET").toBe("GET");
    const url = String(input);
    if (url.includes("/versions?")) return new Response(JSON.stringify({items: versions}));
    const runId = /generation-runs\/([^/]+)\/artifacts/.exec(url)?.[1];
    if (runId) return new Response(JSON.stringify({items: [1, 2].map(number => ({id: `${runId}-${number}`, path: `${runId}/${number}.png`,
      content_url: `/images/${runId}/${number}.png`, thumbnail_url: `/thumb/${runId}/${number}.png`, removed: false}))}));
    throw new Error(`Unexpected request: ${url}`);
  });
});
afterEach(() => {cleanup(); vi.restoreAllMocks();});

it("links Chinese intent and a thumbnail to exact submitted prompts, and permits restoring a version without images", async () => {
  const restoreVersion = vi.fn(), restoreRun = vi.fn();
  render(<WorkbenchHistory record={record} runs={[first]} onRestoreVersion={restoreVersion} onRestoreRun={restoreRun} draftRecovery={<p>本地草稿入口</p>} />);
  const card = await screen.findByRole("article", {name: "生图记录：外套换成红色"});
  expect(await within(card).findByAltText("外套换成红色的生成图片")).toHaveAttribute("src", "/thumb/run-first/1.png");
  expect(card).toHaveTextContent(source.positive_prompt);
  fireEvent.click(within(card).getByRole("button", {name: "从这张继续"}));
  expect(restoreRun).toHaveBeenCalledWith(first, false, expect.objectContaining({revision: 3}));
  const prompt = screen.getByRole("article", {name: "提示词记录：外套换成红色"});
  expect(prompt).toHaveTextContent("尚未生成图片");
  fireEvent.click(within(prompt).getByRole("button", {name: "恢复到这里"}));
  expect(restoreVersion).toHaveBeenCalledWith(expect.objectContaining({revision: 2}));
  expect(screen.getByText("本地草稿入口")).toBeInTheDocument();
});

it("disables complete restoration of incomplete source settings but keeps prompt-only restoration available", async () => {
  const incomplete = {...first, source: {...source, settings: {seed: -1}}};
  const restore = vi.fn();
  render(<WorkbenchImageResults record={record} local={localFromRecord(record)} runs={[incomplete]} run={incomplete} onSelectRun={() => {}} onRestoreRun={restore} />);
  await screen.findByAltText("当前图片：第 1 张");
  expect(screen.getByRole("button", {name: "从这张继续"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button", {name: "只用提示词"}));
  expect(restore).toHaveBeenCalledWith(incomplete, true, expect.anything());
  expect(screen.getByText(/生成设置记录不完整/)).toBeInTheDocument();
});

it("compares selected individual images from two batches and reports submitted input independently of the editor", async () => {
  render(<WorkbenchImageResults record={record} local={{...localFromRecord(record), positive: "unsaved new prompt"}} runs={[second, first]} run={second} onSelectRun={() => {}} onRestoreRun={() => {}} />);
  await screen.findByAltText("当前图片：第 1 张");
  fireEvent.click(screen.getByRole("button", {name: "对比图片"}));
  fireEvent.change(screen.getByLabelText("对比批次"), {target: {value: first.id}});
  await screen.findByAltText("对比图片：第 1 张");
  fireEvent.change(screen.getByLabelText("对比图片"), {target: {value: "run-first-2"}});
  expect(screen.getByAltText("对比图片：第 2 张")).toHaveAttribute("src", "/images/run-first/2.png");
  fireEvent.click(screen.getByRole("button", {name: "查看实际输入"}));
  const details = screen.getByRole("region", {name: "实际提交输入"});
  expect(details).toHaveTextContent("blue coat");
  expect(details).not.toHaveTextContent("unsaved new prompt");
  expect(details).toHaveTextContent("8798399215689017476");
  expect(details).toHaveTextContent(/不保证对应所选单张/);
});

it("keeps the newly selected batch when an older image request finishes late", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  let complete!: (response: Response) => void;
  vi.mocked(fetch).mockImplementation((input, init) => String(input).includes("run-first/artifacts")
    ? new Promise(resolve => {complete = resolve;}) : original(input, init));
  const props = {record, local: localFromRecord(record), runs: [first, second], onSelectRun: vi.fn(), onRestoreRun: vi.fn()};
  const {rerender} = render(<WorkbenchImageResults {...props} run={first} />);
  rerender(<WorkbenchImageResults {...props} run={second} />);
  expect(await screen.findByAltText("当前图片：第 1 张")).toHaveAttribute("src", "/images/run-second/1.png");
  await act(async () => {complete(new Response(JSON.stringify({items: [{id: "old", path: "old.png", content_url: "/wrong-old.png", thumbnail_url: "/wrong-old.png", removed: false}]})));});
  expect(screen.getByAltText("当前图片：第 1 张")).toHaveAttribute("src", "/images/run-second/1.png");
});

it("allows a failed image read to be retried without losing the run snapshot", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  let failed = false;
  vi.mocked(fetch).mockImplementation((input, init) => {
    if (!failed && String(input).includes("/artifacts")) {failed = true; return Promise.resolve(new Response(JSON.stringify({error: {code: "temporary", message: "图片索引暂时不可用"}}), {status: 503}));}
    return original(input, init);
  });
  render(<WorkbenchImageResults record={record} local={localFromRecord(record)} runs={[first]} run={first} onSelectRun={() => {}} onRestoreRun={() => {}} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("图片索引暂时不可用");
  fireEvent.click(screen.getByRole("button", {name: "重新读取图片"}));
  expect(await screen.findByAltText("当前图片：第 1 张")).toHaveAttribute("src", "/images/run-first/1.png");
  fireEvent.click(screen.getByRole("button", {name: "查看实际输入"}));
  expect(screen.getByRole("region", {name: "实际提交输入"})).toHaveTextContent(source.positive_prompt);
});
