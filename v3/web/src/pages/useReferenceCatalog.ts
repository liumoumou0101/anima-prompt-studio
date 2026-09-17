import {useCallback, useEffect, useMemo, useRef, useState} from "react";
import {ApiClientError, apiRequest} from "../lib/api";

export type ReferenceCatalogFilters = {q: string; origin?: string; model?: string; artist?: string; dependency?: string; contentLevel?: string};
export type ReferenceCatalogPage<T> = {items: T[]; next_cursor: string | null; official_pack: {ready: boolean}; total: number};
export type ReferenceCatalogError = {message: string; phase: "first" | "more"; cursorConflict: boolean};

function aborted(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

function normalizedPage<T>(value: ReferenceCatalogPage<T>): ReferenceCatalogPage<T> {
  return {...value, total: typeof value.total === "number" ? value.total : value.items.length};
}

export function useReferenceCatalog<T extends {id: string}>({enabled, filters}: {enabled: boolean; filters: ReferenceCatalogFilters}) {
  const paramsString = useMemo(() => new URLSearchParams({q: filters.q, limit: "20",
    ...(filters.origin ? {origin: filters.origin} : {}), ...(filters.model ? {model: filters.model} : {}),
    ...(filters.artist ? {artist: filters.artist} : {}), ...(filters.dependency ? {lora_dependency: filters.dependency} : {}),
    ...(filters.contentLevel ? {content: filters.contentLevel} : {})}).toString(),
  [filters.q, filters.origin, filters.model, filters.artist, filters.dependency, filters.contentLevel]);
  const [page, setPageState] = useState<ReferenceCatalogPage<T> | null>(null);
  const [loadingFirst, setLoadingFirst] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setErrorState] = useState<ReferenceCatalogError | null>(null);
  const generation = useRef(0);
  const pageRef = useRef<ReferenceCatalogPage<T> | null>(null);
  const errorRef = useRef<ReferenceCatalogError | null>(null);
  const paramsRef = useRef(paramsString);
  const firstController = useRef<AbortController | null>(null);
  const moreController = useRef<AbortController | null>(null);
  const moreCursor = useRef<string | null>(null);
  paramsRef.current = paramsString;

  const setPage = useCallback((next: ReferenceCatalogPage<T> | null) => {pageRef.current = next; setPageState(next);}, []);
  const setError = useCallback((next: ReferenceCatalogError | null) => {errorRef.current = next; setErrorState(next);}, []);

  const fetchFirst = useCallback(async () => {
    if (!enabled) return;
    const requestGeneration = ++generation.current;
    firstController.current?.abort(); moreController.current?.abort(); moreCursor.current = null;
    const controller = new AbortController(); firstController.current = controller;
    setPage(null); setError(null); setLoadingFirst(true); setLoadingMore(false);
    try {
      const next = normalizedPage(await apiRequest<ReferenceCatalogPage<T>>(`/api/v3/reference-examples?${paramsString}`, {signal: controller.signal}));
      if (!controller.signal.aborted && generation.current === requestGeneration) setPage(next);
    } catch (cause) {
      if (!controller.signal.aborted && generation.current === requestGeneration && !aborted(cause))
        setError({message: cause instanceof Error ? cause.message : "无法读取参考案例。", phase: "first", cursorConflict: false});
    } finally {
      if (generation.current === requestGeneration) setLoadingFirst(false);
    }
  }, [enabled, paramsString, setError, setPage]);

  const loadMore = useCallback(async (explicit = false) => {
    const current = pageRef.current;
    const cursor = current?.next_cursor;
    if (!enabled || !cursor || moreCursor.current || (errorRef.current?.phase === "more" && !explicit)) return;
    const requestGeneration = generation.current;
    moreCursor.current = cursor; setLoadingMore(true);
    if (explicit) setError(null);
    const controller = new AbortController(); moreController.current = controller;
    try {
      const join = paramsRef.current ? `${paramsRef.current}&cursor=${encodeURIComponent(cursor)}` : `cursor=${encodeURIComponent(cursor)}`;
      const next = normalizedPage(await apiRequest<ReferenceCatalogPage<T>>(`/api/v3/reference-examples?${join}`, {signal: controller.signal}));
      if (controller.signal.aborted || generation.current !== requestGeneration || paramsRef.current !== paramsString) return;
      const latest = pageRef.current;
      if (!latest) return;
      const ids = new Set(latest.items.map(item => item.id));
      const merged = [...latest.items, ...next.items.filter(item => !ids.has(item.id))];
      setPage({...next, items: merged, total: next.total}); setError(null);
    } catch (cause) {
      if (!controller.signal.aborted && generation.current === requestGeneration && !aborted(cause)) {
        const apiError = cause instanceof ApiClientError ? cause : null;
        setError({message: cause instanceof Error ? cause.message : "无法读取更多案例。", phase: "more",
          cursorConflict: apiError?.code === "reference_version_conflict"});
      }
    } finally {
      if (moreController.current === controller && moreCursor.current === cursor) {
        moreCursor.current = null;
        if (generation.current === requestGeneration) setLoadingMore(false);
      }
    }
  }, [enabled, paramsString, setError, setPage]);

  const retry = useCallback(async () => {
    if (errorRef.current?.phase === "more" && !errorRef.current.cursorConflict) await loadMore(true);
    else await fetchFirst();
  }, [fetchFirst, loadMore]);

  useEffect(() => {
    if (enabled) void fetchFirst();
    else {firstController.current?.abort(); moreController.current?.abort();}
    return () => {firstController.current?.abort(); moreController.current?.abort();};
  }, [enabled, fetchFirst]);

  return {page, loadingFirst, loadingMore, error, refresh: fetchFirst, loadMore, retry};
}
