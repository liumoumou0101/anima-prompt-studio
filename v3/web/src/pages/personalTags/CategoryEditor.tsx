import {useEffect, useState} from "react";
import {personalTagsApi, type CategoryRecord} from "../../lib/personalTags";

export function CategoryEditor({categories, trashCategories, onChanged, onClose, onDirtyChange}: {categories: CategoryRecord[]; trashCategories: CategoryRecord[]; onChanged: () => void; onClose: () => void; onDirtyChange?: (dirty: boolean) => void}) {
  const [selectedId, setSelectedId] = useState("");
  const selected = [...categories, ...trashCategories].find(item => item.id === selectedId);
  const [name, setName] = useState(""); const [parentId, setParentId] = useState(""); const [position, setPosition] = useState(0);
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => {setName(selected?.name ?? ""); setParentId(selected?.parent_id ?? ""); setPosition(selected?.position ?? 0); setError("");}, [selectedId, selected?.revision]);
  const dirty = name !== (selected?.name ?? "") || parentId !== (selected?.parent_id ?? "") || position !== (selected?.position ?? 0);
  useEffect(() => {onDirtyChange?.(dirty); return () => onDirtyChange?.(false);}, [dirty, onDirtyChange]);
  const close = () => {if (!dirty || window.confirm("分类有未保存修改，确定放弃吗？")) onClose();};
  const perform = async (action: () => Promise<unknown>) => {setBusy(true); setError(""); try {await action(); onChanged();} catch (cause) {setError(cause instanceof Error ? cause.message : String(cause));} finally {setBusy(false);}};
  const descendants = (id: string): Set<string> => {const result = new Set([id]); let added = true; while (added) {added = false; for (const item of categories) if (item.parent_id && result.has(item.parent_id) && !result.has(item.id)) {result.add(item.id); added = true;}} return result;};
  const invalidParents = selected ? descendants(selected.id) : new Set<string>();
  return <section className="personal-tags-editor" aria-label="管理分类"><header><h2>管理分类</h2><button type="button" aria-label="关闭分类管理" onClick={close}>×</button></header>
    <label>选择分类<select value={selectedId} onChange={event => {if (!dirty || window.confirm("分类有未保存修改，确定放弃吗？")) setSelectedId(event.target.value);}}><option value="">新增分类</option>{categories.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}{trashCategories.map(item => <option key={item.id} value={item.id}>{item.name}（回收站）</option>)}</select></label>
    <label>分类名称<input value={name} maxLength={200} onChange={event => setName(event.target.value)} /></label>
    <label>上级分类<select value={parentId} onChange={event => setParentId(event.target.value)}><option value="">根分类</option>{categories.filter(item => !invalidParents.has(item.id)).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
    <label>排序位置<input type="number" step="1" value={position} onChange={event => setPosition(Number(event.target.value))} /></label>
    {error && <p role="alert">{error}</p>}
    <div className="personal-tags-editor-actions"><button type="button" disabled={busy || !name.trim() || Boolean(selected?.deleted_at)} onClick={() => void perform(async () => {if (selected) await personalTagsApi.updateCategory(selected.id, {name, parent_id: parentId || null, position}, selected.revision); else {await personalTagsApi.createCategory({name, parent_id: parentId || null, position}); setName(""); setParentId(""); setPosition(0);}})}>{selected ? "保存分类" : "新增分类"}</button>
      {selected && (selected.deleted_at ? <button type="button" disabled={busy} onClick={() => void perform(() => personalTagsApi.restoreCategory(selected.id, selected.revision))}>恢复分类</button> : <button type="button" disabled={busy} onClick={() => {if (window.confirm(`将分类 ${selected.name} 移入回收站？非空分类需先移走内容。`)) void perform(() => personalTagsApi.deleteCategory(selected.id, selected.revision));}}>回收分类</button>)}</div>
  </section>;
}
