import {useEffect, useRef, useState} from "react";
import {Link} from "react-router-dom";
import {apiRequest} from "../lib/api";
import type {ArtistRanking, ArtistSuggestion} from "../lib/types";

export const artistRankings: {id: ArtistRanking; label: string; detail: string}[] = [
  {id: "tag_fit", label: "题材贴合", detail: "按标签关联强度排序，专项作者会靠前。"},
  {id: "volume", label: "投稿量优先", detail: "筛选投稿量至少 400、场景共现至少 50 的画师，再按题材排序。"},
  {id: "balanced", label: "题材与投稿量均衡", detail: "综合题材与投稿量的名次排序。"},
];
const preferenceKey = "anima-workbench-artist-ranking";
const canonical = (name: string) => name.trim().replace(/^@/, "").toLowerCase().replace(/\s+/g, "_");
export function artistSeeds(text: string): string[] {
  return [...new Set(text.split(/[,，;；\n]+/).map(item => item.trim().replace(/^\((.+):[\d.]+\)$/, "$1"))
    .filter(item => item && !item.startsWith("@") && !item.startsWith("<lora:")).map(canonical))];
}
function savedRanking(): ArtistRanking | null {
  try {const value = localStorage.getItem(preferenceKey); return artistRankings.some(item => item.id === value) ? value as ArtistRanking : null;} catch {return null;}
}
type Props = {prompt: string; selected: string[]; disabled: boolean; onChange: (artists: string[]) => void};

export function ArtistRecommendations(props: Props) {
  const [open, setOpen] = useState(false);
  return <section className="conversation-artist-extension"><button aria-expanded={open} aria-controls="conversation-artist-panel" onClick={() => setOpen(value => !value)}>画师推荐（可选）</button>
    {open && <ArtistPanel {...props} />}</section>;
}
function ArtistPanel({prompt, selected, disabled, onChange}: Props) {
  const [input, setInput] = useState(() => artistSeeds(prompt).slice(0, 50).join(", "));
  const [sourcePrompt, setSourcePrompt] = useState(prompt);
  const [ranking, setRanking] = useState<ArtistRanking>(() => savedRanking() || "tag_fit");
  const [items, setItems] = useState<ArtistSuggestion[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const touched = useRef(false);
  const queried = useRef(false);
  const request = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    if (!savedRanking()) void apiRequest<{ranking: ArtistRanking}>("/api/v3/settings/artist-ranking", {signal: controller.signal})
      .then(value => {if (!controller.signal.aborted && !touched.current && artistRankings.some(item => item.id === value.ranking)) setRanking(value.ranking);}).catch(() => {});
    return () => {controller.abort(); request.current?.abort();};
  }, []);
  const tags = artistSeeds(input);
  const valid = tags.length > 0 && tags.length <= 50 && tags.every(tag => tag.length <= 200);
  function invalidate(value: string) {request.current?.abort(); setBusy(false); setItems(null); setError(""); setInput(value);}
  async function recommend(mode = ranking) {
    touched.current = true; queried.current = true;
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    setBusy(true); setError(""); setItems(null);
    try {
      const result = await apiRequest<{items: ArtistSuggestion[]}>("/api/v3/artists/recommend", {method: "POST", signal: controller.signal,
        body: JSON.stringify({tags, ranking: mode, limit: 12})});
      if (!controller.signal.aborted) setItems(result.items);
    } catch (caught) {if (!controller.signal.aborted) setError((caught as Error).message);}
    finally {if (!controller.signal.aborted) setBusy(false);}
  }
  function switchRanking(next: ArtistRanking) {
    touched.current = true; setRanking(next); setItems(null);
    try {localStorage.setItem(preferenceKey, next);} catch { /* Selection remains usable for this visit. */ }
    if (queried.current && valid) void recommend(next);
  }
  return <div id="conversation-artist-panel">
    <p className="conversation-muted">按本地标签共现数据推荐，不调用翻译模型或 LLM。排序反映题材关联，不是画质评分。</p>
    <label>推荐依据标签<textarea rows={2} value={input} maxLength={10000} onChange={event => invalidate(event.target.value)} placeholder="例如 watercolor (medium), scenery, flower；用逗号分隔" /></label>
    <div className="conversation-actions"><button onClick={() => {invalidate(artistSeeds(prompt).slice(0, 50).join(", ")); setSourcePrompt(prompt);}}>读取当前提示词标签</button><span>{tags.length} / 50 个标签</span></div>
    <p className="conversation-muted">只读取逗号或换行分隔的标签，最多 50 个；完整自然语言句子可能无法匹配，请手动调整。</p>
    {sourcePrompt !== prompt && <p className="conversation-warning">提示词已变化，推荐依据仍保留；可重新读取标签。</p>}
    <label>推荐模式<select value={ranking} onChange={event => switchRanking(event.target.value as ArtistRanking)}>{artistRankings.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
    <p className="conversation-muted">{artistRankings.find(item => item.id === ranking)?.detail} 切换模式不改变已选画师。</p>
    <button disabled={!valid || busy} onClick={() => void recommend()}>{busy ? "正在读取推荐…" : "刷新画师推荐"}</button>
    {!valid && <p>请填写 1～50 个标签，每个不超过 200 字。</p>}
    {error && <p role="alert">{error}</p>}
    {items && !items.length && <p role="status">没有匹配的画师。请使用数据包中已有的题材标签，或尝试其他推荐模式。</p>}
    <div className="conversation-artist-cards">{items?.map(item => {
      const added = selected.some(name => canonical(name) === canonical(item.name));
      return <article key={item.name}><Link to={`/artists/${encodeURIComponent(item.name)}`}>{item.render_name}</Link>
        <p>匹配：{item.sources.join("、")}</p><small>历史作品 {item.post_count.toLocaleString()} · 命中 {item.hit_count} 个标签</small>
        <button disabled={disabled || added || selected.length >= 32} onClick={() => onChange([...selected, item.name])}>{added ? "已加入" : "加入画面要求"}</button></article>;
    })}</div>
    <div aria-label="已选画师"><strong>已选画师 · {selected.length} / 32</strong>{selected.length ? selected.map((name, index) => <span key={`${name}-${index}`} className="conversation-artist-selected">@{name}<button aria-label={`移除画师 ${name}`} disabled={disabled} onClick={() => onChange(selected.filter((_, i) => i !== index))}>移除</button></span>) : <p>还没有选择画师。</p>}</div>
    <p className="conversation-muted">加入或移除只修改画面要求，更新提示词后才会用于生成。未保存输入和原有画师都会保留。</p>
  </div>;
}
