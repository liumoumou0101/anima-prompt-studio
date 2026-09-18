import {ImagePreview} from "../components/ImagePreview";
import {ArtistRecommendations} from "../components/ArtistRecommendations";
import {SceneDesignControls} from "../components/SceneDesignControls";
import {sceneFields, sceneChoice} from "../lib/sceneDesign";
import {ManualIdentityTags} from "../components/ManualIdentityTags";
import {GenerationAssessment} from "../components/GenerationAssessment";
import {loadGallery} from "../lib/galleryStore";
import type {GalleryAsset} from "../lib/types";
import {useEffect, useRef, useState} from "react";
import {Link, useSearchParams} from "react-router-dom";
import {ChatCircleDots, Check, Copy, GearSix, ImageSquare, PaperPlaneRight, Plus, SlidersHorizontal, Sparkle} from "@phosphor-icons/react";
import {apiRequest, ApiClientError} from "../lib/api";
import {seedInput, validSeed, applyGenerationRecipe, changeGenerationModel, defaultGenerationSettings, markGenerationCustom, resolvedGenerationSettings} from "../lib/generationSettings";
import {defaultTarget, targetLabel, targetDescription, targetRemoteLabel} from "../lib/workflowTargets";
import {modelProfileChoices, LEGACY_AESTHETIC, resolveLegacyAesthetic} from "../lib/modelProfiles";
import {negativeGuidance, appendNegative} from "../lib/negativeGuidance";
import {cleanRequirements, editableRequirements, emptyRequirements, hasUncompiledInputs, hasUnsavedInputs, layerLabels} from "../lib/conversation";
import {applySelectedContent, consumeTransfer, readTransfer, undoSelectedContent, type ContentTransfer, type SelectedContent} from "../lib/contentTransfer";
import "./conversationWorkbench.css";
import {LlmSettingsPanel} from "../components/LlmSettingsPanel";
import {useWorkbenchThinking} from "../lib/useWorkbenchThinking";
import {ConversationReview, type ConversationProposal} from "../components/ConversationReview";
import {ConversationVersions} from "../components/ConversationVersions";
import {PromptLocks} from "../components/PromptLocks";
import {GenerationComparison} from "../components/GenerationComparison";
import {ConversationDraftRecovery} from "../components/ConversationDraftRecovery";
import {readConversationDraft, saveConversationDraft, initializeConversationTab, recoverConversationPending, saveConversationPending, clearConversationPending, recoverConversationBranch, saveConversationBranch, clearConversationBranch, preserveConversationDraft, readConversationDraftCandidate, type ConversationDraftCandidate} from "../lib/conversationDrafts";
import {mergeConversation, resolveConversationConflicts} from "../lib/conversationMerge";
import {LoraMappingPanel, type ResourceIdentity} from "./LoraMappingPanel";
import type {ConversationRecord, LayerName, LocalConversation, RequirementLayers} from "../lib/conversation";
import type {GenerationRunRecord, GenerationTarget, GenerationTargetListResponse, ModelProfileOption, WorkspaceListResponse} from "../lib/types";

const ACTIVE = "anima-conversation-active";
type Pending = {key: string; body: string};
type Accepted = GenerationRunRecord & {workspace_revision: number; compiled_token: string};
function read<T>(key: string): T | null {try {return JSON.parse(localStorage.getItem(key) || "null") as T | null;} catch {return null;}}
function write(key: string, value: unknown) {try {localStorage.setItem(key, JSON.stringify(value));} catch { /* Server remains authoritative. */ }}
function remove(key: string) {try {localStorage.removeItem(key);} catch { /* Best effort. */ }}
function localFrom(record: ConversationRecord): LocalConversation {
  return {baseRevision: record.revision, delta: "", requirements: editableRequirements(record), mode: record.draft.mode,
    positive: record.draft.compiled?.positive || "", negative: record.draft.compiled?.negative || "",
    model: record.draft.model_profile, settings: record.draft.generation_settings || defaultGenerationSettings()};
}

export function ConversationWorkbenchPage({modelProfiles, remoteEnabled = false}: {modelProfiles?: ModelProfileOption[]; remoteEnabled?: boolean}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedWorkspace = searchParams.get("workspace");
  const requestedTransfer = searchParams.get("transfer");
  const [initialLoaded, setInitialLoaded] = useState(false);
  const transferAttempt = useRef("");
  const [transferRetry, setTransferRetry] = useState(0);
  const [transferNotice, setTransferNotice] = useState<{workspace: string; added: SelectedContent[]} | null>(null);
  const [record, setRecord] = useState<ConversationRecord | null>(null);
  const current = useRef<ConversationRecord | null>(null);
  const [local, setLocal] = useState<LocalConversation | null>(null);
  const base = useRef<LocalConversation | null>(null);
  const [storageWarning, setStorageWarning] = useState("");
  const [invalidDraftRaw, setInvalidDraftRaw] = useState("");
  const draftPersistenceBlocked = useRef<string | null>(null);
  const [notice, setNotice] = useState("");
  const [proposal, setProposal] = useState<ConversationProposal | null>(null);
  const [conflictChoices, setConflictChoices] = useState<Record<string, "local" | "remote">>({});
  const [elapsed, setElapsed] = useState(0);
  const turnController = useRef<AbortController | null>(null);
  const [sessionSearch, setSessionSearch] = useState("");
  const [archived, setArchived] = useState(false);
  const [moreSessions, setMoreSessions] = useState(false);
  const [rename, setRename] = useState<string | null>(null);
  const undoStack = useRef<LocalConversation[]>([]), redoStack = useRef<LocalConversation[]>([]);
  const lastEdit = useRef({keys: "", at: 0});
  const [, setUndoEpoch] = useState(0);
  const [workspaces, setWorkspaces] = useState<WorkspaceListResponse["items"]>([]);
  const [targets, setTargets] = useState<GenerationTarget[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [retryTurn, setRetryTurn] = useState(false);
  const [retryTask, setRetryTask] = useState<"rewrite" | "sync_requirements">("rewrite");
  const [showLlmSettings, setShowLlmSettings] = useState(false);
  const thinking = useWorkbenchThinking();
  const [llmSettingsBusy, setLlmSettingsBusy] = useState(false);
  const [adviceBusy, setAdviceBusy] = useState(false);
  const llmUnavailableReason = thinking.unavailableReason || (llmSettingsBusy ? "正在保存或测试 LLM 配置…" : "");
  const llmContextKey = JSON.stringify([thinking.current?.service, thinking.current?.model, thinking.enabled]);
  const [inspectorTab, setInspectorTab] = useState<"prompt" | "requirements" | "settings">("prompt");
  useEffect(() => {
    if (inspectorTab !== "settings") return;
    const frame = window.requestAnimationFrame(() => {
      document.getElementById("panel-settings")?.scrollIntoView?.({block: "start", behavior: "instant"});
    });
    return () => window.cancelAnimationFrame(frame);
  }, [inspectorTab]);
  const [idea, setIdea] = useState("");
  const [copied, setCopied] = useState("");
  const [conflict, setConflict] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [pendingRecoveryBlocked, setPendingRecoveryBlocked] = useState(false);
  const [run, setRun] = useState<GenerationRunRecord | null>(null);
  const [recentRuns, setRecentRuns] = useState<GenerationRunRecord[]>([]);
  const [runLimit, setRunLimit] = useState(20);
  const [availability, setAvailability] = useState<{availability: string; message?: string; resource_requirements?: ResourceIdentity[]} | null>(null);
  const [mappingEpoch, setMappingEpoch] = useState(0);
  const opening = useRef(0);
  const requestLock = useRef(false);
  const mounted = useRef(true);
  const resultsPanel = useRef<HTMLElement>(null);
  const profiles = modelProfileChoices(modelProfiles);
  useEffect(() => {
    if (!busy) {setElapsed(0); return;}
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [busy]);
  useEffect(() => {
    if (!local || pending || busy) return;
    const model = resolveLegacyAesthetic(local.model, local.settings, targets);
    if (model !== local.model) edit({model});
  }, [local, targets, pending, busy]);

  function persistDraft(id: string, value: LocalConversation, original = base.current) {
    if (draftPersistenceBlocked.current === id) return false;
    const result = saveConversationDraft(id, value, original);
    setStorageWarning(result.warning || "");
    return result.ok;
  }
  function restoreLocalDraft(candidate: ConversationDraftCandidate): boolean {
    if (!record || !local || busy || pending || proposal || pendingRecoveryBlocked) return false;
    const latest = readConversationDraftCandidate(record.id, candidate.key);
    if (!latest?.local || latest.raw !== candidate.raw) {
      setError("所选草稿已变化或无法读取，请刷新草稿列表并重新预览。"); return false;
    }
    const preserved = preserveConversationDraft(record.id, local, base.current);
    if (!preserved.ok) {setError(preserved.warning || "无法备份当前编辑，尚未恢复草稿。"); return false;}
    const value = structuredClone(latest.local);
    const original = latest.base || (value.baseRevision === record.revision ? localFrom(record) : null);
    const saved = saveConversationDraft(record.id, value, original);
    if (!saved.ok) {setStorageWarning(saved.warning); setError("无法保存恢复后的草稿，当前编辑保持不变。"); return false;}
    base.current = original; setLocal(value);
    draftPersistenceBlocked.current = null; setInvalidDraftRaw(""); setStorageWarning(saved.warning);
    undoStack.current = []; redoStack.current = []; lastEdit.current = {keys: "", at: 0};
    setConflict(value.baseRevision !== record.revision); setConflictChoices({}); setError(""); setRetryTurn(false);
    setInspectorTab("prompt");
    setNotice("已恢复到编辑区，尚未保存到服务端。恢复前的编辑已保留，可在“找回本地草稿”中再次选择。");
    return true;
  }
  function adopt(next: ConversationRecord, preserve = false) {
    if (!mounted.current) return;
    if (current.current?.id === next.id && current.current.revision > next.revision) return;
    current.current = next;
    setRecord(next);
    setCopied("");
    setWorkspaces(items => items.map(item => item.id === next.id ? next : item));
    if (!preserve) {
      const value = localFrom(next);
      undoStack.current = []; redoStack.current = []; lastEdit.current = {keys: "", at: 0};
      base.current = value;
      setLocal(value);
      persistDraft(next.id, value, value);
      setConflict(false);
      setConflictChoices({});
    }
  }

  async function open(id: string) {
    if (draftAtRisk) return false;
    const sequence = ++opening.current;
    setBusy("打开工作台"); setError("");
    try {
      const next = await apiRequest<ConversationRecord>(`/api/v3/workspaces/${encodeURIComponent(id)}`);
      if (!mounted.current || sequence !== opening.current) return false;
      const recovered = readConversationDraft(id);
      draftPersistenceBlocked.current = recovered?.persistenceBlocked ? id : null;
      setInvalidDraftRaw(recovered?.invalidRaw || "");
      adopt(next);
      setWorkspaces(items => items.some(item => item.id === next.id) ? items : [next, ...items]);
      if (recovered?.local) {
        const value = recovered.local;
        const original = recovered.base || (value.baseRevision === next.revision ? localFrom(next) : null);
        const untouched = original && JSON.stringify({...value, delta: ""}) === JSON.stringify({...original, delta: ""});
        if (untouched) {
          const kept = {...localFrom(next), delta: value.delta}; setLocal(kept); persistDraft(id, kept, localFrom(next));
        } else {
          base.current = original; setLocal(value); persistDraft(id, value, original);
          setConflict(value.baseRevision !== next.revision);
        }
      }
      if (recovered?.warning) setStorageWarning(recovered.warning);
      setPendingRecoveryBlocked(false);
      try {setPending(recoverConversationPending(id));} catch (caught) {setPending(null); setPendingRecoveryBlocked(true); setError((caught as Error).message);}
      setRun(null); setRecentRuns([]); setRunLimit(20); setAvailability(null); setProposal(null); setNotice(""); setRename(null);
      const review = await apiRequest<{proposal: ConversationProposal | null}>(`/api/v3/workspaces/${encodeURIComponent(id)}/proposal`);
      if (!mounted.current || sequence !== opening.current) return false;
      setProposal(review.proposal || null);
      write(ACTIVE, id);
      if (requestedWorkspace && requestedWorkspace !== id) clearWorkspaceLink();
      return true;
    } catch (caught) {if (mounted.current && sequence === opening.current) setError((caught as Error).message); return false;}
    finally {if (mounted.current && sequence === opening.current) setBusy("");}
  }

  useEffect(() => {
    mounted.current = true;
    setInitialLoaded(false);
    void initializeConversationTab().then(() => apiRequest<WorkspaceListResponse>("/api/v3/workspaces?limit=50")).then(async result => {
      if (!mounted.current) return;
      setWorkspaces(result.items);
      setMoreSessions(result.items.length === 50);
      const id = requestedWorkspace || read<string>(ACTIVE);
      const opened = !id || current.current?.id === id || await open(id);
      if (mounted.current && opened) setInitialLoaded(true);
    }).catch(caught => {if (mounted.current) setError((caught as Error).message);});
    if (remoteEnabled) void apiRequest<GenerationTargetListResponse>("/api/v3/generation-targets").then(result => {
      if (mounted.current) setTargets(result.items);
    }).catch(caught => {if (mounted.current) setError((caught as Error).message);});
    return () => {mounted.current = false; opening.current++; turnController.current?.abort();};
  }, [remoteEnabled, requestedWorkspace, transferRetry]);

  useEffect(() => {
    if (!requestedTransfer || !initialLoaded || busy || pending || conflict || transferAttempt.current === requestedTransfer) return;
    transferAttempt.current = requestedTransfer;
    try {
      const transfer = readTransfer(requestedTransfer);
      if (transfer) void receiveContent(transfer);
      else {clearTransferLink(); setError("这批内容已带入或已过期，请在画面要求中查看，或重新选择。");}
    } catch (caught) {setError((caught as Error).message);}
  }, [requestedTransfer, initialLoaded, busy, pending, conflict, transferRetry]);

  function clearTransferLink() {
    setSearchParams(previous => {const next = new URLSearchParams(previous); next.delete("transfer"); return next;}, {replace: true});
  }
  async function receiveContent(transfer: ContentTransfer) {
    await act("带入已选内容", async () => {
      let next = record, value = local;
      if (transfer.destination === "new" || !next || !value) {
        // Validate the selection before creating a server record.
        const initial = applySelectedContent(emptyRequirements(), transfer.items);
        const creationKey = `anima-content-transfer-create:${transfer.id}`;
        const body = read<string>(creationKey) || JSON.stringify({
          title: transfer.items.map(item => item.name).join("、").slice(0, 40), draft: {
            model_profile: local?.model || profiles.find(p => p.id === "anima_aesthetic_v1_1")?.id || profiles[0].id,
            requirements_edit: initial.requirements, generation_settings: local?.settings || defaultGenerationSettings()}});
        localStorage.setItem(creationKey, JSON.stringify(body));
        next = await apiRequest<ConversationRecord>("/api/v3/workspaces", {method: "POST", body,
          headers: {"Idempotency-Key": transfer.id}});
        value = localFrom(next);
        // The server already saved these tags; retain the additions for undo.
        setTransferNotice({workspace: next.id, added: initial.added});
        adopt(next); write(ACTIVE, next.id); setWorkspaces(items => [next!, ...items]);
        setPending(null); setRun(null); setRecentRuns([]); setProposal(null); setAvailability(null);
        if (requestedWorkspace) clearWorkspaceLink();
      } else {
        const result = applySelectedContent(value.requirements, transfer.items);
        value = {...value, requirements: result.requirements};
        // Do not consume the transfer unless its draft can be recovered after reload.
        if (!persistDraft(next.id, value)) throw new Error("本机草稿保存失败，标签尚未带入；请先保存当前版本后重试。");
        setLocal(value); setTransferNotice({workspace: next.id, added: result.added});
      }
      consumeTransfer(transfer.id); remove(`anima-content-transfer-create:${transfer.id}`); clearTransferLink(); setInspectorTab("requirements");
    });
  }

  const dirty = Boolean(record && local && hasUnsavedInputs(record, local));
  const draftAtRisk = Boolean(storageWarning && (dirty || local?.delta.trim()));
  const inputsDirty = Boolean(record && local && hasUnsavedInputs(record, {...local, positive: record.draft.compiled?.positive || "", negative: record.draft.compiled?.negative || ""}));
  const compileInputsChanged = Boolean(record && local && hasUncompiledInputs(record, local));
  const needsCompile = compileInputsChanged || record?.draft.compile_state !== "fresh";
  const canCompileRequirements = Boolean(local && [local.requirements.layers.subject.text, local.requirements.layers.style.text,
    ...(local.requirements.layers.subject.character_tags || []), ...(local.requirements.layers.subject.series_tags || []),
    ...(local.requirements.layers.subject.general_tags || []),
    ...(local.requirements.layers.style.manual_artist_tags || []),
    local.requirements.layers.style.medium, ...local.requirements.layers.style.artists, local.requirements.layers.lighting.text,
    local.requirements.layers.composition.text, local.requirements.layers.composition.shot,
    ...sceneFields.map(field => sceneChoice(local.requirements, field)?.value || "")].some(value => value.trim()));
  const target = local && local.model !== LEGACY_AESTHETIC ? targets.find(item => item.remote_profile_id === local.settings.remote_profile_id
    && item.workflow_profile_id === local.settings.workflow_profile_id && item.compatible_model_profiles.includes(local.model)) : undefined;

  useEffect(() => {
    if (!record || !target || inputsDirty || conflict) {setAvailability(null); return;}
    const controller = new AbortController();
    setAvailability(null);
    const query = new URLSearchParams({workspace_id: record.id, revision: String(record.revision),
      remote_profile_id: target.remote_profile_id, workflow_profile_id: target.workflow_profile_id});
    if (record.draft.generation_source) query.set("workflow_snapshot_run_id", record.draft.generation_source.run_id);
    void apiRequest<{availability: string; message?: string}>(`/api/v3/workbench/availability?${query}`, {signal: controller.signal})
      .then(value => {if (!controller.signal.aborted) setAvailability(value);})
      .catch(caught => {if (!controller.signal.aborted) setAvailability({availability: "unknown", message: (caught as Error).message});});
    return () => controller.abort();
  }, [record, target, inputsDirty, conflict, mappingEpoch]);

  useEffect(() => {
    if (!record) return;
    const controller = new AbortController();
    let timer = 0;
    async function poll() {
      try {
        const result = await apiRequest<{items: GenerationRunRecord[]}>(`/api/v3/workspaces/${record!.id}/runs?limit=${runLimit}`, {signal: controller.signal});
        if (controller.signal.aborted) return;
        setRecentRuns(result.items);
        setRun(previous => result.items.find(item => item.id === previous?.id) || result.items[0] || null);
      } catch (caught) {if (!controller.signal.aborted) setError((caught as Error).message);}
      if (!controller.signal.aborted) timer = window.setTimeout(() => void poll(), 3000);
    }
    void poll();
    return () => {controller.abort(); window.clearTimeout(timer);};
  }, [record?.id, runLimit]);

  function edit(patch: Partial<LocalConversation>) {
    if (!local || !record) return;
    const keys = Object.keys(patch).sort().join(","), at = Date.now();
    if (keys !== lastEdit.current.keys || at - lastEdit.current.at > 800) undoStack.current = [...undoStack.current.slice(-49), structuredClone(local)];
    redoStack.current = []; lastEdit.current = {keys, at};
    const value = {...local, ...patch};
    if (patch.model && patch.model !== local.model) {
      const compatible = targets.filter(item => item.compatible_model_profiles.includes(patch.model!));
      const next = defaultTarget(compatible.filter(item => item.remote_profile_id === local.settings.remote_profile_id)) || defaultTarget(compatible);
      value.settings = changeGenerationModel(local.settings, next);
    }
    setLocal(value); persistDraft(record.id, value);
  }
  function undoEdit(redo = false) {
    if (!local || !record) return;
    const source = redo ? redoStack.current : undoStack.current, destination = redo ? undoStack.current : redoStack.current;
    const previous = source.pop(); if (!previous) return;
    destination.push(structuredClone(local));
    const value = {...previous, baseRevision: record.revision}; setLocal(value); persistDraft(record.id, value);
    lastEdit.current = {keys: "", at: 0}; setUndoEpoch(value => value + 1);
  }
  function clearWorkspaceLink() {
    setSearchParams(previous => {const next = new URLSearchParams(previous); next.delete("workspace"); return next;}, {replace: true});
  }
  function layer<K extends LayerName>(name: K, patch: Partial<RequirementLayers[K]>) {
    if (local) edit({requirements: {...local.requirements, layers: {...local.requirements.layers,
      [name]: {...local.requirements.layers[name], ...patch}}}});
  }
  async function act(label: string, action: () => Promise<void>) {
    if (requestLock.current) return;
    requestLock.current = true; setBusy(label); setError(""); setNotice("");
    try {await action();}
    catch (caught) {
      if (!mounted.current) return;
      if ((caught as Error).name === "AbortError") {setNotice("已取消本次整理，当前版本与输入均保留。"); return;}
      setError((caught as Error).message);
      if (caught instanceof ApiClientError && caught.code === "workspace_revision_conflict" && current.current) {
        setConflict(true);
        setConflictChoices({}); setProposal(null);
        try {adopt(await apiRequest<ConversationRecord>(`/api/v3/workspaces/${current.current.id}`), true);} catch { /* Keep local edits. */ }
      }
    } finally {requestLock.current = false; if (mounted.current) setBusy("");}
  }
  async function create(initialIdea = "") {
    await act("创建工作台", async () => {
      const next = await apiRequest<ConversationRecord>("/api/v3/workspaces", {method: "POST", body: JSON.stringify({
        title: initialIdea.trim().slice(0, 40) || `新创作 ${new Date().toLocaleString()}`, draft: {model_profile: profiles.find(p => p.id === "anima_aesthetic_v1_1")?.id || profiles[0].id, generation_settings: defaultGenerationSettings()}})});
      adopt(next); write(ACTIVE, next.id); setWorkspaces(items => [next, ...items]); setPending(null); setRun(null); setRecentRuns([]);
      if (requestedWorkspace) clearWorkspaceLink();
      if (initialIdea.trim()) {
        const value = {...localFrom(next), delta: initialIdea};
        setLocal(value); persistDraft(next.id, value, localFrom(next));
        if (!llmUnavailableReason) await requestProposal(next, value, false);
        else setNotice(`想法已保留。${llmUnavailableReason}；配置就绪后点击更新提示词。`);
      }
      setInspectorTab("prompt");
    });
  }
  async function continueRun(source: GenerationRunRecord) {
    if (draftAtRisk) return;
    await act("从生成记录创建会话", async () => {
      const origin = `run:${source.id}` as const;
      const workspaceId = record?.id || source.id;
      const request = recoverConversationBranch(workspaceId, origin) || {key: crypto.randomUUID(), body: JSON.stringify({})};
      saveConversationBranch(workspaceId, origin, request);
      const next = await apiRequest<ConversationRecord>(`/api/v3/generation-runs/${encodeURIComponent(source.id)}/workspace`, {method: "POST", body: request.body, headers: {"Idempotency-Key": request.key}});
      clearConversationBranch(workspaceId, origin, request);
      adopt(next); write(ACTIVE, next.id); setWorkspaces(items => [next, ...items]);
      setPending(null); setRun(source); setRecentRuns([source]); setAvailability(null); setProposal(null); setInspectorTab("prompt");
      if (requestedWorkspace) clearWorkspaceLink();
    });
  }
  async function save(tentativeMode = false): Promise<ConversationRecord> {
    if (!record || !local) throw new Error("请先打开工作台。");
    const next = await apiRequest<ConversationRecord>(`/api/v3/workspaces/${record.id}`, {method: "PUT", body: JSON.stringify({
      revision: record.revision, title: record.title, draft: {model_profile: local.model, mode: tentativeMode ? record.draft.mode : local.mode,
        requirements_edit: cleanRequirements(local.requirements), generation_settings: local.settings,
        ...(local.positive.trim() && (local.positive !== (record.draft.compiled?.positive || "") || local.negative !== (record.draft.compiled?.negative || "")) ? {prompt_edit: {positive: local.positive, negative: local.negative}} : {})}})});
    adopt(next, true);
    base.current = localFrom(next);
    const kept = {...local, requirements: editableRequirements(next), baseRevision: next.revision}; setLocal(kept); persistDraft(next.id, kept, base.current);
    return next;
  }
  async function requestProposal(saved: ConversationRecord, value: LocalConversation, recompile: boolean, task: "rewrite" | "sync_requirements" = "rewrite") {
    setRetryTurn(false); setRetryTask(task);
    const controller = new AbortController(); turnController.current = controller;
    try {
      const next = await apiRequest<ConversationProposal>("/api/v3/workbench/turns", {method: "POST", signal: controller.signal, body: JSON.stringify({
        workspace_id: saved.id, revision: saved.revision, mode: task === "sync_requirements" ? saved.draft.mode : value.mode, preview: true,
        ...(task === "sync_requirements" ? {task} : {}), delta: {text: recompile ? "" : value.delta},
        ...(value.positive.trim() ? {compiled: {positive: value.positive, negative: value.negative}} : {})})});
      if (!mounted.current || controller.signal.aborted || current.current?.id !== saved.id) return;
      if (next.unchanged) {setNotice([next.message || "本次未改变内容，当前版本保持不变。", ...(next.warnings || [])].join("\n")); setProposal(null);}
      else {setProposal(next); setNotice("修改已整理，请检查差异后采用。");}
      setInspectorTab("prompt");
    } catch (caught) {
      if (!controller.signal.aborted && caught instanceof ApiClientError && ["network_error", "internal_error"].includes(caught.code)) {
        const recovery = await apiRequest<{proposal: ConversationProposal | null}>(`/api/v3/workspaces/${saved.id}/proposal`);
        if (mounted.current && current.current?.id === saved.id && recovery.proposal?.base_revision === saved.revision) {
          setProposal(recovery.proposal); setNotice("响应连接中断，已找回待确认的修改；当前版本保持不变。"); setInspectorTab("prompt"); return;
        }
      }
      if (!controller.signal.aborted) setRetryTurn(true);
      throw caught;
    } finally {if (turnController.current === controller) turnController.current = null;}
  }
  async function turn(recompile: boolean) {
    if (!record || !local || proposal || conflict || llmUnavailableReason || adviceBusy) return;
    await act("整理修改", async () => {
      const saved = hasUnsavedInputs(record, {...local, mode: record.draft.mode}) ? await save(true) : record;
      await requestProposal(saved, local, recompile);
    });
  }
  async function syncRequirements() {
    if (!record || !local || !local.positive.trim() || local.delta.trim() || proposal || conflict || llmUnavailableReason || adviceBusy) return;
    await act("同步画面要求", async () => {
      const saved = hasUnsavedInputs(record, {...local, mode: record.draft.mode}) ? await save(true) : record;
      await requestProposal(saved, local, true, "sync_requirements");
    });
  }
  async function decideProposal(accept: boolean) {
    if (!record || !proposal) return;
    await act(accept ? "采用修改" : "保留原版本", async () => {
      const result = await apiRequest<ConversationRecord>(`/api/v3/workspaces/${record.id}/proposals/${proposal.id}${accept ? "/accept" : ""}`, {method: accept ? "POST" : "DELETE", body: JSON.stringify({revision: record.revision})});
      if (accept) adopt(result);
      setProposal(null); setNotice(accept ? "修改已采用并保存，可在版本历史恢复。" : "已保留原版本，修改意见仍在输入框中。");
    });
  }
  async function restoreVersion(revision: number) {
    if (!record || dirty || local?.delta.trim() || proposal || pending) return;
    await act("恢复版本", async () => {
      adopt(await apiRequest<ConversationRecord>(`/api/v3/workspaces/${record.id}/restore`, {method: "POST", body: JSON.stringify({revision: record.revision, source_revision: revision})}));
      setNotice(`已恢复版本 ${revision} 的内容，并保存为新版本。`);
    });
  }
  async function forkVersion(revision: number) {
    if (!record || dirty || local?.delta.trim() || proposal || pending || conflict) return;
    await act("从历史版本另开会话", async () => {
      const source = `version:${revision}` as const;
      const request = recoverConversationBranch(record.id, source) || {key: crypto.randomUUID(), body: JSON.stringify({})};
      saveConversationBranch(record.id, source, request);
      const next = await apiRequest<ConversationRecord>(`/api/v3/workspaces/${record.id}/versions/${revision}/fork`, {method: "POST", body: request.body, headers: {"Idempotency-Key": request.key}});
      clearConversationBranch(record.id, source, request);
      adopt(next); write(ACTIVE, next.id); setWorkspaces(items => [next, ...items]);
      setRun(null); setRecentRuns([]); setProposal(null); setAvailability(null); setInspectorTab("prompt");
      if (requestedWorkspace) clearWorkspaceLink();
      setNotice(`已从版本 ${revision} 另开会话，原会话保留完整历史。`);
    });
  }
  function startNew() {
    if (draftAtRisk) return;
    draftPersistenceBlocked.current = null; setInvalidDraftRaw(""); setStorageWarning(""); setPendingRecoveryBlocked(false);
    current.current = null; base.current = null; setRecord(null); setLocal(null); setProposal(null);
    setConflict(false); setPending(null); setNotice(""); setError(""); setIdea(""); remove(ACTIVE);
    if (requestedWorkspace) clearWorkspaceLink();
  }
  async function searchSessions(query = sessionSearch, archive = archived, append = false) {
    await act("查找会话", async () => {
      const result = await apiRequest<WorkspaceListResponse>(`/api/v3/workspaces?limit=50&offset=${append ? workspaces.length : 0}&q=${encodeURIComponent(query)}&archived=${archive}`);
      setWorkspaces(items => append ? [...items, ...result.items] : result.items); setMoreSessions(result.items.length === 50);
    });
  }
  async function renameSession() {
    if (!record || !local || !rename?.trim()) return;
    await act("重命名会话", async () => {
      const next = await apiRequest<ConversationRecord>(`/api/v3/workspaces/${record.id}`, {method: "PUT", body: JSON.stringify({revision: record.revision, title: rename.trim(), draft: {}})});
      adopt(next, true); base.current = localFrom(next);
      const kept = {...local, baseRevision: next.revision}; setLocal(kept); persistDraft(next.id, kept, base.current); setRename(null);
    });
  }
  async function archiveSession() {
    if (!record || dirty || local?.delta.trim() || proposal || pending) return;
    await act("归档会话", async () => {
      await apiRequest(`/api/v3/workspaces/${record.id}`, {method: "DELETE", body: JSON.stringify({revision: record.revision})});
      setWorkspaces(items => items.filter(item => item.id !== record.id)); startNew(); setNotice("会话已归档，可在已归档会话中恢复。");
    });
  }
  async function branchLocalDraft() {
    if (!record || !local) return;
    await act("另存本窗口草稿", async () => {
      const request = recoverConversationBranch(record.id, "draft") || {key: crypto.randomUUID(), body: JSON.stringify({title: `${record.title} · 本窗口草稿`, draft: {
        model_profile: local.model, mode: local.mode, requirements_edit: cleanRequirements(local.requirements), generation_settings: local.settings,
        ...(local.positive.trim() ? {prompt_edit: {positive: local.positive, negative: local.negative}} : {})}})};
      saveConversationBranch(record.id, "draft", request);
      const next = await apiRequest<ConversationRecord>("/api/v3/workspaces", {method: "POST", body: request.body, headers: {"Idempotency-Key": request.key}});
      clearConversationBranch(record.id, "draft", request);
      const kept = {...local, baseRevision: next.revision}; adopt(next); setLocal(kept); persistDraft(next.id, kept, localFrom(next));
      write(ACTIVE, next.id); setWorkspaces(items => [next, ...items]); setRun(null); setRecentRuns([]); setProposal(null); setAvailability(null);
      if (requestedWorkspace) clearWorkspaceLink();
      setNotice("本窗口内容已另存为新会话，原会话的服务端版本保持不变。");
    });
  }
  async function unarchiveSession(id: string) {
    const item = workspaces.find(value => value.id === id); if (!item) return;
    await act("恢复会话", async () => {
      const restored = await apiRequest<ConversationRecord>(`/api/v3/workspaces/${id}/unarchive`, {method: "POST", body: JSON.stringify({revision: item.revision})});
      await open(restored.id); setArchived(false); setSessionSearch("");
      const result = await apiRequest<WorkspaceListResponse>("/api/v3/workspaces?limit=50"); setWorkspaces(result.items);
    });
  }
  async function reuseRunSettings(source: GenerationRunRecord, selectedAsset?: GalleryAsset) {
    if (!local) return;
    await act("读取图片参数", async () => {
      const artifacts = await apiRequest<{items: {path: string | null; removed: boolean}[]}>(`/api/v3/generation-runs/${source.id}/artifacts`);
      const gallery = await loadGallery();
      const asset = selectedAsset || gallery.items.find(item => artifacts.items.some(image => !image.removed && image.path === item.path));
      const rawSeed = asset?.generation_params?.seed ?? source.source?.settings.seed;
      const seed = typeof rawSeed === "number" || typeof rawSeed === "string" ? seedInput(String(rawSeed)) : -1;
      if (!validSeed(seed, false)) throw new Error("这批图片没有可读取的实际种子，请展开图片信息核对后手动填写。");
      if (source.source?.model_profile && source.source.model_profile !== local.model) throw new Error("这批图片使用了不同模型，请先沿用本次条件创建会话，再进行同条件比较。");
      const saved = source.source?.settings || {};
      const parameters = Object.fromEntries((["width", "height", "steps", "cfg", "sampler", "scheduler"] as const).filter(key => saved[key] !== undefined).map(key => [key, saved[key]]));
      edit({settings: markGenerationCustom(local.settings, {...parameters, aspect: "custom", seed, batch_size: 1})});
      setNotice("已带入保存的种子与采样参数。多图批次的种子记录不保证对应选中的单张图片；比较时请核对图片信息，并保持其他条件一致。");
    });
  }
  async function generate(retry = false) {
    if (!record || !local) return;
    await act("提交生成", async () => {
      const request = retry && pending ? pending : {key: crypto.randomUUID(), body: JSON.stringify({
        submission_kind: "conversational", workspace_id: record.id, workspace_revision: record.revision,
        compiled_token: record.draft.compiled?.compiled_token, positive_prompt: local.positive, negative_prompt: local.negative,
        model_profile: local.model, remote_profile_id: target?.remote_profile_id, workflow_profile_id: target?.workflow_profile_id,
        ...(record.draft.generation_source ? {workflow_snapshot_run_id: record.draft.generation_source.run_id} : {}),
        settings: resolvedGenerationSettings(local.settings)})};
      saveConversationPending(record.id, request);
      setPending(request);
      let accepted: Accepted;
      try {accepted = await apiRequest<Accepted>("/api/v3/direct-prompt/runs", {method: "POST", body: request.body,
        headers: {"Idempotency-Key": request.key}});}
      catch (caught) {
        // A failed query of an earlier submission cannot prove that its original
        // attempt was rejected. Keep its frozen body/key until acceptance is known.
        // For a brand-new key only explicit pre-acceptance validation failures
        // establish rejection; generic errors and idempotency conflicts do not.
        const rejectedBeforeAcceptance = ["invalid_request", "remote_not_configured", "v2_runtime_missing", "submission_store_missing",
          "workspace_revision_conflict", "workspace_not_found", "stale_compiled_prompt", "rate_limited", "session_invalid",
          "incompatible_workflow", "incompatible_model", "workflow_snapshot_missing", "reference_preset_unavailable",
          "mapping_revision_conflict", "missing_lora", "lora_unmapped", "unknown"];
        if (!retry && caught instanceof ApiClientError && rejectedBeforeAcceptance.includes(caught.code)) {
          clearConversationPending(record.id, request); setPending(null);
        }
        throw caught;
      }
      clearConversationPending(record.id, request); setPending(null); setRun(accepted);
      setRecentRuns(items => [accepted, ...items.filter(item => item.id !== accepted.id)]);
      resultsPanel.current?.scrollIntoView?.({block: "start", behavior: "smooth"});
      const submitted = JSON.parse(request.body) as {positive_prompt: string; negative_prompt: string};
      // Retain the new token even if the following read fails.
      const next = {...record, revision: accepted.workspace_revision, draft: {...record.draft,
        compiled: {...record.draft.compiled!, positive: submitted.positive_prompt, negative: submitted.negative_prompt, compiled_token: accepted.compiled_token}}};
      adopt(next);
      adopt(await apiRequest<ConversationRecord>(`/api/v3/workspaces/${record.id}`));
    });
  }

  const promptChanged = Boolean(local && (local.positive !== (record?.draft.compiled?.positive || "") || local.negative !== (record?.draft.compiled?.negative || "")));
  const generationReason = busy ? `${busy}…` : pendingRecoveryBlocked ? "请先核对上次生成请求的恢复记录" : pending ? "请先确认上次提交的结果" : proposal ? "请先采用或不采用待确认的修改" : conflict ? "请先处理版本冲突"
    : local?.model === LEGACY_AESTHETIC ? "旧美学配置版本不明，请在生成设置中选择 v1.0 或 v1.1"
    : local?.delta.trim() ? "有未发送的修改，先整理或清空输入" : inputsDirty ? (compileInputsChanged ? "要求已修改，更新提示词后再生成" : "要求或生成设置尚未保存；保存后即可生成，无需重新整理")
    : record?.draft.compile_state !== "fresh" ? "请先生成或重新编译提示词" : !local?.positive.trim() ? "请填写正向提示词"
    : !remoteEnabled ? "连接生图服务后即可生成" : !target ? (record?.draft.generation_source ? "原任务的执行目标当前不可用；可恢复该环境，或解除快照后选择其他目标" : "在生成设置中选择服务器与工作流")
    : availability?.availability !== "ready" ? availability?.message || "正在检查目标与资源…" : "";
  const tabs = [{id: "prompt", label: "提示词"}, {id: "requirements", label: "画面要求"}, {id: "settings", label: "生成设置"}] as const;
  async function copyPrompt(kind: "positive" | "negative") {
    try {await navigator.clipboard.writeText(local?.[kind] || ""); setCopied(kind);}
    catch {setError("复制失败，请选中提示词后手动复制。");}
  }
  const merge = conflict && base.current && local && record ? mergeConversation(base.current, local, localFrom(record)) : null;
  function resolveConflict() {
    if (!merge || !record || merge.conflicts.some(item => !conflictChoices[item.path])) return;
    const value = resolveConversationConflicts(merge, conflictChoices); base.current = localFrom(record);
    undoStack.current = []; redoStack.current = []; lastEdit.current = {keys: "", at: 0};
    setLocal(value); persistDraft(record.id, value, base.current); setConflict(false); setError("");
    setNotice("不同字段已合并，请核对后保存当前版本。");
  }

  return <section className="conversation-workbench">
    <header className="conversation-heading"><div className="conversation-title"><h1>{record?.title || "开始创作"}</h1>{record && <span className="conversation-save-state">{storageWarning ? "草稿保存需注意" : dirty || local?.delta.trim() ? "本窗口草稿 · 尚未全部保存" : `已保存到服务端 · 版本 ${record.revision}`}</span>}</div>
      <div className="conversation-actions conversation-toolbar">
        <button aria-expanded={showLlmSettings} aria-controls="conversation-llm-settings" disabled={Boolean(busy || adviceBusy || thinking.saving || llmSettingsBusy)} onClick={() => setShowLlmSettings(value => !value)}><GearSix size={17} aria-hidden="true" />LLM 设置</button>
        <button className="conversation-new" disabled={Boolean(busy || pending || draftAtRisk)} onClick={startNew}><Plus size={16} aria-hidden="true" />新会话</button>
      </div></header>
    <div className="conversation-session-bar"><div className="conversation-session-select"><ChatCircleDots size={19} aria-hidden="true" /><select aria-label={archived ? "恢复已归档会话" : "打开已有会话"} value={archived ? "" : record?.id || ""} disabled={Boolean(busy || pending || draftAtRisk)} onChange={event => {if (event.target.value) void (archived ? unarchiveSession(event.target.value) : open(event.target.value));}}>
        <option value="">{archived ? "选择会话并恢复" : "选择工作台"}</option>{record && !archived && !workspaces.some(item => item.id === record.id) && <option value={record.id}>{record.title}</option>}{workspaces.map(item => <option key={item.id} value={item.id}>{item.title} · {new Date(item.updated_at).toLocaleDateString()}</option>)}</select>
      </div><span className="conversation-session-note">修改意见自动保留在本窗口；保存当前版本会保存提示词、要求与生成设置。</span></div>
    <details className="conversation-session-tools"><summary>查找与管理会话</summary><div className="conversation-actions">
      <input aria-label="搜索会话" value={sessionSearch} onChange={event => setSessionSearch(event.target.value)} onKeyDown={event => {if (event.key === "Enter") void searchSessions();}} placeholder="按会话名称搜索" />
      <button disabled={Boolean(busy)} onClick={() => void searchSessions()}>搜索</button>
      <label><input type="checkbox" checked={archived} disabled={Boolean(busy)} onChange={event => {setArchived(event.target.checked); void searchSessions(sessionSearch, event.target.checked);}} />已归档会话</label>
      {moreSessions && <button disabled={Boolean(busy)} onClick={() => void searchSessions(sessionSearch, archived, true)}>加载更多会话</button>}
      {record && <><button disabled={Boolean(busy || pending || proposal || conflict)} onClick={() => setRename(record.title)}>重命名当前会话</button><button disabled={Boolean(busy || pending || proposal || dirty || conflict || local?.delta.trim())} onClick={() => void archiveSession()}>归档当前会话</button></>}
    </div>{rename !== null && <div className="conversation-actions"><input aria-label="会话名称" maxLength={200} value={rename} onChange={event => setRename(event.target.value)} /><button disabled={Boolean(busy) || !rename.trim()} onClick={() => void renameSession()}>保存名称</button><button onClick={() => setRename(null)}>取消改名</button></div>}</details>
    {record && local && <ConversationDraftRecovery key={record.id} workspaceId={record.id}
      disabled={Boolean(busy || pending || proposal || pendingRecoveryBlocked)} onRestore={restoreLocalDraft} />}
    {showLlmSettings && <div id="conversation-llm-settings"><LlmSettingsPanel disabled={Boolean(busy || pending || adviceBusy || thinking.loading || thinking.saving)}
      onSaved={thinking.refresh} onBusyChange={setLlmSettingsBusy} /></div>}
    {error && <div role="alert" className="conversation-error">{error}{retryTurn && record && local && <p>当前内容已保留。<button disabled={Boolean(busy || proposal || conflict || llmUnavailableReason)} onClick={() => void (retryTask === "sync_requirements" ? syncRequirements() : turn(!local.delta.trim()))}>重试整理</button><button onClick={() => setShowLlmSettings(true)}>检查模型设置</button></p>}</div>}
    {storageWarning && <div role="alert" className="conversation-warning">{storageWarning}{invalidDraftRaw && <button onClick={() => {
      const url = URL.createObjectURL(new Blob([invalidDraftRaw], {type: "application/json"}));
      const link = document.createElement("a"); link.href = url; link.download = `anima-draft-recovery-${record?.id || "unknown"}.json`; link.click(); URL.revokeObjectURL(url);
    }}>导出原始草稿</button>}{draftPersistenceBlocked.current === record?.id && <p>原草稿未被覆盖。请先导出；当前编辑可直接保存到服务端，浏览器恢复仍不可用。</p>}</div>}
    {notice && <p role="status" className="conversation-notice">{notice}</p>}
    {busy && <div className="conversation-wait"><p role="status">{busy}… 已等待 {elapsed} 秒{turnController.current ? "；模型正在整理，返回后可先检查再采用。" : ""}</p>{turnController.current && <button onClick={() => turnController.current?.abort()}>取消整理</button>}</div>}
    {requestedTransfer && error && <button disabled={Boolean(busy)} onClick={() => {transferAttempt.current = ""; setInitialLoaded(false); setTransferRetry(value => value + 1);}}>重试带入</button>}
    {record && local && transferNotice?.workspace === record.id && <p role="status">{transferNotice.added.length ? `已加入 ${transferNotice.added.length} 个标签，原有草稿已保留。` : "所选标签已在当前要求中，没有重复添加。"}
      {transferNotice.added.length > 0 && <button disabled={Boolean(busy || pending || conflict)} onClick={() => {
        edit({requirements: undoSelectedContent(local.requirements, transferNotice.added)}); setTransferNotice(null);
      }}>撤销本次带入</button>}</p>}
    {!local || !record ? <section className="conversation-empty"><Sparkle size={30} aria-hidden="true" /><h2>这次，想画些什么？</h2><p>人物、动作、场景或一种氛围，从你最在意的部分开始。</p>
      <label htmlFor="conversation-idea" className="conversation-sr-only">创作想法</label><textarea id="conversation-idea" rows={4} value={idea} maxLength={4000} onChange={event => setIdea(event.target.value)} placeholder="例如：栗色长发的女孩坐在窗边，双手捧着咖啡杯，窗外樱花盛开。" />
      <div className="conversation-starters">{[{title: "日常人物", text: "栗色长发的女孩坐在窗边，双手捧着咖啡杯，清透赛璐璐风格。"}, {title: "幻想场景", text: "身穿白金盔甲的骑士站在空中花园，披着蓝色披风，远处是浮空城堡。"}, {title: "水彩插画", text: "戴尖帽的魔女双手捧着小白花，站在有蕨类和萤火虫的森林，透明水彩风格。"}].map(item => <button key={item.title} disabled={Boolean(busy)} onClick={() => setIdea(item.text)}>{item.title}</button>)}</div>
      <button className="conversation-primary" onClick={() => void create(idea)} disabled={Boolean(busy || thinking.loading) || !idea.trim()}>开始整理想法 <PaperPlaneRight size={17} aria-hidden="true" /></button>
      <p className="conversation-empty-note">先检查提示词变化并采用，再由你决定何时生成图片。</p></section> : <>
      {conflict && <section role="alert" className="conversation-conflict"><strong>其他窗口已保存了更新，你的编辑仍在这里。</strong>
        {merge ? <><p>不同字段的修改会一起保留；同一字段有分歧时，请逐项选择。</p>
          {merge.conflicts.map(item => <fieldset key={item.path}><legend>{item.label}</legend>
            <label><input type="radio" name={`conflict-${item.path}`} checked={conflictChoices[item.path] === "local"} onChange={() => setConflictChoices(value => ({...value, [item.path]: "local"}))} />保留本窗口：<pre>{typeof item.local === "string" ? item.local : JSON.stringify(item.local)}</pre></label>
            <label><input type="radio" name={`conflict-${item.path}`} checked={conflictChoices[item.path] === "remote"} onChange={() => setConflictChoices(value => ({...value, [item.path]: "remote"}))} />采用服务端：<pre>{typeof item.remote === "string" ? item.remote : JSON.stringify(item.remote)}</pre></label>
          </fieldset>)}<button disabled={merge.conflicts.some(item => !conflictChoices[item.path])} onClick={resolveConflict}>{merge.conflicts.length ? "应用所选合并结果" : "合并双方修改"}</button></>
          : <p>这份旧草稿缺少共同版本，无法安全自动合并。可将本窗口内容另存为新会话，原会话的更新会完整保留。</p>}
        <button disabled={Boolean(busy)} onClick={() => void branchLocalDraft()}>将本窗口草稿另存为新会话</button>
        <button onClick={() => {adopt(record); setError("");}}>采用服务端版本</button></section>}
      {pending && !busy && <section className="conversation-conflict"><p>上次生成请求的接受结果尚未确认。请先查询原请求。</p><button onClick={() => void generate(true)}>查询本次提交</button></section>}
      <ol className="conversation-flow" aria-label="当前创作状态">
        <li><strong>1 · 画面要求</strong><span>{local.delta.trim() ? "有待整理的新想法" : compileInputsChanged ? "要求或模型已修改" : !record.draft.requirements ? "等待描述画面" : "当前要求已保存"}</span></li>
        <li><strong>2 · 提示词</strong><span>{local.delta.trim() ? "等待应用新想法" : needsCompile ? "需要更新后再生成" : promptChanged ? "将使用你手动修改的文字" : "已就绪，可继续调整"}</span></li>
        <li><strong>3 · 生成条件</strong><span>{dirty && !compileInputsChanged ? "参数待保存，无需重新编译" : target ? `${local.settings.width} × ${local.settings.height} · ${local.settings.batch_size} 张` : "尚未选择执行目标"}</span></li>
      </ol>
      {proposal && <ConversationReview proposal={proposal} before={local} disabled={Boolean(busy)} acceptBlocked={Boolean(conflict || proposal.base_revision !== record.revision || hasUnsavedInputs(record, {...local, mode: record.draft.mode}))} onAccept={() => void decideProposal(true)} onDiscard={() => void decideProposal(false)} />}
      <fieldset disabled={Boolean(busy || pending || proposal || conflict)} className="conversation-layout">
        <section className="conversation-editor" aria-label="创作编辑区" data-appearance-anchor="editor">
          <div className="conversation-edit-top">
          <div className="conversation-composer"><label htmlFor="conversation-delta">{record.draft.requirements ? "继续追加要求" : "描述你想画的内容"}</label>
            <textarea id="conversation-delta" rows={2} maxLength={4000} value={local.delta} onChange={event => edit({delta: event.target.value})} placeholder="描述人物、动作、场景，或这次希望改变的地方" />
            <div className="conversation-actions"><label>改写方式<select value={local.mode} onChange={event => edit({mode: event.target.value as LocalConversation["mode"]})}><option value="faithful">忠实还原</option><option value="expand">适度扩写</option></select></label>
              <Link to="/references">从参考借用</Link>
              </div>
              <div className="conversation-thinking-control">
                <button type="button" role="switch" aria-label="深度思考" aria-checked={thinking.enabled} aria-describedby="conversation-thinking-status"
                  disabled={Boolean(busy || pending || adviceBusy || llmSettingsBusy || thinking.loading || thinking.saving || !thinking.current?.service || !thinking.current.model)}
                  onClick={() => void thinking.toggle()}>
                  <span aria-hidden="true" className="conversation-thinking-indicator" />
                  深度思考：{thinking.saving ? "保存中…" : thinking.loading ? "读取中…" : !thinking.current ? "状态未读取"
                    : thinking.mode === "unverified" ? `${thinking.enabled ? "开" : "关"}（待确认）` : thinking.enabled ? "开" : thinking.mode === "required" ? "关（需开启）" : "关"}
                </button>
                {thinking.current && <span className="conversation-thinking-model" title={thinking.current.model}>{thinking.current.model || "尚未选择模型"}</span>}
              </div>
            <div id="conversation-thinking-status" className="conversation-thinking-status">
              <span>{llmUnavailableReason || (thinking.mode === "unverified" ? `思考开关尚未验证。${thinking.message}` : thinking.mode === "required" ? thinking.message : "用于更新提示词和给我建议；开启后可能需要更久。")}</span>
              {thinking.error && <span role="alert">{thinking.error}</span>}
              {!thinking.current && !thinking.loading && <button type="button" onClick={() => void thinking.refresh()}>重新读取配置</button>}
            </div>
              <p className="conversation-muted">按文字要求整理提示词，不会查看生成图片。要回到旧内容，请使用版本历史。</p>
              <div className="conversation-text-actions"><button className="conversation-update" disabled={Boolean(llmUnavailableReason || adviceBusy) || conflict || (!canCompileRequirements && !local.delta.trim()) || (!needsCompile && !local.delta.trim())} onClick={() => void turn(!local.delta.trim())}><PaperPlaneRight size={16} aria-hidden="true" />更新提示词</button>
                <button disabled={!dirty || conflict || Boolean(promptChanged && !local.positive.trim())} onClick={() => void act("保存当前版本", async () => {await save(); setNotice("提示词、要求与生成设置已保存到服务端。");})}>保存当前版本</button>
                <button disabled={!undoStack.current.length} onClick={() => undoEdit()}>撤销编辑</button><button disabled={!redoStack.current.length} onClick={() => undoEdit(true)}>重做编辑</button>
                {local.delta && <button onClick={() => edit({delta: ""})}>清空修改意见</button>}
              </div>{llmUnavailableReason && <p className="conversation-warning">{llmUnavailableReason}</p>}
            </div>
          <details className="conversation-supporting-controls"><summary>角色、画师与画面设计</summary>
          <ManualIdentityTags key={record.id} compact modelProfileId={local.model} characters={local.requirements.layers.subject.character_tags || []} series={local.requirements.layers.subject.series_tags || []}
            artists={local.requirements.layers.style.manual_artist_tags || []} onCharacters={character_tags => layer("subject", {character_tags})}
            onSeries={series_tags => layer("subject", {series_tags})} onArtists={manual_artist_tags => layer("style", {manual_artist_tags})} />
            <SceneDesignControls requirements={local.requirements} onChange={requirements => edit({requirements})}
              workspaceId={record.id} workspaceRevision={record.revision} delta={local.delta}
              positive={local.positive} negative={local.negative} disabled={Boolean(busy || pending || conflict)}
              adviceDisabledReason={llmUnavailableReason} llmContextKey={llmContextKey} onBusyChange={setAdviceBusy} />
          </details>
          </div>
          <div className="conversation-inspector">
            <div className="conversation-tabs" role="tablist" aria-label="画面工作区">{tabs.map((item, index) => <button key={item.id} id={`tab-${item.id}`} role="tab" aria-selected={inspectorTab === item.id} aria-controls={`panel-${item.id}`} tabIndex={inspectorTab === item.id ? 0 : -1} onClick={() => setInspectorTab(item.id)} onKeyDown={event => {
              const next = event.key === "ArrowRight" ? (index + 1) % tabs.length : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
              if (next !== null) {event.preventDefault(); setInspectorTab(tabs[next].id); document.getElementById(`tab-${tabs[next].id}`)?.focus();}
            }}>{item.label}</button>)}</div>
          <div id="panel-prompt" role="tabpanel" aria-labelledby="tab-prompt" hidden={inspectorTab === "requirements"} className="conversation-tab-panel">
          <div className="conversation-field-heading"><label htmlFor="conversation-positive">正向提示词</label><button className="conversation-copy" aria-label="复制正向提示词" disabled={!local.positive} onClick={() => void copyPrompt("positive")}>{copied === "positive" ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}复制</button></div>
          <textarea id="conversation-positive" className="conversation-prompt" rows={7} maxLength={20000} value={local.positive} placeholder="生成后的英文提示词会显示在这里，也可以直接编辑。" onChange={event => {setCopied(""); edit({positive: event.target.value});}} />
          <details className="conversation-negative"><summary>负向提示词 <span>{local.negative.trim() ? "已填写" : "未使用"}</span></summary>
          <div className="conversation-field-heading"><label htmlFor="conversation-negative">负向提示词</label><button className="conversation-copy" aria-label="复制负向提示词" disabled={!local.negative} onClick={() => void copyPrompt("negative")}>{copied === "negative" ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}复制</button></div>
          <textarea id="conversation-negative" className="conversation-prompt" rows={2} maxLength={20000} value={local.negative} placeholder="需要避免的画面内容" onChange={event => {setCopied(""); edit({negative: event.target.value});}} />
          <p className="conversation-muted">{negativeGuidance(local.model).note} <a href={negativeGuidance(local.model).source || "https://huggingface.co/circlestone-labs/Anima"} target="_blank" rel="noreferrer">模型作者说明</a></p>
          {negativeGuidance(local.model).text && <button onClick={() => edit({negative: appendNegative(local.negative, negativeGuidance(local.model).text)})}>补充模型负向建议</button>}
          </details>
          <p className="conversation-muted">正负提示词可直接修改，点击“保存当前版本”即可保存；点击生成也会保存使用的提示词。</p>
          {(promptChanged || record.draft.compiled?.source === "user" && !record.draft.compiled.requirements_synced) && <div className="conversation-warning"><p>正在使用手工提示词，中文画面要求不会自动同步。可按当前提示词整理中文要求，再检查候选差异；英文原文会保留。</p>
            <button disabled={Boolean(llmUnavailableReason || adviceBusy || local.delta.trim() || !local.positive.trim())} onClick={() => void syncRequirements()}>按手工提示词同步画面要求</button>
            {local.delta.trim() && <p>请先整理或清空未发送的修改意见。</p>}</div>}
          <PromptLocks key={record.id} positive={local.positive} negative={local.negative} locks={local.requirements.prompt_locks || []}
            onChange={prompt_locks => edit({requirements: {...local.requirements, prompt_locks}})} />
          <span role="status" className="conversation-sr-only">{copied ? "提示词已复制" : ""}</span></div>
          <div id="panel-requirements" role="tabpanel" aria-labelledby="tab-requirements" hidden={inspectorTab !== "requirements"} className="conversation-tab-panel">

          <div aria-label="明确选择的普通标签"><strong>已选普通标签 · {(local.requirements.layers.subject.general_tags || []).length} / 64</strong>
            {(local.requirements.layers.subject.general_tags || []).map(tag => <span key={tag}> {tag} <button aria-label={`移除普通标签 ${tag}`} onClick={() => layer("subject", {general_tags: local.requirements.layers.subject.general_tags!.filter(value => value !== tag)})}>移除</button></span>)}
          </div>
          <p className="conversation-muted">这里锁定整组中文要求。只想保留人物特征，同时修改服装或动作时，可在提示词页固定相应英文片段。已锁定 {Object.values(local.requirements.layers).filter(item => item.locked).length} 组。</p>
            {(Object.keys(layerLabels) as LayerName[]).map(name => <div className="conversation-layer" key={name}><div className="conversation-actions"><strong>{layerLabels[name]}</strong><label><input type="checkbox" aria-label={`锁定${layerLabels[name]}要求`} checked={local.requirements.layers[name].locked} onChange={event => layer(name, {locked: event.target.checked})} />锁定改写</label></div>
              {name !== "exclusions" ? <textarea aria-label={`${layerLabels[name]}要求`} rows={2} value={local.requirements.layers[name].text} onChange={event => layer(name, {text: event.target.value})} /> : <>
                <label>全局排除（每行一项）<textarea value={local.requirements.layers.exclusions.global.join("\n")} onChange={event => layer("exclusions", {global: event.target.value.split("\n")})} /></label>
                {local.requirements.layers.exclusions.scoped.map((item, i) => <div className="conversation-actions" key={i}><input aria-label={`排除对象 ${i + 1}`} value={item.target} onChange={event => layer("exclusions", {scoped: local.requirements.layers.exclusions.scoped.map((entry, index) => index === i ? {...entry, target: event.target.value} : entry)})} /><input aria-label={`排除内容 ${i + 1}`} value={item.concept} onChange={event => layer("exclusions", {scoped: local.requirements.layers.exclusions.scoped.map((entry, index) => index === i ? {...entry, concept: event.target.value} : entry)})} /><button onClick={() => layer("exclusions", {scoped: local.requirements.layers.exclusions.scoped.filter((_, index) => index !== i)})}>移除</button></div>)}
                <button onClick={() => layer("exclusions", {scoped: [...local.requirements.layers.exclusions.scoped, {target: "", concept: ""}]})}>添加局部排除</button></>}
              {name === "style" && <label>媒介<input value={local.requirements.layers.style.medium} onChange={event => layer("style", {medium: event.target.value})} /></label>}
              {name === "composition" && <label>景别<input value={local.requirements.layers.composition.shot} onChange={event => layer("composition", {shot: event.target.value})} /></label>}
            </div>)}
          </div>
            <div className="conversation-update-row">
              <span>{local.delta.trim() ? "有待整理的修改" : needsCompile ? "要求已改变" : "可直接编辑提示词"}</span>
            </div>
          </div>
          {record.draft.workspace_origin && <p className="conversation-muted">分支来自版本 {record.draft.workspace_origin.revision} ·
            <button disabled={Boolean(busy || pending || proposal || draftAtRisk)} onClick={() => void open(record.draft.workspace_origin!.workspace_id)}>打开来源会话</button></p>}
          <ConversationVersions key={record.id} record={record} disabled={Boolean(busy || dirty || pending || proposal || conflict || local.delta.trim())} onRestore={revision => void restoreVersion(revision)} onFork={revision => void forkVersion(revision)} />
        </section>
      <section ref={resultsPanel} className="conversation-results" aria-label="本会话的生成结果" data-appearance-anchor="results">
        <header><div><h2>生成结果</h2></div><Link to="/generate">全部任务</Link></header>
        {record.draft.generation_source && <SourceRunPreview key={record.draft.generation_source.run_id} runId={record.draft.generation_source.run_id} />}
        {recentRuns.length ? <><label>查看生成批次<select disabled={Boolean(busy || pending)} value={run?.id || ""} onChange={event => setRun(recentRuns.find(item => item.id === event.target.value) || null)}>
          {recentRuns.map(item => <option key={item.id} value={item.id}>{item.created_at ? new Date(item.created_at).toLocaleString() : item.id.slice(0, 8)} · {item.status_message} · {item.artifact_count} 张</option>)}
        </select></label>{run && <><div className="conversation-result-heading"><p role="status">{run.status_message}</p>
          <button disabled={Boolean(busy || pending || draftAtRisk)} onClick={() => void continueRun(run)}>沿用本次条件，新建会话</button></div>
          <p className={run.source && (run.source.positive_prompt !== local.positive || run.source.negative_prompt !== local.negative) ? "conversation-warning" : "conversation-muted"}>
            {run.source ? `${run.source.workspace_revision ? `来自版本 ${run.source.workspace_revision}。` : "来自已保存的生成条件。"}${run.source.positive_prompt !== local.positive || run.source.negative_prompt !== local.negative ? "图片使用的是旧提示词，当前修改尚未体现在这张图上。" : "图片提示词与当前文字一致；参数变化需另行比较。"}` : "历史图片尚无可核对的版本信息，可展开图片信息查看原始提示词。"}
          </p><button disabled={Boolean(busy || pending)} onClick={() => void reuseRunSettings(run)}>沿用本批次参数与种子</button>
          {run.error?.message && <p role="alert">{run.error.message}</p>}
          <GenerationComparison key={record.id} workspaceId={record.id} currentRun={run} runs={recentRuns} disabled={Boolean(busy || pending)} onReuseSettings={(source, asset) => void reuseRunSettings(source, asset)} />
          <h3>本批次图片</h3><RunPreview key={run.id} run={run} showStatus={false} />
          </>}{recentRuns.length >= runLimit && runLimit < 100 && <button onClick={() => setRunLimit(value => Math.min(100, value + 20))}>加载更早批次</button>}
          {recentRuns.length >= 100 && <Link to="/gallery">更早结果请到画廊查看</Link>}</> : <div className="conversation-results-empty"><ImageSquare size={42} weight="thin" aria-hidden="true" /><h3>让画面在这里成形</h3><p>整理想法、确认提示词，再生成第一张图片。</p><Link to="/references">浏览参考案例</Link></div>}
      </section>
        <section className="conversation-conditions" aria-label="生成条件" data-appearance-anchor="conditions">
          <div className="conversation-settings-choices">

          <label>模型<select disabled={Boolean(record.draft.generation_source)} value={local.model} onChange={event => edit({model: event.target.value})}>{local.model === LEGACY_AESTHETIC && <option value={LEGACY_AESTHETIC} disabled>旧美学配置：请选择 v1.0 或 v1.1</option>}{profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.label}</option>)}</select></label>
            <label>执行目标<select disabled={Boolean(record.draft.generation_source)} value={target ? `${target.remote_profile_id}::${target.workflow_profile_id}` : ""} onChange={event => {
              const next = targets.find(item => `${item.remote_profile_id}::${item.workflow_profile_id}` === event.target.value);
              if (next) edit({settings: applyGenerationRecipe(local.settings, next, next.default_recipe_id)});
            }}><option value="">选择服务器与工作流</option>{targets.filter(item => item.compatible_model_profiles.includes(local.model)).map(item => <option key={`${item.remote_profile_id}::${item.workflow_profile_id}`} value={`${item.remote_profile_id}::${item.workflow_profile_id}`}>{targetRemoteLabel(item, targets)} / {targetLabel(item, targets)}</option>)}</select></label>
            {target && <p className="conversation-muted">{targetDescription(target)}</p>}
            <label>生成配方<select disabled={!target?.generation_recipes?.length} value={local.settings.preset_id} onChange={event => {if (target) edit({settings: applyGenerationRecipe(local.settings, target, event.target.value)});}}>
              {!target?.generation_recipes?.some(item => item.id === local.settings.preset_id) && <option value={local.settings.preset_id}>{local.settings.preset_id === "custom" ? "自定义参数" : "当前参数"}</option>}
              {target?.generation_recipes?.map(item => <option value={item.id} key={item.id}>{item.display_name}</option>)}
            </select></label>

          </div>
          <details id="panel-settings" role="tabpanel" aria-labelledby="tab-settings" className="conversation-advanced" open={inspectorTab === "settings" ? true : undefined}>
            <summary><SlidersHorizontal size={17} aria-hidden="true" />尺寸、采样与 LoRA <span>{local.settings.width} × {local.settings.height} · {local.settings.batch_size} 张</span></summary>
            <div className="conversation-settings-grid">{(["width", "height", "steps", "cfg", "seed", "batch_size"] as const).map(name => <label key={name}>{({width: "宽度", height: "高度", steps: "步数", cfg: "CFG", seed: "种子（-1 随机）", batch_size: "张数"})[name]}<input type={name === "seed" ? "text" : "number"} inputMode={name === "seed" ? "numeric" : undefined} step={name === "cfg" ? 0.1 : 1} value={local.settings[name]} onChange={event => edit({settings: markGenerationCustom(local.settings, {...(name === "width" || name === "height" ? {aspect: "custom" as const} : {}), [name]: name === "seed" ? seedInput(event.target.value) : Number(event.target.value)})})} /></label>)}
              {(["sampler", "scheduler"] as const).map(name => <label key={name}>{name === "sampler" ? "采样器" : "调度器"}<input list={`conversation-${name}-options`} value={local.settings[name]} onChange={event => edit({settings: markGenerationCustom(local.settings, {[name]: event.target.value})})} /><datalist id={`conversation-${name}-options`}>{target?.parameter_capabilities?.[name]?.options.map(value => <option key={value} value={value} />)}</datalist></label>)}
            </div>
          <details><summary>LoRA 资源 · {local.requirements.loras.length}</summary>{local.requirements.loras.map((item, i) => <div className="conversation-layer" key={i}>
            <label>资源 ID<input value={item.logical_id} onChange={event => edit({requirements: {...local.requirements, loras: local.requirements.loras.map((r, n) => n === i ? {...r, logical_id: event.target.value} : r)}})} /></label>
            <label>文件名<input value={item.file_name} onChange={event => edit({requirements: {...local.requirements, loras: local.requirements.loras.map((r, n) => n === i ? {...r, file_name: event.target.value} : r)}})} /></label>
            <label>权重<input type="number" min={-2} max={2} step={0.05} value={item.weight} onChange={event => edit({requirements: {...local.requirements, loras: local.requirements.loras.map((r, n) => n === i ? {...r, weight: Number(event.target.value)} : r)}})} /></label>
            <label>触发词（每行一项）<textarea value={item.trigger_words.join("\n")} onChange={event => edit({requirements: {...local.requirements, loras: local.requirements.loras.map((r, n) => n === i ? {...r, trigger_words: event.target.value.split("\n")} : r)}})} /></label>
            <button onClick={() => edit({requirements: {...local.requirements, loras: local.requirements.loras.filter((_, n) => n !== i)}})}>移除 LoRA</button></div>)}
            <button onClick={() => edit({requirements: {...local.requirements, loras: [...local.requirements.loras, {logical_id: `lora-${local.requirements.loras.length + 1}`, file_name: "", weight: 1, trigger_words: [], required: true, source: {kind: "user"}}]}})}>添加 LoRA</button>
          </details>

          </details>
          {dirty && !compileInputsChanged && <p className="conversation-muted">只改尺寸、种子或采样参数时，保存即可保留现有提示词。</p>}
          {!target && <div className="conversation-target-help">{record.draft.generation_source ? <Link to="/workflows">检查原执行环境</Link> : <><button onClick={() => setInspectorTab("settings")}>选择生成目标</button><Link to="/settings">管理服务器</Link></>}</div>}
          {target && Boolean(availability?.resource_requirements?.length) && <LoraMappingPanel
            key={`${target.remote_profile_id}:${target.workflow_profile_id}:${JSON.stringify(availability?.resource_requirements)}`}
            remote={target.remote_profile_id} workflow={target.workflow_profile_id} resources={availability!.resource_requirements!}
            disabled={Boolean(busy || pending || conflict || dirty)} onSaved={() => setMappingEpoch(value => value + 1)} />}
          <div className="conversation-generation-footer">
            <div className="conversation-dock-summary">
              <button type="button" className="conversation-dock-conditions" aria-label="查看生成条件" onClick={() => {setInspectorTab("settings"); const panel = document.getElementById("panel-settings") as HTMLDetailsElement | null; if (panel) {panel.open = true; panel.scrollIntoView?.({block: "start", behavior: "instant"});}}}>
                <SlidersHorizontal size={16} aria-hidden="true" /><span>{profiles.find(profile => profile.id === local.model)?.label || local.model} · {local.settings.width} × {local.settings.height} · {local.settings.batch_size} 张</span>
              </button>
              <p role="status" id="conversation-generation-reason" className="conversation-muted">{generationReason || "目标与资源可用，可以生成"}</p>
              {remoteEnabled && target && availability?.availability !== "ready" && !busy && <button type="button" onClick={() => setMappingEpoch(value => value + 1)}>重新检查生图连接</button>}
            </div>
            <div className="conversation-dock-actions">
              <button className="conversation-generate" aria-describedby="conversation-generation-reason" disabled={Boolean(generationReason)} onClick={() => void generate()}><ImageSquare size={19} aria-hidden="true" />生成图片</button>
            </div>

          </div>
        </section>
      </fieldset>
      <ArtistRecommendations key={record.id} prompt={local.positive} selected={local.requirements.layers.style.artists}
        disabled={Boolean(busy || pending || proposal || conflict)} onChange={artists => layer("style", {artists})} />
      <section className="conversation-reference-source"><Link to="/references">打开参考案例库</Link>
        {record.draft.reference_pin && <><p>当前要求来自参考案例。</p><Link to={`/references?example=${record.draft.reference_pin.example_id}`}>查看来源案例</Link>
          <button disabled={Boolean(busy || pending || conflict || dirty || local.delta.trim()) || local.positive !== (record.draft.compiled?.positive || "") || local.negative !== (record.draft.compiled?.negative || "")} onClick={() => void act("解除来源", async () => adopt(await apiRequest<ConversationRecord>("/api/v3/workbench/pins", {method: "DELETE", body: JSON.stringify({workspace_id: record.id, revision: record.revision})})))}>解除参考来源（保留要求）</button></>}
        {record.draft.generation_source && <><p>沿用原任务工作流快照。模型与执行目标已锁定；提示词和参数仍可调整。</p>
          <button disabled={Boolean(busy || pending || conflict || dirty || local.delta.trim()) || local.positive !== (record.draft.compiled?.positive || "") || local.negative !== (record.draft.compiled?.negative || "")}
            onClick={() => void act("解除生成来源", async () => adopt(await apiRequest<ConversationRecord>("/api/v3/workbench/generation-source", {method: "DELETE", body: JSON.stringify({workspace_id: record.id, revision: record.revision})})))}>解除原工作流快照，改用当前模板</button></>}
      </section>
    </>}
  </section>;
}

function SourceRunPreview({runId}: {runId: string}) {
  const [source, setSource] = useState<GenerationRunRecord | null>(null), [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void apiRequest<GenerationRunRecord>(`/api/v3/generation-runs/${encodeURIComponent(runId)}`, {signal: controller.signal})
      .then(value => {if (!controller.signal.aborted) setSource(value);})
      .catch(caught => {if (!controller.signal.aborted) setError((caught as Error).message);});
    return () => controller.abort();
  }, [runId]);
  return <details className="conversation-source-image" open><summary>来源图片 · 本会话沿用了这批图片的条件</summary>
    <p className="conversation-muted">这是继续创作的起点；下方显示本会话的新结果。</p>
    {source && <RunPreview run={source} />}{error && <p role="alert">{error}<Link to="/gallery">在画廊查看来源图片</Link></p>}
    {!source && !error && <p>正在读取来源图片…</p>}
  </details>;
}

export function RunPreview({run, showStatus = true}: {run: GenerationRunRecord; showStatus?: boolean}) {
  const [items, setItems] = useState<{id: string; path: string | null; thumbnail_url: string | null; content_url: string | null; removed: boolean}[]>([]);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [referenceId, setReferenceId] = useState("");
  const [previewIndex, setPreviewIndex] = useState(-1);
  const [assetError, setAssetError] = useState("");
  const [reload, setReload] = useState(0);
  const [metadata, setMetadata] = useState<GalleryAsset[]>([]);
  const previewItems = items.filter(item => !item.removed && item.content_url);
  useEffect(() => {
    if (previewIndex < 0) return;
    let canceled = false;
    void loadGallery().then(data => {if (!canceled) setMetadata(data.items);}).catch(() => {});
    return () => {canceled = true;};
  }, [previewIndex >= 0]);
  useEffect(() => {
    if (!run.artifact_count) return;
    const controller = new AbortController();
    setAssetError("");
    void apiRequest<{items: typeof items}>(`/api/v3/generation-runs/${run.id}/artifacts`, {signal: controller.signal})
      .then(result => {if (!controller.signal.aborted) setItems(result.items);})
      .catch(() => {if (!controller.signal.aborted) setAssetError("结果图片暂时无法读取，可以重试或到任务页查看。");});
    return () => controller.abort();
  }, [run.id, run.artifact_count, reload]);
  return <article>{showStatus && <p>{run.status_message}</p>}
    {assetError && <p role="alert">{assetError}<button onClick={() => setReload(value => value + 1)}>重新读取图片</button></p>}
    {!run.artifact_count && <p>{run.state === "completed" ? "本次任务没有记录到输出图片。" : "输出图片就绪后会自动显示在这里。"}</p>}
    {items.map(item => item.removed || !item.thumbnail_url
    ? <p key={item.id}>图片已移除或不在当前画廊</p>
    : <div key={item.id}><button type="button" className="run-preview-open" disabled={!item.content_url} aria-label={`预览生成图片 ${items.indexOf(item) + 1}`} onClick={() => setPreviewIndex(previewItems.findIndex(image => image.id === item.id))}><img src={item.thumbnail_url} alt="本次生成结果" loading="lazy" /></button>
      <button disabled={saving || !item.path} onClick={async () => {setSaving(true); setMessage(""); try {
        const example = await apiRequest<{id: string}>("/api/v3/reference-examples/from-run", {method: "POST", body: JSON.stringify({run_id: run.id, path: item.path})});
        setReferenceId(example.id); setMessage("已存入参考案例库。");
      } catch (error) {setMessage((error as Error).message);} finally {setSaving(false);}}}>收藏为参考</button>
      {item.path && <GenerationAssessment key={`${run.id}:${item.path}`} runId={run.id} path={item.path} />}</div>)}
    {previewIndex >= 0 && <ImagePreview index={previewIndex} onClose={() => setPreviewIndex(-1)} images={previewItems.map(item => {
      const asset = metadata.find(asset => asset.path === item.path);
      return {src: item.content_url!, alt: asset?.name || item.path?.split(/[\\/]/).pop() || "生成结果",
        width: asset?.width || undefined, height: asset?.height || undefined, positive: asset?.positive_prompt,
        negative: asset?.negative_prompt, parameters: asset ? {model: asset.model_profile, ...asset.generation_params} : {提示: "该图片的生成参数暂未在画廊索引中找到"}};
    })} />}
    {message && <p role="status">{message}</p>}{referenceId && <Link to={`/references?example=${referenceId}`}>查看已保存案例</Link>}<Link to="/generate">查看任务</Link></article>;
}
