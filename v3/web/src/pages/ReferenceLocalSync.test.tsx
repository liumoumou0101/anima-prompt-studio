import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {apiRequest} from "../lib/api";
import {ReferenceLocalSync} from "./ReferenceLocalSync";

vi.mock("../lib/api", () => ({apiRequest: vi.fn()}));

const scanning = {status: "scanning", run_id: 7, counts: {created: 0, updated: 0, unchanged: 0, deleted_preserved: 0}, total: 0, message: "正在扫描", completed_at: null};
const ready = {status: "ready", run_id: 7, counts: {created: 2, updated: 1, unchanged: 3, deleted_preserved: 1}, total: 6, message: "扫描完成", completed_at: "2026-09-17T08:00:00Z"};

beforeEach(() => vi.mocked(apiRequest).mockReset());
afterEach(cleanup);

it("polls only while scanning, reports counts, and announces a newly completed run once", async () => {
  const completed = vi.fn();
  vi.mocked(apiRequest).mockResolvedValueOnce(scanning).mockResolvedValueOnce(scanning).mockResolvedValueOnce(ready);
  render(<ReferenceLocalSync pollMs={10} onCompleted={completed} />);

  expect(await screen.findByText("正在扫描本地案例…")).toBeInTheDocument();
  expect(screen.getByRole("button", {name: "重新扫描本地案例"})).toBeDisabled();
  expect(await screen.findByText("新增 2 · 已有 4 · 保留已删除 1 · 共 6 条")).toBeInTheDocument();
  expect(completed).toHaveBeenCalledTimes(1);
  expect(completed).toHaveBeenCalledWith(7);
  await new Promise(resolve => setTimeout(resolve, 25));
  expect(apiRequest).toHaveBeenCalledTimes(3);
});

it("refreshes once when the first status already contains a completed run with changes", async () => {
  const completed = vi.fn();
  vi.mocked(apiRequest).mockResolvedValueOnce(ready);
  const {rerender} = render(<ReferenceLocalSync pollMs={10} onCompleted={completed} />);
  expect(await screen.findByText("新增 2 · 已有 4 · 保留已删除 1 · 共 6 条")).toBeInTheDocument();
  await waitFor(() => expect(completed).toHaveBeenCalledWith(7));
  rerender(<ReferenceLocalSync pollMs={10} onCompleted={completed} />);
  expect(completed).toHaveBeenCalledTimes(1);
  expect(apiRequest).toHaveBeenCalledTimes(1);
});

it("starts one scan with an empty JSON object and disables repeat starts", async () => {
  let resolveStart!: (value: typeof scanning) => void;
  vi.mocked(apiRequest)
    .mockResolvedValueOnce({...ready, run_id: 6})
    .mockImplementationOnce(() => new Promise(resolve => {resolveStart = resolve as (value: typeof scanning) => void;}));
  render(<ReferenceLocalSync pollMs={10} onCompleted={() => {}} />);
  const button = await screen.findByRole("button", {name: "重新扫描本地案例"});
  fireEvent.click(button); fireEvent.click(button);
  expect(button).toBeDisabled();
  expect(apiRequest).toHaveBeenCalledTimes(2);
  expect(apiRequest).toHaveBeenLastCalledWith("/api/v3/reference-examples/local-sync", {method: "POST", body: "{}"});
  resolveStart(scanning);
  await waitFor(() => expect(screen.getByText("正在扫描本地案例…")).toBeInTheDocument());
});

it("shows friendly missing and malformed-response messages and allows retry", async () => {
  vi.mocked(apiRequest).mockResolvedValueOnce({status: "missing", run_id: 0, counts: {created: 0, updated: 0, unchanged: 0, deleted_preserved: 0}, total: 0, message: "目录不存在", completed_at: null});
  render(<ReferenceLocalSync pollMs={10} onCompleted={() => {}} />);
  expect(await screen.findByText("未找到本地参考案例目录。应用仍可正常使用，你可以稍后重试扫描。" )).toBeInTheDocument();

  cleanup();
  vi.mocked(apiRequest).mockReset().mockResolvedValueOnce({status: "ready"});
  render(<ReferenceLocalSync pollMs={10} onCompleted={() => {}} />);
  expect(await screen.findByText("无法读取本地案例扫描状态，请重试。" )).toBeInTheDocument();
  expect(screen.getByRole("button", {name: "重新扫描本地案例"})).toBeEnabled();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
