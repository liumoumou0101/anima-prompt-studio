import {useEffect, useState} from "react";
import {Check, Plus} from "@phosphor-icons/react";
import {Link, useParams, useSearchParams} from "react-router-dom";
import {ApiClientError, apiRequest} from "../lib/api";
import {tagDetailToSearchItem, useTagBasket} from "../lib/tagBasket";
import type {TagDetail} from "../lib/types";
import {TagBasket} from "../components/TagBasket";
import {NsfwBadge, TagBadge} from "../components/TagBadge";
import {ErrorState, LoadingState} from "../components/States";

export function TagDetailPage() {
  const {name = ""} = useParams();
  const [searchParams] = useSearchParams();
  const sourceGroup = searchParams.get("group") || "";
  const sourceUngrouped = searchParams.get("source") === "ungrouped";
  const sourceArtist = searchParams.get("source") === "artist" ? searchParams.get("artist") || "" : "";
  const backTarget = sourceGroup ? `/tags/groups/${encodeURIComponent(sourceGroup)}` : sourceUngrouped ? "/tags/ungrouped" : sourceArtist ? `/artists/${encodeURIComponent(sourceArtist)}` : "/tags";
  const backLabel = sourceGroup ? "返回完整分组" : sourceUngrouped ? "返回独立标签库" : sourceArtist ? "返回画师场景分析" : "返回标签超市";
  const relatedSuffix = sourceGroup ? `?group=${encodeURIComponent(sourceGroup)}` : sourceUngrouped ? "?source=ungrouped" : sourceArtist ? `?source=artist&artist=${encodeURIComponent(sourceArtist)}` : "";
  const basket = useTagBasket();
  const [detail, setDetail] = useState<TagDetail | null>(null);
  const [error, setError] = useState<ApiClientError | null>(null);
  const [runId, setRunId] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setDetail(null);
    setError(null);
    apiRequest<TagDetail>(`/api/v3/tags/${encodeURIComponent(name)}`, {signal: controller.signal})
      .then(setDetail)
      .catch((caught) => { if (!controller.signal.aborted) setError(caught as ApiClientError); });
    return () => controller.abort();
  }, [name, runId]);

  if (error) return <div className="page"><ErrorState message={error.message} requestId={error.requestId} onRetry={() => setRunId((value) => value + 1)} /></div>;
  if (!detail) return <div className="page"><LoadingState label="正在读取标签详情…" /></div>;

  return (
    <div className={`page detail-page${basket.selected.length ? " has-selection" : ""}`}>
      <Link className="back-link" to={backTarget}>← {backLabel}</Link>
      <header className="detail-hero">
        <div className="detail-title-block">
          <div className="detail-badges"><TagBadge category={detail.category_name} /><NsfwBadge value={detail.nsfw} />{detail.deprecated && <span className="safety-badge">Deprecated</span>}</div>
          <h1>{detail.display_name}</h1>
          <code>{detail.name}</code>
          <p className="detail-cn">{detail.cn_name || "暂无中文名称"}</p>
        </div>
        <div className="detail-action-column"><div className="detail-metric"><strong>{formatNumber(detail.post_count)}</strong><span>Danbooru posts</span><small>快照热度，不是画质分</small></div><button type="button" className={basket.selectedNames.has(detail.name) ? "detail-basket-button is-selected" : "detail-basket-button"} onClick={() => basket.toggle(tagDetailToSearchItem(detail))}>{basket.selectedNames.has(detail.name) ? <><Check />已加入标签篮</> : <><Plus />加入标签篮</>}</button></div>
      </header>
      <div className="detail-layout">
        <div className="detail-main">
          <section className="content-card wiki-card">
            <SectionTitle index="01" title="本地说明" />
            <p>{detail.wiki_summary || "当前数据包没有这条标签的本地说明。"}</p>
          </section>
          <section className="content-card">
            <SectionTitle index="02" title="相关标签" subtitle={`${detail.related.length} 个高置信关系`} />
            {detail.related.length ? <div className="related-list">{detail.related.map((tag) => (
              <Link key={tag.id} className="related-item" to={`/tags/${encodeURIComponent(tag.name)}${relatedSuffix}`}>
                <div><strong>{tag.render_name}</strong><span>{tag.cn_name || tag.name}</span></div>
                <div className="relation-score"><span style={{"--score": tag.display_score} as React.CSSProperties} /><small>{Math.round(tag.display_score * 100)}%</small></div>
              </Link>
            ))}</div> : <p className="muted">当前数据包没有足够稳定的相关标签。</p>}
          </section>
        </div>
        <aside className="detail-aside">
          <section className="content-card compact-card">
            <SectionTitle index="A" title="别名" />
            <div className="token-cloud">{detail.aliases.length ? detail.aliases.map((alias) => <code key={alias}>{alias}</code>) : <span className="muted">无有效别名</span>}</div>
          </section>
          <section className="content-card compact-card">
            <SectionTitle index="B" title="中文检索词" />
            <div className="token-cloud">{[detail.cn_name, ...detail.cn_terms].filter(Boolean).map((term) => <span key={term!}>{term}</span>)}</div>
          </section>
          <section className="content-card compact-card">
            <SectionTitle index="C" title="标签组" />
            <div className="group-list">{detail.groups.length ? detail.groups.map((group) => <Link key={group.id} to={`/tags/groups/${encodeURIComponent(group.name)}`}><strong>{group.cn_name || group.name}</strong><code>{group.name}</code></Link>) : <span className="muted">未加入标签组</span>}</div>
          </section>
          <section className="preview-placeholder">
            <span>PREVIEW OFFLINE</span><strong>在线图片预览尚未启用</strong><p>本地标签、说明与推荐不受影响。</p>
          </section>
        </aside>
      </div>
      <TagBasket selected={basket.selected} onToggle={basket.toggle} onClear={basket.clear} />
    </div>
  );
}

function SectionTitle({index, title, subtitle}: {index: string; title: string; subtitle?: string}) {
  return <div className="section-title"><span>{index}</span><div><h2>{title}</h2>{subtitle && <small>{subtitle}</small>}</div></div>;
}

function formatNumber(value: number) { return new Intl.NumberFormat("zh-CN").format(value); }
