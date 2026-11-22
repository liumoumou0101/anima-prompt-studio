import {apiRequest} from "./api";

const ROOT = "/api/v3/personal-tags";

export interface CategoryWrite {
  name: string;
  parent_id?: string | null;
  position?: number;
}

export interface CategoryRecord extends CategoryWrite {
  id: string;
  parent_id: string | null;
  position: number;
  revision: number;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  source_key: string | null;
  source_id: string | null;
  source_metadata: Record<string, unknown>;
  needs_review: string[];
}

export interface TagWrite {
  display_name: string;
  content: string;
  aliases?: string[];
  category_id?: string | null;
  kind?: "tag" | "fragment";
  notes?: string;
  default_weight?: number;
}

export interface TagRecord extends TagWrite {
  id: string;
  aliases: string[];
  category_id: string | null;
  kind: "tag" | "fragment";
  notes: string;
  default_weight: number;
  revision: number;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  source_key: string | null;
  source_id: string | null;
  source_metadata: Record<string, unknown>;
  needs_review: string[];
}

export interface CompositionItem {
  id: string;
  source_tag_id: string | null;
  display_name: string;
  content: string;
  kind: "tag" | "fragment";
  polarity: "positive" | "negative";
  weight: number;
}

export interface CompositionWrite {
  name: string;
  items: CompositionItem[];
}

export interface CompositionRecord extends CompositionWrite {
  id: string;
  revision: number;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface DraftRecord {
  items: CompositionItem[];
  revision: number;
  updated_at: string;
}

export interface TagPage {
  items: TagRecord[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
}

export interface ImportOptions {
  use_legacy_weights?: boolean;
  fragment_ids?: string[];
}

export interface ImportIssue {
  code: string;
  entity: string;
  source_id: string;
  message: string;
  blocking: boolean;
}

export interface ImportCounts {
  new: number;
  existing: number;
  invalid: number;
  similar: number;
  unmapped: number;
  fragment_candidates: number;
  legacy_weights: number;
}

export interface ImportPreview {
  digest: string;
  library_revision: number;
  counts: ImportCounts;
  issues: ImportIssue[];
}

export interface ImportResult {
  counts: ImportCounts;
  issues: ImportIssue[];
  library_revision: number;
}

export interface PersonalTagBundle {
  format: "anima-personal-tags";
  version: 1;
  source_key: string;
  categories: CategoryRecord[];
  tags: TagRecord[];
  combinations: CompositionRecord[];
  draft: DraftRecord | null;
}

const json = (value: unknown): RequestInit => ({body: JSON.stringify(value), headers: {"Content-Type": "application/json"}});
const query = (values: Record<string, string | number | boolean | null | undefined>): string => {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) if (value !== null && value !== undefined) params.set(key, String(value));
  const text = params.toString();
  return text ? `?${text}` : "";
};
const idPath = (section: string, id: string): string => `${ROOT}/${section}/${encodeURIComponent(id)}`;

export const personalTagsApi = {
  listCategories: (trash = false) => apiRequest<CategoryRecord[]>(`${ROOT}/categories${query({trash})}`),
  createCategory: (value: CategoryWrite) => apiRequest<CategoryRecord>(`${ROOT}/categories`, {method: "POST", ...json(value)}),
  updateCategory: (id: string, value: CategoryWrite, expected_revision: number) =>
    apiRequest<CategoryRecord>(idPath("categories", id), {method: "PUT", ...json({value, expected_revision})}),
  deleteCategory: (id: string, expected_revision: number) =>
    apiRequest<CategoryRecord>(`${idPath("categories", id)}${query({expected_revision})}`, {method: "DELETE", headers: {"Content-Type": "application/json"}}),
  restoreCategory: (id: string, expected_revision: number) =>
    apiRequest<CategoryRecord>(`${idPath("categories", id)}/restore`, {method: "POST", ...json({expected_revision})}),

  listTags: (filters: {q?: string; category_id?: string | null; include_descendants?: boolean; trash?: boolean;
                       offset?: number; limit?: number} = {}) => apiRequest<TagPage>(`${ROOT}/tags${query(filters)}`),
  createTag: (value: TagWrite) => apiRequest<TagRecord>(`${ROOT}/tags`, {method: "POST", ...json(value)}),
  findSimilar: (content: string, exclude_id?: string, limit = 20) =>
    apiRequest<TagRecord[]>(`${ROOT}/tags/similar${query({content, exclude_id, limit})}`),
  getTag: (id: string) => apiRequest<TagRecord>(idPath("tags", id)),
  updateTag: (id: string, value: TagWrite, expected_revision: number) =>
    apiRequest<TagRecord>(idPath("tags", id), {method: "PUT", ...json({value, expected_revision})}),
  deleteTag: (id: string, expected_revision: number) =>
    apiRequest<TagRecord>(`${idPath("tags", id)}${query({expected_revision})}`, {method: "DELETE", headers: {"Content-Type": "application/json"}}),
  restoreTag: (id: string, expected_revision: number) =>
    apiRequest<TagRecord>(`${idPath("tags", id)}/restore`, {method: "POST", ...json({expected_revision})}),
  bulkMove: (items: {id: string; revision: number}[], category_id: string | null) =>
    apiRequest<{moved: number}>(`${ROOT}/tags/bulk-move`, {method: "POST", ...json({items, category_id})}),

  listCombinations: (trash = false) => apiRequest<CompositionRecord[]>(`${ROOT}/combinations${query({trash})}`),
  createCombination: (value: CompositionWrite) =>
    apiRequest<CompositionRecord>(`${ROOT}/combinations`, {method: "POST", ...json(value)}),
  getCombination: (id: string) => apiRequest<CompositionRecord>(idPath("combinations", id)),
  updateCombination: (id: string, value: CompositionWrite, expected_revision: number) =>
    apiRequest<CompositionRecord>(idPath("combinations", id), {method: "PUT", ...json({value, expected_revision})}),
  deleteCombination: (id: string, expected_revision: number) =>
    apiRequest<CompositionRecord>(`${idPath("combinations", id)}${query({expected_revision})}`, {method: "DELETE", headers: {"Content-Type": "application/json"}}),
  restoreCombination: (id: string, expected_revision: number) =>
    apiRequest<CompositionRecord>(`${idPath("combinations", id)}/restore`, {method: "POST", ...json({expected_revision})}),

  getDraft: () => apiRequest<DraftRecord>(`${ROOT}/draft`),
  saveDraft: (items: CompositionItem[], expected_revision: number) =>
    apiRequest<DraftRecord>(`${ROOT}/draft`, {method: "PUT", ...json({items, expected_revision})}),
  previewImport: (document: Record<string, unknown>, options: ImportOptions = {}) =>
    apiRequest<ImportPreview>(`${ROOT}/imports/preview`, {method: "POST", ...json({document, options})}),
  commitImport: (document: Record<string, unknown>, options: ImportOptions, digest: string,
                 expected_library_revision: number) =>
    apiRequest<ImportResult>(`${ROOT}/imports/commit`,
      {method: "POST", ...json({document, options, digest, expected_library_revision})}),
  export: () => apiRequest<PersonalTagBundle>(`${ROOT}/export`),
};
