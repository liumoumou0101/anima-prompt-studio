import {useRef, useState} from "react";
import {Navigate} from "react-router-dom";
import {apiRequest} from "../lib/api";
import {useOpenWorkspace} from "../lib/workbenchRoute";
import type {WorkspaceRecord} from "../lib/types";

export function GalleryWorkspaceButton({path, hasPrompt, disabled}: {path: string; hasPrompt: boolean; disabled: boolean}) {
  const {openWorkspace,destination} = useOpenWorkspace();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const lock = useRef(false);
  const storageKey = `anima-gallery-workspace:${path}`;
  async function open() {
    if (disabled || !hasPrompt || lock.current) return;
    lock.current = true; setBusy(true); setError("");
    try {
      // A retry after a lost response must reopen the same workspace.
      const requestKey = sessionStorage.getItem(storageKey) || crypto.randomUUID();
      sessionStorage.setItem(storageKey, requestKey);
      const record = await apiRequest<WorkspaceRecord>("/api/v3/gallery/assets/workspace", {
        method: "POST", body: JSON.stringify({path}), headers: {"Idempotency-Key": requestKey}});
      if (openWorkspace(record)) {
        try {sessionStorage.removeItem(storageKey);} catch { /* A retained key is safe to retry. */ }
      }
    } catch (caught) {setError((caught as Error).message);}
    finally {lock.current = false; setBusy(false);}
  }
  if (destination) return <Navigate to={destination}/>;
  return <div className="gallery-workspace-action">
    <button type="button" className="is-primary" disabled={disabled || !hasPrompt || busy}
      title="带入原图与已记录的提示词，新建工作台会话" onClick={() => void open()}>{busy ? "正在转入…" : "转入工作台"}</button>
    {!hasPrompt && <p>此图片没有保存提示词，无法直接转入。可先存入参考案例库，再提取画面要求。</p>}
    {error && <p role="alert">{error}</p>}
  </div>;
}
