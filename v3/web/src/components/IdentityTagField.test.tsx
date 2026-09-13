import {useState} from "react";
import {act, cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {apiRequest} from "../lib/api";
import {IdentityTagField, type IdentitySuggestion} from "./IdentityTagField";
import {ManualIdentityTags} from "./ManualIdentityTags";

vi.mock("../lib/api", () => ({apiRequest: vi.fn()}));
const suggestion: IdentitySuggestion = {name: "hakurei_reimu", render_name: "hakurei reimu", cn_name: "博丽灵梦",
  kind: "character", favorite: false, match_kind: "cn_name", user_aliases: [],
  related_series: [{name: "touhou", cn_name: "东方", render_name: "touhou", cooc_count: 100}],
  knowledge: {status: "unknown", model_profile_id: null, reason: "没有验证"}};
const noPrefs = {favorites: [], recent: [], aliases: []};
let favorites: IdentitySuggestion[];

beforeEach(() => {
  favorites = [];
  vi.mocked(apiRequest).mockReset();
  vi.mocked(apiRequest).mockImplementation(async (path, init) => {
    if (path.includes("/preferences")) return {...noPrefs, favorites};
    if (path.includes("/search")) return {items: [suggestion]};
    if (path.endsWith("/favorite")) favorites = JSON.parse(String(init?.body)).enabled ? [{...suggestion, favorite: true}] : [];
    return {saved: true};
  });
});
afterEach(() => {cleanup(); vi.useRealTimers();});
function Field() {
  const [values, setValues] = useState<string[]>([]);
  return <IdentityTagField kind="character" label="角色输入" placeholder="输入角色" values={values} onChange={setValues} modelProfileId="anima_2_9b_preview_v1" />;
}
function searchRequests() {return vi.mocked(apiRequest).mock.calls.filter(call => call[0].includes("/search"));}

it("debounces typed names, chooses with arrows/Enter, and removes a selected tag", async () => {
  render(<Field />);
  const input = screen.getByRole("combobox");
  fireEvent.focus(input);
  fireEvent.change(input, {target: {value: "博"}});
  fireEvent.change(input, {target: {value: "博丽"}});
  fireEvent.change(input, {target: {value: "博丽灵梦"}});
  await screen.findByRole("option");
  expect(searchRequests()).toHaveLength(1);
  expect(searchRequests()[0][0]).toContain("model_profile_id=anima_2_9b_preview_v1");
  fireEvent.keyDown(input, {key: "ArrowDown"});
  expect(input).toHaveAttribute("aria-activedescendant");
  fireEvent.keyDown(input, {key: "Enter"});
  expect(input).toHaveValue("hakurei_reimu");
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("移除角色 hakurei reimu"));
  expect(input).toHaveValue("");
});

it("keeps free text and multi-tag paste without needing dictionary results", () => {
  render(<Field />);
  const input = screen.getByRole("combobox");
  fireEvent.change(input, {target: {value: "unlisted_hero"}});
  expect(input).toHaveValue("unlisted_hero");
  fireEvent.change(input, {target: {value: ""}});
  fireEvent.paste(input, {clipboardData: {getData: () => "unknown_one, unknown_two\nthird_(game)"}});
  expect(input).toHaveValue("unknown_one\nunknown_two\nthird_(game)");
  expect(screen.getByLabelText("已添加角色 tag")).toHaveTextContent("third (game)");
});

it("does not consume Enter or issue search while an IME is composing", async () => {
  vi.useFakeTimers();
  render(<Field />);
  const input = screen.getByRole("combobox");
  fireEvent.compositionStart(input);
  fireEvent.change(input, {target: {value: "れいむ"}});
  await act(async () => {await vi.advanceTimersByTimeAsync(300);});
  expect(searchRequests()).toHaveLength(0);
  fireEvent.keyDown(input, {key: "Enter", isComposing: true, keyCode: 229});
  expect(input).toHaveValue("れいむ");
  fireEvent.compositionEnd(input);
  await act(async () => {await vi.advanceTimersByTimeAsync(300);});
  expect(searchRequests()).toHaveLength(1);
  expect(screen.getByRole("option")).toBeInTheDocument();
  fireEvent.keyDown(input, {key: "Escape"});
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
});

it("aborts obsolete requests and ignores an older response even if it resolves late", async () => {
  let releaseOld: ((result: unknown) => void) | undefined;
  vi.mocked(apiRequest).mockImplementation(async path => {
    if (path.includes("/preferences")) return noPrefs;
    if (path.includes("q=old")) return new Promise(resolve => {releaseOld = resolve;});
    if (path.includes("/search")) return {items: [suggestion]};
    return {};
  });
  render(<Field />);
  const input = screen.getByRole("combobox");
  fireEvent.change(input, {target: {value: "old"}});
  await waitFor(() => expect(releaseOld).toBeDefined());
  const signal = searchRequests()[0][1]?.signal;
  fireEvent.change(input, {target: {value: "new"}});
  expect(signal?.aborted).toBe(true);
  await screen.findByRole("option");
  await act(async () => {releaseOld?.({items: [{...suggestion, name: "stale_result", cn_name: "旧结果"}]});});
  expect(screen.queryByText(/旧结果/)).not.toBeInTheDocument();
  expect(screen.getByRole("option")).toHaveTextContent("博丽灵梦");
});

it("lets selected names be favorited and reused from the persistent list", async () => {
  render(<Field />);
  const input = screen.getByRole("combobox");
  fireEvent.change(input, {target: {value: "hakurei_reimu"}});
  fireEvent.click(screen.getByLabelText("收藏角色 hakurei reimu"));
  await screen.findByLabelText("取消收藏角色 hakurei reimu");
  fireEvent.click(screen.getByLabelText("移除角色 hakurei reimu"));
  fireEvent.focus(input);
  const favoriteButton = await screen.findByRole("button", {name: "博丽灵梦"});
  fireEvent.click(favoriteButton);
  expect(input).toHaveValue("hakurei_reimu");
});

it("only adds a suggested series after explicit confirmation", async () => {
  function Form() {
    const [characters, setCharacters] = useState<string[]>([]);
    const [series, setSeries] = useState<string[]>([]);
    return <ManualIdentityTags characters={characters} series={series} artists={[]} onCharacters={setCharacters} onSeries={setSeries} onArtists={vi.fn()} />;
  }
  render(<Form />);
  fireEvent.click(screen.getByText("手动角色、作品与画师 tag（可选）"));
  const input = screen.getByLabelText("角色 tag（每行一个）");
  fireEvent.change(input, {target: {value: "博丽灵梦"}});
  fireEvent.click(await screen.findByRole("option"));
  const series = screen.getByLabelText("作品 tag（动画／游戏，每行一个）");
  expect(series).toHaveValue("");
  fireEvent.click(screen.getByRole("button", {name: /添加作品：东方/}));
  expect(series).toHaveValue("touhou");
});

it("saves user aliases explicitly and reports failure without dropping free tags", async () => {
  render(<Field />);
  fireEvent.click(screen.getByRole("button", {name: "管理角色别名"}));
  fireEvent.change(screen.getByLabelText("角色标准 tag"), {target: {value: "frieren"}});
  fireEvent.change(screen.getByLabelText("角色自定义别名"), {target: {value: "フリーレン"}});
  fireEvent.click(screen.getByRole("button", {name: "保存角色别名"}));
  await waitFor(() => expect(vi.mocked(apiRequest).mock.calls.some(([path, init]) => path.endsWith("/alias") &&
    JSON.parse(String(init?.body)).alias === "フリーレン")).toBe(true));
  vi.mocked(apiRequest).mockRejectedValue(new Error("词库暂时不可用"));
  const input = screen.getByRole("combobox");
  fireEvent.change(input, {target: {value: "free_hero"}});
  await screen.findByText(/词库暂时不可用/);
  expect(input).toHaveValue("free_hero");
});
