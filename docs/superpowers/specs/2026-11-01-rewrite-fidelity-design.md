# Rewrite fidelity repair

The user authorized fixing the findings from the 2026-11-01 audit and testing a broader set through the real configured API. This continues the existing isolated `codex/temporary-cloud-links` worktree. Preserve the current Sheet layout and real-time identity/artist selection updates.

## Behavior

- The latest explicit edit is mandatory within unlocked editable content. Both Anima modes preserve all other explicit facts and ownership. Expansion stays inside an explicitly narrow edit; it cannot expand a positive prompt explicitly required to remain unchanged.
- Final English, updated requirement descriptions, exclusions, and selected read-only controls must agree. Incompatible literal tags, locks or controls produce a clear conflict without committing contradictory state.
- Review the actual final prompt after deterministic tag/preset insertion. A separate bounded LLM review compares source, delta, candidate, requirement ledger and controls. One repair may address reported issues, followed by review again; otherwise retain the original state and show the reason. No silent success on unchecked failure.
- Existing deterministic schema, literal lock and language checks remain. Review complements them; it does not replace them. The reviewer uses the existing configured service, with a distinct task, no images, and a bounded budget. Direct generation remains available without these editing calls.
- MOSS preserves the original language and exact negative. Actual requested picture text stays literal; quotation marks used for emphasis or naming do not turn their content into picture lettering. Polish adds no visible facts; expansion preserves explicit facts and declares compatible additions.
- No English change preserves the submitted edit and stops the combined update/generate action. Users may explicitly generate the current prompt.
- New identity/artist selections synchronize immediately; unrelated selection changes do not resurrect manually deleted old tokens. Existing literal removal and artist preset ownership are preserved.
- Fetching a MOSS suggestion retains the current adopted and manually edited output until the user adopts a replacement. Failures keep that output usable. Explicit source/negative/mode edits retain their invalidation behavior.

## Approaches

Strengthening the generation instructions alone cannot catch an ignored edit, as the audit proved. Keyword enforcement cannot correctly handle ownership, negation or equivalent Chinese/English wording. The implementation therefore combines existing deterministic protections with independent semantic review and a single bounded repair. This is an engineering choice under the user's instruction to fix the audited behavior, not a new confirmation flow.

## Validation

Use regression tests exercising production state transitions with only external transport mocked, full backend/frontend suites, a production frontend build, and a real-service synthetic matrix broader than the audited examples. Independently inspect final outputs rather than treating either HTTP success or the production reviewer as the test verdict. No GPU generation or Colab startup is required for this text editing task. Publish only synthetic requests/results, never configuration, credentials or private upstream errors. Preserve original workspaces and settings during testing.
