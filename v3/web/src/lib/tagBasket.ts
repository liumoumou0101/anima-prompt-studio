import {useMemo, useState} from "react";
import type {TagDetail, TagSearchItem} from "./types";

export const TAG_BASKET_KEY = "anima-v3-tag-basket";

export function useTagBasket() {
  const [selected, setSelected] = useState<TagSearchItem[]>(loadTagBasket);
  const selectedNames = useMemo(() => new Set(selected.map((item) => item.name)), [selected]);

  function commit(items: TagSearchItem[]) {
    setSelected(items);
    try { sessionStorage.setItem(TAG_BASKET_KEY, JSON.stringify(items)); } catch { /* best effort */ }
  }

  function toggle(item: TagSearchItem) {
    commit(selected.some((entry) => entry.name === item.name)
      ? selected.filter((entry) => entry.name !== item.name)
      : [...selected, item]);
  }

  return {selected, selectedNames, toggle, clear: () => commit([])};
}

export function tagDetailToSearchItem(detail: TagDetail): TagSearchItem {
  return {id: detail.id, name: detail.name, display_name: detail.display_name, cn_name: detail.cn_name, category: detail.category_name, post_count: detail.post_count, nsfw: detail.nsfw, match: {kind: "detail", score: null}};
}

function loadTagBasket(): TagSearchItem[] {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(TAG_BASKET_KEY) || "[]") as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is TagSearchItem => Boolean(item && typeof item === "object" && "name" in item && typeof item.name === "string"));
  } catch {
    return [];
  }
}
