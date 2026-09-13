import {useEffect, useState} from "react";
import {Link} from "react-router-dom";
import {apiRequest} from "../lib/api";

type Sample = {id: string; title: string; artists: string[]; model: string; content_level: string;
  lora_dependency: string; thumbnail_url: string; reference_url: string};
const dependencies: Record<string, string> = {none: "已确认无 LoRA", lora: "含 LoRA", unknown: "LoRA 依赖未知"};

/** Collected model outputs are evidence of a particular recipe, never artist originals. */
export function ArtistReferencePreview({artist, initiallyOpen = false}: {artist: string; initiallyOpen?: boolean}) {
  const [open, setOpen] = useState(initiallyOpen);
  const [items, setItems] = useState<Sample[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setItems([]); setError(""); setLoading(true);
    apiRequest<{items: Sample[]}>(`/api/v3/reference-examples/by-artist?${new URLSearchParams({artist, limit: "4"})}`, {signal: controller.signal})
      .then(result => {if (!controller.signal.aborted) setItems((result.items || []).filter(item => item.content_level === "safe"));})
      .catch(reason => {if (!controller.signal.aborted) setError((reason as Error).message);})
      .finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [open, artist, retry]);
  return <details open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary aria-label={`${artist} 的本地参考样图`}>本地参考样图</summary>
    <p>这里是使用该画师 tag 的模型生成案例，不是画师原作；其他画师、模型、提示词和 LoRA 都可能影响结果。</p>
    {loading ? <p role="status">正在读取本地参考…</p> : error ? <><p role="alert">{error}</p><button onClick={() => setRetry(value => value + 1)}>重试读取参考</button></>
      : !items.length ? <p>本地还没有该画师的一般内容参考样图，暂时无法据此判断生成风格。</p>
      : <div className="reference-cards">{items.map(item => <Link key={item.id} to={item.reference_url}>
        <img src={item.thumbnail_url} alt={item.title} loading="lazy" />
        <span>{item.title}</span><small>{item.model || "模型未记录"} · {dependencies[item.lora_dependency] || dependencies.unknown}</small>
        {item.artists.length > 1 && <small>组合画师：{item.artists.map(value => `@${value}`).join("、")}</small>}
      </Link>)}</div>}
  </details>;
}
