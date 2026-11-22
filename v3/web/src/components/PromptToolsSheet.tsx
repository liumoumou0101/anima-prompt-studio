import {useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode} from "react";
import {X} from "@phosphor-icons/react";
import {useBodyScrollLock} from "../lib/useBodyScrollLock";
import "./promptToolsSheet.css";

export interface PromptToolSection {id: string; label: string; summary?: string; content: ReactNode}

export function PromptToolsSheet({sections, disabled = false, status, initialSection, open: controlledOpen, onOpenChange}: {
  sections: PromptToolSection[]; disabled?: boolean; status?: ReactNode; initialSection?: string;
  open?: boolean; onOpenChange?: (open: boolean) => void;
}) {
  const [internalOpen, setInternalOpen] = useState(false);
  const open = controlledOpen ?? internalOpen;
  function setOpen(next: boolean) {
    if (controlledOpen === undefined) setInternalOpen(next);
    onOpenChange?.(next);
  }
  const [selected, setSelected] = useState(initialSection || sections[0]?.id || "");
  const preferred = useRef<string | undefined>(undefined);
  const dialog = useRef<HTMLDialogElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const entries = useRef(new Map<string, HTMLButtonElement>());
  const tabs = useRef(new Map<string, HTMLButtonElement>());
  const backdropPress = useRef(false);
  const composing = useRef(false);
  const id = useId();
  const active = sections.some(section => section.id === selected) ? selected : sections[0]?.id;
  useBodyScrollLock(open);

  useEffect(() => {
    if (preferred.current === initialSection) return;
    preferred.current = initialSection;
    if (initialSection && sections.some(section => section.id === initialSection)) {
      trigger.current = entries.current.get(initialSection) || null;
      setSelected(initialSection); setOpen(true);
    }
  }, [initialSection, sections]);

  useLayoutEffect(() => {
    if (!open) {
      const previous = trigger.current;
      trigger.current = null;
      // A cleanup focus change is undone by React while the old close button
      // stays mounted. Restore in the closed layout phase after that commit.
      if (previous?.isConnected) previous.focus({preventScroll: true});
      return;
    }
    const element = dialog.current;
    if (!element) return;
    if (!element.open) element.showModal();
    closeButton.current?.focus({preventScroll: true});
    return () => {
      if (element.open) element.close();
      composing.current = false;
      backdropPress.current = false;
    };
  }, [open]);

  function openSection(section: string, source: HTMLButtonElement) {
    trigger.current = source;
    setSelected(section);
    setOpen(true);
  }
  function moveTab(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next: number;
    if (event.key === "ArrowRight") next = (index + 1) % sections.length;
    else if (event.key === "ArrowLeft") next = (index + sections.length - 1) % sections.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = sections.length - 1;
    else return;
    event.preventDefault();
    setSelected(sections[next].id);
    tabs.current.get(sections[next].id)?.focus({preventScroll: true});
  }
  function outside(event: MouseEvent<HTMLDialogElement>) {
    if (event.target !== event.currentTarget) return false;
    const bounds = event.currentTarget.getBoundingClientRect();
    return event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom;
  }

  return <div className="prompt-tools">
    <div className="prompt-tools__toolbar" role="group" aria-label="提示词辅助工具">
      {sections.map(section => <button key={section.id} ref={element => {if (element) entries.current.set(section.id, element); else entries.current.delete(section.id);}}
        type="button" aria-haspopup="dialog" aria-controls={`${id}-dialog`}
        onClick={event => openSection(section.id, event.currentTarget)}>
        <span>{section.label}</span>{section.summary && <small>{section.summary}</small>}
      </button>)}
    </div>
    {status && <div className="prompt-tools__status">{status}</div>}
    <dialog ref={dialog} id={`${id}-dialog`} className="prompt-tools-sheet" aria-modal="true" aria-labelledby={`${id}-title`}
      onClose={event => {if (!event.currentTarget.open) setOpen(false);}}
      onCancel={event => {event.preventDefault(); setOpen(false);}}
      onCompositionStart={() => {composing.current = true;}}
      onCompositionEnd={() => {composing.current = false;}}
      onKeyDown={event => {
        if (event.key === "Tab" && !event.defaultPrevented) {
          const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("button, a[href], input, select, textarea, summary, [tabindex]"))
            .filter(element => element.tabIndex >= 0 && !element.matches(":disabled") && element.getClientRects().length > 0 && getComputedStyle(element).visibility !== "hidden");
          const first = controls[0], last = controls.at(-1);
          if (event.shiftKey && document.activeElement === first || !event.shiftKey && document.activeElement === last) {
            event.preventDefault(); (event.shiftKey ? last : first)?.focus({preventScroll: true});
          }
          return;
        }
        if (event.key !== "Escape") return;
        const consumed = event.defaultPrevented || composing.current || event.nativeEvent.isComposing || event.keyCode === 229;
        // Cancel the native default too: a child popup or an IME owns this Escape.
        event.preventDefault();
        if (consumed) return;
        event.stopPropagation(); setOpen(false);
      }}
      onMouseDown={event => {backdropPress.current = outside(event);}}
      onClick={event => {if (backdropPress.current && outside(event)) setOpen(false); backdropPress.current = false;}}>
      <header className="prompt-tools-sheet__header"><div><p>提示词工作区</p><h2 id={`${id}-title`}>创作辅助</h2></div>
        <button ref={closeButton} type="button" aria-label="关闭辅助设置" onClick={() => setOpen(false)}><X size={20} aria-hidden="true" /></button>
      </header>
      <nav className="prompt-tools-sheet__tabs" role="tablist" aria-label="辅助设置分类">
        {sections.map((section, index) => <button key={section.id} ref={element => {if (element) tabs.current.set(section.id, element); else tabs.current.delete(section.id);}}
          type="button" role="tab" id={`${id}-tab-${section.id}`} aria-controls={`${id}-panel-${section.id}`}
          aria-selected={active === section.id} tabIndex={active === section.id ? 0 : -1}
          onClick={() => setSelected(section.id)} onKeyDown={event => moveTab(event, index)}>{section.label}</button>)}
      </nav>
      <div className="prompt-tools-sheet__body">
        <fieldset className="prompt-tools-sheet__fields" disabled={disabled}>
          {sections.map(section => <section key={section.id} role="tabpanel" id={`${id}-panel-${section.id}`}
            aria-labelledby={`${id}-tab-${section.id}`} hidden={active !== section.id} tabIndex={0}>{section.content}</section>)}
        </fieldset>
      </div>
      <footer className="prompt-tools-sheet__footer"><span>修改会保留在当前提示词草稿中</span><button type="button" onClick={() => setOpen(false)}>返回提示词</button></footer>
    </dialog>
  </div>;
}
