import {fireEvent, render, screen, waitFor} from "@testing-library/react";
import {MemoryRouter, Route, Routes, useLocation} from "react-router-dom";
import {beforeEach, expect, it, vi} from "vitest";
import {TagDetailPage} from "./TagDetailPage";
import {TagGroupPage} from "./TagGroupPage";
import {TagSearchPage} from "./TagSearchPage";
import {TagUngroupedPage} from "./TagUngroupedPage";

beforeEach(() => {
  sessionStorage.setItem("anima-v3-session", "session-token");
  sessionStorage.removeItem("anima-v3-tag-basket");
  vi.restoreAllMocks();
});

it("opens a complete shelf and preserves its basket selection on tag details", async () => {
  const maid = {id: 1, name: "maid", display_name: "maid", cn_name: "女仆", category: "general", post_count: 5000, nsfw: false, match: {kind: "group", score: null}};
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    if (String(input).startsWith("/api/v3/tag-groups/attire")) return new Response(JSON.stringify({
      group: {id: "tag_group:attire", name: "attire", cn_name: "服装", title: "服装", description: "常见服装与角色着装"}, items: [maid], total: 1, offset: 0, limit: 80, has_more: false, data_pack_id: "pack-r1",
    }), {status: 200});
    return new Response(JSON.stringify({
      ...maid, category: 0, category_name: "general", deprecated: false, created_at: null, cn_terms: ["女佣"], wiki_summary: "女仆服装说明。", aliases: [], groups: [{id: "tag_group:attire", name: "attire", cn_name: "服装"}], related: [], preview: {available: false, online: false}, data_pack_id: "pack-r1",
    }), {status: 200});
  });

  render(<MemoryRouter initialEntries={["/tags/groups/attire"]}><Routes><Route path="/tags/groups/:groupName" element={<TagGroupPage />} /><Route path="/tags/:name" element={<TagDetailPage />} /></Routes></MemoryRouter>);

  expect(await screen.findByRole("heading", {name: "服装"})).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "选择 女仆"}));
  fireEvent.click(screen.getByRole("link", {name: /女仆/}));
  expect(await screen.findByText("女仆服装说明。")).toBeInTheDocument();
  expect(screen.getByRole("button", {name: "已加入标签篮"})).toBeInTheDocument();
  expect(screen.getByRole("link", {name: "← 返回完整分组"})).toHaveAttribute("href", "/tags/groups/attire");
});

it("browses grouped shelves, previews and sends selected tags to the workbench", async () => {
  const maid = {id: 1, name: "maid", display_name: "maid", cn_name: "女仆", category: "general", post_count: 5000, nsfw: false, match: {kind: "group", score: null}};
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.startsWith("/api/v3/tags/browse")) return new Response(JSON.stringify({
      featured: [maid], groups: [{id: "tag_group:attire", name: "attire", cn_name: "服装", title: "服装", description: "常见服装与角色着装", tag_count: 531, items: [maid]}], other_groups: [{id: "tag_group:colors", name: "colors", cn_name: "颜色", tag_count: 65}], ungrouped: {total: 43783, safe_count: 39991, nsfw_count: 3792, unknown_count: 0, category_counts: {general: 17043, character: 21995, copyright: 4745}, items: [maid]}, data_pack_id: "pack-r1",
    }), {status: 200});
    return new Response(JSON.stringify({
      ...maid, category: 0, category_name: "general", deprecated: false, created_at: null, cn_terms: ["女佣"], wiki_summary: "女仆服装说明。", aliases: [], groups: [], related: [], preview: {available: false, online: false}, data_pack_id: "pack-r1",
    }), {status: 200});
  });

  render(<MemoryRouter initialEntries={["/tags"]}><Routes><Route path="/tags" element={<TagSearchPage />} /><Route path="/workbench" element={<LocationProbe />} /></Routes></MemoryRouter>);

  expect(await screen.findByRole("heading", {name: "服装"})).toBeInTheDocument();
  expect(screen.getByRole("link", {name: /颜色/})).toHaveAttribute("href", "/tags/groups/colors");
  expect(screen.getByRole("link", {name: /浏览完整标签库/})).toHaveAttribute("href", "/tags/ungrouped");
  fireEvent.change(screen.getByRole("textbox", {name: "筛选更多标签分组"}), {target: {value: "missing"}});
  expect(screen.getByText("没有匹配的标签分组，试试更短的关键词。")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("textbox", {name: "筛选更多标签分组"}), {target: {value: ""}});
  fireEvent.click(screen.getAllByRole("button", {name: "预览 女仆"})[0]);
  expect(await screen.findByText("女仆服装说明。")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "加入标签篮"}));
  fireEvent.click(screen.getByRole("button", {name: "带入工作台"}));
  expect(await screen.findByText("?tag=maid")).toBeInTheDocument();
});

it("browses ungrouped tags and can show only NSFW entries", async () => {
  const safeTag = {id: 2, name: "twintails", display_name: "twintails", cn_name: "双马尾", category: "general", post_count: 3000, nsfw: false, match: {kind: "ungrouped", score: null}};
  const nsfwTag = {id: 3, name: "underwear", display_name: "underwear", cn_name: "内衣", category: "general", post_count: 900, nsfw: true, match: {kind: "ungrouped", score: null}};
  const summary = {total: 43783, safe_count: 39991, nsfw_count: 3792, unknown_count: 0, category_counts: {general: 17043, character: 21995, copyright: 4745}};
  const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    const onlyNsfw = url.includes("safety=nsfw");
    return new Response(JSON.stringify({summary, items: onlyNsfw ? [nsfwTag] : [safeTag], total: 1, offset: 0, limit: 80, has_more: false, data_pack_id: "pack-r1"}), {status: 200});
  });

  render(<MemoryRouter initialEntries={["/tags/ungrouped"]}><Routes><Route path="/tags/ungrouped" element={<TagUngroupedPage />} /><Route path="/tags/:name" element={<TagDetailPage />} /></Routes></MemoryRouter>);

  expect(await screen.findByRole("heading", {name: "独立标签库"})).toBeInTheDocument();
  expect(screen.getByText("双马尾")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "仅显示敏感"}));
  expect(await screen.findByText("内衣")).toBeInTheDocument();
  expect(fetchSpy).toHaveBeenCalledWith(expect.stringContaining("safety=nsfw"), expect.anything());
  fireEvent.click(screen.getByRole("button", {name: "选择 内衣"}));
  expect(screen.getByText("已挑选 1 个标签")).toBeInTheDocument();
  expect(screen.getByRole("link", {name: /内衣/})).toHaveAttribute("href", "/tags/underwear?source=ungrouped");
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

function LocationProbe() {
  return <span>{useLocation().search}</span>;
}
