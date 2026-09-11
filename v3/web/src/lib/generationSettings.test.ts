import {expect, it} from "vitest";
import {applyGenerationRecipe, defaultGenerationSettings, markGenerationCustom, resolvedGenerationSettings, seedInput, validSeed} from "./generationSettings";
import type {GenerationTarget} from "./types";

const target = {
  remote_profile_id: "remote", workflow_profile_id: "workflow", default_recipe_id: "new",
  generation_recipes: [{id: "new", parameters: {steps: 10, cfg: 1, sampler: "er_sde", scheduler: "simple"}}],
} as GenerationTarget;

it("preserves pasted 64-bit seed through settings and request JSON", () => {
  const seed = "8798399215689017476";
  const settings = {...defaultGenerationSettings(), seed: seedInput(seed)};
  expect(JSON.parse(JSON.stringify(resolvedGenerationSettings(settings))).seed).toBe(seed);
  expect(seedInput("20260912")).toBe(20260912);
  expect(seedInput("-1")).toBe(-1);
});

it("validates fixed comparison seeds without using floating point", () => {
  expect(validSeed("8798399215689017476", false)).toBe(true);
  expect(validSeed("9223372036854775808", false)).toBe(false);
  expect(validSeed(9007199254740992, false)).toBe(false);
  expect(validSeed("-1", false)).toBe(false);
  expect(validSeed("-1")).toBe(true);
  expect(validSeed("1e9")).toBe(false);
});

it("keeps manual edits when a target is resolved or changed", () => {
  const settings = markGenerationCustom(defaultGenerationSettings(), {steps: 47, cfg: 6.25, scheduler: "normal"});
  expect(resolvedGenerationSettings(applyGenerationRecipe(settings, target))).toMatchObject({steps: 47, cfg: 6.25, scheduler: "normal"});
});

it("uses recipe values when the user explicitly selects a recipe", () => {
  const settings = markGenerationCustom(defaultGenerationSettings(), {steps: 47});
  expect(applyGenerationRecipe(settings, target, "new")).toMatchObject({preset_id: "new", steps: 10, cfg: 1});
});

it("preserves saved parameters under an obsolete recipe label", () => {
  const settings = {...defaultGenerationSettings(), preset_id: "quality", workflow_profile_id: "old", steps: 47, cfg: 6.25};
  expect(applyGenerationRecipe(settings, target)).toMatchObject({preset_id: "custom", steps: 47, cfg: 6.25});
});

it("initializes a fresh target with its V3 default recipe", () => {
  expect(applyGenerationRecipe(defaultGenerationSettings(), target)).toMatchObject({preset_id: "new", steps: 10, cfg: 1});
});
