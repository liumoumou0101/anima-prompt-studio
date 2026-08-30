import {FormEvent, useEffect, useState} from "react";
import {ArrowRight, MagnifyingGlass} from "@phosphor-icons/react";
import {Link, useSearchParams} from "react-router-dom";
import {ApiClientError, apiRequest} from "../lib/api";
import type {ArtistSearchItem, ArtistSearchResponse} from "../lib/types";
import {EmptyState, ErrorState, LoadingState} from "../components/States";

export function ArtistSearchPage() {
  const [params, setParams] = useSearchParams();
  const query = params.get("q") || "";
  const sort = params.get("sort") === "name" ? "name" : "popularity";
  const [input, setInput] = useState(query);
  const [data, setData] = useState<ArtistSearchResponse | null>(null);
  const [items, setItems] = useState<ArtistSearchItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<ApiClientError | null>(null);
  const [runId, setRunId] = useState(0);

  useEffect(() => setInput(query), [query]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setData(null);
    setItems([]);
    requestArtists(0, controller.signal)
      .then((payload) => { setData(payload); setItems(payload.items); })
      .catch((caught) => { if (!controller.signal.aborted) setError(caught as ApiClientError); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [query, sort, runId]);

  function requestArtists(offset: number, signal?: AbortSignal) {
    const request = new URLSearchParams({limit: "48", offset: String(offset), sort});
    if (query) request.set("q", query);
    return apiRequest<ArtistSearchResponse>(`/api/v3/artists/search?${request}`, {signal});
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
      const payload = await requestArtists(items.length);
      setData(payload);
      setItems((current) => [...current, ...payload.items]);
    } catch (caught) {
      setError(caught as ApiClientError);
    } finally {
      setLoadingMore(false);
    }
  }

  function changeSort(value: string) {
    const next = new URLSearchParams(params);
    if (value === "popularity") next.delete("sort"); else next.set("sort", value);
    setParams(next);
  }

  if (error && !data) return <div className="page"><ErrorState message={error.message} requestId={error.requestId} onRetry={() => setRunId((value) => value + 1)} /></div>;

  return <div className="page artist-search-page">
    {loading && !data ? <LoadingState label="正在读取画师关联数据…" /> : data && <>
      <header className="artist-lab-hero">
        <div><span className="eyebrow">ARTIST CONTEXT LAB</span><h1>画师研究室</h1><p>从画师 tag 出发，查看历史作品中更有代表性的题材与场景线索。</p></div>
        <dl aria-label="画师数据概览">
          <div><dt>画师</dt><dd>{formatCount(data.summary.artist_count)}</dd></div>
          <div><dt>关联证据</dt><dd>{formatCount(data.summary.association_count)}</dd></div>
          <div><dt>当前匹配</dt><dd>{formatCount(data.total)}</dd></div>
        </dl>
      </header>

      <section className="artist-search-console">
        <div><span className="console-index">01</span><div><strong>输入画师 tag</strong><small>支持 `@name`、canonical 下划线名或空格形式</small></div></div>
        <form role="search" onSubmit={submit}><MagnifyingGlass /><input aria-label="搜索画师标签" value={input} onChange={(event) => setInput(event.target.value)} placeholder="例如 @dairi、rurudo…" autoFocus /><button type="submit">分析</button></form>
        <label>排列方式<select aria-label="画师排序" value={sort} onChange={(event) => changeSort(event.target.value)}><option value="popularity">作品量优先</option><option value="name">名称顺序</option></select></label>
      </section>

      <div className="artist-result-meta"><strong>{query ? `“${query}”的匹配结果` : "可研究的画师标签"}</strong><span>共 {formatCount(data.total)} 位 · 共现是题材线索，不是画质评分</span></div>
      {items.length ? <section className="artist-card-grid" aria-live="polite">{items.map((artist) => <ArtistCard key={artist.id} artist={artist} />)}</section> : <EmptyState title="没有找到这个画师 tag" detail="请尝试去掉 @、改用 canonical 名称，或缩短关键词。" />}
      {data.has_more && <button type="button" className="group-load-more" disabled={loadingMore} onClick={() => void loadMore()}>{loadingMore ? "正在读取下一批…" : `继续浏览剩余 ${data.total - items.length} 位画师`}</button>}
      {error && <div className="group-inline-error">{error.message}<button type="button" onClick={() => void loadMore()}>重试</button></div>}
    </>}
  </div>;
}

function ArtistCard({artist}: {artist: ArtistSearchItem}) {
  return <article className="artist-card">
    <div className="artist-card-monogram">{artist.name.slice(0, 2).toUpperCase()}</div>
    <div className="artist-card-copy"><span>ARTIST TAG</span><h2>{artist.render_name}</h2><code>{artist.name}</code></div>
    <dl><div><dt>历史作品</dt><dd>{formatCount(artist.post_count)}</dd></div><div><dt>关联线索</dt><dd>{artist.association_count}</dd></div></dl>
    <div className="artist-preview-tags" aria-label="代表性关联标签">{artist.preview_tags.length ? artist.preview_tags.map((tag) => <span key={tag.name}>{tag.cn_name || tag.render_name}</span>) : <small>暂无非敏感关联标签</small>}</div>
    <Link to={`/artists/${encodeURIComponent(artist.name)}`}>查看适用场景 <ArrowRight /></Link>
  </article>;
}

function formatCount(value: number) {
  return new Intl.NumberFormat("zh-CN", {notation: value >= 10_000 ? "compact" : "standard", maximumFractionDigits: 1}).format(value);
}
