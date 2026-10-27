# Region source and display provenance

Gerber region endpoints must close explicitly. A renderer that fills an open path
with an inferred chord supplies a display interpretation, not evidence that the
source contains that edge. A valid GEOS polygon does not establish source
conformance or manufacturing intent. See section 4.10 of the
[Ucamco specification](https://www.ucamco.com/en/guest/downloads/gerber-format).

The inspection scanner retains the active dark/clear polarity with each source
region. That polarity and the actual filename must survive into repair review:
a clear region removes material, so treating every region as added copper gives
misleading review context. No endpoint is moved by this provenance handling.

Bottom-layer material that depends on open source regions uses the existing
`hypothetical` role in the internal canonical envelope. Source conformance,
independent verification and manufacturing eligibility remain separate. This
role does not change the preview geometry or approve any closure.

`phase2n/source_audit.py` independently tokenizes a deliberately restricted
absolute X4.5 metric linear subset, preserving integer coordinates, moves,
draws, command positions and polarity. It does not use the application scanner
or library region conversion. Unsupported state fails explicitly.
`phase2n/run_audit.py` compares that evidence with Gerbonara and PyGerber, emits
PyGerber's native display renders, and separately compares material composed
from PyGerber command objects. The material comparison shares GEOS with the
application; it is not an independent numerical kernel or a fabrication verdict.

Run with the existing GUI Python environment:

```powershell
& ./phase2g/.venv/Scripts/python.exe -m phase2n.run_audit --archive $privateArchive --screenshots
$env:DEMONX_PHASE2N_ARCHIVE = $privateArchive
& ./phase2i/run_regressions.ps1
Remove-Item Env:DEMONX_PHASE2N_ARCHIVE
```

The optional private acceptance tests require the matching local audit output.
Without the environment variable they report explicit skips; the authored
semantics tests still run. All extracted inputs, hashes, board measurements,
screenshots and detailed reports stay in ignored local evidence paths. This
note intentionally includes no board-specific evidence.
