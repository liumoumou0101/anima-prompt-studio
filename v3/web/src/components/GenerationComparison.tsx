import type {GalleryAsset, GenerationRunRecord} from "../lib/types";
import {useEffect, useState} from "react";
import {ApiClientError, apiRequest} from "../lib/api";
import {loadGallery} from "../lib/galleryStore";
import {validSeed} from "../lib/generationSettings";
import {clearComparisonBaseline, readComparisonBaseline, saveComparisonBaseline} from "../lib/comparisonBaseline";
import "./generationComparison.css";

export interface GenerationComparisonProps {
  workspaceId?: string;
  currentRun: GenerationRunRecord;
  runs: GenerationRunRecord[];
  disabled?: boolean;
  onReuseSettings?: (run: GenerationRunRecord, asset: GalleryAsset | undefined) => void;
}
interface Artifact {id: string; path: string | null; removed: boolean; content_url: string | null; thumbnail_url: string | null}
interface Picture {artifact: Artifact; asset?: GalleryAsset}
interface Sample extends Picture {run: GenerationRunRecord}
type PictureState = {runId: string; pictures: Picture[]; loading: boolean; error: string; warning: string};
const emptyState: PictureState = {runId: "", pictures: [], loading: false, error: "", warning: ""};

async function readPictures(runId: string, signal: AbortSignal): Promise<{pictures: Picture[]; warning: string}> {
  const [images, metadata] = await Promise.allSettled([
    apiRequest<{items: Artifact[]}>(`/api/v3/generation-runs/${encodeURIComponent(runId)}/artifacts`, {signal}),
    loadGallery(),
  ]);
  if (images.status === "rejected") throw images.reason;
  const assets = metadata.status === "fulfilled" ? metadata.value.items : [];
  return {warning: metadata.status === "rejected" ? "图片参数记录暂时无法读取，缺失值显示为未知。" : "",
    pictures: images.value.items.filter(item => !item.removed && (item.content_url || item.thumbnail_url)).map(artifact => ({artifact,
      asset: assets.find(item => item.path === artifact.path && item.batch_id === runId)}))};
}

function usePictures(run: GenerationRunRecord | undefined, enabled: boolean) {
  const [state, setState] = useState<PictureState>(emptyState), [attempt, setAttempt] = useState(0);
  const runId = run?.id || "", count = run?.artifact_count || 0;
  useEffect(() => {
    if (!enabled || !runId) return;
    const controller = new AbortController();
    setState({runId, pictures: [], loading: true, error: "", warning: ""});
    void readPictures(runId, controller.signal).then(result => {
      if (controller.signal.aborted) return;
      setState({runId, loading: false, error: "", ...result});
    }).catch(error => {
      if (!controller.signal.aborted) setState({runId, pictures: [], loading: false, error: (error as Error).message, warning: ""});
    });
    return () => controller.abort();
  }, [runId, count, enabled, attempt]);
  return {...(state.runId === runId ? state : emptyState), retry: () => setAttempt(value => value + 1)};
}

type Value = {key: string | null; text: string; source?: string};
const unknown: Value = {key: null, text: "未知"};
function scalar(value: unknown): Value {
  if (typeof value === "number" && Number.isFinite(value)) return {key: String(value), text: String(value)};
  if (typeof value === "string" && value.trim()) return {key: value.trim(), text: value.trim()};
  return unknown;
}
function seed(value: unknown, submitted = false): Value {
  if ((typeof value !== "number" && typeof value !== "string") || !validSeed(value)) return unknown;
  if (BigInt(value) === -1n) return {key: submitted ? "-1" : null, text: submitted ? "随机（-1）" : "随机（实际值未知）"};
  const exact = BigInt(value).toString(); return {key: exact, text: exact};
}
function dimensions(width: unknown, height: unknown): Value {
  const valid = (value: unknown) => (typeof value === "number" || typeof value === "string") && Number.isInteger(Number(value)) && Number(value) > 0;
  if (!valid(width) || !valid(height)) return unknown;
  const text = `${Number(width)} × ${Number(height)}`; return {key: text, text};
}
function recorded(sample: Sample, field: "steps" | "cfg" | "sampler" | "scheduler"): Value {
  const normalized = (value: unknown): Value => {
    if (field !== "steps" && field !== "cfg") return scalar(value);
    if ((typeof value !== "number" && typeof value !== "string") || String(value).trim() === "") return unknown;
    const number = Number(value);
    if (!Number.isFinite(number) || number < 0 || field === "steps" && (!Number.isInteger(number) || number === 0)) return unknown;
    return scalar(number);
  };
  const submission = normalized(sample.run.source?.settings[field]);
  if (submission.key !== null) return {...submission, source: "提交记录"};
  const image = normalized(sample.asset?.generation_params?.[field]);
  return image.key !== null ? {...image, source: "图片批次记录"} : unknown;
}
function values(sample: Sample): Record<string, Value> {
  return {
    "模型": scalar(sample.run.source?.model_profile || sample.asset?.model_profile),
    "服务器": scalar(sample.run.remote_profile_id), "工作流": scalar(sample.run.workflow_profile_id),
    "图片批次记录种子": seed(sample.asset?.generation_params?.seed),
    "提交种子": seed(sample.run.source?.settings.seed, true),
    "输出图像尺寸": dimensions(sample.asset?.width, sample.asset?.height),
    "提交生成尺寸": dimensions(sample.run.source?.settings.width, sample.run.source?.settings.height),
    "步数": recorded(sample, "steps"), "CFG": recorded(sample, "cfg"),
    "采样器": recorded(sample, "sampler"), "调度器": recorded(sample, "scheduler"),
  };
}
function pictureName(picture: Picture): string {
  return picture.asset?.name || picture.artifact.path?.split(/[\\/]/).at(-1) || picture.artifact.id;
}
function batchName(run: GenerationRunRecord): string {
  const date = new Date(run.created_at);
  return `${Number.isNaN(date.getTime()) ? run.id : date.toLocaleString()} · ${run.id.slice(-8)} · ${run.artifact_count} 张`;
}
function PictureView({sample, baseline = false}: {sample: Sample; baseline?: boolean}) {
  const [failed, setFailed] = useState(false);
  const src = sample.artifact.content_url || sample.artifact.thumbnail_url!;
  useEffect(() => setFailed(false), [src]);
  return <figure><figcaption><strong>{baseline ? "固定基准" : "当前图片"}</strong><span>{pictureName(sample)}</span>
    <small>{batchName(sample.run)}{sample.run.source?.workspace_revision != null && ` · 版本 ${sample.run.source.workspace_revision}`}</small></figcaption>
    {failed ? <><p role="status">这张图片当前无法显示，请重新加载或查看原图。</p>
      <button type="button" onClick={() => setFailed(false)}>重新加载{baseline ? "基准" : "当前"}图片</button></>
      : <img src={src} alt={`${baseline ? "固定基准" : "当前图片"}：${pictureName(sample)}`} onError={() => setFailed(true)} />}
    <a href={src} target="_blank" rel="noreferrer">打开{baseline ? "基准" : "当前"}图片</a></figure>;
}

export function GenerationComparison(props: GenerationComparisonProps) {
  return <WorkspaceGenerationComparison key={props.workspaceId || ""} {...props} />;
}

function WorkspaceGenerationComparison({workspaceId, currentRun, runs, disabled = false, onReuseSettings}: GenerationComparisonProps) {
  const [open, setOpen] = useState(false), [baselineId, setBaselineId] = useState("");
  const [baselineImageId, setBaselineImageId] = useState(""), [currentIds, setCurrentIds] = useState<Record<string, string>>({});
  const [pinned, setPinned] = useState<Sample | null>(null);
  const [initial] = useState(() => readComparisonBaseline(workspaceId));
  const [saved, setSaved] = useState(initial.value), [storageWarning, setStorageWarning] = useState(initial.warning);
  const [restoreAttempt, setRestoreAttempt] = useState(0);
  const [restoration, setRestoration] = useState({loading: false, error: "", warning: ""});
  useEffect(() => {
    if (!saved) return;
    const controller = new AbortController();
    setRestoration({loading: true, error: "", warning: ""});
    void (async () => {
      const run = await apiRequest<GenerationRunRecord>(`/api/v3/generation-runs/${encodeURIComponent(saved.runId)}`, {signal: controller.signal});
      const result = await readPictures(saved.runId, controller.signal);
      if (controller.signal.aborted) return;
      const picture = result.pictures.find(item => item.artifact.id === saved.artifactId);
      if (!picture) {
        setRestoration({loading: false, error: "保存的对比基准已不可用，图片可能已删除。请重新选择或清除基准。", warning: result.warning});
        return;
      }
      setPinned({...picture, run}); setBaselineId(run.id); setBaselineImageId(picture.artifact.id);
      setRestoration({loading: false, error: "", warning: result.warning});
    })().catch(error => {
      if (controller.signal.aborted) return;
      const missing = error instanceof ApiClientError && error.code === "generation_run_not_found";
      setRestoration({loading: false, error: missing ? "保存的对比基准已不可用，生成批次可能已删除。请重新选择或清除基准。"
        : "无法恢复保存的对比基准。可以重试或重新选择图片。", warning: ""});
    });
    return () => controller.abort();
  }, [saved, restoreAttempt]);
  const choices = [...new Map([currentRun, ...runs, ...(pinned ? [pinned.run] : [])].map(run => [run.id, run])).values()];
  const baselineRun = choices.find(run => run.id === baselineId);
  const current = usePictures(currentRun, open), baseline = usePictures(baselineRun, open);
  const currentPicture = currentIds[currentRun.id] ? current.pictures.find(item => item.artifact.id === currentIds[currentRun.id]) : current.pictures[0];
  const baselinePicture = baselineImageId ? baseline.pictures.find(item => item.artifact.id === baselineImageId) : baseline.pictures[0];
  const currentSample = currentPicture ? {...currentPicture, run: currentRun} : null;
  const before = pinned ? values(pinned) : null, after = currentSample ? values(currentSample) : null;
  return <details className="generation-comparison" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>固定图片对比</summary>
    <p>选择一张图作为基准，再查看另一张图及其生成记录。{workspaceId ? "基准会按会话保存在当前浏览器，刷新或重开本会话后可恢复。" : "固定基准会保留到离开本会话。"}</p>
    {storageWarning && <p role="status">{storageWarning}</p>}
    {restoration.loading && <p role="status">正在恢复保存的对比基准…</p>}
    {restoration.error && <p role="alert">{restoration.error}</p>}
    {restoration.warning && <p role="status">{restoration.warning}</p>}
    {saved && restoration.error && <button disabled={disabled || restoration.loading} onClick={() => setRestoreAttempt(value => value + 1)}>重新恢复对比基准</button>}
    <div className="generation-comparison-controls">
      <label>选择基准批次<select aria-label="选择基准批次" disabled={disabled} value={baselineId} onChange={event => {setBaselineId(event.target.value); setBaselineImageId("");}}>
        <option value="">请选择</option>{choices.map(run => <option key={run.id} value={run.id}>{batchName(run)}</option>)}</select></label>
      <label>选择基准图片<select aria-label="选择基准图片" disabled={disabled || baseline.loading || !baseline.pictures.length}
        value={baselinePicture?.artifact.id || ""} onChange={event => setBaselineImageId(event.target.value)}>
        {!baseline.pictures.length && <option value="">{baseline.loading ? "读取图片中…" : "暂无可选图片"}</option>}
        {baseline.pictures.map(item => <option key={item.artifact.id} value={item.artifact.id}>{pictureName(item)}</option>)}</select></label>
      <button disabled={disabled || baseline.loading || !baselinePicture || !baselineRun} onClick={() => {
        if (baselinePicture && baselineRun) {
          setSaved(null); setRestoration({loading: false, error: "", warning: ""});
          setPinned(structuredClone({...baselinePicture, run: baselineRun}));
          setStorageWarning(saveComparisonBaseline(workspaceId, baselineRun.id, baselinePicture.artifact.id));
        }
      }}>固定为对比基准</button>
      {(pinned || saved) && <button disabled={disabled} onClick={() => {
        setSaved(null); setPinned(null); setRestoration({loading: false, error: "", warning: ""});
        setStorageWarning(clearComparisonBaseline(workspaceId));
      }}>清除对比基准</button>}
    </div>
    {baseline.error && <p role="alert">{baseline.error}</p>}{baseline.warning && <p role="status">{baseline.warning}</p>}
    {baselineRun && <button disabled={disabled || baseline.loading} onClick={baseline.retry}>重新读取基准图片</button>}
    <label>选择当前图片<select aria-label="选择当前图片" disabled={disabled || current.loading || !current.pictures.length}
      value={currentPicture?.artifact.id || ""} onChange={event => setCurrentIds(previous => ({...previous, [currentRun.id]: event.target.value}))}>
      {!currentPicture && <option value="">{current.loading ? "读取图片中…" : "所选图片不可用，请重新选择"}</option>}
      {current.pictures.map(item => <option key={item.artifact.id} value={item.artifact.id}>{pictureName(item)}</option>)}</select></label>
    {current.error && <p role="alert">{current.error}</p>}{current.warning && <p role="status">{current.warning}</p>}
    {current.error && <button disabled={disabled || current.loading} onClick={current.retry}>重新读取当前图片</button>}
    {pinned && <div className="generation-comparison-pictures"><PictureView sample={pinned} baseline />
      {currentSample ? <PictureView sample={currentSample} /> : <p role="status">{current.loading ? "正在读取当前图片…" : "当前没有可用图片"}</p>}</div>}
    {pinned && currentSample && <>
      <p className="conversation-muted">种子来自保存的批次或提交记录，不能据此确认逐图实际种子；随机生成或多图批次尤其不能作为精确同种子实验。相同记录也不保证工作流文件和运行环境完全一致。</p>
      <div className="generation-comparison-table"><table aria-label="生成参数对比"><thead><tr><th scope="col">参数</th><th scope="col">固定基准</th><th scope="col">当前图片</th><th scope="col">记录差异</th></tr></thead>
        <tbody>{Object.keys(before!).map(label => {const left = before![label], right = after![label];
          const status = left.key === null || right.key === null ? "未知" : left.key === right.key ? "记录一致" : "不同";
          return <tr key={label} data-difference={status}><th scope="row">{label}</th><td>{left.text}{left.source && <small>{left.source}</small>}</td>
            <td>{right.text}{right.source && <small>{right.source}</small>}</td><td>{status}</td></tr>;
        })}</tbody></table></div>
      {onReuseSettings && <button disabled={disabled} onClick={() => onReuseSettings(pinned.run, pinned.asset)}>沿用基准图片的记录参数</button>}
    </>}
    {pinned && !currentSample && !current.loading && <p>基准已固定；当前批次没有可对比的图片，请选择有图片的批次。</p>}
  </details>;
}
