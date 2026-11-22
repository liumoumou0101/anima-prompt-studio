import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {apiRequest} from "../lib/api";
import {GenerationAssessment} from "./GenerationAssessment";

vi.mock("../lib/api", () => ({apiRequest: vi.fn()}));
beforeEach(() => vi.mocked(apiRequest).mockReset());
afterEach(cleanup);

it("stores the manual observation with its run in one request and links the saved case", async () => {
  vi.mocked(apiRequest).mockResolvedValue({id: "ex_test"});
  render(<GenerationAssessment runId="run_test" path="outputs/one.png" />);
  fireEvent.click(screen.getByText("记录人工实测（可选）"));
  expect(screen.getByRole("button", {name: "保存实测到参考库"})).toBeDisabled();
  fireEvent.change(screen.getByLabelText("角色辨识"), {target: {value: "pass"}});
  fireEvent.change(screen.getByLabelText("结构"), {target: {value: "fail"}});
  fireEvent.change(screen.getByLabelText("测试 tag（可选）"), {target: {value: "frieren"}});
  fireEvent.change(screen.getByLabelText("实测备注"), {target: {value: "角色可认，手部错误"}});
  fireEvent.click(screen.getByRole("button", {name: "保存实测到参考库"}));
  const link = await screen.findByRole("link", {name: "实测已保存 · 打开参考记录"});
  expect(link).toHaveAttribute("href", "/references?example=ex_test");
  expect(apiRequest).toHaveBeenCalledTimes(1);
  const [url, init] = vi.mocked(apiRequest).mock.calls[0];
  expect(url).toBe("/api/v3/reference-examples/from-run");
  const body = JSON.parse(String(init?.body));
  expect(body).toMatchObject({run_id: "run_test", path: "outputs/one.png"});
  expect(body.user_notes).toContain("单图观察，不代表模型整体能力");
  expect(body.user_notes).toContain("角色辨识：符合预期");
  expect(body.user_notes).toContain("构图：未评");
  expect(body.user_notes).toContain("结构：不符合预期");
});

it("preserves failed input and permits a retry without any automatic generation", async () => {
  vi.mocked(apiRequest).mockRejectedValueOnce(new Error("本地服务暂时不可用")).mockResolvedValue({id: "ex_retry"});
  render(<GenerationAssessment runId="run_test" path="outputs/one.png" />);
  fireEvent.click(screen.getByText("记录人工实测（可选）"));
  fireEvent.change(screen.getByLabelText("实测备注"), {target: {value: "保留这段观察"}});
  fireEvent.click(screen.getByRole("button", {name: "保存实测到参考库"}));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("实测备注")).toHaveValue("保留这段观察");
  fireEvent.click(screen.getByRole("button", {name: "保存实测到参考库"}));
  await waitFor(() => expect(screen.getByRole("link")).toHaveAttribute("href", "/references?example=ex_retry"));
  expect(vi.mocked(apiRequest).mock.calls.every(([url]) => url === "/api/v3/reference-examples/from-run")).toBe(true);
});
