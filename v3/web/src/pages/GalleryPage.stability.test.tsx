import {act, cleanup, fireEvent, render, screen, within} from "@testing-library/react";
import {useState, type ReactNode} from "react";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {patchGallerySnapshot, resetGalleryStoreForTests} from "../lib/galleryStore";
import type {GalleryAsset} from "../lib/types";
import {GalleryPage} from "./GalleryPage";

vi.mock("react-photo-album", () => ({
  default: ({photos, render}: {photos: Array<{path: string}>; render: {photo: (props: unknown, context: {photo: {path: string}; width: number; height: number}) => ReactNode}}) => <div>{photos.map(photo => <div key={photo.path}>{render.photo({}, {photo, width: 205, height: 205})}</div>)}</div>,
}));

vi.mock("../components/ImagePreview", () => ({
  ImagePreview: ({images, index, onClose}: {images: Array<{src: string; alt: string}>; index: number; onClose: () => void}) => {
    const [current, setCurrent] = useState(index);
    return index < 0 ? null : <div role="dialog" aria-label="原图预览">
      <img src={images[current].src} alt={images[current].alt} />
      <output aria-label="原图序号">{current + 1} / {images.length}</output>
      <button disabled={current === 0} onClick={() => setCurrent(value => value - 1)}>上一张原图</button>
      <button disabled={current === images.length - 1} onClick={() => setCurrent(value => value + 1)}>下一张原图</button>
      <button onClick={onClose}>关闭原图预览</button>
    </div>;
  },
}));

const assets: GalleryAsset[] = [
  {
    id: "rain/one.png", path: "rain/one.png", name: "one.png", project: "雨夜项目",
    model_profile: "anima_base_v1", batch_id: "run-1", batch_title: "雨夜批次",
    created_at: "2026-08-26T12:00:00+08:00", positive_prompt: "white hair, umbrella",
    negative_prompt: "text", width: 1024, height: 1536, byte_size: 100, source: "generated", state: "",
    candidate: {id: "candidate-1", lane: "hybrid", versions: {}},
    content_url: "/api/v3/gallery/assets/content?path=one.png",
    thumbnail_url: "/api/v3/gallery/assets/thumbnail?path=one.png&size=640",
  },
  {
    id: "external/two.jpg", path: "external/two.jpg", name: "two.jpg", project: "外部图片",
    model_profile: "", batch_id: "folder:two", batch_title: "外部批次",
    created_at: "2026-08-25T12:00:00+08:00", positive_prompt: "", negative_prompt: "",
    width: 1200, height: 800, byte_size: 50, source: "external", state: "",
    candidate: {id: "", lane: "", versions: {}},
    content_url: "/api/v3/gallery/assets/content?path=two.jpg",
    thumbnail_url: "/api/v3/gallery/assets/thumbnail?path=two.jpg&size=640",
  },
];

function setViewport(width: number) {
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
    matches: width >= Number(query.match(/min-width:\s*(\d+)px/)?.[1] || Infinity),
    media: query, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
  })));
}

beforeEach(() => {
  vi.restoreAllMocks();
  resetGalleryStoreForTests();
  sessionStorage.setItem("anima-v3-session", "session-token");
  setViewport(1440);
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify({
    root: "D:/gallery", items: assets, projects: ["外部图片", "雨夜项目"], models: ["anima_base_v1"], trash_count: 0,
  }), {status: 200}));
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("starts with filters collapsed and preserves a removable project filter when collapsed again", async () => {
  render(<GalleryPage enabled />);
  await screen.findByRole("button", {name: "查看 one.png"});
  expect(screen.queryByLabelText("筛选项目")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", {name: "筛选"}));
  fireEvent.change(screen.getByLabelText("筛选项目"), {target: {value: "雨夜项目"}});
  expect(screen.queryByRole("button", {name: "查看 two.jpg"})).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", {name: "筛选"}));
  expect(screen.queryByLabelText("筛选项目")).not.toBeInTheDocument();
  expect(screen.getByRole("button", {name: "查看 one.png"})).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: /雨夜项目/}));
  expect(screen.getByRole("button", {name: "查看 two.jpg"})).toBeInTheDocument();
  expect(screen.queryByLabelText("筛选项目")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", {name: "筛选"}));
  expect(screen.getByLabelText("筛选项目")).toHaveValue("");
});

it.each([
  {width: 1179, role: "dialog", modal: true},
  {width: 1180, role: "region", modal: false},
])("opens $role details at $width px and restores focus without scrolling", async ({width, role, modal}) => {
  setViewport(width);
  render(<GalleryPage enabled />);
  const opener = await screen.findByRole("button", {name: "查看 one.png"});
  opener.focus();
  const focus = vi.spyOn(HTMLElement.prototype, "focus");

  fireEvent.click(within(opener).getByAltText("one.png"));
  const detail = screen.getByRole(role, {name: "图片详情"});
  if (modal) expect(detail).toHaveAttribute("aria-modal", "true");
  else expect(detail).not.toHaveAttribute("aria-modal");
  expect(within(detail).getByText("white hair, umbrella")).toBeInTheDocument();
  const close = within(detail).getByRole("button", {name: "关闭图片详情"});
  expect(close).toHaveFocus();
  const openFocusCall = focus.mock.contexts.findIndex(element => element === close);
  expect(openFocusCall).toBeGreaterThanOrEqual(0);
  expect(focus.mock.calls[openFocusCall]).toEqual([expect.objectContaining({preventScroll: true})]);

  fireEvent.click(close);
  expect(screen.queryByRole(role, {name: "图片详情"})).not.toBeInTheDocument();
  expect(opener).toHaveFocus();
  const restoreFocusCall = focus.mock.contexts.findIndex(element => element === opener);
  expect(restoreFocusCall).toBeGreaterThanOrEqual(0);
  expect(focus.mock.calls[restoreFocusCall]).toEqual([expect.objectContaining({preventScroll: true})]);
});

it("opens the selected original directly from the explicit zoom button without opening details", async () => {
  render(<GalleryPage enabled />);
  fireEvent.click(await screen.findByRole("button", {name: "放大 two.jpg"}));

  const preview = screen.getByRole("dialog", {name: "原图预览"});
  expect(within(preview).getByAltText("two.jpg")).toHaveAttribute("src", assets[1].content_url);
  expect(screen.queryByRole("region", {name: "图片详情"})).not.toBeInTheDocument();
  expect(screen.queryByRole("dialog", {name: "图片详情"})).not.toBeInTheDocument();

  fireEvent.click(within(preview).getByRole("button", {name: "关闭原图预览"}));
  expect(screen.queryByRole("dialog", {name: "原图预览"})).not.toBeInTheDocument();
  expect(screen.queryByRole("region", {name: "图片详情"})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "查看 two.jpg"}));
  expect(screen.getByRole("region", {name: "图片详情"})).toBeInTheDocument();
});

it("clears selected images when leaving multiselect and restores single-click details", async () => {
  render(<GalleryPage enabled />);
  await screen.findByRole("button", {name: "查看 one.png"});
  fireEvent.click(screen.getByRole("button", {name: "多选模式"}));
  expect(screen.getByRole("button", {name: "退出多选"})).toHaveAttribute("aria-pressed", "true");

  fireEvent.click(screen.getByAltText("one.png"));
  fireEvent.click(screen.getByAltText("two.jpg"));
  expect(screen.getByText("已选择 2 项")).toBeInTheDocument();
  expect(screen.queryByRole("region", {name: "图片详情"})).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", {name: "退出多选"}));
  expect(screen.getByRole("button", {name: "多选模式"})).toHaveAttribute("aria-pressed", "false");
  expect(screen.queryByText("已选择 2 项")).not.toBeInTheDocument();
  expect(screen.getByRole("button", {name: "选择 one.png"})).toHaveAttribute("aria-pressed", "false");
  expect(screen.getByRole("button", {name: "选择 two.jpg"})).toHaveAttribute("aria-pressed", "false");

  fireEvent.click(screen.getByAltText("one.png"));
  expect(screen.getByRole("region", {name: "图片详情"})).toBeInTheDocument();
});

it("keeps the open original and its navigation sequence stable during a background gallery update", async () => {
  render(<GalleryPage enabled />);
  fireEvent.click(await screen.findByRole("button", {name: "放大 two.jpg"}));
  const preview = screen.getByRole("dialog", {name: "原图预览"});
  expect(within(preview).getByLabelText("原图序号")).toHaveTextContent("2 / 2");

  const added: GalleryAsset = {...assets[0], id: "rain/new.png", path: "rain/new.png", name: "new.png",
    created_at: "2026-08-27T12:00:00+08:00", content_url: "/api/v3/gallery/assets/content?path=new.png"};
  act(() => patchGallerySnapshot(current => ({...current, items: [added, ...current.items]})));

  expect(within(preview).getByAltText("two.jpg")).toHaveAttribute("src", assets[1].content_url);
  expect(within(preview).getByLabelText("原图序号")).toHaveTextContent("2 / 2");
  fireEvent.click(within(preview).getByRole("button", {name: "上一张原图"}));
  expect(within(preview).getByAltText("one.png")).toHaveAttribute("src", assets[0].content_url);
  expect(within(preview).getByRole("button", {name: "上一张原图"})).toBeDisabled();

  fireEvent.click(within(preview).getByRole("button", {name: "关闭原图预览"}));
  fireEvent.click(screen.getByRole("button", {name: "放大 two.jpg"}));
  const reopened = screen.getByRole("dialog", {name: "原图预览"});
  expect(within(reopened).getByAltText("two.jpg")).toHaveAttribute("src", assets[1].content_url);
  expect(within(reopened).getByLabelText("原图序号")).toHaveTextContent("3 / 3");
  fireEvent.click(within(reopened).getByRole("button", {name: "上一张原图"}));
  expect(within(reopened).getByAltText("one.png")).toHaveAttribute("src", assets[0].content_url);
  fireEvent.click(within(reopened).getByRole("button", {name: "上一张原图"}));
  expect(within(reopened).getByAltText("new.png")).toHaveAttribute("src", added.content_url);
});

it("returns focus to the last directly opened card after switching desktop details", async () => {
  render(<GalleryPage enabled />);
  const first = await screen.findByRole("button", {name: "查看 one.png"});
  const second = screen.getByRole("button", {name: "查看 two.jpg"});
  first.focus();
  fireEvent.click(first);
  expect(within(screen.getByRole("region", {name: "图片详情"})).getByRole("heading", {name: "one.png"})).toBeInTheDocument();

  second.focus();
  fireEvent.click(second);
  const detail = screen.getByRole("region", {name: "图片详情"});
  expect(within(detail).getByRole("heading", {name: "two.jpg"})).toBeInTheDocument();
  const firstFocus = vi.spyOn(first, "focus");
  const secondFocus = vi.spyOn(second, "focus");
  fireEvent.click(within(detail).getByRole("button", {name: "关闭图片详情"}));

  expect(second).toHaveFocus();
  expect(secondFocus).toHaveBeenCalledWith(expect.objectContaining({preventScroll: true}));
  expect(firstFocus).not.toHaveBeenCalled();
});

it("removes modal background inertness before restoring focus to a narrow-screen card", async () => {
  setViewport(390);
  render(<div className="app-shell"><nav aria-label="主导航">应用导航</nav><GalleryPage enabled /></div>);
  const opener = await screen.findByRole("button", {name: "查看 one.png"});
  const inertAncestors = () => {
    const inert: HTMLElement[] = [];
    for (let element: HTMLElement | null = opener; element; element = element.parentElement) {
      if (element.inert) inert.push(element);
    }
    return inert;
  };
  opener.focus();
  fireEvent.click(opener);
  expect(inertAncestors().length).toBeGreaterThan(0);
  const navigation = screen.getByRole("navigation", {name: "主导航", hidden: true});
  expect(navigation.inert).toBe(true);

  const blockedAtRestore: HTMLElement[][] = [];
  const nativeFocus = opener.focus.bind(opener);
  const focus = vi.spyOn(opener, "focus").mockImplementation(options => {
    blockedAtRestore.push(inertAncestors());
    nativeFocus(options);
  });
  fireEvent.click(screen.getByRole("button", {name: "关闭图片详情"}));

  expect(focus).toHaveBeenCalledWith(expect.objectContaining({preventScroll: true}));
  expect(blockedAtRestore).toEqual([[]]);
  expect(navigation.inert).toBeFalsy();
  expect(opener).toHaveFocus();
});

it("continues pending task polling after the task panel closes and adds completed images", async () => {
  render(<GalleryPage enabled />);
  await screen.findByRole("button", {name: "查看 one.png"});
  const added = {...assets[0], id: "rain/completed.png", path: "rain/completed.png", name: "completed.png",
    created_at: "2026-08-27T12:00:00+08:00"};
  let processReads = 0;
  const fetch = vi.mocked(globalThis.fetch).mockImplementation(async url => {
    if (String(url).includes("/gallery/process")) {
      processReads += 1;
      return new Response(JSON.stringify({jobs: [{id: "pending-run", operation: "gallery_txt2img_more",
        state: processReads > 1 ? "completed" : "running", progress: processReads > 1 ? 1 : 0.5,
        message: processReads > 1 ? "已完成" : "仍在出图", sourceName: "one.png"}]}), {status: 200});
    }
    return new Response(JSON.stringify({root: "D:/gallery", items: [added, ...assets],
      projects: ["外部图片", "雨夜项目"], models: ["anima_base_v1"], trash_count: 0}), {status: 200});
  });
  vi.useFakeTimers();
  await act(async () => {fireEvent.click(screen.getByRole("button", {name: "任务"}));});
  expect(screen.getByText("仍在出图")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "关闭任务中心"}));
  expect(screen.queryByRole("region", {name: "画廊处理任务"})).not.toBeInTheDocument();

  await act(async () => {await vi.advanceTimersByTimeAsync(1500);});
  expect(processReads).toBe(2);
  expect(screen.getByRole("button", {name: "查看 completed.png"})).toBeInTheDocument();
  expect(screen.queryByRole("region", {name: "画廊处理任务"})).not.toBeInTheDocument();
  expect(fetch.mock.calls.some(([url]) => String(url) === "/api/v3/gallery/assets?limit=1000&refresh=true")).toBe(true);
});
