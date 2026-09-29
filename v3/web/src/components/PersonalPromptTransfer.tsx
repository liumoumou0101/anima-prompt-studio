import {appendPersonalPromptText, type PersonalPromptText, type PersonalPromptReceipt} from "../lib/personalPromptTransfer";
import {codePointLength} from "../lib/textLength";

export function PersonalPromptTransfer({addition, before, receipt, blockedReason, needsRefresh, undoChanged, busy, onConfirm, onCancel, onRefresh, onUndo}: {
  addition: PersonalPromptText | null; before: PersonalPromptText | null; receipt: PersonalPromptReceipt | null;
  blockedReason: string; needsRefresh: boolean; undoChanged: boolean; busy: boolean;
  onConfirm: () => void; onCancel: () => void; onRefresh: () => void; onUndo: () => void;
}) {
  const after = before && addition ? appendPersonalPromptText(before, addition) : null;
  const validation = after && !after.positive.trim() ? "请先在工作台填写正向提示词，再追加这段负向内容"
    : after && (codePointLength(after.positive) > 20000 || codePointLength(after.negative) > 20000) ? "追加后提示词超过 20,000 字符，请缩短正文后重新预览。" : "";
  return <section aria-label="追加个人提示词" className="conversation-conflict">
    <h2>追加个人提示词</h2>
    {receipt ? <>
      <p role="status">{receipt.state === "undone" ? "本次追加已撤销。" : "个人提示词原文已追加，源组合仍保留在个人库。"}</p>
      {receipt.state === "applied" && <>
        {undoChanged && <p>追加后已继续编辑，请在提示词中手动移除</p>}
        <button disabled={busy || Boolean(blockedReason) || undoChanged} onClick={onUndo}>撤销本次追加</button>
      </>}
    </> : <>
      <p>确认后将原文追加到当前提示词。源组合仍保留在个人库。</p>
      {after && before && <div className="conversation-diff">
        {(["positive", "negative"] as const).map(side => <div key={side}>
          <label>追加前{side === "positive" ? "正向" : "负向"}提示词<textarea readOnly rows={3} value={before[side]} /></label>
          <label>追加后{side === "positive" ? "正向" : "负向"}提示词<textarea readOnly rows={3} value={after[side]} /></label>
        </div>)}
      </div>}
      {validation && <p>{validation}</p>}
      {needsRefresh && before && <p>工作台内容已变化，请保存并重新预览后确认。</p>}
      {(!before || needsRefresh) && <button disabled={busy || Boolean(blockedReason)} onClick={onRefresh}>保存并重新预览</button>}
      <button disabled={busy || Boolean(blockedReason || validation) || !after || needsRefresh} onClick={onConfirm}>确认追加原文</button>
    </>}
    {blockedReason && <p>{blockedReason}</p>}
    <button disabled={busy} onClick={onCancel}>{receipt ? "关闭追加回执" : "取消追加"}</button>
  </section>;
}
