import {useCallback, useEffect, useMemo, useRef, useState} from "react";
import {ArrowClockwise, ArrowsOutSimple, Check, ClockCounterClockwise, Copy, FolderOpen, Funnel, Heart, Images, ListChecks, MagicWand, SelectionAll, SlidersHorizontal, SortAscending, SquaresFour, Trash, X} from "@phosphor-icons/react";
import PhotoAlbum from "react-photo-album";
import "react-photo-album/rows.css";
import Lightbox from "yet-another-react-lightbox";
import "yet-another-react-lightbox/styles.css";
import {apiRequest, ApiClientError} from "../lib/api";
import {getGallerySnapshot, loadGallery, patchGallerySnapshot, subscribeGallery} from "../lib/galleryStore";
import type {GalleryAsset, GalleryProcessJob, GalleryResponse, GalleryTrashAsset, GalleryTrashResponse} from "../lib/types";
import {EmptyState, ErrorState, LoadingState} from "../components/States";

type View = "all" | "recent" | "kept" | "external" | "trash";
type Sort = "newest" | "oldest" | "name";
type AlbumPhoto = GalleryAsset & {src: string; alt: string};
const RowsAlbum = PhotoAlbum as unknown as React.ComponentType<Record<string, unknown>>;
const views: Array<{id: View; label: string}> = [{id: "all", label: "图片"}, {id: "recent", label: "最近生成"}, {id: "kept", label: "保留"}, {id: "external", label: "外部图片"}, {id: "trash", label: "画廊回收站"}];

function bytes(value: number) { return !value ? "大小未知" : value < 1048576 ? `${Math.max(1, Math.round(value / 1024))} KB` : `${(value / 1048576).toFixed(1)} MB`; }
function dateKey(value: string) { const d = new Date(value); return Number.isNaN(d.valueOf()) ? "unknown" : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; }
function dateLabel(value: string) { const d = new Date(value); return Number.isNaN(d.valueOf()) ? "时间未知" : new Intl.DateTimeFormat("zh-CN", {year: "numeric", month: "long", day: "numeric", weekday: "short"}).format(d); }
function dateTime(value: string) { const d = new Date(value); return Number.isNaN(d.valueOf()) ? "时间未知" : d.toLocaleString("zh-CN", {hour12: false}); }

export function GalleryPage({enabled = false}: {enabled?: boolean}) {
  const [data, setData] = useState<GalleryResponse | null>(() => getGallerySnapshot());
  const [trash, setTrash] = useState<GalleryTrashResponse | null>(null);
  const [view, setView] = useState<View>("all");
  const [query, setQuery] = useState("");
  const [project, setProject] = useState("");
  const [model, setModel] = useState("");
  const [batch, setBatch] = useState("");
  const [sort, setSort] = useState<Sort>("newest");
  const [filterOpen, setFilterOpen] = useState(true);
  const [thumbSize, setThumbSize] = useState(() => Number(localStorage.getItem("anima-v3-gallery-thumb-size")) || 205);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [active, setActive] = useState<GalleryAsset | null>(null);
  const [activeTrash, setActiveTrash] = useState<GalleryTrashAsset | null>(null);
  const [lightboxIndex, setLightboxIndex] = useState(-1);
  const [compareOpen, setCompareOpen] = useState(false);
  const [jobsOpen, setJobsOpen] = useState(false);
  const [jobs, setJobs] = useState<GalleryProcessJob[]>([]);
  const [processSelection, setProcessSelection] = useState<{items: GalleryAsset[]; operation: "regenerate" | "upscale"} | null>(null);
  const [regenCount, setRegenCount] = useState(1);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [activity, setActivity] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState<ApiClientError | null>(null);
  const [renderLimit, setRenderLimit] = useState(80);
  const loadMoreRef = useRef<HTMLButtonElement>(null);
  const pageRef = useRef<HTMLElement>(null);
  const dockedDetail = useMediaQuery("(min-width: 1180px)");

  const load = useCallback(async (refresh = false) => {
    if (!enabled) return;
    setError(null);
    try { setData(await loadGallery({refresh, reason: refresh ? "manual" : "initial"})); }
    catch (caught) { setError(caught as ApiClientError); }
  }, [enabled]);
  const loadTrash = async () => {
    try { setTrash(await apiRequest<GalleryTrashResponse>("/api/v3/gallery/trash?limit=1000")); }
    catch (caught) { setError(caught as ApiClientError); }
  };
  const loadJobs = async (open = true) => {
    try { const result = await apiRequest<{jobs: GalleryProcessJob[]}>("/api/v3/gallery/process"); setJobs(result.jobs); if (open) setJobsOpen(true); }
    catch (caught) { setError(caught as ApiClientError); }
  };
  useEffect(() => {
    if (!enabled) return;
    const unsubscribe = subscribeGallery((update) => {
      setData(update.data);
      if (update.reason === "generation" && update.added > 0) {
        setNotice(`已自动加入 ${update.added} 张新生成图片。`);
      }
    });
    const cached = getGallerySnapshot();
    if (cached) setData(cached);
    else void load();
    return unsubscribe;
  }, [enabled, load]);
  useEffect(() => { localStorage.setItem("anima-v3-gallery-thumb-size", String(thumbSize)); }, [thumbSize]);
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 4500);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const batches = useMemo(() => [...new Map((data?.items || []).map((item) => [item.batch_id, {id: item.batch_id, title: item.batch_title}])).values()].sort((a, b) => a.title.localeCompare(b.title, "zh-CN")), [data]);
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    const list = (data?.items || []).filter((asset) => {
      if (view === "recent" && asset.source !== "generated") return false;
      if (view === "kept" && asset.state !== "kept") return false;
      if (view === "external" && asset.source !== "external") return false;
      if (project && asset.project !== project) return false;
      if (model && asset.model_profile !== model) return false;
      if (batch && asset.batch_id !== batch) return false;
      return !needle || [asset.name, asset.path, asset.project, asset.model_profile, asset.positive_prompt, asset.batch_title].filter(Boolean).join(" ").toLocaleLowerCase().includes(needle);
    });
    return list.sort((a, b) => sort === "name" ? a.name.localeCompare(b.name, "zh-CN") : (sort === "oldest" ? 1 : -1) * (new Date(a.created_at).valueOf() - new Date(b.created_at).valueOf())).slice(0, view === "recent" ? 300 : 1000);
  }, [batch, data, model, project, query, sort, view]);
  const visible = useMemo(() => filtered.slice(0, renderLimit), [filtered, renderLimit]);
  const groups = useMemo(() => {
    const map = new Map<string, GalleryAsset[]>();
    visible.forEach((asset) => { const key = dateKey(asset.created_at); map.set(key, [...(map.get(key) || []), asset]); });
    return [...map.entries()].map(([key, items]) => ({key, items, label: dateLabel(items[0].created_at)}));
  }, [visible]);
  const visibleTrash = useMemo(() => (trash?.items || []).filter((asset) => !query.trim() || `${asset.name} ${asset.original_path}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())), [query, trash]);
  const selectedAssets = useMemo(() => filtered.filter((asset) => selected.has(asset.path)), [filtered, selected]);
  const selectedTrash = useMemo(() => visibleTrash.filter((asset) => selected.has(asset.path)), [selected, visibleTrash]);

  useEffect(() => { setRenderLimit(80); }, [batch, model, project, query, sort, view]);
  useEffect(() => {
    const target = loadMoreRef.current;
    if (!target || visible.length >= filtered.length || !("IntersectionObserver" in window)) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) setRenderLimit((value) => Math.min(value + 80, filtered.length));
    }, {rootMargin: "500px"});
    observer.observe(target);
    return () => observer.disconnect();
  }, [filtered.length, visible.length]);
  useEffect(() => {
    const page = pageRef.current;
    if (!page || dockedDetail || (!active && !activeTrash)) return;
    const overlayClasses = ["legacy-detail-layer", "legacy-dialog-backdrop", "legacy-compare"];
    const background = [...page.children].filter((child) => !overlayClasses.some((name) => child.classList.contains(name)));
    const shell = page.closest(".app-shell");
    const outsidePage = shell ? [...shell.children].filter((child) => !child.contains(page)) : [];
    background.push(...outsidePage);
    background.forEach((child) => ((child as HTMLElement).inert = true));
    return () => background.forEach((child) => ((child as HTMLElement).inert = false));
  }, [active, activeTrash, dockedDetail]);

  function toggle(path: string) { setSelected((current) => { const next = new Set(current); next.has(path) ? next.delete(path) : next.add(path); return next; }); }
  function selectGroup(items: Array<{path: string}>) { setSelected((current) => new Set([...current, ...items.map((item) => item.path)])); }
  function updateData(update: (current: GalleryResponse) => GalleryResponse) {
    const current = getGallerySnapshot() || data;
    if (!current) return;
    const next = update(current);
    if (getGallerySnapshot()) patchGallerySnapshot(() => next);
    else setData(next);
  }
  async function openView(next: View) {
    setView(next); setSelected(new Set()); setActive(null); setActiveTrash(null);
    if (next === "trash") { setActivity("正在读取回收站…"); await loadTrash(); setActivity(""); }
  }
  async function refreshNow() {
    if (refreshing) return;
    setRefreshing(true); setActivity(view === "trash" ? "正在刷新回收站…" : "正在同步画廊索引…"); setError(null);
    try {
      if (view === "trash") {
        await loadTrash();
        setNotice("回收站已刷新。");
      } else {
        const beforePaths = new Set(data?.items.map((item) => item.path) || []);
        const next = await loadGallery({refresh: true, reason: "manual"});
        setData(next);
        const added = next.items.filter((item) => !beforePaths.has(item.path)).length;
        setNotice(added ? `已发现 ${added} 张新图片。` : "画廊已是最新。");
      }
    } catch (caught) { setError(caught as ApiClientError); }
    finally { setRefreshing(false); setActivity(""); }
  }
  async function copy(text: string, label: string) { try { if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text); setNotice(`${label}已复制`); } catch { setError(new ApiClientError("无法写入系统剪贴板", "clipboard_failed")); } }
  async function changeState(items: GalleryAsset[], state: "" | "kept" | "rejected") {
    if (!items.length) return; setBusy(true); setActivity(state === "kept" ? "正在保留图片…" : state === "rejected" ? "正在标记淘汰…" : "正在清除状态…");
    try {
      const paths = items.map((item) => item.path);
      await apiRequest("/api/v3/gallery/assets/state", {method: "POST", body: JSON.stringify({paths, state})});
      updateData((current) => ({...current, items: current.items.map((item) => paths.includes(item.path) ? {...item, state} : item)}));
      setActive((current) => current && paths.includes(current.path) ? {...current, state} : current);
      setNotice(state === "kept" ? `已保留 ${paths.length} 张图片` : state === "rejected" ? `已标记淘汰 ${paths.length} 张图片` : "已清除状态");
    } catch (caught) { setError(caught as ApiClientError); } finally { setBusy(false); setActivity(""); }
  }
  async function move(items: GalleryAsset[]) {
    if (!items.length || !window.confirm(`确定将选中的 ${items.length} 张图片移入画廊回收站吗？之后仍可恢复。`)) return; setBusy(true); setActivity("正在移入画廊回收站…");
    try {
      const paths = items.map((item) => item.path);
      const result = await apiRequest<{moved: string[]; failed: Array<{error: string}>}>("/api/v3/gallery/assets/trash", {method: "POST", body: JSON.stringify({paths})});
      if (!result.moved.length) throw new ApiClientError(result.failed[0]?.error || "图片未能移入回收站", "gallery_trash_failed");
      updateData((current) => ({...current, items: current.items.filter((item) => !result.moved.includes(item.path)), trash_count: current.trash_count + result.moved.length}));
      setSelected(new Set()); setActive(null); setNotice(`图片已移入画廊回收站，可随时恢复。`);
    } catch (caught) { setError(caught as ApiClientError); } finally { setBusy(false); setActivity(""); }
  }
  async function restore(items: GalleryTrashAsset[]) {
    if (!items.length) return; setBusy(true); setActivity("正在恢复图片…");
    try {
      const paths = items.map((item) => item.path);
      const result = await apiRequest<{restored: string[]}>("/api/v3/gallery/trash/restore", {method: "POST", body: JSON.stringify({paths})});
      setTrash((current) => current ? {...current, items: current.items.filter((item) => !paths.includes(item.path)), trash_count: Math.max(0, current.trash_count - result.restored.length)} : current);
      setSelected(new Set()); setActiveTrash(null); setNotice(`图片已恢复到原画廊目录。`); await load(true);
    } catch (caught) { setError(caught as ApiClientError); } finally { setBusy(false); setActivity(""); }
  }
  async function deleteForever(items: GalleryTrashAsset[]) {
    if (!items.length || !window.confirm(`永久删除选中的 ${items.length} 张图片？此操作无法恢复。`)) return; setBusy(true); setActivity("正在永久删除图片…");
    try {
      const paths = items.map((item) => item.path);
      const result = await apiRequest<{deleted: string[]}>("/api/v3/gallery/trash/delete", {method: "POST", body: JSON.stringify({paths})});
      setTrash((current) => current ? {...current, items: current.items.filter((item) => !result.deleted.includes(item.path)), trash_count: Math.max(0, current.trash_count - result.deleted.length)} : current);
      setSelected(new Set()); setActiveTrash(null); setNotice(`已永久删除 ${result.deleted.length} 张图片`);
    } catch (caught) { setError(caught as ApiClientError); } finally { setBusy(false); setActivity(""); }
  }
  async function deleteAssetsForever(items: GalleryAsset[]) {
    if (!items.length || !window.confirm(`确定彻底删除选中的 ${items.length} 张图片吗？\n\n原始图片文件和缩略图缓存将直接从磁盘删除，不会进入画廊回收站，也无法恢复。`)) return;
    setBusy(true); setActivity("正在从磁盘永久删除图片…"); setError(null);
    try {
      const paths = items.map((item) => item.path);
      const result = await apiRequest<{deleted: string[]; failed: Array<{path: string; error: string}>}>("/api/v3/gallery/assets/delete", {method: "POST", body: JSON.stringify({paths})});
      if (!result.deleted.length) throw new ApiClientError(result.failed[0]?.error || "没有图片被永久删除", "gallery_delete_failed");
      updateData((current) => ({...current, items: current.items.filter((item) => !result.deleted.includes(item.path))}));
      setSelected(new Set()); setActive(null);
      setNotice(result.failed.length
        ? `已从磁盘永久删除 ${result.deleted.length} 张图片，${result.failed.length} 张删除失败。`
        : `已从磁盘永久删除 ${result.deleted.length} 张图片，无法恢复。`);
    } catch (caught) { setError(caught as ApiClientError); } finally { setBusy(false); setActivity(""); }
  }
  async function submit(items: GalleryAsset[], operation: "regenerate" | "upscale") {
    const usable = operation === "regenerate" ? items.filter((item) => item.positive_prompt) : items;
    if (!usable.length) return; setBusy(true); setActivity(operation === "regenerate" ? "正在加入再生成队列…" : "正在加入高清修复队列…");
    try {
      const result = await apiRequest<{jobs: GalleryProcessJob[]; failed: Array<{error: string}>}>("/api/v3/gallery/process", {method: "POST", body: JSON.stringify({paths: usable.map((item) => item.path), operation, count: operation === "regenerate" ? regenCount : 1})});
      if (!result.jobs.length) throw new ApiClientError(result.failed[0]?.error || "任务未能加入队列", "gallery_process_rejected");
      setJobs((current) => [...result.jobs, ...current]); setJobsOpen(true); setSelected(new Set()); setActive(null); setNotice(operation === "regenerate" ? `已加入 ${result.jobs.length} 项再生成任务。` : `已加入 ${result.jobs.length} 项 1.5× 修复任务。`);
    } catch (caught) { setError(caught as ApiClientError); } finally { setBusy(false); setActivity(""); setProcessSelection(null); }
  }
  async function reveal(item: GalleryAsset) { setBusy(true); setActivity("正在打开文件夹…"); try { await apiRequest("/api/v3/gallery/assets/reveal", {method: "POST", body: JSON.stringify({paths: [item.path]})}); setNotice("已在文件夹中定位图片。"); } catch (caught) { setError(caught as ApiClientError); } finally { setBusy(false); setActivity(""); } }

  if (!enabled) return <section className="page gallery-page"><Header count="—" /><EmptyState title="画廊尚未连接" detail="使用 V2 数据库启动 V3 后，本地图片目录会显示在这里。" /></section>;
  return <section ref={pageRef} aria-busy={busy || refreshing} className={`page gallery-page gallery-page--migrated${active || activeTrash ? " has-detail" : ""}`}><Header count={data ? (view === "trash" ? visibleTrash.length : filtered.length) : "—"} />{error && <ErrorState message={error.message} requestId={error.requestId} />}{!data ? <LoadingState label="正在读取画廊索引…" /> : <>
    <nav className="legacy-gallery-tabs" aria-label="画廊视图">{views.map((item) => <button key={item.id} type="button" className={view === item.id ? "is-active" : ""} onClick={() => void openView(item.id)}>{item.label}{item.id === "trash" && <span>{trash?.trash_count ?? data.trash_count}</span>}</button>)}</nav>
    <div className="legacy-gallery-topbar"><input aria-label="搜索画廊" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索项目、提示词、文件名…" />{view !== "trash" && <button type="button" className={filterOpen ? "is-active" : ""} onClick={() => setFilterOpen((value) => !value)}><Funnel size={17} />筛选</button>}<label><SortAscending size={16} />排序<select aria-label="排序" value={sort} onChange={(event) => setSort(event.target.value as Sort)}><option value="newest">最新优先</option><option value="oldest">最早优先</option><option value="name">文件名</option></select></label><label title="缩略图大小"><SquaresFour size={16} /><input aria-label="缩略图大小" type="range" min="150" max="285" value={thumbSize} onChange={(event) => setThumbSize(Number(event.target.value))} /></label><button type="button" disabled={view === "trash" ? !visibleTrash.length : !filtered.length} onClick={() => selectGroup(view === "trash" ? visibleTrash : filtered)}><SelectionAll size={16} />全选当前结果</button><button type="button" disabled={refreshing} onClick={() => void refreshNow()}><ArrowClockwise size={16} className={refreshing ? "is-spinning" : ""} />{refreshing ? "正在刷新…" : "刷新画廊"}</button><button type="button" className={jobsOpen ? "is-active" : ""} onClick={() => jobsOpen ? setJobsOpen(false) : void loadJobs()}><ListChecks size={17} />任务</button></div>
    {filterOpen && view !== "trash" && <section className="legacy-gallery-filters" aria-label="画廊筛选"><label>项目<select aria-label="筛选项目" value={project} onChange={(event) => setProject(event.target.value)}><option value="">全部项目</option>{data.projects.map((item) => <option key={item}>{item}</option>)}</select></label><label>模型<select aria-label="筛选模型" value={model} onChange={(event) => setModel(event.target.value)}><option value="">全部模型</option>{data.models.map((item) => <option key={item}>{item}</option>)}</select></label><label>批次<select aria-label="筛选批次" value={batch} onChange={(event) => setBatch(event.target.value)}><option value="">全部批次</option>{batches.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label><button type="button" onClick={() => { setProject(""); setModel(""); setBatch(""); }}>清除筛选</button></section>}
    {activity && <div className="legacy-gallery-activity" role="status" aria-live="polite"><ArrowClockwise size={15} className="is-spinning" />{activity}</div>}
    {notice && <div className="workspace-notice workspace-notice--success" role="status" aria-live="polite">{notice}</div>}
    {jobsOpen && <section className="legacy-process-panel" aria-label="画廊处理任务"><header><strong>画廊处理队列</strong><button type="button" onClick={() => setJobsOpen(false)} aria-label="关闭任务中心"><X size={17} /></button></header>{jobs.length ? jobs.map((job) => <article key={job.id}><div><strong>{job.operation === "gallery_txt2img_more" ? "再出图" : "1.5× 高清修复"}</strong><span>{job.sourceName}</span></div><progress max="1" value={job.progress} /><small>{job.error || job.message || job.state}</small></article>) : <p>当前没有画廊处理任务。</p>}</section>}
    {view === "trash" ? <TrashGrid items={visibleTrash} selected={selected} onOpen={setActiveTrash} onToggle={toggle} /> : <div className="legacy-gallery-body">{groups.length ? groups.map((group) => <Group key={group.key} group={group} selected={selected} active={active} thumbSize={thumbSize} onOpen={setActive} onPreview={(item) => setLightboxIndex(filtered.findIndex((asset) => asset.path === item.path))} onToggle={toggle} onSelectGroup={selectGroup} />) : <EmptyState title="没有匹配的图片" detail="清除搜索或筛选条件后再试一次。" />}{visible.length < filtered.length && <button ref={loadMoreRef} type="button" className="legacy-load-more" onClick={() => setRenderLimit((value) => Math.min(value + 80, filtered.length))}>继续加载（剩余 {filtered.length - visible.length} 张）</button>}{groups.length > 1 && <aside className="legacy-date-rail" aria-label="日期导航">{groups.map((group) => <a key={group.key} href={`#date-${group.key}`}>{group.key.slice(-2)}</a>)}</aside>}</div>}
    {(view === "trash" ? selectedTrash : selectedAssets).length > 0 && <Selection selectedCount={(view === "trash" ? selectedTrash : selectedAssets).length} isTrash={view === "trash"} busy={busy} canCompare={selectedAssets.length >= 2 && selectedAssets.length <= 4} onClear={() => setSelected(new Set())} onKeep={() => void changeState(selectedAssets, "kept")} onReject={() => void changeState(selectedAssets, "rejected")} onTrash={() => void move(selectedAssets)} onRestore={() => void restore(selectedTrash)} onDelete={() => void deleteForever(selectedTrash)} onDeleteDirect={() => void deleteAssetsForever(selectedAssets)} onRegen={() => { setRegenCount(1); setProcessSelection({items: selectedAssets, operation: "regenerate"}); }} onUpscale={() => setProcessSelection({items: selectedAssets, operation: "upscale"})} onCompare={() => setCompareOpen(true)} />}
    {active && <div className="legacy-detail-layer"><div className="legacy-detail-backdrop" aria-hidden="true" onMouseDown={() => setActive(null)} /><Detail asset={active} busy={busy} docked={dockedDetail} processing={data.processing} onClose={() => setActive(null)} onPreview={() => setLightboxIndex(filtered.findIndex((item) => item.path === active.path))} onCopy={copy} onReveal={reveal} onState={(state) => void changeState([active], state)} onRegen={() => { setRegenCount(1); setProcessSelection({items: [active], operation: "regenerate"}); }} onUpscale={() => setProcessSelection({items: [active], operation: "upscale"})} onTrash={() => void move([active])} onDelete={() => void deleteAssetsForever([active])} /></div>}
    {activeTrash && <div className="legacy-detail-layer"><div className="legacy-detail-backdrop" aria-hidden="true" onMouseDown={() => setActiveTrash(null)} /><TrashDetail asset={activeTrash} busy={busy} docked={dockedDetail} onClose={() => setActiveTrash(null)} onRestore={() => void restore([activeTrash])} onDelete={() => void deleteForever([activeTrash])} /></div>}
    {processSelection && <ProcessDialog selection={processSelection} count={regenCount} busy={busy} onCount={setRegenCount} onCancel={() => setProcessSelection(null)} onSubmit={() => void submit(processSelection.items, processSelection.operation)} />}
    {compareOpen && <Compare assets={selectedAssets} onClose={() => setCompareOpen(false)} />}
    <Lightbox open={lightboxIndex >= 0} close={() => setLightboxIndex(-1)} index={lightboxIndex} slides={filtered.map((item) => ({src: item.content_url, alt: item.name}))} labels={{Close: "关闭", Previous: "上一张", Next: "下一张"}} />
  </>}</section>;
}

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => typeof window.matchMedia === "function" && window.matchMedia(query).matches);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);
  return matches;
}

function useDetailFocus(onClose: () => void, docked: boolean) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const closeHandler = useRef(onClose);
  closeHandler.current = onClose;
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); closeHandler.current(); return; }
      if (docked || event.key !== "Tab") return;
      const panel = closeRef.current?.closest("aside");
      const focusable = [...(panel?.querySelectorAll<HTMLElement>("button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex='-1'])") || [])];
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", handleKey);
    return () => { document.removeEventListener("keydown", handleKey); if (previous?.isConnected) previous.focus(); };
  }, [docked]);
  return closeRef;
}

function Header({count}: {count: string | number}) { return <header className="page-header gallery-header"><div><span className="eyebrow">LOCAL ARCHIVE · V2 GALLERY</span><h1>生成画廊</h1><p>复用 V2 成熟的图片管理交互，并保留 V3 画师与数据追溯。</p></div><div className="header-stat"><strong>{count}</strong><span>{count === "—" ? "local assets" : `${count} 张`}</span></div></header>; }
function Group({group, selected, active, thumbSize, onOpen, onPreview, onToggle, onSelectGroup}: {group: {key: string; label: string; items: GalleryAsset[]}; selected: Set<string>; active: GalleryAsset | null; thumbSize: number; onOpen: (item: GalleryAsset) => void; onPreview: (item: GalleryAsset) => void; onToggle: (path: string) => void; onSelectGroup: (items: GalleryAsset[]) => void}) {
  const photos: AlbumPhoto[] = group.items.map((item) => ({...item, src: item.thumbnail_url, alt: `${item.project} · ${item.name}`}));
  return <section id={`date-${group.key}`} className="legacy-date-group"><header><div><h2>{group.label}</h2><span>{group.items.length} 张图片</span></div><div><span>{new Set(group.items.map((item) => item.batch_id)).size} 个批次</span><button type="button" onClick={() => onSelectGroup(group.items)}><SelectionAll size={16} />选择本组</button></div></header><RowsAlbum layout="rows" photos={photos} defaultContainerWidth={1440} targetRowHeight={thumbSize} spacing={8} rowConstraints={(width: number) => ({maxPhotos: Math.min(12, Math.max(5, Math.round(width / thumbSize))), singleRowMaxHeight: Math.round(thumbSize * 1.25)})} render={{photo: (_props: unknown, context: {photo: AlbumPhoto; width: number; height: number}) => <Photo asset={context.photo} width={context.width} height={context.height} selected={selected.has(context.photo.path)} active={active?.path === context.photo.path} onOpen={onOpen} onPreview={onPreview} onToggle={onToggle} />}} /></section>;
}
function Photo({asset, width, height, selected, active, onOpen, onPreview, onToggle}: {asset: AlbumPhoto; width: number; height: number; selected: boolean; active: boolean; onOpen: (item: GalleryAsset) => void; onPreview: (item: GalleryAsset) => void; onToggle: (path: string) => void}) { const comparisonPosition = artistComparisonPosition(asset); return <article className={`legacy-photo-card${selected ? " is-selected" : ""}${active ? " is-active" : ""}`} style={{width, height}}><button type="button" className="legacy-photo-open" onClick={() => onOpen(asset)} onDoubleClick={() => onPreview(asset)} aria-label={`查看 ${asset.name}`}><img src={asset.thumbnail_url} alt={asset.name} loading="lazy" /></button><button type="button" className="legacy-selection-toggle" onClick={() => onToggle(asset.path)} aria-pressed={selected} aria-label={`${selected ? "取消选择" : "选择"} ${asset.name}`}>{selected && <Check size={16} weight="bold" />}</button>{asset.state === "kept" && <span className="legacy-state-badge kept"><Heart size={12} weight="fill" />保留</span>}{asset.state === "rejected" && <span className="legacy-state-badge rejected"><X size={12} />淘汰</span>}{asset.source === "external" && <span className="legacy-source-badge"><FolderOpen size={12} />外部图片</span>}{asset.artist_comparison && <span className="legacy-artist-badge">{asset.artist_comparison.rendered_artist}{comparisonPosition ? ` · ${comparisonPosition}` : ""}</span>}<span className="legacy-photo-name">{asset.name}</span></article>; }
function TrashGrid({items, selected, onOpen, onToggle}: {items: GalleryTrashAsset[]; selected: Set<string>; onOpen: (item: GalleryTrashAsset) => void; onToggle: (path: string) => void}) { return !items.length ? <EmptyState title="画廊回收站是空的" detail="移入回收站的图片会出现在这里。" /> : <div className="legacy-trash-grid">{items.map((item) => <article key={item.path} className={`legacy-photo-card${selected.has(item.path) ? " is-selected" : ""}`}><button type="button" className="legacy-photo-open" onClick={() => onOpen(item)} aria-label={`查看 ${item.name}`}><img src={item.thumbnail_url} alt={item.name} /></button><button type="button" className="legacy-selection-toggle" onClick={() => onToggle(item.path)} aria-pressed={selected.has(item.path)} aria-label={`${selected.has(item.path) ? "取消选择" : "选择"} ${item.name}`}>{selected.has(item.path) && <Check size={16} />}</button><span className="legacy-photo-name">{item.name}</span></article>)}</div>; }
function Detail({asset, busy, docked, processing, onClose, onPreview, onCopy, onReveal, onState, onRegen, onUpscale, onTrash, onDelete}: {asset: GalleryAsset; busy: boolean; docked: boolean; processing?: GalleryResponse["processing"]; onClose: () => void; onPreview: () => void; onCopy: (text: string, label: string) => Promise<void>; onReveal: (item: GalleryAsset) => Promise<void>; onState: (state: "" | "kept" | "rejected") => void; onRegen: () => void; onUpscale: () => void; onTrash: () => void; onDelete: () => void}) {
  const params = Object.entries(asset.generation_params || {});
  const comparisonPosition = artistComparisonPosition(asset);
  const closeRef = useDetailFocus(onClose, docked);
  return <aside className="legacy-detail-drawer" role={docked ? "region" : "dialog"} aria-modal={docked ? undefined : "true"} aria-label="图片详情"><header><strong>图片详情</strong><button ref={closeRef} type="button" onClick={onClose} aria-label="关闭图片详情"><X size={20} /></button></header><div className="legacy-detail-body"><button type="button" className="legacy-detail-preview" onClick={onPreview} aria-label="查看原图"><img src={asset.thumbnail_url} alt={asset.name} /><ArrowsOutSimple size={18} /></button><h2>{asset.name}</h2><dl><div><dt>项目</dt><dd>{asset.project}</dd></div><div><dt>模型</dt><dd>{asset.model_profile || "未知"}</dd></div><div><dt>尺寸</dt><dd>{asset.width && asset.height ? `${asset.width} × ${asset.height}` : "未记录"}</dd></div><div><dt>来源</dt><dd>{asset.source === "external" ? "外部图片" : "ANIMA 生成"}</dd></div><div><dt>批次</dt><dd>{asset.batch_title}</dd></div><div><dt>时间</dt><dd>{dateTime(asset.created_at)}</dd></div><div><dt>文件大小</dt><dd>{bytes(asset.byte_size)}</dd></div>{params.map(([key, value]) => <div key={key}><dt>{key.replace("batch_size", "batch")}</dt><dd>{String(value)}</dd></div>)}{asset.artist_comparison && <><div><dt>{asset.artist_comparison.derived_from === "gallery_regenerate" ? "画师 Tag" : "画师对照"}</dt><dd>{asset.artist_comparison.rendered_artist}{comparisonPosition ? `（${comparisonPosition}）` : ""}</dd></div>{typeof asset.artist_comparison.seed === "number" && <div><dt>固定 Seed</dt><dd>{asset.artist_comparison.seed}</dd></div>}</>}{asset.candidate.versions.data_pack && <div><dt>数据包</dt><dd>{asset.candidate.versions.data_pack}</dd></div>}</dl><Prompt title="正向提示词" value={asset.positive_prompt} onCopy={() => void onCopy(asset.positive_prompt, "正向提示词")} />{asset.negative_prompt && <Prompt title="反向提示词" value={asset.negative_prompt} onCopy={() => void onCopy(asset.negative_prompt, "反向提示词")} negative />}</div><footer className="legacy-detail-actions"><button type="button" aria-label="再生成" disabled={busy || !processing?.regenAvailable || !asset.positive_prompt} onClick={onRegen}><Images size={16} />用同样提示词再出图</button><button type="button" disabled={busy || !processing?.available} onClick={onUpscale}><MagicWand size={16} />1.5× 高清修复</button><div><button type="button" disabled={busy} onClick={() => onState(asset.state === "kept" ? "" : "kept")}><Heart size={15} />保留</button><button type="button" disabled={busy} onClick={() => onState(asset.state === "rejected" ? "" : "rejected")}><X size={15} />淘汰</button></div><button type="button" disabled={busy} onClick={() => void onReveal(asset)}><FolderOpen size={16} />在文件夹中显示</button><button type="button" disabled={busy} className="is-danger" aria-label="移入回收站" onClick={onTrash}><Trash size={16} />移入画廊回收站</button><button type="button" disabled={busy} className="is-danger" aria-label="永久删除原图" onClick={onDelete}><Trash size={16} />永久删除原图</button></footer></aside>;
}

function artistComparisonPosition(asset: GalleryAsset): string {
  const comparison = asset.artist_comparison;
  return comparison && typeof comparison.position === "number" && typeof comparison.total === "number"
    ? `${comparison.position}/${comparison.total}`
    : "";
}
function Prompt({title, value, negative = false, onCopy}: {title: string; value: string; negative?: boolean; onCopy: () => void}) { return <section className={`legacy-prompt${negative ? " is-negative" : ""}`}><header><h3>{title}</h3><button type="button" onClick={onCopy}><Copy size={14} />复制</button></header><p>{value || "此图片没有保存提示词。"}</p></section>; }
function TrashDetail({asset, busy, docked, onClose, onRestore, onDelete}: {asset: GalleryTrashAsset; busy: boolean; docked: boolean; onClose: () => void; onRestore: () => void; onDelete: () => void}) { const closeRef = useDetailFocus(onClose, docked); return <aside className="legacy-detail-drawer" role={docked ? "region" : "dialog"} aria-modal={docked ? undefined : "true"} aria-label="回收站图片详情"><header><strong>回收站图片详情</strong><button ref={closeRef} type="button" onClick={onClose} aria-label="关闭图片详情"><X size={20} /></button></header><div className="legacy-detail-body"><img className="legacy-trash-image" src={asset.content_url} alt={asset.name} /><h2>{asset.name}</h2><dl><div><dt>原位置</dt><dd>{asset.original_path}</dd></div><div><dt>文件大小</dt><dd>{bytes(asset.byte_size)}</dd></div></dl></div><footer className="legacy-detail-actions"><button type="button" disabled={busy} onClick={onRestore}><ClockCounterClockwise size={16} />恢复到画廊</button><button type="button" disabled={busy} className="is-danger" onClick={onDelete}><Trash size={16} />永久删除</button></footer></aside>; }
function Selection({selectedCount, isTrash, busy, canCompare, onClear, onKeep, onReject, onTrash, onRestore, onDelete, onDeleteDirect, onRegen, onUpscale, onCompare}: {selectedCount: number; isTrash: boolean; busy: boolean; canCompare: boolean; onClear: () => void; onKeep: () => void; onReject: () => void; onTrash: () => void; onRestore: () => void; onDelete: () => void; onDeleteDirect: () => void; onRegen: () => void; onUpscale: () => void; onCompare: () => void}) { return <section className="legacy-selection-bar" aria-label="批量操作"><div><strong>已选择 {selectedCount} 项</strong><button type="button" onClick={onClear}>清除</button></div>{isTrash ? <div><button type="button" disabled={busy} onClick={onRestore}><ClockCounterClockwise size={16} />恢复</button><button type="button" disabled={busy} className="is-danger" onClick={onDelete}><Trash size={16} />永久删除</button></div> : <div><button type="button" disabled={busy} onClick={onRegen}><Images size={16} />再出图</button><button type="button" disabled={busy} onClick={onUpscale}><MagicWand size={16} />1.5× 修复</button><button type="button" disabled={!canCompare} onClick={onCompare}><SlidersHorizontal size={16} />比较</button><button type="button" disabled={busy} onClick={onKeep}><Heart size={16} />保留</button><button type="button" disabled={busy} onClick={onReject}><X size={16} />淘汰</button><button type="button" disabled={busy} onClick={onTrash}><Trash size={16} />移入回收站</button><button type="button" disabled={busy} className="is-danger" onClick={onDeleteDirect}><Trash size={16} />彻底删除</button></div>}</section>; }
function ProcessDialog({selection, count, busy, onCount, onCancel, onSubmit}: {selection: {items: GalleryAsset[]; operation: "regenerate" | "upscale"}; count: number; busy: boolean; onCount: (value: number) => void; onCancel: () => void; onSubmit: () => void}) { const regen = selection.operation === "regenerate"; return <div className="legacy-dialog-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onCancel()}><section className="legacy-process-dialog" role="dialog" aria-modal="true" aria-label={regen ? "用同样提示词再出图" : "加入 1.5× 高清修复队列"}><header>{regen ? <Images size={22} /> : <MagicWand size={22} />}<div><h2>{regen ? "用同样提示词再出图" : "加入 1.5× 高清修复队列"}</h2><p>将顺序处理 {selection.items.length} 张图片，结果不会覆盖原图。</p></div></header><div className="legacy-process-source"><img src={selection.items[0].thumbnail_url} alt="" /><span>{selection.items[0].name}</span></div>{regen && <label>每张再出<select value={count} onChange={(event) => onCount(Number(event.target.value))}>{[1, 2, 3, 4].map((item) => <option key={item} value={item}>{item} 张</option>)}</select></label>}<footer><button type="button" onClick={onCancel}>取消</button><button type="button" className="is-primary" disabled={busy} onClick={onSubmit}>{busy ? "正在加入…" : "加入队列"}</button></footer></section></div>; }
function Compare({assets, onClose}: {assets: GalleryAsset[]; onClose: () => void}) { return <div className="legacy-compare" role="dialog" aria-modal="true" aria-label="图片比较"><header><div><SlidersHorizontal size={20} /><strong>比较候选</strong><span>{assets.length} 张</span></div><button type="button" onClick={onClose} aria-label="关闭比较"><X size={21} /></button></header><div>{assets.map((asset) => <figure key={asset.path}><img src={asset.content_url} alt={asset.name} /><figcaption>{asset.name}</figcaption></figure>)}</div></div>; }
