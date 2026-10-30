# DemonX PCB Prep — Phase 2G Inspection Preview Report

**Status:** Phase 2G inspection checkpoint complete; physical UI review requested.  
**Manufacturing approval:** Withheld. No machining eligibility is granted by this phase.  
**Branch:** `codex/pcb-prep-phase-2a`  
**Scope:** Region 79 forensic comparison and read-only PySide6 inspection preview.

## 1. Executive findings

- The v2.0 and archived v2.5 Laser Module bottom-copper exports contain the same 182 region command sequences. Phase 2F also matched their top copper, drill bodies, slots, and profile bodies. This does not establish that the missing v2.5 native revision was identical to v2.0.
- The 181 candidate rings other than region 79 have one-to-one cached-fill path correspondences. Their maximum measured boundary Hausdorff distance is `0.001488761878 mm` (region 11), below the `0.005 mm` comparison threshold. They may be shown as **proposed recovered geometry** in the preview only. The original source remains nonconforming and every Laser Module machining operation remains blocked.
- Region 79 is a full-ring outlier: boundary Hausdorff distance `0.284123324586 mm`; symmetric difference `3.540171130422 mm²`. Its source contour, candidate end-to-start chord, and mapped v2.0 cached native fill are all retained separately. The discrepancy mechanism cannot be assigned confidently to stale fill, a different design state, or export behavior without native v2.5 and cache-refresh provenance.
- The preview reuses Phase 2A Gerbonara parsing and primitive conversion, Phase 2D source-region scanning, Phase 2E validation/recovery records, and Phase 2F native-fill mapping. It does not make a second parser or modify any source archive. It has no toolpath, G-code, or CNC export operation.
- Phase 2E/2F regressions passed: 25 tests. Phase 2G model, GUI smoke, and ZIP traversal tests passed: 4 tests. The preview is not a manufacturing-readiness test.

## 2. Region 79 investigation

### 2.1 Immutable source evidence

The original archives and native project remain unchanged. The comparison uses the Phase 2F fixture copies, whose SHA-256 values are bound in the previous report:

| Evidence | SHA-256 |
|---|---|
| EasyEDA v2.0 export ZIP | `d17abf51ea793d7151f7cb452db5bc97a0a1a2d1f1859414c1b37a13c884e1c8` |
| Recovered v2.0 native PCB JSON | `8e16382c5dc9b546e43ed96562e6e58124069c2bac80ba7529d80c19907e3cd9` |
| Archived v2.5 Gerber ZIP | `5e682b600dd19ee798d11830f0867f8cd686853d6a05620b8af174ba9ed3eb33` |
| v2.0 `Gerber_BottomLayer.GBL` | `7ea428faea2d0919adc42e1209fa5d90d7106335a4bd163cd845ec44d903e04d` |
| v2.5 `Gerber_BottomLayer.GBL` | `6a6e08f4bf30852202e56e76d6ec43f50bcf564f33ef184e35afa71f4118359c` |

Region 79 is in `Gerber_BottomLayer.GBL`, G36/G37 command range lines **4845–5637**. The source has 790 coordinate points and 789 source D01 draw segments. Its source coordinate tick is `0.00001 mm`; all region interpolation commands are G01. Gerbonara exposes 790 segments after its implicit closure; PyGerber exposes 789. The Phase 2D independent command scanners report zero coordinate delta from the source records for both representations. These parser comparisons establish that the region command sequence was read consistently; they do not resolve intended fill.

Source path start: `(49.23485, 37.96436) mm`.  
Source path end: `(49.09058, 37.98265) mm`.  
Diagnostic straight end-to-start chord: `0.145424746862 mm`.

The candidate polygon is created only for measurement/display by joining the source path endpoints. It is not written to the source, and its validity is not evidence of intended manufacturing geometry. The region's source polarity is clear; the display must therefore be understood as a contour/polarity diagnostic, not unconditional positive copper.

### 2.2 Exact maximum-displacement evidence

The largest measured displacement pair is:

| Item | Source segment / coordinates |
|---|---|
| Gerber command | Line 5248, modal G01 command `X5304332Y6579971D01*` |
| Gerber segment | segment index 400: `(53.09971, 65.82816)` to `(53.04332, 65.79971) mm` |
| Nearest point on Gerber segment | `(53.044316727201405, 65.80021287087924) mm` |
| Mapped cached native fill path | `COPPERAREA`, bottom copper, net GND, path index 3 |
| Native segment | mapped segment index 406: `(52.97276470, 66.08212734)` to `(52.91633606, 66.05388000) mm` |
| Native point at measured maximum | `(52.91633606, 66.05388) mm` |
| Distance | `0.284123324586 mm` |

The nearest-point comparison is computed from the exact line-segment coordinates after the Phase 2F affine native-to-Gerber coordinate transform. The transform's four-corner outline residual was `0.0000011 mm`; that global fit is not a cause supported by the evidence.

### 2.3 Full-ring comparison

| Measurement | Gerber path plus diagnostic chord | Mapped cached native path 3 |
|---|---:|---:|
| Area | `306.737089685450 mm²` | `309.788283188824 mm²` |
| Bounds (mm) | `[34.44036000, 37.96436000, 70.87108000, 70.36206000]` | `[34.44011952, 37.96446196, 70.87084930, 70.36225594]` |
| Polygon validity | valid | valid |
| Interior rings in the compared path | 0 | 0 |

Symmetric-difference area is `3.540171130422 mm²` over 422 difference components. The largest component is `3.034548517488 mm²`, with bounds `[46.73566897, 63.36792000, 64.92439460, 69.98337334] mm`, or approximately `18.188726 × 6.615453 mm`. Boundary Hausdorff distance is `0.284123324586 mm`. The Hausdorff value is computed by GEOS on the polygon boundaries with densification; the annotated plot marks the recorded maximizing pair. The plot is diagnostic, not independent proof of source design intent.

The forensic script additionally sampled source line segments at spacing no greater than `0.005 mm` against the mapped native boundary. Nine spans exceed `0.005 mm`; these are sampled maxima, not exact continuous maxima:

| Gerber lines | Segment endpoint coordinates (mm) | Sampled maximum distance (mm) |
|---|---|---:|
| 5180–5186 | `(61.94247,64.25692)` → `(65.86829,68.42810)` | 0.104602 |
| 5238–5256 | `(64.90563,69.96582)` → `(46.75581,63.36792)` | 0.284080 |
| 5285–5288 | `(41.04843,63.36792)` → `(40.59326,63.78905)` | 0.095522 |
| 5302–5307 | `(39.09466,64.28181)` → `(37.34257,64.24930)` | 0.039022 |
| 5312–5321 | `(36.82542,64.24930)` → `(35.33343,64.20256)` | 0.080166 |
| 5348–5350 | `(35.74542,62.35344)` → `(37.21455,62.37630)` | 0.079851 |
| 5353–5355 | `(37.43655,62.43624)` → `(39.12819,62.43167)` | 0.039217 |
| 5358–5372 | `(39.35018,62.34226)` → `(40.57700,61.60211)` | 0.095366 |
| 5374–5380 | `(40.64203,61.60008)` → `(50.90515,61.42634)` | 0.090485 |

Full machine-readable segment details are in `phase2g/results/region79-analysis.json`.

### 2.4 Cause assessment and unresolved evidence

Evidence does not support a global registration error, parser command loss, source precision loss, or direct Gerber arc polygonization error for region 79. The source contains linear commands, and the coordinate frame agrees closely with the board outline and the other 181 mapped rings.

The remaining discrepancy is between the region's source boundary and a saved EasyEDA v2.0 `COPPERAREA` cache path. The cache record does not establish when it was last repoured or which exact board revision generated it. The v2.5 original native project is missing. Therefore these causes remain indistinguishable:

1. The saved v2.0 cached fill may be stale relative to its source layout.
2. The native design or cached fill may represent a different copper-pour state than either Gerber export.
3. A region-specific omission or geometry change may have occurred during export.
4. A genuine layout/pour difference may exist, even though the v2.0 and v2.5 Gerber region command sequences are identical.

To resolve this, the evidence needed is an authenticated v2.5 EasyEDA PCB project/revision or a project revision hash, and a controlled fresh native copper repour followed by an export from that exact revision. The export manifest must bind the project revision, exporter version/settings, Gerber hashes, and a saved-fill freshness/repour event. A side-by-side native editor inspection may help, but a visual resemblance alone does not replace the revision-bound comparison.

### 2.5 Other 181 regions

All 181 other candidate rings have a unique one-to-one mapped cached path under the Phase 2F edge-correspondence mapping. None exceeds `0.005 mm` boundary Hausdorff. Maximum is `0.001488761878 mm` for region 11. Their agreement supports a **narrow, source-hash- and exporter-specific display proposal**, not global Gerber closure and not manufacturing eligibility. The v2.0 cached fill is still a saved cache, and the v2.5 native revision is still unavailable.

## 3. Preview recovery/evidence policy

The UI retains three separate concepts:

1. **Source parser interpretation:** the existing Gerbonara/Phase 2A interpretation. The UI labels it as parser geometry; it does not call it source-conforming.
2. **Disclosed derived/proposed geometry:** for known source hashes only, with the Phase 2F mapped cached fill as evidence for regions 0–78 and 80–181; Valentine uses existing Phase 2E hash-bound no-op recovery records. These remain proposals.
3. **Hypothetical closure geometry:** the open source region's endpoint chord, drawn separately as a dotted/dashed diagnostic. It is never substituted into original commands.

Region 79 is marked **BLOCKED · FULL-RING OUTLIER**, and its hypothetical chord and native path are distinguishable. No region candidate is accepted for machining. Laser source status is `NONCONFORMING — 182 open region contour(s)` and machining is `BLOCKED`. Valentine continues to show its Phase 2E warning and blocked machining status. This phase adds no global auto-closure, snapping, unrestricted `make_valid`, source edits, or changes to Phase 2E validation rules.

The evidence mapping is intentionally bound to known source hashes. Unknown archives can be opened and parsed for inspection, but cannot inherit the v2.0/v2.5 native-fill proposal policy.

## 4. Standalone inspection preview

### Capabilities

- Opens Gerber/Excellon ZIP archives with member path, size, compression-ratio, duplicate-name, and symlink checks before extracting only detected manufacturing files to a temporary directory.
- Detects and labels available layers; displays parsed top/bottom copper and board profile; toggles copper, profile, flash/pad features, circular drill centers, routed slots, source contours, disclosed candidates, and native cached-fill overlays.
- Supports zoom, pan, fit-to-board, issue selection, and region 79 selection/zoom. The right inspector reports source hash, Gerber file and region line range, closure endpoints/length, comparison metrics, polarity, status, and required action.
- Feature selection exposes parser source-file/object/primitive metadata and available source coordinates. Gerbonara does not retain original command line numbers for every primitive in the existing service adapter; therefore per-object Gerber lines are not claimed for pads/traces. Exact line ranges are exposed for scanned region findings. This is a current inspection limitation for general primitive line provenance.
- Shows source compliance and machining eligibility independently. It provides no toolpath, G-code, or CNC export.
- Runs archive loading in a worker thread; closing the window waits for an active parse and cleans its temporary extraction directory.

### Launch

Environment is project-local at `phase2g/.venv`. To launch on this workstation:

```powershell
cd C:\Users\ogbul\Documents\Github\gerber_to_vectric
.\phase2g\run_pcbprep.ps1
```

Use **Sample · Valentine**, **Sample · Laser Module**, or **Open Gerber ZIP**. To pass an archive on launch:

```powershell
.\phase2g\run_pcbprep.ps1 "C:\path\to\manufacturing.zip"
```

The direct development entry point is `phase2g/run_gui.py`. Runtime pins are recorded in `phase2g/requirements.txt`; the local resolved package inventory is in `phase2g/requirements.lock`. It uses CPython `3.12.14`, Gerbonara `1.6.3`, PySide6 `6.9.3`, Shapely `2.2.0`, and GEOS `3.14.1`. Shapely uses its bundled GEOS wheel. Gerbonara, Shapely and GEOS provenance/license notes are documented in `phase2a/DEPENDENCIES.md`; PySide6/Qt license notices and release redistribution obligations must be reviewed before packaging. The lock is a version inventory, not a hash-pinned, signature-verified artifact lock.

### Screenshots and forensic image

![Valentine board inspection preview](../phase2g/results/screenshots/valentine-inspection.png)

![Laser Module full-board inspection with region 79 selected](../phase2g/results/screenshots/laser-module-full-board.png)

![Laser Module region 79 zoom and evidence panel](../phase2g/results/screenshots/laser-region-079-inspection.png)

![Annotated region 79 boundary discrepancy](../phase2g/results/region79-discrepancy-annotated.png)

## 5. Regression and GUI smoke tests

| Suite | Result | Coverage relevant to Phase 2G |
|---|---:|---|
| Phase 2E recovery + Phase 2F revision | **PASS — 25 tests** | Hash-bound source status and no-op records, no snapping/generic repair, source-command equivalence, drill/slot/outline revision checks, cached-fill correspondence and no approval |
| Phase 2G | **PASS — 4 tests** | Valentine evidence policy, 183 Laser circular records, 8 slots, 182 region records, 181 proposal correspondences, region 79 exact metrics and BLOCKED state, asynchronous Qt load/selection/toggle/render, malicious ZIP path rejection |
| Diagnostic captures | **PASS** | Generated both board views, selected region 79 view, and annotated discrepancy plot |

The smoke test confirms the GUI remains responsive when requesting an archive load, that the archive finishes loading in the Qt worker thread, that region 79 is selected, that a layer toggle rebuilds the scene, and that a rendered window image is produced. It is not an independent geometric accuracy test. The numerical baselines remain those established in Phase 2F/2G; no new manufacturing accuracy gate is passed here.

## 6. Acceptance status and remaining blockers

| Criterion | Phase 2G assessment |
|---|---|
| Region 79 exact source/native discrepancy measured and annotated | **PASS for measurement; unresolved for design intent** |
| Cause isolated to stale cache vs design/export difference | **NOT VERIFIED** — native v2.5 and cache refresh provenance missing |
| Other 181 mapped rings checked | **PASS for bounded comparison** — max `0.001488761878 mm`; display-only proposal evidence |
| Narrow source-specific, hash-bound preview policy | **PASS for display-only behavior**; not a production recovery approval system |
| Original ZIPs and recovered EasyEDA project preserved | **PASS** — read-only inputs used; no changes made |
| Read-only standalone preview launch and interactions | **PASS** — automated smoke tests and screenshots |
| Exact original source line for every parsed primitive | **PARTIAL / NOT VERIFIED** — region command spans are precise; general Gerbonara primitive line mapping is unavailable in the existing adapter |
| Source-file conformance for Laser Module exports | **FAIL** — 182 open contours remain nonconforming under the adopted validation rules |
| Manufacturing eligibility for either board | **FAIL / BLOCKED** — no machining approval granted |
| Manufacturing readiness | **NOT CLAIMED** |

## 7. Recommended next work

1. Conduct physical UI review with both sample boards and region 79 selected. Capture usability issues without weakening blocked states.
2. Obtain authenticated v2.5 EasyEDA native project or equivalent revision evidence. Request a controlled repour/export artifact manifest tied to a project hash and exporter settings.
3. Compare region 79 against that revision's fresh copper pour and inspect the native editor's exact path at the discrepancy location. Keep it blocked until the discrepancy is explained and independently verified.
4. Improve parser-object to source-line provenance as a separate audit item; preserve command-level region line records already available.
5. After review, define the next verification checkpoint before any manufacturing engine or DemonX integration work. No Phase 2H work is started by this report.

## 8. Changed files and preserved data

Phase 2G adds the inspection model/UI, local environment requirement files, tests, forensic script/data, screenshots, and this report. It does not modify DemonX Circuit, Design, or CNC; original EasyEDA project files or source manufacturing archives; or Phase 2E/2F acceptance logic. Existing untracked work remains preserved.
