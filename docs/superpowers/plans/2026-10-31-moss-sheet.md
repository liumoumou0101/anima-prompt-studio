# MOSS Sheet Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans; root integrates production code and delegates focused regression tests and final read-only review.

**Goal:** Keep MOSS source, final text and daily actions visible while secondary settings live in a Sheet.

**Architecture:** Reuse PromptToolsSheet with optional controlled open/onOpenChange. MossWorkbenchPage keeps its draft/generation handlers, places controlled secondary fields into four sections and presents a two-column desktop editor with a fixed dock.

**Tech Stack:** Existing React, TypeScript, CSS, native dialog, Vitest; no new dependencies.

**Spec:** docs/superpowers/specs/2026-10-31-moss-sheet-design.md

## Global Constraints

- Preserve raw/polish/expand, explicit adoption, exact positive and draft negative submission.
- Preserve direct/intent generation and recovery protocols and parameter validation.
- No backend, model, cloud runtime or original user draft changes.
- Work in existing clean linked codex/temporary-cloud-links worktree; guard original delivery with hashes/backups.

## Review Focus

- Late assistance must not adopt or reopen obsolete results after edits/unmount.
- The Sheet controlled API must leave Anima's uncontrolled behavior unchanged.
- Pending/rejected generation and disabled reasons stay visible outside dialog.
- Suggestion text edits invalidate adoption and preserve original exclusions.
- Scaled 2K and narrow windows keep fixed actions reachable.

### Task 1: Controlled Sheet lifecycle

- [x] Add a failing controlled-open/close test to PromptToolsSheet.test.tsx.
- [x] Add optional open/onOpenChange without changing existing uncontrolled consumers.
- [x] Run shared component tests.

### Task 2: MOSS layout and regression coverage

- [x] Confirm baseline Moss/Sheet tests and original-file hashes.
- [x] Add failing focused Sheet/adoption/submission tests in MossWorkbenchSheet.test.tsx.
- [x] Move exclusions/parameters/resources/review into four mounted Sheet sections, keep original handlers.
- [x] Add compact header, source/final editors, explicit main status and fixed generation dock; responsive CSS.
- [x] Verify raw/polish/expand, stale results, all generation/recovery tests and new Sheet interactions.

### Task 3: Review, verify and deliver

- [x] Independent bounded code review and fixes.
- [x] Full frontend suite, typecheck/build, whitespace check.
- [x] Isolated browser QA at 2560×1440,1920×1080,1707×960,1280×720,390×844; capture screenshots.
- [x] Hash-guard source/build delivery and backups, verify live asset hashes, save report, commit changes.

## Execution record

- Starting state: clean linked worktree at c07d269. User approved the design and requested implementation; no further approval required.

- Final: 86 frontend test files / 884 tests passed, typecheck/build and independent review passed. Browser verified primary2K,1080p,150%scaled2K,720p,480pxheight and390pxmobile. LiveLLMpolish/expand validated using private copy of original selected service configuration. Original settings/drafts and backend untouched; source/build backed up and delivered with live asset hashes verified.
