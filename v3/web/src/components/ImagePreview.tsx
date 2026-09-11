import {useState} from "react";
import Lightbox from "yet-another-react-lightbox";
import Zoom from "yet-another-react-lightbox/plugins/zoom";
import "yet-another-react-lightbox/styles.css";

export type PreviewImage = {src: string; alt: string; width?: number; height?: number;
  positive?: string; negative?: string; parameters?: Record<string, unknown>};

/** One viewer for gallery originals and generation results. No image is fetched until opened. */
export function ImagePreview({images, index, onClose}: {images: PreviewImage[]; index: number; onClose: () => void}) {
  const [current, setCurrent] = useState(index);
  const [details, setDetails] = useState(false);
  if (index < 0 || !images.length) return null;
  const item = images[Math.max(0, Math.min(current, images.length - 1))];
  return <Lightbox open close={onClose} index={index} slides={images} plugins={[Zoom]}
    carousel={{finite: true, preload: 1}} zoom={{scrollToZoom: true}}
    on={{view: ({index: next}) => setCurrent(next)}}
    labels={{Close: "关闭预览", Previous: "上一张", Next: "下一张", "Zoom in": "放大", "Zoom out": "缩小"}}
    toolbar={{buttons: [<button key="details" className="yarl__button" aria-pressed={details} onClick={() => setDetails(value => !value)}>图片信息</button>, "close"]}}
    render={{controls: () => <>
      <div className="image-preview-caption">{current + 1} / {images.length} · {item.alt}</div>
      {details && <aside className="image-preview-info" aria-label="预览图片信息"><h2>{item.alt}</h2>
        {item.width && item.height && <p>{item.width} × {item.height}</p>}
        <dl>{Object.entries(item.parameters || {}).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}</dl>
        {item.positive !== undefined && <><h3>正向提示词</h3><p>{item.positive || "未记录"}</p></>}
        {item.negative !== undefined && <><h3>负向提示词</h3><p>{item.negative || "空"}</p></>}
        <a href={item.src} target="_blank" rel="noreferrer">在新标签页打开原图</a>
        <button onClick={() => setDetails(false)}>收起图片信息</button>
      </aside>}
    </>}} />;
}
