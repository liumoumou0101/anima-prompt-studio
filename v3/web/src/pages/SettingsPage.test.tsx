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

it("confirms a new host fingerprint and tests SSH plus ComfyUI entirely in V3", async () => {
  const ready = {...profile, host_fingerprint_confirmed: true};
  const settings = (item = profile) => ({items: [item], workflows: [], credential_store_available: true});
  const ranking = {ranking: "tag_fit"};
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify(settings()), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify(ranking), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({fingerprint: "SHA256:new-host"}), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify(ready), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify(settings(ready)), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify(ranking), {status: 200}))
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
  expect(fetchMock.mock.calls[6][0]).toBe("/api/v3/settings/remote-profiles/remote-new/test-connection");
});

it("saves a parallel artist ranking without treating it as a quality upgrade", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [profile], workflows: [], credential_store_available: true}), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({ranking: "tag_fit"}), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({ranking: "balanced"}), {status: 200}));

  render(<SettingsPage remoteEnabled />);
  expect(await screen.findByText("画师推荐排序")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("radio", {name: /题材与投稿量均衡/}));
  expect(await screen.findByText(/画师排序已保存/)).toBeInTheDocument();
  expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body)).ranking).toBe("balanced");
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
    .mockResolvedValueOnce(new Response(JSON.stringify({ranking: "tag_fit"}), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify(access), {status: 200}));

  render(<SettingsPage remoteEnabled />);
  fireEvent.click(await screen.findByRole("button", {name: "打开 ComfyUI 网页"}));

  expect(await screen.findByText(/ComfyUI 维护入口已连接/)).toHaveTextContent(access.local_url);
  expect(fetchMock.mock.calls[2][0]).toBe("/api/v3/settings/remote-profiles/remote-new/open-comfy");
  expect(popup.location.replace).toHaveBeenCalledWith(access.local_url);
});
