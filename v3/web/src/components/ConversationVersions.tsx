import {useEffect, useRef, useState} from "react";
import type {ConversationRecord} from "../lib/conversation";
import {editableRequirements, layerLabels} from "../lib/conversation";
import {apiRequest} from "../lib/api";
import {PromptChanges, RequirementChanges} from "./ConversationReview";
type Version = Pick<ConversationRecord, "revision" | "title" | "draft" | "created_at">;
export function ConversationVersions({record, disabled, onRestore, onFork}: {record: ConversationRecord; disabled: boolean; onRestore: (revision: number) => void; onFork?: (revision: number) => void}) {
  const [open, setOpen] = useState(false), [items, setItems] = useState<Version[]>([]), [error, setError] = useState("");
  const [loading, setLoading] = useState(false), [more, setMore] = useState(false), [selected, setSelected] = useState<number | null>(null);
  const sequence = useRef(0);
  async function load(append = false) {
    const requestSequence = ++sequence.current;
    setLoading(true); setError("");
    try {
      const result = await apiRequest<{items: Version[]}>(`/api/v3/workspaces/${record.id}/versions?limit=20&offset=${append ? items.length : 0}`);
      if (requestSequence !== sequence.current) return;
      setItems(previous => append ? [...previous, ...result.items] : result.items); setMore(result.items.length === 20);
    } catch (caught) {if (requestSequence === sequence.current) setError((caught as Error).message);} finally {if (requestSequence === sequence.current) setLoading(false);}
  }
  useEffect(() => {if (open) void load(); return () => {sequence.current++;};}, [record.id, record.revision, open]);
  const version = items.find(item => item.revision === selected);
  return <details className="conversation-versions" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>版本历史 · 当前版本 {record.revision}</summary>
    <p className="conversation-muted">保存和采用修改后自动留存版本。恢复会创建新版本，之后的历史仍然保留。{onFork && "另开会话会从所选版本继续，保留父会话及原历史。"}升级前未保存的中间内容无法补回。</p>
    {disabled && <p>请先保存当前编辑或处理待确认的修改，再恢复或另开会话。</p>}
    {error && <p role="alert">{error}<button disabled={loading} onClick={() => void load()}>重新读取版本</button></p>}
    <ol className="conversation-version-list">{items.map(item => {
      const event = item.draft.conversation_events?.at(-1);
      return <li key={item.revision}><div><strong>版本 {item.revision}{item.revision === record.revision ? " · 当前" : ""}</strong><time>{new Date(item.created_at).toLocaleString()}</time>
        <p>{event?.after_revision === item.revision ? event.delta || "整理当前要求" : item.draft.compiled?.source === "user" ? "手工编辑 / 保存" : "保存的创作状态"}</p></div>
        <div className="conversation-actions"><button onClick={() => setSelected(selected === item.revision ? null : item.revision)}>查看版本 {item.revision}</button>
          <button disabled={disabled || loading || item.revision === record.revision} onClick={() => onRestore(item.revision)}>恢复版本 {item.revision}</button>
          {onFork && <button disabled={disabled || loading} onClick={() => onFork(item.revision)}>从版本 {item.revision} 另开会话</button>}</div></li>;
    })}</ol>
    {loading && <p role="status">读取版本…</p>}{more && <button disabled={loading} onClick={() => void load(true)}>加载更早版本</button>}
    {version && <section className="conversation-version-detail" aria-label={`版本 ${version.revision} 与当前版本的差异`}>
      <h3>版本 {version.revision} → 当前版本 {record.revision}</h3>
      <RequirementChanges before={editableRequirements(version as ConversationRecord)} after={record.draft.requirements} />
      <PromptChanges before={{positive: version.draft.compiled?.positive || "", negative: version.draft.compiled?.negative || ""}} after={{positive: record.draft.compiled?.positive || "", negative: record.draft.compiled?.negative || ""}} />
    </section>}
    <details><summary>旧修改摘要 · {record.draft.conversation_events.length}</summary><p className="conversation-muted">摘要只说明当时的意见；请使用上方版本历史恢复完整内容。</p>
      {record.draft.conversation_events.map(event => <article key={event.id}><time>{new Date(event.created_at).toLocaleString()}</time><p>{event.delta || "整理当前要求"}</p>
        <p>{event.changed_layers.length ? `修改范围：${event.changed_layers.map(name => layerLabels[name]).join("、")}` : "提示词整理（旧记录未保存具体差异）"}</p>
        {event.warnings.map((warning, i) => <p key={i}>{warning}</p>)}</article>)}
    </details>
  </details>;
}
