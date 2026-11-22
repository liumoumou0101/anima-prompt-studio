# Model and workflow parameter correction

The user has authorized continuing the previously incomplete Turbo parameter fix and checking similar errors. They also reported generic capability rejection after changing workflows. The current externally refined UI must be preserved. The production data and already accepted jobs keep their saved conditions.

Use the existing CreationConfiguration recipeValues/parameterOverrides model. New empty configurations initialize from the selected model/workflow schema and its default recipe. Changing model or workflow rebases known recipe defaults while retaining explicit user overrides, including incompatible drafts for visible correction. Same-model environment changes and catalog refreshes do not authorize changing creation values. Historical snapshots and unclassified legacy values remain exact; merely opening an old record must not overwrite it. Trusted pristine defaults are distinguishable from bound or custom legacy settings. Persistence keeps explicit overrides; submission resolves all workflow fields and synchronizes their core counterparts.

Recommendations come from the current target, not a stale historical baseline. The panel keeps its recipe selection synchronized when its model/workflow changes. Existing saved conditions that differ remain visible and can adopt the correct recipe explicitly. Seed precision, selected dimensions, batch size, resources, and prompt text remain protected.

Fresh reference/example and legacy gallery entry points use model-aware sampling and dimensions. An unknown external model keeps prior fallback behavior. Known MOSS defaults must not be recalculated as the generic portrait aspect.

For capability validation, an apparently current cache can miss files installed after its inspection. A new submission may refresh once on a remote capability rejection, within the existing preparation budget, then retry validation once. Dispatch/execution cached planning remains read-only and cannot initiate that refresh. Missing experimental nodes are reported precisely; the application must not silently remove nodes, change the workflow or install extensions.

Alternatives rejected: resetting every sampling value would erase explicit choices; retaining all previous defaults recreates the bug; weakening resource validation would hide genuinely missing dependencies. The chosen correction uses existing provenance and bounded checks without a new submission protocol or user approval step.

Acceptance: regression coverage for all model defaults, model/workflow/environment transitions, legacy/snapshot restoration, explicit overrides, dimensions and exact seeds; recipe display and actual payload agree; missing-node and stale-file cases have different actionable results; integrated tests/build pass, and a controlled Turbo generation demonstrates the resolved submitted graph on the current cloud environment without mutating existing prompts.
