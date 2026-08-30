export type TagCategory = "general" | "artist" | "copyright" | "character" | "meta";

export interface DataPackSummary {
  id: string | null;
  ready: boolean;
  cutoff_mode: "exact" | "approximate" | null;
}

export interface BootstrapResponse {
  app_version: string;
  api_version: string;
  data_pack: DataPackSummary;
  features: Record<string, boolean>;
  model_profiles: string[];
  settings_summary: Record<string, unknown>;
}

export interface TagSearchItem {
  id: number;
  name: string;
  display_name: string;
  cn_name: string | null;
  category: TagCategory;
  post_count: number;
  nsfw: boolean | null;
  match: {kind: string; score: number | null};
}

export interface RelatedTag {
  id: number;
  name: string;
  render_name: string;
  cn_name: string | null;
  category: number;
  category_name: TagCategory;
  post_count: number;
  nsfw: boolean | null;
  raw_score: number;
  display_score: number;
  cooc_count: number;
  sources: string[];
  algorithm_version: string;
  data_pack_id: string;
}

export interface TagGroup {
  id: string;
  name: string;
  cn_name: string | null;
}

export interface TagDetail {
  id: number;
  name: string;
  display_name: string;
  cn_name: string | null;
  category: number;
  category_name: TagCategory;
  post_count: number;
  nsfw: boolean | null;
  deprecated: boolean;
  created_at: string | null;
  cn_terms: string[];
  wiki_summary: string | null;
  aliases: string[];
  groups: TagGroup[];
  related: RelatedTag[];
  preview: {available: boolean; online: boolean};
  data_pack_id: string;
}

export interface SearchResponse {
  items: TagSearchItem[];
  next_cursor: string | null;
  data_pack_id: string;
}

export interface TagBrowseGroup {
  id: string;
  name: string;
  cn_name: string | null;
  title: string;
  description: string;
  tag_count: number;
  items: TagSearchItem[];
}

export interface TagGroupSummary {
  id: string;
  name: string;
  cn_name: string | null;
  tag_count: number;
}

export interface TagUngroupedSummary {
  total: number;
  safe_count: number;
  nsfw_count: number;
  unknown_count: number;
  category_counts: Partial<Record<TagCategory, number>>;
}

export interface TagUngroupedPreview extends TagUngroupedSummary {
  items: TagSearchItem[];
}

export interface TagBrowseResponse {
  featured: TagSearchItem[];
  groups: TagBrowseGroup[];
  other_groups: TagGroupSummary[];
  ungrouped: TagUngroupedPreview;
  data_pack_id: string;
}

export interface TagGroupResponse {
  group: Omit<TagBrowseGroup, "tag_count" | "items">;
  items: TagSearchItem[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
  data_pack_id: string;
}

export interface TagUngroupedResponse {
  summary: TagUngroupedSummary;
  items: TagSearchItem[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
  data_pack_id: string;
}

export interface ApiErrorPayload {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
    request_id: string;
    retryable: boolean;
  };
}

export type CandidateLane = "literal" | "conservative" | "artist" | "hybrid";

export interface CandidateTag {
  name: string;
  rendered: string;
  state: "locked" | "required" | "user_selected" | "suggested" | "automatic";
  source: "user" | "exact" | "alias" | "translation" | "semantic" | "cooccurrence" | "artist";
  source_element_ids: string[];
  reason: string;
  raw_score: number | null;
  display_score: number | null;
  removable: boolean;
}

export interface CandidateArtist {
  name: string;
  rendered: string;
  source_element_ids: string[];
  reason: string;
  display_score: number | null;
  removable: boolean;
}

export interface ArtistSuggestion {
  name: string;
  render_name: string;
  post_count: number;
  raw_score: number;
  display_score: number;
  cooc_count: number;
  sources: string[];
  hit_count: number;
  algorithm_version: string;
  data_pack_id: string;
}

export interface ArtistSummary {
  artist_count: number;
  post_count: number;
  association_count: number;
}

export interface ArtistPreviewTag {
  name: string;
  render_name: string;
  cn_name: string | null;
  category_name: TagCategory;
  cooc_count: number;
  npmi: number | null;
}

export interface ArtistSearchItem {
  id: number;
  name: string;
  render_name: string;
  post_count: number;
  association_count: number;
  preview_tags: ArtistPreviewTag[];
}

export interface ArtistSearchResponse {
  summary: ArtistSummary;
  items: ArtistSearchItem[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
  data_pack_id: string;
}

export type ArtistContextDimension = "composition" | "setting" | "action" | "appearance" | "character" | "copyright" | "meta" | "motif";

export interface ArtistContextTag {
  id: number;
  name: string;
  render_name: string;
  cn_name: string | null;
  category: number;
  category_name: TagCategory;
  post_count: number;
  nsfw: boolean | null;
  deprecated: boolean;
  groups: TagGroup[];
  dimensions: ArtistContextDimension[];
  cooc_count: number;
  coverage: number;
  npmi: number | null;
  association_score: number | null;
  rank: number;
  algorithm_version: string;
  data_pack_id: string;
}

export interface ArtistDetail {
  id: number;
  name: string;
  render_name: string;
  post_count: number;
  association_count: number;
  contexts: ArtistContextTag[];
  dimension_counts: Partial<Record<ArtistContextDimension, number>>;
  safety_summary: {safe_count: number; nsfw_count: number; unknown_count: number};
  analysis_note: string;
  data_pack_id: string;
}

export interface ArtistComparisonInfo {
  id: string;
  artist: string;
  rendered_artist: string;
  position: number;
  total: number;
  seed: number;
}

export interface ArtistComparisonSubmission {
  comparison_id: string;
  project_name: string;
  seed: number;
  requested_count: number;
  submitted: Array<{artist: string; run: GenerationRunRecord}>;
  failed: Array<{artist: string; error: string}>;
}

export interface TagSuggestion {
  id: number;
  name: string;
  render_name: string;
  cn_name: string | null;
  category: number;
  category_name: TagCategory;
  post_count: number;
  nsfw: boolean | null;
  deprecated: boolean;
  raw_score: number;
  display_score: number;
  cooc_count: number;
  sources: string[];
  algorithm_version: string;
  data_pack_id: string;
}

export interface SceneDraftItem {
  id: string;
  text: string;
  canonical_tag: string | null;
  source: "source_exact" | "source_excluded" | "translation_exact" | "user_selected" | "unresolved";
  fact_type?: "subject" | "character" | "appearance" | "clothing" | "action" | "object" | "scene" | "composition" | "style" | "quality" | "relation" | "other";
  owner_entity_id?: string | null;
  suggested_owner_entity_id?: string | null;
  reason: string;
  source_start: number | null;
  source_end: number | null;
}

export interface SceneEntity {
  id: string;
  label: string;
  canonical_tag: string;
  source_element_id: string;
  source_start: number | null;
  source_end: number | null;
}

export interface SceneRelation {
  id: string;
  source_entity_id: string;
  target_element_id: string;
  relation: "wearing";
  state: "suggested" | "confirmed";
  phrase: string;
  reason: string;
}

export interface SceneDraft {
  source_text: string;
  translated_text: string;
  entities?: SceneEntity[];
  relations?: SceneRelation[];
  confirmed: SceneDraftItem[];
  exclusions: SceneDraftItem[];
  suggestions: SceneDraftItem[];
  unresolved: SceneDraftItem[];
  risk_notes: string[];
}

export interface CandidateWarning {
  code: string;
  message: string;
  element_ids: string[];
}

export interface PromptCandidate {
  id: string;
  lane: CandidateLane;
  title: string;
  positive_prompt: string;
  negative_prompt: string;
  artists: CandidateArtist[];
  tags: CandidateTag[];
  preserved_element_ids: string[];
  unresolved_element_ids: string[];
  warnings: CandidateWarning[];
  score_breakdown: Record<string, number>;
  versions: {
    data_pack: string;
    algorithm: string;
    templates: string;
    model_profile: string;
  };
}

export interface WorkbenchResponse {
  intent: IntentDocument;
  candidates: PromptCandidate[];
  validation: {valid: boolean; error_count: number};
  artist_suggestions?: ArtistSuggestion[];
  tag_suggestions?: TagSuggestion[];
  scene_draft?: SceneDraft;
  data_pack_id: string;
}

export interface IntentElement {
  id: string;
  original_text: string;
  type: string;
  state: string;
  confidence: number;
  notes: string[];
}

export interface IntentDocument {
  source_text: string;
  source_language: "zh" | "en" | "mixed";
  translated_text: string | null;
  scene_plan_en: string | null;
  scene_negative_en: string[];
  graph: {elements: IntentElement[]; edges: unknown[]};
  warnings: Array<{code: string; message: string; element_ids: string[]}>;
}

export interface IntentParseResponse {
  intent: IntentDocument;
  extraction: {
    summary_zh: string;
    people_count: number;
    subject_mode: string;
    content_rating: string;
    scene_type: string;
    truncated_source: boolean;
  };
  parser: {name: string; source: "v2_ai_extract" | "v2_local_translation"};
}

export interface WorkspaceDraft {
  positive_text: string;
  excluded_text: string;
  model_profile: string;
  input_mode?: "concepts" | "natural";
  natural_text?: string;
  selected_tags?: string[];
}

export interface WorkspaceRecord {
  id: string;
  title: string;
  draft: WorkspaceDraft;
  revision: number;
  created_at: string;
  updated_at: string;
  candidate_snapshot?: WorkbenchResponse | null;
}

export interface WorkspaceListResponse {
  items: WorkspaceRecord[];
}

export type GenerationRunState = "draft" | "connecting" | "preparing" | "queued" | "running" | "downloading" | "completed" | "failed" | "canceled" | "remote_missing";
export type GenerationRunAction = "cancel_queued" | "retry_check" | "continue_download";

export interface GenerationRunRecord {
  id: string;
  prompt_job_id: string;
  remote_profile_id: string;
  workflow_profile_id: string;
  state: GenerationRunState;
  progress: number;
  status_message: string;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  artifact_count: number;
  available_actions: GenerationRunAction[];
  error: {code: string; message: string} | null;
  artist_comparison?: ArtistComparisonInfo | null;
}

export interface GenerationRunListResponse {
  items: GenerationRunRecord[];
}

export interface GenerationTarget {
  remote_profile_id: string;
  remote_display_name: string;
  workflow_profile_id: string;
  workflow_display_name: string;
  workflow_kind: string;
  compatible_model_profiles: string[];
  host_fingerprint_ready: boolean;
  auth_type: "private_key" | "password" | "agent";
  private_key_passphrase_configured: boolean;
}

export interface GenerationTargetListResponse {
  items: GenerationTarget[];
}

export interface TranslationResponse {
  translated_text: string;
  direction: "zh_en" | "en_zh";
  engine: string;
  local_only: true;
  model_ready: boolean;
}

export interface GalleryAsset {
  id: string;
  path: string;
  name: string;
  project: string;
  model_profile: string;
  batch_id: string;
  batch_title: string;
  created_at: string;
  positive_prompt: string;
  negative_prompt: string;
  width: number | null;
  height: number | null;
  byte_size: number;
  generation_params?: Record<string, string | number | boolean>;
  source: "generated" | "external";
  state: string;
  candidate: {id: string; lane: string; versions: Record<string, string>};
  artist_comparison?: ArtistComparisonInfo | null;
  content_url: string;
  thumbnail_url: string;
}

export interface GalleryResponse {
  root: string;
  items: GalleryAsset[];
  projects: string[];
  models: string[];
  trash_count: number;
  processing?: GalleryProcessingConfiguration;
}

export interface GalleryProcessingConfiguration {
  available: boolean;
  reason?: string;
  scale?: number;
  workflowName?: string;
  regenAvailable: boolean;
  regenReason?: string;
  regenWorkflowName?: string;
  regenMaxCount?: number;
  activeCount?: number;
  queuedCount?: number;
  failedCount?: number;
  totalCount?: number;
}

export interface GalleryProcessJob {
  id: string;
  operation: string;
  state: string;
  message: string;
  progress: number;
  sourceName: string;
  resultPath?: string;
  error?: string;
}

export interface GalleryTrashAsset {
  id: string;
  path: string;
  original_path: string;
  name: string;
  byte_size: number;
  created_at: number;
  content_url: string;
  thumbnail_url: string;
}

export interface GalleryTrashResponse {
  items: GalleryTrashAsset[];
  trash_count: number;
}
