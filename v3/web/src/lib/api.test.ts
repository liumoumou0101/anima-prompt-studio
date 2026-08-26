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
});
