import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {LoraMappingPanel} from "./LoraMappingPanel";

const resource = {logical_id: "style", file_name: "local.safetensors", resource_digest: "a".repeat(64)};
let ready = true;
let writes: Record<string, unknown>[];
beforeEach(() => {
  ready = true; writes = []; sessionStorage.setItem("anima-v3-session", "test");
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_, init) => {
    if (init?.method === "PUT") writes.push(JSON.parse(String(init.body)));
    return new Response(JSON.stringify({mapping_revision: 3, workflow_revision: "revision", remote_fingerprint: "b".repeat(64),
      current: true, capabilities_ready: ready, slots: ready ? {"9.lora_name": ["remote.safetensors"]} : {}, bindings: []}));
  });
});
afterEach(() => {cleanup(); vi.restoreAllMocks();});

async function open() {
  const onSaved = vi.fn();
  const view = render(<MemoryRouter><LoraMappingPanel remote="remote" workflow="workflow" resources={[resource]} disabled={false} onSaved={onSaved} /></MemoryRouter>);
  const details = view.container.querySelector("details")!;
  details.open = true; fireEvent(details, new Event("toggle"));
  return onSaved;
}

it("requires an installed file and sends server-owned mapping versions", async () => {
  const saved = await open();
  fireEvent.change(await screen.findByLabelText("工作流插槽"), {target: {value: "9.lora_name"}});
  expect((screen.getByRole("button", {name: "保存资源映射"}) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("服务器上的文件"), {target: {value: "remote.safetensors"}});
  fireEvent.click(screen.getByRole("button", {name: "保存资源映射"}));
  await waitFor(() => expect(saved).toHaveBeenCalled());
  expect(writes[0]).toEqual({mapping_revision: 3, workflow_revision: "revision", remote_fingerprint: "b".repeat(64),
    bindings: [{logical_id: "style", resource_digest: resource.resource_digest, slot_key: "9.lora_name", remote_file_name: "remote.safetensors"}]});
});

it("keeps saving disabled when remote capabilities are unknown", async () => {
  ready = false; await open();
  expect(await screen.findByText(/服务器能力尚未检测/)).toBeTruthy();
  expect((screen.getByRole("button", {name: "保存资源映射"}) as HTMLButtonElement).disabled).toBe(true);
  expect(writes).toEqual([]);
});
