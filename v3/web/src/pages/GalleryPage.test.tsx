import {fireEvent, render, screen} from "@testing-library/react";
import type {ReactNode} from "react";
import {beforeEach, expect, it, vi} from "vitest";
import {resetGalleryStoreForTests} from "../lib/galleryStore";
import {GalleryPage} from "./GalleryPage";

vi.mock("react-photo-album", () => ({
  default: ({photos, render}: {photos: Array<{path: string}>; render: {photo: (props: unknown, context: {photo: {path: string}; width: number; height: number}) => ReactNode}}) => <div>{photos.map((photo) => <div key={photo.path}>{render.photo({}, {photo, width: 205, height: 205})}</div>)}</div>,
}));

const assets = [
  {
    id: "项目/batch/one.png", path: "项目/batch/one.png", name: "one.png", project: "雨夜项目",
    model_profile: "anima_base_v1", batch_id: "run-1", batch_title: "08-26 12:00 · 雨夜项目",
    created_at: "2026-08-26T12:00:00+08:00", positive_prompt: "score_7, white hair, umbrella",
    negative_prompt: "text", width: 1024, height: 1536, byte_size: 100, source: "generated", state: "",
    candidate: {id: "candidate_hybrid", lane: "hybrid", versions: {data_pack: "pack-r1"}},
    content_url: "/api/v3/gallery/assets/content?path=one.png",
    thumbnail_url: "/api/v3/gallery/assets/thumbnail?path=one.png&size=640",
  },
  {
    id: "外部/two.jpg", path: "外部/two.jpg", name: "two.jpg", project: "外部图片",
    model_profile: "", batch_id: "folder:two", batch_title: "08-25 · 外部图片",
    created_at: "2026-08-25T12:00:00+08:00", positive_prompt: "", negative_prompt: "",
    width: null, height: null, byte_size: 50, source: "external", state: "", candidate: {id: "", lane: "", versions: {}},
    content_url: "/api/v3/gallery/assets/content?path=two.jpg",
    thumbnail_url: "/api/v3/gallery/assets/thumbnail?path=two.jpg&size=640",
  },
];

beforeEach(() => {
  resetGalleryStoreForTests();
  sessionStorage.setItem("anima-v3-session", "session-token");
  vi.restoreAllMocks();
});

it("filters local assets and opens traceable image details", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    root: "D:/Pictures/AnimaPromptStudio",
    items: assets,
    projects: ["外部图片", "雨夜项目"],
    models: ["anima_base_v1"],
    trash_count: 0,
  }), {status: 200}));

  render(<GalleryPage enabled />);
  expect(await screen.findByText("2 张")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("筛选项目"), {target: {value: "雨夜项目"}});
  expect(screen.getByText("1 张")).toBeInTheDocument();
  expect(screen.queryByAltText("two.jpg")).not.toBeInTheDocument();

  fireEvent.click(screen.getByAltText("one.png"));
  expect(screen.getByRole("dialog", {name: "图片详情"})).toBeInTheDocument();
  expect(screen.getByText("score_7, white hair, umbrella")).toBeInTheDocument();
  expect(screen.getByText("pack-r1")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "关闭图片详情"}));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("shows refresh progress and reports newly indexed images", async () => {
  let resolveRefresh!: (response: Response) => void;
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({
      root: "D:/gallery", items: [assets[0]], projects: ["雨夜项目"], models: ["anima_base_v1"], trash_count: 0,
    }), {status: 200}))
    .mockImplementationOnce(() => new Promise<Response>((resolve) => { resolveRefresh = resolve; }));

  render(<GalleryPage enabled />);
  await screen.findByAltText("one.png");
  fireEvent.click(screen.getByRole("button", {name: "刷新画廊"}));
  expect(screen.getByRole("button", {name: "正在刷新…"})).toBeDisabled();
  expect(screen.getByText("正在同步画廊索引…")).toBeInTheDocument();

  resolveRefresh(new Response(JSON.stringify({
    root: "D:/gallery", items: assets, projects: ["外部图片", "雨夜项目"], models: ["anima_base_v1"], trash_count: 0,
  }), {status: 200}));
  expect(await screen.findByText("已发现 1 张新图片。")).toBeInTheDocument();
  expect(fetchMock.mock.calls[1][0]).toBe("/api/v3/gallery/assets?limit=1000&refresh=true");
});

it("renders a bounded first page and progressively exposes the rest", async () => {
  const manyAssets = Array.from({length: 100}, (_, index) => ({
    ...assets[0], id: `asset-${index}`, path: `batch/asset-${index}.png`, name: `asset-${index}.png`,
  }));
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    root: "D:/gallery", items: manyAssets, projects: ["雨夜项目"], models: ["anima_base_v1"], trash_count: 0,
  }), {status: 200}));

  render(<GalleryPage enabled />);
  expect(await screen.findByText("100 张")).toBeInTheDocument();
  expect(screen.getAllByRole("img")).toHaveLength(80);
  fireEvent.click(screen.getByRole("button", {name: "继续加载（剩余 20 张）"}));
  expect(screen.getAllByRole("img")).toHaveLength(100);
});

it("moves an image to recoverable trash and restores it", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({root: "D:/gallery", items: [assets[0]], projects: ["雨夜项目"], models: ["anima_base_v1"], trash_count: 0}), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({moved: [assets[0].path], trash_paths: ["batch/项目/batch/one.png"], failed: []}), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({items: [{
      id: "batch/项目/batch/one.png", path: "batch/项目/batch/one.png", original_path: assets[0].path,
      name: "one.png", byte_size: 100, created_at: 1_777_000_000,
      content_url: "/api/v3/gallery/trash/content?path=one.png",
      thumbnail_url: "/api/v3/gallery/trash/thumbnail?path=one.png&size=640",
    }], trash_count: 1}), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({restored: [assets[0].path], failed: []}), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({root: "D:/gallery", items: [assets[0]], projects: ["雨夜项目"], models: ["anima_base_v1"], trash_count: 0}), {status: 200}));

  render(<GalleryPage enabled />);
  fireEvent.click(await screen.findByAltText("one.png"));
  fireEvent.click(screen.getByRole("button", {name: "移入回收站"}));
  expect(await screen.findByText("图片已移入画廊回收站，可随时恢复。")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: /回收站/}));
  fireEvent.click(await screen.findByAltText("one.png"));
  fireEvent.click(screen.getByRole("button", {name: "恢复到画廊"}));
  expect(await screen.findByText("图片已恢复到原画廊目录。")).toBeInTheDocument();
  expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
    "/api/v3/gallery/assets?limit=1000",
    "/api/v3/gallery/assets/trash",
    "/api/v3/gallery/trash?limit=1000",
    "/api/v3/gallery/trash/restore",
    "/api/v3/gallery/assets?limit=1000&refresh=true",
  ]);
});

it("queues regeneration through the reused gallery process API", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({
      root: "D:/gallery", items: [assets[0]], projects: ["雨夜项目"], models: ["anima_base_v1"], trash_count: 0,
      processing: {available: true, regenAvailable: true, scale: 1.5},
    }), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({jobs: [{
      id: "process-1", operation: "gallery_txt2img_more", state: "queued", message: "等待再出图",
      progress: 0, sourceName: "one.png",
    }], failed: []}), {status: 202}));

  render(<GalleryPage enabled />);
  fireEvent.click(await screen.findByAltText("one.png"));
  fireEvent.click(screen.getByRole("button", {name: "再生成"}));
  fireEvent.click(screen.getByRole("button", {name: "加入队列"}));

  expect(await screen.findByText("已加入 1 项再生成任务。")).toBeInTheDocument();
  expect(screen.getByRole("region", {name: "画廊处理任务"})).toBeInTheDocument();
  const request = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
  expect(request).toEqual({paths: [assets[0].path], operation: "regenerate", count: 1});
});

it("shows an inherited artist tag on gallery-regenerated images without stale comparison positions", async () => {
  const regenerated = {
    ...assets[0],
    id: "项目/batch/regen.png",
    path: "项目/batch/regen.png",
    name: "regen.png",
    artist_comparison: {
      id: "comparison-source",
      artist: "harusa1107",
      rendered_artist: "@harusa1107",
      derived_from: "gallery_regenerate",
      source_comparison_id: "comparison-source",
    },
  };
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    root: "D:/gallery", items: [regenerated], projects: ["雨夜项目"], models: ["anima_base_v1"], trash_count: 0,
  }), {status: 200}));

  render(<GalleryPage enabled />);
  expect(await screen.findByText("@harusa1107")).toBeInTheDocument();
  expect(screen.queryByText(/undefined/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByAltText("regen.png"));
  expect(screen.getByText("画师 Tag")).toBeInTheDocument();
  expect(screen.queryByText(/undefined/)).not.toBeInTheDocument();
});

it("selects the current result set and permanently deletes the original image files in one batch", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({
      root: "D:/gallery", items: assets, projects: ["外部图片", "雨夜项目"], models: ["anima_base_v1"], trash_count: 0,
    }), {status: 200}))
    .mockResolvedValueOnce(new Response(JSON.stringify({deleted: assets.map((item) => item.path), failed: []}), {status: 200}));

  render(<GalleryPage enabled />);
  expect(await screen.findByText("2 张")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "全选当前结果"}));
  expect(screen.getByText("已选择 2 项")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "彻底删除"}));

  expect(await screen.findByText("已从磁盘永久删除 2 张图片，无法恢复。")).toBeInTheDocument();
  expect(fetchMock.mock.calls[1][0]).toBe("/api/v3/gallery/assets/delete");
  expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({paths: assets.map((item) => item.path)});
  expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("直接从磁盘删除"));
});
