import {useState} from "react";
import type {PromptLock} from "../lib/conversation";

export function PromptLocks({positive, negative, locks, onChange}: {
  positive: string; negative: string; locks: PromptLock[]; onChange: (locks: PromptLock[]) => void;
}) {
  const [target, setTarget] = useState<PromptLock["target"]>("positive");
  const [text, setText] = useState("");
  const fragment = text.trim();
  const exists = (target === "positive" ? positive : negative).includes(fragment);
  const duplicate = locks.some(item => item.target === target && item.text === fragment);
  return <details className="conversation-prompt-locks">
    <summary>固定提示词片段 · {locks.length} / 32</summary>
    <p className="conversation-muted">固定人物特征、服装或动作中的一小段英文，其余文字仍可修改。整理和保存时会检查原文是否保留；这不保证生成图片的语义和外观完全不变。</p>
    {locks.length > 0 && <ul>{locks.map(item => <li key={`${item.target}:${item.text}`}>
      <span>{item.target === "positive" ? "正向" : "负向"}：<code>{item.text}</code></span>
      <button type="button" aria-label={`解除固定：${item.text}`} onClick={() => onChange(locks.filter(lock => lock !== item))}>解除固定</button>
      {!(item.target === "positive" ? positive : negative).includes(item.text) && <p role="alert">当前文字已缺少这段原文。请撤销修改或解除固定后再保存。</p>}
    </li>)}</ul>}
    <label>片段所在提示词<select value={target} onChange={event => setTarget(event.target.value as PromptLock["target"])}>
      <option value="positive">正向提示词</option><option value="negative">负向提示词</option>
    </select></label>
    <label>要固定的原文片段<input maxLength={1000} value={text} onChange={event => setText(event.target.value)} placeholder="从当前提示词复制，例如 short black hair" /></label>
    {fragment && !exists && <p role="status">请填写所选提示词中已经存在的原文片段。</p>}
    <button type="button" disabled={!fragment || !exists || duplicate || locks.length >= 32}
      onClick={() => {onChange([...locks, {target, text: fragment}]); setText("");}}>固定片段</button>
    <p className="conversation-muted">点击保存当前版本即可保存固定规则，无需再次调用模型。</p>
  </details>;
}
