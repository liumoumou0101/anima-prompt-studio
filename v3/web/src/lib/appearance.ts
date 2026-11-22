import {useEffect, useSyncExternalStore} from "react";

export type AppearanceLayout = "unified";
export type AppearanceTheme = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";
export interface AppearancePreference {layout: AppearanceLayout; theme: AppearanceTheme}
export interface AppearanceSnapshot extends AppearancePreference {resolvedTheme: ResolvedTheme}
export const APPEARANCE_STORAGE_KEY = "anima-appearance-v1";

function parsePreference(raw: string | null): AppearancePreference {
  try {
    const value = JSON.parse(raw || "null");
    return {
      layout: "unified",
      theme: value?.theme === "dark" || value?.theme === "system" ? value.theme : "light",
    };
  } catch { return {layout: "unified", theme: "light"}; }
}

/** Display preferences never depend on workspaces, API sessions or generation state. */
export function createAppearanceStore(environment: Window | undefined) {
  const listeners = new Set<() => void>();
  let media: MediaQueryList | undefined;
  let initialized = false;
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
    const background = snapshot.resolvedTheme === "dark" ? "#181a1b" : "#f5f6f2";
    root.style.backgroundColor = background;
    environment?.document.querySelector('meta[name="theme-color"]')?.setAttribute("content", background);
  }
  function update(next: AppearancePreference, persist: boolean) {
    const resolvedTheme = resolve(next.theme);
    if (persist) {
      try { environment?.localStorage.setItem(APPEARANCE_STORAGE_KEY, JSON.stringify({layout: next.layout, theme: next.theme})); } catch { /* Keep in-memory selection. */ }
    }
    if (next.layout === snapshot.layout && next.theme === snapshot.theme && resolvedTheme === snapshot.resolvedTheme) return;
    snapshot = {...next, resolvedTheme};
    applyDocument();
    listeners.forEach(listener => listener());
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
    setTheme: (theme: AppearanceTheme) => update({...snapshot, theme}, true),
    destroy: () => {
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
  return {...snapshot, setTheme: appearanceStore.setTheme};
}
