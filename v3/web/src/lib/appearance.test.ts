import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";
import css from "../appearance.css?raw";
import html from "../../index.html?raw";
import {APPEARANCE_STORAGE_KEY, createAppearanceStore} from "./appearance";

describe("appearance preferences", () => {
  let dark = false;
  const mediaListeners = new Set<() => void>();
  const stores: ReturnType<typeof createAppearanceStore>[] = [];
  function store() { const value = createAppearanceStore(window); stores.push(value); value.initialize(); return value; }
  function systemDark(value: boolean) { dark = value; mediaListeners.forEach(listener => listener()); }
  beforeEach(() => {
    localStorage.clear(); dark = false; mediaListeners.clear();
    vi.stubGlobal("matchMedia", () => ({get matches() {return dark;}, addEventListener: (_: string, listener: () => void) => mediaListeners.add(listener), removeEventListener: (_: string, listener: () => void) => mediaListeners.delete(listener)}));
  });
  afterEach(() => { stores.splice(0).forEach(value => value.destroy()); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("defaults to unified/light even when the system prefers dark", () => {
    dark = true;
    expect(store().getSnapshot()).toEqual({layout: "unified", theme: "light", resolvedTheme: "light"});
    expect(document.documentElement.dataset).toMatchObject({layout: "unified", theme: "light"});
  });
  it("restores both preferences, without touching workspace drafts", () => {
    localStorage.setItem("anima-workspace-draft:test", "unsubmitted changes");
    const first = store(); first.setTheme("dark"); first.destroy();
    expect(JSON.parse(localStorage.getItem(APPEARANCE_STORAGE_KEY)!)).toEqual({layout: "unified", theme: "dark"});
    expect(store().getSnapshot()).toEqual({layout: "unified", theme: "dark", resolvedTheme: "dark"});
    expect(localStorage.getItem("anima-workspace-draft:test")).toBe("unsubmitted changes");
  });
  it("follows system brightness without changing explicit theme", () => {
    const value = store(); value.setTheme("system");
    systemDark(true);
    expect(value.getSnapshot()).toEqual({layout: "unified", theme: "system", resolvedTheme: "dark"});
    systemDark(false);
    expect(value.getSnapshot().resolvedTheme).toBe("light");
    value.setTheme("light"); systemDark(true);
    expect(value.getSnapshot().resolvedTheme).toBe("light");
  });
  it("synchronizes another tab without echoing writes", () => {
    const value = store(); const write = vi.spyOn(Storage.prototype, "setItem");
    window.dispatchEvent(new StorageEvent("storage", {key: APPEARANCE_STORAGE_KEY, newValue: '{"layout":"editorial","theme":"dark"}', storageArea: localStorage}));
    expect(value.getSnapshot()).toEqual({layout: "unified", theme: "dark", resolvedTheme: "dark"});
    expect(write).not.toHaveBeenCalled();
    window.dispatchEvent(new StorageEvent("storage", {key: "draft", newValue: "other"}));
    expect(value.getSnapshot().theme).toBe("dark");
    window.dispatchEvent(new StorageEvent("storage", {key: null}));
    expect(value.getSnapshot().theme).toBe("light");
  });
  it.each(['{"layout":"missing","theme":"neon"}', "broken", "null"])("recovers invalid stored data: %s", raw => {
    localStorage.setItem(APPEARANCE_STORAGE_KEY, raw);
    expect(store().getSnapshot()).toEqual({layout: "unified", theme: "light", resolvedTheme: "light"});
  });
  it("still changes in memory when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {throw new Error("blocked");});
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {throw new Error("full");});
    const value = store(); value.setTheme("dark");
    expect(value.getSnapshot()).toEqual({layout: "unified", theme: "dark", resolvedTheme: "dark"});
  });
  it("keeps a stable snapshot and emits only meaningful changes", () => {
    const value = store(); const listener = vi.fn(); const unsubscribe = value.subscribe(listener);
    const initial = value.getSnapshot(); value.setTheme("light"); systemDark(true);
    expect(value.getSnapshot()).toBe(initial); expect(listener).not.toHaveBeenCalled();
    value.setTheme("dark"); expect(listener).toHaveBeenCalledOnce();
    unsubscribe(); value.setTheme("light"); expect(listener).toHaveBeenCalledOnce();
  });
  it("applies saved dark appearance before the React entry script", () => {
    const script = html.match(/<script>([\s\S]*?)<\/script>/)![1];
    expect(html.indexOf(script)).toBeLessThan(html.indexOf('src="/src/main.tsx"'));
    localStorage.setItem(APPEARANCE_STORAGE_KEY, '{"layout":"editorial","theme":"dark"}');
    document.head.innerHTML = '<meta name="theme-color" content="">';
    new Function(script)();
    expect(document.documentElement.dataset).toMatchObject({layout: "unified", theme: "dark"});
    expect(document.documentElement.style.colorScheme).toBe("dark");
    expect(document.documentElement.style.backgroundColor).toBe("rgb(24, 26, 27)");
  });
});

describe("theme contrast", () => {
  function palette(layout: string, theme: string) {
    const values: Record<string, string> = {};
    for (const [selector, body] of [...css.matchAll(/(:root[^{}]*)\{([^{}]*)\}/g)].map(match => [match[1], match[2]])) {
      if (selector.includes('data-layout="editorial"') && layout !== "editorial") continue;
      if (selector.includes('data-theme="dark"') && theme !== "dark") continue;
      for (const match of body.matchAll(/(--[\w-]+):\s*(#[\da-f]{6});/g)) values[match[1]] = match[2];
    }
    return values;
  }
  function ratio(a: string, b: string) {
    const luminance = (hex: string) => {
      const channels = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
      return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
    };
    const x = luminance(a), y = luminance(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05);
  }
  it.each([['unified', 'light'], ['unified', 'dark']])("keeps text, controls and focus readable: %s %s", (layout, theme) => {
    const colors = palette(layout, theme);
    for (const foreground of ['--text', '--soft', '--muted', '--placeholder', '--accent', '--danger', '--amber', '--green']) {
      for (const background of ['--bg', '--panel', '--panel-raised']) expect(ratio(colors[foreground], colors[background]), `${foreground} on ${background}`).toBeGreaterThanOrEqual(4.5);
    }
    expect(ratio(colors['--on-accent'], colors['--accent'])).toBeGreaterThanOrEqual(4.5);
    expect(ratio(colors['--line-bright'], colors['--input-bg'])).toBeGreaterThanOrEqual(3);
    expect(ratio(colors['--focus'], colors['--panel-raised'])).toBeGreaterThanOrEqual(3);
  });
});
