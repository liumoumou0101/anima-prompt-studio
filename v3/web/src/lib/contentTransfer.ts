import {cleanRequirements, normalizeIdentityTags, type RequirementsEdit} from "./conversation";
import type {TagCategory} from "./types";

export type SelectedContent = {name: string; category: TagCategory};
export type ContentTransfer = {id: string; destination: "current" | "new"; items: SelectedContent[]; created: number};
const prefix = "anima-content-transfer:";
const categories = ["character", "copyright", "artist", "general", "meta"];
const normalize = (item: SelectedContent) => normalizeIdentityTags([item.name], item.category === "artist")[0] || "";
const field = (item: SelectedContent) => item.category === "character" ? "character_tags" : item.category === "copyright" ? "series_tags" : "general_tags";

export function transferUrl(items: SelectedContent[], destination: ContentTransfer["destination"] = "current"): string {
  const transfer: ContentTransfer = {id: crypto.randomUUID(), destination, items, created: Date.now()};
  validate(transfer);
  // The address carries only an opaque identifier; selected names remain local.
  localStorage.setItem(prefix + transfer.id, JSON.stringify(transfer));
  return `/workbench?transfer=${transfer.id}`;
}
function validate(value: ContentTransfer) {
  if (!value || !/^[\w-]{1,80}$/.test(value.id) || !["current", "new"].includes(value.destination)
    || !Array.isArray(value.items) || !value.items.length || value.items.length > 192
    || !Number.isFinite(value.created) || Date.now() - value.created > 7 * 86400000
    || value.items.some(item => !item || !categories.includes(item.category) || typeof item.name !== "string"
      || !normalize(item) || item.name.length > 200 || /[,，\n\r<>]/.test(item.name)
      || normalize(item).includes("@"))) throw new Error("带入内容无效或已过期，请从标签或画师页面重新选择。");
}
export function readTransfer(id: string): ContentTransfer | null {
  if (!/^[\w-]{1,80}$/.test(id)) throw new Error("带入内容标识无效。");
  const raw = localStorage.getItem(prefix + id);
  if (!raw) return null;
  const value = JSON.parse(raw) as ContentTransfer;
  validate(value);
  if (value.id !== id) throw new Error("带入内容标识不匹配。");
  return value;
}
export function consumeTransfer(id: string) {localStorage.removeItem(prefix + id);}

export function applySelectedContent(requirements: RequirementsEdit, items: SelectedContent[]) {
  const next = cleanRequirements(requirements), added: SelectedContent[] = [];
  for (const item of items) {
    const name = normalize(item);
    if (!name) continue;
    const values = item.category === "artist" ? next.layers.style.manual_artist_tags ||= [] : next.layers.subject[field(item)] ||= [];
    const existing = item.category === "artist" ? [...values, ...next.layers.style.artists] : values;
    if (normalizeIdentityTags(existing, item.category === "artist").includes(name)) continue;
    if (values.length >= (item.category === "general" || item.category === "meta" ? 64 : 32)) throw new Error("该分类已达到标签数量上限，请先移除一些标签再带入。");
    values.push(name); added.push({...item, name});
  }
  return {requirements: next, added};
}
export function undoSelectedContent(requirements: RequirementsEdit, added: SelectedContent[]): RequirementsEdit {
  const next = structuredClone(requirements);
  for (const item of added) {
    const keep = (name: string) => normalizeIdentityTags([name], item.category === "artist")[0] !== normalize(item);
    if (item.category === "artist") next.layers.style.manual_artist_tags = (next.layers.style.manual_artist_tags || []).filter(keep);
    else next.layers.subject[field(item)] = (next.layers.subject[field(item)] || []).filter(keep);
  }
  return cleanRequirements(next);
}
