import {useCallback, useEffect, useMemo, useState} from "react";
import {ApiClientError, apiRequest} from "../lib/api";
import {EmptyState, ErrorState, LoadingState} from "../components/States";

type AuthType = "password" | "private_key" | "agent";

type RemoteProfile = {
  id: string;
  display_name: string;
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
type SettingsResponse = {items: RemoteProfile[]; workflows: Workflow[]; credential_store_available: boolean};
type ProfileForm = Omit<RemoteProfile, "id" | "has_saved_password" | "host_fingerprint_confirmed" | "comfy_endpoint"> & {password: string; remember_password: boolean};

const newProfile = (): ProfileForm => ({
  display_name: "我的云端 ComfyUI",
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

  const selected = useMemo(() => settings?.items.find((item) => item.id === selectedId) || null, [settings, selectedId]);
  const refresh = useCallback(async () => {
    setError(null);
    try {
      const response = await apiRequest<SettingsResponse>("/api/v3/settings/remote-profiles");
      setSettings(response);
      setSelectedId((current) => current && response.items.some((item) => item.id === current) ? current : response.items[0]?.id || null);
    } catch (caught) {
      setError(caught as ApiClientError);
    }
  }, []);

  useEffect(() => { if (remoteEnabled) void refresh(); }, [remoteEnabled, refresh]);
  useEffect(() => { if (selected) setForm(formFromProfile(selected)); }, [selected]);

  function selectProfile(profile: RemoteProfile) {
    setNotice("");
    setSelectedId(profile.id);
    setForm(formFromProfile(profile));
  }

  function startNew() {
    setNotice("");
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
      const saved = await apiRequest<RemoteProfile>(selectedId ? `/api/v3/settings/remote-profiles/${selectedId}` : "/api/v3/settings/remote-profiles", {
        method: selectedId ? "PUT" : "POST",
        body: JSON.stringify(payload),
      });
      await refresh();
      setSelectedId(saved.id);
      setForm(formFromProfile(saved));
      setNotice(saved.host_fingerprint_confirmed ? "远程连接已保存。" : "远程连接已保存。首次生成前，请在 V2 的连接检测中确认 SSH 主机指纹。");
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

  if (!remoteEnabled) {
    return <section className="page settings-page"><SettingsHeader count="—" /><EmptyState title="远程设置尚未启用" detail="请从 V3 桌面入口启动，并让它检测到 V2 数据库；V3 会复用其中的云主机、工作流和 Windows 凭据。" /></section>;
  }

  return <section className="page settings-page">
    <SettingsHeader count={settings?.items.length ?? "—"} />
    {error && <ErrorState message={error.message} requestId={error.requestId} />}
    {!settings ? <LoadingState label="正在读取 V2 远程连接配置…" /> : <div className="settings-layout">
      <aside className="settings-side">
        <div className="settings-side-head"><span>REMOTE CONNECTIONS</span><button type="button" className="button button--secondary" onClick={startNew}>＋ 新建</button></div>
        <div className="remote-profile-list">
          {settings.items.map((profile) => <button type="button" key={profile.id} className={`remote-profile-item${profile.id === selectedId ? " is-selected" : ""}`} onClick={() => selectProfile(profile)}>
            <span className={profile.enabled ? "status-dot is-ready" : "status-dot"} /><span><strong>{profile.display_name}</strong><small>{profile.ssh_user}@{profile.ssh_host}:{profile.ssh_port}</small></span>
          </button>)}
          {!settings.items.length && <p>尚未配置云主机。</p>}
        </div>
        <div className="settings-workflows"><span>WORKFLOWS</span>{settings.workflows.length ? settings.workflows.map((workflow) => <div key={workflow.id}><strong>{workflow.display_name}</strong><small>{workflow.workflow_kind === "unknown" ? "自定义 API 工作流" : workflow.workflow_kind}</small></div>) : <p>尚未导入 API 工作流。可继续使用 V2 的“导入 ComfyUI API 工作流”。</p>}</div>
      </aside>
      <form className="settings-form" onSubmit={(event) => void save(event)}>
        <div className="settings-form-head"><div><span className="eyebrow">REMOTE SSH</span><h2>{selected ? "编辑远程连接" : "新增远程连接"}</h2><p>连接配置与 V2 共用；保存后生成页面会自动读取最新配置。</p></div><button className="button button--primary" type="submit" disabled={saving}>{saving ? "保存中…" : "保存连接"}</button></div>
        {notice && <div className="workspace-notice">{notice}</div>}
        <fieldset>
          <legend>连接信息</legend>
          <label>显示名称<input required value={form.display_name} onChange={(event) => setForm({...form, display_name: event.target.value})} /></label>
          <label>SSH 地址<input required placeholder="117.50.80.146" value={form.ssh_host} onChange={(event) => setForm({...form, ssh_host: event.target.value})} /></label>
          <label>端口<input required type="number" min="1" max="65535" value={form.ssh_port} onChange={(event) => setForm({...form, ssh_port: Number(event.target.value)})} /></label>
          <label>用户名<input required value={form.ssh_user} onChange={(event) => setForm({...form, ssh_user: event.target.value})} /></label>
        </fieldset>
        <fieldset>
          <legend>认证方式</legend>
          <label>方式<select value={form.auth_type} onChange={(event) => setForm({...form, auth_type: event.target.value as AuthType})}><option value="password">密码</option><option value="private_key">私钥文件</option><option value="agent">SSH Agent</option></select></label>
          {form.auth_type === "password" && <label>SSH 密码<input type="password" placeholder={selected?.has_saved_password ? "留空：保留已保存密码" : "输入后保存到 Windows 凭据管理器"} value={form.password} onChange={(event) => setForm({...form, password: event.target.value})} autoComplete="new-password" /></label>}
          {form.auth_type === "private_key" && <label>私钥路径<input required placeholder="C:\\Users\\you\\.ssh\\id_ed25519" value={form.private_key_path} onChange={(event) => setForm({...form, private_key_path: event.target.value})} /></label>}
          {form.auth_type === "password" && <label className="check-label"><input type="checkbox" checked={form.remember_password} onChange={(event) => setForm({...form, remember_password: event.target.checked})} /> 安全保存密码到 Windows 凭据管理器</label>}
          <label className="check-label"><input type="checkbox" checked={form.enabled} onChange={(event) => setForm({...form, enabled: event.target.checked})} /> 在生成列表中启用此连接</label>
        </fieldset>
        <div className="settings-security"><strong>SSH 指纹保护</strong><p>{selected?.host_fingerprint_confirmed ? "此连接已有已确认的主机指纹。更改地址、端口、用户名、认证方式或私钥后会自动要求重新确认。" : "新建连接尚未确认主机指纹。检测不会自动信任主机；请确认显示的指纹后再保存。"}</p>{selected && <div className="host-key-actions"><button type="button" className="button button--secondary" onClick={() => void probeHostKey()} disabled={probing}>{probing ? "检测中…" : "检测 SSH 指纹"}</button>{fingerprint && <><code>{fingerprint}</code><button type="button" className="button button--secondary" onClick={() => void confirmHostKey()} disabled={probing}>确认并保存指纹</button></>}</div>}</div>
      </form>
    </div>}
  </section>;
}

function SettingsHeader({count}: {count: number | string}) {
  return <header className="page-header"><div><span className="eyebrow">SETTINGS</span><h1>设置</h1><p>集中管理 V3 所复用的 V2 云主机与 ComfyUI 工作流。</p></div><div className="header-stat"><strong>{count}</strong><span>connections</span></div></header>;
}
