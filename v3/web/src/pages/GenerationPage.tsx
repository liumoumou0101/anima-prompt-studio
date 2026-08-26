import {useCallback, useEffect, useState} from "react";
import {ApiClientError, apiRequest} from "../lib/api";
import type {GenerationRunAction, GenerationRunListResponse, GenerationRunRecord} from "../lib/types";
import {EmptyState, ErrorState, LoadingState} from "../components/States";

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
  const [runs, setRuns] = useState<GenerationRunRecord[] | null>(null);
  const [error, setError] = useState<ApiClientError | null>(null);
  const [busyRun, setBusyRun] = useState<string | null>(null);

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
      setBusyRun(null);
    }
  }

  if (!remoteEnabled) {
    return <section className="page generation-page"><PageHeader count="—" /><EmptyState title="远程生成尚未启用" detail="启动本地服务时指定 V2 数据库，即可直接复用已有云主机、工作流和 Windows 凭据配置。" /></section>;
  }

  return (
    <section className="page generation-page">
      <PageHeader count={runs?.length ?? "—"} />
      <div className="generation-toolbar">
        <div><span className="status-dot is-ready" /><span>V2 远程执行服务已接入</span></div>
        <button type="button" onClick={() => void refresh()} disabled={busyRun !== null}>刷新状态</button>
      </div>
      {error && <ErrorState message={error.message} requestId={error.requestId} />}
      {!runs ? <LoadingState label="正在读取本地与云端任务状态…" /> : runs.length ? (
        <div className="generation-list" aria-live="polite">
          {runs.map((run) => <RunCard key={run.id} run={run} busy={busyRun === run.id} onAction={perform} />)}
        </div>
      ) : <EmptyState title="还没有生成任务" detail="从工作台选择一个通过校验的候选后，即可加入远程生成队列。" />}
    </section>
  );
}

function PageHeader({count}: {count: number | string}) {
  return <header className="page-header"><div><span className="eyebrow">GENERATION RUNS</span><h1>远程生成</h1><p>查看本地队列、ComfyUI 执行和结果下载状态。</p></div><div className="header-stat"><strong>{count}</strong><span>recent runs</span></div></header>;
}

function RunCard({run, busy, onAction}: {
  run: GenerationRunRecord;
  busy: boolean;
  onAction: (run: GenerationRunRecord, action: GenerationRunAction) => Promise<void>;
}) {
  const percent = Math.round(run.progress * 100);
  return (
    <article className={`generation-run generation-run--${run.state}`}>
      <header><div><span className={`run-state run-state--${run.state}`}>{stateLabels[run.state] || run.state}</span><code>{run.id}</code></div><time>{new Date(run.updated_at).toLocaleString()}</time></header>
      <div className="run-progress"><span style={{width: `${percent}%`}} /></div>
      <div className="run-summary"><strong>{run.status_message || stateLabels[run.state]}</strong><span>{percent}%</span></div>
      <dl><div><dt>云主机</dt><dd>{run.remote_profile_id}</dd></div><div><dt>工作流</dt><dd>{run.workflow_profile_id}</dd></div><div><dt>图片</dt><dd>{run.artifact_count}</dd></div></dl>
      {run.error && <p className="run-error" role="alert">{run.error.message}</p>}
      {run.available_actions.length > 0 && <footer>{run.available_actions.map((action) => <button type="button" key={action} disabled={busy} onClick={() => void onAction(run, action)}>{busy ? "处理中…" : actionLabels[action]}</button>)}</footer>}
    </article>
  );
}
