# Phase 2C verification harness

This is an audit harness, not production PCB Prep code. It independently composes the four copper layers from PyGerber 2.4.3 command objects, compares those compositions with the retained Phase 2A Gerbonara/Shapely results, measures profile centerlines, records source/drill reconciliation, analyzes the Delta arc bounds, and emits diagnostics and previews.

## Reproducible local run

The harness reuses only the existing project-local environments: Python 3.12.14, Shapely 2.2.0/GEOS 3.14.1 and Matplotlib 3.11.2 from `phase2a/.venv`; PyGerber 2.4.3 from `phase2b/.venv`. Gerbonara 1.6.3 is used only for the Phase 2A comparison output. No global dependencies are installed. Exact direct package versions are listed in `requirements.txt`; the underlying complete locks remain in `phase2a/requirements.lock` and `phase2b/requirements.lock`.

From the repository root, run:

```powershell
.\phase2c\run_verification.ps1
```

The script regenerates the machine-readable comparison reports, full-size difference overlays, PyGerber SVG renders, and then runs the regression tests. Full copper composition can take several minutes because the Laser bottom pour contains 182 regions.

## Evidence and licensing

The independent geometry side is built from PyGerber's parsed command model; Gerbonara's primitives do not construct it. Both comparisons use Shapely/GEOS, so shared overlay-kernel behavior is a known limitation. The harness includes analytic arc extrema, analytic geometry unit tests, ordered-polarity tests, source-hash baselines, and PyGerber's separate SVG renderer as additional checks.

PyGerber is MIT-licensed; its pinned package and source provenance are recorded in Phase 2B. Shapely is BSD-licensed and GEOS is LGPL-2.1-or-later; provenance and the exact Phase 2A pin are recorded in `phase2a/DEPENDENCIES.md`. Gerbonara license/provenance is also recorded there. Phase 2C adds no third-party dependency.

Original archive SHA-256 values are in `results/environment.json`. Per-layer source hashes, object provenance, metrics, and all warnings are in `results/copper-comparison.json`; all source drill records and the deduplication candidates are represented in `results/drill-reconciliation.json` and Phase 2A's preserved `parsed_geometry.json`.
