import type {TagCategory} from "../lib/types";

const labels: Record<TagCategory, string> = {
  general: "General",
  artist: "Artist",
  copyright: "Copyright",
  character: "Character",
  meta: "Meta",
};

export function TagBadge({category}: {category: TagCategory}) {
  return <span className={`tag-badge tag-badge--${category}`}>{labels[category]}</span>;
}

export function NsfwBadge({value}: {value: boolean | null}) {
  if (value === false) return null;
  return <span className={`safety-badge ${value ? "safety-badge--nsfw" : "safety-badge--unknown"}`}>
    {value ? "NSFW" : "未分级"}
  </span>;
}
