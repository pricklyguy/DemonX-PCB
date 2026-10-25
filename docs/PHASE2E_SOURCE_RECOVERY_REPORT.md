# DemonX PCB Prep — Phase 2E Source Validation and Controlled Recovery

Date: 2026-10-25. Branch: `codex/pcb-prep-phase-2a`.

**Result: Valentine’s two bottom-copper regions are RECOVERABLE through a disclosed exact no-op normalization; Laser Module’s 182 open regions remain BLOCKED.** The Phase 2D counts reproduce independently from the source scan, Gerbonara outlines, and PyGerber command buffers: 117 Valentine cut-ins, 119 zero-length region draws, 182 Laser open contours, and 184 regions rejected by the unchanged strict source validator. The distinction is now between strict conformance and recoverable redundancy. Valentine is not rejected as a complete board merely for those redundant commands.

All 182 Laser contours have separate straight-closure candidates, exact displacement records, intersection checks, area/topology sensitivity measurements, and overlays. Every candidate produces a valid polygon and only touches its adjacent boundary endpoints. **That geometric result does not prove manufacturing intent; all 182 remain blocked.** No real manual exception was supplied or recorded.

The user confirms that the original editable EasyEDA projects still exist. No matching project is staged in the inspected locations, and no project access was requested. Archive-to-native revision identity remains **NOT VERIFIED**. This report specifies exactly what native files, settings and measurements would resolve it.

## 1. Preserved state and reproducibility

Original ZIPs, extracted manufacturing files and Phase 1–2D reports/results remain unchanged. The final runner compared hashes of **96 prior files** and found zero changes: [`preservation.json`](../phase2e/results/preservation.json). Pre-existing untracked work and the tracked `.gitignore` edit were preserved. There was no reset, push, merge, global installation, or edit to DemonX Circuit, Design or CNC.

Run from the repository root:

```powershell
.\phase2e\run_recovery.ps1
```

The existing project-local environment provides Python 3.12.14, Gerbonara 1.6.3, PyGerber 2.4.3, Shapely 2.2.0 and GEOS 3.14.1. The new code is an isolated verification/recovery model under `phase2e/`, not the standalone application or manufacturing engine. It handles the observed exact linear region subset and blocks unsupported interpolation. The older strict Phase 2D behavior and historical Phase 2A/2C polygon outputs remain reproducible.

## 2. Specification findings and version dependence

Ucamco [Gerber revision 2026.05, §4.10.3, pp. 98–99](https://www.ucamco.com/files/downloads/file_en/554/gerber-layer-format-specification-revision-2026-05_en.pdf) requires exact region closure, permits constrained coincident cut-ins, and prohibits zero-length contour draws. A region segment is a contour edge rather than a stroked aperture image. G37 ends the region statement without supplying a missing edge. These rules distinguish the two defect classes here.

There is relevant historical reader guidance. [Revision 2021.02, §4.10.3, p. 90](https://www.ucamco.com/files/downloads/file_en/416/the-gerber-layer-format-specification-revision-2021-02_en.pdf) explicitly allowed readers to remove zero-length contour segments before processing. [Revision 2024.05, §4.10.3, p. 91](https://www.ucamco.com/files/downloads/file_en/456/gerber-layer-format-specification-revision-2024-05_en.pdf) already prohibited them; 2026.05 retains that prohibition. This audit establishes the difference between those versions, not the exact intervening revision that changed the wording. Neither older guidance nor an exporter timestamp makes a nonconforming file VALID under 2026.05.

Phase 2E uses that historical reader guidance together with exact path equivalence to define a narrow compatibility policy. The original Valentine regions remain nonconforming under 2026.05, while their derived contours pass current cut-in validation. This is an explicit recovery classification, not a claim that the current specification defines the image of arbitrary invalid contours. No analogous rule justifies inventing an absent Laser edge.

Zero-length draws **outside** regions are different: their aperture produces an image, potentially equivalent to a flash. The policy does not remove them. A regression fixture proves that such a draw retains nonzero area.

### Independent reproduction

| Representation examined directly | Valentine cut-in pairs | Valentine zero-length draws | Laser open contours | Strictly rejected source regions |
|---|---:|---:|---:|---:|
| Original command scanner | 117 | 119 | 182 | 184 |
| Gerbonara raw Region outlines | 117 | 119 | 182 | 184 |
| PyGerber Region2 command buffers | 117 | 119 | 182 | 184 |

Every explicit coordinate matches the original 0.00001 mm source grid exactly in the compared representations. Gerbonara’s later graphics primitive still adds a closing segment to each Laser region; that derived primitive is not used as proof of source closure. Full reproduction results are in [`independent-reproduction.json`](../phase2e/results/independent-reproduction.json).

## 3. Controlled recovery model

| Status | Meaning | Source-region consequence |
|---|---|---|
| VALID | The geometry conforms within the supported validation subset. | Geometry may proceed; unrelated job/tool/setup checks still apply. |
| RECOVERABLE | A recorded normalization has a demonstrated, unambiguous material interpretation. | Preserve the nonconformance warning and original commands; use only the separately identified derived model. |
| BLOCKED | Material intent is uncertain or the construct is unsupported. | Keep source paths and candidate geometry separate; prohibit ordinary downstream use. |

The run explicitly enables policy `pcbprep.exact-zero-length-region-draw.v1`. It omits only **G01/D01 region segments whose original integer start and end coordinates are exactly equal**. It does not move vertices, change nonzero segments, add edges, snap endpoints, or use an area filter. Every omission is recorded with the original command and one-based source line. The source bytes and source hash remain unchanged. The accepted derived contour is built by the Phase 2D strict cut-in converter without `make_valid`.

For uncertain candidates, a tested manual-exception interface requires the exact source hash, candidate hash, reviewer, reason and explicit unresolved-risk acknowledgement. The candidate digest includes its geometry and source-command range; tampering or stale hashes fails the permission check. Even an informed exception leaves validation **BLOCKED**, `intendedGeometryVerified=false`, and `unresolvedRisk=true`; it can authorize only a separately recorded candidate-use exception. It cannot silently reclassify the source as VALID or declare machining readiness. No actual exception was exercised for either board.

The machine-readable records include board/file identity, source ranges, severity, issue code, exact original geometry/commands, proposed changes and geometry, numeric differences, confidence, evidence, eligibility, action and acceptance state. See [`validation-records.json`](../phase2e/results/validation-records.json) and the [draft JSON Schema](../phase2e/schema/source-validation-record.schema.json). The tests check required fields, safety invariants and finite JSON values; a separate complete Draft 2020-12 schema validator was not run. No GUI or receiver was implemented.

## 4. Valentine recovery and cut-in preservation

| Region | Original source lines | Recorded no-op omissions | Preserved horizontal cut-ins / holes | Derived region area (mm²) | Status |
|---:|---|---:|---:|---:|---|
| 0 | 34–5714 | 105 | 103 | 2721.05448472005 | RECOVERABLE |
| 1 | 5715–6302 | 14 | 14 | 410.99482327840 | RECOVERABLE |

The exact sequence of all nonzero edges, first/last coordinates, and signed shoelace area remains identical. The recovery is idempotent. Source-specific original and derived `.gbr` fixtures are retained under [`phase2e/fixtures/`](../phase2e/fixtures/); both independent parsers verify their coordinate sequences and the original/normalized zero-length counts.

Both original contour records remain nonconforming, but their zero-length operations have no material ambiguity in this G01 region context. Their omission changes enclosed material by exactly zero at the integer path level. Cut-ins are converted into actual polygon holes rather than diagnosed as generic polygon self-intersections. No copper islands or clearances are removed. At whole-layer level, the fresh bottom reconstruction retains **110 components and 181 voids**, matching Phase 2C. The actual floating-point area difference is −9.0949470e-12 mm².

The warning is visible in each record, and `sourceConforms202605` remains false. Valentine is eligible for **geometry preparation with disclosed recovery**, not rejected solely because of these commands. Tool selection and other manufacturing gates are separate; this phase does not approve a machining job.

## 5. Laser: candidates and material sensitivity

All **182** original open contours remain BLOCKED. Each record includes start/end coordinates, exact end-minus-start displacement in decimal millimetres, the original G36/G37 line range, the absent edge, and a separately hashed straight-edge proposal. The source closure gaps range from 0.01455039862 mm to 81.40141 mm: 1 horizontal, 69 vertical and 112 diagonal.

Every proposed edge was checked against each explicit contour segment with exact rational predicates. All 182 touch only the expected adjacent endpoints, and all 182 candidate polygons validate geometrically. Neither result establishes that the omitted straight edge is the intended EasyEDA boundary.

The original open contour has no specified filled interior. Consequently **source-to-candidate copper area and topology differences are null**, rather than fabricated as zero or as a loss of the entire candidate area. Records instead provide:

1. Candidate polygon area/topology, including exact shoelace area as a rational value.
2. A diagnostic marginal scenario: assume the other 181 proposed closures; compare the final layer with this region omitted against the layer with it included, preserving source dark/clear order and later artwork.

These are sensitivity measurements, not approved material changes. Effects overlap and cannot be summed independently.

| Candidate | Source lines | Gap (mm) | Candidate region area (mm²) | Effect on final copper in the marginal scenario (mm²) |
|---:|---|---:|---:|---:|
| 0, dark base region | 32–63 | 81.401410 | 8135.808469378 | +5787.247499214 |
| 118, clear region / shortest gap | 7035–7046 | 0.014550 | 0.333834560 | −0.219908086 |
| 181, clear region | 8251–8261 | 0.450090 | 0.124556267 | −0.111900097 |

The largest modeled clear-region effect is **−133.843486501 mm² at region 52**. Adding the dark base candidate changes the modeled layer from 105 to 69 material components and introduces 181 voids. Each clear candidate introduces one modeled void, with component changes also recorded individually. This illustrates why silently omitting a clear region or approving any convenient closure is unsafe.

There are [182 individual SVG overlays](../phase2e/results/overlays/) and a dimensioned selection:

![Original Laser contours and unapproved closing edges](../phase2e/results/overlays/selected-laser-candidates.png)

All real acceptance records remain empty. Independent matching native source evidence or explicit informed acceptance is still required. Manual acceptance, if later supplied, retains the unresolved-intent risk and does not prove the shape.

## 6. Source regeneration and EasyEDA addendum

### Provenance established from the supplied files

| Dataset | Exporter header evidence | Revision match to editable project |
|---|---|---|
| Valentine | EasyEDA Pro 2.2.45.4; Gerber Generator 0.3; 2026-02-05; one-click export | NOT VERIFIED |
| Laser Module | EasyEDA 6.5.51; Gerber Generator 0.2; 2026-06-11; opaque comment markers `97eb0bbe93fb4be09f112c218f02c656,f2a3d59ec7b1417cbfc1eaa01b809597,10` | NOT VERIFIED |

Headers establish exporter claims, not a cryptographically bound native project revision. The opaque Laser comment is preserved without guessing which values identify a project, document or revision. Filename and board-size similarity alone are insufficient. The complete archive-member inventory, hashes and relevant headers are in [`archive-project-provenance.json`](../phase2e/results/archive-project-provenance.json).

The archives contain manufacturing outputs, not editable PCB projects. Valentine’s `FlyingProbeTesting.json` is test data, not the source PCB. The [EasyEDA Pro fabrication documentation](https://prodocs.easyeda.com/en/pcb/export-pcb-fabrication-file-gerber/) identifies that file as JLCPCB flying-probe data and distinguishes the general PTH and JLCPCB-specific via drill files. That documentation is also consistent with preserving the twelve source drill pairs while proposing one physical hole at each exact duplicate location.

The 119 redundant draws recur throughout the two Valentine regions, and omission of the final closing edge occurs in every one of the 182 Laser regions. These are consistent patterns **within these two archived exports**. The boards use different editor editions and generator versions. The official exporter documentation examined does not establish either pattern as a guaranteed EasyEDA-wide convention, and no repeat export was performed. An intentional convention, an exporter defect, cached-pour behavior and revision-specific behavior therefore remain hypotheses. Current [EasyEDA Standard release notes](https://docs.easyeda.com/en/FAQ/Update-Record/) document historical Gerber fixes, but do not prove the cause of these particular commands.

### Regeneration feasibility in this phase

The user confirms that the original editable EasyEDA projects remain available. They have not been accessed. A bounded filename search of this repository and adjacent checkouts under `Documents/Github`, including ignored/hidden files but excluding dependencies and Git internals, found no `.epro`, `.eprj`, `.easyeda`, or `.kicad_pcb` candidate. JSON files in the supplied archives were inspected for native PCB source structure; none was found. This does not assert that the projects are unavailable elsewhere.

The installed `kicad-cli version` reports **10.0.7**. It also emitted restricted profile/registry-access diagnostics during that version check. No matching authoritative KiCad board is present, so no KiCad manufacturing export was attempted. Converting an EasyEDA project to KiCad would create a derived reference with its own conversion risks; it must not be treated as the original authoritative design or substituted merely to obtain a clean Gerber.

### Exact evidence that would help next — documented, not requested

For **Valentine**, the useful package is a complete EasyEDA Pro project export (project ZIP/`.epro`, or an offline `.eprj` copy), including the matching PCB document, cached/saved copper fill data, project/document revision identity and export configuration. The [Pro project export guide](https://prodocs.easyeda.com/en/project/file-save-as-local/) and [Pro import/export FAQ](https://prodocs.easyeda.com/en/faq/import-export/) describe local project export and the distinction between online and offline project forms.

For **Laser Module**, it is the original EasyEDA Standard PCB JSON plus complete project backup ZIP, including copper pours, solid regions, tracks, pads, vias, holes and saved fill data where available, together with revision/history evidence. The [Standard source-export guide](https://docs.easyeda.com/en/Export/Export-EasyEDA-Source-File/) documents JSON source export and whole-project ZIP download.

For both boards, the minimum identity/geometry evidence is:

- Project and PCB document identity, saved revision/history entry and editor/generator version corresponding to the archived export; immutable file hashes before opening or migrating.
- Complete board-outline coordinates and dimensions: Valentine **86.26655 × 76.72680 mm**, Laser **116.45877 × 83.43882 mm** in the delivered coordinate frame.
- Complete drill center/original-diameter/plating/slot table, including all 413 source hit records, 8 slots and the duplicate-file roles. Native physical counts may be 401 unique holes, so source-record counts and physical counts must remain separate.
- Raw top/bottom copper bounds, filled areas, component and hole counts, plus at least three noncollinear pad/drill anchors. Capture units, canvas origin, rotation, mirror, scale and panelization settings.
- For Valentine, the native copper-fill loops proving the 103/14 region holes and retained islands/clearances.
- For **each** Laser candidate, a native object identity, side/net and closed boundary/fill evidence showing intended copper on both sides of the proposed edge. Full native boundary coordinates or a faithful native fill export are stronger evidence than a screenshot. Annotated PCB-editor measurements and selected cross-sections can corroborate that evidence, but a coarse preview cannot prove sub-0.005 mm boundaries.

The machine-readable checklist and numerical fixture targets are in [`native-project-evidence-requirements.json`](../phase2e/results/native-project-evidence-requirements.json). It explicitly records that project access has not been requested.

### Proposed native comparison procedure

1. Hash and preserve an immutable project backup. Match project/document/revision history to the original exporter header and available IDs before assuming correspondence.
2. Open a duplicate in the original EasyEDA edition/version where possible. Record migration or library updates. Capture the **saved** fill first; perform a pour rebuild only on another duplicate so cached-fill differences are measurable.
3. Preserve the export configuration. [EasyEDA Pro’s exporter documentation](https://prodocs.easyeda.com/en/pcb/export-pcb-fabrication-file-gerber/) describes custom configuration, layer/primitive selection, canvas coordinates and drilling precision. Record the actual settings rather than accepting current defaults.
4. Export twice from the same unchanged snapshot into separate fresh directories. Retain native snapshots, export logs, ZIPs and file hashes. Compare content after accounting for documented non-geometric headers; header-only differences do not prove design drift, and identical dimensions do not prove identical design.
5. Independently parse and compose each re-export with the same precision policy. Compare all copper boundaries, symmetric differences, topology, profiles, raw drill/slot coordinates and original diameters. Use explicit coordinate transforms only; do not auto-fit a mirror or translation to hide disagreement. Separate exporter changes, repour changes and actual revision changes.
6. Map all 182 archived Laser source ranges/candidate bounds back to native objects and fill. A re-export counts as supporting intent only after matching revision and whole-board geometry. If original-version reproduction is unavailable, document that limitation and retain the uncertainty.

No native project export, PCB-editor inspection, or native-to-Gerber numerical comparison was possible in this phase without accessing those projects. These outcomes are **NOT VERIFIED**, not assumed to pass.

## 7. Existing geometry and regression results

The four layers were freshly composed from PyGerber commands. Valentine bottom uses strict cut-in construction after the recorded no-op normalization. Laser bottom is explicitly an **unapproved all-closures diagnostic scenario**, not an accepted layer.

| Board / layer | Fresh area (mm²) | Components | Interior voids | Area delta from Phase 2C reference (mm²) |
|---|---:|---:|---:|---:|
| Valentine top | 803.967680437 | 165 | 0 | 0 |
| Valentine bottom, disclosed recovery | 3857.550818124 | 110 | 181 | −9.0949470e-12 |
| Laser top | 511.742855622 | 191 | 0 | 0 |
| Laser bottom, candidate scenario | 7762.055001280 | 69 | 181 | −3.6379788e-12 |

All component/void counts match and maximum bound discrepancies are at floating-point noise scale. Exact current metrics and comparisons are in [`copper-remeasurement.json`](../phase2e/results/copper-remeasurement.json). These use the Phase 2C 128-segments-per-quadrant policy; they should not be confused with the coarser Phase 2A areas. Fresh Phase 2B tests also reconstruct all four Gerbonara copper layers and both board profiles against the retained Phase 2A baseline.

All five Excellon files were freshly parsed. Each hit/slot record, original diameter, source feature index and coordinate matches the saved inventory. Totals remain **413 circular source records, 8 routed slots, 12 proposed physical-hole deduplications, 401 unique circular physical-hole candidates, and 87 unassigned source diameters**. Both profiles and mathematical mirror round-trips pass the existing regressions. The physical machining-side convention remains unproven and no source mirror was applied by recovery.

| Suite | Passed | Log |
|---|---:|---|
| Phase 2A | 16 | [test-phase2a.txt](../phase2e/results/test-phase2a.txt) |
| Phase 2B | 7 | [test-phase2b.txt](../phase2e/results/test-phase2b.txt) |
| Phase 2C | 9 | [test-phase2c.txt](../phase2e/results/test-phase2c.txt) |
| Phase 2D | 19 | [test-phase2d.txt](../phase2e/results/test-phase2d.txt) |
| Phase 2E | 16 | [test-phase2e.txt](../phase2e/results/test-phase2e.txt) |
| **Total** | **67** | All final-run commands exited successfully. |

New tests cover exact edge/material preservation, idempotence, policy enablement, cut-in holes, source-specific fixtures parsed independently, rejection of one-tick gaps and unsupported arcs, meaningful zero-length draws outside regions, all candidate closures remaining blocked, hash-bound manual exceptions with retained risk, live drill/slot/diameter reconciliation, and fresh copper metrics. No production GUI tests or toolpath generation ran.

## 8. Eligibility, remaining blockers and next phase

[`manufacturing-eligibility.json`](../phase2e/results/manufacturing-eligibility.json) contains the scoped outcomes. Source-region handling now permits Valentine geometry preparation with visible recovery records. Its original nonconformance remains recorded; that alone does not reject the complete board. Laser’s 182 bottom regions and any operation dependent on their material/clearances remain blocked. Unrelated top copper, profile and drill inventory are not discarded.

The remaining blockers are explicit:

1. **182 Laser open regions:** no native revision/intent evidence and no real informed manual acceptance. All candidate fills remain unapproved despite valid polygon checks.
2. **Native revision correspondence:** both EasyEDA project matches and repeat export behavior remain NOT VERIFIED. The user confirms project availability; this phase specifies evidence without requesting access.
3. **Tooling and setup:** the 87 unassigned diameters, actual cutter selection, stock/depth and physical side transforms remain separate manufacturing gates. No tool assignment was inferred from hole geometry.
4. **Accuracy limits:** common Shapely/GEOS behavior, absence of a fabrication-approved native reference, and the scoped linear validator remain limitations. Current agreement does not establish universal Gerber conformance or manufacturing readiness.

The recommended next phase is **native EasyEDA revision and design-intent verification**, using the documented evidence package and comparison procedure. It should resolve the Laser closures, repeat the exporter experiment and lock reviewed source-specific golden results before manufacturing engines or UI work.

**Phase 2E stops here for review.** No GUI, CNC/toolpath implementation, DemonX integration, or native `.dxd` writing was started.
