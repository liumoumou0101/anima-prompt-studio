import {useEffect, useState} from "react";
import {apiRequest} from "../lib/api";

type Asset = {key: string; value: string; template_value?: string; node_type?: string; choices: string[]; mapped: boolean};
type Item = {workflow_id: string; display_name: string; revision: string; state: string; errors: string[]; assets: Asset[]};
type Report = {remote_profile_id: string; checked_at: number | null; items: Item[]; inspection?: {state: string; error?: string}};
const labels: Record<string, string> = {ready: "依赖就绪", unchecked: "未检测", stale: "需重新检测", missing_nodes: "缺少节点", invalid_inputs: "资源或参数不匹配", connection_failed: "连接失败", mapping_stale: "映射需确认", disabled: "模板已停用"};

export function WorkflowManager({remoteId, password, passphrase, workflowId, expanded = false, onDocument}: {
  remoteId: string; password: string; passphrase: string; workflowId?: string; expanded?: boolean; onDocument?: (document: object) => void;
}) {
  const [open, setOpen] = useState(expanded);
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [diagnostics, setDiagnostics] = useState("");
  const [remotePath, setRemotePath] = useState("");
  const [mappings, setMappings] = useState<Record<string, Record<string, string>>>({});
  const root = `/api/v3/workflows/servers/${encodeURIComponent(remoteId)}`;
  const checking = report?.inspection?.state === "running";

  useEffect(() => {
    setReport(null); setMappings({}); setError(""); setNotice(""); setDiagnostics("");
  }, [root, workflowId]);
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
  }, [root, workflowId, open, checking]);

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
  async function save(item: Item, defaults = false) {
    const mapping = defaults ? {} : {...Object.fromEntries(item.assets.filter(a => a.mapped).map(a => [a.key, a.value])), ...mappings[item.workflow_id]};
    setReport(await apiRequest<Report>(`${root}/${encodeURIComponent(item.workflow_id)}/mapping`, {method: "PUT", body: JSON.stringify({revision: item.revision, mapping})}));
    setMappings({}); setNotice("映射已保存，仅对当前执行环境生效。本地模板未改变。");
  }
  return <section className="settings-security" aria-label="环境资源映射">
    <h3>环境资源映射</h3>
    <p>本地模板 → 当前环境中的实际文件 → 提交完整工作流。云端无需保存同名工作流。依赖就绪不代表已验证生图效果。</p>
    {!expanded && <button type="button" onClick={() => setOpen(!open)}>{open ? "收起工作流管理" : "管理工作流"}</button>}
    {open && <>
      <div className="host-key-actions">
        <button type="button" disabled={busy || checking} onClick={inspect}>{checking ? "正在检测…" : "检测并刷新服务器能力"}</button>
        <button type="button" disabled={busy} onClick={() => void action(async () => {setDiagnostics(JSON.stringify(await apiRequest(root + "/diagnostics"), null, 2));})}>生成脱敏诊断</button>
        {checking && <button type="button" disabled={busy} onClick={() => void action(async () => { await apiRequest(root + "/cancel", {method: "POST"}); setNotice("已请求取消，正在关闭连接。"); })}>取消检测</button>}
      </div>
      {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
      {diagnostics && <label>脱敏诊断<textarea readOnly rows={6} value={diagnostics} /></label>}
      <p>上次检测：{report?.checked_at ? new Date(report.checked_at * 1000).toLocaleString() : "尚未检测"}。打开页面仅读取本地记录，点击检测才会连接服务器。</p>
      {report?.items.filter(item => !workflowId || item.workflow_id === workflowId).map(item => {
        const unavailable = busy || checking || ["unchecked", "stale", "connection_failed", "disabled"].includes(item.state);
        return <div key={item.workflow_id} className="workflow-environment-report">
          <h4>{item.display_name} · {labels[item.state] || item.state}</h4>
          <p>模板版本：{item.revision.slice(0, 12)}</p>
          {item.errors.length > 0 && <ul>{item.errors.map((message, index) => <li key={index}>{message}</li>)}</ul>}
          {item.assets.map(asset => <label key={asset.key} className="workflow-asset-field">
            <span>{asset.node_type || "模型文件"} · {asset.key}</span>
            <small>模板文件：{asset.template_value ?? asset.value} · {asset.mapped ? "已确认映射" : "沿用模板"}</small>
            <select aria-label={`${item.display_name} ${asset.key}`} disabled={unavailable || !asset.choices.length} value={mappings[item.workflow_id]?.[asset.key] ?? asset.value} onChange={event => setMappings(current => ({...current, [item.workflow_id]: {...current[item.workflow_id], [asset.key]: event.target.value}}))}>
              {!asset.choices.includes(asset.value) && <option value={asset.value}>{asset.value}（未匹配）</option>}
              {asset.choices.map(choice => <option key={choice} value={choice}>{choice}</option>)}
            </select>
          </label>)}
          <p>确认所选文件对应目标权重后保存。更换环境不会继承这里的文件映射。</p>
          <button type="button" disabled={unavailable || !mappings[item.workflow_id]} onClick={() => void action(() => save(item))}>保存文件映射</button>
          <button type="button" disabled={unavailable} onClick={() => void action(() => save(item, true))}>确认使用模板默认文件</button>
        </div>;
      })}
      {onDocument && <details><summary>从云端文件导入本地模板（可选）</summary>
        <label>云端工作流文件路径<input value={remotePath} placeholder="/path/to/workflow.json" onChange={event => setRemotePath(event.target.value)} /></label>
        <button type="button" disabled={busy || checking || !remotePath} onClick={() => void action(async () => {
          const result = await apiRequest<{document: object}>(root + "/read-file", {method: "POST", body: JSON.stringify({path: remotePath, ...(password ? {password} : {}), ...(passphrase ? {passphrase} : {})})});
          onDocument(result.document);
        })}>读取云端 JSON 到本地预览</button>
      </details>}
    </>}
  </section>;
}
