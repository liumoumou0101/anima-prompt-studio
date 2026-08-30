import {useEffect, useMemo, useRef, useState} from "react";
import type {FormEvent} from "react";
import {useSearchParams} from "react-router-dom";
import {apiRequest, ApiClientError} from "../lib/api";
import type {ArtistComparisonSubmission, ArtistSuggestion, CandidateLane, GenerationRunRecord, GenerationTarget, GenerationTargetListResponse, IntentParseResponse, PromptCandidate, SceneDraft, SceneRelation, TagSuggestion, TranslationResponse, WorkbenchResponse, WorkspaceDraft, WorkspaceListResponse, WorkspaceRecord} from "../lib/types";
import {EmptyState, ErrorState, LoadingState} from "../components/States";

const profiles = [
  {id: "anima_base_v1", label: "ANIMA Base"},
  {id: "anima_aesthetic_v1", label: "ANIMA Aesthetic"},
  {id: "anima_turbo_v1", label: "ANIMA Turbo"},
];
const RECOVERY_KEY = "anima-v3-workbench-recovery";
const GENERATION_TARGET_KEY = "anima-v3-generation-target";
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
    const base = recovered?.draft || {positive_text: "", excluded_text: "", model_profile: "anima_aesthetic_v1", input_mode: naturalLanguageEnabled ? "natural" : "concepts", natural_text: "", selected_tags: []};
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

  const positiveText = draft.positive_text;
  const excludedText = draft.excluded_text;
  const profile = draft.model_profile;
  const inputMode = draft.input_mode || "concepts";
  const naturalText = draft.natural_text || "";
  const selectedTags = draft.selected_tags || [];

  const positiveItems = useMemo(() => splitConcepts(positiveText), [positiveText]);
  const excludedItems = useMemo(() => splitConcepts(excludedText), [excludedText]);
  const compatibleTargets = useMemo(() => {
    const unique = new Map<string, GenerationTarget>();
    for (const target of generationTargets) {
      if (target.compatible_model_profiles.length && !target.compatible_model_profiles.includes(profile)) continue;
      const visibleIdentity = `${target.remote_display_name}\u0000${target.workflow_display_name}`;
      if (!unique.has(visibleIdentity)) unique.set(visibleIdentity, target);
    }
    return [...unique.values()];
  }, [generationTargets, profile]);
  const activeTarget = compatibleTargets.find((target) => targetKey(target) === selectedTarget);
  const reviewedFacts = useMemo(() => groupIntentFacts(parseInfo?.intent.graph.elements || []), [parseInfo]);

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
      .then((payload) => setGenerationTargets(payload.items.filter((item) => item.host_fingerprint_ready)))
      .catch((caught) => setGenerationNotice((caught as ApiClientError).message));
  }, [remoteEnabled]);

  useEffect(() => {
    if (!compatibleTargets.some((target) => targetKey(target) === selectedTarget)) {
      const preferred = compatibleTargets.find((target) => /aesthetic[_\s-]*v?1\.1/i.test(target.workflow_display_name)) || compatibleTargets[0];
      setSelectedTarget(preferred ? targetKey(preferred) : "");
    }
  }, [compatibleTargets, selectedTarget]);

  useEffect(() => {
    if (!selectedTarget) return;
    try { localStorage.setItem(GENERATION_TARGET_KEY, selectedTarget); } catch { /* Best-effort preference. */ }
  }, [selectedTarget]);

  function editDraft(patch: Partial<WorkspaceDraft>) {
    const next = {...draft, ...patch};
    if (next.positive_text === draft.positive_text && next.excluded_text === draft.excluded_text && next.model_profile === draft.model_profile && next.input_mode === draft.input_mode && next.natural_text === draft.natural_text && sameStringList(next.selected_tags || [], draft.selected_tags || [])) return;
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
    setDraft({...item.draft, input_mode: item.draft.input_mode || "concepts", natural_text: item.draft.natural_text || "", selected_tags: item.draft.selected_tags || []});
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

  function structuredCandidateRequest(selected = selectedTags, translatedText?: string) {
    return {
      source_text: [...positiveItems, ...excludedItems.map((item) => `不要 ${item}`)].join("，"),
      source_language: "mixed",
      model_profile: profile,
      elements: structuredElements(),
      selected_tags: selected,
      ...(translatedText ? {translated_text: translatedText} : {}),
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
          body: JSON.stringify({source_text: naturalText, excluded_text: excludedText, model_profile: profile, selected_tags: selectedTags}),
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
          body: JSON.stringify({source_text: naturalText, excluded_text: excludedText, translated_text: translatedText, model_profile: profile, selected_tags: nextTags, ...factOwnersRequest(result.scene_draft), ...confirmedRelationsRequest(result.scene_draft)}),
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
          body: JSON.stringify({source_text: naturalText, excluded_text: excludedText, translated_text: translatedText, model_profile: profile, selected_tags: selectedTags, ...factOwnersRequest(result.scene_draft), ...confirmedRelationsRequest(result.scene_draft)}),
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
        body: JSON.stringify({
          source_text: naturalText,
          excluded_text: excludedText,
          translated_text: result.scene_draft.translated_text,
          model_profile: profile,
          selected_tags: selectedTags,
          fact_owners: factOwners,
          ...(confirmedRelations.length ? {confirmed_relations: confirmedRelations} : {}),
        }),
      });
      setLocalParseInfo(local, "已更新实体归属；未调用翻译模型");
      setResult(local);
    } catch (caught) {
      setError(caught as ApiClientError);
    } finally {
      setLoading(false);
    }
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
        body: JSON.stringify({
          source_text: naturalText,
          excluded_text: excludedText,
          translated_text: result.scene_draft.translated_text,
          model_profile: profile,
          selected_tags: selectedTags,
          ...factOwnersRequest(result.scene_draft),
          ...(relations.length ? {confirmed_relations: relations} : {}),
        }),
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
    setArtistSuggestions(result.artist_suggestions || []);
    try {
      const payload = await apiRequest<{items: ArtistSuggestion[]}>("/api/v3/artists/recommend", {
        method: "POST",
        body: JSON.stringify({tags: candidate.tags.map((tag) => tag.name), limit: 20}),
      });
      setArtistSuggestions(payload.items);
    } catch (caught) {
      setGenerationNotice(`无法扩展画师推荐池：${(caught as ApiClientError).message}`);
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
    const selection = [artistComparisonBase.id, selectedTarget, artistComparisonSeed, ...selectedArtists].join("|");
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
          settings: {seed: artistComparisonSeed, batch_size: 1},
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
        <div><span className="eyebrow">PROMPT WORKBENCH</span><h1>候选工作台</h1><p>先忠实映射输入，再把推荐和画师作为可比较、可移除的增量。</p></div>
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
        <button type="button" role="tab" aria-selected={inputMode === "concepts"} onClick={() => editDraft({input_mode: "concepts"})}>结构化概念</button>
        <button type="button" role="tab" aria-selected={inputMode === "natural"} disabled={!naturalLanguageEnabled} title={naturalLanguageEnabled ? "本地翻译、词典与数据包索引；不调用 AI API" : "请先连接 V2 本地翻译资源"} onClick={() => editDraft({input_mode: "natural"})}>自然语言描述</button>
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
        {parseInfo.intent.scene_plan_en && <details><summary>查看 Hybrid 英文画面计划</summary><p>{parseInfo.intent.scene_plan_en}</p></details>}
        {result?.scene_draft ? <SceneDraftReview draft={result.scene_draft} relatedSuggestions={result.tag_suggestions || []} selectedTags={selectedTags} busy={loading} onToggle={toggleTagSuggestion} onApplyTranslation={applySceneDraftTranslation} onAssignFactOwner={inputMode === "natural" ? applyFactOwner : undefined} onToggleRelation={inputMode === "natural" ? applySceneRelation : undefined} /> : <p className="intent-review-warning">本地翻译只会把本地索引中的精确匹配加入标签；未命中的画面信息会保留在 Hybrid 英文提示词中，提交前可继续检查候选说明。</p>}
      </section>}

      <div className="workbench-results" aria-live="polite">
        {loading ? <LoadingState label="正在映射标签、计算推荐并验证候选…" /> : error ? (
          <ErrorState message={error.message} requestId={error.requestId} />
        ) : result ? (
          <>
            <div className="validation-strip"><span className="status-dot is-ready" /><strong>结构检查通过</strong><span>语义仍需确认 · {result.candidates.length} 条候选 · {result.data_pack_id}</span></div>
            {remoteEnabled && <div className="generation-submit-bar">
              <div><strong>远程生图</strong><span>{compatibleTargets.length ? "选择 V2 已验证目标后，从候选卡片提交" : "当前模型没有已确认指纹的兼容工作流"}</span></div>
              <select aria-label="远程生成目标" value={selectedTarget} onChange={(event) => setSelectedTarget(event.target.value)} disabled={!compatibleTargets.length}>
                {compatibleTargets.length ? compatibleTargets.map((target) => <option key={targetKey(target)} value={targetKey(target)}>{target.remote_display_name} · {target.workflow_display_name}</option>) : <option value="">无可用目标</option>}
              </select>
              {activeTarget?.auth_type === "private_key" && <label className="passphrase-input"><span>私钥口令（可选，仅本次运行内存）</span><input type="password" autoComplete="current-password" value={privateKeyPassphrase} onChange={(event) => setPrivateKeyPassphrase(event.target.value)} placeholder={activeTarget.private_key_passphrase_configured ? "已在本次运行中设置" : "私钥未加密可留空"} /></label>}
            </div>}
            {generationNotice && <div className="workspace-notice workspace-notice--error" role="alert">{generationNotice}</div>}
            <div className="candidate-grid">
              {result.candidates.map((candidate) => (
                <CandidateCard key={candidate.id} candidate={candidate} copied={copied} onCopy={copyPrompt} onGenerate={remoteEnabled ? submitGeneration : undefined} generationBusy={generationBusy === candidate.id} generationDisabled={!selectedTarget || generationBusy !== null} onUseArtistComparisonBase={useArtistComparisonBase} isArtistComparisonBase={artistComparisonBase?.id === candidate.id} />
              ))}
            </div>
            <ArtistComparisonPanel
              items={artistComparisonBase ? artistSuggestions : (result.artist_suggestions || [])}
              base={artistComparisonBase}
              selectedArtists={selectedArtists}
              seed={artistComparisonSeed}
              remoteEnabled={remoteEnabled}
              canSubmit={Boolean(selectedTarget)}
              busy={artistComparisonBusy}
              onToggle={toggleArtistSuggestion}
              onSelectVisible={() => setSelectedArtists((artistComparisonBase ? artistSuggestions : result.artist_suggestions || []).slice(0, 20).map((item) => item.name))}
              onClear={() => setSelectedArtists([])}
              onSeedChange={setArtistComparisonSeed}
              onSubmit={() => void submitArtistComparison()}
            />
          </>
        ) : (
          <EmptyState title="从忠实基准开始" detail="输入画面概念后，工作台会并排生成可追踪的候选。自动推荐不会静默加入角色或版权标签。" />
        )}
      </div>
    </section>
  );
}

function ArtistComparisonPanel({items, base, selectedArtists, seed, remoteEnabled, canSubmit, busy, onToggle, onSelectVisible, onClear, onSeedChange, onSubmit}: {
  items: ArtistSuggestion[];
  base: PromptCandidate | null;
  selectedArtists: string[];
  seed: number;
  remoteEnabled: boolean;
  canSubmit: boolean;
  busy: boolean;
  onToggle: (name: string) => void;
  onSelectVisible: () => void;
  onClear: () => void;
  onSeedChange: (value: number) => void;
  onSubmit: () => void;
}) {
  if (!items?.length) return null;
  return (
    <section className="artist-suggestion-pool" aria-label="画师对照">
      <header><div><strong>画师对照组</strong><span>{base ? "每位画师各自生成一张；只改变 @artist 标签。" : "先在候选卡上选择一条提示词作为画师对照基准。"}</span></div><small>Top {items.length}</small></header>
      {base && <div className="artist-comparison-base"><span>已锁定基准</span><strong>{base.title}</strong><code>{base.positive_prompt}</code></div>}
      {base && <div className="artist-comparison-controls">
        <span>已选 {selectedArtists.length}/20</span>
        <button type="button" onClick={onSelectVisible} disabled={busy}>选中当前 {Math.min(items.length, 20)} 位</button>
        <button type="button" onClick={onClear} disabled={!selectedArtists.length || busy}>清空</button>
        <label>固定 Seed<input type="number" min="0" max="2147483647" value={seed} disabled={busy} onChange={(event) => onSeedChange(Number(event.target.value))} /></label>
        <button type="button" className="artist-comparison-submit" disabled={!remoteEnabled || !canSubmit || !selectedArtists.length || busy} onClick={onSubmit}>{busy ? "正在提交对照组…" : `提交 ${selectedArtists.length || ""} 位画师对照`}</button>
      </div>}
      <ol>
        {items.map((artist, index) => <li key={artist.name} className={selectedArtists.includes(artist.name) ? "is-selected" : ""}>
          <span className="artist-rank">{index + 1}</span>
          <div><strong>{artist.render_name}</strong><small>匹配 {artist.sources.join("、")} · 共现 {artist.cooc_count}</small></div>
          <span className="artist-score">{Math.round(artist.display_score * 100)}%</span>
          {base && <button type="button" aria-pressed={selectedArtists.includes(artist.name)} disabled={busy} onClick={() => onToggle(artist.name)}>{selectedArtists.includes(artist.name) ? "已选" : "选入对照"}</button>}
        </li>)}
      </ol>
      <p>{base ? "同一组会共用模型、工作流、尺寸、预设与 Seed；远程队列按顺序执行。" : "推荐不会自动写入提示词；锁定基准后可选择最多 20 位画师批量生图。"}</p>
    </section>
  );
}

function SceneDraftReview({draft, relatedSuggestions, selectedTags, busy, onToggle, onApplyTranslation, onAssignFactOwner, onToggleRelation}: {
  draft: SceneDraft;
  relatedSuggestions: TagSuggestion[];
  selectedTags: string[];
  busy: boolean;
  onToggle: (tag: string) => Promise<void>;
  onApplyTranslation: (translatedText: string) => Promise<void>;
  onAssignFactOwner?: (factId: string, entityId: string) => Promise<void>;
  onToggleRelation?: (relation: SceneRelation, confirmed: boolean) => Promise<void>;
}) {
  const [translatedText, setTranslatedText] = useState(draft.translated_text);
  useEffect(() => setTranslatedText(draft.translated_text), [draft.translated_text]);
  const suggestions = new Map<string, {rendered: string; reason: string}>();
  for (const item of draft.suggestions) {
    if (item.canonical_tag) suggestions.set(item.canonical_tag, {rendered: item.canonical_tag.replaceAll("_", " "), reason: item.reason});
  }
  for (const item of relatedSuggestions) {
    if (!suggestions.has(item.name)) suggestions.set(item.name, {rendered: item.render_name, reason: `与 ${item.sources.join("、")} 共现；默认不应用`});
  }
  return (
    <section className="scene-draft-review" aria-label="Scene Draft">
      <header><div><strong>Scene Draft</strong><span>原文证据、译文和本地映射分开保存；建议不会自动加入候选。</span></div></header>
      <div className="scene-draft-prose">
        <div><strong>可编辑画面计划</strong><span>修改后只重新映射与渲染，不重新加载翻译模型。</span></div>
        <textarea aria-label="可编辑画面计划" value={translatedText} disabled={busy} onChange={(event) => setTranslatedText(event.target.value)} rows={4} />
        <button type="button" disabled={busy || !translatedText.trim() || translatedText.trim() === draft.translated_text.trim()} onClick={() => void onApplyTranslation(translatedText.trim())}>{busy ? "正在重新映射…" : "应用译文修改"}</button>
      </div>
      <LayeredDraftGroup items={draft.confirmed} />
      <EntityOwnershipReview draft={draft} busy={busy} onAssign={onAssignFactOwner} />
      <SceneRelationReview draft={draft} busy={busy} onToggle={onToggleRelation} />
      <DraftGroup label="明确排除" items={draft.exclusions || []} empty="当前没有识别到明确排除项。" excluded />
      <div className="scene-draft-group">
        <strong>待确认建议</strong>
        {suggestions.size ? <div className="scene-draft-suggestions">{[...suggestions].map(([tag, item]) => {
          const selected = selectedTags.includes(tag);
          return <button type="button" key={tag} aria-pressed={selected} disabled={busy} title={item.reason} onClick={() => void onToggle(tag)}><span>{item.rendered}</span><small>{selected ? "已选用" : "选用"}</small></button>;
        })}</div> : <p>没有待确认的标签建议。</p>}
      </div>
      <DraftGroup label="未命中内容" items={draft.unresolved} empty="全部内容都有本地确认映射；仍请检查动作、关系和构图。" />
      {draft.risk_notes.length > 0 && <ul className="scene-draft-risks">{draft.risk_notes.map((item) => <li key={item}>{item}</li>)}</ul>}
    </section>
  );
}

function DraftGroup({label, items, empty, excluded = false}: {label: string; items: SceneDraft["confirmed"]; empty: string; excluded?: boolean}) {
  return <div className={`scene-draft-group${excluded ? " is-excluded" : ""}`}><strong>{label}</strong>{items.length ? <ul>{items.map((item) => <li key={item.id}><span>{item.text}</span>{item.canonical_tag && <code>{item.canonical_tag.replaceAll("_", " ")}</code>}<small>{item.reason}</small></li>)}</ul> : <p>{empty}</p>}</div>;
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

function LayeredDraftGroup({items}: {items: SceneDraft["confirmed"]}) {
  const layers = factLayerMeta
    .map((meta) => ({...meta, items: items.filter((item) => (item.fact_type || "other") === meta.type)}))
    .filter((layer) => layer.items.length > 0);
  return (
    <div className="scene-draft-layers">
      <div><strong>已确认画面事实</strong><span>只改变排列和审阅层次，不会补充原文没有的内容。</span></div>
      {layers.length ? layers.map((layer) => (
        <DraftGroup key={layer.type} label={layer.label} items={layer.items} empty="" />
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

function CandidateCard({candidate, copied, onCopy, onGenerate, generationBusy = false, generationDisabled = false, onUseArtistComparisonBase, isArtistComparisonBase = false}: {
  candidate: PromptCandidate;
  copied: string | null;
  onCopy: (candidate: PromptCandidate, kind: "positive" | "negative") => Promise<void>;
  onGenerate?: (candidate: PromptCandidate) => Promise<void>;
  generationBusy?: boolean;
  generationDisabled?: boolean;
  onUseArtistComparisonBase: (candidate: PromptCandidate) => Promise<void>;
  isArtistComparisonBase?: boolean;
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
      <PromptBlock label="Positive" value={candidate.positive_prompt} copied={copied === `${candidate.id}:positive`} onCopy={() => onCopy(candidate, "positive")} />
      {candidate.negative_prompt && <PromptBlock label="Negative" value={candidate.negative_prompt} copied={copied === `${candidate.id}:negative`} onCopy={() => onCopy(candidate, "negative")} negative />}
      <div className="candidate-tokens">
        {candidate.tags.map((tag) => <span key={tag.name} className={tag.state === "automatic" ? "is-automatic" : tag.state === "locked" ? "is-locked" : ""} title={tag.reason}>{tag.rendered}</span>)}
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

function PromptBlock({label, value, copied, onCopy, negative = false}: {label: string; value: string; copied: boolean; onCopy: () => void; negative?: boolean}) {
  return (
    <div className={`prompt-block${negative ? " prompt-block--negative" : ""}`}>
      <div><span>{label}</span><button type="button" onClick={onCopy}>{copied ? "已复制" : "复制"}</button></div>
      <code>{value}</code>
    </div>
  );
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
