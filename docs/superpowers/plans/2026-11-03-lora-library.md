# LoRA Library Implementation Plan

> Agentic workers use subagent-driven-development. User already authorized continuous implementation and real Colab verification.

**Goal** Deliver local manually supplied LoRA management, ordered multi-LoRA generation and persistent Colab cache reuse for ANIMA/MOSS.

**Architecture** A content-addressed local index supplies existing requirement lists. Supported template extension points materialize ordered loaders before capability validation. An authenticated Colab asset service and background sync jobs prepare only selected resources.

**Tech Stack** Existing Python/FastAPI/Pydantic/SQLite, React/TypeScript, aiohttp gateway, native ComfyUI.

**Spec** docs/superpowers/specs/2026-11-03-lora-library-design.md

## Global Constraints

Preserve old request/digest/replay behavior and dirty source baseline. No download-provider UI or credentials management. All cloud operations use current authenticated connection. Graphs and resources are frozen on acceptance. Maximum 16 items. Mutable local names never replace byte identity.

## Review Focus

Old snapshots omitting new fields; disabled resources missing from server; loader without clip input; interrupted/concurrent uploads; replaced runtime with same URL. Each belongs to regression tests below.

## Task 1 — Graph contracts and materialization

Owner workflow agent. Modify execution_models.py, core/requirements.py, api/models.py, core/lora_resolution.py, core/workflow_compiler.py, runtime/lora_catalog.py, runtime/generation_queue.py and selected templates. Preserve frozen/idempotent graphs and old fixed mappings. Add narrowly scoped regression tests for ordered two-loader chain, disabled absence, model-only strength, frozen replay and legacy digest. Run existing LoRA and compiler/submission tests.

## Task 2 — Colab assets

Owner cloud agent. Add tools/colab/lora_gateway.py and runtime/lora_assets.py. Update notebook generator and generated gateway source without removing original or user cells. Implement sha-only status/upload/restore with atomic verification and reusable connections. Test authentication, invalid paths/hash/length, interrupted upload, duplicate/concurrent sync, zero upload on cache hit and restore. Expose LoraAssetClient(manager) with status(remote_id,sha256), ensure(remote_id,sha256,local_path,progress=None), returning status plus uploaded_bytes/restored flags. Use local test transports.

## Task 3 — Local library and API

Owner root. Add runtime/lora_library.py and api/loras.py. Use current workspace DB settings for metadata and a project-root loras folder (override for tests). Scan stable regular safetensors headers, hash without loading tensors, deduplicate by bytes, preserve metadata across rename and missing files. Register routes and background sync jobs. Test index mutation, source traversal/symlink rejection, malformed/incomplete files, CRUD/API sessions and sync failure/retry using local stubs.

## Task 4 — Normal user entry points

Owner UI agent. Add LoRA library page/navigation and reusable picker/editor. Use the spec API contract. Store full list including disabled items in requirements, synchronize active library items for selected environment, show independent progress/failures. Integrate ANIMA and MOSS, retain manual records, order controls and per-item weights. Run targeted frontend tests and typecheck.

## Task 5 — Integration, review and real acceptance

Root integrates, independent reviewer checks relevant changes against baseline. Run focused backend/frontend suites, typecheck and production build. Install updated notebook gateway in existing Colab using explicit generation authorization and existing public tunnel scope. Drop real test files into project loras directory, scan and classify. Test from normal workbench/API path, including two different LoRAs, zero-upload repeat and Drive restore. Compare PNG embedded graphs/history/file hashes. Save evidence, copy verified task changes back only if original baselines match, run final smoke checks.

## Progress ledger

2026-11-03 isolated worktree created from HEAD then populated with current source working state. Snapshot reports/lora-library-20261103/baseline.json. No implementation code changed yet.

Ruling — execution method is parallel workers plus root integration because the user explicitly said to start and the four domains have separable ownership.

Task 1 complete in the isolated worktree. Ten trusted baseline templates declare extension points in the catalog manifest. Added ordered model/CLIP or model-only loading, opt-out filtering, asset identity checks, frozen replay and gallery variations. Template revisions and legacy payload digests retain the old form for unchanged graphs. The 207 focused V3 tests and 36 V2 remote execution tests passed. Real GPU acceptance remains with Task 5.

Task 1 review fix: snapshot reuse with a changed LoRA now verifies the new digest against the current target model. Unchanged accepted digests replay independently of library edits. Reproduced the wrong-family replacement against both template families; 149 focused tests passed after correction.

Tasks 2–4 complete. The index uses the existing runtime database setting `lora_library_v1`; conversation selections remain in workspace state. Added bounded safetensors scanning, content identity, authenticated resumable Drive caching, library editing and ordered ANIMA/MOSS selection. Same-URL readiness now performs a live authenticated identity probe. Relevant final backend suites passed 355 cases with one Windows symlink skip. Frontend typecheck/build passed; the four full-suite timing failures passed individually with their original time limits.

Task 5 in progress. MOSS OFF, NAM 0.5 and NAM 0.5 + Destripe 1.0 generated successfully through the ordinary API/workbench. Complete PNG graphs exactly match accepted frozen snapshots. The two-LoRA model has 164 attached patches, compared with 144 for NAM alone, and no unloaded-key warnings. Drive restoration also succeeded with both the desktop file and runtime copy absent, uploading zero bytes. ANIMA baseline is complete; managed CunnyFunky upload is resuming after interruption.

Real Colab testing exposed inherited process-group interruption. ComfyUI, gateway and tunnel now start in separate sessions. Stopping the foreground monitor was repeated live and all three services remained running. The monitor rejects inherited service sessions before entering its loop. The updated notebook suite passed 34 tests with two Windows-only skips.

Task 5 complete. All seven GPU cases (three MOSS and four ANIMA) passed full PNG graph versus accepted-snapshot verification. ANIMA v4 0.7 → v2 0.3 changes the rendered image; disabling v2 produces exactly the same RGB pixels as v4 alone. Full CunnyFunky v4 upload resumed at byte 142606336, transferred the remaining 224496824 bytes, and completed SHA-256 verification and Drive/runtime installation. Repeating preparation for all four assets uploaded zero bytes. Source and built frontend were copied back under baseline hash guards, with pre-change backups. The previously mixed-source wheel test also passed in the actual original checkout after paired V2/V3 delivery. The original Colab profile and four library classifications were prepared without replacing other personal settings. The Drive notebook retains its nine prior cells, updates three service/monitor cells, and removes only our temporary acceptance helper.
