import {useEffect, useRef, useState} from "react";
import {apiRequest} from "../lib/api";
import type {RemoteProfile} from "../pages/SettingsPage";

const MAX_CONNECTION_BYTES = 65536;

function readFile(file: File): Promise<string> {
  if (typeof file.text === "function") return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("file_read_failed"));
    reader.readAsText(file);
  });
}

export function TemporaryConnectionImport({target, onImported, onCancel}: {
  target: Pick<RemoteProfile, "id" | "display_name"> | null;
  onImported: (profile: RemoteProfile) => void;
  onCancel: () => void;
}) {
  const [mode, setMode] = useState<"new" | "update">("new");
  const [name, setName] = useState("我的临时 ComfyUI");
  const [error, setError] = useState("");
  const [reading, setReading] = useState(false);
  const [saving, setSaving] = useState(false);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const keyRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const generation = useRef(0);
  const active = useRef(true);
  const saveLock = useRef(false);

  function clearSecrets() {
    generation.current++;
    if (textRef.current) textRef.current.value = "";
    if (keyRef.current) keyRef.current.value = "";
    if (fileRef.current) fileRef.current.value = "";
  }

  useEffect(() => {
    active.current = true;
    // Capture the elements: React can detach refs before passive cleanup.
    const text = textRef.current;
    const key = keyRef.current;
    const file = fileRef.current;
    return () => {
      active.current = false;
      generation.current++;
      if (text) text.value = "";
      if (key) key.value = "";
      if (file) file.value = "";
    };
  }, []);

  async function chooseFile(file?: File) {
    const version = ++generation.current;
    setReading(false);
    setError("");
    if (!file) return;
    if (file.size > MAX_CONNECTION_BYTES) {
      setError("JSON 文件不能超过 64 KiB，请重新选择。");
      if (fileRef.current) fileRef.current.value = "";
      return;
    }
    setReading(true);
    try {
      const text = await readFile(file);
      if (!active.current || generation.current !== version) return;
      if (textRef.current) textRef.current.value = text;
    } catch {
      if (active.current && generation.current === version) setError("无法读取 JSON 文件，请重选或粘贴连接信息。");
    } finally {
      if (active.current && generation.current === version) setReading(false);
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (saveLock.current || reading) return;
    const text = textRef.current?.value || "";
    const key = keyRef.current?.value || "";
    if (!text.trim() || !name.trim()) {
      setError("请填写连接信息与连接名称。");
      return;
    }
    saveLock.current = true;
    setSaving(true);
    setError("");
    try {
      let embeddedKey = false;
      try {
        const document: unknown = JSON.parse(text);
        embeddedKey = typeof document === "object" && document !== null && "api_key" in document
          && typeof document.api_key === "string" && document.api_key.length > 0;
      } catch { /* The import service validates URLs and malformed JSON. */ }
      const saved = await apiRequest<RemoteProfile>("/api/v3/settings/temporary-connections/import", {
        method: "POST",
        body: JSON.stringify({connection_text: text, ...(key || !embeddedKey ? {api_key: key} : {}), display_name: name.trim(),
          ...(mode === "update" && target ? {target_profile_id: target.id} : {})}),
      });
      if (!active.current) return;
      clearSecrets();
      onImported(saved);
    } catch {
      // Never render server echoes of the submitted JSON or key.
      if (active.current) setError("导入失败，请检查 HTTPS API 地址、JSON 格式和认证方式，并确认本地服务及凭据管理器可用后重试。");
    } finally {
      saveLock.current = false;
      if (active.current) setSaving(false);
    }
  }

  return <section className="temporary-connection-import" aria-label="导入临时连接">
    <header><h2>导入临时连接</h2><p>粘贴 Colab 最后一格的 HTTPS API 地址及密钥，或导入 moss_connection.json。不要填写 Colab 笔记本网址。</p></header>
    <form onSubmit={event => void submit(event)}>
      <fieldset disabled={saving}>
        <legend>导入方式</legend>
        <div className="temporary-import-modes">
          <label className="check-label"><input type="radio" name="temporary-import-mode" checked={mode === "new"} onChange={() => {setMode("new"); setName("我的临时 ComfyUI");}} />新建连接</label>
          <label className="check-label"><input type="radio" name="temporary-import-mode" disabled={!target} checked={mode === "update"} onChange={() => {setMode("update"); setName(target?.display_name || "");}} />更新当前临时连接</label>
        </div>
        {mode === "update" && <p>更新“{target?.display_name}”，保留连接 ID、模型映射及工作流偏好；更新后需重新检测资源。</p>}
        <label>连接名称<input value={name} required onChange={event => setName(event.target.value)} /></label>
        <label>连接信息<textarea ref={textRef} required rows={5} placeholder="https://… 或连接 JSON 内容" spellCheck={false} autoComplete="off" onChange={() => {generation.current++; setReading(false);}} /></label>
        <label>选择 JSON 文件<input ref={fileRef} type="file" accept=".json,application/json" onChange={event => void chooseFile(event.target.files?.[0])} /></label>
        <small>JSON 文件最大 64 KiB，仅读取文本，不执行内容。</small>
        <label>访问密钥<input ref={keyRef} type="password" autoComplete="new-password" /></label>
        <small>只填写原始密钥，不要添加 Bearer 前缀。公开 API 可留空；JSON 内已有密钥时可留空。</small>
        {mode === "update" && <small>更新使用完整替换：如需认证，请重新填写密钥或提供含密钥的 JSON；留空不会保留旧密钥。</small>}
      </fieldset>
      {error && <p role="alert" className="temporary-import-error">{error}</p>}
      {reading && <p role="status">正在读取连接文件…</p>}
      <div className="temporary-import-actions">
        <button className="button button--primary" type="submit" disabled={saving || reading}>{saving ? "正在保存…" : "导入并保存"}</button>
        <button className="button button--secondary" type="button" disabled={saving} onClick={() => {clearSecrets(); onCancel();}}>取消导入</button>
      </div>
    </form>
  </section>;
}
