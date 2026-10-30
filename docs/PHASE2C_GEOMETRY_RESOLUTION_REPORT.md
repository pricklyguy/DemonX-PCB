# DemonX PCB Prep — Phase 2C Geometry Resolution Report

**Status: partial verification; overall geometry gate NOT PASSED.** The independent PyGerber command composition agrees with the Phase 2A Gerbonara reconstruction to less than 0.001 mm maximum boundary Hausdorff distance on all four copper files. Drill source records reconcile, the twelve exact Valentine PTH/via duplicate pairs map to one physical hole each while retaining both records, and all assigned/unassigned drill counts reconcile. However, the Laser Module bottom Gerber contains 182 open region contours that violate the Ucamco closure rule, and two Valentine bottom copper regions are invalid self-intersecting polygons that need repair. The source data does not uniquely establish the intended material/topology for those regions. These results do not establish manufacturing readiness.

## Scope and preserved state

Work remained on `codex/pcb-prep-phase-2a`. The tracked `.gitignore` edit and pre-existing untracked `Prickly_Converter_Vectric/`, `gerbers/`, `phase2a/`, `phase2b/`, and `docs/` work were preserved. The original ZIPs and Phase 2A/2B files were not edited. No other DemonX repository, UI, CNC output, or `.dxd` file was changed. No package was installed globally.

The two archive SHA-256 hashes are preserved and rechecked by the regression suite:

| Archive | SHA-256 |
|---|---|
| `Gerber_PCB_Valentine_Feb_New.zip` | `2e23a8cff4bd48d947f5f7fda371b8669d054c03cc87bb561bc2854d39337796` |
| `Gerber_Prickly-Laser-Module-2.5.zip` | `5e682b600dd19ee798d11830f0867f8cd686853d6a05620b8af174ba9ed3eb33` |

The run used Python 3.12.14, PyGerber 2.4.3, Gerbonara 1.6.3, Shapely 2.2.0, and GEOS 3.14.1. PyGerber is loaded from the existing `phase2b/.venv`; Shapely, GEOS, and Matplotlib are loaded from `phase2a/.venv`. Version and archive hashes are recorded in [`phase2c/results/environment.json`](../phase2c/results/environment.json). Direct pins are in [`phase2c/requirements.txt`](../phase2c/requirements.txt); provenance and license references are in [`phase2c/README.md`](../phase2c/README.md), `phase2a/DEPENDENCIES.md`, and the Phase 2B report.

## Independent copper method

The new composition uses PyGerber's parsed command objects. It does **not** use Gerbonara primitive geometry to make the reference. The four copper files have no arc commands and contain only circle, obround, and rectangle apertures, circular line strokes, and regions. The composer retains source object order and source indices, applies dark/clear objects in that order, accounts for aperture holes when supplied, and refuses unreviewed aperture transforms or primitive types. No aperture in these four files declares a hole; all object transforms are identity. No file contains an `%IPNEG` image-polarity command. The Laser bottom layer has 181 clear-polarity objects among 627 commands; they are applied in stream order.

Circular shapes were polygonized with 128 segments per quadrant. The maximum analytic circle sagitta for the largest 3.0 mm aperture is 0.0000283 mm. Shapely/GEOS is shared by the independent composition and Phase 2A comparison, so their overlay implementation is not independent; the source parsers and command-to-shape adapters are independent. The regression suite also tests analytic arc bounds, circle/line/region composition, and ordered dark-clear-dark semantics. PyGerber's own SVG renderer was run separately on all four copper files as a render check, but it uses the same parsed command model and is not an independent parser or manual CAM review.

The composition follows Ucamco region, aperture, polarity, and arc rules. The current [Ucamco Gerber specification, revision 2026.05](https://www.ucamco.com/files/downloads/file_en/554/gerber-layer-format-specification-revision-2026-05_en.pdf?326db511181711a85150ce4139bb1c23=) specifies ordered image composition and dark/clear polarity. Its prior [revision 2024.05](https://www.ucamco.com/files/downloads/file_en/456/gerber-layer-format-specification-revision-2024-05_en.pdf?d0da0b92e6c2eee0a8193cc2bf20fc58=) explicitly requires each region contour to be connected, non-self-intersecting, and closed with its final point exactly equal to its first point. Those requirements are the basis for the source warnings below.

## Copper measurements

Areas, bounds, components, and interior voids below are the actual output of the independent PyGerber command composition compared with the existing Phase 2A Gerbonara/Shapely result. Symmetric difference reports the area covered by either result but not both. The `Phase 2A-only` and `PyGerber-only` columns give the direction of that difference; they do not mean that source objects were dropped.

| Board / layer | PyGerber area (mm²) | Phase 2A area (mm²) | Symmetric difference (mm²) | Max boundary Hausdorff (mm) | Bounds max delta (mm) | Components P/G | Voids P/G |
|---|---:|---:|---:|---:|---:|---:|---:|
| Valentine top | 803.967680 | 803.600676 | 0.367019 | 0.000964 | 0.000913 | 165 / 165 | 0 / 0 |
| Valentine bottom | 3,857.550818 | 3,857.227030 | 0.323800 | 0.000981 | <1e-12 | 110 / 110 | 181 / 181 |
| Laser Module top | 511.742856 | 511.150953 | 0.591974 | 0.000964 | <1e-12 | 191 / 191 | 0 / 0 |
| Laser Module bottom | 7,762.055001 | 7,761.637669 | 0.417383 | 0.000983 | <1e-12 | 69 / 69 | 181 / 181 |

All measured boundary distances are below both the 0.005 mm target and 0.01 mm interim ceiling **for the two interpreted polygonal results**. The larger area deltas track the different circle/round-cap polygonizations: the independent reference uses a finer fixed 128-segment-per-quadrant approximation while Phase 2A targeted 0.001 mm sagitta. The measured maximum displacement is under 0.001 mm; no component or void count changed. The Valentine top minimum-Y bound differs by 0.000912 mm, consistent with that tessellation difference. Bounds, directed missing/extra area, object inventory, and full source object records are in [`copper-comparison.json`](../phase2c/results/copper-comparison.json).

The Phase 2A parser and PyGerber command counts match on every layer:

| Board / layer | Commands | Types | Polarity | Source concern |
|---|---:|---|---|---|
| Valentine top | 429 | 214 flashes, 215 lines | 429 dark | None in this layer |
| Valentine bottom | 561 | 222 flashes, 337 lines, 2 regions | 561 dark | Both regions self-intersect and required `make_valid` |
| Laser Module top | 191 | 191 flashes | 191 dark | None in this layer |
| Laser Module bottom | 627 | 191 flashes, 254 lines, 182 regions | 446 dark, 181 clear | All 182 region contours are open |

For Laser Module bottom, each open contour was polygonized by implicitly adding a final-to-first chord so that its filled-area interpretation could be compared and measured. This is a diagnostic interpretation; it does not make the source Gerber conforming. Under the Ucamco closure rule, those region fills are invalid source data. The measured Laser bottom area/topology and its 0.000983 mm boundary comparison therefore remain **NOT VERIFIED as intended manufacturing copper**. The two Valentine bottom regions are closed, but self-intersecting: GEOS repairs are repeatable and have negligible measured area changes, yet the intended source topology cannot be proven from an invalid ring. Valentine bottom is also **NOT VERIFIED as intended manufacturing copper**.

No source command was silently dropped. All 1,808 top/bottom copper commands map to a recognized flash, line stroke, or region. The independent shape inventory contains per-object source indices and bounds. No arbitrary speck removal or via filtering was applied. The symmetric difference primarily follows rounded boundaries; localized numerical comparisons do not prove every semantic feature against fabrication-approved data.

### Difference and renderer artifacts

The difference overlays are 3,080 × 2,200 PNG images with millimetre axes. Blue is common geometry, red is PyGerber-only geometry, and green is Phase 2A-only geometry. The boundary strips are thinner than a display pixel at full-board scale; the numeric measurements above are the evidence, not visual appearance.

- ![Valentine top copper difference](../phase2c/results/visuals/gerber-pcb-valentine-feb-new-Gerber_TopLayer.GTL-diff.png)
- ![Valentine bottom copper difference](../phase2c/results/visuals/gerber-pcb-valentine-feb-new-Gerber_BottomLayer.GBL-diff.png)
- ![Laser Module top copper difference](../phase2c/results/visuals/gerber-prickly-laser-module-2-5-Gerber_TopLayer.GTL-diff.png)
- ![Laser Module bottom copper difference](../phase2c/results/visuals/gerber-prickly-laser-module-2-5-Gerber_BottomLayer.GBL-diff.png)

Separate PyGerber SVG renderings of each source copper layer are under `phase2c/results/visuals/*-pygerber.svg`; their inventory is in [`independent-render-inventory.json`](../phase2c/results/independent-render-inventory.json).

## Drill and slot reconciliation

The record totals are **413 circular drill records + 8 routed slots = 421 source features**. This reconciles the Phase 2B figure; the 405 number in the Phase 2A executive summary was an error. Every source record remains in the Phase 2A record inventory with file, source index, tool code, original diameter, coordinates, plating label, and role.

The 12 Valentine duplicate pairs are identical in X, Y, and 0.30998 mm diameter, one PTH-through record and one PTH-via record per pair. At every one of the twelve coordinates, the top copper has an exact-center circular pad flash and the bottom copper has a matching circular pad flash. This supports a single physical plated hole with two retained provenance records; two physical holes at one identical center/diameter are not represented as two operations. The machine-readable reconciliation lists both source record IDs and the top/bottom pad-flash object indices. These 24 source rows reconcile to 12 physical holes. The remaining source records produce 401 unique circular physical-hole candidates from 413 circular records. Tool selection remains unset, including for the 12 reconciled holes.

| Nominal group | Valentine records | Laser Module records | Total |
|---|---:|---:|---:|
| PCB - Drill 0.8mm (≤0.805 under the retained ±0.005 mm policy) | 188 | 74 | 262 |
| PCB - Drill 1.0mm | 20 | 38 | 58 |
| PCB - Drill 1.1mm | 0 | 0 | 0 |
| PCB - Drill 1.2mm | 0 | 6 | 6 |
| PCB - Drill 2.0mm | 0 | 0 | 0 |
| PCB - Drill 3.0mm | 0 | 0 | 0 |
| PCB - Drill 3.1mm | 0 | 0 | 0 |
| Unassigned | 22 | 65 | 87 |
| **Circular source records** | **230** | **183** | **413** |

The complete unassigned distribution retains original dimensions and file/tool/plating data:

| Board | File / tool | Original diameter (mm) | Class | Count |
|---|---|---:|---|---:|
| Valentine | `Drill_PTH_Through.DRL` / T04 | 0.89916 | PTH, unsupported nominal size | 2 |
| Valentine | `Drill_PTH_Through.DRL` / T05 | 0.91440 | PTH, unsupported nominal size | 16 |
| Valentine | `Drill_NPTH_Through.DRL` / T01 | 2.20000 | NPTH, unsupported nominal size | 4 |
| Laser Module | `Drill_PTH_Through.DRL` / T04 | 0.91500 | PTH, unsupported nominal size | 44 |
| Laser Module | `Drill_PTH_Through.DRL` / T06 | 1.18000 | PTH, unsupported nominal size | 21 |

These diameter groups remain unassigned; no source diameter was rounded or substituted. There are no >3.105 mm profile-bore candidates. Laser Module has 8 separate plated slots: four 0.751 mm and four 1.000 mm. The machine-readable [`drill-reconciliation.json`](../phase2c/results/drill-reconciliation.json) gives each unassigned size a `DRILL_DIAMETER_UNASSIGNED` warning that blocks tool assignment. A future output guard rejects repeated identical physical drill operations unless an explicit approval is supplied. This phase does not choose actual cutter diameters or generate a machining tool plan.

Plating and role labels remain derived from Excellon headers and filenames, not cross-section fabrication data. The Valentine flying-probe JSON member was read directly from the preserved ZIP. It is in mils and its pin coordinates have no explicit transform to the Gerber/Excellon frame; it did not resolve hole roles or prove the registration transform. No Laser native CAD project was available within the supplied archive.

## Profile and coordinate registration

PyGerber independently rebuilt the profile layers from line centerlines and polygonized the closed networks. The 0.254 mm profile aperture is the drawn stroke width; nominal profile coordinates are the centerlines, not a 0.127 mm offset silhouette. Both layers yield one closed polygon, zero dangles, zero cut-line length, and no internal cutouts. Comparing against the Phase 2A profile yields zero symmetric-difference area and 1.42e-14 mm maximum boundary distance for each board. Profile bounds and measurements are in [`profile-comparison.json`](../phase2c/results/profile-comparison.json).

All drill centers and all slot paths lie inside the independently rebuilt profile: Valentine 230/230 hits; Laser Module 183/183 hits and 8/8 slots. Comparing plated drill centers with copper flash centers gives a maximum nearest-pad residual of 0.000100 mm for Valentine and 0.000580 mm for Laser Module. At those small screening tolerances, 226 Valentine plated records (214 through-hole + 12 via) and all 183 Laser plated hits have a flash center on both copper sides. Four Valentine NPTH holes have no matched copper pad flash, as expected for NPTH. The coordinate checks applied no bottom-side mirror. A mathematical round-trip of an X reflection about the profile center has residual below 1e-12 mm, but the physical machining-side mirror convention is not proven. Detailed counts and residuals are in [`coordinate-registration.json`](../phase2c/results/coordinate-registration.json).

These results show strong coordinate consistency among the supplied Gerber and Excellon files. They do not prove how the original PCB authoring system placed those files in a global board coordinate system, nor establish the downstream machining orientation.

## Delta arc-bound investigation

The four copper files contain no arcs. For the 293 arcs in the other Gerber layers, the independent analytic calculation used each directed arc's parsed start/end/center, Ucamco clockwise/counterclockwise sweep semantics, exact circle cardinal extrema, and half the circular aperture width. It matched Delta's reported bounding boxes on 14 arcs; **279 bounds differ**, with a maximum bound-coordinate discrepancy of **2.500120 mm**. This reproduces the Phase 2B set: 256 Valentine top silkscreen, 6 Valentine bottom silkscreen, 8 Valentine documentation, and 9 Laser Module top silkscreen arcs. At the largest example, Valentine top silkscreen object 1983, the Delta upper-Y bound is 2.50012 mm beyond the analytic directed-sweep envelope. Delta and PyGerber/Gerbonara arc endpoints, centers and directions agree within 1.5e-14 mm. The evidence points to Delta's arc bounding-box calculation using the wrong sweep extrema; it does not indicate a copper parser defect. All per-arc source parameters, analytic bounds, Delta bounds, and signed differences are in [`delta-arc-analytic.json`](../phase2c/results/delta-arc-analytic.json).

No affected arc belongs to a copper layer, so this Delta bounds defect does not change the four copper measurements above. Ucamco semantics and independent analytic extrema establish the intended bounding box for the directed source arc. Delta rendered geometry itself was not compared to a numerical raster reference.

## Repair audit

Phase 2A had 98 `make_valid` repairs in total: 2 Valentine bottom copper, 37 Valentine top silkscreen, and 59 Laser Module top silkscreen. Phase 2B replayed all 98 repairs twice and found normalized WKB-identical results. The Phase 2C review independently rechecked the two copper regions:

| Valentine bottom object | Input state | Area before → after (mm²) | Area delta (mm²) | Repeatable | Repaired result |
|---:|---|---:|---:|---|---|
| 0 | Invalid, self-intersecting | 2721.054484720063 → 2721.054484720053 | −1.00044e-11 | Yes | GeometryCollection: polygonal area plus MultiLineString remainder |
| 1 | Invalid, self-intersecting | 410.994823278400 → 410.994823278400 | +3.41061e-13 | Yes | GeometryCollection: polygonal area plus MultiLineString remainder |

The affected polygons were not valid inputs, so GEOS cannot give a meaningful source-to-repaired symmetric difference or prove the intended source topology. At whole-layer level, independent and Phase 2A final copper have equal component and void counts and a 0.000981 mm boundary distance. That confirms the repair is stable and numerically small; it does not prove that the self-intersecting source rings represented the intended material. Repair and intended topology remain separate warnings. Details are in [`copper-repair-audit.json`](../phase2c/results/copper-repair-audit.json).

## Regression suite and reproducibility

Run from the repository root:

```powershell
.\phase2c\run_verification.ps1
```

The script regenerates the copper compositions, numerical reports, high-resolution overlays, PyGerber SVG renders, and then runs the tests. **The full regeneration and test command completed successfully; 9 tests passed.** Tests cover the independent copper metrics, source archive hashes, area/topology and profile baselines, drill and slot totals, diameter reconciliation, duplicate provenance, duplicate-operation guard, ordered clear/dark compositing, analytic arc extrema, known Delta disagreements, repair determinism, and registration/mirror round-trip. The committed test log from the final run is the terminal result; tests can be rerun with `phase2a/.venv/Scripts/python.exe -m unittest -v phase2c.test_phase2c` after setting `PYTHONPATH` to `phase2b/.venv/Lib/site-packages`.

The baselines are categorized as follows:

- **Independent parser plus independent composition:** PyGerber command parsing and the Phase 2C command-to-geometry adapter, compared with the Phase 2A Gerbonara reconstruction.
- **Shared geometry engine:** Both polygon compositions use Shapely/GEOS; common overlay-kernel behavior remains a validation limitation.
- **Analytic verification:** Directed arc extrema, known circle sagitta, region closure checks, and analytic test geometries.
- **Renderer comparison:** PyGerber SVG output exists for every copper layer, but uses PyGerber's own parser output and has not been accepted as independent numerical proof.
- **Self-consistency/golden regression:** Source hashes, recorded metrics, topology counts, drill reconciliation, and deterministic repairs.
- **Manual independent CAM confirmation:** Not performed. KiCad GerbView and Ucamco's Reference Gerber Viewer were not used to create a numerical golden; Ucamco conformance fixtures were not run.

## Acceptance assessment

| Criterion | Result | Evidence / remaining gap |
|---|---|---|
| Preserve source archives and previous Phase 2A/2B state | **PASS** | Original archive hashes rechecked; old files left unchanged. |
| Reconcile 413 circular records and 8 slots | **PASS** | 421 source features reconcile; 401 unique circular location/diameter features after the 12 exact paired records are represented once. |
| Preserve all 87 unassigned diameters | **PASS** | Exact file, tool, diameter, plating and count appear in machine-readable warning inventory. |
| Resolve Valentine duplicate PTH/via records | **PASS, physical feature identity** | 12 pairs each have same source XY/diameter and an exact pad flash on top and bottom; one physical hole retains both provenance records. Cutter selection remains unset. |
| No accidental duplicate physical output operation | **PASS, guard verified** | Output guard rejects duplicate identical location/diameter operations without explicit approval; the duplicate source rows are reconciled to one physical feature each. |
| PyGerber/Phase 2A numerical copper comparison | **PASS, interpreted polygon results** | All four maximum boundary distances are 0.000964–0.000983 mm, below 0.005 mm; measured areas, symmetric differences, bounds, components and voids are retained. |
| Valentine top copper source geometry | **PASS, parser/compositor scope** | Valid composition, counts and boundary comparison agree; no unsupported source construct in the layer. |
| Valentine bottom copper intended topology/material | **NOT VERIFIED** | Two source regions self-intersect and require `make_valid`; repaired outputs are repeatable and area deltas negligible, but intended topology cannot be established from invalid rings. |
| Laser Module top copper source geometry | **PASS, parser/compositor scope** | Valid composition, counts and boundary comparison agree; no unsupported source construct in the layer. |
| Laser Module bottom copper intended topology/material | **NOT VERIFIED** | All 182 source region contours are open, contrary to the Gerber closure rule; measured result uses an explicit implicit-closing-chord interpretation. |
| Board profile reconstruction | **PASS, source centerline reconstruction** | Both profiles close as one polygon with zero dangles/cut lines; independent profile symmetric difference is zero and boundary distance is about 1.4e-14 mm. |
| Source-coordinate registration | **PASS, numeric consistency** | All drill hits/slots lie inside profile; plated hits map to copper flash centers within reported residuals; no raw-side mirror applied. Physical authoring origin and actual machine orientation remain unproven. |
| Delta arc-bound discrepancy diagnosis | **PASS, diagnostic** | Analytic directed extrema reproduce 279 mismatches up to 2.50012 mm; copper files have no arcs. |
| Two Valentine copper repair repeatability | **PASS, stability only** | Repeated `make_valid` normalized geometry is identical; material intent is not verified. |
| Independent absolute manufacturing geometry truth | **NOT VERIFIED** | No approved CAM/EDA golden output or manual independent viewer confirmation; shared GEOS is used by both numerical compositions. |
| Manufacturing readiness | **NOT CLAIMED** | Open and invalid source regions and unassigned drill sizes still require source/design-owner review and tool policy. |

## Remaining work before the next phase

1. Obtain a corrected Laser Module bottom Gerber with all 182 region contours explicitly closed, or get the source owner to approve the intended closure rule. Re-run composition and compare the fixed source hash.
2. Adjudicate the two self-intersecting Valentine bottom regions against native CAD or fabrication-approved output before using those copper boundaries for machining.
3. Review the twelve deduplicated Valentine holes and their retained PTH/via roles in the source project; the paired copper pads corroborate one physical hole, but the source export's role semantics still need owner confirmation.
4. Decide tool handling for the 87 unassigned diameters and choose actual cutters only from an approved tooling policy; original diameters remain intact.
5. Obtain an independent CAM/EDA render or conformance-approved output for visual and numerical golden confirmation. Until then, current numerical results verify agreement between independently parsed and reconstructed models, not an absolute manufacturing truth.

**Phase 2C stops here.** No GUI, isolation engine, native Design importer, or manufacturing toolpath work has started.
