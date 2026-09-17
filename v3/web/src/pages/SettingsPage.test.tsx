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

it("keeps appearance available without a connection and preserves connection drafts across all four modes", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({items: [], workflows: [], credential_store_available: true})));
  const empty = render(<SettingsPage remoteEnabled={false} />);
  expect(screen.getByLabelText("界面布局")).toBeEnabled();
  expect(screen.getByLabelText("明暗主题")).toBeEnabled();
  expect(fetchMock).not.toHaveBeenCalled();
  empty.unmount();
  render(<SettingsPage remoteEnabled />);
  const name = await screen.findByLabelText("显示名称");
  fireEvent.change(name, {target: {value: "未保存的云主机名称"}});
  fireEvent.change(screen.getByLabelText("SSH 密码"), {target: {value: "unsaved-test-password"}});
  const layout = screen.getByLabelText("界面布局") as HTMLSelectElement;
  const theme = screen.getByLabelText("明暗主题") as HTMLSelectElement;
  const previous = {layout: layout.value, theme: theme.value};
  for (const value of ["studio", "editorial"]) {
    fireEvent.change(layout, {target: {value}});
    for (const mode of ["light", "dark"]) {
      fireEvent.change(theme, {target: {value: mode}});
      expect(name).toHaveValue("未保存的云主机名称");
      expect(screen.getByLabelText("SSH 密码")).toHaveValue("unsaved-test-password");
    }
  }
  expect(fetchMock).toHaveBeenCalledTimes(1);
  fireEvent.change(layout, {target: {value: previous.layout}});
  fireEvent.change(theme, {target: {value: previous.theme}});
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
  const openButton = await screen.findByRole("button", {name: "打开 ComfyUI 网页"});
  await waitFor(() => expect(openButton).toBeEnabled());
  fireEvent.click(openButton);

  expect(await screen.findByText(/ComfyUI 维护入口已连接/)).toHaveTextContent(access.local_url);
  expect(fetchMock.mock.calls[1][0]).toBe("/api/v3/settings/remote-profiles/remote-new/open-comfy");
  expect(popup.location.replace).toHaveBeenCalledWith(access.local_url);
});

it("deletes a saved connection only after naming it in explicit confirmation and supports cancel", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({items: [profile], workflows: [], credential_store_available: true})));
  render(<SettingsPage remoteEnabled />);
  const remove = await screen.findByRole("button", {name: "删除此连接"});
  fireEvent.click(remove);
  expect(screen.getByText(/确定删除已保存的连接“新云显卡”/)).toBeInTheDocument();
  expect(screen.getByText(/生成记录、图片和远端主机内容都会保留/)).toBeInTheDocument();
  expect(fetchMock.mock.calls.some(call => call[1]?.method === "DELETE")).toBe(false);
  fireEvent.click(screen.getByRole("button", {name: "取消删除"}));
  expect(screen.queryByRole("button", {name: "确认删除连接"})).not.toBeInTheDocument();
  expect(fetchMock.mock.calls.some(call => call[1]?.method === "DELETE")).toBe(false);
});

it("locks confirmation to the exact id and changing selection cannot delete the wrong profile", async () => {
  const other = {...profile, id: "remote-other", display_name: "备用云主机", ssh_host: "203.0.113.11"};
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [profile, other], workflows: [], credential_store_available: true})))
    .mockResolvedValueOnce(new Response(null, {status: 204}))
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [profile], workflows: [], credential_store_available: true})));
  render(<SettingsPage remoteEnabled />);
  fireEvent.click(await screen.findByRole("button", {name: "删除此连接"}));
  fireEvent.click(screen.getByRole("button", {name: /备用云主机/}));
  expect(screen.queryByRole("button", {name: "确认删除连接"})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "删除此连接"}));
  fireEvent.click(screen.getByRole("button", {name: "确认删除连接"}));
  await waitFor(() => expect(fetchMock.mock.calls.some(call => call[1]?.method === "DELETE")).toBe(true));
  const deletion = fetchMock.mock.calls.find(call => call[1]?.method === "DELETE")!;
  expect(deletion[0]).toBe("/api/v3/settings/remote-profiles/remote-other");
  expect(deletion[1]?.body).toBe("{}");
});

it("selects a remaining connection after deletion and resets to a fresh form after deleting the last one", async () => {
  const passwordProfile = {...profile, auth_type: "password" as const};
  const other = {...passwordProfile, id: "remote-other", display_name: "备用云主机", ssh_host: "203.0.113.11"};
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [passwordProfile, other], workflows: [], credential_store_available: true})))
    .mockResolvedValueOnce(new Response(null, {status: 204}))
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [other], workflows: [], credential_store_available: true})))
    .mockResolvedValueOnce(new Response(null, {status: 204}))
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [], workflows: [], credential_store_available: true})));
  render(<SettingsPage remoteEnabled />);
  fireEvent.change(await screen.findByLabelText("SSH 密码"), {target: {value: "temporary-secret"}});
  fireEvent.click(screen.getByRole("button", {name: "删除此连接"}));
  fireEvent.click(screen.getByRole("button", {name: "确认删除连接"}));
  await waitFor(() => expect(screen.getByLabelText("显示名称")).toHaveValue("备用云主机"));
  expect(screen.getByLabelText("SSH 密码")).toHaveValue("");
  fireEvent.click(screen.getByRole("button", {name: "删除此连接"}));
  fireEvent.click(screen.getByRole("button", {name: "确认删除连接"}));
  await waitFor(() => expect(screen.getByRole("heading", {name: "新增连接"})).toBeInTheDocument());
  expect(screen.getByLabelText("显示名称")).toHaveValue("我的云端 ComfyUI");
  expect(screen.queryByRole("button", {name: "删除此连接"})).not.toBeInTheDocument();
  expect(screen.getByText(/已删除连接“备用云主机”/)).toBeInTheDocument();
  expect(fetchMock.mock.calls.filter(call => call[1]?.method === "DELETE")).toHaveLength(2);
});

it("preserves the profile after delete failure, allows retry, and prevents double delete", async () => {
  let resolveDelete!: (response: Response) => void;
  const pendingDelete = new Promise<Response>(resolve => {resolveDelete = resolve;});
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [profile], workflows: [], credential_store_available: true})))
    .mockReturnValueOnce(pendingDelete)
    .mockResolvedValueOnce(new Response(JSON.stringify({error: {code: "remote_profile_in_use", message: "当前任务仍在使用此连接，请稍后重试。", retryable: true}}), {status: 409}));
  render(<SettingsPage remoteEnabled />);
  fireEvent.click(await screen.findByRole("button", {name: "删除此连接"}));
  const confirm = screen.getByRole("button", {name: "确认删除连接"});
  fireEvent.click(confirm); fireEvent.click(confirm);
  expect(fetchMock.mock.calls.filter(call => call[1]?.method === "DELETE")).toHaveLength(1);
  expect(confirm).toBeDisabled();
  resolveDelete(new Response(JSON.stringify({error: {code: "remote_cleanup_failed", message: "清理连接失败，请重试。", retryable: true}}), {status: 503}));
  expect(await screen.findByText("清理连接失败，请重试。")).toBeInTheDocument();
  expect(screen.getByLabelText("显示名称")).toHaveValue("新云显卡");
  fireEvent.click(screen.getByRole("button", {name: "确认删除连接"}));
  expect(await screen.findByText("当前任务仍在使用此连接，请稍后重试。")).toBeInTheDocument();
  expect(fetchMock.mock.calls.filter(call => call[1]?.method === "DELETE")).toHaveLength(2);
});

it("blocks a confirmed deletion while another connection operation is running", async () => {
  let resolveProbe!: (response: Response) => void;
  const pendingProbe = new Promise<Response>(resolve => {resolveProbe = resolve;});
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [profile], workflows: [], credential_store_available: true})))
    .mockReturnValueOnce(pendingProbe);
  render(<SettingsPage remoteEnabled />);
  fireEvent.click(await screen.findByRole("button", {name: "删除此连接"}));
  fireEvent.click(screen.getByRole("button", {name: "检测 SSH 指纹"}));
  const confirm = screen.getByRole("button", {name: "确认删除连接"});
  expect(confirm).toBeDisabled();
  fireEvent.click(confirm);
  expect(fetchMock.mock.calls.filter(call => call[1]?.method === "DELETE")).toHaveLength(0);
  resolveProbe(new Response(JSON.stringify({fingerprint: "SHA256:busy"})));
  await waitFor(() => expect(confirm).toBeEnabled());
});

it("removes a deleted connection locally when the post-delete refresh fails", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [profile], workflows: [], credential_store_available: true})))
    .mockResolvedValueOnce(new Response(null, {status: 204}))
    .mockResolvedValueOnce(new Response(JSON.stringify({error: {code: "settings_unavailable", message: "连接已删除，但列表刷新失败，请稍后重试。", retryable: true}}), {status: 503}));
  render(<SettingsPage remoteEnabled />);
  fireEvent.click(await screen.findByRole("button", {name: "删除此连接"}));
  fireEvent.click(screen.getByRole("button", {name: "确认删除连接"}));
  expect(await screen.findByText("连接已删除，但列表刷新失败，请稍后重试。")).toBeInTheDocument();
  expect(screen.getByText(/已删除连接“新云显卡”/)).toBeInTheDocument();
  expect(screen.getByRole("heading", {name: "新增连接"})).toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "删除此连接"})).not.toBeInTheDocument();
  expect(fetchMock.mock.calls.filter(call => call[1]?.method === "DELETE")).toHaveLength(1);
});
