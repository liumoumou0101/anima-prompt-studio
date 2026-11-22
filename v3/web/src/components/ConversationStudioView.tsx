import {useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode} from "react";
import {ClockCounterClockwise, ImageSquare, SlidersHorizontal, TextT, X} from "@phosphor-icons/react";
import "./conversationStudio.css";

export interface ConversationStudioViewProps {
  editor: ReactNode;
  results: ReactNode;
  settings: ReactNode;
  composer: ReactNode;
  auxiliary?: ReactNode;
  history?: ReactNode;
  context?: ReactNode;
  generationBar?: ReactNode;
  historyOpen: boolean;
  onOpenHistory?: () => void;
  onCloseHistory: () => void;
  busy?: boolean;
  activeView?: "prompt" | "images";
  resultRequestKey?: string;
  parameterRequestKey?: number;
}

/** Stable slots share one responsive shell; viewing parameters never replaces the editor. */
export function ConversationStudioView({editor, results, settings, composer, auxiliary, history, context, generationBar,
  historyOpen, onOpenHistory, onCloseHistory, busy = false, activeView = "images", resultRequestKey, parameterRequestKey}: ConversationStudioViewProps) {
  const [view, setView] = useState(activeView);
  const [inspector, setInspector] = useState<"results" | "parameters">("results");
  const root = useRef<HTMLDivElement>(null), closeButton = useRef<HTMLButtonElement>(null);
  const settingsRegion = useRef<HTMLElement>(null), focusedParameterRequest = useRef<number|undefined>(undefined);
  const id = useId();
  useEffect(() => setView(activeView), [activeView]);
  useEffect(() => {if(resultRequestKey){setInspector("results");setView("images");}},[resultRequestKey]);
  useEffect(() => {if(parameterRequestKey){setInspector("parameters");setView("images");}},[parameterRequestKey]);
  useLayoutEffect(() => {
    const element = root.current;
    if (!element) return;
    const measure = () => element.style.setProperty("--studio-top", `${Math.max(0, Math.ceil(element.getBoundingClientRect().top))}px`);
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    const page = element.closest(".conversation-workbench");
    if (page) observer?.observe(page);
    window.addEventListener("resize", measure);
    return () => {observer?.disconnect(); window.removeEventListener("resize", measure);};
  }, []);
  useEffect(() => {
    if (!historyOpen) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setView("images"); closeButton.current?.focus();
    return () => {if (previousFocus?.isConnected) previousFocus.focus();};
  }, [historyOpen]);
  useEffect(() => {
    if (!parameterRequestKey || focusedParameterRequest.current === parameterRequestKey || historyOpen || view !== "images" || inspector !== "parameters") return;
    // Wait for visibility and history focus restoration before handing keyboard navigation to the panel.
    settingsRegion.current?.focus();
    focusedParameterRequest.current = parameterRequestKey;
  }, [parameterRequestKey, historyOpen, view, inspector]);
  function selectInspector(next: "results" | "parameters") {
    setInspector(next); setView("images"); if (historyOpen) onCloseHistory();
  }
  return <div ref={root} className="conversation-studio" data-view={view} data-inspector={historyOpen ? "history" : inspector}>
    {context && <div className="conversation-studio__context">{context}</div>}
    <nav className="conversation-studio__compact-tabs" aria-label="工作区视图">
      <button type="button" aria-pressed={view === "prompt"} aria-controls={`${id}-prompt`} onClick={() => setView("prompt")}><TextT size={17} aria-hidden="true" />提示词</button>
      <button type="button" aria-pressed={view === "images"} aria-controls={`${id}-images`} onClick={() => setView("images")}><ImageSquare size={17} aria-hidden="true" />图片预览</button>
    </nav>
    <div className="conversation-studio__workspace" aria-busy={busy}>
      <section className="conversation-studio__editor" id={`${id}-prompt`} aria-label="编辑工作区">
        <div className="conversation-studio__editor-main">{editor}
          {auxiliary && <section className="conversation-studio__auxiliary" aria-label="创作工具">{auxiliary}</section>}
        </div>
        <footer className="conversation-studio__composer" aria-label="修改意见与生成操作">{composer}</footer>
      </section>
      <aside className="conversation-studio__inspector" id={`${id}-images`} aria-label="结果与创作条件">
        <nav className="conversation-studio__inspector-tabs" aria-label="查看结果、参数或版本">
          <button type="button" aria-pressed={!historyOpen && inspector === "results"} aria-controls={`${id}-results`} onClick={() => selectInspector("results")}><ImageSquare size={17} aria-hidden="true" />结果</button>
          <button type="button" aria-label="生成参数" aria-pressed={!historyOpen && inspector === "parameters"} aria-controls={`${id}-parameters`} onClick={() => selectInspector("parameters")}><SlidersHorizontal size={17} aria-hidden="true" />参数</button>
          <button type="button" aria-label="创作记录" title="创作记录：版本与历史图片" aria-pressed={historyOpen} aria-controls={`${id}-history`} onClick={onOpenHistory}><ClockCounterClockwise size={17} aria-hidden="true" />记录</button>
        </nav>
        <section className="conversation-studio__results" id={`${id}-results`} aria-label="生成结果" hidden={historyOpen || inspector !== "results"}>{results}</section>
        <section ref={settingsRegion} tabIndex={-1} className="conversation-studio__settings" id={`${id}-parameters`} aria-label="生成参数" hidden={historyOpen || inspector !== "parameters"}>{settings}</section>
        <dialog open={historyOpen} aria-modal="false" id={`${id}-history`} className="conversation-studio__history" aria-labelledby={`${id}-history-title`}
          onCancel={event => {event.preventDefault(); onCloseHistory();}} onKeyDown={event => {if (event.key === "Escape") {event.preventDefault(); onCloseHistory();}}}>
          <header className="conversation-studio__history-heading"><h2 id={`${id}-history-title`}>创作记录</h2>
            <button ref={closeButton} type="button" aria-label="关闭创作记录" onClick={onCloseHistory}><X size={18} aria-hidden="true" />关闭</button>
          </header>
          {historyOpen && history}
        </dialog>
      </aside>
    </div>
    {generationBar && <footer className="conversation-studio__generation">{generationBar}</footer>}
  </div>;
}
