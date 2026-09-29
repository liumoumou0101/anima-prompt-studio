import {useEffect, useState} from "react";
import {personalTagsApi, type CategoryRecord, type TagRecord, type TagWrite} from "../../lib/personalTags";

export function TagEditor({tag, categories, onSave, onCancel, onDelete, onRestore, onReload, onDirtyChange}: {
  tag: TagRecord | null; categories: CategoryRecord[]; onSave: (value: TagWrite, expectedRevision?: number) => Promise<void>;
  onCancel: () => void; onDelete?: () => Promise<void>; onRestore?: () => Promise<void>; onReload?: () => Promise<void>; onDirtyChange?: (dirty: boolean) => void;
}) {
  const [value, setValue] = useState<TagWrite>(() => initial(tag));
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [similar, setSimilar] = useState<TagRecord[]>([]);
  const [showSimilar, setShowSimilar] = useState(false);
  useEffect(() => {setValue(initial(tag)); setError(""); setSimilar([]);}, [tag]);
  useEffect(() => {
    if (!value.content.trim()) {setSimilar([]); return;}
    let live = true;
    const timer = window.setTimeout(() => {void personalTagsApi.findSimilar(value.content, tag?.id).then(result => {if (live) setSimilar(result);}).catch(() => {if (live) setSimilar([]);});}, 220);
    return () => {live = false; clearTimeout(timer);};
  }, [value.content, tag?.id]);
  const dirty = JSON.stringify(value) !== JSON.stringify(initial(tag));
  useEffect(() => {onDirtyChange?.(dirty); return () => onDirtyChange?.(false);}, [dirty, onDirtyChange]);
  const cancel = () => {if (!dirty || window.confirm("有未保存修改，确定放弃吗？")) onCancel();};
  const change = <K extends keyof TagWrite>(key: K, next: TagWrite[K]) => setValue(current => ({...current, [key]: next}));
  const save = async () => {
    if (!value.content.trim()) {setError("英文原文不能为空"); return;}
    const weight = Number(value.default_weight);
    if (!Number.isFinite(weight) || weight < 0.1 || weight > 2 || Math.abs(weight * 20 - Math.round(weight * 20)) > 1e-8) {setError("默认权重须为 0.1–2.0，步长 0.05"); return;}
    setSaving(true); setError("");
    try {await onSave({...value, default_weight: weight}, tag?.revision);} catch (cause) {setError(cause instanceof Error ? cause.message : String(cause));}
    finally {setSaving(false);}
  };
  return <section aria-label={tag ? "编辑标签" : "新增标签"} className="personal-tags-editor">
    <header><h2>{tag ? "编辑标签" : "新增标签"}</h2><button type="button" onClick={cancel} aria-label="关闭标签编辑">×</button></header>
    <label>中文名称<input value={value.display_name} maxLength={200} onChange={event => change("display_name", event.target.value)} /></label>
    <label>英文原文<textarea aria-label="英文原文" value={value.content} onChange={event => change("content", event.target.value)} rows={5} /></label>
    <label>类型<select value={value.kind} onChange={event => change("kind", event.target.value as "tag" | "fragment")}><option value="tag">单标签</option><option value="fragment">提示词片段</option></select></label>
    <label>分类<select value={value.category_id ?? ""} onChange={event => change("category_id", event.target.value || null)}><option value="">未分类</option>{categories.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
    <fieldset><legend>别名</legend>{(value.aliases ?? []).map((alias, index) => <div className="personal-tags-alias" key={index}><input aria-label={`别名 ${index + 1}`} value={alias} onChange={event => change("aliases", (value.aliases ?? []).map((current, i) => i === index ? event.target.value : current))} /><button type="button" aria-label={`移除别名 ${index + 1}`} onClick={() => change("aliases", (value.aliases ?? []).filter((_, i) => i !== index))}>移除</button></div>)}<button type="button" onClick={() => change("aliases", [...(value.aliases ?? []), ""])}>添加别名</button></fieldset>
    <label>备注<textarea value={value.notes} onChange={event => change("notes", event.target.value)} rows={3} /></label>
    <label>默认权重<input type="number" min="0.1" max="2" step="0.05" value={value.default_weight} onChange={event => change("default_weight", Number(event.target.value))} /></label>
    {tag && (tag.source_key || tag.source_id || Object.keys(tag.source_metadata).length > 0 || tag.needs_review.length > 0) && <details><summary>原始来源（只读）</summary><pre>{JSON.stringify({source_key: tag.source_key, source_id: tag.source_id, source_metadata: tag.source_metadata, needs_review: tag.needs_review}, null, 2)}</pre></details>}
    {similar.length > 0 && <aside className="personal-tags-similar">发现 {similar.length} 个相近项 <button type="button" onClick={() => setShowSimilar(open => !open)} aria-expanded={showSimilar}>查看</button>{showSimilar && <ul>{similar.map(item => <li key={item.id}>{item.display_name} · {item.content}</li>)}</ul>}</aside>}
    {error && <div role="alert"><p>{error}</p>{tag && <button type="button" onClick={() => {if (!dirty || window.confirm("放弃表单修改并重新载入服务器版本？")) void onReload?.().catch(cause => setError(String(cause)));}}>重新载入服务器版本</button>}</div>}
    <div className="personal-tags-editor-actions"><button type="button" className="button button--primary" disabled={saving} onClick={() => void save()}>{saving ? "保存中…" : tag ? "保存修改" : "新增标签"}</button><button type="button" onClick={cancel}>取消</button>{tag && (tag.deleted_at ? <button type="button" onClick={() => void onRestore?.().catch(cause => setError(String(cause)))}>恢复标签</button> : <button type="button" onClick={() => {if (window.confirm(`移入回收站：${tag.display_name}？`)) void onDelete?.().catch(cause => setError(String(cause)));}}>移入回收站</button>)}</div>
  </section>;
}

function initial(tag: TagRecord | null): TagWrite {return tag ? {display_name: tag.display_name, content: tag.content, aliases: [...tag.aliases], category_id: tag.category_id, kind: tag.kind, notes: tag.notes, default_weight: tag.default_weight} : {display_name: "", content: "", aliases: [], category_id: null, kind: "tag", notes: "", default_weight: 1};}
