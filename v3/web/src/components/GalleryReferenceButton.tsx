import {useRef, useState} from "react";
import {apiRequest} from "../lib/api";

export function GalleryReferenceButton({path, disabled}: {path: string; disabled: boolean}) {
  const [id, setId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const lock = useRef(false);
  async function save() {
    if (lock.current || id) return;
    lock.current = true; setBusy(true); setError("");
    try {
      const example = await apiRequest<{id: string}>("/api/v3/reference-examples/from-gallery", {method: "POST", body: JSON.stringify({path})});
      setId(example.id);
    } catch (caught) {setError((caught as Error).message);} finally {setBusy(false); lock.current = false;}
  }
  return <div className="gallery-reference-action">{id ? <a href={`/references?example=${id}`}>已存入案例库 · 打开案例</a>
    : <button disabled={disabled || busy} onClick={() => void save()}>{busy ? "正在保存案例…" : "存入参考案例库"}</button>}{error && <p role="alert">{error}</p>}</div>;
}
