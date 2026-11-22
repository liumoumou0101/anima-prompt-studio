import type {LocalConversation} from "./conversation";

export interface ArtistPresetSnapshot {
  id: string; revision: number; name: string; positive: string; negative: string;
  model_family: "anima" | "sdxl" | "novelai" | "other" | "unknown";
  model_label: string; syntax: "comfy" | "novelai" | "plain" | "unknown";
  source_url: string; content_hash: string;
}

/** start/end own precisely the inserted prefix + raw block, never an inferred tag. */
export interface ArtistPresetRange {start: number; end: number; prefix: string}
export interface ArtistPresetPlacement {
  presetId: string; revision: number; contentHash: string;
  positive?: ArtistPresetRange; negative?: ArtistPresetRange;
}
const targets = ["positive", "negative"] as const;
const object = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === "object" && !Array.isArray(value);
const boundedString = (value: unknown, max: number, min = 0): value is string => typeof value === "string" && value.length >= min && value.length <= max;

/** Shared with durable draft validation; malformed snapshots must stay recoverable as raw backups. */
export function validArtistPresetSnapshot(value: unknown): value is ArtistPresetSnapshot {
  return object(value) && boundedString(value.id, 200, 1) && boundedString(value.name, 200, 1)
    && Number.isSafeInteger(value.revision) && Number(value.revision) >= 1
    && boundedString(value.positive, 20_000) && boundedString(value.negative, 20_000)
    && Boolean(value.positive.trim() || value.negative.trim())
    && typeof value.model_family === "string" && ["anima", "sdxl", "novelai", "other", "unknown"].includes(value.model_family)
    && boundedString(value.model_label, 200) && typeof value.syntax === "string" && ["comfy", "novelai", "plain", "unknown"].includes(value.syntax)
    && boundedString(value.source_url, 2000) && typeof value.content_hash === "string" && /^[a-f0-9]{64}$/.test(value.content_hash)
    && Object.keys(value).every(key => ["id", "revision", "name", "positive", "negative", "model_family", "model_label", "syntax", "source_url", "content_hash"].includes(key));
}

export function validArtistPresetPlacement(value: unknown): value is ArtistPresetPlacement {
  return object(value) && boundedString(value.presetId, 200, 1)
    && Number.isSafeInteger(value.revision) && Number(value.revision) >= 1
    && typeof value.contentHash === "string" && /^[a-f0-9]{64}$/.test(value.contentHash)
    && targets.every(target => value[target] === undefined || object(value[target])
      && Number.isSafeInteger(value[target].start) && Number(value[target].start) >= 0
      && Number.isSafeInteger(value[target].end) && Number(value[target].end) >= Number(value[target].start)
      && boundedString(value[target].prefix, 2) && ["", "\n", "\n\n"].includes(value[target].prefix));
}

function detach(local: LocalConversation, name?: string): LocalConversation {
  const result = structuredClone(local);
  delete result.requirements.layers.style.artist_preset;
  delete result.artistPresetPlacement;
  if (name) result.artistPresetCustomized = name;
  return result;
}

function validRange(text: string, raw: string, range?: ArtistPresetRange): boolean {
  if (!raw) return range === undefined;
  return Boolean(range && Number.isInteger(range.start) && Number.isInteger(range.end)
    && range.start >= 0 && range.end >= range.start && range.end <= text.length
    && typeof range.prefix === "string" && text.slice(range.start, range.end) === range.prefix + raw);
}

function validPlacement(local: LocalConversation): boolean {
  const preset = local.requirements.layers.style.artist_preset, placement = local.artistPresetPlacement;
  return Boolean(preset && placement && placement.presetId === preset.id && placement.revision === preset.revision
    && placement.contentHash === preset.content_hash && targets.every(target => validRange(local[target], preset[target], placement[target])));
}

/** On server/AI reload we can locate a unique exact raw block, but own no adjacent separators. */
export function reconcileArtistPresetCompiled(local: LocalConversation): LocalConversation {
  const preset = local.requirements.layers.style.artist_preset;
  if (!preset) {
    if (!local.artistPresetPlacement) return local;
    const result = {...local}; delete result.artistPresetPlacement; return result;
  }
  const presetName = typeof preset.name === "string" ? preset.name : "画师串";
  if (!validArtistPresetSnapshot(preset)) return detach(local, presetName);
  if (validPlacement(local)) return local;
  const placement: ArtistPresetPlacement = {presetId: preset.id, revision: preset.revision, contentHash: preset.content_hash};
  for (const target of targets) {
    const raw = preset[target];
    if (!raw) continue;
    const start = local[target].indexOf(raw);
    if (start < 0 || local[target].indexOf(raw, start + 1) >= 0) return detach(local, preset.name);
    placement[target] = {start, end: start + raw.length, prefix: ""};
  }
  return {...local, artistPresetPlacement: placement};
}

/** Remove only spans whose ownership and bytes are still known. Ambiguity keeps the text. */
export function removeArtistPreset(local: LocalConversation): LocalConversation {
  const current = reconcileArtistPresetCompiled(local);
  const preset = current.requirements.layers.style.artist_preset;
  if (!preset || !validPlacement(current)) return current;
  const result = detach(current);
  for (const target of targets) {
    const range = current.artistPresetPlacement?.[target];
    if (range) result[target] = current[target].slice(0, range.start) + current[target].slice(range.end);
  }
  delete result.artistPresetCustomized;
  return result;
}

/** Replace the managed selection as one reversible editor operation. */
export function applyArtistPreset(local: LocalConversation, preset: ArtistPresetSnapshot): LocalConversation {
  if (!preset.positive.trim() && !preset.negative.trim()) throw new Error("画师串没有可调用的原文。");
  const result = structuredClone(removeArtistPreset(local));
  const placement: ArtistPresetPlacement = {presetId: preset.id, revision: preset.revision, contentHash: preset.content_hash};
  for (const target of targets) {
    const raw = preset[target];
    if (!raw) continue;
    const prefix = !result[target] || result[target].endsWith("\n\n") ? "" : result[target].endsWith("\n") ? "\n" : "\n\n";
    const start = result[target].length;
    result[target] += prefix + raw;
    if (result[target].length > 20_000) throw new Error(`${target === "positive" ? "正向" : "负向"}提示词超过 20000 字，请先缩短内容。`);
    placement[target] = {start, end: result[target].length, prefix};
  }
  // Copy the contract fields explicitly: callers may pass a full library record
  // with sample images, notes or future properties that are not workspace data.
  const {id, revision, name, positive, negative, model_family, model_label, syntax, source_url, content_hash} = preset;
  result.requirements.layers.style.artist_preset = {id, revision, name, positive, negative,
    model_family, model_label, syntax, source_url, content_hash};
  result.artistPresetPlacement = placement;
  delete result.artistPresetCustomized;
  return result;
}

function mapRange(before: string, after: string, range: ArtistPresetRange): ArtistPresetRange | null {
  if (before === after) return {...range};
  let start = 0;
  while (start < before.length && start < after.length && before[start] === after[start]) start++;
  let oldEnd = before.length, newEnd = after.length;
  while (oldEnd > start && newEnd > start && before[oldEnd - 1] === after[newEnd - 1]) {oldEnd--; newEnd--;}
  if (oldEnd <= range.start) {
    const delta = newEnd - oldEnd;
    return {...range, start: range.start + delta, end: range.end + delta};
  }
  if (start >= range.end) return {...range};
  return null;
}

/** Call for plain text edits; an intersecting edit detaches both blocks without deleting either. */
export function reconcileArtistPresetEdit(before: LocalConversation, after: LocalConversation): LocalConversation {
  const prior = before.requirements.layers.style.artist_preset, selected = after.requirements.layers.style.artist_preset;
  if (!prior || !selected || JSON.stringify(prior) !== JSON.stringify(selected)) return after;
  const current = reconcileArtistPresetCompiled(before);
  if (!current.requirements.layers.style.artist_preset || !current.artistPresetPlacement) return detach(after, prior.name);
  const placement = structuredClone(current.artistPresetPlacement);
  for (const target of targets) {
    const range = placement[target];
    if (!range) continue;
    const mapped = mapRange(before[target], after[target], range);
    if (!mapped || !validRange(after[target], prior[target], mapped)) return detach(after, prior.name);
    placement[target] = mapped;
  }
  return {...after, artistPresetPlacement: placement};
}
