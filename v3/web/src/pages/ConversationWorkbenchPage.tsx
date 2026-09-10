import {useEffect, useRef, useState} from "react";
import {Link} from "react-router-dom";
import {apiRequest, ApiClientError} from "../lib/api";
import {applyGenerationRecipe, defaultGenerationSettings, resolvedGenerationSettings} from "../lib/generationSettings";
import {modelProfileChoices} from "../lib/modelProfiles";
import {cleanRequirements, editableRequirements, hasUnsavedInputs, layerLabels} from "../lib/conversation";
import "./conversationWorkbench.css";
import {ReferenceLibrary} from "./ReferenceLibrary";
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
  const [record, setRecord] = useState<ConversationRecord | null>(null);
  const current = useRef<ConversationRecord | null>(null);
  const [local, setLocal] = useState<LocalConversation | null>(null);
  const [workspaces, setWorkspaces] = useState<WorkspaceListResponse["items"]>([]);
  const [targets, setTargets] = useState<GenerationTarget[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [showLlmSettings, setShowLlmSettings] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [run, setRun] = useState<GenerationRunRecord | null>(null);
  const [recentRuns, setRecentRuns] = useState<GenerationRunRecord[]>([]);
  const [availability, setAvailability] = useState<{availability: string; message?: string; resource_requirements?: ResourceIdentity[]} | null>(null);
  const [mappingEpoch, setMappingEpoch] = useState(0);
  const opening = useRef(0);
  const requestLock = useRef(false);
  const mounted = useRef(true);
  const profiles = modelProfileChoices(modelProfiles);

  function adopt(next: ConversationRecord, preserve = false) {
    if (!mounted.current) return;
    if (current.current?.id === next.id && current.current.revision > next.revision) return;
    current.current = next;
    setRecord(next);
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
      setRun(null); setRecentRuns([]); setAvailability(null);
      write(ACTIVE, id);
    } catch (caught) {if (mounted.current && sequence === opening.current) setError((caught as Error).message);}
    finally {if (mounted.current && sequence === opening.current) setBusy("");}
  }

  useEffect(() => {
    mounted.current = true;
    void apiRequest<WorkspaceListResponse>("/api/v3/workspaces?limit=50").then(result => {
      if (!mounted.current) return;
      setWorkspaces(result.items);
      const id = read<string>(ACTIVE);
      if (id) void open(id);
    }).catch(caught => {if (mounted.current) setError((caught as Error).message);});
    if (remoteEnabled) void apiRequest<GenerationTargetListResponse>("/api/v3/generation-targets").then(result => {
      if (mounted.current) setTargets(result.items);
    }).catch(caught => {if (mounted.current) setError((caught as Error).message);});
    return () => {mounted.current = false; opening.current++;};
  }, [remoteEnabled]);

  const dirty = Boolean(record && local && hasUnsavedInputs(record, local));
  const target = local && targets.find(item => item.remote_profile_id === local.settings.remote_profile_id
    && item.workflow_profile_id === local.settings.workflow_profile_id && item.compatible_model_profiles.includes(local.model));

  useEffect(() => {
    if (!record || !target || dirty || conflict) {setAvailability(null); return;}
    const controller = new AbortController();
    setAvailability(null);
    const query = new URLSearchParams({workspace_id: record.id, revision: String(record.revision),
      remote_profile_id: target.remote_profile_id, workflow_profile_id: target.workflow_profile_id});
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
  async function create() {
    await act("创建工作台", async () => {
      const next = await apiRequest<ConversationRecord>("/api/v3/workspaces", {method: "POST", body: JSON.stringify({
        title: "会话创作", draft: {model_profile: profiles[0].id, generation_settings: defaultGenerationSettings()}})});
      adopt(next); write(ACTIVE, next.id); setWorkspaces(items => [next, ...items]); setPending(null); setRun(null); setRecentRuns([]);
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
      adopt(next);
    });
  }
  async function generate(retry = false) {
    if (!record || !local) return;
    await act("提交生成", async () => {
      const request = retry && pending ? pending : {key: crypto.randomUUID(), body: JSON.stringify({
        submission_kind: "conversational", workspace_id: record.id, workspace_revision: record.revision,
        compiled_token: record.draft.compiled?.compiled_token, positive_prompt: local.positive, negative_prompt: local.negative,
        model_profile: local.model, remote_profile_id: target?.remote_profile_id, workflow_profile_id: target?.workflow_profile_id,
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
      const submitted = JSON.parse(request.body) as {positive_prompt: string; negative_prompt: string};
      // Retain the new token even if the following read fails.
      const next = {...record, revision: accepted.workspace_revision, draft: {...record.draft,
        compiled: {...record.draft.compiled!, positive: submitted.positive_prompt, negative: submitted.negative_prompt, compiled_token: accepted.compiled_token}}};
      adopt(next);
      adopt(await apiRequest<ConversationRecord>(`/api/v3/workspaces/${record.id}`));
    });
  }

  return <main className="conversation-workbench">
    <header className="conversation-heading"><div><p className="eyebrow">ANIMA / CONVERSATION</p><h1>把画面聊清楚</h1><p>逐步追加要求，检查提示词，准备好后再生成。</p></div>
      <div className="conversation-actions"><select aria-label="打开已有会话" value={record?.id || ""} disabled={Boolean(busy)} onChange={event => {if (event.target.value) void open(event.target.value);}}>
        <option value="">选择工作台</option>{workspaces.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select>
        <button disabled={Boolean(busy)} onClick={() => void create()}>新会话</button>
        <button disabled={Boolean(busy)} onClick={() => setShowLlmSettings(value => !value)}>LLM 设置</button></div></header>
    {showLlmSettings && <LlmSettingsPanel />}
    {error && <p role="alert" className="conversation-error">{error}</p>}
    {busy && <p role="status">{busy}…</p>}
    {!local || !record ? <section className="conversation-empty"><h2>从一个想法开始</h2><p>例如：雨后的街道，一位短发侦探，右手拿着信。</p><button onClick={() => void create()} disabled={Boolean(busy)}>创建会话</button></section> : <>
      {conflict && <section role="alert" className="conversation-conflict"><strong>服务端已有更新，你未提交的输入仍在这里。</strong><p>可与最新提示词对照后，保留本地编辑，或采用服务端版本。</p>
        <pre>{record.draft.compiled?.positive || "尚未编译"}</pre>
        <button onClick={() => {edit({baseRevision: record.revision}); setConflict(false);}}>基于最新版本保留本地编辑</button>
        <button onClick={() => adopt(record)}>采用服务端版本</button></section>}
      {pending && <section className="conversation-conflict"><p>上次生成请求的接受结果尚未确认。请先查询原请求。</p><button disabled={Boolean(busy)} onClick={() => void generate(true)}>查询本次提交</button></section>}
      <fieldset disabled={Boolean(busy) || Boolean(pending)} className="conversation-layout">
        <section className="conversation-dialogue">
          <div className="conversation-receipts" aria-label="修改记录">{!record.draft.conversation_events.length && <p className="conversation-muted">描述主体、风格或构图。每轮修改都会保留在当前会话。</p>}
            {record.draft.conversation_events.map(event => <article key={event.id}><p className="conversation-user">{event.delta || "重新编译"}</p>
              <p>已更新：{event.changed_layers.map(name => layerLabels[name]).join("、") || "提示词"}</p>{event.warnings.map((warning, i) => <p key={i} className="conversation-warning">{warning}</p>)}</article>)}</div>
          <div className="conversation-composer"><label htmlFor="conversation-delta">{record.draft.requirements ? "继续追加要求" : "描述你想画的内容"}</label>
            <textarea id="conversation-delta" rows={4} maxLength={4000} value={local.delta} onChange={event => edit({delta: event.target.value})} placeholder="描述人物、动作、场景，或这次希望改变的地方" />
            <div className="conversation-actions"><label>改写方式<select value={local.mode} onChange={event => edit({mode: event.target.value as LocalConversation["mode"]})}><option value="faithful">忠实还原</option><option value="expand">适度扩写</option></select></label>
              <button disabled={conflict || !local.delta.trim()} onClick={() => void turn(false)}>发送修改</button>
              <button disabled={conflict || !record.draft.requirements} onClick={() => void turn(true)}>重新编译</button></div></div>
        </section>
        <aside className="conversation-inspector"><div className="conversation-actions"><h2>本次提示词</h2><span>{dirty ? "要求尚未保存" : {fresh: "已编译", stale: "需要重新编译", missing: "等待编译"}[record.draft.compile_state]}</span></div>
          <label>正向提示词<textarea rows={7} maxLength={20000} value={local.positive} onChange={event => edit({positive: event.target.value})} /></label>
          <label>负向提示词<textarea rows={3} maxLength={20000} value={local.negative} onChange={event => edit({negative: event.target.value})} /></label>
          <p className="conversation-muted">正负提示词可直接修改；点击生成时一并保存。</p>
          <details><summary>五层要求 · {Object.values(local.requirements.layers).filter(item => item.locked).length} 层已锁定</summary>
            {(Object.keys(layerLabels) as LayerName[]).map(name => <div className="conversation-layer" key={name}><div className="conversation-actions"><strong>{layerLabels[name]}</strong><label><input type="checkbox" checked={local.requirements.layers[name].locked} onChange={event => layer(name, {locked: event.target.checked})} />锁定改写</label></div>
              {name !== "exclusions" ? <textarea aria-label={`${layerLabels[name]}要求`} rows={2} value={local.requirements.layers[name].text} onChange={event => layer(name, {text: event.target.value})} /> : <>
                <label>全局排除（每行一项）<textarea value={local.requirements.layers.exclusions.global.join("\n")} onChange={event => layer("exclusions", {global: event.target.value.split("\n")})} /></label>
                {local.requirements.layers.exclusions.scoped.map((item, i) => <div className="conversation-actions" key={i}><input aria-label={`排除对象 ${i + 1}`} value={item.target} onChange={event => layer("exclusions", {scoped: local.requirements.layers.exclusions.scoped.map((entry, index) => index === i ? {...entry, target: event.target.value} : entry)})} /><input aria-label={`排除内容 ${i + 1}`} value={item.concept} onChange={event => layer("exclusions", {scoped: local.requirements.layers.exclusions.scoped.map((entry, index) => index === i ? {...entry, concept: event.target.value} : entry)})} /><button onClick={() => layer("exclusions", {scoped: local.requirements.layers.exclusions.scoped.filter((_, index) => index !== i)})}>移除</button></div>)}
                <button onClick={() => layer("exclusions", {scoped: [...local.requirements.layers.exclusions.scoped, {target: "", concept: ""}]})}>添加局部排除</button></>}
              {name === "style" && <><label>媒介<input value={local.requirements.layers.style.medium} onChange={event => layer("style", {medium: event.target.value})} /></label><label>画师（每行一个，不含 @）<textarea value={local.requirements.layers.style.artists.join("\n")} onChange={event => layer("style", {artists: event.target.value.split("\n")})} /></label></>}
              {name === "composition" && <label>景别<input value={local.requirements.layers.composition.shot} onChange={event => layer("composition", {shot: event.target.value})} /></label>}
            </div>)}
          </details>
          <details><summary>LoRA 资源 · {local.requirements.loras.length}</summary>{local.requirements.loras.map((item, i) => <div className="conversation-layer" key={i}>
            <label>资源 ID<input value={item.logical_id} onChange={event => edit({requirements: {...local.requirements, loras: local.requirements.loras.map((r, n) => n === i ? {...r, logical_id: event.target.value} : r)}})} /></label>
            <label>文件名<input value={item.file_name} onChange={event => edit({requirements: {...local.requirements, loras: local.requirements.loras.map((r, n) => n === i ? {...r, file_name: event.target.value} : r)}})} /></label>
            <label>权重<input type="number" min={-2} max={2} step={0.05} value={item.weight} onChange={event => edit({requirements: {...local.requirements, loras: local.requirements.loras.map((r, n) => n === i ? {...r, weight: Number(event.target.value)} : r)}})} /></label>
            <label>触发词（每行一项）<textarea value={item.trigger_words.join("\n")} onChange={event => edit({requirements: {...local.requirements, loras: local.requirements.loras.map((r, n) => n === i ? {...r, trigger_words: event.target.value.split("\n")} : r)}})} /></label>
            <button onClick={() => edit({requirements: {...local.requirements, loras: local.requirements.loras.filter((_, n) => n !== i)}})}>移除 LoRA</button></div>)}
            <button onClick={() => edit({requirements: {...local.requirements, loras: [...local.requirements.loras, {logical_id: `lora-${local.requirements.loras.length + 1}`, file_name: "", weight: 1, trigger_words: [], required: true, source: {kind: "user"}}]}})}>添加 LoRA</button>
          </details>
          <details><summary>模型与生成设置</summary><label>模型<select value={local.model} onChange={event => edit({model: event.target.value})}>{profiles.map(profile => <option key={profile.id} value={profile.id}>{profile.label}</option>)}</select></label>
            <label>执行目标<select value={target ? `${target.remote_profile_id}::${target.workflow_profile_id}` : ""} onChange={event => {
              const next = targets.find(item => `${item.remote_profile_id}::${item.workflow_profile_id}` === event.target.value);
              if (next) edit({settings: applyGenerationRecipe(local.settings, next, next.default_recipe_id)});
            }}><option value="">选择服务器与工作流</option>{targets.filter(item => item.compatible_model_profiles.includes(local.model)).map(item => <option key={`${item.remote_profile_id}::${item.workflow_profile_id}`} value={`${item.remote_profile_id}::${item.workflow_profile_id}`}>{item.remote_display_name} / {item.workflow_display_name}</option>)}</select></label>
            {(["width", "height", "steps", "cfg", "seed", "batch_size"] as const).map(name => <label key={name}>{({width: "宽度", height: "高度", steps: "步数", cfg: "CFG", seed: "种子（-1 随机）", batch_size: "张数"})[name]}<input type="number" value={local.settings[name]} onChange={event => edit({settings: {...local.settings, aspect: "custom", [name]: Number(event.target.value)}})} /></label>)}
          </details>
          <button disabled={!dirty || conflict} onClick={() => void act("保存要求", async () => {await save();})}>保存要求与设置</button>
          <p role="status" className="conversation-muted">{availability?.availability === "ready" ? "目标与资源可用" : availability?.message || (target ? "保存并编译后可生成" : "选择执行目标后可生成")}</p>
          {target && Boolean(availability?.resource_requirements?.length) && <LoraMappingPanel
            key={`${target.remote_profile_id}:${target.workflow_profile_id}:${JSON.stringify(availability?.resource_requirements)}`}
            remote={target.remote_profile_id} workflow={target.workflow_profile_id} resources={availability!.resource_requirements!}
            disabled={Boolean(busy || pending || conflict || dirty)} onSaved={() => setMappingEpoch(value => value + 1)} />}
          <button className="conversation-generate" disabled={Boolean(pending) || conflict || dirty || Boolean(local.delta.trim()) || record.draft.compile_state !== "fresh" || !local.positive.trim() || availability?.availability !== "ready"} onClick={() => void generate()}>生成图片</button>
        </aside>
      </fieldset>
      <ReferenceLibrary key={record.id} record={record}
        disabled={Boolean(busy || pending || conflict || dirty || local.delta.trim())
          || local.positive !== (record.draft.compiled?.positive || "") || local.negative !== (record.draft.compiled?.negative || "")}
        onPin={async (example, role) => {await act("钉选参考", async () => adopt(await apiRequest<ConversationRecord>("/api/v3/workbench/pins", {
          method: "POST", body: JSON.stringify({workspace_id: record.id, revision: record.revision, example_id: example.id, source_version: example.source_version, role})})));}}
        onUnpin={async () => {await act("解除来源", async () => adopt(await apiRequest<ConversationRecord>("/api/v3/workbench/pins", {
          method: "DELETE", body: JSON.stringify({workspace_id: record.id, revision: record.revision})})));}} />
      {run && <section className="conversation-run" aria-live="polite"><strong>{run.status_message}</strong><p>{run.error?.message}</p><Link to="/generate">查看生成任务与结果 →</Link></section>}
      {recentRuns.length > 0 && <section className="conversation-filmstrip" aria-label="本会话的生成结果">{recentRuns.map(item => <RunPreview key={item.id} run={item} />)}</section>}
    </>}
  </main>;
}

function RunPreview({run}: {run: GenerationRunRecord}) {
  const [items, setItems] = useState<{id: string; path: string | null; thumbnail_url: string | null; content_url: string | null; removed: boolean}[]>([]);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (!run.artifact_count) return;
    const controller = new AbortController();
    void apiRequest<{items: typeof items}>(`/api/v3/generation-runs/${run.id}/artifacts`, {signal: controller.signal})
      .then(result => {if (!controller.signal.aborted) setItems(result.items);})
      .catch(() => { /* Keep the run link available when assets cannot be read. */ });
    return () => controller.abort();
  }, [run.id, run.artifact_count]);
  return <article><p>{run.status_message}</p>{items.map(item => item.removed || !item.thumbnail_url
    ? <p key={item.id}>图片已移除或不在当前画廊</p>
    : <div key={item.id}><a href={item.content_url || undefined} target="_blank" rel="noreferrer"><img src={item.thumbnail_url} alt="本次生成结果" loading="lazy" /></a>
      <button disabled={saving || !item.path} onClick={async () => {setSaving(true); setMessage(""); try {
        await apiRequest("/api/v3/reference-examples/from-run", {method: "POST", body: JSON.stringify({run_id: run.id, path: item.path})});
        setMessage("已收藏，可在参考收藏中刷新查看。");
      } catch (error) {setMessage((error as Error).message);} finally {setSaving(false);}}}>收藏为参考</button></div>)}
    {message && <p role="status">{message}</p>}<Link to="/generate">查看任务</Link></article>;
}
