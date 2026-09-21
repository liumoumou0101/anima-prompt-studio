import {useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode} from "react";
import {ImageSquare, TextT, X} from "@phosphor-icons/react";
import "./conversationStudio.css";

export interface ConversationStudioViewProps {
  editor: ReactNode;
  results: ReactNode;
  settings: ReactNode;
  composer: ReactNode;
  auxiliary?: ReactNode;
  history?: ReactNode;
  historyOpen: boolean;
  onCloseHistory: () => void;
  busy?: boolean;
  activeView?: "prompt" | "images";
}

/** Presentation only: slot contents retain their identity when compact views change. */
export function ConversationStudioView({editor, results, settings, composer, auxiliary, history,
  historyOpen, onCloseHistory, busy = false, activeView = "images"}: ConversationStudioViewProps) {
  const [view, setView] = useState(activeView);
  const root = useRef<HTMLDivElement>(null), dock = useRef<HTMLElement>(null);
  const dialog = useRef<HTMLDialogElement>(null), closeButton = useRef<HTMLButtonElement>(null);
  const id = useId();

  useEffect(() => setView(activeView), [activeView]);

  useLayoutEffect(() => {
    const element = root.current, footer = dock.current;
    if (!element || !footer) return;
    const measure = () => {
      const bounds = element.getBoundingClientRect();
      element.style.setProperty("--studio-dock-height", `${Math.ceil(footer.getBoundingClientRect().height)}px`);
      // The workspace fills the viewport still visible above the fixed composer.
      // Expanded page notices can scroll away without leaving a permanently tiny editor.
      element.style.setProperty("--studio-top", `${Math.max(0, Math.ceil(bounds.top))}px`);
      element.style.setProperty("--studio-dock-left", `${Math.max(0, Math.ceil(bounds.left))}px`);
      element.style.setProperty("--studio-dock-right", `${Math.max(0, Math.ceil(window.innerWidth - bounds.right))}px`);
    };
    measure();
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    observer?.observe(footer);
    observer?.observe(element);
    const page = element.closest(".conversation-workbench");
    if (page) observer?.observe(page);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, {passive: true});
    return () => {observer?.disconnect(); window.removeEventListener("resize", measure); window.removeEventListener("scroll", measure);};
  }, []);

  useEffect(() => {
    const element = dialog.current;
    if (!historyOpen || !element) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    if (!element.open) {
      if (typeof element.showModal === "function") element.showModal();
      else element.setAttribute("open", "");
    }
    closeButton.current?.focus();
    return () => {
      if (element.open) {
        if (typeof element.close === "function") element.close();
        else element.removeAttribute("open");
      }
      document.body.style.overflow = previousOverflow;
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, [historyOpen]);

  return <div ref={root} className="conversation-studio" data-view={view}>
    <nav className="conversation-studio__compact-tabs" aria-label="工作区视图">
      <button type="button" aria-pressed={view === "images"} aria-controls={`${id}-images`} onClick={() => setView("images")}><ImageSquare size={17} aria-hidden="true" />图片预览</button>
      <button type="button" aria-pressed={view === "prompt"} aria-controls={`${id}-prompt`} onClick={() => setView("prompt")}><TextT size={17} aria-hidden="true" />提示词</button>
    </nav>
    <div className="conversation-studio__workspace" aria-busy={busy}>
      <div className="conversation-studio__editor" id={`${id}-prompt`}>
        {editor}
        {auxiliary && <details className="conversation-studio__auxiliary"><summary>更多创作工具</summary>{auxiliary}</details>}
      </div>
      <div className="conversation-studio__results" id={`${id}-images`}>{results}</div>
    </div>
    <footer ref={dock} className="conversation-studio__dock" aria-label="修改意见与生成操作">
      <div className="conversation-studio__settings">{settings}</div>
      <div className="conversation-studio__composer">{composer}</div>
    </footer>
    <dialog ref={dialog} className="conversation-studio__history" aria-labelledby={`${id}-history-title`}
      onCancel={event => {event.preventDefault(); onCloseHistory();}}
      onKeyDown={event => {
        if (event.key === "Escape") {event.preventDefault(); onCloseHistory();}
      }}>
      <header className="conversation-studio__history-heading"><div><p>按想法和图片找回</p><h2 id={`${id}-history-title`}>创作记录</h2></div>
        <button ref={closeButton} type="button" aria-label="关闭创作记录" onClick={onCloseHistory}><X size={18} aria-hidden="true" />关闭</button>
      </header>
      {historyOpen && history}
    </dialog>
  </div>;
}
