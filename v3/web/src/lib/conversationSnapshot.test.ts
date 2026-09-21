import {describe, expect, it} from "vitest";
import {emptyRequirements, type ConversationRecord, type LocalConversation} from "./conversation";
import {defaultGenerationSettings} from "./generationSettings";
import {migrateWorkflowSnapshot, reconcileWorkflowSnapshot} from "./conversationSnapshot";

function local(): LocalConversation {
  return {baseRevision: 2, delta: "未发送的意见", mode: "faithful", requirements: emptyRequirements(),
    positive: "woman, blue coat", negative: "blurry", model: "anima_base_v1",
    settings: {...defaultGenerationSettings(), remote_profile_id: "remote-a", workflow_profile_id: "workflow-a"}};
}
function record(): ConversationRecord {
  return {id: "workspace_example", title: "原图继续", revision: 2, created_at: "2026-09-21", updated_at: "2026-09-21",
    draft: {positive_text: "", excluded_text: "", model_profile: "anima_base_v1", mode: "faithful",
      requirements: null, compiled: null, compile_state: "missing", conversation_events: [],
      generation_settings: local().settings, generation_source: {run_id: "run-a", model_profile: "anima_base_v1",
        remote_profile_id: "remote-a", workflow_profile_id: "workflow-a"}}};
}

describe("migrateWorkflowSnapshot", () => {
  it("retains the verified source when upgrading an old dirty draft", () => {
    const draft = local();
    draft.positive = "my unsaved edit";
    const migrated = migrateWorkflowSnapshot(draft, record());
    expect(migrated.workflowSnapshotRunId).toBe("run-a");
    expect(migrated.positive).toBe("my unsaved edit");
    expect(migrated.delta).toBe("未发送的意见");
    expect(Object.hasOwn(draft, "workflowSnapshotRunId")).toBe(false);
  });

  it.each([null, "run-other"])("preserves the explicit snapshot choice %s", choice => {
    const draft = {...local(), workflowSnapshotRunId: choice};
    expect(migrateWorkflowSnapshot(draft, record()).workflowSnapshotRunId).toBe(choice);
  });

  it.each(["model", "remote", "workflow"])("does not attach an old source after changing %s", changed => {
    const draft = local();
    if (changed === "model") draft.model = "anima_turbo_v1_1";
    if (changed === "remote") draft.settings.remote_profile_id = "remote-b";
    if (changed === "workflow") draft.settings.workflow_profile_id = "workflow-b";
    expect(migrateWorkflowSnapshot(draft, record()).workflowSnapshotRunId).toBeNull();
  });

  it("sets an old draft with no verified source to the current workflow", () => {
    const workspace = record();
    workspace.draft.generation_source = null;
    expect(migrateWorkflowSnapshot(local(), workspace).workflowSnapshotRunId).toBeNull();
  });
});

describe("reconcileWorkflowSnapshot", () => {
  it.each(["model", "remote", "workflow"])("clears a local frozen source when a merged %s comes from elsewhere", changed => {
    const source = {...local(), workflowSnapshotRunId: "run-a"};
    const merged = structuredClone(source);
    if (changed === "model") merged.model = "anima_turbo_v1_1";
    if (changed === "remote") merged.settings.remote_profile_id = "remote-b";
    if (changed === "workflow") merged.settings.workflow_profile_id = "workflow-b";
    const reconciled = reconcileWorkflowSnapshot(merged, [null, source]);
    expect(reconciled.workflowSnapshotRunId).toBeNull();
    expect(merged.workflowSnapshotRunId).toBe("run-a");
    expect(reconciled.model).toBe(merged.model);
    expect(reconciled.settings).toEqual(merged.settings);
  });

  it("preserves a matching source while changing prompt and sampling settings", () => {
    const source = {...local(), workflowSnapshotRunId: "run-a"};
    const merged = {...source, positive: "woman, red coat", settings: {...source.settings, seed: 42, steps: 20}};
    expect(reconcileWorkflowSnapshot(merged, [null, source]).workflowSnapshotRunId).toBe("run-a");
  });

  it("accepts matching conditions from any candidate with the same snapshot", () => {
    const source = {...local(), workflowSnapshotRunId: "run-a"};
    const unrelated = {...source, model: "anima_turbo_v1_1"};
    expect(reconcileWorkflowSnapshot(source, [unrelated, null, source]).workflowSnapshotRunId).toBe("run-a");
  });

  it("does not infer ownership from another snapshot with identical generation conditions", () => {
    const value = {...local(), workflowSnapshotRunId: "run-a"};
    const unrelated = {...local(), workflowSnapshotRunId: "run-b"};
    expect(reconcileWorkflowSnapshot(value, [unrelated]).workflowSnapshotRunId).toBeNull();
  });

  it("keeps an explicit choice to use the current workflow", () => {
    const value = {...local(), workflowSnapshotRunId: null};
    expect(reconcileWorkflowSnapshot(value, [{...local(), workflowSnapshotRunId: "run-a"}]).workflowSnapshotRunId).toBeNull();
  });
});
