import {describe, expect, it, vi} from "vitest";
import {defaultGenerationSettings} from "./generationSettings";
import {emptyRequirements, type LocalConversation} from "./conversation";
import {conversationDraftKey, getConversationPendingKey, getConversationTabId,
  cleanupConversationDrafts, initializeConversationTab, listConversationDraftCandidates, preserveConversationDraft,
  readConversationDraft, readConversationDraftCandidate, saveConversationDraft, type ConversationDraftStorage} from "./conversationDrafts";

class MemoryStorage implements Storage {
  readonly values = new Map<string, string>();
  get length() { return this.values.size; }
  clear() { this.values.clear(); }
  getItem(key: string) { return this.values.get(key) ?? null; }
  key(index: number) { return [...this.values.keys()][index] ?? null; }
  removeItem(key: string) { this.values.delete(key); }
  setItem(key: string, value: string) { this.values.set(key, value); }
}

function draft(revision = 3): LocalConversation {
  return {baseRevision: revision, delta: "", mode: "faithful", requirements: emptyRequirements(), positive: "blue coat", negative: "",
    model: "anima_base_v1", settings: defaultGenerationSettings()};
}

function environment(localStorage = new MemoryStorage(), sessionStorage = new MemoryStorage(), id = "tab-a"): ConversationDraftStorage {
  return {localStorage, sessionStorage, createTabId: () => id, now: () => 123};
}

describe("conversation draft persistence", () => {
  it("stores a versioned local/base envelope under a tab-scoped key", () => {
    const storage = environment();
    const base = draft(); const local = structuredClone(base); local.delta = "未发送";
    expect(saveConversationDraft("workspace_test", local, base, storage)).toEqual({ok: true, warning: ""});
    expect(storage.localStorage.getItem(conversationDraftKey("workspace_test", "tab-a"))).toContain('"version":1');
    expect(readConversationDraft("workspace_test", storage)).toEqual({local, base, warning: ""});
  });

  it("accepts nullable scene defaults and empty identity arrays emitted by the API", () => {
    const storage = environment();
    const local = draft();
    local.requirements.layers.subject.character_tags = [];
    local.requirements.layers.subject.series_tags = [];
    local.requirements.layers.subject.general_tags = [];
    local.requirements.layers.style.manual_artist_tags = [];
    local.requirements.layers.lighting.mood = null;
    local.requirements.layers.composition.design = null;
    expect(saveConversationDraft("workspace_test", local, structuredClone(local), storage).ok).toBe(true);
    expect(readConversationDraft("workspace_test", storage)).toEqual({local, base: local, warning: ""});
  });

  it.each([
    {locks: [{target: "positive", text: "blue coat"}], accepted: true},
    {locks: [{target: "negative", text: "blurry"}], accepted: true},
    {locks: [], accepted: true},
    {locks: [{target: "unknown", text: "blue coat"}], accepted: false},
    {locks: [{target: "positive", text: "  "}], accepted: false},
    {locks: [{target: "positive", text: 42}], accepted: false},
    {locks: null, accepted: false},
  ])("validates persisted prompt protection entries: $locks", ({locks, accepted}) => {
    const storage = environment();
    const local = draft();
    Object.assign(local.requirements, {prompt_locks: locks});
    saveConversationDraft("workspace_test", local, draft(), storage);
    const recovered = readConversationDraft("workspace_test", storage);
    if (accepted) expect(recovered?.local).toEqual(local);
    else expect(recovered?.invalidRaw).toContain('"prompt_locks"');
  });

  it("returns a visible failure result when quota or storage policy rejects a write", () => {
    const localStorage = new MemoryStorage();
    localStorage.setItem = () => { throw new DOMException("quota", "QuotaExceededError"); };
    const result = saveConversationDraft("workspace_test", draft(), draft(), environment(localStorage));
    expect(result.ok).toBe(false);
    expect(result.warning).toMatch(/无法保留|存储/);
  });

  it("degrades draft recovery and persistence when browser policy denies the storage getters", async () => {
    const blocked = () => { throw new DOMException("blocked", "SecurityError"); };
    const localGetter = vi.spyOn(window, "localStorage", "get").mockImplementation(blocked);
    const sessionGetter = vi.spyOn(window, "sessionStorage", "get").mockImplementation(blocked);
    try {
      expect(readConversationDraft("workspace_blocked")).toMatchObject({local: null, base: null,
        warning: expect.stringMatching(/读取|存储/), persistenceBlocked: true});
      const result = saveConversationDraft("workspace_blocked", draft(), draft());
      expect(result.ok).toBe(false);
      expect(result.warning).toMatch(/无法保留|存储/);
      await expect(initializeConversationTab()).resolves.toEqual(expect.any(String));
    } finally {
      localGetter.mockRestore(); sessionGetter.mockRestore();
    }
  });

  it("migrates a valid legacy bare draft without inventing a merge base", () => {
    const storage = environment();
    storage.localStorage.setItem("anima-conversation-draft:workspace_test", JSON.stringify(draft()));
    const recovered = readConversationDraft("workspace_test", storage);
    expect(recovered?.local).toEqual(draft());
    expect(recovered?.base).toBeNull();
    expect(recovered?.warning).toMatch(/旧版|基准/);
  });

  it("persists edits to a recovered legacy draft without inventing its unknown base", () => {
    const storage = environment();
    const legacy = draft(); legacy.delta = "旧版未发送内容";
    storage.localStorage.setItem("anima-conversation-draft:workspace_test", JSON.stringify(legacy));
    const recovered = readConversationDraft("workspace_test", storage)!;
    expect(recovered.local).not.toBeNull();
    const local = recovered.local!; local.positive = "edited after recovery";
    expect(saveConversationDraft("workspace_test", local, recovered.base, storage)).toEqual({ok: true, warning: ""});
    expect(readConversationDraft("workspace_test", storage)).toEqual({local, base: null,
      warning: "缺少可靠的合并基准；保存到服务端前请逐项核对版本。"});
  });

  it("rejects parseable malformed legacy drafts safely", () => {
    const storage = environment();
    storage.localStorage.setItem("anima-conversation-draft:workspace_test", JSON.stringify({baseRevision: 3, positive: "partial"}));
    expect(readConversationDraft("workspace_test", storage)).toBeNull();
  });

  it("backs up an incompatible current envelope and returns its raw text for export", () => {
    const storage = environment();
    const raw = JSON.stringify({version: 1, workspaceId: "workspace_test", tabId: "tab-a", savedAt: 100,
      local: {baseRevision: 3, positive: "recover me"}, base: null});
    storage.localStorage.setItem(conversationDraftKey("workspace_test", "tab-a"), raw);
    const result = readConversationDraft("workspace_test", storage);
    const backupKey = result?.invalidBackupKey!;
    expect(backupKey).toMatch(/^anima-conversation-draft-invalid:v1:workspace_test:123:/);
    expect(result).toEqual({local: null, base: null, warning: "旧草稿结构不兼容，已保留原始副本；请先导出并核对后再继续。",
      invalidRaw: raw, invalidBackupKey: backupKey});
    expect(storage.localStorage.getItem(backupKey)).toBe(raw);
    expect(storage.localStorage.getItem(conversationDraftKey("workspace_test", "tab-a"))).toBe(raw);
  });

  it("blocks automatic persistence when an incompatible envelope cannot be backed up", () => {
    const localStorage = new MemoryStorage();
    const storage = environment(localStorage);
    const raw = "{not-json";
    localStorage.setItem(conversationDraftKey("workspace_test", "tab-a"), raw);
    const originalSet = localStorage.setItem.bind(localStorage);
    localStorage.setItem = (key, value) => {
      if (key.startsWith("anima-conversation-draft-invalid:")) throw new DOMException("quota", "QuotaExceededError");
      originalSet(key, value);
    };
    expect(readConversationDraft("workspace_test", storage)).toEqual({local: null, base: null,
      warning: "旧草稿结构不兼容，且浏览器存储无法保留副本；请立即导出原始草稿，确认后再继续。",
      invalidRaw: raw, persistenceBlocked: true});
    expect(localStorage.getItem(conversationDraftKey("workspace_test", "tab-a"))).toBe(raw);
  });

  it("keeps independent tab slots and offers the newest slot as shared recovery", () => {
    const localStorage = new MemoryStorage();
    const a = environment(localStorage, new MemoryStorage(), "tab-a");
    const b = environment(localStorage, new MemoryStorage(), "tab-b");
    const aLocal = draft(); aLocal.delta = "A";
    saveConversationDraft("workspace_test", aLocal, draft(), a);
    b.now = () => 456;
    const bLocal = draft(); bLocal.delta = "B";
    saveConversationDraft("workspace_test", bLocal, draft(), b);
    expect(readConversationDraft("workspace_test", a)?.local?.delta).toBe("A");
    expect(readConversationDraft("workspace_test", b)?.local?.delta).toBe("B");
    const fresh = environment(localStorage, new MemoryStorage(), "tab-c");
    const recovered = readConversationDraft("workspace_test", fresh);
    expect(recovered?.local?.delta).toBe("B");
    expect(recovered?.warning).toMatch(/其他标签页|恢复/);
  });

  it("keeps a stable tab id for the current browser tab", () => {
    const storage = environment();
    expect(getConversationTabId(storage)).toBe("tab-a");
    storage.createTabId = () => "tab-b";
    expect(getConversationTabId(storage)).toBe("tab-a");
  });

  it("uses separate pending-submission keys for separate tab ids", () => {
    const localStorage = new MemoryStorage();
    const a = environment(localStorage, new MemoryStorage(), "tab-a");
    const b = environment(localStorage, new MemoryStorage(), "tab-b");
    expect(getConversationPendingKey("workspace_test", a)).not.toBe(getConversationPendingKey("workspace_test", b));
    expect(getConversationPendingKey("workspace_test", a)).toContain("tab-a");
  });
});

describe("explicit local draft recovery", () => {
  it("discovers all document slots even when the shared index lost an update, plus legacy and damaged records", () => {
    const storage = environment();
    const other = environment(storage.localStorage as MemoryStorage, new MemoryStorage(), "other-document");
    const local = draft(); local.delta = "unsaved other window";
    saveConversationDraft("workspace_test", draft(), draft(), storage);
    saveConversationDraft("workspace_test", local, null, other);
    saveConversationDraft("workspace_test_extra", draft(), draft(), storage);
    storage.localStorage.removeItem("anima-conversation-draft-recovery:v1:workspace_test");
    storage.localStorage.setItem("anima-conversation-draft:workspace_test", JSON.stringify(draft(2)));
    storage.localStorage.setItem("anima-conversation-draft-invalid:workspace_test:100", "{damaged");
    const result = listConversationDraftCandidates("workspace_test", storage);
    expect(result.warning).toBe("");
    expect(result.candidates).toHaveLength(4);
    expect(result.candidates.find(item => item.tabId === "other-document")).toMatchObject({status: "valid", local, base: null});
    expect(result.candidates.find(item => item.kind === "legacy")).toMatchObject({status: "valid", base: null, savedAt: null});
    expect(result.candidates.find(item => item.status === "invalid")).toMatchObject({raw: "{damaged", local: null});
  });

  it("only reads a requested workspace's candidate and rereads its current value without mutating storage", () => {
    const storage = environment();
    saveConversationDraft("workspace_test", draft(), draft(), storage);
    saveConversationDraft("another_workspace", draft(), draft(), storage);
    const listed = listConversationDraftCandidates("workspace_test", storage).candidates[0];
    const latest = draft(); latest.delta = "changed since listing";
    saveConversationDraft("workspace_test", latest, draft(), storage);
    const before = [...(storage.localStorage as MemoryStorage).values];
    expect(readConversationDraftCandidate("workspace_test", listed.key, storage)?.local).toEqual(latest);
    expect(readConversationDraftCandidate("workspace_test", "anima-conversation-draft:v1:another_workspace:tab-a", storage)).toBeNull();
    expect(readConversationDraftCandidate("workspace_test", "anima-conversation-submission:v1:workspace_test:tab-a", storage)).toBeNull();
    expect([...(storage.localStorage as MemoryStorage).values]).toEqual(before);
  });

  it("rejects envelopes whose workspace or document identity does not match their storage key", () => {
    const storage = environment();
    const key = "anima-conversation-draft:v1:workspace_test:tab-a";
    saveConversationDraft("workspace_test", draft(), draft(), storage);
    const original = JSON.parse(storage.localStorage.getItem(key)!);
    for (const change of [{workspaceId: "another_workspace"}, {tabId: "different-document"}]) {
      storage.localStorage.setItem(key, JSON.stringify({...original, ...change}));
      expect(readConversationDraftCandidate("workspace_test", key, storage)).toMatchObject({status: "invalid", local: null, base: null});
    }
  });

  it("preserves the current local/base in an independent snapshot across replacement and reload", async () => {
    const storage = environment();
    const api = await document(storage, "document-a");
    const original = draft(); original.delta = "current unsaved";
    const saved = api.preserveConversationDraft("workspace_test", original, draft(), storage);
    expect(saved.ok).toBe(true);
    api.saveConversationDraft("workspace_test", draft(4), draft(4), storage);
    const reloaded = await document(storage, "document-b");
    expect(reloaded.readConversationDraftCandidate("workspace_test", saved.key!, storage)).toMatchObject({
      kind: "snapshot", status: "valid", local: original, base: draft(),
    });
    expect(reloaded.listConversationDraftCandidates("workspace_test", storage).candidates.some(item => item.key === saved.key)).toBe(true);
  });

  it("reuses identical immutable snapshots while preserving different merge bases and unknown bases", () => {
    const storage = environment();
    const first = preserveConversationDraft("workspace_test", draft(), draft(), storage);
    storage.now = () => 999;
    const repeat = preserveConversationDraft("workspace_test", draft(), draft(), storage);
    const otherBase = preserveConversationDraft("workspace_test", draft(), draft(2), storage);
    const unknownBase = preserveConversationDraft("workspace_test", draft(), null, storage);
    expect(repeat.key).toBe(first.key);
    expect(otherBase.key).not.toBe(first.key);
    expect(unknownBase.key).not.toBe(first.key);
    expect(listConversationDraftCandidates("workspace_test", storage).candidates).toHaveLength(3);
  });

  it("does not claim preservation succeeded if quota prevents writing the snapshot", () => {
    const storage = environment();
    storage.localStorage.setItem = () => { throw new DOMException("quota", "QuotaExceededError"); };
    expect(preserveConversationDraft("workspace_test", draft(), null, storage)).toMatchObject({ok: false});
  });

  it("cleans duplicate immutable snapshots but retains every writable document, legacy draft and request marker", () => {
    const storage = environment();
    const snapshot = preserveConversationDraft("workspace_test", draft(), draft(), storage);
    const snapshotRaw = storage.localStorage.getItem(snapshot.key!)!;
    storage.localStorage.setItem(`${snapshot.key!}-duplicate`, snapshotRaw);
    saveConversationDraft("workspace_test", draft(), draft(), storage);
    const currentKey = conversationDraftKey("workspace_test", "tab-a");
    const otherKey = conversationDraftKey("workspace_test", "suspended-document");
    storage.localStorage.setItem(otherKey, JSON.stringify({...JSON.parse(storage.localStorage.getItem(currentKey)!), tabId: "suspended-document"}));
    const protectedRecords = {
      "anima-conversation-draft:workspace_test": JSON.stringify(draft()),
      "anima-conversation-draft-invalid:workspace_test:10": "{old damaged backup",
      "anima-conversation-submission:v1:workspace_test:tab-a": JSON.stringify(pending()),
      "anima-conversation-submission-done:v1:workspace_test:completed-request": "1",
      "anima-conversation-branch:v1:workspace_test:draft:tab-a": JSON.stringify({key: "branch", body: "{}"}),
      "anima-conversation-branch-done:v1:workspace_test:draft:branch": "1",
    };
    for (const [key, value] of Object.entries(protectedRecords)) storage.localStorage.setItem(key, value);
    storage.localStorage.setItem(`${snapshot.key!}-duplicate`, snapshotRaw);
    const cleaned = cleanupConversationDrafts("workspace_test", storage);
    expect(cleaned.removed).toBe(1);
    expect(storage.localStorage.getItem(snapshot.key!)).toBe(snapshotRaw);
    expect(storage.localStorage.getItem(currentKey)).not.toBeNull();
    expect(storage.localStorage.getItem(otherKey)).not.toBeNull();
    for (const [key, value] of Object.entries(protectedRecords)) expect(storage.localStorage.getItem(key)).toBe(value);
  });

  it("backs up damaged current bytes before a recovery write replaces them, and makes the backup discoverable", () => {
    const storage = environment();
    const currentKey = conversationDraftKey("workspace_test", "tab-a");
    storage.localStorage.setItem(currentKey, "{unique broken current");
    expect(saveConversationDraft("workspace_test", draft(), draft(), storage).ok).toBe(true);
    const records = listConversationDraftCandidates("workspace_test", storage).candidates;
    expect(records.some(item => item.status === "invalid" && item.raw === "{unique broken current")).toBe(true);
    expect(readConversationDraft("workspace_test", storage)?.local).toEqual(draft());
  });

  it("leaves a damaged source untouched when its raw backup cannot be written", () => {
    const storage = environment();
    const key = conversationDraftKey("workspace_test", "tab-a");
    storage.localStorage.setItem(key, "{irreplaceable raw");
    const write = storage.localStorage.setItem.bind(storage.localStorage);
    storage.localStorage.setItem = (target, value) => { if (target !== key) throw new Error("quota"); write(target, value); };
    expect(saveConversationDraft("workspace_test", draft(), draft(), storage).ok).toBe(false);
    expect(storage.localStorage.getItem(key)).toBe("{irreplaceable raw");
  });

  it("keeps different damaged backups created at the same millisecond and reuses repeated backups", () => {
    const storage = environment();
    const key = conversationDraftKey("workspace_test", "tab-a");
    storage.localStorage.setItem(key, "{first damage");
    const first = readConversationDraft("workspace_test", storage)!;
    storage.localStorage.setItem(key, "{second damage");
    const second = readConversationDraft("workspace_test", storage)!;
    expect(second.invalidBackupKey).not.toBe(first.invalidBackupKey);
    expect(storage.localStorage.getItem(first.invalidBackupKey!)).toBe("{first damage");
    expect(storage.localStorage.getItem(second.invalidBackupKey!)).toBe("{second damage");
    storage.now = () => 999;
    expect(readConversationDraft("workspace_test", storage)?.invalidBackupKey).toBe(second.invalidBackupKey);
  });

  it("returns a warning instead of throwing when browser storage cannot be enumerated", () => {
    const storage = environment();
    storage.localStorage.getItem = () => { throw new DOMException("blocked", "SecurityError"); };
    expect(listConversationDraftCandidates("workspace_test", storage)).toMatchObject({candidates: [], warning: expect.stringMatching(/存储|读取/)});
    expect(cleanupConversationDrafts("workspace_test", storage)).toMatchObject({removed: 0, warning: expect.stringMatching(/存储|读取/)});
  });

  it("keeps unique snapshot content, distinct bases and unknown future fields during cleanup", () => {
    const storage = environment();
    const first = preserveConversationDraft("workspace_test", draft(), draft(), storage);
    const otherBase = preserveConversationDraft("workspace_test", draft(), null, storage);
    const edited = draft(); edited.delta = "unique earlier content";
    storage.now = () => 1;
    const otherContent = preserveConversationDraft("workspace_test", edited, draft(), storage);
    const futureKey = `${first.key!}-future`;
    storage.localStorage.setItem(futureKey, JSON.stringify({...JSON.parse(storage.localStorage.getItem(first.key!)!),
      futureRecoveryData: "must not lose this field"}));
    expect(cleanupConversationDrafts("workspace_test", storage).removed).toBe(0);
    for (const key of [first.key, otherBase.key, otherContent.key, futureKey]) expect(storage.localStorage.getItem(key!)).not.toBeNull();
  });

  it("deduplicates only immutable damaged backups and does not confuse a workspace named v1 with their namespace", () => {
    const storage = environment();
    storage.localStorage.setItem(conversationDraftKey("workspace_test", "tab-a"), "{damaged raw");
    const result = readConversationDraft("workspace_test", storage)!;
    storage.localStorage.setItem(`${result.invalidBackupKey!}-duplicate`, "{damaged raw");
    storage.localStorage.setItem("anima-conversation-draft-invalid:v1:123", "old backup in workspace v1");
    storage.localStorage.setItem("anima-conversation-draft-invalid:workspace_test:123", "{damaged raw");
    expect(cleanupConversationDrafts("workspace_test", storage).removed).toBe(1);
    expect(storage.localStorage.getItem("anima-conversation-draft-invalid:workspace_test:123")).toBe("{damaged raw");
    expect(listConversationDraftCandidates("v1", storage).candidates).toMatchObject([{raw: "old backup in workspace v1"}]);
  });

  it("persists frequent edits without rescanning all browser storage for every keystroke", () => {
    const storage = environment();
    const enumerate = vi.spyOn(storage.localStorage as MemoryStorage, "key");
    saveConversationDraft("workspace_test", draft(), draft(), storage);
    const initialScans = enumerate.mock.calls.length;
    expect(initialScans).toBeGreaterThan(0);
    for (let edit = 0; edit < 20; edit++) {
      const local = draft(); local.delta = `edit ${edit}`;
      expect(saveConversationDraft("workspace_test", local, draft(), storage).ok).toBe(true);
    }
    expect(enumerate.mock.calls).toHaveLength(initialScans);
    expect(readConversationDraft("workspace_test", storage)?.local?.delta).toBe("edit 19");
  });

  it("blocks persistence after a transient draft read failure instead of treating an unread slot as empty", () => {
    const storage = environment();
    const local = draft(); local.delta = "unique unread edit";
    saveConversationDraft("workspace_test", local, draft(), storage);
    const key = conversationDraftKey("workspace_test", "tab-a");
    const originalRaw = storage.localStorage.getItem(key);
    const read = storage.localStorage.getItem.bind(storage.localStorage);
    let failed = false;
    storage.localStorage.getItem = target => {
      if (!failed && target === key) { failed = true; throw new Error("temporary storage failure"); }
      return read(target);
    };
    const result = readConversationDraft("workspace_test", storage);
    expect(result).toMatchObject({local: null, base: null, persistenceBlocked: true, warning: expect.stringMatching(/读取|存储/)});
    expect(storage.localStorage.getItem(key)).toBe(originalRaw);
    expect(readConversationDraft("workspace_test", storage)?.local).toEqual(local);
  });
});

const CONTEXT_KEY = "anima-conversation-document:v1";
async function document(storage: ConversationDraftStorage, id: string) {
  vi.resetModules();
  const api = await import("./conversationDrafts");
  await api.initializeConversationTab(storage, {createDocumentId: () => id});
  return api;
}
function duplicate(storage: ConversationDraftStorage): ConversationDraftStorage {
  const sessionStorage = new MemoryStorage();
  for (const key of ["anima-conversation-tab-id", CONTEXT_KEY]) {
    const raw = storage.sessionStorage.getItem(key);
    if (raw !== null) sessionStorage.setItem(key, raw);
  }
  return {...storage, sessionStorage};
}
function pending(workspace = "workspace_test", key = "request-original") {
  return {key, body: JSON.stringify({workspace_id: workspace, submission_kind: "conversational", positive_prompt: "blue coat"})};
}

describe("document-owned draft and pending recovery", () => {
  it.each(["missing", "constructor error", "post error"])("isolates duplicated draft writes when BroadcastChannel is %s", async failure => {
    const previous = globalThis.BroadcastChannel;
    vi.stubGlobal("BroadcastChannel", failure === "missing" ? undefined : class {
      constructor() { if (failure === "constructor error") throw new Error("blocked"); }
      postMessage() { throw new Error("transport failed"); }
    });
    try {
      const originalStorage = environment();
      originalStorage.sessionStorage.setItem("anima-conversation-tab-id", "inherited-id");
      const cloneStorage = duplicate(originalStorage);
      const original = await document(originalStorage, "document-a");
      const clone = await document(cloneStorage, "document-b");
      const a = draft(); a.delta = "original";
      const b = draft(); b.delta = "clone";
      original.saveConversationDraft("workspace_test", a, draft(), originalStorage);
      clone.saveConversationDraft("workspace_test", b, draft(), cloneStorage);
      expect(original.readConversationDraft("workspace_test", originalStorage)?.local?.delta).toBe("original");
      expect(clone.readConversationDraft("workspace_test", cloneStorage)?.local?.delta).toBe("clone");
    } finally { vi.stubGlobal("BroadcastChannel", previous); }
  });

  it("recovers its own latest draft through repeated reloads instead of another document's newer draft", async () => {
    const storage = environment();
    const first = await document(storage, "document-a");
    const own = draft(); own.delta = "my edit";
    first.saveConversationDraft("workspace_test", own, draft(), storage);
    const cloneStorage = duplicate(storage);
    cloneStorage.now = () => 900;
    const clone = await document(cloneStorage, "document-b");
    const other = draft(); other.delta = "other edit";
    clone.saveConversationDraft("workspace_test", other, draft(), cloneStorage);
    await document(storage, "document-reload-1");
    const reloaded = await document(storage, "document-reload-2");
    expect(reloaded.readConversationDraft("workspace_test", storage)).toEqual({local: own, base: draft(), warning: ""});
    expect(first.getConversationTabId(storage)).not.toBe(reloaded.getConversationTabId(storage));
    expect(first.getConversationTabId(storage)).not.toBe(clone.getConversationTabId(cloneStorage));
  });

  it("keeps a cached document's slot independent while a cloned page initializes and writes", async () => {
    const storage = environment();
    const cached = await document(storage, "cached-document");
    const cachedId = cached.getConversationTabId(storage);
    const cloneStorage = duplicate(storage);
    const clone = await document(cloneStorage, "clone-document");
    const restored = draft(); restored.delta = "after bfcache restore";
    cached.saveConversationDraft("workspace_test", restored, draft(), storage);
    clone.saveConversationDraft("workspace_test", draft(), draft(), cloneStorage);
    expect(cached.getConversationTabId(storage)).toBe(cachedId);
    expect(cached.readConversationDraft("workspace_test", storage)?.local?.delta).toBe("after bfcache restore");
  });

  it("restores the cached document's recovery context before a subsequent reload", async () => {
    const storage = environment();
    vi.resetModules();
    const cached = await import("./conversationDrafts");
    let restore = (_event: {persisted: boolean}) => {};
    await cached.initializeConversationTab(storage, {createDocumentId: () => "cached-document",
      lifecycle: {addEventListener(_type, listener) { restore = listener; }}});
    const first = draft(); first.delta = "cached edit";
    cached.saveConversationDraft("workspace_test", first, draft(), storage);
    // Navigating within one browser tab shares sessionStorage, unlike Duplicate Tab.
    const next = await document(storage, "next-document");
    const second = draft(); second.delta = "later document edit";
    next.saveConversationDraft("workspace_test", second, draft(), storage);
    next.saveConversationPending("workspace_test", pending(), storage);
    restore({persisted: true});
    const reloaded = await document(storage, "reload-after-back");
    expect(reloaded.readConversationDraft("workspace_test", storage)?.local?.delta).toBe("cached edit");
    expect(reloaded.recoverConversationPending("workspace_test", storage)).toEqual(pending());
  });

  it("isolates concurrent initialization of cloned sessions and initializes one document only once", async () => {
    const a = environment();
    a.sessionStorage.setItem("anima-conversation-tab-id", "inherited");
    const b = duplicate(a);
    vi.resetModules();
    const api = await import("./conversationDrafts");
    const [first, second, repeated] = await Promise.all([
      api.initializeConversationTab(a, {createDocumentId: () => "doc-a"}),
      api.initializeConversationTab(b, {createDocumentId: () => "doc-b"}),
      api.initializeConversationTab(a, {createDocumentId: () => "unused"}),
    ]);
    expect(first).not.toBe(second);
    expect(repeated).toBe(first);
  });

  it("recovers a pre-upgrade slot and pending request without changing its idempotency key or body", async () => {
    const storage = environment();
    const old = draft(); old.delta = "before upgrade";
    saveConversationDraft("workspace_test", old, draft(), storage);
    storage.localStorage.setItem(getConversationPendingKey("workspace_test", storage), JSON.stringify(pending()));
    const api = await document(storage, "upgraded-document");
    expect(api.readConversationDraft("workspace_test", storage)?.local).toEqual(old);
    expect(api.recoverConversationPending("workspace_test", storage)).toEqual(pending());
    expect(JSON.parse(storage.localStorage.getItem(api.getConversationPendingKey("workspace_test", storage))!)).toEqual(pending());
    expect(api.recoverConversationPending("another_workspace", storage)).toBeNull();
  });

  it("migrates legacy pending requests and blocks malformed records instead of forgetting them", async () => {
    const storage = environment();
    storage.localStorage.setItem("anima-conversation-submission:workspace_test", JSON.stringify(pending()));
    const api = await document(storage, "document-a");
    expect(api.recoverConversationPending("workspace_test", storage)).toEqual(pending());
    storage.localStorage.setItem(api.getConversationPendingKey("workspace_test", storage), "{broken");
    expect(() => api.recoverConversationPending("workspace_test", storage)).toThrow(/恢复记录/);
  });

  it("shares request completion across cloned recovery records and never revives an ancestor request on reload", async () => {
    const storage = environment();
    const original = await document(storage, "document-a");
    original.saveConversationPending("workspace_test", pending(), storage);
    const cloneStorage = duplicate(storage);
    const clone = await document(cloneStorage, "document-b");
    expect(clone.recoverConversationPending("workspace_test", cloneStorage)).toEqual(pending());
    clone.clearConversationPending("workspace_test", pending(), cloneStorage);
    expect(original.recoverConversationPending("workspace_test", storage)).toBeNull();
    expect(() => original.saveConversationPending("workspace_test", pending(), storage)).toThrow(/完成|核对/);
    const reload = await document(storage, "document-c");
    expect(reload.recoverConversationPending("workspace_test", storage)).toBeNull();
    reload.saveConversationPending("another_workspace", pending("another_workspace"), storage);
    expect(reload.recoverConversationPending("another_workspace", storage)).toEqual(pending("another_workspace"));
  });

  it("keeps independent new requests in duplicate documents and only clears the matching request", async () => {
    const storage = environment();
    const original = await document(storage, "document-a");
    const cloneStorage = duplicate(storage);
    const clone = await document(cloneStorage, "document-b");
    original.saveConversationPending("workspace_test", pending(), storage);
    clone.saveConversationPending("workspace_test", pending("workspace_test", "request-clone"), cloneStorage);
    original.clearConversationPending("workspace_test", pending(), storage);
    expect(clone.recoverConversationPending("workspace_test", cloneStorage)?.key).toBe("request-clone");
  });

  it.each(["write failure", "malformed context"])("protects recovery when session lineage has %s", async failure => {
    const storage = environment();
    saveConversationDraft("workspace_test", draft(), draft(), storage);
    storage.localStorage.setItem(getConversationPendingKey("workspace_test", storage), JSON.stringify(pending()));
    if (failure === "write failure") storage.sessionStorage.setItem = () => { throw new Error("quota"); };
    else storage.sessionStorage.setItem(CONTEXT_KEY, "{broken");
    const api = await document(storage, "document-new");
    expect(() => api.recoverConversationPending("workspace_test", storage)).toThrow(/恢复|存储/);
    expect(() => api.saveConversationPending("workspace_test", pending("workspace_test", "new-request"), storage)).toThrow(/恢复|存储/);
    expect(api.saveConversationDraft("workspace_test", draft(), draft(), storage).ok).toBe(false);
    expect(api.readConversationDraft("workspace_test", storage)?.persistenceBlocked).toBe(true);
    expect(storage.localStorage.getItem("anima-conversation-submission:v1:workspace_test:tab-a")).toContain("request-original");
  });

  it("retains pending recovery if marking completion fails", async () => {
    const storage = environment();
    const api = await document(storage, "document-a");
    api.saveConversationPending("workspace_test", pending(), storage);
    const set = storage.localStorage.setItem.bind(storage.localStorage);
    storage.localStorage.setItem = () => { throw new Error("quota"); };
    expect(() => api.clearConversationPending("workspace_test", pending(), storage)).toThrow();
    storage.localStorage.setItem = set;
    expect(api.recoverConversationPending("workspace_test", storage)).toEqual(pending());
  });

  it("does not overwrite a different unresolved request with a new idempotency key", async () => {
    const storage = environment();
    const api = await document(storage, "document-a");
    api.saveConversationPending("workspace_test", pending(), storage);
    expect(() => api.saveConversationPending("workspace_test", pending("workspace_test", "new-request"), storage)).toThrow(/核对|恢复/);
    expect(api.recoverConversationPending("workspace_test", storage)).toEqual(pending());
  });
});

describe("document-owned branch recovery", () => {
  const request = {key: "branch-original", body: JSON.stringify({title: "My branch", draft: {model_profile: "anima_base_v1"}})};

  it("migrates the old draft-branch request and preserves its key and body through reload", async () => {
    const storage = environment();
    storage.localStorage.setItem(`${getConversationPendingKey("workspace_test", storage)}:branch`, JSON.stringify(request));
    const api = await document(storage, "document-a");
    expect(api.recoverConversationBranch("workspace_test", "draft", storage)).toEqual(request);
    const reload = await document(storage, "document-b");
    expect(reload.recoverConversationBranch("workspace_test", "draft", storage)).toEqual(request);
    expect(reload.recoverConversationBranch("workspace_test", "version:3", storage)).toBeNull();
  });

  it("keeps draft, different historical versions, and other workspaces in separate recovery slots", async () => {
    const storage = environment();
    const api = await document(storage, "document-a");
    api.saveConversationBranch("workspace_test", "draft", request, storage);
    api.saveConversationBranch("workspace_test", "version:3", {...request, key: "version-three"}, storage);
    api.saveConversationBranch("workspace_test", "version:4", {...request, key: "version-four"}, storage);
    api.saveConversationBranch("workspace_test", "run:run_original-123", {...request, key: "source-run"}, storage);
    api.saveConversationBranch("other_workspace", "version:3", {...request, key: "other-workspace"}, storage);
    const reload = await document(storage, "document-b");
    expect(reload.recoverConversationBranch("workspace_test", "draft", storage)?.key).toBe("branch-original");
    expect(reload.recoverConversationBranch("workspace_test", "version:3", storage)?.key).toBe("version-three");
    expect(reload.recoverConversationBranch("workspace_test", "version:4", storage)?.key).toBe("version-four");
    expect(reload.recoverConversationBranch("workspace_test", "run:run_original-123", storage)?.key).toBe("source-run");
    expect(reload.recoverConversationBranch("workspace_test", "run:run_other", storage)).toBeNull();
    expect(reload.recoverConversationBranch("other_workspace", "version:3", storage)?.key).toBe("other-workspace");
    expect(reload.recoverConversationPending("workspace_test", storage)).toBeNull();
  });

  it("shares branch completion across cloned documents without consuming a different branch's request", async () => {
    const storage = environment();
    const api = await document(storage, "document-a");
    api.saveConversationBranch("workspace_test", "draft", request, storage);
    api.saveConversationBranch("workspace_test", "version:3", request, storage);
    const cloneStorage = duplicate(storage);
    const clone = await document(cloneStorage, "document-b");
    expect(clone.recoverConversationBranch("workspace_test", "draft", cloneStorage)).toEqual(request);
    clone.clearConversationBranch("workspace_test", "draft", request, cloneStorage);
    expect(api.recoverConversationBranch("workspace_test", "draft", storage)).toBeNull();
    expect(() => api.saveConversationBranch("workspace_test", "draft", request, storage)).toThrow(/完成|核对/);
    expect(api.recoverConversationBranch("workspace_test", "version:3", storage)).toEqual(request);
    const reload = await document(storage, "document-c");
    expect(reload.recoverConversationBranch("workspace_test", "draft", storage)).toBeNull();
  });

  it("isolates new branch requests in cloned tabs while rejecting replacement of an unresolved request", async () => {
    const storage = environment();
    const api = await document(storage, "document-a");
    const cloneStorage = duplicate(storage);
    const clone = await document(cloneStorage, "document-b");
    api.saveConversationBranch("workspace_test", "version:3", request, storage);
    clone.saveConversationBranch("workspace_test", "version:3", {...request, key: "clone-branch"}, cloneStorage);
    expect(() => api.saveConversationBranch("workspace_test", "version:3", {...request, key: "replacement"}, storage)).toThrow(/恢复|核对/);
    expect(api.recoverConversationBranch("workspace_test", "version:3", storage)).toEqual(request);
    expect(clone.recoverConversationBranch("workspace_test", "version:3", cloneStorage)?.key).toBe("clone-branch");
  });

  it("blocks branch recreation when source migration is damaged or cannot be persisted", async () => {
    const storage = environment();
    const legacyKey = `${getConversationPendingKey("workspace_test", storage)}:branch`;
    storage.localStorage.setItem(legacyKey, "{broken");
    const api = await document(storage, "document-a");
    expect(() => api.recoverConversationBranch("workspace_test", "draft", storage)).toThrow(/恢复/);
    storage.localStorage.setItem(legacyKey, JSON.stringify(request));
    storage.localStorage.setItem = () => { throw new Error("quota"); };
    expect(() => api.recoverConversationBranch("workspace_test", "draft", storage)).toThrow(/恢复/);
    expect(storage.localStorage.getItem(legacyKey)).toBe(JSON.stringify(request));
  });

  it.each(["run:", "run:../../other", `run:${"a".repeat(129)}`])("rejects an invalid run recovery source: %s", async source => {
    const storage = environment();
    const api = await document(storage, "document-a");
    expect(() => api.saveConversationBranch("workspace_test", source as `run:${string}`, request, storage)).toThrow(/识别|核对/);
  });
});
