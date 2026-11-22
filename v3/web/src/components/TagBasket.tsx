import {useState} from "react";
import {Copy, ShoppingBagOpen, X} from "@phosphor-icons/react";
import {useNavigate} from "react-router-dom";
import type {TagSearchItem} from "../lib/types";
import {transferUrl} from "../lib/contentTransfer";

export function TagBasket({selected, onToggle, onClear}: {selected: TagSearchItem[]; onToggle: (item: TagSearchItem) => void; onClear: () => void}) {
  const navigate = useNavigate();
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  if (!selected.length) return null;

  async function copySelected() {
    await navigator.clipboard.writeText(selected.map((item) => item.name.replaceAll("_", " ")).join(", "));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  function sendToWorkbench(destination: "current" | "new" = "current") {
    try {navigate(transferUrl(selected.map(({name, category}) => ({name, category})), destination));}
    catch (caught) {setError((caught as Error).message);}
  }

  return <aside className="tag-basket" aria-label="已选择标签">
    <div className="tag-basket-title"><ShoppingBagOpen size={20} /><span><strong>已挑选 {selected.length} 个标签</strong><small>按类型加入会话要求，保留已有草稿，可撤销</small></span></div>
    <div className="tag-basket-items">{selected.map((item) => <button type="button" key={item.name} onClick={() => onToggle(item)} title="移除"><span>{item.cn_name || item.display_name}</span><X size={12} /></button>)}</div>
    {error && <p role="alert">{error}</p>}
    <div className="tag-basket-actions"><button type="button" onClick={onClear}>清空</button><button type="button" onClick={() => void copySelected()}><Copy />{copied ? "已复制" : "复制标签"}</button><button type="button" onClick={() => sendToWorkbench("new")}>带入新会话</button><button type="button" className="basket-primary" onClick={() => sendToWorkbench()}>带入工作台</button></div>
  </aside>;
}
