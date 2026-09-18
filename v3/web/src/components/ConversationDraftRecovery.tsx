import {useState} from "react";
import {cleanupConversationDrafts, getConversationTabId, listConversationDraftCandidates,
  readConversationDraftCandidate, type ConversationDraftCandidate} from "../lib/conversationDrafts";
import type {LocalConversation} from "../lib/conversation";
import {modelProfileChoices} from "../lib/modelProfiles";

function requirementsPreview(local: LocalConversation): [string, string][] {
  const {subject, style, lighting, composition, exclusions} = local.requirements.layers;
  const joined = (items: (string | undefined)[]) => items.filter(Boolean).join("；") || "（空）";
  return [
    ["主体" + (subject.locked ? " · 已锁定" : ""), joined([subject.text, ...(subject.character_tags || []), ...(subject.series_tags || []), ...(subject.general_tags || [])])],
    ["风格" + (style.locked ? " · 已锁定" : ""), joined([style.text, style.medium, ...style.artists, ...(style.manual_artist_tags || [])])],
    ["光影" + (lighting.locked ? " · 已锁定" : ""), joined([lighting.text, lighting.mood?.value])],
    ["构图" + (composition.locked ? " · 已锁定" : ""), joined([composition.text, composition.shot, ...Object.values(composition.design || {}).map(choice => choice?.value)])],
    ["排除内容" + (exclusions.locked ? " · 已锁定" : ""), joined([...exclusions.global, ...exclusions.scoped.map(item => `${item.target}：${item.concept}`)])],
    ["固定提示词片段", joined((local.requirements.prompt_locks || []).map(item => `${item.target === "positive" ? "正向" : "负向"}：${item.text}`))],
    ["LoRA", joined(local.requirements.loras.map(item => `${item.file_name || item.logical_id}（权重 ${item.weight}）`))],
  ];
}

function candidateLabel(candidate: ConversationDraftCandidate): string {
  const source = candidate.status === "invalid" ? "待核对的原始内容" : candidate.kind === "legacy" ? "旧版草稿"
    : candidate.kind === "snapshot" ? "恢复前备份" : candidate.tabId === getConversationTabId() ? "本窗口" : "其他窗口";
  const date = candidate.savedAt === null ? "时间未知" : new Date(candidate.savedAt).toLocaleString();
  const preview = candidate.local?.positive || candidate.local?.delta || candidate.local?.requirements.layers.subject.text || "";
  return `${source} · ${date}${candidate.local ? ` · 版本 ${candidate.local.baseRevision}` : ""}${preview ? ` · ${preview.replace(/\s+/g, " ").slice(0, 65)}` : ""}`;
}

export function ConversationDraftRecovery({workspaceId, disabled, onRestore}: {
  workspaceId: string; disabled: boolean; onRestore: (candidate: ConversationDraftCandidate) => boolean;
}) {
  const [open, setOpen] = useState(false);
  const [candidates, setCandidates] = useState<ConversationDraftCandidate[]>([]);
  const [selected, setSelected] = useState<ConversationDraftCandidate | null>(null);
  const [warning, setWarning] = useState("");
  const [notice, setNotice] = useState("");

  function refresh() {
    const result = listConversationDraftCandidates(workspaceId);
    setCandidates(result.candidates); setWarning(result.warning); setSelected(null);
  }
  function select(key: string) {
    setNotice("");
    const candidate = key ? readConversationDraftCandidate(workspaceId, key) : null;
    setSelected(candidate);
    if (key && !candidate) setWarning("这份草稿已变化或无法读取，请刷新列表后重新选择。");
  }
  function currentSelection(): ConversationDraftCandidate | null {
    if (!selected) return null;
    const latest = readConversationDraftCandidate(workspaceId, selected.key);
    if (!latest || latest.raw !== selected.raw) {
      setSelected(latest); setWarning("这份草稿在其他窗口发生了变化，请检查最新内容后再次操作。");
      return null;
    }
    return latest;
  }
  function exportSelected() {
    const candidate = currentSelection();
    if (!candidate) return;
    try {
      const url = URL.createObjectURL(new Blob([candidate.raw], {type: "application/json"}));
      const link = document.createElement("a"); link.href = url;
      link.download = `anima-draft-${workspaceId}-${candidate.savedAt ?? "undated"}.json`;
      link.click(); URL.revokeObjectURL(url);
    } catch {setWarning("导出失败，请复制下方的草稿内容另行保存。");}
  }
  return <div className="conversation-draft-recovery">
    <button aria-expanded={open} aria-controls="conversation-draft-recovery" onClick={() => {
      if (!open) {refresh(); setNotice("");}
      setOpen(value => !value);
    }}>找回本地草稿</button>
    {open && <section id="conversation-draft-recovery" aria-label="本地草稿恢复">
      <p>这里保留本浏览器中这份会话的草稿。先预览再恢复；恢复前会备份当前编辑，恢复后需另行保存到服务端。</p>
      <div className="conversation-actions">
        <button onClick={() => {refresh(); setNotice("");}}>刷新草稿列表</button>
        <button disabled={disabled} onClick={() => {
          const result = cleanupConversationDrafts(workspaceId); refresh();
          setWarning(result.warning); setNotice(result.removed ? `已整理 ${result.removed} 项重复备份。` : "没有可安全整理的重复备份。");
        }}>整理重复备份</button>
      </div>
      <p className="conversation-muted">自动整理仅移除确认重复的备份；其他窗口草稿、独有内容和待确认请求会保留。</p>
      {warning && <p role="alert">{warning}</p>}{notice && <p role="status">{notice}</p>}
      {candidates.length ? <label>选择本地草稿<select value={selected?.key || ""} onChange={event => select(event.target.value)}>
        <option value="">选择一份草稿查看内容</option>
        {candidates.map(candidate => <option key={candidate.key} value={candidate.key}>{candidateLabel(candidate)}</option>)}
      </select></label> : <p>没有找到可读取的本地草稿。</p>}
      {selected && <div className="conversation-draft-preview">
        {selected.local ? <>
          <p>基于服务端版本 {selected.local.baseRevision} · {modelProfileChoices().find(model => model.id === selected.local!.model)?.label || selected.local.model} · {selected.local.settings.width} × {selected.local.settings.height}</p>
          <h3>未发送的修改意见</h3><pre>{selected.local.delta || "（空）"}</pre>
          <h3>正向提示词</h3><pre>{selected.local.positive || "（空）"}</pre>
          <h3>负向提示词</h3><pre>{selected.local.negative || "（空）"}</pre>
          <details><summary>查看画面要求与生成设置</summary>
            {requirementsPreview(selected.local).map(([label, value]) => <div key={label}>
              <strong>{label}</strong><pre>{value}</pre>
            </div>)}
            <p>种子 {selected.local.settings.seed} · {selected.local.settings.steps} 步 · CFG {selected.local.settings.cfg} · {selected.local.settings.batch_size} 张</p>
            <p>采样器 {selected.local.settings.sampler} · 调度器 {selected.local.settings.scheduler}</p>
          </details>
          {!selected.base && <p>这份草稿缺少合并基准；如果服务端版本已更新，需要核对冲突或另存为新会话。</p>}
        </> : <><p>这份内容的格式无法自动恢复，可以先导出保留。</p><pre>{selected.raw}</pre></>}
        <div className="conversation-actions">
          <button disabled={disabled || selected.status !== "valid"} onClick={() => {
            const candidate = currentSelection();
            if (candidate?.local && onRestore(candidate)) setOpen(false);
          }}>恢复到编辑区</button>
          <button onClick={exportSelected}>导出这份草稿</button>
        </div>
        {disabled && <p>请先处理当前操作或待确认的修改，再恢复草稿。</p>}
      </div>}
    </section>}
  </div>;
}
