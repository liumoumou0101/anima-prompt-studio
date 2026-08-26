import type {ApiErrorPayload, BootstrapResponse} from "./types";

const SESSION_KEY = "anima-v3-session";
let initialization: Promise<BootstrapResponse> | null = null;

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
  if (!initialization) initialization = initializeAppOnce();
  return initialization;
}

export function resetApiClientForTests(): void {
  initialization = null;
  sessionStorage.removeItem(SESSION_KEY);
}

async function initializeAppOnce(): Promise<BootstrapResponse> {
  const url = new URL(window.location.href);
  const bootstrap = url.searchParams.get("bootstrap");
  if (bootstrap) {
    const response = await fetch("/api/v3/session/exchange", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({bootstrap_token: bootstrap}),
    });
    const payload = await parseResponse<{session_token: string}>(response);
    sessionStorage.setItem(SESSION_KEY, payload.session_token);
    url.searchParams.delete("bootstrap");
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
  }
  if (!sessionStorage.getItem(SESSION_KEY)) {
    throw new ApiClientError("缺少启动会话。请从 ANIMA Prompt Studio 桌面入口重新打开。", "session_invalid");
  }
  return apiRequest<BootstrapResponse>("/api/v3/bootstrap");
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = sessionStorage.getItem(SESSION_KEY);
  if (!token) throw new ApiClientError("本地会话已经失效，请重新打开应用。", "session_invalid");
  const headers = new Headers(init.headers);
  headers.set("X-Anima-Session", token);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(path, {...init, headers});
  } catch {
    throw new ApiClientError("无法连接本地服务。请确认应用仍在运行。", "network_error", undefined, true);
  }
  if (response.status === 401) sessionStorage.removeItem(SESSION_KEY);
  return parseResponse<T>(response);
}

async function parseResponse<T>(response: Response): Promise<T> {
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
