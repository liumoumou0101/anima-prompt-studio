import {useLayoutEffect} from "react";

type Lock = {count: number; restore: () => void};
const locks = new WeakMap<Document, Lock>();

function saveProperty(style: CSSStyleDeclaration, property: string) {
  const value = style.getPropertyValue(property);
  const priority = style.getPropertyPriority(property);
  return () => {
    if (value) style.setProperty(property, value, priority);
    else style.removeProperty(property);
  };
}

/** Share one scroll lock across nested overlays without moving the page. */
export function useBodyScrollLock(enabled = true): void {
  useLayoutEffect(() => {
    if (!enabled) return;
    const doc = document;
    let lock = locks.get(doc);
    if (!lock) {
      const root = doc.documentElement;
      const body = doc.body;
      const restoreGutter = saveProperty(root.style, "scrollbar-gutter");
      // Preserve longhands too: changing the shorthand overwrites them.
      const restoreOverflow = ["overflow", "overflow-x", "overflow-y"].map(property => saveProperty(body.style, property));
      const view = doc.defaultView;
      const gutter = view?.getComputedStyle(root).getPropertyValue("scrollbar-gutter") || "";
      const needsGutter = !/(^|\s)stable(?:\s|$)/.test(gutter) && Boolean(view && view.innerWidth > root.clientWidth);
      // Reserve the existing scrollbar space before hiding it. No padding
      // compensation is needed, including when the stylesheet already reserves it.
      // Short pages without a scrollbar must not acquire a new empty gutter.
      if (needsGutter) root.style.setProperty("scrollbar-gutter", "stable", "important");
      body.style.setProperty("overflow", "hidden", "important");
      lock = {count: 0, restore: () => {
        restoreOverflow.forEach(restore => restore());
        if (needsGutter) restoreGutter();
      }};
      locks.set(doc, lock);
    }
    lock.count += 1;
    const activeLock = lock;
    return () => {
      activeLock.count -= 1;
      if (activeLock.count === 0) {
        activeLock.restore();
        locks.delete(doc);
      }
    };
  }, [enabled]);
}
