# Workbench UI design QA

## Visual truth and captured state

- Source: `C:\Users\10937\AppData\Local\Temp\codex-clipboard-9778ecf2-98b5-4830-833a-e60be2d39a51.png`
- Source size: 1507 × 6845 physical pixels.
- Implementation viewport: 1507 × 1000 CSS pixels at device scale factor 1.
- Implementation full-page capture: `C:\Users\10937\AppData\Local\Temp\anima-v3-workbench-qa\workbench-desktop-collapsed.png`
- Implementation full-page size: 1507 × 2393 physical pixels.
- Focused comparison: `C:\Users\10937\AppData\Local\Temp\anima-v3-workbench-qa\comparison-top.png`
- Full-view comparison: `C:\Users\10937\AppData\Local\Temp\anima-v3-workbench-qa\comparison-full.png`
- Desktop resolution matrix: `C:\Users\10937\AppData\Local\Temp\anima-v3-workbench-qa\desktop-resolution-matrix.png`
- Captured state: natural-language input compiled locally; input and candidate sections open; translation, picture-understanding, and artist sections collapsed.

## Comparison findings

- Fonts: existing project typography and hierarchy are preserved; the new outline and disclosure labels use the same sans/serif and monospace conventions already present on the workbench.
- Spacing and geometry: a 164 px page-local outline is added inside the existing content column. The main editor remains three-column at desktop width. Collapsing picture understanding reduces the rendered page from 4197 px to 2393 px for the same result state.
- Colors and surfaces: navigation, badges, section headers, focus states, and disclosure borders reuse the existing dark neutral and violet accent palette. No new competing visual system was introduced.
- Imagery: no imagery or generated-output presentation was changed.
- Copy: section names and helper text are concise, describe the existing regions, and do not change generation semantics.

## Interaction and desktop resolution checks

- Desktop outline buttons open a collapsed destination and scroll it to the top of the viewport.
- Every functional section exposes an accessible `aria-expanded` disclosure button.
- Translation and artist comparison default to collapsed; picture understanding and candidate results can be collapsed independently.
- Standard 2K at 2560 × 1440: page-local outline remains visible, the three-column generation grid remains stable, candidate navigation opens and reveals the destination, and no horizontal overflow was detected.
- Standard 1K/FHD at 1920 × 1080: page-local outline remains visible, candidate navigation aligns the destination near the viewport top, and no horizontal overflow was detected.
- Current laptop: the panel reports 1920 × 1200 physical pixels with a 1280 × 800 effective viewport at 150% Windows scaling. Both the effective viewport and native-resolution simulation preserve the desktop outline and contain all workbench content without horizontal overflow.
- Tablet and mobile layouts are outside this acceptance scope and were not used as release criteria.
- Browser console: zero warnings and zero errors during the checked flow.

## Issue history

- P1 — long result state required 4197 px of vertical scrolling. Fixed with section disclosures; the checked compact state is 2393 px.
- P1 — no persistent way to move between distant workbench regions. Fixed with a sticky desktop outline and sticky mobile selector.
- P2 — low-frequency translation and artist regions added permanent page length. Fixed by collapsing them by default while preserving their content and state.

## Verification

- `npm test`: 45 tests passed.
- `npm run build`: passed.
- 2K, FHD, and current-laptop browser interaction checks: passed.
- Final result: passed.
