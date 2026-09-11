import {useCallback, useEffect, useMemo, useState} from "react";
import {ApiClientError, apiRequest} from "../lib/api";
import {EmptyState, ErrorState, LoadingState} from "../components/States";
type AuthType = "password" | "private_key" | "agent";

type RemoteProfile = {
  id: string;
  display_name: string;
  connection_type?: "ssh" | "local";
  comfy_host?: string;
  comfy_port?: number;
  connection_ready?: boolean;
  ssh_host: string;
  ssh_port: number;
  ssh_user: string;
  auth_type: AuthType;
  private_key_path: string;
  enabled: boolean;
  has_saved_password: boolean;
  host_fingerprint_confirmed: boolean;
  comfy_endpoint: string;
};

type Workflow = {id: string; display_name: string; workflow_kind: string; notes: string};
type ComfyAccess = {
  state: "stopped" | "connecting" | "ready" | "error";
  ready: boolean;
  remote_profile_id: string | null;
  remote_display_name: string | null;
  local_url: string;
  message: string;
  devices: string[];
  queue_running: number;
  queue_pending: number;
};
type SettingsResponse = {items: RemoteProfile[]; workflows: Workflow[]; credential_store_available: boolean; comfy_access?: ComfyAccess | null};
type ProfileForm = Omit<RemoteProfile, "id" | "has_saved_password" | "host_fingerprint_confirmed" | "connection_ready" | "comfy_endpoint"> & {password: string; remember_password: boolean};

const newProfile = (): ProfileForm => ({
  display_name: "我的云端 ComfyUI",
  connection_type: "ssh",
  comfy_host: "127.0.0.1",
  comfy_port: 8188,
  ssh_host: "",
  ssh_port: 22,
  ssh_user: "root",
  auth_type: "password",
  private_key_path: "",
  enabled: true,
  password: "",
  remember_password: true,
});

function formFromProfile(profile: RemoteProfile): ProfileForm {
  return {
    display_name: profile.display_name,
    connection_type: profile.connection_type || "ssh",
    comfy_host: profile.comfy_host || "127.0.0.1",
    comfy_port: profile.comfy_port || 8188,
    ssh_host: profile.ssh_host,
    ssh_port: profile.ssh_port,
    ssh_user: profile.ssh_user,
    auth_type: profile.auth_type,
    private_key_path: profile.private_key_path,
    enabled: profile.enabled,
    password: "",
    remember_password: profile.has_saved_password,
  };
}

export function SettingsPage({remoteEnabled}: {remoteEnabled: boolean}) {
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [form, setForm] = useState<ProfileForm>(newProfile);
  const [error, setError] = useState<ApiClientError | null>(null);
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [fingerprint, setFingerprint] = useState("");
  const [probing, setProbing] = useState(false);
  const [testing, setTesting] = useState(false);
  const [comfyOpening, setComfyOpening] = useState(false);
  const [comfyAccess, setComfyAccess] = useState<ComfyAccess | null>(null);
  const [privateKeyPassphrase, setPrivateKeyPassphrase] = useState("");

  const selected = useMemo(() => settings?.items.find((item) => item.id === selectedId) || null, [settings, selectedId]);
  const endpointDirty = !!selected && (["connection_type", "comfy_host", "comfy_port", "ssh_host", "ssh_port", "ssh_user", "auth_type", "private_key_path"] as const).some(key => form[key] !== formFromProfile(selected)[key]);
  const comfyUrl = selected?.connection_type === "local" ? `http://${selected.comfy_host === "::1" ? "[::1]" : selected.comfy_host || "127.0.0.1"}:${selected.comfy_port || 8188}` : comfyAccess?.remote_profile_id === selectedId ? comfyAccess.local_url : "http://127.0.0.1:18188";
  const refresh = useCallback(async () => {
    setError(null);
    try {
      const response = await apiRequest<SettingsResponse>("/api/v3/settings/remote-profiles");
      setSettings(response);
      setComfyAccess(response.comfy_access || null);
      setSelectedId((current) => current && response.items.some((item) => item.id === current) ? current : response.items[0]?.id || null);
    } catch (caught) {
      setError(caught as ApiClientError);
    }
  }, []);

  useEffect(() => { if (remoteEnabled) void refresh(); }, [remoteEnabled, refresh]);
  useEffect(() => { if (selected) setForm(formFromProfile(selected)); }, [selected]);

  function selectProfile(profile: RemoteProfile) {
    setNotice("");
    setFingerprint("");
    setPrivateKeyPassphrase("");
    setSelectedId(profile.id);
    setForm(formFromProfile(profile));
  }

  function startNew() {
    setNotice("");
    setFingerprint("");
    setPrivateKeyPassphrase("");
    setSelectedId(null);
    setForm(newProfile());
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setNotice("");
    const payload = {
      ...form,
      password: form.password || undefined,
      private_key_path: form.auth_type === "private_key" ? form.private_key_path : "",
    };
    try {
      const enteredPassword = form.password;
      const saved = await apiRequest<RemoteProfile>(selectedId ? `/api/v3/settings/remote-profiles/${selectedId}` : "/api/v3/settings/remote-profiles", {
        method: selectedId ? "PUT" : "POST",
        body: JSON.stringify(payload),
      });
      await refresh();
      setSelectedId(saved.id);
      setForm({...formFromProfile(saved), password: form.remember_password ? "" : enteredPassword});
      setNotice(saved.connection_type === "local" ? "本地连接已保存，可以测试 ComfyUI。" : saved.host_fingerprint_confirmed ? "远程连接已保存，可以继续执行完整连接测试。" : "远程连接已保存。请在下方检测并确认 SSH 主机指纹。");
    } catch (caught) {
      setError(caught as ApiClientError);
    } finally {
      setSaving(false);
    }
  }

  async function probeHostKey() {
    if (!selectedId) return;
    setProbing(true);
    setError(null);
    setNotice("");
    try {
      const result = await apiRequest<{fingerprint: string}>(`/api/v3/settings/remote-profiles/${selectedId}/probe-host-key`, {method: "POST", body: JSON.stringify({})});
      setFingerprint(result.fingerprint);
      setNotice("已读取 SSH 主机指纹。请核对后点击“确认并保存指纹”。");
    } catch (caught) {
      setError(caught as ApiClientError);
    } finally {
      setProbing(false);
    }
  }

  async function confirmHostKey() {
    if (!selectedId || !fingerprint) return;
    setProbing(true);
    setError(null);
    try {
      const saved = await apiRequest<RemoteProfile>(`/api/v3/settings/remote-profiles/${selectedId}/confirm-host-key`, {method: "POST", body: JSON.stringify({fingerprint})});
      setFingerprint("");
      setNotice("SSH 主机指纹已确认并保存，可用于 V3 远程生成。");
      await refresh();
      setSelectedId(saved.id);
    } catch (caught) {
      setError(caught as ApiClientError);
    } finally {
      setProbing(false);
    }
  }

  async function testConnection() {
    if (!selectedId) return;
    setTesting(true);
    setError(null);
    setNotice("");
    try {
      const result = await apiRequest<{ok: true; devices: string[]; queue_running: number; queue_pending: number; comfy_endpoint: string}>(`/api/v3/settings/remote-profiles/${selectedId}/test-connection`, {
        method: "POST",
        body: JSON.stringify({
          ...(form.password ? {password: form.password} : {}),
          ...(privateKeyPassphrase ? {passphrase: privateKeyPassphrase} : {}),
        }),
      });
      const device = result.devices.length ? result.devices.join("、") : "未返回设备名称";
      setNotice(`连接正常 · ${device} · ComfyUI ${result.comfy_endpoint} · 队列 ${result.queue_running + result.queue_pending}`);
    } catch (caught) {
      setError(caught as ApiClientError);
    } finally {
      setTesting(false);
    }
  }

  async function openComfy() {
    if (!selectedId) return;
    const popup = window.open("about:blank", "anima-comfyui");
    setComfyOpening(true);
    setError(null);
    setNotice("");
    try {
      const result = await apiRequest<ComfyAccess>(`/api/v3/settings/remote-profiles/${selectedId}/open-comfy`, {
        method: "POST",
        body: JSON.stringify({
          ...(form.password ? {password: form.password} : {}),
          ...(privateKeyPassphrase ? {passphrase: privateKeyPassphrase} : {}),
        }),
      });
      setComfyAccess(result);
      setNotice(`ComfyUI 维护入口已连接：${result.local_url}`);
      if (popup) popup.location.replace(result.local_url);
      else window.open(result.local_url, "_blank", "noopener,noreferrer");
    } catch (caught) {
      popup?.close();
      setError(caught as ApiClientError);
    } finally {
      setComfyOpening(false);
    }
  }

  if (!remoteEnabled) {
    return <section className="page settings-page"><SettingsHeader count="—" /><EmptyState title="远程设置尚未启用" detail="请从 V3 桌面入口启动，并让它检测到 V2 数据库；V3 会复用其中的云主机、工作流和 Windows 凭据。" /></section>;
  }

  return <section className="page settings-page">
    <SettingsHeader count={settings?.items.length ?? "—"} />
    {error && <ErrorState message={error.message} requestId={error.requestId} />}
    {!settings ? <LoadingState label="正在读取 V2 远程连接配置…" /> : <>
    <div className="settings-ranking"><h2>画师推荐</h2><p>在工作台展开“画师推荐”，可随时切换排序并选择画师。</p><a href="/workbench">打开工作台</a></div>
    <div className="settings-layout">
      <aside className="settings-side">
        <div className="settings-side-head"><span>CONNECTIONS</span><button type="button" className="button button--secondary" onClick={startNew}>＋ 新建</button></div>
        <div className="remote-profile-list">
          {settings.items.map((profile) => <button type="button" key={profile.id} className={`remote-profile-item${profile.id === selectedId ? " is-selected" : ""}`} onClick={() => selectProfile(profile)}>
            <span className={profile.enabled && (profile.connection_ready ?? profile.host_fingerprint_confirmed) ? "status-dot is-ready" : "status-dot"} /><span><strong>{profile.display_name}</strong><small>{profile.connection_type === "local" ? `本机 · ${profile.comfy_endpoint}` : `${profile.ssh_user}@${profile.ssh_host}:${profile.ssh_port} · ${profile.host_fingerprint_confirmed ? "指纹已确认" : "待确认指纹"}`}</small></span>
          </button>)}
          {!settings.items.length && <p>尚未配置执行环境。</p>}
        </div>
        <div className="settings-workflows"><strong>本地工作流模板</strong><p>模板导入、模型关联和版本管理已集中到独立页面。</p><a href="/workflows">打开工作流模板库</a></div>
      </aside>
      <form className="settings-form" onSubmit={(event) => void save(event)}>
        <div className="settings-form-head"><div><span className="eyebrow">COMFYUI</span><h2>{selected ? "编辑连接" : "新增连接"}</h2><p>选择本机直连或云端 SSH；保存后在工作流页面检测并映射资源。</p></div><button className="button button--primary" type="submit" disabled={saving}>{saving ? "保存中…" : "保存连接"}</button></div>
        {endpointDirty && <p role="status">连接信息已修改，请先保存再测试或打开网页。</p>}
        {notice && <div className="workspace-notice" role="status" style={{whiteSpace: "pre-wrap"}}>{notice}</div>}
        <fieldset>
          <legend>连接信息</legend>
          <label>连接类型<select value={form.connection_type} onChange={e => {setForm({...form, connection_type: e.target.value as "ssh" | "local", password: ""}); setPrivateKeyPassphrase(""); setFingerprint("");}}><option value="ssh">云端 SSH</option><option value="local">本地 ComfyUI</option></select></label>
          <label>显示名称<input required value={form.display_name} onChange={(event) => setForm({...form, display_name: event.target.value})} /></label>
          {form.connection_type !== "local" && <><label>SSH 地址<input required placeholder="117.50.80.146" value={form.ssh_host} onChange={(event) => setForm({...form, ssh_host: event.target.value})} /></label>
          <label>端口<input required type="number" min="1" max="65535" value={form.ssh_port} onChange={(event) => setForm({...form, ssh_port: Number(event.target.value)})} /></label>
          <label>用户名<input required value={form.ssh_user} onChange={(event) => setForm({...form, ssh_user: event.target.value})} /></label></>}
          {form.connection_type === "local" && <><label>ComfyUI 本机地址<select value={form.comfy_host} onChange={e => setForm({...form, comfy_host: e.target.value})}><option>127.0.0.1</option><option>localhost</option><option>::1</option></select></label><label>ComfyUI 端口<input type="number" required min="1" max="65535" value={form.comfy_port} onChange={e => setForm({...form, comfy_port: Number(e.target.value)})} /></label><p>先启动本机 ComfyUI，再测试连接。</p></>}
        </fieldset>
        {form.connection_type !== "local" && <fieldset>
          <legend>认证方式</legend>
          <label>方式<select value={form.auth_type} onChange={(event) => setForm({...form, auth_type: event.target.value as AuthType})}><option value="password">密码</option><option value="private_key">私钥文件</option><option value="agent">SSH Agent</option></select></label>
          {form.auth_type === "password" && <label>SSH 密码<input type="password" placeholder={selected?.has_saved_password ? "留空：保留已保存密码" : "输入后保存到 Windows 凭据管理器"} value={form.password} onChange={(event) => setForm({...form, password: event.target.value})} autoComplete="new-password" /></label>}
          {form.auth_type === "private_key" && <label>私钥路径<input required placeholder="C:\\Users\\you\\.ssh\\id_ed25519" value={form.private_key_path} onChange={(event) => setForm({...form, private_key_path: event.target.value})} /></label>}
          {form.auth_type === "private_key" && <label>私钥口令（可选，仅本次测试）<input type="password" autoComplete="current-password" value={privateKeyPassphrase} onChange={(event) => setPrivateKeyPassphrase(event.target.value)} /></label>}
          {form.auth_type === "password" && <label className="check-label"><input type="checkbox" checked={form.remember_password} onChange={(event) => setForm({...form, remember_password: event.target.checked})} /> 安全保存密码到 Windows 凭据管理器</label>}
        </fieldset>}
        <label className="check-label"><input type="checkbox" checked={form.enabled} onChange={(event) => setForm({...form, enabled: event.target.checked})} /> 在生成列表中启用此连接</label>
        {form.connection_type === "local" && selected?.connection_type === "local" && <div className="settings-security"><button type="button" className="button button--primary" onClick={() => void testConnection()} disabled={endpointDirty || saving || testing}>{testing ? "正在测试 ComfyUI…" : "测试本地连接"}</button></div>}
        {form.connection_type !== "local" && <div className="settings-security"><strong>SSH 指纹与连接测试</strong><p>{selected?.host_fingerprint_confirmed ? "主机指纹已确认。更改地址、端口、用户名、认证方式或私钥后会自动要求重新确认。完整测试会继续验证 SSH 登录、隧道和 ComfyUI API。" : "新建连接尚未确认主机指纹。检测不会自动信任主机；请核对显示的指纹后确认保存。"}</p>{selected && <div className="host-key-actions"><button type="button" className="button button--secondary" onClick={() => void probeHostKey()} disabled={probing || testing}>{probing ? "检测中…" : "检测 SSH 指纹"}</button>{fingerprint && <><code>{fingerprint}</code><button type="button" className="button button--secondary" onClick={() => void confirmHostKey()} disabled={probing || testing}>确认并保存指纹</button></>}<button type="button" className="button button--primary" onClick={() => void testConnection()} disabled={endpointDirty || saving || !selected.host_fingerprint_confirmed || probing || testing}>{testing ? "正在测试 SSH 与 ComfyUI…" : "测试完整连接"}</button></div>}</div>}
        <div className="settings-security">
          <strong>ComfyUI 网页维护入口</strong>
          <p>{form.connection_type === "local" ? "直接打开已启动的本机 ComfyUI 网页。" : "项目运行期间通过本机 SSH 隧道访问云端 ComfyUI。"}</p>
          <div className="host-key-actions">
            <a href={comfyUrl} target="_blank" rel="noreferrer"><code>{comfyUrl}</code></a>
            <button type="button" className="button button--primary" onClick={() => void openComfy()} disabled={endpointDirty || saving || !(selected?.connection_ready ?? selected?.host_fingerprint_confirmed) || comfyOpening || testing || probing}>{comfyOpening ? "正在连接 ComfyUI…" : "打开 ComfyUI 网页"}</button>
          </div>
          <small>{comfyAccess?.remote_profile_id === selectedId ? comfyAccess.message : "保存连接后，可在这里打开 ComfyUI 网页。"}</small>
        </div>
      </form>
      {selectedId && <div className="settings-security"><strong>工作流资源映射</strong><p>保存连接配置后，在工作流页面检测当前环境并确认模型文件。</p><a href={`/workflows?environment=${encodeURIComponent(selectedId)}`}>管理此环境的工作流资源</a></div>}
    </div>
    </>}
  </section>;
}

function SettingsHeader({count}: {count: number | string}) {
  return <header className="page-header"><div><span className="eyebrow">SETTINGS</span><h1>设置</h1><p>管理连接、认证与应用偏好。模板和文件映射位于工作流页面。</p></div><div className="header-stat"><strong>{count}</strong><span>connections</span></div></header>;
}
