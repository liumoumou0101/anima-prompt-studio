import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Aperture,
  ArrowsOutSimple,
  CaretDown,
  Check,
  ClockCounterClockwise,
  Copy,
  FolderOpen,
  Funnel,
  Heart,
  ImageSquare,
  ListChecks,
  MagnifyingGlass,
  MagicWand,
  SelectionAll,
  SpinnerGap,
  SlidersHorizontal,
  SortAscending,
  SquaresFour,
  Trash,
  X,
} from "@phosphor-icons/react";
import PhotoAlbum from "react-photo-album";
import "react-photo-album/rows.css";
import Lightbox from "yet-another-react-lightbox";
import "yet-another-react-lightbox/styles.css";
import "./styles.css";

const EMPTY_DATA = {
  assets: [], projects: [], models: [], batches: [], trashCount: 0,
  processing: { available: false, reason: "", scale: 1.5, workflowName: "", activeJob: null, queuedCount: 0 },
  processingToken: "",
};
const THUMB_SIZE_KEY = "anima-gallery-thumb-size";
const DEFAULT_THUMB_SIZE = 205;
const VIEWS = [
  { id: "all", label: "图片", icon: ImageSquare },
  { id: "recent", label: "最近生成", icon: ClockCounterClockwise },
  { id: "kept", label: "保留", icon: Heart },
  { id: "external", label: "外部图片", icon: FolderOpen },
  { id: "trash", label: "画廊回收站", icon: Trash },
];

function initialThumbSize() {
  const saved = Number.parseInt(window.localStorage.getItem(THUMB_SIZE_KEY) || "", 10);
  return Number.isFinite(saved) ? Math.min(285, Math.max(150, saved)) : DEFAULT_THUMB_SIZE;
}

function galleryRowConstraints(containerWidth, thumbSize) {
  const target = Math.max(150, thumbSize);
  return {
    maxPhotos: Math.min(12, Math.max(6, Math.round(containerWidth / target))),
    singleRowMaxHeight: Math.round(target * 1.25),
  };
}

function formatBytes(bytes) {
  if (!bytes) return "大小未知";
  if (bytes < 1024 * 1024) return Math.max(1, Math.round(bytes / 1024)) + " KB";
  return (bytes / 1024 / 1024).toFixed(1) + " MB";
}

function formatDate(value) {
  if (!value) return "时间未知";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function dateKey(value) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "unknown";
  return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join("-");
}

function dateLabel(value) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "short",
  }).format(date);
}

async function postJson(url, payload, token = "") {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { "X-Gallery-Token": token } : {}),
    },
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "HTTP " + response.status);
  return result;
}

function App() {
  const [data, setData] = useState(EMPTY_DATA);
  const [view, setView] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [project, setProject] = useState("");
  const [model, setModel] = useState("");
  const [batch, setBatch] = useState("");
  const [sort, setSort] = useState("newest");
  const [filterOpen, setFilterOpen] = useState(false);
  const [thumbSize, setThumbSize] = useState(initialThumbSize);
  const [selected, setSelected] = useState(() => new Set());
  const [active, setActive] = useState(null);
  const [lightboxIndex, setLightboxIndex] = useState(-1);
  const [compareOpen, setCompareOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [processSubmitting, setProcessSubmitting] = useState(false);
  const [processJobs, setProcessJobs] = useState([]);
  const [confirmAssets, setConfirmAssets] = useState([]);
  const [taskCenterOpen, setTaskCenterOpen] = useState(false);
  const [pendingResultPath, setPendingResultPath] = useState("");
  const [visibleLimit, setVisibleLimit] = useState(160);
  const loadMoreRef = useRef(null);
  const processStatesRef = useRef(new Map());
  const processPollReadyRef = useRef(false);

  const load = async (nextView = view) => {
    setLoading(true);
    setError("");
    try {
      const endpoint = nextView === "trash" ? "/api/gallery/trash" : "/api/gallery";
      const response = await fetch(endpoint, { cache: "no-store" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      const payload = { ...EMPTY_DATA, ...(await response.json()) };
      setData(payload);
      return payload;
    } catch (reason) {
      setError("无法读取画廊数据：" + (reason.message || reason));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setSelected(new Set());
    setActive(null);
    setVisibleLimit(160);
    load(view);
  }, [view]);

  useEffect(() => {
    if (!pendingResultPath) return;
    const result = data.assets.find((asset) => asset.path === pendingResultPath);
    if (result) {
      setActive(result);
      setPendingResultPath("");
    }
  }, [data.assets, pendingResultPath]);

  useEffect(() => {
    if (!data.processingToken) return undefined;
    let stopped = false;
    const poll = async () => {
      try {
        const response = await fetch("/api/gallery/process/jobs", {
          cache: "no-store",
          headers: { "X-Gallery-Token": data.processingToken },
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "HTTP " + response.status);
        if (stopped) return;
        const jobs = result.jobs || [];
        if (processPollReadyRef.current) {
          const completed = jobs.find((job) => processStatesRef.current.get(job.id) !== "completed" && job.state === "completed");
          const failed = jobs.find((job) => processStatesRef.current.get(job.id) !== "failed" && job.state === "failed");
          if (completed) {
            setNotice("1.5× 高清修复完成，结果已加入画廊");
            setPendingResultPath(completed.resultPath || "");
            if (view !== "all") setView("all");
            else await load("all");
          }
          if (failed) setError("高清修复失败：" + (failed.error || failed.message));
        }
        processStatesRef.current = new Map(jobs.map((job) => [job.id, job.state]));
        processPollReadyRef.current = true;
        setProcessJobs(jobs);
        setData((previous) => ({ ...previous, processing: result.processing || previous.processing }));
      } catch (reason) {
        if (!stopped) setError("无法读取高清修复进度：" + (reason.message || reason));
      }
    };
    const timer = window.setInterval(poll, 1200);
    poll();
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [data.processingToken, view]);

  useEffect(() => {
    window.localStorage.setItem(THUMB_SIZE_KEY, String(thumbSize));
  }, [thumbSize]);

  const visible = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    let assets = data.assets.filter((asset) => {
      if (view === "recent" && asset.source !== "generated") return false;
      if (view === "kept" && asset.state !== "kept") return false;
      if (view === "external" && asset.source !== "external") return false;
      if (project && asset.project !== project) return false;
      if (model && asset.model !== model) return false;
      if (batch && asset.batchId !== batch) return false;
      if (!normalized) return true;
      return [asset.name, asset.path, asset.project, asset.model, asset.prompt, asset.batchTitle]
        .filter(Boolean)
        .join(" ")
        .toLocaleLowerCase()
        .includes(normalized);
    });
    assets = [...assets].sort((left, right) => {
      if (sort === "name") return left.name.localeCompare(right.name, "zh-CN");
      const difference = new Date(right.createdAt).valueOf() - new Date(left.createdAt).valueOf();
      return sort === "oldest" ? -difference : difference;
    });
    return view === "recent" ? assets.slice(0, 300) : assets;
  }, [batch, data.assets, model, project, query, sort, view]);

  const displayed = visible.slice(0, visibleLimit);
  const groups = useMemo(() => {
    const result = [];
    for (const asset of displayed) {
      const key = dateKey(asset.createdAt);
      let group = result.find((item) => item.key === key);
      if (!group) {
        group = { key, label: dateLabel(asset.createdAt), assets: [] };
        result.push(group);
      }
      group.assets.push(asset);
    }
    return result;
  }, [displayed]);

  useEffect(() => {
    const node = loadMoreRef.current;
    if (!node || visibleLimit >= visible.length) return undefined;
    const observer = new IntersectionObserver((entries) => {
      if (entries[0]?.isIntersecting) setVisibleLimit((value) => Math.min(value + 160, visible.length));
    }, { rootMargin: "600px" });
    observer.observe(node);
    return () => observer.disconnect();
  }, [visible.length, visibleLimit]);

  useEffect(() => {
    const onKeyDown = (event) => {
      const tag = event.target?.tagName?.toLowerCase();
      if (tag === "input" || tag === "select" || tag === "textarea") return;
      if (event.key === "Escape") {
        if (confirmAssets.length) {
          setConfirmAssets([]);
          return;
        }
        if (taskCenterOpen) {
          setTaskCenterOpen(false);
          return;
        }
        setCompareOpen(false);
        setActive(null);
        return;
      }
      if (!active || view === "trash") return;
      if (event.key.toLowerCase() === "p") updateState("kept", [active.path]);
      if (event.key.toLowerCase() === "x") updateState("rejected", [active.path]);
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        const index = visible.findIndex((asset) => asset.id === active.id);
        const next = event.key === "ArrowRight" ? index + 1 : index - 1;
        if (visible[next]) setActive(visible[next]);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [active, confirmAssets, taskCenterOpen, view, visible]);

  const selectedAssets = useMemo(
    () => data.assets.filter((asset) => selected.has(asset.id)),
    [data.assets, selected],
  );

  const lightboxSlides = useMemo(
    () => visible.map((asset) => ({ src: asset.src, width: asset.width, height: asset.height, alt: asset.project + " · " + asset.name })),
    [visible],
  );

  const filterCount = [project, model, batch].filter(Boolean).length;
  const pendingProcessJobs = processJobs.filter((job) => !["completed", "failed", "canceled"].includes(job.state));
  const activeProcessJob = processJobs.find((job) => !["queued", "completed", "failed", "canceled"].includes(job.state));
  const queuedProcessCount = processJobs.filter((job) => job.state === "queued").length;

  const openView = (nextView) => {
    setView(nextView);
    setFilterOpen(false);
  };

  const toggleSelected = (asset) => {
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(asset.id)) next.delete(asset.id);
      else next.add(asset.id);
      return next;
    });
  };

  const selectGroup = (assets) => {
    setSelected((previous) => {
      const next = new Set(previous);
      const allSelected = assets.every((asset) => next.has(asset.id));
      assets.forEach((asset) => allSelected ? next.delete(asset.id) : next.add(asset.id));
      return next;
    });
  };

  const clearFilters = () => {
    setProject("");
    setModel("");
    setBatch("");
    setQuery("");
  };

  const updateState = async (state, explicitPaths = null) => {
    const paths = explicitPaths || selectedAssets.map((asset) => asset.path);
    if (!paths.length || busy) return;
    setBusy(true);
    setError("");
    try {
      await postJson("/api/gallery/state", { paths, state });
      setData((previous) => ({
        ...previous,
        assets: previous.assets.map((asset) => paths.includes(asset.path) ? { ...asset, state } : asset),
      }));
      setNotice(state === "kept" ? `已保留 ${paths.length} 张图片` : state === "rejected" ? `已标记淘汰 ${paths.length} 张图片` : "已清除标记");
    } catch (reason) {
      setError("无法更新图片状态：" + (reason.message || reason));
    } finally {
      setBusy(false);
    }
  };

  const moveToTrash = async () => {
    const paths = selectedAssets.map((asset) => asset.path);
    if (!paths.length || busy) return;
    if (!window.confirm(`确定将选中的 ${paths.length} 张图片移入画廊回收站吗？之后仍可恢复。`)) return;
    setBusy(true);
    try {
      const result = await postJson("/api/gallery/trash", { paths });
      setSelected(new Set());
      setActive(null);
      setNotice(`已将 ${result.moved.length} 张图片移入画廊回收站`);
      await load(view);
    } catch (reason) {
      setError("批量管理失败：" + (reason.message || reason));
    } finally {
      setBusy(false);
    }
  };

  const restoreSelected = async () => {
    const paths = selectedAssets.map((asset) => asset.path);
    if (!paths.length || busy) return;
    setBusy(true);
    try {
      const result = await postJson("/api/gallery/restore", { paths });
      setSelected(new Set());
      setActive(null);
      setNotice(`已恢复 ${result.restored.length} 张图片`);
      await load("trash");
    } catch (reason) {
      setError("恢复失败：" + (reason.message || reason));
    } finally {
      setBusy(false);
    }
  };

  const deleteSelected = async () => {
    const paths = selectedAssets.map((asset) => asset.path);
    if (!paths.length || busy) return;
    if (!window.confirm(`将永久删除选中的 ${paths.length} 张图片，此操作无法撤销。确定继续吗？`)) return;
    setBusy(true);
    try {
      const result = await postJson("/api/gallery/delete", { paths });
      setSelected(new Set());
      setActive(null);
      setNotice(`已永久删除 ${result.deleted.length} 张图片`);
      await load("trash");
    } catch (reason) {
      setError("永久删除失败：" + (reason.message || reason));
    } finally {
      setBusy(false);
    }
  };

  const copyText = async (value, label) => {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setNotice(`已复制${label}`);
    } catch {
      setError(`无法复制${label}`);
    }
  };

  const revealActive = async () => {
    if (!active || view === "trash") return;
    try {
      await postJson("/api/gallery/reveal", { path: active.path });
    } catch (reason) {
      setError(reason.message || String(reason));
    }
  };

  const openLightbox = (asset) => {
    const index = visible.findIndex((candidate) => candidate.id === asset.id);
    if (index >= 0) setLightboxIndex(index);
  };

  const startUpscale = async () => {
    if (!confirmAssets.length || processSubmitting) return;
    setProcessSubmitting(true);
    setError("");
    try {
      const result = await postJson(
        "/api/gallery/process",
        { paths: confirmAssets.map((asset) => asset.path) },
        data.processingToken,
      );
      setProcessJobs((previous) => [...(result.jobs || []), ...previous]);
      setConfirmAssets([]);
      setSelected(new Set());
      setTaskCenterOpen(true);
      const accepted = result.jobs?.length || 0;
      const failed = result.failed?.length || 0;
      setNotice(`已加入 ${accepted} 项 1.5× 高清修复任务${failed ? `，${failed} 项未加入` : ""}`);
      if (failed) setError(result.failed.map((item) => `${item.path}：${item.error}`).join("；"));
    } catch (reason) {
      setError("无法加入高清修复队列：" + (reason.message || reason));
    } finally {
      setProcessSubmitting(false);
    }
  };

  const processAction = async (job, action) => {
    try {
      await postJson("/api/gallery/process/action", { job: job?.id || "", action }, data.processingToken);
      const response = await fetch("/api/gallery/process/jobs", { cache: "no-store", headers: { "X-Gallery-Token": data.processingToken } });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "HTTP " + response.status);
      setProcessJobs(result.jobs || []);
      setData((previous) => ({ ...previous, processing: result.processing || previous.processing }));
    } catch (reason) {
      setError("任务操作失败：" + (reason.message || reason));
    }
  };

  const openProcessResult = async (job) => {
    if (!job.resultPath) return;
    if (view !== "all") {
      setPendingResultPath(job.resultPath);
      setTaskCenterOpen(false);
      setView("all");
      return;
    }
    let result = data.assets.find((asset) => asset.path === job.resultPath);
    if (!result) {
      const payload = await load("all");
      result = payload?.assets?.find((asset) => asset.path === job.resultPath);
    }
    if (result) {
      setActive(result);
      setTaskCenterOpen(false);
    }
  };

  return (
    <div className="gallery-app">
      <aside className="sidebar" aria-label="画廊导航">
        <div className="brand">
          <Aperture size={28} weight="duotone" />
          <div><strong>ANIMA</strong><span>PROMPT STUDIO</span></div>
        </div>
        <nav>
          {VIEWS.map(({ id, label, icon: Icon }) => (
            <button key={id} className={view === id ? "is-active" : ""} onClick={() => openView(id)} aria-label={label}>
              <Icon size={22} />
              <span>{label}</span>
              {id === "trash" && data.trashCount > 0 && <small>{data.trashCount}</small>}
              {id === "external" && <i aria-hidden="true" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-tip"><kbd>P</kbd> 保留　<kbd>X</kbd> 淘汰</div>
      </aside>

      <main className="main-shell">
        <header className="topbar">
          <div className="title-block">
            <h1>{view === "all" ? "图片画廊" : VIEWS.find((item) => item.id === view)?.label || "图片画廊"}</h1>
            <span>{visible.length} 张</span>
          </div>
          <label className="search-box">
            <MagnifyingGlass size={20} />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索项目、提示词、文件名…" />
            <kbd>/</kbd>
          </label>
          <div className="top-actions">
            <button
              className={taskCenterOpen ? "tool-button is-active" : "tool-button"}
              onClick={() => setTaskCenterOpen((value) => !value)}
              aria-label="高清修复任务中心"
            >
              <ListChecks size={20} /><span>任务</span>{pendingProcessJobs.length > 0 && <b>{pendingProcessJobs.length}</b>}
            </button>
            {view !== "trash" && (
              <button className={filterOpen || filterCount ? "tool-button is-active" : "tool-button"} onClick={() => setFilterOpen((value) => !value)} aria-label="筛选">
                <Funnel size={20} /><span>筛选</span>{filterCount > 0 && <b>{filterCount}</b>}
              </button>
            )}
            <label className="sort-control">
              <SortAscending size={19} />
              <select value={sort} onChange={(event) => setSort(event.target.value)} aria-label="排序">
                <option value="newest">最新优先</option>
                <option value="oldest">最早优先</option>
                <option value="name">文件名</option>
              </select>
              <CaretDown size={14} />
            </label>
            <div className="size-control" aria-label="缩略图大小">
              <SquaresFour size={18} />
              <input
                type="range"
                min="150"
                max="285"
                value={thumbSize}
                aria-label="缩略图高度"
                aria-valuetext={`${thumbSize} 像素`}
                title={`缩略图高度：${thumbSize} 像素`}
                onChange={(event) => setThumbSize(Number(event.target.value))}
              />
              <SquaresFour size={24} weight="fill" />
            </div>
            <button className="icon-button" onClick={() => load(view)} aria-label="刷新画廊" title="刷新画廊">
              <ClockCounterClockwise size={22} />
            </button>
          </div>
        </header>

        {filterOpen && view !== "trash" && (
          <section className="filter-popover" aria-label="画廊筛选">
            <label><span>项目</span><select value={project} onChange={(event) => setProject(event.target.value)}><option value="">全部项目</option>{data.projects.map((value) => <option key={value}>{value}</option>)}</select></label>
            <label><span>模型</span><select value={model} onChange={(event) => setModel(event.target.value)}><option value="">全部模型</option>{data.models.map((value) => <option key={value}>{value}</option>)}</select></label>
            <label><span>批次</span><select value={batch} onChange={(event) => setBatch(event.target.value)}><option value="">全部批次</option>{data.batches.map((value) => <option key={value.id} value={value.id}>{value.title}</option>)}</select></label>
            <button onClick={clearFilters}>清除筛选</button>
          </section>
        )}

        {error && <div className="message error-message" role="alert"><X size={18} />{error}<button onClick={() => load(view)}>重试</button></div>}
        {notice && <div className="message success-message" role="status"><Check size={18} />{notice}<button onClick={() => setNotice("")} aria-label="关闭通知"><X size={16} /></button></div>}

        <section className="gallery-scroll">
          {loading && <EmptyState title="正在读取图片…" />}
          {!loading && !visible.length && (
            <EmptyState
              title={view === "trash" ? "画廊回收站是空的" : data.assets.length ? "没有匹配的图片" : "画廊里还没有图片"}
              description={view === "trash" ? "移入画廊回收站的图片会出现在这里。" : data.assets.length ? "清除搜索或筛选条件后再试一次。" : "完成一次生图，或将图片放入当前保存目录。"}
              action={data.assets.length && view !== "trash" ? <button onClick={clearFilters}>清除筛选</button> : null}
            />
          )}
          {!loading && groups.map((group) => (
            <GalleryGroup
              key={group.key}
              group={group}
              selected={selected}
              thumbSize={thumbSize}
              active={active}
              onOpen={setActive}
              onPreview={openLightbox}
              onToggle={toggleSelected}
              onSelectGroup={selectGroup}
              isTrash={view === "trash"}
            />
          ))}
          <div ref={loadMoreRef} className="load-more-sentinel">
            {visibleLimit < visible.length ? `继续载入 · ${visible.length - visibleLimit} 张` : visible.length ? `已显示全部 ${visible.length} 张` : ""}
          </div>
        </section>

        {groups.length > 1 && (
          <aside className="date-rail" aria-label="日期导航">
            <strong>{groups[0].key.slice(0, 7).replace("-", "年")}月</strong>
            {groups.map((group) => (
              <a key={group.key} href={`#date-${group.key}`}><i />{group.key.slice(-2)}</a>
            ))}
          </aside>
        )}
      </main>

      {active && (
        <DetailDrawer
          asset={active}
          isTrash={view === "trash"}
          onClose={() => setActive(null)}
          onPreview={() => openLightbox(active)}
          onCopy={copyText}
          onReveal={revealActive}
          onState={(state) => updateState(state, [active.path])}
          processing={data.processing}
          processJobs={processJobs}
          onUpscale={() => setConfirmAssets([active])}
        />
      )}

      {(activeProcessJob || queuedProcessCount > 0) && !taskCenterOpen && (
        <ProcessStatus
          job={activeProcessJob}
          queuedCount={queuedProcessCount}
          onOpen={() => setTaskCenterOpen(true)}
        />
      )}

      {confirmAssets.length > 0 && (
        <UpscaleConfirmDialog
          assets={confirmAssets}
          processing={data.processing}
          submitting={processSubmitting}
          onCancel={() => setConfirmAssets([])}
          onConfirm={startUpscale}
        />
      )}

      {taskCenterOpen && (
        <TaskCenter
          jobs={processJobs}
          assets={data.assets}
          processing={data.processing}
          onClose={() => setTaskCenterOpen(false)}
          onAction={processAction}
          onOpenResult={openProcessResult}
        />
      )}

      {selectedAssets.length > 0 && (
        <SelectionBar
          assets={selectedAssets}
          isTrash={view === "trash"}
          busy={busy}
          onClear={() => setSelected(new Set())}
          onCompare={() => selectedAssets.length >= 2 && setCompareOpen(true)}
          onState={updateState}
          onTrash={moveToTrash}
          onRestore={restoreSelected}
          onDelete={deleteSelected}
          upscaleAvailable={data.processing?.available}
          onUpscale={() => setConfirmAssets(selectedAssets)}
        />
      )}

      {compareOpen && <CompareOverlay assets={selectedAssets.slice(0, 4)} onClose={() => setCompareOpen(false)} />}

      <Lightbox
        open={lightboxIndex >= 0}
        close={() => setLightboxIndex(-1)}
        index={lightboxIndex}
        slides={lightboxSlides}
        labels={{ Close: "关闭", Previous: "上一张", Next: "下一张" }}
        on={{ view: ({ index }) => setLightboxIndex(index) }}
      />
    </div>
  );
}

function GalleryGroup({ group, selected, thumbSize, active, onOpen, onPreview, onToggle, onSelectGroup, isTrash }) {
  const photos = group.assets.map((asset) => ({
    ...asset,
    src: asset.thumbnail || asset.src,
    alt: `${asset.project || "未分类"} · ${asset.name}`,
    width: asset.width || 1024,
    height: asset.height || 1024,
  }));
  const batches = new Set(group.assets.map((asset) => asset.batchId)).size;
  return (
    <section className="date-group" id={`date-${group.key}`}>
      <header className="date-heading">
        <div><h2>{group.label}</h2><span>{group.assets.length} 个项目</span></div>
        <div><span>{batches > 1 ? `${batches} 个批次` : group.assets[0]?.batchTitle}</span><button onClick={() => onSelectGroup(group.assets)}><SelectionAll size={17} />选择本组</button></div>
      </header>
      <PhotoAlbum
        layout="rows"
        photos={photos}
        targetRowHeight={thumbSize}
        spacing={8}
        rowConstraints={(containerWidth) => galleryRowConstraints(containerWidth, thumbSize)}
        render={{
          photo: (_props, { photo, width, height }) => (
            <PhotoCard
              asset={photo}
              style={{ width, height }}
              selected={selected.has(photo.id)}
              active={active?.id === photo.id}
              onOpen={() => onOpen(photo)}
              onPreview={() => onPreview(photo)}
              onToggle={() => onToggle(photo)}
              isTrash={isTrash}
            />
          ),
        }}
      />
    </section>
  );
}

function PhotoCard({ asset, style, selected, active, onOpen, onPreview, onToggle, isTrash }) {
  return (
    <article className={`photo-card${selected ? " is-selected" : ""}${active ? " is-active" : ""}`} style={style}>
      <button className="photo-open" onClick={onOpen} onDoubleClick={onPreview} aria-label={`查看 ${asset.name}`}>
        <img src={asset.thumbnail || asset.src} alt={asset.alt} loading="lazy" />
      </button>
      <button className="selection-toggle" onClick={onToggle} aria-pressed={selected} aria-label={`${selected ? "取消选择" : "选择"} ${asset.name}`}>
        {selected && <Check size={16} weight="bold" />}
      </button>
      {!isTrash && asset.state === "kept" && <span className="state-badge kept"><Heart size={14} weight="fill" />保留</span>}
      {!isTrash && asset.state === "rejected" && <span className="state-badge rejected"><X size={14} weight="bold" />淘汰</span>}
      {!isTrash && asset.source === "external" && <span className="source-badge"><FolderOpen size={13} />外部图片</span>}
      {asset.parameters?.operation === "gallery_upscale_1_5x" && <span className="process-badge"><MagicWand size={13} />1.5× 修复</span>}
      <span className="photo-name">{asset.name}</span>
    </article>
  );
}

function DetailDrawer({ asset, isTrash, onClose, onPreview, onCopy, onReveal, onState, processing, processJobs, onUpscale }) {
  const parameters = Object.entries(asset.parameters || {}).filter(([key]) => !["width", "height"].includes(key)).slice(0, 5);
  const processJob = processJobs.find((job) => job.sourcePath === asset.path && !["completed", "failed", "canceled"].includes(job.state));
  const activeForAsset = processJob && processJob.state !== "queued";
  const waitingForAsset = processJob?.state === "queued";
  const queueBusy = processJobs.some((job) => !["completed", "failed", "canceled"].includes(job.state));
  return (
    <aside className="detail-drawer" aria-label="图片详情">
      <header><span>图片详情</span><button onClick={onClose} aria-label="关闭图片详情"><X size={22} /></button></header>
      <div className="drawer-body">
        <button className="drawer-preview" onClick={onPreview} aria-label="查看原图"><img src={asset.thumbnail || asset.src} alt={asset.name} /><ArrowsOutSimple size={22} /></button>
        <h2>{asset.name}</h2>
        <dl>
          <div><dt>项目</dt><dd>{asset.project || "未分类"}</dd></div>
          <div><dt>模型</dt><dd>{asset.model || "未知"}</dd></div>
          <div><dt>尺寸</dt><dd>{asset.width} × {asset.height}</dd></div>
          <div><dt>来源</dt><dd>{isTrash ? "画廊回收站" : asset.source === "external" ? "外部图片" : "ANIMA 生成"}</dd></div>
          <div><dt>时间</dt><dd>{formatDate(asset.createdAt)}</dd></div>
          <div><dt>文件大小</dt><dd>{formatBytes(asset.bytes)}</dd></div>
          {parameters.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}
        </dl>
        {asset.prompt && <section className="prompt-section"><h3>提示词</h3><p>{asset.prompt}</p><button onClick={() => onCopy(asset.prompt, "提示词")}><Copy size={17} />复制提示词</button></section>}
      </div>
      {!isTrash && <footer className="drawer-footer">
        <button
          className="upscale-button"
          onClick={onUpscale}
          disabled={!processing?.available || Boolean(processJob)}
          title={!processing?.available ? processing?.reason : waitingForAsset ? `队列第 ${processJob.queuePosition} 位` : ""}
        >
          {activeForAsset ? <SpinnerGap className="spin" size={19} /> : <MagicWand size={19} weight="duotone" />}
          {activeForAsset ? processJob.message : waitingForAsset ? `已排队 · 第 ${processJob.queuePosition} 位` : queueBusy ? "加入 1.5× 修复队列" : "1.5× 高清修复"}
        </button>
        {!processing?.available && <p className="upscale-unavailable">{processing?.reason}</p>}
        {activeForAsset && <progress className="drawer-progress" max="1" value={processJob.progress || 0} aria-label="高清修复进度" />}
        <div className="drawer-state-actions"><button onClick={() => onState("kept")}><Heart size={17} />保留</button><button onClick={() => onState("rejected")}><X size={17} />淘汰</button></div>
        <button className="reveal-button" onClick={onReveal}><FolderOpen size={19} />在文件夹中显示</button>
      </footer>}
    </aside>
  );
}

function UpscaleConfirmDialog({ assets, processing, submitting, onCancel, onConfirm }) {
  const asset = assets[0];
  const scale = processing?.scale || 1.5;
  const targetWidth = Math.round(asset.width * scale);
  const targetHeight = Math.round(asset.height * scale);
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onCancel()}>
      <section className="upscale-dialog" role="dialog" aria-modal="true" aria-labelledby="upscale-dialog-title">
        <header><MagicWand size={24} weight="duotone" /><div><h2 id="upscale-dialog-title">加入 1.5× 高清修复队列</h2><p>使用云显卡的分块放大工作流依次处理 {assets.length} 张图片</p></div></header>
        <div className="upscale-source">
          <img src={asset.thumbnail || asset.src} alt="待处理原图" />
          <div><strong>{asset.name}{assets.length > 1 ? ` 等 ${assets.length} 张` : ""}</strong><span>{asset.width} × {asset.height} → {targetWidth} × {targetHeight}</span><span>{processing?.workflowName}</span></div>
        </div>
        <p className="upscale-note">任务会按顺序执行。结果不会覆盖原图，每项完成后会自动出现在画廊中；你可以继续浏览和添加任务。</p>
        <footer><button onClick={onCancel} disabled={submitting}>取消</button><button className="confirm-upscale" onClick={onConfirm} disabled={submitting} autoFocus>{submitting ? <><SpinnerGap className="spin" size={18} />正在加入…</> : <><MagicWand size={18} />加入队列</>}</button></footer>
      </section>
    </div>
  );
}

function ProcessStatus({ job, queuedCount, onOpen }) {
  return (
    <button className="process-status" onClick={onOpen} type="button">
      <div className="process-status-icon">{job ? <SpinnerGap className="spin" size={20} /> : <ListChecks size={20} />}</div>
      <div><strong>{job ? "正在进行 1.5× 高清修复" : "高清修复任务队列"}</strong><span>{job?.message || `等待处理 ${queuedCount} 项`}{queuedCount > 0 && job ? ` · 后面还有 ${queuedCount} 项` : ""}</span>{job && <progress max="1" value={job.progress || 0} aria-label="高清修复进度" />}</div>
      <span className="process-status-open">查看任务</span>
    </button>
  );
}

function TaskCenter({ jobs, assets, processing, onClose, onAction, onOpenResult }) {
  const terminalCount = jobs.filter((job) => ["completed", "canceled"].includes(job.state)).length;
  const stateLabel = (job) => {
    if (job.state === "queued") return `等待中 · 第 ${job.queuePosition} 位`;
    if (job.state === "completed") return "已完成";
    if (job.state === "failed") return "失败";
    if (job.state === "canceled") return "已取消";
    return "处理中";
  };
  return (
    <aside className="task-center" aria-label="高清修复任务中心">
      <header><div><ListChecks size={21} /><span>高清修复任务</span></div><button onClick={onClose} aria-label="关闭任务中心"><X size={22} /></button></header>
      <div className="task-summary">
        <div><strong>{processing?.activeCount || 0}</strong><span>处理中</span></div>
        <div><strong>{processing?.queuedCount || 0}</strong><span>等待中</span></div>
        <div><strong>{processing?.failedCount || 0}</strong><span>失败</span></div>
      </div>
      <div className="task-list">
        {!jobs.length && <div className="task-empty"><ListChecks size={32} weight="thin" /><span>还没有高清修复任务</span></div>}
        {jobs.map((job) => {
          const asset = assets.find((item) => item.path === job.sourcePath);
          const active = !["queued", "completed", "failed", "canceled"].includes(job.state);
          return (
            <article className={`task-card is-${job.state}`} key={job.id}>
              <img src={asset?.thumbnail || `/api/thumbnail?path=${encodeURIComponent(job.sourcePath)}&size=240`} alt="" />
              <div className="task-card-body">
                <div className="task-card-title"><strong>{job.sourceName}</strong><span>{stateLabel(job)}</span></div>
                <small>{job.sourceWidth} × {job.sourceHeight} → {job.targetWidth} × {job.targetHeight}</small>
                <p>{job.state === "failed" ? job.error || job.message : job.message}</p>
                {active && <progress max="1" value={job.progress || 0} aria-label={`${job.sourceName} 处理进度`} />}
                <div className="task-actions">
                  {job.state === "queued" && <button onClick={() => onAction(job, "cancel")}>取消等待</button>}
                  {["failed", "canceled"].includes(job.state) && <button onClick={() => onAction(job, "retry")}>重新加入</button>}
                  {job.state === "completed" && job.resultPath && <button onClick={() => onOpenResult(job)}>查看结果</button>}
                </div>
              </div>
            </article>
          );
        })}
      </div>
      {terminalCount > 0 && <footer><button onClick={() => onAction(null, "clear_completed")}>清理已完成记录</button></footer>}
    </aside>
  );
}

function SelectionBar({ assets, isTrash, busy, onClear, onCompare, onState, onTrash, onRestore, onDelete, upscaleAvailable, onUpscale }) {
  return (
    <section className="selection-bar" aria-label="批量操作">
      <div className="selection-summary"><strong>已选择 {assets.length} 项</strong><button onClick={onClear}>清除</button><div>{assets.slice(0, 3).map((asset) => <img key={asset.id} src={asset.thumbnail || asset.src} alt="" />)}</div></div>
      <div className="selection-actions">
        {isTrash ? <><button onClick={onRestore} disabled={busy}><ClockCounterClockwise size={19} />恢复</button><button className="danger" onClick={onDelete} disabled={busy}><Trash size={19} />永久删除</button></> : <><button className="upscale" onClick={onUpscale} disabled={busy || !upscaleAvailable}><MagicWand size={19} />1.5× 修复</button><button onClick={onCompare} disabled={assets.length < 2 || assets.length > 4}><SlidersHorizontal size={19} />比较</button><button className="keep" onClick={() => onState("kept")} disabled={busy}><Heart size={19} />保留</button><button onClick={() => onState("rejected")} disabled={busy}><X size={19} />淘汰</button><button className="danger" onClick={onTrash} disabled={busy}><Trash size={19} />移入画廊回收站</button></>}
      </div>
    </section>
  );
}

function CompareOverlay({ assets, onClose }) {
  return (
    <div className="compare-overlay" role="dialog" aria-modal="true" aria-label="图片比较">
      <header><div><SlidersHorizontal size={22} /><strong>比较候选</strong><span>{assets.length} 张</span></div><button onClick={onClose} aria-label="关闭比较"><X size={24} /></button></header>
      <div className={`compare-grid count-${assets.length}`}>{assets.map((asset) => <figure key={asset.id}><img src={asset.src} alt={asset.name} /><figcaption>{asset.name}</figcaption></figure>)}</div>
    </div>
  );
}

function EmptyState({ title, description, action }) {
  return <div className="empty-state"><ImageSquare size={38} weight="thin" /><strong>{title}</strong>{description && <span>{description}</span>}{action}</div>;
}

createRoot(document.getElementById("root")).render(<App />);
