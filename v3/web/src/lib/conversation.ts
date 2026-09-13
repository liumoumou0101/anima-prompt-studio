import type {WorkbenchGenerationSettings, WorkspaceRecord} from "./types";
import {defaultGenerationSettings} from "./generationSettings";
import type {SceneChoice, SceneDesign} from "./sceneDesign";

export type LayerName = "subject" | "style" | "lighting" | "composition" | "exclusions";
export type Mode = "faithful" | "expand";
export const layerLabels: Record<LayerName, string> = {subject: "主体", style: "风格", lighting: "光影", composition: "构图", exclusions: "排除"};
export interface RequirementLayers {
  subject: {text: string; locked: boolean; character_tags?: string[]; series_tags?: string[]; general_tags?: string[]};
  style: {text: string; medium: string; artists: string[]; manual_artist_tags?: string[]; locked: boolean};
  lighting: {text: string; locked: boolean; include_with_style_pin: boolean; mood?: SceneChoice | null};
  composition: {text: string; shot: string; locked: boolean; include_with_style_pin: boolean; design?: SceneDesign | null};
  exclusions: {global: string[]; scoped: {target: string; concept: string}[]; locked: boolean};
}
export interface RequirementLora {
  logical_id: string; file_name: string; weight: number; trigger_words: string[]; required: boolean;
  source: {kind: "user" | "civitai" | "huggingface" | "official" | "run"; model_version_id?: string | null};
}
export interface RequirementsEdit {layers: RequirementLayers; loras: RequirementLora[]}
export interface CompiledPrompt {positive: string; negative: string; compiled_token: string; source: "llm" | "user"}
export interface ConversationEvent {id: string; delta: string; changed_layers: LayerName[]; warnings: string[]; created_at: string}
export interface ConversationRecord extends WorkspaceRecord {
  draft: WorkspaceRecord["draft"] & {
    mode: Mode; requirements: (RequirementsEdit & {contract: string; revision: number}) | null;
    compiled: CompiledPrompt | null; compile_state: "missing" | "fresh" | "stale";
    conversation_events: ConversationEvent[];
    reference_pin?: {example_id: string; source_version: string; role: string} | null;
    generation_source?: {run_id: string; remote_profile_id: string; workflow_profile_id: string; model_profile: string} | null;
  };
}
export interface LocalConversation {
  baseRevision: number; delta: string; mode: Mode; requirements: RequirementsEdit;
  positive: string; negative: string; model: string; settings: WorkbenchGenerationSettings;
}
export function emptyRequirements(): RequirementsEdit {
  return {layers: {subject: {text: "", locked: false}, style: {text: "", medium: "", artists: [], locked: false},
    lighting: {text: "", locked: false, include_with_style_pin: false},
    composition: {text: "", shot: "", locked: false, include_with_style_pin: false},
    exclusions: {global: [], scoped: [], locked: false}}, loras: []};
}
export function editableRequirements(record: ConversationRecord): RequirementsEdit {
  const requirement = record.draft.requirements;
  return requirement ? structuredClone({layers: requirement.layers, loras: requirement.loras}) : emptyRequirements();
}
export function normalizeIdentityTags(values: string[], artist = false): string[] {
  return [...new Set(values.map(value => (artist ? value.trim().replace(/^@+\s*/, "") : value.trim())
    .toLowerCase().replaceAll("_", " ").replace(/\\([()])/g, "$1").replace(/\s+/g, " ").trim()).filter(Boolean))];
}
export function cleanRequirements(value: RequirementsEdit): RequirementsEdit {
  const clean = structuredClone(value);
  clean.layers.style.artists = normalizeIdentityTags(clean.layers.style.artists, true);
  const artists = normalizeIdentityTags(clean.layers.style.manual_artist_tags || [], true);
  if (artists.length) clean.layers.style.manual_artist_tags = artists;
  else delete clean.layers.style.manual_artist_tags;
  for (const key of ["character_tags", "series_tags", "general_tags"] as const) {
    const tags = normalizeIdentityTags(clean.layers.subject[key] || []);
    if (tags.length) clean.layers.subject[key] = tags;
    else delete clean.layers.subject[key];
  }
  clean.layers.exclusions.global = clean.layers.exclusions.global.map(item => item.trim()).filter(Boolean);
  if (!clean.layers.lighting.mood) delete clean.layers.lighting.mood;
  const design = Object.fromEntries(Object.entries(clean.layers.composition.design || {}).filter(([, choice]) => choice != null));
  if (Object.keys(design).length) clean.layers.composition.design = design;
  else delete clean.layers.composition.design;
  for (const choice of [...Object.values(clean.layers.composition.design || {}), clean.layers.lighting.mood]) {
    if (!choice) continue;
    choice.value = choice.value.trim();
    choice.source ||= "user";
    if (choice.target?.trim()) choice.target = choice.target.trim(); else delete choice.target;
    if (choice.evidence?.trim()) choice.evidence = choice.evidence.trim(); else delete choice.evidence;
  }
  clean.layers.exclusions.scoped = clean.layers.exclusions.scoped.filter(item => item.target.trim() || item.concept.trim());
  clean.loras.forEach(item => {item.trigger_words = item.trigger_words.map(word => word.trim()).filter(Boolean);});
  return clean;
}
function comparable(value: unknown): string {
  return JSON.stringify(value, (_key, item) => item && typeof item === "object" && !Array.isArray(item)
    ? Object.fromEntries(Object.entries(item).sort(([left], [right]) => left.localeCompare(right))) : item);
}
export function hasUnsavedInputs(record: ConversationRecord, local: LocalConversation): boolean {
  return hasUncompiledInputs(record, local)
    || comparable(record.draft.generation_settings || defaultGenerationSettings()) !== comparable(local.settings);
}
export function hasUncompiledInputs(record: ConversationRecord, local: LocalConversation): boolean {
  return record.draft.model_profile !== local.model || record.draft.mode !== local.mode
    || comparable(cleanRequirements(editableRequirements(record))) !== comparable(cleanRequirements(local.requirements));
}
