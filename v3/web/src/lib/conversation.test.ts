import {describe, expect, it} from "vitest";
import {defaultGenerationSettings} from "./generationSettings";
import {cleanRequirements, emptyRequirements, editableRequirements, hasUncompiledInputs, hasUnsavedInputs, hasUnsavedRequirementsOrSettings, type ConversationRecord, type LocalConversation} from "./conversation";

function fixture(): {record: ConversationRecord; local: LocalConversation} {
  const requirements = emptyRequirements();
  requirements.layers.subject.text = "蓝色外套";
  const record = {
    id: "workspace_test", title: "test", revision: 3, created_at: "", updated_at: "", candidate_snapshot: null,
    draft: {positive_text: "", excluded_text: "", model_profile: "anima_base_v1", mode: "faithful", requirements: {...requirements, contract: "anima-requirements/1", revision: 1},
      compiled: {positive: "blue coat", negative: "bad hands", compiled_token: "cmp_test", source: "llm"}, compile_state: "fresh",
      conversation_events: [], generation_settings: defaultGenerationSettings()},
  } as ConversationRecord;
  const local: LocalConversation = {baseRevision: 3, delta: "", mode: "faithful", requirements: structuredClone(requirements),
    positive: "blue coat", negative: "bad hands", model: "anima_base_v1", settings: defaultGenerationSettings()};
  return {record, local};
}

describe("conversation change classification", () => {
  it("sends an explicit empty list when removing the last protected fragment", () => {
    const {record, local} = fixture();
    record.draft.requirements!.prompt_locks = [{target: "positive", text: "blue coat"}];
    local.requirements.prompt_locks = [];
    expect(cleanRequirements(local.requirements).prompt_locks).toEqual([]);
    expect(hasUnsavedInputs(record, local)).toBe(true);
    record.draft.requirements!.prompt_locks = [];
    expect(hasUnsavedInputs(record, local)).toBe(false);
  });
  it("preserves prompt locks on reopening and treats them as save-only controls", () => {
    const {record, local} = fixture();
    local.requirements.prompt_locks = [{target: "positive", text: "blue coat"}];
    expect(hasUnsavedInputs(record, local)).toBe(true);
    expect(hasUncompiledInputs(record, local)).toBe(false);
    record.draft.requirements!.prompt_locks = [{target: "positive", text: "blue coat"}];
    expect(editableRequirements(record).prompt_locks).toEqual([{target: "positive", text: "blue coat"}]);
    expect(hasUnsavedInputs(record, local)).toBe(false);
  });
  it("counts manually edited positive and negative prompts as unsaved", () => {
    const {record, local} = fixture();
    local.positive = "red coat";
    expect(hasUnsavedInputs(record, local)).toBe(true);
    expect(hasUnsavedRequirementsOrSettings(record, local)).toBe(false);
    local.positive = "blue coat";
    local.negative = "bad anatomy";
    expect(hasUnsavedInputs(record, local)).toBe(true);
  });

  it("does not require recompilation for lock-only control changes", () => {
    const {record, local} = fixture();
    local.requirements.layers.subject.locked = true;
    local.requirements.layers.lighting.include_with_style_pin = true;
    local.requirements.layers.composition.include_with_style_pin = true;
    expect(hasUncompiledInputs(record, local)).toBe(false);
    expect(hasUnsavedRequirementsOrSettings(record, local)).toBe(true);
  });

  it("requires recompilation for semantic requirements, model, and mode changes", () => {
    const semantic = fixture();
    semantic.local.requirements.layers.subject.text = "红色外套";
    expect(hasUncompiledInputs(semantic.record, semantic.local)).toBe(true);
    const model = fixture(); model.local.model = "anima_aesthetic_v1_1";
    expect(hasUncompiledInputs(model.record, model.local)).toBe(true);
    const mode = fixture(); mode.local.mode = "expand";
    expect(hasUncompiledInputs(mode.record, mode.local)).toBe(true);
  });
});
