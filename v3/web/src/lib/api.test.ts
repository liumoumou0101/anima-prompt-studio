import {beforeEach, describe, expect, it, vi} from "vitest";
import {apiRequest, initializeApp, resetApiClientForTests} from "./api";

const bootstrapPayload = {
  app_version: "3.0.0-test",
  api_version: "v3",
  data_pack: {id: "pack-r1", ready: true, cutoff_mode: "approximate"},
  features: {},
  model_profiles: [],
  settings_summary: {},
};

describe("API bootstrap client", () => {
  beforeEach(() => {
    resetApiClientForTests();
    window.history.replaceState({}, "", "/?bootstrap=one-time-token");
    vi.restoreAllMocks();
  });

  it("exchanges the URL token once, removes it, and loads bootstrap", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({session_token: "session-token"}), {status: 200}))
      .mockResolvedValueOnce(new Response(JSON.stringify(bootstrapPayload), {status: 200}));

    const result = await initializeApp();

    expect(result.data_pack.id).toBe("pack-r1");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v3/session/exchange");
    expect(window.location.search).toBe("");
    expect(sessionStorage.getItem("anima-v3-session")).toBe("session-token");
  });

  it("adds the session header to API requests", async () => {
    sessionStorage.setItem("anima-v3-session", "session-token");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({items: []}), {status: 200}),
    );

    await apiRequest("/api/v3/tags/search?q=maid");

    const request = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(request.headers).get("X-Anima-Session")).toBe("session-token");
  });

  it("restores a new tab using only the remembered same-origin secret", async () => {
    window.history.replaceState({}, "", "/workbench?workspace=draft-1");
    localStorage.setItem("anima-v3-session-recovery", "remembered-secret");
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({session_token: "restored-session", recovery_token: "remembered-secret"})))
      .mockResolvedValueOnce(new Response(JSON.stringify(bootstrapPayload)));
    await initializeApp();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v3/session/restore");
    const request = fetchMock.mock.calls[0][1] as RequestInit;
    expect(request.method).toBe("POST");
    expect(new Headers(request.headers).get("X-Anima-Recovery")).toBe("remembered-secret");
    expect(window.location.search).toBe("?workspace=draft-1");
    expect(sessionStorage.getItem("anima-v3-session")).toBe("restored-session");
  });

  it("recovers idle expiration and retries the original write once without changing its idempotency key", async () => {
    sessionStorage.setItem("anima-v3-session", "expired-session");
    localStorage.setItem("anima-v3-session-recovery", "remembered-secret");
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({error: {code: "session_invalid", message: "expired"}}), {status: 401}))
      .mockResolvedValueOnce(new Response(JSON.stringify({session_token: "restored-session", recovery_token: "remembered-secret"})))
      .mockResolvedValueOnce(new Response(JSON.stringify({id: "run-1"})));
    const body = JSON.stringify({prompt: "kept draft", idempotency_key: "key-1"});
    expect(await apiRequest("/api/v3/generation-runs", {method: "POST", body})).toEqual({id: "run-1"});
    expect(fetchMock).toHaveBeenCalledTimes(3);
    const retried = fetchMock.mock.calls[2][1] as RequestInit;
    expect(retried.body).toBe(body);
    expect(new Headers(retried.headers).get("X-Anima-Session")).toBe("restored-session");
  });

  it("creates a local session from a clean URL without discarding local drafts or query parameters", async () => {
    window.history.replaceState({}, "", "/workbench?workspace=draft-1");
    localStorage.setItem("anima-draft", "unfinished changes");
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({session_token: "local-session", recovery_token: "local-recovery"})))
      .mockResolvedValueOnce(new Response(JSON.stringify(bootstrapPayload)));
    await expect(initializeApp()).resolves.toEqual(bootstrapPayload);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v3/session/local");
    const request = fetchMock.mock.calls[0][1] as RequestInit;
    expect(request.method).toBe("POST");
    expect(request.body).toBe("{}");
    expect(new Headers(request.headers).get("Content-Type")).toBe("application/json");
    expect(new Headers(request.headers).get("X-Anima-Local")).toBe("1");
    expect(window.location.search).toBe("?workspace=draft-1");
    expect(sessionStorage.getItem("anima-v3-session")).toBe("local-session");
    expect(localStorage.getItem("anima-v3-session-recovery")).toBe("local-recovery");
    expect(localStorage.getItem("anima-draft")).toBe("unfinished changes");
  });

  it("falls back once to a local session when a remembered recovery credential is invalid", async () => {
    window.history.replaceState({}, "", "/workbench");
    localStorage.setItem("anima-v3-session-recovery", "stale-recovery");
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({error: {code: "session_invalid", message: "expired"}}), {status: 401}))
      .mockResolvedValueOnce(new Response(JSON.stringify({session_token: "rebuilt", recovery_token: "new-recovery"})))
      .mockResolvedValueOnce(new Response(JSON.stringify(bootstrapPayload)));
    await initializeApp();
    expect(fetchMock.mock.calls.map(call => call[0])).toEqual([
      "/api/v3/session/restore", "/api/v3/session/local", "/api/v3/bootstrap",
    ]);
    expect(sessionStorage.getItem("anima-v3-session")).toBe("rebuilt");
    expect(localStorage.getItem("anima-v3-session-recovery")).toBe("new-recovery");
  });

  it("falls back to a local session after an expired one-time bootstrap credential", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({error: {code: "session_invalid", message: "consumed"}}), {status: 401}))
      .mockResolvedValueOnce(new Response(JSON.stringify({session_token: "local-after-bootstrap", recovery_token: "recovery"})))
      .mockResolvedValueOnce(new Response(JSON.stringify(bootstrapPayload)));
    await initializeApp();
    expect(fetchMock.mock.calls.map(call => call[0])).toEqual([
      "/api/v3/session/exchange", "/api/v3/session/local", "/api/v3/bootstrap",
    ]);
    expect(window.location.search).toBe("");
  });

  it("shares one local rebuild when concurrent requests discover the same failed recovery", async () => {
    window.history.replaceState({}, "", "/");
    sessionStorage.setItem("anima-v3-session", "expired");
    localStorage.setItem("anima-v3-session-recovery", "stale");
    let releaseRestore!: (response: Response) => void;
    const pendingRestore = new Promise<Response>(resolve => {releaseRestore = resolve;});
    const unauthorized = () => new Response(JSON.stringify({error: {code: "session_invalid"}}), {status: 401});
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (path, init) => {
      if (path === "/api/v3/session/restore") return pendingRestore;
      if (path === "/api/v3/session/local") return new Response(JSON.stringify({session_token: "rebuilt", recovery_token: "fresh"}));
      if (new Headers(init?.headers).get("X-Anima-Session") === "expired") return unauthorized();
      return new Response(JSON.stringify({ok: true}));
    });
    const requests = Promise.all([apiRequest("/api/v3/one"), apiRequest("/api/v3/two")]);
    await vi.waitFor(() => expect(fetchMock.mock.calls.filter(call => call[0] === "/api/v3/session/restore")).toHaveLength(1));
    releaseRestore(unauthorized());
    await requests;
    expect(fetchMock.mock.calls.filter(call => call[0] === "/api/v3/session/local")).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(call => call[0] === "/api/v3/one")).toHaveLength(2);
    expect(fetchMock.mock.calls.filter(call => call[0] === "/api/v3/two")).toHaveLength(2);
  });

  it.each([
    ["a forbidden browser mode", () => Promise.resolve(new Response(JSON.stringify({error: {code: "local_session_unavailable", message: "desktop only"}}), {status: 403})), "local_session_unavailable"],
    ["a server failure", () => Promise.resolve(new Response(JSON.stringify({error: {code: "local_session_failed", message: "temporarily unavailable", retryable: true}}), {status: 503})), "local_session_failed"],
    ["a network failure", () => Promise.reject(new TypeError("offline")), "network_error"],
  ])("does not loop local-session acquisition after %s", async (_label, result, code) => {
    window.history.replaceState({}, "", "/");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementationOnce(result);
    await expect(initializeApp()).rejects.toMatchObject({code});
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v3/session/local");
  });

  it("upgrades an existing session and shares a recovery request between concurrent requests", async () => {
    window.history.replaceState({}, "", "/");
    sessionStorage.setItem("anima-v3-session", "old-session");
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({session_token: "current", recovery_token: "remembered"})))
      .mockResolvedValueOnce(new Response(JSON.stringify(bootstrapPayload)));
    await initializeApp();
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get("X-Anima-Session")).toBe("old-session");
    expect(localStorage.getItem("anima-v3-session-recovery")).toBe("remembered");

    sessionStorage.removeItem("anima-v3-session");
    fetchMock.mockReset().mockImplementation(async (path) => new Response(JSON.stringify(
      path === "/api/v3/session/restore" ? {session_token: "new", recovery_token: "remembered"} : {items: []},
    )));
    await Promise.all([apiRequest("/api/v3/one"), apiRequest("/api/v3/two")]);
    expect(fetchMock.mock.calls.filter(call => call[0] === "/api/v3/session/restore")).toHaveLength(1);
  });

  it("can retry initialization after a temporary connection failure and cannot leak tokens to another origin", async () => {
    window.history.replaceState({}, "", "/");
    localStorage.setItem("anima-v3-session-recovery", "remembered");
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockResolvedValueOnce(new Response(JSON.stringify({session_token: "new", recovery_token: "remembered"})))
      .mockResolvedValueOnce(new Response(JSON.stringify(bootstrapPayload)));
    await expect(initializeApp()).rejects.toMatchObject({code: "network_error"});
    await expect(initializeApp()).resolves.toEqual(bootstrapPayload);
    await expect(apiRequest("http://127.0.0.1:33333/api/v3/bootstrap")).rejects.toMatchObject({code: "invalid_request"});
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("retains an unexchanged bootstrap credential in memory for connection retries", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockResolvedValueOnce(new Response(JSON.stringify({session_token: "new", recovery_token: "remembered"})))
      .mockResolvedValueOnce(new Response(JSON.stringify(bootstrapPayload)));
    await expect(initializeApp()).rejects.toMatchObject({code: "network_error"});
    expect(window.location.search).toBe("");
    await expect(initializeApp()).resolves.toEqual(bootstrapPayload);
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({bootstrap_token: "one-time-token"});
  });

  it("reuses a recovered token when a slower parallel 401 arrives, and executes each business write once", async () => {
    sessionStorage.setItem("anima-v3-session", "expired");
    localStorage.setItem("anima-v3-session-recovery", "remembered");
    let releaseSlow!: (response: Response) => void;
    const slowResponse = new Promise<Response>(resolve => { releaseSlow = resolve; });
    const executed: string[] = [];
    const unauthorized = () => new Response(JSON.stringify({error: {code: "session_invalid"}}), {status: 401});
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (path, init) => {
      if (path === "/api/v3/session/restore") return new Response(JSON.stringify({session_token: "recovered", recovery_token: "remembered"}));
      if (new Headers(init?.headers).get("X-Anima-Session") === "expired") {
        return path === "/api/v3/slow" ? slowResponse : unauthorized();
      }
      executed.push(String(init?.body));
      return new Response(JSON.stringify({ok: true}));
    });
    const first = apiRequest("/api/v3/fast", {method: "POST", body: '{"idempotency_key":"fast"}'});
    const second = apiRequest("/api/v3/slow", {method: "POST", body: '{"idempotency_key":"slow"}'});
    await first;
    releaseSlow(unauthorized());
    await second;
    expect(fetchMock.mock.calls.filter(call => call[0] === "/api/v3/session/restore")).toHaveLength(1);
    expect(executed).toEqual(['{"idempotency_key":"fast"}', '{"idempotency_key":"slow"}']);
  });

  it("does not repeat a business rejection or erase a valid local session", async () => {
    sessionStorage.setItem("anima-v3-session", "valid");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(
      JSON.stringify({error: {code: "service_credential_rejected", message: "upstream rejected"}}), {status: 401},
    ));
    await expect(apiRequest("/api/v3/service-action", {method: "POST", body: "{}"})).rejects.toMatchObject({code: "service_credential_rejected"});
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem("anima-v3-session")).toBe("valid");
  });

  it.each(["session_invalid", "service_credential_rejected"])("stops after one retry when the result is %s", async code => {
    sessionStorage.setItem("anima-v3-session", "expired");
    localStorage.setItem("anima-v3-session-recovery", "remembered");
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({error: {code: "session_invalid"}}), {status: 401}))
      .mockResolvedValueOnce(new Response(JSON.stringify({session_token: "recovered", recovery_token: "remembered"})))
      .mockResolvedValueOnce(new Response(JSON.stringify({error: {code}}), {status: 401}));
    await expect(apiRequest("/api/v3/action", {method: "POST", body: "{}"})).rejects.toMatchObject({code});
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(sessionStorage.getItem("anima-v3-session")).toBe(code === "session_invalid" ? null : "recovered");
  });
});
