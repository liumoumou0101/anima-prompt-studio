import {FormEvent, useEffect, useState} from "react";
import {ArrowLeft, Check, MagnifyingGlass, Plus} from "@phosphor-icons/react";
import {Link, useParams, useSearchParams} from "react-router-dom";
import {ApiClientError, apiRequest} from "../lib/api";
import {useTagBasket} from "../lib/tagBasket";
import type {TagCategory, TagGroupResponse, TagSearchItem} from "../lib/types";
import {TagBasket} from "../components/TagBasket";
import {NsfwBadge, TagBadge} from "../components/TagBadge";
import {EmptyState, ErrorState, LoadingState} from "../components/States";

const categories: Array<{value: TagCategory | ""; label: string}> = [
  {value: "", label: "全部"},
  {value: "general", label: "通用"},
  {value: "character", label: "角色"},
  {value: "copyright", label: "作品"},
  {value: "meta", label: "元信息"},
];

export function TagGroupPage() {
  const {groupName = ""} = useParams();
  const [params, setParams] = useSearchParams();
  const query = params.get("q") || "";
  const category = (params.get("category") || "") as TagCategory | "";
  const sort = params.get("sort") === "name" ? "name" : "popularity";
  const includeNsfw = params.get("nsfw") === "1";
  const hasCnName = params.get("cn") === "1";
  const [input, setInput] = useState(query);
  const [data, setData] = useState<TagGroupResponse | null>(null);
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
    requestGroup(0, controller.signal)
      .then((payload) => { setData(payload); setItems(payload.items); })
      .catch((caught) => { if (!controller.signal.aborted) setError(caught as ApiClientError); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [groupName, query, category, sort, includeNsfw, hasCnName, runId]);

  function requestGroup(offset: number, signal?: AbortSignal) {
    const request = new URLSearchParams({limit: "80", offset: String(offset), sort});
    if (query) request.set("q", query);
    if (category) request.set("category", category);
    if (includeNsfw) request.set("include_nsfw", "true");
    if (hasCnName) request.set("has_cn_name", "true");
    return apiRequest<TagGroupResponse>(`/api/v3/tag-groups/${encodeURIComponent(groupName)}?${request}`, {signal});
  }

  function updateParam(name: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value); else next.delete(name);
    setParams(next);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    updateParam("q", input.trim());
  }

  async function loadMore() {
    setLoadingMore(true);
    setError(null);
    try {
      const payload = await requestGroup(items.length);
      setData(payload);
      setItems((current) => [...current, ...payload.items]);
    } catch (caught) {
      setError(caught as ApiClientError);
    } finally {
      setLoadingMore(false);
    }
  }

  if (error && !data) return <div className="page"><ErrorState message={error.message} requestId={error.requestId} onRetry={() => setRunId((value) => value + 1)} /></div>;

  return <div className={`page tag-group-page${basket.selected.length ? " has-selection" : ""}`}>
    <nav className="tag-breadcrumb" aria-label="面包屑"><Link to="/tags"><ArrowLeft />标签超市</Link><span>/</span><strong>{data?.group.title || "完整分组"}</strong></nav>
    {loading && !data ? <LoadingState label="正在读取完整标签分组…" /> : data && <>
      <header className="group-hero">
        <div><span className="eyebrow">COMPLETE SHELF</span><h1>{data.group.title}</h1><p>{data.group.description}</p></div>
        <div className="group-total"><strong>{formatCount(data.total)}</strong><span>当前匹配标签</span><small>分组规模不做人工平衡</small></div>
      </header>

      <section className="group-browser-toolbar">
        <form className="group-search" role="search" onSubmit={submit}><MagnifyingGlass /><input aria-label="分组内搜索" value={input} onChange={(event) => setInput(event.target.value)} placeholder={`在“${data.group.title}”中搜索…`} /><button type="submit">搜索</button></form>
        <div className="group-sort"><label>排序<select aria-label="标签排序" value={sort} onChange={(event) => updateParam("sort", event.target.value === "name" ? "name" : "")}><option value="popularity">按热度</option><option value="name">按名称</option></select></label></div>
        <div className="group-filter-row">
          <div className="category-tabs" aria-label="标签分类">{categories.map((item) => <button type="button" key={item.value || "all"} className={category === item.value ? "is-active" : ""} onClick={() => updateParam("category", item.value)}>{item.label}</button>)}</div>
          <div><label className="safety-filter"><input type="checkbox" checked={hasCnName} onChange={(event) => updateParam("cn", event.target.checked ? "1" : "")} />只看有中文名</label><label className="safety-filter"><input type="checkbox" checked={includeNsfw} onChange={(event) => updateParam("nsfw", event.target.checked ? "1" : "")} />含成人标签</label></div>
        </div>
      </section>

      <div className="group-list-meta"><span>已显示 {items.length} / {data.total}</span>{query && <button type="button" onClick={() => { setInput(""); updateParam("q", ""); }}>清除“{query}”</button>}</div>
      {items.length ? <section className="group-tag-grid" aria-live="polite">{items.map((item) => <GroupTag key={item.id} item={item} groupName={data.group.name} selected={basket.selectedNames.has(item.name)} onToggle={basket.toggle} />)}</section> : <EmptyState title="这个分组中没有匹配标签" detail="尝试清除搜索词、中文名筛选或分类条件。" />}
      {data.has_more && <button type="button" className="group-load-more" disabled={loadingMore} onClick={() => void loadMore()}>{loadingMore ? "正在读取下一批…" : `继续浏览剩余 ${data.total - items.length} 个标签`}</button>}
      {error && <div className="group-inline-error">{error.message}<button type="button" onClick={() => void loadMore()}>重试</button></div>}
    </>}
    <TagBasket selected={basket.selected} onToggle={basket.toggle} onClear={basket.clear} />
  </div>;
}

function GroupTag({item, groupName, selected, onToggle}: {item: TagSearchItem; groupName: string; selected: boolean; onToggle: (item: TagSearchItem) => void}) {
  return <article className={`group-tag${selected ? " is-selected" : ""}`}>
    <Link to={`/tags/${encodeURIComponent(item.name)}?group=${encodeURIComponent(groupName)}`}>
      <div><TagBadge category={item.category} /><NsfwBadge value={item.nsfw} /></div>
      <strong>{item.cn_name || item.display_name}</strong><code>{item.name}</code><small>{formatCount(item.post_count)} posts</small>
    </Link>
    <button type="button" onClick={() => onToggle(item)} aria-label={`${selected ? "移除" : "选择"} ${item.cn_name || item.display_name}`} aria-pressed={selected}>{selected ? <Check /> : <Plus />}</button>
  </article>;
}

function formatCount(value: number) {
  return new Intl.NumberFormat("zh-CN", {notation: value >= 10_000 ? "compact" : "standard", maximumFractionDigits: 1}).format(value);
}
