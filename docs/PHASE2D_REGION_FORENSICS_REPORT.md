# DemonX PCB Prep — Phase 2D Source-Region Forensics

Date: 2026-10-25. Branch: `codex/pcb-prep-phase-2a`.

**Forensics completed; manufacturing acceptance remains blocked for 184 source regions.** Valentine is not a case of crossing copper boundaries: its two contours encode 117 legitimate horizontal cut-ins, alongside 119 prohibited zero-length D01 segments. Treating the entire cut-in ring as an ordinary Shapely polygon caused a misleading self-intersection diagnosis. Laser's 182 contours really are open in the original Gerber. Both parsers retain those source endpoints; Gerbonara adds a closing edge later in its graphics-primitive conversion. No manufacturing geometry was repaired or accepted from these invalid source contours.

This report refines the Phase 2C diagnosis. It preserves all Phase 1/2A/2B/2C reports and artifacts as historical evidence. No original archive, extracted source file, prior converter, or other DemonX repository was edited. The pre-existing `.gitignore` modification and untracked work remain present. No branch reset, push, merge, dependency installation, GUI, integration, or toolpath work was performed.

## Authority and method

The authority is Ucamco's [Gerber Layer Format Specification, revision 2026.05, section 4.10.3](https://www.ucamco.com/files/downloads/file_en/554/gerber-layer-format-specification-revision-2026-05_en.pdf?eac6410808ad1d0b3f977429ddaab7d0=). A contour must end exactly where it starts. Legal cut-ins join a hole contour to its surrounding contour with two fully coincident, oppositely traversed horizontal or vertical segments; all cut-ins in a contour use the same axis. Zero-length contour draws, partial overlaps, diagonal retraces, and other self-crossings/touches are prohibited. G37 ends the region statement; it does not specify an additional geometric segment. Separate D02 contours are individually filled and their areas combined.

The new [`phase2d/forensics.py`](../phase2d/forensics.py) is a narrow source-command evidence scanner for the observed absolute X4.5 mm, linear subset. It is **not** a new independent reference parser. It reads original integer coordinates, retaining a 0.00001 mm tick before float conversion. Segment-intersection predicates and locations use integer/rational arithmetic. STRtree only narrows bounding-box candidates; integer coordinates in these datasets are exactly representable in that broad-phase index. Each region is then compared with Gerbonara 1.6.3 and PyGerber 2.4.3 independently. Both libraries preserve every explicit region segment's coordinates with zero measured delta at the emitted decimal precision.

The runtime is Python 3.12.14, Shapely 2.2.0, and the existing project-local environments from Phases 2A/2B. No new dependencies were introduced. The scanner rejects unhandled region commands and curved region interpolation rather than silently approximating them. Every affected real contour uses G01 linear interpolation and one D02 start.

## Source identity and complete evidence

Both bottom-copper files exactly match the corresponding bytes in the original ZIP members; archive hashes still match Phase 2A/2C.

| Board | `Gerber_BottomLayer.GBL` SHA-256 | Regions |
|---|---|---:|
| Valentine | `f701e7ada043321c89a2c3baf73a84c32a3aad93cc3259bd9eff07bbd8e47843` | 2 |
| Laser Module | `6a6e08f4bf30852202e56e76d6ec43f50bcf564f33ef184e35afa71f4118359c` | 182 |

[`region-evidence.json`](../phase2d/results/region-evidence.json) contains **every** affected region's source hash, G36/G37 line range, verbatim D01/D02 command text, exact coordinate sequence, interpolation modes, original start/end, closure delta, intersection locations and segment indices, Gerbonara outline/primitive representation, PyGerber command representation, and acceptance status. Segment ordinals are zero-based; source line numbers are one-based. Intersection coordinates are stored in exact source ticks, including rational values where needed. The complete verbatim region commands are also preserved in:

- [Valentine region excerpts](../phase2d/results/gerber-pcb-valentine-feb-new-source-regions.txt)
- [Laser Module region excerpts](../phase2d/results/gerber-prickly-laser-module-2-5-source-regions.txt)

[`summary.json`](../phase2d/results/summary.json) records archive identity checks, versions, gap patterns, and all blocked region IDs. Original command geometry remains addressable even when no accepted manufacturing polygon exists.

## Valentine: cut-ins plus zero-length source commands

| Region index | G36–G37 source lines | Explicit D01 segments | Start and end (mm) | Exact closure delta | Horizontal cut-in pairs | Zero-length D01 commands |
|---:|---|---:|---|---|---:|---:|
| 0 | 34–5714 | 5678 | (2.34578, 66.17442) | (0, 0) ticks | 103 | 105 |
| 1 | 5715–6302 | 585 | (8.18493, 67.18602) | (0, 0) ticks | 14 | 14 |

Both source contours are exactly closed. The exact intersection audit finds **no crossing edges, diagonal return pairs, or partially overlapping edges**. Non-adjacent endpoint encounters occur at cut-ins and duplicated zero-length operations. All 117 return pairs are fully coincident and horizontal. Gerbonara's original outlines and primitive segments and PyGerber's region command buffers preserve the source segment counts and coordinates.

For example, region 0 has these original consecutive commands at lines 302–304:

```gerber
G01X1057643Y4840541D01*
G01X1057643Y4840541D01*
G01X1045528Y4851104D01*
```

The second command is a source D01 from (10.57643, 48.40541) mm to the same point. It is not an endpoint duplicated by either parser. Region 1 has the same pattern, including the zero-length draw at line 5768. The JSON evidence enumerates all 119 such source commands.

### Root cause and controlled geometry experiment

An ordinary OGC/Shapely Polygon ring cannot directly represent a Gerber cut-in: the fully coincident bridge is an allowed Gerber construction but a non-simple polygon ring. Therefore an OGC validity failure alone does not establish that a Gerber cut-in is invalid. Phase 2C's broad self-intersection label conflated those two models.

The actual source conformance defect is the 119 zero-length D01 segments. These are prohibited even though they have no swept length or area. Strict conversion rejects both source regions and preserves their commands; it does not silently remove those operations.

A separately labeled diagnostic experiment explicitly omits only the zero-length draws and validates the remaining contour topology. The converter recognizes the horizontal reverse pairs, verifies the remaining loops and source winding, and constructs the material with its holes. It uses no `make_valid`, buffer, snap, or invented closing edge. The experimental polygons are **not approved for manufacturing** and do not replace source data.

| Region | Diagnostic area (mm²) | Retained holes | Symmetric difference against actual Phase 2A `primitive_to_geometry` + `make_valid` comparator (mm²) | Boundary Hausdorff (mm) |
|---:|---:|---:|---:|---:|
| 0 | 2721.05448472005 | 103 | 8.1051511e-12 | 2.0097183e-14 |
| 1 | 410.99482327840 | 14 | 5.7501981e-13 | 1.4648214e-14 |

These comparisons recompute the historical comparator in millimetres; they are not a comparison with a second output from the same source scanner. They establish that the old repaired **material** corresponds to the intended cut-in construction after the explicit no-op omission. They do not approve that omission or the old automatic repair policy. No valid copper or hole was added or removed by the new accepted path, since the original invalid regions produce no accepted manufacturing geometry.

**Disposition:** topology understood; source conformance still fails on 2 regions. Source regeneration without the redundant D01 operations, or an explicit reviewed source correction with new hashes, is required before acceptance. A fabrication owner need not redraw crossing boundaries: none were found.

## Laser Module: 182 genuinely open source contours

All 182 G36/G37 statements contain one contour and end at a point different from their D02 start. The gaps are exact source-coordinate differences, not results of polygonization or floating-point rounding. No final source D01 returns to the start.

| Example region | G36–G37 lines | Source start (mm) | Source end (mm) | Exact end minus start (mm) |
|---:|---|---|---|---|
| 0 | 32–63 | (45.69460, 2.03708) | (127.09601, 2.03708) | (+81.40141, 0) |
| 118, shortest gap | 7035–7046 | (13.93545, 64.94881) | (13.94155, 64.96202) | (+0.00610, +0.01321) |
| 181 | 8251–8261 | (105.18851, 79.45424) | (105.18851, 79.90433) | (0, +0.45009) |

Region 0 ends with these original commands:

```gerber
X12716814Y206705D01*
X12713512Y204470D01*
X12709601Y203708D01*
G37*
```

Its D02 start is `X4569460Y203708D02*`. There is no source instruction for the 81.40141 mm closing side. Across the file, the missing endpoint connections would be 1 horizontal, 69 vertical, and 112 diagonal. Euclidean gap lengths range from approximately **0.01455039862 mm to 81.40141 mm**, much larger than the 0.00001 mm coordinate tick. All exact delta vectors, command ranges, and source endpoints are recorded individually. The explicit open paths have no crossing/overlap defects in the exact segment audit.

### Parser and conversion behavior

Gerbonara's `Region.outline` retains the original first and last points. Its subsequent `ArcPoly.segments` conversion adds **one final segment from the last source point to the first** for each of the 182 regions. PyGerber retains exactly the explicit source D01 segments in its Region2 buffer and does not add that segment there. Thus Gerbonara has N+1 graphics-primitive segments and PyGerber N command segments for each source contour with N explicit segments. The N explicit segments agree exactly between the original commands and both libraries.

Phase 2C's Shapely `Polygon(points)` construction also implicitly closed PyGerber's open chain. That explains why the two prior filled silhouettes agreed numerically: both ultimately used a closing edge absent from the source. It is agreement under an implicit-closure interpretation, not proof of source conformance. The earlier claim that the 182 contours are open is confirmed, with the additional finding that Gerbonara's primitive representation hides the open state unless the original outline is inspected.

**Disposition:** all 182 source regions remain blocked. No closing segment is inserted by the new strict adapter. The prior implicit-fill area is historical diagnostic evidence; there is no valid strict after-area or source-to-after symmetric difference to report. Corrected source commands or a separately reviewed source revision are required.

## Targeted conversion changes

The new `region_geometry_ticks` adapter in `phase2d/forensics.py` demonstrates the corrected interpretation boundary:

- It validates exact closure and source segment relationships before making polygons.
- It supports simple linear contours and validated horizontal/vertical cut-ins, including their holes, without using generic polygon repair.
- It fills each D02 contour independently and unions those regions, preserving islands and the distinction between a cut-in hole and overlapping separately filled contours.
- It rejects zero-length draws, true crossings, partial overlaps, diagonal retraces, mixed cut-in axes, unsupported touches, or retraced spurs without hole loops.
- It preserves all source records and exposes blocking diagnostics, with no fallback to implicit closure or `make_valid`.

This is a scoped audit adapter, not a full Gerber engine. The earlier Phase 2A/2C scripts and saved outputs were preserved; their automatic region repair/closure behavior must not be promoted into a manufacturing engine. No existing accepted whole-board geometry was rewritten.

Blocked diagnostics apply to the two Valentine and 182 Laser bottom-copper regions and any proposed operation that depends on their copper/clearance interpretation. They do not reject unrelated top copper or the drill inventory. In particular, Laser clear-polarity regions cannot simply be dropped from an operation: that would fill clearance areas with copper.

## Regression results and limitations

Reproduce from the repository root:

```powershell
.\phase2d\run_forensics.ps1
```

The full run completed successfully:

| Suite | Result | Evidence |
|---|---:|---|
| Phase 2D | 19 passed | [test-phase2d.txt](../phase2d/results/test-phase2d.txt) |
| Existing Phase 2A | 16 passed | [test-phase2a.txt](../phase2d/results/test-phase2a.txt) |
| Existing Phase 2C | 9 passed | [test-phase2c.txt](../phase2d/results/test-phase2c.txt) |

New locally authored `.gbr` fixtures cover simple regions, legal cut-ins, fully coincident returns, true crossing contours, open contours, one-tick closure gaps, zero-length commands, holes and islands, and separately filled D02 contours. Tests additionally cover modal axes/interpolation, separate G36/G37 statements, reversed contour orientation, diagonal/partial return rejection, and coincident spurs without hole loops. Gerbonara and PyGerber independently parse the synthetic cut-in and preserve its segments. These are regression fixtures, not official Ucamco-certified conformance files.

Real-board tests retain exact source hashes, all 182 Laser gaps, the two Valentine zero-length counts and cut-in inventories, parser agreement on explicit source segments, and the controlled material comparisons. Existing checks still reconcile **413 circular source records, 8 slots, 12 duplicate record pairs represented once physically, and 87 unassigned diameters**. Recorded copper counts and metrics pass the retained regressions. The four full-board boolean compositions were not regenerated during Phase 2D; no prior composition code or baseline file was modified. The affected Valentine comparator polygons were recomputed in this phase.

GerbView manual inspection was not performed. It was unnecessary to determine the exact source-command defects, but remains a possible additional visual corroboration. Official Ucamco conformance suites and general arc-region support were not exercised. The source scanner is not offered as an independent replacement parser.

## Manufacturing assessment

| Criterion | Assessment |
|---|---|
| Source-vs-parser origin of both reported problem categories identified | **PASS**: original commands and independent parser representations retained for all 184 regions. |
| Valentine cut-in topology distinguished from true crossings | **PASS**: 117 horizontal cut-ins; no true crossing or partial-overlap edges; 119 forbidden zero-length commands remain in source. |
| Laser source closure established | **FAIL source conformance**: 182 exact nonzero gaps; no missing endpoint was caused by parser coordinate loss. |
| Strict conversion accepts valid synthetic cut-ins without repair | **PASS** within the declared linear subset. |
| Invalid source regions preserved and operation scope blocked | **PASS**: all original commands retained; no accepted manufacturing polygons for affected regions. |
| Existing drill and recorded copper regressions | **PASS** with the recomputation limits stated above. |
| Valentine bottom manufacturing acceptance | **BLOCKED** pending approved removal/regeneration of zero-length source operations. |
| Laser bottom manufacturing acceptance | **BLOCKED** pending an explicit source revision defining the missing contour edges. |
| Manufacturing readiness / advancement | **NOT APPROVED**. No geometry edits or semantic fallback were silently applied. |

**Phase 2D stops here.** There are 184 source regions remaining unaccepted, with their root causes and exact records documented. Valentine no longer has unexplained material topology; Laser closure remains a source-authoring decision.
