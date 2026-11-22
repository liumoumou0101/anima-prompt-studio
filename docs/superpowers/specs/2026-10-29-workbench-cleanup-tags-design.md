# Workbench cleanup and tag consistency

## Intent

The user explicitly requested removing obsolete workflow clutter, then checking role/artist tag addition and the whole workbench logic. After fixes, build and tests, terminate Colab compute and shut down the PC. This continues the parameter/capability repair; existing UI refinements and user text remain authoritative.

## Scope and approach

- Remove 25 audited obsolete, duplicate, experimental or incomplete templates from active catalogs. Persist a recoverable removal marker and original version snapshots rather than rewriting packaged history definitions. Keep 9 main-generation entries plus the dedicated Tile Upscale source used by the gallery.
- Retain current MOSS and 2.9B preview definitions despite missing weights on this runtime. Missing runtime files alone are not evidence of obsolescence. Preserve gallery's valid five-node super-resolution path.
- Plain new submissions cannot select removed templates. Frozen history with a saved graph/schema/config remains usable without a current catalog entry. Historical images, prompts, source records, raw profiles and credentials are preserved.
- Trace role, series, general and artist tags from UI selection through requirements, compile, save/reopen and actual submitted prompt. Fix only reproduced inconsistencies; preserve manual prompt text and MOSS Chinese support.
- Review adjacent draft, model/environment switching, undo, pending submission and snapshot boundaries for concrete failures. Do not redesign the UI or add speculative features.

Alternatives considered: physical deletion of packaged definitions would break old sources and require changing unrelated graph fixtures; disabled flags still clutter choices and also reject frozen history. Recoverable removal addresses the user's operational problem with a smaller change.

## Completion

Targeted regressions, final full backend/frontend suites, typecheck, production build, guarded delivery and actual UI exercise must pass. Run a representative tag-based cloud generation if prepared models and the connection remain available. Then disconnect and delete the active Colab runtime, verify disconnected/no compute, save completion evidence, and issue the explicitly authorized Windows shutdown. Do not download unprepared weights.
