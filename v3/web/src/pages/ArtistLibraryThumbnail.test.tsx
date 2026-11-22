import {cleanup, fireEvent, render, screen} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {ArtistLibraryThumbnail} from "./ArtistLibraryThumbnail";
import {apiRequest} from "../lib/api";

vi.mock("../lib/api", () => ({apiRequest: vi.fn()}));
beforeEach(() => vi.mocked(apiRequest).mockReset());
afterEach(cleanup);

it("shows only an actual safe local example and links its exact source", async () => {
  vi.mocked(apiRequest).mockResolvedValue({items: [{id: "ex_real", title: "真实案例", content_level: "safe", model: "AnimaYume 1.5",
    thumbnail_url: "/api/v3/gallery/reference-examples/ex_real/thumbnail", reference_url: "/references?example=ex_real"}]});
  render(<MemoryRouter><ArtistLibraryThumbnail artist="sample_artist" /></MemoryRouter>);
  const image = await screen.findByRole("img", {name: "真实案例"});
  expect(image).toHaveAttribute("src", "/api/v3/gallery/reference-examples/ex_real/thumbnail");
  expect(screen.getByRole("link")).toHaveAttribute("href", "/references?example=ex_real");
  expect(screen.getByText("模型案例 · AnimaYume 1.5")).toBeInTheDocument();
  fireEvent.error(image);
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(screen.getByText("样图暂不可用")).toBeInTheDocument();
});

it("uses an explicit no-sample state instead of an invented portrait", async () => {
  vi.mocked(apiRequest).mockResolvedValue({items: [{id: "ex_unknown", title: "未标记来源", content_level: "unknown",
    thumbnail_url: "/unknown.png", reference_url: "/references?example=ex_unknown"}]});
  render(<MemoryRouter><ArtistLibraryThumbnail artist="unrepresented_artist" /></MemoryRouter>);
  await screen.findByText("本地暂无样图");
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
});
