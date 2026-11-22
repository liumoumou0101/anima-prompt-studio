import type {CompositionItem, TagRecord} from "./personalTags";
import {codePointLength} from "./textLength";

type Polarity = CompositionItem["polarity"];

function validWeight(weight: number): boolean {
  return Number.isFinite(weight) && weight >= 0.1 && weight <= 2 &&
    Math.abs(weight * 20 - Math.round(weight * 20)) < 1e-8;
}

/** Select a library snapshot; later library edits never change the selected item. */
export function addCompositionItem(items: CompositionItem[], tag: TagRecord, polarity: Polarity): CompositionItem[] {
  if (items.some(item => item.source_tag_id === tag.id && item.polarity === polarity)) return items;
  if (!validWeight(tag.default_weight)) throw new RangeError("Weight must be 0.1–2.0 in steps of 0.05");
  return [...items, {id: crypto.randomUUID(), source_tag_id: tag.id, display_name: tag.display_name,
    content: tag.content, kind: tag.kind, polarity, weight: tag.default_weight}];
}

/** Move one item past its adjacent item on the same side, leaving the other side in place. */
export function moveCompositionItem(items: CompositionItem[], itemId: string, direction: -1 | 1): CompositionItem[] {
  const index = items.findIndex(item => item.id === itemId);
  if (index < 0) return items;
  const side = items[index].polarity;
  let target = index + direction;
  while (target >= 0 && target < items.length && items[target].polarity !== side) target += direction;
  if (target < 0 || target >= items.length) return items;
  const moved = [...items];
  [moved[index], moved[target]] = [moved[target], moved[index]];
  return moved;
}

/** Render stored content verbatim, with the same size and weight limits as the API. */
export function renderComposition(items: CompositionItem[]): {positive: string; negative: string; warnings: string[]} {
  if (items.length > 300) throw new RangeError("Composition cannot exceed 300 items");
  const sides: Record<Polarity, string[]> = {positive: [], negative: []};
  const contents: Record<Polarity, Set<string>> = {positive: new Set(), negative: new Set()};
  for (const item of items) {
    if (!validWeight(item.weight)) throw new RangeError("Weight must be 0.1–2.0 in steps of 0.05");
    if (item.polarity !== "positive" && item.polarity !== "negative") throw new Error("Invalid polarity");
    if (!item.content.trim()) throw new Error("Snapshot content cannot be blank");
    const output = item.weight === 1 ? item.content : `(${item.content}:${Number(item.weight.toFixed(2))})`;
    sides[item.polarity].push(output);
    contents[item.polarity].add(item.content);
  }
  const positive = sides.positive.join(", ");
  const negative = sides.negative.join(", ");
  if (codePointLength(positive) > 20_000 || codePointLength(negative) > 20_000)
    throw new RangeError("Output cannot exceed 20000 characters per side");
  const warnings = [...contents.positive].filter(content => contents.negative.has(content))
    .map(content => `正负向同时包含：${content}`);
  return {positive, negative, warnings};
}
