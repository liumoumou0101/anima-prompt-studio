import {useId, useLayoutEffect, useRef} from "react";
import {createPortal} from "react-dom";
import {SlidersHorizontal, X} from "@phosphor-icons/react";
import type {GalleryAsset} from "../lib/types";
import {useBodyScrollLock} from "../lib/useBodyScrollLock";
import "./GalleryCompare.css";

/** Keep a comparison above the gallery without changing the gallery's dimensions or scroll. */
export function GalleryCompare({assets, onClose}: {assets: GalleryAsset[]; onClose: () => void}) {
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const closeHandler = useRef(onClose);
  closeHandler.current = onClose;
  const titleId = useId();
  useBodyScrollLock();

  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const {body} = document;

    const backgrounds = new Map<HTMLElement, boolean>();
    const isolateBackground = () => {
      for (const child of body.children) {
        if (!(child instanceof HTMLElement) || child === dialog || backgrounds.has(child)) continue;
        backgrounds.set(child, child.inert);
        child.inert = true;
      }
    };
    isolateBackground();
    const observer = new MutationObserver(isolateBackground);
    observer.observe(body, {childList: true});
    closeRef.current?.focus({preventScroll: true});

    const keepFocus = (event: FocusEvent) => {
      if (!dialog.contains(event.target as Node)) closeRef.current?.focus({preventScroll: true});
    };
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        closeHandler.current();
      } else if (event.key === "Tab") {
        // The close button is currently the only interactive element in this viewer.
        event.preventDefault();
        closeRef.current?.focus({preventScroll: true});
      }
    };
    document.addEventListener("focusin", keepFocus);
    document.addEventListener("keydown", handleKey, true);
    return () => {
      observer.disconnect();
      document.removeEventListener("focusin", keepFocus);
      document.removeEventListener("keydown", handleKey, true);
      backgrounds.forEach((inert, element) => { element.inert = inert; });
      if (previousFocus?.isConnected) previousFocus.focus({preventScroll: true});
    };
  }, []);

  return createPortal(<section ref={dialogRef} className="gallery-compare-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}>
    <header className="gallery-compare-header">
      <div><SlidersHorizontal size={20} aria-hidden="true" /><h2 id={titleId}>图片比较</h2><span>{assets.length} 张</span></div>
      <button ref={closeRef} type="button" onClick={onClose} aria-label="关闭比较"><span>关闭</span><kbd>Esc</kbd><X size={19} aria-hidden="true" /></button>
    </header>
    <div className={`gallery-compare-grid${assets.length > 2 ? " has-multiple-rows" : ""}`}>
      {assets.map((asset, index) => {
        const params = asset.generation_params || {};
        const seed = params.seed ?? asset.artist_comparison?.seed;
        return <figure key={asset.path} className="gallery-compare-item">
          <div className="gallery-compare-image"><img src={asset.content_url} alt={asset.name} decoding="async" /></div>
          <figcaption>
            <div className="gallery-compare-filename"><span>{index + 1}</span><strong title={asset.name}>{asset.name}</strong></div>
            <dl>
              <div><dt>模型</dt><dd title={asset.model_profile || "未记录"}>{asset.model_profile || "未记录"}</dd></div>
              <div><dt>Seed</dt><dd title={seed == null ? "未记录" : String(seed)}>{seed == null ? "未记录" : String(seed)}</dd></div>
              <div><dt>尺寸</dt><dd>{asset.width && asset.height ? `${asset.width} × ${asset.height}` : "未记录"}</dd></div>
              {params.steps != null && <div><dt>步数</dt><dd>{String(params.steps)}</dd></div>}
              {params.cfg != null && <div><dt>CFG</dt><dd>{String(params.cfg)}</dd></div>}
            </dl>
          </figcaption>
        </figure>;
      })}
    </div>
  </section>, document.body);
}
