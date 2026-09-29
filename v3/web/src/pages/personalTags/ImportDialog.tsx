import {useEffect, useRef, useState} from "react";
import {useBodyScrollLock} from "../../lib/useBodyScrollLock";
import {personalTagsApi, type ImportOptions, type ImportPreview} from "../../lib/personalTags";

export function ImportDialog({onClose, onImported}: {onClose: () => void; onImported: () => void}) {
  const container = useRef<HTMLDivElement>(null);
  const previousFocus = useRef<HTMLElement | null>(document.activeElement as HTMLElement | null);
  const request = useRef(0);
  const readSequence = useRef(0);
  const [documentValue, setDocumentValue] = useState<Record<string, unknown> | null>(null);
  const [filename, setFilename] = useState("");
  const [options, setOptions] = useState<ImportOptions>({use_legacy_weights: false, fragment_ids: []});
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [pending, setPending] = useState(false); const [error, setError] = useState(""); const [result, setResult] = useState("");
  useBodyScrollLock();
  useEffect(() => {container.current?.querySelector<HTMLButtonElement>("button")?.focus(); return () => {readSequence.current++; request.current++; previousFocus.current?.focus();};}, []);
  useEffect(() => {
    if (!documentValue) return;
    const current = ++request.current; setPreview(null); setPending(true); setError("");
    void personalTagsApi.previewImport(documentValue, options).then(value => {if (current === request.current) setPreview(value);})
      .catch(cause => {if (current === request.current) setError(cause instanceof Error ? cause.message : String(cause));})
      .finally(() => {if (current === request.current) setPending(false);});
    return () => {request.current++;};
  }, [documentValue, options]);
  const read = async (file?: File) => {
    const current = ++readSequence.current;
    request.current++;
    setDocumentValue(null); setPreview(null); setPending(Boolean(file)); setError(""); setResult("");
    setFilename(file?.name ?? "");
    setOptions(previous => ({...previous, fragment_ids: []}));
    if (!file) return;
    try {
      const value: unknown = JSON.parse(await file.text());
      if (current !== readSequence.current) return;
      if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("JSON 顶层应为对象");
      setDocumentValue(value as Record<string, unknown>);
    } catch (cause) {
      if (current === readSequence.current) setError(`无法读取 JSON：${cause instanceof Error ? cause.message : String(cause)}`);
    } finally {if (current === readSequence.current) setPending(false);}
  };
  const commit = async () => {
    if (!documentValue || !preview) return; setPending(true); setError("");
    try {const saved = await personalTagsApi.commitImport(documentValue, options, preview.digest, preview.library_revision); setResult(`导入完成：新增 ${saved.counts.new}，已存在 ${saved.counts.existing}`); onImported();}
    catch (cause) {setError(cause instanceof Error ? cause.message : String(cause));} finally {setPending(false);}
  };
  const fragmentCandidates = preview?.issues.filter(issue => issue.code.includes("fragment") && issue.source_id) ?? [];
  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {event.preventDefault(); onClose();}
    if (event.key !== "Tab") return;
    const focusable = [...(container.current?.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled)") ?? [])];
    if (!focusable.length) return;
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {event.preventDefault(); last.focus();}
    else if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first.focus();}
  };
  return <div className="personal-tags-scrim"><div className="personal-tags-dialog" role="dialog" aria-modal="true" aria-labelledby="personal-tags-import-title" ref={container} onKeyDown={onKeyDown}>
    <header><h2 id="personal-tags-import-title">导入个人标签 JSON</h2><button type="button" aria-label="关闭导入对话框" onClick={onClose}>×</button></header>
    <label>选择本地 JSON 文件<input type="file" accept="application/json,.json" onChange={event => void read(event.target.files?.[0])} /></label>
    {filename && <p>文件：{filename}</p>}
    <label><input type="checkbox" checked={Boolean(options.use_legacy_weights)} onChange={event => setOptions(current => ({...current, use_legacy_weights: event.target.checked}))} />将有效旧权重用作个人默认权重</label>
    {pending && <p role="status">正在生成预览…</p>}
    {preview && <section aria-label="导入预览"><h3>导入预览</h3><dl>{Object.entries(preview.counts).map(([key, count]) => <div key={key}><dt>{({new: "新增", existing: "已导入", invalid: "无效", similar: "相近变体", unmapped: "待分类", fragment_candidates: "片段候选", legacy_weights: "旧权重"} as Record<string, string>)[key] ?? key}</dt><dd>{count}</dd></div>)}</dl>
      {fragmentCandidates.length > 0 && <fieldset><legend>确认片段候选类型</legend>{fragmentCandidates.map(issue => <label key={issue.source_id}><input type="checkbox" checked={options.fragment_ids?.includes(issue.source_id) ?? false} onChange={event => setOptions(current => ({...current, fragment_ids: event.target.checked ? [...(current.fragment_ids ?? []), issue.source_id] : (current.fragment_ids ?? []).filter(id => id !== issue.source_id)}))} />{issue.source_id}：{issue.message}</label>)}</fieldset>}
      <details><summary>问题明细 ({preview.issues.length})</summary><ul>{preview.issues.map((issue, index) => <li key={`${issue.code}-${issue.source_id}-${index}`}>{issue.blocking ? "阻断" : "提示"} · {issue.entity} {issue.source_id} · {issue.message}</li>)}</ul></details>
    </section>}
    {error && <p role="alert">{error}</p>}{result && <p role="status">{result}</p>}
    <div className="personal-tags-dialog-actions"><button type="button" className="button button--primary" disabled={!preview || pending || preview.issues.some(issue => issue.blocking)} onClick={() => void commit()}>确认导入</button><button type="button" onClick={onClose}>关闭</button></div>
  </div></div>;
}
