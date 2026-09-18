import {describe, expect, it} from "vitest";
import {defaultGenerationSettings} from "./generationSettings";
import {emptyRequirements, type LocalConversation} from "./conversation";
import {mergeConversation, resolveConversationConflicts} from "./conversationMerge";

function draft(): LocalConversation {
  const requirements = emptyRequirements();
  requirements.layers.subject.text = "蓝色外套";
  requirements.layers.lighting.text = "傍晚";
  return {baseRevision: 3, delta: "", mode: "faithful", requirements, positive: "blue coat", negative: "", model: "anima_base_v1", settings: defaultGenerationSettings()};
}

describe("mergeConversation", () => {
  it("preserves unrelated remote and local leaf edits", () => {
    const base = draft();
    const local = structuredClone(base); local.requirements.layers.composition.text = "居中构图";
    const remote = structuredClone(base); remote.baseRevision = 4; remote.requirements.layers.lighting.text = "清晨";
    const result = mergeConversation(base, local, remote);
    expect(result.conflicts).toEqual([]);
    expect(result.merged.baseRevision).toBe(4);
    expect(result.merged.requirements.layers.lighting.text).toBe("清晨");
    expect(result.merged.requirements.layers.composition.text).toBe("居中构图");
  });

  it("reports same-field edits and defaults unresolved values to remote", () => {
    const base = draft();
    const local = structuredClone(base); local.requirements.layers.subject.text = "红色外套";
    const remote = structuredClone(base); remote.baseRevision = 4; remote.requirements.layers.subject.text = "绿色外套";
    const result = mergeConversation(base, local, remote);
    expect(result.merged.requirements.layers.subject.text).toBe("绿色外套");
    expect(result.conflicts).toEqual([{path: "requirements.layers.subject.text", label: "主体要求", base: "蓝色外套", local: "红色外套", remote: "绿色外套"}]);
    expect(resolveConversationConflicts(result, {"requirements.layers.subject.text": "local"}).requirements.layers.subject.text).toBe("红色外套");
  });

  it("treats arrays as atomic values", () => {
    const base = draft(); base.requirements.layers.subject.general_tags = ["coat"];
    const local = structuredClone(base); local.requirements.layers.subject.general_tags = ["coat", "red"];
    const remote = structuredClone(base); remote.requirements.layers.subject.general_tags = ["coat", "green"];
    const result = mergeConversation(base, local, remote);
    expect(result.conflicts[0]?.path).toBe("requirements.layers.subject.general_tags");
    expect(result.merged.requirements.layers.subject.general_tags).toEqual(["coat", "green"]);
  });

  it("provides readable labels for generation-setting conflicts", () => {
    const base = draft();
    const local = structuredClone(base); local.settings.width = 768;
    const remote = structuredClone(base); remote.settings.width = 1024;
    expect(mergeConversation(base, local, remote).conflicts[0]?.label).toBe("生成设置 · 宽度");
  });

  it("takes remote changes without conflict when the saved local draft was untouched", () => {
    const base = draft();
    const local = structuredClone(base);
    const remote = structuredClone(base); remote.baseRevision = 5; remote.requirements.layers.lighting.text = "清晨";
    const result = mergeConversation(base, local, remote);
    expect(result.conflicts).toEqual([]);
    expect(result.merged.requirements.layers.lighting.text).toBe("清晨");
  });
});
