import {fireEvent, render, screen, waitFor} from "@testing-library/react";
import {beforeEach, expect, it, vi} from "vitest";
import {WorkflowManager} from "./WorkflowManager";

beforeEach(() => {
  sessionStorage.setItem("anima-v3-session", "token");
  vi.restoreAllMocks();
});

it("starts persisted inspection for the selected server without storing credentials", async () => {
  const report = {remote_profile_id: "server-a", checked_at: null, items: [], inspection: {state: "idle"}};
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) =>
    new Response(JSON.stringify(String(url).endsWith("/inspect") ? {state: "running"} : report)));
  render(<WorkflowManager remoteId="server-a" password="transient" passphrase="" />);
  fireEvent.click(screen.getByRole("button", {name: "管理工作流"}));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", {name: "检测并刷新服务器能力"}));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  expect(fetchMock.mock.calls[1][0]).toBe("/api/v3/workflows/servers/server-a/inspect");
  expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({password: "transient"});
  expect(localStorage.length).toBe(0);
});

it("saves renamed assets with the displayed content revision", async () => {
  const report = {checked_at: 1, items: [{workflow_id: "official:turbo", display_name: "Turbo", revision: "revision-1", origin: "official", experimental: false, state: "invalid_inputs", errors: ["模型文件缺失"], assets: [{key: "1.unet_name", value: "old.safetensors", choices: ["new.safetensors"], mapped: false}]}]};
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify(report)));
  render(<WorkflowManager remoteId="server-a" password="" passphrase="" />);
  fireEvent.click(screen.getByRole("button", {name: "管理工作流"}));
  const select = await screen.findByLabelText("Turbo 1.unet_name");
  fireEvent.change(select, {target: {value: "new.safetensors"}});
  fireEvent.click(screen.getByRole("button", {name: "保存文件映射"}));
  expect(await screen.findByRole("status")).toHaveTextContent("映射已保存");
  expect(fetchMock.mock.calls[1][0]).toBe("/api/v3/workflows/servers/server-a/official%3Aturbo/mapping");
  expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({revision: "revision-1", mapping: {"1.unet_name": "new.safetensors"}});
});
