import {useRef, useState} from "react";
import {Link} from "react-router-dom";
import {apiRequest} from "../lib/api";

export type ResourceIdentity = {logical_id: string; file_name: string; resource_digest: string};
type Binding = {logical_id: string; resource_digest: string; slot_key: string; remote_file_name: string};
type Mapping = {mapping_revision: number; workflow_revision: string; remote_fingerprint: string;
  current: boolean; capabilities_ready: boolean; slots: Record<string, string[]>; bindings: Binding[]};

export function LoraMappingPanel({remote, workflow, resources, disabled, onSaved}: {
  remote: string; workflow: string; resources: ResourceIdentity[]; disabled: boolean; onSaved: () => void;
}) {
  const [mapping, setMapping] = useState<Mapping | null>(null);
  const [bindings, setBindings] = useState<Binding[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const path = `/api/v3/workflows/servers/${encodeURIComponent(remote)}/${encodeURIComponent(workflow)}/lora-bindings`;
  async function act(action: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setMessage("");
    try {await action();} catch (error) {setMessage((error as Error).message);}
    finally {lock.current = false; setBusy(false);}
  }
  async function load() {
    const next = await apiRequest<Mapping>(path);
    setMapping(next);
    setBindings(next.bindings.filter(binding => resources.some(resource => resource.logical_id === binding.logical_id && resource.resource_digest === binding.resource_digest)));
  }
  function replace(resource: ResourceIdentity, binding?: Binding) {
    setBindings(previous => [...previous.filter(item => item.logical_id !== resource.logical_id), ...(binding ? [binding] : [])]);
  }
  return <details onToggle={event => {if (event.currentTarget.open && !mapping) void act(load);}}>
    <summary>LoRA 文件与工作流插槽映射</summary>
    <fieldset disabled={disabled || busy} className="lora-mapping-fields">
      <button onClick={() => void act(load)}>读取最新映射</button>
      {mapping && !mapping.capabilities_ready && <p>服务器能力尚未检测或已过期。请在<Link to="/settings">设置中的工作流管理</Link>中检测服务器，再读取映射。</p>}
      {mapping && !mapping.current && <p>工作流或连接已变化，请重新确认下面的文件与插槽。</p>}
      {mapping?.capabilities_ready && resources.map(resource => {
        const binding = bindings.find(item => item.logical_id === resource.logical_id);
        return <div key={resource.logical_id} className="conversation-layer"><strong>{resource.logical_id}</strong><p>{resource.file_name}</p>
          <label>工作流插槽<select value={binding?.slot_key || ""} onChange={event => {
            const slot = event.target.value;
            replace(resource, slot ? {logical_id: resource.logical_id, resource_digest: resource.resource_digest, slot_key: slot, remote_file_name: ""} : undefined);
          }}><option value="">自动匹配精确文件名</option>{Object.keys(mapping.slots).map(slot => <option key={slot}>{slot}</option>)}</select></label>
          {binding && <label>服务器上的文件<select value={binding.remote_file_name} onChange={event => replace(resource, {...binding, remote_file_name: event.target.value})}>
            <option value="">选择已安装的文件</option>{(mapping.slots[binding.slot_key] || []).map(name => <option key={name}>{name}</option>)}</select></label>}
        </div>;
      })}
      <p>保存会替换此服务器与工作流的整份 LoRA 映射，只保留上面选定的条目。不会下载文件。</p>
      <button disabled={!mapping?.capabilities_ready || bindings.some(item => !item.remote_file_name || !(mapping.slots[item.slot_key] || []).includes(item.remote_file_name))
        || new Set(bindings.map(item => item.slot_key)).size !== bindings.length}
        onClick={() => void act(async () => {
          if (!mapping) return;
          await apiRequest(path, {method: "PUT", body: JSON.stringify({mapping_revision: mapping.mapping_revision,
            workflow_revision: mapping.workflow_revision, remote_fingerprint: mapping.remote_fingerprint, bindings})});
          await load(); onSaved(); setMessage("映射已保存，正在重新检查资源。");
        })}>保存资源映射</button>
    </fieldset>
    {message && <p role="status">{message}</p>}
  </details>;
}
