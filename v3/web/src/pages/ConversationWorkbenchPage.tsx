import {ImagePreview} from "../components/ImagePreview";
import {PersonalPromptTransfer as PersonalPromptTransferPanel} from "../components/PersonalPromptTransfer";
import {consumePersonalPromptTransfer, readPersonalPromptTransfer, type PersonalPromptTransfer, type PersonalPromptResult} from "../lib/personalPromptTransfer";
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
import {ConversationStudioView} from "../components/ConversationStudioView";
import {WorkbenchHistory} from "../components/WorkbenchHistory";
import {WorkbenchImageResults} from "../components/WorkbenchImageResults";
import {type WorkbenchHistoryVersion, canRestoreRun} from "../lib/workbenchHistory";
import {LlmSettingsPanel} from "../components/LlmSettingsPanel";
import {useWorkbenchThinking} from "../lib/useWorkbenchThinking";
import {ConversationReview, PromptChanges, type ConversationProposal} from "../components/ConversationReview";
import {ConversationVersions} from "../components/ConversationVersions";
import {PromptLocks} from "../components/PromptLocks";
import {GenerationComparison} from "../components/GenerationComparison";
import {ConversationDraftRecovery} from "../components/ConversationDraftRecovery";
import {readConversationDraft, saveConversationDraft, initializeConversationTab, recoverConversationPending, saveConversationPending, clearConversationPending, recoverConversationBranch, saveConversationBranch, clearConversationBranch, preserveConversationDraft, readConversationDraftCandidate, type ConversationDraftCandidate} from "../lib/conversationDrafts";
import {mergeConversation, resolveConversationConflicts} from "../lib/conversationMerge";
import {migrateWorkflowSnapshot, reconcileWorkflowSnapshot} from "../lib/conversationSnapshot";
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
    model: record.draft.model_profile, settings: record.draft.generation_settings || defaultGenerationSettings(), workflowSnapshotRunId: record.draft.generation_source?.run_id || null};
}

export function ConversationWorkbenchPage({modelProfiles, remoteEnabled = false}: {modelProfiles?: ModelProfileOption[]; remoteEnabled?: boolean}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedWorkspace = searchParams.get("workspace");
  const requestedTransfer = searchParams.get("transfer");
  const requestedPersonalTransfer = searchParams.get("personal_transfer");
  const personalAttempt = useRef("");
  const [personalTransfer, setPersonalTransfer] = useState<PersonalPromptTransfer | null>(null);
  const [personalPreview, setPersonalPreview] = useState<ConversationRecord | null>(null);
  const [personalResult, setPersonalResult] = useState<PersonalPromptResult | null>(null);
  const [initialLoaded, setInitialLoaded] = useState(false);
  const openedWorkspace = useRef<string | null>(null);
  const transferAttempt = useRef("");
  const [transferRetry, setTransferRetry] = useState(0);
  const [transferNotice, setTransferNotice] = useState<{workspace: string; added: SelectedContent[]} | null>(null);
  const [record, setRecord] = useState<ConversationRecord | null>(null);
  const current = useRef<ConversationRecord | null>(null);
  const [local, setLocalState] = useState<LocalConversation | null>(null);
  const localRef = useRef<LocalConversation | null>(null);
  function setLocal(value: LocalConversation | null) {localRef.current = value; setLocalState(value);}
  const [historyOpen, setHistoryOpen] = useState(false);
  const [activeView, setActiveView] = useState<"prompt" | "images">("images");
  const [lastChange, setLastChange] = useState<{before: LocalConversation; after: LocalConversation; label: string} | null>(null);
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
  type EditStep = {value: LocalConversation; label: string; deltaAfter: string};
  const undoStack = useRef<EditStep[]>([]), redoStack = useRef<EditStep[]>([]);
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
  const resultsPanel = useRef<HTMLDivElement>(null);
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
    const recovered = migrateWorkflowSnapshot(structuredClone(latest.local), record);
    const value = latest.kind === "snapshot" ? {...recovered, baseRevision: record.revision} : recovered;
    const original = latest.kind === "snapshot" ? localFrom(record) : latest.base
      ? migrateWorkflowSnapshot(latest.base, record) : value.baseRevision === record.revision ? localFrom(record) : null;
    const saved = saveConversationDraft(record.id, value, original);
    if (!saved.ok) {setStorageWarning(saved.warning); setError("无法保存恢复后的草稿，当前编辑保持不变。"); return false;}
    base.current = original; setLocal(value);
    draftPersistenceBlocked.current = null; setInvalidDraftRaw(""); setStorageWarning(saved.warning);
    rememberEdit(local, "恢复草稿", value.delta);
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
    const resumeProposalLoad = current.current?.id === id && openedWorkspace.current !== id;
    if (draftAtRisk && !resumeProposalLoad) return false;
    const sequence = ++opening.current;
    openedWorkspace.current = null; setInitialLoaded(false);
    setBusy("打开工作台"); setError("");
    try {
      // A partial open already restored local edits. Retry only the missing proposal read.
      if (!resumeProposalLoad) {
        const next = await apiRequest<ConversationRecord>(`/api/v3/workspaces/${encodeURIComponent(id)}`);
        if (!mounted.current || sequence !== opening.current) return false;
        const recovered = readConversationDraft(id);
        draftPersistenceBlocked.current = recovered?.persistenceBlocked ? id : null;
        setInvalidDraftRaw(recovered?.invalidRaw || "");
        adopt(next);
        setWorkspaces(items => items.some(item => item.id === next.id) ? items : [next, ...items]);
        if (recovered?.local) {
          const value = migrateWorkflowSnapshot(recovered.local, next);
          const original = recovered.base ? migrateWorkflowSnapshot(recovered.base, next) : value.baseRevision === next.revision ? localFrom(next) : null;
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
      }
      const review = await apiRequest<{proposal: ConversationProposal | null}>(`/api/v3/workspaces/${encodeURIComponent(id)}/proposal`);
      if (!mounted.current || sequence !== opening.current) return false;
      setProposal(review.proposal || null);
      openedWorkspace.current = id; setInitialLoaded(true);
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
      // Adopting the workspace alone does not confirm whether a proposal is pending.
      const opened = !id || (current.current?.id === id && openedWorkspace.current === id) || await open(id);
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
  const personalBlockedReason = busy ? `${busy}…` : pending || pendingRecoveryBlocked ? "请先查询上次生成请求的结果。"
    : proposal ? "请先接受或放弃待处理的提示词草案。" : conflict ? "请先处理版本冲突。"
    : recentRuns.some(item => ["draft", "connecting", "preparing", "queued", "running", "downloading"].includes(item.state)) ? "图片生成中，请完成后再追加或撤销。" : "";

  function closePersonalTransfer() {
    setPersonalTransfer(null); setPersonalPreview(null); setPersonalResult(null); personalAttempt.current = "";
    setSearchParams(previous => {const next = new URLSearchParams(previous); next.delete("personal_transfer"); return next;}, {replace: true});
  }
  function acceptPersonalResult(result: PersonalPromptResult, id: string) {
    // Only a matching durable receipt permits consuming the raw transfer.
    if (!result.receipt || result.receipt.id !== id || result.receipt.workspace_id !== result.workspace?.id
      || !["applied", "undone"].includes(result.receipt.state)) throw new Error("追加回执未确认，请重试查询。");
    if (!mounted.current || current.current?.id !== result.workspace.id) return;
    const value = localRef.current;
    const unsaved = value && current.current && hasUnsavedInputs(current.current, value);
    setPersonalResult(result); setPersonalPreview(null);
    if (unsaved) {
      adopt(result.workspace, true); setConflict(true); setConflictChoices({});
    } else {
      const delta = value?.delta || "";
      adopt(result.workspace);
      const kept = {...localFrom(result.workspace), delta}; setLocal(kept); persistDraft(result.workspace.id, kept);
    }
    consumePersonalPromptTransfer(id);
    setActiveView("prompt"); setInspectorTab("prompt");
  }
  async function recoverPersonalReceipt(id: string, source: ConversationRecord): Promise<boolean> {
    try {
      const result = await apiRequest<PersonalPromptResult>(`/api/v3/workspaces/${source.id}/personal-prompt-transfers/${encodeURIComponent(id)}`);
      acceptPersonalResult(result, id); return true;
    } catch (caught) {
      if (caught instanceof ApiClientError && caught.code === "personal_prompt_transfer_not_found") return false;
      throw caught;
    }
  }
  async function preparePersonalTransfer() {
    if (!requestedPersonalTransfer) return;
    if (!initialLoaded) {personalAttempt.current = ""; setTransferRetry(value => value + 1); return;}
    const id = requestedPersonalTransfer;
    await act("准备追加预览", async () => {
      const transfer = readPersonalPromptTransfer(id); setPersonalTransfer(transfer);
      let source = current.current;
      // Recover before flushing: a lost append response must not be overwritten by an older local draft.
      if (source && await recoverPersonalReceipt(id, source)) return;
      if (!transfer) throw new Error("未找到个人提示词传递记录或回执，请从个人标签超市重新追加。");
      if (personalBlockedReason) return;
      if (!source) {
        // Creation is idempotent and the body is frozen before sending, including across reloads.
        const key = `anima-personal-prompt-create:${id}`;
        const body = read<string>(key) || JSON.stringify({title: "个人提示词", draft: {
          model_profile: profiles.find(item => item.id === "anima_aesthetic_v1_1")?.id || profiles[0].id,
          generation_settings: defaultGenerationSettings()}});
        localStorage.setItem(key, JSON.stringify(body));
        source = await apiRequest<ConversationRecord>("/api/v3/workspaces", {method: "POST", body, headers: {"Idempotency-Key": `personal-prompt:${id}`}});
        if (!mounted.current) return;
        adopt(source); write(ACTIVE, source.id); setWorkspaces(items => [source!, ...items.filter(item => item.id !== source!.id)]);
        if (await recoverPersonalReceipt(id, source)) return;
      }
      const value = localRef.current;
      if (!value || current.current?.id !== source.id) return;
      if (hasUnsavedInputs(source, value)) {
        if (!value.positive.trim() && (value.positive !== (source.draft.compiled?.positive || "") || value.negative !== (source.draft.compiled?.negative || ""))) {
          throw new Error("请先在工作台填写正向提示词，再保存并预览追加内容。");
        }
        source = await save();
      }
      setPersonalPreview(source); setPersonalResult(null);
      setSearchParams(previous => {const next = new URLSearchParams(previous); next.set("workspace", source!.id); return next;}, {replace: true});
    });
  }
  useEffect(() => {
    if (!requestedPersonalTransfer || !initialLoaded || busy || personalAttempt.current === requestedPersonalTransfer) return;
    personalAttempt.current = requestedPersonalTransfer;
    void preparePersonalTransfer();
  }, [requestedPersonalTransfer, initialLoaded, busy]);

  async function confirmPersonalTransfer() {
    if (!initialLoaded || !personalTransfer || !personalPreview || !current.current || personalBlockedReason) return;
    if (personalPreview.id !== current.current.id || personalPreview.revision !== current.current.revision
      || (localRef.current && hasUnsavedInputs(current.current, localRef.current))) {await preparePersonalTransfer(); return;}
    const id = personalTransfer.id, source = current.current;
    await act("追加个人提示词", async () => {
      const result = await apiRequest<PersonalPromptResult>(`/api/v3/workspaces/${source.id}/personal-prompt-transfers`, {method: "POST", body: JSON.stringify({
        transfer_id: id, revision: source.revision, positive: personalTransfer.positive, negative: personalTransfer.negative})});
      acceptPersonalResult(result, id);
    });
  }
  async function undoPersonalTransfer() {
    if (!initialLoaded || !personalResult || !current.current || !localRef.current || personalBlockedReason || personalUndoChanged) return;
    const id = personalResult.receipt.id;
    await act("撤销个人提示词追加", async () => {
      const source = hasUnsavedInputs(current.current!, localRef.current!) ? await save() : current.current!;
      const result = await apiRequest<PersonalPromptResult>(`/api/v3/workspaces/${source.id}/personal-prompt-transfers/${encodeURIComponent(id)}/undo`, {
        method: "POST", body: JSON.stringify({revision: source.revision})});
      acceptPersonalResult(result, id);
    });
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
    if (local?.workflowSnapshotRunId) query.set("workflow_snapshot_run_id", local.workflowSnapshotRunId);
    void apiRequest<{availability: string; message?: string}>(`/api/v3/workbench/availability?${query}`, {signal: controller.signal})
      .then(value => {if (!controller.signal.aborted) setAvailability(value);})
      .catch(caught => {if (!controller.signal.aborted) setAvailability({availability: "unknown", message: (caught as Error).message});});
    return () => controller.abort();
  }, [record, target, inputsDirty, conflict, mappingEpoch, local?.workflowSnapshotRunId]);

  useEffect(() => {
    if (!record) return;
    const controller = new AbortController();
    let timer = 0;
    async function poll() {
      try {
        const result = await apiRequest<{items: GenerationRunRecord[]}>(`/api/v3/workspaces/${record!.id}/runs?limit=${runLimit}`, {signal: controller.signal});
        if (controller.signal.aborted) return;
        setRecentRuns(result.items);
        // A response started before submission can omit the newly accepted run;
        // the recent page can also omit the historical image currently selected.
        setRun(previous => result.items.find(item => item.id === previous?.id) || previous || result.items[0] || null);
      } catch (caught) {if (!controller.signal.aborted) setError((caught as Error).message);}
      if (!controller.signal.aborted) timer = window.setTimeout(() => void poll(), 3000);
    }
    void poll();
    return () => {controller.abort(); window.clearTimeout(timer);};
  }, [record?.id, runLimit]);

  function rememberEdit(before: LocalConversation, label: string, deltaAfter = before.delta) {
    undoStack.current = [...undoStack.current.slice(-49), {value: structuredClone(before), label, deltaAfter}];
    redoStack.current = []; lastEdit.current = {keys: "", at: 0}; setUndoEpoch(value => value + 1);
  }
  function edit(patch: Partial<LocalConversation>) {
    const before = localRef.current;
    if (!before || !record) return;
    const keys = Object.keys(patch).sort().join(","), at = Date.now();
    const onlyDelta = keys === "delta";
    if (!onlyDelta && (keys !== lastEdit.current.keys || at - lastEdit.current.at > 800)) {
      rememberEdit(before, patch.model ? "切换模型" : patch.settings ? "修改生成条件" : "编辑提示词与要求");
    }
    if (!onlyDelta) {redoStack.current = []; lastEdit.current = {keys, at};}
    const value = {...before, ...patch};
    if (patch.model && patch.model !== before.model) {
      const compatible = targets.filter(item => item.compatible_model_profiles.includes(patch.model!));
      const next = defaultTarget(compatible.filter(item => item.remote_profile_id === before.settings.remote_profile_id)) || defaultTarget(compatible);
      value.settings = patch.settings || changeGenerationModel(before.settings, next);
      value.workflowSnapshotRunId = null;
    }
    if (patch.settings && (patch.settings.remote_profile_id !== before.settings.remote_profile_id || patch.settings.workflow_profile_id !== before.settings.workflow_profile_id)) value.workflowSnapshotRunId = null;
    setLocal(value); persistDraft(record.id, value);
  }
  function undoEdit(redo = false) {
    const before = localRef.current;
    if (!before || !record || busy || pending) return;
    const source = redo ? redoStack.current : undoStack.current, destination = redo ? undoStack.current : redoStack.current;
    const previous = source.pop(); if (!previous) return;
    destination.push({value: structuredClone(before), label: previous.label, deltaAfter: previous.value.delta});
    const nextDelta = before.delta && before.delta !== previous.deltaAfter ? before.delta : previous.value.delta;
    const value = {...previous.value, delta: nextDelta, baseRevision: record.revision};
    setLocal(value); persistDraft(record.id, value);
    setLastChange({before, after: value, label: (redo ? "重做：" : "撤销：") + previous.label});
    setNotice((redo ? "已重做：" : "已撤销：") + previous.label);
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
      adopt(next); write(ACTIVE, next.id); setWorkspaces(items => [next, ...items.filter(item => item.id !== next.id)]); setPending(null); setRun(null); setRecentRuns([]);
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
      adopt(next); write(ACTIVE, next.id); setWorkspaces(items => [next, ...items.filter(item => item.id !== next.id)]);
      setPending(null); setRun(source); setRecentRuns([source]); setAvailability(null); setProposal(null); setInspectorTab("prompt");
      if (requestedWorkspace) clearWorkspaceLink();
    });
  }
  async function save(tentativeMode = false, value = localRef.current): Promise<ConversationRecord> {
    let source = current.current;
    if (!source || !value) throw new Error("请先打开工作台。");
    value = migrateWorkflowSnapshot(value, source);
    const bound = source.draft.generation_source;
    if (bound && (value.workflowSnapshotRunId !== bound.run_id || bound.model_profile !== value.model
      || bound.remote_profile_id !== value.settings.remote_profile_id || bound.workflow_profile_id !== value.settings.workflow_profile_id)) {
      source = await apiRequest<ConversationRecord>("/api/v3/workbench/generation-source", {method:"DELETE",body:JSON.stringify({workspace_id:source.id,revision:source.revision})});
      adopt(source,true);
    }
    const next = await apiRequest<ConversationRecord>('/api/v3/workspaces/' + source.id, {method:"PUT",body:JSON.stringify({
      revision:source.revision,title:source.title,draft:{model_profile:value.model,mode:tentativeMode?source.draft.mode:value.mode,
        requirements_edit:{...cleanRequirements(value.requirements),prompt_locks:value.requirements.prompt_locks||[]},generation_settings:value.settings,
        ...(value.positive.trim()?{prompt_edit:{positive:value.positive,negative:value.negative}}:{})}})});
    adopt(next,true); base.current=localFrom(next);
    const kept={...value,delta:localRef.current?.delta ?? value.delta,baseRevision:next.revision};
    setLocal(kept);persistDraft(next.id,kept,base.current);
    return next;
  }
  async function requestProposal(saved:ConversationRecord,value:LocalConversation,recompile:boolean,task:"rewrite"|"sync_requirements"="rewrite"):Promise<{record:ConversationRecord;local:LocalConversation}|null> {
    setRetryTurn(false);setRetryTask(task);
    const controller=new AbortController();turnController.current=controller;
    const submittedDelta=recompile?"":value.delta;
    function applied(next:ConversationRecord & {unchanged?:boolean;message?:string;warnings?:string[]}) {
      if(!mounted.current || controller.signal.aborted || current.current?.id!==saved.id)return null;
      const freshDelta=localRef.current?.delta ?? value.delta;
      const after={...localFrom(next),delta:freshDelta===value.delta?"":freshDelta,
        workflowSnapshotRunId:value.workflowSnapshotRunId,restoredFrom:value.restoredFrom};
      rememberEdit(value,value.delta.trim()||"更新提示词",after.delta);
      adopt(next,true);base.current=localFrom(next);setLocal(after);persistDraft(next.id,after,base.current);
      setLastChange({before:structuredClone(value),after:structuredClone(after),label:value.delta.trim()||"更新提示词"});
      setProposal(null);setInspectorTab("prompt");setActiveView("prompt");
      const unchanged=value.positive===after.positive && value.negative===after.negative;
      setNotice([unchanged?"本次提示词没有变化，可直接生成或调整意见再试。":"提示词已更新，可直接生成或撤销。",...(next.warnings||[])].join("\n"));
      return {record:next,local:after};
    }
    try {
      if(task==="sync_requirements") {
        const candidate=await apiRequest<ConversationProposal>("/api/v3/workbench/turns",{method:"POST",signal:controller.signal,body:JSON.stringify({workspace_id:saved.id,revision:saved.revision,mode:saved.draft.mode,preview:true,task,delta:{text:""},compiled:{positive:value.positive,negative:value.negative}})});
        if(!controller.signal.aborted){setProposal(candidate);setNotice("已整理中文要求，可按需查看。");}return null;
      }
      const next=await apiRequest<ConversationRecord & {unchanged?:boolean;warnings?:string[]}>("/api/v3/workbench/turns",{method:"POST",signal:controller.signal,body:JSON.stringify({
        workspace_id:saved.id,revision:saved.revision,mode:value.mode,preview:false,delta:{text:submittedDelta},
        ...(value.positive.trim()?{compiled:{positive:value.positive,negative:value.negative}}:{})})});
      return applied(next);
    } catch(caught) {
      if(!controller.signal.aborted && caught instanceof ApiClientError && ["network_error","internal_error"].includes(caught.code)) {
        try {
          const recovered=await apiRequest<ConversationRecord>('/api/v3/workspaces/'+saved.id);
          const last=recovered.draft.conversation_events.at(-1);
          if(recovered.revision===saved.revision+1 && last?.after_revision===recovered.revision && last.before_revision===saved.revision && last.delta===submittedDelta)return applied(recovered);
          if(recovered.revision!==saved.revision) {adopt(recovered,true);setConflict(true);}
        } catch { /* Keep the original failure and all local inputs. */ }
      }
      if(!controller.signal.aborted)setRetryTurn(true);
      throw caught;
    } finally {if(turnController.current===controller)turnController.current=null;}
  }
  async function turn(recompile:boolean,generateAfter=false) {
    const before=localRef.current;
    if(!record||!before||proposal||conflict||pending||pendingRecoveryBlocked||llmUnavailableReason||adviceBusy)return;
    await act(generateAfter?"更新提示词并生成":"更新提示词",async()=>{
      const saved=hasUnsavedInputs(record,{...before,mode:record.draft.mode})?await save(true,before):record;
      const updated=await requestProposal(saved,before,recompile);
      if(updated && generateAfter) {setBusy("提交生成");await submitGeneration(updated.local,updated.record);}
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
  function restoreEditor(value:LocalConversation,label:string) {
    const before=localRef.current;
    if(!record||!before||busy||pending||conflict)return false;
    const preserved=preserveConversationDraft(record.id,before,base.current);
    if(!preserved.ok){setError(preserved.warning||"无法保留当前草稿，当前内容未变。");return false;}
    const next={...value,baseRevision:record.revision};
    const saved=saveConversationDraft(record.id,next,base.current);
    if(!saved.ok){setError(saved.warning||"无法保存恢复内容，当前内容未变。");return false;}
    rememberEdit(before,label,next.delta);setLocal(next);setStorageWarning("");setHistoryOpen(false);
    setLastChange({before,after:next,label});setNotice(label+"；可撤销恢复，后续图片与记录均保留。");return true;
  }
  function restoreVersion(version:WorkbenchHistoryVersion) {
    if(!record)return;
    restoreEditor({...localFrom({...record,...version,draft:version.draft}),delta:"",restoredFrom:"历史创作："+version.title},"恢复历史创作");
  }
  async function restoreRun(source:GenerationRunRecord,onlyPrompt=false,version?:WorkbenchHistoryVersion) {
    const before=localRef.current;
    if(!record||!before||busy||pending||conflict||!source.source?.positive_prompt)return;
    if(!onlyPrompt && !canRestoreRun(source)){setError("这份旧记录缺少完整参数，可以只用提示词。");return;}
    let historical=version;
    if(!onlyPrompt && !historical && source.source.workspace_revision) {
      try {
        for(let offset=0;!historical;offset+=50) {
          const response=await apiRequest<{items:WorkbenchHistoryVersion[]}>('/api/v3/workspaces/'+record.id+'/versions?limit=50&offset='+offset);
          historical=response.items.find(item=>item.revision===source.source!.workspace_revision);
          if(response.items.length<50 || response.items.at(-1)!.revision<source.source.workspace_revision)break;
        }
      } catch {setError("无法读取这张图的创作背景，请重试，或只用提示词。");return;}
      if(localRef.current!==before){setError("读取期间编辑已变化，请重新选择恢复。");return;}
    }
    if(!onlyPrompt&&!historical){setError("这张旧图缺少可恢复的画面与资源记录，请使用“只用提示词”。");return;}
    const requirements=onlyPrompt?{...emptyRequirements(),prompt_locks:[],loras:structuredClone(before.requirements.loras)}
      :editableRequirements({...record,...historical!,draft:historical!.draft});
    const settings=onlyPrompt?before.settings:{...defaultGenerationSettings(),...source.source.settings,
      preset_id:"custom",aspect:"custom" as const,remote_profile_id:source.remote_profile_id,workflow_profile_id:source.workflow_profile_id};
    const value={...before,positive:source.source.positive_prompt,negative:source.source.negative_prompt,
      requirements,mode:onlyPrompt?before.mode:historical?.draft.mode||before.mode,delta:"",
      model:onlyPrompt?before.model:source.source.model_profile!,settings,
      workflowSnapshotRunId:onlyPrompt?before.workflowSnapshotRunId:source.id,
      restoredFrom:(onlyPrompt?"只用提示词 · ":"从图片继续 · ")+(historical?.draft.conversation_events?.at(-1)?.delta||source.created_at||"历史图片")};
    if(restoreEditor(value,onlyPrompt?"已载入图片提示词，保留当前生成条件":"已载入图片提示词和当时设置")){
      setRun(source);setActiveView("prompt");
      if(!onlyPrompt && (source.source.settings.seed===-1 || (source.source.settings.batch_size||1)>1))setNotice("已恢复提交时的条件；随机或多图批次的种子不保证对应单张图片。可撤销恢复。");
    }
  }
  async function forkVersion(revision: number) {
    if (!record || !local || proposal || pending || conflict) return;
    await act("从历史版本另开会话", async () => {
      const preserved = preserveConversationDraft(record.id, local, base.current);
      if (!preserved.ok) throw new Error(preserved.warning || "无法保留当前编辑，尚未另开会话。");
      const source = `version:${revision}` as const;
      const request = recoverConversationBranch(record.id, source) || {key: crypto.randomUUID(), body: JSON.stringify({})};
      saveConversationBranch(record.id, source, request);
      const next = await apiRequest<ConversationRecord>(`/api/v3/workspaces/${record.id}/versions/${revision}/fork`, {method: "POST", body: request.body, headers: {"Idempotency-Key": request.key}});
      clearConversationBranch(record.id, source, request);
      adopt(next); write(ACTIVE, next.id); setWorkspaces(items => [next, ...items.filter(item => item.id !== next.id)]);
      setRun(null); setRecentRuns([]); setProposal(null); setAvailability(null); setInspectorTab("prompt"); setHistoryOpen(false);
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
      write(ACTIVE, next.id); setWorkspaces(items => [next, ...items.filter(item => item.id !== next.id)]); setRun(null); setRecentRuns([]); setProposal(null); setAvailability(null);
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
  async function submitGeneration(value:LocalConversation,initial:ConversationRecord,retry=false) {
    value=migrateWorkflowSnapshot(value,initial);
    let saved=initial;
    if(!retry && (hasUnsavedInputs(initial,value) || initial.draft.generation_source?.run_id && value.workflowSnapshotRunId!==initial.draft.generation_source.run_id)) saved=await save(false,value);
    const chosen=targets.find(item=>item.remote_profile_id===value.settings.remote_profile_id && item.workflow_profile_id===value.settings.workflow_profile_id && item.compatible_model_profiles.includes(value.model));
    const snapshotRun=value.workflowSnapshotRunId;
    const request=retry&&pending?pending:{key:crypto.randomUUID(),body:JSON.stringify({
      submission_kind:"conversational",use_current_prompt:true,workspace_id:saved.id,workspace_revision:saved.revision,
      compiled_token:saved.draft.compiled?.compiled_token,positive_prompt:value.positive,negative_prompt:value.negative,
      model_profile:value.model,remote_profile_id:chosen?.remote_profile_id,workflow_profile_id:chosen?.workflow_profile_id,
      ...(snapshotRun?{workflow_snapshot_run_id:snapshotRun}:{}),settings:resolvedGenerationSettings(value.settings)})};
    saveConversationPending(saved.id,request);setPending(request);
    let accepted:Accepted;
    try {accepted=await apiRequest<Accepted>("/api/v3/direct-prompt/runs",{method:"POST",body:request.body,headers:{"Idempotency-Key":request.key}});}
    catch(caught) {
      const rejected=["invalid_request","remote_not_configured","v2_runtime_missing","submission_store_missing","workspace_revision_conflict","workspace_not_found","stale_compiled_prompt","rate_limited","session_invalid","incompatible_workflow","incompatible_model","workflow_snapshot_missing","reference_preset_unavailable","mapping_revision_conflict","missing_lora","lora_unmapped","lora_not_installed","protected_prompt_changed","workflow_incompatible","unknown"];
      const confirmedRejection=["lora_not_installed","protected_prompt_changed","workflow_incompatible","incompatible_workflow","reference_preset_unavailable","mapping_revision_conflict"];
      if(caught instanceof ApiClientError&&(!retry&&rejected.includes(caught.code)||retry&&confirmedRejection.includes(caught.code))){clearConversationPending(saved.id,request);setPending(null);}
      throw caught;
    }
    clearConversationPending(saved.id,request);setPending(null);setRun(accepted);setActiveView("images");
    setRecentRuns(items=>[accepted,...items.filter(item=>item.id!==accepted.id)]);
    const submitted=JSON.parse(request.body) as {positive_prompt:string;negative_prompt:string};
    let next:ConversationRecord={...saved,revision:accepted.workspace_revision,draft:{...saved.draft,compile_state:"fresh",
      compiled:{positive:submitted.positive_prompt,negative:submitted.negative_prompt,compiled_token:accepted.compiled_token,source:"user"}}};
    adopt(next,true);base.current=localFrom(next);
    const kept={...(localRef.current||value),baseRevision:next.revision};setLocal(kept);persistDraft(next.id,kept,base.current);
    try {
      const latest=await apiRequest<ConversationRecord>('/api/v3/workspaces/'+saved.id);
      if(latest.revision>next.revision){adopt(latest,true);setConflict(true);setConflictChoices({});setNotice("生成已提交；其他窗口又保存了修改，当前草稿保留，请合并后继续。");}
      else if(latest.revision===next.revision){next=latest;adopt(next,true);base.current=localFrom(next);persistDraft(next.id,kept,base.current);}
    } catch {setNotice("生成已提交，读取最新记录暂时失败；请勿重复提交。");}
  }
  async function generate(retry=false) {
    if(!record||!localRef.current)return;
    await act(retry?"查询生成结果":"提交生成",()=>submitGeneration(localRef.current!,current.current!,retry));
  }

  const promptChanged = Boolean(local && (local.positive !== (record?.draft.compiled?.positive || "") || local.negative !== (record?.draft.compiled?.negative || "")));
  const personalUndoChanged = Boolean(personalResult && (personalResult.workspace.id !== record?.id || !personalResult.receipt.can_undo
    || local?.positive !== (personalResult.workspace.draft.compiled?.positive || "")
    || local?.negative !== (personalResult.workspace.draft.compiled?.negative || "")));
  const executionReason=busy ? busy+"…" : pendingRecoveryBlocked?"请先核对上次生成请求的恢复记录":pending?"请先查询上次提交的结果":conflict?"请先处理版本冲突"
    :local?.model===LEGACY_AESTHETIC?"请选择明确的模型版本":!remoteEnabled?"连接生图服务后即可生成":!target?"请选择可用的服务器与工作流"
    :local&&!validSeed(local.settings.seed)?"请填写有效种子，-1 表示随机":"";
  const generationReason=executionReason||(!local?.positive.trim()?"请填写或更新正向提示词":"");
  const tabs = [{id: "prompt", label: "提示词"}, {id: "requirements", label: "画面要求"}, {id: "settings", label: "生成设置"}] as const;
  async function copyPrompt(kind: "positive" | "negative") {
    try {await navigator.clipboard.writeText(local?.[kind] || ""); setCopied(kind);}
    catch {setError("复制失败，请选中提示词后手动复制。");}
  }
  const merge = conflict && base.current && local && record ? mergeConversation(base.current, local, localFrom(record)) : null;
  function resolveConflict() {
    if (!merge || !record || merge.conflicts.some(item => !conflictChoices[item.path])) return;
    const value = reconcileWorkflowSnapshot(resolveConversationConflicts(merge, conflictChoices), [local, base.current, localFrom(record)]); base.current = localFrom(record);
    undoStack.current = []; redoStack.current = []; lastEdit.current = {keys: "", at: 0};
    setLocal(value); persistDraft(record.id, value, base.current); setConflict(false); setError("");
    setNotice("已合并双方修改，可以继续更新提示词或生图。");
  }

  return <section className="conversation-workbench conversation-workbench--studio">
    <header className="conversation-heading"><div className="conversation-title"><h1>{record?.title || "开始创作"}</h1>{record && <span className="conversation-save-state">{storageWarning ? "草稿保存需注意" : dirty || local?.delta.trim() ? "草稿已保留" : "已保存"}</span>}</div>
      <div className="conversation-actions conversation-toolbar">{record && <button onClick={()=>setHistoryOpen(true)}>创作记录</button>}
        <button aria-expanded={showLlmSettings} aria-controls="conversation-llm-settings" disabled={Boolean(busy || adviceBusy || thinking.saving || llmSettingsBusy)} onClick={() => setShowLlmSettings(value => !value)}><GearSix size={17} aria-hidden="true" />LLM 设置</button>
        <button className="conversation-new" disabled={Boolean(busy || pending || draftAtRisk)} onClick={startNew}><Plus size={16} aria-hidden="true" />新会话</button>
      </div></header>
    <div className="conversation-session-bar"><div className="conversation-session-select"><ChatCircleDots size={19} aria-hidden="true" /><select aria-label={archived ? "恢复已归档会话" : "打开已有会话"} value={archived ? "" : record?.id || ""} disabled={Boolean(busy || pending || draftAtRisk)} onChange={event => {if (event.target.value) void (archived ? unarchiveSession(event.target.value) : open(event.target.value));}}>
        <option value="">{archived ? "选择会话并恢复" : "选择工作台"}</option>{record && !archived && !workspaces.some(item => item.id === record.id) && <option value={record.id}>{record.title}</option>}{workspaces.map(item => <option key={item.id} value={item.id}>{item.title} · {new Date(item.updated_at).toLocaleDateString()}</option>)}</select>
      </div><span className="conversation-session-note">修改自动保留；更新和生图时自动保存所需内容。</span></div>
    <details className="conversation-session-tools"><summary>查找与管理会话</summary><div className="conversation-actions">
      <input aria-label="搜索会话" value={sessionSearch} onChange={event => setSessionSearch(event.target.value)} onKeyDown={event => {if (event.key === "Enter") void searchSessions();}} placeholder="按会话名称搜索" />
      <button disabled={Boolean(busy)} onClick={() => void searchSessions()}>搜索</button>
      <label><input type="checkbox" checked={archived} disabled={Boolean(busy)} onChange={event => {setArchived(event.target.checked); void searchSessions(sessionSearch, event.target.checked);}} />已归档会话</label>
      {moreSessions && <button disabled={Boolean(busy)} onClick={() => void searchSessions(sessionSearch, archived, true)}>加载更多会话</button>}
      {record && <><button disabled={Boolean(busy || pending || proposal || conflict)} onClick={() => setRename(record.title)}>重命名当前会话</button><button disabled={Boolean(busy || pending || proposal || dirty || conflict || local?.delta.trim())} onClick={() => void archiveSession()}>归档当前会话</button></>}
    </div>{rename !== null && <div className="conversation-actions"><input aria-label="会话名称" maxLength={200} value={rename} onChange={event => setRename(event.target.value)} /><button disabled={Boolean(busy) || !rename.trim()} onClick={() => void renameSession()}>保存名称</button><button onClick={() => setRename(null)}>取消改名</button></div>}</details>

    {showLlmSettings && <div id="conversation-llm-settings"><LlmSettingsPanel disabled={Boolean(busy || pending || adviceBusy || thinking.loading || thinking.saving)}
      onSaved={thinking.refresh} onBusyChange={setLlmSettingsBusy} /></div>}
    {error && <div role="alert" className="conversation-error">{error}{retryTurn && record && local && <p>当前内容已保留。<button disabled={Boolean(busy || proposal || conflict || llmUnavailableReason)} onClick={() => void (retryTask === "sync_requirements" ? syncRequirements() : turn(!local.delta.trim()))}>重试整理</button><button onClick={() => setShowLlmSettings(true)}>检查模型设置</button></p>}</div>}
    {storageWarning && <div role="alert" className="conversation-warning">{storageWarning}{invalidDraftRaw && <button onClick={() => {
      const url = URL.createObjectURL(new Blob([invalidDraftRaw], {type: "application/json"}));
      const link = document.createElement("a"); link.href = url; link.download = `anima-draft-recovery-${record?.id || "unknown"}.json`; link.click(); URL.revokeObjectURL(url);
    }}>导出原始草稿</button>}{draftPersistenceBlocked.current === record?.id && <p>原草稿未被覆盖。请先导出；当前编辑可直接保存到服务端，浏览器恢复仍不可用。</p>}</div>}
    {notice && <p role="status" className="conversation-notice">{notice}</p>}
    {busy && <div className="conversation-wait"><p role="status">{busy}… 已等待 {elapsed} 秒{turnController.current ? "；完成后提示词会直接更新。" : ""}</p>{turnController.current && <button onClick={() => turnController.current?.abort()}>取消整理</button>}</div>}
    {requestedTransfer && error && <button disabled={Boolean(busy)} onClick={() => {transferAttempt.current = ""; setInitialLoaded(false); setTransferRetry(value => value + 1);}}>重试带入</button>}
    {requestedPersonalTransfer && <PersonalPromptTransferPanel addition={personalTransfer}
      before={personalPreview ? {positive: personalPreview.draft.compiled?.positive || "", negative: personalPreview.draft.compiled?.negative || ""} : null}
      receipt={personalResult?.receipt || null} blockedReason={personalBlockedReason} busy={Boolean(busy)}
      needsRefresh={Boolean(personalPreview && (!initialLoaded || personalPreview.id !== record?.id || personalPreview.revision !== record?.revision || dirty))}
      undoChanged={personalUndoChanged} onConfirm={() => void confirmPersonalTransfer()} onCancel={closePersonalTransfer}
      onRefresh={() => void preparePersonalTransfer()} onUndo={() => void undoPersonalTransfer()} />}
    {record && local && transferNotice?.workspace === record.id && <p role="status">{transferNotice.added.length ? `已加入 ${transferNotice.added.length} 个标签，原有草稿已保留。` : "所选标签已在当前要求中，没有重复添加。"}
      {transferNotice.added.length > 0 && <button disabled={Boolean(busy || pending || conflict)} onClick={() => {
        edit({requirements: undoSelectedContent(local.requirements, transferNotice.added)}); setTransferNotice(null);
      }}>撤销本次带入</button>}</p>}
    {!local || !record ? <section className="conversation-empty"><Sparkle size={30} aria-hidden="true" /><h2>这次，想画些什么？</h2><p>人物、动作、场景或一种氛围，从你最在意的部分开始。</p>
      <label htmlFor="conversation-idea" className="conversation-sr-only">创作想法</label><textarea id="conversation-idea" rows={4} value={idea} maxLength={4000} onChange={event => setIdea(event.target.value)} placeholder="例如：栗色长发的女孩坐在窗边，双手捧着咖啡杯，窗外樱花盛开。" />
      <div className="conversation-starters">{[{title: "日常人物", text: "栗色长发的女孩坐在窗边，双手捧着咖啡杯，清透赛璐璐风格。"}, {title: "幻想场景", text: "身穿白金盔甲的骑士站在空中花园，披着蓝色披风，远处是浮空城堡。"}, {title: "水彩插画", text: "戴尖帽的魔女双手捧着小白花，站在有蕨类和萤火虫的森林，透明水彩风格。"}].map(item => <button key={item.title} disabled={Boolean(busy)} onClick={() => setIdea(item.text)}>{item.title}</button>)}</div>
      <button className="conversation-primary" onClick={() => void create(idea)} disabled={Boolean(busy || thinking.loading) || !idea.trim()}>开始整理想法 <PaperPlaneRight size={17} aria-hidden="true" /></button>
      <p className="conversation-empty-note">提示词更新后，点击生成图片；修改不满意可以撤销。</p></section> : <>
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

      {proposal && <details className="conversation-legacy-proposal"><summary>上次未处理的提示词草案</summary><ConversationReview proposal={proposal} before={local} disabled={Boolean(busy)} acceptBlocked={Boolean(conflict || proposal.base_revision !== record.revision || hasUnsavedInputs(record, {...local, mode: record.draft.mode}))} onAccept={() => void decideProposal(true)} onDiscard={() => void decideProposal(false)} /></details>}
      <ConversationStudioView activeView={activeView} busy={Boolean(busy)} historyOpen={historyOpen} onCloseHistory={()=>setHistoryOpen(false)}
        history={<WorkbenchHistory record={record} runs={recentRuns} disabled={Boolean(busy||pending||conflict)}
          onRestoreVersion={restoreVersion} onForkVersion={revision=>void forkVersion(revision)} onRestoreRun={(source,onlyPrompt,version)=>void restoreRun(source,onlyPrompt,version)}
          draftRecovery={<ConversationDraftRecovery key={record.id} workspaceId={record.id} disabled={Boolean(busy||pending||pendingRecoveryBlocked)} onRestore={restoreLocalDraft} />} />}
        editor={<fieldset disabled={Boolean(busy||pending||conflict)} className="studio-editor-fields">
          <header className="conversation-studio__section-heading"><div><p className="conversation-muted">当前创作</p><h2>提示词</h2></div><span className="conversation-save-state">{local.positive.trim()?"可直接生成":"等待更新"}</span></header>
          <div className="conversation-studio__undo"><button disabled={!undoStack.current.length} onClick={()=>undoEdit()}>撤销</button><button disabled={!redoStack.current.length} onClick={()=>undoEdit(true)}>重做</button><span>{undoStack.current.length?"可撤销："+undoStack.current.at(-1)!.label:"修改会自动保留为草稿"}</span></div>
          {local.restoredFrom && <p className="conversation-studio__source">{local.restoredFrom}</p>}
          <div className="conversation-field-heading"><label htmlFor="conversation-positive">正向提示词</label><button className="conversation-copy" aria-label="复制正向提示词" disabled={!local.positive} onClick={()=>void copyPrompt("positive")}><Copy size={15} aria-hidden="true"/>{copied==="positive"?"已复制":"复制"}</button></div>
          <textarea id="conversation-positive" className="conversation-prompt" rows={8} maxLength={20000} value={local.positive} placeholder="更新后的英文提示词显示在这里，也可以直接输入。" onChange={event=>{setCopied("");edit({positive:event.target.value});}} />
          <p className="conversation-muted">生成图片使用这里的文字和下方选定的条件。</p>
          <details className="conversation-negative"><summary>负向提示词 <span>{local.negative.trim()?"已填写":"未使用"}</span></summary>
            <div className="conversation-field-heading"><label htmlFor="conversation-negative">负向提示词</label><button className="conversation-copy" aria-label="复制负向提示词" onClick={()=>void copyPrompt("negative")}>{copied==="negative"?"已复制":"复制"}</button></div>
            <textarea id="conversation-negative" className="conversation-prompt" rows={3} maxLength={20000} value={local.negative} onChange={event=>edit({negative:event.target.value})}/>
            <p className="conversation-muted">{negativeGuidance(local.model).note}</p>
            {negativeGuidance(local.model).text&&<button onClick={()=>edit({negative:appendNegative(local.negative,negativeGuidance(local.model).text)})}>补充模型负向建议</button>}
          </details>
          {lastChange&&<div className="conversation-studio__change"><span>最近一步</span><p>{lastChange.label}</p><details><summary>查看本次文字变化</summary><PromptChanges before={lastChange.before} after={lastChange.after}/></details></div>}
          <p className="conversation-muted">修改可撤销，历史图片会保留。</p>
        </fieldset>}
        results={<div ref={resultsPanel} className="studio-results-content">
          <header className="conversation-studio__section-heading"><div><p className="conversation-muted">看结果，再继续调整</p><h2>图片预览</h2></div><Link to="/generate">全部任务</Link></header>
          <WorkbenchImageResults record={record} local={local} runs={recentRuns} run={run} onSelectRun={setRun}
            disabled={Boolean(busy||pending||conflict||draftAtRisk)} onContinueRun={source=>void continueRun(source)} onRestoreRun={(source,onlyPrompt,version)=>void restoreRun(source,onlyPrompt,version)}/>
          {recentRuns.length>=runLimit&&runLimit<100&&<button onClick={()=>setRunLimit(value=>Math.min(100,value+20))}>加载更早图片</button>}
        </div>}
        settings={<fieldset disabled={Boolean(busy||pending||conflict)} className="studio-settings-fields">
                    <div className="conversation-settings-choices">

          <label>模型<select value={local.model} onChange={event => edit({model: event.target.value})}>{local.model === LEGACY_AESTHETIC && <option value={LEGACY_AESTHETIC} disabled>旧美学配置：请选择 v1.0 或 v1.1</option>}{profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.label}</option>)}</select></label>
            <label>执行目标<select value={target ? `${target.remote_profile_id}::${target.workflow_profile_id}` : ""} onChange={event => {
              const next = targets.find(item => `${item.remote_profile_id}::${item.workflow_profile_id}` === event.target.value);
              if (next) edit({settings: applyGenerationRecipe(local.settings, next, next.default_recipe_id)});
            }}><option value="">选择服务器与工作流</option>{targets.filter(item => item.compatible_model_profiles.includes(local.model)).map(item => <option key={`${item.remote_profile_id}::${item.workflow_profile_id}`} value={`${item.remote_profile_id}::${item.workflow_profile_id}`}>{targetRemoteLabel(item, targets)} / {targetLabel(item, targets)}</option>)}</select></label>
            <label>生成配方<select disabled={!target?.generation_recipes?.length} value={local.settings.preset_id} onChange={event => {if (target) edit({settings: applyGenerationRecipe(local.settings, target, event.target.value)});}}>
              {!target?.generation_recipes?.some(item => item.id === local.settings.preset_id) && <option value={local.settings.preset_id}>{local.settings.preset_id === "custom" ? "自定义参数" : "当前参数"}</option>}
              {target?.generation_recipes?.map(item => <option value={item.id} key={item.id}>{item.display_name}</option>)}
            </select></label>

          </div>
          <details id="panel-settings" className="conversation-advanced" >
            <summary><SlidersHorizontal size={17} aria-hidden="true" />尺寸、采样与 LoRA <span>{local.settings.width} × {local.settings.height} · {local.settings.batch_size} 张</span></summary>
            {target && <p className="conversation-muted">{targetDescription(target)}</p>}
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

          {!target&&<p className="conversation-muted"><Link to="/settings">配置生图服务器</Link> · 选择与当前模型兼容的工作流</p>}
          {target&&Boolean(availability?.resource_requirements?.length)&&<LoraMappingPanel key={JSON.stringify(availability?.resource_requirements)} remote={target.remote_profile_id} workflow={target.workflow_profile_id} resources={availability!.resource_requirements!} disabled={Boolean(busy||pending||conflict)} onSaved={()=>setMappingEpoch(value=>value+1)}/>}
        </fieldset>}
        composer={<div className="studio-composer">
          <div className="conversation-field-heading"><label htmlFor="conversation-delta">这次想怎么改？</label><span className="conversation-muted">{local.delta.trim()?"意见尚未应用；直接生图仍使用当前提示词":"输入修改意见，再更新提示词"}</span></div>
          <div className="conversation-studio__composer-row"><textarea id="conversation-delta" rows={2} maxLength={4000} value={local.delta} disabled={Boolean(pending||conflict)} onChange={event=>edit({delta:event.target.value})} placeholder="描述人物、动作、场景，或这次希望改变的地方"/>
            <div className="conversation-studio__buttons">
              <button className="conversation-update" disabled={Boolean(busy||pending||pendingRecoveryBlocked||proposal||conflict||llmUnavailableReason||adviceBusy)||(!local.delta.trim()&&!canCompileRequirements&&!local.positive.trim())} onClick={()=>void turn(!local.delta.trim())}>更新提示词</button>
              <button className="conversation-generate" aria-describedby="conversation-generation-reason" disabled={Boolean(generationReason)} onClick={()=>void generate()}>生成图片</button>
              <button className="conversation-studio__combined" disabled={Boolean(executionReason||proposal||llmUnavailableReason||adviceBusy)||!local.delta.trim()} onClick={()=>void turn(false,true)}>更新并生图</button>
            </div>
          </div>
          <div className="conversation-studio__composer-meta"><label>改写方式<select disabled={Boolean(busy||pending||conflict)} value={local.mode} onChange={event=>edit({mode:event.target.value as LocalConversation["mode"]})}><option value="faithful">忠实还原</option><option value="expand">适度扩写</option></select></label>
            <Link to="/references">从参考借用</Link>
            <details className="studio-llm-options"><summary>改词模型 · {thinking.current?.model||"尚未配置"}</summary>              <div className="conversation-thinking-control">
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
</details>
            <span role="status" id="conversation-generation-reason" className="conversation-muted">{generationReason||"当前提示词和条件可直接生成"}</span>
          </div>
          {llmUnavailableReason&&<p className="conversation-warning">{llmUnavailableReason}<button onClick={()=>setShowLlmSettings(true)}>配置改词模型</button></p>}
        </div>}
        auxiliary={<fieldset disabled={Boolean(busy||pending||conflict)}>
          <details className="conversation-supporting-controls"><summary>角色、画师与画面设计</summary>          <ManualIdentityTags key={record.id} compact modelProfileId={local.model} characters={local.requirements.layers.subject.character_tags || []} series={local.requirements.layers.subject.series_tags || []}
            artists={local.requirements.layers.style.manual_artist_tags || []} onCharacters={character_tags => layer("subject", {character_tags})}
            onSeries={series_tags => layer("subject", {series_tags})} onArtists={manual_artist_tags => layer("style", {manual_artist_tags})} />
            <SceneDesignControls requirements={local.requirements} onChange={requirements => edit({requirements})}
              workspaceId={record.id} workspaceRevision={record.revision} delta={local.delta}
              positive={local.positive} negative={local.negative} disabled={Boolean(busy || pending || conflict)}
              adviceDisabledReason={llmUnavailableReason} llmContextKey={llmContextKey} onBusyChange={setAdviceBusy} />
</details>
          <details><summary>分层画面要求与锁定</summary>          <div aria-label="明确选择的普通标签"><strong>已选普通标签 · {(local.requirements.layers.subject.general_tags || []).length} / 64</strong>
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
</details>
          <PromptLocks key={"locks:"+record.id} positive={local.positive} negative={local.negative} locks={local.requirements.prompt_locks||[]} onChange={prompt_locks=>edit({requirements:{...local.requirements,prompt_locks}})}/>
          <ArtistRecommendations key={"artists:"+record.id} prompt={local.positive} selected={local.requirements.layers.style.artists} disabled={Boolean(busy||pending||conflict)} onChange={artists=>layer("style",{artists})}/>
          {(promptChanged||record.draft.compiled?.source==="user"&&!record.draft.compiled.requirements_synced)&&<button disabled={Boolean(busy||proposal||llmUnavailableReason||adviceBusy||local.delta.trim()||!local.positive.trim())} onClick={()=>void syncRequirements()}>按手工提示词同步画面要求</button>}
          <button disabled={!dirty||conflict||Boolean(promptChanged&&!local.positive.trim())} onClick={()=>void act("保存当前版本",async()=>{await save();setNotice("当前内容已保存。");})}>保存当前版本</button>
          {record.draft.workspace_origin&&<button onClick={()=>void open(record.draft.workspace_origin!.workspace_id)}>打开来源会话</button>}
          {record.draft.reference_pin&&<Link to={"/references?example="+record.draft.reference_pin.example_id}>查看参考来源</Link>}
          {local.workflowSnapshotRunId&&<><p>沿用历史工作流快照。切换模型或工作流会改用所选模板。</p><button onClick={()=>edit({workflowSnapshotRunId:null})}>改用当前工作流模板</button></>}
        </fieldset>}
      />
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
