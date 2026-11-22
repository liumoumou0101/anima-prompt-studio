import type {ConversationRecord, LocalConversation} from "./conversation";

function workflowId(value:LocalConversation) {
  return value.settings.creation_configuration?.workflow.id ?? value.settings.workflow_profile_id;
}

/** Old drafts omitted the field; an explicit null is the user's detach choice. */
export function migrateWorkflowSnapshot(value: LocalConversation, record: ConversationRecord): LocalConversation {
  if (Object.prototype.hasOwnProperty.call(value, "workflowSnapshotRunId")) return value;
  const source = record.draft.generation_source;
  const matches = source && source.model_profile === value.model
    && source.workflow_profile_id === workflowId(value);
  return {...value, workflowSnapshotRunId: matches ? source.run_id : null};
}

/** A merge may combine one side's snapshot with the other side's execution target. */
export function reconcileWorkflowSnapshot(value: LocalConversation, candidates: (LocalConversation | null)[]): LocalConversation {
  if (!value.workflowSnapshotRunId) return value;
  const matches = candidates.some(candidate => candidate
    && candidate.workflowSnapshotRunId === value.workflowSnapshotRunId
    && candidate.model === value.model
    && workflowId(candidate) === workflowId(value));
  return matches ? value : {...value, workflowSnapshotRunId: null};
}
