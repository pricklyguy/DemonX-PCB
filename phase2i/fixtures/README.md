# Phase 2I external verification fixtures

## Ucamco Gerber Layer Format tests

- Source: Ucamco, “Gerber Layer Format - Test files (zip),” 19 May 2026, linked from the official [Gerber Format downloads page](https://www.ucamco.com/en/guest/downloads/gerber-format).
- Local archive: `ucamco-gerber-tests.zip`.
- SHA-256: `7e1e6bacdc24deb92fbf08940d37ccd26cff25fc9e5ca608b919d4d542d2698f`.
- Ucamco’s short included readme says specification examples are prefixed by their paragraph number. The download page describes the files as test files to help debug implementations.
- No separate license grant was included in the ZIP or identified on the download entry. Ucamco’s website terms reserve rights not expressly granted. This local engineering fixture must not be treated as cleared for redistribution; obtain Ucamco permission or arrange a first-party download in CI before publishing the repository or bundling the files in a release.
- The regression suite checks known object counts for ordinary aperture/polarity/macro examples and records two block-aperture examples as currently unsupported by Gerbonara 1.6.3. Those failures are test findings, not expected passes.

## KiCad `interf_u` export

- Source project: the `interf_u.kicad_pcb` demo installed with KiCad 10.0.7 at `C:\Program Files\KiCad\10.0\share\kicad\demos\interf_u\interf_u.kicad_pcb`.
- Source SHA-256: `ffc26d2ec84c4a2109b2912e6d1631e23f29e9712fd76db35cc11a634c7ce8c8`.
- Export command: `kicad-cli pcb export gerbers --output <fixture-dir> --layers F.Cu,B.Cu,Edge.Cuts --precision 6 <source-board>` followed by `kicad-cli pcb export drill --output <fixture-dir> <source-board>`.
- CLI version: KiCad 10.0.7. The CLI emitted access errors while probing the user’s KiCad registry/preferences, but both export commands produced their requested files. The source PCB was read only; generated output was written to this fixture directory.
- The generated X2 layer attributes identify top copper, bottom copper, and profile; Gerbonara parsed 903, 862, and 9 top-level objects respectively. Excellon parsed 401 drill objects. These are parser-compatibility regression values, not independent geometric truth.
- `kicad-interf-u-export.zip` (SHA-256 `b54fce5bb2a98f8845c4f54702c6c5d8b425422aa7430777a3c474b19c32d18e`) packages the generated top, bottom, outline, drill and job files. The PCB Prep archive loader classifies all four manufacturing functions and reconciles 401 circular hits. It also reports that the narrow Phase 2D X4.5 scanner does not support the exported coordinate format and surfaces one Phase 2A bottom-layer GEOS repair; those records are intentionally asserted as unresolved test findings.
- No per-project license file was present in the installed `interf_u` directory. KiCad’s project-level license page distinguishes KiCad code and library licenses, but does not by itself establish this demo board’s specific reuse terms. Keep as a local test reference pending a project-specific license check before redistribution.

## Authored region cases

`regions/valid_square.gbr`, `invalid_open.gbr`, and `invalid_crossing.gbr` are small hand-authored Gerber X4.5 millimetre cases. Their exact commands and expected condition are the test source; they are not Ucamco conformance fixtures. The test reuses Phase 2D’s deliberately limited source scanner and exact region geometry checks.
