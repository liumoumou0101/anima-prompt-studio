import {useState} from "react";
import {fireEvent, render, screen, waitFor} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {beforeEach, afterEach, expect, it, vi} from "vitest";
import {ArtistRecommendations, artistSeeds} from "./ArtistRecommendations";
const artist = {name: "artist_one", render_name: "@artist one", post_count: 1234, sources: ["scenery"], hit_count: 1};
beforeEach(() => {localStorage.clear(); sessionStorage.setItem("anima-v3-session", "test");});
afterEach(() => vi.restoreAllMocks());
function Harness() {const [selected, setSelected] = useState(["kept_artist"]); return <MemoryRouter><ArtistRecommendations prompt="scenery, (watercolor:1.2), @existing" selected={selected} disabled={false} onChange={setSelected} /></MemoryRouter>;}
it("loads only on demand and preserves selected artists across all ranking modes", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async url => new Response(JSON.stringify(String(url).includes("/settings/") ? {ranking: "tag_fit"} : {items: [artist]})));
  render(<Harness />);
  expect(fetchMock).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", {name: "画师推荐（可选）"}));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", {name: "刷新画师推荐"}));
  fireEvent.click(await screen.findByRole("button", {name: "加入画面要求"}));
  expect(screen.getByRole("button", {name: "移除画师 kept_artist"})).toBeInTheDocument();
  for (const mode of ["volume", "balanced"]) {
    fireEvent.change(screen.getByRole("combobox", {name: "推荐模式"}), {target: {value: mode}});
    await screen.findByRole("button", {name: "已加入"});
    expect(screen.getByRole("button", {name: "移除画师 artist_one"})).toBeInTheDocument();
  }
  const requests = fetchMock.mock.calls.filter(call => String(call[0]).endsWith("/recommend"));
  expect(requests.map(call => JSON.parse(String(call[1]?.body)).ranking)).toEqual(["tag_fit", "volume", "balanced"]);
  expect(JSON.parse(String(requests[0][1]?.body)).tags).toEqual(["scenery", "watercolor"]);
  expect(localStorage.getItem("anima-workbench-artist-ranking")).toBe("balanced");
  fireEvent.click(screen.getByRole("button", {name: "画师推荐（可选）"}));
  fireEvent.click(screen.getByRole("button", {name: "画师推荐（可选）"}));
  expect(screen.getByRole("button", {name: "移除画师 artist_one"})).toBeInTheDocument();
});
it("ignores a superseded response when switching modes during a query", async () => {
  localStorage.setItem("anima-workbench-artist-ranking", "tag_fit");
  let finish: (value: Response) => void = () => {};
  vi.spyOn(globalThis, "fetch").mockImplementationOnce(() => new Promise(resolve => {finish = resolve;}))
    .mockResolvedValue(new Response(JSON.stringify({items: [{...artist, name: "new_artist", render_name: "@new"}]})));
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", {name: "画师推荐（可选）"}));
  fireEvent.click(screen.getByRole("button", {name: "刷新画师推荐"}));
  fireEvent.change(screen.getByRole("combobox", {name: "推荐模式"}), {target: {value: "balanced"}});
  await screen.findByText("@new");
  finish(new Response(JSON.stringify({items: [artist]})));
  await waitFor(() => expect(screen.queryByText("@artist one")).not.toBeInTheDocument());
  expect(screen.getByText("@new")).toBeInTheDocument();
});
it("invalidates recommendations when seed tags change and never calls the API with too many tags", async () => {
  localStorage.setItem("anima-workbench-artist-ranking", "tag_fit");
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({items: [artist]})));
  render(<Harness />); fireEvent.click(screen.getByRole("button", {name: "画师推荐（可选）"}));
  fireEvent.click(screen.getByRole("button", {name: "刷新画师推荐"}));
  await screen.findByText("@artist one");
  fireEvent.change(screen.getByLabelText("推荐依据标签"), {target: {value: Array.from({length: 51}, (_, i) => `tag_${i}`).join(",")}});
  expect(screen.queryByText("@artist one")).not.toBeInTheDocument();
  expect(screen.getByRole("button", {name: "刷新画师推荐"})).toBeDisabled();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
it("only parses explicit tag boundaries and excludes existing artist and LoRA directives", () => {
  expect(artistSeeds("scenery, scenery; (flower:1.1), @a, <lora:x:1>, girl by a window")).toEqual(["scenery", "flower", "girl_by_a_window"]);
});
