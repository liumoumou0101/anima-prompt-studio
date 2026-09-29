import {act, cleanup, fireEvent, render, screen, waitFor, within} from "@testing-library/react";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {copyImageFileToClipboard} from "../lib/copyImage";
import {GallerySourcePreview} from "./GallerySourcePreview";

vi.mock("../lib/copyImage", () => ({copyImageFileToClipboard: vi.fn()}));

const source = {path: "gallery/中文 & draft.png", name: "画廊来源图", mode: "generation" as const};
const url = `/api/v3/gallery/assets/content?path=${encodeURIComponent(source.path)}`;

beforeEach(() => {vi.mocked(copyImageFileToClipboard).mockReset().mockResolvedValue(undefined);});
afterEach(() => {cleanup();});

it("shows the original with its encoded content URL and explains generation restoration", () => {
  render(<GallerySourcePreview source={source} />);
  expect(screen.getByAltText(source.name)).toHaveAttribute("src", url);
  expect(screen.getByText(/生成条件/)).toBeInTheDocument();
  expect(screen.getByText(/模型/)).toBeInTheDocument();
  expect(screen.getByText(/执行目标/)).toBeInTheDocument();
  expect(screen.getByRole("button", {name: "复制原图"})).toBeEnabled();
});

it("opens a single original without prompt or parameter metadata", async () => {
  render(<GallerySourcePreview source={source} />);
  fireEvent.click(screen.getByRole("button", {name: "放大查看来源原图"}));
  const preview = within(screen.getByRole("dialog", {name: "Lightbox"}));
  expect(preview.getByRole("img", {name: source.name})).toHaveAttribute("src", url);
  expect(preview.getByRole("button", {name: "下一张"})).toBeDisabled();
  fireEvent.click(preview.getByRole("button", {name: "图片信息"}));
  expect(preview.getByRole("link", {name: "在新标签页打开原图"})).toHaveAttribute("href", url);
  expect(preview.queryByRole("heading", {name: "正向提示词"})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "关闭预览"}));
  await waitFor(() => expect(screen.queryByRole("dialog", {name: "Lightbox"})).not.toBeInTheDocument());
});

it("explains prompt-only import and default parameters", () => {
  render(<GallerySourcePreview source={{...source, mode: "prompt"}} />);
  expect(screen.getByText(/只导入提示词/)).toBeInTheDocument();
  expect(screen.getByText(/默认参数/)).toBeInTheDocument();
  expect(screen.getByText(/模型/)).toBeInTheDocument();
  expect(screen.getByText(/执行目标/)).toBeInTheDocument();
});

it("prevents duplicate copies and reports success", async () => {
  let finish!: () => void;
  vi.mocked(copyImageFileToClipboard).mockReturnValue(new Promise(resolve => {finish = resolve;}));
  render(<GallerySourcePreview source={source} />);
  fireEvent.click(screen.getByRole("button", {name: "复制原图"}));
  expect(screen.getByRole("button", {name: "复制中…"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button", {name: "复制中…"}));
  expect(copyImageFileToClipboard).toHaveBeenCalledExactlyOnceWith(source.path);
  await act(async () => finish());
  expect(screen.getByRole("status")).toHaveTextContent("已复制原图");
});

it("reports copy errors and allows retry", async () => {
  vi.mocked(copyImageFileToClipboard).mockRejectedValueOnce(new Error("剪贴板不可用"));
  render(<GallerySourcePreview source={source} />);
  fireEvent.click(screen.getByRole("button", {name: "复制原图"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("剪贴板不可用");
  fireEvent.click(screen.getByRole("button", {name: "复制原图"}));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("已复制原图"));
  expect(copyImageFileToClipboard).toHaveBeenCalledTimes(2);
});

it("shows a clear failure when the original cannot load", () => {
  render(<GallerySourcePreview source={source} />);
  fireEvent.error(screen.getByAltText(source.name));
  expect(screen.getByRole("alert")).toHaveTextContent("来源原图读取失败");
  expect(screen.getByRole("button", {name: "放大查看来源原图"})).toBeDisabled();
});
