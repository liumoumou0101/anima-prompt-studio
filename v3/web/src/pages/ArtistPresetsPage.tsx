import {type FormEvent, useEffect, useMemo, useRef, useState} from "react";
import {Link, useBlocker, useSearchParams} from "react-router-dom";
import {DownloadSimple, Image, Plus, Star, UploadSimple, X} from "@phosphor-icons/react";
import {artistModelLabels, artistPresetModelLabel, artistPresetsApi, artistPresetWrite, currentArtistSample,
  type ArtistModelFamily, type ArtistPreset, type ArtistPresetImportPreview, type ArtistPresetSample,
  type ArtistPresetSuggestion, type ArtistPresetWrite, type ArtistSampleWrite} from "../lib/artistPresets";
import "./libraryPages.css";
import "./artistPresets.css";

const emptyPreset = (): ArtistPresetWrite => ({name: "", positive: "", negative: "", model_family: "anima", model_label: "", syntax: "comfy", source_url: "", source_author: "", notes: "", favorite: false});
const errorMessage = (error: unknown) => error instanceof Error ? error.message : String(error);
const externalUrl = (url: string) => {try {const value = new URL(url); return ["https:", "http:"].includes(value.protocol) ? value.href : null;} catch {return null;}};
type Editor = {original: ArtistPreset | null; draft: ArtistPresetWrite};

export function ArtistPresetsPage() {
  const [searchParams] = useSearchParams();
  const requestedId = searchParams.get("selected");
  const openedRequest = useRef<string | null>(null);
  const [items, setItems] = useState<ArtistPreset[]>([]);
  const [suggestions, setSuggestions] = useState<ArtistPresetSuggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [suggestionError, setSuggestionError] = useState("");
  const [query, setQuery] = useState("");
  const [family, setFamily] = useState<ArtistModelFamily | "all">("anima");
  const [onlyFavorites, setOnlyFavorites] = useState(false);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [sampleDirty, setSampleDirty] = useState(false);
  const [sampleReset, setSampleReset] = useState(0);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const panel = useRef<HTMLElement>(null);
  const dirty = !!editor && JSON.stringify(editor.draft) !== JSON.stringify(editor.original ? artistPresetWrite(editor.original) : emptyPreset());
  const blocker = useBlocker(dirty || sampleDirty || !!busy);
  useEffect(() => {
    if (blocker.state !== "blocked") return;
    if (busy) {setNotice("请等待当前保存完成后再离开。"); blocker.reset();}
    else if (window.confirm("画师串或样品有未保存的修改，确定离开吗？")) blocker.proceed();
    else blocker.reset();
  }, [blocker, busy]);
  useEffect(() => {
    const unload = (event: BeforeUnloadEvent) => {if (dirty || sampleDirty || busy) {event.preventDefault(); event.returnValue = "";}};
    window.addEventListener("beforeunload", unload); return () => window.removeEventListener("beforeunload", unload);
  }, [dirty, sampleDirty, busy]);
  useEffect(() => {
    let active = true; setLoading(true); setLoadError("");
    void artistPresetsApi.list().then(result => {if (active) setItems(result.items);})
      .catch(cause => {if (active) setLoadError(errorMessage(cause));}).finally(() => {if (active) setLoading(false);});
    void artistPresetsApi.suggestions().then(result => {if (active) {setSuggestions(result.items); setSuggestionError("");}})
      .catch(cause => {if (active) setSuggestionError(errorMessage(cause));});
    return () => {active = false;};
  }, [reloadKey]);
  useEffect(() => {
    if (loading || !requestedId || openedRequest.current === requestedId) return;
    const selected = items.find(item => item.id === requestedId);
    if (!selected) return;
    openedRequest.current = requestedId;
    setSampleDirty(false); setSampleReset(value => value + 1);
    setEditor({original: selected, draft: artistPresetWrite(selected)});
    setFamily(selected.model_family);
  }, [items, loading, requestedId]);
  const visible = useMemo(() => {
    const term = query.trim().toLocaleLowerCase();
    return items.filter(item => (family === "all" || item.model_family === family) && (!onlyFavorites || item.favorite)
      && (!term || [item.name, item.positive, item.negative, item.notes, item.source_author, item.model_label].some(text => text.toLocaleLowerCase().includes(term))))
      .sort((left, right) => Number(right.favorite) - Number(left.favorite) || right.updated_at.localeCompare(left.updated_at));
  }, [items, query, family, onlyFavorites]);
  const guard = () => !busy && (!(dirty || sampleDirty) || window.confirm("画师串或样品有未保存的修改，确定放弃吗？"));
  const resetSampleDraft = () => {setSampleDirty(false); setSampleReset(value => value + 1);};
  const open = (item: ArtistPreset | null) => {
    if (!guard()) return; setError(""); setNotice("");
    resetSampleDraft();
    setEditor({original: item, draft: item ? artistPresetWrite(item) : emptyPreset()});
    window.setTimeout(() => {panel.current?.focus(); if (window.innerWidth < 1100) panel.current?.scrollIntoView?.({block: "start", behavior: "smooth"});}, 0);
  };
  const adopt = (item: ArtistPreset) => {
    setItems(current => [item, ...current.filter(other => other.id !== item.id)]);
    setEditor({original: item, draft: artistPresetWrite(item)});
  };
  async function action(label: string, task: () => Promise<void>): Promise<boolean> {
    if (busy) return false; setBusy(label); setError(""); setNotice("");
    try {await task(); return true;} catch (cause) {setError(errorMessage(cause)); return false;} finally {setBusy("");}
  }
  function change<K extends keyof ArtistPresetWrite>(field: K, value: ArtistPresetWrite[K]) {
    setEditor(current => current ? {...current, draft: {...current.draft, [field]: value}} : null);
  }
  const save = (event: FormEvent) => {
    event.preventDefault(); if (!editor) return;
    const changesSampleVersion = editor.original && (["positive", "negative", "model_family", "model_label", "syntax"] as const).some(key => editor.draft[key] !== editor.original![key]);
    if (sampleDirty && changesSampleVersion && !window.confirm("修改原串或模型会切换样品版本，并清空尚未上传的样品草稿。确定保存吗？")) return;
    void action("保存画师串", async () => {
      const item = editor.original ? await artistPresetsApi.update(editor.original.id, editor.draft, editor.original.revision) : await artistPresetsApi.create(editor.draft);
      if (changesSampleVersion) resetSampleDraft();
      adopt(item); setNotice(item.ready ? "画师串已保存。" : "画师串已保存，请在下方补充一张当前版本的样品。");
    });
  };
  const reloadEditor = () => {
    if (!editor?.original || !guard()) return;
    void action("重新载入", async () => {adopt(await artistPresetsApi.get(editor.original!.id)); resetSampleDraft(); setNotice("已载入最新版本。");});
  };
  const deletePreset = () => {
    if (!editor?.original || !window.confirm(`删除「${editor.original.name}」？工作台中已调用的快照和历史不会受影响。`)) return;
    void action("删除画师串", async () => {const id = editor.original!.id; await artistPresetsApi.remove(id, editor.original!.revision); setItems(current => current.filter(item => item.id !== id)); setEditor(null); resetSampleDraft(); setNotice("画师串已删除。");});
  };
  const favorite = (item: ArtistPreset) => {
    if (dirty && editor?.original?.id === item.id) {change("favorite", !editor.draft.favorite); return;}
    void action("更新收藏", async () => {
      const updated = await artistPresetsApi.update(item.id, {...artistPresetWrite(item), favorite: !item.favorite}, item.revision);
      setItems(current => current.map(value => value.id === item.id ? updated : value));
      if (editor?.original?.id === item.id) setEditor({original: updated, draft: artistPresetWrite(updated)});
    });
  };
  const importReference = (item: ArtistPresetSuggestion) => {
    if (!guard()) return;
    void action("收藏参考串", async () => {const result = await artistPresetsApi.fromReference(item.reference_id); adopt(result); resetSampleDraft(); setFamily("anima"); setQuery(""); setOnlyFavorites(false); setNotice("已保存画师串与独立样品副本，保留原图完整提示词。");});
  };
  const exportLibrary = (presetId?: string) => void action("导出备份", async () => {
    const document = await artistPresetsApi.export(presetId); const url = URL.createObjectURL(new Blob([JSON.stringify(document, null, 2)], {type: "application/json"}));
    const link = window.document.createElement("a"); link.href = url; link.download = presetId ? `artist-preset-${presetId}.json` : "anima-artist-presets.json"; window.document.body.append(link); link.click(); link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000); setNotice("已导出画师串与样品图片的完整 JSON 备份。");
  });

  return <div className="page library-page artist-presets-page">
    <header className="library-page-heading artist-presets-heading"><div><h1>画师串</h1><p>把一组画师、原始权重和真实样品放在一起，随时在工作台调用。</p></div>
      <div className="artist-presets-actions"><button type="button" className="is-primary" disabled={!!busy} onClick={() => open(null)}><Plus />新建画师串</button><button type="button" disabled={!!busy} onClick={() => setImportOpen(value => !value)}><UploadSimple />导入备份</button><button type="button" disabled={!!busy || loading} onClick={() => exportLibrary()}><DownloadSimple />导出备份</button></div></header>
    <nav className="artist-library-tabs" aria-label="画师库视图"><Link to="/artists">单个画师</Link><Link to="/artists/presets" aria-current="page">画师串</Link></nav>
    {notice && <p className="artist-presets-notice" role="status">{notice}</p>}
    {error && <div className="artist-presets-error" role="alert">{error}{editor?.original && <button type="button" disabled={!!busy} onClick={reloadEditor}>重新载入最新版本</button>}</div>}
    {importOpen && <ArtistPresetImport onClose={() => setImportOpen(false)} onImported={result => {setItems(current => [...result, ...current.filter(item => !result.some(next => next.id === item.id))]); setNotice(`已导入 ${result.length} 个画师串。`);}} />}
    <div className="artist-presets-toolbar"><label>搜索画师串<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="名称、画师、模型版本或备注" /></label>
      <label>模型筛选<select value={family} onChange={event => setFamily(event.target.value as ArtistModelFamily | "all")}><option value="all">全部模型</option>{Object.entries(artistModelLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label className="artist-presets-check"><input type="checkbox" checked={onlyFavorites} onChange={event => setOnlyFavorites(event.target.checked)} />只看收藏</label>
      <span>{visible.length} / {items.length} 组</span><button type="button" disabled={!!busy || loading} onClick={() => setReloadKey(value => value + 1)}>刷新</button></div>
    {loading && <p role="status">正在加载画师串…</p>}
    {loadError && <p role="alert">加载失败：{loadError} <button type="button" onClick={() => setReloadKey(value => value + 1)}>重试</button></p>}
    <div className={`artist-presets-layout${editor ? " has-editor" : ""}`}>
      <section className="artist-presets-results" aria-label="画师串结果">
        {!loading && !loadError && visible.length === 0 && <div className="artist-presets-empty"><Image size={32} /><h2>{items.length ? "当前筛选下没有画师串" : "从一张真实样品开始"}</h2><p>{items.length ? "可切换全部模型，或清除搜索与收藏筛选。" : "新建并粘贴画师串，或收藏下方已有的 Anima 参考组合。"}</p>{items.length > 0 && <button type="button" onClick={() => {setFamily("all"); setQuery(""); setOnlyFavorites(false);}}>清除筛选</button>}</div>}
        <div className="artist-presets-grid">{visible.map(item => {const sample = currentArtistSample(item) || item.samples[0]; return <article key={item.id} className={`artist-preset-card${editor?.original?.id === item.id ? " is-selected" : ""}`}>
          <button type="button" className="artist-preset-card-main" aria-label={`查看 ${item.name}`} disabled={!!busy} onClick={() => open(item)}>
            {sample ? <img src={sample.image_url} alt={`${item.name}的原提示词样品`} loading="lazy" /> : <span className="artist-preset-no-image"><Image size={30} />待补样品</span>}
            <span className="artist-preset-card-copy"><strong>{item.name}</strong><small>{artistPresetModelLabel(item)}</small><span className={`artist-preset-badge${item.ready ? " has-sample" : ""}`}>{item.ready ? "有当前样品" : "待补样品"}</span><code>{item.positive || item.negative}</code></span>
          </button><button type="button" className="artist-preset-favorite" aria-label={`${item.favorite ? "取消收藏" : "收藏"} ${item.name}`} aria-pressed={item.favorite} disabled={!!busy} onClick={() => favorite(item)}><Star weight={item.favorite ? "fill" : "regular"} /></button>
        </article>;})}</div>
        {suggestions.length > 0 && <details className="artist-preset-suggestions" open={items.length === 0}><summary>已有参考图中的 Anima 组合 · {suggestions.length} 组</summary><p>每组至少一张真实生成样品。画师串截取自原提示词；图片效果还受完整提示词和参数影响。</p>
          <div className="artist-presets-grid">{suggestions.map(item => <article key={item.reference_id} className="artist-preset-suggestion"><img src={item.thumbnail_url} alt={`${item.name}的参考样品`} loading="lazy" /><div><h3>{item.name}</h3><small>{item.model_label}</small><code>{item.positive}</code><p>{item.notes}</p><button type="button" disabled={!!busy} aria-label={`收藏 ${item.name}`} onClick={() => importReference(item)}>收藏画师串和样品</button></div></article>)}</div>
        </details>}
        {suggestionError && <p className="artist-presets-subtle">参考组合暂不可用：{suggestionError}</p>}
      </section>
      {editor && <aside className="artist-preset-editor library-scroll-panel" ref={panel} tabIndex={-1} aria-label="画师串编辑">
        <div className="artist-preset-editor-heading"><div><h2>{editor.original ? "编辑画师串" : "新建画师串"}</h2><small>{dirty || sampleDirty ? "有未保存修改" : editor.original ? `版本 ${editor.original.revision}` : "先保存，再添加样品"}</small></div><button type="button" aria-label="关闭编辑" disabled={!!busy} onClick={() => {if (guard()) {setEditor(null); resetSampleDraft();}}}><X /></button></div>
        <form onSubmit={save}><fieldset disabled={!!busy}>
          <label>名称<input required maxLength={200} value={editor.draft.name} onChange={event => change("name", event.target.value)} placeholder="给这一组风格起个名字" /></label>
          <div className="artist-preset-form-row"><label>适用模型<select value={editor.draft.model_family} onChange={event => change("model_family", event.target.value as ArtistModelFamily)}>{Object.entries(artistModelLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>具体模型 / 版本<input maxLength={200} value={editor.draft.model_label} onChange={event => change("model_label", event.target.value)} placeholder="如 anima-base-v1.0" /></label></div>
          <label>正向画师串原文<textarea rows={4} maxLength={20000} value={editor.draft.positive} onChange={event => change("positive", event.target.value)} placeholder="直接粘贴原串，保留权重、顺序和括号" spellCheck={false} /></label>
          <label>负向画师串原文<textarea rows={2} maxLength={20000} value={editor.draft.negative} onChange={event => change("negative", event.target.value)} placeholder="没有可留空" spellCheck={false} /></label>
          <div className="artist-preset-form-row"><label>权重语法<select value={editor.draft.syntax} onChange={event => change("syntax", event.target.value as ArtistPresetWrite["syntax"])}><option value="comfy">ComfyUI / 括号权重</option><option value="novelai">NovelAI</option><option value="plain">纯文本</option><option value="unknown">未注明</option></select></label><label className="artist-presets-check"><input type="checkbox" checked={editor.draft.favorite} onChange={event => change("favorite", event.target.checked)} />加入收藏</label></div>
          <details className="artist-preset-metadata"><summary>来源和备注</summary><label>分享者 / 作者<input maxLength={200} value={editor.draft.source_author} onChange={event => change("source_author", event.target.value)} /></label><label>来源链接<input type="url" maxLength={2000} value={editor.draft.source_url} onChange={event => change("source_url", event.target.value)} placeholder="https://…" /></label><label>备注<textarea rows={3} maxLength={10000} value={editor.draft.notes} onChange={event => change("notes", event.target.value)} /></label></details>
          <p className="artist-presets-subtle">原文逐字保存，不自动转换模型语法。修改原串或模型后，已有样品会保留并标为旧版。</p>
          <div className="artist-presets-actions"><button type="submit" className="is-primary" disabled={!editor.draft.name.trim() || !(editor.draft.positive.trim() || editor.draft.negative.trim())}>{busy === "保存画师串" ? "正在保存…" : "保存画师串"}</button>{editor.original && <><button type="button" disabled={dirty} onClick={() => exportLibrary(editor.original!.id)}>导出本条（含样品）</button><button type="button" onClick={deletePreset}>删除</button></>}</div>
        </fieldset></form>
        {editor.original && <>
          <Link className={`artist-preset-workbench-link${dirty || busy ? " is-disabled" : ""}`} aria-disabled={dirty || !!busy} to={`/workbench?artist_preset=${encodeURIComponent(editor.original.id)}`} onClick={event => {if (dirty || busy) {event.preventDefault(); setNotice("请先保存画师串，再到工作台调用。");}}}>在工作台调用这组画师串 →</Link>
          <section className="artist-preset-samples"><h3>样品 · {editor.original.samples.length} 张</h3><p className="artist-presets-subtle">原提示词生成样品，模型和参数来自来源声明或手动填写。上传图片不等于本机验证；缺少种子或工作流时无法保证复现。</p>
            {!editor.original.ready && <p className="artist-preset-sample-needed">待补样品：当前画师串版本还没有关联图片。</p>}
            {editor.original.samples.map(sample => <SampleDetails key={sample.id} sample={sample} current={sample.content_hash === editor.original!.content_hash} disabled={!!busy || dirty} onRemove={() => {
              if (!window.confirm("移除这张样品？")) return;
              void action("移除样品", async () => {adopt(await artistPresetsApi.removeSample(editor.original!.id, sample.id, editor.original!.revision)); setNotice("样品已移除。");});
            }} />)}
            <SampleUpload key={`${editor.original.id}:${editor.original.content_hash}:${sampleReset}`} preset={editor.original} disabled={!!busy || dirty} onDirtyChange={setSampleDirty} onUpload={(file, value) => action("上传样品", async () => {adopt(await artistPresetsApi.uploadSample(editor.original!.id, file, value, editor.original!.revision)); setNotice("样品已保存，已关联当前画师串版本。");})} />
            {dirty && <p className="artist-presets-subtle">请先保存修改，再上传或移除样品。</p>}
          </section>
        </>}
      </aside>}
    </div>
  </div>;
}

function SampleDetails({sample, current, disabled, onRemove}: {sample: ArtistPresetSample; current: boolean; disabled: boolean; onRemove: () => void}) {
  const source = externalUrl(sample.source_url);
  return <article className="artist-preset-sample"><a href={sample.image_url} target="_blank" rel="noreferrer" aria-label="打开样品原图"><img src={sample.image_url} alt={sample.caption || "原提示词生成样品"} loading="lazy" /></a>
    <div className="artist-preset-sample-heading"><span className="artist-preset-badge">{current ? "当前版本样品" : "旧版样品"}</span><button type="button" disabled={disabled} onClick={onRemove}>移除样品</button></div>
    <p>{sample.caption || "原提示词生成样品"}</p><small>{sample.model_label || "样品模型未注明"} · 图片 {sample.width} × {sample.height}</small>
    <details><summary>完整提示词与生成参数</summary><dl><dt>正向提示词</dt><dd><pre>{sample.full_positive || "未提供"}</pre></dd><dt>负向提示词</dt><dd><pre>{sample.full_negative || "未提供"}</pre></dd><dt>来源参数</dt><dd><pre>{Object.keys(sample.parameters).length ? JSON.stringify(sample.parameters, null, 2) : "未提供"}</pre></dd></dl><p>未列出的参数均未知。图中构图、角色和细节来自完整提示词，不能归因于画师串本身。</p>{source && <a href={source} target="_blank" rel="noreferrer">查看样品来源 ↗</a>}</details>
  </article>;
}

function SampleUpload({preset, disabled, onUpload, onDirtyChange}: {preset: ArtistPreset; disabled: boolean; onUpload: (file: File, metadata: ArtistSampleWrite) => Promise<boolean>; onDirtyChange: (dirty: boolean) => void}) {
  const form = useRef<HTMLFormElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [model, setModel] = useState(preset.model_label);
  const [caption, setCaption] = useState(""); const [source, setSource] = useState("");
  const [positive, setPositive] = useState(""); const [negative, setNegative] = useState("");
  const [parameters, setParameters] = useState(""); const [error, setError] = useState("");
  const dirty = !!file || model !== preset.model_label || !!(caption || source || positive || negative || parameters);
  useEffect(() => {onDirtyChange(dirty);}, [dirty, onDirtyChange]);
  const submit = (event: FormEvent) => {
    event.preventDefault(); if (!file) return;
    if (file.size > 20 * 1024 * 1024) {setError("图片不能超过 20 MB。"); return;}
    let parsed: Record<string, unknown> = {};
    try {if (parameters.trim()) {const value: unknown = JSON.parse(parameters, (_key, value: unknown) => {
      if (typeof value === "number" && (!Number.isFinite(value) || (Number.isInteger(value) && !Number.isSafeInteger(value)))) throw new Error("大整数参数（例如 64 位种子）请用双引号包成字符串，避免精度丢失。");
      return value;
    }); if (!value || Array.isArray(value) || typeof value !== "object") throw new Error(); parsed = value as Record<string, unknown>;}}
    catch (cause) {setError(cause instanceof Error && cause.message.includes("双引号") ? cause.message : "生成参数应为 JSON 对象，例如 {\"steps\": 28, \"cfg\": 4}。"); return;}
    setError(""); void onUpload(file, {caption, model_label: model, source_url: source, full_positive: positive, full_negative: negative, parameters: parsed}).then(saved => {
      if (!saved) return;
      form.current?.reset(); setFile(null); setModel(preset.model_label); setCaption(""); setSource(""); setPositive(""); setNegative(""); setParameters(""); onDirtyChange(false);
    });
  };
  return <details className="artist-preset-upload"><summary>添加一张样品</summary><form ref={form} onSubmit={submit}><fieldset disabled={disabled}><label>样品图片<input type="file" accept="image/png,image/jpeg,image/webp" required onChange={event => {setFile(event.target.files?.[0] || null); setError("");}} /></label><p className="artist-presets-subtle">PNG、JPEG 或 WebP，最多 20 MB。请上传这组画师串实际参与生成的图片。</p><label>样品使用的具体模型<input maxLength={200} value={model} onChange={event => setModel(event.target.value)} placeholder="不清楚可留空" /></label><label>样品说明<input maxLength={2000} value={caption} onChange={event => setCaption(event.target.value)} /></label><label>样品来源链接<input type="url" maxLength={2000} value={source} onChange={event => setSource(event.target.value)} /></label><details><summary>补充原图完整提示词和参数</summary><label>样品完整正向提示词<textarea rows={4} maxLength={40000} value={positive} onChange={event => setPositive(event.target.value)} /></label><label>样品完整负向提示词<textarea rows={2} maxLength={40000} value={negative} onChange={event => setNegative(event.target.value)} /></label><label>生成参数（JSON，可留空）<textarea rows={3} value={parameters} onChange={event => setParameters(event.target.value)} placeholder={'{"steps": 28, "cfg": 4, "seed": "1234"}'} /></label></details>{error && <p role="alert">{error}</p>}<button type="submit" disabled={!file}>保存样品</button></fieldset></form></details>;
}

function ArtistPresetImport({onClose, onImported}: {onClose: () => void; onImported: (items: ArtistPreset[]) => void}) {
  const [document, setDocument] = useState<unknown>(null); const [preview, setPreview] = useState<ArtistPresetImportPreview | null>(null);
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false); const [name, setName] = useState("");
  async function choose(file: File | undefined) {
    setDocument(null); setPreview(null); setError(""); if (!file) return;
    if (file.size > 50 * 1024 * 1024) {setError("备份文件不能超过 50 MB。"); return;}
    setBusy(true); setName(file.name);
    try {const value: unknown = JSON.parse(await file.text()); const result = await artistPresetsApi.previewImport(value); setDocument(value); setPreview(result);}
    catch (cause) {setError(errorMessage(cause));} finally {setBusy(false);}
  }
  async function commit() {
    if (!preview || !document || busy) return; setBusy(true); setError("");
    try {const result = await artistPresetsApi.import(document, preview.token); onImported(result.items); setPreview(null); setDocument(null); setName(""); onClose();}
    catch (cause) {setError(errorMessage(cause));} finally {setBusy(false);}
  }
  return <section className="artist-preset-import" aria-label="导入画师串备份"><div className="artist-preset-editor-heading"><h2>导入画师串备份</h2><button type="button" disabled={busy} onClick={onClose}>关闭</button></div><p>读取本工具导出的 JSON，包含画师串和样品图片。先预览，再导入；已有同内容条目会跳过。</p><label>选择 JSON 备份<input type="file" accept=".json,application/json" disabled={busy} onChange={event => void choose(event.target.files?.[0])} /></label>{busy && <p role="status">正在处理备份…</p>}{error && <p role="alert">{error}</p>}{preview && <><p>{name} · {preview.items.length} 条 · {preview.duplicates} 条重复</p><ul>{preview.items.map((item, index) => <li key={index}>{item.name} · {item.model_label || "模型未注明"} · {item.sample_count || 0} 张样品</li>)}</ul>{preview.warnings.map((warning, index) => <p key={index}>{warning}</p>)}<button type="button" className="is-primary" disabled={busy} onClick={() => void commit()}>确认导入</button></>}</section>;
}
