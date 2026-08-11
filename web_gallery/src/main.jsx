import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import PhotoAlbum from "react-photo-album";
import Lightbox from "yet-another-react-lightbox";
import "yet-another-react-lightbox/styles.css";
import "./styles.css";

const EMPTY_DATA = { assets: [], projects: [], models: [], batches: [] };

function formatBytes(bytes) {
  if (!bytes) return "大小未知";
  if (bytes < 1024 * 1024) return Math.max(1, Math.round(bytes / 1024)) + " KB";
  return (bytes / 1024 / 1024).toFixed(1) + " MB";
}

function formatDate(value) {
  if (!value) return "时间未知";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString();
}

function App() {
  const [data, setData] = useState(EMPTY_DATA);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [project, setProject] = useState("");
  const [model, setModel] = useState("");
  const [batch, setBatch] = useState("");
  const [selected, setSelected] = useState(() => new Set());
  const [active, setActive] = useState(null);
  const [lightboxIndex, setLightboxIndex] = useState(-1);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/gallery", { cache: "no-store" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      setData(await response.json());
    } catch (reason) {
      setError("无法读取画廊数据：" + (reason.message || reason));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const visible = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return data.assets.filter((asset) => {
      if (project && asset.project !== project) return false;
      if (model && asset.model !== model) return false;
      if (batch && asset.batchId !== batch) return false;
      if (!normalized) return true;
      return [asset.name, asset.project, asset.model, asset.prompt, asset.batchTitle]
        .filter(Boolean)
        .join(" ")
        .toLocaleLowerCase()
        .includes(normalized);
    });
  }, [batch, data.assets, model, project, query]);

  const photos = useMemo(
    () => visible.map((asset) => ({
      ...asset,
      alt: asset.project + " · " + asset.name,
      width: asset.width || 1024,
      height: asset.height || 1024,
    })),
    [visible],
  );

  const selectedCount = selected.size;
  const allVisibleSelected = visible.length > 0 && visible.every((asset) => selected.has(asset.id));
  const selectedAsset = active || visible.find((asset) => selected.has(asset.id)) || visible[0];

  const toggleSelected = (assetId) => {
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(assetId)) next.delete(assetId);
      else next.add(assetId);
      return next;
    });
  };

  const selectVisible = () => {
    setSelected((previous) => {
      const next = new Set(previous);
      visible.forEach((asset) => next.add(asset.id));
      return next;
    });
  };

  const clearSelection = () => setSelected(new Set());

  const moveSelectedToTrash = async () => {
    if (!selectedCount || busy) return;
    if (!window.confirm("确定将选中的 " + selectedCount + " 张图片移入回收站吗？图片不会立即永久删除。")) return;
    setBusy(true);
    try {
      const response = await fetch("/api/gallery/trash", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paths: [...selected] }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "HTTP " + response.status);
      setSelected(new Set());
      setActive(null);
      await load();
      if (result.failed && result.failed.length) {
        setError("已移动 " + result.moved.length + " 张，" + result.failed.length + " 张未能移动。");
      }
    } catch (reason) {
      setError("批量管理失败：" + (reason.message || reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">ANIMA PROMPT STUDIO</p>
          <h1>图片画廊</h1>
          <p className="subtitle">生成记录与保存目录中的图片都会出现在这里。</p>
        </div>
        <div className="topbar-actions">
          <span className="count-pill">{visible.length} / {data.assets.length} 张</span>
          <button className="secondary-button" onClick={load} disabled={loading}>
            {loading ? "读取中…" : "刷新"}
          </button>
        </div>
      </header>

      <section className="filter-panel" aria-label="画廊筛选">
        <label className="search-field">
          <span>搜索</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="项目、文件名、模型或提示词" />
        </label>
        <label>
          <span>项目</span>
          <select value={project} onChange={(event) => setProject(event.target.value)}>
            <option value="">全部项目</option>
            {data.projects.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <label>
          <span>模型</span>
          <select value={model} onChange={(event) => setModel(event.target.value)}>
            <option value="">全部模型</option>
            {data.models.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <label className="batch-filter">
          <span>批次</span>
          <select value={batch} onChange={(event) => setBatch(event.target.value)}>
            <option value="">全部批次</option>
            {data.batches.map((value) => <option key={value.id} value={value.id}>{value.title}</option>)}
          </select>
        </label>
      </section>

      <section className="toolbar">
        <div className="toolbar-left">
          <button className="secondary-button" onClick={allVisibleSelected ? clearSelection : selectVisible}>
            {allVisibleSelected ? "清除当前选择" : "全选当前结果"}
          </button>
          {selectedCount > 0 && <span className="selection-note">已选择 {selectedCount} 张</span>}
        </div>
        <button className="danger-button" onClick={moveSelectedToTrash} disabled={!selectedCount || busy}>
          {busy ? "处理中…" : "移入回收站" + (selectedCount ? "（" + selectedCount + "）" : "")}
        </button>
      </section>

      {error && <div className="error-banner">{error}</div>}

      <section className="gallery-layout">
        <div className="gallery-stage">
          {loading && <div className="empty-state">正在读取图片…</div>}
          {!loading && !visible.length && (
            <div className="empty-state"><strong>没有匹配的图片</strong><span>可以清除筛选条件，或先在提示词工具中完成一次生图。</span></div>
          )}
          {!loading && visible.length > 0 && (
            <PhotoAlbum
              layout="rows"
              photos={photos}
              targetRowHeight={230}
              spacing={12}
              onClick={({ index }) => {
                setActive(visible[index]);
                setLightboxIndex(index);
              }}
              renderPhoto={({ photo, imageProps, wrapperStyle }) => (
                <div className={"photo-card" + (selected.has(photo.id) ? " is-selected" : "")} style={wrapperStyle}>
                  <img {...imageProps} loading="lazy" />
                  <button
                    className="selection-toggle"
                    type="button"
                    aria-label={selected.has(photo.id) ? "取消选择 " + photo.name : "选择 " + photo.name}
                    aria-pressed={selected.has(photo.id)}
                    onClick={(event) => {
                      event.stopPropagation();
                      toggleSelected(photo.id);
                      setActive(photo);
                    }}
                  >
                    {selected.has(photo.id) ? "✓" : ""}
                  </button>
                  <span className="photo-caption">{photo.name}</span>
                </div>
              )}
            />
          )}
        </div>

        <aside className="detail-panel">
          <div className="detail-heading">
            <span>图片详情</span>
            {selectedCount > 0 && <span className="detail-count">{selectedCount} 已选</span>}
          </div>
          {selectedAsset ? (
            <>
              <img className="detail-preview" src={selectedAsset.src} alt={selectedAsset.alt} />
              <h2>{selectedAsset.name}</h2>
              <dl>
                <div><dt>项目</dt><dd>{selectedAsset.project || "未命名项目"}</dd></div>
                <div><dt>模型</dt><dd>{selectedAsset.model || "未知模型"}</dd></div>
                <div><dt>尺寸</dt><dd>{selectedAsset.width} × {selectedAsset.height}</dd></div>
                <div><dt>文件</dt><dd>{formatBytes(selectedAsset.bytes)}</dd></div>
                <div><dt>时间</dt><dd>{formatDate(selectedAsset.createdAt)}</dd></div>
              </dl>
              {selectedAsset.prompt && <p className="prompt-preview">{selectedAsset.prompt}</p>}
            </>
          ) : (
            <div className="detail-empty">选择一张图片查看详情。</div>
          )}
        </aside>
      </section>

      <Lightbox
        open={lightboxIndex >= 0}
        close={() => setLightboxIndex(-1)}
        index={lightboxIndex}
        slides={photos}
        on={{ view: ({ index }) => setLightboxIndex(index) }}
      />
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
