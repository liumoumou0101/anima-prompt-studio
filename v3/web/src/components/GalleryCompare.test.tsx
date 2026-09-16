import {useState} from "react";
import {fireEvent, render, screen, within} from "@testing-library/react";
import {afterEach, expect, it, vi} from "vitest";
import type {GalleryAsset} from "../lib/types";
import {GalleryCompare} from "./GalleryCompare";

function asset(index: number, overrides: Partial<GalleryAsset> = {}): GalleryAsset {
  return {id: `image-${index}`, path: `batch/image-${index}.png`, name: `image-${index}.png`, project: "测试项目",
    model_profile: "anima", batch_id: "batch", batch_title: "生成批次", created_at: "2026-09-16T08:00:00Z",
    positive_prompt: "a forest", negative_prompt: "", width: 1024, height: 1536, byte_size: 1024,
    source: "generated", state: "", candidate: {id: "", lane: "", versions: {}},
    content_url: `/original-${index}.png`, thumbnail_url: `/thumbnail-${index}.png`, ...overrides};
}

afterEach(() => vi.restoreAllMocks());

it("opens in a body portal, contains keyboard focus and restores the trigger without scrolling on Escape", () => {
  function Harness() {
    const [open, setOpen] = useState(false);
    return <><button onClick={() => setOpen(true)}>比较所选图片</button><button>背景操作</button>
      {open && <GalleryCompare assets={[asset(1), asset(2)]} onClose={() => setOpen(false)} />}</>;
  }
  const {container} = render(<Harness />);
  const trigger = screen.getByRole("button", {name: "比较所选图片"});
  trigger.focus();
  const focus = vi.spyOn(trigger, "focus");
  fireEvent.click(trigger);
  const dialog = screen.getByRole("dialog", {name: "图片比较"});
  const close = within(dialog).getByRole("button", {name: "关闭比较"});
  expect(dialog.parentElement).toBe(document.body);
  expect(dialog).toHaveAttribute("aria-modal", "true");
  expect(container.inert).toBe(true);
  expect(close).toHaveFocus();
  fireEvent.keyDown(close, {key: "Tab"});
  expect(close).toHaveFocus();
  fireEvent.keyDown(close, {key: "Tab", shiftKey: true});
  expect(close).toHaveFocus();
  fireEvent.keyDown(close, {key: "Escape"});
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(container.inert).not.toBe(true);
  expect(trigger).toHaveFocus();
  expect(focus).toHaveBeenLastCalledWith({preventScroll: true});
});

it("locks page scroll without dropping the scrollbar gutter and restores existing styles and inert state", () => {
  const {body, documentElement: root} = document;
  const originalOverflow = body.style.overflow;
  const originalPadding = body.style.paddingRight;
  const originalGutter = root.style.scrollbarGutter;
  body.style.overflow = "auto";
  body.style.paddingRight = "7px";
  root.style.scrollbarGutter = "";
  vi.spyOn(root, "clientWidth", "get").mockReturnValue(window.innerWidth - 15);
  const existingOverlay = document.createElement("div");
  existingOverlay.inert = true;
  body.append(existingOverlay);
  try {
    const {unmount} = render(<GalleryCompare assets={[asset(1), asset(2)]} onClose={vi.fn()} />);
    expect(body.style.overflow).toBe("hidden");
    expect(body.style.paddingRight).toBe("7px");
    expect(root.style.scrollbarGutter).toBe("stable");
    unmount();
    expect(body.style.overflow).toBe("auto");
    expect(body.style.paddingRight).toBe("7px");
    expect(root.style.scrollbarGutter).toBe("");
    expect(existingOverlay.inert).toBe(true);
  } finally {
    existingOverlay.remove();
    body.style.overflow = originalOverflow;
    body.style.paddingRight = originalPadding;
    root.style.scrollbarGutter = originalGutter;
  }
});

it("shows original images and readable per-image metadata for four candidates, including exact large seeds and zero", () => {
  const onClose = vi.fn();
  const assets = [asset(1, {generation_params: {seed: "8798399215689017476", steps: 30, cfg: 4.5}}),
    asset(2, {generation_params: {seed: 0}}), asset(3, {model_profile: "", width: null, height: null}), asset(4)];
  render(<GalleryCompare assets={assets} onClose={onClose} />);
  const dialog = screen.getByRole("dialog", {name: "图片比较"});
  expect(within(dialog).getAllByRole("figure")).toHaveLength(4);
  for (const item of assets) {
    expect(within(dialog).getByRole("img", {name: item.name})).toHaveAttribute("src", item.content_url);
    expect(within(dialog).getByText(item.name)).toBeVisible();
  }
  expect(within(dialog).getByText("8798399215689017476")).toBeVisible();
  expect(within(dialog).getByText("0")).toBeVisible();
  expect(within(dialog).getByText("30")).toBeVisible();
  expect(within(dialog).getByText("4.5")).toBeVisible();
  fireEvent.click(within(dialog).getByRole("button", {name: "关闭比较"}));
  expect(onClose).toHaveBeenCalledOnce();
});
