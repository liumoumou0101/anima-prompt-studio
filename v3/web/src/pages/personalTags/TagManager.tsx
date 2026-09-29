import {useEffect, useState} from "react";
import {personalTagsApi, type CategoryRecord, type TagRecord} from "../../lib/personalTags";

export function TagManager({items, categories, trash, onEdit, onChanged}: {items: TagRecord[]; categories: CategoryRecord[]; trash: boolean; onEdit: (tag: TagRecord) => void; onChanged: () => void}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [target, setTarget] = useState(""); const [error, setError] = useState(""); const [notice, setNotice] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => {setSelected(new Set());}, [items]);
  const rows = items.filter(item => selected.has(item.id));
  const move = async () => {
    setBusy(true); setError(""); setNotice("");
    try {const result = await personalTagsApi.bulkMove(rows.map(item => ({id: item.id, revision: item.revision})), target || null); setNotice(`已移动 ${result.moved} 项`); setSelected(new Set()); onChanged();}
    catch (cause) {setError(cause instanceof Error ? cause.message : String(cause));} finally {setBusy(false);}
  };
  return <div className="personal-tags-manager">
    <div className="personal-tags-table-wrap"><table><thead><tr><th><input type="checkbox" aria-label="选择本页全部" checked={items.length > 0 && selected.size === items.length} onChange={event => setSelected(event.target.checked ? new Set(items.map(item => item.id)) : new Set())} /></th><th>中文名称</th><th>英文内容</th><th>类型</th><th>分类</th><th>操作</th></tr></thead><tbody>{items.map(item => <tr key={item.id}><td><input type="checkbox" aria-label={`选择 ${item.display_name}`} checked={selected.has(item.id)} onChange={event => setSelected(previous => {const next = new Set(previous); if (event.target.checked) next.add(item.id); else next.delete(item.id); return next;})} /></td><td>{item.display_name}</td><td className="personal-tags-content-cell" title={item.content}>{item.content}</td><td>{item.kind === "fragment" ? "片段" : "单标签"}</td><td>{categories.find(category => category.id === item.category_id)?.name ?? "未分类"}</td><td><button type="button" aria-label={`编辑 ${item.display_name}`} onClick={() => onEdit(item)}>{trash ? "查看/恢复" : "编辑"}</button></td></tr>)}</tbody></table></div>
    {!trash && <div className="personal-tags-bulk"><span>本页已选 {selected.size} 项</span><label>移动到分类<select value={target} onChange={event => setTarget(event.target.value)}><option value="">未分类</option>{categories.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><button type="button" disabled={selected.size === 0 || busy} onClick={() => void move()}>批量移动</button></div>}
    {notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
  </div>;
}
