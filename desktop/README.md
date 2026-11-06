# DemonX PCB Prep desktop

DemonX PCB Prep is an independent Electron desktop application. The Electron main process owns the Python geometry child and passes versioned JSONL requests over standard input/output. The renderer is a static, sandboxed local UI; imported ZIP members are parsed as untrusted data and never executed.

- Electron: 45.0.0. Node runtime requirement: 22.12 or newer; the DemonX Design Desktop Phase 1D reference was exercised with Node 24.19.
- Development runtime: this product's `desktop/.venv` (CPython 3.12) and local Electron dependency. Run `SET UP DemonX PCB Prep DEV.cmd` once to provision pinned dependencies and the Electron runtime; launch by double-clicking `DemonX PCB Prep DEV.vbs`.
- Linux development: `bash ./scripts/linux/launch-dev.sh` after creating the local venv and running `npm ci` in `desktop/`.
- Windows portable package: `cd desktop; npm run package:win`. Linux AppImage/deb: build natively on a supported Linux x64 host with `npm run package:linux`.
- After `npm run build`, the optional packaged-engine round-trip is `npm run test:real-board -- "<path-to-Gerber-ZIP>"`.
- Logs: the packaged application opens its user-data diagnostics folder from the Inspection panel. The DEV launcher keeps startup output under `desktop/logs/`.
- The Python build tools are separately pinned in `desktop/requirements-build.lock`; the runtime engine still uses the existing Phase 2 dependency lock.

The Python child runs only the existing Phase 2 parser and geometry modules. It provides ZIP opening, layer geometry, source metadata, single-pass V-bit simulation, collision-aware two-pass simulation and selective clearing previews. All calculated statuses remain inspection-only and manufacturing remains BLOCKED. No G-code or machine execution is provided.

Builds must include the matching OS's PyInstaller bridge executable. The build does not download Python or Electron. Do not copy a Windows Python executable into a Linux package.
