import {useEffect, useMemo, useState} from "react";
import {apiRequest, ApiClientError} from "../lib/api";
import type {GalleryAsset, GalleryProcessJob, GalleryResponse, GalleryTrashAsset, GalleryTrashResponse} from "../lib/types";
import {EmptyState, ErrorState, LoadingState} from "../components/States";

export function GalleryPage({enabled = false}: {enabled?: boolean}) {
  const [data, setData] = useState<GalleryResponse | null>(null);
  const [error, setError] = useState<ApiClientError | null>(null);
  const [project, setProject] = useState("");
  const [model, setModel] = useState("");
  const [query, setQuery] = useState("");
  const [active, setActive] = useState<GalleryAsset | null>(null);
  const [view, setView] = useState<"library" | "trash">("library");
  const [trash, setTrash] = useState<GalleryTrashResponse | null>(null);
  const [activeTrash, setActiveTrash] = useState<GalleryTrashAsset | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [processJobs, setProcessJobs] = useState<GalleryProcessJob[]>([]);
  const [jobsOpen, setJobsOpen] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    apiRequest<GalleryResponse>("/api/v3/gallery/assets?limit=1000")
      .then(setData)
      .catch((caught) => setError(caught as ApiClientError));
  }, [enabled]);

  const items = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return (data?.items || []).filter((asset) => (
      (!project || asset.project === project)
      && (!model || asset.model_profile === model)
      && (!needle || `${asset.name} ${asset.project} ${asset.positive_prompt}`.toLocaleLowerCase().includes(needle))
    ));
  }, [data, model, project, query]);

  async function openTrash() {
    setView("trash");
    setNotice("");
    try {
      setTrash(await apiRequest<GalleryTrashResponse>("/api/v3/gallery/trash?limit=1000"));
    } catch (caught) {
      setError(caught as ApiClientError);
    }
  }

  async function setAssetState(asset: GalleryAsset, state: "" | "kept" | "rejected") {
    setBusy(true);
    try {
      await apiRequest("/api/v3/gallery/assets/state", {method: "POST", body: JSON.stringify({paths: [asset.path], state})});
      setData((current) => current ? {...current, items: current.items.map((item) => item.path === asset.path ? {...item, state} : item)} : current);
      setActive((current) => current?.path === asset.path ? {...current, state} : current);
      setNotice(state === "kept" ? "已标记为保留" : state === "rejected" ? "已标记为淘汰" : "已清除状态");
    } catch (caught) { setError(caught as ApiClientError); } finally { setBusy(false); }
  }

  async function moveAssetToTrash(asset: GalleryAsset) {
    if (!window.confirm("将这张图片移入可恢复的画廊回收站？")) return;
    setBusy(true);
    try {
      const result = await apiRequest<{moved: string[]; failed: Array<{error: string}>}>("/api/v3/gallery/assets/trash", {method: "POST", body: JSON.stringify({paths: [asset.path]})});
      if (!result.moved.length) throw new ApiClientError(result.failed[0]?.error || "图片未能移入回收站", "gallery_trash_failed");
      setData((current) => current ? {...current, items: current.items.filter((item) => item.path !== asset.path), trash_count: current.trash_count + 1} : current);
      setActive(null);
      setNotice("图片已移入画廊回收站，可随时恢复。");
    } catch (caught) { setError(caught as ApiClientError); } finally { setBusy(false); }
  }

  async function restoreTrashAsset(asset: GalleryTrashAsset) {
    setBusy(true);
    try {
      const result = await apiRequest<{restored: string[]}>("/api/v3/gallery/trash/restore", {method: "POST", body: JSON.stringify({paths: [asset.path]})});
      if (!result.restored.length) throw new ApiClientError("图片未能恢复", "gallery_restore_failed");
      setTrash((current) => current ? {...current, items: current.items.filter((item) => item.path !== asset.path), trash_count: current.trash_count - 1} : current);
      setActiveTrash(null);
      setNotice("图片已恢复到原画廊目录。");
      setData(await apiRequest<GalleryResponse>("/api/v3/gallery/assets?limit=1000"));
    } catch (caught) { setError(caught as ApiClientError); } finally { setBusy(false); }
  }

  async function submitProcess(asset: GalleryAsset, operation: "regenerate" | "upscale") {
    setBusy(true);
    try {
      const result = await apiRequest<{jobs: GalleryProcessJob[]; failed: Array<{error: string}>}>("/api/v3/gallery/process", {
        method: "POST",
        body: JSON.stringify({paths: [asset.path], operation, count: 1}),
      });
      if (!result.jobs.length) throw new ApiClientError(result.failed[0]?.error || "任务未能加入队列", "gallery_process_rejected");
      setProcessJobs((current) => [...result.jobs, ...current.filter((item) => !result.jobs.some((added) => added.id === item.id))]);
      setActive(null);
      setJobsOpen(true);
      setNotice(operation === "regenerate" ? "已加入再生成队列。" : "已加入 1.5× 放大队列。");
    } catch (caught) { setError(caught as ApiClientError); } finally { setBusy(false); }
  }

  async function loadProcessJobs() {
    try {
      const result = await apiRequest<{jobs: GalleryProcessJob[]}>("/api/v3/gallery/process");
      setProcessJobs(result.jobs);
      setJobsOpen(true);
    } catch (caught) { setError(caught as ApiClientError); }
  }

  async function processAction(job: GalleryProcessJob, action: "cancel" | "retry") {
    setBusy(true);
    try {
      const result = await apiRequest<{job: GalleryProcessJob}>("/api/v3/gallery/process/action", {method: "POST", body: JSON.stringify({job_id: job.id, action})});
      setProcessJobs((current) => current.map((item) => item.id === job.id ? result.job : item));
    } catch (caught) { setError(caught as ApiClientError); } finally { setBusy(false); }
  }

  return (
    <section className="page gallery-page">
      <header className="page-header gallery-header">
        <div><span className="eyebrow">LOCAL ARCHIVE</span><h1>生成画廊</h1><p>读取 V2 已归档图片，并保留 V3 候选、模型和数据版本线索。</p></div>
        <div className="header-stat"><strong>{data?.items.length ?? "—"}</strong><span>local assets</span></div>
      </header>

      {!enabled ? <EmptyState title="画廊尚未连接" detail="使用 V2 数据库启动 V3 后，本地图片目录会显示在这里。" /> : error ? (
        <ErrorState message={error.message} requestId={error.requestId} />
      ) : !data ? <LoadingState label="正在扫描本地生成记录和 manifest…" /> : <>
        <div className="gallery-view-tabs">
          <button type="button" className={view === "library" ? "is-active" : ""} onClick={() => setView("library")}>全部图片</button>
          <button type="button" className={view === "trash" ? "is-active" : ""} onClick={() => void openTrash()}>回收站 <span>{trash?.trash_count ?? data.trash_count}</span></button>
          <button type="button" className={jobsOpen ? "is-active" : ""} onClick={() => jobsOpen ? setJobsOpen(false) : void loadProcessJobs()}>处理任务</button>
        </div>
        {notice && <div className="workspace-notice workspace-notice--success" role="status">{notice}</div>}
        {jobsOpen && <section className="gallery-jobs" aria-label="画廊处理任务">
          <header><strong>画廊处理队列</strong><span>{processJobs.length} 项</span></header>
          {processJobs.length ? processJobs.map((job) => <article key={job.id}>
            <div><strong>{job.operation === "gallery_txt2img_more" ? "再生成" : "1.5× 放大"}</strong><span>{job.sourceName}</span></div>
            <div className="gallery-job-progress"><span style={{width: `${Math.round(job.progress * 100)}%`}} /></div>
            <small>{job.message || job.state}</small>
            {job.state === "queued" && <button type="button" disabled={busy} onClick={() => void processAction(job, "cancel")}>取消</button>}
            {(job.state === "failed" || job.state === "canceled") && <button type="button" disabled={busy} onClick={() => void processAction(job, "retry")}>重试</button>}
          </article>) : <p>当前没有画廊处理任务。</p>}
        </section>}
        {view === "library" ? <>
        <div className="gallery-toolbar">
          <input aria-label="搜索画廊" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索文件名、项目或提示词" />
          <select aria-label="筛选项目" value={project} onChange={(event) => setProject(event.target.value)}><option value="">全部项目</option>{data.projects.map((item) => <option key={item}>{item}</option>)}</select>
          <select aria-label="筛选模型" value={model} onChange={(event) => setModel(event.target.value)}><option value="">全部模型</option>{data.models.map((item) => <option key={item}>{item}</option>)}</select>
          <span>{items.length} 张</span>
        </div>
        {items.length ? <div className="gallery-grid">
          {items.map((asset) => <button type="button" className="gallery-card" key={asset.id} onClick={() => setActive(asset)}>
            <div className="gallery-image-wrap"><img src={asset.thumbnail_url} alt={asset.name} loading="lazy" /></div>
            <div className="gallery-card-copy">
              <strong>{asset.project}</strong><span>{asset.name}</span>
              <small>{asset.artist_comparison ? `画师 ${asset.artist_comparison.rendered_artist} · Seed ${asset.artist_comparison.seed}` : `${asset.model_profile || "未知模型"}${asset.candidate.lane ? ` · ${asset.candidate.lane.toUpperCase()}` : ""}`}</small>
            </div>
          </button>)}
        </div> : <EmptyState title="没有匹配的图片" detail="清除搜索或筛选条件后再试一次。" />}
        </> : !trash ? <LoadingState label="正在读取画廊回收站…" /> : trash.items.length ? <div className="gallery-grid gallery-trash-grid">
          {trash.items.map((asset) => <button type="button" className="gallery-card" key={asset.id} onClick={() => setActiveTrash(asset)}>
            <div className="gallery-image-wrap"><img src={asset.thumbnail_url} alt={asset.name} loading="lazy" /></div>
            <div className="gallery-card-copy"><strong>{asset.name}</strong><span>{asset.original_path}</span><small>可恢复</small></div>
          </button>)}
        </div> : <EmptyState title="画廊回收站是空的" detail="移入回收站的图片会出现在这里。" />}
      </>}

      {active && <div className="gallery-lightbox" role="dialog" aria-modal="true" aria-label="图片详情" onClick={() => setActive(null)}>
        <article onClick={(event) => event.stopPropagation()}>
          <button type="button" className="gallery-lightbox-close" aria-label="关闭图片详情" onClick={() => setActive(null)}>×</button>
          <div className="gallery-lightbox-image"><img src={active.content_url} alt={active.name} /></div>
          <aside>
            <span className="eyebrow">{active.candidate.lane || active.source}</span>
            <h2>{active.project}</h2><p className="gallery-file-name">{active.name}</p>
            <dl>
              <div><dt>模型</dt><dd>{active.model_profile || "未知"}</dd></div>
              <div><dt>尺寸</dt><dd>{active.width && active.height ? `${active.width} × ${active.height}` : "未记录"}</dd></div>
              <div><dt>批次</dt><dd>{active.batch_title}</dd></div>
              {active.artist_comparison && <><div><dt>画师对照</dt><dd>{active.artist_comparison.rendered_artist}（{active.artist_comparison.position}/{active.artist_comparison.total}）</dd></div><div><dt>固定 Seed</dt><dd>{active.artist_comparison.seed}</dd></div></>}
              <div><dt>生成时间</dt><dd>{new Date(active.created_at).toLocaleString()}</dd></div>
              {active.candidate.versions.data_pack && <div><dt>数据包</dt><dd>{active.candidate.versions.data_pack}</dd></div>}
            </dl>
            <h3>Positive Prompt</h3><p className="gallery-prompt">{active.positive_prompt || "此图片没有保存提示词。"}</p>
            {active.negative_prompt && <><h3>Negative Prompt</h3><p className="gallery-prompt is-negative">{active.negative_prompt}</p></>}
            <div className="gallery-actions">
              <button type="button" disabled={busy || !data?.processing?.regenAvailable} title={data?.processing?.regenReason || "使用原提示词再生成"} onClick={() => void submitProcess(active, "regenerate")}>再生成</button>
              <button type="button" disabled={busy || !data?.processing?.available} title={data?.processing?.reason || "使用分块工作流放大"} onClick={() => void submitProcess(active, "upscale")}>1.5× 放大</button>
              <button type="button" disabled={busy} className={active.state === "kept" ? "is-active" : ""} onClick={() => void setAssetState(active, active.state === "kept" ? "" : "kept")}>保留</button>
              <button type="button" disabled={busy} className={active.state === "rejected" ? "is-active" : ""} onClick={() => void setAssetState(active, active.state === "rejected" ? "" : "rejected")}>淘汰</button>
              <button type="button" disabled={busy} className="is-danger" onClick={() => void moveAssetToTrash(active)}>移入回收站</button>
            </div>
          </aside>
        </article>
      </div>}
      {activeTrash && <div className="gallery-lightbox" role="dialog" aria-modal="true" aria-label="回收站图片详情" onClick={() => setActiveTrash(null)}>
        <article onClick={(event) => event.stopPropagation()}>
          <button type="button" className="gallery-lightbox-close" aria-label="关闭回收站图片详情" onClick={() => setActiveTrash(null)}>×</button>
          <div className="gallery-lightbox-image"><img src={activeTrash.content_url} alt={activeTrash.name} /></div>
          <aside><span className="eyebrow">RECOVERABLE</span><h2>{activeTrash.name}</h2><p className="gallery-file-name">原位置：{activeTrash.original_path}</p><div className="gallery-actions"><button type="button" disabled={busy} className="is-active" onClick={() => void restoreTrashAsset(activeTrash)}>{busy ? "正在恢复…" : "恢复到画廊"}</button></div></aside>
        </article>
      </div>}
    </section>
  );
}
