import type {ReactNode} from "react";
import type {ConversationRecord} from "../lib/conversation";
import type {GenerationRunRecord} from "../lib/types";
import {canRestoreRun, canUseRunPrompt, runSeedNote, runVersion, useWorkbenchArtifacts, useWorkbenchVersions, versionIntent, type WorkbenchHistoryVersion} from "../lib/workbenchHistory";
import "./workbenchResults.css";

export interface WorkbenchHistoryProps {
  record: ConversationRecord; runs: GenerationRunRecord[]; disabled?: boolean; draftRecovery?: ReactNode;
  onRestoreVersion(version: WorkbenchHistoryVersion): void;
  onForkVersion?(revision: number): void;
  onRestoreRun(run: GenerationRunRecord, onlyPrompt: boolean, version?: WorkbenchHistoryVersion): void;
}

export function RunInputDetails({run}: {run: GenerationRunRecord}) {
  const source = run.source, settings = source?.settings;
  return <div className="workbench-run-input"><dl>
    <div><dt>模型</dt><dd>{source?.model_profile || "未记录"}</dd></div>
    <div><dt>工作流</dt><dd>{run.workflow_profile_id || "未记录"}</dd></div>
    <div><dt>尺寸</dt><dd>{settings?.width && settings?.height ? `${settings.width} × ${settings.height}` : "工作流默认 / 未记录"}</dd></div>
    <div><dt>提交种子</dt><dd>{settings?.seed === undefined ? "未记录" : String(settings.seed) === "-1" ? "随机（-1）" : String(settings.seed)}</dd></div>
    <div><dt>步数 / CFG</dt><dd>{settings?.steps ?? "未记录"} / {settings?.cfg ?? "未记录"}</dd></div>
    <div><dt>采样器 / 调度器</dt><dd>{settings?.sampler || "未记录"} / {settings?.scheduler || "未记录"}</dd></div>
  </dl><p className="workbench-results-note">{runSeedNote(run)}</p>
    <h4>实际提交的正向提示词</h4><p className="workbench-prompt-text">{source?.positive_prompt || "未记录"}</p>
    <h4>实际提交的负向提示词</h4><p className="workbench-prompt-text">{source ? source.negative_prompt || "空" : "未记录"}</p></div>;
}

function HistoryRun({run, version, disabled, onRestoreRun, onForkVersion}: Pick<WorkbenchHistoryProps, "disabled" | "onRestoreRun" | "onForkVersion"> & {run: GenerationRunRecord; version?: WorkbenchHistoryVersion}) {
  const pictures = useWorkbenchArtifacts(run), title = versionIntent(version);
  return <article className="workbench-history-card" aria-label={`生图记录：${title}`}>
    <div className="workbench-history-card-heading">{pictures.items[0] && <img src={pictures.items[0].thumbnail_url || pictures.items[0].content_url!} alt={`${title}的生成图片`} loading="lazy" />}
      <div><span className="workbench-history-kind">生成图片 · {run.artifact_count} 张</span><h3>{title}</h3><time>{new Date(run.created_at).toLocaleString()}</time><p>{run.status_message}</p></div></div>
    {pictures.error && <p role="alert">图片暂时无法读取 <button onClick={pictures.retry}>重试</button></p>}
    <div className="workbench-result-actions"><button disabled={disabled || !canRestoreRun(run)} onClick={() => onRestoreRun(run, false, version)}>从这张继续</button>
      <button disabled={disabled || !canUseRunPrompt(run)} onClick={() => onRestoreRun(run, true, version)}>只用提示词</button></div>
    {!canRestoreRun(run) && <p className="workbench-results-note">生成设置记录不完整，无法完整恢复。</p>}
    <details><summary>查看实际输入</summary><RunInputDetails run={run} /></details>
    {version && onForkVersion && <details><summary>更多操作</summary><button disabled={disabled} onClick={() => onForkVersion(version.revision)}>从版本 {version.revision} 另开会话</button></details>}
  </article>;
}

export function WorkbenchHistory({record, runs, disabled, onRestoreRun, onRestoreVersion, onForkVersion, draftRecovery}: WorkbenchHistoryProps) {
  const versions = useWorkbenchVersions(record);
  const entries = [...runs.map(run => ({kind: "run" as const, run, date: run.created_at})),
    ...versions.items.filter(version => !runs.some(run => run.source?.workspace_revision === version.revision))
      .map(version => ({kind: "version" as const, version, date: version.created_at}))]
    .sort((left, right) => new Date(right.date).getTime() - new Date(left.date).getTime());
  return <section className="workbench-history" aria-label="创作记录内容">
    <p className="workbench-results-note">按当时的修改意见和图片找回创作。恢复前的编辑会保留，恢复后还可撤销。</p>
    {versions.error && <p role="alert">{versions.error} <button onClick={versions.retry}>重新读取记录</button></p>}
    {versions.loading && <p role="status">正在读取创作记录…</p>}
    {entries.map(entry => entry.kind === "run" ? <HistoryRun key={entry.run.id} run={entry.run} version={runVersion(entry.run, versions.items)} disabled={disabled} onRestoreRun={onRestoreRun} onForkVersion={onForkVersion} />
      : <article className="workbench-history-card" key={`version-${entry.version.revision}`} aria-label={`提示词记录：${versionIntent(entry.version)}`}>
        <span className="workbench-history-kind">提示词 · 尚未生成图片</span><h3>{versionIntent(entry.version)}</h3><time>{new Date(entry.date).toLocaleString()}</time>
        <div className="workbench-result-actions"><button disabled={disabled} onClick={() => onRestoreVersion(entry.version)}>恢复到这里</button></div>
        <details><summary>查看提示词</summary><p className="workbench-prompt-text">{entry.version.draft.compiled?.positive || "尚无提示词"}</p>
          <p className="workbench-prompt-text">{entry.version.draft.compiled?.negative || "负向提示词为空"}</p></details>
        {onForkVersion && <details><summary>更多操作</summary><button disabled={disabled} onClick={() => onForkVersion(entry.version.revision)}>从版本 {entry.version.revision} 另开会话</button></details>}
      </article>)}
    {versions.more && <button disabled={versions.loading} onClick={versions.loadMore}>加载更早记录</button>}
    {draftRecovery}
  </section>;
}
