# DemonX PCB Prep — Phase 2B Geometry Verification

**Status: verification gate not passed.** The supplied files were parsed by independent implementations and drill records reconcile at the source-record level. A 405-hit total in the Phase 2A report was incorrect: the files contain **413 circular drill records plus 8 routed slots**. Twelve Valentine PTH and via records have identical coordinates and diameters across separate files, so physical feature duplication remains unresolved. Independent parser comparison also found large Gerber arc bounding-box disagreements. Full copper-area, topology, clearance, and boundary-displacement verification was not completed. These data are not manufacturing-ready.

## Scope and preserved state

Work remained on branch `codex/pcb-prep-phase-2a`. No branch reset, push, merge, archive modification, or edit to DemonX Circuit, Design, or CNC was made. The original ZIPs and extracted Phase 2A fixture files remain unchanged; regression tests verify their hashes. The existing tracked `.gitignore` modification and untracked `Prickly_Converter_Vectric/`, `gerbers/`, `phase2a/`, and prior `docs/` work were present before Phase 2B and were preserved. Phase 2B audit code, parser output records, and this report are new.

The project-local Python environment used Python 3.12.14, Gerbonara 1.6.3, Shapely 2.2.0, and GEOS 3.14.1. The independent tools were Delta Gerber 1.7.0 (Java 17.0.18, Maven 3.9.14) and PyGerber 2.4.3. Delta Gerber is MIT-licensed; PyGerber is MIT-licensed; their upstream and package provenance is linked below. The exact Python environment is in [`phase2b/requirements.lock`](../phase2b/requirements.lock); Delta's direct version is pinned in [`phase2b/pom.xml`](../phase2b/pom.xml). Maven-resolved transitive artifacts are cached locally under ignored `phase2b/local-m2/`; no global Python dependencies were installed. The transitive Java license inventory and package signatures were not audited.

## Fixture identity

The original archive hashes from Phase 2A are:

| Board | Original archive | SHA-256 | Extracted manufacturing files |
|---|---|---|---:|
| Valentine | `Gerber_PCB_Valentine_Feb_New.zip` | `2e23a8cff4bd48d947f5f7fda371b8669d054c03cc87bb561bc2854d39337796` | 10 Gerber, 3 Excellon |
| Laser Module | `Gerber_Prickly-Laser-Module-2.5.zip` | `5e682b600dd19ee798d11830f0867f8cd686853d6a05620b8af174ba9ed3eb33` | 7 Gerber, 2 Excellon |

The full archive hashes and each extracted manufacturing-file hash are retained in [`phase2a/fixture_inventory.json`](../phase2a/fixture_inventory.json) and [`phase2a/results/parsed_geometry.json`](../phase2a/results/parsed_geometry.json). The Phase 2B hash regression test recomputes these values against the preserved ZIPs and extracted files. Extraction was not repeated and original archives were not rewritten.

## Reconciled manufacturing records

The Phase 2A table's “features” were circular hits only, while its executive count included hits and slots in a single “drill source features” figure. The separate sentence reporting 405 point hits is inconsistent with both the file-level records and the table totals. Direct parser outputs from Delta and the Phase 2A JSON establish:

| Dataset | Circular drill hits | Routed slots | Total source records |
|---|---:|---:|---:|
| Valentine | 230 | 0 | 230 |
| Laser Module | 183 | 8 | 191 |
| **Combined** | **413** | **8** | **421** |

Thus, **405 circular hits is an arithmetic/reporting error**, not the result of excluding slots. `230 + 183 = 413`; the Laser file contributes 183 hits and 8 additional slots. Delta and Gerbonara both parse those per-file counts, each of the 8 slot paths, all endpoints, and every source tool diameter. All 413 circular records and 8 slots reconcile one-to-one by source file and record index; no individual source record disappeared between the two parsers.

### Required drill groups

Group membership uses the Phase 2A documented ±0.005 mm tolerance, with the 0.8 mm group also accepting diameters up to 0.805 mm. Original source diameters are retained. Group assignment does not specify a cutter diameter.

| Group | Valentine | Laser Module | Combined |
|---|---:|---:|---:|
| PCB - Drill 0.8mm | 188 | 74 | 262 |
| PCB - Drill 1.0mm | 20 | 38 | 58 |
| PCB - Drill 1.1mm | 0 | 0 | 0 |
| PCB - Drill 1.2mm | 0 | 6 | 6 |
| PCB - Drill 2.0mm | 0 | 0 | 0 |
| PCB - Drill 3.0mm | 0 | 0 | 0 |
| PCB - Drill 3.1mm | 0 | 0 | 0 |
| Unassigned | 22 | 65 | 87 |
| Above 3.105 mm profile-bore candidates | 0 | 0 | 0 |
| **Circular hit reconciliation** | **230** | **183** | **413** |
| Separate routed slots | 0 | 8 | 8 |

There are no profile-bore candidates. The eight Laser Module slots are plated: four are 0.751 mm wide and four are 1.000 mm wide. Slots remain separately represented and are not included in the circular groups.

### Unassigned drill diameter distribution

Every unassigned row is an explicit tool-table diameter from the indicated source file. “Unsupported” means it does not match any currently supported application group at the selected tolerance; it does not authorize substitution or machining. The source encodes these dimensions clearly enough that they are not coordinate-measurement ambiguities. Nominal design intent beyond the source tool table remains unknown.

| Board | Source file | Tool | Source diameter (mm) | Plating | Count | Assessment |
|---|---|---:|---:|---|---:|---|
| Valentine | `Drill_PTH_Through.DRL` | T04 | 0.89916 | PTH | 2 | Unsupported source size; no mapping inferred |
| Valentine | `Drill_PTH_Through.DRL` | T05 | 0.91440 | PTH | 16 | Unsupported source size (0.036 in equivalent); no mapping inferred |
| Valentine | `Drill_NPTH_Through.DRL` | T01 | 2.20000 | NPTH | 4 | Unsupported source size; below profile-bore threshold |
| Laser Module | `Drill_PTH_Through.DRL` | T04 | 0.91500 | PTH | 44 | Unsupported source size; no mapping inferred |
| Laser Module | `Drill_PTH_Through.DRL` | T06 | 1.18000 | PTH | 21 | Unsupported source size; outside 1.2 mm tolerance; no mapping inferred |
| **Total** |  |  |  |  | **87** | **87 unassigned records reconcile** |

No diameter was adjusted, merged, or assigned to an unsupported tool group. The exact hits and source indices remain in the Phase 2A JSON inventory.

### Plating and role labels

| Board | Source classification | Circular hits | Slots | Basis and limitation |
|---|---|---:|---:|---|
| Valentine | PTH through-hole file | 214 | 0 | Filename/header-derived PTH classification |
| Valentine | NPTH through-hole file | 4 | 0 | Filename/header-derived NPTH classification |
| Valentine | PTH via file | 12 | 0 | Via role inferred from filename; all 12 overlap PTH records below |
| Laser Module | PTH through-hole file | 183 | 8 | Filename/header-derived PTH classification |
| Laser Module | PTH via file | 0 | 0 | File declares a 0.001 mm tool but has no operations |
| Laser Module | NPTH | 0 | 0 | No NPTH source file supplied |

These are file-derived labels, not electrical netlist or plating inspection. The combined source-record role totals are 397 PTH through-hole records, 4 NPTH records, 12 via records, and 8 separately routed slots.

### Duplicate physical drill locations

The 12 records in `Drill_PTH_Through_Via.DRL` for Valentine repeat 12 records in `Drill_PTH_Through.DRL` with exactly the same X, Y, and 0.30998 mm diameter. Each pair is labeled `through-hole` in one file and `via` in the other. They are distinct source records but only 12 physical center/diameter locations. Source-level reconciliation therefore has no dropped or duplicated **record IDs**, while physical feature reconciliation has **12 unresolved duplicate locations** (401 unique circular locations across 413 records if equal location/diameter records are treated as one physical hole). We do not deduplicate them or choose a role. A design owner/fabrication source must establish whether they are intentionally repeated operations or duplicate export content before they become machining features.

## Independent reference tools and method

### Tools used

1. **Delta Gerber 1.7.0** (Java): an independent implementation that parses RS-274X and Excellon. It parsed all 17 Gerber files, including the 218-object Gerber drill-drawing layer, and all 5 Excellon files. Its output records are retained as CSV under [`phase2b/reference/delta/`](../phase2b/reference/delta/). Delta's upstream README documents its parser and model; its 1.7.0 release is available at [Delta Gerber releases](https://github.com/Delta-Proto/delta-gerber/releases/tag/v1.7.0).
2. **PyGerber 2.4.3** (Python): a second independent RS-274X parser. It parsed all 17 Gerber files. Its ordered command counts/types and arc start, end, center, and direction were compared with Gerbonara and retained in [`phase2b/reference/pygerber-comparison.json`](../phase2b/reference/pygerber-comparison.json). See [PyGerber package](https://pypi.org/project/pygerber/) and [documentation](https://argmaster.github.io/pygerber/latest/).
3. **KiCad 10.0.7** was present locally. `kicad-cli --help` lists PCB, schematic, footprint, symbol, and jobset commands, but no Gerber import or Gerber measurement subcommand. The official [KiCad 10 GerbView manual](https://docs.kicad.org/10.0/en/gerbview/gerbview.pdf) documents GUI layer loading, visual comparison, and measurement tools. GerbView's “Export to PCB Editor” conversion is limited and can lose rasterized/negative features, so it is not a complete quantitative golden geometry exporter. GerbView is suitable for a future human visual overlay check; it was not used as a numerical reference here.

The official Gerber basis is Ucamco's [Gerber Layer Format Specification, revision 2026.05](https://www.ucamco.com/files/downloads/file_en/554/gerber-layer-format-specification-revision-2026-05_en.pdf?326db511181711a85150ce4139bb1c23=). The official Excellon/XNC basis carried forward from Phase 2A is [Ucamco XNC Specification, revision 2021.11](https://www.ucamco.com/files/downloads/file_en/452/xnc-format-specification-revision-2021-11_en.pdf?546c7e5e6abc3dee080ab00d1f10f7e1=). Ucamco conformance fixtures were not run; neither vendor's complete conformance against the current Gerber revision was independently established.

### Measured parser-level comparisons

| Comparison | Result | Interpretation |
|---|---:|---|
| Gerber files parsed by Delta | 17 / 17 | No uncaught parse error; zero parser warnings in its recorded model |
| Gerber object/command counts, Delta vs Gerbonara | 10,961 / 10,961 | Exact per-file counts and normalized feature-type counts match |
| Excellon circular records, Delta vs Gerbonara | 413 / 413 | Exact per-file counts, source indices, X/Y, and tool diameters match; max coordinate/diameter difference 0 mm |
| Excellon routed slots, Delta vs Gerbonara | 8 / 8 | Endpoints and tool diameter match; maximum difference 0 mm |
| Gerber object bounding boxes, Delta vs Gerbonara | 10,961 compared | 10,682 have coordinate deltas ≤1e-6 mm; 279 arc-object bounds differ |
| Maximum arc-object bounding-box coordinate difference | 2.50012 mm | Observed on Valentine top silkscreen; largest bounding-box disagreement |
| Gerbonara vs PyGerber arc count/type/direction | All 293 arcs agree | Arc endpoints, center, and direction max delta 1.4211e-14 mm across 17 Gerbers |

The 279 Delta bounds discrepancies are all arc objects: 256 Valentine top silkscreen, 6 Valentine bottom silkscreen, 8 Valentine documentation, and 9 Laser Module top silkscreen arcs. For example, at Valentine top silkscreen object 1983, Delta and Gerbonara have the same object index and type, but their arc-derived bounding boxes differ by 2.50012 mm. PyGerber's ordered arc endpoints, centers, and CCW direction agree with Gerbonara for that file and all other arcs. This triangulation points to a Delta arc-bound calculation or interpretation issue; the available outputs do not independently prove which rendered arc boundary is correct. The mismatch is retained, not normalized away.

For the four copper files, no arcs are present. All 1,808 individual top/bottom copper object bounding boxes match between Delta and Gerbonara within 1.5e-14 mm. The overall parser-derived bounds are:

| Board | Layer | Gerbonara-derived copper bounds (mm) | Delta object bounds (mm) | Maximum extent delta |
|---|---|---|---:|
| Valentine | Top | [4.453, 12.962912, 85.425920, 82.987005] | [4.453, 12.962000, 85.425920, 82.987005] | 0.000913 mm |
| Valentine | Bottom | [1.954270, 7.765020, 87.707630, 83.912450] | [1.954270, 7.765020, 87.707630, 83.912450] | <1e-12 mm |
| Laser Module | Top | [13.994000, 2.877990, 125.594948, 82.153980] | same | <1e-12 mm |
| Laser Module | Bottom | [11.257280, 2.037080, 127.197610, 84.957920] | same | <1e-12 mm |

The Valentine top minimum-Y delta is consistent with Phase 2A's circular polygonization sagitta (target 0.001 mm; actual maximum reported 0.000963635 mm). This checks extents and source records; it is not a symmetric-difference or copper-boundary comparison.

### Copper and profile measurements still parser-derived

Phase 2A reports the following Shapely/GEOS composition results. **These are not independent Delta or PyGerber copper-area/topology measurements.**

| Board | Top copper area / components / voids | Bottom copper area / components / voids | Profile dimensions / area / components / voids |
|---|---|---|---|
| Valentine | 803.600676 mm² / 165 / 0 | 3,857.227030 mm² / 110 / 181 | 86.26655 × 76.72680 mm / 4,330.933726 mm² / 1 / 0 |
| Laser Module | 511.150953 mm² / 191 / 0 | 7,761.637669 mm² / 69 / 181 | 116.45877 × 83.43882 mm / 9,717.182347 mm² / 1 / 0 |

The profile file objects have exact matching per-object parser bounds in Delta and Gerbonara. Delta's bounding boxes include the profile aperture stroke, expanding the Phase 2A closed centerline profile envelope by 0.127 mm on each side. The top-level check did not reconstruct a second closed outline, classify interior cuts independently, or compare profile polygons. Phase 2A's 181 bottom copper voids per board are GEOS-derived counts only; the independent parsers' source feature records agree, but no independent topology inventory was composed.

No independent symmetric-difference area, Hausdorff boundary displacement, copper pad/trace silhouette area, internal void topology, clearance-region area, or source-feature-to-region loss/duplication metric was obtained. Therefore the ≤0.005 mm target and 0.01 mm interim ceiling cannot be judged. The arc bounding-box discrepancy is not itself a boundary-displacement measurement, but it is far above both ceilings and prevents accepting the affected curves.

## Coordinate registration and side transforms

Both parsers preserve the raw Gerber coordinate values in mm. For every Excellon file, Delta and Gerbonara match hit centers and diameters exactly; all eight slot endpoint pairs also match exactly. No source-side mirror was applied. Top copper, bottom copper, profile, PTH, NPTH, and via layers are compared in their emitted file coordinates, with the profile bounds and copper bounds reported above.

The source files do not carry a shared native coordinate-frame metadata record that proves physical registration. Equal parser coordinates establish a common numeric coordinate convention in the delivered set, but do not prove that the fabrication export aligned each file correctly. No pad-hit correlation or independently composed all-layer overlay was completed. Registration across source-file origins is therefore **NOT VERIFIED**.

The declared machining-side mirror is treated as a separate transform. For a board-frame reflection about its centerline, `M(x,y)=(x, 2cy-y)` is an involution: a numeric check on all source point coordinates returns them after two applications with maximum floating-point residual below 1e-12 mm. This is a mathematical round-trip check only; it does not establish which bottom-side reflection DemonX Design/CNC expects.

## Phase 2A geometry repair audit

Phase 2A explicitly applied `shapely.make_valid` to **98** invalid polygonized `ArcPoly` primitives and recorded each repair by archive source hash, filename, object index, and primitive index:

| Dataset/layer | Repairs | Total area delta after repair |
|---|---:|---:|
| Valentine bottom copper (`Gerber_BottomLayer.GBL`) | 2 | −9.7e-12 mm² |
| Valentine top silkscreen (`Gerber_TopSilkscreenLayer.GTO`) | 37 | +4.6e-14 mm² |
| Laser Module top silkscreen (`Gerber_TopSilkscreenLayer.GTO`) | 59 | −0.001873039 mm² |

For each affected primitive, replaying the same Gerbonara object-to-primitive conversion and `make_valid` call twice with the same installed GEOS produced normalized WKB-identical outputs. Each result is a valid `GeometryCollection` containing a positive-area `Polygon` plus one zero-area `LineString` or `MultiLineString`. This proves repeatability in this exact runtime. It does not prove that the input's self-intersecting outline encodes the intended copper or that the repairs preserve intended material. GEOS cannot compute a meaningful symmetric difference against the invalid input polygon. No repair silently removed a feature, but the geometry operation changes the representation and small amounts of measured area; the 0.001836419 mm² loss in one Laser top-silkscreen region is much larger than floating-point noise. The two copper repair area deltas are negligible numerically but their topology was still altered into polygon plus linework. Repairs require source-format or independent-tool adjudication before manufacturing use.

No speck removal or automatic via filtering was performed.

## Regression harness and test results

Phase 2B artifacts include:

- [`phase2b/src/main/java/local/demonx/audit/DeltaAudit.java`](../phase2b/src/main/java/local/demonx/audit/DeltaAudit.java): pinned Delta Gerber/Excellon record extractor.
- [`phase2b/compare_references.py`](../phase2b/compare_references.py): compares Delta record positions/bounds with Phase 2A parser records.
- [`phase2b/compare_pygerber_arcs.py`](../phase2b/compare_pygerber_arcs.py): independently checks all Gerber counts/types and arc parameters against PyGerber.
- [`phase2b/test_phase2b.py`](../phase2b/test_phase2b.py): golden and hash regression suite.
- [`phase2b/reference/comparison.json`](../phase2b/reference/comparison.json), [`phase2b/reference/pygerber-comparison.json`](../phase2b/reference/pygerber-comparison.json), and per-source CSV files: recorded independent parser results.

Run from `phase2b/`:

```powershell
mvn -s maven-settings.xml -DskipTests package
$jars = Get-ChildItem local-m2 -Recurse -Filter *.jar | ForEach-Object { $_.FullName }
$cp = 'target\classes;' + ($jars -join ';')
java -cp $cp local.demonx.audit.DeltaAudit ..\phase2a\fixtures\extracted\gerber-pcb-valentine-feb-new reference\delta\valentine.csv
java -cp $cp local.demonx.audit.DeltaAudit ..\phase2a\fixtures\extracted\gerber-prickly-laser-module-2-5 reference\delta\laser.csv
..\.venv\Scripts\python.exe compare_references.py
.venv\Scripts\python.exe compare_pygerber_arcs.py
..\phase2a\.venv\Scripts\python.exe -m unittest -v test_phase2b.py
```

**Phase 2B automated tests: 7 passed.** They cover preserved archive and extracted-file hashes, independent parser record totals, per-file primitive-type/count matches, exact drill/slot values and record indices, PyGerber arc records, the known Delta arc-bound discrepancies, and unresolved repeated Valentine physical drill locations. One additional self-consistency test reruns the Phase 2A Gerbonara/GEOS composition for copper and profiles and checks its area, bounds, components, voids, validity, and mirror round-trip against the saved baseline. That same-parser test is not independent manufacturing geometry evidence. Phase 2A previously reported 16 harness tests passing; those tests were not rerun during Phase 2B. Ucamco conformance tests and a KiCad GerbView inspection were not run.

## Acceptance assessment

| Acceptance criterion | Result | Evidence/remaining gap |
|---|---|---|
| Preserve source archives and hashes | **PASS** | Seven-test suite recomputes original archive and extracted manufacturing hashes successfully. |
| Parse both datasets without uncaught parser errors | **PASS** | Delta parsed 17 Gerber and 5 Excellon files; PyGerber parsed all 17 Gerbers. |
| Reconcile circular hits and routed slots | **PASS, source records only** | 413 hits + 8 slots = 421 records; exact per-file agreement between Gerbonara and Delta. The 405 figure in the old report is incorrect. |
| No missing source record IDs | **PASS, source records only** | All record counts, hit coordinates, diameters, and slot endpoints match by source file/index. |
| No duplicate physical manufacturing features | **FAIL / unresolved** | 12 exact Valentine PTH/via coordinate/diameter overlaps; intent is unclear and no deduplication was applied. |
| Complete unassigned diameter frequency and classification | **PASS** | 87 records across five source/tool/plating/diameter rows; no substitute group or cutter assigned. |
| Independent top/bottom copper primitive and extent check | **PARTIAL** | All copper records and per-object bounds agree; one 0.000913 mm aggregate extent difference follows circular polygonization. Area and topology remain same-parser-only. |
| Independent arc geometry check | **PARTIAL / mismatch found** | PyGerber and Gerbonara arc parameters agree within 1.5e-14 mm; Delta bounds disagree on 279 arcs by up to 2.50012 mm. |
| Copper area, symmetric difference, topology, clearance, and boundary deviation | **NOT VERIFIED** | No independent composed filled-region reference was available. |
| Board outline/cutout reconstruction accuracy | **NOT VERIFIED** | Parser object counts/bounds match, but second closed profile reconstruction and internal cuts were not compared. |
| Drill and slot coordinate/diameter accuracy | **PASS, parser values** | Independent Delta records match Gerbonara exactly. Plating and via role remain filename/header classifications. |
| Shared top/bottom/profile/drill physical registration | **NOT VERIFIED** | Numeric source frames are preserved and agree per file; pad correlation/independent overlay was not completed. |
| Bottom machining mirror round-trip | **PASS, math-only** | Reflection is involutive within 1e-12 mm; machine-side convention is not confirmed. |
| Geometry repairs documented and deterministic | **PASS, repeatability only** | All 98 repairs are recorded and replayed with identical normalized WKB; intended source topology/material is still unresolved. |
| Geometry accuracy ≤0.005 mm or interim ≤0.01 mm | **NOT VERIFIED** | No independent composed boundary metric exists; detected Delta arc-bound disagreements block acceptance. |

## Remaining uncertainties and proposed verification path

1. Resolve the 12 repeated Valentine PTH/via locations against the original CAD project or a fabrication-approved drill export. Preserve both source records until their roles are adjudicated.
2. Reconcile the arc bounds with the Gerber semantics using a tool that exposes parsed center, endpoints, direction, and aperture-expanded path. The existing PyGerber AST and Gerbonara primitives agree on all 303 arcs; inspect the affected 279 source arc commands in KiCad GerbView and capture a high-resolution overlay for visual corroboration. Do not use Delta's mismatched arc bounds as a golden boundary.
3. For numerical copper area/topology/boundary checks, generate a second composed reference from PyGerber's independently parsed commands using a separately reviewed aperture/polarity reconstruction path, or use a future KiCad/EDA export only after proving that it preserves dark/clear polarity, aperture macros, arcs, and holes. Compare that reference with the Gerbonara/GEOS result using bounding boxes, area, symmetric difference, Hausdorff distance, components, holes, and per-feature provenance. Do not consider two outputs from Gerbonara independent.
4. Confirm layer origin alignment and bottom-side machine transform against CAD design coordinates or approved manufacturing data. Maintain raw source coordinates for parsing validation.
5. Evaluate each invalid `ArcPoly` repair against the Gerber source interpretation before allowing repaired polygons into isolation or profile geometry.

Until those items are closed, Phase 2B fails its independent-accuracy gate. No GUI, manufacturing toolpath engine, or DemonX Design interchange work was started.
