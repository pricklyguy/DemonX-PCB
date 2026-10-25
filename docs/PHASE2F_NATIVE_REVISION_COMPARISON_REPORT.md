# Phase 2F — Laser Module Native Revision Comparison

**Status:** Investigation complete; manufacturing approval remains blocked.  
**Branch:** `codex/pcb-prep-phase-2a`  
**Scope:** Read-only comparison of the recovered EasyEDA Standard v2.0 native PCB, its fresh 2026-10-25 Gerber export, and the supplied v2.5 Gerber archive. No source archive or native project was modified. No geometry-acceptance rule was changed.

## Executive assessment

The EasyEDA Standard 6.5.51 / Gerber Generator 0.2 exporter behavior was reproduced: the fresh v2.0 bottom-copper export contains the same 182 open G36/G37 region command sequences as the v2.5 archive, byte-for-byte at the region-command and coordinate-record level. Both exports have the same 183 circular drill hits and eight routed slots, and equivalent top and bottom copper primitive geometry after accounting for command ordering and aperture declarations. This is strong evidence that the open-contour behavior is reproducible for these exports. It does **not** make the files conforming or prove that every closing edge describes intended copper.

The v2.0 PCB's cached copper-fill data independently supports the proposed straight closing edge for each of the 182 contours: every candidate edge maps one-to-one to a unique cached-fill path and stays within 0.005 mm of that path. Full candidate-ring comparison is more nuanced: 181 of 182 rings are within 0.005 mm boundary Hausdorff distance of their mapped cached fill. Region 79 is a material outlier (0.284123 mm boundary displacement and 3.540171 mm² symmetric difference). Its contour's closing edge itself matches the native fill, but the rest of the candidate ring does not. The cached fill may be stale or may represent a different design revision or pour state; this comparison cannot decide which.

Therefore, **do not promote a blanket closure rule**. All 182 region recoveries remain unapproved under Phase 2E's controlled-recovery policy; copper-dependent manufacturing remains blocked wherever the open region or region 79 ambiguity affects the operation. This phase does not establish manufacturing readiness.

## Inputs, provenance, and hashes

Originals were preserved. The v2.0 export and PCB JSON were copied into the repository for reproducibility; their staged hashes equal the received originals. The v2.5 archive remains in `gerbers/`.

| Input | SHA-256 | Bytes / identity |
|---|---|---|
| Fresh v2.0 export ZIP | `d17abf51ea793d7151f7cb452db5bc97a0a1a2d1f1859414c1b37a13c884e1c8` | 192,172 |
| Recovered v2.0 native PCB JSON | `8e16382c5dc9b546e43ed96562e6e58124069c2bac80ba7529d80c19907e3cd9` | 1,000,352; editorVersion 6.5.51 |
| v2.5 Gerber ZIP | `5e682b600dd19ee798d11830f0867f8cd686853d6a05620b8af174ba9ed3eb33` | 192,206 |
| v2.5 bottom copper GBL | `6a6e08f4bf30852202e56e76d6ec43f50bcf564f33ef184e35afa71f4118359c` | member of v2.5 ZIP |

The two export headers identify EasyEDA 6.5.51 / Gerber Generator 0.2 and contain the same two opaque G04 identifiers. Those identifiers are treated only as matching labels; no documented revision semantics were found or assumed. Identical exporter metadata and geometry strongly connect these exports, but **v2.5 native revision identity is not proven**. The machine-readable manifest records hashes for every staged v2.0 manufacturing member and records that external originals were not modified: [source-manifest.json](../phase2f/results/source-manifest.json).

ZIP extraction was limited to the five expected manufacturing members, with traversal, file type, member count/size and destination checks. No unexpected archive member was extracted into the fixture directory. The comparison can be regenerated with [run_phase2f.ps1](../phase2f/run_phase2f.ps1); implementation and full results are in [compare_revision.py](../phase2f/compare_revision.py) and [revision-comparison.json](../phase2f/results/revision-comparison.json).

## Source-command comparison

### Bottom copper region correspondence

Both bottom copper files contain 182 region contours. All 182 have identical source command sequences and coordinate sequences in source order; their G36/G37 command ranges match. Polarity counts also match: one dark (`D`) region and 181 clear (`C`) regions. Every contour is still open. The measured start-to-end closure displacement ranges from **0.01455039862 mm** to **81.40141 mm**. The fresh export therefore reproduces the Phase 2E behavior, but exact closure is still required by Gerber region semantics; a repeatable exporter defect is not a conformity waiver.

### Copper primitives, order, and apertures

PyGerber 2.4.3 was used as a parsed-command comparison tool, not as an independent oracle. Top copper has 191 equivalent geometry descriptors. Bottom copper has 627 equivalent descriptors (182 regions, 254 line primitives, 191 flashes); primitive ordering can vary within equivalent polarity runs. Ordered polarity-run geometry multisets are equivalent across the two exports. Thus the body-level textual mismatch in bottom copper is not interpreted as changed geometry.

Some aperture definitions changed or were renumbered between exports. For example, the bottom-layer aperture codes 11, 13, 16 and 17 have different definitions/assignments, and profile aperture 11 differs (`0.0159` vs `0.0110` mm). The corresponding parsed emitted primitive geometry remains equivalent. These declaration differences are recorded rather than normalized away. Top copper has two differing aperture-code definitions. The detailed per-file declaration and primitive comparisons are in `revision-comparison.json`.

The two drill bodies are geometrically identical after ignoring comment/header text: 183 circular hits plus eight routed slots. The outline command rows are also identical after disregarding comments and aperture declarations. Thus the reported possible fuse-location change is not visible in generated copper, profile, or drill geometry; it could still concern nonmanufacturing metadata, but cannot be confirmed without the v2.5 native PCB.

## Board coordinate frame and outline

The v2.0 native outline is a rectangle corresponding to the Gerber profile bounds. Gerber source-coordinate bounds are **[10.99797, 1.77800, 127.45674, 85.21682] mm**, giving **116.45877 × 83.43882 mm**. The export contains one profile stroke and no inner profile cutout.

The native-to-Gerber transform was solved from the four corresponding outline vertices:

```text
Xgerber_mm =  0.254 × Xnative − 1021.0800021
Ygerber_mm = −0.254 × Ynative + 858.0119989
```

The fitted residual is **0.0000011 mm**. The negative Y scale accounts for the native canvas Y-down convention. Top and bottom source coordinates were compared in the same board frame; **no bottom-side manufacturing mirror was applied**. The Gerber image attributes specify no rotation or reflection. This establishes frame registration for the source files; it does not prescribe a future machine-side transform.

## Cached native copper-fill comparison

The recovered v2.0 PCB JSON contains 182 cached copper-fill paths. For each open region, a separately labelled candidate straight edge from source end to source start was compared with cached native fill linework in the registered coordinate frame. No candidate was promoted into source geometry.

| Measurement | Result |
|---|---:|
| Candidate edges fully within 0.005 mm of cached-fill linework | 182 / 182 |
| One-to-one mapping to distinct cached-fill paths | 182 / 182 |
| Candidate edges matching one native segment within 0.0001 mm | 4 / 182 |
| Maximum sampled edge deviation | 0.000312590 mm |
| Conservative maximum deviation bound | 0.000810797 mm |
| Full rings within 0.005 mm boundary Hausdorff | 181 / 182 |
| Median full-ring boundary Hausdorff | 0.000270488 mm |

The edge test samples each proposed segment at at most approximately 0.001 mm spacing and uses the 1-Lipschitz distance bound to account conservatively for unsampled locations. The fact that only four edges match one individual native segment is consistent with the native path representing some straight boundaries as multiple pieces; the broader unique-path linework comparison is the relevant coverage measurement.

### Region 79 outlier

| Property | Candidate ring | Native cached fill path |
|---|---:|---:|
| Source range / path | Gerber lines 4845–5637 | native fill path index 3 |
| Candidate closing-edge length | 0.145424747 mm | — |
| Area | 306.737089685 mm² | 309.788283189 mm² |
| Interior rings | 0 | 0 |

The ring symmetric-difference area is **3.540171130 mm²** and boundary Hausdorff distance is **0.284123325 mm**. Both polygons are individually valid; validity does not resolve which copper geometry is intended. While the candidate closing edge maps to the cached fill within tolerance, the complete region does not. A diagnostic overlay is available at [region-079-native-vs-candidate.png](../phase2f/results/region-079-native-vs-candidate.png).

For the other 181 rings, the maximum boundary Hausdorff distance is approximately **0.001488762 mm**. Median per-ring symmetric difference is **0.000239986 mm²**. The sum of per-ring symmetric differences is 3.864886279 mm², but rings overlap, so this sum is **not** a whole-board copper difference and must not be interpreted as one. Cached fill is useful design-intent evidence, but it is neither a newly regenerated Gerber nor an independent CAM interpretation.

## Drills, slots, and component revision evidence

The v2.0 export has **183 circular plated drill hits** and **8 routed plated slots**. The native PCB contains **191 through-hole pads**: 183 circular plus eight slotted. Every circular drill matches a unique native pad for both v2.0 and v2.5 exports. Maximum registered center residual is **0.0005811 mm**; maximum diameter residual is **0.0009888 mm**. All eight slot midpoints match unique native slot pads; maximum endpoint residual is **0.000212981 mm**, and maximum total-length residual is **0.001131 mm**. The normalized hit and slot records from the two Gerber exports are identical.

The EasyEDA PCB format's through-hole pad field used here denotes **hole radius**; the comparison converts radius to diameter when matching the Gerber drill. Slots are compared as routed geometry, not collapsed into circular hits. See the [EasyEDA Standard PCB file format](https://docs.easyeda.com/en/DocumentFormat/3-EasyEDA-PCB-File-Format/index.html), [PCB tools documentation](https://docs.easyeda.com/en/PCB/PCB-Tools/), and [PCB file object documentation](https://docs.easyeda.com/en/DocumentFormat/5-EasyEDA-PCB-File-Object/).

The v2.0 native board lists F2 and F3 as MINI FUSE HOLDER SL-506P at registered origins **(118.7449979, 22.0979989) mm** and **(28.5749979, 81.1529989) mm**. Since the v2.0/v2.5 copper and drill export geometry is the same, a fuse change did not alter those manufacturing layers in these exports. The v2.5 native project was not supplied, so the v2.5 fuse reference/location and nonmanufacturing revision changes remain unverified.

## Confidence and acceptance status

| Claim | Assessment | Basis / limit |
|---|---|---|
| Same 182 bottom-region command sequences in v2.0 and v2.5 exports | **High confidence** | Exact command and coordinate sequence comparison. |
| Open-contour behavior reproducible with this exporter/version | **High confidence for these two exports** | Fresh v2.0 export produced identical region sequences. Does not generalize to every EasyEDA export. |
| Top/bottom copper and drill/profile output geometry unchanged between the two exports | **High confidence at parsed primitive/body level** | PyGerber command AST, polarity-run and command-body comparisons; not an independent Gerber renderer. |
| Candidate closure boundary corresponds to v2.0 cached fill | **High confidence as a geometric correspondence** | 182/182 unique path mappings within 0.005 mm. Cached fill provenance/freshness is not independently attested. |
| Full intended copper proven for all candidate rings | **Not established** | Region 79 is a large mismatch; cached pour may not correspond to exported source revision/state. |
| v2.5 native revision and fuse placement verified | **Not established** | No v2.5 native board file. Matching opaque header tokens are not revision proof. |
| Gerbers conforming / manufacturing ready | **No** | All 182 G36/G37 contours remain open and unapproved; region-specific intent remains unresolved. |

No unrestricted geometry repair, snapping, or source rewrite was performed. No closure acceptance rules or Phase 2E eligibility records were changed. Existing unresolved-region diagnostics are preserved.

## Regression and execution results

Ran from the repository root:

```powershell
.\phase2f\run_phase2f.ps1
```

**Result: 25 tests passed** (16 Phase 2E recovery tests and 9 Phase 2F revision tests). Tests cover source hashes and safe extraction, all 182 exact region sequences, top/bottom primitive and polarity-run equivalence, drill/slot/native-pad correspondence, outline transform, native path mapping without approval, region 79 mismatch preservation, and v2.5-native identity limitations. PyGerber emitted PyParsing `oneOf` deprecation warnings; no test failed. Full captured output: [test-phase2f.txt](../phase2f/results/test-phase2f.txt).

## Limits and next evidence needed

The supplied visual screenshots were not found as accessible image attachments in the local attachment directory, so no screenshot-based comparison is claimed. No independent current v2.5 native project was found. The tests establish agreement against the v2.0 cached fill and between two exports; they do not constitute an independent manufacturing geometry oracle. Region 79 needs source-authoritative resolution, for example a verified v2.5 native PCB and matching revision metadata, or a controlled repour/re-export from the v2.0 PCB with revision provenance and direct copper geometry comparison. Until then, retain region-level warnings and keep affected copper machining blocked. Even a future match to the v2.0 source should not waive Gerber conformance validation globally.

## Working-tree note

The work remained on `codex/pcb-prep-phase-2a`. Existing untracked directories and prior phase files were preserved. No commit, push, merge, branch reset, third-party repository modification, global dependency installation, manufacturing toolpath work, UI, or DemonX integration was performed.
