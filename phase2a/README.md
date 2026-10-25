# Phase 2A local verification environment

This directory contains a disposable, project-local Python verification environment, safely extracted manufacturing fixtures, the parser/geometry inventory harness, results, previews, tests, and draft interchange schema. The two source ZIP archives remain unchanged in `../gerbers/`.

## Recreate the environment

Use 64-bit CPython 3.12.14 for the recorded baseline. From the repository root:

```powershell
py -3.12 -m venv phase2a/.venv
phase2a/.venv/Scripts/python.exe -m pip install -r phase2a/requirements.lock
```

The lock file captures exact resolved versions from this Windows x64 run. `requirements.txt` lists the direct verification dependencies. GEOS is bundled in the Shapely wheel and was measured at runtime as 3.14.1. This lock is version-pinned but does not yet include per-wheel hashes or a signed supply-chain attestation; see `DEPENDENCIES.md`.

## Re-run extraction and inventory

```powershell
phase2a/.venv/Scripts/python.exe phase2a/extract_fixtures.py
phase2a/.venv/Scripts/python.exe phase2a/verify_fixtures.py
phase2a/.venv/Scripts/python.exe -m pytest phase2a/test_verification.py -q
```

The extractor rejects absolute/traversal paths, backslash paths, links, duplicate/case-colliding names, oversized members/archives, and excessive compression ratios. It extracts content-identified Gerber and Excellon manufacturing files only. It does not delete or clean the destination; an existing file with different bytes fails closed.

Results are parser-derived. Neither visual rendering nor the same parser's alternate output is independent evidence of correctness. The archive-wide manifest is `fixture_inventory.json`; parsed feature-level reports are under `results/`.
