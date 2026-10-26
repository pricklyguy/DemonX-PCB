# DemonX PCB Prep — Phase 2J Valentine Native Copper Verification

**Status:** Native reference inspected; comparison remains partial and manufacturing blocked.
**Branch/checkpoint:** `codex/pcb-prep-phase-2a`, base `a450926943169ec3cf599ceb797d50aca8344e4b`.
**Scope:** Read-only Valentine `.epro` and Gerber ZIP comparison, strict cut-in material reconstruction, diagnostic offsets, draft canonical geometry contract. No toolpaths, G-code, CNC output, or `.dxd` transfer.

## 1. Executive findings

The available EasyEDA Pro project is a strong geometry reference for the supplied Valentine Gerber export, but this comparison does not cryptographically bind the export to the saved project revision. We classify correspondence **PARTIAL**. Twelve native VIA objects register to all 12 via-export hits and the same 12 repeated PTH records with residuals at floating-point noise. Native outline bounds agree with the Gerber profile to the original Gerber 0.00001 mm coordinate grid. Those checks strongly support the board coordinate frame and demonstrate the PTH/via records are repeated fabrication representations of the same native VIA objects.

The two bottom Gerber regions are valid material under the already reviewed strict cut-in interpretation after omission of only exact zero-length region draws. They produce valid polygonal material with 103 and 14 voids; no `make_valid` is needed. This resolves the earlier GEOS *invalid intermediate Polygon* concern for these two source regions. It does **not** prove the Gerber and saved fill match: the strict reconstruction and native cached fills differ by 2.202307531 mm² and 0.210049321 mm² symmetric-difference area. Region 0’s GEOS boundary Hausdorff distance is 0.005050711 mm, 0.000050711 mm above the stated 0.005 mm target, and region 1’s is 0.004760805 mm. The differences require explanation; both regions remain blocked from machining approval.

The historical 23.174808194 mm² generic 0.05 mm inset difference came from buffering the invalid raw self-intersecting Polygon representation. It is not evidence of an actual board defect and is not a valid reference comparison. Strict Gerber and native saved-fill polygons buffer repeatably and have matching connected-component counts at 0.05, 0.1 and 0.2 mm, but their area and symmetric differences remain nonzero. These are diagnostic offsets only, not V-bit isolation paths.

## 2. Evidence provenance and project identity

Inputs were read without modifying or extracting the native project/archive. The comparison runner writes hashes, parsed summary and derived visuals only under the ignored `phase2j/results/` directory. Input SHA-256 values:

| Input | Size | SHA-256 | Provenance evidence |
|---|---:|---|---|
| `Gerber_PCB_Valentine_Feb_New.zip` | 225,120 bytes | `2e23a8cff4bd48d947f5f7fda371b8669d054c03cc87bb561bc2854d39337796` | `Gerber_BottomLayer.GBL` SHA-256 `f701e7ada043321c89a2c3baf73a84c32a3aad93cc3259bd9eff07bbd8e47843`; headers identify EasyEDA Pro 2.2.45.4 / Gerber Generator 0.3, one-click export, 2026-02-05 23:23:45. |
| `ProPrj_PCB_Valentine_2026_2026-02-05.epro` | 193,226 bytes | `43c1992652a107d1e7967ae902a643701695c2132cfbf87ce2b475c7fe7cc440` | Project config editor version 2.2.45.4; one PCB document; native JSONL member SHA-256 `4adfbeb65d55f5635be1a78b19edb6f51500018b26d54629a1ccab1947b67941`; project manifest SHA-256 `c2a9e63e8b5d942c213684e7efaac1c9337affaf742c11517067c30cb76beaea`. |

The project PCB UUID `6a919ff151664a69a5e442d68ea9e07c` matches the UUID prefix in its native document HEAD. Filesystem modification times differ by 51.387 seconds (project later). Both archive header and project config report the same EasyEDA Pro editor version. Those are corroborating provenance, not an immutable export-to-revision link: the Gerber archive has no matching project/document UUID or signed revision identifier. Timestamp proximity, filename and visual similarity are not treated as proof.

The installed EasyEDA Pro is 2.2.47.7, newer than the source project exporter (2.2.45.4). The project was not opened or migrated. The 2.2.47.7 packaged JS parser was inspected read-only to corroborate `POURED` unit/path token behavior. This is not the original exporter build and not independent validation of that exporter’s saved-fill state.

### Native saved-fill interpretation

The native project contains a bottom-side GND `POUR` definition and two cached `POURED` fill records. Their path counts are 104 and 15, matching the boundary rings expected for 103 and 14 voids. Native cached paths store coordinates in `PX100` values; in the document’s mm canvas, the inspected EasyEDA conversion applies `0.254 mm` per serialized path unit. The native decoder retains source endpoints and analytic arc descriptors before bounded chord approximation (`0.00005 mm` sagitta target) for the Shapely comparison. No coordinate snapping was applied. Three object-0 native paths have endpoint gaps between `7.1e-15` and `1.42e-14 mm`; the fill decoder accepts only these one-ULP floating roundoff cases under a bound derived from the serialized float ULPs. The endpoints are not moved. The implicit polygon fill edge is represented separately in machine-readable output.

This native serialization/curve interpretation is reverse-engineered from saved project data with corroboration from a later editor build. It is not an official EasyEDA Pro export API. Arc approximation contributes at most the selected sagitta bound, but the area mismatches are much larger than floating arithmetic noise; a source-version native render/export or original-version API remains needed to establish the precise cached-fill interpretation.

## 3. Native-to-Gerber registration and non-copper checks

No transform was fitted to conceal disagreement. The matched VIA anchors support identity registration: native coordinates are in mil and scale exactly by 0.0254 mm/mil, with no rotation, translation, reflection or bottom mirroring.

| Check | Result | Assessment |
|---|---|---|
| Native board-outline bounds from `.epcb` layer 11 | [1.6976852, 7.4422508, 87.9642386, 84.1690468] mm; 86.2665534 × 76.7267960 mm | Native POLY bounds converted from mil. |
| Gerber `Gerber_BoardOutlineLayer.GKO` bounds | [1.69769, 7.44225, 87.96424, 84.16905] mm; 86.26655 × 76.72680 mm | Independently parsed in Phase 2C using PyGerber and Gerbonara command models. Bounds differences are within 0.0000048 mm; source rounding is 0.00001 mm. Full native outline topology correspondence was not computed. |
| Native VIA anchors | 12/12 match via-specific Excellon file and 12/12 match the duplicate PTH file; maximum center residual `1.42e-14 mm` | Strong anchor correspondence; source files are two representations at identical center coordinates. |
| Native VIA original hole diameter | `0.3099816 mm`; Gerber tool diameter `0.30998 mm`; delta `−0.0000016 mm` | Small encoding/precision difference retained, not normalized away. |
| Full pad geometries/flash contours | Not compared feature-by-feature | Native footprints/pad records need a complete footprint attachment transform and pad-shape decoder; no claim of full pad verification. |
| All PTH/NPTH centers and diameters | Not compared against native object inventory | Only the 12 VIA center anchors were checked here. Phase 2A–2I drill record/deduplication baselines remain in force. |
| Complete native profile curves/cutouts | Not compared topologically | Bounds agree, but full native POLY curve geometry and board-outline material semantics remain unverified. |
| Top copper and complete bottom copper | Top copper not compared to native; affected bottom cached fills compared below | Full board-wide native/Gerber revision identity remains PARTIAL. |

The twelve identical-coordinate VIA/PTH pairs correspond to twelve distinct native VIA objects, each present in both fabrication drill files. They are repeated file-role representations, not twelve pairs of coincident unrelated native drills. Phase 2A–2I’s 413 circular source records, eight routed slots, and twelve proposed physical-hole deduplications are unchanged; this native cross-check only confirms the twelve via/PTH pairs.

## 4. Bottom-copper region comparison

Gerber commands were reconstructed using the existing Phase 2D strict cut-in converter and Phase 2E source-specific exact no-op policy. Only G01/D01 region draws whose source integer start and end ticks are identical were omitted in the derived diagnostic. Original files and command sequences remain unchanged. Gerber coordinates have 0.00001 mm ticks. Native and Gerber material were composed separately; no invalid raw Gerber ring was used as an authority for material comparison.

| Gerber object | Source lines G36–G37 | Exact no-op draws omitted in derived geometry | Native fill ID / paths / arcs | Gerber material area (mm²) | Native saved-fill area (mm²) | Native minus Gerber area (mm²) | Symmetric difference (mm²) | Boundary Hausdorff (mm) | Components / voids, Gerber vs native |
|---:|---|---:|---|---:|---:|---:|---:|---:|---|
| 0 | 34–5714 | 105 | `e1698` / 104 / 539 | 2721.054484720 | 2718.853597164 | −2.200887556 | 2.202307531 | 0.005050711 | 1/103 vs 1/103 |
| 1 | 5715–6302 | 14 | `e1699` / 15 / 50 | 410.994823278 | 410.784954101 | −0.209869178 | 0.210049321 | 0.004760805 | 1/14 vs 1/14 |

The native outline/path bounds and ring counts closely correspond, but the nontrivial symmetric differences show that area and topology-count agreement alone do not establish identity. The current ring pairing is a greedy minimum-Hausdorff diagnostic and not a globally optimal proof. Full area, symmetric difference and GEOS boundary Hausdorff are calculated on valid composed polygons. Source-to-native boundary sample locations are recorded in the ignored result JSON; these are sampled vertices, not claimed exact Hausdorff maximizers.

For region 0, the largest sampled Gerber boundary displacement is near `(59.085700, 65.405000) mm`. The source command neighborhood is lines 4375–4376:

```text
line 4375: G01X5908570Y6540500D01*  ; (59.095410,65.305840) → (59.085700,65.405000) mm
line 4376: G01X6217666Y6540500D01*  ; (59.085700,65.405000) → (62.176660,65.405000) mm
```

This joins a curved boundary to a long horizontal segment within a valid cut-in/retrace construction. A nearby native saved-fill arc path is the closest corresponding boundary. This locates a discrepancy neighborhood; it does not identify whether the cause is stale cache, native fill generation, Gerber export, or a genuine revision difference. The exact missing evidence is an authenticated same-revision export plus a native Pro render/export or supported exact path API from the source exporter version, including whether the cached pour had been repoured at export time.

![Valentine region 0 full native/strict Gerber comparison](../phase2j/results/valentine-bottom-region-0-comparison.png)

![Valentine region 0 localized sampled boundary difference](../phase2j/results/valentine-bottom-region-0-local-discrepancy.png)

![Valentine region 1 full native/strict Gerber comparison](../phase2j/results/valentine-bottom-region-1-comparison.png)

![Valentine region 1 localized sampled boundary difference](../phase2j/results/valentine-bottom-region-1-local-discrepancy.png)

These generated diagnostic images are in ignored `phase2j/results/`, intentionally excluded from public Git along with all board-derived result JSON and source exports. Regenerate them using the command in §8.

## 5. GEOS repair and inset findings

The old Phase 2A warnings were caused by constructing an ordinary Shapely `Polygon` directly from Gerber cut-in boundary sequences that intentionally retrace coincident paths. That self-touching sequence is not a suitable polygon-ring representation of the material. The strict Phase 2D converter interprets the reviewed horizontal/vertical cut-in construction into valid faces, retains all 117 cut-in pairs across the two regions, and preserves the 103/14 voids. It makes no `make_valid` call and has no remaining invalid-polygon warning for these two source-specific conversions. Phase 2E’s 119 zero-length draws remain **HANDLED** as exact no-op normalization (105 + 14); they neither create missing copper nor shift points.

Therefore the prior two Phase 2A `make_valid` repair diagnostics are **obsolete as blockers for this specific strict cut-in material representation**, not evidence that the design is defective. Their legacy historical records remain traceable. The newly measured native-versus-Gerber material differences are independent current blockers; they are not superseded by the no-op/cut-in result.

### Offset diagnostic experiments

Old object-0 test: buffer of invalid raw ring versus buffer of `make_valid` output at −0.05 mm gave 23.174808194 mm² symmetric difference and 7 versus 6 connected components. This measures GEOS behavior on two interpretations of an invalid intermediate representation, not intended copper. The old pipeline must not feed these source regions to manufacturing offsets.

| Diagnostic inset distance | Region | Strict Gerber material area (mm²) | Native saved fill inset area (mm²) | Symmetric difference (mm²) | Components, Gerber / native |
|---:|---:|---:|---:|---:|---:|
| 0.05 | 0 | 2633.530340248 | 2631.423210729 | 2.108692528 | 6 / 6 |
| 0.10 | 0 | 2549.916221131 | 2547.877782506 | 2.039913935 | 12 / 12 |
| 0.20 | 0 | 2386.249222212 | 2384.273754670 | 1.976768763 | 15 / 15 |
| 0.05 | 1 | 402.866517881 | 402.678955005 | 0.187741141 | 1 / 1 |
| 0.10 | 1 | 395.631424822 | 395.461103596 | 0.170487554 | 2 / 2 |
| 0.20 | 1 | 382.048214527 | 381.892696173 | 0.155648222 | 3 / 3 |

Repeat runs produced identical JSON metrics. Strict and native inputs are valid polygonal sets; tested topology counts agree at each distance. This removes the alarming 23.17 mm² invalid-ring effect as a meaningful indicator of actual copper mismatch, but does not erase real measured differences between the two current source representations. Offset collapse of narrow cut-ins/voids still changes component counts; that is a geometry sensitivity warning. These buffers use GEOS round joins (`quad_segs=32`) and are diagnostic morphology, not cutter-radius compensation or actual V-bit isolation.

## 6. Canonical geometry contract and safety state

The draft shared contract is documented at [`CANONICAL_PCB_GEOMETRY_CONTRACT.md`](CANONICAL_PCB_GEOMETRY_CONTRACT.md), with a Draft 2020-12 JSON Schema and deterministic content-hash/status guard in `phase2j/`. It specifies exact file/command provenance, mm board frame, explicit side transforms, analytic line/arc retention, copper material with holes/islands, drill/slot original diameters, distinct source/derived/candidate roles, independent validation/manufacturing statuses, recovery evidence, approximation bounds, and reproducible hashes. Bottom mirroring is forbidden implicitly, and snapping is forbidden. Design transfer is structured JSON, not DXF; no Design receiver or `.dxd` writer was created.

### Existing inspection preview guidance

For the exact Valentine bottom source hash above, the preview now labels the two old invalid-intermediate-ring warnings **HANDLED · strict cut-in interpretation**. It states that valid source-aware material reconstruction preserves 103/14 voids and that no generic repair is needed. Each is paired with a separate **NEEDS VERIFICATION · bottom copper** saved-fill comparison issue containing the measured area difference, symmetric difference, boundary distance, source lines, and fill ID. Because the revision/fill state is not authenticated, it draws no localized defect marker and keeps the affected isolation operation blocked. Valentine’s 119 exact zero-length commands remain a separate HANDLED formatting finding. Other sources retain their previous generic repair warning behavior. Laser keeps its 182 open-region findings, the 181 display-only proposals, and blocked region 79.

## 7. Acceptance status and remaining blockers

| Criterion | Assessment | Evidence / unresolved work |
|---|---|---|
| Immutable native/Gerber identities and provenance recorded | **PASS** | SHA-256 and member hashes; originals read-only. |
| Native project represents exact Gerber revision | **PARTIAL** | Matching exporter version, UUID consistency internal to project, timestamp proximity, bounds, and via anchors; no cryptographic export/revision link, no saved-fill export history. |
| Shared native/Gerber board frame | **PASS for tested anchors and bounds** | Identity transform; 12 vias and outline bounds. No automatic mirror. |
| Full pad geometry and all holes compared to native | **NOT VERIFIED** | Only VIA anchors and their PTH duplicates were matched. Full footprint/pad-shape and all native hole inventories remain. |
| Board outline topology and internal cutouts compared | **NOT VERIFIED** | Bounds agree; full native outline curve/material comparison not built. |
| Strict cut-in reconstruction preserves valid material and holes without GEOS repair | **PASS for two source-specific regions** | Valid geometry, 103/14 voids, 117 cut-ins preserved, 119 exact no-ops handled. |
| Strict material agrees with native saved fill at ≤0.005 mm / no unexplained material discrepancy | **FAIL / unresolved** | Region 0 Hausdorff 0.005050711 mm and 2.202307531 mm² symmetric difference; region 1 0.210049321 mm² symmetric difference. Region 0 exceeds target slightly. Native saved fill source-version semantics/cache freshness not authenticated. |
| Old 23.174808194 mm² invalid raw-buffer warning interpreted | **PASS as an invalid-representation artifact** | Correct material model removes that anomaly; valid-vs-valid comparisons remain nonzero. |
| Strict/native diagnostic offset stability | **PASS for repeatability only** | Deterministic; same component counts at tested offsets. Nonzero material differences and topology changes remain; no manufacturing use. |
| Existing Laser blockers preserved | **PASS** | 182 open regions, 181 candidates display-only, region 79 blocked; no eligibility-policy changes. |
| Manufacturing eligibility | **BLOCKED** | No manufacturing approval granted. |

## 8. Tests and reproduction

Local environment: Python 3.12.14, Gerbonara 1.6.3, Shapely 2.2.0, GEOS 3.14.1, Matplotlib 3.11.2. Package provenance/licenses are inherited from `phase2a/DEPENDENCIES.md`. The source project is not installed into the environment. Gerbonara emits its known Excellon warning that G90 follows the header for these extracted byte streams; drilling anchors still parse and match. That warning remains visible.

Commands:

```powershell
& .\phase2g\.venv\Scripts\python.exe phase2j\verify_valentine_native.py
& .\phase2g\.venv\Scripts\python.exe -m unittest phase2j.test_phase2j -v
.\phase2i\run_regressions.ps1
```

The complete Phase 2A–2I regression command passed: **88 tests across eight suites**. Phase 2J tests passed: **8 tests**. The Phase 2J tests cover safe project reading and hashes, revision/version identity, native units/arcs, strict cut-in material/topology, deterministic valid-geometry offsets, canonical serialization/hash/status guards, existing Laser-blocker preservation, and source-specific native comparison where local inputs are provisioned. Python compile checks passed for the Phase 2J modules and JSON Schema syntax parsed. The project-local runtime does not contain `jsonschema`, so Draft 2020-12 meta-schema validation did not run. Local raw comparison JSON/PNGs remain ignored and untracked.

## 9. Decision and next evidence

The two legacy GEOS warnings can be reclassified to **resolved for strict cut-in conversion validity**. They cannot be reclassified to “native copper equivalence verified.” The strict reconstruction is the correct source-aware replacement for the old invalid-ring offset input, while both reconstructed regions remain **BLOCKED for manufacturing geometry** due measurable native-fill differences and incomplete source revision authentication.

To resolve the remaining comparison, obtain an immutable export log/project history entry tying the Gerber archive to the project save, and a source-version EasyEDA Pro export or supported API for the saved copper-fill paths. Compare the current saved fill with both a fresh export and a separately controlled repour in duplicate project copies. Also decode and compare all footprint pad geometry, native plated/non-plated holes and complete outline curves. Until those checks reconcile the current difference, do not approve these boundaries for isolation planning.

**Phase 2J stops here.** Physical/owner acceptance is required before further development. Phase 2F Laser findings remain unchanged: all 182 open regions flagged, 181 candidates display-only, region 79 blocked.
