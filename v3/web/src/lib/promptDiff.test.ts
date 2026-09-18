import {describe, expect, it} from "vitest";
import {diffPrompt} from "./promptDiff";

const beforeText = (parts: ReturnType<typeof diffPrompt>) => parts.filter(part => part.kind !== "added").map(part => part.text).join("");
const afterText = (parts: ReturnType<typeof diffPrompt>) => parts.filter(part => part.kind !== "removed").map(part => part.text).join("");

describe("diffPrompt", () => {
  it("returns one same chunk for unchanged text", () => {
    expect(diffPrompt("蓝色外套", "蓝色外套")).toEqual([{kind: "same", text: "蓝色外套"}]);
  });

  it("keeps Chinese and punctuation changes readable", () => {
    const parts = diffPrompt("蓝色外套。", "红色外套！");
    expect(beforeText(parts)).toBe("蓝色外套。");
    expect(afterText(parts)).toBe("红色外套！");
    expect(parts).toContainEqual({kind: "same", text: "色外套"});
    expect(parts).toContainEqual({kind: "removed", text: "蓝"});
    expect(parts).toContainEqual({kind: "added", text: "红"});
  });

  it("shows swapped words without losing either source", () => {
    const parts = diffPrompt("red blue", "blue red");
    expect(beforeText(parts)).toBe("red blue");
    expect(afterText(parts)).toBe("blue red");
    expect(parts.some(part => part.kind === "added")).toBe(true);
    expect(parts.some(part => part.kind === "removed")).toBe(true);
  });

  it("bounds work for 20k inputs while preserving exact reconstruction", () => {
    const before = "甲".repeat(10_000) + "蓝" + "乙".repeat(9_999);
    const after = "甲".repeat(10_000) + "红" + "乙".repeat(9_999);
    const parts = diffPrompt(before, after);
    expect(beforeText(parts)).toBe(before);
    expect(afterText(parts)).toBe(after);
    expect(parts.length).toBeLessThanOrEqual(5);
  });
});
