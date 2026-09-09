# Momentum workspace — design QA

## Result

final result: passed

Scope: the approved session-oriented adaptation of the supplied dashboard, not a pixel-exact clone of the example ticker, prices, or live-agent claims.

## Visual evidence

- Source visual truth: `../docs/design/assets/momentum-reference.png`.
- Implementation: `qa/dashboard-desktop.png`, Home / Demo, no open dialogs.
- Source and implementation are both 1536 × 1024 pixels. Implementation CSS viewport: 1536 × 1024, device scale factor 1.
- Full-view comparisons: `qa/comparison-initial.png` and `qa/comparison-final.png`. Each combines the source on the left with the implementation on the right, both downsampled to 768 × 512.
- Focused comparison: `qa/cards-comparison.png`, unscaled card regions from both original screenshots, aligned at the top. This checks readable typography, padding, borders, and supporting text; the extra 14 px of implementation card height reflects its longer research summary.
- Additional states: `qa/evidence-desktop.png`, `qa/demo-desktop.png`, `qa/home-1280.png`, `qa/home-1024.png`, and `qa/home-390.png`.
- The in-app screenshot API produced a scaled content region with blank padding. That capture was not used as 1:1 evidence. The fixed-size automated browser capture supplied the usable comparison.

## Comparison history and findings

### Iteration 1 — blocked

- **P2: supporting text was too small and pale.** Card summaries, source labels, table metadata, and checklist text were harder to scan than the reference. Increased summaries to 13 px, source labels to 11 px, table rows and checklist to 12 px, with darker neutral foregrounds.
- **P2: first content section started too low.** Reduced hero bottom spacing by 4 px, metric-strip vertical padding by 2 px, and the following gap by 5 px.
- **P2: dialog did not return keyboard focus reliably.** The autofocus input displaced the trigger before the return target was captured. Capture the focused element before mounting the dialog; regression test and mobile drawer browser check now pass.

### Iteration 2 — passed

Compared `comparison-final.png` and the focused `cards-comparison.png` after the fixes. The desktop keeps the same navigation/header/main/rail composition, readable three-card update group, and research table hierarchy. No remaining actionable P0/P1/P2 visual issues were identified in the inspected states.

## Required fidelity surfaces

- **Fonts/typography:** Inter UI text and locally bundled Instrument Serif display text, as selected in the approved design. Instrument Serif is narrower and more editorial than the reference serif; this is an intentional typeface choice, not an exact font match. Headings and excerpts remain distinct from small UI labels. Longer research questions wrap naturally; list summaries truncate with full text available on detail pages.
- **Spacing/layout:** 205 px navigation, 76 px header, flexible main column, and 330 px rail content with its surrounding padding. Soft borders and restrained rounding reproduce the reference structure. Research rows replace market quote rows, so the table content density intentionally differs.
- **Colors/tokens:** warm ivory backgrounds, near-black body text, subtle neutral borders, muted sage accents. Green means recorded status or verified evidence, amber means caveats or unresolved work. Supporting text was darkened in iteration 2.
- **Image quality/assets:** this adaptation deliberately omits ticker logos and sparklines because the primary objects are research sessions, not market quotes. N/M/AI are labeled scope initials, not reconstructed company logos. Lucide supplies interface icons. No generated raster imagery or handcrafted logo approximations are required.
- **Copy/content:** all research values are clearly Demo or local snapshot data. No fabricated current prices, daily returns, live progress percentages, or citation links. Research task completion, report status, and verifier verdict remain separate. Suggested review checks explicitly say they are not dispatched tasks.

## Interaction and responsive verification

- Home → session → evidence → inspector → verification → gaps.
- Research question validation → start Demo → pause → refresh → continue → completed state.
- Source switching persists in the current tab; importer notices are visible.
- Local bookmarks and thesis decisions leave verifier data unchanged.
- Command search, Escape, and focus return have component regression tests.
- 1280, 1024, and 390 px: no document-level horizontal overflow in the Home and mobile navigation flows. The inspector and navigation become dialogs; tables scroll within their container.
- Reduced motion is supported. Controls use semantic buttons/links and labeled inputs.
- Browser acceptance run: 2 tests passed; no page errors in the desktop user journey. A transient development-only context error during multi-file hot reload was cleared by reload and did not reproduce in the acceptance run.

## Remaining validation limits / P3 follow-up

- The repository currently has no actual saved research sessions to inspect. Import behavior is verified with synthetic fixtures plus the real static profile catalog.
- Not a full WCAG conformance audit; browser zoom, screen-reader announcements, and every legacy artifact combination have not been exhaustively tested.
- Remote API pagination, live updates, authentication, and real agent controls are intentionally outside this phase.

## Implementation checklist

- [x] Opened reference and rendered implementation.
- [x] Compared both artifacts in the same full-view and focused inputs.
- [x] Fixed P2 findings and captured the revised design.
- [x] Checked desktop, narrow layouts, interaction states, and page errors.
- [x] Preserved local-only, read-only data semantics.
