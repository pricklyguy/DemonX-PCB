# DemonX PCB Prep Electron Conversion Report

**Checkpoint:** development implementation is available for owner review; standalone completion is not yet verified.

## Repository and baseline

- Verified repository: `pricklyguy/DemonX-PCB`, canonical remote `https://github.com/pricklyguy/DemonX-PCB.git`.
- Development branch: `codex/pcb-prep-electron`, created from the verified local and GitHub `main` baseline `13089c6fa2a6b18424d0623a76a978735ca4a034`.
- The earlier Phase 2O commit `88106fa` is present in the baseline history. No branch was reset, rewritten, or merged.
- The local worktree was clean before the branch was created. It had no other registered worktrees.
- Product identity: **DemonX PCB Prep**, version `0.1.0`, Electron app ID `com.demonx.pcbprep`.

## DemonX Design reference

The current source reference available in the development workspace is `Desktop-Phase1`, branch `feature/desktop-phase1-hardware-free`, commit `58c6ba38…`. It is a Phase 1D hardware-free prototype. It uses Electron 45.0.0 and was exercised with Node 24.19.0; its code requires the Electron 45 runtime. The renderer is a static local UI with a sandboxed BrowserWindow, context isolation, no Node integration, native dialogs, strict sender checks, and a parent-managed child process.

That reference does not provide a production Windows/Linux installer, updater, or final Suite contract. PCB Prep reuses its secure window and child-ownership direction. It does not copy Design's loopback HTTP/cookie/token service or Design-specific short-lived child behavior. No other DemonX repository was modified.

## Chosen architecture

- Electron main process owns the window, single-instance lock, native ZIP picker, logging, packaged resource paths, file-open activation, and Python child lifecycle.
- A sandboxed static renderer displays the board and diagnostic controls. It receives only the narrow `demonxPCB` preload API.
- The existing Python Phase 2 parser and geometry modules remain the source of truth. Electron sends versioned JSON Lines over the managed child’s stdin and reads responses from stdout; no network listener is opened.
- Protocol: `demonx.pcbprep.engine/1`. Requests and responses have size bounds, structured errors, progress events, and cancellation. ZIP opening continues through the existing safe member validation and extraction logic.
- Development uses the product's local Python 3.12 environment. Packaging builds a native, one-file PyInstaller engine for the target OS and includes it as an Electron resource. Windows binaries are not reused for Linux.
- Application resources use the product-specific PCB Prep `.ico` and Linux PNG icon set found in the owner workspace. No other DemonX product logo is used.

## Implemented workflow

The Electron renderer includes Gerber ZIP selection; top/bottom copper, board outline and drill display; zoom, pan and fit; operation-specific findings; source provenance and source feature records; V-bit angle, tip and depth controls; single-pass isolation; collision-aware two-pass spacing; selective-clearing candidate controls; and toolpath, rejected path and swept-footprint overlays. The renderer labels previews diagnostic-only, preserves the engine eligibility state, and does not generate G-code or authorize machining.

The current Windows PyInstaller engine build opened the available private Valentine ZIP and completed all three preview modes. It returned copper and profile paths, 230 drill features, 1,148 source features, BLOCKED machining, 196 first-pass contours, 3,221.091449 mm first-pass length, effective width 0.153589838 mm, 191 two-pass rejection findings, and 92 selective-clearing candidates.

The available archive's SHA-256 is `2e23a8cff4bd48d947f5f7fda371b8669d054c03cc87bb561bc2854d39337796`; the pinned Phase 2O test archive SHA differs. Its bottom-copper layer digest matches the pinned layer digest, but its whole archive does not. Consequently, the comparison with the Phase 2O baseline of 225 contours and approximately 3,400.34 mm is **unverified**. The original 113 source findings are also **unverified** with this archive; this run returned four current archive findings. No geometry correction was made.

## Development and packaging

- Windows DEV launcher: `DemonX PCB Prep DEV.vbs` (double-click). First-run setup: `SET UP DemonX PCB Prep DEV.cmd`. The setup provisions the locked Python dependencies, pinned build tools, npm packages, and Electron runtime; the launcher resolves paths from itself, records startup logs, and reports startup failure.
- Linux DEV command: `bash ./scripts/linux/launch-dev.sh` after the documented one-time environment setup.
- Windows engine build succeeded at `desktop/build/engine/pcbprep-engine.exe` (ignored build output).
- Windows standalone portable package: **not produced**. Electron Builder reached Windows packaging, then failed extracting its `winCodeSign` support archive because the restricted build account cannot create the archive's macOS symbolic links (`A required privilege is not held by the client`). Retrying with automatic certificate discovery disabled produced the same failure. No installer/package success is claimed.
- Linux AppImage/deb: **not built or runtime-tested**; this host is Windows. The native Linux build command and target metadata are present.
- A real Electron window and Electron screenshots were **not captured**. The workspace Electron runtime reached Chromium startup, but Windows denied its sandbox token access to the workspace runtime folder's ACL. I did not weaken the ACL or disable Chromium sandboxing. The alternate Design runtime also could not create a window from this restricted launch context. This is an environment-limited launch check, not a reproduced application defect.

## Test and validation results

- New Node tests: 7 passed. They cover bridge request/result/progress routing, structured errors, cancellation messages, size bounds, sender and preload wiring, secure window settings, second-instance handling, startup file-open queuing, and packaged resource paths.
- New Python engine contract tests: 5 passed. They cover protocol identity, existing V-bit width calculation, numeric bounds, point and line SVG path output.
- Built native Windows Python engine: success. Real-board archive round-trip and single-pass, two-pass, and selective-clearing previews: success, with the parity limits above.
- Electron main, preload, bridge, renderer, build script, and real-board check JavaScript syntax checks: passed. Renderer is static JavaScript; no TypeScript project is configured.
- Existing baseline suites could not be fully established from this checkout. The Phase 2A suite reached 15 passing tests and one failure because generated `phase2a/results/parsed_geometry.json` is absent. Phase 2O reached 15 passing tests and one failure because the available private archive's SHA does not match its pinned SHA. The full 165-test A–O checkpoint was not reproduced.
- `git diff --cached --check`: passed. The staged-file privacy audit found no private archive, photos, run logs, generated board geometry, host paths, or key material.

## Security review

- Renderer settings: `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`, `webSecurity: true`, and a restrictive local-content CSP.
- Preload exposes only ZIP open, simulation, cancellation, progress/opened subscriptions, and opening the diagnostics folder. Main-process IPC checks the exact renderer frame and local UI path.
- Navigation and new windows are denied unless they remain at the local application page. Renderer code has no filesystem or shell API. Imported filenames and feature labels are inserted as text.
- The Python process is spawned without a shell, with a deliberately reduced environment, private stdio transport, and controlled lifetime. ZIP parsing and member validation remain in the existing Python engine.
- Cancellation is cooperative at existing parser progress callbacks and geometry-stage boundaries; GEOS operations already in progress cannot be interrupted mid-call.
- Manufacturing controls remain diagnostic-only. There is no G-code output, CNC execution, `.dxd` output, or authorization path.

## Suite integration readiness

The proposed activation contract is the registered product identity plus a command-line `.zip` path. A second launch activates and restores the existing window; queued file-open requests wait until the renderer is loaded. This remains useful standalone and does not require DemonX Suite.

Future Circuit handoff can open its existing Gerber ZIP through this activation path. A future Design handoff could consume a canonical geometry/job package only after the Suite owners confirm the existing shared format. CNC could receive only a reviewed, approved operation through its established job handoff. No inter-application transfer or new shared format is implemented here. Shared launcher and updater integration remains a future opt-in capability.

## Owner review checkpoint and next steps

This branch is an implementation checkpoint, not an accepted standalone release. Before calling the milestone complete:

1. Launch the DEV app in an unrestricted owner desktop session and confirm its native window, second-launch activation, close cleanup, diagnostics, and ZIP file-open behavior.
2. Import the pinned Valentine archive in Electron and inspect copper, drills, zoom/pan, the 113 findings, BLOCKED status, and all three preview modes. Reconcile 225 contours, approximately 3,400.34 mm, and V-bit width against that exact archive.
3. Complete a Windows portable package build in an environment that can extract the electron-builder signing support archive, then launch the package independently of the development venv.
4. Build and launch the Linux AppImage or deb on native Linux; verify its bundled GEOS/Shapely runtime and desktop identity.
5. Re-run the full baseline suite with its required generated/private inputs, review the staged file list and public-export privacy checks, then request owner review before any merge.

## Owner launch instructions

On Windows, double-click `SET UP DemonX PCB Prep DEV.cmd` once. After it completes, double-click `DemonX PCB Prep DEV.vbs`. Use **Open Gerber ZIP** to choose the private Valentine archive. Enable **Diagnostic preview** to inspect the existing Python geometry previews. The app remains BLOCKED for machining. Startup logs are under `desktop/logs/`.
