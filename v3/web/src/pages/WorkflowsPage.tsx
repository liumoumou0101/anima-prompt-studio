import {useEffect, useState} from "react";
import {Link, useSearchParams} from "react-router-dom";
import {apiRequest} from "../lib/api";
import {modelProfileChoices} from "../lib/modelProfiles";
import type {ModelProfileOption} from "../lib/types";
import {WorkflowManager} from "../components/WorkflowManager";

type Template = {workflow_id: string; display_name: string; revision: string; origin: string; enabled: boolean;
  experimental: boolean; model_profiles: string[]; workflow_kind: string; notes: string; nodes: string[];
  assets: {key: string; value: string; node_type: string}[]; source?: {id: string; revision: string} | null};
type Environment = {connection_type?: "ssh" | "local"; id: string; display_name: string; enabled: boolean; host_fingerprint_confirmed: boolean; auth_type: string; has_saved_password: boolean};
type Document = {schema: string; profile: {display_name: string; compatible_model_profiles: string[]; notes?: string; [key: string]: unknown}};

export function WorkflowsPage({enabled, modelProfiles}: {enabled: boolean; modelProfiles?: ModelProfileOption[]}) {
  const [params] = useSearchParams();
  const [items, setItems] = useState<Template[]>([]);
  const [environments, setEnvironments] = useState<Environment[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [remoteId, setRemoteId] = useState(params.get("environment") || "");
  const [view, setView] = useState<"library" | "environment">(params.has("environment") ? "environment" : "library");
  const [query, setQuery] = useState("");
  const [model, setModel] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editor, setEditor] = useState(false);
  const [json, setJson] = useState("");
  const [preview, setPreview] = useState<Document | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [password, setPassword] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [versions, setVersions] = useState<{revision: string; display_name: string}[]>([]);
  const choices = modelProfileChoices(modelProfiles);
  const selected = items.find(item => item.workflow_id === selectedId);
  const remote = environments.find(item => item.id === remoteId);
  const filtered = items.filter(item => (!model || item.model_profiles.includes(model)) && `${item.display_name} ${item.notes}`.toLowerCase().includes(query.toLowerCase()));
  const modelLabel = (id: string) => choices.find(item => item.id === id)?.label || id;

  async function refresh(select?: string) {
    const result = await apiRequest<{items: Template[]}>("/api/v3/workflows/catalog");
    setItems(result.items); setSelectedId(current => select || (result.items.some(item => item.workflow_id === current) ? current : result.items[0]?.workflow_id || ""));
  }
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    void Promise.all([apiRequest<{items: Template[]}>("/api/v3/workflows/catalog"), apiRequest<{items: Environment[]}>("/api/v3/settings/remote-profiles")])
      .then(([library, settings]) => {if (active) {setItems(library.items); setSelectedId(library.items[0]?.workflow_id || ""); setEnvironments(settings.items); setLoaded(true);}})
      .catch(caught => {if (active) {setError(String(caught)); setLoaded(true);}});
    return () => {active = false;};
  }, [enabled]);
  async function action(work: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try {await work();} catch (caught) {setError(String(caught));} finally {setBusy(false);}
  }
  function receive(document: object) {
    setJson(JSON.stringify(document, null, 2)); setPreview(null); setConfirmed(false); setEditor(true); setView("library");
  }
  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(preview || JSON.parse(json), null, 2)], {type: "application/json"}));
    const a = document.createElement("a"); a.href = url; a.download = "anima-workflow.json"; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  if (!enabled) return <section className="workflow-page"><h1>工作流</h1><p>请从完整桌面入口启动，以使用本地模板库。</p></section>;
  return <section className="workflow-page">
    <header><p className="eyebrow">WORKFLOWS</p><h1>工作流</h1><p>模板保存在本机，ComfyUI 负责执行。先选择模板，再为执行环境确认资源。</p></header>
    <div className="workflow-toolbar" role="tablist" aria-label="工作流管理视图">
      <button role="tab" aria-selected={view === "library"} onClick={() => setView("library")}>本地模板</button>
      <button role="tab" aria-selected={view === "environment"} onClick={() => setView("environment")}>执行环境与资源</button>
    </div>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {!loaded && <p role="status">正在读取本地模板…</p>}
    <div className="workflow-layout">
      <aside className="workflow-library" aria-label="本地模板列表">
        <label>搜索模板<input value={query} onChange={e => setQuery(e.target.value)} /></label>
        <label>适配模型<select value={model} onChange={e => setModel(e.target.value)}><option value="">全部模型</option>{choices.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
        <p>{filtered.length} 个模板 · 本机保存</p>
        {filtered.map(item => <button className="workflow-template-card" key={item.workflow_id} aria-pressed={selectedId === item.workflow_id} onClick={() => {setSelectedId(item.workflow_id); setVersions([]);}}>
          <strong>{item.display_name}</strong><span>{item.origin === "official" ? "内置" : "用户副本"} · {item.enabled ? "启用" : "停用"}{item.experimental ? " · 含实验节点" : ""}</span>
          <small>{item.model_profiles.map(modelLabel).join(" / ") || "模型待确认"}</small>
        </button>)}
        {loaded && !filtered.length && <p>没有匹配的模板。可调整筛选或导入新模板。</p>}
        <button disabled={busy} onClick={() => {setEditor(true); setView("library");}}>导入本地模板</button>
      </aside>
      <div className="workflow-content">
        {selected && <header><h2>{selected.display_name}</h2><p>本地内容版本 {selected.revision.slice(0, 12)} · {selected.enabled ? "已启用" : "已停用"}</p></header>}
        {view === "library" && <>
          {selected && <section aria-label="模板详情">
            <p>{selected.notes || "尚无备注"}</p><p>适配模型：{selected.model_profiles.map(modelLabel).join("、") || "待确认"}</p>
            {selected.source && <p>来源模板：{selected.source.id} · 版本 {selected.source.revision.slice(0, 12)}</p>}
            <div className="workflow-toolbar">
              <button disabled={busy} onClick={() => void action(async () => {receive(await apiRequest(`/api/v3/workflows/export/${encodeURIComponent(selected.workflow_id)}`));})}>编辑副本 / 模型关联</button>
              <button disabled={busy} onClick={() => void action(async () => {await apiRequest(`/api/v3/workflows/${encodeURIComponent(selected.workflow_id)}/enabled`, {method: "PUT", body: JSON.stringify({enabled: !selected.enabled})}); await refresh();})}>{selected.enabled ? "停用模板" : "启用模板"}</button>
              <button onClick={() => setView("environment")}>配置执行环境</button>
            </div>
            <h3>模板声明的文件</h3><ul>{selected.assets.map(asset => <li key={asset.key}><strong>{asset.node_type}</strong> · {asset.value}</li>)}</ul>
            <details><summary>依赖节点（{selected.nodes.length} 类）</summary><ul>{selected.nodes.map(node => <li key={node}>{node}</li>)}</ul></details>
            {selected.origin === "official" && <details><summary onClick={() => void action(async () => {setVersions((await apiRequest<{items: typeof versions}>(`/api/v3/workflows/${encodeURIComponent(selected.workflow_id)}/versions`)).items);})}>已保存的内置版本</summary>
              {versions.map(version => <p key={version.revision}>{version.revision.slice(0, 12)} <button disabled={busy} onClick={() => void action(async () => {const result = await apiRequest<{id: string}>(`/api/v3/workflows/${encodeURIComponent(selected.workflow_id)}/restore`, {method: "POST", body: JSON.stringify({revision: version.revision})}); await refresh(result.id); setNotice("已恢复为独立用户副本。");})}>恢复为副本</button></p>)}
            </details>}
          </section>}
          {editor && <section className="workflow-import" aria-label="模板导入编辑区"><h2>导入与编辑副本</h2>
            <p>支持 ComfyUI API JSON 或本工具导出的模板。先解析，再确认模型关联；复杂节点图需要明确的参数绑定。编辑器格式需在 ComfyUI 中导出为 API 格式。</p>
            <label>本地工作流文件<input type="file" accept=".json,application/json" disabled={busy} onChange={e => {const file = e.target.files?.[0]; if (file) void action(async () => {if (file.size > 2_000_000) throw new Error("文件不能超过 2 MB"); receive(JSON.parse(await file.text()));});}} /></label>
            <label>工作流 JSON<textarea rows={8} value={json} disabled={busy} onChange={e => {setJson(e.target.value); setPreview(null); setConfirmed(false);}} /></label>
            <button disabled={busy || !json.trim()} onClick={() => void action(async () => {setPreview(await apiRequest<Document>("/api/v3/workflows/preview", {method: "POST", body: json})); setConfirmed(false);})}>解析并预览</button>
            {preview && <fieldset disabled={busy}><legend>确认模板信息</legend>
              <label>模板名称<input value={preview.profile.display_name} onChange={e => setPreview({...preview, profile: {...preview.profile, display_name: e.target.value}})} /></label>
              <p>以下关联来自模板声明或自动识别，请结合实际权重确认。改变模型关联不会替换图内权重。</p>
              {[...choices, ...preview.profile.compatible_model_profiles.filter(id => !choices.some(c => c.id === id)).map(id => ({id, label: id}))].map(item => <label className="workflow-model-choice" key={item.id}><input type="checkbox" checked={preview.profile.compatible_model_profiles.includes(item.id)} onChange={e => {setConfirmed(false); setPreview({...preview, profile: {...preview.profile, compatible_model_profiles: e.target.checked ? [...preview.profile.compatible_model_profiles, item.id] : preview.profile.compatible_model_profiles.filter(id => id !== item.id)}});}} />{item.label}</label>)}
              <label>备注<textarea value={preview.profile.notes || ""} onChange={e => setPreview({...preview, profile: {...preview.profile, notes: e.target.value}})} /></label>
              <label className="workflow-model-choice"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />已确认模板与模型关联</label>
              <button disabled={!confirmed || !preview.profile.display_name.trim() || !preview.profile.compatible_model_profiles.length} onClick={() => void action(async () => {const result = await apiRequest<{id: string}>("/api/v3/workflows/import", {method: "POST", body: JSON.stringify(preview)}); await refresh(result.id); setEditor(false); setPreview(null); setJson(""); setNotice("已保存为新的本地模板，尚未为任何环境配置文件映射。");})}>保存为新的本地模板</button>
            </fieldset>}
            <div className="workflow-toolbar"><button disabled={busy || !json.trim()} onClick={() => void action(async () => download())}>下载当前模板 JSON</button><button disabled={busy} onClick={() => setEditor(false)}>收起编辑区（保留草稿）</button></div>
          </section>}
        </>}
        {view === "environment" && <section aria-label="执行环境设置">
          <label>执行环境<select value={remoteId} onChange={e => {setRemoteId(e.target.value); setPassword(""); setPassphrase("");}}><option value="">选择执行环境</option>{environments.map(item => <option key={item.id} value={item.id}>{item.display_name} · {item.connection_type === "local" ? "本地 ComfyUI" : "云端 SSH"}{item.enabled ? "" : " · 已停用"}</option>)}</select></label>
          <p><Link to="/settings">管理连接配置</Link> · 支持本地 ComfyUI 直连与云端 SSH 环境。</p>
          {!environments.length && <p>尚未添加执行环境。仍可离线导入、编辑和保存本地模板。</p>}
          {remote && <>
            <p>{remote.enabled ? "连接已启用" : "连接已停用"} · {remote.connection_type === "local" ? "本机 ComfyUI 直连" : remote.host_fingerprint_confirmed ? "SSH 指纹已确认" : "请先在设置中确认 SSH 指纹"}</p>
            {remote.auth_type === "password" && <label>本次连接密码{remote.has_saved_password && "（已保存时可留空）"}<input type="password" autoComplete="off" value={password} onChange={e => setPassword(e.target.value)} /></label>}
            {remote.auth_type === "private_key" && <label>本次私钥口令<input type="password" autoComplete="off" value={passphrase} onChange={e => setPassphrase(e.target.value)} /></label>}
            {selected && <WorkflowManager key={`${remoteId}:${selectedId}`} remoteId={remoteId} workflowId={selectedId} password={password} passphrase={passphrase} expanded onDocument={remote.connection_type === "local" ? undefined : receive} />}
          </>}
        </section>}
      </div>
    </div>
  </section>;
}
