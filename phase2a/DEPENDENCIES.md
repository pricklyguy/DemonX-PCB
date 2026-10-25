# Phase 2A dependency provenance and licensing

## Runtime baseline

Recorded from the isolated `phase2a/.venv` on Windows x64:

| Component | Exact version | Role | License/provenance |
|---|---:|---|---|
| CPython | 3.12.14 | Runtime | Python Software Foundation License; bundled Codex Python runtime used to create the venv |
| Gerbonara | 1.6.3 | Gerber and Excellon parser | Apache-2.0; [PyPI project](https://pypi.org/project/gerbonara/), [upstream source](https://gitlab.com/gerbolyze/gerbonara/), [documentation](https://gerbolyze.gitlab.io/gerbonara/) |
| Shapely | 2.2.0 | Python geometry operations | BSD-3-Clause; [PyPI project](https://pypi.org/project/shapely/), [upstream source](https://github.com/shapely/shapely) |
| GEOS | 3.14.1 | Shapely geometry engine bundled in wheel | LGPL-2.1; runtime version queried from Shapely |
| Matplotlib | 3.11.2 | Static verification plots only | Matplotlib license (PSF-compatible); [PyPI project](https://pypi.org/project/matplotlib/) |
| pytest | 9.1.1 | Verification tests | MIT; [PyPI project](https://pypi.org/project/pytest/) |

Exact top-level constraints are in `requirements.txt`; the exact resolved environment, including transitive packages, is in `requirements.lock`. `results/installed_packages.json` records installed distribution versions and available license/project URL metadata. Some transitive distributions omit normalized license metadata; that inventory does not replace a release-time license audit or notices bundle.

## Provenance limits

Packages were installed into the repository-local venv from the configured Python package index using pip. No global Python packages or system-wide geometry libraries were installed. The installed Gerbonara package reports no PyPI provenance attestation metadata in its distribution record. This Phase 2A lock pins versions but does not carry hashes for each platform wheel, verify signatures/attestations, or pin the package-index mirror. Before distributing PCB Prep, produce a platform-specific hash-locked requirements file, verify upstream release checksums/signatures where available, preserve license texts/notices, and review the full transitive-license inventory.

Shapely's wheel supplies its matching GEOS runtime; therefore users do not need a separate system GEOS installation for this baseline. Clipper2 was not installed or benchmarked in Phase 2A: no isolation or machining offsets are generated in this verification run. It remains a separate candidate for the later offset-engine evaluation and will require wrapper-license, integer scale, arc tessellation, and topology-collapse tests before selection.
