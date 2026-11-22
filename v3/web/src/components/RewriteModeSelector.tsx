import {useId} from "react";
import type {Mode} from "../lib/conversation";
import "./rewriteModeSelector.css";

const options: {value: Mode; title: string; description: string}[] = [
  {value: "faithful", title: "忠实还原", description: "保留原意，整理表达"},
  {value: "expand", title: "适度扩写", description: "保留要求，补充画面细节"},
];

export function RewriteModeSelector({value, onChange, disabled = false, initial = false}: {
  value: Mode; onChange: (mode: Mode) => void; disabled?: boolean; initial?: boolean;
}) {
  const id = useId();
  return <div className="rewrite-mode" role="radiogroup" aria-labelledby={`${id}-label`} aria-describedby={`${id}-hint`}>
    <div className="rewrite-mode__heading">
      <strong id={`${id}-label`}>改写方式</strong>
      <span id={`${id}-hint`}>{initial ? "用于首次整理想法" : "点击“更新提示词”时生效"}</span>
    </div>
    <div className="rewrite-mode__options">
      {options.map(option => <label key={option.value} className="rewrite-mode__choice">
        <input type="radio" name={`${id}-mode`} value={option.value} checked={value === option.value}
          disabled={disabled} onChange={() => onChange(option.value)}
          aria-labelledby={`${id}-${option.value}-title`} aria-describedby={`${id}-${option.value}-description`} />
        <span className="rewrite-mode__copy">
          <strong id={`${id}-${option.value}-title`}>{option.title}</strong>
          <span id={`${id}-${option.value}-description`}>{option.description}</span>
        </span>
      </label>)}
    </div>
  </div>;
}
