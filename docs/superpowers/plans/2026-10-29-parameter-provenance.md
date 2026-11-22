# Parameter Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement the tasks below.

**Goal:** Correct model/workflow parameter initialization and capability-refresh errors while preserving explicit choices and current UI.

**Architecture:** Reuse CreationConfiguration defaults and explicit overrides, with trusted initialization and historical-snapshot boundaries. Model-aware backend factories handle fresh external entry points; bounded retry handles fresh but incomplete capability caches.

**Tech Stack:** TypeScript/React/Vitest, Python/FastAPI/Pytest, existing ComfyUI HTTP adapter.

**Spec:** docs/superpowers/specs/2026-10-29-parameter-provenance-design.md

## Global Constraints

- Preserve current original-project UI, saved prompts, source snapshots, credentials and accepted jobs.
- Preserve explicit incompatible overrides as visible validation errors, not silent replacements.
- Preserve exact 64-bit seeds and deliberate width/height/batch values.
- Refresh missing capabilities once only inside the existing short preparation budget.
- No installation or removal of experimental remote nodes.

## Review Focus

- Initial target arriving after draft creation; missing targets must not reuse stale schemas.
- Old default values versus explicit edits equal to a default; unclassified history stays conservative.
- Same workflow ID on another environment or catalog revision does not reset values.
- Frozen historical workflows must retain original schema and graph conditions.
- Sampler enums, workflow-specific fields and fixed parameters remain validated in the actual request.

### Task 1: Configuration and submission boundaries

- [x] Reproduce default Aesthetic to Turbo inheritance and stale workflow schemas with failing tests.
- [x] Rebase known default recipes on model/workflow change; preserve explicit overrides and snapshots.
- [x] Keep persistent overrides explicit and outgoing full values/core fields consistent.
- [x] Run focused helper tests, seed and workflow parameter regressions.

### Task 2: Workbench integration and recommendations

- [x] Add failing creation/model/workflow/recipe-panel tests.
- [x] Initialize trusted new drafts, preserve source-run snapshots, and use current model recommendations.
- [x] Synchronize recipe selection and restore controls with the actual target.
- [x] Test model matrices, unknown targets, environment-only changes and request snapshots.

### Task 3: Fresh backend entry points

- [x] Reproduce reference requirements defaults and MOSS dimension/aspect leakage.
- [x] Reuse runtime profiles for model-aware defaults in fresh reference/gallery records.
- [x] Preserve explicit history/settings and unknown-model compatibility.
- [x] Run targeted entry-point regressions.

### Task 4: Workflow capability errors

- [x] Reproduce missing experimental nodes and newly installed assets absent from a fresh cache.
- [x] Refresh once only for remote capability rejection during fresh planning.
- [x] Return precise missing-node/file diagnostics without changing workflow intent.
- [x] Test no second refresh after cache miss, no network during cached planning, and budget failure.

### Task 5: Integration and delivery

- [x] Review the combined changes independently and resolve findings.
- [x] Run appropriate complete suites, typecheck and production build.
- [x] Compare a controlled Turbo graph and timing at the recommended settings.
- [x] Guard-copy changed source/build into the original project with backups and hash verification.
- [x] Record behavior, verification and any remaining compatibility limits.

## Final verification

- Full backend: 1441 passed; full frontend: 83 files / 839 passed. TypeScript and production build passed.
- All 35 current workflows resolved against one live inspection without further HTTP requests; 9 were ready. The full audit also covers 6 historical copies.
- All 9 ready workflows across 6 prepared models generated 10 actual PNGs. Bound parameters and exact seeds were checked against persisted ComfyUI graphs. Turbo 896x1152 at 10 steps/CFG1 took 12.203s and 12.214s end to end; cloud execution 4.820s and 4.542s.
- Independent review found and resolved learned-identity, timeout propagation, missing-loader classification, and historical environment/template transition issues.
- Source/build delivery guarded original hashes, kept SQLite/source backups, and verified copied hashes. Original port7085 restarted only while no local worker owned a task; three months-old imported running rows were checked as retryable historical records and left untouched.
- Live production verification confirmed the new JS bundle, one successful capability inspection, HTTP connection, and Turbo's current recipe. Missing legacy weights, MOSS weights and experimental NAG/LayerReplay extensions remain precisely reported without downloads.
- Local report: H:/soft/提示词工具2/reports/parameter-workflow-fix-20261029/验收报告.md
