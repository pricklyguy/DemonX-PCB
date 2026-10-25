# Phase 2F — Laser Module revision comparison

This phase compares the supplied EasyEDA Standard 6.5.51 v2.0 PCB and its
2026-10-25 Gerber export with the preserved Laser Module v2.5 Gerber archive.
It is a read-only geometry investigation. It does not change the Phase 2E
recovery policy or manufacturing eligibility.

## Reproducible inputs

- `fixtures/laser-v2.0-export.zip` — staged copy of the fresh export.
- `fixtures/laser-v2.0-pcb.json` — staged copy of the original v2.0 native PCB.
- `../gerbers/Gerber_Prickly-Laser-Module-2.5.zip` — preserved v2.5 archive.
- `fixtures/extracted/laser-v2.0/` — only five whitelisted manufacturing files,
  extracted after ZIP path/type/size checks.

Originals remain at their received locations and are not modified. SHA-256
identities and member hashes are in `results/source-manifest.json`.

## Run

From the repository root in PowerShell:

```powershell
.\phase2f\run_phase2f.ps1
```

The script uses the repository-local `phase2a/.venv` Python environment and
the pinned PyGerber environment already used by Phase 2C. It regenerates the
machine-readable comparison and runs the Phase 2E recovery tests plus the new
Phase 2F tests. It installs no packages.

## Evidence boundary

The source-command comparison uses PyGerber's parsed Gerber command model and
exact source-region records. Native copper comparison uses cached polygon paths
from the EasyEDA PCB JSON. It does not establish the behavior of a later EasyEDA
version, a v2.5 native document, or a CAM toolpath. The 182 candidate closures
remain blocked pending an explicit geometry-acceptance decision.
