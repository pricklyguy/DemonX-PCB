# Phase 2K — EasyEDA Valentine export instructions

These steps produce the two missing comparison datasets. They do not approve machining. Do not open or edit the original February Gerber ZIP or original `.epro` file.

## Before you start

1. Run `Get-FileHash` on both project copies and confirm they match the original project SHA-256 `43c1992652a107d1e7967ae902a643701695c2132cfbf87ce2b475c7fe7cc440`. The provided copies are under `E:\Gerber_Recovery\Phase2K_Exports\A_saved_state\` and `B_rebuilt_state\`.
2. Keep the original `.epro` and Gerber ZIP unchanged. Use only the A and B copies for the operations below.
3. The project reports EasyEDA Pro **2.2.45.4**. The inspected installation is **2.2.47.7**. Prefer 2.2.45.4 if it is available. If 2.2.47.7 opens the copy, record that version and any migration, conversion, fill-refresh or save prompt. Do not claim it preserved the old saved copper state if the application recalculates fills automatically.
4. Use local project open/export only. Do not import the design into an online workspace, publish/share it, or upload it. If EasyEDA requires cloud upload/sync, account access, or migration that you cannot decline, stop and ask for a local/offline export path.
5. Capture the export settings, editor version, operation messages, local timestamps and SHA-256 hashes. Save outputs only under `E:\Gerber_Recovery\Phase2K_Exports\`.

## Export A — open without an explicit pour rebuild

1. In EasyEDA Pro, choose **Open Project** and select `A_saved_state\Valentine_A_saved_state.epro`.
2. Record the exact application version and every prompt about project conversion or copper fill. Do not run a copper rebuild for this copy.
3. If the editor automatically updates copper on open, or you cannot tell whether it did, record that as **saved-fill preservation unknown**. Do not describe this as an untouched saved-fill export.
4. Use the PCB fabrication/Gerber export command. Keep the layer selection, coordinate origin, units, precision, outline and drill options as close as the application allows to the February export. Save the Gerber ZIP in `E:\Gerber_Recovery\Phase2K_Exports\A_saved_state\` using a new filename.
5. Save or screenshot the export settings and completion messages alongside the ZIP. Record SHA-256 for the ZIP and every member.

## Export B — rebuild copper, then export

1. Open `B_rebuilt_state\Valentine_B_rebuilt_state.epro` as a separate project copy. Do not reuse the A editor document.
2. Select the PCB and explicitly run the application’s **Rebuild/Update Copper Area** command. The menu wording can vary by version; use the command that recalculates copper pours, and record its exact displayed name and completion result.
3. Record any changed-pour or design-update message. Do not make unrelated layout edits.
4. Export Gerbers with the same settings used for Export A into `E:\Gerber_Recovery\Phase2K_Exports\B_rebuilt_state\` under a new filename.
5. Save the settings and completion evidence, then hash the ZIP and all members.

## Send back for comparison

Provide both ZIPs plus a short note containing:

- EasyEDA version and platform.
- Whether opening A changed or rebuilt fills automatically.
- The exact command used to rebuild B and any status/message shown.
- Export settings for A and B, including selected layers and coordinate origin/precision.
- Local timestamps and SHA-256 hashes for both ZIPs and all manufacturing members.
- Any migration, missing-footprint, font/library, or upload/sync warnings.

The comparison will separately check source bytes/headers, parsed commands, canonical copper material/topology, drill and slot records, and coordinate registration. Matching screenshots or dimensions alone will not resolve the existing copper discrepancies.

To run the Phase 2K schema tests from the repository root, install `phase2k/requirements.txt` into the existing project-local environment and run:

```powershell
& .\phase2g\.venv\Scripts\python.exe -m unittest phase2k.test_phase2k -v
```
