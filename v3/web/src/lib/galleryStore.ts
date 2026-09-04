import {apiRequest} from "./api";
import type {GalleryResponse} from "./types";

export type GalleryUpdateReason = "initial" | "background" | "manual" | "generation" | "mutation";

export interface GalleryUpdate {
  data: GalleryResponse;
  added: number;
  reason: GalleryUpdateReason;
}

type GalleryListener = (update: GalleryUpdate) => void;

let snapshot: GalleryResponse | null = null;
let normalRequest: Promise<GalleryResponse> | null = null;
let refreshRequest: Promise<GalleryResponse> | null = null;
let requestSequence = 0;
let appliedSequence = 0;
const listeners = new Set<GalleryListener>();

export function getGallerySnapshot(): GalleryResponse | null {
  return snapshot;
}

export function subscribeGallery(listener: GalleryListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export async function loadGallery(options: {refresh?: boolean; reason?: GalleryUpdateReason} = {}): Promise<GalleryResponse> {
  const refresh = Boolean(options.refresh);
  const reason = options.reason || (refresh ? "background" : "initial");
  const existing = refresh ? refreshRequest : normalRequest;
  if (existing) return existing;

  const sequence = ++requestSequence;
  const path = `/api/v3/gallery/assets?limit=1000${refresh ? "&refresh=true" : ""}`;
  const request = apiRequest<GalleryResponse>(path).then((next) => {
    if (sequence >= appliedSequence) {
      const previousPaths = new Set(snapshot?.items.map((item) => item.path) || []);
      const added = snapshot ? next.items.filter((item) => !previousPaths.has(item.path)).length : 0;
      snapshot = next;
      appliedSequence = sequence;
      listeners.forEach((listener) => listener({data: next, added, reason}));
    }
    return snapshot || next;
  }).finally(() => {
    if (refresh) refreshRequest = null;
    else normalRequest = null;
  });

  if (refresh) refreshRequest = request;
  else normalRequest = request;
  return request;
}

export async function primeGallery(): Promise<void> {
  const first = await loadGallery({reason: "initial"});
  const indexedAt = first.indexed_at ? Date.parse(first.indexed_at) : Number.NaN;
  if (Number.isFinite(indexedAt) && Date.now() - indexedAt < 15_000) return;
  await loadGallery({refresh: true, reason: "background"});
}

export function patchGallerySnapshot(update: (current: GalleryResponse) => GalleryResponse): void {
  if (!snapshot) return;
  snapshot = update(snapshot);
  listeners.forEach((listener) => listener({data: snapshot as GalleryResponse, added: 0, reason: "mutation"}));
}

export function resetGalleryStoreForTests(): void {
  snapshot = null;
  normalRequest = null;
  refreshRequest = null;
  requestSequence = 0;
  appliedSequence = 0;
  listeners.clear();
}
