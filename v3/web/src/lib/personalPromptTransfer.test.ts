import {beforeEach, expect, it, vi} from "vitest";
import {storePersonalPromptTransfer, readPersonalPromptTransfer, consumePersonalPromptTransfer} from "./personalPromptTransfer";

beforeEach(() => localStorage.clear());
it("round trips raw fragments through an opaque URL and consumes only explicitly", () => {
  const value = {positive: "  Blue_Sky,\n(Cat:1.2) ", negative: "LOW_quality,\n blur "};
  const url = storePersonalPromptTransfer(value);
  expect(url).toMatch(/^\/workbench\?personal_transfer=[\w-]+$/);
  const id = new URL(url, "http://localhost").searchParams.get("personal_transfer")!;
  expect(readPersonalPromptTransfer(id)).toMatchObject({...value, id, version: 1});
  expect(readPersonalPromptTransfer(id)).not.toBeNull();
  consumePersonalPromptTransfer(id);
  expect(readPersonalPromptTransfer(id)).toBeNull();
});
it.each([{positive: " ", negative: "\n"}, {positive: "x".repeat(20001), negative: ""}, {positive: "a", negative: "x".repeat(20001)}])("rejects invalid payload without storing it", value => {
  expect(() => storePersonalPromptTransfer(value)).toThrow();
  expect(localStorage.length).toBe(0);
});
it("accepts negative-only and exact length limits", () => {
  const url = storePersonalPromptTransfer({positive: "", negative: "x".repeat(20000)});
  expect(readPersonalPromptTransfer(url.split("=")[1])?.negative).toHaveLength(20000);
});
it.each(["{bad", JSON.stringify({version: 2, id: "test", positive: "x", negative: ""}), JSON.stringify({version: 1, id: "other", positive: "x", negative: ""}), JSON.stringify({version: 1, id: "test", positive: 5, negative: ""})])("rejects corrupted records and preserves them for recovery", raw => {
  localStorage.setItem("anima-personal-prompt-transfer:test", raw);
  expect(() => readPersonalPromptTransfer("test")).toThrow();
  expect(localStorage.getItem("anima-personal-prompt-transfer:test")).toBe(raw);
});
it("reports storage failure without returning a success URL", () => {
  const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {throw new Error("quota");});
  expect(() => storePersonalPromptTransfer({positive: "cat", negative: ""})).toThrow();
  spy.mockRestore();
});
