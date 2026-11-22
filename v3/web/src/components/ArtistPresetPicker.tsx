import {useEffect, useRef, useState} from "react";
import {Link} from "react-router-dom";
import {apiRequest} from "../lib/api";
import type {ArtistPreset} from "../lib/artistPresets";
import type {ArtistPresetSnapshot} from "../lib/artistPresetApplication";
import "./artistPresetPicker.css";

const RECENT = "anima-artist-preset-recent";
function recentIds(): string[] {try {const value: unknown = JSON.parse(localStorage.getItem(RECENT) || "[]"); return Array.isArray(value) ? value.filter((id): id is string => typeof id === "string").slice(0, 12) : [];} catch {return [];}}
export function artistPresetSnapshot(preset: ArtistPreset): ArtistPresetSnapshot {
  const {id, revision, name, positive, negative, model_family, model_label, syntax, source_url, content_hash} = preset;
  return {id, revision, name, positive, negative, model_family, model_label, syntax, source_url, content_hash};
}
const families: Record<string,string> = {anima:"Anima",sdxl:"SDXL / Illustrious",novelai:"NovelAI",other:"其他模型",unknown:"模型未标注"};
export function ArtistPresetPicker({active, customized, model, disabled, onApply, onRemove, preferredId}: {
  active?: ArtistPresetSnapshot | null; customized?: string; model: string; disabled?: boolean;
  onApply: (snapshot: ArtistPresetSnapshot) => boolean | void; onRemove: () => void; preferredId?: string | null;
}) {
  const [open,setOpen] = useState(false), [items,setItems] = useState<ArtistPreset[]>([]), [error,setError] = useState("");
  const [loading,setLoading] = useState(false), [attempt,setAttempt] = useState(0), [query,setQuery] = useState("");
  const [family,setFamily] = useState("anima"), [favorites,setFavorites] = useState(false), [recent,setRecent] = useState(recentIds);
  const [selected,setSelected] = useState<string | null>(null);
  const search = useRef<HTMLInputElement>(null), root = useRef<HTMLElement>(null);
  useEffect(()=>{if(preferredId){setOpen(true);setFamily("");setSelected(preferredId);}},[preferredId]);
  useEffect(()=>{
    if(!open)return;
    // The library is an overlay; a click elsewhere returns to the prompt.
    const close=(event:PointerEvent)=>{if(root.current&&event.target instanceof Node&&!root.current.contains(event.target))setOpen(false);};
    document.addEventListener("pointerdown",close);
    return ()=>document.removeEventListener("pointerdown",close);
  },[open]);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController(); setLoading(true); setError("");
    apiRequest<{items:ArtistPreset[]}>("/api/v3/artist-presets", {signal:controller.signal})
      .then(result=>{if(!controller.signal.aborted)setItems(result.items);})
      .catch(caught=>{if(!controller.signal.aborted)setError((caught as Error).message);})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    search.current?.focus();
    return ()=>controller.abort();
  },[open,attempt]);
  const filtered = items.filter(item=>(!family||item.model_family===family)&&(!favorites||item.favorite)&&
    `${item.name}\n${item.positive}\n${item.model_label}`.toLowerCase().includes(query.toLowerCase()))
    .sort((a,b)=>{
      const rank=(item:ArtistPreset)=>recent.includes(item.id)?recent.indexOf(item.id):100;
      return rank(a)-rank(b)||Number(b.favorite)-Number(a.favorite)||a.name.localeCompare(b.name);
    });
  const chosen = filtered.find(item=>item.id===selected);
  const sample = chosen?.samples.find(item=>item.content_hash===chosen.content_hash) || chosen?.samples[0];
  const activeRecord = items.find(item=>item.id===active?.id);
  const activeSample = activeRecord?.samples.find(item=>item.content_hash===active?.content_hash);
  const mismatch = chosen && model.toLowerCase().startsWith("anima") && chosen.model_family!=="anima";
  function apply() {
    if (!chosen || disabled) return;
    if(onApply(artistPresetSnapshot(chosen))===false)return;
    const next=[chosen.id,...recent.filter(id=>id!==chosen.id)].slice(0,12); setRecent(next);
    try {localStorage.setItem(RECENT,JSON.stringify(next));} catch { /* Library stays available without browser storage. */ }
    setOpen(false);
  }
  return <section ref={root} className="artist-preset-picker" aria-label="画师串调用">
    <div className="artist-preset-picker__bar">
      {activeSample&&<img src={activeSample.image_url} alt="当前画师串的原提示词样品"/>}
      <div><strong>画师串</strong><span title={active?.name}>{active ? active.name : "未使用 · 选用后保留原始权重与顺序"}</span>
        {active&&<small>{families[active.model_family]} · {active.model_label||"具体版本未标注"} · 已固定此版本</small>}</div>
      <button type="button" aria-expanded={open} onClick={()=>setOpen(value=>!value)} disabled={disabled}>{open?"收起":active?"更换画师串":"选择画师串"}</button>
      {active&&<button type="button" disabled={disabled} onClick={onRemove}>移除画师串</button>}
    </div>
    {customized&&!active&&<p role="status">“{customized}”已自定义，文字保留在提示词中。再次选用会添加一组新的画师串。</p>}
    {active&&model.toLowerCase().startsWith("anima")&&active.model_family!=="anima"&&<p className="artist-preset-picker__warning" role="status">当前画师串标注为{families[active.model_family]}，与 Anima 不同。原文已保留，语法和效果未转换。</p>}
    {active&&<details className="artist-preset-picker__snapshot"><summary>查看当前串原文</summary><pre>{active.positive}</pre>{active.negative&&<><small>附带负向</small><pre>{active.negative}</pre></>}</details>}
    {open&&<div className="artist-preset-picker__panel" onKeyDown={event=>{if(event.key==="Escape"&&!event.nativeEvent.isComposing&&event.keyCode!==229){event.preventDefault();setOpen(false);}}}>
      <div className="artist-preset-picker__filters">
        <input ref={search} aria-label="搜索画师串" placeholder="名称、画师 tag 或模型版本" value={query} onChange={event=>setQuery(event.target.value)}/>
        <select aria-label="画师串模型范围" value={family} onChange={event=>{setFamily(event.target.value);setSelected(null);}}><option value="">全部模型</option>{Object.entries(families).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select>
        <label><input type="checkbox" checked={favorites} onChange={event=>setFavorites(event.target.checked)}/>仅收藏</label>
        <Link to="/artists/presets">管理画师串库</Link>
      </div>
      {loading?<p role="status">正在读取画师串…</p>:error?<p role="alert">{error} <button type="button" onClick={()=>setAttempt(n=>n+1)}>重试</button></p>:<>
        <div className="artist-preset-picker__choices" aria-label="可选画师串">{filtered.map(item=>{
          const cover=item.samples.find(image=>image.content_hash===item.content_hash);
          return <button type="button" key={item.id} aria-pressed={item.id===selected} onClick={()=>setSelected(item.id)}>
            {cover?<img loading="lazy" src={cover.image_url} alt={`${item.name} 原提示词样品`}/>:<span className="artist-preset-picker__placeholder">待补样品</span>}
            <span><strong>{item.favorite?"★ ":""}{item.name}</strong><small>{families[item.model_family]} · {item.model_label||"版本未标注"}</small>{recent.includes(item.id)&&<small>最近使用</small>}</span>
          </button>;
        })}</div>
        {!filtered.length&&<p>没有符合条件的画师串。可调整筛选，或到画师串库添加带样品的条目。</p>}
        {chosen&&<div className="artist-preset-picker__preview">
          {sample&&<img src={sample.image_url} alt={`${chosen.name} 样品预览`}/>}
          <div><strong>{chosen.name}</strong><p>{families[chosen.model_family]} · {chosen.model_label||"具体版本未标注"}</p>
            <pre>{chosen.positive}</pre>{chosen.negative&&<><small>附带负向</small><pre>{chosen.negative}</pre></>}
            <small>{chosen.ready?"样品来自原提示词，效果也受主体、模型和生成参数影响。":"当前版本待补样品；尚无对应效果参考。"}</small>
            {mismatch&&<p role="status" className="artist-preset-picker__warning">这组标注为{families[chosen.model_family]}，与当前 Anima 不同。调用仅带入原文，不会转换语法或切换模型。</p>}
            <button type="button" className="conversation-primary" disabled={disabled} onClick={apply}>{active?"替换当前画师串":"应用这组画师串"}</button>
            <Link to={`/artists/presets?selected=${encodeURIComponent(chosen.id)}`}>查看样品详情</Link>
          </div>
        </div>}
      </>}
    </div>}
  </section>;
}
