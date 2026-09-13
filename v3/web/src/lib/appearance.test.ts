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

  it("defaults to studio/light even when the system prefers dark", () => {
    dark = true;
    expect(store().getSnapshot()).toEqual({layout: "studio", theme: "light", resolvedTheme: "light"});
    expect(document.documentElement.dataset).toMatchObject({layout: "studio", theme: "light"});
  });
  it("restores both preferences, without touching workspace drafts", () => {
    localStorage.setItem("anima-workspace-draft:test", "unsubmitted changes");
    const first = store(); first.setLayout("editorial"); first.setTheme("dark"); first.destroy();
    expect(JSON.parse(localStorage.getItem(APPEARANCE_STORAGE_KEY)!)).toEqual({layout: "editorial", theme: "dark"});
    expect(store().getSnapshot()).toEqual({layout: "editorial", theme: "dark", resolvedTheme: "dark"});
    expect(localStorage.getItem("anima-workspace-draft:test")).toBe("unsubmitted changes");
  });
  it("follows system brightness without changing layout or explicit theme", () => {
    const value = store(); value.setLayout("editorial"); value.setTheme("system");
    systemDark(true);
    expect(value.getSnapshot()).toEqual({layout: "editorial", theme: "system", resolvedTheme: "dark"});
    systemDark(false);
    expect(value.getSnapshot().resolvedTheme).toBe("light");
    value.setTheme("light"); systemDark(true);
    expect(value.getSnapshot().resolvedTheme).toBe("light");
  });
  it("synchronizes another tab without echoing writes", () => {
    const value = store(); const write = vi.spyOn(Storage.prototype, "setItem");
    window.dispatchEvent(new StorageEvent("storage", {key: APPEARANCE_STORAGE_KEY, newValue: '{"layout":"editorial","theme":"dark"}', storageArea: localStorage}));
    expect(value.getSnapshot()).toEqual({layout: "editorial", theme: "dark", resolvedTheme: "dark"});
    expect(write).not.toHaveBeenCalled();
    window.dispatchEvent(new StorageEvent("storage", {key: "draft", newValue: "other"}));
    expect(value.getSnapshot().theme).toBe("dark");
    window.dispatchEvent(new StorageEvent("storage", {key: null}));
    expect(value.getSnapshot().theme).toBe("light");
  });
  it.each(['{"layout":"missing","theme":"neon"}', "broken", "null"])("recovers invalid stored data: %s", raw => {
    localStorage.setItem(APPEARANCE_STORAGE_KEY, raw);
    expect(store().getSnapshot()).toEqual({layout: "studio", theme: "light", resolvedTheme: "light"});
  });
  it("still changes in memory when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {throw new Error("blocked");});
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {throw new Error("full");});
    const value = store(); value.setTheme("dark"); value.setLayout("editorial");
    expect(value.getSnapshot()).toEqual({layout: "editorial", theme: "dark", resolvedTheme: "dark"});
  });
  it("keeps a stable snapshot and emits only meaningful changes", () => {
    const value = store(); const listener = vi.fn(); const unsubscribe = value.subscribe(listener);
    const initial = value.getSnapshot(); value.setTheme("light"); systemDark(true);
    expect(value.getSnapshot()).toBe(initial); expect(listener).not.toHaveBeenCalled();
    value.setTheme("dark"); expect(listener).toHaveBeenCalledOnce();
    unsubscribe(); value.setLayout("editorial"); expect(listener).toHaveBeenCalledOnce();
  });
  it("applies saved dark appearance before the React entry script", () => {
    const script = html.match(/<script>([\s\S]*?)<\/script>/)![1];
    expect(html.indexOf(script)).toBeLessThan(html.indexOf('src="/src/main.tsx"'));
    localStorage.setItem(APPEARANCE_STORAGE_KEY, '{"layout":"editorial","theme":"dark"}');
    document.head.innerHTML = '<meta name="theme-color" content="">';
    new Function(script)();
    expect(document.documentElement.dataset).toMatchObject({layout: "editorial", theme: "dark"});
    expect(document.documentElement.style.colorScheme).toBe("dark");
    expect(document.documentElement.style.backgroundColor).toBe("rgb(24, 26, 27)");
  });
});

describe("layout reading position", () => {
  let value: ReturnType<typeof createAppearanceStore>;
  let frames: Map<number, FrameRequestCallback>;
  function geometry(element: Element, top: number, height = 80, left = 240, width = 400) {
    vi.spyOn(element, "getBoundingClientRect").mockReturnValue({top, bottom: top + height, left, right: left + width, width, height, x: left, y: top, toJSON: () => ({})});
  }
  function finishFrame() {
    for (const [id, callback] of [...frames]) {frames.delete(id); callback(0);}
  }
  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = '<aside class="sidebar"><select aria-label="界面布局"><option>工作室</option></select></aside><main><section data-appearance-anchor="editor"><textarea>已写的提示词</textarea><input value="猫"></section></main>';
    frames = new Map(); let frameId = 0;
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback: FrameRequestCallback) => {const id = ++frameId; frames.set(id, callback); return id;}));
    vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
    vi.stubGlobal("scrollY", 500); vi.stubGlobal("innerHeight", 800); vi.stubGlobal("innerWidth", 1280);
    vi.spyOn(window, "scrollBy").mockImplementation(() => {});
    value = createAppearanceStore(window); value.initialize();
    geometry(document.querySelector("section")!, -150, 1200);
    geometry(document.querySelector("textarea")!, 120, 200);
    geometry(document.querySelector("input")!, 400, 40);
  });
  afterEach(() => {value.destroy(); document.body.innerHTML = ""; vi.unstubAllGlobals(); vi.restoreAllMocks();});

  it("keeps a visible control near its previous position while leaving focus on the layout selector", () => {
    const selector = document.querySelector("select")!; selector.focus();
    const text = document.querySelector("textarea")!;
    value.setLayout("editorial");
    expect(window.scrollBy).not.toHaveBeenCalled();
    geometry(text, 470, 240);
    finishFrame();
    expect(window.scrollBy).toHaveBeenCalledExactlyOnceWith({top: 350, left: 0, behavior: "instant"});
    expect(document.activeElement).toBe(selector);
    expect(document.querySelector("textarea")).toBe(text);
    expect(text.value).toBe("已写的提示词");
  });

  it.each([410, -80])("prioritizes the existing focused editor at top %s and keeps its text selection", top => {
    const text = document.querySelector("textarea")!;
    geometry(text, top, 180); text.focus(); text.setSelectionRange(1, 4);
    value.setLayout("editorial"); geometry(text, top + 280, 240);
    finishFrame();
    expect(window.scrollBy).toHaveBeenCalledExactlyOnceWith({top: 280, left: 0, behavior: "instant"});
    expect(document.activeElement).toBe(text);
    expect([text.selectionStart, text.selectionEnd]).toEqual([1, 4]);
  });

  it("keeps an anchored region clear of the new sticky navigation", () => {
    document.querySelector("textarea")!.remove(); document.querySelector("input")!.remove();
    const section = document.querySelector("section")!;
    geometry(section, 30, 500);
    value.setLayout("editorial"); geometry(section, 210, 500);
    const navigation = document.querySelector<HTMLElement>(".sidebar")!;
    navigation.style.position = "sticky"; geometry(navigation, 0, 74, 0, 1280);
    finishFrame();
    expect(window.scrollBy).toHaveBeenCalledExactlyOnceWith({top: 120, left: 0, behavior: "instant"});
  });

  it.each(["theme only", "page top", "unmarked page"])("does not adjust scrolling for %s", situation => {
    if (situation === "page top") vi.stubGlobal("scrollY", 0);
    if (situation === "unmarked page") document.querySelector("section")!.removeAttribute("data-appearance-anchor");
    if (situation === "theme only") value.setTheme("dark"); else value.setLayout("editorial");
    finishFrame();
    expect(window.requestAnimationFrame).not.toHaveBeenCalled();
    expect(window.scrollBy).not.toHaveBeenCalled();
  });

  it.each(["navigation", "user scroll", "destroy"])("drops a queued adjustment after %s", action => {
    const text = document.querySelector("textarea")!;
    value.setLayout("editorial"); geometry(text, 470, 240);
    if (action === "navigation") document.querySelector("main")!.innerHTML = "<h1>参考案例</h1>";
    else if (action === "user scroll") window.dispatchEvent(new Event("wheel"));
    else value.destroy();
    finishFrame();
    expect(window.scrollBy).not.toHaveBeenCalled();
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
  it.each([['studio', 'light'], ['studio', 'dark'], ['editorial', 'light'], ['editorial', 'dark']])("keeps text, controls and focus readable: %s %s", (layout, theme) => {
    const colors = palette(layout, theme);
    for (const foreground of ['--text', '--soft', '--muted', '--placeholder', '--accent', '--danger', '--amber', '--green']) {
      for (const background of ['--bg', '--panel', '--panel-raised']) expect(ratio(colors[foreground], colors[background]), `${foreground} on ${background}`).toBeGreaterThanOrEqual(4.5);
    }
    expect(ratio(colors['--on-accent'], colors['--accent'])).toBeGreaterThanOrEqual(4.5);
    expect(ratio(colors['--line-bright'], colors['--input-bg'])).toBeGreaterThanOrEqual(3);
    expect(ratio(colors['--focus'], colors['--panel-raised'])).toBeGreaterThanOrEqual(3);
  });
});
