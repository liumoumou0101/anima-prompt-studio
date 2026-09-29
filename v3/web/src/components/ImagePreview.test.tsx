import {act, cleanup, fireEvent, render, screen} from "@testing-library/react";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {ImagePreview, type PreviewImage} from "./ImagePreview";

function images(count = 6): PreviewImage[] {
  return Array.from({length: count}, (_, index) => ({src: `/original-${index + 1}.png`,
    alt: `图片 ${index + 1}`, positive: `prompt ${index + 1}`, width: 1280, height: 960}));
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => {cleanup(); vi.useRealTimers();});

function navigate(direction: "上一张" | "下一张") {
  fireEvent.click(screen.getByRole("button", {name: direction}));
  act(() => vi.advanceTimersByTime(600));
}

function expectCurrent(number: number, count = 6) {
  expect(screen.getByText(`${number} / ${count} · 图片 ${number}`)).toBeInTheDocument();
  // Check the actual displayed slide too, not just our independently rendered caption.
  expect(document.querySelector(".yarl__slide_current img")).toHaveAttribute("src", `/original-${number}.png`);
}

it("keeps browsing position when polling recreates the image list", () => {
  const props = {index: 0, onClose: vi.fn()};
  const view = render(<ImagePreview {...props} images={images()} />);
  navigate("下一张");
  navigate("下一张");
  expectCurrent(3);

  view.rerender(<ImagePreview {...props} images={images()} />);
  expectCurrent(3);
  fireEvent.click(screen.getByRole("button", {name: "图片信息"}));
  expect(screen.getByRole("link", {name: "在新标签页打开原图"})).toHaveAttribute("href", "/original-3.png");
  expect(screen.getByText("prompt 3")).toBeInTheDocument();

  for (const number of [4, 5, 6]) {
    navigate("下一张");
    view.rerender(<ImagePreview {...props} images={images()} />);
    expectCurrent(number);
  }
  expect(screen.getByRole("button", {name: "下一张"})).toBeDisabled();
  navigate("上一张");
  view.rerender(<ImagePreview {...props} images={images()} />);
  expectCurrent(5);
});

it("honors a newly selected starting image and reopens at the clicked image", () => {
  const onClose = vi.fn();
  const view = render(<ImagePreview images={images()} index={1} onClose={onClose} />);
  expectCurrent(2);
  navigate("下一张");
  view.rerender(<ImagePreview images={images()} index={4} onClose={onClose} />);
  expectCurrent(5);
  navigate("下一张");
  expectCurrent(6);
  fireEvent.click(screen.getByRole("button", {name: "关闭预览"}));
  act(() => vi.advanceTimersByTime(600));
  expect(onClose).toHaveBeenCalledOnce();
  view.rerender(<></>);
  view.rerender(<ImagePreview images={images()} index={1} onClose={onClose} />);
  expectCurrent(2);
});

it("keeps a valid current image if the list becomes shorter", () => {
  const props = {index: 0, onClose: vi.fn()};
  const view = render(<ImagePreview {...props} images={images()} />);
  for (let step = 0; step < 5; step++) navigate("下一张");
  expectCurrent(6);
  view.rerender(<ImagePreview {...props} images={images(3)} />);
  expectCurrent(3, 3);
  expect(screen.getByRole("button", {name: "下一张"})).toBeDisabled();
});
