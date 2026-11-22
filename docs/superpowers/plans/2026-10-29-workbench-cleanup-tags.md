# Workbench Cleanup and Tag Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox syntax for tracking.

**Goal:** Clear historical workflow clutter and fix reproduced role/artist/workbench inconsistencies, then safely release cloud compute and shut down.

**Architecture:** Existing catalogs gain recoverable removal metadata; historical execution keeps its frozen graph. Existing UI requirements and prompt compiler remain the tag ownership boundary.

**Tech Stack:** Python/FastAPI/SQLite, React/TypeScript/Vitest, ComfyUI HTTP, in-app browser.

**Spec:** docs/superpowers/specs/2026-10-29-workbench-cleanup-tags-design.md

## Global Constraints

- Preserve current UI layout, explicit user text/parameters, pictures and run history.
- Do not delete current model definitions merely for missing runtime weights.
- Keep gallery Tile Upscale and frozen historical execution usable.
- No new model downloads or extension installations.
- Terminate Colab only after remote testing; shutdown only after verified termination.

## Review Focus

- Archived ordinary requests versus frozen history without a catalog target.
- Role/series/artist category ownership, aliases, duplicates and deletion.
- Selected identity tags surviving compile/save/reopen and reaching final prompt.
- Async results and record/model changes cannot overwrite unrelated drafts.
- Manual prompt edits, MOSS Chinese and exact seed/settings remain intact.

### Task 1: Recoverable catalog cleanup

- [x] Add RED tests for atomic removal, persistence, all catalog consumers, regular rejection and frozen replay.
- [x] Implement minimal remove_many/catalog filtering and active settings/inspection consumers.
- [x] Verify the gallery source remains available; review and run focused tests.

### Task 2: Frontend history and tag ownership

- [x] Reproduce removed-target history gating and concrete identity/artist UI bugs.
- [x] Fix existing page/components with focused regressions, keeping layout intact.
- [x] Verify saved schema/config and ordinary target requirements remain distinct.

### Task 3: Backend tag and adjacent workbench audit

- [x] Trace requirements through compiler/aliases/persistence, using sanitized production evidence if useful.
- [x] Reproduce and fix concrete role/series/artist bugs with RED/GREEN tests.
- [x] Review save/source/compile protection; report covered paths and actual limitations.

### Task 4: Integration and delivery

- [x] Independent review of combined changes and resolve confirmed findings.
- [x] Final full backend/frontend, typecheck and production build.
- [x] UI test new/archive history, role/artist add/remove/save/reopen and representative real generation.
- [x] Backup and hash-guard delivery; atomically remove audited IDs in original state; verify resulting choices.
- [x] Save sanitized report and recovery inventory.

### Task 5: Requested shutdown

- [x] Finish downloads, persist reports and stop QA helpers.
- [x] Disconnect/delete Colab runtime through its visible UI; verify no connected GPU and unavailable old endpoint.
- [x] Save termination proof and final status, then schedule Windows shutdown without forced data loss.

## Verification receipt

- Final backend: 1480 passed; frontend: 84 files / 862 passed. TypeScript and production build passed (`index-C7ISocTV.js`).
- Actual TS/Python overlay implementations: 48/48 identical outputs. Additional real concurrency diagnosis fixed the Windows lock-file initialization race; 200 real imports without failure.
- Real UI found and corrected formal-alias append duplicates and the misleading manual-only artist count. Add/remove/save/reopen and 3 real GPU generations verified actual text node inputs, including retired-template frozen history.
- Original catalog: 35 to 10, with 9 main generation choices. 25 recoverable removals; gallery super-resolution, MOSS and 2.9B retained. Original workspace rows and generation history unchanged after delivery.
- Original source/build hashes verified (62 files); private recovery backups and per-template import JSON saved under v3/.local/backups/workbench-cleanup-tags-20261029.
- Colab explicitly disconnected and runtime deleted; session manager shows no active sessions, former gateway returns530. Termination proof saved. Windows normal shutdown is the final requested action after records are persisted.
