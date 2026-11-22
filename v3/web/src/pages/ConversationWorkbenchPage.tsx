import {GenerationSettingsPanel} from "../components/GenerationSettingsPanel";
import {CloudModelCatalogPanel} from "../components/CloudModelCatalogPanel";
import {PromptTranslationPreview} from "../components/PromptTranslationPreview";
import {PromptToolsSheet} from "../components/PromptToolsSheet";
import ExecutionEnvironmentControl from "../components/ExecutionEnvironmentControl";
import {configurationFromSettings, settingsFromConfiguration, resolveConfiguration, configurationToGenerationPayload} from "../lib/creationConfiguration";
import {schemaForTarget} from "../lib/workflowParameterSchema";
import {declaredIdentityTags, missingIdentityTags, overlayIdentityTags} from "../lib/identityPrompt";
import {createGenerationIntent, getGenerationIntent, retryGenerationIntent, cancelGenerationIntent, confirmEnvironmentAssets, markEnvironmentRebuilt, type GenerationIntentRequest, type GenerationIntentRecord} from "../lib/generationIntents";
import type {ExecutionPolicy} from "../lib/types";
import {ImagePreview} from "../components/ImagePreview";
import {useEditorHistory} from "../lib/useEditorHistory";
import {operationBetween} from "../lib/editorHistory";
import {saveEditorBundle,readLatestEditorBundle} from "../lib/editorHistoryStore";
import {restoreContent} from "../lib/restoreScope";
import {readDirectImport,acknowledgeDirectImport} from "../lib/directPrompt";
import {PersonalPromptTransfer as PersonalPromptTransferPanel} from "../components/PersonalPromptTransfer";
import {consumePersonalPromptTransfer, readPersonalPromptTransfer, type PersonalPromptTransfer, type PersonalPromptResult} from "../lib/personalPromptTransfer";
import {ArtistRecommendations} from "../components/ArtistRecommendations";
import {ArtistPresetPicker} from "../components/ArtistPresetPicker";
import {applyArtistPreset, removeArtistPreset, reconcileArtistPresetEdit, reconcileArtistPresetCompiled, type ArtistPresetSnapshot} from "../lib/artistPresetApplication";
import {SceneDesignControls} from "../components/SceneDesignControls";
import {sceneFields, sceneChoice} from "../lib/sceneDesign";
import {ManualIdentityTags} from "../components/ManualIdentityTags";
import {GenerationAssessment} from "../components/GenerationAssessment";
import {loadGallery} from "../lib/galleryStore";
import type {GalleryAsset} from "../lib/types";
import {useEffect, useRef, useState} from "react";
import {Link, useNavigate, useSearchParams} from "react-router-dom";
import {isAnimaModel, workbenchPathForModel, workspaceUrl} from "../lib/workbenchRoute";
import {ChatCircleDots, Check, Copy, GearSix, ImageSquare, PaperPlaneRight, Plus, SlidersHorizontal, Sparkle} from "@phosphor-icons/react";
import {apiRequest, ApiClientError} from "../lib/api";
import {seedInput, validSeed, changeGenerationModel, defaultGenerationSettings, inactiveModelConfigurations} from "../lib/generationSettings";
import {defaultTarget, targetReady, targetLabel, targetDescription} from "../lib/workflowTargets";
import {modelProfileChoices, LEGACY_AESTHETIC, resolveLegacyAesthetic} from "../lib/modelProfiles";
import {negativeGuidance, appendNegative} from "../lib/negativeGuidance";
import {cleanRequirements, editableRequirements, emptyRequirements, hasUncompiledInputs, hasUnsavedInputs, layerLabels, normalizeIdentityTags} from "../lib/conversation";
import {applySelectedContent, consumeTransfer, readTransfer, undoSelectedContent, type ContentTransfer, type SelectedContent} from "../lib/contentTransfer";
import "./conversationWorkbench.css";
import {ConversationStudioView} from "../components/ConversationStudioView";
import {ConflictPanel, LayerRequirementsEditor, PendingSubmissionPanel, WorkbenchHeader} from "../components/ConversationWorkbenchSections";
import {LoraResources} from "../components/LoraResources";
import {useLoraPreparation} from "../lib/loraLibrary";
import {RewriteModeSelector} from "../components/RewriteModeSelector";
import {WorkbenchHistory} from "../components/WorkbenchHistory";
import {WorkbenchImageResults} from "../components/WorkbenchImageResults";
import {type WorkbenchHistoryVersion, canRestoreRun, notifyEditorHistoryChanged} from "../lib/workbenchHistory";
import {LlmSettingsPanel} from "../components/LlmSettingsPanel";
import {useWorkbenchThinking} from "../lib/useWorkbenchThinking";
import {ConversationReview, PromptChanges, isPromptPreview, type ConversationProposal} from "../components/ConversationReview";
import {ConversationVersions} from "../components/ConversationVersions";
import {PromptLocks} from "../components/PromptLocks";
import {GenerationComparison} from "../components/GenerationComparison";
import {ConversationDraftRecovery} from "../components/ConversationDraftRecovery";
import {getConversationTabId,getConversationRecoveryDocumentIds,readConversationDraft, saveConversationDraft, initializeConversationTab, recoverConversationPending, saveConversationPending, clearConversationPending, recoverConversationBranch, saveConversationBranch, clearConversationBranch, preserveConversationDraft, readConversationDraftCandidate, ConversationRequestSettledError, type ConversationDraftCandidate} from "../lib/conversationDrafts";
import {mergeConversation, resolveConversationConflicts} from "../lib/conversationMerge";
import {migrateWorkflowSnapshot, reconcileWorkflowSnapshot} from "../lib/conversationSnapshot";
import {LoraMappingPanel, type ResourceIdentity} from "./LoraMappingPanel";
import type {ConversationRecord, LayerName, LocalConversation, RequirementLayers} from "../lib/conversation";
import type {CreationConfiguration, GenerationRunRecord, GenerationTarget, GenerationTargetListResponse, ModelProfileOption, WorkflowParameterSchema, WorkspaceListResponse} from "../lib/types";

const ACTIVE = "anima-conversation-active";
type Pending = {key: string; body: string};
type Accepted = GenerationRunRecord & {workspace_revision: number; compiled_token: string};
function validRunReceipt(run:GenerationRunRecord|null|undefined){
  return typeof run?.id==="string"&&Boolean(run.id.trim())&&["draft","connecting","preparing","queued","running","downloading","completed","failed","canceled","remote_missing"].includes(run.state);
}
const directRecoveryPrefix=(workspaceId:string)=>`anima-conversation-direct-recovery:${encodeURIComponent(workspaceId)}:`;
function directRecoveries(workspaceId:string):Pending[]{
  const items:Pending[]=[];
  try{for(let index=0;index<localStorage.length;index++){
    const key=localStorage.key(index);if(!key?.startsWith(directRecoveryPrefix(workspaceId)))continue;
    const request=JSON.parse(localStorage.getItem(key)||"null") as Pending|null;
    if(!request?.key||typeof request.body!=="string")continue;
    const body=JSON.parse(request.body);
    if(body.workspace_id===workspaceId&&body.submission_kind==="conversational"&&!body.creationConfiguration)items.push(request);
  }}catch{/* Keep unreadable records on disk without locking the editor. */}
  return items;
}
const definitiveDirectRejections=new Set(["direct_preparation_timeout","rate_limited","queue_full","invalid_request","invalid_idempotency_key",
  "unauthorized","forbidden","session_invalid","remote_not_configured","remote_profile_not_found","remote_profile_disabled","v2_runtime_missing","submission_store_missing",
  "lora_not_installed","missing_lora","lora_unmapped","unknown","protected_prompt_changed","workflow_incompatible","incompatible_workflow","incompatible_model",
  "reference_preset_unavailable","reference_preset_not_found","mapping_revision_conflict","stale_compiled_prompt","workflow_snapshot_missing","gallery_source_changed","workspace_not_found","workspace_revision_conflict"]);
function read<T>(key: string): T | null {try {return JSON.parse(localStorage.getItem(key) || "null") as T | null;} catch {return null;}}
function write(key: string, value: unknown) {try {localStorage.setItem(key, JSON.stringify(value));} catch { /* Server remains authoritative. */ }}
function remove(key: string) {try {localStorage.removeItem(key);} catch { /* Best effort. */ }}
function localFrom(record: ConversationRecord): LocalConversation {
  return reconcileArtistPresetCompiled({baseRevision: record.revision, delta: "", requirements: editableRequirements(record), mode: record.draft.mode,
    positive: record.draft.compiled?.positive || "", negative: record.draft.compiled?.negative || "",
    model: record.draft.model_profile, settings: record.draft.generation_settings || defaultGenerationSettings(), workflowSnapshotRunId: record.draft.generation_source?.run_id || null});
}
function hasSavedWorkflowSnapshot(value:LocalConversation,configuration:CreationConfiguration,schema:WorkflowParameterSchema) {
  return Boolean(value.workflowSnapshotRunId && value.settings.parameter_schema
    && configuration.modelProfile===value.model
    && configuration.workflow.id===schema.workflowId && configuration.workflow.revision===schema.templateRevision);
}
function creationFor(value:LocalConversation,target?:GenerationTarget) {
  const preserveSnapshot=Boolean(value.workflowSnapshotRunId);
  const schema=preserveSnapshot&&value.settings.parameter_schema?value.settings.parameter_schema:schemaForTarget(target);
  const configuration={...configurationFromSettings(value.settings,value.model,target,{preserveSnapshot}),resourceRequirements:value.requirements.loras};
  return {schema,configuration,resolved:resolveConfiguration(configuration,schema)};
}
function targetForCreation(value:LocalConversation,targets:GenerationTarget[]) {
  if(value.model===LEGACY_AESTHETIC)return undefined;
  const compatible=targets.filter(item=>item.compatible_model_profiles.includes(value.model));
  const workflowId=value.settings.creation_configuration?.workflow.id??value.settings.workflow_profile_id;
  return compatible.find(item=>item.workflow_profile_id===workflowId)
    ||(!workflowId?defaultTarget(compatible):undefined);
}

function newModelSettings(model:string, targets:GenerationTarget[]) {
  const target=defaultTarget(targets.filter(item=>item.compatible_model_profiles.includes(model)));
  return changeGenerationModel(defaultGenerationSettings(),target,model);
}

export function ConversationWorkbenchPage({modelProfiles, remoteEnabled = false}: {modelProfiles?: ModelProfileOption[]; remoteEnabled?: boolean}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
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
  const [resultRequestKey,setResultRequestKey]=useState<string>();
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
  const editorHistory=useEditorHistory();
  const documentId=useRef(crypto.randomUUID());
  const editorEpoch=useRef(0);
  const activeEditorContext=useRef<{workspaceId:string;token:string}|null>(null);
  const checkpointTimer=useRef<ReturnType<typeof setTimeout>|null>(null);
  const syncingCheckpoints=useRef(new Set<string>());
  const directAttempt=useRef(false);
  const rawAttempt=useRef(false);
  const [rawRetry,setRawRetry]=useState(0);
  const lastEdit = useRef({keys: "", at: 0});
  const [, setUndoEpoch] = useState(0);
  const [workspaces, setWorkspaces] = useState<WorkspaceListResponse["items"]>([]);
  const [targets, setTargets] = useState<GenerationTarget[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [retryTurn, setRetryTurn] = useState(false);
  const [retryTask, setRetryTask] = useState<"rewrite" | "sync_requirements" | "bold_rewrite">("rewrite");
  const [showLlmSettings, setShowLlmSettings] = useState(false);
  const thinking = useWorkbenchThinking();
  const [llmSettingsBusy, setLlmSettingsBusy] = useState(false);
  const [adviceBusy, setAdviceBusy] = useState(false);
  const llmUnavailableReason = thinking.unavailableReason || (llmSettingsBusy ? "正在保存或测试 LLM 配置…" : "");
  const llmContextKey = JSON.stringify([thinking.current?.service, thinking.current?.model, thinking.enabled]);
  const [inspectorTab, setInspectorTab] = useState<"prompt" | "requirements" | "settings">("prompt");
  const [parameterRequestKey, setParameterRequestKey] = useState(0);
  const [parameterEditsPending, setParameterEditsPending] = useState(false);
  useEffect(() => {
    if (inspectorTab !== "settings") return;
    const frame = window.requestAnimationFrame(() => {
      document.getElementById("panel-settings")?.scrollIntoView?.({block: "start", behavior: "instant"});
    });
    return () => window.cancelAnimationFrame(frame);
  }, [inspectorTab]);
  const [idea, setIdea] = useState("");
  const [initialMode, setInitialMode] = useState<LocalConversation["mode"]>("faithful");
  const [copied, setCopied] = useState("");
  const [conflict, setConflict] = useState(false);
  const [pending, setPendingState] = useState<Pending | null>(null);
  const pendingRef=useRef<Pending|null>(null);
  function setPending(value:Pending|null){pendingRef.current=value;setPendingState(value);}
  const [pendingRecoveryBlocked, setPendingRecoveryBlocked] = useState(false);
  const [optionalRequests,setOptionalRequests]=useState<Pending[]>([]);
  useEffect(()=>{setOptionalRequests(record?directRecoveries(record.id):[]);},[record?.id]);
  const [run, setRun] = useState<GenerationRunRecord | null>(null);
  const [recentRuns, setRecentRuns] = useState<GenerationRunRecord[]>([]);
  const [runLimit, setRunLimit] = useState(20);
  const [availability, setAvailability] = useState<{availability: string; message?: string; resource_requirements?: ResourceIdentity[]} | null>(null);
  const [mappingEpoch, setMappingEpoch] = useState(0);
  const [resourceCheck, setResourceCheck] = useState(false);
  const [generationIntent, setGenerationIntent] = useState<(GenerationIntentRecord & {clientRequestKey:string}) | null>(null);
  const opening = useRef(0);
  const requestLock = useRef(false);
  const mounted = useRef(true);
  const resultsPanel = useRef<HTMLDivElement>(null);
  const availableProfiles=modelProfileChoices(modelProfiles);
  const activeModelIds=new Set(targets.flatMap(item=>item.compatible_model_profiles));
  const activeProfiles=availableProfiles.filter(profile=>activeModelIds.has(profile.id)||profile.id===local?.model);
  const profiles=remoteEnabled&&targets.length&&activeProfiles.length?activeProfiles:availableProfiles;
  useEffect(() => {
    if (!busy) {setElapsed(0); return;}
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [busy]);
  useEffect(() => {
    if (!local || local.workflowSnapshotRunId || pending || busy) return;
    const legacy = resolveLegacyAesthetic(local.model, local.settings, targets);
    if (legacy) edit({model:legacy.model}, legacy.target);
  }, [local, targets, pending, busy]);

  function persistDraft(id: string, value: LocalConversation, original = base.current) {
    const journal=editorHistory.journal.current?.workspaceId===id?editorHistory.journal.current:undefined;
    const result = draftPersistenceBlocked.current === id
      ? {ok:false,warning:"原始草稿恢复记录已保留；请导出损坏记录并保存当前版本。本机持久副本继续保留编辑。"}
      : saveConversationDraft(id, value, original,undefined,journal);
    setStorageWarning(result.warning || "");
    if(journal&&typeof indexedDB!=="undefined")void saveEditorBundle({schemaVersion:1,workspaceId:id,documentId:getConversationTabId(),local:value,base:original,journal:structuredClone(journal),savedAt:Date.now()}).catch(()=>{if(mounted.current)setStorageWarning("编辑已保留在浏览器恢复副本中；IndexedDB 写入失败，请保留本页并导出重要内容。");});
    if(result.ok&&journal?.outbox.length){if(checkpointTimer.current)clearTimeout(checkpointTimer.current);checkpointTimer.current=setTimeout(()=>void syncCheckpoints(id),850);}
    return result.ok;
  }
  async function syncCheckpoints(id:string){
    if(syncingCheckpoints.current.has(id))return;syncingCheckpoints.current.add(id);lastEdit.current={keys:"",at:0};
    try{for(const operation of [...(editorHistory.journal.current?.workspaceId===id?editorHistory.journal.current.outbox:[])]){
      await apiRequest(`/api/v3/workspaces/${encodeURIComponent(id)}/checkpoints`,{method:"POST",body:JSON.stringify({operation_id:operation.id,base_revision:operation.baseRevision,kind:operation.kind,label:operation.label,snapshot:operation.snapshot,source:{editor_epoch:operation.editorEpoch,document_id:operation.documentId||documentId.current}})});
      const journal=editorHistory.journal.current;if(journal?.workspaceId!==id)return;
      journal.outbox=journal.outbox.filter(item=>item.id!==operation.id);
      if(localRef.current){saveConversationDraft(id,localRef.current,base.current,undefined,journal);if(typeof indexedDB!=="undefined")void saveEditorBundle({schemaVersion:1,workspaceId:id,documentId:getConversationTabId(),local:localRef.current,base:base.current,journal:structuredClone(journal),savedAt:Date.now()}).catch(()=>{});}
      notifyEditorHistoryChanged(id);
    }}catch{/* Immutable outbox remains available for reconnect/reload retry. */}finally{syncingCheckpoints.current.delete(id);}
  }
  function invalidateEditor(){
    editorEpoch.current++;turnController.current?.abort();
    const context=activeEditorContext.current;activeEditorContext.current=null;
    if(context)void apiRequest(`/api/v3/workspaces/${encodeURIComponent(context.workspaceId)}/editor-context/${encodeURIComponent(documentId.current)}?expected_token=${encodeURIComponent(context.token)}`,{method:"DELETE",keepalive:true}).catch(()=>{});
  }
  function restoreLocalDraft(candidate: ConversationDraftCandidate): boolean {
    if (!record || !local || busy || pending || proposal || pendingRecoveryBlocked) return false;
    const latest = readConversationDraftCandidate(record.id, candidate.key);
    if (!latest?.local || latest.raw !== candidate.raw) {
      setError("所选草稿已变化或无法读取，请刷新草稿列表并重新预览。"); return false;
    }
    if (!isAnimaModel(latest.local.model,modelProfiles)) {
      setError("所选草稿属于其他工作台，已保留在本地备份中。"); return false;
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
    rememberEdit(local, "恢复草稿", value,"restore");persistDraft(record.id,value,original);invalidateEditor();
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
      if(editorHistory.journal.current?.workspaceId!==next.id){invalidateEditor();editorHistory.initialize(next.id,documentId.current);}
      lastEdit.current = {keys: "", at: 0};
      base.current = value;
      setLocal(value);
      persistDraft(next.id, value, value);
      setConflict(false);
      setConflictChoices({});
    }
  }

  function openOtherWorkbench(next:ConversationRecord, replace=false) {
    if (!mounted.current) return true;
    if (isAnimaModel(next.draft.model_profile,modelProfiles)) return false;
    navigate(workspaceUrl(next,modelProfiles),{replace});
    return true;
  }

  async function open(id: string, restoreLast=false) {
    const resumeProposalLoad = current.current?.id === id && openedWorkspace.current !== id;
    if (draftAtRisk && !resumeProposalLoad) return false;
    const sequence = ++opening.current;
    let recoveredDraft = true;
    openedWorkspace.current = null; setInitialLoaded(false);
    setBusy("打开工作台"); setError("");
    try {
      // A partial open already restored local edits. Retry only the missing proposal read.
      if (!resumeProposalLoad) {
        const next = await apiRequest<ConversationRecord>(`/api/v3/workspaces/${encodeURIComponent(id)}`);
        if (!mounted.current || sequence !== opening.current) return false;
        if (restoreLast && !isAnimaModel(next.draft.model_profile,modelProfiles)) {
          if (read<string>(ACTIVE)===id) remove(ACTIVE);
          return true;
        }
        if (openOtherWorkbench(next,true)) return false;
        let recovered = readConversationDraft(id);
        if(typeof indexedDB!=="undefined"){
          try {
            const bundle=await readLatestEditorBundle(id,getConversationRecoveryDocumentIds());
            if(bundle&&(!recovered?.local||(recovered.savedAt!==undefined&&bundle.savedAt>recovered.savedAt))){
              recovered={...recovered,local:bundle.local,base:bundle.base??null,editorJournal:bundle.journal,savedAt:bundle.savedAt,warning:recovered?.warning||""};
            }
          } catch { /* Keep the validated browser draft; do not overwrite a damaged backup. */ }
          if(!mounted.current||sequence!==opening.current)return false;
        }
        let recoveryNotice="";
        if (recovered?.local && !isAnimaModel(recovered.local.model,modelProfiles)) {
          const backup=preserveConversationDraft(id,recovered.local,recovered.base);
          if (!backup.ok) throw new Error(backup.warning || "无法备份旧工作台草稿。");
          recovered=null;
          recoveryNotice="已打开原会话。其他模型的旧编辑已保留在「找回本地草稿」里。";
        }
        draftPersistenceBlocked.current = recovered?.persistenceBlocked ? id : null;
        recoveredDraft = Boolean(recovered?.local);
        setInvalidDraftRaw(recovered?.invalidRaw || "");
        adopt(next);
        editorHistory.initialize(id,documentId.current,recovered?.editorJournal);
        setWorkspaces(items => items.some(item => item.id === next.id) ? items : [next, ...items]);
        if (recovered?.local) {
          const value = migrateWorkflowSnapshot(recovered.local, next);
          const original = recovered.base ? migrateWorkflowSnapshot(recovered.base, next) : value.baseRevision === next.revision ? localFrom(next) : null;
          const untouched = original && JSON.stringify({...value, delta: ""}) === JSON.stringify({...original, delta: ""});
          if (untouched) {
            if (value.baseRevision !== next.revision) {
              preserveConversationDraft(id,value,original);
              const journal=editorHistory.journal.current;
              if(journal){journal.archived.push(...journal.entries);journal.entries=[];journal.cursor=0;journal.editorEpoch++;journal.baseFingerprint=JSON.stringify(localFrom(next));}
            }
            const kept = {...localFrom(next), delta: value.delta}; setLocal(kept); persistDraft(id, kept, localFrom(next));
          } else {
            base.current = original; setLocal(value); persistDraft(id, value, original);
            setConflict(value.baseRevision !== next.revision);
          }
        }
        if (recovered?.warning) setStorageWarning(recovered.warning);
        setPendingRecoveryBlocked(false);
        try {setPending(recoverConversationPending(id));} catch (caught) {setPending(null); setPendingRecoveryBlocked(true); setError((caught as Error).message);}
        setRun(null); setGenerationIntent(null); setResourceCheck(false); setRecentRuns([]); setRunLimit(20); setAvailability(null); setProposal(null); setNotice(recoveryNotice); setRename(null);
      }
      const review = await apiRequest<{proposal: ConversationProposal | null}>(`/api/v3/workspaces/${encodeURIComponent(id)}/proposal`);
      if (!mounted.current || sequence !== opening.current) return false;
      setProposal(review.proposal || null);
      if(review.proposal && isPromptPreview(review.proposal)){
        setActiveView("prompt");
        const value = localRef.current;
        if(!recoveredDraft && value && !value.delta){
          const restored = {...value, delta: review.proposal.draft.conversation_events.at(-1)?.delta || ""};
          setLocal(restored);persistDraft(id, restored);
        }
      }
      openedWorkspace.current = id; setInitialLoaded(true);
      write(ACTIVE, id);
      if (requestedWorkspace && requestedWorkspace !== id) clearWorkspaceLink();
      return true;
    } catch (caught) {if (mounted.current && sequence === opening.current) setError((caught as Error).message); return false;}
    finally {if (mounted.current && sequence === opening.current) setBusy("");}
  }

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    const {signal} = controller;
    setInitialLoaded(false);
    void initializeConversationTab().then(async () => {
      if (signal.aborted || !mounted.current) return;
      const result = await apiRequest<WorkspaceListResponse>("/api/v3/workspaces?limit=50", {signal});
      if (signal.aborted || !mounted.current) return;
      setWorkspaces(result.items);
      setMoreSessions(result.items.length === 50);
      const id = requestedWorkspace || read<string>(ACTIVE);
      // Adopting the workspace alone does not confirm whether a proposal is pending.
      const opened = !id || (current.current?.id === id && openedWorkspace.current === id) || await open(id,!requestedWorkspace);
      if (!signal.aborted && mounted.current && opened) setInitialLoaded(true);
    }).catch(caught => {if (!signal.aborted && mounted.current) setError((caught as Error).message);});
    if (remoteEnabled) void apiRequest<GenerationTargetListResponse>("/api/v3/generation-targets",{signal}).then(result => {
      if (!signal.aborted && mounted.current) setTargets(result.items);
    }).catch(caught => {if (!signal.aborted && mounted.current) setError((caught as Error).message);});
    return () => {controller.abort();invalidateEditor();if(checkpointTimer.current)clearTimeout(checkpointTimer.current);mounted.current = false; opening.current++;};
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

  useEffect(()=>{
    if(searchParams.get("from")!=="direct"||!initialLoaded||busy||pending||conflict||directAttempt.current)return;
    directAttempt.current=true;
    void act("导入原文",async()=>{
      const payload=readDirectImport();if(!payload){setNotice("原文导入已完成，或没有待导入内容。");return;}
      if(current.current&&localRef.current){const backup=preserveConversationDraft(current.current.id,localRef.current,base.current);if(!backup.ok)throw new Error(backup.warning);}
      let key=payload.import_id||sessionStorage.getItem("anima-v3-direct-import-request");if(!key){key=crypto.randomUUID();sessionStorage.setItem("anima-v3-direct-import-request",key);}
      const currentDraft=localRef.current;
      const model=payload.model_profile||currentDraft?.model||profiles[0].id;
      const destination=workbenchPathForModel(model,modelProfiles);
      const settings=payload.generation_settings||(currentDraft?.model===model?currentDraft.settings:destination==="/workbench"?newModelSettings(model,targets):undefined);
      const next=await apiRequest<ConversationRecord>("/api/v3/workspaces",{method:"POST",headers:{"Idempotency-Key":`direct-import:${key}`},body:JSON.stringify({title:payload.title||payload.positive_text.trim().slice(0,40)||"原文创作",draft:{positive_text:payload.positive_text,excluded_text:payload.excluded_text,mode:"faithful",model_profile:model,generation_settings:settings,...(payload.english_positive.trim()?{prompt_edit:{positive:payload.english_positive,negative:payload.english_negative}}:{})}})});
      if(!mounted.current)return;
      if (openOtherWorkbench(next,true)) {
        acknowledgeDirectImport(payload,next.id);sessionStorage.removeItem("anima-v3-direct-import-request");
        return;
      }
      adopt(next);const original=localFrom(next);
      const imported=payload.allow_empty?{...original,positive:payload.english_positive,negative:payload.english_negative}:original;
      setLocal(imported);
      if(!persistDraft(next.id,imported,original))throw new Error("原文已保存至服务端，浏览器草稿未写入；导入记录已保留，可重试。");
      acknowledgeDirectImport(payload,next.id);sessionStorage.removeItem("anima-v3-direct-import-request");write(ACTIVE,next.id);
      setWorkspaces(items=>[next,...items.filter(item=>item.id!==next.id)]);setActiveView("prompt");setInspectorTab("prompt");
      setNotice(payload.english_positive.trim()?"已将英文原文载入工作台；中文对照保留在会话来源，未调用 AI，也未生成图片。":"已恢复原文草稿的项目与生成条件，可直接输入英文提示词；未调用 AI，也未生成图片。");
      setSearchParams(previous=>{const next=new URLSearchParams(previous);next.delete("from");next.set("workspace",imported?current.current!.id:"");return next;},{replace:true});
    });
  },[initialLoaded,busy,pending,conflict,searchParams]);

  useEffect(()=>{
    if(searchParams.get("entry")!=="raw"||!initialLoaded||busy||pending||conflict||rawAttempt.current)return;
    rawAttempt.current=true;
    void create("",true).then(created=>{if(!created||!mounted.current)return;setSearchParams(previous=>{const next=new URLSearchParams(previous);next.delete("entry");return next;},{replace:true});setNotice("可直接输入英文提示词并生成图片，无需配置改词模型。");});
  },[initialLoaded,busy,pending,conflict,searchParams,rawRetry]);

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
        const model=profiles.find(item=>item.id==="anima_aesthetic_v1_1")?.id || profiles[0].id;
        const body = read<string>(key) || JSON.stringify({title: "个人提示词", draft: {
          model_profile:model, generation_settings:newModelSettings(model,targets)}});
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
        const model=local?.model || profiles.find(p=>p.id==="anima_aesthetic_v1_1")?.id || profiles[0].id;
        const body = read<string>(creationKey) || JSON.stringify({
          title: transfer.items.map(item => item.name).join("、").slice(0, 40), draft: {
            model_profile:model, requirements_edit:initial.requirements, generation_settings:local?.settings || newModelSettings(model,targets)}});
        localStorage.setItem(creationKey, JSON.stringify(body));
        next = await apiRequest<ConversationRecord>("/api/v3/workspaces", {method: "POST", body,
          headers: {"Idempotency-Key": transfer.id}});
        value = localFrom(next);
        value=reconcileArtistPresetEdit(value,{...value,positive:overlayIdentityTags(value.positive,value.requirements,emptyRequirements())});
        // The server already saved these tags; retain the additions for undo.
        setTransferNotice({workspace: next.id, added: initial.added});
        adopt(next);setLocal(value);persistDraft(next.id,value,localFrom(next));write(ACTIVE, next.id); setWorkspaces(items => [next!, ...items]);
        setPending(null); setRun(null); setRecentRuns([]); setProposal(null); setAvailability(null);
        if (requestedWorkspace) clearWorkspaceLink();
      } else {
        const result = applySelectedContent(value.requirements, transfer.items);
        value = reconcileArtistPresetEdit(value,{...value, requirements: result.requirements,
          positive:overlayIdentityTags(value.positive,result.requirements,value.requirements)});
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
  const compatibleTargets = targets.filter(item => item.compatible_model_profiles.includes(local?.model || ""));
  const workflows = compatibleTargets.filter((item,index,items)=>items.findIndex(other=>other.workflow_profile_id===item.workflow_profile_id)===index);
  const target = local ? targetForCreation(local,targets) : undefined;
  const creation = local ? creationFor(local,target) : null;
  const parameterSchema = creation?.schema || schemaForTarget(target);
  const configuration = creation?.configuration || null;
  const savedWorkflowSnapshot = Boolean(local && configuration && hasSavedWorkflowSnapshot(local,configuration,parameterSchema));
  const executionPolicy:ExecutionPolicy = local?.settings.execution_policy || (local?.settings.remote_profile_id
    ? {mode:"pinned",environmentId:local.settings.remote_profile_id} : {mode:"auto",preferredEnvironmentIds:[]});
  const editableTemplates = compatibleTargets.filter(item=>item.template_revision && item.availability!=="disabled"
    && (item.lora_extension_supported!==false || Boolean(item.lora_slot_order?.length))
    && (executionPolicy.mode!=="pinned" || item.remote_profile_id===executionPolicy.environmentId));
  const currentTemplate = target && editableTemplates.includes(target) ? target : undefined;
  const currentWorkflowTarget = currentTemplate && targetReady(currentTemplate) ? currentTemplate : defaultTarget(editableTemplates) || currentTemplate;
  const resolvedConfiguration = creation?.resolved;
  const configurationValid = !resolvedConfiguration || resolvedConfiguration.valid;
  const fixedIdentityTags=local?declaredIdentityTags(local.requirements):[];
  const missingFixedTags=local?missingIdentityTags(local.positive,fixedIdentityTags):[];
  const identitySelectionChanged=Boolean(record&&JSON.stringify(fixedIdentityTags)!==JSON.stringify(declaredIdentityTags(editableRequirements(record))));
  const explicitEmptyTagSelection=Boolean(record&&local&&local.positive===""&&identitySelectionChanged
    &&local.negative===(record.draft.compiled?.negative||"")
    &&overlayIdentityTags(record.draft.compiled?.positive||"",local.requirements,editableRequirements(record))==="");
  const unsavedEmptyPrompt=Boolean(record && local && !local.positive.trim() && !explicitEmptyTagSelection
    && (record.draft.compiled?.positive.trim() || local.negative!==(record.draft.compiled?.negative||"")));
  const environments = targets.filter((item,index,items)=>items.findIndex(other=>other.remote_profile_id===item.remote_profile_id)===index)
    .map(item=>({id:item.remote_profile_id,display_name:item.remote_display_name,address:item.connection_type==="http"?item.remote_http_base_url||undefined:item.remote_ssh_host || item.remote_comfy_host}));
  const loraTarget=executionPolicy.mode==="pinned"?executionPolicy.environmentId:
    executionPolicy.preferredEnvironmentIds.find(id=>compatibleTargets.some(t=>t.remote_profile_id===id&&t.workflow_profile_id===target?.workflow_profile_id)) || target?.remote_profile_id;
  const loraPrep=useLoraPreparation(remoteEnabled?loraTarget:undefined,local?.requirements.loras || []);

  useEffect(() => {
    if (!resourceCheck || !record || !target || inputsDirty || conflict) {setAvailability(null); return;}
    const controller = new AbortController();
    setAvailability(null);
    const query = new URLSearchParams({workspace_id: record.id, revision: String(record.revision),
      remote_profile_id: executionPolicy.mode==="pinned"?executionPolicy.environmentId:target.remote_profile_id, workflow_profile_id: target.workflow_profile_id});
    if (local?.workflowSnapshotRunId) query.set("workflow_snapshot_run_id", local.workflowSnapshotRunId);
    void apiRequest<{availability: string; message?: string}>(`/api/v3/workbench/availability?${query}`, {signal: controller.signal})
      .then(value => {if (!controller.signal.aborted) setAvailability(value);})
      .catch(caught => {if (!controller.signal.aborted) setAvailability({availability: "unknown", message: (caught as Error).message});});
    return () => controller.abort();
  }, [resourceCheck, record, target, inputsDirty, conflict, mappingEpoch, local?.workflowSnapshotRunId, executionPolicy.mode==="pinned"?executionPolicy.environmentId:""]);

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

  function rememberEdit(before: LocalConversation, label: string, after:LocalConversation,kind:"ai"|"manual"|"parameter"|"restore"|"import"="manual") {
    editorHistory.record(before,after,kind,label);
    lastEdit.current = {keys: "", at: 0}; setUndoEpoch(value => value + 1);
    if(kind!=="manual" && current.current)queueMicrotask(()=>void syncCheckpoints(current.current!.id));
  }
  useEffect(()=>{const retry=()=>{if(current.current)void syncCheckpoints(current.current.id);};window.addEventListener("online",retry);return()=>window.removeEventListener("online",retry);},[]);
  function edit(patch: Partial<LocalConversation>, legacyTarget?: GenerationTarget) {
    const before = localRef.current;
    if (!before || !record) return;
    const at = Date.now();
    let changed={...before,...patch};
    if(patch.requirements){
      changed={...changed,positive:overlayIdentityTags(changed.positive,changed.requirements,before.requirements)};
      if(changed.positive.length>20_000){setError("固定 tag 加入后正向提示词超过 20000 字，请先缩短内容。");return;}
      if(changed.requirements.prompt_locks?.some(lock=>lock.target==="positive"&&before.positive.includes(lock.text)&&!changed.positive.includes(lock.text))){
        setError("这次 tag 修改会改变固定的提示词片段，请先解除对应片段的固定。");return;
      }
    }
    const value = reconcileArtistPresetEdit(before, changed);
    if (patch.model && patch.model !== before.model) {
      const model=patch.model;
      const compatible=targets.filter(item=>item.compatible_model_profiles.includes(model));
      const preferredWorkflow=before.settings.model_configurations?.[model]?.workflow.id;
      const pick=(items:GenerationTarget[])=>items.find(item=>item.workflow_profile_id===preferredWorkflow && item.availability!=="disabled") || defaultTarget(items);
      const pinned=executionPolicy.mode==="pinned" ? compatible.filter(item=>item.remote_profile_id===executionPolicy.environmentId) : [];
      const next=legacyTarget || pick(pinned) || pick(compatible);
      // Resolving an old alias identifies the same model; keep its existing recipe and LoRAs.
      const source=legacyTarget && before.settings.creation_configuration?.modelProfile===model ? {...before, model} : before;
      const prior=creationFor(source,legacyTarget || targetForCreation(before,targets)).configuration;
      const active=legacyTarget ? {...prior,modelProfile:model} : prior;
      value.settings=changeGenerationModel({...before.settings,creation_configuration:active},next,model,before.model);
      value.requirements={...value.requirements,loras:value.settings.creation_configuration!.resourceRequirements};
      value.workflowSnapshotRunId = null;
    }
    if (patch.settings && (patch.settings.creation_configuration?.workflow.id ?? patch.settings.workflow_profile_id)
      !== (before.settings.creation_configuration?.workflow.id ?? before.settings.workflow_profile_id)) value.workflowSnapshotRunId = null;
    const operation=operationBetween(before,value,patch.settings||patch.model?"parameter":"manual",patch.model?"切换模型":patch.settings?"修改生成条件":"编辑提示词与要求",editorEpoch.current);
    if(operation){
      const keys=operation.scope.join(","),journal=editorHistory.journal.current;
      const previous=journal?.entries.at(-1);
      const textual=operation.scope.every(key=>["positive","negative"].includes(key)||key.startsWith("requirements.layers.")&&typeof operation.after[key]==="string");
      if(journal&&previous&&textual&&keys===lastEdit.current.keys&&at-lastEdit.current.at<=800&&journal.cursor===journal.entries.length&&journal.outbox.some(item=>item.id===previous.id)){
        previous.after=operation.after;previous.snapshot=structuredClone(value);editorHistory.refresh();
      }else rememberEdit(before,operation.label,value,operation.kind as "manual"|"parameter");
      lastEdit.current={keys:textual?keys:"",at};
    }
    setLocal(value); persistDraft(record.id, value);
  }
  function adoptCurrentWorkflow() {
    if (!local || !currentWorkflowTarget || !configuration) return;
    const nextConfiguration=configurationFromSettings({...local.settings,creation_configuration:{...configuration,workflow:{id:"",revision:""}}},local.model,currentWorkflowTarget);
    edit({settings:settingsFromConfiguration(nextConfiguration,local.settings,schemaForTarget(currentWorkflowTarget)),workflowSnapshotRunId:null});
  }
  function chooseArtistPreset(snapshot: ArtistPresetSnapshot | null) {
    const before = localRef.current;
    if (!before || !record || busy || pending || conflict) return false;
    try {
      const value = snapshot ? applyArtistPreset(before,snapshot) : removeArtistPreset(before);
      const label = snapshot ? `${before.requirements.layers.style.artist_preset?"更换":"调用"}画师串：${snapshot.name}` : "移除画师串";
      rememberEdit(before,label,value,"import");
      invalidateEditor(); setLocal(value); persistDraft(record.id,value);
      setNotice(snapshot?"已带入画师串原文；可继续改写主体，也可撤销本次调用。":"已移除管理中的画师串；可撤销恢复。");
      setError("");
      if(searchParams.has("artist_preset"))setSearchParams(previous=>{const next=new URLSearchParams(previous);next.delete("artist_preset");return next;},{replace:true});
      return true;
    } catch(caught) {setError((caught as Error).message);return false;}
  }
  function undoEdit(redo = false) {
    const before = localRef.current;
    if (!before || !record || busy || pending) return;
    const previous=editorHistory.travel(before,redo);if(!previous)return;
    const value = {...previous.value, baseRevision: record.revision};invalidateEditor();
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
  function editArtists(tags:string[],source:"manual"|"recommended") {
    const value=localRef.current;if(!value)return;
    const style=value.requirements.layers.style;
    const previous=source==="manual"?style.manual_artist_tags||[]:style.artists;
    const selected=new Set(normalizeIdentityTags(tags,true));
    const removed=new Set(normalizeIdentityTags(previous,true).filter(name=>!selected.has(name)));
    const other=(source==="manual"?style.artists:style.manual_artist_tags||[])
      .filter(name=>{const canonical=normalizeIdentityTags([name],true)[0];return !canonical||!selected.has(canonical)&&!removed.has(canonical);});
    layer("style",source==="manual"?{manual_artist_tags:tags,artists:other}:{artists:tags,manual_artist_tags:other});
  }
  function removeArtist(name:string) {
    const style=localRef.current?.requirements.layers.style;if(!style)return;
    const selected=normalizeIdentityTags([name],true)[0];
    const keep=(value:string)=>normalizeIdentityTags([value],true)[0]!==selected;
    layer("style",{artists:style.artists.filter(keep),manual_artist_tags:(style.manual_artist_tags||[]).filter(keep)});
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
  async function create(initialIdea = "",rawEntry = false):Promise<boolean> {
    let created=false;
    await act("创建工作台", async () => {
      if(draftAtRisk)throw new Error("当前草稿尚未安全保存，请先导出或找回草稿后再新建创作。");
      if(current.current&&localRef.current){const backup=preserveConversationDraft(current.current.id,localRef.current,base.current);if(!backup.ok)throw new Error(backup.warning||"无法备份当前草稿，尚未新建创作。");}
      const model=profiles.find(p=>p.id==="anima_aesthetic_v1_1")?.id || profiles[0].id;
      const settings=newModelSettings(model,targets);
      const body=JSON.stringify({title: initialIdea.trim().slice(0, 40) || `新创作 ${new Date().toLocaleString()}`, draft: {mode: initialMode, model_profile:model, generation_settings:settings}});
      const request=rawEntry?recoverConversationBranch("raw-entry","draft")||{key:crypto.randomUUID(),body}:{key:crypto.randomUUID(),body};
      if(rawEntry)saveConversationBranch("raw-entry","draft",request);
      const next = await apiRequest<ConversationRecord>("/api/v3/workspaces", {method: "POST",body:request.body,...(rawEntry?{headers:{"Idempotency-Key":`raw-create:${request.key}`}}:{})});
      if(!mounted.current)return;
      if(!next?.id||!next.draft||!Number.isInteger(next.revision))throw new Error("新创作回执不完整，原请求已保留，请重试。");
      if(rawEntry){const value=localFrom(next);if(!persistDraft(next.id,value,value))throw new Error("新创作已保存在服务端，浏览器草稿未写入；原请求已保留，请重试。");clearConversationBranch("raw-entry","draft",request);}
      adopt(next); write(ACTIVE, next.id); setWorkspaces(items => [next, ...items.filter(item => item.id !== next.id)]); setPending(null); setRun(null); setRecentRuns([]);
      if (requestedWorkspace) clearWorkspaceLink();
      if (initialIdea.trim()) {
        const value = {...localFrom(next), mode: initialMode, delta: initialIdea};
        setLocal(value); persistDraft(next.id, value, localFrom(next));
        if (!llmUnavailableReason) await requestProposal(next, value, false);
        else setNotice(`想法已保留。${llmUnavailableReason}；配置就绪后点击更新提示词。`);
      }
      setInspectorTab("prompt");
      created=true;
    });
    return created;
  }
  async function continueRun(source: GenerationRunRecord) {
    if (draftAtRisk) return;
    await act("从生成记录创建会话", async () => {
      const origin = `run:${source.id}` as const;
      const workspaceId = record?.id || source.id;
      const request = recoverConversationBranch(workspaceId, origin) || {key: crypto.randomUUID(), body: JSON.stringify({})};
      saveConversationBranch(workspaceId, origin, request);
      const next = await apiRequest<ConversationRecord>(`/api/v3/generation-runs/${encodeURIComponent(source.id)}/workspace`, {method: "POST", body: request.body, headers: {"Idempotency-Key": request.key}});
      if (!mounted.current) return;
      const url=workspaceUrl(next,modelProfiles);
      clearConversationBranch(workspaceId, origin, request);
      if (!isAnimaModel(next.draft.model_profile,modelProfiles)) {navigate(url);return;}
      adopt(next); write(ACTIVE, next.id); setWorkspaces(items => [next, ...items.filter(item => item.id !== next.id)]);
      setPending(null); setRun(source); setRecentRuns([source]); setAvailability(null); setProposal(null); setInspectorTab("prompt");
      if (requestedWorkspace) clearWorkspaceLink();
    });
  }
  async function save(tentativeMode = false, value = localRef.current): Promise<ConversationRecord> {
    let source = current.current;
    if (!source || !value) throw new Error("请先打开工作台。");
    const pendingRestore=editorHistory.journal.current?.pendingRestore;
    if(pendingRestore){
      let restored:ConversationRecord;
      try {
        restored=await apiRequest<ConversationRecord>(`/api/v3/workspaces/${encodeURIComponent(source.id)}/editor-restore`,{method:"POST",body:pendingRestore.body});
      } catch(caught) {
        const journal=editorHistory.journal.current;
        if(caught instanceof ApiClientError&&caught.code==="workspace_revision_conflict"&&journal?.workspaceId===source.id&&journal.pendingRestore?.operationId===pendingRestore.operationId){
          journal.pendingRestore.rejected=true;
          if(localRef.current)persistDraft(source.id,localRef.current);
        }
        throw caught;
      }
      if(!restored.id||!restored.draft)throw new Error("恢复回执不完整；本地备份已保留，请重试保存。");
      const journal=editorHistory.journal.current;
      if(journal?.workspaceId!==source.id||journal.pendingRestore?.operationId!==pendingRestore.operationId){
        // The receipt belongs to an earlier restore. Keep the newer frozen
        // restore request intact and let its own CAS receipt decide its state.
        if(current.current?.id===restored.id)adopt(restored,true);
        return restored;
      }
      delete journal.pendingRestore;
      if(current.current?.id!==restored.id) return restored;
      adopt(restored,true);base.current=localFrom(restored);source=restored;
      const kept={...(localRef.current||value),baseRevision:restored.revision};setLocal(kept);persistDraft(restored.id,kept,base.current);
      if(!hasUnsavedInputs(restored,kept))return restored;
      value=kept;
    }
    value = migrateWorkflowSnapshot(value, source);
    const settingsBeforeProjection=value.settings;
    const savedCreation=creationFor(value,targetForCreation(value,targets));
    value={...value,settings:settingsFromConfiguration(savedCreation.configuration,value.settings,savedCreation.schema)};
    const bound = source.draft.generation_source;
    if (bound && (value.workflowSnapshotRunId !== bound.run_id || bound.model_profile !== value.model
      || bound.workflow_profile_id !== value.settings.workflow_profile_id)) {
      source = await apiRequest<ConversationRecord>("/api/v3/workbench/generation-source", {method:"DELETE",body:JSON.stringify({workspace_id:source.id,revision:source.revision})});
      adopt(source,true);
    }
    const next = await apiRequest<ConversationRecord>('/api/v3/workspaces/' + source.id, {method:"PUT",body:JSON.stringify({
      revision:source.revision,title:source.title,draft:{model_profile:value.model,mode:tentativeMode?source.draft.mode:value.mode,
        requirements_edit:{...cleanRequirements(value.requirements),prompt_locks:value.requirements.prompt_locks||[]},generation_settings:value.settings,
        ...(value.positive.trim()?{prompt_edit:{positive:value.positive,negative:value.negative}}:{})}})});
    if(current.current?.id!==source.id)return next;
    adopt(next,true); base.current=localFrom(next);
    const latest=localRef.current||value;
    const submittedSettingsUnchanged=latest.model===value.model&&JSON.stringify(latest.settings)===JSON.stringify(settingsBeforeProjection);
    const kept=reconcileArtistPresetCompiled({...latest,baseRevision:next.revision,...(submittedSettingsUnchanged?{settings:next.draft.generation_settings||value.settings}:{})});
    setLocal(kept);persistDraft(next.id,kept,base.current);
    return next;
  }
  async function requestProposal(saved:ConversationRecord,value:LocalConversation,recompile:boolean,task:NonNullable<ConversationProposal["task"]>="rewrite"):Promise<{record:ConversationRecord;local:LocalConversation;promptChanged:boolean}|null> {
    setRetryTurn(false);setRetryTask(task);
    const controller=new AbortController();turnController.current=controller;
    const epoch=editorEpoch.current,requestId=crypto.randomUUID();
    const submittedDelta=recompile?"":value.delta;
    function showProposal(candidate: ConversationProposal) {
      setProposal(candidate);
      if(isPromptPreview(candidate)){
        setActiveView("prompt");
        setNotice(candidate.review_status==="needs_review"?"改写结果需要你核对，可采用、带入草稿或保留原版。":"重构预览已就绪，采用后才会替换当前正文。");
      }else setNotice("已整理中文要求，可按需查看。");
    }
    function applied(next:ConversationRecord & {unchanged?:boolean;message?:string;warnings?:string[]}) {
      if(!mounted.current || controller.signal.aborted || current.current?.id!==saved.id || editorEpoch.current!==epoch)return null;
      const freshDelta=localRef.current?.delta ?? value.delta;
      const nextLocal=localFrom(next);
      // Requirement bookkeeping alone does not mean the submitted prompt changed.
      const promptChanged=value.positive!==nextLocal.positive || value.negative!==nextLocal.negative;
      const after={...nextLocal,delta:promptChanged&&freshDelta===value.delta?"":freshDelta,
        workflowSnapshotRunId:value.workflowSnapshotRunId,restoredFrom:value.restoredFrom};
      rememberEdit(value,value.delta.trim()||"更新提示词",after,"ai");
      adopt(next,true);base.current=localFrom(next);setLocal(after);persistDraft(next.id,after,base.current);
      setLastChange({before:structuredClone(value),after:structuredClone(after),label:value.delta.trim()||"更新提示词"});
      setProposal(null);setInspectorTab("prompt");setActiveView("prompt");
      setNotice([promptChanged?"提示词已更新，可直接生成或撤销。":submittedDelta.trim()?"本次提示词没有变化，修改意见已保留。":"本次提示词没有变化，当前版本保持不变。",
        ...(next.message?[next.message]:[]),...(next.warnings||[])].join("\n"));
      return {record:next,local:after,promptChanged};
    }
    try {
      const context=await apiRequest<{token?:string}>(`/api/v3/workspaces/${encodeURIComponent(saved.id)}/editor-context`,{method:"POST",signal:controller.signal,body:JSON.stringify({document_id:documentId.current,request_id:requestId,editor_epoch:epoch})});
      if(context.token)activeEditorContext.current={workspaceId:saved.id,token:context.token};
      if(controller.signal.aborted||editorEpoch.current!==epoch)return null;
      const contextBody=context.token?{document_id:documentId.current,context_token:context.token,request_id:requestId,editor_epoch:epoch}:{};
      if(task!=="rewrite") {
        const result=await apiRequest<ConversationProposal | (ConversationRecord & {unchanged:true;message?:string})>("/api/v3/workbench/turns",{method:"POST",signal:controller.signal,body:JSON.stringify({...contextBody,workspace_id:saved.id,revision:saved.revision,mode:saved.draft.mode,preview:true,task,delta:{text:submittedDelta},compiled:{positive:value.positive,negative:value.negative}})});
        if(!mounted.current || controller.signal.aborted || current.current?.id!==saved.id || editorEpoch.current!==epoch)return null;
        if(result.unchanged){setProposal(null);setNotice(result.message || (task==="bold_rewrite"?"本次重构没有变化。":"画面要求与当前提示词一致。"));}
        else showProposal(result);
        return null;
      }
      const next=await apiRequest<ConversationProposal | (ConversationRecord & {unchanged?:boolean;message?:string;warnings?:string[]})>("/api/v3/workbench/turns",{method:"POST",signal:controller.signal,body:JSON.stringify({
        ...contextBody,workspace_id:saved.id,revision:saved.revision,mode:value.mode,preview:false,delta:{text:submittedDelta},
        ...(value.positive.trim()?{compiled:{positive:value.positive,negative:value.negative}}:{})})});
      if("base_revision" in next){
        if(mounted.current && !controller.signal.aborted && current.current?.id===saved.id && editorEpoch.current===epoch)showProposal(next);
        return null;
      }
      return applied(next);
    } catch(caught) {
      if(!controller.signal.aborted && caught instanceof ApiClientError && ["network_error","internal_error","workspace_proposal_pending"].includes(caught.code)) {
        try {
          const pendingReview=await apiRequest<{proposal:ConversationProposal|null}>(`/api/v3/workspaces/${saved.id}/proposal`,{signal:controller.signal});
          if(pendingReview.proposal && !controller.signal.aborted && mounted.current && current.current?.id===saved.id && editorEpoch.current===epoch){
            showProposal(pendingReview.proposal);return null;
          }
          if(task==="rewrite"){
            const recovered=await apiRequest<ConversationRecord>('/api/v3/workspaces/'+saved.id);
            const last=recovered.draft.conversation_events.at(-1);
            if(recovered.revision===saved.revision+1 && last?.after_revision===recovered.revision && last.before_revision===saved.revision && last.delta===submittedDelta)return applied(recovered);
            if(recovered.revision!==saved.revision) {adopt(recovered,true);setConflict(true);}
          }
        } catch { /* Keep the original failure and all local inputs. */ }
      }
      if(!controller.signal.aborted)setRetryTurn(true);
      throw caught;
    } finally {if(turnController.current===controller)turnController.current=null;}
  }
  async function turn(recompile:boolean,generateAfter=false) {
    const before=localRef.current;
    if(generateAfter && parameterEditsPending)return;
    if(!record||!before||proposal||conflict||pending||pendingRecoveryBlocked||llmUnavailableReason||adviceBusy||unsavedEmptyPrompt)return;
    await act(generateAfter?"更新提示词并生成":"更新提示词",async()=>{
      const saved=hasUnsavedInputs(record,{...before,mode:record.draft.mode})?await save(true,before):record;
      if(!before.positive.trim() && (saved.draft.compiled?.positive.trim() || (saved.draft.compiled?.negative||"")!==before.negative))
        throw new Error("当前正向为空，已保存的提示词与编辑区不同；请先填写正向提示词再更新。");
      const updated=await requestProposal(saved,{...before,baseRevision:saved.revision},recompile);
      if(updated?.promptChanged && generateAfter) {setBusy("提交生成");await submitGeneration(updated.local,updated.record);}
    });
  }
  async function previewTurn(task: "sync_requirements" | "bold_rewrite") {
    const value=localRef.current, sync=task==="sync_requirements";
    if (!record || !value?.positive.trim() || (sync && value.delta.trim()) || proposal || conflict || pending || pendingRecoveryBlocked || llmUnavailableReason || adviceBusy) return;
    await act(sync?"同步画面要求":"准备大胆重构预览", async () => {
      const saved = hasUnsavedInputs(record, {...value, mode: record.draft.mode}) ? await save(true,value) : record;
      await requestProposal(saved, value, sync, task);
    });
  }
  async function decideProposal(accept: boolean) {
    if (!record || !local || !proposal || (accept && proposalBlocked)) return;
    await act(accept ? "采用修改" : "保留原版本", async () => {
      const result = await apiRequest<ConversationRecord>(`/api/v3/workspaces/${record.id}/proposals/${proposal.id}${accept ? "/accept" : ""}`, {method: accept ? "POST" : "DELETE", body: JSON.stringify({revision: record.revision})});
      if (accept && isPromptPreview(proposal)) {
        const before=localRef.current || local;
        const delta=proposal.draft.conversation_events.at(-1)?.delta || "";
        const after={...localFrom(result),mode:before.mode,delta:before.delta.trim()===delta.trim()?"":before.delta,
          workflowSnapshotRunId:before.workflowSnapshotRunId,restoredFrom:before.restoredFrom};
        const label=proposal.task==="bold_rewrite"?"采用大胆重构":"采用待核对候选";
        rememberEdit(before,label,after,"ai");
        adopt(result,true);base.current=localFrom(result);setLocal(after);persistDraft(result.id,after);
        setLastChange({before,after,label});setActiveView("prompt");
      } else if(accept) adopt(result);
      setProposal(null); setNotice(accept ? "修改已采用并保存，可在版本历史恢复。" : "已保留原版本，修改意见仍在输入框中。");
    });
  }
  async function editProposalDraft() {
    if(!record || !local || !proposal?.draft.compiled || proposalBlocked)return;
    const next=reconcileArtistPresetCompiled({...local, positive:proposal.draft.compiled.positive, negative:proposal.draft.compiled.negative,
      requirements:editableRequirements({...record,draft:proposal.draft})});
    await act("带入候选草稿",async()=>{
      const backup=preserveConversationDraft(record.id,next,base.current);
      if(!backup.ok)throw new Error(backup.warning || "候选草稿无法保存，请重试。");
      await apiRequest(`/api/v3/workspaces/${record.id}/proposals/${proposal.id}`,{method:"DELETE",body:JSON.stringify({revision:record.revision})});
      if(!mounted.current || current.current?.id!==record.id)return;
      const before=localRef.current || local;
      const after={...next,delta:before.delta};
      rememberEdit(before,"带入候选草稿",after,"ai");
      setLocal(after);persistDraft(record.id,after);setProposal(null);setActiveView("prompt");
      setNotice("候选正文和画面要求已带入本机草稿，可继续编辑，原版本已保留。");
    });
  }
  function restoreEditor(value:LocalConversation,label:string) {
    const before=localRef.current;
    if(!record||!before||(busy&&!turnController.current)||pending||conflict)return false;
    const preserved=preserveConversationDraft(record.id,before,base.current);
    if(!preserved.ok){setError(preserved.warning||"无法保留当前草稿，当前内容未变。");return false;}
    const restored={...value,baseRevision:record.revision};
    delete restored.artistPresetPlacement; delete restored.artistPresetCustomized;
    const next=reconcileArtistPresetCompiled(restored);
    const saved=saveConversationDraft(record.id,next,base.current);
    if(!saved.ok){setError(saved.warning||"无法保存恢复内容，当前内容未变。");return false;}
    rememberEdit(before,label,next,"restore");
    const journal=editorHistory.journal.current,operation=journal?.entries.at(-1);
    if(journal){journal.pendingRestore={operationId:operation?.id||crypto.randomUUID(),body:JSON.stringify({document_id:documentId.current,operation_id:operation?.id||crypto.randomUUID(),revision:record.revision,title:record.title,draft:{model_profile:next.model,mode:next.mode,requirements_edit:{...cleanRequirements(next.requirements),prompt_locks:next.requirements.prompt_locks||[]},generation_settings:next.settings,...(next.positive.trim()?{prompt_edit:{positive:next.positive,negative:next.negative}}:{})}})};}
    setLocal(next);persistDraft(record.id,next);invalidateEditor();setStorageWarning("");setHistoryOpen(false);
    void save(false,next).catch(async caught=>{if(!mounted.current)return;setError((caught as Error).message);if(caught instanceof ApiClientError&&caught.code==="workspace_revision_conflict"){setConflict(true);try{adopt(await apiRequest<ConversationRecord>(`/api/v3/workspaces/${record.id}`),true);}catch{}}});
    setLastChange({before,after:next,label});setNotice(label+"；可撤销恢复，后续图片与记录均保留。");return true;
  }
  function restoreVersion(version:WorkbenchHistoryVersion) {
    if(!record||!localRef.current)return;
    restoreEditor(restoreContent(localRef.current,localFrom({...record,...version,draft:version.draft}),"历史创作："+version.title),"已载入历史内容，保留当前生成条件");
  }
  async function restoreRun(source:GenerationRunRecord,onlyPrompt=false,version?:WorkbenchHistoryVersion) {
    const before=localRef.current;
    if(!record||!before||busy||pending||conflict||!source.source?.positive_prompt)return;
    if(!onlyPrompt && source.source.model_profile && !isAnimaModel(source.source.model_profile,modelProfiles)) {
      await continueRun(source);
      return;
    }
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
    const model=onlyPrompt?before.model:source.source.model_profile!;
    let settings=before.settings;
    if(!onlyPrompt){
      const prior=creationFor(before,targetForCreation(before,targets)).configuration;
      settings={...defaultGenerationSettings(),...source.source.settings,
        model_configurations:inactiveModelConfigurations(before.settings,prior,model),
        preset_id:"custom",aspect:"custom",remote_profile_id:before.settings.remote_profile_id,
        workflow_profile_id:source.workflow_profile_id,execution_policy:before.settings.execution_policy || executionPolicy};
    }
    const value={...before,positive:source.source.positive_prompt,negative:source.source.negative_prompt,
      requirements,mode:onlyPrompt?before.mode:historical?.draft.mode||before.mode,delta:"",
      model,settings,
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
      if (openOtherWorkbench(next)) return;
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
    setConflict(false); setPending(null); setNotice(""); setError(""); setIdea(""); setInitialMode("faithful"); remove(ACTIVE);
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
      if (openOtherWorkbench(next)) return;
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
      const previous=configurationFromSettings(local.settings,local.model,target,{preserveSnapshot:Boolean(local.workflowSnapshotRunId)});
      const next={...previous,seedMode:"fixed" as const,parameterOverrides:{...previous.parameterOverrides,...parameters,seed,batch_size:1}};
      edit({settings:settingsFromConfiguration(next,local.settings,parameterSchema)});
      setNotice("已带入保存的种子与采样参数。多图批次的种子记录不保证对应选中的单张图片；比较时请核对图片信息，并保持其他条件一致。");
    });
  }
  async function acceptGeneration(accepted:Accepted, saved:ConversationRecord, value:LocalConversation, request:Pending, submitted:{positive_prompt:string;negative_prompt:string}, tracked=true) {
    if(tracked)clearConversationPending(saved.id,request);
    if(current.current?.id!==saved.id)return;
    setPending(null);setRun(accepted);setActiveView("images");setHistoryOpen(false);setResultRequestKey(accepted.id);
    setRecentRuns(items=>[accepted,...items.filter(item=>item.id!==accepted.id)]);
    const revision=accepted.workspace_revision||saved.revision;
    let next:ConversationRecord={...saved,revision,draft:{...saved.draft,compile_state:"fresh",
      compiled:{positive:submitted.positive_prompt,negative:submitted.negative_prompt,compiled_token:accepted.compiled_token||saved.draft.compiled?.compiled_token||"",source:"user"}}};
    adopt(next,true);base.current=localFrom(next);
    const kept={...(localRef.current||value),baseRevision:next.revision};setLocal(kept);persistDraft(next.id,kept,base.current);
    try {
      const latest=await apiRequest<ConversationRecord>('/api/v3/workspaces/'+saved.id);
      if(current.current?.id!==saved.id)return;
      if(latest.revision>next.revision){adopt(latest,true);setConflict(true);setConflictChoices({});setNotice("生成已提交；其他窗口又保存了修改，当前草稿保留，请合并后继续。");}
      else if(latest.revision===next.revision){next=latest;adopt(next,true);base.current=localFrom(next);persistDraft(next.id,localRef.current||kept,base.current);}
    } catch {setNotice("生成已提交，读取最新记录暂时失败；请勿重复提交。");}
  }
  async function receiveIntent(receipt:GenerationIntentRecord, request:Pending, saved:ConversationRecord, value:LocalConversation) {
    if(current.current?.id!==saved.id || pendingRef.current?.key!==request.key)return;
    setGenerationIntent({...receipt,clientRequestKey:request.key});
    if(receipt.state==="accepted" && receipt.response){
      const body=JSON.parse(request.body) as GenerationIntentRequest;
      await acceptGeneration(receipt.response as Accepted,saved,value,request,body.source as {positive_prompt:string;negative_prompt:string});
    } else if(receipt.state==="canceled") {clearConversationPending(saved.id,request);setPending(null);setNotice("本次生成已取消，创作内容保持不变。");}
  }
  async function resolveIntent(recheck=false) {
    if(!pending||!current.current||!localRef.current)return;
    const request=pending,saved=current.current,value=localRef.current;
    const isCurrent=()=>mounted.current&&current.current?.id===saved.id&&pendingRef.current?.key===request.key;
    await act("检查生成请求",async()=>{
      const matched=generationIntent?.clientRequestKey===request.key?generationIntent:null;
      let receipt=recheck&&matched?await retryGenerationIntent(matched.id):matched?await getGenerationIntent(matched.id):await createGenerationIntent(JSON.parse(request.body),request.key);
      if(!isCurrent())return;
      await receiveIntent(receipt,request,saved,value);
      if(!recheck||!matched||receipt.state!=="blocked"||receipt.state!==matched.state||receipt.updated_at>matched.updated_at)return;
      // A 202 can still contain the blocked receipt from before the scheduled check starts.
      setNotice("已请求重新检查，正在等待新的检查结果…");
      for(let attempt=0;attempt<20;attempt++){
        await new Promise<void>(resolve=>window.setTimeout(resolve,800));
        if(!isCurrent())return;
        receipt=await getGenerationIntent(matched.id);
        if(!isCurrent())return;
        if(receipt.state!==matched.state||receipt.updated_at>matched.updated_at){
          setNotice("");await receiveIntent(receipt,request,saved,value);return;
        }
      }
      setNotice("尚未收到新的环境检查结果。可稍后重新检查，或取消本次生成。");
    });
  }
  async function cancelIntent() {
    if(!generationIntent||!pending||generationIntent.clientRequestKey!==pending.key||!current.current||!localRef.current)return;
    const request=pending,saved=current.current,value=localRef.current;
    await act("取消本次生成",async()=>{await receiveIntent(await cancelGenerationIntent(generationIntent.id),request,saved,value);});
  }
  useEffect(()=>{
    if(!pending||!generationIntent||generationIntent.clientRequestKey!==pending.key||generationIntent.state!=="resolving"||!record)return;
    const request=pending,id=record.id;let stopped=false,timer=0,pollError="";
    const poll=async()=>{try{const receipt=await getGenerationIntent(generationIntent.id);if(stopped||current.current?.id!==id)return;
      if(pollError){const recoveredError=pollError;pollError="";setError(message=>message===recoveredError?"":message);}
      await receiveIntent(receipt,request,current.current!,localRef.current!);
      if(receipt.state==="resolving")timer=window.setTimeout(()=>void poll(),800);
    }catch(caught){if(!stopped&&current.current?.id===id&&pendingRef.current?.key===request.key){
      pollError=(caught as Error).message;setError(pollError);timer=window.setTimeout(()=>void poll(),800);
    }}};
    timer=window.setTimeout(()=>void poll(),800);return()=>{stopped=true;window.clearTimeout(timer);};
  },[generationIntent?.id,generationIntent?.state,pending?.key,record?.id]);
  function forgetDirectRequest(workspaceId:string,request:Pending){
    localStorage.removeItem(directRecoveryPrefix(workspaceId)+encodeURIComponent(request.key));
    if(mounted.current&&current.current?.id===workspaceId)setOptionalRequests(directRecoveries(workspaceId));
  }
  async function queryDirectRequest(request:Pending){
    if(!record||busy||pending||JSON.parse(request.body).workspace_id!==record.id)return;
    const workspaceId=record.id;
    await act("查询旧提交结果",async()=>{
      const controller=new AbortController(),timer=window.setTimeout(()=>controller.abort(),12000);
      try{
        const result=await apiRequest<{found:boolean;response:Accepted|null}>(`/api/v3/generation-submissions/by-key?key=${encodeURIComponent(request.key)}`,{signal:controller.signal});
        if(!mounted.current||current.current?.id!==workspaceId)return;
        if(!result.found){setNotice("暂未查到已接受任务，旧任务仍可能完成；可继续编辑或显式重新生成。");return;}
        if(!validRunReceipt(result.response))throw new ApiClientError("查询回执不完整，结果尚未确认；旧提交记录已保留。","submission_unconfirmed");
        forgetDirectRequest(workspaceId,request);
        setRun(result.response);setActiveView("images");setResultRequestKey(result.response!.id);
        setRecentRuns(items=>[result.response!,...items.filter(item=>item.id!==result.response!.id)]);
        setNotice("已找到旧提交的任务，当前草稿与后续修改保持不变。");
      }catch(caught){
        if((caught as Error).name==="AbortError")throw new ApiClientError("查询旧提交超时，恢复记录已保留；可继续编辑或换连接。","submission_unconfirmed");
        throw caught;
      }finally{window.clearTimeout(timer);}
    });
  }
  async function submitPinned(request:Pending,saved:ConversationRecord,value:LocalConversation){
    // Each uncertain direct request owns one optional record; it never occupies the blocking legacy slot.
    try{localStorage.setItem(directRecoveryPrefix(saved.id)+encodeURIComponent(request.key),JSON.stringify(request));}
    catch{throw new Error("无法保存这次提交的恢复记录，尚未发送，请释放浏览器存储后重试。");}
    setOptionalRequests(directRecoveries(saved.id));
    const controller=new AbortController(),timer=window.setTimeout(()=>controller.abort(),12000);
    try{
      const accepted=await apiRequest<Accepted>("/api/v3/direct-prompt/runs",{method:"POST",body:request.body,headers:{"Idempotency-Key":request.key},signal:controller.signal});
      if(!validRunReceipt(accepted)||!Number.isInteger(accepted.workspace_revision)||!accepted.compiled_token)throw new ApiClientError("提交回执不完整，结果尚未确认。","submission_unconfirmed");
      if(!mounted.current||current.current?.id!==saved.id)return;
      await acceptGeneration(accepted,saved,value,request,JSON.parse(request.body),false);
      forgetDirectRequest(saved.id,request);
    }catch(caught){
      if(caught instanceof ApiClientError&&definitiveDirectRejections.has(caught.code))forgetDirectRequest(saved.id,request);
      else if(mounted.current&&current.current?.id===saved.id)setNotice("提交结果尚未确认，可查询旧提交，也可换连接重新生成；旧任务仍可能完成。");
      if((caught as Error).name==="AbortError")throw new ApiClientError("等待本地服务超时，提交结果尚未确认，可稍后查询旧提交。","submission_unconfirmed");
      throw caught;
    }finally{window.clearTimeout(timer);}
  }
  async function submitGeneration(value:LocalConversation,initial:ConversationRecord,retry=false) {
    value=migrateWorkflowSnapshot(value,initial);
    let saved=initial;
    let request=retry&&pending?pending:null;
    if(!request){
      if(loraPrep.blocked)throw new Error(loraPrep.message);
      if(loraPrep.state!=="idle")await loraPrep.verifyCurrent();
      if(!value.positive.trim())throw new Error("请填写或更新正向提示词。");
      setGenerationIntent(null);
      const policy=value.settings.execution_policy||executionPolicy;
      const selected=targetForCreation(value,policy.mode==="pinned"?targets.filter(item=>item.remote_profile_id===policy.environmentId):targets);
      const {schema,configuration:config,resolved}=creationFor(value,selected);
      if(!selected&&!hasSavedWorkflowSnapshot(value,config,schema))throw new Error("请选择兼容的创作工作流。");
      if(!resolved.valid)throw new Error("请先修正生成参数。");
      value={...value,settings:settingsFromConfiguration(config,value.settings,schema)};
      setLocal(value);
      if(hasUnsavedInputs(initial,value)||initial.draft.generation_source?.run_id&&value.workflowSnapshotRunId!==initial.draft.generation_source.run_id){
        saved=await save(false,value);
      }
      const source={submission_kind:"conversational",use_current_prompt:true,workspace_id:saved.id,workspace_revision:saved.revision,
        compiled_token:saved.draft.compiled?.compiled_token,positive_prompt:value.positive,negative_prompt:value.negative,model_profile:value.model,
        ...(value.workflowSnapshotRunId?{workflow_snapshot_run_id:value.workflowSnapshotRunId}:{}),settings:configurationToGenerationPayload(config,schema)};
      const pinnedDirect=policy.mode==="pinned"&&!value.workflowSnapshotRunId;
      const body=pinnedDirect?{...source,remote_profile_id:policy.environmentId,workflow_profile_id:config.workflow.id}
        :{source,creationConfiguration:{...config},executionPolicy:policy};
      request={key:crypto.randomUUID(),body:JSON.stringify(body)};
      if(pinnedDirect){await submitPinned(request,saved,value);return;}
    }
    try{saveConversationPending(saved.id,request);}catch(caught){
      if(!(caught instanceof ConversationRequestSettledError))throw caught;
      setPending(null);
      try {setPending(recoverConversationPending(saved.id));setPendingRecoveryBlocked(false);}
      catch(recoveryError){setPendingRecoveryBlocked(true);throw recoveryError;}
      setNotice("这次请求已完成或已明确拒绝，已停止重复查询。当前草稿已保留，请先到全部任务核对结果。");return;
    }
    setPending(request);
    const body=JSON.parse(request.body);
    if(body.creationConfiguration){
      try {const receipt=await createGenerationIntent(body,request.key);await receiveIntent(receipt,request,saved,value);}
      catch(caught){if(!retry&&caught instanceof ApiClientError&&["invalid_request","incompatible_workflow","incompatible_model","stale_compiled_prompt","workspace_revision_conflict"].includes(caught.code)){clearConversationPending(saved.id,request);setPending(null);}throw caught;}
      return;
    }
    // A pre-upgrade uncertain submission must retain its original protocol/key/body.
    let accepted:Accepted;
    try{accepted=await apiRequest<Accepted>("/api/v3/direct-prompt/runs",{method:"POST",body:request.body,headers:{"Idempotency-Key":request.key}});}
    catch(caught){if(caught instanceof ApiClientError&&["lora_not_installed","protected_prompt_changed","workflow_incompatible","incompatible_workflow","reference_preset_unavailable","mapping_revision_conflict"].includes(caught.code)){clearConversationPending(saved.id,request);setPending(null);}throw caught;}
    await acceptGeneration(accepted,saved,value,request,body);
  }
  async function generate(retry=false) {
    if(!record||!localRef.current||(!retry && (promptPreview || parameterEditsPending)))return;
    await act(retry?"查询生成结果":"提交生成",()=>submitGeneration(localRef.current!,current.current!,retry));
  }

  const promptChanged = Boolean(local && (local.positive !== (record?.draft.compiled?.positive || "") || local.negative !== (record?.draft.compiled?.negative || "")));
  const personalUndoChanged = Boolean(personalResult && (personalResult.workspace.id !== record?.id || !personalResult.receipt.can_undo
    || local?.positive !== (personalResult.workspace.draft.compiled?.positive || "")
    || local?.negative !== (personalResult.workspace.draft.compiled?.negative || "")));
  const matchedPendingIntent=pending&&generationIntent?.clientRequestKey===pending.key?generationIntent:null;
  const showPendingEnvironment=matchedPendingIntent?.state==="blocked"||matchedPendingIntent?.state==="resolving";
  const executionReason=busy ? busy+"…" : pendingRecoveryBlocked?"请先核对上次生成请求的恢复记录":pending?showPendingEnvironment?"请查看上方本次提交的环境检查结果":"请先查询上次提交的结果":conflict?"请先处理版本冲突"
    :parameterEditsPending?"生成参数有修改待确认"
    :local?.model===LEGACY_AESTHETIC&&!savedWorkflowSnapshot?"请选择明确的模型版本":!remoteEnabled?"连接生图服务后即可生成":!target&&!savedWorkflowSnapshot?"请选择创作工作流":!configurationValid?"请修正参数面板中标出的数值":loraPrep.blocked?loraPrep.message:"";
  const promptPreview=isPromptPreview(proposal);
  const proposalBlocked=Boolean(proposal && record && local && (conflict || proposal.base_revision!==record.revision
    || hasUnsavedInputs(record,{...local,mode:record.draft.mode})
    || (promptPreview && local.delta.trim()!==(proposal.draft.conversation_events.at(-1)?.delta || "").trim())));
  const reviewPanel=proposal && record && local && <ConversationReview proposal={proposal}
    before={promptPreview?localFrom(record):local} disabled={Boolean(busy)} acceptBlocked={proposalBlocked}
    onAccept={()=>void decideProposal(true)} onDiscard={()=>void decideProposal(false)} onEdit={promptPreview?()=>void editProposalDraft():undefined} />;
  const generationReason=executionReason || (promptPreview?"请先处理候选提示词":!local?.positive.trim()?"请填写或更新正向提示词":"");
  const tabs = [{id: "prompt", label: "提示词"}, {id: "requirements", label: "画面要求"}, {id: "settings", label: "生成设置"}] as const;
  async function copyPrompt(kind: "positive" | "negative") {
    try {await navigator.clipboard.writeText(local?.[kind] || ""); setCopied(kind);}
    catch {setError("复制失败，请选中提示词后手动复制。");}
  }
  const merge = conflict && base.current && local && record ? mergeConversation(base.current, local, localFrom(record)) : null;
  function resolveConflict() {
    if (!merge || !record || merge.conflicts.some(item => !conflictChoices[item.path])) return;
    const value = reconcileArtistPresetCompiled(reconcileWorkflowSnapshot(resolveConversationConflicts(merge, conflictChoices), [local, base.current, localFrom(record)])); base.current = localFrom(record);
    const journal=editorHistory.journal.current;
    if(journal){journal.archived.push(...journal.entries);journal.entries=[];journal.cursor=0;journal.editorEpoch++;if(journal.pendingRestore?.rejected)delete journal.pendingRestore;}
    invalidateEditor();lastEdit.current = {keys: "", at: 0};
    setLocal(value); persistDraft(record.id, value, base.current); setConflict(false); setError("");
    setNotice("已合并双方修改，可以继续更新提示词或生图。"+(value.artistPresetCustomized?"画师串与合并后的文字不同，已解除自动管理并保留原文。":""));
  }
  const executionEnvironmentControl=local&&<ExecutionEnvironmentControl policy={executionPolicy} environments={environments} intent={!pending?generationIntent:matchedPendingIntent} disabled={Boolean(busy||conflict)}
    onChange={policy=>edit({settings:{...local.settings,execution_policy:policy}})}
    onRetry={()=>void resolveIntent(true)} onCancel={()=>void cancelIntent()}
    onConfirmAssets={id=>void act("确认资源映射",async()=>{if(!configuration)return;await confirmEnvironmentAssets(id,configuration.workflow,generationIntent?.id);setNotice("资源映射已确认，可重新检查环境。");})}
    onRebuilt={id=>void act("标记环境重建",async()=>{await markEnvironmentRebuilt(id);setNotice("已清除旧环境验证，请重新确认当前实例的资源。");})}/>;

  return <section className="conversation-workbench conversation-workbench--studio" onBlurCapture={()=>{lastEdit.current={keys:"",at:0};}} onCompositionEndCapture={()=>{lastEdit.current={keys:"",at:0};}}>
    {searchParams.has("artist_preset")&&!local&&<p className="conversation-studio__source">画师串已准备好。先打开已有会话或输入想法开始创作，再确认调用。</p>}
    {/* One header row: the session switcher doubles as the visible title so the editor keeps its height. */}
    <WorkbenchHeader record={record} local={local} workspaces={workspaces} archived={archived} busy={busy} pending={pending} draftAtRisk={draftAtRisk}
      proposal={proposal} conflict={conflict} dirty={dirty} storageWarning={storageWarning} sessionSearch={sessionSearch} moreSessions={moreSessions} rename={rename}
      showLlmToggle={!local || !record} showLlmSettings={showLlmSettings} adviceBusy={adviceBusy} thinkingSaving={thinking.saving} llmSettingsBusy={llmSettingsBusy}
      onSelectSession={id => void (archived ? unarchiveSession(id) : open(id))} onSearchChange={setSessionSearch} onSearch={() => void searchSessions()}
      onArchivedChange={next => {setArchived(next); void searchSessions(sessionSearch, next);}} onLoadMore={() => void searchSessions(sessionSearch, archived, true)}
      onStartRename={() => record && setRename(record.title)} onRenameChange={setRename} onSaveRename={() => void renameSession()} onCancelRename={() => setRename(null)}
      onArchive={() => void archiveSession()} onToggleLlmSettings={() => setShowLlmSettings(value => !value)} onStartNew={startNew} />

    {showLlmSettings && <div id="conversation-llm-settings"><LlmSettingsPanel disabled={Boolean(busy || pending || adviceBusy || thinking.loading || thinking.saving)}
      onSaved={thinking.refresh} onBusyChange={setLlmSettingsBusy} /></div>}
    {error && <div role="alert" className="conversation-error">{error}{retryTurn && record && local && <p>当前内容已保留。<button disabled={Boolean(busy || proposal || conflict || llmUnavailableReason)} onClick={() => void (retryTask === "rewrite" ? turn(!local.delta.trim()) : previewTurn(retryTask))}>{retryTask==="bold_rewrite"?"重试大胆重构":"重试整理"}</button><button onClick={() => setShowLlmSettings(true)}>检查模型设置</button></p>}</div>}
    {unsavedEmptyPrompt&&<p role="status">正向为空，当前编辑保留在本机草稿；填写正向后可以保存版本、更新提示词或生成。</p>}
    {storageWarning && <div role="alert" className="conversation-warning">{storageWarning}{invalidDraftRaw && <button onClick={() => {
      const url = URL.createObjectURL(new Blob([invalidDraftRaw], {type: "application/json"}));
      const link = document.createElement("a"); link.href = url; link.download = `anima-draft-recovery-${record?.id || "unknown"}.json`; link.click(); URL.revokeObjectURL(url);
    }}>导出原始草稿</button>}{draftPersistenceBlocked.current === record?.id && <p>原草稿未被覆盖。请先导出；当前编辑可直接保存到服务端，浏览器恢复仍不可用。</p>}</div>}
    {notice && <p role="status" className="conversation-notice">{notice}</p>}
    {busy && <div className="conversation-wait"><p role="status">{busy}… 已等待 {elapsed} 秒{turnController.current && (retryTask==="rewrite"?"，完成后提示词会直接更新。":"，完成后可查看改动。")}</p>{turnController.current && <button onClick={invalidateEditor}>取消整理</button>}</div>}
    {requestedTransfer && error && <button disabled={Boolean(busy)} onClick={() => {transferAttempt.current = ""; setInitialLoaded(false); setTransferRetry(value => value + 1);}}>重试带入</button>}
    {searchParams.get("entry")==="raw"&&error&&<button disabled={Boolean(busy)} onClick={()=>{rawAttempt.current=false;setRawRetry(value=>value+1);}}>重试原文创作</button>}
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
      <label htmlFor="conversation-idea" className="conversation-sr-only">创作想法</label><textarea id="conversation-idea" rows={3} value={idea} maxLength={4000} onChange={event => setIdea(event.target.value)} placeholder="例如：栗色长发的女孩坐在窗边，双手捧着咖啡杯，窗外樱花盛开。" />
      <div className="conversation-starters">{[{title: "日常人物", text: "栗色长发的女孩坐在窗边，双手捧着咖啡杯，清透赛璐璐风格。"}, {title: "幻想场景", text: "身穿白金盔甲的骑士站在空中花园，披着蓝色披风，远处是浮空城堡。"}, {title: "水彩插画", text: "戴尖帽的魔女双手捧着小白花，站在有蕨类和萤火虫的森林，透明水彩风格。"}].map(item => <button key={item.title} disabled={Boolean(busy)} onClick={() => setIdea(item.text)}>{item.title}</button>)}</div>
      <RewriteModeSelector value={initialMode} onChange={setInitialMode} disabled={Boolean(busy)} initial />
      <div className="conversation-empty-actions">
        <button type="button" className="conversation-secondary" onClick={()=>void create()} disabled={Boolean(busy)}>直接编写提示词</button>
        <button className="conversation-primary" onClick={() => void create(idea)} disabled={Boolean(busy || thinking.loading) || !idea.trim()}>开始整理想法 <PaperPlaneRight size={17} aria-hidden="true" /></button>
      </div>
      <p className="conversation-empty-note">提示词更新后，点击生成图片；修改不满意可以撤销。</p></section> : <>
      {conflict && <ConflictPanel merge={merge} conflictChoices={conflictChoices} busy={Boolean(busy)}
        onChoiceChange={(path, choice) => setConflictChoices(value => ({...value, [path]: choice}))} onResolve={resolveConflict}
        onBranch={() => void branchLocalDraft()} onAdoptRemote={() => {
          const journal=editorHistory.journal.current;
          if(journal?.workspaceId===record.id&&journal.pendingRestore?.rejected){journal.archived.push(...journal.entries);journal.entries=[];journal.cursor=0;journal.editorEpoch++;delete journal.pendingRestore;invalidateEditor();}
          adopt(record);setError("");
        }} />}
      <PendingSubmissionPanel pending={Boolean(pending)} showPendingEnvironment={Boolean(showPendingEnvironment)} pendingState={matchedPendingIntent?.state}
        executionEnvironmentControl={executionEnvironmentControl} optionalRequests={optionalRequests} busy={Boolean(busy)}
        onQueryCurrent={() => void generate(true)} onQueryDirect={request => void queryDirectRequest(request)}
        onForgetDirect={request => {try{forgetDirectRequest(record.id,request);}catch(caught){setError((caught as Error).message);}}} />

      {proposal && !promptPreview && <details className="conversation-legacy-proposal"><summary>上次未处理的提示词草案</summary>{reviewPanel}</details>}
      <ConversationStudioView activeView={activeView} resultRequestKey={resultRequestKey} parameterRequestKey={parameterRequestKey} busy={Boolean(busy)} historyOpen={historyOpen} onOpenHistory={()=>setHistoryOpen(true)} onCloseHistory={()=>setHistoryOpen(false)}
        history={<WorkbenchHistory record={record} runs={recentRuns} disabled={Boolean((busy&&!turnController.current)||pending||conflict)}
          onRestoreVersion={restoreVersion} onForkVersion={revision=>void forkVersion(revision)} onRestoreRun={(source,onlyPrompt,version)=>void restoreRun(source,onlyPrompt,version)}
          draftRecovery={<ConversationDraftRecovery key={record.id} workspaceId={record.id} disabled={Boolean(busy||pending||pendingRecoveryBlocked)} onRestore={restoreLocalDraft} />} />}
        editor={<>{promptPreview && reviewPanel}<fieldset disabled={Boolean(busy||pending||conflict)} className="studio-editor-toolbar">
          <header className="conversation-studio__section-heading conversation-studio__editor-heading"><h2>提示词</h2>
          <div className="conversation-studio__undo"><button disabled={!editorHistory.canUndo} onClick={()=>undoEdit()}>撤销</button><button disabled={!editorHistory.canRedo} onClick={()=>undoEdit(true)}>重做</button>{editorHistory.canUndo&&<span>{"可撤销："+editorHistory.journal.current!.entries[editorHistory.journal.current!.cursor-1].label}</span>}</div>
            <div className="conversation-studio__editor-actions">{(promptChanged||record.draft.compiled?.source==="user"&&!record.draft.compiled.requirements_synced)&&<button disabled={Boolean(busy||proposal||llmUnavailableReason||adviceBusy||local.delta.trim()||!local.positive.trim())} onClick={()=>void previewTurn("sync_requirements")}>按手工提示词同步画面要求</button>}<button disabled={!dirty||conflict||unsavedEmptyPrompt||promptPreview} onClick={()=>void act("保存当前版本",async()=>{
              const saved=await save(),latest=localRef.current;
              setNotice(latest && (latest.positive!==(saved.draft.compiled?.positive||"") || latest.negative!==(saved.draft.compiled?.negative||""))
                ?"版本已保存；编辑框里与该版本不同的文字仍保留在本机草稿。":"当前内容已保存。");
            })}>保存当前版本</button></div></header>
          {local.restoredFrom && <p className="conversation-studio__source">{local.restoredFrom}</p>}
        </fieldset>
        <PromptToolsSheet key={record.id} disabled={Boolean(busy||pending||conflict)} initialSection={searchParams.has("artist_preset")?"identity":undefined}
          status={<>
            {fixedIdentityTags.length>0&&<p role="status" aria-label="固定 tag 生效状态" className={missingFixedTags.length?"studio-tag-status is-missing":"studio-tag-status"}>已选 {fixedIdentityTags.length} 个固定 tag，当前正向提示词包含 {fixedIdentityTags.length-missingFixedTags.length} 个。
              {missingFixedTags.length>0?` 未出现：${missingFixedTags.join("、")}。`:" 已同步，可直接生成。"}</p>}
            {local.requirements.layers.style.artist_preset&&<p className="studio-preset-summary">画师串：{local.requirements.layers.style.artist_preset.name}</p>}
            {local.artistPresetCustomized&&!local.requirements.layers.style.artist_preset&&<p className="studio-preset-summary">画师串「{local.artistPresetCustomized}」已自定义，文字保留在提示词中。</p>}
          </>}
          sections={[
            {id:"identity",label:"角色与画师",summary:`角色 ${normalizeIdentityTags(local.requirements.layers.subject.character_tags||[]).length} · 画师 ${normalizeIdentityTags([...(local.requirements.layers.style.manual_artist_tags||[]),...(local.requirements.layers.style.artists||[])],true).length}`,content:<>
              <ManualIdentityTags key={record.id} compact initiallyOpen modelProfileId={local.model} characters={local.requirements.layers.subject.character_tags||[]} series={local.requirements.layers.subject.series_tags||[]}
                artists={local.requirements.layers.style.manual_artist_tags||[]} onCharacters={character_tags=>layer("subject",{character_tags})}
                onSeries={series_tags=>layer("subject",{series_tags})} onArtists={manual_artist_tags=>editArtists(manual_artist_tags,"manual")}/>
              <ArtistPresetPicker key={"preset:"+record.id} active={local.requirements.layers.style.artist_preset} customized={local.artistPresetCustomized}
                model={local.model} preferredId={searchParams.get("artist_preset")} disabled={Boolean(busy||pending||conflict)} onApply={chooseArtistPreset} onRemove={()=>chooseArtistPreset(null)}/>
              <ArtistRecommendations key={"artists:"+record.id} prompt={local.positive} selected={local.requirements.layers.style.artists}
                alreadySelected={local.requirements.layers.style.manual_artist_tags} disabled={Boolean(busy||pending||conflict)} onChange={artists=>editArtists(artists,"recommended")} onRemoveArtist={removeArtist}/>
            </>},
            {id:"design",label:"画面设计",content:<SceneDesignControls key={"scene:"+record.id} requirements={local.requirements} onChange={requirements=>edit({requirements})}
              workspaceId={record.id} workspaceRevision={record.revision} delta={local.delta} positive={local.positive} negative={local.negative}
              disabled={Boolean(busy||pending||conflict)} adviceDisabledReason={llmUnavailableReason} llmContextKey={llmContextKey} onBusyChange={setAdviceBusy}/>},
            {id:"requirements",label:"分层要求",content:<>
              <LayerRequirementsEditor layers={local.requirements.layers} onLayerChange={layer}/>
              {record.draft.workspace_origin&&<button onClick={()=>void open(record.draft.workspace_origin!.workspace_id)}>打开来源会话</button>}
              {record.draft.reference_pin&&<Link to={"/references?example="+record.draft.reference_pin.example_id}>查看参考来源</Link>}
            </>},
            {id:"locks",label:"固定片段",summary:String((local.requirements.prompt_locks||[]).length),content:<PromptLocks key={"locks:"+record.id} positive={local.positive} negative={local.negative} locks={local.requirements.prompt_locks||[]} onChange={prompt_locks=>edit({requirements:{...local.requirements,prompt_locks}})}/>},
            {id:"translation",label:"中英对照",content:<PromptTranslationPreview positive={local.positive} negative={local.negative} model={local.model} disabled={Boolean(busy||pending||conflict)}/>},
          ]}/>
        <fieldset disabled={Boolean(busy||pending||conflict)} className="studio-editor-fields">
          <div className="conversation-field-heading"><label htmlFor="conversation-positive">正向提示词</label><button className="conversation-copy" aria-label="复制正向提示词" disabled={!local.positive} onClick={()=>void copyPrompt("positive")}><Copy size={15} aria-hidden="true"/>{copied==="positive"?"已复制":"复制"}</button></div>
          <textarea id="conversation-positive" className="conversation-prompt" rows={8} maxLength={20000} value={local.positive} placeholder="更新后的英文提示词显示在这里，也可以直接输入。" onChange={event=>{setCopied("");edit({positive:event.target.value});}} />
          {local.positive.trim() && missingFixedTags.length>0 && <p className="studio-tag-status is-missing">正文未包含 {missingFixedTags.length} 个已选 tag。直接生成按当前正文；更新提示词时仍选中的 tag 可能重新加入。若不再使用，请在“角色与画师”里取消选择。</p>}
          <details className="conversation-negative"><summary>负向提示词 <span>{local.negative.trim()?"已填写":"未使用"}</span></summary>
            <div className="conversation-field-heading"><label htmlFor="conversation-negative">负向提示词</label><button className="conversation-copy" aria-label="复制负向提示词" onClick={()=>void copyPrompt("negative")}>{copied==="negative"?"已复制":"复制"}</button></div>
            <textarea id="conversation-negative" className="conversation-prompt" rows={3} maxLength={20000} value={local.negative} onChange={event=>edit({negative:event.target.value})}/>
            <p className="conversation-muted">{negativeGuidance(local.model).note}</p>
            {negativeGuidance(local.model).text&&<button onClick={()=>edit({negative:appendNegative(local.negative,negativeGuidance(local.model).text)})}>补充模型负向建议</button>}
          </details>
          {lastChange&&<div className="conversation-studio__change"><span>最近一步</span><p>{lastChange.label}</p><details><summary>查看本次文字变化</summary><PromptChanges before={lastChange.before} after={lastChange.after}/></details></div>}
        </fieldset></>}
        results={<div ref={resultsPanel} className="studio-results-content">
          <header className="conversation-studio__section-heading"><h2>图片预览</h2><Link to="/generate">全部任务</Link></header>
          <WorkbenchImageResults record={record} local={local} runs={recentRuns} run={run} onSelectRun={setRun}
            disabled={Boolean(busy||pending||conflict||draftAtRisk)} onContinueRun={source=>void continueRun(source)} onRestoreRun={(source,onlyPrompt,version)=>void restoreRun(source,onlyPrompt,version)}/>
          {recentRuns.length>=runLimit&&runLimit<100&&<button onClick={()=>setRunLimit(value=>Math.min(100,value+20))}>加载更早图片</button>}
          {run&&<GenerationComparison workspaceId={record.id} currentRun={run} runs={recentRuns} disabled={Boolean(busy||pending||conflict)} onReuseSettings={(source,asset)=>void reuseRunSettings(source,asset)}/>}
        </div>}
        context={<div className="studio-context-controls">
          <label>模型<select value={local.model} disabled={Boolean(busy||pending||conflict)} onChange={event=>edit({model:event.target.value})}>{local.model===LEGACY_AESTHETIC&&<option value={LEGACY_AESTHETIC} disabled>{savedWorkflowSnapshot?"历史模型（由工作流快照确定）":"请选择明确模型"}</option>}{profiles.map(profile=><option key={profile.id} value={profile.id}>{profile.label}</option>)}</select></label>
          <label>创作工作流<select value={target?.workflow_profile_id||(savedWorkflowSnapshot?configuration?.workflow.id:"")} disabled={Boolean(busy||pending||conflict)} onChange={event=>{
            const next=workflows.find(item=>item.workflow_profile_id===event.target.value);if(!next||!configuration)return;
            edit({settings:changeGenerationModel({...local.settings,creation_configuration:configuration},next,local.model),workflowSnapshotRunId:null});
          }}><option value="">选择工作流</option>{savedWorkflowSnapshot&&!target&&<option value={configuration?.workflow.id} disabled>历史工作流快照（已清理的模板）</option>}{workflows.map(item=><option key={item.workflow_profile_id} value={item.workflow_profile_id}>{targetLabel(item,workflows)}</option>)}</select></label>
          <span className="studio-condition-summary">{resolvedConfiguration?.values.width} × {resolvedConfiguration?.values.height} · {resolvedConfiguration?.values.batch_size} 张 · {executionPolicy.mode==="auto"?"自动选择环境":"固定环境"}</span>
        </div>}
        settings={<fieldset disabled={Boolean(busy||pending||conflict)} className="studio-settings-fields">
          {target&&<p className="conversation-muted">{targetDescription(target)}</p>}
          {remoteEnabled&&configuration&&<CloudModelCatalogPanel
            environmentId={executionPolicy.mode==="pinned"?executionPolicy.environmentId:null}
            environmentName={executionPolicy.mode==="pinned"?environments.find(item=>item.id===executionPolicy.environmentId)?.display_name:undefined}
            configuration={configuration} schema={parameterSchema} disabled={Boolean(busy||pending||conflict)}
            onChange={next=>edit({settings:settingsFromConfiguration(next,local.settings,parameterSchema)})}
            onMappingApplied={()=>setMappingEpoch(value=>value+1)} onEnvironmentRefreshed={loraPrep.retry}/>}
          {configuration&&<GenerationSettingsPanel contextId={`${record.id}:${local.workflowSnapshotRunId || ""}`} configuration={configuration} schema={parameterSchema} recipes={target?.generation_recipes} defaultRecipeId={target?.default_recipe_id}
            disabled={Boolean(busy||pending||conflict)} onPendingChange={setParameterEditsPending}
            onChange={(next)=>edit({settings:settingsFromConfiguration(next,local.settings,parameterSchema)})}
            loraContent={<><LoraResources items={local.requirements.loras} model={local.model} family="anima" target={target} frozen={savedWorkflowSnapshot}
              disabled={Boolean(busy||pending||conflict)} onEditSnapshot={currentWorkflowTarget?adoptCurrentWorkflow:undefined}
              preparation={loraPrep} onChange={loras=>edit({requirements:{...local.requirements,loras}})}/>
              {target&&<details className="lora-remote-mapping"><summary>服务器文件与映射</summary>
                <button type="button" onClick={()=>{setResourceCheck(true);setMappingEpoch(value=>value+1);}}>检查当前环境资源与 LoRA 映射</button>
                {Boolean(availability?.resource_requirements?.length)&&<LoraMappingPanel key={JSON.stringify(availability?.resource_requirements)} remote={executionPolicy.mode==="pinned"?executionPolicy.environmentId:target.remote_profile_id} workflow={target.workflow_profile_id} resources={availability!.resource_requirements!} disabled={Boolean(busy||pending||conflict)} onSaved={()=>setMappingEpoch(value=>value+1)}/>}
              </details>}
            </>} />}
          {!target&&<p><Link to="/workflows">配置创作工作流</Link> · <Link to="/settings">添加运行环境</Link></p>}
          {availability?.message&&<p role="status">{availability.message}</p>}
        </fieldset>}
        generationBar={<div className="studio-generation-bar">
          {!showPendingEnvironment&&executionEnvironmentControl}
          <div className="studio-generation-action"><span role="status" id="conversation-generation-reason">{generationReason||"使用当前提示词与参数生成"}</span>
            {(parameterEditsPending || !configurationValid)&&<button type="button" onClick={()=>{setHistoryOpen(false);setParameterRequestKey(value=>value+1);}}>{parameterEditsPending?"确认生成参数":"查看无效参数"}</button>}
            <button className="conversation-generate" aria-describedby="conversation-generation-reason" disabled={Boolean(generationReason)} onClick={()=>void generate()}>生成图片</button>
          </div>
        </div>}
        composer={<div className="studio-composer">
          <div className="studio-rewrite-actions">
            <RewriteModeSelector value={local.mode} onChange={mode => edit({mode})} disabled={Boolean(busy || pending || conflict)} />
            <button type="button" className="studio-bold-rewrite" aria-label="大胆重构"
              title="探索新的构图、用光和背景，先预览改动再决定是否采用"
              disabled={Boolean(busy||pending||pendingRecoveryBlocked||proposal||conflict||llmUnavailableReason||adviceBusy)||!local.positive.trim()}
              onClick={()=>void previewTurn("bold_rewrite")}>大胆重构 <small>先预览</small></button>
          </div>
          <div className="conversation-field-heading"><label htmlFor="conversation-delta">这次想怎么改？</label><span className="conversation-muted">{local.delta.trim()?"意见尚未应用；直接生图仍使用当前提示词":"输入修改意见，再更新提示词"}</span></div>
          <div className="conversation-studio__composer-row"><textarea id="conversation-delta" rows={2} maxLength={4000} value={local.delta} disabled={Boolean(pending||conflict)} onChange={event=>edit({delta:event.target.value})} placeholder="描述人物、动作、场景，或这次希望改变的地方"/>
            <div className="conversation-studio__buttons">
              <button className="conversation-update" disabled={Boolean(busy||pending||pendingRecoveryBlocked||proposal||conflict||llmUnavailableReason||adviceBusy||unsavedEmptyPrompt)||(!local.delta.trim()&&!canCompileRequirements&&!local.positive.trim())} onClick={()=>void turn(!local.delta.trim())}>更新提示词</button>
              <button className="conversation-studio__combined" disabled={Boolean(executionReason||proposal||llmUnavailableReason||adviceBusy||unsavedEmptyPrompt)||!local.delta.trim()} onClick={()=>void turn(false,true)}>更新并生图</button>
            </div>
          </div>
          <div className="conversation-studio__composer-meta">
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
                <button type="button" aria-expanded={showLlmSettings} aria-controls="conversation-llm-settings" disabled={Boolean(busy || adviceBusy || thinking.saving || llmSettingsBusy)} onClick={() => setShowLlmSettings(value => !value)}><GearSix size={15} aria-hidden="true" />LLM 设置</button>
              </div>
            <div id="conversation-thinking-status" className="conversation-thinking-status">
              <span>{llmUnavailableReason || (thinking.mode === "unverified" ? `思考开关尚未验证。${thinking.message}` : thinking.mode === "required" ? thinking.message : "用于更新提示词和给我建议；开启后可能需要更久。")}</span>
              {thinking.error && <span role="alert">{thinking.error}</span>}
              {!thinking.current && !thinking.loading && <button type="button" onClick={() => void thinking.refresh()}>重新读取配置</button>}
            </div>
</details>

          </div>
          {llmUnavailableReason&&<p className="conversation-warning">{llmUnavailableReason}<button onClick={()=>setShowLlmSettings(true)}>配置改词模型</button></p>}
        </div>}
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
