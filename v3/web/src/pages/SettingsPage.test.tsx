import {fireEvent, render, screen, waitFor} from "@testing-library/react";
import {beforeEach, expect, it, vi} from "vitest";
import {SettingsPage} from "./SettingsPage";

const profile = {
  id: "remote-new",
  display_name: "新云显卡",
  ssh_host: "203.0.113.10",
  ssh_port: 23,
  ssh_user: "root",
  auth_type: "agent",
  private_key_path: "",
  enabled: true,
  has_saved_password: false,
  host_fingerprint_confirmed: false,
  comfy_endpoint: "127.0.0.1:8188",
};

beforeEach(() => {
  sessionStorage.setItem("anima-v3-session", "session-token");
  vi.restoreAllMocks();
});

it("saves a local endpoint and tests it without SSH fields or fingerprint confirmation", async () => {
  const local = {...profile, connection_type: "local", connection_ready: true, display_name: "本机",
    comfy_host: "127.0.0.1", comfy_port: 8288, comfy_endpoint: "127.0.0.1:8288"};
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [], workflows: [], credential_store_available: true})))
    .mockResolvedValueOnce(new Response(JSON.stringify(local)))
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [local], workflows: [], credential_store_available: true})))
    .mockResolvedValueOnce(new Response(JSON.stringify({ok: true, devices: ["Local GPU"], queue_running: 0,
      queue_pending: 0, comfy_endpoint: local.comfy_endpoint})));
  render(<SettingsPage remoteEnabled />);
  fireEvent.change(await screen.findByLabelText("连接类型"), {target: {value: "local"}});
  expect(screen.queryByLabelText("SSH 地址")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "检测 SSH 指纹"})).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("ComfyUI 端口"), {target: {value: "8288"}});
  fireEvent.click(screen.getByRole("button", {name: "保存连接"}));
  fireEvent.click(await screen.findByRole("button", {name: "测试本地连接"}));
  expect(await screen.findByText(/连接正常 · Local GPU/)).toBeInTheDocument();
  expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toMatchObject({connection_type: "local", comfy_port: 8288});
  expect(screen.getByRole("button", {name: "打开 ComfyUI 网页"})).toBeEnabled();
});

it("links the selected server to the independent workflow resource page", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [{...profile, host_fingerprint_confirmed: true}], workflows: [], credential_store_available: true})))
    .mockResolvedValueOnce(new Response(JSON.stringify({remote_profile_id: "remote-new", checked_at: null, items: [{workflow_id: "turbo", revision: "abc", origin: "official", experimental: true, display_name: "Turbo experiment", state: "missing_nodes", errors: ["缺少节点 AnimaLayerReplayPatcher"], assets: []}]})));
  render(<SettingsPage remoteEnabled />);
  const link = await screen.findByRole("link", {name: "管理此环境的工作流资源"});
  expect(link).toHaveAttribute("href", "/workflows?environment=remote-new");
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("confirms a new host fingerprint and tests SSH plus ComfyUI entirely in V3", async () => {
  const ready = {...profile, host_fingerprint_confirmed: true};
  const settings = (item = profile) => ({items: [item], workflows: [], credential_store_available: true});
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify(settings()), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({fingerprint: "SHA256:new-host"}), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify(ready), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify(settings(ready)), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({ok: true, devices: ["NVIDIA Test GPU"], queue_running: 1, queue_pending: 2, comfy_endpoint: "127.0.0.1:8188"}), {status: 200}));

  render(<SettingsPage remoteEnabled />);
  expect(await screen.findByText(/待确认指纹/)).toBeInTheDocument();
  expect(screen.getByRole("button", {name: "测试完整连接"})).toBeDisabled();

  fireEvent.click(screen.getByRole("button", {name: "检测 SSH 指纹"}));
  expect(await screen.findByText("SHA256:new-host")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "确认并保存指纹"}));

  await waitFor(() => expect(screen.getByRole("button", {name: "测试完整连接"})).toBeEnabled());
  fireEvent.click(screen.getByRole("button", {name: "测试完整连接"}));
  expect(await screen.findByText(/连接正常 · NVIDIA Test GPU/)).toHaveTextContent("队列 3");
  expect(fetchMock.mock.calls[4][0]).toBe("/api/v3/settings/remote-profiles/remote-new/test-connection");
});

it("moves artist ranking controls to the workbench", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({items: [profile], workflows: [], credential_store_available: true})));
  render(<SettingsPage remoteEnabled />);
  expect(await screen.findByRole("link", {name: "打开工作台"})).toHaveAttribute("href", "/workbench");
  expect(screen.queryByRole("radio")).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it("opens the selected remote ComfyUI through the managed local tunnel", async () => {
  const ready = {...profile, host_fingerprint_confirmed: true};
  const popup = {location: {replace: vi.fn()}, close: vi.fn()} as unknown as Window;
  vi.spyOn(window, "open").mockReturnValue(popup);
  const access = {
    state: "ready",
    ready: true,
    remote_profile_id: ready.id,
    remote_display_name: ready.display_name,
    local_url: "http://127.0.0.1:18188",
    message: "ComfyUI 网页已连接。",
    devices: ["NVIDIA Test GPU"],
    queue_running: 0,
    queue_pending: 0,
  };
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [ready], workflows: [], credential_store_available: true, comfy_access: {state: "stopped", ready: false, local_url: access.local_url}}), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify(access), {status: 200}));

  render(<SettingsPage remoteEnabled />);
  fireEvent.click(await screen.findByRole("button", {name: "打开 ComfyUI 网页"}));

  expect(await screen.findByText(/ComfyUI 维护入口已连接/)).toHaveTextContent(access.local_url);
  expect(fetchMock.mock.calls[1][0]).toBe("/api/v3/settings/remote-profiles/remote-new/open-comfy");
  expect(popup.location.replace).toHaveBeenCalledWith(access.local_url);
});
