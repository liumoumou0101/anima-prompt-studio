import {useEffect, useState} from "react";
import {apiRequest} from "./api";
import type {ConversationRecord} from "./conversation";
import {validSeed} from "./generationSettings";
import type {GenerationRunRecord} from "./types";

export type WorkbenchHistoryVersion = Pick<ConversationRecord, "revision" | "title" | "draft" | "created_at">;
export interface WorkbenchArtifact {id: string; path: string | null; removed: boolean; thumbnail_url: string | null; content_url: string | null}
export function versionIntent(version?: WorkbenchHistoryVersion): string {
  if (!version) return "生成图片";
  const events = version.draft.conversation_events || [];
  const event = [...events].reverse().find(item => !item.after_revision || item.after_revision <= version.revision);
  return event?.delta?.trim() || (version.draft.compiled?.source === "user" ? "手动调整提示词" : version.draft.positive_text?.trim()) || version.title || "整理提示词";
}
export function runVersion(run: GenerationRunRecord, versions: WorkbenchHistoryVersion[]): WorkbenchHistoryVersion | undefined {
  return versions.find(item => item.revision === run.source?.workspace_revision);
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
  useEffect(() => {setLimit(50);}, [record.id]);
  useEffect(() => {
    const controller = new AbortController();
    setState(previous => ({...previous, id: record.id, revision: record.revision,
      items: previous.id === record.id ? previous.items : [], loading: true, error: ""}));
    void (async () => {
      const items: WorkbenchHistoryVersion[] = [];
      let more = false;
      for (let offset = 0; offset < limit; offset += 50) {
        const result = await apiRequest<{items: WorkbenchHistoryVersion[]}>(`/api/v3/workspaces/${encodeURIComponent(record.id)}/versions?limit=50&offset=${offset}`, {signal: controller.signal});
        items.push(...result.items); more = result.items.length === 50;
        if (!more) break;
      }
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
