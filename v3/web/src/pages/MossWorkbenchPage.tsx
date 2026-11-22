import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { ApiClientError, apiRequest } from "../lib/api";
import type {
  CreationConfiguration,
  GenerationTarget,
  GenerationTargetListResponse,
  GenerationRunRecord,
  ModelProfileOption,
  ExecutionPolicy,
} from "../lib/types";
import {editableRequirements, type ConversationRecord} from "../lib/conversation";
import {LoraResources} from "../components/LoraResources";
import {useLoraPreparation} from "../lib/loraLibrary";
import {MOSS_IMAGE_MODEL as MODEL,workbenchPathForModel,workspaceUrl} from "../lib/workbenchRoute";
import {mossWorkspacePrompt} from "../lib/mossWorkspacePrompt";
import {defaultGenerationSettings} from "../lib/generationSettings";
import { basicWorkflowSchema } from "../lib/workflowParameterSchema";
import {targetReady} from "../lib/workflowTargets";
import {
  configurationToGenerationPayload,
  configurationFromSettings,rebaseConfiguration,settingsFromConfiguration,
  resolveConfiguration,
} from "../lib/creationConfiguration";
import {
  recoverGenerationIntent,
  createGenerationIntent,
  getGenerationIntent,
  retryGenerationIntent,
  cancelGenerationIntent,
  confirmEnvironmentAssets,
  markEnvironmentRebuilt,
  type GenerationIntentRecord,
  type PendingGenerationIntent,
} from "../lib/generationIntents";
import { GenerationSettingsPanel } from "../components/GenerationSettingsPanel";
import { CloudModelCatalogPanel } from "../components/CloudModelCatalogPanel";
import ExecutionEnvironmentControl from "../components/ExecutionEnvironmentControl";
import { PromptToolsSheet } from "../components/PromptToolsSheet";
import {MossGenerationResults} from "../components/MossGenerationResults";
import {GallerySourcePreview} from "../components/GallerySourcePreview";
import {MossNegativePrompt} from "../components/MossNegativePrompt";
import "./MossWorkbenchPage.css";
const KEY = "moss-workbench-v1";
const WORKFLOW = "v3_moss_image_sft_int8";
function rejectedBeforeAcceptance(error: unknown): error is ApiClientError {
  return error instanceof ApiClientError && (error.details?.accepted === false || [
    "invalid_request", "remote_not_configured", "workflow_incompatible", "incompatible_workflow", "incompatible_model",
    "stale_compiled_prompt", "workspace_revision_conflict", "workflow_snapshot_missing", "lora_not_installed",
    "protected_prompt_changed", "reference_preset_unavailable", "mapping_revision_conflict", "rate_limited",
    "runtime_identity_mismatch", "runtime_identity_unavailable", "http_credentials_missing", "direct_preparation_timeout",
  ].includes(error.code));
}
type Mode = "raw" | "polish" | "expand";
type PendingDirectSubmission = {
  protocol: "direct-v1";
  clientRequestId: string;
  body: {
    submission_kind: "legacy" | "conversational";
    use_current_prompt?: boolean;
    workspace_id?: string;
    workspace_revision?: number;
    compiled_token?: string;
    workflow_snapshot_run_id?: string;
    positive_prompt: string;
    negative_prompt: string;
    model_profile: string;
    project_name: string;
    settings: ReturnType<typeof configurationToGenerationPayload>;
    remote_profile_id: string;
    workflow_profile_id: string;
  };
};
type Suggestion = {
  positive: string;
  manuallyEdited?: boolean;
  negative: string;
  changes: string[];
  warnings: string[];
  engine: string;
  mode: string;
};
const baseline = {
  width: 1024,
  height: 1024,
  steps: 25,
  cfg: 2.5,
  sampler: "er_sde",
  scheduler: "simple",
  seed: "-1",
  batch_size: 1,
};
function mossSchema(workflowId:string, revision:string) {
  const schema=basicWorkflowSchema(workflowId,revision);
  schema.fields=schema.fields.map(field=>({...field,default:baseline[field.key as keyof typeof baseline]??field.default,
    ...(["width","height"].includes(field.key)?{step:16}:{})}));
  return schema;
}
const initialConfiguration: CreationConfiguration = {
  modelProfile: MODEL,
  workflow: { id: WORKFLOW, revision: "" },
  baseRecipeId: "moss_baseline",
  recipeValues: baseline,
  parameterOverrides: {},
  resourceRequirements: [],
  seedMode: "random",
};
type Draft = {
  source: string;
  negative: string;
  mode: Mode;
  suggestion: Suggestion | null;
  adopted: boolean;
  suggestionAdopted: boolean;
  output: string;
  outputEdited: boolean;
  environment: string;
  executionPolicy?: ExecutionPolicy;
  workspaceRevision?: number;
  borrowedReference?: boolean;
  configuration: CreationConfiguration;
  pending?: PendingGenerationIntent | PendingDirectSubmission;
  unconfirmed: PendingDirectSubmission[];
  lastRunId?: string;
};
function load(key: string, workspace?: ConversationRecord): Draft {
  const settings = workspace?.draft.generation_settings;
  const snapshot = workspace?.draft.generation_source;
  const prompt = mossWorkspacePrompt(workspace);
  const configuration = settings ? configurationFromSettings(settings,MODEL,undefined,{preserveSnapshot:true}) : initialConfiguration;
  const policy = settings?.execution_policy || (settings?.remote_profile_id || snapshot?.remote_profile_id
    ? {mode:"pinned" as const,environmentId:(settings?.remote_profile_id || snapshot?.remote_profile_id)!}
    : {mode:"auto" as const,preferredEnvironmentIds:[]});
  const empty: Draft = {
    ...prompt,
    mode: "raw",
    suggestion: null,
    adopted: false,
    suggestionAdopted: false,
    output: "",
    outputEdited: false,
    environment: workspace && policy.mode==="pinned" ? policy.environmentId : "",
    ...(workspace ? {workspaceRevision:workspace.revision,executionPolicy:policy}:{}),
    configuration: {...configuration,resourceRequirements:workspace?.draft.requirements?.loras || configuration.resourceRequirements},
    unconfirmed: [],
    lastRunId: snapshot?.model_profile === MODEL ? snapshot.run_id : undefined,
  };
  try {
    const saved = JSON.parse(localStorage.getItem(key) || "null");
    if (saved) {
      const pending = saved.pending as Draft["pending"];
      const unconfirmed = Array.isArray(saved.unconfirmed) ? saved.unconfirmed : [];
      const current = !workspace || saved.workspaceRevision===workspace.revision;
      return {
        ...empty,...(current ? saved : {}),
        suggestionAdopted: current && (saved.suggestionAdopted ?? Boolean(saved.adopted)),
        outputEdited: current && (saved.outputEdited ?? Boolean(saved.adopted && saved.suggestion && saved.output!==saved.suggestion.positive)),
        lastRunId: current && typeof saved.lastRunId === "string" && saved.lastRunId.length<=128 ? saved.lastRunId : empty.lastRunId,
        configuration: current && saved.configuration && (!saved.configuration.modelProfile || saved.configuration.modelProfile===MODEL)
          ? {...empty.configuration,...saved.configuration,modelProfile:MODEL} : empty.configuration,
        pending: pending?.protocol === "direct-v1" ? undefined : pending,
        unconfirmed: pending?.protocol === "direct-v1"
          ? [...unconfirmed.filter((item: PendingDirectSubmission) => item.clientRequestId !== pending.clientRequestId), pending]
          : unconfirmed,
      };
    }
    return empty;
  } catch {
    return empty;
  }
}
type MossProps = {
  modelProfiles?: ModelProfileOption[];
  remoteEnabled?: boolean;
};
export function MossWorkbenchPage(props: MossProps) {
  const [query] = useSearchParams();
  const id = query.get("workspace");
  return id===null ? <MossEditor key="standalone" {...props}/> : <WorkspaceEntry key={id} id={id} {...props}/>;
}

function WorkspaceEntry({id,...props}: MossProps & {id:string}) {
  const location=useLocation();
  const [record,setRecord]=useState<ConversationRecord|null>(null);
  const [error,setError]=useState("");
  useEffect(()=>{
    let live=true;
    if(!id){setError("缺少来源创作记录的标识。");return;}
    apiRequest<ConversationRecord>("/api/v3/workspaces/"+encodeURIComponent(id))
      .then(value=>{if(live){if(value.id!==id) throw new Error("没有找到所选创作记录。");setRecord(value);}})
      .catch(e=>{if(live)setError(e instanceof Error?e.message:"无法读取创作记录。");});
    return ()=>{live=false;};
  },[id]);
  if (record) {
    try {
      const path=workbenchPathForModel(record.draft?.model_profile,props.modelProfiles);
      if(path!=="/moss")return <Navigate replace to={{pathname:path,search:location.search,hash:location.hash}}/>;
    } catch(e) { return <p role="alert">{e instanceof Error?e.message:"无法识别来源模型。"}</p>; }
    return <MossEditor {...props} sourceWorkspace={record}/>;
  }
  return error ? <p role="alert">{error}</p> : <p role="status">正在读取创作记录…</p>;
}

function MossEditor({modelProfiles,remoteEnabled=false,sourceWorkspace}:MossProps & {sourceWorkspace?:ConversationRecord}) {
  const navigate=useNavigate();
  const [workspace,setWorkspace]=useState(sourceWorkspace);
  const storageKey=sourceWorkspace ? `${KEY}:workspace:${encodeURIComponent(sourceWorkspace.id)}` : KEY;
  const [draft,setDraft]=useState(()=>load(storageKey,sourceWorkspace));
  const gallerySource=sourceWorkspace?.draft.gallery_source;
  const [rightPane,setRightPane]=useState<"text"|"results"|"source">(()=>{
    if(gallerySource && (!draft.lastRunId || draft.lastRunId===sourceWorkspace?.draft.generation_source?.run_id))return "source";
    return draft.lastRunId?"results":"text";
  });
  const [negativeOpen,setNegativeOpen]=useState(Boolean(draft.negative));
  const paneChosen=useRef(false);
  const preparing = useRef(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [toolsSection, setToolsSection] = useState<string | undefined>();
  function changeToolsOpen(next: boolean) {
    setToolsOpen(next);
    if (!next) setToolsSection(undefined);
  }
  const root = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const element=root.current;
    if(!element)return;
    const measure=()=>element.style.setProperty("--moss-top",`${Math.max(0,Math.ceil(element.getBoundingClientRect().top))}px`);
    measure();
    const observer=typeof ResizeObserver==="undefined"?null:new ResizeObserver(measure);
    observer?.observe(element);
    window.addEventListener("resize",measure);
    return ()=>{observer?.disconnect();window.removeEventListener("resize",measure);};
  },[]);
  const [targets, setTargets] = useState<GenerationTarget[]>([]);
  const [busy, setBusy] = useState(false);
  const [generationBusy, setGenerationBusy] = useState(false);
  const [parametersPending, setParametersPending] = useState(false);
  const [creatingWorkspace,setCreatingWorkspace]=useState(false);
  const [error, setError] = useState("");
  const [intent, setIntent] = useState<GenerationIntentRecord | null>(null);
  const [run, setRun] = useState<GenerationRunRecord | null>(null);
  useEffect(()=>{
    if(draft.lastRunId || !remoteEnabled) return;
    const controller=new AbortController();
    const path=sourceWorkspace ? `/api/v3/workspaces/${encodeURIComponent(sourceWorkspace.id)}/runs?limit=30` : "/api/v3/generation-runs?limit=30";
    void apiRequest<{items:GenerationRunRecord[]}>(path,{signal:controller.signal}).then(result=>{
      if(controller.signal.aborted)return;
      const latest=result.items?.find(item=>item.source?.model_profile===MODEL || (!item.source?.model_profile && item.workflow_profile_id===WORKFLOW));
      if(!latest)return;
      setDraft(current=>current.lastRunId?current:{...current,lastRunId:latest.id});
      if(!paneChosen.current && revision.current===0)setRightPane("results");
    }).catch(()=>{});
    return ()=>controller.abort();
  },[draft.lastRunId,remoteEnabled,sourceWorkspace?.id]);
  const revision = useRef(0);
  const mounted = useRef(true);
  const generationAction = useRef(0);
  const activeAction = useRef<number | null>(null);
  const pendingRequest = useRef(draft.pending);
  pendingRequest.current = draft.pending;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generationAction.current++;
      activeAction.current = null;
    };
  }, []);
  const available =
    modelProfiles?.some((p) => p.id === MODEL && (!p.family || p.family === "moss")) ?? false;
  const snapshot = workspace?.draft.generation_source;
  const workflowId=snapshot?.workflow_profile_id || draft.configuration.workflow.id || WORKFLOW;
  const policy:ExecutionPolicy=draft.executionPolicy || {mode:"pinned",environmentId:draft.environment};
  const compatible = targets.filter(
    (t) =>
      t.compatible_model_profiles.includes(MODEL) &&
      t.workflow_profile_id === workflowId,
  );
  const target = policy.mode==="pinned" ? compatible.find(t=>t.remote_profile_id===policy.environmentId)
    : policy.preferredEnvironmentIds.map(id=>compatible.find(t=>t.remote_profile_id===id)).find(Boolean) || compatible[0];
  const liveTemplates=targets.filter(t=>t.compatible_model_profiles.includes(MODEL) && t.template_revision && t.availability!=="disabled" &&
    (policy.mode!=="pinned" || t.remote_profile_id===policy.environmentId) &&
    (t.lora_extension_supported!==false || Boolean(t.lora_slot_order?.length)));
  const preferredEnvironment=policy.mode==="auto"?policy.preferredEnvironmentIds.find(id=>liveTemplates.some(t=>t.remote_profile_id===id)):undefined;
  const inEnvironment=preferredEnvironment?liveTemplates.filter(t=>t.remote_profile_id===preferredEnvironment):liveTemplates;
  const readyTemplates=inEnvironment.filter(targetReady);
  const eligible=readyTemplates.length?readyTemplates:inEnvironment;
  const liveTemplate=eligible.find(t=>t.workflow_profile_id===workflowId) || eligible.find(t=>t.workflow_profile_id===WORKFLOW) || eligible[0];
  const fallback=mossSchema(workflowId,target?.template_revision || "");
  const savedSchema=workspace?.draft.generation_settings?.parameter_schema;
  const matchingSchema=savedSchema?.workflowId===workflowId && (!target || savedSchema.templateRevision===target.template_revision) ? savedSchema : undefined;
  const schema=snapshot ? savedSchema || fallback : target?.parameter_schema || matchingSchema || fallback;
  const configuration=target && !snapshot ? configurationFromSettings(
    {...(workspace?.draft.generation_settings || defaultGenerationSettings()),creation_configuration:draft.configuration},
    MODEL,{...target,parameter_schema:schema},
  ) : draft.configuration;
  const snapshotValid=!snapshot || Boolean(snapshot.model_profile===MODEL && configuration.workflow.id===workflowId && configuration.workflow.revision &&
    savedSchema?.workflowId===workflowId && savedSchema.templateRevision===configuration.workflow.revision);
  const readyWorkflow=snapshot ? snapshotValid && (policy.mode!=="pinned" || Boolean(policy.environmentId)) : Boolean(target?.template_revision);
  const loraRemote=policy.mode==="pinned"?policy.environmentId:target?.remote_profile_id;
  const loraPrep=useLoraPreparation(remoteEnabled?loraRemote:undefined,configuration.resourceRequirements);
  const values = resolveConfiguration(configuration, schema);
  const dimensionsValid =
    Number(values.values.width) % 16 === 0 &&
    Number(values.values.height) % 16 === 0;
  const output =
    draft.mode === "raw" ? draft.source : draft.adopted ? draft.output : "";
  function applyReceipt(result: GenerationRunRecord | null, source: Record<string,unknown>) {
    if(result?.id){
      setRun(result);setRightPane("results");
      setDraft(current=>({...current,lastRunId:result.id}));
    }
    const receipt=result as (GenerationRunRecord & {workspace_id?:string;workspace_revision?:number;compiled_token?:string}) | null;
    if(!workspace || receipt?.workspace_id!==workspace.id || typeof receipt.workspace_revision!=="number" || !receipt.compiled_token) return;
    const revision=receipt.workspace_revision,token=receipt.compiled_token;
    setWorkspace(prev=>!prev || prev.revision>revision ? prev : {...prev,revision,draft:{...prev.draft,
      compiled:{positive:String(source.positive_prompt),negative:String(source.negative_prompt??""),source:"user",compiled_token:token}}});
    setDraft(d=>({...d,workspaceRevision:Math.max(d.workspaceRevision||0,revision)}));
  }
  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(draft));
    } catch {
      /* draft remains in memory */
    }
  }, [draft,storageKey]);
  useEffect(() => {
    let live = true;
    if (remoteEnabled)
      apiRequest<GenerationTargetListResponse>("/api/v3/generation-targets")
        .then((r) => {
          if (live) setTargets(r.items);
        })
        .catch(() => {
          if (live) setError("无法读取执行环境，请检查连接设置。");
        });
    return () => {
      live = false;
      revision.current++;
    };
  }, [remoteEnabled]);
  useEffect(() => {
    const pending = draft.pending;
    if (!pending || pending.protocol !== "intent-v1" || !intent || intent.state !== "resolving" || generationBusy)
      return;
    const intentId = intent.id;
    const actionVersion = generationAction.current;
    let stopped = false;
    let timer = 0;
    const poll = async () => {
      try {
        const result = await getGenerationIntent(intentId);
        if (stopped || !mounted.current || generationAction.current !== actionVersion || result.id !== intentId) return;
        setIntent(result);
        if(result.state==="accepted")applyReceipt(result.response,pending.body.source);
        setDraft((current) => {
          if (current.pending?.protocol !== "intent-v1" || current.pending.clientRequestId !== pending.clientRequestId)
            return current;
          return {
            ...current,
            pending:
              result.state === "accepted" || result.state === "canceled"
                ? undefined
                : { ...current.pending, intentId },
          };
        });
        if (result.state === "resolving")
          timer = window.setTimeout(() => void poll(), 800);
      } catch {
        if (!stopped)
          setError("暂时无法查询原请求状态，请继续原请求，避免重复提交。");
      }
    };
    timer = window.setTimeout(() => void poll(), 800);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [
    intent?.id,
    intent?.state,
    draft.pending?.clientRequestId,
    generationBusy,
  ]);
  function edit(patch: {source:string} | {negative:string} | {mode:Mode}) {
    revision.current++;
    setBusy(false);
    setError("");
    setDraft((d) => {
      const keepConfirmedOutput = "negative" in patch && d.adopted;
      return {...d,...patch,suggestion:null,suggestionAdopted:false,
        adopted:keepConfirmedOutput,outputEdited:keepConfirmedOutput && d.outputEdited,output:keepConfirmedOutput?d.output:""};
    });
  }
  async function assist() {
    const ticket = ++revision.current;
    setToolsSection(undefined);
    setBusy(true);
    setError("");
    try {
      const result = await apiRequest<Suggestion>(
        "/api/v3/moss/prompt-assist",
        {
          method: "POST",
          body: JSON.stringify({
            source_text: draft.source,
            negative_prompt: draft.negative,
            mode: draft.mode,
          }),
        },
      );
      if (ticket !== revision.current) return;
      setDraft((d) => ({
        ...d,
        suggestion: result,
        suggestionAdopted: false,
      }));
      setToolsSection("suggestions");
      setToolsOpen(true);
    } catch (caught) {
      if (ticket === revision.current)
        setError(`${caught instanceof ApiClientError&&caught.code==="moss_assistance_failed"?caught.message:"暂时无法获取提示词辅助，请重试。"} 原文和当前出图文本已保留。`);
    } finally {
      if (ticket === revision.current) setBusy(false);
    }
  }
  async function receive(
    request: () => Promise<GenerationIntentRecord>,
    pending?: PendingGenerationIntent,
  ) {
    const frozen = pending || pendingRequest.current;
    if (!mounted.current || activeAction.current !== null || !frozen || frozen.protocol !== "intent-v1") return;
    const ticket = ++generationAction.current;
    activeAction.current = ticket;
    const current = () => mounted.current && activeAction.current === ticket &&
      pendingRequest.current?.clientRequestId === frozen.clientRequestId;
    setGenerationBusy(true);
    setError("");
    try {
      const result = await request();
      if (!current() || (frozen.intentId && result.id !== frozen.intentId)) return;
      setIntent(result);
      if(result.state==="accepted")applyReceipt(result.response,frozen.body.source);
      const nextPending = result.state === "accepted" || result.state === "canceled"
        ? undefined : { ...frozen, intentId: result.id };
      pendingRequest.current = nextPending;
      setDraft((d) => d.pending?.clientRequestId !== frozen.clientRequestId ? d : ({
        ...d,
        pending: nextPending,
      }));
    } catch (caught) {
      if (!current()) return;
      if (!frozen.intentId && rejectedBeforeAcceptance(caught)) {
        pendingRequest.current = undefined;
        setDraft(d => d.pending?.clientRequestId === frozen.clientRequestId ? {...d, pending: undefined} : d);
        setIntent(null);
        setError(caught.message);
      } else {
        setError("尚未确认本次请求状态，请继续原请求，避免重复提交。");
      }
    } finally {
      if (mounted.current && activeAction.current === ticket) {
        activeAction.current = null;
        setGenerationBusy(false);
      }
    }
  }
  function forgetDirect(request: PendingDirectSubmission) {
    setDraft((d) => ({
      ...d,
      pending: d.pending?.clientRequestId === request.clientRequestId ? undefined : d.pending,
      unconfirmed: d.unconfirmed.filter((item) => item.clientRequestId !== request.clientRequestId),
    }));
  }
  async function receiveDirect(request: PendingDirectSubmission, query = false) {
    if (!mounted.current || activeAction.current !== null) return;
    const ticket = ++generationAction.current;
    activeAction.current = ticket;
    const current = () => mounted.current && activeAction.current === ticket;
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 15000);
    setGenerationBusy(true);
    setError("");
    setIntent(null);
    if (!query) setRun(null);
    try {
      let result: GenerationRunRecord;
      if (query) {
        const receipt = await apiRequest<{found: boolean; response: GenerationRunRecord | null}>(
          `/api/v3/generation-submissions/by-key?key=${encodeURIComponent(request.clientRequestId)}`,
          {signal: controller.signal},
        );
        if (!current()) return;
        if (!receipt.found || !receipt.response) {
          setError("暂未找到已接受任务，仍可换连接重新生成；旧任务仍可能完成。");
          return;
        }
        result = receipt.response;
      } else {
        result = await apiRequest<GenerationRunRecord>("/api/v3/direct-prompt/runs", {
          method: "POST", body: JSON.stringify(request.body),
          headers: {"Idempotency-Key": request.clientRequestId}, signal: controller.signal,
        });
      }
      if (!current()) return;
      if (typeof result?.id !== "string" || !result.id.trim() || ![
        "draft", "connecting", "preparing", "queued", "running", "downloading", "completed", "failed", "canceled", "remote_missing",
      ].includes(result.state)) throw new ApiClientError("提交回执不完整，结果尚未确认。", "submission_unconfirmed");
      setRun(result);
      applyReceipt(result,request.body);
      forgetDirect(request);
    } catch (caught) {
      if (!current()) return;
      const rejected = !query && rejectedBeforeAcceptance(caught);
      if (rejected) {
        forgetDirect(request);
        setError((caught as Error).message);
      } else {
        setDraft((d) => ({
          ...d,
          pending: d.pending?.clientRequestId === request.clientRequestId ? undefined : d.pending,
          unconfirmed: [...d.unconfirmed.filter((item) => item.clientRequestId !== request.clientRequestId), request],
        }));
        setError(query ? "暂时无法查询上次提交，仍可换连接重新生成。" : "本次提交结果尚未确认，可查询上次提交，也可换连接重新生成。");
      }
    } finally {
      window.clearTimeout(timer);
      if (current()) {
        activeAction.current = null;
        setGenerationBusy(false);
      }
    }
  }
  async function saveConditions(record: ConversationRecord, nextConfiguration=configuration, nextSchema=schema, detachSource=false):Promise<ConversationRecord> {
    const previous=record.draft.generation_settings || defaultGenerationSettings();
    const priorConfig=configurationFromSettings(previous,MODEL,undefined,{preserveSnapshot:true});
    const priorPolicy=previous.execution_policy || (previous.remote_profile_id || snapshot?.remote_profile_id ?
      {mode:"pinned",environmentId:previous.remote_profile_id || snapshot?.remote_profile_id} : {mode:"auto",preferredEnvironmentIds:[]});
    const requirements=editableRequirements(record);
    const resourcesChanged=JSON.stringify(nextConfiguration.resourceRequirements)!==JSON.stringify(requirements.loras);
    if(!detachSource && !resourcesChanged && record.draft.compiled?.compiled_token && record.draft.compiled.positive===output && record.draft.compiled.negative===draft.negative &&
      JSON.stringify(priorConfig)===JSON.stringify(nextConfiguration) && JSON.stringify(policy)===JSON.stringify(priorPolicy)) return record;
    const settings={...settingsFromConfiguration(nextConfiguration,previous,nextSchema),remote_profile_id:policy.mode==="pinned"?policy.environmentId:null,execution_policy:policy};
    const {positive_text,excluded_text,input_mode,natural_text,selected_tags,suppressed_tags,mode}=record.draft;
    return apiRequest<ConversationRecord>("/api/v3/workspaces/"+encodeURIComponent(record.id),{method:"PUT",body:JSON.stringify({
      revision:record.revision,title:record.title,draft:{model_profile:MODEL,mode,positive_text,excluded_text,input_mode,natural_text,selected_tags,suppressed_tags,
        ...(detachSource?{detach_generation_source:true}:{}),
        ...(resourcesChanged?{requirements_edit:{...requirements,loras:nextConfiguration.resourceRequirements}}:{}),
        generation_settings:settings,...(output.trim()?{prompt_edit:{positive:output,negative:draft.negative}}:{})},
    })});
  }
  async function editSnapshotLoras() {
    if(!snapshot || !workspace || !liveTemplate || preparing.current || activeAction.current!==null || pendingRequest.current)return;
    preparing.current=true;
    setGenerationBusy(true);
    setError("");
    try {
      const nextSchema=liveTemplate.parameter_schema || mossSchema(liveTemplate.workflow_profile_id,liveTemplate.template_revision!);
      const next=rebaseConfiguration(configuration,{...liveTemplate,parameter_schema:nextSchema});
      if(next.seedMode==="fixed" && next.parameterOverrides.seed==null)next.parameterOverrides={...next.parameterOverrides,seed:String(values.values.seed)};
      const saved=await saveConditions(workspace,next,nextSchema,true);
      if(saved.id!==workspace.id || saved.draft.generation_source || saved.draft.model_profile!==MODEL)
        throw new Error("未能确认当前工作流，请重新打开此创作记录。");
      if(mounted.current){
        setWorkspace(saved);
        setDraft(d=>({...d,configuration:next,workspaceRevision:saved.revision}));
      }
    } catch(e) {
      if(mounted.current)setError(e instanceof Error?e.message:"无法切换当前模板，请重新打开此创作记录后重试。");
    } finally {
      preparing.current=false;
      if(mounted.current)setGenerationBusy(false);
    }
  }
  async function createWorkspace() {
    if(preparing.current || activeAction.current!==null || pendingRequest.current)return;
    preparing.current=true;
    setCreatingWorkspace(true);setGenerationBusy(true);setError("");
    const requestStorageKey=storageKey+":new-workspace";
    try {
      // Keep both the old draft and the creation receipt recoverable if the response is lost.
      localStorage.setItem(storageKey,JSON.stringify(draft));
      let request:{key:string;body:string}|null=null;
      try {
        const saved=JSON.parse(localStorage.getItem(requestStorageKey)||"null");
        if(typeof saved?.key==="string" && typeof saved?.body==="string")request=saved;
      } catch { /* A malformed retry record cannot be sent. Start a new request. */ }
      if(!request) {
        const fresh=structuredClone(initialConfiguration);
        const settings={...settingsFromConfiguration(fresh,defaultGenerationSettings(),mossSchema(WORKFLOW,"")),
          remote_profile_id:null,execution_policy:{mode:"auto",preferredEnvironmentIds:[]}};
        request={key:crypto.randomUUID(),body:JSON.stringify({title:"新创作",draft:{mode:"faithful",model_profile:MODEL,generation_settings:settings}})};
        localStorage.setItem(requestStorageKey,JSON.stringify(request));
      }
      const record=await apiRequest<ConversationRecord>("/api/v3/workspaces",{
        method:"POST",body:request.body,headers:{"Idempotency-Key":request.key},
      });
      if(!mounted.current)return;
      if(!record?.id || !Number.isInteger(record.revision) || record.draft?.model_profile!==MODEL)
        throw new Error("新创作回执不完整，请重试；当前草稿已保留。");
      const destination=workspaceUrl(record,modelProfiles);
      localStorage.removeItem(requestStorageKey);
      navigate(destination);
    } catch(caught) {
      if(mounted.current)setError(caught instanceof Error?caught.message:"暂时无法新建创作，当前草稿已保留，请重试。");
    } finally {
      preparing.current=false;
      if(mounted.current){setCreatingWorkspace(false);setGenerationBusy(false);}
    }
  }
  async function generate() {
    if (preparing.current || activeAction.current!==null || pendingRequest.current?.protocol==="intent-v1" || parametersPending || loraPrep.blocked || !readyWorkflow || !output.trim() || !values.valid || !dimensionsValid) return;
    preparing.current=true;
    setGenerationBusy(true);
    setError("");
    try {
      if(loraPrep.state!=="idle")await loraPrep.verifyCurrent();
      const saved=workspace ? await saveConditions(workspace) : undefined;
      if(!mounted.current)return;
      if(saved && (!saved.draft.compiled?.compiled_token || saved.id!==workspace?.id || saved.draft.model_profile!==MODEL))
        throw new Error("未能确认来源记录的保存版本，请重新打开此记录。");
      if(saved) {setWorkspace(saved);setDraft(d=>({...d,workspaceRevision:saved.revision}));}
      const source={
        ...(saved?{submission_kind:"conversational" as const,use_current_prompt:true,workspace_id:saved.id,workspace_revision:saved.revision,
          compiled_token:saved.draft.compiled!.compiled_token,...(snapshot?{workflow_snapshot_run_id:snapshot.run_id}:{})}:{submission_kind:"legacy" as const}),
        positive_prompt:output,negative_prompt:draft.negative,model_profile:MODEL,project_name:"MOSS",settings:configurationToGenerationPayload(configuration,schema),
        ...(!saved && configuration.resourceRequirements.length ? {lora_selection:configuration.resourceRequirements.map(({required:_required,source:_source,...item})=>item)} : {}),
      };
      const clientRequestId=crypto.randomUUID();
      const pending:PendingGenerationIntent|PendingDirectSubmission=policy.mode==="auto"||snapshot
        ? {protocol:"intent-v1",clientRequestId,body:{source,creationConfiguration:{...configuration},executionPolicy:policy}}
        : {protocol:"direct-v1",clientRequestId,body:{...source,remote_profile_id:policy.environmentId,workflow_profile_id:workflowId}};
      try {localStorage.setItem(storageKey,JSON.stringify({...draft,workspaceRevision:saved?.revision,pending}));}
      catch {throw new Error("无法保存请求凭证，请释放浏览器存储后重试。");}
      setDraft(d=>({...d,pending}));
      pendingRequest.current=pending;
      if(pending.protocol==="direct-v1")await receiveDirect(pending);
      else await receive(()=>createGenerationIntent(pending.body,pending.clientRequestId),pending);
    } catch(e) {
      if(mounted.current)setError(e instanceof Error?e.message:"暂时无法提交此创作记录。");
    } finally {
      preparing.current=false;
      if(mounted.current)setGenerationBusy(false);
    }
  }
  const pendingSuggestion=Boolean(draft.suggestion&&!draft.suggestionAdopted);
  const manuallyEdited=draft.outputEdited && (!draft.suggestionAdopted || draft.output!==draft.suggestion?.positive);
  const confirmedStatus=manuallyEdited?"已手动编辑出图文本":draft.suggestionAdopted?"已采用辅助建议":"使用已确认文本";
  const textStatus = draft.mode === "raw" ? "使用中文原文"
    : draft.adopted ? busy?"保留当前文本，正在获取新建议":pendingSuggestion?"保留当前文本，新建议待采用":confirmedStatus : busy ? "正在获取辅助建议"
    : draft.suggestion ? "建议待采用" : "尚未采用建议";
  const generationReason = creatingWorkspace ? "正在新建创作…" : generationBusy ? "正在提交本次生成…"
    : draft.pending?.protocol === "intent-v1" ? "请先继续或取消原请求"
    : parametersPending ? "生成参数有修改待确认"
    : !remoteEnabled ? "请先启用并配置出图环境"
    : !available ? "当前未配置 MOSS 模型"
    : !snapshotValid ? "原任务缺少匹配的工作流版本或参数声明，无法按此快照生成。"
    : !readyWorkflow ? "请选择可用的 MOSS 工作流执行环境"
    : draft.mode !== "raw" && !draft.adopted ? "请先获取并采用辅助建议，或切换为原文直接出图"
    : !output.trim() ? "请填写本次出图文本"
    : !dimensionsValid ? "宽高必须为 16 的倍数。"
    : !values.valid ? "请检查生成参数" : loraPrep.blocked ? loraPrep.message : "使用当前出图文本与参数生成";
  return (
    <div ref={root} className="moss-workbench">
      <header className="moss-header">
        <div><span className="moss-eyebrow">中文自然语言</span><h1>MOSS 工作台</h1><p>{workspace?`来源：${workspace.title}${snapshot?" · 历史工作流快照":""}`:"保留原意，按需润色或扩写"}</p></div>
        <div className="moss-header-actions"><button type="button" disabled={generationBusy||Boolean(draft.pending)}
          title={draft.pending?"请先处理当前生成请求，再新建创作。":"保留当前草稿，打开空白创作"}
          onClick={()=>void createWorkspace()}>{creatingWorkspace?"正在新建…":"新建创作"}</button>
          <Link to="/settings">共享 LLM 与连接设置</Link></div>
      </header>
      <div className="moss-studio">
        <div className="moss-tools">
            <fieldset className="moss-modes"><legend>处理方式</legend>
              {([["raw","原文直接出图"],["polish","只整理润色"],["expand","创意扩写"]] as const).map(([mode,label])=><label key={mode} className={draft.mode===mode?"is-selected":""}>
                <input type="radio" name="moss-mode" checked={draft.mode===mode} onChange={()=>edit({mode})}/>{label}
              </label>)}
            </fieldset>
          <PromptToolsSheet open={toolsOpen} onOpenChange={changeToolsOpen} initialSection={toolsSection} sections={[
            {id:"negative",label:"排除内容",summary:draft.negative.trim()?"已填写":"未填写",content:<div className="moss-tool-content">
              <h3>不希望出现在画面中的内容</h3><p className="moss-hint">负向提示词在正文区直接编辑，修改时保留你已经确认的正向文本。</p>
              <button type="button" onClick={()=>{changeToolsOpen(false);setNegativeOpen(true);}}>在正文区编辑负向提示词</button>
            </div>},
            {id:"parameters",label:"生成参数",summary:`${values.values.width} × ${values.values.height}`,content:<div className="moss-tool-content">
              <h3>MOSS 生成参数</h3><p className="moss-hint">MOSS 原生单阶段 · MOSS Image SFT INT8</p>
              {gallerySource && <p className="moss-hint">{gallerySource.mode==="generation"
                ? "已带入来源图记录的参数。恢复按钮会改回模板默认值。"
                : "已带入来源图可读取的参数，缺失项使用模型默认值。"}</p>}
              <GenerationSettingsPanel contextId={snapshot?.run_id || "live"} configuration={configuration} schema={schema} disabled={generationBusy||Boolean(draft.pending)} recipes={snapshot?undefined:target?.generation_recipes} onChange={c=>setDraft(d=>({...d,configuration:c}))}
                onPendingChange={setParametersPending} validateApply={values=>Number(values.width)%16===0 && Number(values.height)%16===0 ? undefined : "宽高必须为 16 的倍数。"}
                loraContent={<LoraResources items={configuration.resourceRequirements} model={MODEL} family="moss" target={target} frozen={Boolean(snapshot)}
                  onEditSnapshot={snapshot && liveTemplate ? ()=>void editSnapshotLoras() : undefined}
                  disabled={generationBusy||Boolean(draft.pending)} preparation={loraPrep} onChange={items=>setDraft(d=>({...d,configuration:{...configuration,resourceRequirements:items}}))}/>} />
              {!dimensionsValid&&<p role="alert">宽高必须为 16 的倍数。</p>}
            </div>},
            {id:"resources",label:"云端资源",content:<div className="moss-tool-content">
              <h3>模型与工作流资源</h3><label>模型配置<select aria-label="模型配置" value={MODEL} disabled><option value={MODEL}>MOSS Image SFT INT8</option></select></label>
              <p className="moss-hint">工作流：{workflowId}{snapshot?" · 历史快照":""}</p>
              {configuration.resourceRequirements.length>0 && <p>已启用 {configuration.resourceRequirements.filter(item=>item.enabled!==false).length} 项 LoRA，可在「生成参数」中查看和调整。</p>}
              <CloudModelCatalogPanel environmentId={loraRemote||null} configuration={configuration} schema={schema}
                disabled={generationBusy||Boolean(draft.pending)} onEnvironmentRefreshed={loraPrep.retry} onChange={c=>setDraft(d=>({...d,configuration:c}))}/>
              <Link to="/workflows">管理资源与工作流</Link>
            </div>},
            {id:"suggestions",label:"辅助建议",summary:draft.suggestion?(draft.suggestionAdopted?(manuallyEdited?"正文已手动编辑":"已采用"):"待采用"):"可选",content:<div className="moss-tool-content">
              <p className="moss-hint">审阅并编辑后，点击“采用建议”才会更新本次出图文本。关闭抽屉会保留建议，不会自动采用。</p>
              {draft.adopted&&pendingSuggestion&&<p role="status">当前出图文本已保留；采用这份新建议后才会替换。</p>}
              {manuallyEdited&&draft.suggestionAdopted&&<p role="status">再次采用这份建议，会替换手动编辑的出图文本。</p>}
                        {draft.suggestion && (
            <section className="moss-suggestion">
              <h3>审阅辅助建议</h3>
              <label>
                建议文本
                <textarea
                  aria-label="建议文本"
                  rows={6}
                  value={draft.suggestion.positive}
                  onChange={(e) => {
                    const positive=e.target.value;
                    revision.current++;
                    setBusy(false);
                    setDraft((d) => ({
                      ...d,
                      suggestion: {
                        ...d.suggestion!,
                        positive,
                        manuallyEdited: true,
                      },
                      suggestionAdopted: false,
                    }));
                  }}
                />
              </label>
              <p>排除内容保留：{draft.negative || "无"}</p>
              <ul>
                {draft.suggestion.changes.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
              {draft.suggestion.warnings.map((s, i) => (
                <p key={i} role="status">
                  {s}
                </p>
              ))}
              <button
                disabled={busy}
                onClick={() => {
                  setDraft((d) => ({
                    ...d,
                    adopted: true,
                    suggestionAdopted: true,
                    output: d.suggestion!.positive,
                    outputEdited: Boolean(d.suggestion!.manuallyEdited),
                  }));
                  changeToolsOpen(false);
                }}
              >
                采用建议
              </button>
            </section>
          )}

              {!draft.suggestion&&<p role="status">选择“只整理润色”或“创意扩写”，再点击主区的“获取建议”。中文原文可以直接出图。</p>}
            </div>},
          ]}/>
        </div>
        <div className="moss-columns">
          <section className="moss-card" aria-label="创作原文工作区">
            <header className="moss-card-heading"><h2>创作原文</h2><span>中文直接使用</span></header>
            {draft.borrowedReference && <p className="moss-hint">原文来自参考案例中已借用的画面要求，可直接编辑。</p>}

            <label className="moss-prompt-field">原文<textarea aria-label="原文" rows={8} value={draft.source} placeholder="描述主体、画风、构图与希望画面出现的中文文字…" onChange={e=>edit({source:e.target.value})}/></label>
            <p className="moss-hint moss-editor-note">原文直接出图不调用 LLM。润色整理表达，扩写补充细节；你明确写出的内容继续保留。</p>
            <MossNegativePrompt value={draft.negative} onChange={value=>edit({negative:value})} expanded={negativeOpen} onExpandedChange={setNegativeOpen}/>
          </section>
          <section className="moss-card" aria-label="本次出图文本工作区">
            <div className="moss-result-tabs" role="tablist" aria-label="出图文本与结果">
              <button id="moss-text-tab" type="button" role="tab" aria-selected={rightPane==="text"} aria-controls="moss-text-pane" onClick={()=>{paneChosen.current=true;setRightPane("text");}}>出图文本</button>
              {gallerySource && <button id="moss-source-tab" type="button" role="tab" aria-selected={rightPane==="source"} aria-controls="moss-source-pane" onClick={()=>{paneChosen.current=true;setRightPane("source");}}>来源原图</button>}
              <button id="moss-results-tab" type="button" role="tab" aria-selected={rightPane==="results"} aria-controls="moss-results-pane" onClick={()=>{paneChosen.current=true;setRightPane("results");}}>生成结果</button>
            </div>
            <div id="moss-text-pane" role="tabpanel" aria-labelledby="moss-text-tab" className="moss-text-pane" hidden={rightPane!=="text"}>
            <header className="moss-card-heading"><h2>确认出图文本</h2><span role="status" aria-label="本次出图文本状态" className={draft.mode!=="raw"&&!draft.adopted?"moss-text-status is-pending":"moss-text-status"}>{textStatus}</span></header>
            <label className="moss-prompt-field">本次出图文本<textarea aria-label="本次出图文本" rows={8} readOnly={draft.mode==="raw"||!draft.adopted} value={output}
              placeholder={draft.mode==="raw"?"左侧原文会直接用于生成，无需翻译":"获取并采用辅助建议后，实际出图文本会显示在这里"} onChange={e=>{
                const text=e.target.value;
                setDraft(d=>({...d,output:text,outputEdited:!d.suggestionAdopted || text!==d.suggestion?.positive || Boolean(d.suggestion?.manuallyEdited)}));
              }}/></label>
            <div className="moss-output-actions">
              {draft.mode!=="raw"&&<button type="button" onClick={()=>edit({mode:"raw"})}>使用原文</button>}
              {draft.suggestion&&<button type="button" onClick={()=>{setToolsSection("suggestions");setToolsOpen(true);}}>审阅辅助建议</button>}
              <span className="moss-hint">{draft.mode==="raw"?"提交左侧中文原文，不强制翻译。":draft.adopted?"提交上方文本，也可以继续手工编辑。":"建议需要明确采用，才会用于生成。"}</span>
            </div>
            </div>
            <div id="moss-results-pane" role="tabpanel" aria-labelledby="moss-results-tab" className="moss-results-pane" hidden={rightPane!=="results"}>
              {rightPane==="results" && <MossGenerationResults runId={draft.lastRunId}/>}
            </div>
            {gallerySource && <div id="moss-source-pane" role="tabpanel" aria-labelledby="moss-source-tab" className="moss-results-pane" hidden={rightPane!=="source"}>
              {rightPane==="source" && <GallerySourcePreview source={gallerySource}/>}
            </div>}
          </section>
        </div>
        <footer className="moss-dock" aria-label="MOSS 出图操作">
          <div className="moss-dock-status">
            {error&&<p role="alert">{error}</p>}
            {!available&&<p role="status">当前未配置 MOSS 模型，请先在设置中完成资源配置。</p>}
            <div className="moss-receipts">          {draft.unconfirmed.length > 0 && <section aria-label="上次提交查询" className="moss-hint">
            <p>有提交结果尚未确认；旧任务仍可能完成。你可以继续编辑或换连接生成新任务。</p>
            {draft.unconfirmed.map((request) => <div key={request.clientRequestId}>
              <button disabled={generationBusy} onClick={() => void receiveDirect(request, true)}>查询上次提交</button>
              <button disabled={generationBusy} onClick={() => forgetDirect(request)}>关闭这条记录</button>
            </div>)}
          </section>}
          {run && intent?.state!=="accepted" && <p role="status">任务已接受：{run.id} · {run.status_message || run.state} <Link to="/generate">查看任务</Link> · <Link to="/gallery">前往画廊</Link></p>}
          {intent?.state === "accepted" && (
            <p role="status">
              任务已接受：{intent.run_id}
              <Link to="/generate">查看任务</Link> ·{" "}
              <Link to="/gallery">前往画廊</Link>
            </p>
          )}
</div>
          </div>
          <div className="moss-dock-controls">
            <div className="moss-environment">          <ExecutionEnvironmentControl
            allowAutomatic={Boolean(workspace)}
            policy={policy}
            environments={[...new Map((snapshot?targets:compatible).map(t=>[t.remote_profile_id,t])).values()].map((t) => ({
              id: t.remote_profile_id,
              display_name: t.remote_display_name,
            }))}
            onChange={(p) => {
              setDraft(d=>({...d,environment:p.mode==="pinned"?p.environmentId:"",executionPolicy:p}));
            }}
            intent={intent}
            disabled={generationBusy}
            onRetry={() =>
              intent && void receive(() => retryGenerationIntent(intent.id))
            }
            onCancel={() =>
              intent && void receive(() => cancelGenerationIntent(intent.id))
            }
            onConfirmAssets={(id) => {
              if (intent)
                void receive(async () => {
                  await confirmEnvironmentAssets(
                    id,
                    (draft.pending?.protocol === "intent-v1" ? draft.pending.body.creationConfiguration.workflow : null) ||
                      configuration.workflow,
                    intent.id,
                  );
                  return retryGenerationIntent(intent.id);
                });
            }}
            onRebuilt={draft.pending?.protocol === "intent-v1" ? (id) => {
              void markEnvironmentRebuilt(id)
                .then(() => {setError("环境已标记重建，请重新核验当前资源映射。");})
                .catch(() => setError("无法标记环境重建。"));
            } : undefined}
          />
</div>
            <span className="moss-condition-summary">{values.values.width} × {values.values.height} · {values.values.batch_size} 张 · {values.values.steps} 步 · CFG {values.values.cfg}</span>
            <div className="moss-dock-actions">
              <span role="status" id="moss-generation-reason">{generationReason}</span>
              {parametersPending&&<button type="button" onClick={()=>{setToolsSection("parameters");setToolsOpen(true);}}>确认生成参数</button>}
              {(!values.valid||!dimensionsValid)&&<button type="button" onClick={()=>{setToolsSection("parameters");setToolsOpen(true);}}>查看无效参数</button>}
              <button type="button" className="moss-assist" disabled={busy||draft.mode==="raw"||!draft.source.trim()} onClick={()=>void assist()}>{busy?"正在获取建议…":"获取建议"}</button>
                        {draft.pending?.protocol === "intent-v1" ? (
            <button
              disabled={generationBusy}
              onClick={() =>
                draft.pending?.protocol === "intent-v1" && void receive(() => recoverGenerationIntent(draft.pending as PendingGenerationIntent))
              }
            >
              继续原请求
            </button>
          ) : (
            <button
              className="moss-generate" aria-describedby="moss-generation-reason"
              disabled={
                generationBusy ||
                parametersPending ||
                !remoteEnabled ||
                !available ||
                !readyWorkflow ||
                loraPrep.blocked ||
                !output.trim() ||
                !values.valid ||
                !dimensionsValid
              }
              onClick={generate}
            >
              生成图像
            </button>
          )}

            </div>
          </div>
        </footer>
      </div>
    </div>
  );
}
