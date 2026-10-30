# DemonX PCB Prep — Phase 2H GUI Usability Report

**Status:** Corrections implemented; ready for another physical UI review.  
**Manufacturing approval:** Withheld. This is an inspection-only application.  
**Branch:** `codex/pcb-prep-phase-2a`  
**Previous checkpoint:** `docs/PHASE2G_INSPECTION_PREVIEW_REPORT.md`

## 1. Summary

Phase 2H addresses the viewport jump, CAD navigation, invisible issue selection, frozen-looking imports, cryptic source warnings, and cramped side-panel layout. Gerber parsing and geometry reconstruction continue to use the existing Phase 2A/2D/2E/2F services. The source archive, recovery status, displayed candidate geometry, and machining blocks are unchanged in meaning.

The UI differentiates source contours, the Gerbonara parser interpretation, cached EasyEDA boundaries, proposed derived geometry, and the localized region 79 symmetric difference. The red region 79 overlay is a comparison diagnostic only. Valentine’s verified zero-length no-op recovery is highlighted as an outline; it is not depicted as missing copper. Phase 2A GEOS repair diagnostics are listed separately from Phase 2E no-op source-command records.

## 2. Navigation corrections

- Mouse wheel zoom is anchored to the PCB/world coordinate under the cursor. The view uses the `QGraphicsView` transform and scene mapping; it does not alter source geometry.
- Middle drag and Space+left drag pan using the view’s scroll position. Ordinary left click remains available for scene selection.
- `F` and the **Fit board** toolbar action fit the full board. `Home` resets the transform and centers the board.
- Single-clicking an issue highlights it while retaining the current viewport. Double-clicking an issue zooms to it.
- Region 79 zoom uses the measured maximum-displacement point rather than fitting the entire ring. The zoom is centered at native point `(52.91633606, 66.05388) mm` with its nearest Gerber point shown nearby.
- Scene bounds retain virtual workspace around the board to allow panning while fitted. Layer toggles and issue selection preserve the current scale and center; `sceneRect` is no longer changed to a selected contour, preventing the prior top-left jump.
- Selection outlines, discrepancy lines, and warning markers use cosmetic/fixed-pixel pens and marker sizes so they remain legible across zoom levels.

## 3. Issue highlighting and language

The primary issue list and inspector use plain descriptions with severity and layer. Examples now shown:

- Valentine: **“2 copper regions contain redundant commands.”** Its detail says the hash-bound Phase 2E normalization is shape-preserving and the source files remain unchanged. Selecting one outlines the actual region without a defect marker or a claim of missing copper.
- Laser Module: **“182 copper regions have open boundaries.”** The issue explains that proposed geometry is for inspection and not approved for machining. Selecting a region emphasizes that contour and marks its exact open endpoints.
- Region 79: **“Copper boundary differs from the saved design.”** The issue shows the Gerber contour in orange, saved native boundary in teal, measured symmetric-difference geometry in red, and paired fixed-pixel markers at the maximum measured displacement.
- Parser repair/unresolved-object messages appear as separate **Parser geometry review record** issues. Their advanced details identify the Phase 2A source diagnostic, file/hash, and available repair records; they are not merged with the Phase 2E exact-zero-length recovery status.

The **Highlight issue** checkbox turns these diagnostics on or off. A layer-level parser warning with no location gets no fabricated canvas marker. Every issue inspector includes a suggested review action and a collapsed **Advanced details** section with validation code, source path/hash, command range where available, and numeric comparisons.

## 4. Import feedback and processing

Archive parsing remains on a `QThread` worker. The worker emits textual stages while checking the archive, extracting manufacturing members, parsing each manufacturing file, and combining layer geometry. The toolbar shows an animated text spinner and stage without invented percentages. The application sets a wait cursor while importing and disables the three conflicting import actions; view navigation remains available. A clear Ready state appears after the document and scene are installed.

Errors open a titled dialog with a plain-language message and expandable technical details. The previous board remains loaded if a later import fails; the status explicitly says the previous board was retained. The busy cursor and disabled actions are restored when the worker finishes.

The geometric parsing work is off the GUI thread. Scene construction and widget installation still happen on the GUI thread after parsing. The two supplied boards completed in the automated smoke tests without losing the loading animation; very large future archives may warrant batched scene insertion if installation time becomes perceptible.

## 5. Layout refinement

- Left, canvas, and right panes are in a resizable horizontal splitter. The canvas receives the largest stretch share and the side panes retain practical minimum widths.
- Long source listings are collapsed by default. Advanced forensic detail is collapsed by default. Text panels wrap and do not expose horizontal text scrollbars.
- Common geometry toggles use shorter labels to fit the sidebar. The canvas uses hidden scrollbars with scroll position retained for mouse pan, freeing the canvas edge and avoiding the previous scroll-bar intrusion.
- Typography, warning cards, severity colors, and copper/teal accents retain the DemonX dark theme.

## 6. Automated test outcomes

The latest complete Phase 2G GUI suite run after the interaction/layout changes passed **5 tests** in approximately 40 seconds. It covers:

| Test area | Result / assertion |
|---|---|
| Valentine source wording | Independent Valentine ZIP loads; 2 regions are described as redundant commands; Phase 2E no-op records remain distinct from Phase 2A parser repair records; region outline is highlighted with no missing-copper marker |
| Laser counts and status | 183 circular records, 8 routed slots, 182 open regions; 181 candidate correspondences remain proposals; region 79 metrics and blocked state remain unchanged |
| Wheel zoom | Same world coordinate remains under the cursor within `0.05 mm` in the widget test |
| Pan and selection | Middle pan and Space+left pan both move the view; an ordinary left click selects a diagnostic marker and does not activate pan |
| Fit/Home | Both keyboard actions return to full-board fit |
| Viewport retention | Scale is unchanged and center drift stays below `0.5 mm` (scrollbar quantization) after a layer toggle |
| Issue highlight / localized zoom | Diagnostic switch removes/restores overlays; region 79 difference geometry and two measured-point markers are present; double-click centers within `0.15 mm` of its recorded maximum point |
| Loading lifecycle | Import controls disable; busy cursor appears; stage text changes; spinner advances; successful completion restores controls/cursor and reports Ready |
| Import error | Missing-archive failure displays the error path, restores controls, and leaves no document installed |
| ZIP safety | Unsafe traversal member remains rejected before extraction |

The Phase 2E recovery and Phase 2F revision regression suites also passed **25 tests**. They confirm no change to source hashes, validation statuses, recovery records, drill/slot reconciliation, or native correspondence baselines. Valentine is a second, independent PCB dataset in this repository; no unrelated third-party Gerber ZIP was available.

## 7. Updated review screenshots

![Valentine board and plain-language source status](../phase2g/results/screenshots/valentine-inspection.png)

![Laser Module full board with region 79 selected](../phase2g/results/screenshots/laser-module-full-board.png)

![Localized region 79 boundary difference and measured-point markers](../phase2g/results/screenshots/laser-region-079-inspection.png)

## 8. Launch instructions

The project-local Python environment remains in `phase2g/.venv` with requirements in `phase2g/requirements.txt` and resolved package versions in `phase2g/requirements.lock`. On the repository workstation:

```powershell
cd C:\Users\ogbul\Documents\Github\gerber_to_vectric
.\phase2g\run_pcbprep.ps1
```

Click **Sample · Valentine**, **Sample · Laser Module**, or **Open Gerber ZIP**. To launch with an archive selected:

```powershell
.\phase2g\run_pcbprep.ps1 "C:\path\to\manufacturing.zip"
```

Navigation shortcuts: wheel to zoom at pointer, middle drag to pan, Space+left drag to pan, `F` to fit the board, and `Home` to reset to board view. Single-click selects an issue; double-click zooms to it.

## 9. Remaining items and safeguards

- Region 79 remains blocked pending an authenticated v2.5 native project/revision and controlled fresh copper repour/export evidence. No proposed geometry has been approved for machining.
- Laser source compliance remains nonconforming for all 182 open region contours; machining remains blocked.
- Valentine retains its Phase 2E warning and blocked machining state despite shape-preserving no-op recovery records.
- Primitive-to-source-line mapping remains unavailable through the existing Gerbonara adapter; region command spans have exact lines, and parsed primitives expose source file/object/primitive references and coordinates.
- An animated textual busy indicator has no percentage estimate. Archive parsing is background work; very large scene rendering may eventually need incremental GUI insertion.
- Regression tests emit upstream PyGerber/pyparsing deprecation warnings from Phase 2E/2F, but they pass. GUI synthetic mouse-event tests were updated to the current Qt event constructor.
- No G-code, toolpaths, automatic closure approval, or DemonX integration was added. No DemonX Circuit, Design, or CNC repository was changed. Original Gerbers, native projects, and prior validation records remain preserved.

**Stop point:** Phase 2H is ready for physical review. No subsequent phase was started.
