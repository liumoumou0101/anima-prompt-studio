import {useEffect, useRef, useState} from "react";
import {Navigate} from "react-router-dom";
import {apiRequest} from "../lib/api";

export function GalleryWorkspaceButton({path, hasPrompt, disabled}: {path: string; hasPrompt: boolean; disabled: boolean}) {
  const [workspace, setWorkspace] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const lock = useRef(false);
  const storageKey = `anima-gallery-workspace:${path}`;
  useEffect(() => {
    if (!workspace) return;
    // Only acknowledge while mounted and navigating. A late response after the
    // detail is closed must leave its request available for an idempotent retry.
    try {sessionStorage.removeItem(storageKey);} catch { /* Keeping the key is safe. */ }
  }, [workspace, storageKey]);
  async function open() {
    if (disabled || !hasPrompt || lock.current || workspace) return;
    lock.current = true; setBusy(true); setError("");
    try {
      // A retry after a lost response must reopen the same workspace.
      const requestKey = sessionStorage.getItem(storageKey) || crypto.randomUUID();
      sessionStorage.setItem(storageKey, requestKey);
      const record = await apiRequest<{id: string}>("/api/v3/gallery/assets/workspace", {
        method: "POST", body: JSON.stringify({path}), headers: {"Idempotency-Key": requestKey}});
      setWorkspace(record.id);
    } catch (caught) {setError((caught as Error).message);}
    finally {lock.current = false; setBusy(false);}
  }
  return <div className="gallery-workspace-action">
    <button type="button" className="is-primary" disabled={disabled || !hasPrompt || busy}
      title="带入原图与已记录的提示词，新建工作台会话" onClick={() => void open()}>{busy ? "正在转入…" : "转入工作台"}</button>
    {!hasPrompt && <p>此图片没有保存提示词，无法直接转入。可先存入参考案例库，再提取画面要求。</p>}
    {error && <p role="alert">{error}</p>}
    {workspace && <Navigate to={`/workbench?workspace=${encodeURIComponent(workspace)}`} />}
  </div>;
}
