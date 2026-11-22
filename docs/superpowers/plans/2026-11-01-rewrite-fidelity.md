# Rewrite fidelity implementation plan

> **For agentic workers:** Use executing-plans for the root backend work and independent delegated tasks for MOSS, frontend and live test tooling. All work is already authorized by the user's repair request.

**Goal:** Apply explicit edits faithfully, preserve unrelated constraints and user drafts, and verify with broad real-service tests.

**Architecture:** Keep current services and UI. Add one shared semantic review boundary over final candidates, with a single bounded repair and atomic persistence only after acceptance. Keep deterministic validation and current direct-generation behavior.

**Tech Stack:** Python 3.12+, Pydantic, pytest; React, TypeScript, Vitest; existing configured LLM transport.

**Spec:** `docs/superpowers/specs/2026-11-01-rewrite-fidelity-design.md`

## Global constraints

- No new runtime dependencies, no GPU/Colab tests, no changes to user settings or workspaces in verification.
- No credential values or upstream exception bodies in output or published reports.
- Preserve Sheet layout, current prompt generation, selected tag normalization and artist preset ownership.
- Only commit validated candidates; retain source state on errors, cancellation, conflicts and failed repair.

## Review focus

- Negation and local exclusions must retain ownership rather than becoming a global ban: backend review integration and live matrix.
- Narrow edits in expansion must retain unrelated text/facts: backend repair integration and live matrix.
- Locked and selected controls must not contradict the final prompt: review integration with post-render candidate.
- Late/failed suggestion responses must retain current adopted manual text: frontend integration tests.
- Multilingual quotes distinguish picture lettering from prose names: MOSS integration and live tests.

### Task 1: Shared semantic review and Anima integration (root)

Files: create `core/rewrite_review.py`, `tests/test_rewrite_review.py`, `tests/test_conversation_review.py`; modify `api/conversation.py`, `services/completion.py`, prompt guidance and isolated test fixtures.

Interface: `async review_rewrite(context: dict, candidate: dict, *, timeout_s: float = 45) -> dict`, returning bounded `issues` and `conflicts` lists. MOSS and Anima import the module so tests can isolate existing unrelated units at this explicit boundary.

- [x] Write failing transport/semantic integration tests for ignored edits, narrow edits, contradictory ledger and controls, post-insertion tags, repair success/failure and atomic cancellation.
- [x] Run tests and verify meaningful failures.
- [x] Implement strict structured review with task `rewrite_review`, protected against treating source content as system instructions.
- [x] Add final-candidate Anima review and at most one correction; maintain one request deadline and existing CAS/disconnect checks.
- [x] Run related backend tests, then the full backend suite.

### Task 2: MOSS correction and quote semantics (delegated)

Files: `api/moss.py`, MOSS backend tests. Consumes Task 1's review interface.

- [x] Red/green tests for names vs actual picture text, count/ownership/scope preservation, exact negative, original language and reviewer failure.
- [x] Implement bounded generation/review/repair with no intermediate user-state mutation.
- [x] Run MOSS and related backend tests.

### Task 3: Frontend state and feedback (delegated)

Files: conversation/MOSS pages, `identityPrompt.ts`, related Vitest files.

- [x] Red/green no-op edit preservation, no automatic generation of unchanged text, latest saved prompt use, non-resurrection of old tags, MOSS output survival.
- [x] Keep immediate newly selected identity/artist insertion and ownership-safe removal.
- [x] Run related tests and full frontend tests/typecheck/build.

### Task 4: Expanded real API verification and delivery (tooling delegated; root executes/reviews)

Files: reproducible opt-in live test runner and synthetic fixtures; ignored local results.

- [x] Implement default no-network listing and explicit opt-in real-service runner over isolated state/configuration.
- [x] Execute the broad matrix including multi-turn, scope, ownership, negation, locks, text and multilingual cases.
- [x] Independently review all final outputs, add regressions for material findings, and correct the relevant implementation.
- [x] Obtain a fresh whole-change review, run final suites/build, verify artifact hashes and deploy the verified local build using the existing project delivery workflow.
- [x] Publish synthetic evidence and concise results including limits; preserve original user data.

## Verification record

- Final backend: 1543 passed, one existing Starlette warning.
- Frontend: 893 passed with two workers, typecheck and production build passed using bundled Node 24.22.1.
- Live corpus: 51 synthetic cases / 95 steps, including two raw workflow controls; independently reviewed final candidates and six expected read-only conflicts. Additional authenticated HTTP tests called the real LLM in isolated application state.
- Earlier live failures were diagnostic inputs to repairs; final evidence selects the latest result for each case/mode/step and retains source records. Two source combinations have intrinsic color/medium ambiguity; one compatible expansion is weak. These are observations, not silently removed requirements.
- Local delivery preserves unrelated original-project changes and backs up overwritten files. No settings/database copies, Colab startup, image-generation requests, remote publishing or branch merge.

## Runtime activation

Verified files and frontend assets were backed up and copied into the original project. Automatic approval review rejected the combined stop/copy/restart action with only `blocked by policy`; the existing service was not stopped. A safer file-only delivery succeeded, and the live frontend asset hashes match. Backend activation remains pending a restart of the existing local service; refreshing a browser tab alone does not restart Python. No alternate process-termination mechanism was attempted.
