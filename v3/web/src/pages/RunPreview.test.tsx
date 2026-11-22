import {fireEvent, render, screen, waitFor} from "@testing-library/react";
import {expect, it, vi} from "vitest";
import {MemoryRouter} from "react-router-dom";
import {RunPreview} from "./ConversationWorkbenchPage";
import {resetGalleryStoreForTests} from "../lib/galleryStore";
import type {GenerationRunRecord} from "../lib/types";

it("opens generated images in the shared viewer and returns to the same result", async () => {
  resetGalleryStoreForTests();
  sessionStorage.setItem("anima-v3-session", "test");
  vi.spyOn(globalThis, "fetch").mockImplementation(async url => new Response(JSON.stringify(String(url).includes("/artifacts") ? {items: [
    {id: "a", path: "a.png", removed: false, thumbnail_url: "/thumb-a", content_url: "/image-a"},
    {id: "b", path: "b.png", removed: false, thumbnail_url: "/thumb-b", content_url: "/image-b"},
  ]} : {items: [{path: "a.png", name: "a.png", width: 768, height: 1024, positive_prompt: "original prompt", negative_prompt: "text", generation_params: {seed: "8798399215689017476"}}]})));
  render(<MemoryRouter><RunPreview run={{id: "run", artifact_count: 2, status_message: "已完成"} as GenerationRunRecord} /></MemoryRouter>);
  const open = await screen.findByRole("button", {name: "预览生成图片 1"});
  fireEvent.click(open);
  expect(await screen.findByRole("button", {name: "关闭预览"})).toBeInTheDocument();
  expect(screen.getByRole("button", {name: "放大"})).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "图片信息"}));
  expect(await screen.findByText("original prompt")).toBeInTheDocument();
  expect(screen.getByText("8798399215689017476")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "收起图片信息"}));
  fireEvent.click(screen.getByRole("button", {name: "关闭预览"}));
  await waitFor(() => expect(screen.queryByRole("button", {name: "关闭预览"})).not.toBeInTheDocument());
  expect(open).toBeInTheDocument();
  vi.restoreAllMocks();
});


it("can retry a failed result fetch without submitting another generation", async () => {
  sessionStorage.setItem("anima-v3-session", "test");
  const fetchMock = vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new TypeError("offline"))
    .mockResolvedValue(new Response(JSON.stringify({items: [{id: "a", path: "a.png", removed: false, thumbnail_url: "/thumb-a", content_url: "/image-a"}]})));
  render(<MemoryRouter><RunPreview run={{id: "run_retry", state: "completed", artifact_count: 1, status_message: "已完成"} as GenerationRunRecord} /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", {name: "重新读取图片"}));
  expect(await screen.findByRole("button", {name: "预览生成图片 1"})).toBeInTheDocument();
  expect(fetchMock.mock.calls.map(call => String(call[0]))).toEqual(["/api/v3/generation-runs/run_retry/artifacts", "/api/v3/generation-runs/run_retry/artifacts"]);
  vi.restoreAllMocks();
});
