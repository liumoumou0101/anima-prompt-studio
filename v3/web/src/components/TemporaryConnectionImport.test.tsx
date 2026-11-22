import {act, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {beforeEach, expect, it, vi} from "vitest";
import {SettingsPage} from "../pages/SettingsPage";

const httpProfile = {
  id: "temporary-one", display_name: "Colab 临时环境", connection_type: "http",
  comfy_host: "127.0.0.1", comfy_port: 8188, connection_ready: true,
  ssh_host: "", ssh_port: 22, ssh_user: "root", auth_type: "password", private_key_path: "",
  enabled: true, has_saved_password: false, host_fingerprint_confirmed: false,
  comfy_endpoint: "https://gpu.example.test/prefix", http_base_url: "https://gpu.example.test/prefix",
  http_session_id: "session-v1", http_runtime_id: "runtime-one", has_saved_api_key: true,
  web_url: "https://gpu.example.test/prefix/_moss/login",
};
const connectionJson = '{"protocol":"comfyui-http","base_url":"https://gpu.example.test/prefix","api_key":"json-secret","auth_scheme":"Bearer"}';

beforeEach(() => {
  vi.restoreAllMocks();
  sessionStorage.setItem("anima-v3-session", "session-token");
});

function server(initial = [httpProfile], failure = false) {
  let items = initial;
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (path, init) => {
    if (path === "/api/v3/settings/temporary-connections/import") {
      if (failure) return new Response(JSON.stringify({error: {code: "invalid_request", message: "rejected-key invalid secret payload"}}), {status: 400});
      const body = JSON.parse(String(init?.body));
      const saved = {...httpProfile, id: body.target_profile_id || "temporary-new", display_name: body.display_name, http_session_id: "session-v2"};
      items = body.target_profile_id ? items.map(item => item.id === saved.id ? saved : item) : [...items, saved];
      return new Response(JSON.stringify(saved));
    }
    if (init?.method === "PUT") {
      items = items.map(item => ({...item, ...JSON.parse(String(init.body))}));
      return new Response(JSON.stringify(items[0]));
    }
    if (String(path).endsWith("/test-connection")) return new Response(JSON.stringify({ok: true, devices: ["Protocol GPU"], queue_running: 0, queue_pending: 0, comfy_endpoint: httpProfile.comfy_endpoint}));
    if (String(path).endsWith("/open-comfy")) return new Response(JSON.stringify({state: "ready", ready: true, remote_profile_id: httpProfile.id, remote_display_name: httpProfile.display_name, local_url: httpProfile.web_url, message: "请在网关登录页输入访问密钥。", devices: [], queue_running: 0, queue_pending: 0}));
    if (init?.method === "DELETE") { items = []; return new Response(null, {status: 204}); }
    return new Response(JSON.stringify({items, workflows: [], credential_store_available: true}));
  });
}

async function openImport() {
  fireEvent.click(await screen.findByRole("button", {name: "导入临时连接"}));
  return screen.getByRole("region", {name: "导入临时连接"});
}

it("imports JSON as a new selected HTTP connection and clears raw secrets without persisting them", async () => {
  const network = server([]);
  const storage = vi.spyOn(Storage.prototype, "setItem");
  render(<SettingsPage remoteEnabled />);
  await openImport();
  fireEvent.change(screen.getByLabelText("连接信息"), {target: {value: connectionJson}});
  fireEvent.change(screen.getByLabelText("连接名称"), {target: {value: "新的临时连接"}});
  fireEvent.click(screen.getByRole("button", {name: "导入并保存"}));
  expect(await screen.findByText(/临时连接已保存.*测试/)).toBeInTheDocument();
  expect(screen.getByLabelText("显示名称")).toHaveValue("新的临时连接");
  expect(screen.queryByLabelText("访问密钥")).not.toBeInTheDocument();
  const request = network.mock.calls.find(call => call[0] === "/api/v3/settings/temporary-connections/import")!;
  expect(JSON.parse(String(request[1]?.body))).toEqual({connection_text: connectionJson, display_name: "新的临时连接"});
  expect(storage.mock.calls.some(call => String(call[1]).includes("json-secret"))).toBe(false);
  await openImport();
  expect(screen.getByLabelText("连接信息")).toHaveValue("");
  expect(screen.getByLabelText("访问密钥")).toHaveValue("");
});

it("updates the selected HTTP target with URL and raw key while preserving its logical id", async () => {
  const network = server();
  render(<SettingsPage remoteEnabled />);
  await openImport();
  fireEvent.click(screen.getByLabelText("更新当前临时连接"));
  fireEvent.change(screen.getByLabelText("连接信息"), {target: {value: "https://new.example.test"}});
  fireEvent.change(screen.getByLabelText("访问密钥"), {target: {value: "raw-secret"}});
  expect(screen.getByText(/不要.*Bearer/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "导入并保存"}));
  expect(await screen.findByText(/临时连接已保存/)).toBeInTheDocument();
  expect(screen.getByRole("link", {name: "管理此环境的工作流资源"})).toHaveAttribute("href", "/workflows?environment=temporary-one");
  const request = network.mock.calls.find(call => call[0] === "/api/v3/settings/temporary-connections/import")!;
  expect(JSON.parse(String(request[1]?.body))).toEqual({connection_text: "https://new.example.test", api_key: "raw-secret", display_name: "Colab 临时环境", target_profile_id: "temporary-one"});
});

it.each(["https://public.example.test", '{"protocol":"comfyui-http","base_url":"https://public.example.test"}'])
("clears the selected connection key when importing public connection %s with blank input", async text => {
  const network = server();
  render(<SettingsPage remoteEnabled />);
  await openImport();
  fireEvent.click(screen.getByLabelText("更新当前临时连接"));
  fireEvent.change(screen.getByLabelText("连接信息"), {target: {value: text}});
  fireEvent.click(screen.getByRole("button", {name: "导入并保存"}));
  expect(await screen.findByText(/临时连接已保存/)).toBeInTheDocument();
  const request = network.mock.calls.find(call => call[0] === "/api/v3/settings/temporary-connections/import")!;
  expect(JSON.parse(String(request[1]?.body))).toEqual({connection_text: text, api_key: "", display_name: "Colab 临时环境", target_profile_id: "temporary-one"});
});

it("uses the embedded Colab JSON key on update without a conflicting blank field", async () => {
  const network = server();
  render(<SettingsPage remoteEnabled />);
  await openImport();
  fireEvent.click(screen.getByLabelText("更新当前临时连接"));
  fireEvent.change(screen.getByLabelText("连接信息"), {target: {value: connectionJson}});
  fireEvent.click(screen.getByRole("button", {name: "导入并保存"}));
  expect(await screen.findByText(/临时连接已保存/)).toBeInTheDocument();
  const request = network.mock.calls.find(call => call[0] === "/api/v3/settings/temporary-connections/import")!;
  expect(JSON.parse(String(request[1]?.body))).toEqual({connection_text: connectionJson, display_name: "Colab 临时环境", target_profile_id: "temporary-one"});
});

it("keeps the selected profile and displays a safe failure without a success notice", async () => {
  server([httpProfile], true);
  render(<SettingsPage remoteEnabled />);
  await openImport();
  fireEvent.change(screen.getByLabelText("连接信息"), {target: {value: "invalid secret payload"}});
  fireEvent.change(screen.getByLabelText("访问密钥"), {target: {value: "rejected-key"}});
  fireEvent.click(screen.getByRole("button", {name: "导入并保存"}));
  expect(await screen.findByRole("alert")).toHaveTextContent(/导入失败/);
  expect(screen.getByLabelText("显示名称")).toHaveValue("Colab 临时环境");
  expect(screen.queryByText(/临时连接已保存/)).not.toBeInTheDocument();
  expect(screen.getByRole("alert")).not.toHaveTextContent("rejected-key");
});

it("reads a JSON file as text and allows importing the content", async () => {
  server([]);
  render(<SettingsPage remoteEnabled />);
  await openImport();
  const file = new File([connectionJson], "moss_connection.json", {type: "application/json"});
  fireEvent.change(screen.getByLabelText("选择 JSON 文件"), {target: {files: [file]}});
  await waitFor(() => expect(screen.getByLabelText("连接信息")).toHaveValue(connectionJson));
  fireEvent.click(screen.getByRole("button", {name: "导入并保存"}));
  expect(await screen.findByText(/临时连接已保存/)).toBeInTheDocument();
});

it("rejects files over 64 KiB before reading them", async () => {
  server([]);
  render(<SettingsPage remoteEnabled />);
  await openImport();
  const read = vi.fn().mockResolvedValue("must-not-read");
  const file = new File(["x".repeat(65537)], "large.json");
  Object.defineProperty(file, "text", {value: read});
  fireEvent.change(screen.getByLabelText("选择 JSON 文件"), {target: {files: [file]}});
  expect(await screen.findByRole("alert")).toHaveTextContent(/64 KiB/);
  expect(read).not.toHaveBeenCalled();
  expect(screen.getByLabelText("连接信息")).toHaveValue("");
});

it("clears cancellation secrets and ignores a file that finishes after cancellation", async () => {
  server([]);
  const view = render(<SettingsPage remoteEnabled />);
  await openImport();
  let complete!: (text: string) => void;
  const file = new File(["pending"], "late.json");
  Object.defineProperty(file, "text", {value: () => new Promise<string>(resolve => {complete = resolve;})});
  fireEvent.change(screen.getByLabelText("访问密钥"), {target: {value: "cancel-secret"}});
  fireEvent.change(screen.getByLabelText("连接信息"), {target: {value: "old-json-secret"}});
  fireEvent.change(screen.getByLabelText("选择 JSON 文件"), {target: {files: [file]}});
  fireEvent.click(screen.getByRole("button", {name: "取消导入"}));
  await openImport();
  await act(async () => complete(connectionJson));
  expect(screen.getByLabelText("连接信息")).toHaveValue("");
  expect(screen.getByLabelText("访问密钥")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("访问密钥"), {target: {value: "unmount-secret"}});
  const detachedKey = screen.getByLabelText("访问密钥");
  const detachedText = screen.getByLabelText("连接信息");
  fireEvent.change(detachedText, {target: {value: "unmount-json-secret"}});
  fireEvent.change(screen.getByLabelText("选择 JSON 文件"), {target: {files: [file]}});
  view.unmount();
  await act(async () => complete("late-unmounted-secret"));
  expect(detachedKey).toHaveValue("");
  expect(detachedText).toHaveValue("");
  render(<SettingsPage remoteEnabled />);
  await openImport();
  expect(screen.getByLabelText("访问密钥")).toHaveValue("");
});

it("ignores an older file completion and an in-flight file after manual edits", async () => {
  server([]);
  render(<SettingsPage remoteEnabled />);
  await openImport();
  let first!: (text: string) => void;
  let second!: (text: string) => void;
  const fileA = new File(["a"], "a.json");
  const fileB = new File(["b"], "b.json");
  Object.defineProperty(fileA, "text", {value: () => new Promise<string>(resolve => {first = resolve;})});
  Object.defineProperty(fileB, "text", {value: () => new Promise<string>(resolve => {second = resolve;})});
  fireEvent.change(screen.getByLabelText("选择 JSON 文件"), {target: {files: [fileA]}});
  fireEvent.change(screen.getByLabelText("选择 JSON 文件"), {target: {files: [fileB]}});
  await act(async () => second("new-json"));
  await act(async () => first("old-json"));
  expect(screen.getByLabelText("连接信息")).toHaveValue("new-json");
  fireEvent.change(screen.getByLabelText("选择 JSON 文件"), {target: {files: [fileA]}});
  fireEvent.change(screen.getByLabelText("连接信息"), {target: {value: "manual-url"}});
  await act(async () => first("late-json"));
  expect(screen.getByLabelText("连接信息")).toHaveValue("manual-url");
});

it("edits HTTP metadata without sending transport or credential fields", async () => {
  const network = server();
  render(<SettingsPage remoteEnabled />);
  fireEvent.change(await screen.findByDisplayValue(httpProfile.display_name), {target: {value: "重命名环境"}});
  fireEvent.click(screen.getByLabelText("在生成列表中启用此连接"));
  fireEvent.click(screen.getByRole("button", {name: "保存连接"}));
  expect(await screen.findByText(/临时连接设置已保存/)).toBeInTheDocument();
  expect(screen.getByLabelText("显示名称")).toHaveValue("重命名环境");
  const request = network.mock.calls.find(call => call[1]?.method === "PUT")!;
  expect(JSON.parse(String(request[1]?.body))).toEqual({connection_type: "http", display_name: "重命名环境", enabled: false});
  expect(screen.queryByLabelText("SSH 密码")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "检测 SSH 指纹"})).not.toBeInTheDocument();
});

it("tests HTTP through the established route and opens its separate gateway login", async () => {
  const network = server();
  const popup = {location: {replace: vi.fn()}, close: vi.fn()} as unknown as Window;
  vi.spyOn(window, "open").mockReturnValue(popup);
  render(<SettingsPage remoteEnabled />);
  fireEvent.click(await screen.findByRole("button", {name: "测试临时连接"}));
  expect(await screen.findByText(/连接正常 · Protocol GPU/)).toBeInTheDocument();
  expect(screen.getByRole("link", {name: httpProfile.web_url})).toHaveAttribute("href", httpProfile.web_url);
  expect(screen.getByText(/浏览器.*密钥/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "打开 ComfyUI 网页"}));
  expect(await screen.findByText(/已打开网关登录入口/)).toBeInTheDocument();
  expect(popup.location.replace).toHaveBeenCalledWith(httpProfile.web_url);
  expect(network.mock.calls.find(call => String(call[0]).endsWith("/test-connection"))?.[1]?.body).toBe("{}");
});

it("shows an honest explanation without a fake SSH URL for an unknown HTTPS gateway", async () => {
  server([{...httpProfile, web_url: ""}]);
  render(<SettingsPage remoteEnabled />);
  expect(await screen.findByText(/未识别.*网页登录入口/)).toBeInTheDocument();
  expect(screen.queryByRole("link", {name: /18188/})).not.toBeInTheDocument();
  expect(screen.getByRole("button", {name: "打开 ComfyUI 网页"})).toBeDisabled();
  expect(screen.getByRole("button", {name: "测试临时连接"})).toBeEnabled();
});

it("deletes an HTTP connection using the existing confirmation flow", async () => {
  server();
  render(<SettingsPage remoteEnabled />);
  fireEvent.click(await screen.findByRole("button", {name: "删除此连接"}));
  expect(screen.getByText(/确定删除已保存的连接“Colab 临时环境”/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "确认删除连接"}));
  expect(await screen.findByRole("heading", {name: "新增连接"})).toBeInTheDocument();
  expect(screen.queryByRole("button", {name: /Colab 临时环境/})).not.toBeInTheDocument();
});
