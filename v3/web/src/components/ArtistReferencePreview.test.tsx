import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {ArtistReferencePreview} from "./ArtistReferencePreview";

beforeEach(() => sessionStorage.setItem("anima-v3-session", "test"));
afterEach(() => {cleanup(); vi.restoreAllMocks();});

it("loads only when expanded and labels LoRA-dependent model outputs", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({items: [{
    id: "ex_a", title: "水彩示例", artists: ["artist_a", "artist_b"], model: "anima-base-v1.0", content_level: "safe",
    lora_dependency: "lora", thumbnail_url: "/api/v3/gallery/reference-examples/ex_a/thumbnail", reference_url: "/references?example=ex_a"}]})));
  const view = render(<MemoryRouter><ArtistReferencePreview artist="artist_a" /></MemoryRouter>);
  expect(fetchMock).not.toHaveBeenCalled();
  const details = view.container.querySelector("details")!;
  details.open = true; fireEvent(details, new Event("toggle"));
  const image = await screen.findByRole("img", {name: "水彩示例"});
  expect(image).toHaveAttribute("src", "/api/v3/gallery/reference-examples/ex_a/thumbnail");
  expect(screen.getByText("anima-base-v1.0 · 含 LoRA")).toBeInTheDocument();
  expect(screen.getByText(/组合画师：@artist_a、@artist_b/)).toBeInTheDocument();
  expect(screen.getByRole("link")).toHaveAttribute("href", "/references?example=ex_a");
  expect(screen.getByText(/不是画师原作/)).toBeInTheDocument();
});

it("states that evidence is missing when no safe samples exist", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({items: []})));
  const view = render(<MemoryRouter><ArtistReferencePreview artist="missing_artist" /></MemoryRouter>);
  const details = view.container.querySelector("details")!;
  details.open = true; fireEvent(details, new Event("toggle"));
  await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
  expect(await screen.findByText(/本地还没有该画师的一般内容参考样图/)).toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
});
