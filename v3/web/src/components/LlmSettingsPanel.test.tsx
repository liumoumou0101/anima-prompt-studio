import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {afterEach, expect, it, vi} from "vitest";
import {LlmSettingsPanel} from "./LlmSettingsPanel";
import {apiRequest} from "../lib/api";

vi.mock("../lib/api", () => ({apiRequest: vi.fn()}));
afterEach(() => {cleanup(); vi.resetAllMocks();});
const settings = {current: {service: "opencode", model: "old-model"}, services: [{
  id: "opencode", name: "OpenCode Go", type: "openai_compatible", base_url: "https://opencode.ai/zen/go/v1",
  api_key_exists: true, llm_models: [{name: "old-model", display_name: "Old", is_default: true}],
}]};

it("refreshes, searches and selects without automatically saving or switching models", async () => {
  vi.mocked(apiRequest).mockImplementation(async path => String(path).endsWith("/refresh")
    ? {models: ["kimi-new", "qwen-new"], count: 2} : settings);
  render(<LlmSettingsPanel />);
  await screen.findByLabelText("模型名称");
  fireEvent.click(screen.getByRole("button", {name: "刷新模型列表"}));
  await screen.findByText(/已获取 2 个模型/);
  expect(screen.getByLabelText("模型名称")).toHaveValue("old-model");
  fireEvent.change(screen.getByLabelText("搜索可选模型"), {target: {value: "qwen"}});
  expect(screen.queryByRole("option", {name: "kimi-new"})).toBeNull();
  fireEvent.change(screen.getByLabelText("快速选择模型"), {target: {value: "qwen-new"}});
  expect(screen.getByLabelText("模型名称")).toHaveValue("qwen-new");
  expect(vi.mocked(apiRequest).mock.calls.some(([,init]) => init?.method === "PUT")).toBe(false);
  fireEvent.click(screen.getByRole("button", {name: "保存配置"}));
  await waitFor(() => expect(vi.mocked(apiRequest).mock.calls.some(([,init]) => init?.method === "PUT" && String(init.body).includes('"model_name":"qwen-new"'))).toBe(true));
});

it("blocks refresh when address or key has unsaved changes", async () => {
  vi.mocked(apiRequest).mockResolvedValue(settings);
  render(<LlmSettingsPanel />);
  const address = await screen.findByLabelText("API 地址（Base URL）");
  fireEvent.change(address, {target: {value: "https://other.example/v1"}});
  expect(screen.getByRole("button", {name: "刷新模型列表"})).toBeDisabled();
});
