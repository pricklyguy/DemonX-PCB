# Phase 2D region forensics

Run from repository root: `./phase2d/run_forensics.ps1`.

This uses the existing project-local environments and adds no dependency. `forensics.py` scans original commands in the observed absolute X4.5 mm linear subset to retain exact integer source coordinates and command lines. It is an evidence scanner, not a new independent Gerber parser. Gerbonara and PyGerber are the two independent parser implementations compared with it.

`region_geometry_ticks` is the strict replacement behavior demonstrated for region conversion: reject open or illegal contours; preserve legal horizontal/vertical cut-ins using validated closed faces and source winding; union separately filled D02 contours. It returns geometry in source ticks (0.00001 mm). It never snaps, closes, buffers, removes no-ops, or calls `make_valid`. Unsupported curved contours are rejected by the scanner, not flattened. This is a scoped verification adapter, not a general Gerber conformance implementation or application engine.

The separate `diagnosticZeroLengthOmission` experiment explicitly omits 119 zero-length commands from two Valentine rings, solely to test whether their cut-in topology explains the old repairs. Source data and source acceptance are unchanged; this diagnostic geometry is not approved for manufacturing. `make_valid` is called only on the historical comparator, never on accepted geometry.

`results/region-evidence.json` records every affected region's hash, command range, raw D01/D02 operations, exact tick coordinates, rational intersection positions, closure deltas, library representations, and status. Original source commands are copied verbatim into the two `*-source-regions.txt` files with region/range separators. `summary.json` supplies blocked region IDs, archive identity checks, versions and aggregate patterns.

The synthetic `.gbr` files are locally authored regression fixtures, not official Ucamco-certified conformance files. Tests regenerate those fixtures and exercise strict conversion and parser behavior. Prior Phase 2A/2C regressions check drill counts, source hashes and recorded copper metrics; they do not regenerate all four prior full-board boolean compositions. Only the two affected Valentine region comparator geometries are recomputed in this phase. GerbView manual review has not been performed.
