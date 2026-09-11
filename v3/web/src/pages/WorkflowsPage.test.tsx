import {fireEvent, render, screen, waitFor} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {beforeEach, expect, it, vi} from "vitest";
import {WorkflowsPage} from "./WorkflowsPage";

const item = {workflow_id: "base", display_name: "本地 Base", revision: "rev-original", origin: "official", enabled: true,
  model_profiles: ["anima_base_v1"], notes: "我的模板说明", nodes: ["UNETLoader"], assets: [{key: "1.unet_name", value: "base.safetensors", node_type: "UNETLoader"}]};
beforeEach(() => {vi.restoreAllMocks(); sessionStorage.setItem("anima-v3-session", "token");});

it("browses the local catalog with no server and never starts an inspection on mount", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async url => new Response(JSON.stringify(String(url).includes("/catalog") ? {items: [item]} : {items: []})));
  render(<MemoryRouter><WorkflowsPage enabled /></MemoryRouter>);
  expect(await screen.findByText("我的模板说明")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", {name: "执行环境与资源"}));
  expect(screen.getByText(/尚未添加执行环境/)).toBeInTheDocument();
  expect(fetchMock.mock.calls.map(call => call[0])).toEqual(["/api/v3/workflows/catalog", "/api/v3/settings/remote-profiles"]);
});

it("requires model confirmation and saves a distinct template without an environment", async () => {
  let saved = false;
  const document = {schema: "anima-user-workflow/1", profile: {display_name: "API 模板", compatible_model_profiles: [], api_workflow: {}}};
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async url => {
    const path = String(url);
    if (path.endsWith("/import")) {saved = true; return new Response(JSON.stringify({id: "user:copy"}));}
    if (path.endsWith("/preview")) return new Response(JSON.stringify(document));
    return new Response(JSON.stringify(path.endsWith("/catalog") ? {items: saved ? [item, {...item, workflow_id: "user:copy", display_name: "手动确认副本", origin: "user"}] : [item]} : {items: []}));
  });
  render(<MemoryRouter><WorkflowsPage enabled /></MemoryRouter>);
  await screen.findByText("我的模板说明");
  fireEvent.click(screen.getByRole("button", {name: "导入本地模板"}));
  fireEvent.change(screen.getByLabelText("工作流 JSON"), {target: {value: JSON.stringify(document)}});
  fireEvent.click(screen.getByRole("button", {name: "解析并预览"}));
  const save = await screen.findByRole("button", {name: "保存为新的本地模板"});
  expect(save).toBeDisabled();
  fireEvent.change(screen.getByLabelText("模板名称"), {target: {value: "手动确认副本"}});
  fireEvent.click(screen.getByLabelText("ANIMA Base", {selector: "input"}));
  expect(save).toBeDisabled();
  fireEvent.click(screen.getByLabelText("已确认模板与模型关联"));
  fireEvent.click(save);
  await screen.findByText("已保存为新的本地模板，尚未为任何环境配置文件映射。");
  const request = fetchMock.mock.calls.find(call => String(call[0]).endsWith("/import"));
  expect(JSON.parse(String(request?.[1]?.body)).profile).toMatchObject({display_name: "手动确认副本", compatible_model_profiles: ["anima_base_v1"]});
  expect(screen.getByRole("heading", {name: "手动确认副本"})).toBeInTheDocument();
});

it("clears temporary credentials and does not carry mappings between environments", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async url => {
    const path = String(url);
    if (path.endsWith("/catalog")) return new Response(JSON.stringify({items: [item]}));
    if (path.endsWith("/remote-profiles")) return new Response(JSON.stringify({items: ["a", "b"].map(id => ({id, display_name: id, auth_type: "password", enabled: true, host_fingerprint_confirmed: true}))}));
    return new Response(JSON.stringify({items: [{...item, state: "unchecked", errors: [], assets: []}], checked_at: null}));
  });
  render(<MemoryRouter initialEntries={["/workflows?environment=a"]}><WorkflowsPage enabled /></MemoryRouter>);
  const password = await screen.findByLabelText("本次连接密码");
  fireEvent.change(password, {target: {value: "transient"}});
  fireEvent.change(screen.getByLabelText("执行环境"), {target: {value: "b"}});
  expect(screen.getByLabelText("本次连接密码")).toHaveValue("");
  await waitFor(() => expect(fetchMock.mock.calls.some(call => String(call[0]).endsWith("/servers/b"))).toBe(true));
  expect(fetchMock.mock.calls.every(call => !String(call[0]).endsWith("/inspect"))).toBe(true);
  expect(screen.getByRole("button", {name: "确认使用模板默认文件"})).toBeDisabled();
});
