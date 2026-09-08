import {useEffect, useState} from "react";
import {apiRequest} from "../lib/api";

type Asset = {key: string; value: string; choices: string[]; mapped: boolean};
type Item = {workflow_id: string; display_name: string; revision: string; origin: string; experimental: boolean; state: string; errors: string[]; assets: Asset[]};
type Report = {remote_profile_id: string; checked_at: number | null; items: Item[]; inspection?: {state: string; error?: string}};
const labels: Record<string, string> = {ready: "依赖就绪", unchecked: "未检测", stale: "需重新检测", missing_nodes: "缺少节点", invalid_inputs: "资产或参数不匹配", connection_failed: "连接失败", mapping_stale: "映射需确认", disabled: "已停用"};

export function WorkflowManager({remoteId, password, passphrase}: {remoteId: string; password: string; passphrase: string}) {
  const [open, setOpen] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [json, setJson] = useState("");
  const [remotePath, setRemotePath] = useState("");
  const [versions, setVersions] = useState<Record<string, {revision: string; display_name: string}[]>>({});
  const [mappings, setMappings] = useState<Record<string, Record<string, string>>>({});
  const root = `/api/v3/workflows/servers/${encodeURIComponent(remoteId)}`;
  const checking = report?.inspection?.state === "running";

  useEffect(() => {
    if (!open) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function refresh() {
      try {
        const next = await apiRequest<Report>(root);
        if (active) {
          setReport(next);
          if (next.inspection?.error) setError(next.inspection.error);
          if (next.inspection?.state === "running") timer = setTimeout(refresh, 1500);
        }
      } catch (caught) { if (active) setError(String(caught)); }
    }
    void refresh();
    return () => { active = false; clearTimeout(timer); };
  }, [root, open, checking]);

  async function action(callback: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await callback(); } catch (caught) { setError(String(caught)); }
    finally { setBusy(false); }
  }
  function inspect() {
    void action(async () => {
      await apiRequest(root + "/inspect", {method: "POST", body: JSON.stringify({...(password ? {password} : {}), ...(passphrase ? {passphrase} : {})})});
      setReport(await apiRequest<Report>(root));
    });
  }
  async function save(item: Item) {
    const mapping = {...Object.fromEntries(item.assets.filter(a => a.mapped).map(a => [a.key, a.value])), ...mappings[item.workflow_id]};
    const next = await apiRequest<Report>(`${root}/${encodeURIComponent(item.workflow_id)}/mapping`, {method: "PUT", body: JSON.stringify({revision: item.revision, mapping})});
    setReport(next); setMappings({}); setNotice("映射已保存。回到生成页面可选择依赖就绪的工作流。");
  }
  return <div className="settings-security">
    <strong>工作流与模型配置</strong>
    <p>按当前已保存的服务器配置检测依赖、选择文件和管理自定义工作流。依赖就绪不代表已验证实际生图。</p>
    <button type="button" onClick={() => setOpen(!open)}>{open ? "收起工作流管理" : "管理工作流"}</button>
    {open && <>
      <div className="host-key-actions">
        <button type="button" disabled={busy || checking} onClick={inspect}>{checking ? "正在检测…" : "检测并刷新服务器能力"}</button>
        {checking && <button type="button" disabled={busy} onClick={() => void action(async () => { await apiRequest(root + "/cancel", {method: "POST"}); setNotice("已请求取消，正在关闭连接。"); })}>取消检测</button>}
        <button type="button" disabled={busy} onClick={() => void action(async () => { setJson(JSON.stringify(await apiRequest(root + "/diagnostics"), null, 2)); setNotice("已生成脱敏诊断：不含地址、凭据、文件路径或提示词。"); })}>生成脱敏诊断</button>
      </div>
      {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
      <p>上次检测：{report?.checked_at ? new Date(report.checked_at * 1000).toLocaleString() : "尚未检测"}</p>
      {report?.items.map(item => <details key={item.workflow_id}>
        <summary>{item.display_name} · {item.origin === "official" ? "内置" : "用户"} · {item.experimental ? "实验（不自动推荐）" : "基线 / 自定义"} · {labels[item.state] || item.state}</summary>
        <p>内容版本：{item.revision.slice(0, 12)}</p>
        {item.errors.length > 0 && <ul>{item.errors.map((message, index) => <li key={index}>{message}</li>)}</ul>}
        {item.assets.map(asset => <label key={asset.key}>{asset.key}<select aria-label={`${item.display_name} ${asset.key}`} disabled={busy || checking || !asset.choices.length} value={mappings[item.workflow_id]?.[asset.key] ?? asset.value} onChange={event => setMappings(current => ({...current, [item.workflow_id]: {...current[item.workflow_id], [asset.key]: event.target.value}}))}>
          {!asset.choices.includes(asset.value) && <option value={asset.value}>{asset.value}（未匹配）</option>}
          {asset.choices.map(choice => <option key={choice} value={choice}>{choice}</option>)}
        </select></label>)}
        <p>请确认所选文件是目标模型权重。文件名本身不能证明模型身份。</p>
        <button type="button" disabled={busy || checking || !mappings[item.workflow_id]} onClick={() => void action(() => save(item))}>保存文件映射</button>
        <button type="button" disabled={busy || checking} onClick={() => void action(async () => { setReport(await apiRequest<Report>(`${root}/${encodeURIComponent(item.workflow_id)}/mapping`, {method: "PUT", body: JSON.stringify({revision: item.revision, mapping: {}})})); setMappings({}); })}>确认使用模板默认文件</button>
        <button type="button" disabled={busy || checking} onClick={() => void action(async () => { await apiRequest(`/api/v3/workflows/${encodeURIComponent(item.workflow_id)}/enabled`, {method: "PUT", body: JSON.stringify({enabled: item.state === "disabled"})}); setReport(await apiRequest<Report>(root)); })}>{item.state === "disabled" ? "启用工作流" : "停用工作流"}</button>
        <button type="button" disabled={busy} onClick={() => void action(async () => { setJson(JSON.stringify(await apiRequest(`/api/v3/workflows/export/${encodeURIComponent(item.workflow_id)}`), null, 2)); setNotice("工作流已载入编辑区。可修改后导入为新副本；分享前请检查节点文本和个人信息。"); })}>导出 / 创建副本</button>
        {item.origin === "official" && <button type="button" disabled={busy} onClick={() => void action(async () => { const result = await apiRequest<{items: {revision: string; display_name: string}[]}>(`/api/v3/workflows/${encodeURIComponent(item.workflow_id)}/versions`); setVersions(current => ({...current, [item.workflow_id]: result.items})); })}>已保存的官方版本</button>}
        {versions[item.workflow_id]?.map(version => <div key={version.revision}>{version.revision.slice(0, 12)} <button type="button" disabled={busy} onClick={() => void action(async () => { await apiRequest(`/api/v3/workflows/${encodeURIComponent(item.workflow_id)}/restore`, {method: "POST", body: JSON.stringify({revision: version.revision})}); setReport(await apiRequest<Report>(root)); setNotice("已恢复为独立用户副本，可检测并选择使用。"); })}>恢复为自定义副本</button></div>)}
      </details>)}
      <label>云端工作流文件路径<input value={remotePath} placeholder="/path/to/workflow.json" onChange={event => setRemotePath(event.target.value)} /></label>
      <button type="button" disabled={busy || checking || !remotePath} onClick={() => void action(async () => { const result = await apiRequest<{document: object}>(root + "/read-file", {method: "POST", body: JSON.stringify({path: remotePath, ...(password ? {password} : {}), ...(passphrase ? {passphrase} : {})})}); setJson(JSON.stringify(result.document, null, 2)); setNotice("云端文件已载入预览，尚未导入。"); })}>读取云端 JSON（预览）</button>
      <label>本地工作流文件<input type="file" accept=".json,application/json" onChange={event => { const file = event.target.files?.[0]; if (file) void action(async () => { if (file.size > 2_000_000) throw new Error("文件不能超过 2 MB"); setJson(await file.text()); }); }} /></label>
      <label>工作流 JSON<textarea aria-label="工作流 JSON" rows={10} value={json} onChange={event => setJson(event.target.value)} /></label>
      <p>支持软件导出的配置 JSON，以及单 KSampler / CLIPTextEncode / EmptyLatentImage 的 API 图。复杂图请提供 display_name、api_workflow、bindings 和 compatible_model_profiles；编辑器格式不自动转换。</p>
      <button type="button" disabled={!json.trim()} onClick={() => { const blob = new Blob([json], {type: "application/json"}); const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = "workflow-export.json"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }}>下载当前 JSON（分享前检查个人信息）</button>
      <button type="button" disabled={busy || checking || !json.trim()} onClick={() => void action(async () => { await apiRequest("/api/v3/workflows/import", {method: "POST", body: JSON.stringify(JSON.parse(json))}); setReport(await apiRequest<Report>(root)); setNotice("已导入为独立用户副本，原工作流保持不变。"); })}>校验并导入新副本</button>
    </>}
  </div>;
}
