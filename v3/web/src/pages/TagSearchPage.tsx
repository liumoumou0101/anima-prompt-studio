import {FormEvent, useEffect, useMemo, useState} from "react";
import {ArrowRight, Check, Info, MagnifyingGlass, Plus, X} from "@phosphor-icons/react";
import {Link, useSearchParams} from "react-router-dom";
import {ApiClientError, apiRequest} from "../lib/api";
import type {SearchResponse, TagBrowseResponse, TagCategory, TagDetail, TagSearchItem} from "../lib/types";
import {tagDetailToSearchItem, useTagBasket} from "../lib/tagBasket";
import {NsfwBadge, TagBadge} from "../components/TagBadge";
import {TagBasket} from "../components/TagBasket";
import {EmptyState, ErrorState, LoadingState} from "../components/States";

const categories: Array<{value: TagCategory | ""; label: string}> = [
  {value: "", label: "全部"},
  {value: "general", label: "通用"},
  {value: "character", label: "角色"},
  {value: "copyright", label: "作品"},
  {value: "meta", label: "元信息"},
];

export function TagSearchPage() {
  const [params, setParams] = useSearchParams();
  const urlQuery = params.get("q") || "";
  const urlCategory = (params.get("category") || "") as TagCategory | "";
  const [input, setInput] = useState(urlQuery);
  const [items, setItems] = useState<TagSearchItem[]>([]);
  const [browse, setBrowse] = useState<TagBrowseResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [error, setError] = useState<ApiClientError | null>(null);
  const [runId, setRunId] = useState(0);
  const [includeNsfw, setIncludeNsfw] = useState(false);
  const basket = useTagBasket();
  const [preview, setPreview] = useState<TagDetail | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  useEffect(() => setInput(urlQuery), [urlQuery]);

  useEffect(() => {
    if (urlQuery.trim()) return;
    const controller = new AbortController();
    setBrowseLoading(true);
    setError(null);
    const query = new URLSearchParams({tags_per_group: "12", featured_limit: "24"});
    if (urlCategory) query.append("category", urlCategory);
    if (includeNsfw) query.set("include_nsfw", "true");
    apiRequest<TagBrowseResponse>(`/api/v3/tags/browse?${query}`, {signal: controller.signal})
      .then(setBrowse)
      .catch((caught) => { if (!controller.signal.aborted) setError(caught as ApiClientError); })
      .finally(() => { if (!controller.signal.aborted) setBrowseLoading(false); });
    return () => controller.abort();
  }, [urlQuery, urlCategory, includeNsfw, runId]);

  useEffect(() => {
    if (!urlQuery.trim()) {
      setItems([]);
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
        setItems(includeNsfw ? response.items : response.items.filter((item) => item.nsfw !== true));
      } catch (caught) {
        if (!controller.signal.aborted) setError(caught as ApiClientError);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }, 180);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [urlQuery, urlCategory, includeNsfw, runId]);

  const resultLabel = useMemo(() => {
    if (!urlQuery) return browseLoading ? "正在整理货架…" : `${browse?.groups.length || 0} 个主题货架`;
    return loading ? "正在检索…" : `${items.length} 个匹配结果`;
  }, [browse?.groups.length, browseLoading, items.length, loading, urlQuery]);

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

  async function openPreview(item: TagSearchItem) {
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      setPreview(await apiRequest<TagDetail>(`/api/v3/tags/${encodeURIComponent(item.name)}`));
    } catch (caught) {
      setPreview(null);
      setPreviewError((caught as ApiClientError).message);
    } finally {
      setPreviewLoading(false);
    }
  }

  const retry = () => setRunId((value) => value + 1);
  const showPreview = previewLoading || preview || previewError;

  return (
    <div className={`page tag-search-page${basket.selected.length ? " has-selection" : ""}`}>
      <header className="page-header tag-market-header">
        <div><span className="eyebrow">REFERENCE MARKET</span><h1>标签超市</h1><p>按主题逛本地 Danbooru 标签，预览含义后把需要的标签一起带走。</p></div>
        <div className="header-stat"><strong>{basket.selected.length || "—"}</strong><span>已挑选标签</span></div>
      </header>

      <section className="search-console">
        <form className="search-box" onSubmit={submit} role="search">
          <MagnifyingGlass className="search-icon" aria-hidden="true" />
          <input value={input} onChange={(event) => setInput(event.target.value)} placeholder="搜索 maid、女仆、构图、角色名或别名…" aria-label="搜索标签" />
          {input && <button type="button" className="clear-button" onClick={() => { setInput(""); const next = new URLSearchParams(params); next.delete("q"); setParams(next); }} aria-label="清空搜索"><X /></button>}
          <button className="button button--primary" type="submit">搜索</button>
        </form>
        <div className="filter-row">
          <div className="category-tabs" aria-label="标签分类">
            {categories.map((category) => <button type="button" key={category.value || "all"} className={urlCategory === category.value ? "is-active" : ""} onClick={() => selectCategory(category.value)}>{category.label}</button>)}
          </div>
          <div className="tag-filter-meta">
            <label className="safety-filter"><input type="checkbox" checked={includeNsfw} onChange={(event) => setIncludeNsfw(event.target.checked)} />含成人标签</label>
            <span className="result-count">{resultLabel}</span>
          </div>
        </div>
      </section>

      <section className="results-region" aria-live="polite">
        {error && <ErrorState message={error.message} requestId={error.requestId} onRetry={retry} />}
        {!error && !urlQuery && browseLoading && !browse && <LoadingState label="正在从本地数据包整理主题货架…" />}
        {!error && !urlQuery && browse && <BrowseMarket browse={browse} selected={basket.selectedNames} onToggle={basket.toggle} onPreview={openPreview} />}
        {urlQuery && loading && items.length === 0 && <LoadingState label="正在查询 FTS 索引…" />}
        {!loading && !error && urlQuery && items.length === 0 && <EmptyState title="没有找到匹配标签" detail="试试英文 canonical 名、中文简称，或者移除分类筛选。" />}
        {urlQuery && items.length > 0 && <div className="tag-grid">{items.map((item) => <TagCard key={item.id} item={item} selected={basket.selectedNames.has(item.name)} onToggle={basket.toggle} onPreview={openPreview} />)}</div>}
      </section>

      {showPreview && <TagPreviewPanel detail={preview} loading={previewLoading} error={previewError} selected={preview ? basket.selectedNames.has(preview.name) : false} onClose={() => { setPreview(null); setPreviewError(null); }} onToggle={() => preview && basket.toggle(tagDetailToSearchItem(preview))} />}
      <TagBasket selected={basket.selected} onToggle={basket.toggle} onClear={basket.clear} />
    </div>
  );
}

function BrowseMarket({browse, selected, onToggle, onPreview}: {browse: TagBrowseResponse; selected: Set<string>; onToggle: (item: TagSearchItem) => void; onPreview: (item: TagSearchItem) => void}) {
  const [groupQuery, setGroupQuery] = useState("");
  const [groupSort, setGroupSort] = useState<"count" | "name">("count");
  const otherGroups = useMemo(() => {
    const query = groupQuery.trim().toLocaleLowerCase();
    const filtered = browse.other_groups.filter((group) => !query
      || group.name.toLocaleLowerCase().includes(query)
      || (group.cn_name || "").toLocaleLowerCase().includes(query));
    return [...filtered].sort((left, right) => groupSort === "name"
      ? (left.cn_name || left.name).localeCompare(right.cn_name || right.name, "zh-CN")
      : right.tag_count - left.tag_count || left.name.localeCompare(right.name));
  }, [browse.other_groups, groupQuery, groupSort]);

  return <div className="tag-market">
    <section className="featured-shelf">
      <header><div><span>POPULAR PICKS</span><h2>高频标签</h2><p>从数据包中按使用量排序，适合快速建立画面的基础骨架。</p></div><strong>{browse.featured.length}</strong></header>
      <div className="market-tag-grid">{browse.featured.map((item) => <MarketTag key={item.id} item={item} selected={selected.has(item.name)} onToggle={onToggle} onPreview={onPreview} />)}</div>
    </section>

    <nav className="shelf-index" aria-label="主题货架快速导航">
      <span>快速到达</span>
      {browse.groups.map((group) => <a key={group.id} href={`#shelf-${group.name}`}>{group.title}</a>)}
    </nav>

    <div className="market-shelves">{browse.groups.map((group, index) => <section className="market-shelf" id={`shelf-${group.name}`} key={group.id}>
      <header><span className="shelf-number">{String(index + 1).padStart(2, "0")}</span><div><h2>{group.title}</h2><p>{group.description}</p></div><Link className="shelf-open-link" to={`/tags/groups/${encodeURIComponent(group.name)}`}><strong>{formatCount(group.tag_count)}<small> TAGS</small></strong><span>查看全部 <ArrowRight /></span></Link></header>
      <div className="market-tag-grid">{group.items.map((item) => <MarketTag key={item.id} item={item} selected={selected.has(item.name)} onToggle={onToggle} onPreview={onPreview} />)}</div>
    </section>)}</div>

    {browse.other_groups.length > 0 && <section className="group-directory" id="more-groups">
      <header className="group-directory-header">
        <div><span>GROUP DIRECTORY</span><h2>更多标签分组</h2><p>这些标签已有可靠分组，但不属于首页的 18 个核心货架。选择分组后继续浏览完整标签。</p></div>
        <strong>{browse.other_groups.length}<small> GROUPS</small></strong>
      </header>
      <div className="group-directory-toolbar">
        <label className="group-directory-search"><MagnifyingGlass aria-hidden="true" /><input value={groupQuery} onChange={(event) => setGroupQuery(event.target.value)} placeholder="筛选分组名称…" aria-label="筛选更多标签分组" /></label>
        <label className="group-directory-sort"><span>排序</span><select value={groupSort} onChange={(event) => setGroupSort(event.target.value as "count" | "name")} aria-label="更多标签分组排序"><option value="count">标签数量</option><option value="name">分组名称</option></select></label>
      </div>
      <div className="group-directory-meta"><span>显示 {otherGroups.length} / {browse.other_groups.length} 个分组</span><span>点击进入完整分组</span></div>
      {otherGroups.length > 0 ? <nav className="group-directory-grid" aria-label="更多标签分组">
        {otherGroups.map((group) => <Link key={group.id} className="group-directory-item" to={`/tags/groups/${encodeURIComponent(group.name)}`}>
          <span><strong>{group.cn_name || humanizeGroupName(group.name)}</strong><code>{humanizeGroupName(group.name)}</code></span>
          <span className="group-directory-count"><strong>{formatCount(group.tag_count)}</strong><small>TAGS</small><ArrowRight /></span>
        </Link>)}
      </nav> : <div className="group-directory-empty">没有匹配的标签分组，试试更短的关键词。</div>}
    </section>}

    <section className="ungrouped-showcase">
      <header>
        <div><span>LONG TAIL LIBRARY</span><h2>独立标签库</h2><p>浏览尚未进入主题分组的标签。默认优先显示未标记敏感的高热标签，也可以单独查看敏感标签。</p></div>
        <div className="ungrouped-showcase-total"><strong>{formatCount(browse.ungrouped.total)}</strong><span>未归组标签</span></div>
      </header>
      <div className="ungrouped-showcase-meta"><span>{formatCount(browse.ungrouped.safe_count)} 未标记敏感</span><span>{formatCount(browse.ungrouped.nsfw_count)} 已标记敏感</span><Link to="/tags/ungrouped">浏览完整标签库 <ArrowRight /></Link></div>
      <div className="market-tag-grid">{browse.ungrouped.items.map((item) => <MarketTag key={item.id} item={item} selected={selected.has(item.name)} onToggle={onToggle} onPreview={onPreview} />)}</div>
    </section>
  </div>;
}

function MarketTag({item, selected, onToggle, onPreview}: {item: TagSearchItem; selected: boolean; onToggle: (item: TagSearchItem) => void; onPreview: (item: TagSearchItem) => void}) {
  return <div className={`market-tag${selected ? " is-selected" : ""}`}>
    <button type="button" className="market-tag-preview" onClick={() => onPreview(item)} aria-label={`预览 ${item.cn_name || item.display_name}`}>
      <span><strong>{item.cn_name || item.display_name}</strong><code>{item.name}</code></span><small>{formatCount(item.post_count)}</small>
    </button>
    <button type="button" className="market-tag-select" onClick={() => onToggle(item)} aria-label={`${selected ? "移除" : "选择"} ${item.cn_name || item.display_name}`} aria-pressed={selected}>{selected ? <Check /> : <Plus />}</button>
  </div>;
}

function TagCard({item, selected, onToggle, onPreview}: {item: TagSearchItem; selected: boolean; onToggle: (item: TagSearchItem) => void; onPreview: (item: TagSearchItem) => void}) {
  return <article className={`tag-card${selected ? " is-selected" : ""}`}>
    <div className="tag-card-top"><TagBadge category={item.category} /><NsfwBadge value={item.nsfw} /></div>
    <button type="button" className="tag-card-name" onClick={() => onPreview(item)}><strong>{item.display_name}</strong><code>{item.name}</code></button>
    <div className="tag-card-bottom"><span>{item.cn_name || "暂无中文名"}</span><span>{formatCount(item.post_count)} posts</span></div>
    <div className="tag-card-actions"><Link to={`/tags/${encodeURIComponent(item.name)}`} aria-label={`查看 ${item.name} 完整详情`}><Info /></Link><button type="button" onClick={() => onToggle(item)} aria-label={`${selected ? "移除" : "选择"} ${item.name}`} aria-pressed={selected}>{selected ? <Check /> : <Plus />}</button></div>
  </article>;
}

function TagPreviewPanel({detail, loading, error, selected, onClose, onToggle}: {detail: TagDetail | null; loading: boolean; error: string | null; selected: boolean; onClose: () => void; onToggle: () => void}) {
  return <><button type="button" className="tag-preview-scrim" aria-label="关闭标签预览" onClick={onClose} /><aside className="tag-preview-panel" aria-label="标签快速预览">
    <header><span>QUICK PREVIEW</span><button type="button" onClick={onClose} aria-label="关闭"><X /></button></header>
    {loading && <LoadingState label="正在读取本地标签详情…" />}
    {error && <p className="preview-error">{error}</p>}
    {!loading && detail && <>
      <div className="preview-heading"><div><TagBadge category={detail.category_name} /><NsfwBadge value={detail.nsfw} /></div><h2>{detail.cn_name || detail.display_name}</h2><code>{detail.name}</code><strong>{formatCount(detail.post_count)} posts</strong></div>
      <div className="preview-copy"><span>标签说明</span><p>{detail.wiki_summary || "本地数据包暂时没有这个标签的说明。"}</p></div>
      {detail.groups.length > 0 && <div className="preview-groups"><span>所属分组</span><div>{detail.groups.map((group) => <em key={group.id}>{group.cn_name || group.name.replaceAll("_", " ")}</em>)}</div></div>}
      {detail.related.length > 0 && <div className="preview-related"><span>经常一起出现</span><div>{detail.related.slice(0, 8).map((item) => <code key={item.id}>{item.cn_name || item.render_name}</code>)}</div></div>}
      <div className="preview-actions"><Link to={`/tags/${encodeURIComponent(detail.name)}`}>查看完整详情</Link><button type="button" className={selected ? "is-selected" : ""} onClick={onToggle}>{selected ? <><Check />已挑选</> : <><Plus />加入标签篮</>}</button></div>
    </>}
  </aside></>;
}

function formatCount(value: number) {
  return new Intl.NumberFormat("zh-CN", {notation: value >= 10_000 ? "compact" : "standard", maximumFractionDigits: 1}).format(value);
}

function humanizeGroupName(value: string) {
  return value.replaceAll("_", " ");
}
