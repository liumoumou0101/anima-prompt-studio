import {useEffect, useState} from "react";
import {apiRequest} from "./api";
import type {ConversationRecord,LocalConversation} from "./conversation";
import {validSeed} from "./generationSettings";
import type {GenerationRunRecord} from "./types";
import {readConversationDraft} from "./conversationDrafts";

export type WorkbenchHistoryVersion = Pick<ConversationRecord, "revision" | "title" | "draft" | "created_at"> & {checkpointId?:string;versionNumber?:number;operationKind?:string;pendingSync?:boolean};
export interface WorkbenchCheckpoint {id:string;operation_id?:string;version_number:number;base_revision:number;kind:string;label:string;created_at:string;snapshot:LocalConversation}
export function checkpointVersion(checkpoint:WorkbenchCheckpoint,record:ConversationRecord):WorkbenchHistoryVersion {
 const snapshot=checkpoint.snapshot;
 return {checkpointId:checkpoint.id,versionNumber:checkpoint.version_number,operationKind:checkpoint.kind,revision:checkpoint.base_revision,title:checkpoint.label,created_at:checkpoint.created_at,draft:{...record.draft,model_profile:snapshot.model,generation_settings:snapshot.settings,mode:snapshot.mode,requirements:{...snapshot.requirements,contract:"anima-requirements/1",revision:1},compiled:{positive:snapshot.positive,negative:snapshot.negative,source:"user",compiled_token:""},conversation_events:[]}};
}
export interface WorkbenchArtifact {id: string; path: string | null; removed: boolean; thumbnail_url: string | null; content_url: string | null}
const EDITOR_HISTORY_CHANGED="anima-editor-history-changed";
export function notifyEditorHistoryChanged(workspaceId:string):void{window.dispatchEvent(new CustomEvent(EDITOR_HISTORY_CHANGED,{detail:{workspaceId}}));}
export function versionIntent(version?: WorkbenchHistoryVersion): string {
  if (!version) return "生成图片";
  if(version.checkpointId)return version.title;
  const events = version.draft.conversation_events || [];
  const event = [...events].reverse().find(item => !item.after_revision || item.after_revision <= version.revision);
  return event?.delta?.trim() || (version.draft.compiled?.source === "user" ? "手动调整提示词" : version.draft.positive_text?.trim()) || version.title || "整理提示词";
}
export function runVersion(run: GenerationRunRecord, versions: WorkbenchHistoryVersion[]): WorkbenchHistoryVersion | undefined {
  return versions.find(item => !item.checkpointId&&item.revision === run.source?.workspace_revision);
}
export function canUseRunPrompt(run: GenerationRunRecord): boolean {return Boolean(run.source?.positive_prompt?.trim());}
export function canRestoreRun(run: GenerationRunRecord): boolean {
  const source = run.source, settings = source?.settings;
  return Boolean(canUseRunPrompt(run) && source?.model_profile && run.remote_profile_id && run.workflow_profile_id && settings
    && [settings.width, settings.height, settings.steps, settings.batch_size].every(value => typeof value === "number" && Number.isInteger(value) && value > 0)
    && typeof settings.cfg === "number" && Number.isFinite(settings.cfg) && settings.cfg >= 0
    && settings.sampler && settings.scheduler && settings.seed !== undefined && validSeed(settings.seed));
}

/** A workspace-scoped list; late responses never replace another workspace's history. */
export function useWorkbenchVersions(record: ConversationRecord) {
  const [state, setState] = useState<{id: string; revision: number; items: WorkbenchHistoryVersion[]; loading: boolean; error: string; more: boolean}>({id: "", revision: 0, items: [], loading: false, error: "", more: false});
  const [limit, setLimit] = useState(50), [attempt, setAttempt] = useState(0);
  useEffect(()=>{
    const changed=(event:Event)=>{if((event as CustomEvent<{workspaceId:string}>).detail?.workspaceId===record.id)setAttempt(value=>value+1);};
    window.addEventListener(EDITOR_HISTORY_CHANGED,changed);return()=>window.removeEventListener(EDITOR_HISTORY_CHANGED,changed);
  },[record.id]);
  useEffect(() => {setLimit(50);}, [record.id]);
  useEffect(() => {
    const controller = new AbortController();
    const localOperations=readConversationDraft(record.id)?.editorJournal?.outbox||[];
    const localVersions=()=>localOperations.map(operation=>({...checkpointVersion({id:`local:${operation.id}`,version_number:0,base_revision:operation.baseRevision,kind:operation.kind,label:operation.label,created_at:new Date(operation.createdAt).toISOString(),snapshot:operation.snapshot},record),pendingSync:true}));
    setState(previous => ({...previous, id: record.id, revision: record.revision,
      items: previous.id === record.id ? previous.items : localVersions(), loading: true, error: ""}));
    void (async () => {
      const items: WorkbenchHistoryVersion[] = [];
      let more = false;
      for (let offset = 0; offset < limit; offset += 50) {
        const result = await apiRequest<{items: WorkbenchHistoryVersion[]}>(`/api/v3/workspaces/${encodeURIComponent(record.id)}/versions?limit=50&offset=${offset}`, {signal: controller.signal});
        items.push(...result.items); more = result.items.length === 50;
        if (!more) break;
      }
      // Revision snapshots remain available for old runs; user numbers belong only to immutable checkpoints.
      const checkpoints:WorkbenchCheckpoint[]=[];let checkpointsMore=false;
      for(let offset=0;offset<limit;offset+=50){
        const page=await apiRequest<{items:WorkbenchCheckpoint[]}>(`/api/v3/workspaces/${encodeURIComponent(record.id)}/checkpoints?limit=50&offset=${offset}`,{signal:controller.signal});
        checkpoints.push(...(page.items||[]));checkpointsMore=(page.items||[]).length===50;if(!checkpointsMore)break;
      }
      more ||= checkpointsMore;
      items.unshift(...checkpoints.filter(item=>item.snapshot?.requirements&&typeof item.snapshot.positive==="string").map(item=>checkpointVersion(item,record)));
      items.unshift(...localVersions().filter(item=>!checkpoints.some(checkpoint=>`local:${checkpoint.operation_id}`===item.checkpointId)));
      if (!controller.signal.aborted) setState({id: record.id, revision: record.revision, items, loading: false, error: "", more});
    })().catch(error => {if (!controller.signal.aborted) setState(previous => ({...previous, loading: false, error: (error as Error).message}));});
    return () => controller.abort();
  }, [record.id, record.revision, limit, attempt]);
  return {...(state.id === record.id ? state : {...state, items: [], error: "", loading: true}),
    loadMore: () => setLimit(value => value + 50), retry: () => setAttempt(value => value + 1)};
}

export function useWorkbenchArtifacts(run: GenerationRunRecord | null | undefined) {
  const [state, setState] = useState<{id: string; items: WorkbenchArtifact[]; loading: boolean; error: string}>({id: "", items: [], loading: false, error: ""});
  const [attempt, setAttempt] = useState(0);
  const id = run?.id || "", count = run?.artifact_count || 0;
  useEffect(() => {
    if (!id || !count) {setState({id, items: [], loading: false, error: ""}); return;}
    const controller = new AbortController();
    setState(previous => ({id, items: previous.id === id ? previous.items : [], loading: true, error: ""}));
    void apiRequest<{items: WorkbenchArtifact[]}>(`/api/v3/generation-runs/${encodeURIComponent(id)}/artifacts`, {signal: controller.signal})
      .then(result => {if (!controller.signal.aborted) setState({id, items: result.items.filter(item => !item.removed && (item.content_url || item.thumbnail_url)), loading: false, error: ""});})
      .catch(error => {if (!controller.signal.aborted) setState({id, items: [], loading: false, error: (error as Error).message});});
    return () => controller.abort();
  }, [id, count, attempt]);
  return {...(state.id === id ? state : {id, items: [], loading: Boolean(count), error: ""}), retry: () => setAttempt(value => value + 1)};
}

export function runSeedNote(run: GenerationRunRecord): string {
  return (run.source?.settings.batch_size || 1) > 1
    ? "多图批次会恢复提交时的种子，不保证对应所选单张图片。"
    : String(run.source?.settings.seed) === "-1" ? "当时使用随机种子；恢复后仍会随机生成。" : "种子来自当时的提交记录。";
}
