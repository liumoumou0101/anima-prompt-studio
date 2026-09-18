import type {LocalConversation, RequirementLayers, RequirementsEdit} from "./conversation";

export const CONVERSATION_DRAFT_SCHEMA_VERSION = 1 as const;
const TAB_ID_KEY = "anima-conversation-tab-id";
const LEGACY_PREFIX = "anima-conversation-draft:";
const SLOT_PREFIX = "anima-conversation-draft:v1:";
const RECOVERY_PREFIX = "anima-conversation-draft-recovery:v1:";
const INVALID_PREFIX = "anima-conversation-draft-invalid:";
const SNAPSHOT_PREFIX = "anima-conversation-draft-snapshot:v1:";
const RAW_SNAPSHOT_PREFIX = `${INVALID_PREFIX}v1:`;
const PENDING_PREFIX = "anima-conversation-submission:v1:";
const PENDING_DONE_PREFIX = "anima-conversation-submission-done:v1:";
const DOCUMENT_CONTEXT_KEY = "anima-conversation-document:v1";

export interface ConversationDraftStorage {
  localStorage: Pick<Storage, "getItem" | "setItem" | "removeItem"> & Partial<Pick<Storage, "length" | "key">>;
  sessionStorage: Pick<Storage, "getItem" | "setItem">;
  createTabId?: () => string;
  now?: () => number;
}

export interface ConversationTabInitializationOptions {
  createDocumentId?: () => string;
  lifecycle?: {addEventListener(type: "pageshow", listener: (event: {persisted: boolean}) => void): void};
}

interface DocumentContext {
  version: 1;
  tabId: string;
  ancestors: string[];
}
interface DocumentIdentity extends DocumentContext {recoveryError?: string; recoveryRaw?: string}
export interface ConversationPending {key: string; body: string}
export type ConversationBranchSource = "draft" | `version:${number}` | `run:${string}`;

interface DraftEnvelope {
  version: typeof CONVERSATION_DRAFT_SCHEMA_VERSION;
  workspaceId: string;
  tabId: string;
  savedAt: number;
  local: LocalConversation;
  base: LocalConversation | null;
}

interface RecoveryIndex {
  version: typeof CONVERSATION_DRAFT_SCHEMA_VERSION;
  slots: Record<string, {key: string; savedAt: number}>;
}

export interface ConversationDraftReadResult {
  local: LocalConversation | null;
  base: LocalConversation | null;
  warning: string;
  invalidRaw?: string;
  invalidBackupKey?: string;
  persistenceBlocked?: boolean;
}

export interface ConversationDraftSaveResult {ok: boolean; warning: string}

export interface ConversationDraftCandidate {
  key: string;
  kind: "document" | "snapshot" | "legacy" | "invalid";
  status: "valid" | "invalid";
  savedAt: number | null;
  tabId: string | null;
  local: LocalConversation | null;
  base: LocalConversation | null;
  raw: string;
}

export interface ConversationDraftCandidateList {candidates: ConversationDraftCandidate[]; warning: string}
export interface ConversationDraftPreserveResult extends ConversationDraftSaveResult {key?: string}
export interface ConversationDraftCleanupResult {removed: number; warning: string}

let volatileTabId = "";
const documentIdentities = new WeakMap<ConversationDraftStorage, DocumentIdentity>();
const automaticCleanupTimes = new WeakMap<ConversationDraftStorage, Map<string, number>>();
// Keep the environment object stable while deferring policy-sensitive getters.
const browserStorage: ConversationDraftStorage = {
  get localStorage() { return window.localStorage; },
  get sessionStorage() { return window.sessionStorage; },
};

function environment(storage?: ConversationDraftStorage): ConversationDraftStorage {
  return storage || browserStorage;
}

export function conversationDraftKey(workspaceId: string, tabId: string): string {
  return `${SLOT_PREFIX}${encodeURIComponent(workspaceId)}:${encodeURIComponent(tabId)}`;
}

export function conversationDraftRecoveryKey(workspaceId: string): string {
  return `${RECOVERY_PREFIX}${encodeURIComponent(workspaceId)}`;
}

export function conversationDraftInvalidBackupKey(workspaceId: string, savedAt: number): string {
  return `${INVALID_PREFIX}${encodeURIComponent(workspaceId)}:${savedAt}`;
}

export function getConversationPendingKey(workspaceId: string, storage?: ConversationDraftStorage): string {
  return pendingKey(workspaceId, getConversationTabId(storage));
}

export function legacyConversationDraftKey(workspaceId: string): string {
  return LEGACY_PREFIX + workspaceId;
}

export function getConversationTabId(storage?: ConversationDraftStorage): string {
  const target = environment(storage);
  const identity = documentIdentities.get(target);
  if (identity) return identity.tabId;
  try {
    const context = readDocumentContext(target);
    if (context) return context.tabId;
    const existing = target.sessionStorage.getItem(TAB_ID_KEY);
    if (existing) return existing;
    const created = target.createTabId?.() || crypto.randomUUID();
    target.sessionStorage.setItem(TAB_ID_KEY, created);
    return created;
  } catch {
    volatileTabId ||= target.createTabId?.() || crypto.randomUUID();
    return volatileTabId;
  }
}

function readDocumentContext(target: ConversationDraftStorage): DocumentContext | null {
  const raw = target.sessionStorage.getItem(DOCUMENT_CONTEXT_KEY);
  if (raw === null) return null;
  const value = parse(raw);
  if (!object(value) || value.version !== 1 || typeof value.tabId !== "string" || !value.tabId
      || !Array.isArray(value.ancestors) || value.ancestors.some(id => typeof id !== "string" || !id)) {
    throw new Error("页面恢复来源记录已损坏；请先导出草稿并到全部任务核对生成状态。");
  }
  return value as unknown as DocumentContext;
}

function preserveDocumentContext(target: ConversationDraftStorage, identity: DocumentIdentity): void {
  try {
    // A restored BFCache document becomes the primary recovery source again,
    // while retaining newer documents' unresolved submission records as ancestors.
    const previous = readDocumentContext(target);
    const legacyId = previous ? null : target.sessionStorage.getItem(TAB_ID_KEY);
    identity.ancestors = [...new Set([...identity.ancestors,
      ...(previous ? [previous.tabId, ...previous.ancestors] : legacyId ? [legacyId] : [])])].filter(id => id !== identity.tabId);
    const saved: DocumentContext = {version: 1, tabId: identity.tabId, ancestors: identity.ancestors};
    target.sessionStorage.setItem(DOCUMENT_CONTEXT_KEY, JSON.stringify(saved));
  } catch {
    identity.recoveryError = "浏览器无法读取或保存页面恢复来源；请先导出草稿并到全部任务核对生成状态，暂勿重复提交。";
    try { identity.recoveryRaw = target.sessionStorage.getItem(DOCUMENT_CONTEXT_KEY) || undefined; } catch { /* Policy denies access. */ }
  }
}

/**
 * Every document writes to its own slot. A single atomic sessionStorage record
 * remembers predecessor slots for reload/duplicate recovery. This does not depend
 * on live pages answering a channel, on timeouts, or on expiring leases. A BFCache
 * document keeps its in-memory identity even if a newer document updated the session.
 */
export function initializeConversationTab(storage?: ConversationDraftStorage,
  options: ConversationTabInitializationOptions = {}): Promise<string> {
  const target = environment(storage);
  const existing = documentIdentities.get(target);
  if (existing) return Promise.resolve(existing.tabId);
  const identity: DocumentIdentity = {version: 1, tabId: options.createDocumentId?.() || crypto.randomUUID(), ancestors: []};
  documentIdentities.set(target, identity);
  preserveDocumentContext(target, identity);
  const lifecycle: ConversationTabInitializationOptions["lifecycle"] | null = options.lifecycle || (typeof window !== "undefined" ? window : null);
  lifecycle?.addEventListener("pageshow", event => { if (event.persisted) preserveDocumentContext(target, identity); });
  return Promise.resolve(identity.tabId);
}

function recoveryTabIds(target: ConversationDraftStorage): string[] {
  const identity = documentIdentities.get(target);
  if (identity?.recoveryError) throw new Error(identity.recoveryError);
  const context = identity || readDocumentContext(target);
  return context ? [context.tabId, ...context.ancestors] : [getConversationTabId(target)];
}

function pendingKey(workspaceId: string, tabId: string): string {
  return `${PENDING_PREFIX}${encodeURIComponent(workspaceId)}:${encodeURIComponent(tabId)}`;
}

function pendingDoneKey(workspaceId: string, request: ConversationPending): string {
  return `${PENDING_DONE_PREFIX}${encodeURIComponent(workspaceId)}:${encodeURIComponent(request.key)}`;
}

function validPending(value: unknown, workspaceId: string): value is ConversationPending {
  if (!object(value) || typeof value.key !== "string" || !value.key || typeof value.body !== "string") return false;
  const body = parse(value.body);
  return object(body) && body.workspace_id === workspaceId && body.submission_kind === "conversational";
}

function requestSlot(workspaceId: string, target: ConversationDraftStorage, source: ConversationBranchSource | null) {
  const ids = recoveryTabIds(target);
  if (source === null) return {
    currentKey: getConversationPendingKey(workspaceId, target),
    recoveryKeys: [...ids.map(id => pendingKey(workspaceId, id)), `anima-conversation-submission:${workspaceId}`],
    doneKey: (request: ConversationPending) => pendingDoneKey(workspaceId, request),
    valid: (value: unknown): value is ConversationPending => validPending(value, workspaceId),
  };
  if (source !== "draft" && !/^version:[1-9]\d*$/.test(source) && !/^run:[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(source)) {
    throw new Error("无法识别要另存的来源，请先核对历史版本或生成记录。");
  }
  const namespace = `${encodeURIComponent(workspaceId)}:${encodeURIComponent(source)}`;
  const prefix = `anima-conversation-branch:v1:${namespace}:`;
  return {
    currentKey: prefix + encodeURIComponent(getConversationTabId(target)),
    recoveryKeys: [...ids.map(id => prefix + encodeURIComponent(id)),
      ...(source === "draft" ? ids.map(id => `${pendingKey(workspaceId, id)}:branch`) : [])],
    doneKey: (request: ConversationPending) => `anima-conversation-branch-done:v1:${namespace}:${encodeURIComponent(request.key)}`,
    valid: (value: unknown): value is ConversationPending => object(value) && typeof value.key === "string" && Boolean(value.key)
      && typeof value.body === "string" && object(parse(value.body)),
  };
}

function recoverConversationRequest(workspaceId: string, source: ConversationBranchSource | null,
  storage?: ConversationDraftStorage): ConversationPending | null {
  const target = environment(storage);
  try {
    const slot = requestSlot(workspaceId, target, source);
    for (const key of slot.recoveryKeys) {
      const raw = target.localStorage.getItem(key);
      if (raw === null) continue;
      const request = parse(raw);
      if (!slot.valid(request)) throw new Error();
      // Completion belongs to a request, not a document: all clones see it.
      if (target.localStorage.getItem(slot.doneKey(request)) === "1") continue;
      target.localStorage.setItem(slot.currentKey, JSON.stringify(request));
      return request;
    }
    return null;
  } catch { throw new Error(`上次${source === null ? "生成" : "另存"}请求的恢复记录无法读取或迁移。请先核对${source === null ? "全部任务" : "会话列表"}，暂勿重复提交。`); }
}

function saveConversationRequest(workspaceId: string, source: ConversationBranchSource | null,
  request: ConversationPending, storage?: ConversationDraftStorage): void {
  const target = environment(storage);
  const slot = requestSlot(workspaceId, target, source); // Fail closed if preserving recovery is impossible.
  if (!slot.valid(request)) throw new Error("请求的恢复记录不完整，尚未提交。");
  if (target.localStorage.getItem(slot.doneKey(request)) === "1") {
    throw new Error("这次请求已完成或已明确拒绝，请刷新页面核对全部任务，暂勿重复提交。");
  }
  const currentRaw = target.localStorage.getItem(slot.currentKey);
  if (currentRaw !== null) {
    const current = parse(currentRaw);
    if (!slot.valid(current) || current.key !== request.key && target.localStorage.getItem(slot.doneKey(current)) !== "1") {
      throw new Error("仍有未确认结果的请求，请先恢复并核对结果，暂勿重复提交。");
    }
    if (current.key === request.key && current.body !== request.body) throw new Error("恢复请求内容已变化，请先核对全部任务。");
  }
  try { target.localStorage.setItem(slot.currentKey, JSON.stringify(request)); }
  catch { throw new Error("无法保存请求的恢复记录，尚未提交。请释放浏览器存储后重试。"); }
}

function clearConversationRequest(workspaceId: string, source: ConversationBranchSource | null,
  request: ConversationPending, storage?: ConversationDraftStorage): void {
  const target = environment(storage);
  const slot = requestSlot(workspaceId, target, source);
  if (!slot.valid(request)) throw new Error("请求的恢复记录不完整，请先核对结果。");
  // Record completion before deleting the current pointer; predecessor records
  // are immutable recovery sources and must not be removed from another document.
  try { target.localStorage.setItem(slot.doneKey(request), "1"); }
  catch { throw new Error("请求状态已返回，但无法保存完成记录；请先核对全部任务，暂勿重复提交。"); }
  try {
    const current = parse(target.localStorage.getItem(slot.currentKey));
    if (slot.valid(current) && current.key === request.key) target.localStorage.removeItem(slot.currentKey);
  } catch { /* The durable completion marker already prevents recovery. */ }
}

/** Recover exactly the original request; these storage helpers never submit it. */
export function recoverConversationPending(workspaceId: string, storage?: ConversationDraftStorage): ConversationPending | null {
  return recoverConversationRequest(workspaceId, null, storage);
}

export function saveConversationPending(workspaceId: string, request: ConversationPending, storage?: ConversationDraftStorage): void {
  saveConversationRequest(workspaceId, null, request, storage);
}

/** Call only after acceptance or a definitive rejection, never after an ambiguous network error. */
export function clearConversationPending(workspaceId: string, request: ConversationPending, storage?: ConversationDraftStorage): void {
  clearConversationRequest(workspaceId, null, request, storage);
}

export function recoverConversationBranch(workspaceId: string, source: ConversationBranchSource,
  storage?: ConversationDraftStorage): ConversationPending | null {
  return recoverConversationRequest(workspaceId, source, storage);
}

export function saveConversationBranch(workspaceId: string, source: ConversationBranchSource,
  request: ConversationPending, storage?: ConversationDraftStorage): void {
  saveConversationRequest(workspaceId, source, request, storage);
}

export function clearConversationBranch(workspaceId: string, source: ConversationBranchSource,
  request: ConversationPending, storage?: ConversationDraftStorage): void {
  clearConversationRequest(workspaceId, source, request, storage);
}

function object(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

const strings = (value: unknown) => Array.isArray(value) && value.every(item => typeof item === "string");
const choice = (value: unknown) => value == null || object(value) && typeof value.value === "string"
  && ["user", "extracted", "suggestion"].includes(String(value.source))
  && (value.target == null || typeof value.target === "string") && (value.evidence == null || typeof value.evidence === "string");

function requirements(value: unknown): value is RequirementsEdit {
  if (!object(value) || !object(value.layers) || !Array.isArray(value.loras)) return false;
  if (value.prompt_locks !== undefined && (!Array.isArray(value.prompt_locks)
      || value.prompt_locks.some(item => !object(item) || !["positive", "negative"].includes(String(item.target))
        || typeof item.text !== "string" || !item.text.trim()))) return false;
  const layers = value.layers as unknown as RequirementLayers;
  if (!object(layers.subject) || typeof layers.subject.text !== "string" || typeof layers.subject.locked !== "boolean"
      || !object(layers.style) || typeof layers.style.text !== "string" || typeof layers.style.medium !== "string"
      || !strings(layers.style.artists) || typeof layers.style.locked !== "boolean"
      || !object(layers.lighting) || typeof layers.lighting.text !== "string" || typeof layers.lighting.locked !== "boolean"
      || typeof layers.lighting.include_with_style_pin !== "boolean" || !choice(layers.lighting.mood)
      || !object(layers.composition) || typeof layers.composition.text !== "string" || typeof layers.composition.shot !== "string"
      || typeof layers.composition.locked !== "boolean" || typeof layers.composition.include_with_style_pin !== "boolean"
      || !object(layers.exclusions) || !strings(layers.exclusions.global) || !Array.isArray(layers.exclusions.scoped)
      || typeof layers.exclusions.locked !== "boolean") return false;
  if ([layers.subject.character_tags, layers.subject.series_tags, layers.subject.general_tags, layers.style.manual_artist_tags]
    .some(items => items !== undefined && !strings(items))) return false;
  if (layers.exclusions.scoped.some(item => !object(item) || typeof item.target !== "string" || typeof item.concept !== "string")) return false;
  if (layers.composition.design != null && (!object(layers.composition.design)
      || Object.keys(layers.composition.design).some(key => !["shot", "layout", "camera", "gaze"].includes(key))
      || Object.values(layers.composition.design).some(item => !choice(item)))) return false;
  return value.loras.every(item => object(item) && typeof item.logical_id === "string" && typeof item.file_name === "string"
    && typeof item.weight === "number" && strings(item.trigger_words) && typeof item.required === "boolean" && object(item.source) && typeof item.source.kind === "string");
}

function localConversation(value: unknown): value is LocalConversation {
  if (!object(value) || !Number.isInteger(value.baseRevision) || Number(value.baseRevision) < 1
      || typeof value.delta !== "string" || !["faithful", "expand"].includes(String(value.mode))
      || !requirements(value.requirements) || typeof value.positive !== "string" || typeof value.negative !== "string"
      || typeof value.model !== "string" || !object(value.settings)) return false;
  const settings = value.settings;
  return typeof settings.preset_id === "string" && typeof settings.aspect === "string"
    && typeof settings.width === "number" && typeof settings.height === "number" && typeof settings.steps === "number"
    && typeof settings.cfg === "number" && typeof settings.sampler === "string" && typeof settings.scheduler === "string"
    && (typeof settings.seed === "number" || typeof settings.seed === "string") && typeof settings.batch_size === "number"
    && (settings.remote_profile_id === null || typeof settings.remote_profile_id === "string")
    && (settings.workflow_profile_id === null || typeof settings.workflow_profile_id === "string");
}

function parse(raw: string | null): unknown {
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

function envelope(value: unknown, workspaceId?: string): value is DraftEnvelope {
  return object(value) && value.version === CONVERSATION_DRAFT_SCHEMA_VERSION
    && typeof value.workspaceId === "string" && (!workspaceId || value.workspaceId === workspaceId)
    && typeof value.tabId === "string" && Boolean(value.tabId) && typeof value.savedAt === "number"
    && Number.isFinite(value.savedAt) && value.savedAt >= 0
    && localConversation(value.local) && (value.base === null || localConversation(value.base));
}

function recovery(value: unknown): value is RecoveryIndex {
  return object(value) && value.version === CONVERSATION_DRAFT_SCHEMA_VERSION && object(value.slots)
    && Object.values(value.slots).every(slot => object(slot) && typeof slot.key === "string" && typeof slot.savedAt === "number");
}

function workspacePrefix(prefix: string, workspaceId: string): string {
  return `${prefix}${encodeURIComponent(workspaceId)}:`;
}

function candidateKind(workspaceId: string, key: string): ConversationDraftCandidate["kind"] | null {
  if (key === legacyConversationDraftKey(workspaceId)) return "legacy";
  if (key.startsWith(workspacePrefix(SLOT_PREFIX, workspaceId))) return "document";
  if (key.startsWith(workspacePrefix(SNAPSHOT_PREFIX, workspaceId))) return "snapshot";
  if (key.startsWith(workspacePrefix(RAW_SNAPSHOT_PREFIX, workspaceId))) return "invalid";
  // Old backups were timestamp-addressed. Do not confuse workspace "v1" with
  // the newer immutable raw-backup namespace below that same prefix.
  const oldPrefix = workspacePrefix(INVALID_PREFIX, workspaceId);
  if (key.startsWith(oldPrefix) && /^\d+$/.test(key.slice(oldPrefix.length))) return "invalid";
  return null;
}

function readCandidate(workspaceId: string, key: string, target: ConversationDraftStorage): ConversationDraftCandidate | null {
  const kind = candidateKind(workspaceId, key);
  if (!kind) return null;
  const raw = target.localStorage.getItem(key);
  if (raw === null) return null;
  const value = parse(raw);
  if ((kind === "document" || kind === "snapshot") && envelope(value, workspaceId)
      && (kind !== "document" || conversationDraftKey(workspaceId, value.tabId) === key)) {
    return {key, kind, status: "valid", savedAt: value.savedAt, tabId: value.tabId,
      local: value.local, base: value.base, raw};
  }
  if (kind === "legacy" && localConversation(value)) {
    return {key, kind, status: "valid", savedAt: null, tabId: null, local: value, base: null, raw};
  }
  const timestampPrefix = key.startsWith(workspacePrefix(RAW_SNAPSHOT_PREFIX, workspaceId))
    ? workspacePrefix(RAW_SNAPSHOT_PREFIX, workspaceId) : workspacePrefix(INVALID_PREFIX, workspaceId);
  const timestamp = kind === "invalid" ? Number(key.slice(timestampPrefix.length).split(":")[0]) : NaN;
  return {key, kind, status: "invalid", savedAt: Number.isFinite(timestamp) ? timestamp : null,
    tabId: null, local: null, base: null, raw};
}

/** Reads fresh bytes without migrating, deleting or writing the selected source. */
export function readConversationDraftCandidate(workspaceId: string, key: string,
  storage?: ConversationDraftStorage): ConversationDraftCandidate | null {
  try { return readCandidate(workspaceId, key, environment(storage)); }
  catch { return null; }
}

/** Enumerates real keys as the recovery index can lose concurrent tab updates. */
export function listConversationDraftCandidates(workspaceId: string, storage?: ConversationDraftStorage): ConversationDraftCandidateList {
  const target = environment(storage);
  const candidates: ConversationDraftCandidate[] = [];
  let warning = "";
  try {
    const localStorage = target.localStorage;
    const keys = new Set<string>([legacyConversationDraftKey(workspaceId)]);
    const index = parse(localStorage.getItem(conversationDraftRecoveryKey(workspaceId)));
    if (recovery(index)) for (const slot of Object.values(index.slots)) keys.add(slot.key);
    try { for (const id of recoveryTabIds(target)) keys.add(conversationDraftKey(workspaceId, id)); }
    catch { /* A damaged session lineage must not hide independently discoverable backups. */ }
    if (typeof localStorage.key === "function" && typeof localStorage.length === "number") {
      for (let position = 0; position < localStorage.length; position++) {
        const key = localStorage.key(position);
        if (key && candidateKind(workspaceId, key)) keys.add(key);
      }
    } else warning = "浏览器存储无法列出全部备份，仅显示已知的草稿记录。";
    for (const key of keys) {
      const candidate = readCandidate(workspaceId, key, target);
      if (candidate) candidates.push(candidate);
    }
  } catch { warning = "浏览器存储无法完整读取，请先导出当前草稿后重试。"; }
  candidates.sort((left, right) => (right.savedAt ?? -1) - (left.savedAt ?? -1) || left.key.localeCompare(right.key));
  return {candidates, warning};
}

function snapshotContent(candidate: Pick<ConversationDraftCandidate, "local" | "base">): string {
  return JSON.stringify({local: candidate.local, base: candidate.base});
}

function completeSnapshotContent(candidate: ConversationDraftCandidate): string {
  // Preserve unknown envelope fields introduced by future writers. Only the
  // known copy identity and timestamp may differ between redundant snapshots.
  return JSON.stringify({...JSON.parse(candidate.raw), tabId: null, savedAt: null});
}

function preserveRawDraft(workspaceId: string, raw: string, target: ConversationDraftStorage): string {
  const prefix = workspacePrefix(RAW_SNAPSHOT_PREFIX, workspaceId);
  const existing = listConversationDraftCandidates(workspaceId, target).candidates
    .filter(candidate => candidate.key.startsWith(prefix) && candidate.raw === raw).sort((left, right) => left.key.localeCompare(right.key))[0];
  if (existing && target.localStorage.getItem(existing.key) === raw) return existing.key;
  // UUID addresses are never reused, even when simultaneous failures share a timestamp.
  const key = `${prefix}${target.now?.() ?? Date.now()}:${crypto.randomUUID()}`;
  target.localStorage.setItem(key, raw);
  return key;
}

/** Preserve before replacing the editable slot. This never saves to the server. */
export function preserveConversationDraft(workspaceId: string, local: LocalConversation, base: LocalConversation | null,
  storage?: ConversationDraftStorage): ConversationDraftPreserveResult {
  const target = environment(storage);
  if (!localConversation(local) || base !== null && !localConversation(base)) {
    return {ok: false, warning: "当前草稿结构不完整，无法创建恢复副本；请先导出当前内容。"};
  }
  try {
    const content = snapshotContent({local, base});
    const existing = listConversationDraftCandidates(workspaceId, target).candidates
      .filter(candidate => candidate.kind === "snapshot" && candidate.status === "valid" && snapshotContent(candidate) === content)
      .sort((left, right) => left.key.localeCompare(right.key))[0];
    if (existing && target.localStorage.getItem(existing.key) === existing.raw) return {ok: true, warning: "", key: existing.key};
    const id = crypto.randomUUID();
    const key = workspacePrefix(SNAPSHOT_PREFIX, workspaceId) + id;
    const value: DraftEnvelope = {version: CONVERSATION_DRAFT_SCHEMA_VERSION, workspaceId, tabId: id,
      savedAt: target.now?.() ?? Date.now(), local, base};
    target.localStorage.setItem(key, JSON.stringify(value));
    return {ok: true, warning: "", key};
  } catch { return {ok: false, warning: "无法保留当前草稿的恢复副本；请先导出当前内容或释放浏览器存储。"}; }
}

/**
 * Only new, immutable backup namespaces are eligible. Mutable document slots,
 * old timestamp backups, lineage, requests and completion markers never expire.
 * A deterministic retained key prevents simultaneous cleaners deleting each
 * other's final copy; rereads also protect against external storage changes.
 */
export function cleanupConversationDrafts(workspaceId: string, storage?: ConversationDraftStorage): ConversationDraftCleanupResult {
  const target = environment(storage);
  const listed = listConversationDraftCandidates(workspaceId, target);
  let removed = 0;
  try {
    const retained = new Map<string, ConversationDraftCandidate>();
    for (const candidate of [...listed.candidates].sort((left, right) => left.key.localeCompare(right.key))) {
      const immutableRaw = candidate.key.startsWith(workspacePrefix(RAW_SNAPSHOT_PREFIX, workspaceId));
      const signature = immutableRaw ? `raw:${candidate.raw}`
        : candidate.kind === "snapshot" && candidate.status === "valid" ? `draft:${completeSnapshotContent(candidate)}` : null;
      if (signature === null) continue;
      const previous = retained.get(signature);
      if (!previous) { retained.set(signature, candidate); continue; }
      if (target.localStorage.getItem(previous.key) !== previous.raw || target.localStorage.getItem(candidate.key) !== candidate.raw) continue;
      target.localStorage.removeItem(candidate.key);
      removed++;
    }
    return {removed, warning: listed.warning};
  } catch { return {removed, warning: "部分重复备份无法整理；现有草稿仍保留在浏览器中。"}; }
}

function automaticallyCleanupDrafts(workspaceId: string, target: ConversationDraftStorage): void {
  const now = Date.now();
  const previous = automaticCleanupTimes.get(target) || new Map<string, number>();
  const last = previous.get(workspaceId);
  if (last !== undefined && now - last < 60_000) return;
  previous.set(workspaceId, now);
  automaticCleanupTimes.set(target, previous);
  cleanupConversationDrafts(workspaceId, target);
}

export function readConversationDraft(workspaceId: string, storage?: ConversationDraftStorage): ConversationDraftReadResult | null {
  const target = environment(storage);
  const identity = documentIdentities.get(target);
  if (identity?.recoveryError) return {local: null, base: null, warning: identity.recoveryError,
    persistenceBlocked: true, ...(identity.recoveryRaw ? {invalidRaw: identity.recoveryRaw} : {})};
  try {
    for (const tabId of recoveryTabIds(target)) {
      const ownRaw = target.localStorage.getItem(conversationDraftKey(workspaceId, tabId));
      const own = parse(ownRaw);
      if (envelope(own, workspaceId)) return {local: own.local, base: own.base,
        warning: own.base ? "" : "缺少可靠的合并基准；保存到服务端前请逐项核对版本。"};
      if (ownRaw !== null) {
        try {
          const invalidBackupKey = preserveRawDraft(workspaceId, ownRaw, target);
          return {local: null, base: null, warning: "旧草稿结构不兼容，已保留原始副本；请先导出并核对后再继续。",
            invalidRaw: ownRaw, invalidBackupKey};
        } catch {
          return {local: null, base: null, warning: "旧草稿结构不兼容，且浏览器存储无法保留副本；请立即导出原始草稿，确认后再继续。",
            invalidRaw: ownRaw, persistenceBlocked: true};
        }
      }
    }
    const index = parse(target.localStorage.getItem(conversationDraftRecoveryKey(workspaceId)));
    if (recovery(index)) {
      const slots = Object.values(index.slots).sort((left, right) => right.savedAt - left.savedAt);
      for (const slot of slots) {
        const candidate = parse(target.localStorage.getItem(slot.key));
        if (envelope(candidate, workspaceId)) return {local: candidate.local, base: candidate.base,
          warning: candidate.base ? "已从其他标签页的最近草稿恢复，请核对后再保存。"
            : "已从其他标签页恢复草稿，但缺少可靠的合并基准；保存到服务端前请逐项核对版本。"};
      }
    }
    const legacy = parse(target.localStorage.getItem(legacyConversationDraftKey(workspaceId)));
    if (localConversation(legacy)) return {local: legacy, base: null, warning: "已恢复旧版草稿，但缺少合并基准；请逐项核对本地与服务端版本。"};
  } catch {
    // A temporarily unreadable slot can still contain unique edits. Treating
    // it as absent would let the initial server draft silently overwrite it.
    return {local: null, base: null, persistenceBlocked: true,
      warning: "浏览器存储中的草稿暂时无法读取，已暂停自动保存；请先找回本地草稿或刷新后重试。"};
  }
  return null;
}

export function saveConversationDraft(workspaceId: string, local: LocalConversation, base: LocalConversation | null,
  storage?: ConversationDraftStorage): ConversationDraftSaveResult {
  const target = environment(storage);
  const identity = documentIdentities.get(target);
  if (identity?.recoveryError) return {ok: false, warning: identity.recoveryError};
  const tabId = getConversationTabId(target);
  const savedAt = target.now?.() ?? Date.now();
  const key = conversationDraftKey(workspaceId, tabId);
  const value: DraftEnvelope = {version: CONVERSATION_DRAFT_SCHEMA_VERSION, workspaceId, tabId, savedAt,
    local: structuredClone(local), base: structuredClone(base)};
  try {
    const previousRaw = target.localStorage.getItem(key);
    const previous = parse(previousRaw);
    if (previousRaw !== null && (!envelope(previous, workspaceId) || previous.tabId !== tabId)) {
      preserveRawDraft(workspaceId, previousRaw, target);
    }
    target.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    return {ok: false, warning: "浏览器存储不可用，当前草稿无法保留；请先复制重要内容。"};
  }
  try {
    const previous = parse(target.localStorage.getItem(conversationDraftRecoveryKey(workspaceId)));
    const index: RecoveryIndex = recovery(previous) ? previous : {version: CONVERSATION_DRAFT_SCHEMA_VERSION, slots: {}};
    index.slots[tabId] = {key, savedAt};
    target.localStorage.setItem(conversationDraftRecoveryKey(workspaceId), JSON.stringify(index));
    automaticallyCleanupDrafts(workspaceId, target);
    return {ok: true, warning: ""};
  } catch {
    return {ok: true, warning: "草稿已保留在当前标签页，但跨标签恢复索引未能更新。"};
  }
}
