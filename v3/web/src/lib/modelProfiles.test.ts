import {expect, it} from "vitest";
import {modelProfileChoices, resolveLegacyAesthetic, LEGACY_AESTHETIC} from "./modelProfiles";
import {defaultGenerationSettings} from "./generationSettings";
import type {GenerationTarget} from "./types";

it("offers distinct Aesthetic versions even with an old bootstrap catalog", () => {
  const ids = modelProfileChoices([{id:LEGACY_AESTHETIC, display_name:"旧版美学", variant:"aesthetic"}]).map(p=>p.id);
  expect(ids).toEqual(["anima_aesthetic_v1_0", "anima_aesthetic_v1_1"]);
});

it.each(["anima_aesthetic_v1_0", "anima_aesthetic_v1_1"])("recovers %s only from the saved target", model => {
  const settings = {...defaultGenerationSettings(), remote_profile_id:"server", workflow_profile_id:"old-import"};
  const targets = [{remote_profile_id:"server", workflow_profile_id:"old-import", compatible_model_profiles:[model]}] as GenerationTarget[];
  expect(resolveLegacyAesthetic(LEGACY_AESTHETIC,settings,targets)).toEqual({model,target:targets[0]});
  expect(resolveLegacyAesthetic(LEGACY_AESTHETIC,{...settings,workflow_profile_id:"missing"},targets)).toBeUndefined();
  expect(resolveLegacyAesthetic(LEGACY_AESTHETIC,{...settings,remote_profile_id:"other-server"},targets)).toBeUndefined();
});

it("does not guess a legacy Aesthetic version from a workflow shared by both versions", () => {
  const settings = {...defaultGenerationSettings(),remote_profile_id:"server",workflow_profile_id:"shared"};
  const targets = [{remote_profile_id:"server",workflow_profile_id:"shared",compatible_model_profiles:["anima_aesthetic_v1_0","anima_aesthetic_v1_1"]}] as GenerationTarget[];
  expect(resolveLegacyAesthetic(LEGACY_AESTHETIC,settings,targets)).toBeUndefined();
});
