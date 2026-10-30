# DemonX PCB Prep — Phase 2I Practical Validation and User Guidance

**Status:** Practical validation and guidance checkpoint complete; ready for physical review.  
**Manufacturing approval:** Withheld. No toolpath or machining eligibility is granted.  
**Branch:** `codex/pcb-prep-phase-2a`  
**Date:** 2026-10-25

## 1. Summary

Phase 2I changes how the inspection preview explains existing evidence. It does not change source Gerbers, source archives, recovery rules, geometry interpretation, or machining guards. The same Phase 2A/2D/2E/2F parsing and validation services remain in use; this work adds display classifications, explanatory text, regression cases, and external test fixtures.

Valentine’s 119 exact zero-length region draws now appear as **HANDLED · formatting**. The original source remains nonconforming under the adopted 2026.05 check, but that finding alone requires no user action, creates no copper-defect highlight, and does not change the source bytes. Two separate Phase 2A bottom-copper GEOS repairs remain **NEEDS VERIFICATION** because the input rings are self-intersecting and isolation-offset impact is not established.

Laser Module retains all 182 open-contour findings. The 181 v2.0 saved-fill correspondences remain proposed display geometry only. Region 79 remains **BLOCKED** and shows its localized difference. Overall source-standard status, geometric verification, and machining eligibility are shown separately; both example boards still show machining **BLOCKED**.

## 2. Valentine zero-length and GEOS findings

### Exact zero-length draws

The existing Phase 2E evidence identifies **119** zero-length region D01 draws in two source regions. The disclosed recovery removes only those zero-length path steps in the derived inspection model. It inserts no edge, moves no coordinate, and changes no source file. The GUI shows one neutral aggregate finding with the category HANDLED and “No action is needed for this finding.” It no longer outlines either entire region as if copper were defective.

This is a narrow no-op handling of a source-format issue. The source conformance badge still reports that the source is nonconforming, and the board remains machining-blocked by the separate GEOS geometry findings. No claim is based on prior fabrication by JLCPCB.

### Phase 2A GEOS repairs

The two records are shown separately, bound to `Gerber_BottomLayer.GBL` with SHA-256 `f701e7ada043321c89a2c3baf73a84c32a3aad93cc3259bd9eff07bbd8e47843`:

| Source object | Raw polygon area (mm²) | `make_valid` area (mm²) | Area delta (mm²) | Repaired representation |
|---:|---:|---:|---:|---|
| 0 | 2721.0544847200626 | 2721.0544847200526 | −1.000444171950221×10⁻¹¹ | GeometryCollection; 1 polygonal component and a MultiLineString remainder |
| 1 | 410.99482327839974 | 410.9948232784001 | +3.410605131648481×10⁻¹³ | GeometryCollection; 1 polygonal component and a MultiLineString remainder |

Both raw polygons were invalid. Repeating `make_valid` gave byte-identical normalized WKB for each record. Each raw ring and its repaired polygonal boundary have a GEOS Hausdorff distance of **0.0 mm** (same boundary support), but the path lengths differ: object 0 is **2282.850057 mm** raw versus **1804.717597 mm** repaired; object 1 is **176.413753 mm** versus **175.179493 mm**. The repaired material-area deltas remain at floating-point noise scale.

A bounded diagnostic sensitivity run compares a generic Shapely/GEOS negative buffer on the raw invalid polygon with a negative buffer on its explicitly repaired polygonal part (`quad_segs=16`). At a **0.05 mm** inset, object 0 produces **23.174808194 mm² symmetric difference and 7 versus 6 connected components**. At 0.1 mm, the difference is 45.210588180 mm² (15 versus 12 components); at 0.2 mm, 86.090311756 mm² (21 versus 15); at 0.5 mm, 176.238064160 mm² (48 versus 11). Object 1's tested offsets have zero symmetric difference, with equal component counts. Full numeric output is in [geos-repair-sensitivity.json](../phase2i/results/geos-repair-sensitivity.json), and its principal values are regression-golden checks.

This is **diagnostic morphology sensitivity**, not a V-bit path or cutter simulation. Buffering an invalid polygon has its own GEOS interpretation; neither branch is an independent oracle for intended copper. The 0.05 mm case is a generic circular inset, not a depth-dependent 30° V-bit calculation. It does show that object 0’s near-zero area delta and zero boundary-support distance do not guarantee equivalent downstream offsets: parser representation can yield materially different candidate isolation geometry. The UI shows this numerical warning in Advanced details, while keeping the issue NEEDS VERIFICATION and bottom-copper machining blocked. The exact designed copper material, correct offset policy, and final cutter/depth-specific geometry remain unresolved.

In the separate Phase 2C interpreted full-layer comparison, the parser/composition outputs had matching **110 components and 181 interior voids**; their maximum boundary Hausdorff distance was **0.000981454668 mm** and symmetric-difference area was **0.323800485244 mm²**. Both paths used Shapely/GEOS `make_valid`; this is parser/composition agreement, not independent confirmation of self-intersecting ring semantics. Symmetric difference against an invalid polygon’s presumed filled material is undefined.

## 3. Laser Module findings

- **182 open bottom-copper contours** remain reported as source-nonconforming and NEEDS VERIFICATION. The missing edges could change isolation clearance. Proposed closure geometry is display-only; no automatic closure acceptance was introduced.
- **181** contours have one-to-one correspondences to cached copper-fill paths from the recovered EasyEDA v2.0 reference. Their maximum full-ring boundary Hausdorff distance is `0.001488761878 mm`. This is evidence for a proposed visual interpretation, not proof that the missing v2.5 source edges are intended or manufacturing-ready.
- **Region 79** remains BLOCKED. Its saved-fill comparison has maximum boundary displacement `0.284123324586 mm` and symmetric difference `3.540171130422 mm²`. The UI distinguishes Gerber source contour, cached native boundary, and the localized magenta difference. The v2.5 native revision and fill-refresh provenance remain unavailable.
- Individual region rows retain endpoints and available source line ranges. Aggregate warnings do not fabricate a point marker. All 183 circular drill records and eight slots remain present; Phase 2I changed no drill classification, deduplication or geometry baselines.

## 4. Interface changes

### Issue categories and user guidance

Each issue record now has one of these display categories:

- **HANDLED** — verified safe processing for that finding only. Valentine’s redundant no-op commands are the current example.
- **NEEDS VERIFICATION** — an intended boundary or geometric effect remains uncertain. This applies to the two Valentine GEOS repairs and Laser’s open contours, including the 181 reference matches.
- **BLOCKED** — this affected operation cannot safely proceed. Laser region 79 is the current localized example.

The source-standard badge, category, and machining-eligibility badge remain separate. A HANDLED formatting finding cannot clear unrelated geometry issues or change overall machining eligibility.

The inspector uses short explanations about the effect on isolation clearance. It offers **View geometry** only when a specific affected region is available, and **Open another Gerber ZIP** for a supported archive. HANDLED findings say no action is needed and do not show competing actions. No “proceed anyway” action exists. Hashes, exact command ranges and geometry metrics remain collapsed under Advanced details.

### Visualization, layout and import feedback

- The canvas has a compact copper/source/proposed/difference/native legend. Magenta is reserved for a measured discrepancy; the handled Valentine finding receives no defect outline.
- The side panes remain resizable. The right inspector is margin-padded and hosted in a vertical scroll area with wrapped text and no horizontal scrollbar. Advanced evidence and the source-file tree start collapsed.
- Import now displays a centered animated activity card over the PCB viewport. It shows the actual current archive stage with no percentage estimate. Archive parsing stays on the worker thread; the brief scene/widget installation still occurs on the GUI thread.
- Import actions are disabled during processing. The normal Ready state returns on completion; errors retain the previous board and show a clear import-failure dialog.

## 5. Independent regression corpus

### Ucamco official cases

The official [Ucamco Gerber Format downloads page](https://www.ucamco.com/en/guest/downloads/gerber-format) lists a Gerber Layer Format test ZIP dated 19 May 2026. The downloaded archive is preserved at `phase2i/fixtures/ucamco-gerber-tests.zip`, SHA-256 `7e1e6bacdc24deb92fbf08940d37ccd26cff25fc9e5ca608b919d4d542d2698f`. Ucamco describes the official [Reference Gerber Viewer](https://www.ucamco.com/en/gerber/reference-gerber-viewer) as a viewer for Gerber, Excellon and related formats and points to sample CAD jobs for testing.

The Phase 2I suite parses six ordinary Ucamco examples and verifies object counts. It checks the primitive type inventory for `Polarities_and_Apertures.gbr` and the two five-millimetre square outlines, their one-millimetre separation, and 0.01 mm stroke width in `Two_square_boxes.gbr`. The two aperture-block examples are asserted as unsupported by current Gerbonara 1.6.3; warnings and parse errors are intentionally visible rather than treated as successful geometry.

Three additional hand-authored linear-region files cover a valid square, a genuinely open contour, and a closed self-crossing contour. Tests use the existing constrained Phase 2D source scanner and exact predicates; these fixtures are not represented as Ucamco conformance files.

**Licensing:** No separate reuse license was included in the Ucamco test ZIP or listed on its download entry. The [Ucamco terms](https://www.ucamco.com/en/terms) reserve rights not expressly granted. The local copy is for this requested engineering validation; obtain a specific redistribution grant or switch to first-party download-on-test before publishing or bundling it.

### KiCad-generated project

KiCad CLI **10.0.7** exported a local installed `interf_u.kicad_pcb` demo into `phase2i/fixtures/kicad-interf-u/`; the input board hash is recorded in `phase2i/fixtures/README.md`. Top, bottom, Edge.Cuts, drill and job files were also packaged in `kicad-interf-u-export.zip`. Gerbonara parsed **903** top-copper objects, **862** bottom-copper objects, **9** profile objects and **401** Excellon circular hits. The archive loader identifies all four layer functions and reports the hits.

This is a parser/layer regression fixture with source geometry available, not an independent numerical gold standard: the Gerbers were produced by KiCad and then read by the same selected parser. The narrow Phase 2D command scanner does not support the KiCad coordinate declaration, and the imported bottom layer emits one Phase 2A GEOS repair warning. Both remain asserted unresolved. Gerbonara also warns that KiCad’s `G90` appears after the Excellon header; the 401 hits still parse and reconcile.

The installed demo folder contained no project-specific license file. KiCad’s [license page](https://www.kicad.org/about/licenses/) describes software/library licenses but does not establish this particular demo board’s reuse terms. Keep these fixtures local until the board’s project-specific license is confirmed before redistribution. The CLI emitted access-denied messages while checking Windows KiCad preference/registry paths, but it generated all requested outputs in the Phase 2I fixture directory; it did not modify the source board.

No external independent trusted geometry image was used as a numeric golden in this phase. Ucamco’s bundled PNG previews are retained inside the archive but were not pixel-diffed against a generated render. The numerical golden assertions above come from source coordinates or recorded fixture metrics, and are labeled as such.

## 6. Automated verification

Run the entire regression sequence with:

```powershell
.\phase2i\run_regressions.ps1
```

Latest complete Phase 2A–2I run: **88 tests passed** across eight suites (Phase 2A through Phase 2I; Phase 2A uses pytest). The full output is preserved in [regression-suite.txt](../phase2i/results/regression-suite.txt). After strengthening the Ucamco primitive/path assertions, the seven-test Phase 2I suite was rerun independently and also passed.

Coverage includes prior source/archive hash baselines; drill, slot and recovery guards; region closure and cut-in cases; copper/topology and registration baselines; Laser source/native correspondence and region 79; viewport navigation and retention; issue-selection/diagnostic visibility; loading lifecycle/error handling; ZIP traversal rejection; Valentine handled wording; the separate two-object GEOS repair records; Ucamco parser/primitive behavior; KiCad layer/hit import; and centered progress-card placement.

Observed non-failing dependency warnings: Gerbonara flags KiCad’s `G90` header position and the Ucamco block examples it does not implement; PyGerber/pyparsing emits deprecation warnings in earlier phase suites. The Ucamco block cases remain explicit parser limitations, not passes.

## 7. Screenshots and launch

Review captures were generated at 1700×1000 from the read-only UI:

![Valentine handled formatting finding](../phase2i/results/screenshots/valentine-handled.png)

![Valentine bottom-copper GEOS repair requiring verification](../phase2i/results/screenshots/valentine-geos-repair.png)

![Advanced diagnostic inset sensitivity for Valentine GEOS repair object 0](../phase2i/results/screenshots/valentine-geos-offset-sensitivity.png)

![Laser Module with all 182 open contours summarized](../phase2i/results/screenshots/laser-full-board.png)

![Laser Module region 79 localized difference and blocked status](../phase2i/results/screenshots/laser-region-79-blocked.png)

Launch the standalone preview on this workstation:

```powershell
cd C:\Users\ogbul\Documents\Github\gerber_to_vectric
.\phase2g\run_pcbprep.ps1
```

Choose **Sample · Valentine**, **Sample · Laser Module**, or **Open Gerber ZIP**. Wheel zoom, middle-button drag, Space+left drag, `F`, and `Home` navigation remain available.

## 8. Remaining blockers and acceptance

| Acceptance item | Phase 2I result |
|---|---|
| Valentine’s 119 zero-length draws presented as handled; source hashes/files retained | **PASS** |
| Handled formatting finding creates no whole-pour issue highlight and does not clear unrelated machining blocks | **PASS** |
| Both bottom-copper GEOS repairs separately visible with measured deltas | **PASS for disclosure; NOT VERIFIED for intended boundary** |
| Repair effect on reviewed copper boundary and topology independently established | **NOT VERIFIED** — invalid-ring semantics, shared GEOS repair, and absent native copper confirmation remain |
| Repair sensitivity of generic derived offsets measured | **PASS as diagnostic only** — object 0 differs by 23.174808194 mm² at a 0.05 mm inset; not an approved V-bit toolpath |
| Actual cutter/depth-specific isolation geometry verified | **NOT VERIFIED** — no validated source boundary or manufacturing engine exists |
| Laser retains 182 open-boundary findings and 181 proposals as display-only | **PASS** |
| Region 79 remains localized and blocked | **PASS** |
| All UI issues distinguish source conformance, geometry verification, and machining eligibility | **PASS** |
| Right inspector wrapping, margins, scrolling, and centered animated import stage | **PASS in automated offscreen/UI smoke tests; physical display scaling review pending** |
| Official Ucamco and KiCad-generated data added with provenance and limitations | **PASS as local regression data; redistribution license review pending** |
| Existing and Phase 2I regression suites | **PASS — 88 tests; latest Phase 2I corpus assertions rerun** |
| Manufacturing readiness | **NOT CLAIMED; machining remains blocked** |

No Gerber or EasyEDA source file, original supplied archive, other DemonX repository, manufacturing toolpath or CNC output was modified or produced. Phase 2I stops here for physical UI review.
