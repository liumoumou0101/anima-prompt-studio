import {useEffect, useState} from "react";
import type {ConversationRecord, LocalConversation} from "../lib/conversation";
import type {GenerationRunRecord} from "../lib/types";
import {canRestoreRun, canUseRunPrompt, runSeedNote, runVersion, useWorkbenchArtifacts, useWorkbenchVersions, versionIntent, type WorkbenchHistoryVersion} from "../lib/workbenchHistory";
import {ImagePreview} from "./ImagePreview";
import {RunInputDetails} from "./WorkbenchHistory";
import "./workbenchResults.css";

export interface WorkbenchImageResultsProps {
  record: ConversationRecord; local: LocalConversation; runs: GenerationRunRecord[]; run: GenerationRunRecord | null;
  disabled?: boolean; onSelectRun(run: GenerationRunRecord): void;
  onContinueRun?(run: GenerationRunRecord): void;
  onRestoreRun(run: GenerationRunRecord, onlyPrompt: boolean, version?: WorkbenchHistoryVersion): void;
}

function batchLabel(run: GenerationRunRecord, versions: WorkbenchHistoryVersion[]) {
  return `${versionIntent(runVersion(run, versions))} · ${new Date(run.created_at).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})} · ${run.artifact_count} 张`;
}

export function WorkbenchImageResults({record, local, runs, run, onSelectRun, onRestoreRun, onContinueRun, disabled}: WorkbenchImageResultsProps) {
  const selectedRun = run || runs[0] || null;
  const versions = useWorkbenchVersions(record);
  const choices = selectedRun && !runs.some(item => item.id === selectedRun.id) ? [selectedRun, ...runs] : runs;
  const [selectedImages, setSelectedImages] = useState<Record<string, string>>({});
  const [compare, setCompare] = useState(false), [baselineId, setBaselineId] = useState("");
  const [baselineImages, setBaselineImages] = useState<Record<string, string>>({});
  const [showInput, setShowInput] = useState(false), [preview, setPreview] = useState(false);
  const pictures = useWorkbenchArtifacts(selectedRun);
  const baselineRun = compare ? choices.find(item => item.id === baselineId) || choices.find(item => item.id !== selectedRun?.id) || selectedRun : null;
  const baseline = useWorkbenchArtifacts(baselineRun);
  useEffect(() => {setCompare(false); setBaselineId(""); setSelectedImages({}); setBaselineImages({}); setPreview(false);}, [record.id]);
  useEffect(() => {setPreview(false);}, [selectedRun?.id]);
  const selectedId = selectedRun ? selectedImages[selectedRun.id] : "";
  const image = pictures.items.find(item => item.id === selectedId) || pictures.items[0];
  const selectedIndex = image ? pictures.items.indexOf(image) : -1;
  const baselineImage = baseline.items.find(item => item.id === (baselineRun ? baselineImages[baselineRun.id] : "")) || baseline.items[0];
  const baselineIndex = baselineImage ? baseline.items.indexOf(baselineImage) : -1;
  const matchingPrompt = selectedRun?.source && local.positive === selectedRun.source.positive_prompt && local.negative === selectedRun.source.negative_prompt;
  if (!selectedRun) return <section className="workbench-image-results workbench-image-empty" aria-label="图片预览"><div><h2>图片会出现在这里</h2>
    <p>写下画面或修改意见，更新提示词后即可生成。</p></div></section>;
  const version = runVersion(selectedRun, versions.items);
  return <section className="workbench-image-results" aria-label="图片预览">
    <header className="workbench-result-heading"><div><h2>图片预览</h2><p>{versionIntent(version)}</p></div>
      <button type="button" aria-pressed={compare} onClick={() => setCompare(value => !value)} disabled={!pictures.items.length}>{compare ? "结束对比" : "对比图片"}</button></header>
    {choices.length > 1 && <label className="workbench-batch-select">查看生成批次<select aria-label="查看生成批次" value={selectedRun.id} onChange={event => {
      const next = choices.find(item => item.id === event.target.value); if (next) onSelectRun(next);
    }}>{choices.map(item => <option key={item.id} value={item.id}>{batchLabel(item, versions.items)}</option>)}</select></label>}
    {compare && <div className="workbench-compare-controls"><label>对比批次<select aria-label="对比批次" value={baselineRun?.id || ""} onChange={event => setBaselineId(event.target.value)}>
      {choices.map(item => <option key={item.id} value={item.id}>{batchLabel(item, versions.items)}</option>)}</select></label>
      <label>对比图片<select aria-label="对比图片" value={baselineImage?.id || ""} disabled={!baseline.items.length} onChange={event => {
        if (baselineRun) setBaselineImages(previous => ({...previous, [baselineRun.id]: event.target.value}));
      }}>{baseline.items.map((item, index) => <option key={item.id} value={item.id}>第 {index + 1} 张</option>)}</select></label></div>}
    <div className={`workbench-image-stage${compare ? " is-comparing" : ""}`}>
      {compare && <figure className="workbench-image-frame">{baselineImage ? <img src={baselineImage.content_url || baselineImage.thumbnail_url!} alt={`对比图片：第 ${baselineIndex + 1} 张`} />
        : <p>{baseline.loading ? "正在读取对比图片…" : "此批次暂无可用图片"}</p>}<figcaption>对比 · {baselineRun ? batchLabel(baselineRun, versions.items) : ""}</figcaption>
        {baseline.error && <p role="alert">{baseline.error} <button onClick={baseline.retry}>重新读取对比图片</button></p>}</figure>}
      <figure className="workbench-image-frame">{image ? <button className="workbench-image-open" aria-label="放大查看当前图片" onClick={() => setPreview(true)}>
        <img src={image.content_url || image.thumbnail_url!} alt={`当前图片：第 ${selectedIndex + 1} 张`} /></button>
        : <div className="workbench-image-placeholder"><p>{pictures.loading ? "正在读取图片…" : selectedRun.state === "completed" ? "此批次没有可用图片" : selectedRun.status_message}</p>
          {!["completed", "failed", "canceled", "remote_missing"].includes(selectedRun.state) && <progress max={1} value={selectedRun.progress} aria-label="生图进度" />}</div>}
        <figcaption>当前查看 · 第 {selectedIndex + 1 || "—"} 张 / {pictures.items.length} 张</figcaption></figure>
    </div>
    {pictures.error && <p role="alert">{pictures.error} <button onClick={pictures.retry}>重新读取图片</button></p>}
    {pictures.items.length > 1 && <div className="workbench-image-filmstrip" aria-label="本批次图片">{pictures.items.map((item, index) => <button key={item.id} aria-pressed={image?.id === item.id}
      aria-label={`查看第 ${index + 1} 张图片`} onClick={() => setSelectedImages(previous => ({...previous, [selectedRun.id]: item.id}))}>
      <img src={item.thumbnail_url || item.content_url!} alt={`缩略图 ${index + 1}`} loading="lazy" /><span>{index + 1}</span></button>)}</div>}
    <div className="workbench-result-footer"><p className="workbench-results-note">{selectedRun.source ? matchingPrompt ? "当前提示词与这批图片一致" : "当前提示词已与这批图片不同" : "这批图片未保留提示词记录"}</p>
      <div className="workbench-result-actions"><button disabled={disabled || !canRestoreRun(selectedRun)} onClick={() => onRestoreRun(selectedRun, false, version)}>从这张继续</button>
        <button disabled={disabled || !canUseRunPrompt(selectedRun)} onClick={() => onRestoreRun(selectedRun, true, version)}>只用提示词</button>
        <button aria-expanded={showInput} onClick={() => setShowInput(value => !value)}>{showInput ? "收起实际输入" : "查看实际输入"}</button></div>
      {!canRestoreRun(selectedRun) && <p className="workbench-results-note">生成设置记录不完整，无法完整恢复。</p>}
      <p className="workbench-results-note">{runSeedNote(selectedRun)}</p></div>
    {onContinueRun && <details><summary>更多图片操作</summary><button disabled={disabled} onClick={() => onContinueRun(selectedRun)}>沿用本次条件，新建会话</button></details>}
    {showInput && <section className="workbench-actual-input" aria-label="实际提交输入"><RunInputDetails run={selectedRun} />
      {compare && baselineRun && <details><summary>对比图片的实际输入</summary><RunInputDetails run={baselineRun} /></details>}</section>}
    {preview && <ImagePreview index={selectedIndex} onClose={() => setPreview(false)} images={pictures.items.map((item, index) => ({
      src: item.content_url || item.thumbnail_url!, alt: `${versionIntent(version)} · 第 ${index + 1} 张`, positive: selectedRun.source?.positive_prompt,
      negative: selectedRun.source?.negative_prompt, parameters: {模型: selectedRun.source?.model_profile, 工作流: selectedRun.workflow_profile_id, ...selectedRun.source?.settings}}))} />}
  </section>;
}
