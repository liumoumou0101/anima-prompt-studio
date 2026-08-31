import {useState} from "react";
import {Copy, ShoppingBagOpen, X} from "@phosphor-icons/react";
import {useNavigate} from "react-router-dom";
import type {TagSearchItem} from "../lib/types";

export function TagBasket({selected, onToggle, onClear}: {selected: TagSearchItem[]; onToggle: (item: TagSearchItem) => void; onClear: () => void}) {
  const navigate = useNavigate();
  const [copied, setCopied] = useState(false);
  if (!selected.length) return null;

  async function copySelected() {
    await navigator.clipboard.writeText(selected.map((item) => item.name.replaceAll("_", " ")).join(", "));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  function sendToWorkbench() {
    const query = new URLSearchParams();
    selected.forEach((item) => query.append("tag", item.name));
    navigate(`/workbench?${query}`);
  }

  return <aside className="tag-basket" aria-label="已选择标签">
    <div className="tag-basket-title"><ShoppingBagOpen size={20} /><span><strong>已挑选 {selected.length} 个标签</strong><small>会作为明确选择带入结构化工作台</small></span></div>
    <div className="tag-basket-items">{selected.map((item) => <button type="button" key={item.name} onClick={() => onToggle(item)} title="移除"><span>{item.cn_name || item.display_name}</span><X size={12} /></button>)}</div>
    <div className="tag-basket-actions"><button type="button" onClick={onClear}>清空</button><button type="button" onClick={() => void copySelected()}><Copy />{copied ? "已复制" : "复制标签"}</button><button type="button" className="basket-primary" onClick={sendToWorkbench}>带入工作台</button></div>
  </aside>;
}
