# Unified generation logic

**Goal:** Make the workbench's visible, saved and submitted parameters derive from one configuration. Remove obsolete duplicate implementations.

**Architecture:** `CreationConfiguration` is the editable source. One resolver computes values and errors; settings and requests are projections. Legacy flat records are read through one adapter. The backend executes the resolved request snapshot and uses configuration metadata for routing/provenance, without recomputing recipes.

**Scope:** Existing React/TypeScript and Python code, no dependencies, no new service/framework, no changes to user prompts or stored drafts.

## Implementation

- [x] Centralize defaults and legacy reading without circular imports. Remove duplicate parameter resolution, flat-cache inference and unused legacy editing helpers. Test contradictory caches, invalid drafts, exact seeds, model switches and old records.
- [x] Use the same resolved configuration for ANIMA's summary, validation, saving and payload; share MOSS's payload projection. Replace ANIMA's double model rebase with one transition.
- [x] Remove the two unreachable old workbench implementations and their exclusive tests. Keep `/direct` migration and move the two still-applicable LLM settings tests to the live component suite.
- [x] Extract the backend's three identical parameter merges into one helper used by preflight, eligibility and workflow rendering. Preserve typed-core precedence and accepted-request freezing.
- [x] Run relevant tests, full frontend/backend suites, typecheck and production build. Review the diff; back up and sync only scoped files to the user's project, preserving unrelated changes. Do not restart the previously blocked running service.

## Compatibility and review

Historical workflow snapshots retain their schema/version; pending requests retain their exact body. Invalid text drafts remain invalid. Seed `-1` remains random and large seeds remain precise. Model/workflow changes replace the baseline and preserve explicit edits. Environment changes only choose execution location. Old records without provenance retain saved values. Obsolete asynchronous workspace loads must not replace the current workspace.

The user additionally authorized Colab verification using already prepared models, followed by releasing the Colab runtime and shutting down Windows. Use independent safe test prompts and outputs; do not download missing models or change the user's prompts and data.

Verification completed: backend 1560 passed; frontend full suite passed; final parameter-page regression 40 passed; typecheck and production build passed. Independent browser QA verified save/refresh state with normalized Seed receipts. Seven prepared Colab models each produced an image, with exact submitted/executed graph agreement. Colab was disconnected and its runtime deleted; session management confirmed no active sessions. Evidence is in the user's project under `reports/unified-logic-20261101`.
