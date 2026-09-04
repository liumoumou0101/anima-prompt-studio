# Workbench UI design QA

## Visual truth and captured state

- Original long-page reference: `C:\Users\10937\AppData\Local\Temp\codex-clipboard-9778ecf2-98b5-4830-833a-e60be2d39a51.png`
- Pre-refinement 2K captures: `C:\Users\10937\AppData\Local\Temp\anima-workbench-ui-audit-2026-09-03\01-editor-2k.png`, `02-understanding-2k.png`, and `03-candidates-2k.png`.
- Pre-refinement laptop capture: `C:\Users\10937\AppData\Local\Temp\anima-workbench-ui-audit-2026-09-03\04-candidates-laptop.png`.
- Final captures: `C:\Users\10937\AppData\Local\Temp\anima-workbench-ui-qa-2026-09-03\`.
- Side-by-side comparisons: `compare-01-editor-2k.png` through `compare-04-candidates-laptop.png` in the final capture directory.
- Captured state: natural-language input compiled locally with two validated candidate lanes; no remote generation was submitted.

## Refinement findings and fixes

- P1 — 2K underused the available desktop width. The workbench-only page now grows to 1840 px; its usable flow increased from about 1086 px to 1502 px while keeping the global navigation and local outline visually separate.
- P1 — picture understanding was a single deeply nested stack. At 2K it now uses a balanced 55/45 plan-and-evidence split, with confirmed facts grouped under the editable plan. The checked section height dropped from about 1792 px to 1278 px.
- P1 — validation and remote-generation summaries consumed two full rows before candidates. They now share one compact summary row on FHD and 2K, and stack safely on the laptop viewport.
- P2 — candidate cards were narrow and tall at 2K. They changed from about 537 × 738 px to 744 × 663 px, with tighter prompt spacing and aligned footers while preserving the two-column comparison.
- P2 — the page-local outline used 7–9 px metadata. Its labels, metadata, badges, and guidance now use clearer 8–11 px sizing and higher secondary-text contrast.
- P2 — generation controls did not use 2K width efficiently. They use five columns at 2560 px, remain three columns at 1920 px and 1280 px, and preserve all existing controls and values.
- The existing dark palette, typography, focus treatment, disclosure behavior, and candidate-lane colors are preserved. No generation, API, workflow, preset, or state logic was changed.

## Desktop resolution checks

- Standard 2K, 2560 × 1440: 1840 px workbench page, 1704 px local layout, 1502 px content flow, five-column generation controls, two-column picture understanding, 744 px candidate cards, and no horizontal overflow.
- Standard FHD, 1920 × 1080: 1673 px workbench page, 1335 px content flow, 184 px local outline, three-column generation controls, stacked picture understanding, 660 px candidate cards, and no horizontal overflow.
- Current laptop effective viewport, 1280 × 800: 1033 px workbench page, 738 px content flow, 176 px local outline, three-column generation controls, stacked picture understanding, two 362 px candidate cards, and no horizontal overflow.
- Tablet and mobile layouts remain outside this acceptance scope and were not used as release criteria.

## Interaction and code checks

- Local outline navigation updates the active item and moves between editor, understanding, candidates, and artist regions.
- Candidate disclosure closes and reopens without losing the compiled result.
- Browser console reported zero warnings and zero errors in the checked flow.
- `npm test -- --run`: 45 tests passed.
- `npm run build`: passed; the existing Vite advisory for a JavaScript chunk larger than 500 kB remains unchanged.
- Final result: passed.
