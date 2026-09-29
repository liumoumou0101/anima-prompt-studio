import {useCallback, useEffect, useRef, useState} from "react";
import {useBlocker} from "react-router-dom";
import {DownloadSimple, Plus, UploadSimple} from "@phosphor-icons/react";
import {addCompositionItem} from "../lib/personalTagComposition";
import {personalTagsApi, type TagRecord, type TagWrite} from "../lib/personalTags";
import {CategoryTree} from "./personalTags/CategoryTree";
import {TagPicker} from "./personalTags/TagPicker";
import {TagManager} from "./personalTags/TagManager";
import {TagEditor} from "./personalTags/TagEditor";
import {CategoryEditor} from "./personalTags/CategoryEditor";
import {CompositionPanel} from "./personalTags/CompositionPanel";
import {ImportDialog} from "./personalTags/ImportDialog";
import {usePersonalCatalog} from "./personalTags/usePersonalCatalog";
import {usePersonalComposition} from "./personalTags/usePersonalComposition";
import "./personalTags.css";

type Editor = {kind: "tag"; tag: TagRecord | null} | {kind: "category"} | null;

export function PersonalTagsPage() {
  const catalog = usePersonalCatalog();
  const composition = usePersonalComposition();
  const blocker = useBlocker(({currentLocation, nextLocation}) => currentLocation.pathname === "/personal-tags" && nextLocation.pathname !== currentLocation.pathname);
  const handlingBlock = useRef(false);
  const [mode, setMode] = useState<"pick" | "manage">("pick");
  const [editor, setEditor] = useState<Editor>(null);
  const [editorDirty, setEditorDirty] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [sort, setSort] = useState("default");
  const [message, setMessage] = useState("");
  const [compactCompositionOpen, setCompactCompositionOpen] = useState(false);
  const setDirty = useCallback((value: boolean) => setEditorDirty(value), []);
  const guard = () => !editorDirty || window.confirm("编辑表单有未保存修改，确定离开吗？");
  const switchMode = async (next: "pick" | "manage") => {
    if (next === mode || !guard()) return;
    if (!await composition.flush()) {setMessage("组合草稿尚未保存，请重试或处理保存错误"); return;}
    setEditor(null); setEditorDirty(false); setMode(next);
  };
  useEffect(() => {
    if (blocker.state !== "blocked" || handlingBlock.current) return;
    handlingBlock.current = true;
    void (async () => {
      if (editorDirty && !window.confirm("编辑表单有未保存修改，确定离开吗？")) {blocker.reset(); return;}
      if (await composition.flush()) blocker.proceed();
      else {setMessage("组合草稿尚未保存，请重试或处理保存错误"); blocker.reset();}
    })().finally(() => {handlingBlock.current = false;});
  }, [blocker, editorDirty, composition.flush]);
  useEffect(() => {
    const onUnload = (event: BeforeUnloadEvent) => {if (editorDirty || ["dirty", "saving", "error", "conflict"].includes(composition.saveState)) {event.preventDefault(); event.returnValue = "";}};
    window.addEventListener("beforeunload", onUnload);
    return () => window.removeEventListener("beforeunload", onUnload);
  }, [editorDirty, composition.saveState]);
  const openEditor = (tag: TagRecord | null) => {if (!guard()) return; void composition.flush().then(ok => {if (!ok) {setMessage("组合草稿尚未保存，请重试或处理保存错误"); return;} setEditor({kind: "tag", tag}); setEditorDirty(false); setMode("manage");});};
  const saveTag = async (value: TagWrite, expectedRevision?: number) => {
    if (editor?.kind !== "tag") return;
    if (editor.tag) await personalTagsApi.updateTag(editor.tag.id, value, expectedRevision ?? editor.tag.revision);
    else await personalTagsApi.createTag(value);
    setMessage("标签已保存"); setEditor(null); setEditorDirty(false); catalog.refresh();
  };
  const deleteTag = async () => {if (editor?.kind !== "tag" || !editor.tag) return; await personalTagsApi.deleteTag(editor.tag.id, editor.tag.revision); setEditor(null); catalog.refresh(); setMessage("标签已移入回收站");};
  const restoreTag = async () => {if (editor?.kind !== "tag" || !editor.tag) return; await personalTagsApi.restoreTag(editor.tag.id, editor.tag.revision); setEditor(null); catalog.refresh(); setMessage("标签已恢复");};
  const reloadTag = async () => {if (editor?.kind !== "tag" || !editor.tag) return; const latest = await personalTagsApi.getTag(editor.tag.id); setEditor({kind: "tag", tag: latest}); catalog.refresh();};
  const add = (tag: TagRecord, side: "positive" | "negative") => {try {if (composition.items.length >= 300) throw new Error("组合最多 300 项"); composition.setItems(items => addCompositionItem(items, tag, side));} catch (cause) {setMessage(cause instanceof Error ? cause.message : String(cause));}};
  const exportBundle = async () => {
    try {const bundle = await personalTagsApi.export(); const blob = new Blob([JSON.stringify(bundle, null, 2)], {type: "application/json"}); const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = "anima-personal-tags.json"; document.body.append(link); link.click(); link.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000); setMessage("已下载当前个人标签数据");}
    catch (cause) {setMessage(cause instanceof Error ? cause.message : String(cause));}
  };
  const ordered = [...catalog.items].sort((a, b) => sort === "name" ? a.display_name.localeCompare(b.display_name, "zh") : sort === "updated" ? b.updated_at.localeCompare(a.updated_at) : 0);
  const categoryName = catalog.categories.find(item => item.id === catalog.categoryId)?.name ?? "全部分类";
  return <div className="personal-tags-page">
    <header className="personal-tags-heading"><div><p className="eyebrow">PERSONAL TAG MARKET</p><h1>私人标签库</h1><p>搜索、整理并组合自己的提示词素材</p></div><div className="personal-tags-top-actions"><button type="button" className="button button--primary" onClick={() => openEditor(null)}><Plus />新增标签</button><button type="button" onClick={() => setImportOpen(true)}><UploadSimple />导入 JSON</button><button type="button" onClick={() => void exportBundle()}><DownloadSimple />导出 JSON</button></div></header>
    <div className="personal-tags-tabs" role="group" aria-label="个人标签视图"><button type="button" className={mode === "pick" ? "is-active" : ""} aria-pressed={mode === "pick"} onClick={() => void switchMode("pick")}>挑选标签</button><button type="button" className={mode === "manage" ? "is-active" : ""} aria-pressed={mode === "manage"} onClick={() => void switchMode("manage")}>管理词库</button><span>{catalog.total} 条结果 · {catalog.categories.length} 个分类</span></div>
    <div className={`personal-tags-layout ${mode === "manage" ? "is-managing" : ""}`}>
      <aside className="personal-tags-panel personal-tags-categories"><h2>分类目录</h2><CategoryTree categories={catalog.categories} selected={catalog.categoryId} onSelect={catalog.setCategoryId} /><label><input type="checkbox" checked={catalog.includeDescendants} onChange={event => catalog.setIncludeDescendants(event.target.checked)} />包含子分类</label>{mode === "manage" && <button type="button" onClick={() => {if (guard()) setEditor({kind: "category"});}}>管理分类</button>}</aside>
      <section className="personal-tags-panel personal-tags-results" aria-label={mode === "pick" ? "标签结果" : "词库条目"}>
        <div className="personal-tags-search"><label>搜索标签<input type="search" value={catalog.q} onChange={event => catalog.setQ(event.target.value)} placeholder="搜索中文、英文或别名" /></label><label>本页排序<select value={sort} onChange={event => setSort(event.target.value)}><option value="default">默认</option><option value="name">名称</option><option value="updated">最近更新</option></select></label></div>
        <div className="personal-tags-result-meta"><span>{categoryName} · 共 {catalog.total} 条</span><button type="button" onClick={catalog.refresh}>刷新结果</button>{mode === "manage" && <label><input type="checkbox" checked={catalog.trash} onChange={event => catalog.setTrash(event.target.checked)} />回收站</label>}</div>
        {catalog.error && <p role="alert">加载失败：{catalog.error.message} <button type="button" onClick={catalog.refresh}>重试</button></p>}
        {catalog.loading && <p role="status">正在加载标签…</p>}
        {!catalog.loading && !catalog.error && (ordered.length ? mode === "pick" ? <TagPicker items={ordered} selected={composition.items} onAdd={add} onEdit={openEditor} /> : <TagManager items={ordered} categories={catalog.categories} trash={catalog.trash} onEdit={openEditor} onChanged={catalog.refresh} /> : <p className="personal-tags-empty">当前范围暂无标签</p>)}
        <div className="personal-tags-pagination"><button type="button" disabled={catalog.page === 0 || catalog.loading} onClick={() => catalog.setPage(page => page - 1)}>上一页</button><span>第 {catalog.page + 1} 页 / {Math.max(1, Math.ceil(catalog.total / catalog.pageSize))} 页</span><button type="button" disabled={(catalog.page + 1) * catalog.pageSize >= catalog.total || catalog.loading} onClick={() => catalog.setPage(page => page + 1)}>下一页</button></div>
      </section>
      {mode === "pick" ? <div className="personal-tags-composition-column"><button type="button" className="personal-tags-compact-toggle" aria-expanded={compactCompositionOpen} onClick={() => setCompactCompositionOpen(open => !open)}>已选组合 ({composition.items.length}) {compactCompositionOpen ? "收起" : "展开"}</button><div className={compactCompositionOpen ? "is-open" : ""}><CompositionPanel composition={composition} /></div></div> : <aside className="personal-tags-panel personal-tags-editor-column">{editor?.kind === "tag" ? <TagEditor key={editor.tag?.id ?? "new"} tag={editor.tag} categories={catalog.categories} onSave={saveTag} onCancel={() => setEditor(null)} onDelete={deleteTag} onRestore={restoreTag} onReload={reloadTag} onDirtyChange={setDirty} /> : editor?.kind === "category" ? <CategoryEditor categories={catalog.categories} trashCategories={catalog.trashCategories} onChanged={catalog.refresh} onClose={() => setEditor(null)} onDirtyChange={setDirty} /> : <p>选择条目查看或编辑。</p>}<p className="personal-tags-selection-summary">已选 {composition.items.length} 项 · <button type="button" onClick={() => void switchMode("pick")}>查看组合</button></p></aside>}
    </div>
    {message && <p className="personal-tags-message" role="status" aria-live="polite">{message}</p>}
    {importOpen && <ImportDialog onClose={() => setImportOpen(false)} onImported={catalog.refresh} />}
  </div>;
}
