import {expect, it} from "vitest";
import {addCompositionItem, moveCompositionItem, renderComposition} from "./personalTagComposition";
import type {CompositionItem, TagRecord} from "./personalTags";

const tag = (id: string, content = "Blue_eyes", weight = 1.1): TagRecord => ({
  id, display_name: id, content, default_weight: weight, kind: "tag", aliases: [],
  category_id: null, notes: "", revision: 1, created_at: "", updated_at: "",
  deleted_at: null, source_key: null, source_id: null, source_metadata: {}, needs_review: [],
});
const item = (id: string, content: string, polarity: CompositionItem["polarity"] = "positive", weight = 1): CompositionItem =>
  ({id, source_tag_id: id, display_name: id, content, kind: "tag", polarity, weight});

it("preserves_raw_text_and_formats_explicit_weights", () => {
  expect(renderComposition([item("a", "Blue_eyes", "positive", 1.1), item("b", "a, b\nc")]))
    .toEqual({positive: "(Blue_eyes:1.1), a, b\nc", negative: "", warnings: []});
  expect(renderComposition([item("a", "Blue_eyes", "positive", 1.0)]) .positive).toBe("Blue_eyes");
  for (const weight of [NaN, Infinity, -Infinity, 0.09, 2.05, 1.03]) {
    expect(() => renderComposition([item("a", "x", "positive", weight)])).toThrow();
  }
});

it("deduplicates_only_same_source_and_side", () => {
  const one = tag("one"); const two = tag("two");
  const first = addCompositionItem([], one, "positive");
  expect(addCompositionItem(first, one, "positive")).toBe(first);
  const both = addCompositionItem(addCompositionItem(first, two, "positive"), one, "negative");
  expect(both).toHaveLength(3);
  expect(both.map(entry => entry.source_tag_id)).toEqual(["one", "two", "one"]);
  expect(renderComposition(both).warnings).toHaveLength(1);
  expect(moveCompositionItem(both, both[0].id, 1).map(entry => entry.source_tag_id))
    .toEqual(["two", "one", "one"]);
  expect(moveCompositionItem(both, both[2].id, -1)).toBe(both);
});

it("does_not_mutate_library_defaults", () => {
  const source = tag("original", "a, b\nc", 1.25);
  const selected = addCompositionItem([], source, "positive");
  expect(selected[0]).toMatchObject({content: "a, b\nc", weight: 1.25, source_tag_id: "original"});
  selected[0] = {...selected[0], weight: 1.5};
  source.content = "changed";
  expect(selected[0].content).toBe("a, b\nc");
  expect(source.default_weight).toBe(1.25);
});

it("rejects_server_size_limits_before_rendering", () => {
  expect(() => renderComposition(Array.from({length: 301}, (_, index) => item(String(index), "x")))).toThrow();
  expect(() => renderComposition([item("a", "x".repeat(20_001))])).toThrow();
});

it.each(["", " \n\t "])("rejects blank snapshot content %j", content => {
  expect(() => renderComposition([item("blank", content)])).toThrow(/blank|empty/i);
});

it("counts Unicode code points and preserves surrounding raw whitespace", () => {
  const raw = " \n" + "😀".repeat(19_997) + " ";
  expect(renderComposition([item("unicode", raw)]).positive).toBe(raw);
  expect(() => renderComposition([item("unicode", raw + "😀")])).toThrow(/20000/);
});
