import {useEffect, useState} from "react";
import {Copy, ArrowUp, ArrowDown, Trash} from "@phosphor-icons/react";
import {moveCompositionItem, renderComposition} from "../../lib/personalTagComposition";
import {personalTagsApi, type CompositionItem, type CompositionRecord, type TagRecord} from "../../lib/personalTags";
import type {PersonalComposition} from "./usePersonalComposition";

export function CompositionPanel({composition}: {composition: PersonalComposition}) {
  const {items, setItems, saveState, error, flush, reload} = composition;
  const [name, setName] = useState(""); const [combinations, setCombinations] = useState<CompositionRecord[]>([]);
  const [trashCombinations, setTrashCombinations] = useState<CompositionRecord[]>([]);
  const [selectedId, setSelectedId] = useState(""); const [message, setMessage] = useState(""); const [busy, setBusy] = useState(false);
  let output: ReturnType<typeof renderComposition>;
  let validOutput = true;
  try {output = renderComposition(items);} catch (cause) {validOutput = false; output = {positive: "", negative: "", warnings: [cause instanceof Error ? cause.message : String(cause)]};}
  const refresh = () => {void Promise.all([personalTagsApi.listCombinations(false), personalTagsApi.listCombinations(true)]).then(([active, deleted]) => {setCombinations(active); setTrashCombinations(deleted);}).catch(cause => setMessage(String(cause)));};
  useEffect(refresh, []);
  const operation = async (job: () => Promise<void>) => {setBusy(true); setMessage(""); try {await job();} catch (cause) {setMessage(cause instanceof Error ? cause.message : String(cause));} finally {setBusy(false);}};
  const selected = combinations.find(item => item.id === selectedId);
  const save = () => void operation(async () => {
    if (!name.trim()) throw new Error("请输入组合名称");
    if (!await flush()) throw new Error("草稿尚未保存，请重试或处理版本冲突");
    if (selected) await personalTagsApi.updateCombination(selected.id, {name, items}, selected.revision);
    else await personalTagsApi.createCombination({name, items});
    setMessage("组合已保存"); refresh();
  });
  const load = () => void operation(async () => {
    if (!selected) return;
    if (items.length && !window.confirm("载入组合将替换当前已选内容，继续吗？")) return;
    if (!await flush()) throw new Error("当前草稿尚未保存，请重试");
    const record = await personalTagsApi.getCombination(selected.id);
    setItems(record.items.map(item => ({...item}))); setName(record.name);
    setMessage(`已载入 ${record.name}`);
  });
  const copy = (value: string) => void operation(async () => {await navigator.clipboard.writeText(value); setMessage("已复制原文");});
  const changeItem = (id: string, update: (item: CompositionItem) => CompositionItem) => setItems(previous => previous.map(item => item.id === id ? update(item) : item));
  return <section className="personal-tags-panel personal-tags-composition" aria-label="已选组合">
    <header><h2>已选内容 <small>{items.length}</small></h2><button type="button" disabled={!items.length} onClick={() => {if (window.confirm("清空当前组合？")) setItems([]);}}>清空</button></header>
    {(["positive", "negative"] as const).map(side => <div key={side} className="personal-tags-side"><h3>{side === "positive" ? "正向" : "负向"} ({items.filter(item => item.polarity === side).length})</h3><ol>{items.filter(item => item.polarity === side).map(item => <li key={item.id}><div><strong>{item.display_name}</strong><small>{item.content}</small></div><div className="personal-tags-item-actions"><button type="button" aria-label={`上移 ${item.display_name}`} onClick={() => setItems(previous => moveCompositionItem(previous, item.id, -1))}><ArrowUp /></button><button type="button" aria-label={`下移 ${item.display_name}`} onClick={() => setItems(previous => moveCompositionItem(previous, item.id, 1))}><ArrowDown /></button><button type="button" aria-label={`移到${side === "positive" ? "负向" : "正向"} ${item.display_name}`} onClick={() => {if (items.some(other => other.source_tag_id === item.source_tag_id && other.polarity !== side)) {setMessage("该条目已在另一侧"); return;} changeItem(item.id, current => ({...current, polarity: side === "positive" ? "negative" : "positive"}));}}>{side === "positive" ? "负" : "正"}</button><WeightInput item={item} onChange={weight => changeItem(item.id, current => ({...current, weight}))} /><button type="button" aria-label={`移除 ${item.display_name}`} onClick={() => setItems(previous => previous.filter(current => current.id !== item.id))}><Trash /></button></div></li>)}</ol></div>)}
    <div className="personal-tags-preview"><h3>提示词预览</h3><label>正向英文<pre>{output.positive}</pre></label><button type="button" disabled={!output.positive || !validOutput} onClick={() => copy(output.positive)}><Copy />复制正向</button><label>负向英文<pre>{output.negative}</pre></label><button type="button" disabled={!output.negative || !validOutput} onClick={() => copy(output.negative)}><Copy />复制负向</button><button type="button" disabled={!items.length || !validOutput} onClick={() => copy(`Positive: ${output.positive}\nNegative: ${output.negative}`)}><Copy />复制完整提示词</button></div>
    {output.warnings.map(warning => <p className="personal-tags-warning" key={warning}>{warning}</p>)}
    <section className="personal-tags-combinations" aria-label="命名组合"><h3>命名组合</h3><label>选择已保存组合<select value={selectedId} onChange={event => {setSelectedId(event.target.value); setName(combinations.find(item => item.id === event.target.value)?.name ?? "");}}><option value="">新组合</option>{combinations.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>组合名称<input value={name} onChange={event => setName(event.target.value)} /></label><div><button type="button" disabled={busy} onClick={save}>{selected ? "更新组合" : "保存组合"}</button><button type="button" disabled={!selected || busy} onClick={load}>载入组合</button>{selected && <button type="button" disabled={busy} onClick={() => void operation(async () => {await personalTagsApi.deleteCombination(selected.id, selected.revision); setSelectedId(""); setName(""); refresh();})}>回收组合</button>}</div>{trashCombinations.length > 0 && <details><summary>已回收组合 ({trashCombinations.length})</summary>{trashCombinations.map(item => <div key={item.id}>{item.name} <button type="button" onClick={() => void operation(async () => {await personalTagsApi.restoreCombination(item.id, item.revision); refresh();})}>恢复组合 {item.name}</button></div>)}</details>}</section>
    <p role="status" aria-live="polite">{message || `草稿：${({loading: "载入中", dirty: "待保存", saving: "保存中", saved: "已保存", error: "保存失败", conflict: "版本冲突"} as const)[saveState]}`}</p>
    {(saveState === "error" || saveState === "conflict") && <div role="alert">{error?.message}<button type="button" onClick={() => void flush()}>重试保存</button><button type="button" onClick={() => {if (window.confirm("放弃本地修改并重新载入服务器草稿？")) void reload();}}>放弃本地修改并重载</button></div>}
  </section>;
}

function WeightInput({item, onChange}: {item: CompositionItem; onChange: (weight: number) => void}) {
  const [draft, setDraft] = useState(String(item.weight)); const [error, setError] = useState(false);
  useEffect(() => {setDraft(String(item.weight)); setError(false);}, [item.weight]);
  const commit = () => {const value = Number(draft); if (!draft || !Number.isFinite(value) || value < 0.1 || value > 2 || Math.abs(value * 20 - Math.round(value * 20)) > 1e-8) {setError(true); return;} setError(false); onChange(value);};
  return <label className="personal-tags-weight">权重 {item.display_name}<input type="number" min="0.1" max="2" step="0.05" aria-invalid={error} value={draft} onChange={event => setDraft(event.target.value)} onBlur={commit} onKeyDown={event => {if (event.key === "Enter") {event.preventDefault(); commit();}}} />{error && <small>0.1–2.0，步长 0.05</small>}</label>;
}
