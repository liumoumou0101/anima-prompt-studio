import {createElement, StrictMode} from "react";
import {cleanup, renderHook} from "@testing-library/react";
import {afterEach, expect, it, vi} from "vitest";
import {useBodyScrollLock} from "./useBodyScrollLock";

afterEach(() => {
  cleanup();
  document.documentElement.removeAttribute("style");
  document.body.removeAttribute("style");
  vi.restoreAllMocks();
});

it("reserves the gutter before hiding overflow without padding or scrolling the page", () => {
  document.body.style.paddingRight = "12px";
  const rootSet = vi.spyOn(document.documentElement.style, "setProperty");
  const bodySet = vi.spyOn(document.body.style, "setProperty");
  const scrollTo = vi.spyOn(window, "scrollTo");
  const scrollBy = vi.spyOn(window, "scrollBy");
  const {unmount} = renderHook(() => useBodyScrollLock());

  expect(document.documentElement.style.scrollbarGutter).toBe("stable");
  expect(document.body.style.overflow).toBe("hidden");
  expect(rootSet.mock.invocationCallOrder[0]).toBeLessThan(bodySet.mock.invocationCallOrder[0]);
  expect(document.body.style.paddingRight).toBe("12px");
  unmount();
  expect(document.documentElement.style.scrollbarGutter).toBe("");
  expect(document.body.style.overflow).toBe("");
  expect(document.body.style.paddingRight).toBe("12px");
  expect(scrollTo).not.toHaveBeenCalled();
  expect(scrollBy).not.toHaveBeenCalled();
});

it("keeps nested overlays locked until the last enabled owner releases it", () => {
  document.documentElement.style.setProperty("scrollbar-gutter", "auto", "important");
  document.body.style.setProperty("overflow", "scroll", "important");
  const first = renderHook(() => useBodyScrollLock());
  const second = renderHook(({enabled}) => useBodyScrollLock(enabled), {initialProps: {enabled: false}});
  second.rerender({enabled: true});
  first.unmount();
  expect(document.body.style.overflow).toBe("hidden");
  expect(document.documentElement.style.scrollbarGutter).toBe("stable");

  second.rerender({enabled: false});
  expect(document.body.style.overflow).toBe("scroll");
  expect(document.body.style.getPropertyPriority("overflow")).toBe("important");
  expect(document.documentElement.style.scrollbarGutter).toBe("auto");
  expect(document.documentElement.style.getPropertyPriority("scrollbar-gutter")).toBe("important");
});

it("preserves an existing stable gutter, overflow longhands, and unrelated style changes", () => {
  document.documentElement.style.setProperty("scrollbar-gutter", "stable both-edges", "important");
  document.body.style.setProperty("overflow-x", "clip", "important");
  document.body.style.setProperty("overflow-y", "scroll");
  const {unmount} = renderHook(() => useBodyScrollLock());
  expect(document.documentElement.style.scrollbarGutter).toBe("stable both-edges");
  document.body.style.backgroundColor = "red";
  unmount();

  expect(document.body.style.overflowX).toBe("clip");
  expect(document.body.style.getPropertyPriority("overflow-x")).toBe("important");
  expect(document.body.style.overflowY).toBe("scroll");
  expect(document.body.style.getPropertyPriority("overflow-y")).toBe("");
  expect(document.body.style.backgroundColor).toBe("red");
  expect(document.documentElement.style.scrollbarGutter).toBe("stable both-edges");
  expect(document.documentElement.style.getPropertyPriority("scrollbar-gutter")).toBe("important");
});

it("balances development StrictMode setup and cleanup", () => {
  const {unmount} = renderHook(() => useBodyScrollLock(), {
    wrapper: ({children}) => createElement(StrictMode, null, children),
  });
  expect(document.body.style.overflow).toBe("hidden");
  unmount();
  expect(document.body.style.overflow).toBe("");
  expect(document.documentElement.style.scrollbarGutter).toBe("");
});

it("does not introduce a gutter on short pages without a scrollbar", () => {
  vi.spyOn(document.documentElement, "clientWidth", "get").mockReturnValue(window.innerWidth);
  const {unmount} = renderHook(() => useBodyScrollLock());
  expect(document.body.style.overflow).toBe("hidden");
  expect(document.documentElement.style.scrollbarGutter).toBe("");
  unmount();
  expect(document.body.style.overflow).toBe("");
});
