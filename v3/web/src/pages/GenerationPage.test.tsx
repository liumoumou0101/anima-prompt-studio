import {fireEvent, render, screen, waitFor} from "@testing-library/react";
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
  sessionStorage.setItem("anima-v3-session", "session-token");
  vi.restoreAllMocks();
});

it("renders generation progress and queues a recovery action", async () => {
  const recovered = {...run, status_message: "等待恢复远程任务", available_actions: []};
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [run]}), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify(recovered), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [recovered]}), {status: 200}));

  render(<GenerationPage remoteEnabled />);
  expect(await screen.findByText("ComfyUI 正在生成")).toBeInTheDocument();
  expect(screen.getByText("50%")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "重新检查远端"}));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({action: "retry_check"});
});

it("explains how to enable the reused V2 runtime", () => {
  render(<GenerationPage remoteEnabled={false} />);
  expect(screen.getByRole("heading", {name: "远程生成尚未启用"})).toBeInTheDocument();
  expect(screen.getByText(/指定 V2 数据库/)).toBeInTheDocument();
});
