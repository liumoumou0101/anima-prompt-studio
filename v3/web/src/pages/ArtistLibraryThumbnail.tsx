import {useEffect, useRef, useState} from "react";
import {Link} from "react-router-dom";
import {ImageSquare} from "@phosphor-icons/react";
import {apiRequest} from "../lib/api";

type Sample = {id: string; title: string; content_level: string; model: string;
  thumbnail_url: string; reference_url: string; artists?: string[]; lora_dependency?: string};

/** Only real, locally indexed model examples are shown; never an invented artist avatar. */
export function ArtistLibraryThumbnail({artist}: {artist: string}) {
  const host = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [sample, setSample] = useState<Sample | null>(null);
  const [state, setState] = useState<"pending" | "loading" | "ready" | "empty" | "error">("pending");
  useEffect(() => {
    if (!host.current || typeof IntersectionObserver === "undefined") {setVisible(true); return;}
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) {setVisible(true); observer.disconnect();}
    }, {rootMargin: "160px"});
    observer.observe(host.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!visible) return;
    const controller = new AbortController();
    setState("loading"); setSample(null);
    void apiRequest<{items: Sample[]}>(`/api/v3/reference-examples/by-artist?${new URLSearchParams({artist, limit: "1"})}`, {signal: controller.signal})
      .then(response => {
        if (controller.signal.aborted) return;
        const next = response.items?.find(item => item.content_level === "safe" && item.thumbnail_url && item.reference_url);
        setSample(next || null); setState(next ? "ready" : "empty");
      }).catch(() => {if (!controller.signal.aborted) setState("error");});
    return () => controller.abort();
  }, [artist, visible]);
  return <div ref={host} className="artist-library-thumbnail">
    {sample && state === "ready" ? <Link to={sample.reference_url} aria-label={`查看 ${artist} 的案例：${sample.title}`}>
      <img src={sample.thumbnail_url} alt={sample.title} loading="lazy" onError={() => setState("error")} />
      <span>模型案例 · {sample.model || "模型未记录"}{(sample.artists?.length || 0) > 1 ? " · 多画师组合" : ""}{sample.lora_dependency === "lora" ? " · 含 LoRA" : ""}</span>
    </Link> : <div className="artist-thumbnail-empty"><ImageSquare aria-hidden="true" size={28} />
      <span>{state === "pending" || state === "loading" ? "正在读取本地样图" : state === "error" ? "样图暂不可用" : "本地暂无样图"}</span>
      <small>可继续查看题材关联</small></div>}
  </div>;
}
