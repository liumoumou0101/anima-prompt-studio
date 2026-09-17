import {useEffect, useRef, useState} from "react";
import {apiRequest} from "../lib/api";

type SyncStatusName = "idle" | "scanning" | "ready" | "missing" | "error";
type SyncStatus = {
  status: SyncStatusName;
  run_id: number;
  counts: {created: number; updated: number; unchanged: number; deleted_preserved: number};
  total: number;
  message: string;
  completed_at: string | null;
};

const endpoint = "/api/v3/reference-examples/local-sync";
const statuses = new Set<SyncStatusName>(["idle", "scanning", "ready", "missing", "error"]);

function parseStatus(value: unknown): SyncStatus | null {
  if (!value || typeof value !== "object") return null;
  const item = value as Partial<SyncStatus>;
  const counts = item.counts as Partial<SyncStatus["counts"]> | undefined;
  const numbers = [item.run_id, item.total, counts?.created, counts?.updated, counts?.unchanged, counts?.deleted_preserved];
  if (!statuses.has(item.status as SyncStatusName) || numbers.some(number => typeof number !== "number" || !Number.isFinite(number) || number < 0)
      || typeof item.message !== "string" || (item.completed_at !== null && typeof item.completed_at !== "string")) return null;
  return item as SyncStatus;
}

function statusText(status: SyncStatus | null, error: string): string {
  if (error) return error;
  if (!status) return "正在读取本地案例扫描状态…";
  if (status.status === "scanning") return "正在扫描本地案例…";
  if (status.status === "missing") return "未找到本地参考案例目录。应用仍可正常使用，你可以稍后重试扫描。";
  if (status.status === "error") return `本地案例扫描失败：${status.message || "未能完成扫描"}。可以重新扫描重试。`;
  if (status.status === "idle") return "本地案例扫描尚未开始。";
  const existing = status.counts.updated + status.counts.unchanged;
  return `新增 ${status.counts.created} · 已有 ${existing} · 保留已删除 ${status.counts.deleted_preserved} · 共 ${status.total} 条`;
}

export function ReferenceLocalSync({onCompleted, pollMs = 1000}: {onCompleted: (runId: number) => void; pollMs?: number}) {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const startingRef = useRef(false);
  const scanningRun = useRef<number | null>(null);
  const completedRuns = useRef(new Set<number>());
  const completedCallback = useRef(onCompleted);
  completedCallback.current = onCompleted;

  function accept(value: unknown): void {
    const parsed = parseStatus(value);
    if (!parsed) {
      setError("无法读取本地案例扫描状态，请重试。");
      setStatus(null);
      return;
    }
    setError("");
    setStatus({...parsed, counts: {...parsed.counts}});
  }

  useEffect(() => {
    const controller = new AbortController();
    void apiRequest<unknown>(endpoint, {signal: controller.signal}).then(accept).catch(cause => {
      if (!controller.signal.aborted) {
        setStatus(null);
        setError(`${cause instanceof Error ? cause.message : "无法读取本地案例扫描状态。"} 可以重新扫描重试。`);
      }
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (status?.status !== "scanning") return;
    scanningRun.current = status.run_id;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void apiRequest<unknown>(endpoint, {signal: controller.signal}).then(accept).catch(cause => {
        if (!controller.signal.aborted) {
          setStatus(null);
          setError(`${cause instanceof Error ? cause.message : "本地案例扫描状态读取失败。"} 可以重新扫描重试。`);
        }
      });
    }, pollMs);
    return () => {window.clearTimeout(timer); controller.abort();};
  }, [status, pollMs]);

  useEffect(() => {
    if (status?.status !== "ready" || completedRuns.current.has(status.run_id)) return;
    const changed = status.counts.created + status.counts.updated + status.counts.deleted_preserved > 0;
    if (scanningRun.current !== status.run_id && !changed) return;
    completedRuns.current.add(status.run_id);
    scanningRun.current = null;
    completedCallback.current(status.run_id);
  }, [status]);

  async function start(): Promise<void> {
    if (startingRef.current || status?.status === "scanning") return;
    startingRef.current = true; setStarting(true); setError("");
    try {
      const value = await apiRequest<unknown>(endpoint, {method: "POST", body: "{}"});
      const parsed = parseStatus(value);
      if (parsed) scanningRun.current = parsed.run_id;
      accept(value);
    } catch (cause) {
      setStatus(null);
      setError(`${cause instanceof Error ? cause.message : "本地案例扫描启动失败。"} 可以重新扫描重试。`);
    } finally {
      startingRef.current = false; setStarting(false);
    }
  }

  const scanning = status?.status === "scanning";
  return <section className="reference-local-sync" aria-label="本地案例同步">
    <div aria-live="polite">{statusText(status, error)}</div>
    <button type="button" disabled={starting || scanning} onClick={() => void start()}>重新扫描本地案例</button>
  </section>;
}
