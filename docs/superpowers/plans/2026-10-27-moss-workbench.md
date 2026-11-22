# MOSS Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Deliver a Chinese MOSS workbench with raw, polish and creative paths and real Colab generation.

**Architecture:** Independent MOSS page and LLM adapter; shared authenticated connection/catalog/generation intent/task/gallery infrastructure. Explicit maintained MOSS workflow and model family; ANIMA behavior stays scoped to ANIMA.

**Tech Stack:** Python/FastAPI/Pydantic/SQLite, React/TypeScript/Vitest, existing ComfyUI Colab.

**Spec:** `docs/superpowers/specs/2026-10-27-moss-workbench-design.md`

## Global Constraints

- Chinese stays Chinese. Raw generation calls no LLM; assisted results require explicit adoption and generation.
- Models: `moss_image_sft_int8`; family `moss`; workflow `v3_moss_image_sft_int8`; baseline `25 / 2.5 / er_sde / simple`, 1024×1024, dimensions divisible by 16.
- Exact assets: `moss_image_sft_int8_convrot.safetensors`, `qwen3.5_9b_w4a8_gptq.safetensors`, `flux2-vae_small.safetensors`; CLIP type `moss_image`, latent `EmptyFlux2LatentImage`, native default shift 5.
- API `POST /api/v3/moss/prompt-assist`: `{source_text, negative_prompt?: string, mode: polish|expand}` → `{positive, negative, changes: string[], warnings: string[], mode, engine}`.
- Preserve explicit input, quoted text and negative prompt; review assistant additions before generating. No new credentials or forced translation, no automatic cloud upsampler.
- No changes to user databases/config during QA or guarded delivery; no weakening access or runtime fences.

## Review Focus

- MOSS leaking into ANIMA-specific model choices or prompt compiler: test family filtering/explicit unsupported API paths.
- Quoted Chinese text changed, omitted or translated by LLM: reject candidate and keep original.
- Late assistance after editing input/mode or unmount: cannot overwrite current draft.
- MOSS frozen graph recovered/retried with ANIMA defaults or text transformations: test actual graph/text/model/recipe.
- Local/cloud catalog compatibility rejects valid Flux2 latent or accepts bad dimensions/assets: test compiled and submitted graph.

### Task 1: MOSS backend model, workflow and assistant

**Files:** Model/runtime/recipe/version/profile modules, cloud catalog model mapping, explicit workflow JSON/catalog, direct generation validations, new `api/moss.py`, minimal app route registration; `v3/tests/test_moss_*.py` and affected exact-list fixtures.

**Interfaces:** Produces the model/workflow IDs and prompt-assist API above; consumes existing LLMService and generation intents; retains existing direct request payload contracts. Bootstrap model options must expose `family` so UI scopes choices. MOSS catalog supported/mapping and dimensions validated at server submission.

- [x] Add meaningful failing tests for family, workflow rendering with Chinese text, MOSS assets/latent/defaults/dimension errors, LLM instructions and response validation, unchanged negative/quoted text, sanitized error and raw direct path without LLM.
- [x] Run new tests red; implement minimal behavior, including explicit rejection of MOSS through ANIMA tag/candidate/LLM paths if those cannot safely support it.
- [x] Run targeted regression and full V3 suite; update exact model-list fixtures only to reflect added model.
- [x] Commit owned files and report actual commands/results; review task diff and fix important findings.

### Task 2: Independent MOSS workbench

**Files:** New `v3/web/src/pages/MossWorkbenchPage.tsx`, scoped CSS and tests; App route, AppShell nav, bootstrap type, ANIMA model filters.

**Interfaces:** Consumes Task 1 API and family metadata, existing generation-target list, model catalog and generation-intent endpoints. Uses localStorage key `moss-workbench-v1`, distinct from ANIMA. Source + selected mode + adopted output revision determine current generation text.

- [x] Add failing interaction tests: raw no LLM, polish/expand correct payload, no implicit adopt/generate, edit/switch fences late result, errors preserve text, scoped models and settings, draft isolation, same intent continuation.
- [x] Implement accessible natural-language page with original input, three modes, optional LLM assistance, editable suggestion and explicit adoption, negative field, pinned environment/workflow/basic settings, generation status/result links. Reuse existing components where appropriate without copying ANIMA conversation logic.
- [x] Run focused tests, full frontend suite, typecheck and production build; commit owned files and obtain task review.

### Task 3: Integrated real acceptance and delivery

**Files:** `docs/v3/MOSS_WORKBENCH_20261027.md`, `v3/STATUS.md`, test evidence in ignored `.local/moss-v1` and original reports folder; minimal integration corrections with regression tests.

**Interfaces:** Actual production local server with isolated DB; existing authorized Colab/Drive; preserve authentication and user data.

- [x] Run original-source baseline capture before implementation. Use current notebook to prepare MOSS only, verify runtime nodes/assets and actual GPU.
- [x] With configured existing LLM, evaluate raw/polish/expand on neutral Chinese scene and preserve quoted text/explicit details; do not invent test success if no usable LLM configuration exists.
- [x] Generate real outputs through local production queue at two dimensions and several requested styles; verify PNG prompt equals frozen workflow and Chinese payload. Check ANIMA→MOSS→ANIMA and runtime safeguards.
- [x] Run appropriate final regression, broad independent review, resolve material findings, record results and limits.
- [x] Build frontend and guard-copy only changed source/build to original project with backup/hash receipt; preserve databases, keys and unrelated changes. Open guide and working page, concise handoff with evidence.
