# Four-appearance workbench design QA — 2026-09-12

final result: passed

## Visual truth and comparison scope

Source directory: `C:/Users/MSN/.codex/generated_images/01a09066-e406-7140-8751-697ff98c5783/`.

- Studio light: `exec-0c06b537-c878-4579-98e7-36a206012aea.png`.
- Studio dark: `exec-fe6f0fc6-c301-49fa-92c1-8eff02a86a69.png`.
- Editorial light: `exec-c2abd623-dd9d-4e16-836d-65b25581a8a9.png`.
- Editorial dark: `exec-29e68dfc-cffa-43fe-a322-819c838211e0.png`.

Implementation evidence: `H:/soft/提示词工具2/docs/v3/audits/2026-09-12-ui/`. The final four files are `{studio,editorial}-{light,dark}-1440-final.png`; two laptop captures are `studio-1280-final.png` and `editorial-1280-final.png`. Combined source/implementation evidence: the four `*-final-comparison.jpg` files. A focused scene-controls/prompt comparison is saved as `focused-controls.jpg` (density iteration before the final action bar).

Source images measure 1487×1058 pixels. Main implementation captures measure 1425×1013 pixels for a requested 1440×1024 CSS viewport (browser capture excludes viewport chrome/scrollbar edges). Source images are contained to the implementation image size for combined comparisons; no stretching or pixel-level equality claims. The reference and implementation were opened together in the same review input, and an independent reviewer inspected all four pairs plus the 1280 captures.

State: an existing conversation with one completed-image fixture, editable prompt, empty optional identity selection, five scene controls, and explicit actions. Final captures also show a local unsent change and selected shot to verify disabled generation. The concept uses imaginary multi-image Frieren content; the offline fixture uses a locally collected meadow reference and a single image, explicitly labelled as a layout sample. Different content, absence of fabricated character portraits and additional runtime controls are intentional, based on the implementation constraints in `docs/v3/UI_REDESIGN_20260912.md`. This is an implementation of the selected layouts and interaction requirements, not evidence of image-generation fidelity.

## Findings and iteration history

- P1 fixed: the interrupted implementation had new layout markup but old hardcoded black/purple workbench CSS. Replaced the workbench presentation and connected shared tokens throughout controls and states.
- P2 fixed: the optional identity editor used tall multi-line fields and pushed the prompt far below the fold (`01-studio-before-density-fix.png`). It now uses three compact rows when expanded, folds to one line when empty, and preserves mounted fields and their values.
- P2 fixed after first full comparison: model information and all three main actions were below the desktop viewport (`*-1440.png`, `*-1280.png`). Final screenshots show a fixed desktop bar containing model/size/count, readiness, Update Prompt, Save, and Generate. In a 1280×800 CSS viewport its bottom is 784px; at 1440×1024 it is 1008px. Narrow screens place the same controls in normal flow. No duplicated business actions were introduced.
- P2 fixed: selecting Generation Settings opened a distant section without showing it. It now opens and scrolls to the actual parameter section. The action-bar shortcut also reopens a manually collapsed section. Evidence: `editorial-390-settings.png`; regression tests retain prompt-node identity, manual text and negative text.
- Post-fix review: no remaining actionable P0/P1/P2 visual issue found in the captured scope. Keyboard Tab from the gaze selector focuses the target input above the bar: input bottom 413.9px, bar top 701.6px at 1280×800. Inputs use scroll margins; page bottom padding keeps final content reachable.

## Required fidelity surfaces

- Fonts/typography: shared Chinese-capable Segoe UI / Microsoft YaHei UI / PingFang SC sans-serif; main prompt 14px in studio and 16px in editorial, with generous line height. Editorial's Latin brand uses Georgia while Chinese body remains sans-serif as required. Metadata uses smaller secondary text. No oversized English decoration remains.
- Spacing/layout rhythm: side navigation and paired editing/result regions in studio; top navigation and prompt-priority composition in editorial. Shared actions remain available at desktop size. The five-control schema and explicit source review intentionally require more vertical space than the illustrative mock. Single-column reflow preserves all controls.
- Colors/tokens: warm light panels, neutral charcoal night panels, green and terracotta accents. Automated palette checks cover text, semantic colors, primary-button text, control boundaries and focus for all four combinations. No purple backgrounds remain in the workbench. Disabled controls remain readable.
- Image quality/assets: real imported/reference thumbnails are used; images retain aspect ratio and have no theme filter (`filter: none` in all four combinations). A single result is shown as one result, without fake thumbnail variants or generated identity portraits. Icons come from the established Phosphor library.
- Copy/content: Chinese operational labels retain separate meanings for advice, adopting a suggestion, updating prompts, saving and generating. Requirements, pending input and unavailable generation remain explicit. Unknown model parameters are not supplied by the visual layer.

## Interactions and validation

- Four-mode switching retained unsent text, manually edited prompt, selected shot and image. Layout changes keep the same route/component nodes, maintain reading anchors when scrolled and do not steal focus; theme changes do not add scrolling.
- Scene controls change local drafts; an offline advice failure preserves inputs. Unit/integration coverage includes stale results, target ownership, locked layers, sources, clear/undo and conflict handling.
- Actual local production app was opened after rebuilding and restarting the API. Its existing conversation list and reference thumbnails loaded; reference light/dark rendering was checked (`references-dark-1440.png`). Captured production/browser error and warning logs were empty in the checked flow.
- Requested viewports and measured document widths: 1440→1425px; 1280→1265px; 720→705px; 390→375px. No horizontal document overflow found. 720×512 is a reflow-width check; the in-app browser did not respond to zoom keyboard shortcuts, so actual browser 200% zoom is still unverified.
- Backend full suite: 609 passed. Frontend full suite before the final parameter-navigation/action-bar changes: 33 files, 208 passed. Final affected workbench/shell/appearance suites: 55 passed; the current frontend contains 209 tests. TypeScript and production build passed.
- Build command: `npm run build -- --emptyOutDir false`. Regular output-directory cleanup hit the previously documented Windows native-process exit; preserving dist succeeds. The existing bundle-size advisory remains.

## Follow-up polish and limits

P3: studio at 1280×800 still requires scrolling to read the full prompt; the action bar makes the key actions immediately accessible. Repeated title/selector/state metadata could be compressed further, and the bar could show the recipe name alongside the model.

No new real LLM or GPU request was made. Visual/state checks do not prove natural-language semantic correctness or model image quality. Actual 200% browser zoom and a new Windows installer roundtrip remain outside this verified pass. Existing alpha.3 release packages have not been rebuilt with this UI.
