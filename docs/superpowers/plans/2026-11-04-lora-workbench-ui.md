# LoRA Workbench UI Implementation Plan

> For agentic workers: use subagent-driven development with independent ownership and final review. User explicitly requested implementation.

**Goal:** Put LoRA editing and historical-template switching in one usable ANIMA/MOSS panel.

**Architecture:** Reuse LoraResources, expose `onEditSnapshot?: () => void`, and render the action `切换模板并编辑 LoRA` outside the frozen fieldset. Reuse the existing ANIMA template adoption logic and implement equivalent persisted MOSS draft detachment. Fix the LoRA grid container without changing other parameter groups.

**Tech Stack:** Existing React, TypeScript, CSS, Vitest and current workspace API. No new dependencies.

**Spec:** docs/superpowers/specs/2026-11-04-lora-workbench-ui-design.md

## Global Constraints

- Preserve raw prompt whitespace, negative prompt, manual values, large seed strings, resources and historical run data.
- Keep snapshot reproduction until the explicit action; block switching while a generation request is pending.
- Preserve all previous library filtering, order, toggle and cache readiness behavior.
- Work in the existing isolated worktree. Baseline: reports/lora-ui-20261104/baseline.json. Original target files initially match.
- Do not commit or overwrite unrelated pre-existing changes.

## Review Focus

Reload after MOSS detachment; frozen same workflow ID but a newer revision; no compatible live template; stale accepted token after save; CSS specificity at wide and narrow widths.

## Task 1 — Shared component and layout (UI worker)

Files: LoraResources.tsx / test, loraLibrary.css, GenerationSettingsPanel.tsx and scoped CSS if required.

- [x] Add failing behavior coverage proving frozen editing remains locked but the switch callback is reachable, and unavailable actions explain why.
- [x] Implement `onEditSnapshot` prop, compact rows/cards, advanced details and local actions. Preserve existing accessible names for resource actions.
- [x] Give the LoRA fieldset a dedicated class and full-width single-column container, including wide-window media rules.
- [x] Run component tests and report layout verification hooks. Leave page integration to other owners.

## Task 2 — MOSS historical editing (MOSS worker)

Files: MossWorkbenchPage.tsx / test, optional narrowly scoped MOSS configuration helper/tests.

- [x] Add failing source-workspace behavior test: click switch in LoRA, select MOSS asset, retain literal text/manual values/seed, submit current template with resource list and no historical run ID.
- [x] Implement explicit persisted detachment using current workspace save contracts; retain unmodified frozen behavior before the action and workspace isolation.
- [x] Wire the shared `onEditSnapshot` callback only with a usable current MOSS template, and block during active submission.
- [x] Verify reopen behavior, no-target explanation and existing MOSS suites.

## Task 3 — ANIMA integration, review, delivery (root)

Files: ConversationWorkbenchPage.tsx / parameter tests, guide, reports.

- [x] Add regression for switching from within the LoRA group, preserving manual parameters and resources; remove the remote entry under layered requirements.
- [x] Wire the existing adoption function to shared callback. Keep original history unchanged.
- [x] Run combined relevant tests, typecheck and build, then real browser QA in full-width and side-inspector contexts.
- [x] Independent integration review, resolve findings, and copy only changed files/build under baseline guards to H:/soft/提示词工具2. Update concise guide and provide actual result screenshots.

## Ledger

2026-11-04: Diagnosed shared CSS grid assigning the section element only one parameter column. All initial target source files match the original project. User requested direct implementation; use compact cards and explicit local template switching.

Task 2 complete. MOSS adopts the selected compatible live template with one revision-checked workspace PUT (draft.detach_generation_source=true). This commits source release, settings, resources and literal prompt together, and preserves the old revision on conflicts. Prefer a ready template within the chosen environment; a revisioned non-disabled template may also be edited offline, with execution still subject to normal environment validation. Disabled or explicitly zero-slot/no-extension templates are ineligible. Manual overrides and fixed string seeds survive both a retired source workflow and a newer revision of the same ID. 77 MOSS UI tests and 96 backend workspace/gallery/conversation tests passed, along with TypeScript checking. Independent review exercised the atomic and frozen/changed-template cases.


Tasks 1 and 3 complete. The shared panel now spans the complete parameter group, with compact cards and advanced controls collapsed. ANIMA's historical-template adoption and server mapping controls are in the LoRA group; unrelated layered requirements no longer contain the action. Eligible current templates honor the pinned environment and exclude disabled/explicitly unsupported LoRA templates; known unchecked templates remain editable offline.

Browser acceptance used the real built pages/API with isolated previous acceptance histories and an injected ready cache, without new GPU dispatch. ANIMA historical editing unlocks from its own LoRA panel and its cards fill all 520px at a 1280px viewport and 855px at 1920px. MOSS historical editing, remove/re-add, toggle/order and source-mode persistence were exercised; an edited 0.65 weight survived reload, and advanced controls omit the unsupported CLIP weight. At a 480px dark viewport, dialog client/scroll widths both equal 447px, with no document overflow.

Validation: full frontend suite 1010 passed and one pre-existing 5s timeout (`ConversationWorkbenchPage.test.tsx: rewrites without generating, then explicitly submits the current token and edited prompt`); the unchanged isolated test passed in 3.00s at its original timeout. Production typecheck/build passed. Related backend suites passed 96 cases, and root separately reran all 19 gallery/workspace tests. Independent MOSS/backend and ANIMA/shared-component reviews found no remaining blockers. Original source delivery uses the Nov4 baseline, keeps backups, and includes the built frontend.
