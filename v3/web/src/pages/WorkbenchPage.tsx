import {useEffect, useMemo, useRef, useState} from "react";
import type {FormEvent} from "react";
import {useSearchParams} from "react-router-dom";
import {apiRequest, ApiClientError} from "../lib/api";
import type {ArtistComparisonSubmission, ArtistSuggestion, CandidateLane, CandidateTag, GenerationRunRecord, GenerationTarget, GenerationTargetListResponse, IntentParseResponse, PromptCandidate, SceneDraft, SceneDraftItem, SceneRelation, TagSuggestion, TranslationResponse, WorkbenchGenerationSettings, WorkbenchResponse, WorkspaceDraft, WorkspaceListResponse, WorkspaceRecord} from "../lib/types";
import {EmptyState, ErrorState, LoadingState} from "../components/States";

const profiles = [
  {id: "anima_base_v1", label: "ANIMA Base"},
  {id: "anima_aesthetic_v1", label: "ANIMA Aesthetic"},
  {id: "anima_turbo_v1", label: "ANIMA Turbo"},
];
const RECOVERY_KEY = "anima-v3-workbench-recovery";
const GENERATION_TARGET_KEY = "anima-v3-generation-target";
const defaultGenerationSettings: WorkbenchGenerationSettings = {preset_id: "balanced", aspect: "portrait", seed: -1, batch_size: 1};
const aspectSizes: Record<WorkbenchGenerationSettings["aspect"], {width: number; height: number} | null> = {
  portrait: {width: 896, height: 1152},
  landscape: {width: 1152, height: 896},
  square: {width: 1024, height: 1024},
  model_default: null,
};
const presetLabels: Record<WorkbenchGenerationSettings["preset_id"], string> = {fast: "快速", balanced: "平衡", quality: "高质量"};
const aspectLabels: Record<WorkbenchGenerationSettings["aspect"], string> = {portrait: "竖图 896×1152", landscape: "横图 1152×896", square: "方形 1024×1024", model_default: "模型默认"};
type WorkspaceIdentity = Pick<WorkspaceRecord, "id" | "title" | "revision" | "created_at" | "updated_at">;
type RecoveredWorkbench = {draft: WorkspaceDraft; result: WorkbenchResponse | null; workspaceTitle: string; workspace: WorkspaceIdentity | null};

const laneMeta: Record<CandidateLane, {index: string; label: string; detail: string}> = {
  literal: {index: "L", label: "Literal", detail: "只保留可确定映射的输入"},
  conservative: {index: "C", label: "Conservative", detail: "增加少量高置信相关标签"},
  artist: {index: "A", label: "Artist", detail: "在保守候选上增加一位画师"},
  hybrid: {index: "H", label: "Hybrid", detail: "保留画面计划与明确关系"},
};

export function WorkbenchPage({remoteEnabled = false, naturalLanguageEnabled = false, localTranslationEnabled = false}: {remoteEnabled?: boolean; naturalLanguageEnabled?: boolean; localTranslationEnabled?: boolean}) {
  const [searchParams] = useSearchParams();
  const importedTags = useMemo(() => Array.from(new Set(searchParams.getAll("tag").map((item) => item.trim()).filter(Boolean))), []);
  const recovered = useMemo(loadRecoveredWorkbench, []);
  const [draft, setDraft] = useState<WorkspaceDraft>(() => {
    const base = normalizeDraft(recovered?.draft, naturalLanguageEnabled);
    if (!importedTags.length) return base;
    const currentTags = base.selected_tags || [];
    return {
      ...base,
      input_mode: "concepts",
      positive_text: mergeImportedTags(base.positive_text, importedTags),
      selected_tags: Array.from(new Set([...currentTags, ...importedTags])),
    };
  });
  const [past, setPast] = useState<WorkspaceDraft[]>([]);
  const [future, setFuture] = useState<WorkspaceDraft[]>([]);
  const [result, setResult] = useState<WorkbenchResponse | null>(recovered?.result || null);
  const [error, setError] = useState<ApiClientError | null>(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceIdentity | null>(recovered?.workspace || null);
  const [workspaceTitle, setWorkspaceTitle] = useState(recovered?.workspaceTitle || "未命名工作台");
  const [workspaceList, setWorkspaceList] = useState<WorkspaceRecord[] | null>(null);
  const [workspaceNotice, setWorkspaceNotice] = useState<{kind: "success" | "error"; text: string} | null>(null);
  const [workspaceBusy, setWorkspaceBusy] = useState(false);
  const [generationTargets, setGenerationTargets] = useState<GenerationTarget[]>([]);
  const [selectedTarget, setSelectedTarget] = useState(() => {
    try { return localStorage.getItem(GENERATION_TARGET_KEY) || ""; } catch { return ""; }
  });
  const [generationBusy, setGenerationBusy] = useState<string | null>(null);
  const [generationNotice, setGenerationNotice] = useState<string | null>(null);
  const [parseInfo, setParseInfo] = useState<IntentParseResponse | null>(() => recovered?.result ? buildLocalParseInfo(recovered.result, "已恢复的工作台快照") : null);
  const [translation, setTranslation] = useState<TranslationResponse | null>(null);
  const [translationBusy, setTranslationBusy] = useState(false);
  const [privateKeyPassphrase, setPrivateKeyPassphrase] = useState("");
  const [artistComparisonBase, setArtistComparisonBase] = useState<PromptCandidate | null>(null);
  const [artistSuggestions, setArtistSuggestions] = useState<ArtistSuggestion[]>([]);
  const [selectedArtists, setSelectedArtists] = useState<string[]>([]);
  const [artistComparisonSeed, setArtistComparisonSeed] = useState(() => Math.floor(Math.random() * 2_000_000_000));
  const [artistComparisonBusy, setArtistComparisonBusy] = useState(false);
  const idempotencyKeys = useRef(new Map<string, string>());
  const artistComparisonIdempotency = useRef<{selection: string; comparisonId: string; key: string} | null>(null);
  const artistRecommendAbort = useRef<AbortController | null>(null);
  const artistRecommendRequestId = useRef(0);

  const positiveText = draft.positive_text;
  const excludedText = draft.excluded_text;
  const profile = draft.model_profile;
  const inputMode = draft.input_mode || "concepts";
  const naturalText = draft.natural_text || "";
  const selectedTags = draft.selected_tags || [];
  const suppressedTags = draft.suppressed_tags || [];
  const generationSettings = draft.generation_settings || defaultGenerationSettings;

  const positiveItems = useMemo(() => splitConcepts(positiveText), [positiveText]);
  const excludedItems = useMemo(() => splitConcepts(excludedText), [excludedText]);
  const compatibleTargets = useMemo(() => generationTargets.filter((target) => (
    !target.compatible_model_profiles.length || target.compatible_model_profiles.includes(profile)
  )), [generationTargets, profile]);
  const remoteConnections = useMemo(() => {
    const unique = new Map<string, GenerationTarget>();
    for (const target of compatibleTargets) {
      if (!unique.has(target.remote_profile_id)) unique.set(target.remote_profile_id, target);
    }
    return [...unique.values()];
  }, [compatibleTargets]);
  const duplicateConnectionLabels = useMemo(() => {
    const counts = new Map<string, number>();
    for (const target of remoteConnections) {
      const label = remoteConnectionLabel(target);
      counts.set(label, (counts.get(label) || 0) + 1);
    }
    return new Set(remoteConnections.filter((target) => (counts.get(remoteConnectionLabel(target)) || 0) > 1).map((target) => target.remote_profile_id));
  }, [remoteConnections]);
  const [selectedRemoteId, selectedWorkflowId] = selectedTarget.split("::");
  const connectionWorkflows = useMemo(() => compatibleTargets.filter((target) => target.remote_profile_id === selectedRemoteId), [compatibleTargets, selectedRemoteId]);
  const activeTarget = compatibleTargets.find((target) => targetKey(target) === selectedTarget);
  const reviewedFacts = useMemo(() => groupIntentFacts(parseInfo?.intent.graph.elements || []), [parseInfo]);
  const chineseLabels = useMemo(() => chineseLabelsFromResult(result), [result]);

  useEffect(() => {
    try {
      localStorage.setItem(RECOVERY_KEY, JSON.stringify({draft, result, workspaceTitle, workspace, saved_at: new Date().toISOString()}));
    } catch {
      // Recovery is best-effort: quota errors must never interrupt prompt work.
    }
  }, [draft, result, workspaceTitle, workspace]);
  const translationSource = inputMode === "natural" ? naturalText : positiveText;

  useEffect(() => {
    if (!remoteEnabled) return;
    apiRequest<GenerationTargetListResponse>("/api/v3/generation-targets")
      .then((payload) => setGenerationTargets(payload.items))
      .catch((caught) => setGenerationNotice((caught as ApiClientError).message));
  }, [remoteEnabled]);

  useEffect(() => {
    if (!compatibleTargets.some((target) => targetKey(target) === selectedTarget)) {
      const ready = compatibleTargets.filter((target) => target.host_fingerprint_ready);
      const preferred = ready.find((target) => /aesthetic[_\s-]*v?1\.1/i.test(target.workflow_display_name)) || ready[0] || compatibleTargets[0];
      setSelectedTarget(preferred ? targetKey(preferred) : "");
    }
  }, [compatibleTargets, selectedTarget]);

  function selectRemoteConnection(remoteProfileId: string) {
    const options = compatibleTargets.filter((target) => target.remote_profile_id === remoteProfileId);
    const preferred = options.find((target) => target.workflow_profile_id === selectedWorkflowId)
      || options.find((target) => /aesthetic[_\s-]*v?1\.1/i.test(target.workflow_display_name))
      || options[0];
    setSelectedTarget(preferred ? targetKey(preferred) : "");
  }

  useEffect(() => {
    if (!selectedTarget) return;
    try { localStorage.setItem(GENERATION_TARGET_KEY, selectedTarget); } catch { /* Best-effort preference. */ }
  }, [selectedTarget]);

  function editDraft(patch: Partial<WorkspaceDraft>) {
    const next = {...draft, ...patch};
    if (next.positive_text === draft.positive_text && next.excluded_text === draft.excluded_text && next.model_profile === draft.model_profile && next.input_mode === draft.input_mode && next.natural_text === draft.natural_text && sameStringList(next.selected_tags || [], draft.selected_tags || []) && sameStringList(next.suppressed_tags || [], draft.suppressed_tags || [])) return;
    setPast((items) => [...items.slice(-49), draft]);
    setDraft(next);
    setFuture([]);
    setWorkspaceNotice(null);
    setResult(null);
    setParseInfo(null);
    setTranslation(null);
    setArtistComparisonBase(null);
    setArtistSuggestions([]);
    setSelectedArtists([]);
    artistComparisonIdempotency.current = null;
  }

  function updateGenerationSettings(patch: Partial<WorkbenchGenerationSettings>) {
    const next = {...generationSettings, ...patch};
    if (next.preset_id === generationSettings.preset_id && next.aspect === generationSettings.aspect && next.seed === generationSettings.seed && next.batch_size === generationSettings.batch_size) return;
    setPast((items) => [...items.slice(-49), draft]);
    setDraft({...draft, generation_settings: next});
    setFuture([]);
    setWorkspaceNotice(null);
    idempotencyKeys.current.clear();
    artistComparisonIdempotency.current = null;
  }

  function switchInputMode(mode: "concepts" | "natural") {
    if (mode === inputMode) return;
    editDraft({input_mode: mode, selected_tags: [], suppressed_tags: []});
  }

  function undo() {
    const previous = past[past.length - 1];
    if (!previous) return;
    setPast((items) => items.slice(0, -1));
    setFuture((items) => [draft, ...items].slice(0, 50));
    setDraft(previous);
    setResult(null);
    setParseInfo(null);
    setArtistComparisonBase(null);
    setArtistSuggestions([]);
    setSelectedArtists([]);
  }

  function redo() {
    const next = future[0];
    if (!next) return;
    setFuture((items) => items.slice(1));
    setPast((items) => [...items.slice(-49), draft]);
    setDraft(next);
    setResult(null);
    setParseInfo(null);
    setArtistComparisonBase(null);
    setArtistSuggestions([]);
    setSelectedArtists([]);
  }

  async function saveWorkspace() {
    setWorkspaceBusy(true);
    setWorkspaceNotice(null);
    try {
      const saved = workspace ? await apiRequest<WorkspaceRecord>(`/api/v3/workspaces/${workspace.id}`, {
        method: "PUT",
        body: JSON.stringify({title: workspaceTitle, draft, candidate_snapshot: workspaceCandidateSnapshot(result), revision: workspace.revision}),
      }) : await apiRequest<WorkspaceRecord>("/api/v3/workspaces", {
        method: "POST",
        body: JSON.stringify({title: workspaceTitle, draft, candidate_snapshot: workspaceCandidateSnapshot(result)}),
      });
      setWorkspace(saved);
      setWorkspaceTitle(saved.title);
      setWorkspaceNotice({kind: "success", text: `已保存 revision ${saved.revision}`});
      setWorkspaceList((items) => items ? [saved, ...items.filter((item) => item.id !== saved.id)] : items);
    } catch (caught) {
      const apiError = caught as ApiClientError;
      setWorkspaceNotice({kind: "error", text: apiError.code === "workspace_revision_conflict" ? "另一个标签页已更新此工作台；请重新打开后再合并。" : apiError.message});
    } finally {
      setWorkspaceBusy(false);
    }
  }

  async function openWorkspaceList() {
    setWorkspaceBusy(true);
    setWorkspaceNotice(null);
    try {
      const payload = await apiRequest<WorkspaceListResponse>("/api/v3/workspaces");
      setWorkspaceList(payload.items);
    } catch (caught) {
      setWorkspaceNotice({kind: "error", text: (caught as ApiClientError).message});
    } finally {
      setWorkspaceBusy(false);
    }
  }

  function loadWorkspace(item: WorkspaceRecord) {
    setWorkspace(item);
    setWorkspaceTitle(item.title);
    setDraft(normalizeDraft(item.draft, naturalLanguageEnabled));
    setPast([]);
    setFuture([]);
    setResult(item.candidate_snapshot || null);
    setParseInfo(item.candidate_snapshot ? buildLocalParseInfo(item.candidate_snapshot, "已打开的工作台快照") : null);
    setArtistComparisonBase(null);
    setArtistSuggestions([]);
    setSelectedArtists([]);
    artistComparisonIdempotency.current = null;
    setError(null);
    setWorkspaceList(null);
    setWorkspaceNotice({kind: "success", text: `已打开 revision ${item.revision}`});
  }

  function structuredElements() {
    return [
      ...positiveItems.map((raw, index) => ({
        id: `e_positive_${index + 1}`,
        text: raw.startsWith("!") ? raw.slice(1).trim() : raw,
        state: raw.startsWith("!") ? "locked" : "required",
      })),
      ...excludedItems.map((text, index) => ({id: `e_excluded_${index + 1}`, text, state: "excluded"})),
    ];
  }

  function structuredCandidateRequest(selected = selectedTags, translatedText?: string, suppressed = suppressedTags) {
    return {
      source_text: [...positiveItems, ...excludedItems.map((item) => `不要 ${item}`)].join("，"),
      source_language: "mixed",
      model_profile: profile,
      elements: structuredElements(),
      selected_tags: selected,
      ...(suppressed.length ? {suppressed_tags: suppressed} : {}),
      ...(translatedText ? {translated_text: translatedText} : {}),
    };
  }

  function naturalCandidateRequest(overrides: Record<string, unknown> = {}) {
    const sceneDraft = result?.scene_draft;
    return {
      source_text: naturalText,
      excluded_text: excludedText,
      model_profile: profile,
      selected_tags: selectedTags,
      ...(suppressedTags.length ? {suppressed_tags: suppressedTags} : {}),
      ...(sceneDraft ? {translated_text: sceneDraft.translated_text, ...factOwnersRequest(sceneDraft), ...confirmedRelationsRequest(sceneDraft)} : {}),
      ...overrides,
    };
  }

  function setLocalParseInfo(payload: WorkbenchResponse & {local_translation?: {engine: string}}, label: string) {
    setParseInfo(buildLocalParseInfo(payload, label));
  }

  async function generate(event: FormEvent) {
    event.preventDefault();
    if (inputMode === "natural" ? !naturalText.trim() : !positiveItems.length) return;
    setLoading(true);
    setError(null);
    try {
      let payload: WorkbenchResponse;
      if (inputMode === "natural") {
        const local = await apiRequest<WorkbenchResponse & {local_translation: {translated_text: string; engine: string; local_only: boolean}}>("/api/v3/local-natural/candidates", {
          method: "POST",
          body: JSON.stringify({source_text: naturalText, excluded_text: excludedText, model_profile: profile, selected_tags: selectedTags, ...(suppressedTags.length ? {suppressed_tags: suppressedTags} : {})}),
        });
        setLocalParseInfo(local, "本地翻译与本地标签索引");
        payload = local;
      } else {
        const local = await apiRequest<WorkbenchResponse & {local_translation?: {engine: string}}>("/api/v3/workbench/candidates", {
          method: "POST",
          body: JSON.stringify(structuredCandidateRequest()),
        });
        setLocalParseInfo(local, "本地翻译与结构化概念映射");
        payload = local;
      }
      setResult(payload);
    } catch (caught) {
      setError(caught as ApiClientError);
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  async function toggleTagSuggestion(tag: string) {
    const sourceText = inputMode === "natural" ? naturalText : positiveText;
    if (!result?.scene_draft || !sourceText.trim()) return;
    const nextTags = selectedTags.includes(tag) ? selectedTags.filter((item) => item !== tag) : [...selectedTags, tag];
    const translatedText = result.scene_draft.translated_text;
    editDraft({selected_tags: nextTags});
    setLoading(true);
    setError(null);
    try {
      const local = inputMode === "natural"
        ? await apiRequest<WorkbenchResponse & {local_translation: {translated_text: string; engine: string; local_only: boolean}}>("/api/v3/local-natural/candidates", {
          method: "POST",
          body: JSON.stringify(naturalCandidateRequest({selected_tags: nextTags, translated_text: translatedText})),
        })
        : await apiRequest<WorkbenchResponse & {local_translation?: {engine: string}}>("/api/v3/workbench/candidates", {
          method: "POST",
          body: JSON.stringify(structuredCandidateRequest(nextTags, translatedText)),
        });
      setLocalParseInfo(local, "复用当前译文并更新用户选择");
      setResult(local);
    } catch (caught) {
      setError(caught as ApiClientError);
    } finally {
      setLoading(false);
    }
  }

  async function applySceneDraftTranslation(translatedText: string) {
    const sourceText = inputMode === "natural" ? naturalText : positiveText;
    if (!result?.scene_draft || !sourceText.trim() || !translatedText.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const local = inputMode === "natural"
        ? await apiRequest<WorkbenchResponse & {local_translation: {translated_text: string; engine: string; local_only: boolean}}>("/api/v3/local-natural/candidates", {
          method: "POST",
          body: JSON.stringify(naturalCandidateRequest({translated_text: translatedText})),
        })
        : await apiRequest<WorkbenchResponse & {local_translation?: {engine: string}}>("/api/v3/workbench/candidates", {
          method: "POST",
          body: JSON.stringify(structuredCandidateRequest(selectedTags, translatedText)),
        });
      setLocalParseInfo(local, "使用已编辑译文重新映射；未调用翻译模型");
      setResult(local);
    } catch (caught) {
      setError(caught as ApiClientError);
    } finally {
      setLoading(false);
    }
  }

  async function applyFactOwner(factId: string, entityId: string) {
    if (inputMode !== "natural" || !result?.scene_draft || !naturalText.trim()) return;
    const factOwners = confirmedFactOwners(result.scene_draft);
    if (entityId) factOwners[factId] = entityId;
    else delete factOwners[factId];
    const confirmedRelations = confirmedSceneRelations(result.scene_draft)
      .filter((relation) => factOwners[relation.target_element_id] === relation.source_entity_id);
    setLoading(true);
    setError(null);
    try {
      const local = await apiRequest<WorkbenchResponse & {local_translation: {translated_text: string; engine: string; local_only: boolean}}>("/api/v3/local-natural/candidates", {
        method: "POST",
        body: JSON.stringify(naturalCandidateRequest({
          translated_text: result.scene_draft.translated_text,
          fact_owners: factOwners,
          ...(confirmedRelations.length ? {confirmed_relations: confirmedRelations} : {}),
        })),
      });
      setLocalParseInfo(local, "已更新实体归属；未调用翻译模型");
      setResult(local);
    } catch (caught) {
      setError(caught as ApiClientError);
    } finally {
      setLoading(false);
    }
  }

  async function recompileCurrentDraft(overrides: Record<string, unknown> = {}, selected = selectedTags, suppressed = suppressedTags) {
    const sourceText = inputMode === "natural" ? naturalText : positiveText;
    if (!sourceText.trim()) return;
    const translatedText = result?.scene_draft?.translated_text;
    setLoading(true);
    setError(null);
    try {
      const local = inputMode === "natural"
        ? await apiRequest<WorkbenchResponse & {local_translation: {translated_text: string; engine: string; local_only: boolean}}>("/api/v3/local-natural/candidates", {
          method: "POST",
          body: JSON.stringify(naturalCandidateRequest({translated_text: translatedText, selected_tags: selected, ...(suppressed.length ? {suppressed_tags: suppressed} : {suppressed_tags: []}), ...overrides})),
        })
        : await apiRequest<WorkbenchResponse & {local_translation?: {engine: string}}>("/api/v3/workbench/candidates", {
          method: "POST",
          body: JSON.stringify(structuredCandidateRequest(selected, translatedText, suppressed)),
        });
      setLocalParseInfo(local, "已按人工修改重新编译；未调用翻译模型");
      setResult(local);
    } catch (caught) {
      setError(caught as ApiClientError);
    } finally {
      setLoading(false);
    }
  }

  async function suppressCanonicalTag(tag: string) {
    if (!tag) return;
    const nextSelected = selectedTags.filter((item) => item !== tag);
    const nextSuppressed = suppressedTags.includes(tag) ? suppressedTags : [...suppressedTags, tag];
    editDraft({selected_tags: nextSelected, suppressed_tags: nextSuppressed});
    await recompileCurrentDraft({}, nextSelected, nextSuppressed);
  }

  async function restoreCanonicalTag(tag: string) {
    if (!tag) return;
    const nextSuppressed = suppressedTags.filter((item) => item !== tag);
    editDraft({suppressed_tags: nextSuppressed});
    await recompileCurrentDraft({}, selectedTags, nextSuppressed);
  }

  async function clearSuppressedTags() {
    if (!suppressedTags.length) return;
    editDraft({suppressed_tags: []});
    if (result) await recompileCurrentDraft({}, selectedTags, []);
  }

  async function removeConfirmedItem(item: SceneDraftItem) {
    if (!item.canonical_tag) return;
    if (item.source === "user_selected") {
      await toggleTagSuggestion(item.canonical_tag);
      return;
    }
    await suppressCanonicalTag(item.canonical_tag);
  }

  async function removeCandidateTag(tag: CandidateTag) {
    if (!tag.removable) return;
    if (tag.state === "user_selected") {
      await toggleTagSuggestion(tag.name);
      return;
    }
    await suppressCanonicalTag(tag.name);
  }

  async function applySceneRelation(relation: SceneRelation, confirmed: boolean) {
    if (inputMode !== "natural" || !result?.scene_draft || !naturalText.trim()) return;
    const relations = confirmedSceneRelations(result.scene_draft)
      .filter((item) => relationRequestKey(item) !== relationRequestKey(relation));
    if (confirmed) relations.push(sceneRelationRequest(relation));
    setLoading(true);
    setError(null);
    try {
      const local = await apiRequest<WorkbenchResponse & {local_translation: {translated_text: string; engine: string; local_only: boolean}}>("/api/v3/local-natural/candidates", {
        method: "POST",
        body: JSON.stringify(naturalCandidateRequest({
          translated_text: result.scene_draft.translated_text,
          ...factOwnersRequest(result.scene_draft),
          confirmed_relations: relations,
        })),
      });
      setLocalParseInfo(local, "已更新显式关系；未调用翻译模型");
      setResult(local);
    } catch (caught) {
      setError(caught as ApiClientError);
    } finally {
      setLoading(false);
    }
  }

  async function copyPrompt(candidate: PromptCandidate, kind: "positive" | "negative") {
    const value = kind === "positive" ? candidate.positive_prompt : candidate.negative_prompt;
    await navigator.clipboard.writeText(value);
    const key = `${candidate.id}:${kind}`;
    setCopied(key);
    window.setTimeout(() => setCopied((current) => current === key ? null : current), 1500);
  }

  async function useArtistComparisonBase(candidate: PromptCandidate) {
    if (!result) return;
    setArtistComparisonBase(candidate);
    setSelectedArtists([]);
    artistComparisonIdempotency.current = null;
    setGenerationNotice(null);
    setArtistSuggestions([]);
    artistRecommendAbort.current?.abort();
    const controller = new AbortController();
    artistRecommendAbort.current = controller;
    const requestId = ++artistRecommendRequestId.current;
    const candidateId = candidate.id;
    try {
      const payload = await apiRequest<{items: ArtistSuggestion[]}>("/api/v3/artists/recommend", {
        method: "POST",
        signal: controller.signal,
        body: JSON.stringify({tags: candidate.tags.map((tag) => tag.name), limit: 20}),
      });
      if (requestId !== artistRecommendRequestId.current) return;
      setArtistSuggestions(payload.items);
    } catch (caught) {
      if ((caught as Error).name === "AbortError") return;
      if (requestId !== artistRecommendRequestId.current) return;
      setGenerationNotice(`无法扩展画师推荐池：${(caught as ApiClientError).message}`);
      if (artistComparisonBase?.id === candidateId || !artistComparisonBase) setArtistSuggestions([]);
    }
  }

  function toggleArtistSuggestion(name: string) {
    setSelectedArtists((items) => {
      if (items.includes(name)) return items.filter((item) => item !== name);
      if (items.length >= 20) {
        setGenerationNotice("一组画师对照最多选择 20 位画师。");
        return items;
      }
      return [...items, name];
    });
    artistComparisonIdempotency.current = null;
  }

  async function submitArtistComparison() {
    if (!result || !artistComparisonBase) return;
    const target = compatibleTargets.find((item) => targetKey(item) === selectedTarget);
    if (!target) {
      setGenerationNotice("当前模型没有可用的远程工作流。");
      return;
    }
    if (!selectedArtists.length) {
      setGenerationNotice("请至少选择一位画师后再提交对照组。");
      return;
    }
    if (!Number.isInteger(artistComparisonSeed) || artistComparisonSeed < 0) {
      setGenerationNotice("画师对照必须使用非负整数 Seed。");
      return;
    }
    const comparisonSettings = resolvedGenerationSettings(generationSettings, {seed: artistComparisonSeed, batch_size: 1});
    const selection = [artistComparisonBase.id, selectedTarget, JSON.stringify(comparisonSettings), ...selectedArtists].join("|");
    let identity = artistComparisonIdempotency.current;
    if (!identity || identity.selection !== selection) {
      identity = {
        selection,
        comparisonId: `comparison_${crypto.randomUUID().replaceAll("-", "")}`,
        key: `artist-comparison-${workspace?.id || "draft"}-${workspace?.revision || 0}-${crypto.randomUUID()}`,
      };
      artistComparisonIdempotency.current = identity;
    }
    setArtistComparisonBusy(true);
    setGenerationNotice(null);
    try {
      if (target.auth_type === "private_key" && privateKeyPassphrase) {
        await apiRequest<{configured: boolean}>("/api/v3/generation-credentials/private-key-passphrase", {
          method: "POST",
          body: JSON.stringify({remote_profile_id: target.remote_profile_id, passphrase: privateKeyPassphrase}),
        });
        setPrivateKeyPassphrase("");
        setGenerationTargets((items) => items.map((item) => item.remote_profile_id === target.remote_profile_id ? {...item, private_key_passphrase_configured: true} : item));
      }
      const response = await apiRequest<ArtistComparisonSubmission>("/api/v3/artist-comparisons", {
        method: "POST",
        headers: {"Idempotency-Key": identity.key},
        body: JSON.stringify({
          comparison_id: identity.comparisonId,
          candidate: artistComparisonBase,
          intent: result.intent,
          artist_names: selectedArtists,
          project_name: workspaceTitle,
          settings: comparisonSettings,
          workspace_id: workspace?.id || null,
          workspace_revision: workspace?.revision || null,
          remote_profile_id: target.remote_profile_id,
          workflow_profile_id: target.workflow_profile_id,
        }),
      });
      const suffix = response.failed.length ? `；${response.failed.length} 位未加入队列` : "";
      setGenerationNotice(`画师对照组已提交：${response.submitted.length}/${response.requested_count} 位，固定 Seed ${response.seed}${suffix}。可在“生成”页和画廊查看。`);
    } catch (caught) {
      setGenerationNotice((caught as ApiClientError).message);
    } finally {
      setArtistComparisonBusy(false);
    }
  }

  async function submitGeneration(candidate: PromptCandidate) {
    if (!result) return;
    const target = compatibleTargets.find((item) => targetKey(item) === selectedTarget);
    if (!target) {
      setGenerationNotice("当前模型没有可用的远程工作流。");
      return;
    }
    setGenerationBusy(candidate.id);
    setGenerationNotice(null);
    let idempotencyKey = idempotencyKeys.current.get(candidate.id);
    if (!idempotencyKey) {
      idempotencyKey = `web-${workspace?.id || "draft"}-${workspace?.revision || 0}-${candidate.id}-${crypto.randomUUID()}`;
      idempotencyKeys.current.set(candidate.id, idempotencyKey);
    }
    try {
      if (target.auth_type === "private_key" && privateKeyPassphrase) {
        await apiRequest<{configured: boolean}>("/api/v3/generation-credentials/private-key-passphrase", {
          method: "POST",
          body: JSON.stringify({remote_profile_id: target.remote_profile_id, passphrase: privateKeyPassphrase}),
        });
        setPrivateKeyPassphrase("");
        setGenerationTargets((items) => items.map((item) => item.remote_profile_id === target.remote_profile_id ? {...item, private_key_passphrase_configured: true} : item));
      }
      await apiRequest<GenerationRunRecord>("/api/v3/generation-runs", {
        method: "POST",
        headers: {"Idempotency-Key": idempotencyKey},
        body: JSON.stringify({
          candidate,
          intent: result.intent,
          project_name: workspaceTitle,
          settings: resolvedGenerationSettings(generationSettings),
          workspace_id: workspace?.id || null,
          workspace_revision: workspace?.revision || null,
          remote_profile_id: target.remote_profile_id,
          workflow_profile_id: target.workflow_profile_id,
        }),
      });
      idempotencyKeys.current.delete(candidate.id);
      setGenerationNotice("已提交到远程队列。你可以继续比较或修改候选；进度可在“生成”页查看。");
    } catch (caught) {
      setGenerationNotice((caught as ApiClientError).message);
    } finally {
      setGenerationBusy(null);
    }
  }

  async function previewTranslation() {
    if (!translationSource.trim()) return;
    setTranslationBusy(true);
    setTranslation(null);
    setError(null);
    try {
      const payload = await apiRequest<TranslationResponse>("/api/v3/translation", {
        method: "POST",
        body: JSON.stringify({source_text: translationSource, direction: "zh_en"}),
      });
      setTranslation(payload);
    } catch (caught) {
      setError(caught as ApiClientError);
    } finally {
      setTranslationBusy(false);
    }
  }

  return (
    <section className="page workbench-page">
      <header className="page-header workbench-header">
        <div><span className="eyebrow">PROMPT WORKBENCH</span><h1>候选工作台</h1><p>先忠实映射输入，再人工删改标签和英文画面计划；推荐和画师都是可比较、可移除的增量。</p></div>
        <div className="header-stat"><strong>{result?.candidates.length || "—"}</strong><span>validated lanes</span></div>
      </header>

      <div className="workspace-toolbar">
        <input aria-label="工作台名称" value={workspaceTitle} onChange={(event) => setWorkspaceTitle(event.target.value)} maxLength={200} />
        <span className="workspace-identity">{workspace ? `r${workspace.revision}` : "未保存"}</span>
        <button type="button" onClick={undo} disabled={!past.length} aria-label="撤销">↶</button>
        <button type="button" onClick={redo} disabled={!future.length} aria-label="恢复">↷</button>
        <button type="button" onClick={openWorkspaceList} disabled={workspaceBusy}>打开</button>
        <button type="button" className="workspace-save" onClick={saveWorkspace} disabled={workspaceBusy || !workspaceTitle.trim()}>{workspaceBusy ? "处理中…" : "保存工作台"}</button>
      </div>
      {workspaceNotice && <div className={`workspace-notice workspace-notice--${workspaceNotice.kind}`} role={workspaceNotice.kind === "error" ? "alert" : "status"}>{workspaceNotice.text}</div>}
      {workspaceList && <div className="workspace-picker">
        <div><strong>打开工作台</strong><button type="button" onClick={() => setWorkspaceList(null)} aria-label="关闭工作台列表">×</button></div>
        {workspaceList.length ? workspaceList.map((item) => <button type="button" key={item.id} onClick={() => loadWorkspace(item)}><span>{item.title}</span><small>r{item.revision} · {new Date(item.updated_at).toLocaleString()}</small></button>) : <p>还没有保存的工作台。</p>}
      </div>}

      <div className="input-mode-tabs" role="tablist" aria-label="输入方式">
        <button type="button" role="tab" aria-selected={inputMode === "concepts"} onClick={() => switchInputMode("concepts")}>结构化概念</button>
        <button type="button" role="tab" aria-selected={inputMode === "natural"} disabled={!naturalLanguageEnabled} title={naturalLanguageEnabled ? "本地翻译、词典与数据包索引；不调用 AI API" : "请先连接 V2 本地翻译资源"} onClick={() => switchInputMode("natural")}>自然语言描述</button>
      </div>
      <form className="workbench-composer" onSubmit={generate}>
        <div className="composer-main">
          {inputMode === "natural" ? <>
            <label htmlFor="natural-description">描述你想生成的画面</label>
            <textarea id="natural-description" value={naturalText} onChange={(event) => editDraft({natural_text: event.target.value})} placeholder="可以粘贴小说片段或完整画面描述。系统只抽取当前画面可见事实。" rows={7} />
            <div className="concept-summary"><span>{naturalText.trim().length} 字</span><span>本地翻译与词典索引 · V3 负责映射、推荐与校验</span></div>
          </> : <>
            <label htmlFor="positive-concepts">希望画面中出现</label>
            <textarea id="positive-concepts" value={positiveText} onChange={(event) => editDraft({positive_text: event.target.value})} placeholder="每行或用逗号分隔，例如：女仆、双马尾、咖啡厅\n在词前加 ! 可锁定" rows={5} />
            <div className="concept-summary"><span>{positiveItems.length} 个正向概念</span><span>输入精确标签、中文名或有效别名</span></div>
          </>}
        </div>
        <div className="composer-side">
          {inputMode === "concepts" ? <>
            <label htmlFor="excluded-concepts">明确排除</label>
            <textarea id="excluded-concepts" value={excludedText} onChange={(event) => editDraft({excluded_text: event.target.value})} placeholder="例如：金发、文字、水印" rows={3} />
          </> : <>
            <label htmlFor="natural-exclusions">明确排除（可选）</label>
            <textarea id="natural-exclusions" value={excludedText} onChange={(event) => editDraft({excluded_text: event.target.value})} placeholder="例如：文字、水印、金发" rows={3} />
            <p className="natural-mode-hint">描述里的“不要文字和水印”也会识别；这里用于补充或修正，并始终按排除优先。</p>
          </>}
          <label htmlFor="model-profile">模型配置</label>
          <select id="model-profile" value={profile} onChange={(event) => editDraft({model_profile: event.target.value})}>
            {profiles.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
          <div className="generation-spec">
            <strong>生成规格</strong>
            <label htmlFor="generation-aspect">画幅</label>
            <select id="generation-aspect" value={generationSettings.aspect} onChange={(event) => updateGenerationSettings({aspect: event.target.value as WorkbenchGenerationSettings["aspect"]})}>
              <option value="portrait">{aspectLabels.portrait}</option>
              <option value="landscape">{aspectLabels.landscape}</option>
              <option value="square">{aspectLabels.square}</option>
              <option value="model_default">{aspectLabels.model_default}</option>
            </select>
            <label htmlFor="generation-preset">预设</label>
            <select id="generation-preset" value={generationSettings.preset_id} onChange={(event) => updateGenerationSettings({preset_id: event.target.value as WorkbenchGenerationSettings["preset_id"]})}>
              <option value="fast">{presetLabels.fast}</option>
              <option value="balanced">{presetLabels.balanced}</option>
              <option value="quality">{presetLabels.quality}</option>
            </select>
            <label htmlFor="generation-seed">Seed</label>
            <input id="generation-seed" type="number" min="-1" max="2147483647" value={generationSettings.seed} onChange={(event) => updateGenerationSettings({seed: Number(event.target.value)})} />
            <small>填 -1 表示随机 Seed；画师对照仍会使用下方固定 Seed。</small>
            <label htmlFor="generation-batch">批量</label>
            <input id="generation-batch" type="number" min="1" max="8" value={generationSettings.batch_size} onChange={(event) => updateGenerationSettings({batch_size: Math.max(1, Number(event.target.value) || 1)})} />
          </div>
          {suppressedTags.length > 0 && <div className="suppressed-summary"><span>当前工作台已移除 {suppressedTags.length} 个标签</span><button type="button" disabled={loading} onClick={() => void clearSuppressedTags()}>恢复全部</button></div>}
          <button className="button generate-button" type="submit" disabled={(inputMode === "natural" ? !naturalText.trim() : !positiveItems.length) || loading}>{loading ? (inputMode === "natural" ? "正在本地编译并验证…" : "正在验证…") : (inputMode === "natural" ? "编译并生成候选" : "生成候选")}</button>
        </div>
      </form>

      {localTranslationEnabled && <section className="translation-preview" aria-label="本地翻译预览">
        <div><strong>本地英译预览</strong><span>独立工具，不参与 V3 候选编译</span></div>
        <button type="button" onClick={() => void previewTranslation()} disabled={!translationSource.trim() || translationBusy}>{translationBusy ? "正在本地翻译…" : "翻译当前输入"}</button>
        {translation && <div className="translation-result"><p>{translation.translated_text}</p><small>{translation.engine} · {translation.model_ready ? "本地 Marian 模型" : "内置离线词典"}</small></div>}
      </section>}

      {parseInfo && <section className="intent-review" aria-label="自然语言抽取结果">
        <div><strong>已整理 {reviewedFacts.length} 项画面证据</strong><span>{parseInfo.parser.name} · {parseInfo.extraction.summary_zh}</span></div>
        <div className="intent-facts">{reviewedFacts.map(({element, count}) => <span key={`${element.state}:${element.original_text}`} className={element.state === "excluded" ? "is-excluded" : ""}>{element.original_text}<small>{element.state === "excluded" ? `排除${count > 1 ? ` · ${count} 个映射` : ""}` : factTypeLabel(element.type)}</small></span>)}</div>
        {parseInfo.intent.scene_plan_en && <details><summary>查看 Hybrid 英文画面计划</summary><p>{parseInfo.intent.scene_plan_en}</p>{result?.scene_draft?.back_translation?.text && <p className="scene-plan-zh">{result.scene_draft.back_translation.text}</p>}</details>}
        {result?.scene_draft ? <SceneDraftReview draft={result.scene_draft} relatedSuggestions={result.tag_suggestions || []} selectedTags={selectedTags} busy={loading} onToggle={toggleTagSuggestion} onApplyTranslation={applySceneDraftTranslation} onRemoveItem={removeConfirmedItem} onRestoreTag={restoreCanonicalTag} onAssignFactOwner={inputMode === "natural" ? applyFactOwner : undefined} onToggleRelation={inputMode === "natural" ? applySceneRelation : undefined} chineseLabels={chineseLabels} /> : <p className="intent-review-warning">本地翻译只会把本地索引中的精确匹配加入标签；未命中的画面信息会保留在 Hybrid 英文提示词中，提交前可继续检查候选说明。</p>}
      </section>}

      <div className="workbench-results" aria-live="polite">
        {loading ? <LoadingState label="正在映射标签、计算推荐并验证候选…" /> : error ? (
          <ErrorState message={error.message} requestId={error.requestId} />
        ) : result ? (
          <>
            <div className={`validation-strip${(result.scene_draft?.unresolved.length || result.scene_draft?.risk_notes.some((note) => note.includes("已移除的标签仍出现"))) ? " is-warning" : ""}`}><span className="status-dot is-ready" /><strong>结构检查通过</strong><span>语义仍需人工确认 · {result.candidates.length} 条候选 · {result.data_pack_id}</span></div>
            {remoteEnabled && <div className="generation-submit-bar">
              <div><strong>远程生图</strong><span>{generationSummary(generationSettings)}{activeTarget?.host_fingerprint_ready ? " · 当前连接已确认指纹" : activeTarget ? " · 当前连接尚未确认指纹，请先前往设置" : " · 当前模型没有兼容工作流"}</span></div>
              <label className="generation-target-field"><span>云主机连接</span><select aria-label="云主机连接" value={selectedRemoteId || ""} onChange={(event) => selectRemoteConnection(event.target.value)} disabled={!remoteConnections.length}>
                {remoteConnections.length ? remoteConnections.map((target) => <option key={target.remote_profile_id} value={target.remote_profile_id}>{remoteConnectionLabel(target)}{duplicateConnectionLabels.has(target.remote_profile_id) ? ` · 连接 ${target.remote_profile_id.slice(0, 8)}` : ""}{target.host_fingerprint_ready ? "" : " · 待确认指纹"}</option>) : <option value="">无可用连接</option>}
              </select></label>
              <label className="generation-target-field"><span>工作流</span><select aria-label="远程工作流" value={selectedWorkflowId || ""} onChange={(event) => setSelectedTarget(`${selectedRemoteId}::${event.target.value}`)} disabled={!connectionWorkflows.length}>
                {connectionWorkflows.length ? connectionWorkflows.map((target) => <option key={target.workflow_profile_id} value={target.workflow_profile_id}>{target.workflow_display_name}</option>) : <option value="">当前模型无兼容工作流</option>}
              </select></label>
              {activeTarget?.auth_type === "private_key" && <label className="passphrase-input"><span>私钥口令（可选，仅本次运行内存）</span><input type="password" autoComplete="current-password" value={privateKeyPassphrase} onChange={(event) => setPrivateKeyPassphrase(event.target.value)} placeholder={activeTarget.private_key_passphrase_configured ? "已在本次运行中设置" : "私钥未加密可留空"} /></label>}
            </div>}
            {generationNotice && <div className="workspace-notice workspace-notice--error" role="alert">{generationNotice}</div>}
            <div className="candidate-grid">
              {result.candidates.map((candidate) => (
                <CandidateCard key={candidate.id} candidate={candidate} copied={copied} onCopy={copyPrompt} onGenerate={remoteEnabled ? submitGeneration : undefined} generationBusy={generationBusy === candidate.id} generationDisabled={!activeTarget?.host_fingerprint_ready || generationBusy !== null} onRemoveTag={removeCandidateTag} onUseArtistComparisonBase={useArtistComparisonBase} isArtistComparisonBase={artistComparisonBase?.id === candidate.id} chineseLabels={chineseLabels} proseZh={result.scene_draft?.back_translation?.text || ""} negativeZh={result.scene_draft?.back_translation?.negative_text || ""} />
              ))}
            </div>
            <ArtistComparisonPanel
              items={artistComparisonBase ? artistSuggestions : (result.artist_suggestions || [])}
              base={artistComparisonBase}
              selectedArtists={selectedArtists}
              seed={artistComparisonSeed}
              remoteEnabled={remoteEnabled}
              canSubmit={Boolean(activeTarget?.host_fingerprint_ready)}
              busy={artistComparisonBusy}
              onToggle={toggleArtistSuggestion}
              onSelectVisible={() => setSelectedArtists((artistComparisonBase ? artistSuggestions : result.artist_suggestions || []).slice(0, 20).map((item) => item.name))}
              onClear={() => setSelectedArtists([])}
              onSeedChange={setArtistComparisonSeed}
              onSubmit={() => void submitArtistComparison()}
              chineseLabels={chineseLabels}
            />
          </>
        ) : (
          <EmptyState title="从忠实基准开始" detail="输入画面概念后，工作台会并排生成可追踪的候选。自动推荐不会静默加入角色或版权标签。" />
        )}
      </div>
    </section>
  );
}

function ArtistComparisonPanel({items, base, selectedArtists, seed, remoteEnabled, canSubmit, busy, onToggle, onSelectVisible, onClear, onSeedChange, onSubmit, chineseLabels}: {
  items: ArtistSuggestion[];
  base: PromptCandidate | null;
  selectedArtists: string[];
  seed: number;
  remoteEnabled: boolean;
  canSubmit: boolean;
  busy: boolean;
  chineseLabels: Map<string, string>;
  onToggle: (name: string) => void;
  onSelectVisible: () => void;
  onClear: () => void;
  onSeedChange: (value: number) => void;
  onSubmit: () => void;
}) {
  const weakEvidence = items.length > 0 && items.every((item) => item.hit_count < 2);
  return (
    <section className="artist-suggestion-pool" aria-label="画师对照">
      <header><div><strong>画师对照组</strong><span>{base ? "每位画师各自生成一张；只改变 @artist 标签。" : "先在候选卡上选择一条提示词作为画师对照基准。"}</span></div><small>{items.length ? `Top ${items.length}` : "暂无可靠推荐"}</small></header>
      {base && <div className="artist-comparison-base"><span>已锁定基准</span><strong>{base.title}</strong><code>{base.positive_prompt}</code></div>}
      {base && <div className="artist-comparison-controls">
        <span>已选 {selectedArtists.length}/20</span>
        <button type="button" onClick={onSelectVisible} disabled={busy}>选中当前 {Math.min(items.length, 20)} 位</button>
        <button type="button" onClick={onClear} disabled={!selectedArtists.length || busy}>清空</button>
        <label>固定 Seed<input type="number" min="0" max="2147483647" value={seed} disabled={busy} onChange={(event) => onSeedChange(Number(event.target.value))} /></label>
        <button type="button" className="artist-comparison-submit" disabled={!remoteEnabled || !canSubmit || !selectedArtists.length || busy} onClick={onSubmit}>{busy ? "正在提交对照组…" : `提交 ${selectedArtists.length || ""} 位画师对照`}</button>
      </div>}
      {items.length ? <ol>
        {items.map((artist, index) => <li key={artist.name} className={selectedArtists.includes(artist.name) ? "is-selected" : ""}>
          <span className="artist-rank">{index + 1}</span>
          <div><strong>{artist.render_name}</strong><small>匹配 {artist.sources.map((tag) => chineseLabels.get(tag) ? `${chineseLabels.get(tag)} ${tag.replaceAll("_", " ")}` : tag.replaceAll("_", " ")).join("、")} · {artist.hit_count} 项证据 · 共现 {artist.cooc_count}</small></div>
          <span className="artist-score">{Math.round(artist.display_score * 100)}%</span>
          {base && <button type="button" aria-pressed={selectedArtists.includes(artist.name)} disabled={busy} onClick={() => onToggle(artist.name)}>{selectedArtists.includes(artist.name) ? "已选" : "选入对照"}</button>}
        </li>)}
      </ol> : <p className="artist-empty">当前只有过弱或过泛的标签证据，暂不给出画师排行。</p>}
      <p>{weakEvidence ? "当前证据偏弱，分数只是相对排序，不代表完整场景匹配。" : base ? "同一组会共用模型、工作流、尺寸、预设与 Seed；远程队列按顺序执行。" : "推荐不会自动写入提示词；锁定基准后可选择最多 20 位画师批量生图。"}</p>
    </section>
  );
}

function SceneDraftReview({draft, relatedSuggestions, selectedTags, busy, onToggle, onApplyTranslation, onRemoveItem, onRestoreTag, onAssignFactOwner, onToggleRelation, chineseLabels}: {
  draft: SceneDraft;
  relatedSuggestions: TagSuggestion[];
  selectedTags: string[];
  busy: boolean;
  onToggle: (tag: string) => Promise<void>;
  onApplyTranslation: (translatedText: string) => Promise<void>;
  onRemoveItem: (item: SceneDraftItem) => Promise<void>;
  onRestoreTag: (tag: string) => Promise<void>;
  onAssignFactOwner?: (factId: string, entityId: string) => Promise<void>;
  onToggleRelation?: (relation: SceneRelation, confirmed: boolean) => Promise<void>;
  chineseLabels: Map<string, string>;
}) {
  const [translatedText, setTranslatedText] = useState(draft.translated_text);
  useEffect(() => setTranslatedText(draft.translated_text), [draft.translated_text]);
  const suggestions = new Map<string, {rendered: string; zh: string; reason: string}>();
  const ambiguousTags = new Set((draft.ambiguous || []).flatMap((group) => group.options.map((option) => option.canonical_tag)));
  for (const item of draft.suggestions) {
    if (item.canonical_tag && ambiguousTags.has(item.canonical_tag)) continue;
    if (item.canonical_tag) suggestions.set(item.canonical_tag, {rendered: item.canonical_tag.replaceAll("_", " "), zh: item.cn_name || chineseLabels.get(item.canonical_tag) || "", reason: item.reason});
  }
  for (const item of relatedSuggestions) {
    if (ambiguousTags.has(item.name)) continue;
    if (!suggestions.has(item.name)) suggestions.set(item.name, {rendered: item.render_name, zh: item.cn_name || chineseLabels.get(item.name) || "", reason: `与 ${item.sources.join("、")} 共现；默认不应用`});
  }
  const back = draft.back_translation;
  return (
    <section className="scene-draft-review" aria-label="Scene Draft">
      <header><div><strong>Scene Draft</strong><span>原文证据、译文和本地映射分开保存；建议不会自动加入候选。误出的角色或标签可以直接删掉。</span></div></header>
      {draft.scene_plan_enabled !== false && <div className="scene-draft-prose">
        <div><strong>可编辑画面计划</strong><span>英文可直接改；周围的中文是回译对照，不会自动改提示词。</span></div>
        <textarea aria-label="可编辑画面计划" value={translatedText} disabled={busy} onChange={(event) => setTranslatedText(event.target.value)} rows={4} />
        {back?.segments?.length ? (
          <div className="scene-draft-backtranslation" role="region" aria-label="英文画面计划的中文回译对照">
            <strong>中文回译对照</strong>
            <p>{back.text || "回译不可用"}</p>
            <ul>{back.segments.map((segment) => (
              <li key={segment.en}>
                <code>{segment.en}</code>
                <span>{segment.zh || "无中文对照"}</span>
              </li>
            ))}</ul>
            {back.engine && <small>{back.engine} · 仅供人工对照，发现串词或幻觉时请改英文或删除标签</small>}
          </div>
        ) : null}
        <button type="button" disabled={busy || !translatedText.trim() || translatedText.trim() === draft.translated_text.trim()} onClick={() => void onApplyTranslation(translatedText.trim())}>{busy ? "正在重新映射…" : "应用译文修改"}</button>
      </div>}
      <LayeredDraftGroup items={draft.confirmed} busy={busy} onRemove={onRemoveItem} />
      <EntityOwnershipReview draft={draft} busy={busy} onAssign={onAssignFactOwner} />
      <SceneRelationReview draft={draft} busy={busy} onToggle={onToggleRelation} />
      <DraftGroup label="明确排除" items={draft.exclusions || []} empty="当前没有识别到明确排除项。" excluded busy={busy} onRemove={onRemoveItem} />
      {(draft.ambiguous || []).length > 0 && (
        <div className="scene-draft-group">
          <strong>一对多，请点选</strong>
          {(draft.ambiguous || []).map((group) => (
            <div key={group.text} className="scene-draft-ambiguous">
              <span>“{group.text}”可对应多条标签</span>
              <div className="scene-draft-suggestions">{group.options.map((option) => {
                const selected = selectedTags.includes(option.canonical_tag);
                return <button type="button" key={option.canonical_tag} aria-pressed={selected} disabled={busy} onClick={() => void onToggle(option.canonical_tag)}><span>{option.cn_name || option.render_name}</span><small>{selected ? "已选用" : option.render_name}</small></button>;
              })}</div>
            </div>
          ))}
        </div>
      )}
      <div className="scene-draft-group">
        <strong>待确认建议</strong>
        {suggestions.size ? <div className="scene-draft-suggestions">{[...suggestions].map(([tag, item]) => {
          const selected = selectedTags.includes(tag);
          return <button type="button" key={tag} aria-pressed={selected} disabled={busy} title={item.reason} onClick={() => void onToggle(tag)}><span>{item.zh || item.rendered}</span><small>{item.zh ? `${item.rendered}${selected ? " · 已选用" : ""}` : `${selected ? "已选用 · " : ""}无中文名`}</small></button>;
        })}</div> : <p>没有待确认的标签建议。</p>}
      </div>
      <DraftGroup label="未命中内容" items={draft.unresolved} empty="全部内容都有本地确认映射；仍请检查动作、关系和构图。" />
      {(draft.suppressed || []).length > 0 && (
        <div className="scene-draft-group is-suppressed">
          <strong>已移除，不会自动恢复</strong>
          <ul>{(draft.suppressed || []).map((item) => (
            <li key={item.id}>
              <span>{item.text}</span>
              {item.canonical_tag && <code>{item.canonical_tag.replaceAll("_", " ")}</code>}
              <small>{item.reason}</small>
              {item.canonical_tag && <button type="button" aria-label={`恢复 ${item.text}`} disabled={busy} onClick={() => void onRestoreTag(item.canonical_tag as string)}>恢复</button>}
            </li>
          ))}</ul>
        </div>
      )}
      {draft.risk_notes.length > 0 && <ul className="scene-draft-risks">{draft.risk_notes.map((item) => <li key={item}>{item}</li>)}</ul>}
    </section>
  );
}

function DraftGroup({label, items, empty, excluded = false, busy = false, onRemove}: {label: string; items: SceneDraft["confirmed"]; empty: string; excluded?: boolean; busy?: boolean; onRemove?: (item: SceneDraftItem) => Promise<void>}) {
  return <div className={`scene-draft-group${excluded ? " is-excluded" : ""}`}><strong>{label}</strong>{items.length ? <ul>{items.map((item) => {
    const zh = item.cn_name || (hasCjk(item.text) ? item.text : "");
    const en = item.canonical_tag ? item.canonical_tag.replaceAll("_", " ") : "";
    const title = zh || item.text;
    return <li key={item.id}><span>{title}</span>{en && <code>{en}</code>}<small>{item.reason}</small>{onRemove && item.canonical_tag && <button type="button" aria-label={`移除 ${title}`} disabled={busy} onClick={() => void onRemove(item)}>移除</button>}</li>;
  })}</ul> : <p>{empty}</p>}</div>;
}

const factLayerMeta: Array<{type: NonNullable<SceneDraft["confirmed"][number]["fact_type"]>; label: string}> = [
  {type: "character", label: "角色身份"},
  {type: "subject", label: "可见主体"},
  {type: "appearance", label: "外观特征"},
  {type: "clothing", label: "服装配饰"},
  {type: "action", label: "动作姿态"},
  {type: "relation", label: "实体关系"},
  {type: "object", label: "物体道具"},
  {type: "scene", label: "场景光线"},
  {type: "composition", label: "构图镜头"},
  {type: "style", label: "风格表达"},
  {type: "quality", label: "模型质量控制"},
  {type: "other", label: "尚未归层"},
];

function LayeredDraftGroup({items, busy, onRemove}: {items: SceneDraft["confirmed"]; busy: boolean; onRemove: (item: SceneDraftItem) => Promise<void>}) {
  const layers = factLayerMeta
    .map((meta) => ({...meta, items: items.filter((item) => (item.fact_type || "other") === meta.type)}))
    .filter((layer) => layer.items.length > 0);
  return (
    <div className="scene-draft-layers">
      <div><strong>已确认画面事实</strong><span>可直接移除误映射的角色或标签；删除后重编译不会自动回来。</span></div>
      {layers.length ? layers.map((layer) => (
        <DraftGroup key={layer.type} label={layer.label} items={layer.items} empty="" busy={busy} onRemove={onRemove} />
      )) : <p>当前没有可直接确认的本地标签。</p>}
    </div>
  );
}

const ownerAssignableTypes = new Set(["appearance", "clothing", "action", "relation", "object"]);

function EntityOwnershipReview({draft, busy, onAssign}: {draft: SceneDraft; busy: boolean; onAssign?: (factId: string, entityId: string) => Promise<void>}) {
  const entities = draft.entities || [];
  if (!entities.length || !onAssign) return null;
  const entityById = new Map(entities.map((entity) => [entity.id, entity]));
  const entitySourceIds = new Set(entities.map((entity) => entity.source_element_id));
  const facts = draft.confirmed.filter((item) => !entitySourceIds.has(item.id) && ownerAssignableTypes.has(item.fact_type || "other"));
  return (
    <div className="scene-entity-review">
      <div><strong>实体与属性归属</strong><span>建议不会自动确认，也不会因此改变当前提示词。</span></div>
      <div className="scene-entity-list">{entities.map((entity) => <span key={entity.id}><b>{entity.label}</b><code>{entity.canonical_tag.replaceAll("_", " ")}</code></span>)}</div>
      {facts.length ? <ul>{facts.map((item) => {
        const suggested = item.suggested_owner_entity_id ? entityById.get(item.suggested_owner_entity_id) : null;
        return <li key={item.id}>
          <div><span>{item.text}</span>{suggested && !item.owner_entity_id && <small>建议归属：{suggested.label}</small>}</div>
          <select aria-label={`${item.text} 的归属`} value={item.owner_entity_id || ""} disabled={busy} onChange={(event) => void onAssign(item.id, event.target.value)}>
            <option value="">未确认归属</option>
            {entities.map((entity) => <option key={entity.id} value={entity.id}>{entity.label}</option>)}
          </select>
        </li>;
      })}</ul> : <p>当前没有可绑定到实体的已确认属性、动作或道具。</p>}
    </div>
  );
}

function SceneRelationReview({draft, busy, onToggle}: {draft: SceneDraft; busy: boolean; onToggle?: (relation: SceneRelation, confirmed: boolean) => Promise<void>}) {
  const relations = draft.relations || [];
  if (!relations.length || !onToggle) return null;
  return (
    <div className="scene-relation-review">
      <div><strong>显式关系</strong><span>只有再次确认的关系才进入 Hybrid；Literal 始终不变。</span></div>
      <ul>{relations.map((relation) => {
        const confirmed = relation.state === "confirmed";
        return <li key={relation.id}>
          <div><code>{relation.phrase}</code><small>{relation.reason}</small></div>
          <button type="button" aria-pressed={confirmed} disabled={busy} onClick={() => void onToggle(relation, !confirmed)}>{confirmed ? "取消确认" : "确认关系"}</button>
        </li>;
      })}</ul>
    </div>
  );
}

function CandidateCard({candidate, copied, onCopy, onGenerate, generationBusy = false, generationDisabled = false, onRemoveTag, onUseArtistComparisonBase, isArtistComparisonBase = false, chineseLabels, proseZh, negativeZh}: {
  candidate: PromptCandidate;
  copied: string | null;
  onCopy: (candidate: PromptCandidate, kind: "positive" | "negative") => Promise<void>;
  onGenerate?: (candidate: PromptCandidate) => Promise<void>;
  generationBusy?: boolean;
  generationDisabled?: boolean;
  onRemoveTag: (tag: CandidateTag) => Promise<void>;
  onUseArtistComparisonBase: (candidate: PromptCandidate) => Promise<void>;
  isArtistComparisonBase?: boolean;
  chineseLabels: Map<string, string>;
  proseZh: string;
  negativeZh: string;
}) {
  const meta = laneMeta[candidate.lane];
  const automatic = candidate.tags.filter((tag) => tag.state === "automatic");
  return (
    <article className={`candidate-card candidate-card--${candidate.lane}${isArtistComparisonBase ? " is-comparison-base" : ""}`}>
      <header className="candidate-header">
        <span className="lane-index">{meta.index}</span>
        <div><span>{meta.label}</span><h2>{candidate.title}</h2><p>{meta.detail}</p></div>
        <span className="candidate-valid">✓ FORMAT</span>
      </header>
      <PromptBlock label="Positive" value={candidate.positive_prompt} copied={copied === `${candidate.id}:positive`} onCopy={() => onCopy(candidate, "positive")} notes={annotatePrompt(candidate.positive_prompt, chineseLabels, proseZh)} />
      {candidate.negative_prompt && <PromptBlock label="Negative" value={candidate.negative_prompt} copied={copied === `${candidate.id}:negative`} onCopy={() => onCopy(candidate, "negative")} negative notes={annotatePrompt(candidate.negative_prompt, chineseLabels, negativeZh, true)} />}
      <div className="candidate-tokens">
        {candidate.tags.map((tag) => {
          const zh = tag.cn_name || chineseLabels.get(tag.name) || chineseLabels.get(tag.rendered);
          const label = zh ? `${zh} ${tag.rendered}` : tag.rendered;
          return tag.removable
            ? <button type="button" key={tag.name} className={tag.state === "automatic" ? "is-automatic" : tag.state === "locked" ? "is-locked" : ""} title={tag.reason} aria-label={`移除 ${label}`} disabled={generationBusy} onClick={() => void onRemoveTag(tag)}>{zh || tag.rendered}{zh && <small>{tag.rendered}</small>}<small>×</small></button>
            : <span key={tag.name} className={tag.state === "automatic" ? "is-automatic" : tag.state === "locked" ? "is-locked" : ""} title={tag.reason}>{zh || tag.rendered}{zh && <small>{tag.rendered}</small>}</span>;
        })}
        {candidate.artists.map((artist) => <span key={artist.name} className="is-artist" title={artist.reason}>{artist.rendered}</span>)}
      </div>
      <footer className="candidate-footer">
        <span>{candidate.tags.length} tags{candidate.artists.length ? ` · ${candidate.artists.length} artist` : ""}</span>
        <span>{automatic.length ? `${automatic.length} 个自动推荐` : "无自动扩展"}</span>
        {candidate.unresolved_element_ids.length > 0 && <span className="unresolved-count">{candidate.unresolved_element_ids.length} 项未解析</span>}
        <button type="button" className="candidate-comparison-base" disabled={generationBusy} onClick={() => void onUseArtistComparisonBase(candidate)}>{isArtistComparisonBase ? "当前对照基准" : "设为画师对照基准"}</button>
        {onGenerate && <button type="button" className="candidate-generate" disabled={generationDisabled} onClick={() => void onGenerate(candidate)}>{generationBusy ? "正在提交…" : "远程生图"}</button>}
      </footer>
      {candidate.warnings.length > 0 && <details className="candidate-warnings"><summary>{candidate.warnings.length} 条说明</summary>{candidate.warnings.map((warning) => <p key={`${warning.code}-${warning.message}`}>{warning.message}</p>)}</details>}
    </article>
  );
}

function PromptBlock({label, value, copied, onCopy, negative = false, notes = []}: {label: string; value: string; copied: boolean; onCopy: () => void; negative?: boolean; notes?: Array<{en: string; zh: string}>}) {
  return (
    <div className={`prompt-block${negative ? " prompt-block--negative" : ""}`}>
      <div><span>{label}</span><button type="button" onClick={onCopy}>{copied ? "已复制" : "复制"}</button></div>
      <code>{value}</code>
      {notes.some((note) => note.zh) && (
        <ul className="prompt-zh" aria-label={`${label} 中文对照`}>
          {notes.map((note) => (
            <li key={note.en}>
              <code>{note.en}</code>
              <span>{note.zh || "（无中文名）"}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function normalizeDraft(draft: Partial<WorkspaceDraft> | undefined, naturalLanguageEnabled: boolean): WorkspaceDraft {
  return {
    positive_text: draft?.positive_text || "",
    excluded_text: draft?.excluded_text || "",
    model_profile: draft?.model_profile || "anima_aesthetic_v1",
    input_mode: draft?.input_mode || (naturalLanguageEnabled ? "natural" : "concepts"),
    natural_text: draft?.natural_text || "",
    selected_tags: draft?.selected_tags || [],
    suppressed_tags: draft?.suppressed_tags || [],
    generation_settings: {...defaultGenerationSettings, ...(draft?.generation_settings || {})},
  };
}

function resolvedGenerationSettings(settings: WorkbenchGenerationSettings, overrides: {seed?: number; batch_size?: number} = {}) {
  const size = aspectSizes[settings.aspect];
  return {
    preset_id: settings.preset_id,
    ...(size || {}),
    seed: overrides.seed ?? settings.seed,
    batch_size: overrides.batch_size ?? settings.batch_size,
  };
}

const defaultNegativeZh: Record<string, string> = {
  "worst quality": "最差画质",
  "low quality": "低画质",
  "artist name": "画师名",
  "blurry": "模糊",
  "jpeg artifacts": "jpeg 压缩噪点",
  "chromatic aberration": "色差",
  "watermark": "水印",
  "signature": "签名",
  "english text": "英文文字",
  "speech bubble": "对话框",
  "character name": "角色名",
  "copyright name": "作品名",
  "web address": "网址",
};

function hasCjk(value: string): boolean {
  return /[\u3400-\u9fff]/.test(value);
}

function chineseLabelsFromResult(result: WorkbenchResponse | null): Map<string, string> {
  const labels = new Map<string, string>(Object.entries(defaultNegativeZh).map(([en, zh]) => [en.replaceAll(" ", "_"), zh]));
  const remember = (tag: string | null | undefined, zh: string | null | undefined) => {
    if (!tag || !zh || !hasCjk(zh)) return;
    labels.set(tag, zh);
    labels.set(tag.replaceAll("_", " "), zh);
  };
  const draft = result?.scene_draft;
  if (draft) {
    for (const item of [...draft.confirmed, ...draft.exclusions, ...(draft.suggestions || []), ...(draft.suppressed || [])]) {
      remember(item.canonical_tag, item.cn_name || (hasCjk(item.text) ? item.text : null));
    }
    for (const group of draft.ambiguous || []) {
      for (const option of group.options) remember(option.canonical_tag, option.cn_name);
    }
  }
  for (const item of result?.tag_suggestions || []) remember(item.name, item.cn_name);
  for (const candidate of result?.candidates || []) {
    for (const tag of candidate.tags) remember(tag.name, tag.cn_name);
  }
  return labels;
}

function annotatePrompt(value: string, labels: Map<string, string>, proseZh: string, isNegative = false): Array<{en: string; zh: string}> {
  const trimmed = value.trim();
  if (!trimmed) return [];
  const lookup = (token: string) => labels.get(token.toLowerCase().replaceAll(" ", "_")) || labels.get(token.toLowerCase()) || labels.get(token) || "";
  if (isNegative) {
    const tokens = trimmed.split(",").map((item) => item.trim()).filter(Boolean);
    const mapped = tokens.map((token) => ({en: token, zh: lookup(token)}));
    if (mapped.every((item) => item.zh) || !proseZh) return mapped;
    return [{en: trimmed, zh: proseZh}, ...mapped.filter((item) => item.zh)];
  }
  const dot = trimmed.search(/\.\s+[A-Z"'“]/);
  const tagPart = dot >= 0 ? trimmed.slice(0, dot) : trimmed;
  const prose = dot >= 0 ? trimmed.slice(dot + 1).trim() : "";
  const rows = tagPart.split(",").map((item) => item.trim()).filter(Boolean).map((token) => ({en: token, zh: lookup(token)}));
  if (prose) rows.push({en: prose, zh: proseZh});
  return rows;
}

function generationSummary(settings: WorkbenchGenerationSettings): string {
  const seedLabel = settings.seed < 0 ? "随机 Seed" : `Seed ${settings.seed}`;
  return `${presetLabels[settings.preset_id]} · ${aspectLabels[settings.aspect]} · ${seedLabel} · 批量 ${settings.batch_size}`;
}

function splitConcepts(value: string): string[] {
  return value.split(/[，,;；\n]+/).map((item) => item.trim()).filter(Boolean);
}

function mergeImportedTags(value: string, importedTags: string[]): string {
  const current = splitConcepts(value);
  const known = new Set(current.map((item) => item.toLowerCase().replaceAll(" ", "_")));
  return [...current, ...importedTags.filter((item) => !known.has(item.toLowerCase().replaceAll(" ", "_")))].join("，");
}

function sameStringList(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}

function confirmedFactOwners(draft: SceneDraft): Record<string, string> {
  return Object.fromEntries(draft.confirmed.filter((item) => item.owner_entity_id).map((item) => [item.id, item.owner_entity_id as string]));
}

function factOwnersRequest(draft: SceneDraft): {fact_owners?: Record<string, string>} {
  const factOwners = confirmedFactOwners(draft);
  return Object.keys(factOwners).length ? {fact_owners: factOwners} : {};
}

type SceneRelationRequest = Pick<SceneRelation, "source_entity_id" | "target_element_id" | "relation">;

function sceneRelationRequest(relation: SceneRelation): SceneRelationRequest {
  return {source_entity_id: relation.source_entity_id, target_element_id: relation.target_element_id, relation: relation.relation};
}

function confirmedSceneRelations(draft: SceneDraft): SceneRelationRequest[] {
  return (draft.relations || []).filter((item) => item.state === "confirmed").map(sceneRelationRequest);
}

function confirmedRelationsRequest(draft: SceneDraft): {confirmed_relations?: SceneRelationRequest[]} {
  const relations = confirmedSceneRelations(draft);
  return relations.length ? {confirmed_relations: relations} : {};
}

function relationRequestKey(relation: SceneRelationRequest): string {
  return `${relation.source_entity_id}\u0000${relation.target_element_id}\u0000${relation.relation}`;
}

function workspaceCandidateSnapshot(result: WorkbenchResponse | null): WorkbenchResponse | null {
  if (!result) return null;
  return {
    intent: result.intent,
    candidates: result.candidates,
    validation: result.validation,
    data_pack_id: result.data_pack_id,
    ...(result.artist_suggestions ? {artist_suggestions: result.artist_suggestions} : {}),
    ...(result.tag_suggestions ? {tag_suggestions: result.tag_suggestions} : {}),
    ...(result.scene_draft ? {scene_draft: result.scene_draft} : {}),
  };
}

function groupIntentFacts(elements: IntentParseResponse["intent"]["graph"]["elements"]): Array<{element: IntentParseResponse["intent"]["graph"]["elements"][number]; count: number}> {
  const grouped = new Map<string, {element: IntentParseResponse["intent"]["graph"]["elements"][number]; count: number}>();
  for (const element of elements) {
    const key = `${element.state}\u0000${element.original_text}`;
    const existing = grouped.get(key);
    if (existing) existing.count += 1;
    else grouped.set(key, {element, count: 1});
  }
  return [...grouped.values()];
}

function factTypeLabel(value: string): string {
  return factLayerMeta.find((item) => item.type === value)?.label || "尚未归层";
}

function buildLocalParseInfo(payload: WorkbenchResponse & {local_translation?: {engine: string}}, label: string): IntentParseResponse {
  return {
    intent: payload.intent,
    extraction: {summary_zh: label, people_count: 0, subject_mode: "local", content_rating: "unknown", scene_type: "local", truncated_source: false},
    parser: {name: `本地翻译 · ${payload.local_translation?.engine || "当前译文"}`, source: "v2_local_translation"},
  };
}

function targetKey(target: GenerationTarget): string {
  return `${target.remote_profile_id}::${target.workflow_profile_id}`;
}

function remoteConnectionLabel(target: GenerationTarget): string {
  const endpoint = target.remote_ssh_host
    ? `${target.remote_ssh_host}${target.remote_ssh_port ? `:${target.remote_ssh_port}` : ""}`
    : "";
  return endpoint ? `${target.remote_display_name} · ${endpoint}` : target.remote_display_name;
}

function loadRecoveredWorkbench(): RecoveredWorkbench | null {
  if (import.meta.env.MODE === "test") return null;
  try {
    const value = localStorage.getItem(RECOVERY_KEY);
    if (!value) return null;
    const parsed = JSON.parse(value) as Partial<RecoveredWorkbench>;
    if (!parsed.draft || typeof parsed.workspaceTitle !== "string") return null;
    const workspace = parsed.workspace
      && typeof parsed.workspace.id === "string"
      && typeof parsed.workspace.revision === "number"
      ? parsed.workspace
      : null;
    return {draft: parsed.draft, result: parsed.result || null, workspaceTitle: parsed.workspaceTitle, workspace};
  } catch {
    return null;
  }
}
