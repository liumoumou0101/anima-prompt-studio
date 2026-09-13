import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {afterEach, expect, it, vi} from "vitest";
import {ManualIdentityTags} from "./ManualIdentityTags";
import {cleanRequirements, emptyRequirements, normalizeIdentityTags} from "../lib/conversation";

afterEach(cleanup);
it("previews normalized tags without changing prompt text", () => {
  const onCharacters = vi.fn();
  render(<ManualIdentityTags characters={["Unknown_Hero_(Game)"]} series={["Example_Game"]} artists={["@Sample_Artist"]}
    onCharacters={onCharacters} onSeries={vi.fn()} onArtists={vi.fn()} />);
  fireEvent.click(screen.getByText("手动角色、作品与画师 tag（可选）"));
  expect(screen.getByLabelText("手动 tag 预览")).toHaveTextContent("unknown hero \\(game\\), example game, @sample artist");
  fireEvent.change(screen.getByLabelText("角色 tag（每行一个）"), {target: {value: "new_character\nsecond_character"}});
  expect(onCharacters).toHaveBeenCalledWith(["new_character", "second_character"]);
});
it("cleans pasted artists and preserves character disambiguation", () => {
  const req = emptyRequirements();
  req.layers.subject.character_tags = ["Unknown_Hero_(Game)", "unknown hero (game)", ""];
  req.layers.subject.series_tags = [""];
  req.layers.style.artists = ["@Sample_Artist", "sample artist"];
  const clean = cleanRequirements(req);
  expect(clean.layers.subject.character_tags).toEqual(["unknown hero (game)"]);
  expect(clean.layers.subject.series_tags).toBeUndefined();
  expect(clean.layers.style.artists).toEqual(["sample artist"]);
  expect(normalizeIdentityTags(["@@Some_Name"], true)).toEqual(["some name"]);
});

it("keeps compact fields mounted and preserves expansion while editing within a record", async () => {
  const props = {series: [], artists: [], onCharacters: vi.fn(), onSeries: vi.fn(), onArtists: vi.fn()};
  const {rerender} = render(<ManualIdentityTags key="first" compact characters={[]} {...props} />);
  const input = screen.getByLabelText("角色 tag（每行一个）");
  const details = input.closest("details")!;
  expect(details).not.toHaveAttribute("open");
  fireEvent.click(screen.getByText("角色、作品与画师"));
  await waitFor(() => expect(details).toHaveAttribute("open"));

  rerender(<ManualIdentityTags key="first" compact characters={["example_hero"]} {...props} />);
  expect(screen.getByText("· 已选 1 项")).toBeInTheDocument();
  rerender(<ManualIdentityTags key="first" compact characters={[]} {...props} />);
  expect(details).toHaveAttribute("open");
  fireEvent.click(screen.getByText("角色、作品与画师"));
  await waitFor(() => expect(details).not.toHaveAttribute("open"));
  expect(screen.getByLabelText("角色 tag（每行一个）")).toBe(input);

  rerender(<ManualIdentityTags key="second" compact characters={["example_hero"]} {...props} />);
  expect(screen.getByLabelText("角色 tag（每行一个）").closest("details")).toHaveAttribute("open");
});
