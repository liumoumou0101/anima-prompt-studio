import {fireEvent, render, screen, waitFor, within} from "@testing-library/react";
import {MemoryRouter, Route, Routes} from "react-router-dom";
import {beforeEach, expect, it, vi} from "vitest";
import {ArtistDetailPage} from "./ArtistDetailPage";
import {ArtistSearchPage} from "./ArtistSearchPage";

beforeEach(() => {
  sessionStorage.setItem("anima-v3-session", "session-token");
  sessionStorage.removeItem("anima-v3-tag-basket");
  vi.restoreAllMocks();
});

it("searches artist tags and opens their context profile", async () => {
  const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    summary: {artist_count: 24636, post_count: 1000000, association_count: 614772},
    items: [{id: 1, name: "sample_artist", render_name: "@sample artist", post_count: 700, association_count: 2, preview_tags: [{name: "maid", render_name: "maid", cn_name: "女仆", category_name: "general", cooc_count: 400, npmi: .5}]}],
    total: 1, offset: 0, limit: 48, has_more: false, data_pack_id: "pack-r1",
  }), {status: 200}));

  render(<MemoryRouter initialEntries={["/artists"]}><Routes><Route path="/artists" element={<ArtistSearchPage />} /></Routes></MemoryRouter>);

  expect(await screen.findByRole("heading", {name: "画师研究室"})).toBeInTheDocument();
  expect(screen.getByText("女仆")).toBeInTheDocument();
  expect(screen.getByRole("link", {name: /查看适用场景/})).toHaveAttribute("href", "/artists/sample_artist");
  fireEvent.change(screen.getByRole("textbox", {name: "搜索画师标签"}), {target: {value: "@sample artist"}});
  fireEvent.click(screen.getByRole("button", {name: "分析"}));
  await waitFor(() => expect(fetchSpy).toHaveBeenLastCalledWith(expect.stringContaining("q=%40sample+artist"), expect.anything()));
});

it("filters an artist's context clues and adds them to the scene basket", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    id: 1, name: "sample_artist", render_name: "@sample artist", post_count: 700, association_count: 3,
    contexts: [
      {id: 1, name: "maid", render_name: "maid", cn_name: "女仆", category: 0, category_name: "general", post_count: 5000, nsfw: false, deprecated: false, groups: [{id: "tag_group:attire", name: "attire", cn_name: "服装"}], dimensions: ["appearance"], cooc_count: 400, coverage: .5714, npmi: .5, association_score: .5, rank: 1, algorithm_version: "npmi-v1", data_pack_id: "pack-r1"},
      {id: 2, name: "underwear", render_name: "underwear", cn_name: "内衣", category: 0, category_name: "general", post_count: 900, nsfw: true, deprecated: false, groups: [], dimensions: ["appearance"], cooc_count: 120, coverage: .1714, npmi: .4, association_score: .4, rank: 2, algorithm_version: "npmi-v1", data_pack_id: "pack-r1"},
      {id: 3, name: "hakurei_reimu", render_name: "hakurei reimu", cn_name: "博丽灵梦", category: 4, category_name: "character", post_count: 2500, nsfw: false, deprecated: false, groups: [], dimensions: ["character"], cooc_count: 80, coverage: .1143, npmi: .3, association_score: .3, rank: 3, algorithm_version: "npmi-v1", data_pack_id: "pack-r1"},
    ],
    dimension_counts: {appearance: 2, character: 1}, safety_summary: {safe_count: 2, nsfw_count: 1, unknown_count: 0},
    analysis_note: "关联强度来自历史标签共现，不是 ANIMA 生成质量评分。", data_pack_id: "pack-r1",
  }), {status: 200}));

  render(<MemoryRouter initialEntries={["/artists/sample_artist"]}><Routes><Route path="/artists/:name" element={<ArtistDetailPage />} /></Routes></MemoryRouter>);

  expect(await screen.findByRole("heading", {name: "@sample artist"})).toBeInTheDocument();
  expect(within(screen.getByRole("region", {name: "关联场景列表"})).getByText("女仆")).toBeInTheDocument();
  expect(within(screen.getByRole("region", {name: "关联场景列表"})).queryByText("内衣")).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", {name: "关联标签敏感内容"}), {target: {value: "nsfw"}});
  expect(within(screen.getByRole("region", {name: "关联场景列表"})).getByText("内衣")).toBeInTheDocument();
  expect(within(screen.getByRole("region", {name: "关联场景列表"})).queryByText("女仆")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "选择 内衣"}));
  expect(screen.getByText("已挑选 1 个标签")).toBeInTheDocument();
  expect(screen.getByRole("link", {name: /内衣/})).toHaveAttribute("href", "/tags/underwear?source=artist&artist=sample_artist");
});
