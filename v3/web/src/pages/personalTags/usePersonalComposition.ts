import {useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction} from "react";
import {ApiClientError} from "../../lib/api";
import {personalTagsApi, type CompositionItem, type DraftRecord} from "../../lib/personalTags";

export const PERSONAL_COMPOSITION_CACHE_KEY = "anima-personal-composition-draft:v1";
type Cache = {version: 1; baseRevision: number; items: CompositionItem[]};
export type PersonalCompositionSaveState = "loading" | "dirty" | "saving" | "saved" | "error" | "conflict";
export interface PersonalComposition {
  items: CompositionItem[];
  setItems: Dispatch<SetStateAction<CompositionItem[]>>;
  saveState: PersonalCompositionSaveState;
  error: Error | null;
  /** Resolves true only when all edits made before and during this call reached the server. */
  flush: () => Promise<boolean>;
  /** Explicitly discards local edits and loads the current server draft. */
  reload: () => Promise<void>;
}

function readCache(): Cache | null {
  try {
    const raw = localStorage.getItem(PERSONAL_COMPOSITION_CACHE_KEY);
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    if (typeof value !== "object" || value === null) return null;
    const cache = value as Partial<Cache>;
    if (cache.version !== 1 || !Number.isSafeInteger(cache.baseRevision) ||
        !Array.isArray(cache.items)) return null;
    return cache as Cache;
  } catch { return null; }
}

function writeCache(items: CompositionItem[], baseRevision: number): void {
  try { localStorage.setItem(PERSONAL_COMPOSITION_CACHE_KEY, JSON.stringify({version: 1, baseRevision, items})); }
  catch { /* Server saves still work in storage-restricted browsers. */ }
}

function clearMatchingCache(items: CompositionItem[]): void {
  try {
    const cache = readCache();
    if (cache && JSON.stringify(cache.items) === JSON.stringify(items))
      localStorage.removeItem(PERSONAL_COMPOSITION_CACHE_KEY);
  } catch { /* Leave a recoverable copy if storage is unavailable. */ }
}

export function usePersonalComposition(): PersonalComposition {
  const initial = useRef<Cache | null | undefined>(undefined);
  if (initial.current === undefined) initial.current = readCache();
  const [items, updateItems] = useState<CompositionItem[]>(initial.current?.items ?? []);
  const [saveState, updateSaveState] = useState<PersonalCompositionSaveState>("loading");
  const [error, updateError] = useState<Error | null>(null);
  const itemsRef = useRef(items);
  const revision = useRef(initial.current?.baseRevision ?? 0);
  const ready = useRef(false);
  const dirty = useRef(Boolean(initial.current));
  const generation = useRef(0);
  const inFlight = useRef<Promise<boolean> | null>(null);
  const loading = useRef<Promise<void> | null>(null);
  const blocked = useRef(false);
  const mounted = useRef(true);

  const save = useCallback((): Promise<boolean> => {
    if (inFlight.current) return inFlight.current;
    if (!ready.current || blocked.current) return Promise.resolve(false);
    if (!dirty.current) return Promise.resolve(true);
    const run = async (): Promise<boolean> => {
      while (dirty.current && !blocked.current) {
        const snapshot = itemsRef.current.map(item => ({...item}));
        const snapshotGeneration = generation.current;
        if (mounted.current) updateSaveState("saving");
        try {
          const saved = await personalTagsApi.saveDraft(snapshot, revision.current);
          revision.current = saved.revision;
          if (generation.current === snapshotGeneration) {
            dirty.current = false;
            clearMatchingCache(snapshot);
            if (mounted.current) {updateError(null); updateSaveState("saved");}
          } else {
            writeCache(itemsRef.current, revision.current);
          }
        } catch (cause) {
          const failure = cause instanceof Error ? cause : new Error(String(cause));
          const conflict = cause instanceof ApiClientError && cause.code === "revision_conflict";
          blocked.current = conflict;
          if (mounted.current) {
            updateError(failure);
            updateSaveState(conflict ? "conflict" : "error");
          }
          return false;
        }
      }
      return !dirty.current;
    };
    const task = run();
    inFlight.current = task;
    void task.finally(() => {if (inFlight.current === task) inFlight.current = null;});
    return task;
  }, []);

  const setItems = useCallback<Dispatch<SetStateAction<CompositionItem[]>>>(value => {
    const next = (typeof value === "function" ? value(itemsRef.current) : value).map(item => ({...item}));
    itemsRef.current = next;
    generation.current++;
    dirty.current = true;
    writeCache(next, revision.current);
    updateItems(next);
    if (!blocked.current) {updateError(null); updateSaveState(ready.current ? "dirty" : "loading"); void save();}
  }, [save]);

  const load = useCallback(async (discardLocal: boolean) => {
    const before = generation.current;
    if (discardLocal && inFlight.current) await inFlight.current;
    const baseRevision = revision.current;
    ready.current = false;
    if (mounted.current) updateSaveState("loading");
    try {
      const server: DraftRecord = await personalTagsApi.getDraft();
      revision.current = server.revision;
      ready.current = true;
      if (discardLocal && generation.current === before) {
        itemsRef.current = server.items;
        dirty.current = false;
        blocked.current = false;
        clearMatchingCache(itemsRef.current);
        try {localStorage.removeItem(PERSONAL_COMPOSITION_CACHE_KEY);} catch { /* unavailable */ }
        if (mounted.current) {updateItems(server.items); updateError(null); updateSaveState("saved");}
      } else if (dirty.current) {
        if (JSON.stringify(itemsRef.current) === JSON.stringify(server.items)) {
          dirty.current = false;
          clearMatchingCache(itemsRef.current);
          if (mounted.current) {updateError(null); updateSaveState("saved");}
        } else if (baseRevision !== server.revision) {
          blocked.current = true;
          if (mounted.current) {
            updateError(new ApiClientError("Server draft changed since local edits", "revision_conflict",
              undefined, false, {current_revision: server.revision, current: server}));
            updateSaveState("conflict");
          }
        } else {
          writeCache(itemsRef.current, server.revision);
          if (mounted.current) updateSaveState("dirty");
          if (generation.current !== before) void save();
        }
      } else {
        itemsRef.current = server.items;
        if (mounted.current) {updateItems(server.items); updateError(null); updateSaveState("saved");}
      }
    } catch (cause) {
      const failure = cause instanceof Error ? cause : new Error(String(cause));
      if (mounted.current) {updateError(failure); updateSaveState("error");}
    }
  }, [save]);

  useEffect(() => {
    mounted.current = true;
    const task = load(false);
    loading.current = task;
    return () => {mounted.current = false;};
  }, [load]);

  const flush = useCallback(async (): Promise<boolean> => {
    if (loading.current) await loading.current;
    while (dirty.current && !blocked.current) {
      if (!await save()) return false;
    }
    return ready.current && !dirty.current && !blocked.current;
  }, [save]);

  const reload = useCallback(async (): Promise<void> => {await load(true);}, [load]);
  return {items, setItems, saveState, error, flush, reload};
}
