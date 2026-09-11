import {expect, it} from "vitest";
import {negativeGuidance, appendNegative} from "./negativeGuidance";

it("keeps model-specific guidance separate from manually reviewed negatives", () => {
  expect(negativeGuidance("anima_base_v1").text).toContain("score_1");
  expect(negativeGuidance("anima_aesthetic_v1_1").text).not.toContain("score_");
  expect(negativeGuidance("anima_turbo_v1_1").text).toBe("");
  expect(negativeGuidance("animayume_v1_0_final").text).toBe("");
  expect(negativeGuidance("miaomiao_harem_anima_v1_6").text).toContain("shiny skin");
  const custom = "text, BLURRY, (bad hands:1.2)";
  const added = appendNegative(custom, "blurry, jpeg artifacts");
  expect(added).toBe(custom + ", jpeg artifacts");
  expect(appendNegative(added, "blurry, jpeg artifacts")).toBe(added);
});
