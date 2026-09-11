import {ImagePreview} from "../components/ImagePreview";
import {ArtistRecommendations} from "../components/ArtistRecommendations";
import {loadGallery} from "../lib/galleryStore";
import type {GalleryAsset} from "../lib/types";
import {useEffect, useRef, useState} from "react";
import {Link, useSearchParams} from "react-router-dom";
import {ChatCircleDots, Check, Copy, GearSix, ImageSquare, PaperPlaneRight, Plus, SlidersHorizontal, Sparkle} from "@phosphor-icons/react";
import {apiRequest, ApiClientError} from "../lib/api";
import {seedInput, applyGenerationRecipe, defaultGenerationSettings, markGenerationCustom, resolvedGenerationSettings} from "../lib/generationSettings";
import {modelProfileChoices, LEGACY_AESTHETIC, resolveLegacyAesthetic} from "../lib/modelProfiles";
import {negativeGuidance, appendNegative} from "../lib/negativeGuidance";
import {cleanRequirements, editableRequirements, hasUncompiledInputs, hasUnsavedInputs, layerLabels} from "../lib/conversation";
import "./conversationWorkbench.css";
import {LlmSettingsPanel} from "../components/LlmSettingsPanel";
import {LoraMappingPanel, type ResourceIdentity} from "./LoraMappingPanel";
import type {ConversationRecord, LayerName, LocalConversation, RequirementLayers} from "../lib/conversation";
import type {GenerationRunRecord, GenerationTarget, GenerationTargetListResponse, ModelProfileOption, WorkspaceListResponse} from "../lib/types";

const ACTIVE = "anima-conversation-active";
const draftKey = (id: string) => `anima-conversation-draft:${id}`;
const pendingKey = (id: string) => `anima-conversation-submission:${id}`;
type Pending = {key: string; body: string};
type Accepted = GenerationRunRecord & {workspace_revision: number; compiled_token: string};
function read<T>(key: string): T | null {try {return JSON.parse(localStorage.getItem(key) || "null") as T | null;} catch {return null;}}
function write(key: string, value: unknown) {try {localStorage.setItem(key, JSON.stringify(value));} catch { /* Server remains authoritative. */ }}
function remove(key: string) {try {localStorage.removeItem(key);} catch { /* Best effort. */ }}
function localFrom(record: ConversationRecord): LocalConversation {
  return {baseRevision: record.revision, delta: "", requirements: editableRequirements(record), mode: record.draft.mode,
    positive: record.draft.compiled?.positive || "", negative: record.draft.compiled?.negative || "",
    model: record.draft.model_profile, settings: record.draft.generation_settings || defaultGenerationSettings()};
}

export function ConversationWorkbenchPage({modelProfiles, remoteEnabled = false}: {modelProfiles?: ModelProfileOption[]; remoteEnabled?: boolean}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedWorkspace = searchParams.get("workspace");
  const [record, setRecord] = useState<ConversationRecord | null>(null);
  const current = useRef<ConversationRecord | null>(null);
  const [local, setLocal] = useState<LocalConversation | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceListResponse["items"]>([]);
  const [targets, setTargets] = useState<GenerationTarget[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [showLlmSettings, setShowLlmSettings] = useState(false);
  const [inspectorTab, setInspectorTab] = useState<"prompt" | "requirements" | "settings">("prompt");
  const [idea, setIdea] = useState("");
  const [copied, setCopied] = useState("");
  const [comparison, setComparison] = useState<{before: {positive: string; negative: string}; after: {positive: string; negative: string}} | null>(null);
  const [conflict, setConflict] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [run, setRun] = useState<GenerationRunRecord | null>(null);
  const [recentRuns, setRecentRuns] = useState<GenerationRunRecord[]>([]);
  const [availability, setAvailability] = useState<{availability: string; message?: string; resource_requirements?: ResourceIdentity[]} | null>(null);
  const [mappingEpoch, setMappingEpoch] = useState(0);
  const opening = useRef(0);
  const requestLock = useRef(false);
  const mounted = useRef(true);
  const resultsPanel = useRef<HTMLElement>(null);
  const profiles = modelProfileChoices(modelProfiles);
  useEffect(() => {
    if (!local || pending || busy) return;
    const model = resolveLegacyAesthetic(local.model, local.settings, targets);
    if (model !== local.model) edit({model});
  }, [local, targets, pending, busy]);

  function adopt(next: ConversationRecord, preserve = false) {
    if (!mounted.current) return;
    if (current.current?.id === next.id && current.current.revision > next.revision) return;
    current.current = next;
    setRecord(next);
    setCopied("");
    if (!preserve) {
      const value = localFrom(next);
      setLocal(value);
      write(draftKey(next.id), value);
      setConflict(false);
    }
  }

  async function open(id: string) {
    const sequence = ++opening.current;
    setBusy("打开工作台"); setError("");
    try {
      const next = await apiRequest<ConversationRecord>(`/api/v3/workspaces/${encodeURIComponent(id)}`);
      if (!mounted.current || sequence !== opening.current) return;
      const recovered = read<LocalConversation>(draftKey(id));
      adopt(next);
      setWorkspaces(items => items.some(item => item.id === next.id) ? items : [next, ...items]);
      if (recovered) {
        setLocal(recovered);
        write(draftKey(id), recovered);
        setConflict(recovered.baseRevision !== next.revision);
      }
      setPending(read<Pending>(pendingKey(id)));
      setRun(null); setRecentRuns([]); setAvailability(null); setComparison(null);
      write(ACTIVE, id);
      if (requestedWorkspace && requestedWorkspace !== id) clearWorkspaceLink();
    } catch (caught) {if (mounted.current && sequence === opening.current) setError((caught as Error).message);}
    finally {if (mounted.current && sequence === opening.current) setBusy("");}
  }

  useEffect(() => {
    mounted.current = true;
    void apiRequest<WorkspaceListResponse>("/api/v3/workspaces?limit=50").then(result => {
      if (!mounted.current) return;
      setWorkspaces(result.items);
      const id = requestedWorkspace || read<string>(ACTIVE);
      if (id && current.current?.id !== id) void open(id);
    }).catch(caught => {if (mounted.current) setError((caught as Error).message);});
    if (remoteEnabled) void apiRequest<GenerationTargetListResponse>("/api/v3/generation-targets").then(result => {
      if (mounted.current) setTargets(result.items);
    }).catch(caught => {if (mounted.current) setError((caught as Error).message);});
    return () => {mounted.current = false; opening.current++;};
  }, [remoteEnabled, requestedWorkspace]);

  const dirty = Boolean(record && local && hasUnsavedInputs(record, local));
  const compileInputsChanged = Boolean(record && local && hasUncompiledInputs(record, local));
  const needsCompile = compileInputsChanged || record?.draft.compile_state !== "fresh";
  const canCompileRequirements = Boolean(local && [local.requirements.layers.subject.text, local.requirements.layers.style.text,
    local.requirements.layers.style.medium, ...local.requirements.layers.style.artists, local.requirements.layers.lighting.text,
    local.requirements.layers.composition.text, local.requirements.layers.composition.shot].some(value => value.trim()));
  const target = local && local.model !== LEGACY_AESTHETIC ? targets.find(item => item.remote_profile_id === local.settings.remote_profile_id
    && item.workflow_profile_id === local.settings.workflow_profile_id && item.compatible_model_profiles.includes(local.model)) : undefined;

  useEffect(() => {
    if (!record || !target || dirty || conflict) {setAvailability(null); return;}
    const controller = new AbortController();
    setAvailability(null);
    const query = new URLSearchParams({workspace_id: record.id, revision: String(record.revision),
      remote_profile_id: target.remote_profile_id, workflow_profile_id: target.workflow_profile_id});
    if (record.draft.generation_source) query.set("workflow_snapshot_run_id", record.draft.generation_source.run_id);
    void apiRequest<{availability: string; message?: string}>(`/api/v3/workbench/availability?${query}`, {signal: controller.signal})
      .then(value => {if (!controller.signal.aborted) setAvailability(value);})
      .catch(caught => {if (!controller.signal.aborted) setAvailability({availability: "unknown", message: (caught as Error).message});});
    return () => controller.abort();
  }, [record, target, dirty, conflict, mappingEpoch]);

  useEffect(() => {
    if (!record) return;
    const controller = new AbortController();
    let timer = 0;
    async function poll() {
      try {
        const result = await apiRequest<{items: GenerationRunRecord[]}>(`/api/v3/workspaces/${record!.id}/runs?limit=20`, {signal: controller.signal});
        if (controller.signal.aborted) return;
        setRecentRuns(result.items);
        setRun(previous => result.items.find(item => item.id === previous?.id) || result.items[0] || null);
      } catch (caught) {if (!controller.signal.aborted) setError((caught as Error).message);}
      if (!controller.signal.aborted) timer = window.setTimeout(() => void poll(), 3000);
    }
    void poll();
    return () => {controller.abort(); window.clearTimeout(timer);};
  }, [record?.id]);

  function edit(patch: Partial<LocalConversation>) {
    if (!local || !record) return;
    const value = {...local, ...patch}; setLocal(value); write(draftKey(record.id), value);
  }
  function clearWorkspaceLink() {
    setSearchParams(previous => {const next = new URLSearchParams(previous); next.delete("workspace"); return next;}, {replace: true});
  }
  function layer<K extends LayerName>(name: K, patch: Partial<RequirementLayers[K]>) {
    if (local) edit({requirements: {...local.requirements, layers: {...local.requirements.layers,
      [name]: {...local.requirements.layers[name], ...patch}}}});
  }
  async function act(label: string, action: () => Promise<void>) {
    if (requestLock.current) return;
    requestLock.current = true; setBusy(label); setError("");
    try {await action();}
    catch (caught) {
      if (!mounted.current) return;
      setError((caught as Error).message);
      if (caught instanceof ApiClientError && caught.code === "workspace_revision_conflict" && current.current) {
        setConflict(true);
        try {adopt(await apiRequest<ConversationRecord>(`/api/v3/workspaces/${current.current.id}`), true);} catch { /* Keep local edits. */ }
      }
    } finally {requestLock.current = false; if (mounted.current) setBusy("");}
  }
  async function create(initialIdea = "") {
    await act("创建工作台", async () => {
      const next = await apiRequest<ConversationRecord>("/api/v3/workspaces", {method: "POST", body: JSON.stringify({
        title: initialIdea.trim().slice(0, 40) || "会话创作", draft: {model_profile: profiles.find(p => p.id === "anima_aesthetic_v1_1")?.id || profiles[0].id, generation_settings: defaultGenerationSettings()}})});
      adopt(next); write(ACTIVE, next.id); setWorkspaces(items => [next, ...items]); setPending(null); setRun(null); setRecentRuns([]);
      if (requestedWorkspace) clearWorkspaceLink();
      if (initialIdea.trim()) {
        const value = {...localFrom(next), delta: initialIdea};
        setLocal(value); write(draftKey(next.id), value);
      }
      setInspectorTab("prompt"); setComparison(null);
    });
  }
  async function continueRun(source: GenerationRunRecord) {
    await act("从生成记录创建会话", async () => {
      const next = await apiRequest<ConversationRecord>(`/api/v3/generation-runs/${encodeURIComponent(source.id)}/workspace`, {method: "POST", body: JSON.stringify({})});
      adopt(next); write(ACTIVE, next.id); setWorkspaces(items => [next, ...items]);
      setPending(null); setRun(null); setRecentRuns([]); setAvailability(null); setComparison(null); setInspectorTab("prompt");
      if (requestedWorkspace) clearWorkspaceLink();
    });
  }
  async function save(tentativeMode = false): Promise<ConversationRecord> {
    if (!record || !local) throw new Error("请先打开工作台。");
    const next = await apiRequest<ConversationRecord>(`/api/v3/workspaces/${record.id}`, {method: "PUT", body: JSON.stringify({
      revision: record.revision, title: record.title, draft: {model_profile: local.model, mode: tentativeMode ? record.draft.mode : local.mode,
        requirements_edit: cleanRequirements(local.requirements), generation_settings: local.settings}})});
    adopt(next, true);
    const kept = {...local, requirements: editableRequirements(next), baseRevision: next.revision}; setLocal(kept); write(draftKey(next.id), kept);
    return next;
  }
  async function turn(recompile: boolean) {
    if (!record || !local || conflict) return;
    await act(recompile ? "重新编译" : "发送修改", async () => {
      const saved = hasUnsavedInputs(record, {...local, mode: record.draft.mode}) ? await save(true) : record;
      const next = await apiRequest<ConversationRecord>("/api/v3/workbench/turns", {method: "POST", body: JSON.stringify({
        workspace_id: saved.id, revision: saved.revision, mode: local.mode, delta: {text: recompile ? "" : local.delta},
        ...(local.positive.trim() ? {compiled: {positive: local.positive, negative: local.negative}} : {})})});
      setComparison({before: {positive: local.positive, negative: local.negative}, after: {positive: next.draft.compiled?.positive || "", negative: next.draft.compiled?.negative || ""}});
      adopt(next); setInspectorTab("prompt");
    });
  }
  async function generate(retry = false) {
    if (!record || !local) return;
    await act("提交生成", async () => {
      const request = retry && pending ? pending : {key: crypto.randomUUID(), body: JSON.stringify({
        submission_kind: "conversational", workspace_id: record.id, workspace_revision: record.revision,
        compiled_token: record.draft.compiled?.compiled_token, positive_prompt: local.positive, negative_prompt: local.negative,
        model_profile: local.model, remote_profile_id: target?.remote_profile_id, workflow_profile_id: target?.workflow_profile_id,
        ...(record.draft.generation_source ? {workflow_snapshot_run_id: record.draft.generation_source.run_id} : {}),
        settings: resolvedGenerationSettings(local.settings)})};
      setPending(request); write(pendingKey(record.id), request);
      let accepted: Accepted;
      try {accepted = await apiRequest<Accepted>("/api/v3/direct-prompt/runs", {method: "POST", body: request.body,
        headers: {"Idempotency-Key": request.key}});}
      catch (caught) {
        if (caught instanceof ApiClientError && !["network_error", "internal_error"].includes(caught.code)) {
          setPending(null); remove(pendingKey(record.id));
        }
        throw caught;
      }
      setPending(null); remove(pendingKey(record.id)); setRun(accepted);
      setRecentRuns(items => [accepted, ...items.filter(item => item.id !== accepted.id)]);
      resultsPanel.current?.scrollIntoView?.({block: "start", behavior: "smooth"});
      const submitted = JSON.parse(request.body) as {positive_prompt: string; negative_prompt: string};
      // Retain the new token even if the following read fails.
      const next = {...record, revision: accepted.workspace_revision, draft: {...record.draft,
        compiled: {...record.draft.compiled!, positive: submitted.positive_prompt, negative: submitted.negative_prompt, compiled_token: accepted.compiled_token}}};
      adopt(next);
      adopt(await apiRequest<ConversationRecord>(`/api/v3/workspaces/${record.id}`));
    });
  }

  const promptChanged = Boolean(local && (local.positive !== (record?.draft.compiled?.positive || "") || local.negative !== (record?.draft.compiled?.negative || "")));
  const generationReason = busy ? `${busy}…` : pending ? "请先确认上次提交的结果" : conflict ? "请先处理版本冲突"
    : local?.model === LEGACY_AESTHETIC ? "旧美学配置版本不明，请在生成设置中选择 v1.0 或 v1.1"
    : local?.delta.trim() ? "有未发送的修改，先发送或清空输入" : dirty ? (compileInputsChanged ? "要求已修改，更新提示词后再生成" : "生成设置尚未保存；保存后即可生成，无需重新编译")
    : record?.draft.compile_state !== "fresh" ? "请先生成或重新编译提示词" : !local?.positive.trim() ? "请填写正向提示词"
    : !remoteEnabled ? "连接生图服务后即可生成" : !target ? (record?.draft.generation_source ? "原任务的执行目标当前不可用；可恢复该环境，或解除快照后选择其他目标" : "在生成设置中选择服务器与工作流")
    : availability?.availability !== "ready" ? availability?.message || "正在检查目标与资源…" : "";
  const tabs = [{id: "prompt", label: "提示词"}, {id: "requirements", label: "画面要求"}, {id: "settings", label: "生成设置"}] as const;
  async function copyPrompt(kind: "positive" | "negative") {
    try {await navigator.clipboard.writeText(local?.[kind] || ""); setCopied(kind);}
    catch {setError("复制失败，请选中提示词后手动复制。");}
  }

  return <section className="conversation-workbench">
    <header className="conversation-heading"><div><p className="eyebrow">ANIMA STUDIO <span> / </span> WORKBENCH</p><h1>会话创作 <span className="conversation-preview-label">预览</span></h1><p>把想法写下来，让画面逐步成形。</p></div>
      <div className="conversation-actions conversation-toolbar">
        <button aria-expanded={showLlmSettings} aria-controls="conversation-llm-settings" disabled={Boolean(busy)} onClick={() => setShowLlmSettings(value => !value)}><GearSix size={17} aria-hidden="true" />LLM 设置</button>
        <button className="conversation-new" disabled={Boolean(busy)} onClick={() => void create()}><Plus size={16} aria-hidden="true" />新会话</button>
      </div></header>
    <div className="conversation-session-bar"><div className="conversation-session-select"><ChatCircleDots size={19} aria-hidden="true" /><select aria-label="打开已有会话" value={record?.id || ""} disabled={Boolean(busy)} onChange={event => {if (event.target.value) void open(event.target.value);}}>
        <option value="">选择工作台</option>{workspaces.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select>
      </div><span className="conversation-session-note">{record ? `${record.draft.conversation_events.length} 次修改 · 输入自动保留在本机` : "开始新创作，或继续已有会话"}</span></div>
    {showLlmSettings && <div id="conversation-llm-settings"><LlmSettingsPanel /></div>}
    {error && <p role="alert" className="conversation-error">{error}</p>}
    {busy && <p role="status">{busy}…</p>}
    {!local || !record ? <section className="conversation-empty"><Sparkle size={30} aria-hidden="true" /><h2>这次，想画些什么？</h2><p>人物、动作、场景或一种氛围，从你最在意的部分开始。</p>
      <label htmlFor="conversation-idea" className="conversation-sr-only">创作想法</label><textarea id="conversation-idea" rows={4} value={idea} maxLength={4000} onChange={event => setIdea(event.target.value)} placeholder="例如：栗色长发的女孩坐在窗边，双手捧着咖啡杯，窗外樱花盛开。" />
      <div className="conversation-starters">{[{title: "日常人物", text: "栗色长发的女孩坐在窗边，双手捧着咖啡杯，清透赛璐璐风格。"}, {title: "幻想场景", text: "身穿白金盔甲的骑士站在空中花园，披着蓝色披风，远处是浮空城堡。"}, {title: "水彩插画", text: "戴尖帽的魔女双手捧着小白花，站在有蕨类和萤火虫的森林，透明水彩风格。"}].map(item => <button key={item.title} disabled={Boolean(busy)} onClick={() => setIdea(item.text)}>{item.title}</button>)}</div>
      <button className="conversation-primary" onClick={() => void create(idea)} disabled={Boolean(busy)}>创建会话 <PaperPlaneRight size={17} aria-hidden="true" /></button>
      <p className="conversation-empty-note">创建后可以继续修改，再由你确认生成图片。</p></section> : <>
      {conflict && <section role="alert" className="conversation-conflict"><strong>服务端已有更新，你未提交的输入仍在这里。</strong><p>可与最新提示词对照后，保留本地编辑，或采用服务端版本。</p>
        <pre>{record.draft.compiled?.positive || "尚未编译"}</pre>
        <button onClick={() => {edit({baseRevision: record.revision}); setConflict(false);}}>基于最新版本保留本地编辑</button>
        <button onClick={() => adopt(record)}>采用服务端版本</button></section>}
      {pending && !busy && <section className="conversation-conflict"><p>上次生成请求的接受结果尚未确认。请先查询原请求。</p><button onClick={() => void generate(true)}>查询本次提交</button></section>}
      <ol className="conversation-flow" aria-label="当前创作状态">
        <li><strong>1 · 画面要求</strong><span>{local.delta.trim() ? "有待整理的新想法" : compileInputsChanged ? "要求或模型已修改" : !record.draft.requirements ? "等待描述画面" : "当前要求已保存"}</span></li>
        <li><strong>2 · 提示词</strong><span>{local.delta.trim() ? "等待应用新想法" : needsCompile ? "需要更新后再生成" : promptChanged ? "将使用你手动修改的文字" : "已就绪，可继续调整"}</span></li>
        <li><strong>3 · 生成条件</strong><span>{dirty && !compileInputsChanged ? "参数待保存，无需重新编译" : target ? `${local.settings.width} × ${local.settings.height} · ${local.settings.batch_size} 张` : "尚未选择执行目标"}</span></li>
      </ol>
      <fieldset disabled={Boolean(busy) || Boolean(pending)} className="conversation-layout">
        <section className="conversation-dialogue">
          <div className="conversation-panel-heading"><div><ChatCircleDots size={20} aria-hidden="true" /><h2>创作对话</h2></div><span>{record.draft.conversation_events.length} 次修改</span></div>
          <div className="conversation-receipts" aria-label="修改记录">{!record.draft.conversation_events.length && <div className="conversation-dialogue-empty"><ChatCircleDots size={30} aria-hidden="true" /><h3>先描述画面，再慢慢完善</h3><p>追加新的想法，或只修改光线、服装等细节。需要保持不变的内容，可在右侧锁定。</p></div>}
            {record.draft.conversation_events.map((event, index) => <article key={event.id}><div className="conversation-event-meta">修改 {index + 1}</div><p className="conversation-user">{event.delta || "重新编译当前要求"}</p>
              <p>已更新：{event.changed_layers.map(name => layerLabels[name]).join("、") || "提示词"}</p>{event.warnings.map((warning, i) => <p key={i} className="conversation-warning">{warning}</p>)}</article>)}</div>
          <div className="conversation-composer"><label htmlFor="conversation-delta">{record.draft.requirements ? "继续追加要求" : "描述你想画的内容"}</label>
            <textarea id="conversation-delta" rows={4} maxLength={4000} value={local.delta} onChange={event => edit({delta: event.target.value})} placeholder="描述人物、动作、场景，或这次希望改变的地方" />
            <div className="conversation-actions"><label>改写方式<select value={local.mode} onChange={event => edit({mode: event.target.value as LocalConversation["mode"]})}><option value="faithful">忠实还原</option><option value="expand">适度扩写</option></select></label>
              <button className="conversation-primary" disabled={conflict || !local.delta.trim()} onClick={() => void turn(false)}><PaperPlaneRight size={16} aria-hidden="true" />发送修改</button>
              </div><p className="conversation-composer-note">只更新提示词，不会自动生成图片。</p></div>
        </section>
        <aside className="conversation-inspector"><div className="conversation-panel-heading"><div><SlidersHorizontal size={20} aria-hidden="true" /><h2>画面工作区</h2></div><span className={`conversation-badge ${!dirty && record.draft.compile_state === "fresh" ? "is-ready" : ""}`}>{dirty ? (compileInputsChanged ? "要求尚未保存" : "参数尚未保存") : promptChanged ? "提示词已手改" : {fresh: "已编译", stale: "需要重新编译", missing: "等待编译"}[record.draft.compile_state]}</span></div>
          <div className="conversation-tabs" role="tablist" aria-label="画面工作区">{tabs.map((item, index) => <button key={item.id} id={`tab-${item.id}`} role="tab" aria-selected={inspectorTab === item.id} aria-controls={`panel-${item.id}`} tabIndex={inspectorTab === item.id ? 0 : -1} onClick={() => setInspectorTab(item.id)} onKeyDown={event => {
            const next = event.key === "ArrowRight" ? (index + 1) % tabs.length : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
            if (next !== null) {event.preventDefault(); setInspectorTab(tabs[next].id); document.getElementById(`tab-${tabs[next].id}`)?.focus();}
          }}>{item.label}</button>)}</div>
          <div id="panel-prompt" role="tabpanel" aria-labelledby="tab-prompt" hidden={inspectorTab !== "prompt"} className="conversation-tab-panel">
          <div className="conversation-field-heading"><label htmlFor="conversation-positive">正向提示词</label><button className="conversation-copy" aria-label="复制正向提示词" disabled={!local.positive} onClick={() => void copyPrompt("positive")}>{copied === "positive" ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}复制</button></div>
          <textarea id="conversation-positive" className="conversation-prompt" rows={9} maxLength={20000} value={local.positive} placeholder="生成后的英文提示词会显示在这里，也可以直接编辑。" onChange={event => {setCopied(""); edit({positive: event.target.value});}} />
          <div className="conversation-field-heading"><label htmlFor="conversation-negative">负向提示词</label><button className="conversation-copy" aria-label="复制负向提示词" disabled={!local.negative} onClick={() => void copyPrompt("negative")}>{copied === "negative" ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}复制</button></div>
          <textarea id="conversation-negative" className="conversation-prompt" rows={2} maxLength={20000} value={local.negative} placeholder="需要避免的画面内容" onChange={event => {setCopied(""); edit({negative: event.target.value});}} />
          <p className="conversation-muted">{negativeGuidance(local.model).note} <a href={negativeGuidance(local.model).source || "https://huggingface.co/circlestone-labs/Anima"} target="_blank" rel="noreferrer">模型作者说明</a></p>
          {negativeGuidance(local.model).text && <button onClick={() => edit({negative: appendNegative(local.negative, negativeGuidance(local.model).text)})}>补充模型负向建议</button>}
          <p className="conversation-muted">正负提示词可直接修改；点击生成时一并保存。</p>
          <button className="conversation-recompile" disabled={conflict || !canCompileRequirements || !needsCompile || Boolean(local.delta.trim())} onClick={() => void turn(true)}><Sparkle size={16} aria-hidden="true" />重新编译</button>
          {comparison && <details className="conversation-prompt-comparison"><summary>查看本次提示词变化</summary><p className="conversation-muted">这里只展示最近一次整理前后的文本，后续手动编辑保留在上方输入框。</p><div>
            <section><h3>整理前</h3><h4>正向</h4><pre>{comparison.before.positive || "空"}</pre><h4>负向</h4><pre>{comparison.before.negative || "空"}</pre></section>
            <section><h3>整理后</h3><h4>正向</h4><pre>{comparison.after.positive || "空"}</pre><h4>负向</h4><pre>{comparison.after.negative || "空"}</pre></section>
          </div></details>}
          <span role="status" className="conversation-sr-only">{copied ? "提示词已复制" : ""}</span></div>
          <div id="panel-requirements" role="tabpanel" aria-labelledby="tab-requirements" hidden={inspectorTab !== "requirements"} className="conversation-tab-panel">
          <p className="conversation-muted">锁定的内容会在后续改写中保留。已锁定 {Object.values(local.requirements.layers).filter(item => item.locked).length} 层。</p>
            {(Object.keys(layerLabels) as LayerName[]).map(name => <div className="conversation-layer" key={name}><div className="conversation-actions"><strong>{layerLabels[name]}</strong><label><input type="checkbox" aria-label={`锁定${layerLabels[name]}要求`} checked={local.requirements.layers[name].locked} onChange={event => layer(name, {locked: event.target.checked})} />锁定改写</label></div>
              {name !== "exclusions" ? <textarea aria-label={`${layerLabels[name]}要求`} rows={2} value={local.requirements.layers[name].text} onChange={event => layer(name, {text: event.target.value})} /> : <>
                <label>全局排除（每行一项）<textarea value={local.requirements.layers.exclusions.global.join("\n")} onChange={event => layer("exclusions", {global: event.target.value.split("\n")})} /></label>
                {local.requirements.layers.exclusions.scoped.map((item, i) => <div className="conversation-actions" key={i}><input aria-label={`排除对象 ${i + 1}`} value={item.target} onChange={event => layer("exclusions", {scoped: local.requirements.layers.exclusions.scoped.map((entry, index) => index === i ? {...entry, target: event.target.value} : entry)})} /><input aria-label={`排除内容 ${i + 1}`} value={item.concept} onChange={event => layer("exclusions", {scoped: local.requirements.layers.exclusions.scoped.map((entry, index) => index === i ? {...entry, concept: event.target.value} : entry)})} /><button onClick={() => layer("exclusions", {scoped: local.requirements.layers.exclusions.scoped.filter((_, index) => index !== i)})}>移除</button></div>)}
                <button onClick={() => layer("exclusions", {scoped: [...local.requirements.layers.exclusions.scoped, {target: "", concept: ""}]})}>添加局部排除</button></>}
              {name === "style" && <><label>媒介<input value={local.requirements.layers.style.medium} onChange={event => layer("style", {medium: event.target.value})} /></label><label>画师（每行一个，不含 @）<textarea value={local.requirements.layers.style.artists.join("\n")} onChange={event => layer("style", {artists: event.target.value.split("\n")})} /></label></>}
              {name === "composition" && <label>景别<input value={local.requirements.layers.composition.shot} onChange={event => layer("composition", {shot: event.target.value})} /></label>}
            </div>)}
          </div>
          <div id="panel-settings" role="tabpanel" aria-labelledby="tab-settings" hidden={inspectorTab !== "settings"} className="conversation-tab-panel">

          <label>模型<select disabled={Boolean(record.draft.generation_source)} value={local.model} onChange={event => edit({model: event.target.value})}>{local.model === LEGACY_AESTHETIC && <option value={LEGACY_AESTHETIC} disabled>旧美学配置：请选择 v1.0 或 v1.1</option>}{profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.label}</option>)}</select></label>
            <label>执行目标<select disabled={Boolean(record.draft.generation_source)} value={target ? `${target.remote_profile_id}::${target.workflow_profile_id}` : ""} onChange={event => {
              const next = targets.find(item => `${item.remote_profile_id}::${item.workflow_profile_id}` === event.target.value);
              if (next) edit({settings: applyGenerationRecipe(local.settings, next, next.default_recipe_id)});
            }}><option value="">选择服务器与工作流</option>{targets.filter(item => item.compatible_model_profiles.includes(local.model)).map(item => <option key={`${item.remote_profile_id}::${item.workflow_profile_id}`} value={`${item.remote_profile_id}::${item.workflow_profile_id}`}>{item.experimental ? "[实验] " : ""}{item.remote_display_name} / {item.workflow_display_name}</option>)}</select></label>
            {target && <p className="conversation-muted">{target.experimental ? "实验工作流：包含额外模型处理，请与基础工作流分别比较。" : "基础工作流"}{target.workflow_notes && ` ${target.workflow_notes}`}</p>}
            <label>生成配方<select disabled={!target?.generation_recipes?.length} value={local.settings.preset_id} onChange={event => {if (target) edit({settings: applyGenerationRecipe(local.settings, target, event.target.value)});}}>
              {!target?.generation_recipes?.some(item => item.id === local.settings.preset_id) && <option value={local.settings.preset_id}>{local.settings.preset_id === "custom" ? "自定义参数" : "当前参数"}</option>}
              {target?.generation_recipes?.map(item => <option value={item.id} key={item.id}>{item.display_name}</option>)}
            </select></label>
            <div className="conversation-settings-grid">{(["width", "height", "steps", "cfg", "seed", "batch_size"] as const).map(name => <label key={name}>{({width: "宽度", height: "高度", steps: "步数", cfg: "CFG", seed: "种子（-1 随机）", batch_size: "张数"})[name]}<input type={name === "seed" ? "text" : "number"} inputMode={name === "seed" ? "numeric" : undefined} step={name === "cfg" ? 0.1 : 1} value={local.settings[name]} onChange={event => edit({settings: markGenerationCustom(local.settings, {...(name === "width" || name === "height" ? {aspect: "custom" as const} : {}), [name]: name === "seed" ? seedInput(event.target.value) : Number(event.target.value)})})} /></label>)}
              {(["sampler", "scheduler"] as const).map(name => <label key={name}>{name === "sampler" ? "采样器" : "调度器"}<input list={`conversation-${name}-options`} value={local.settings[name]} onChange={event => edit({settings: markGenerationCustom(local.settings, {[name]: event.target.value})})} /><datalist id={`conversation-${name}-options`}>{target?.parameter_capabilities?.[name]?.options.map(value => <option key={value} value={value} />)}</datalist></label>)}
            </div>
          <details><summary>LoRA 资源 · {local.requirements.loras.length}</summary>{local.requirements.loras.map((item, i) => <div className="conversation-layer" key={i}>
            <label>资源 ID<input value={item.logical_id} onChange={event => edit({requirements: {...local.requirements, loras: local.requirements.loras.map((r, n) => n === i ? {...r, logical_id: event.target.value} : r)}})} /></label>
            <label>文件名<input value={item.file_name} onChange={event => edit({requirements: {...local.requirements, loras: local.requirements.loras.map((r, n) => n === i ? {...r, file_name: event.target.value} : r)}})} /></label>
            <label>权重<input type="number" min={-2} max={2} step={0.05} value={item.weight} onChange={event => edit({requirements: {...local.requirements, loras: local.requirements.loras.map((r, n) => n === i ? {...r, weight: Number(event.target.value)} : r)}})} /></label>
            <label>触发词（每行一项）<textarea value={item.trigger_words.join("\n")} onChange={event => edit({requirements: {...local.requirements, loras: local.requirements.loras.map((r, n) => n === i ? {...r, trigger_words: event.target.value.split("\n")} : r)}})} /></label>
            <button onClick={() => edit({requirements: {...local.requirements, loras: local.requirements.loras.filter((_, n) => n !== i)}})}>移除 LoRA</button></div>)}
            <button onClick={() => edit({requirements: {...local.requirements, loras: [...local.requirements.loras, {logical_id: `lora-${local.requirements.loras.length + 1}`, file_name: "", weight: 1, trigger_words: [], required: true, source: {kind: "user"}}]}})}>添加 LoRA</button>
          </details>
          </div>
          <div className="conversation-generation-footer">
          <button disabled={!dirty || conflict} onClick={() => void act("保存要求与设置", async () => {await save();})}>保存要求与设置</button>
          {(needsCompile || local.delta.trim()) && <button className="conversation-primary" disabled={conflict || (!canCompileRequirements && !local.delta.trim())} onClick={() => void turn(!local.delta.trim())}>{local.delta.trim() ? "整理新想法，更新提示词" : "保存并编译提示词"}</button>}
          {dirty && !compileInputsChanged && <p className="conversation-muted">只改尺寸、种子或采样参数时，保存即可保留现有提示词。</p>}
          <p role="status" id="conversation-generation-reason" className="conversation-muted">{generationReason || "目标与资源可用，可以生成"}</p>
          {!target && <div className="conversation-target-help">{record.draft.generation_source ? <Link to="/workflows">检查原执行环境</Link> : <><button onClick={() => setInspectorTab("settings")}>选择生成目标</button><Link to="/settings">管理服务器</Link></>}</div>}
          {target && Boolean(availability?.resource_requirements?.length) && <LoraMappingPanel
            key={`${target.remote_profile_id}:${target.workflow_profile_id}:${JSON.stringify(availability?.resource_requirements)}`}
            remote={target.remote_profile_id} workflow={target.workflow_profile_id} resources={availability!.resource_requirements!}
            disabled={Boolean(busy || pending || conflict || dirty)} onSaved={() => setMappingEpoch(value => value + 1)} />}
          <button className="conversation-generate" aria-describedby="conversation-generation-reason" disabled={Boolean(generationReason)} onClick={() => void generate()}><ImageSquare size={19} aria-hidden="true" />生成图片</button>
          </div>
        </aside>
      </fieldset>
      <ArtistRecommendations key={record.id} prompt={local.positive} selected={local.requirements.layers.style.artists}
        disabled={Boolean(busy || pending || conflict)} onChange={artists => layer("style", {artists})} />
      <section className="conversation-reference-source"><Link to="/references">打开参考案例库</Link>
        {record.draft.reference_pin && <><p>当前要求来自参考案例。</p><Link to={`/references?example=${record.draft.reference_pin.example_id}`}>查看来源案例</Link>
          <button disabled={Boolean(busy || pending || conflict || dirty || local.delta.trim()) || local.positive !== (record.draft.compiled?.positive || "") || local.negative !== (record.draft.compiled?.negative || "")} onClick={() => void act("解除来源", async () => adopt(await apiRequest<ConversationRecord>("/api/v3/workbench/pins", {method: "DELETE", body: JSON.stringify({workspace_id: record.id, revision: record.revision})})))}>解除参考来源（保留要求）</button></>}
        {record.draft.generation_source && <><p>沿用原任务工作流快照。模型与执行目标已锁定；提示词和参数仍可调整。</p>
          <button disabled={Boolean(busy || pending || conflict || dirty || local.delta.trim()) || local.positive !== (record.draft.compiled?.positive || "") || local.negative !== (record.draft.compiled?.negative || "")}
            onClick={() => void act("解除生成来源", async () => adopt(await apiRequest<ConversationRecord>("/api/v3/workbench/generation-source", {method: "DELETE", body: JSON.stringify({workspace_id: record.id, revision: record.revision})})))}>解除原工作流快照，改用当前模板</button></>}
      </section>
      <section ref={resultsPanel} className="conversation-results" aria-label="本会话的生成结果">
        <header><div><h2>生成结果</h2><p>显示最多 20 次任务，进行中的任务优先。历史图片使用当时的生成条件。</p></div><Link to="/generate">管理全部任务 →</Link></header>
        {recentRuns.length ? <><label>查看生成批次<select disabled={Boolean(busy || pending)} value={run?.id || ""} onChange={event => setRun(recentRuns.find(item => item.id === event.target.value) || null)}>
          {recentRuns.map(item => <option key={item.id} value={item.id}>{item.created_at ? new Date(item.created_at).toLocaleString() : item.id.slice(0, 8)} · {item.status_message} · {item.artifact_count} 张</option>)}
        </select></label>{run && <><div className="conversation-result-heading"><p role="status">{run.status_message}</p>
          <button disabled={Boolean(busy || pending)} onClick={() => void continueRun(run)}>沿用本次条件，新建会话</button></div>
          {run.error?.message && <p role="alert">{run.error.message}</p>}
          <p className="conversation-muted">新会话继承该任务的提示词、参数、LoRA 和工作流快照；当前未发送内容保留，不会自动出图。</p>
          <RunPreview key={run.id} run={run} showStatus={false} /></>}</> : <p className="conversation-results-empty">生成后，图片和任务状态会留在这里。先确认提示词和参数，再点击“生成图片”。</p>}
      </section>
    </>}
  </section>;
}

export function RunPreview({run, showStatus = true}: {run: GenerationRunRecord; showStatus?: boolean}) {
  const [items, setItems] = useState<{id: string; path: string | null; thumbnail_url: string | null; content_url: string | null; removed: boolean}[]>([]);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [referenceId, setReferenceId] = useState("");
  const [previewIndex, setPreviewIndex] = useState(-1);
  const [assetError, setAssetError] = useState("");
  const [reload, setReload] = useState(0);
  const [metadata, setMetadata] = useState<GalleryAsset[]>([]);
  const previewItems = items.filter(item => !item.removed && item.content_url);
  useEffect(() => {
    if (previewIndex < 0) return;
    let canceled = false;
    void loadGallery().then(data => {if (!canceled) setMetadata(data.items);}).catch(() => {});
    return () => {canceled = true;};
  }, [previewIndex >= 0]);
  useEffect(() => {
    if (!run.artifact_count) return;
    const controller = new AbortController();
    setAssetError("");
    void apiRequest<{items: typeof items}>(`/api/v3/generation-runs/${run.id}/artifacts`, {signal: controller.signal})
      .then(result => {if (!controller.signal.aborted) setItems(result.items);})
      .catch(() => {if (!controller.signal.aborted) setAssetError("结果图片暂时无法读取，可以重试或到任务页查看。");});
    return () => controller.abort();
  }, [run.id, run.artifact_count, reload]);
  return <article>{showStatus && <p>{run.status_message}</p>}
    {assetError && <p role="alert">{assetError}<button onClick={() => setReload(value => value + 1)}>重新读取图片</button></p>}
    {!run.artifact_count && <p>{run.state === "completed" ? "本次任务没有记录到输出图片。" : "输出图片就绪后会自动显示在这里。"}</p>}
    {items.map(item => item.removed || !item.thumbnail_url
    ? <p key={item.id}>图片已移除或不在当前画廊</p>
    : <div key={item.id}><button type="button" className="run-preview-open" disabled={!item.content_url} aria-label={`预览生成图片 ${items.indexOf(item) + 1}`} onClick={() => setPreviewIndex(previewItems.findIndex(image => image.id === item.id))}><img src={item.thumbnail_url} alt="本次生成结果" loading="lazy" /></button>
      <button disabled={saving || !item.path} onClick={async () => {setSaving(true); setMessage(""); try {
        const example = await apiRequest<{id: string}>("/api/v3/reference-examples/from-run", {method: "POST", body: JSON.stringify({run_id: run.id, path: item.path})});
        setReferenceId(example.id); setMessage("已存入参考案例库。");
      } catch (error) {setMessage((error as Error).message);} finally {setSaving(false);}}}>收藏为参考</button></div>)}
    {previewIndex >= 0 && <ImagePreview index={previewIndex} onClose={() => setPreviewIndex(-1)} images={previewItems.map(item => {
      const asset = metadata.find(asset => asset.path === item.path);
      return {src: item.content_url!, alt: asset?.name || item.path?.split(/[\\/]/).pop() || "生成结果",
        width: asset?.width || undefined, height: asset?.height || undefined, positive: asset?.positive_prompt,
        negative: asset?.negative_prompt, parameters: asset ? {model: asset.model_profile, ...asset.generation_params} : {提示: "该图片的生成参数暂未在画廊索引中找到"}};
    })} />}
    {message && <p role="status">{message}</p>}{referenceId && <Link to={`/references?example=${referenceId}`}>查看已保存案例</Link>}<Link to="/generate">查看任务</Link></article>;
}
