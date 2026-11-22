# Prompt tools Sheet implementation plan

> **For agentic workers:** Use superpowers:executing-plans for integration and a focused component implementer; track verified results below.

**Goal:** Replace the long auxiliary-control stack with a Sheet while preserving exact live tag synchronization and optimizing the 2K editor.

**Architecture:** A native dialog component owns its toolbar, tabs, focus/scroll lifecycle, and mounted content. The workbench supplies existing controlled components and handlers, while editor CSS assigns remaining height to the positive prompt.

**Tech Stack:** Existing React 19, TypeScript, native dialog, CSS, Vitest/Testing Library; no new dependencies.

**Spec:** docs/superpowers/specs/2026-10-31-prompt-tools-sheet-design.md

## Global Constraints

- Prioritize 2560×1440 maximized and preserve narrow-screen access.
- Keep all identity-to-prompt and generation/save handlers unchanged.
- Keep Sheet content mounted across closes; reset on workspace change.
- Do not alter backend, Colab, model configuration, user drafts or history.
- Reuse the existing linked worktree; guard original-project delivery with hashes and backups.

## Review Focus

- Esc in autocomplete closes suggestions first, Sheet second; IME remains usable.
- Close controls remain usable even when child fieldset is disabled.
- Hidden panels retain draft input without exposing invisible tab stops.
- Moving artist preset selection must preserve preferred-id entry and current preset visibility.
- Short desktop and narrow layouts retain editor, composer and generation access.

### Task 1: Sheet component

**Files:** Create components/PromptToolsSheet.tsx, promptToolsSheet.css, PromptToolsSheet.test.tsx under v3/web/src.

**Interfaces:** `PromptToolSection {id:string; label:string; summary?:string; content:ReactNode}`; props `sections`, `disabled?`, `status?`, `initialSection?`.

- [x] Add focused failing interaction tests: open named dialog, tab switching, mounted local input preservation, close/focus/scroll unlock, disabled content vs enabled close, consumed Escape and IME.
- [x] Implement toolbar and native dialog with fixed header/footer, semantic tabs, keep-mounted panels and existing useBodyScrollLock.
- [x] Verify focused tests and typecheck.

### Task 2: Workbench integration and desktop layout

**Files:** ConversationWorkbenchPage.tsx, ManualIdentityTags.tsx, IdentityTagField.tsx and relevant tests; components/conversationStudio.css.

**Interfaces:** Supply Task 1 sections using the existing handlers. Preserve record keys. Add initially-open compact identity controls.

- [x] Record clean baseline; add failing integration assertion for Sheet entry and live identity text after close/reopen.
- [x] Move helper controls into sections; keep current preset summary and real tag status visible. Keep close outside disabled fieldsets.
- [x] Make positive editor stretch within desktop remaining height; keep main editor accessible on short/narrow screens.
- [x] Make autocomplete consume Esc only while open and artist picker consume its own Esc.
- [x] Adapt existing tests to open relevant Sheet sections and verify generation payload and no unsolicited LLM/save calls.

### Task 3: Verification and delivery

- [x] Run frontend suite, typecheck, production build and diff whitespace check.
- [x] Review changed code independently; address material findings.
- [x] Open isolated local QA in in-app browser; inspect 2560×1440 and smaller viewports, Sheet keyboard/close/state and live tags.
- [x] Back up and hash-guard touched original files, deliver source/build; confirm live app serves new bundle.
- [x] Save screenshots and concise validation notes; record final results.

## Execution record

- Initial state: clean linked worktree on codex/temporary-cloud-links at 316ff07. User approved the concrete design and requested implementation; continue without another approval round.

- Final verification: 85 frontend test files / 878 tests passed; production typecheck and build passed; independent code review clean. Browser verified 2560×1440, 1920×1080, 1707×960, 1280×720 and 390×844; native focus wrap and live identity add/remove verified. Delivered with guarded backups and matching live HTML.
