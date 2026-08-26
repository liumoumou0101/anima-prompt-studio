import {FormEvent, useEffect, useMemo, useState} from "react";
import {Link, useSearchParams} from "react-router-dom";
import {ApiClientError, apiRequest} from "../lib/api";
import type {SearchResponse, TagCategory, TagSearchItem} from "../lib/types";
import {NsfwBadge, TagBadge} from "../components/TagBadge";
import {EmptyState, ErrorState, LoadingState} from "../components/States";

const categories: Array<{value: TagCategory | ""; label: string}> = [
  {value: "", label: "全部"},
  {value: "general", label: "General"},
  {value: "character", label: "Character"},
  {value: "copyright", label: "Copyright"},
  {value: "meta", label: "Meta"},
];

export function TagSearchPage() {
  const [params, setParams] = useSearchParams();
  const urlQuery = params.get("q") || "";
  const urlCategory = (params.get("category") || "") as TagCategory | "";
  const [input, setInput] = useState(urlQuery);
  const [items, setItems] = useState<TagSearchItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiClientError | null>(null);
  const [runId, setRunId] = useState(0);

  useEffect(() => setInput(urlQuery), [urlQuery]);
  useEffect(() => {
    if (!urlQuery.trim()) {
      setItems([]);
      setError(null);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setLoading(true);
      setError(null);
      const query = new URLSearchParams({q: urlQuery, limit: "60"});
      if (urlCategory) query.append("category", urlCategory);
      try {
        const response = await apiRequest<SearchResponse>(`/api/v3/tags/search?${query}`, {signal: controller.signal});
        setItems(response.items);
      } catch (caught) {
        if (!controller.signal.aborted) setError(caught as ApiClientError);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }, 180);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [urlQuery, urlCategory, runId]);

  const resultLabel = useMemo(() => {
    if (!urlQuery) return "本地标签索引";
    return loading ? "正在检索…" : `${items.length} 个匹配结果`;
  }, [items.length, loading, urlQuery]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const next = new URLSearchParams(params);
    if (input.trim()) next.set("q", input.trim()); else next.delete("q");
    setParams(next);
  }

  function selectCategory(category: TagCategory | "") {
    const next = new URLSearchParams(params);
    if (category) next.set("category", category); else next.delete("category");
    setParams(next);
  }

  return (
    <div className="page tag-search-page">
      <header className="page-header">
        <div><span className="eyebrow">REFERENCE LIBRARY</span><h1>标签浏览器</h1><p>搜索本地 Danbooru 标签、中文名与有效别名。</p></div>
        <div className="header-stat"><strong>52K+</strong><span>离线标签</span></div>
      </header>
      <section className="search-console">
        <form className="search-box" onSubmit={submit} role="search">
          <span className="search-icon" aria-hidden="true">⌕</span>
          <input value={input} onChange={(event) => setInput(event.target.value)} placeholder="输入 maid、女仆、角色名或别名…" aria-label="搜索标签" autoFocus />
          {input && <button type="button" className="clear-button" onClick={() => setInput("")} aria-label="清空">×</button>}
          <button className="button button--primary" type="submit">搜索</button>
        </form>
        <div className="filter-row">
          <div className="category-tabs" aria-label="标签分类">
            {categories.map((category) => <button key={category.value || "all"} className={urlCategory === category.value ? "is-active" : ""} onClick={() => selectCategory(category.value)}>{category.label}</button>)}
          </div>
          <span className="result-count">{resultLabel}</span>
        </div>
      </section>
      <section className="results-region" aria-live="polite">
        {!urlQuery && <EmptyState title="从一个视觉概念开始" detail="搜索结果完全来自本地 reference.db；断网时仍然可用。" />}
        {urlQuery && loading && items.length === 0 && <LoadingState label="正在查询 FTS 索引…" />}
        {error && <ErrorState message={error.message} requestId={error.requestId} onRetry={() => setRunId((value) => value + 1)} />}
        {!loading && !error && urlQuery && items.length === 0 && <EmptyState title="没有找到匹配标签" detail="试试英文 canonical 名、中文简称，或者移除分类筛选。" />}
        {items.length > 0 && <div className="tag-grid">{items.map((item) => <TagCard key={item.id} item={item} />)}</div>}
      </section>
    </div>
  );
}

function TagCard({item}: {item: TagSearchItem}) {
  return (
    <Link className="tag-card" to={`/tags/${encodeURIComponent(item.name)}`}>
      <div className="tag-card-top"><TagBadge category={item.category} /><NsfwBadge value={item.nsfw} /></div>
      <div className="tag-card-name"><strong>{item.display_name}</strong><code>{item.name}</code></div>
      <div className="tag-card-bottom"><span>{item.cn_name || "暂无中文名"}</span><span>{formatCount(item.post_count)} posts</span></div>
      <span className="card-arrow" aria-hidden="true">↗</span>
    </Link>
  );
}

function formatCount(value: number) {
  return new Intl.NumberFormat("zh-CN", {notation: value >= 10_000 ? "compact" : "standard", maximumFractionDigits: 1}).format(value);
}
