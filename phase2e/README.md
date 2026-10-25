# Phase 2E controlled source recovery

Run from the repository root:

```powershell
.\phase2e\run_recovery.ps1
```

This uses the existing Phase 2A/2B local Python environments and adds no dependency. The runner regenerates Phase 2E records, source-specific fixtures and diagnostic overlays, reruns the Phase 2A–2E suites, and verifies hashes of prior phase files. It writes only Phase 2E outputs; the existing Phase 2D tests regenerate identical synthetic fixture bytes.

## Scope and policy

`VALID` means the region geometry passes the declared linear source-validation subset. `RECOVERABLE` means a recorded, exact, non-material normalization yields valid geometry. `BLOCKED` means intended geometry is unproven or the construct is unsupported. None of these statuses alone certifies a complete manufacturing job.

The run explicitly enables `pcbprep.exact-zero-length-region-draw.v1`. It omits only G01/D01 region segments whose original integer start and end coordinates are exactly equal. It preserves all source commands, logs every source line, retains original file hashes, and constructs cut-in holes with the Phase 2D strict converter. Original source conformance remains false under revision 2026.05. The derived geometry can proceed to geometry preparation with its warning. Zero-length draws outside regions are never removed: they have an aperture image.

Open contours receive separate closing-edge candidates, not accepted manufacturing polygons. All 182 Laser candidates remain BLOCKED even though their polygons are valid and their new edges do not cross the existing boundary. No real manual acceptance was supplied or recorded. The tested exception function binds an informed risk acknowledgement to source and candidate hashes while retaining BLOCKED validation status and unresolved risk.

## Outputs

- `results/validation-records.json`: original paths and commands, exact displacement, source ranges, all proposed changes, candidate geometry, edge intersections, confidence, eligibility and required action for all 184 issue regions.
- `schema/source-validation-record.schema.json`: draft record contract for future warning/overlay consumers; no GUI or integration is implemented.
- `results/independent-reproduction.json`: separate source-scanner, Gerbonara-outline and PyGerber-command reproduction of the counts.
- `results/copper-remeasurement.json`: fresh measurements of four layers. Laser bottom is explicitly the unapproved all-closures scenario.
- `results/overlays/laser-region-000.svg` through `laser-region-181.svg`: original path in blue and proposed edge in red. `selected-laser-candidates.png` provides dimensioned examples.
- `fixtures/valentine-region-*.original.gbr` and `*.recovered.gbr`: source-specific original/candidate regression fixtures. Original production sources are untouched.
- `results/archive-project-provenance.json` and `native-project-evidence-requirements.json`: archive inventory and the evidence needed for later EasyEDA revision/intent comparison. No project access was requested.
- `results/manufacturing-eligibility.json`: operation-scoped source-region results, separate from tooling/setup readiness.
- `results/test-*.txt` and `preservation.json`: test logs and prior-file hash comparison.

## Numerical interpretation

An open source contour has no specified filled interior, so its source-to-candidate area/topology difference is null, not zero. Each record instead gives its candidate polygon metrics and a clearly labeled marginal scenario: assume all other closures, omit this one region, then include it in the final ordered dark/clear composition. This measures sensitivity to the proposed fill without asserting that it is intended copper. The candidates' effects must not be added together as independent material changes because regions overlap and later dark artwork can restore material.

The implementation is restricted to the observed absolute X4.5 mm, G01 region subset. Curved region commands and ambiguous geometry are blocked. The exact source scanner is not an independent Gerber implementation; Gerbonara and PyGerber are the independent parsers. Shapely/GEOS remains a shared numerical dependency. No unrestricted `make_valid`, snapping, tolerance closure, toolpath, or native Design import is used by controlled recovery.
