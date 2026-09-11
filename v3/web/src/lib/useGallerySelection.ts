import {useEffect, useRef, useState} from "react";
import type {Dispatch, PointerEvent as ReactPointerEvent, SetStateAction} from "react";

type Modifiers = {shiftKey?: boolean; ctrlKey?: boolean; metaKey?: boolean};
type Box = {left: number; top: number; width: number; height: number};

export function useGallerySelection(paths: string[], scope: string, selected: Set<string>,
  setSelected: Dispatch<SetStateAction<Set<string>>>, disabled: boolean) {
  const [selecting, setSelecting] = useState(false);
  const [box, setBox] = useState<Box | null>(null);
  const anchor = useRef<string | null>(null);
  const cleanup = useRef<(() => void) | null>(null);
  const suppressClick = useRef(false);
  const gridRef = useRef<HTMLDivElement>(null);
  const latest = useRef({paths, selected, disabled});
  latest.current = {paths, selected, disabled};

  useEffect(() => {
    cleanup.current?.(); anchor.current = null; setSelected(new Set());
  }, [scope, setSelected]);
  useEffect(() => () => cleanup.current?.(), []);
  const pathKey = JSON.stringify(paths);
  useEffect(() => {
    const allowed = new Set(latest.current.paths);
    setSelected(current => [...current].some(path => !allowed.has(path))
      ? new Set([...current].filter(path => allowed.has(path))) : current);
  }, [pathKey, setSelected]);

  function toggle(path: string, event: Modifiers = {}) {
    if (disabled) return;
    setSelecting(true);
    const from = anchor.current ? paths.indexOf(anchor.current) : -1;
    const to = paths.indexOf(path);
    if (event.shiftKey && from >= 0 && to >= 0) {
      setSelected(current => new Set([...current, ...paths.slice(Math.min(from, to), Math.max(from, to) + 1)]));
    } else {
      setSelected(current => {const next = new Set(current); next.has(path) ? next.delete(path) : next.add(path); return next;});
      anchor.current = path;
    }
  }
  function clear() {setSelected(new Set()); anchor.current = null;}
  function all() {if (!disabled) {setSelecting(true); setSelected(new Set(paths));}}

  function pointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (disabled || event.button !== 0 || event.pointerType === "touch") return;
    const target = event.target as HTMLElement;
    if (target.closest("button, a, input, select") && !(selecting && target.closest(".legacy-photo-open"))) return;
    const host = event.currentTarget;
    const startX = event.clientX, startY = event.clientY, startScroll = window.scrollY;
    const original = new Set(selected);
    const additive = event.ctrlKey || event.metaKey || event.shiftKey;
    let moved = false, x = startX, y = startY;
    let frame = 0;
    const autoScroll = () => {
      if (moved) {
        const speed = y > window.innerHeight - 60 ? 14 : y < 60 ? -14 : 0;
        if (speed) window.scrollBy(0, speed);
      }
      frame = window.requestAnimationFrame(autoScroll);
    };
    const update = () => {
      const originY = startY + startScroll - window.scrollY;
      if (!moved && Math.hypot(x - startX, y - originY) < 6) return;
      moved = true; setSelecting(true);
      const rect = {left: Math.min(startX, x), top: Math.min(originY, y), width: Math.abs(x - startX), height: Math.abs(y - originY)};
      const next = new Set(additive ? original : []);
      host.querySelectorAll<HTMLElement>("[data-selection-path]").forEach(card => {
        const r = card.getBoundingClientRect();
        if (r.width && r.height && r.left < rect.left + rect.width && r.right > rect.left
          && r.top < rect.top + rect.height && r.bottom > rect.top) next.add(card.dataset.selectionPath!);
      });
      setSelected(next); setBox(rect);
    };
    const move = (e: PointerEvent) => {if (e.pointerId !== event.pointerId) return; x = e.clientX; y = e.clientY; update(); if (moved) e.preventDefault();};
    const finish = (cancel = false) => {
      if (cancel && moved) setSelected(original);
      if (moved) {suppressClick.current = true; window.setTimeout(() => {suppressClick.current = false;}, 0); anchor.current = null;}
      window.cancelAnimationFrame(frame);
      setBox(null); document.removeEventListener("pointermove", move); document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", canceled); document.removeEventListener("keydown", key);
      window.removeEventListener("scroll", update); cleanup.current = null;
    };
    const up = (e: PointerEvent) => {if (e.pointerId === event.pointerId) finish();};
    const canceled = () => finish(true);
    const key = (e: KeyboardEvent) => {if (e.key === "Escape") {e.preventDefault(); finish(true);}};
    cleanup.current = canceled;
    document.addEventListener("pointermove", move, {passive: false}); document.addEventListener("pointerup", up);
    document.addEventListener("pointercancel", canceled); document.addEventListener("keydown", key);
    window.addEventListener("scroll", update);
    frame = window.requestAnimationFrame(autoScroll);
  }
  return {selecting, setSelecting, box, gridRef, toggle, clear, all, pointerDown,
    suppressClick, isSelectionClick: (event: Modifiers) => selecting || event.shiftKey || event.ctrlKey || event.metaKey};
}
