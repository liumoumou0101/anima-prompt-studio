import {useEffect, useMemo, useState} from "react";
import {ArrowLeft, Check, Copy, MagnifyingGlass, Plus} from "@phosphor-icons/react";
import {Link, useParams} from "react-router-dom";
import {ApiClientError, apiRequest} from "../lib/api";
import {useTagBasket} from "../lib/tagBasket";
import type {ArtistContextDimension, ArtistContextTag, ArtistDetail, TagSearchItem} from "../lib/types";
import {TagBasket} from "../components/TagBasket";
import {NsfwBadge, TagBadge} from "../components/TagBadge";
import {EmptyState, ErrorState, LoadingState} from "../components/States";

type SafetyMode = "safe" | "nsfw" | "all";
type ContextSort = "association" | "coverage" | "popularity";

const dimensions: Array<{value: ArtistContextDimension | "all"; label: string; detail: string}> = [
  {value: "all", label: "全部线索", detail: "全部关联标签"},
  {value: "composition", label: "构图光影", detail: "构图、焦点、背景与光线"},
  {value: "setting", label: "场景环境", detail: "地点、环境与主题"},
  {value: "action", label: "动作姿态", detail: "姿势、手势与行为"},
  {value: "appearance", label: "外观服饰", detail: "服装、发型、配饰与颜色"},
  {value: "character", label: "角色", detail: "高关联角色"},
  {value: "copyright", label: "作品", detail: "高关联作品系列"},
  {value: "motif", label: "其他题材", detail: "尚未归入上述维度的题材"},
];

export function ArtistDetailPage() {
  const {name = ""} = useParams();
  const [data, setData] = useState<ArtistDetail | null>(null);
  const [error, setError] = useState<ApiClientError | null>(null);
  const [runId, setRunId] = useState(0);
  const [dimension, setDimension] = useState<ArtistContextDimension | "all">("all");
  const [safety, setSafety] = useState<SafetyMode>("safe");
  const [sort, setSort] = useState<ContextSort>("association");
  const [query, setQuery] = useState("");
  const [copied, setCopied] = useState(false);
  const basket = useTagBasket();

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError(null);
    apiRequest<ArtistDetail>(`/api/v3/artists/${encodeURIComponent(name)}`, {signal: controller.signal})
      .then(setData)
      .catch((caught) => { if (!controller.signal.aborted) setError(caught as ApiClientError); });
    return () => controller.abort();
  }, [name, runId]);

  const filtered = useMemo(() => {
    if (!data) return [];
    const normalized = query.trim().toLowerCase().replaceAll(" ", "_");
    const items = data.contexts.filter((item) => {
      if (safety === "safe" && item.nsfw !== false) return false;
      if (safety === "nsfw" && item.nsfw !== true) return false;
      if (dimension !== "all" && !item.dimensions.includes(dimension)) return false;
      if (normalized && !item.name.includes(normalized) && !(item.cn_name || "").toLowerCase().includes(normalized)) return false;
      return true;
    });
    return [...items].sort((left, right) => {
      if (sort === "coverage") return right.coverage - left.coverage || left.rank - right.rank;
      if (sort === "popularity") return right.post_count - left.post_count || left.rank - right.rank;
      return (right.association_score ?? -1) - (left.association_score ?? -1) || left.rank - right.rank;
    });
  }, [data, dimension, safety, sort, query]);

  async function copyArtist() {
    if (!data) return;
    await navigator.clipboard.writeText(data.render_name);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  if (error) return <div className="page"><ErrorState message={error.message} requestId={error.requestId} onRetry={() => setRunId((value) => value + 1)} /></div>;
  if (!data) return <div className="page"><LoadingState label="正在分析画师关联场景…" /></div>;

  const strongest = data.contexts.filter((item) => item.nsfw === false && item.category_name === "general").slice(0, 6);
  return <div className={`page artist-detail-page${basket.selected.length ? " has-selection" : ""}`}>
    <nav className="tag-breadcrumb" aria-label="面包屑"><Link to="/artists"><ArrowLeft />画师研究室</Link><span>/</span><strong>{data.render_name}</strong></nav>
    <header className="artist-profile-hero">
      <div className="artist-profile-mark">@</div>
      <div><span className="eyebrow">ARTIST CONTEXT PROFILE</span><h1>{data.render_name}</h1><code>{data.name}</code><p>{data.analysis_note}</p></div>
      <dl><div><dt>历史作品</dt><dd>{formatCount(data.post_count)}</dd></div><div><dt>关联线索</dt><dd>{data.association_count}</dd></div><div><dt>非敏感线索</dt><dd>{data.safety_summary.safe_count}</dd></div></dl>
      <button type="button" onClick={() => void copyArtist()}><Copy />{copied ? "已复制" : "复制画师 tag"}</button>
    </header>

    {strongest.length > 0 && <section className="artist-signature-strip" aria-label="优先测试线索"><header><div><span>START HERE</span><strong>优先测试的关联题材</strong></div><small>从高特征关联的非敏感通用标签开始</small></header><div>{strongest.map((item) => <button type="button" key={item.name} aria-pressed={basket.selectedNames.has(item.name)} onClick={() => basket.toggle(contextToSearchItem(item))}>{basket.selectedNames.has(item.name) ? <Check /> : <Plus />}<span>{item.cn_name || item.render_name}</span><small>{Math.round((item.association_score || 0) * 100)}%</small></button>)}</div></section>}

    <section className="artist-context-controls">
      <div className="artist-dimension-tabs" aria-label="关联场景维度">{dimensions.map((item) => <button type="button" key={item.value} className={dimension === item.value ? "is-active" : ""} title={item.detail} onClick={() => setDimension(item.value)}>{item.label}{item.value !== "all" && <small>{data.dimension_counts[item.value] || 0}</small>}</button>)}</div>
      <div className="artist-context-toolbar"><label><MagnifyingGlass /><input aria-label="筛选关联标签" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="筛选当前画师的关联标签…" /></label><label>敏感内容<select aria-label="关联标签敏感内容" value={safety} onChange={(event) => setSafety(event.target.value as SafetyMode)}><option value="safe">未标记敏感</option><option value="nsfw">仅显示敏感</option><option value="all">全部</option></select></label><label>排序<select aria-label="关联标签排序" value={sort} onChange={(event) => setSort(event.target.value as ContextSort)}><option value="association">特征关联</option><option value="coverage">作品覆盖</option><option value="popularity">标签热度</option></select></label></div>
      <p><strong>{filtered.length}</strong> 条可见线索 · “特征关联”衡量该画师与标签的相对共现，“作品覆盖”衡量标签在该画师历史作品中的出现比例。</p>
    </section>

    {filtered.length ? <section className="artist-context-grid" aria-label="关联场景列表" aria-live="polite">{filtered.map((item) => <ContextCard key={item.id} artist={data.name} item={item} selected={basket.selectedNames.has(item.name)} onToggle={() => basket.toggle(contextToSearchItem(item))} />)}</section> : <EmptyState title="当前筛选没有关联线索" detail="尝试切换维度、敏感内容状态或清除搜索词。" />}
    <TagBasket selected={basket.selected} onToggle={basket.toggle} onClear={basket.clear} />
  </div>;
}

function ContextCard({artist, item, selected, onToggle}: {artist: string; item: ArtistContextTag; selected: boolean; onToggle: () => void}) {
  const dimension = dimensions.find((entry) => entry.value === item.dimensions[0]);
  return <article className={`artist-context-card${selected ? " is-selected" : ""}`}>
    <Link to={`/tags/${encodeURIComponent(item.name)}?source=artist&artist=${encodeURIComponent(artist)}`}>
      <div className="context-card-label"><span>{dimension?.label || "关联题材"}</span><TagBadge category={item.category_name} /><NsfwBadge value={item.nsfw} /></div>
      <h2>{item.cn_name || item.render_name}</h2><code>{item.name}</code>
      <div className="context-score"><span style={{width: `${Math.max(2, Math.round((item.association_score || 0) * 100))}%`}} /></div>
      <dl><div><dt>特征关联</dt><dd>{item.association_score === null ? "—" : `${Math.round(item.association_score * 100)}%`}</dd></div><div><dt>作品覆盖</dt><dd>{formatPercent(item.coverage)}</dd></div><div><dt>历史共现</dt><dd>{formatCount(item.cooc_count)}</dd></div></dl>
    </Link>
    <button type="button" aria-label={`${selected ? "移除" : "选择"} ${item.cn_name || item.render_name}`} aria-pressed={selected} onClick={onToggle}>{selected ? <Check /> : <Plus />}</button>
  </article>;
}

function contextToSearchItem(item: ArtistContextTag): TagSearchItem {
  return {id: item.id, name: item.name, display_name: item.render_name, cn_name: item.cn_name, category: item.category_name, post_count: item.post_count, nsfw: item.nsfw, match: {kind: "artist_context", score: item.association_score}};
}

function formatCount(value: number) {
  return new Intl.NumberFormat("zh-CN", {notation: value >= 10_000 ? "compact" : "standard", maximumFractionDigits: 1}).format(value);
}

function formatPercent(value: number) {
  if (value > 0 && value < 0.001) return "<0.1%";
  return `${(value * 100).toFixed(value < 0.1 ? 1 : 0)}%`;
}
