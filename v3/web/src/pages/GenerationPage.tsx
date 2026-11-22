import {useCallback, useEffect, useRef, useState} from "react";
import {useOpenWorkspace} from "../lib/workbenchRoute";
import {Navigate} from "react-router-dom";
import {ApiClientError, apiRequest} from "../lib/api";
import type {GenerationRunAction, GenerationRunListResponse, GenerationRunRecord, WorkspaceRecord} from "../lib/types";
import {EmptyState, ErrorState, LoadingState} from "../components/States";
import {clearConversationBranch, initializeConversationTab, recoverConversationBranch, saveConversationBranch} from "../lib/conversationDrafts";

const activeStates = new Set(["draft", "connecting", "preparing", "queued", "running", "downloading"]);
const stateLabels: Record<string, string> = {
  draft: "本地排队",
  connecting: "正在连接",
  preparing: "准备工作流",
  queued: "云端排队",
  running: "正在生成",
  downloading: "下载结果",
  completed: "已完成",
  failed: "失败",
  canceled: "已取消",
  remote_missing: "远端记录缺失",
};
const actionLabels: Record<GenerationRunAction, string> = {
  cancel_queued: "取消排队",
  retry_check: "重新检查远端",
  continue_download: "继续下载",
};

export function GenerationPage({remoteEnabled}: {remoteEnabled: boolean}) {
  const {openWorkspace,destination} = useOpenWorkspace();
  const [runs, setRuns] = useState<GenerationRunRecord[] | null>(null);
  const [error, setError] = useState<ApiClientError | null>(null);
  const [busyRun, setBusyRun] = useState<string | null>(null);
  const [openingRun, setOpeningRun] = useState<string | null>(null);
  const actionLock = useRef(false);

  const refresh = useCallback(async (quiet = false) => {
    if (!remoteEnabled) return;
    if (!quiet) setError(null);
    try {
      const payload = await apiRequest<GenerationRunListResponse>("/api/v3/generation-runs?limit=50");
      setRuns(payload.items);
    } catch (caught) {
      setError(caught as ApiClientError);
    }
  }, [remoteEnabled]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!remoteEnabled || !runs?.some((run) => activeStates.has(run.state))) return;
    const timer = window.setInterval(() => void refresh(true), 2000);
    return () => window.clearInterval(timer);
  }, [remoteEnabled, refresh, runs]);

  async function perform(run: GenerationRunRecord, action: GenerationRunAction) {
    if (actionLock.current) return;
    actionLock.current = true;
    setBusyRun(run.id);
    setError(null);
    try {
      const updated = await apiRequest<GenerationRunRecord>(`/api/v3/generation-runs/${run.id}/actions`, {
        method: "POST",
        body: JSON.stringify({action}),
      });
      setRuns((items) => items?.map((item) => item.id === updated.id ? updated : item) || [updated]);
      await refresh(true);
    } catch (caught) {
      setError(caught as ApiClientError);
    } finally {
      actionLock.current = false;
      setBusyRun(null);
    }
  }

  async function continueRun(run: GenerationRunRecord) {
    if (actionLock.current) return;
    actionLock.current = true; setBusyRun(run.id); setOpeningRun(run.id); setError(null);
    try {
      await initializeConversationTab();
      const origin = `run:${run.id}` as const;
      const request = recoverConversationBranch(run.id, origin) || {key:crypto.randomUUID(), body:JSON.stringify({})};
      // Persist before POST; an uncertain response must reuse this exact request.
      saveConversationBranch(run.id, origin, request);
      const workspace = await apiRequest<WorkspaceRecord>(`/api/v3/generation-runs/${encodeURIComponent(run.id)}/workspace`, {
        method:"POST", body:request.body, headers:{"Idempotency-Key":request.key},
      });
      if (!workspace || !/^workspace_[A-Za-z0-9]+$/.test(workspace.id) || !Number.isInteger(workspace.revision) || workspace.revision < 1 || !workspace.draft) {
        throw new ApiClientError("创作回执不完整，当前请求已保留，请重试打开。", "invalid_workspace_response");
      }
      if (openWorkspace(workspace)) clearConversationBranch(run.id, origin, request);
    } catch (caught) { setError(caught as ApiClientError); }
    finally { actionLock.current = false; setBusyRun(null); setOpeningRun(null); }
  }

  if (destination) return <Navigate to={destination}/>;
  if (!remoteEnabled) {
    return <section className="page generation-page"><PageHeader count="—" /><EmptyState title="远程生成尚未启用" detail="请到设置配置执行环境，完成连接检测后即可从工作台生成图片。" /></section>;
  }

  return (
    <section className="page generation-page">
      <PageHeader count={runs?.length ?? "—"} />
      <div className="generation-toolbar">
        <div><span className="status-dot is-ready" /><span>生成记录与任务恢复</span></div>
        <button type="button" onClick={() => void refresh()} disabled={busyRun !== null}>刷新状态</button>
      </div>
      {error && <ErrorState message={error.message} requestId={error.requestId} />}
      {!runs ? <LoadingState label="正在读取本地与云端任务状态…" /> : runs.length ? (
        <div className="generation-list" aria-live="polite">
          {runs.map((run) => <RunCard key={run.id} run={run} busy={busyRun !== null} opening={openingRun === run.id} onAction={perform} onContinue={continueRun} />)}
        </div>
      ) : <EmptyState title="还没有生成任务" detail="在工作台编辑提示词并生成图片后，可以在这里查看进度和继续创作。" />}
    </section>
  );
}

function PageHeader({count}: {count: number | string}) {
  return <header className="page-header"><div><span className="eyebrow">生成记录</span><h1>生成任务</h1><p>查看生成进度、结果图片，并从满意的记录继续编辑。</p></div><div className="header-stat"><strong>{count}</strong><span>最近任务</span></div></header>;
}

function RunCard({run, busy, opening, onAction, onContinue}: {
  run: GenerationRunRecord;
  busy: boolean;
  opening: boolean;
  onAction: (run: GenerationRunRecord, action: GenerationRunAction) => Promise<void>;
  onContinue: (run: GenerationRunRecord) => Promise<void>;
}) {
  const percent = Math.max(0, Math.min(100, Math.round(run.progress * 100)));
  const prompt = run.source?.positive_prompt?.trim();
  return (
    <article className={`generation-run generation-run--${run.state}`}>
      <header style={{flexWrap:"wrap"}}><div><span className={`run-state run-state--${run.state}`}>{stateLabels[run.state] || run.state}</span>
        <span>{run.source?.workspace_revision ? `来源修订 ${run.source.workspace_revision}` : "来源修订未记录"}</span>
      </div><time dateTime={run.updated_at}>{new Date(run.updated_at).toLocaleString()}</time></header>
      <h2 style={{fontSize:16,lineHeight:1.6,overflowWrap:"anywhere",margin:"12px 0"}}>{prompt ? prompt.length > 180 ? prompt.slice(0,180) + "…" : prompt : "未记录来源提示词"}</h2>
      <div className="run-progress"><span style={{width: `${percent}%`}} /></div>
      <div className="run-summary"><strong>{run.status_message || stateLabels[run.state]}</strong><span>{percent}%</span></div>
      <dl><div><dt>结果图片</dt><dd>{run.artifact_count} 张</dd></div></dl>
      {run.artifact_count > 0 && <RunThumbnail runId={run.id} artifactCount={run.artifact_count} />}
      {run.artist_comparison && <p className="run-comparison">画师对照 {run.artist_comparison.position}/{run.artist_comparison.total} · {run.artist_comparison.rendered_artist} · 固定 Seed {run.artist_comparison.seed}</p>}
      {run.error && <p className="run-error" role="alert">{run.error.message}</p>}
      <details style={{marginTop:14,overflowWrap:"anywhere"}}><summary>技术详情</summary>
        <dl><div><dt>任务 ID</dt><dd>{run.id}</dd></div><div><dt>执行环境 ID</dt><dd>{run.remote_profile_id}</dd></div><div><dt>工作流 ID</dt><dd>{run.workflow_profile_id}</dd></div></dl>
        <dl><div><dt>提示词任务 ID</dt><dd>{run.prompt_job_id}</dd></div>{run.source?.model_profile && <div><dt>模型配置</dt><dd>{run.source.model_profile}</dd></div>}</dl>
        {prompt && <p><strong>完整正向提示词：</strong>{prompt}</p>}
        {run.source?.negative_prompt && <p><strong>反向提示词：</strong>{run.source.negative_prompt}</p>}
      </details>
      <footer style={{flexWrap:"wrap"}}><button type="button" disabled={busy} onClick={()=>void onContinue(run)}>{opening ? "正在打开…" : "从这次生成继续"}</button>
        {run.available_actions.map((action) => <button type="button" key={action} disabled={busy} onClick={() => void onAction(run, action)}>{actionLabels[action]}</button>)}
      </footer>
    </article>
  );
}

function RunThumbnail({runId, artifactCount}: {runId:string; artifactCount:number}) {
  const [image,setImage] = useState<{thumbnail_url:string;content_url:string|null}|null>(null);
  useEffect(()=>{
    const controller = new AbortController();
    void apiRequest<{items:{thumbnail_url:string|null;content_url:string|null;removed:boolean}[]}>(`/api/v3/generation-runs/${encodeURIComponent(runId)}/artifacts`,{signal:controller.signal})
      .then(result=>{
        if(controller.signal.aborted)return;
        const candidate=result.items.find(item=>!item.removed && item.thumbnail_url);
        setImage(candidate?.thumbnail_url ? {thumbnail_url:candidate.thumbnail_url,content_url:candidate.content_url} : null);
      })
      .catch(()=>{/* Task progress and continuation remain available if its preview is missing. */});
    return ()=>controller.abort();
  },[runId,artifactCount]);
  if(!image)return null;
  const thumbnail=<img src={image.thumbnail_url} alt="这次生成的结果预览" loading="lazy" width={144} height={144} style={{objectFit:"contain",marginTop:12,maxWidth:"100%"}} />;
  return image.content_url ? <a href={image.content_url} target="_blank" rel="noreferrer" aria-label="打开这次生成的结果图片">{thumbnail}</a> : thumbnail;
}
