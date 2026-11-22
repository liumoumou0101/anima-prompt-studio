import {fireEvent, render, screen} from "@testing-library/react";
import {expect, it, vi} from "vitest";
import {GalleryReferenceButton} from "./GalleryReferenceButton";
it("saves a gallery case and links to the saved entry", async () => {
  sessionStorage.setItem("anima-v3-session", "test");
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({id: "ex_saved"})));
  render(<GalleryReferenceButton path="batch/image.png" disabled={false} />);
  fireEvent.click(screen.getByRole("button", {name: "存入参考案例库"}));
  expect(await screen.findByRole("link", {name: "已存入案例库 · 打开案例"})).toHaveAttribute("href", "/references?example=ex_saved");
  expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({path: "batch/image.png"});
  vi.restoreAllMocks();
});
