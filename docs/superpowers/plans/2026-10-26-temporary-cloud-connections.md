# Temporary Cloud Connections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import and replace temporary HTTPS ComfyUI connections in the existing V3 application, safely carrying Bearer authentication through actual generation and downloads.

**Architecture:** Preserve RemoteProfile.id; add non-secret HTTPS/session metadata and an OS credential reference. Share transport/client construction across V3 consumers, freeze HTTP connection versions in tasks, and expose a small dedicated import API consumed by the settings UI.

**Tech Stack:** Python 3.12+, Pydantic/FastAPI, requests, Windows Credential Manager, React/TypeScript/Vitest.

**Spec:** docs/superpowers/specs/2026-10-26-temporary-cloud-connections-design.md

## Global Constraints

- Preserve existing SSH/local behavior and legacy SSH fingerprints; keep all pre-existing user changes.
- No key in SQLite, responses, logs, workflows, or generation sidecars; HTTPS certificate verification stays enabled, and authenticated redirects never auto-follow.
- No external GPU calls, real user database writes, cloud notebook edits, push, publish, or automatic prompt resubmission.
- API base: /api/v3; use the existing session/origin protections and error envelopes.
- Use the original H:/soft/提示词工具2/.venv/Scripts/python.exe with the isolated worktree's v3/src and src; frontend dependencies are a junction to the existing node_modules.

## Review Focus

- Invalid/oversized JSON containing a secret must neither mutate an existing profile nor echo the input.
- Imported URL/key/runtime changes must invalidate resource evidence while keeping logical profile ID and mappings.
- Direct generation, probe, gallery, upload, and view must all use authentication; webpage access is explicitly separate.
- Existing SSH/local snapshots remain compatible; an old task cannot query or resubmit to a replaced HTTP session.
- Repeated import and credential-store failures must not leave mismatched key/profile state or lose prior settings.

### Task 1: HTTPS import backend and complete runtime integration

**Files:** Modify src/anima_prompt_studio/domain/execution_models.py; v3 remote/comfy_client.py, credential_store.py, execution_coordinator.py; v3 runtime/comfy_access.py, environment_probe.py, workflow_catalog.py, generation_queue.py, submissions.py; v3 storage/runtime_repository.py; v3 adapters/v2/gallery.py; v3 api/app.py and models.py. Create focused modules under v3 remote/ and api/ for HTTPS transport/import parsing/service/routes rather than growing app.py significantly. Add behavioral tests under v3/tests/.

**Interfaces:** Produce POST /api/v3/settings/temporary-connections/import with {connection_text: string, api_key?: string, display_name: string, target_profile_id?: string}. connection_text is JSON content or a plain HTTPS base URL. Existing settings response fields remain; add connection_type='http', http_base_url, http_session_id, http_runtime_id (optional identity string), has_saved_api_key, web_url. Return the same non-secret RemoteProfile response used by the list. The key is optional for public URL mode and required when the JSON declares Bearer. Update only an existing HTTP profile when target_profile_id is supplied. Preserve display name and mappings on target updates unless explicitly changed. No network request is needed merely to save/import; the existing test-connection route performs the check.

- [ ] Write failing tests for JSON/plain URL normalization, forbidden URL/auth/protocol, metadata-only persistence, stable-ID updates/idempotence, safe validation/credential failures, and key deletion.
- [ ] Run focused tests and record expected RED output.
- [ ] Implement import DTO/service and secure credential methods; integrate API with existing locks and protected routes.
- [ ] Write failing protocol/runtime tests for authenticated stats/object_info/prompt/history/queue/view/upload, redirect rejection, failed auth sanitization, and replaced-session recovery before any connection opens. Cover gallery and probe consumers as applicable.
- [ ] Run the new tests RED, then implement a shared transport/client factory and integrate all V3 consumers; keep legacy SSH fingerprint serialization and injected factories compatible. HTTP without gateway runtime identity remains weak. Use a non-secret session snapshot for execute and restore.
- [ ] Run focused tests GREEN, then the full V3 backend suite. Self-review the diff, commit only Task 1 files, and record results in the task report.

### Task 2: Settings import UI, documentation, and build

**Files:** Modify v3/web/src/pages/SettingsPage.tsx and tests; create a focused temporary-connection import component and tests; add styles to the relevant existing settings/library stylesheet. Add docs/v3/TEMPORARY_CLOUD_CONNECTIONS_20261026.md and update v3/STATUS.md with precise validation boundaries.

**Interfaces:** Consume Task 1 import endpoint and additive response fields exactly. Existing test-connection and open-comfy routes remain entry points. UI labels: “导入临时连接”, “连接信息”, “访问密钥”, “新建连接”, “更新当前临时连接”. Provide JSON file selection as an alternative to paste; read size-bounded files as text and never persist raw content/key in localStorage. Clear secrets on successful import/cancel/unmount; avoid success claims on failure. HTTP profiles must not show SSH fingerprint or password controls; test, select, edit metadata, delete, and the gateway login link remain usable. Changing URL/key is done through the import UI to preserve replacement semantics.

- [ ] Write and run failing tests through the real settings/component tree for JSON and URL/key submission, file input, updating an existing HTTP target, clearing secrets, preventing oversized files, and displaying API failure without replacing the selected profile. Existing SSH/local controls must remain functional.
- [ ] Implement the import panel and HTTP-specific settings presentation. Support enabled/name updates through the established settings route if Task 1 exposes them, otherwise provide the same controls via reimport without accidental credential deletion.
- [ ] Run new tests GREEN, full frontend suite, typecheck and production build. Add usage documentation explaining where to obtain the connection JSON, temporary identity limits, reconnect behavior, and that MOSS workflow support is separate.
- [ ] Self-review, commit Task 2 files, and record report. Controller performs browser QA with isolated state and a whole-branch review, then synchronizes only the verified task diff/build to the original project.
