import {FormEvent, useEffect, useState} from "react";
import {ArrowLeft, Check, MagnifyingGlass, Plus} from "@phosphor-icons/react";
import {Link, useSearchParams} from "react-router-dom";
import {ApiClientError, apiRequest} from "../lib/api";
import {useTagBasket} from "../lib/tagBasket";
import type {TagCategory, TagSearchItem, TagUngroupedResponse} from "../lib/types";
import {TagBasket} from "../components/TagBasket";
import {NsfwBadge, TagBadge} from "../components/TagBadge";
import {EmptyState, ErrorState, LoadingState} from "../components/States";

type SafetyMode = "safe" | "nsfw" | "all";
type HeatTier = "all" | "100k" | "10k" | "1k" | "longtail";

const categories: Array<{value: TagCategory | "all"; label: string}> = [
  {value: "general", label: "通用推荐"},
  {value: "character", label: "角色"},
  {value: "copyright", label: "作品"},
  {value: "all", label: "全部"},
];

const heatTiers: Array<{value: HeatTier; label: string}> = [
  {value: "all", label: "全部热度"},
  {value: "100k", label: "10万+"},
  {value: "10k", label: "1万–10万"},
  {value: "1k", label: "1千–1万"},
  {value: "longtail", label: "1千以下"},
];

const safetyModes: Array<{value: SafetyMode; label: string; detail: string}> = [
  {value: "safe", label: "未标记敏感", detail: "只显示明确标记为非敏感的标签"},
  {value: "nsfw", label: "仅显示敏感", detail: "只显示已标记 NSFW 的标签"},
  {value: "all", label: "全部", detail: "同时显示两类标签"},
];

export function TagUngroupedPage() {
  const [params, setParams] = useSearchParams();
  const query = params.get("q") || "";
  const rawCategory = params.get("category") || "general";
  const category = (["general", "character", "copyright", "all"].includes(rawCategory) ? rawCategory : "general") as TagCategory | "all";
  const rawSafety = params.get("safety") || "safe";
  const safety = (["safe", "nsfw", "all"].includes(rawSafety) ? rawSafety : "safe") as SafetyMode;
  const rawHeat = params.get("heat") || "all";
  const heat = (["all", "100k", "10k", "1k", "longtail"].includes(rawHeat) ? rawHeat : "all") as HeatTier;
  const sort = params.get("sort") === "name" ? "name" : "popularity";
  const [input, setInput] = useState(query);
  const [data, setData] = useState<TagUngroupedResponse | null>(null);
  const [items, setItems] = useState<TagSearchItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<ApiClientError | null>(null);
  const [runId, setRunId] = useState(0);
  const basket = useTagBasket();

  useEffect(() => setInput(query), [query]);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setItems([]);
    setLoading(true);
    setError(null);
    requestTags(0, controller.signal)
      .then((payload) => { setData(payload); setItems(payload.items); })
      .catch((caught) => { if (!controller.signal.aborted) setError(caught as ApiClientError); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [query, category, safety, heat, sort, runId]);

  function requestTags(offset: number, signal?: AbortSignal) {
    const request = new URLSearchParams({limit: "80", offset: String(offset), safety, heat, sort});
    if (query) request.set("q", query);
    if (category !== "all") request.set("category", category);
    return apiRequest<TagUngroupedResponse>(`/api/v3/tags/ungrouped?${request}`, {signal});
  }

  function updateParam(name: string, value: string, defaultValue: string) {
    const next = new URLSearchParams(params);
    if (value === defaultValue) next.delete(name); else next.set(name, value);
    setParams(next);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const next = new URLSearchParams(params);
    if (input.trim()) next.set("q", input.trim()); else next.delete("q");
    setParams(next);
  }

  async function loadMore() {
    setLoadingMore(true);
    setError(null);
    try {
      const payload = await requestTags(items.length);
      setData(payload);
      setItems((current) => [...current, ...payload.items]);
    } catch (caught) {
      setError(caught as ApiClientError);
    } finally {
      setLoadingMore(false);
    }
  }

  if (error && !data) return <div className="page"><ErrorState message={error.message} requestId={error.requestId} onRetry={() => setRunId((value) => value + 1)} /></div>;

  return <div className={`page tag-ungrouped-page${basket.selected.length ? " has-selection" : ""}`}>
    <nav className="tag-breadcrumb" aria-label="面包屑"><Link to="/tags"><ArrowLeft />标签超市</Link><span>/</span><strong>独立标签库</strong></nav>
    {loading && !data ? <LoadingState label="正在读取独立标签库…" /> : data && <>
      <header className="ungrouped-hero">
        <div><span className="eyebrow">LONG TAIL LIBRARY</span><h1>独立标签库</h1><p>这些标签尚未进入主题分组；热度用于发现，不代表画质或提示词效果。</p></div>
        <div className="group-total"><strong>{formatCount(data.total)}</strong><span>当前匹配标签</span><small>从 {formatCount(data.summary.total)} 个独立标签中筛选</small></div>
      </header>

      <section className="ungrouped-summary" aria-label="独立标签统计">
        <div><span>未标记敏感</span><strong>{formatCount(data.summary.safe_count)}</strong></div>
        <div className="is-sensitive"><span>已标记敏感</span><strong>{formatCount(data.summary.nsfw_count)}</strong></div>
        <div><span>角色 / 作品</span><strong>{formatCount((data.summary.category_counts.character || 0) + (data.summary.category_counts.copyright || 0))}</strong></div>
      </section>

      <section className="group-browser-toolbar ungrouped-browser-toolbar">
        <form className="group-search" role="search" onSubmit={submit}><MagnifyingGlass /><input aria-label="独立标签库搜索" value={input} onChange={(event) => setInput(event.target.value)} placeholder="搜索 canonical、中文名或有效别名…" /><button type="submit">搜索</button></form>
        <div className="group-sort"><label>排序<select aria-label="独立标签排序" value={sort} onChange={(event) => updateParam("sort", event.target.value, "popularity")}><option value="popularity">按热度</option><option value="name">按名称</option></select></label></div>
        <div className="ungrouped-filter-block"><span>标签类型</span><div className="category-tabs" aria-label="未分组标签分类">{categories.map((item) => <button type="button" key={item.value} className={category === item.value ? "is-active" : ""} onClick={() => updateParam("category", item.value, "general")}>{item.label}</button>)}</div></div>
        <div className="ungrouped-filter-block"><span>热度区间</span><div className="ungrouped-heat-tabs" aria-label="标签热度区间">{heatTiers.map((item) => <button type="button" key={item.value} className={heat === item.value ? "is-active" : ""} onClick={() => updateParam("heat", item.value, "all")}>{item.label}</button>)}</div></div>
        <div className="ungrouped-filter-block safety-mode-block"><span>敏感内容</span><div className="safety-mode-tabs" role="group" aria-label="敏感内容显示方式">{safetyModes.map((item) => <button type="button" key={item.value} className={safety === item.value ? "is-active" : ""} aria-pressed={safety === item.value} title={item.detail} onClick={() => updateParam("safety", item.value, "safe")}>{item.label}</button>)}</div><small>{safetyModes.find((item) => item.value === safety)?.detail}</small></div>
      </section>

      <div className="group-list-meta"><span>已显示 {items.length} / {data.total}</span>{query && <button type="button" onClick={() => { setInput(""); updateParam("q", "", ""); }}>清除“{query}”</button>}</div>
      {items.length ? <section className="group-tag-grid" aria-live="polite">{items.map((item) => <UngroupedTag key={item.id} item={item} selected={basket.selectedNames.has(item.name)} onToggle={basket.toggle} />)}</section> : <EmptyState title={safety === "nsfw" ? "没有匹配的敏感标签" : "没有匹配的独立标签"} detail="尝试清除搜索词、切换标签类型、热度区间或敏感内容模式。" />}
      {data.has_more && <button type="button" className="group-load-more" disabled={loadingMore} onClick={() => void loadMore()}>{loadingMore ? "正在读取下一批…" : `继续浏览剩余 ${data.total - items.length} 个标签`}</button>}
      {error && <div className="group-inline-error">{error.message}<button type="button" onClick={() => void loadMore()}>重试</button></div>}
    </>}
    <TagBasket selected={basket.selected} onToggle={basket.toggle} onClear={basket.clear} />
  </div>;
}

function UngroupedTag({item, selected, onToggle}: {item: TagSearchItem; selected: boolean; onToggle: (item: TagSearchItem) => void}) {
  return <article className={`group-tag${selected ? " is-selected" : ""}`}>
    <Link to={`/tags/${encodeURIComponent(item.name)}?source=ungrouped`}>
      <div><TagBadge category={item.category} /><NsfwBadge value={item.nsfw} /></div>
      <strong>{item.cn_name || item.display_name}</strong><code>{item.name}</code><small>{formatCount(item.post_count)} posts</small>
    </Link>
    <button type="button" onClick={() => onToggle(item)} aria-label={`${selected ? "移除" : "选择"} ${item.cn_name || item.display_name}`} aria-pressed={selected}>{selected ? <Check /> : <Plus />}</button>
  </article>;
}

function formatCount(value: number) {
  return new Intl.NumberFormat("zh-CN", {notation: value >= 10_000 ? "compact" : "standard", maximumFractionDigits: 1}).format(value);
}
