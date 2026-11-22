import { useEffect, useId, useRef } from "react";
import "./mossNegativePrompt.css";

export function MossNegativePrompt({ value, onChange, expanded, onExpandedChange, disabled = false }: {
  value: string;
  onChange: (value: string) => void;
  expanded: boolean;
  onExpandedChange: (expanded: boolean) => void;
  disabled?: boolean;
}) {
  const id = useId();
  const input = useRef<HTMLTextAreaElement>(null);
  const wasExpanded = useRef(expanded);
  useEffect(() => {
    if (expanded && !wasExpanded.current) input.current?.focus({ preventScroll: true });
    wasExpanded.current = expanded;
  }, [expanded]);
  return <section className="moss-negative">
    <button type="button" className="moss-negative-toggle" aria-expanded={expanded} aria-controls={id}
      disabled={disabled} onClick={() => onExpandedChange(!expanded)}>
      <span aria-hidden="true">{expanded ? "▾" : "▸"}</span>
      <span>负向提示词（可选）</span>
      <small>{value.trim() ? "已填写" : "未填写"}</small>
    </button>
    {expanded && <div id={id} className="moss-negative-content">
      <label htmlFor={`${id}-input`}>不希望出现的内容</label>
      <textarea ref={input} id={`${id}-input`} aria-label="负向提示词" rows={3} value={value}
        disabled={disabled} placeholder="如水印、模糊、多余的肢体，可留空。"
        onChange={event => onChange(event.target.value)} />
      <p>支持中文，也可以留空。</p>
    </div>}
  </section>;
}
