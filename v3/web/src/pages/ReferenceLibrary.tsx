import {useEffect, useRef, useState} from "react";
import {ImagePreview} from "../components/ImagePreview";
import {apiRequest} from "../lib/api";
import {layerLabels, cleanRequirements} from "../lib/conversation";
import {ReferenceRequirementsEditor} from "./ReferenceRequirementsEditor";
import type {ConversationRecord, LayerName, RequirementsEdit} from "../lib/conversation";

export type Example = {id: string; title: string; revision: number | null; source_version: string;
  origin?: string; override_revision?: number; analysis_source?: "image" | "prompt";
  requirements_valid: boolean; requirements: RequirementsEdit | null; ingest_state: string;
  notes: {external_prompt: string; user_notes: string; source_url: string};
  provenance?: {positive?: string; negative?: string; model_profile?: string; settings?: Record<string, unknown>; run_id?: string} | null};
type Page = {items: Example[]; next_cursor: string | null; official_pack: {ready: boolean}};
export type Role = "style" | "lighting" | "composition" | "whole_scene";

export function ReferenceLibrary({record, disabled = false, onPin, onUnpin, standalone = false, exampleId, onStart}: {
  record?: ConversationRecord; disabled?: boolean; standalone?: boolean; exampleId?: string;
  onPin?: (example: Example, role: Role) => Promise<void>; onUnpin?: () => Promise<void>;
  onStart?: (example: Example, mode: "requirements" | "generation", role: Role) => Promise<void>;
}) {
  const [page, setPage] = useState<Page | null>(null);
  const [selected, setSelected] = useState<Example | null>(null);
  const [role, setRole] = useState<Role>("style");
  const [query, setQuery] = useState("");
  const [origin, setOrigin] = useState("");
  const [loadedFilter, setLoadedFilter] = useState("");
  const [previewOpen, setPreviewOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [sendNotes, setSendNotes] = useState(false);
  const [removeConfirm, setRemoveConfirm] = useState(false);
  const [savedRequirements, setSavedRequirements] = useState("null");
  const [savedNotes, setSavedNotes] = useState("");
  const [savedTitle, setSavedTitle] = useState("");
  const lock = useRef(false);
  const title = useRef<HTMLInputElement>(null);
  const file = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (standalone) void act(async () => {await load(); if (exampleId) choose(await apiRequest<Example>(`/api/v3/reference-examples/${encodeURIComponent(exampleId)}`));});
  }, [standalone, exampleId]);

  async function act(action: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setMessage("");
    try {await action();} catch (error) {setMessage((error as Error).message);}
    finally {lock.current = false; setBusy(false);}
  }
  async function load(cursor?: string) {
    const params = new URLSearchParams({q: query, limit: "20", ...(origin ? {origin} : {}), ...(cursor ? {cursor} : {})});
    const next = await apiRequest<Page>(`/api/v3/reference-examples?${params}`);
    setPage(previous => cursor && previous ? {...next, items: [...previous.items, ...next.items]} : next);
    setLoadedFilter(JSON.stringify([query, origin]));
  }
  function choose(example: Example) {setSelected(example); setSavedTitle(example.title); setSavedRequirements(JSON.stringify(example.requirements)); setSavedNotes(JSON.stringify(example.notes)); setSendNotes(false); setRemoveConfirm(false); setPreviewOpen(false);}
  const requirementsDirty = Boolean(selected && JSON.stringify(selected.requirements) !== savedRequirements);
  const notesDirty = Boolean(selected && (JSON.stringify(selected.notes) !== savedNotes || selected.title !== savedTitle));
  const copied: LayerName[] = role === "whole_scene" ? Object.keys(layerLabels) as LayerName[] : [role];
  if (role === "style" && selected?.requirements) {
    for (const name of ["lighting", "composition"] as const)
      if (selected.requirements.layers[name].include_with_style_pin) copied.push(name);
  }
  const overwritten = copied.filter(name => !record?.draft.requirements?.layers[name].locked);

  const content = <>
    <fieldset disabled={busy}>
      <div className="conversation-actions"><label>搜索收藏<input value={query} maxLength={200} onChange={event => setQuery(event.target.value)} /></label>
        <button onClick={() => void act(() => load())}>搜索 / 刷新</button></div>
      {standalone && <label>案例来源<select value={origin} onChange={event => setOrigin(event.target.value)}><option value="">全部来源</option><option value="session_pin">生成记录</option><option value="gallery_keep">画廊图片</option><option value="upload">上传图片</option><option value="official">内置样例</option></select></label>}
      <div className="conversation-actions"><label>图片标题<input ref={title} maxLength={200} /></label>
        <label>参考图片<input ref={file} type="file" accept="image/png,image/jpeg,image/webp" /></label>
        <button disabled={requirementsDirty || notesDirty} onClick={() => void act(async () => {
          const image = file.current?.files?.[0];
          if (!image || !title.current?.value.trim()) throw new Error("请选择图片并填写标题。");
          if (image.size > 20 * 1024 * 1024) throw new Error("图片不能超过 20 MB。");
          const form = new FormData(); form.append("file", image); form.append("title", title.current.value.trim());
          const example = await apiRequest<Example>("/api/v3/reference-examples", {method: "POST", body: form});
          choose(example); await load();
        })}>保存参考图</button></div>
      {page && !page.official_pack.ready && <div className="conversation-actions">
        <p className="conversation-muted">可安装内置的木刻、炭笔与水彩样例，也可以上传自己的参考图。</p>
        <button onClick={() => void act(async () => {
          await apiRequest("/api/v3/reference-examples/install-bundled", {method: "POST", body: JSON.stringify({})});
          await load(); setMessage("内置样例已就绪，可以选择参考并复制风格要求。");
        })}>安装内置样例</button>
      </div>}
      {page && !page.items.length && <p>没有找到案例，可以上传参考图，或从画廊存入案例库。</p>}
      {(requirementsDirty || notesDirty) && <p>当前案例有未保存修改，保存或重新加载后再切换案例。</p>}
      <div className="reference-cards">{page?.items.map(example => <button key={example.id} disabled={requirementsDirty || notesDirty} aria-pressed={selected?.id === example.id} onClick={() => choose(example)}>
        <img src={`/api/v3/gallery/reference-examples/${example.id}/thumbnail`} alt={example.title} loading="lazy" />
        <span>{example.title}</span><small>{example.requirements_valid ? "已有要求" : "待分析或编辑"}</small></button>)}</div>
      {page?.next_cursor && <button disabled={loadedFilter !== JSON.stringify([query, origin])} onClick={() => void act(() => load(page.next_cursor!))}>加载更多</button>}
      {selected && <section className="reference-detail">
        {standalone && <><button className="reference-image-open" onClick={() => setPreviewOpen(true)} aria-label="预览案例原图"><img src={`/api/v3/gallery/reference-examples/${selected.id}/thumbnail?size=640`} alt={selected.title} /></button>
          <p>案例版本：{selected.source_version} · {selected.provenance?.run_id ? "来自生成记录" : "参考素材"}</p>
          {selected.provenance && <details><summary>原图提示词与参数</summary><h3>正向提示词</h3><p>{selected.provenance.positive || "未记录"}</p><h3>负向提示词</h3><p>{selected.provenance.negative || "空"}</p><p>模型：{selected.provenance.model_profile || "未记录"}</p><dl>{Object.entries(selected.provenance.settings || {}).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}</dl></details>}</>}
        <button onClick={() => void act(async () => choose(await apiRequest<Example>(`/api/v3/reference-examples/${selected.id}`)))}>重新加载此参考（放弃未保存修改）</button>
        <label>收藏标题<input readOnly={selected.origin === "official"} value={selected.title} maxLength={200} onChange={event => setSelected({...selected, title: event.target.value})} /></label>
        <label>我的笔记<textarea value={selected.notes.user_notes} maxLength={20000} onChange={event => setSelected({...selected, notes: {...selected.notes, user_notes: event.target.value}})} /></label>
        <label>来源地址<input value={selected.notes.source_url} maxLength={2000} onChange={event => setSelected({...selected, notes: {...selected.notes, source_url: event.target.value}})} /></label>
        <label>外部提示词<textarea value={selected.notes.external_prompt} maxLength={20000} onChange={event => setSelected({...selected, notes: {...selected.notes, external_prompt: event.target.value}})} /></label>
        <button disabled={requirementsDirty} onClick={() => void act(async () => {const official = selected.origin === "official";
          const saved = await apiRequest<Example>(`/api/v3/reference-examples/${selected.id}${official ? "/notes" : ""}`, {
          method: "PATCH", body: JSON.stringify(official ? {override_revision: selected.override_revision || 0, notes: selected.notes}
            : {revision: selected.revision, title: selected.title, notes: selected.notes})}); choose(saved); await load();})}>{selected.origin === "official" ? "保存我的笔记" : "保存标题与笔记"}</button>
        {selected.origin === "official" ? <button disabled={notesDirty || requirementsDirty} onClick={() => void act(async () => {
          const copied = await apiRequest<Example>(`/api/v3/reference-examples/${selected.id}/copy`, {method: "POST", body: JSON.stringify({source_version: selected.source_version})});
          choose(copied); await load();
        })}>复制为我的参考</button> : <>
        <p>优先从原始提示词提取要求，也可以直接手动编辑。请在外部提示词中明确区分正向与负向内容。</p>
        {notesDirty && <p>请先保存标题与笔记，再开始分析。</p>}
        <button disabled={requirementsDirty || notesDirty || !selected.notes.external_prompt.trim()} onClick={() => void act(async () => {
          const saved = await apiRequest<Example & {warnings: string[]}>(`/api/v3/reference-examples/${selected.id}/ingest`, {
            method: "POST", body: JSON.stringify({revision: selected.revision, source: "prompt"})});
          choose(saved); await load(); setMessage(saved.warnings.join("；") || "提示词已提取，请核对要求。");
        })}>从提示词提取要求（不发送图片）</button>
        <details><summary>辅助：读图建议</summary>
        <p>读图结果仅供参考，可能误判动作、材质或风格。分析会更新未锁定的参考要求，请核对和修正后再钉选。</p>
        <label><input type="checkbox" checked={sendNotes} onChange={event => setSendNotes(event.target.checked)} />分析时发送已保存的外部提示词</label>
        <button disabled={requirementsDirty || notesDirty} onClick={() => void act(async () => {const saved = await apiRequest<Example & {warnings: string[]}>(`/api/v3/reference-examples/${selected.id}/ingest`, {
          method: "POST", body: JSON.stringify({revision: selected.revision, use_external_prompt_notes: sendNotes})}); choose(saved); await load(); setMessage(["读图建议已生成，仅供参考，请核对和修正后再钉选。", ...saved.warnings].join("；"));})}>分析图片（调用当前视觉模型）</button></details></>}
        {selected.analysis_source && <p>{selected.analysis_source === "prompt" ? "上次分析来源：提示词文字，未核对图片。" : "上次分析来源：图片。"}</p>}
        {selected.requirements && <dl>{(Object.keys(layerLabels) as LayerName[]).map(name => <div key={name}><dt>{layerLabels[name]}</dt><dd>{name === "exclusions"
          ? selected.requirements!.layers.exclusions.global.join("、") || "无全局排除"
          : selected.requirements!.layers[name].text || "未填写"}</dd></div>)}</dl>}
        {selected.origin !== "official" && <><ReferenceRequirementsEditor value={selected.requirements} onChange={value => setSelected({...selected,requirements:value})} />
          {requirementsDirty && <p>参考要求尚未保存；保存后才能分析或钉选。</p>}
          <button disabled={!requirementsDirty || !selected.requirements} onClick={() => void act(async () => {
            const saved = await apiRequest<Example>(`/api/v3/reference-examples/${selected.id}`, {method:"PATCH",body:JSON.stringify({
              revision:selected.revision,title:selected.title,notes:selected.notes,requirements_edit:cleanRequirements({layers:selected.requirements!.layers,loras:selected.requirements!.loras})})});
            choose(saved); await load();
          })}>保存参考要求</button></>}
        <label>复制用途<select value={role} onChange={event => setRole(event.target.value as Role)}><option value="style">风格</option><option value="lighting">光影</option><option value="composition">构图</option><option value="whole_scene">完整场景</option></select></label>
        {!standalone && <p>将覆盖：{overwritten.map(name => layerLabels[name]).join("、") || "无（所选层均已锁定）"}。已锁层保持原样。</p>}
        <p>{standalone ? "借用要求时携带的 LoRA：" : "将替换当前全部 LoRA 为："}{selected.requirements?.loras.filter(item => item.required).map(item => `${item.file_name} (${item.weight})`).join("、") || "无 LoRA"}。</p>
        {disabled && <p>请先处理未提交的输入或工作台冲突，再钉选参考。</p>}
        {standalone ? <div className="reference-start-actions"><p>在新会话中继续，当前工作台和未保存草稿会保留。借用要求不携带原图参数；沿用生成条件会保留原任务的模型、参数与工作流快照。</p>
          <button disabled={requirementsDirty || notesDirty || !selected.requirements_valid} onClick={() => void act(() => onStart!(selected, "requirements", role))}>借用要求，新建会话</button>
          <button disabled={requirementsDirty || notesDirty || !selected.provenance?.run_id} onClick={() => void act(() => onStart!(selected, "generation", role))}>沿用生成条件，新建会话</button>
          {!selected.provenance?.run_id && <p>此案例没有原始生成快照，可查看已记录参数并借用创作要求。</p>}
        </div> : <button disabled={disabled || requirementsDirty || notesDirty || !selected.requirements_valid} onClick={() => void act(() => onPin!(selected, role))}>复制并钉选</button>}
        {selected.origin !== "official" && <><label><input type="checkbox" checked={removeConfirm} onChange={event => setRemoveConfirm(event.target.checked)} />移除此收藏</label>
        <button disabled={!removeConfirm} onClick={() => void act(async () => {await apiRequest<void>(`/api/v3/reference-examples/${selected.id}`, {method: "DELETE", body: JSON.stringify({revision: selected.revision})}); setSelected(null); await load();})}>确认移除收藏</button></>}
      </section>}
      {record?.draft.reference_pin && <button disabled={disabled} onClick={() => void act(onUnpin!)}>解除当前来源（保留已复制要求）</button>}
    </fieldset>
    {message && <p role="status">{message}</p>}
    {previewOpen && selected && <ImagePreview index={0} onClose={() => setPreviewOpen(false)} images={[{src: `/api/v3/gallery/reference-examples/${selected.id}/content`, alt: selected.title, positive: selected.provenance?.positive, negative: selected.provenance?.negative, parameters: selected.provenance?.settings}]} />}
  </>;
  return standalone ? <section className="reference-library reference-library-page">{content}</section> : <details className="reference-library" onToggle={event => {if (event.currentTarget.open && !page) void act(() => load());}}><summary>参考收藏 · 上传、分析与钉选</summary>{content}</details>;
}
