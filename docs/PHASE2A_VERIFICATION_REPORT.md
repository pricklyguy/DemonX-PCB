# DemonX PCB Prep — Phase 2A Geometry Baselines and Verification

**Date:** 2026-10-24  
**Branch:** `codex/pcb-prep-phase-2a`  
**Status:** Phase 2A artifacts prepared for review. This is not manufacturing readiness and does not authorize Phase 2B.

## Executive result

The two original archives were preserved and content-sniffed extraction produced 17 Gerber and 5 Excellon files. Gerbonara 1.6.3 parsed all 22 manufacturing files without an uncaught parse failure. The harness accounted for 413 drill source features: 405 point hits and 8 routed slots. All 405 point hits have exactly one nominal/unassigned/profile-bore classification; the reconciliation reports zero missing or duplicate assignments. All 8 slots remain separate and retain source diameter and endpoints.

Both source profile layers polygonized into one closed region with no dangles, cut-lines, invalid linework or detected internal rings. Coordinates were retained in the source frame (identity transform recorded); all Gerber files declare mm and the same L/A X4.5 Y4.5 format, while Excellon coordinate formats are recorded per file. This establishes the frame used by the files, not physical registration against an independent reference.

The parser/geometry harness provides useful baselines, explicit source-feature references, validity checks and diagnostic plots. The key outstanding accuracy gap is material: there was no local KiCad/GerbView or other independent trusted interpretation available to compare against. Therefore source-to-reconstruction bounding-box/area/boundary/symmetric-difference errors are **not measured** and the ≤0.01 mm interim acceptance ceiling is **not demonstrated**. Arc/circle tessellation alone has a measured maximum sagitta below 0.001 mm; this is not a total geometry-error bound. Do not use these results to approve a manufacturing job.

## 1. Worktree and preservation

- Initial branch/HEAD: `claude/epic-rubin-9urbl2` / `ff26412`.
- Dedicated branch created: `codex/pcb-prep-phase-2a`; no reset, commit, push or merge was performed.
- Pre-existing untracked `Prickly_Converter_Vectric/` and `gerbers/` were preserved. The supplied ZIPs were read only. `.venv/` is ignored; the isolated environment is local to `phase2a/`.
- This work adds only Phase 2A artifacts and the `.gitignore` entry for the local virtual environment. No other DemonX repository was changed.

## 2. Environment, pins and sources

The Windows x64 project-local environment records CPython 3.12.14, Gerbonara 1.6.3, Shapely 2.2.0 and bundled GEOS 3.14.1. Matplotlib 3.11.2 renders the diagnostic plots; pytest 9.1.1 runs the requested verification harness tests. Direct pins are in [`phase2a/requirements.txt`](../phase2a/requirements.txt); the full resolved environment is pinned in [`phase2a/requirements.lock`](../phase2a/requirements.lock). Recreation steps and extraction controls are in [`phase2a/README.md`](../phase2a/README.md). License and provenance notes, including the absence of per-wheel hash/signature verification, are in [`phase2a/DEPENDENCIES.md`](../phase2a/DEPENDENCIES.md).

Gerber geometry requirements were checked against Ucamco's [Gerber Layer Format Specification, Revision 2026.05](https://www.ucamco.com/files/downloads/file_en/554/gerber-layer-format-specification-revision-2026-05_en.pdf?326db511181711a85150ce4139bb1c23=), [official grammar and conformance-test downloads](https://www.ucamco.com/en/guest/downloads). Excellon/XNC concepts were checked against Ucamco's [XNC Specification, Revision 2021.11](https://www.ucamco.com/files/downloads/file_en/452/xnc-format-specification-revision-2021-11_en.pdf?546c7e5e6abc3dee080ab00d1f10f7e1=). Parser/API provenance is [Gerbonara upstream and documentation](https://gitlab.com/gerbolyze/gerbonara/) / [docs](https://gerbolyze.gitlab.io/gerbonara/); geometry-engine documentation is [Shapely](https://shapely.readthedocs.io/) / [GEOS](https://libgeos.org/).

## 3. Original fixture inventory and hashes

The archive-wide manifest includes every ZIP entry, its uncompressed size, each extracted path, and SHA-256 hashes for every extracted manufacturing file. Only content-identified Gerber/Excellon files were extracted. Entry limits, path traversal, absolute paths, symlink members, duplicate/case-colliding names and compression-ratio limits are checked before writing. See [`phase2a/fixture_inventory.json`](../phase2a/fixture_inventory.json).

| Original archive | ZIP entries | Extracted Gerber | Extracted Excellon | Archive SHA-256 |
|---|---:|---:|---:|---|
| `Gerber_PCB_Valentine_Feb_New.zip` | 15 | 10 | 3 | `2e23a8cff4bd48d947f5f7fda371b8669d054c03cc87bb561bc2854d39337796` |
| `Gerber_Prickly-Laser-Module-2.5.zip` | 10 | 7 | 2 | `5e682b600dd19ee798d11830f0867f8cd686853d6a05620b8af174ba9ed3eb33` |

Extracted manufacturing files are retained under `phase2a/fixtures/extracted/<board-id>/`; their per-file hashes are in the manifest and parsed report. Non-manufacturing archive members were not extracted. Original archives remain in `gerbers/`.

## 4. Parser-derived source geometry inventories

Metrics below come from Gerbonara parsing plus the harness's Shapely/GEOS conversion and ordered dark/clear composition. They are **parser-derived**, not independently confirmed. Areas, bounds, components and voids describe the verification geometry output, not a verified fabrication truth. Gerbonara supplied no X2 `FileFunction` attributes on these files, so semantic layer functions below are inferred from filenames. Every converted source object/primitive has a provenance reference in the JSON result (file hash, object index, primitive index/type, attributes and polarity); original source files are retained.

| PCB | Layer | Detected function | Objects | Primitive summary |
|---|---|---|---:|---|
| Valentine | `Gerber_TopLayer.GTL` | Top copper, filename inferred | 429 | 214 flashes (pads), 215 line objects (strokes); primitive types: 40 circles, 384 lines, 5 rectangles |
| Valentine | `Gerber_BottomLayer.GBL` | Bottom copper, filename inferred | 561 | 222 flashes, 337 line objects, 2 regions; primitives: 2 ArcPoly, 506 lines, 40 circles, 13 rectangles |
| Valentine | `Gerber_BoardOutlineLayer.GKO` | Board profile, filename inferred | 158 | 158 line objects; 1 closed polygonized ring |
| Laser Module | `Gerber_TopLayer.GTL` | Top copper, filename inferred | 191 | 191 flashes; primitives: 158 circles, 21 lines, 12 rectangles |
| Laser Module | `Gerber_BottomLayer.GBL` | Bottom copper, filename inferred | 627 | 191 flashes, 254 line objects, 182 regions; primitives: 182 ArcPoly, 275 lines, 158 circles, 12 rectangles |
| Laser Module | `Gerber_BoardOutlineLayer.GKO` | Board profile, filename inferred | 4 | 4 line objects; 1 closed polygonized ring |

Other source layers were parsed and inventoried: Valentine includes top/bottom silkscreen, top/bottom solder mask, bottom paste, document and drill-drawing; Laser Module includes top silkscreen, top/bottom solder mask and document. Their object/primitive counts and warnings are in the machine-readable report. ArcPoly remains a compound region primitive; exact arc/line segments are available from the source-indexed parser representation, while the preview composition is polygonal.

### Geometry measurements

| PCB | Top copper bounds (mm) | Top area (mm²) | Bottom copper bounds (mm) | Bottom area (mm²) | Profile bounds (mm) | Width × height (mm) | Profile area (mm²) | Profile interior rings |
|---|---|---:|---|---:|---|---:|---:|---:|
| Valentine | `[4.453, 12.962912, 85.425920, 82.987005]` | 803.600676 | `[1.954270, 7.765020, 87.707630, 83.912450]` | 3,857.227030 | `[1.697690, 7.442250, 87.964240, 84.169050]` | 86.266550 × 76.726800 | 4,330.933726 | 0 detected |
| Laser Module | `[13.994000, 2.877990, 125.594948, 82.153980]` | 511.150953 | `[11.257280, 2.037080, 127.197610, 84.957920]` | 7,761.637669 | `[10.997970, 1.778000, 127.456740, 85.216820]` | 116.458770 × 83.438820 | 9,717.182347 | 0 detected |

The profile source for each board is a single closed connected outline: zero dangle length, cut-line length and invalid-linework length. No profile-layer internal cutout rings were found. The eight Laser Module slots are in the Excellon file, are separate from the outline, and are not represented as profile cutouts. A complete manufacturing interpretation must determine whether these paths or any other features should affect the finished board boundary.

Top and bottom copper bounds differ, as expected for different copper artwork extents; this is not itself a misregistration measure. The bounds differences `(bottom - top)` are `[-2.498730, -5.197892, 2.281710, 0.925445]` mm for Valentine and `[-2.736720, -0.840910, 1.602662, 2.803940]` mm for Laser Module. All files were parsed as absolute coordinates in the same declared mm units and Gerber L/A X4.5 Y4.5 format; Excellon is 4:5 on Valentine and 3:3 on Laser Module. The harness applied no mirror, offset or normalization: explicit source-frame transform is identity. Copper bounds fall within profile bounds. No registration fiducials or independent board-side measurement were used, so physical side-to-side registration is not independently established.

### Geometry validity and approximation

- Composed top/bottom copper and polygonized profile outputs are nonempty and GEOS-valid for both boards. Top/bottom copper interior-ring counts are 0 and 181 (Valentine), and 0 and 181 (Laser Module).
- The adapter approximates circular primitive geometry with a target sagitta of 0.001 mm. Measured maximum sagitta is 0.000994453 mm (Valentine files) and 0.000989998 mm (Laser Module files). These values only bound the arc/circle subdivision step under the adapter's calculation; overlay operations, source interpretation and downstream export errors are not covered.
- Explicit `make_valid` repairs were recorded, never silently filtered: two malformed ArcPoly regions in Valentine bottom copper (area delta approximately `-9.7e-12 mm²`), 37 top-silkscreen ArcPoly regions in Valentine, and 59 top-silkscreen ArcPoly regions in Laser Module (area delta sum approximately `-0.001873 mm²`). Invalid-source symmetric-difference cannot be computed by GEOS; records state this. No arbitrary speck deletion or via filtering was used.
- No unsupported/unmapped primitive types were found among the 10,961 parsed Gerber objects and 11,323 converted primitive records. This does not prove that the library interpreted every source-language construct as intended. Layer polarity, filename-derived function and ArcPoly segmentation remain items for independent verification.

## 5. Drill classification and reconciliation

Tolerance is ±0.005 mm for nominal groups. The requested 0.8 group includes all diameters ≤0.800 mm and diameters up to 0.005 mm above nominal. Other groups match only within ±0.005 mm. Source diameters remain in every hit record; cutter diameter is not inferred. Values >3.105 mm are marked profile-bore candidates (none found); other non-matches are unassigned. Slots are excluded from hit grouping and retained separately.

| PCB | 0.8 mm | 1.0 mm | 1.1 mm | 1.2 mm | 2.0 mm | 3.0 mm | 3.1 mm | Unassigned hits | >3.1 profile-bore candidates | Slots | Point hits reconciled |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Valentine | 188 | 20 | 0 | 0 | 0 | 0 | 0 | 22 | 0 | 0 | 230 / 230; 0 missing, 0 duplicate |
| Laser Module | 74 | 38 | 0 | 6 | 0 | 0 | 0 | 65 | 0 | 8 | 183 / 183; 0 missing, 0 duplicate |

Unassigned source diameters: Valentine has 0.89916 mm × 2, 0.91440 mm × 16 and NPTH 2.20000 mm × 4. Laser Module has 0.91500 mm × 44 and 1.18000 mm × 21. These remain available for manual policy; no substitute cutter size is assigned. Valentine files declare 214 PTH hits, 4 NPTH hits and 12 vias (all 230 hits are represented). Laser Module declares 183 PTH hits and an empty PTH-via file with a 0.001 mm tool definition but no hit features. No NPTH file was supplied for Laser Module. Plating is inferred from source filename/header where explicit; via role is inferred from filename. These classifications are not independent electrical verification.

Both boards' per-file tool tables, tool codes, original hit diameters, coordinates, source indices, classification basis and warnings are available in [`phase2a/results/parsed_geometry.json`](../phase2a/results/parsed_geometry.json). The 8 slots are plated line paths of 0.751 mm (4) and 1.000 mm (4), with source coordinates preserved. Drill parsing emitted compatibility warnings: misplaced `G90` statements in several files and repeated tool-index declarations in the Laser Module PTH file; Gerbonara still returned parsed features, but the source warnings require review.

## 6. Accuracy verification and limits

| Required metric | Result |
|---|---|
| Bounds / area / components / interior voids / validity | Measured for parser-derived polygonal geometry and stored in `parsed_geometry.json` |
| Boundary deviation, symmetric-difference area, area delta vs trusted reference | Not measurable: no independent reference was loaded; values remain null rather than estimated |
| Component/void count difference vs trusted reference | Not measurable for the same reason |
| Polygonization/reconstruction | Arc/circle maximum calculated sagitta below 0.001 mm; total reconstruction error is unknown |
| Source-feature loss / duplication | 22 Gerbers and 5 Excellon files opened; no unmapped primitive types; 405 point hits uniquely reconcile; 8 slot features separately represented |
| Invalid geometry | Composed copper/profile GEOS-valid; invalid source-derived ArcPoly repairs enumerated above with source provenance |
| Independent reference | No local KiCad/GerbView executable or trusted reference output was available or run. Same-parser plotting is not independent evidence. Ucamco conformance fixtures were not run in this phase. |

The harness explicitly distinguishes source entities, parser objects and Shapely derivations. Gerbonara source objects/primitives are preserved by source-file hash and ordinal references, while the original files are kept intact. The current JSON result is an audit artifact, not a canonical production PCB model. No geometry offset, isolation width, tool-depth adjustment, cutter compensation, automatic via suppression or DXF conversion was run.

## 7. Diagnostic previews

These are dimensioned 300-dpi parser-derived visual checks. They show top copper, bottom copper, overlay, drill groups and profile linework. They are not an independent reference or GUI and do not prove geometry correctness.

- [Valentine diagnostic preview](../phase2a/results/visuals/gerber-pcb-valentine-feb-new.png)
- [Laser Module diagnostic preview](../phase2a/results/visuals/gerber-prickly-laser-module-2-5.png)

No independent-reference difference image was generated because no independent reference was available.

## 8. Draft interchange schema

The preliminary JSON Schema is [`phase2a/schema/pcb-manufacturing.schema.json`](../phase2a/schema/pcb-manufacturing.schema.json). It defines version, mm units, board frame, explicit top/bottom affine transforms, source identities/hashes, semantically named layers, exact primitive records with provenance, derived geometry metadata, drills, slots, plating and diagnostics. It is an early draft and has only been checked for JSON well-formedness in this phase; it is not yet a versioned production contract, linked to `.dxd`, or validated against an implemented Design receiver. No `.dxd` file was read or written.

## 9. Automated verification

Command: `phase2a/.venv/Scripts/python.exe -m pytest phase2a/test_verification.py -q`  
Result: **16 passed**. Tests cover unsafe ZIP path rejection, drill nominal/tolerance boundaries, arc subdivision sagitta, persisted two-board source counts/dimensions/geometry validity, drill reconciliation, and JSON schema syntax. This is baseline harness coverage, not a complete Gerber/XNC conformance suite. Legacy root tests were not run because they test the old implementation and do not validate these Phase 2A artifacts.

## 10. Gate review and recommended next gate

The Phase 2A inventory/reconciliation conditions are met for these two inputs: every identified manufacturing file was opened, all parser-returned source features have an inventory/provenance reference or explicit diagnostic, all recognized drill hits reconcile, dimensions and identity source-coordinate transforms are recorded, and unresolved accuracy gaps are explicit. The geometry accuracy ceiling is not independently established, so this result must not be represented as a verified ≤0.01 mm result or manufacturing approval.

Before Phase 2B, review the unassigned drill policy, Laser Module repeated-tool warnings, filename-based layer/plating classifications, the two repaired Valentine copper ArcPoly regions, profile/slot semantics, and the need for an independent Gerber reference. A later verification gate should compare against Ucamco conformance tests and a distinct trusted implementation (e.g. KiCad/GerbView), then establish measured boundary displacement, symmetric-difference area and registration tolerances. Clipper2 offset selection is still unevaluated.

