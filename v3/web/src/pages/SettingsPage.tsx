import {useCallback, useEffect, useMemo, useRef, useState} from "react";
import {ApiClientError, apiRequest} from "../lib/api";
import {notifyLoraEnvironmentChanged} from "../lib/loraLibrary";
import {EmptyState, ErrorState, LoadingState} from "../components/States";
import {AppearanceControls} from "../components/AppearanceControls";
import {TemporaryConnectionImport} from "../components/TemporaryConnectionImport";
import "./libraryPages.css";
type AuthType = "password" | "private_key" | "agent";

export type RemoteProfile = {
  id: string;
  display_name: string;
  connection_type?: "ssh" | "local" | "http";
  http_base_url?: string;
  http_session_id?: string;
  http_runtime_id?: string;
  has_saved_api_key?: boolean;
  web_url?: string;
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
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const deleteLock = useRef(false);

  const selected = useMemo(() => settings?.items.find((item) => item.id === selectedId) || null, [settings, selectedId]);
  const deleteTarget = useMemo(() => settings?.items.find((item) => item.id === deleteConfirmId) || null, [settings, deleteConfirmId]);
  const endpointDirty = !!selected && (["connection_type", "comfy_host", "comfy_port", "ssh_host", "ssh_port", "ssh_user", "auth_type", "private_key_path"] as const).some(key => form[key] !== formFromProfile(selected)[key]);
  const isHttp = form.connection_type === "http";
  const isSsh = !isHttp && form.connection_type !== "local";
  const comfyUrl = selected?.connection_type === "http" ? selected.web_url || "" : selected?.connection_type === "local" ? `http://${selected.comfy_host === "::1" ? "[::1]" : selected.comfy_host || "127.0.0.1"}:${selected.comfy_port || 8188}` : comfyAccess?.remote_profile_id === selectedId ? comfyAccess.local_url : "http://127.0.0.1:18188";
  const refresh = useCallback(async (): Promise<SettingsResponse | null> => {
    setError(null);
    try {
      const response = await apiRequest<SettingsResponse>("/api/v3/settings/remote-profiles");
      setSettings(response);
      setComfyAccess(response.comfy_access || null);
      setSelectedId((current) => current && response.items.some((item) => item.id === current) ? current : response.items[0]?.id || null);
      return response;
    } catch (caught) {
      setError(caught as ApiClientError);
      return null;
    }
  }, []);

  useEffect(() => { if (remoteEnabled) void refresh(); }, [remoteEnabled, refresh]);
  useEffect(() => { if (selected) setForm(formFromProfile(selected)); }, [selected]);

  function selectProfile(profile: RemoteProfile) {
    if (deleting || importOpen) return;
    setNotice("");
    setFingerprint("");
    setPrivateKeyPassphrase("");
    setDeleteConfirmId(null);
    setSelectedId(profile.id);
    setForm(formFromProfile(profile));
  }

  function startNew() {
    if (deleting || importOpen) return;
    setNotice("");
    setFingerprint("");
    setPrivateKeyPassphrase("");
    setDeleteConfirmId(null);
    setSelectedId(null);
    setForm(newProfile());
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (deleting || importOpen) return;
    setSaving(true);
    setError(null);
    setNotice("");
    const payload = isHttp ? {connection_type: "http", display_name: form.display_name, enabled: form.enabled} : {
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
      notifyLoraEnvironmentChanged(saved.id);
      await refresh();
      setSelectedId(saved.id);
      setForm({...formFromProfile(saved), password: form.remember_password ? "" : enteredPassword});
      setNotice(saved.connection_type === "http" ? "临时连接设置已保存；地址与密钥未更改。" : saved.connection_type === "local" ? "本地连接已保存，可以测试 ComfyUI。" : saved.host_fingerprint_confirmed ? "远程连接已保存，可以继续执行完整连接测试。" : "远程连接已保存。请在下方检测并确认 SSH 主机指纹。");
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
      notifyLoraEnvironmentChanged(saved.id);
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
      setNotice(isHttp ? `已打开网关登录入口：${result.local_url}。请在浏览器中手动输入访问密钥。` : `ComfyUI 维护入口已连接：${result.local_url}`);
      if (popup) popup.location.replace(result.local_url);
      else window.open(result.local_url, "_blank", "noopener,noreferrer");
    } catch (caught) {
      popup?.close();
      setError(caught as ApiClientError);
    } finally {
      setComfyOpening(false);
    }
  }

  async function deleteProfile() {
    if (deleteLock.current || deleting || saving || probing || testing || comfyOpening || !deleteConfirmId || !settings) return;
    const targetId = deleteConfirmId;
    const target = settings.items.find((item) => item.id === targetId);
    if (!target) return;
    const targetIndex = settings.items.findIndex((item) => item.id === targetId);
    deleteLock.current = true;
    setDeleting(true);
    setError(null);
    setNotice("");
    try {
      await apiRequest<void>(`/api/v3/settings/remote-profiles/${encodeURIComponent(targetId)}`, {
        method: "DELETE",
        body: JSON.stringify({}),
      });
      const remaining = settings.items.filter((item) => item.id !== targetId);
      notifyLoraEnvironmentChanged(targetId);
      const optimisticNext = remaining[Math.min(targetIndex, remaining.length - 1)] || null;
      setSettings({...settings, items: remaining, comfy_access: settings.comfy_access?.remote_profile_id === targetId ? null : settings.comfy_access});
      setDeleteConfirmId(null);
      setFingerprint("");
      setPrivateKeyPassphrase("");
      setComfyAccess((current) => current?.remote_profile_id === targetId ? null : current);
      if (optimisticNext) {
        setSelectedId(optimisticNext.id);
        setForm(formFromProfile(optimisticNext));
      } else {
        setSelectedId(null);
        setForm(newProfile());
      }
      setNotice(`已删除连接“${target.display_name}”。本地连接配置和已保存${target.connection_type === "http" ? "访问密钥" : "密码"}已移除；生成记录、图片和远端主机内容都会保留。`);
      const response = await refresh();
      if (!response) return;
      const next = response.items[Math.min(targetIndex, response.items.length - 1)] || null;
      if (next) {
        setSelectedId(next.id);
        setForm(formFromProfile(next));
      } else {
        setSelectedId(null);
        setForm(newProfile());
      }
    } catch (caught) {
      setError(caught as ApiClientError);
    } finally {
      deleteLock.current = false;
      setDeleting(false);
    }
  }

  if (!remoteEnabled) {
    return <section className="page library-page settings-page"><SettingsHeader count="—" /><AppearanceSettings /><EmptyState title="远程设置尚未启用" detail="请从 V3 桌面入口启动本地服务，再添加本机或云端 ComfyUI 连接。" /></section>;
  }

  return <section className="page library-page settings-page">
    <SettingsHeader count={settings?.items.length ?? "—"} />
    <AppearanceSettings />
    {error && <ErrorState message={error.message} requestId={error.requestId} />}
    {!settings ? <LoadingState label="正在读取生成环境配置…" /> : <>
    <div className="settings-ranking"><h2>画师推荐</h2><p>在工作台展开“画师推荐”，可随时切换排序并选择画师。</p><a href="/workbench">打开工作台</a></div>
    <div className="temporary-import-entry"><div><strong>临时云端 ComfyUI</strong><p>云端地址或密钥变化后，可导入并更新同一连接。</p></div><button type="button" className="button button--secondary" disabled={deleting || saving || probing || testing || comfyOpening || importOpen} onClick={() => {setNotice(""); setError(null); setDeleteConfirmId(null); setImportOpen(true);}}>导入临时连接</button></div>
    {importOpen && <TemporaryConnectionImport target={selected?.connection_type === "http" ? selected : null} onCancel={() => setImportOpen(false)} onImported={saved => {
      notifyLoraEnvironmentChanged(saved.id);
      setSettings(current => current ? {...current, items: current.items.some(item => item.id === saved.id) ? current.items.map(item => item.id === saved.id ? saved : item) : [...current.items, saved]} : current);
      setSelectedId(saved.id);
      setForm(formFromProfile(saved));
      setFingerprint("");
      setPrivateKeyPassphrase("");
      setComfyAccess(null);
      setDeleteConfirmId(null);
      setImportOpen(false);
      setNotice("临时连接已保存，请测试连接并重新检测工作流资源。保存成功不代表云端已连通。");
    }} />}
    <div className="settings-layout">
      <aside className="settings-side">
        <div className="settings-side-head"><span>生成环境</span><button type="button" className="button button--secondary" onClick={startNew} disabled={deleting || importOpen}>＋ 新建</button></div>
        <div className="remote-profile-list">
          {settings.items.map((profile) => <button type="button" key={profile.id} className={`remote-profile-item${profile.id === selectedId ? " is-selected" : ""}`} onClick={() => selectProfile(profile)} disabled={deleting || importOpen}>
            <span className={profile.enabled && (profile.connection_ready ?? profile.host_fingerprint_confirmed) ? "status-dot is-ready" : "status-dot"} /><span><strong>{profile.display_name}</strong><small>{profile.connection_type === "http" ? `临时 HTTPS · ${profile.http_base_url}` : profile.connection_type === "local" ? `本机 · ${profile.comfy_endpoint}` : `${profile.ssh_user}@${profile.ssh_host}:${profile.ssh_port} · ${profile.host_fingerprint_confirmed ? "指纹已确认" : "待确认指纹"}`}</small></span>
          </button>)}
          {!settings.items.length && <p>尚未配置执行环境。</p>}
        </div>
        <div className="settings-workflows"><strong>本地工作流模板</strong><p>模板导入、模型关联和版本管理已集中到独立页面。</p><a href="/workflows">打开工作流模板库</a></div>
      </aside>
      <form className="settings-form" onSubmit={(event) => void save(event)}>
        <div className="settings-form-head"><div><span className="eyebrow">COMFYUI</span><h2>{selected ? "编辑连接" : "新增连接"}</h2><p>{isHttp ? "临时 HTTPS 连接；此处可修改名称与启用状态。地址和密钥请通过导入更新。" : "选择本机直连或云端 SSH；保存后在工作流页面检测并映射资源。"}</p></div><button className="button button--primary" type="submit" disabled={saving || deleting || importOpen}>{saving ? "保存中…" : "保存连接"}</button></div>
        {endpointDirty && <p role="status">连接信息已修改，请先保存再测试或打开网页。</p>}
        {notice && <div className="workspace-notice" role="status" style={{whiteSpace: "pre-wrap"}}>{notice}</div>}
        <fieldset disabled={deleting || importOpen}>
          <legend>连接信息</legend>
          {isHttp ? <p>连接类型：临时 HTTPS</p> : <label>连接类型<select value={form.connection_type} onChange={e => {setForm({...form, connection_type: e.target.value as "ssh" | "local", password: ""}); setPrivateKeyPassphrase(""); setFingerprint("");}}><option value="ssh">云端 SSH</option><option value="local">本地 ComfyUI</option></select></label>}
          <label>显示名称<input required value={form.display_name} onChange={(event) => setForm({...form, display_name: event.target.value})} /></label>
          {isHttp && <div className="temporary-connection-details"><p>API 地址：<code>{selected?.http_base_url}</code></p><p>{selected?.has_saved_api_key ? "访问密钥已安全保存。" : "公开 API，未保存访问密钥。"}</p><p>{selected?.http_runtime_id ? `云端运行时标识：${selected.http_runtime_id}` : "未提供云端运行时标识；同一地址可能已切换运行环境，请更新连接并重新检测资源。"}</p></div>}
          {isSsh && <><label>SSH 地址<input required placeholder="117.50.80.146" value={form.ssh_host} onChange={(event) => setForm({...form, ssh_host: event.target.value})} /></label>
          <label>端口<input required type="number" min="1" max="65535" value={form.ssh_port} onChange={(event) => setForm({...form, ssh_port: Number(event.target.value)})} /></label>
          <label>用户名<input required value={form.ssh_user} onChange={(event) => setForm({...form, ssh_user: event.target.value})} /></label></>}
          {form.connection_type === "local" && <><label>ComfyUI 本机地址<select value={form.comfy_host} onChange={e => setForm({...form, comfy_host: e.target.value})}><option>127.0.0.1</option><option>localhost</option><option>::1</option></select></label><label>ComfyUI 端口<input type="number" required min="1" max="65535" value={form.comfy_port} onChange={e => setForm({...form, comfy_port: Number(e.target.value)})} /></label><p>先启动本机 ComfyUI，再测试连接。</p></>}
        </fieldset>
        {isSsh && <fieldset disabled={deleting || importOpen}>
          <legend>认证方式</legend>
          <label>方式<select value={form.auth_type} onChange={(event) => setForm({...form, auth_type: event.target.value as AuthType})}><option value="password">密码</option><option value="private_key">私钥文件</option><option value="agent">SSH Agent</option></select></label>
          {form.auth_type === "password" && <label>SSH 密码<input type="password" placeholder={selected?.has_saved_password ? "留空：保留已保存密码" : "输入后保存到 Windows 凭据管理器"} value={form.password} onChange={(event) => setForm({...form, password: event.target.value})} autoComplete="new-password" /></label>}
          {form.auth_type === "private_key" && <label>私钥路径<input required placeholder="C:\\Users\\you\\.ssh\\id_ed25519" value={form.private_key_path} onChange={(event) => setForm({...form, private_key_path: event.target.value})} /></label>}
          {form.auth_type === "private_key" && <label>私钥口令（可选，仅本次测试）<input type="password" autoComplete="current-password" value={privateKeyPassphrase} onChange={(event) => setPrivateKeyPassphrase(event.target.value)} /></label>}
          {form.auth_type === "password" && <label className="check-label"><input type="checkbox" checked={form.remember_password} onChange={(event) => setForm({...form, remember_password: event.target.checked})} /> 安全保存密码到 Windows 凭据管理器</label>}
        </fieldset>}
        <label className="check-label"><input type="checkbox" checked={form.enabled} disabled={deleting || importOpen} onChange={(event) => setForm({...form, enabled: event.target.checked})} /> 在生成列表中启用此连接</label>
        {isHttp && selected?.connection_type === "http" && <div className="settings-security"><button type="button" className="button button--primary" onClick={() => void testConnection()} disabled={saving || testing || deleting || importOpen || comfyOpening}>{testing ? "正在测试 ComfyUI…" : "测试临时连接"}</button></div>}
        {form.connection_type === "local" && selected?.connection_type === "local" && <div className="settings-security"><button type="button" className="button button--primary" onClick={() => void testConnection()} disabled={endpointDirty || saving || testing || deleting || importOpen}>{testing ? "正在测试 ComfyUI…" : "测试本地连接"}</button></div>}
        {isSsh && <div className="settings-security"><strong>SSH 指纹与连接测试</strong><p>{selected?.host_fingerprint_confirmed ? "主机指纹已确认。更改地址、端口、用户名、认证方式或私钥后会自动要求重新确认。完整测试会继续验证 SSH 登录、隧道和 ComfyUI API。" : "新建连接尚未确认主机指纹。检测不会自动信任主机；请核对显示的指纹后确认保存。"}</p>{selected && <div className="host-key-actions"><button type="button" className="button button--secondary" onClick={() => void probeHostKey()} disabled={probing || testing || saving || comfyOpening || deleting || importOpen}>{probing ? "检测中…" : "检测 SSH 指纹"}</button>{fingerprint && <><code>{fingerprint}</code><button type="button" className="button button--secondary" onClick={() => void confirmHostKey()} disabled={probing || testing || saving || comfyOpening || deleting || importOpen}>确认并保存指纹</button></>}<button type="button" className="button button--primary" onClick={() => void testConnection()} disabled={endpointDirty || saving || !selected.host_fingerprint_confirmed || probing || testing || comfyOpening || deleting || importOpen}>{testing ? "正在测试 SSH 与 ComfyUI…" : "测试完整连接"}</button></div>}</div>}
        <div className="settings-security">
          <strong>ComfyUI 网页维护入口</strong>
          <p>{isHttp ? comfyUrl ? "浏览器需要在网关登录页手动输入访问密钥，API 中保存的 Bearer 密钥不会自动传给网页。" : "未识别此网关的网页登录入口。API 可测试；网页入口可从云端打开。" : form.connection_type === "local" ? "直接打开已启动的本机 ComfyUI 网页。" : "项目运行期间通过本机 SSH 隧道访问云端 ComfyUI。"}</p>
          <div className="host-key-actions">
            {comfyUrl && <a href={comfyUrl} target="_blank" rel="noreferrer"><code>{comfyUrl}</code></a>}
            <button type="button" className="button button--primary" onClick={() => void openComfy()} disabled={!comfyUrl || endpointDirty || saving || !(selected?.connection_ready ?? selected?.host_fingerprint_confirmed) || comfyOpening || testing || probing || deleting || importOpen}>{comfyOpening ? "正在连接 ComfyUI…" : "打开 ComfyUI 网页"}</button>
          </div>
          <small>{comfyAccess?.remote_profile_id === selectedId ? comfyAccess.message : "保存连接后，可在这里打开 ComfyUI 网页。"}</small>
        </div>
        {selected && <div className="settings-security">
          <strong>删除已保存连接</strong>
          <p>删除只会移除本机保存的连接配置和{isHttp ? "访问密钥" : "密码"}。</p>
          <button type="button" className="button button--danger" onClick={() => setDeleteConfirmId(selected.id)} disabled={saving || probing || testing || comfyOpening || deleting || importOpen}>删除此连接</button>
          {deleteTarget?.id === selected.id && <div className="settings-delete-confirm" role="group" aria-label={`删除连接 ${deleteTarget.display_name}`}>
            <strong>确定删除已保存的连接“{deleteTarget.display_name}”吗？</strong>
            <p>本地连接配置和已保存{isHttp ? "访问密钥" : "密码"}将被移除；生成记录、图片和远端主机内容都会保留。</p>
            <div className="settings-delete-actions">
              <button type="button" className="button button--secondary" onClick={() => setDeleteConfirmId(null)} disabled={deleting}>取消删除</button>
              <button type="button" className="button button--danger is-danger" onClick={() => void deleteProfile()} disabled={deleting || saving || probing || testing || comfyOpening}>{deleting ? "正在删除…" : "确认删除连接"}</button>
            </div>
          </div>}
        </div>}
      </form>
      {selectedId && <div className="settings-security"><strong>工作流资源映射</strong><p>保存连接配置后，在工作流页面检测当前环境并确认模型文件。</p><a href={`/workflows?environment=${encodeURIComponent(selectedId)}`}>管理此环境的工作流资源</a></div>}
    </div>
    </>}
  </section>;
}

function SettingsHeader({count}: {count: number | string}) {
  return <header className="page-header"><div><h1>设置</h1><p>调整界面外观，管理生成环境与连接。模板和文件映射位于工作流页面。</p></div><div className="header-stat"><strong>{count}</strong><span>个连接</span></div></header>;
}

function AppearanceSettings() {
  return <section className="settings-appearance" aria-label="界面外观设置"><header><h2>界面外观</h2><p>统一工作台支持浅色、夜间与跟随系统，主题切换会保留当前编辑。</p></header><AppearanceControls /></section>;
}
