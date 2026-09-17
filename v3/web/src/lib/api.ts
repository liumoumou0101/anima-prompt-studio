import type {ApiErrorPayload, BootstrapResponse} from "./types";

const SESSION_KEY = "anima-v3-session";
const RECOVERY_KEY = "anima-v3-session-recovery";
let initialization: Promise<BootstrapResponse> | null = null;
let recovery: Promise<void> | null = null;
let pendingBootstrap: string | null = null;
type SessionResponse = {session_token: string; recovery_token?: string};

export class ApiClientError extends Error {
  readonly code: string;
  readonly requestId?: string;
  readonly retryable: boolean;

  constructor(message: string, code = "network_error", requestId?: string, retryable = false) {
    super(message);
    this.name = "ApiClientError";
    this.code = code;
    this.requestId = requestId;
    this.retryable = retryable;
  }
}

export function initializeApp(): Promise<BootstrapResponse> {
  if (!initialization) initialization = initializeAppOnce().catch(error => {
    initialization = null;
    throw error;
  });
  return initialization;
}

export function resetApiClientForTests(): void {
  initialization = null;
  recovery = null;
  pendingBootstrap = null;
  sessionStorage.removeItem(SESSION_KEY);
  localStorage.removeItem(RECOVERY_KEY);
}

function recoveryToken(): string | null {
  // Some private browser modes disallow persistent storage. Existing sessions
  // still work there; the desktop entry remains the fallback after closing.
  try { return localStorage.getItem(RECOVERY_KEY); } catch { return null; }
}

function rememberSession(payload: SessionResponse): void {
  sessionStorage.setItem(SESSION_KEY, payload.session_token);
  if (payload.recovery_token) {
    try { localStorage.setItem(RECOVERY_KEY, payload.recovery_token); } catch { /* session-only browser */ }
  }
}

async function restoreSession(): Promise<void> {
  if (!recovery) recovery = restoreSessionOnce().finally(() => { recovery = null; });
  return recovery;
}

async function restoreSessionOnce(): Promise<void> {
  const remembered = recoveryToken();
  const current = sessionStorage.getItem(SESSION_KEY);
  if (!remembered && !current) {
    await createLocalSession();
    return;
  }
  const headers = new Headers({"Content-Type": "application/json"});
  if (remembered) headers.set("X-Anima-Recovery", remembered);
  if (current) headers.set("X-Anima-Session", current);
  const response = await fetchLocal("/api/v3/session/restore", {method: "POST", headers, body: "{}"});
  if (response.status === 401) {
    if (sessionStorage.getItem(SESSION_KEY) === current) sessionStorage.removeItem(SESSION_KEY);
    try { if (recoveryToken() === remembered) localStorage.removeItem(RECOVERY_KEY); } catch { /* storage unavailable */ }
    await createLocalSession();
    return;
  }
  rememberSession(await parseResponse<SessionResponse>(response));
}

async function createLocalSession(): Promise<void> {
  const response = await fetchLocal("/api/v3/session/local", {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-Anima-Local": "1"},
    body: "{}",
  });
  rememberSession(await parseResponse<SessionResponse>(response));
}

async function initializeAppOnce(): Promise<BootstrapResponse> {
  const url = new URL(window.location.href);
  const bootstrap = url.searchParams.get("bootstrap") || pendingBootstrap;
  if (bootstrap) {
    pendingBootstrap = bootstrap;
    // Remove one-time credentials before any subsequent navigation or fetch.
    url.searchParams.delete("bootstrap");
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
    const response = await fetchLocal("/api/v3/session/exchange", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({bootstrap_token: bootstrap}),
    });
    if (response.ok || response.status === 401) pendingBootstrap = null;
    if (response.status === 401) {
      await restoreSession();
    } else {
      rememberSession(await parseResponse<SessionResponse>(response));
    }
  } else if (sessionStorage.getItem(SESSION_KEY) && !recoveryToken()) {
    // Upgrade an existing tab's pre-recovery session without losing its draft.
    await restoreSession();
  }
  if (!sessionStorage.getItem(SESSION_KEY)) {
    await restoreSession();
  }
  return apiRequest<BootstrapResponse>("/api/v3/bootstrap");
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (!sessionStorage.getItem(SESSION_KEY)) await restoreSession();
  const headers = new Headers(init.headers);
  const sentToken = sessionStorage.getItem(SESSION_KEY)!;
  headers.set("X-Anima-Session", sentToken);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  let response = await fetchLocal(path, {...init, headers});
  if (response.status === 401) {
    const error = await response.clone().json() as ApiErrorPayload;
    if (error.error?.code === "session_invalid") {
      // Authentication failed before the route ran. Restore and retry once,
      // retaining the original body and idempotency key for queued operations.
      // A slower parallel response can arrive after another request already
      // recovered. Reuse that credential instead of rotating yet again.
      if (!sessionStorage.getItem(SESSION_KEY) || sessionStorage.getItem(SESSION_KEY) === sentToken) await restoreSession();
      headers.set("X-Anima-Session", sessionStorage.getItem(SESSION_KEY)!);
      response = await fetchLocal(path, {...init, headers});
      if (response.status === 401) {
        const retryError = await response.clone().json() as ApiErrorPayload;
        if (retryError.error?.code === "session_invalid" && sessionStorage.getItem(SESSION_KEY) === headers.get("X-Anima-Session")) {
          sessionStorage.removeItem(SESSION_KEY);
        }
      }
    }
  }
  return parseResponse<T>(response);
}

async function fetchLocal(path: string, init: RequestInit): Promise<Response> {
  if (new URL(path, window.location.href).origin !== window.location.origin) {
    throw new ApiClientError("本地 API 请求不能发送到其他服务。", "invalid_request");
  }
  try {
    return await fetch(path, {...init, credentials: "same-origin"});
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    if (error instanceof Error && error.name === "AbortError") throw error;
    throw new ApiClientError("无法连接本地服务。请确认应用仍在运行。", "network_error", undefined, true);
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T;
  const payload = (await response.json()) as T | ApiErrorPayload;
  if (!response.ok) {
    const apiError = payload as ApiErrorPayload;
    throw new ApiClientError(
      apiError.error?.message || `请求失败（${response.status}）`,
      apiError.error?.code || "request_failed",
      apiError.error?.request_id,
      apiError.error?.retryable || false,
    );
  }
  return payload as T;
}
