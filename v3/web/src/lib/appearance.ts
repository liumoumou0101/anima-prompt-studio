import {useEffect, useSyncExternalStore} from "react";

export type AppearanceLayout = "studio" | "editorial";
export type AppearanceTheme = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";
export interface AppearancePreference {layout: AppearanceLayout; theme: AppearanceTheme}
export interface AppearanceSnapshot extends AppearancePreference {resolvedTheme: ResolvedTheme}
export const APPEARANCE_STORAGE_KEY = "anima-appearance-v1";

function parsePreference(raw: string | null): AppearancePreference {
  try {
    const value = JSON.parse(raw || "null");
    return {
      layout: value?.layout === "editorial" ? "editorial" : "studio",
      theme: value?.theme === "dark" || value?.theme === "system" ? value.theme : "light",
    };
  } catch { return {layout: "studio", theme: "light"}; }
}

interface LayoutAnchor {main: HTMLElement; element: HTMLElement; top: number}
function captureLayoutAnchor(environment: Window | undefined): LayoutAnchor | undefined {
  if (!environment || environment.scrollY <= 0) return;
  const main = environment.document.querySelector<HTMLElement>("main");
  if (!main) return;
  // Only explicitly opted-in content participates; library/settings pages keep
  // their ordinary browser scrolling when the application shell changes.
  const regions = [...main.querySelectorAll<HTMLElement>("[data-appearance-anchor]")];
  const visible = (element: HTMLElement) => {
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < environment.innerHeight
      && rect.right > 0 && rect.left < environment.innerWidth;
  };
  const active = environment.document.activeElement as HTMLElement | null;
  let element = active && regions.some(region => region.contains(active)) && visible(active) ? active : undefined;
  if (!element) {
    const controls = regions.flatMap(region => [...region.querySelectorAll<HTMLElement>("input, textarea, select, button, [contenteditable='true'], h2, h3")]);
    const candidates = controls.filter(visible);
    if (!candidates.length) candidates.push(...regions.filter(visible));
    const readingLine = Math.min(128, environment.innerHeight / 5);
    element = candidates.sort((left, right) => Math.abs(left.getBoundingClientRect().top - readingLine)
      - Math.abs(right.getBoundingClientRect().top - readingLine))[0];
  }
  return element ? {main, element, top: element.getBoundingClientRect().top} : undefined;
}

function scheduleAnchorRestore(environment: Window, anchor: LayoutAnchor): () => void {
  let frame = 0;
  const cancel = () => {
    environment.cancelAnimationFrame(frame);
    for (const type of ["wheel", "touchstart", "pointerdown", "keydown"]) environment.removeEventListener(type, cancel);
  };
  frame = environment.requestAnimationFrame(() => {
    cancel();
    if (!anchor.element.isConnected || !anchor.main.contains(anchor.element)) return;
    const rect = anchor.element.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    let safeTop = 16;
    const navigation = environment.document.querySelector<HTMLElement>(".sidebar");
    if (navigation) {
      const navRect = navigation.getBoundingClientRect();
      const position = environment.getComputedStyle(navigation).position;
      if ((position === "sticky" || position === "fixed") && navRect.top <= 0
        && navRect.right > rect.left && navRect.left < rect.right) safeTop = Math.max(safeTop, navRect.bottom + 16);
    }
    // Preserve the visible portion of a tall editor/image whose top was already
    // above the viewport; do not jump back to the start of that content.
    const desiredTop = anchor.top < 0 ? anchor.top : Math.max(safeTop, Math.min(anchor.top, environment.innerHeight - 48));
    const change = rect.top - desiredTop;
    if (Math.abs(change) > 1) environment.scrollBy({top: change, left: 0, behavior: "instant"});
    // The same DOM nodes stay mounted. In particular, never steal focus back
    // from the appearance selector or disturb a text selection / IME session.
  });
  // Navigation or a new user interaction takes priority over a queued restore.
  for (const type of ["wheel", "touchstart", "pointerdown", "keydown"]) environment.addEventListener(type, cancel, {passive: true});
  return cancel;
}

/** Display preferences never depend on workspaces, API sessions or generation state. */
export function createAppearanceStore(environment: Window | undefined) {
  const listeners = new Set<() => void>();
  let media: MediaQueryList | undefined;
  let initialized = false;
  let cancelAnchorRestore: (() => void) | undefined;
  try { media = environment?.matchMedia?.("(prefers-color-scheme: dark)"); } catch { /* Embedded browser may not expose it. */ }
  let initial: string | null = null;
  try { initial = environment?.localStorage.getItem(APPEARANCE_STORAGE_KEY) ?? null; } catch { /* The current tab still works without storage. */ }
  const preference = parsePreference(initial);
  const resolve = (theme: AppearanceTheme): ResolvedTheme => theme === "system" ? (media?.matches ? "dark" : "light") : theme;
  let snapshot: AppearanceSnapshot = {...preference, resolvedTheme: resolve(preference.theme)};

  function applyDocument() {
    const root = environment?.document.documentElement;
    if (!root) return;
    root.dataset.layout = snapshot.layout;
    root.dataset.theme = snapshot.resolvedTheme;
    root.style.colorScheme = snapshot.resolvedTheme;
    // This also covers the interval before the stylesheet has loaded.
    const background = snapshot.resolvedTheme === "dark" ? "#181a1b" : snapshot.layout === "editorial" ? "#f8f7f4" : "#f5f6f2";
    root.style.backgroundColor = background;
    environment?.document.querySelector('meta[name="theme-color"]')?.setAttribute("content", background);
  }
  function update(next: AppearancePreference, persist: boolean) {
    const resolvedTheme = resolve(next.theme);
    if (persist) {
      try { environment?.localStorage.setItem(APPEARANCE_STORAGE_KEY, JSON.stringify({layout: next.layout, theme: next.theme})); } catch { /* Keep in-memory selection. */ }
    }
    if (next.layout === snapshot.layout && next.theme === snapshot.theme && resolvedTheme === snapshot.resolvedTheme) return;
    const layoutChanged = next.layout !== snapshot.layout;
    const anchor = layoutChanged ? captureLayoutAnchor(environment) : undefined;
    if (layoutChanged) {cancelAnchorRestore?.(); cancelAnchorRestore = undefined;}
    snapshot = {...next, resolvedTheme};
    applyDocument();
    listeners.forEach(listener => listener());
    if (anchor && environment?.requestAnimationFrame) cancelAnchorRestore = scheduleAnchorRestore(environment, anchor);
  }
  function systemChanged() { update(snapshot, false); }
  function storageChanged(event: StorageEvent) {
    if (event.key !== APPEARANCE_STORAGE_KEY && event.key !== null) return;
    // Ignore sessionStorage events that happen to use the same key.
    try { if (event.storageArea && event.storageArea !== environment?.localStorage) return; } catch { return; }
    update(parsePreference(event.newValue), false);
  }
  function initialize() {
    if (initialized) return;
    initialized = true;
    applyDocument();
    environment?.addEventListener("storage", storageChanged);
    if (media?.addEventListener) media.addEventListener("change", systemChanged);
    else media?.addListener?.(systemChanged);
  }
  return {
    initialize,
    getSnapshot: () => snapshot,
    subscribe: (listener: () => void) => { initialize(); listeners.add(listener); return () => { listeners.delete(listener); }; },
    setLayout: (layout: AppearanceLayout) => update({...snapshot, layout}, true),
    setTheme: (theme: AppearanceTheme) => update({...snapshot, theme}, true),
    destroy: () => {
      cancelAnchorRestore?.(); cancelAnchorRestore = undefined;
      environment?.removeEventListener("storage", storageChanged);
      if (media?.removeEventListener) media.removeEventListener("change", systemChanged);
      else media?.removeListener?.(systemChanged);
      listeners.clear();
      initialized = false;
    },
  };
}

const appearanceStore = createAppearanceStore(typeof window === "undefined" ? undefined : window);
export const initializeAppearance = appearanceStore.initialize;

export function useAppearance() {
  const snapshot = useSyncExternalStore(appearanceStore.subscribe, appearanceStore.getSnapshot, appearanceStore.getSnapshot);
  useEffect(appearanceStore.initialize, []);
  return {...snapshot, setLayout: appearanceStore.setLayout, setTheme: appearanceStore.setTheme};
}
