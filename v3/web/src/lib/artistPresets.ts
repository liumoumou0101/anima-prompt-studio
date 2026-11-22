import {apiRequest} from "./api";

export type ArtistModelFamily = "anima" | "sdxl" | "novelai" | "other" | "unknown";
export type ArtistPresetSyntax = "comfy" | "novelai" | "plain" | "unknown";
export interface ArtistPresetWrite {
  name: string; positive: string; negative: string; model_family: ArtistModelFamily;
  model_label: string; syntax: ArtistPresetSyntax; source_url: string; source_author: string;
  notes: string; favorite: boolean;
}
export interface ArtistPresetSample {
  id: string; content_hash: string; image_url: string; width: number; height: number;
  model_label: string; source_url: string; caption: string; full_positive: string; full_negative: string;
  parameters: Record<string, unknown>; source_kind: "upload" | "reference"; source_id: string; created_at: string;
}
export interface ArtistPreset extends ArtistPresetWrite {
  id: string; revision: number; content_hash: string; created_at: string; updated_at: string;
  samples: ArtistPresetSample[]; ready: boolean;
}
export interface ArtistPresetSuggestion {
  reference_id: string; name: string; positive: string; model_label: string; source_url: string;
  thumbnail_url: string; notes: string;
}
export interface ArtistPresetImportPreview {
  items: Array<{name: string; model_label?: string; sample_count?: number}>;
  duplicates: number; warnings: string[]; token: string;
}
export interface ArtistSampleWrite {
  caption: string; model_label: string; source_url: string; full_positive: string;
  full_negative: string; parameters: Record<string, unknown>;
}
export const artistModelLabels: Record<ArtistModelFamily, string> = {
  anima: "Anima", sdxl: "SDXL / Illustrious", novelai: "NovelAI", other: "其他模型", unknown: "模型未注明",
};
export function artistPresetModelLabel(preset: Pick<ArtistPreset, "model_family" | "model_label">): string {
  const family = artistModelLabels[preset.model_family] || artistModelLabels.unknown;
  return preset.model_label ? `${family} · ${preset.model_label}` : family;
}
export function artistPresetWrite(preset: ArtistPresetWrite): ArtistPresetWrite {
  const {name, positive, negative, model_family, model_label, syntax, source_url, source_author, notes, favorite} = preset;
  return {name, positive, negative, model_family, model_label, syntax, source_url, source_author, notes, favorite};
}
export function currentArtistSample(preset: ArtistPreset): ArtistPresetSample | undefined {
  return preset.samples.find(sample => sample.content_hash === preset.content_hash);
}
const prefix = "/api/v3/artist-presets";
const path = (id: string) => `${prefix}/${encodeURIComponent(id)}`;
const json = (method: string, body: unknown): RequestInit => ({method, body: JSON.stringify(body)});
export const artistPresetsApi = {
  list: () => apiRequest<{items: ArtistPreset[]}>(prefix),
  get: (id: string) => apiRequest<ArtistPreset>(path(id)),
  create: (value: ArtistPresetWrite) => apiRequest<ArtistPreset>(prefix, json("POST", value)),
  update: (id: string, value: ArtistPresetWrite, expected_revision: number) =>
    apiRequest<ArtistPreset>(path(id), json("PUT", {...value, expected_revision})),
  remove: (id: string, expected_revision: number) =>
    apiRequest<void>(`${path(id)}?expected_revision=${expected_revision}`, {method: "DELETE", headers: {"Content-Type": "application/json"}}),
  uploadSample: (id: string, file: File, value: ArtistSampleWrite, expected_revision: number) => {
    const body = new FormData(); body.append("file", file); body.append("metadata", JSON.stringify({...value, expected_revision}));
    return apiRequest<ArtistPreset>(`${path(id)}/samples`, {method: "POST", body});
  },
  removeSample: (id: string, sampleId: string, expected_revision: number) =>
    apiRequest<ArtistPreset>(`${path(id)}/samples/${encodeURIComponent(sampleId)}?expected_revision=${expected_revision}`, {method: "DELETE", headers: {"Content-Type": "application/json"}}),
  suggestions: () => apiRequest<{items: ArtistPresetSuggestion[]}>(`${prefix}/suggestions`),
  fromReference: (reference_id: string) => apiRequest<ArtistPreset>(`${prefix}/from-reference`, json("POST", {reference_id})),
  export: (presetId?: string) => apiRequest<unknown>(`${prefix}/export${presetId ? `?preset_id=${encodeURIComponent(presetId)}` : ""}`),
  previewImport: (document: unknown) => apiRequest<ArtistPresetImportPreview>(`${prefix}/import-preview`, json("POST", {document})),
  import: (document: unknown, token: string) => apiRequest<{items: ArtistPreset[]; skipped: number}>(`${prefix}/import`, json("POST", {document, token})),
};
