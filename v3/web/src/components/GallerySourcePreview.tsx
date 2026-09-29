import {useRef, useState} from "react";
import {Copy} from "@phosphor-icons/react";
import {copyImageFileToClipboard} from "../lib/copyImage";
import {ImagePreview} from "./ImagePreview";
import "./workbenchResults.css";

export type GallerySource = {path: string; name: string; mode: "generation" | "prompt"};

export function GallerySourcePreview({source}: {source: GallerySource}) {
  const src = `/api/v3/gallery/assets/content?path=${encodeURIComponent(source.path)}`;
  const [preview, setPreview] = useState(false);
  const [failedPath, setFailedPath] = useState<string | null>(null);
  const [copying, setCopying] = useState(false);
  const [copyResult, setCopyResult] = useState<{path: string; error?: string} | null>(null);
  const copyInFlight = useRef(false);
  const imageFailed = failedPath === source.path;
  const currentCopyResult = copyResult?.path === source.path ? copyResult : null;

  async function copyOriginal() {
    if (!source.path || copyInFlight.current) return;
    copyInFlight.current = true;
    setCopying(true);
    setCopyResult(null);
    try {
      await copyImageFileToClipboard(source.path);
      setCopyResult({path: source.path});
    } catch (error) {
      setCopyResult({path: source.path, error: error instanceof Error ? error.message : "复制失败，请重试。"});
    } finally {
      copyInFlight.current = false;
      setCopying(false);
    }
  }

  return <section className="workbench-image-results" aria-label="画廊来源图片">
    <header className="workbench-result-heading"><div><h2>画廊来源图</h2><p>{source.name}</p></div>
      <button type="button" className="workbench-copy-original" disabled={copying || !source.path}
        onClick={() => void copyOriginal()}><Copy size={16} aria-hidden="true" />{copying ? "复制中…" : "复制原图"}</button></header>
    {currentCopyResult && <p className="workbench-copy-feedback" role={currentCopyResult.error ? "alert" : "status"}>
      {currentCopyResult.error || "已复制原图文件，可粘贴到文件夹。"}</p>}
    <div className="workbench-image-stage"><figure className="workbench-image-frame">
      <button type="button" className="workbench-image-open" aria-label="放大查看来源原图" disabled={imageFailed}
        onClick={() => setPreview(true)}><img src={src} alt={source.name} onError={() => setFailedPath(source.path)} /></button>
      <figcaption>来源原图 · {source.name}</figcaption></figure></div>
    {imageFailed && <p role="alert">来源原图读取失败，请检查图片文件是否仍可用。</p>}
    <div className="workbench-result-footer"><p className="workbench-results-note">{source.mode === "generation"
      ? "已恢复画廊图片的生成条件；继续前请核对模型和执行目标。"
      : "只导入提示词，生成时使用工作台默认参数；继续前请核对模型和执行目标。"}</p></div>
    {preview && !imageFailed && <ImagePreview index={0} onClose={() => setPreview(false)}
      images={[{src, alt: source.name}]} />}
  </section>;
}
