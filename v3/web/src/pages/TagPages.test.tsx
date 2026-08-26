import {render, screen, waitFor} from "@testing-library/react";
import {MemoryRouter, Route, Routes} from "react-router-dom";
import {beforeEach, expect, it, vi} from "vitest";
import {TagDetailPage} from "./TagDetailPage";
import {TagSearchPage} from "./TagSearchPage";

beforeEach(() => {
  sessionStorage.setItem("anima-v3-session", "session-token");
  vi.restoreAllMocks();
});

it("renders local tag search results and links to details", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    items: [{id: 1, name: "maid", display_name: "maid", cn_name: "女仆", category: "general", post_count: 100, nsfw: false, match: {kind: "search", score: null}}],
    next_cursor: null,
    data_pack_id: "pack-r1",
  }), {status: 200}));

  render(<MemoryRouter initialEntries={["/tags?q=maid"]}><Routes><Route path="/tags" element={<TagSearchPage />} /></Routes></MemoryRouter>);

  expect(await screen.findByText("女仆")).toBeInTheDocument();
  expect(screen.getByRole("link", {name: /maid/})).toHaveAttribute("href", "/tags/maid");
  await waitFor(() => expect(screen.getByText("1 个匹配结果")).toBeInTheDocument());
});

it("renders aliases, groups, wiki and related tags in detail", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
    id: 1, name: "maid", display_name: "maid", cn_name: "女仆", category: 0, category_name: "general", post_count: 100,
    nsfw: false, deprecated: false, created_at: null, cn_terms: ["女佣"], wiki_summary: "女仆服装说明。", aliases: ["maid_uniform"],
    groups: [{id: "tag_group:attire", name: "attire", cn_name: "服装"}],
    related: [{id: 2, name: "maid_apron", render_name: "maid apron", cn_name: "女仆围裙", category: 0, category_name: "general", post_count: 50, nsfw: false, raw_score: .7, display_score: 1, cooc_count: 40, sources: ["maid"], algorithm_version: "npmi-v1", data_pack_id: "pack-r1"}],
    preview: {available: false, online: false}, data_pack_id: "pack-r1",
  }), {status: 200}));

  render(<MemoryRouter initialEntries={["/tags/maid"]}><Routes><Route path="/tags/:name" element={<TagDetailPage />} /></Routes></MemoryRouter>);

  expect(await screen.findByText("女仆服装说明。")).toBeInTheDocument();
  expect(screen.getByText("maid_uniform")).toBeInTheDocument();
  expect(screen.getByText("服装")).toBeInTheDocument();
  expect(screen.getByRole("link", {name: /maid apron/})).toHaveAttribute("href", "/tags/maid_apron");
});
