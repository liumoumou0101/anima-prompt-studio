import {afterEach, expect, it, vi} from "vitest";
import {APPEARANCE_STORAGE_KEY, createAppearanceStore} from "./appearance";

afterEach(() => {localStorage.clear(); vi.restoreAllMocks();});
it.each(["studio", "editorial"])("migrates %s to one layout without losing dark theme or draft", layout => {
  localStorage.setItem(APPEARANCE_STORAGE_KEY, JSON.stringify({layout, theme: "dark"}));
  localStorage.setItem("anima-conversation-draft:preserve", "draft content");
  const store = createAppearanceStore(window);
  store.initialize();
  expect(store.getSnapshot()).toMatchObject({layout: "unified", theme: "dark", resolvedTheme: "dark"});
  expect(document.documentElement.dataset.layout).toBe("unified");
  expect(localStorage.getItem("anima-conversation-draft:preserve")).toBe("draft content");
  store.destroy();
});
