# DemonX PCB Prep — Phase 1 Repository Audit and Architecture

**Status:** Proposed for review; no Phase 2 implementation authorized  
**Audit date:** 2026-10-24  
**Scope:** Read-only audit of this repository and related DemonX repositories; this report is the only new artifact.

## Executive summary

The repository contains two generations of Pcb2Vectric work. The legacy scripts implement partial Gerber and Excellon parsers directly; the tracked `pcb2vectric/` package is a more capable Python rewrite using Gerbonara, Shapely/GEOS, ezdxf, and PySide6. The newer rewrite is useful as a behavioral and UI reference, but its geometry shortcuts, implicit manufacturing assumptions, and DXF-centered output are not a reliable shared core for the intended application.

Two user-provided ZIP archives contain useful real board manufacturing outputs, including top and bottom copper, profiles, and separate plated, non-plated, and via drill files. They have not been parsed or geometrically verified in this audit. Existing tests generate a compact synthetic board in memory and assert parser/geometry behavior; there are no checked-in extracted real-board baselines or reference geometry comparisons.

The DemonX Circuit and DemonX Design/CNC repositories are available locally. Circuit is an Electron/TypeScript workflow shell around native KiCad projects and CLI operations. Design/CNC is a React/TypeScript application whose `.dxd` document stores millimetre coordinates and polygonal paths/circles; its current import seam handles DXF/SVG, not PCB Prep data. There is no existing direct Circuit→PCB Prep→Design API or native PCB handoff. A versioned, structured interchange object/API is needed so standalone and integrated flows invoke the same Python core, and Design receives structured geometry without a DXF round trip.

**Recommendation:** Retain Python for the first shared engine because Gerbonara, Shapely/GEOS and the current prototype are Python. Use Gerbonara as a pinned parser adapter, retain source precision and primitive semantics in a canonical internal model, and use a separately tested topology engine for boolean composition and machining offsets. Keep exact/analytic lines and arcs until an operation requires polygonization. Start with GEOS/OverlayNG through Shapely for overlay and settable precision; benchmark a pinned Clipper2 binding for offset operations and integer-grid behavior before finalizing the offset backend. Make structured, versioned JSON the integration boundary. Treat DXF as a legacy export adapter only.

## 1. Repository audit

### Git and workspace state

- Repository: `gerber_to_vectric`; current branch `claude/epic-rubin-9urbl2`, tracking `origin/claude/epic-rubin-9urbl2`.
- HEAD: `ff26412` (`Ignore vias option: skip drilling small holes and drop lone via pads`). Recent history includes the Gerbonara rewrite, GUI, configurable drill groups, and speck filtering.
- `git status` shows two untracked directories: `Prickly_Converter_Vectric/` and `gerbers/`. They were present before this audit and were not changed.
- The repository has no root `AGENTS.md` in the inspected file set. The tracked docs directory is `doc/` and contains images; there was no `docs/` directory at audit start. This report creates `docs/` without touching existing files.
- No branch changes, resets, package installs, test runs, file extraction, or edits to the adjacent DemonX repositories were performed.

### Existing Pcb2Vectric code and architecture

The current tracked app is `pcb2vectric/`, with a conventional Python package split:

| Module | Current responsibility | Audit view |
|---|---|---|
| `gerber_io.py` | Opens Gerbonara Gerber/Excellon files and converts graphic primitives into Shapely shapes | Best parser reference, but mixes parsing, tessellation, image composition, filtering, outline inference and drill normalization. |
| `job.py` | Applies origin/mirror rules, via heuristics, drill planning, optional isolation | Useful workflow reference; configuration mixes source interpretation, manufacturing assumptions and presentation. |
| `isolation.py` | Buffers copper and emits rings per pass; detects narrow gaps | Demonstrates intended preview/check workflow; fixed groove-width model is not cutter/depth aware. |
| `drills.py` | Assigns holes to available drill sizes, records milled holes/slots | Useful grouping baseline; unsupported-size handling and plating semantics need a stronger data model. |
| `tools.py` | Reads Vectric `.vtdb` SQLite tools and computes V-bit width/depth | Reference for Vectric compatibility only; should not define the core tool model or be the native Design library adapter. |
| `detect.py` | Guesses layers from filename suffixes and simple Excellon header strings | Keep as a suggestion mechanism only; never let a suffix override Gerber X2 file attributes or user confirmation. |
| `dxf_out.py` | Writes polygons, circles and operation layers to DXF | Legacy export reference; DXF cannot be the internal or DemonX Design transfer contract. |
| `setup_sheet.py`, `cli.py` | VCarve instructions and command-line wrapper | Useful legacy workflow reference. |
| `gui/` | PySide6 file selection, preview and setup UI | Potential interaction reference; keep UI separate from geometry and manufacturing services. |

The older `script/dxf_script.py` and four files in the untracked `Prickly_Converter_Vectric/` directory use hand-written parsers followed by Shapely/DXF conversion. The old Excellon parser guesses coordinate format from digit count, falls back to a default 0.8 mm drill when a tool is missing, and retries a different format when the result seems too small compared with copper bounds. The Gerber parser understands only a limited syntax subset; its line state, aperture handling, and regions are handwritten. These implementations are historical evidence of earlier approaches, not candidate production parsers.

### Dependencies and automated tests

`requirements.txt` currently pins `ezdxf==1.4.3` and `shapely==2.1.2`, allows any `gerbonara>=1.5.0`, and allows `PySide6>=6.6`. This is not a reproducible parser/UI dependency set: Gerbonara and PySide6 can move without a lock. There is no `pyproject.toml`, lock file, or package build metadata in the root listing.

`tests/test_core.py` contains 16 pytest tests. Coverage includes a synthetic Gerber with line, arc, rectangular flash, region, and clear polarity; a synthetic closed outline; synthetic Excellon tools/holes; isolation buffers; gap detection; drill grouping; bottom mirroring/alignment; DXF layer export; Vectric database templates; suffix detection; GUI smoke; and via heuristics. The tests do not establish correctness on either real ZIP fixture, the full Gerber grammar, X2 attributes, real exporter variation, plated/non-plated semantics, or native DemonX transfer. No tests were run for this Phase 1 audit.

## 2. Supplied fixture inventory

Only two archive files were present in `gerbers/`. Their ZIP directory listings were inspected; the archive members were not extracted, parsed, rendered, or compared with a reference viewer.

| Archive | Files observed in ZIP listing | Coverage suggested by filenames | Verification status |
|---|---|---|---|
| `Gerber_PCB_Valentine_Feb_New.zip` | `Gerber_TopLayer.GTL`, `Gerber_BottomLayer.GBL`, top/bottom silkscreen, top/bottom solder mask, bottom paste, `Gerber_BoardOutlineLayer.GKO`, documentation, drill drawing, `Drill_PTH_Through.DRL`, `Drill_NPTH_Through.DRL`, `Drill_PTH_Through_Via.DRL`, flying-probe JSON, order notes | Top/bottom copper and candidate double-sided board; profile; three logically separated drill files; non-plated and via coverage by name. Multiple actual drill sizes and slots are unknown until contents are inspected. | Inventory only; not parsed or verified. |
| `Gerber_Prickly-Laser-Module-2.5.zip` | `Gerber_TopLayer.GTL`, `Gerber_BottomLayer.GBL`, top silkscreen, top/bottom solder mask, top/bottom drill? (only PTH through and PTH via files listed), profile, documentation, `Drill_PTH_Through.DRL`, `Drill_PTH_Through_Via.DRL` | Top/bottom copper, candidate double-sided board, profile, PTH and via separation by name. No NPTH file in listing. | Inventory only; not parsed or verified. |

The repository's only parser fixture is embedded as strings in `tests/test_core.py`; it is synthetic, not a supplied production export. It covers top copper semantics in one simple hand-built case, but not actual alignment between separate top, bottom, outline, PTH and NPTH files.

### Fixture coverage still unknown or absent

- Multiple Excellon unit/zero-suppression modes, omitted axes, modal coordinates, repeat codes, routed slots/arcs, tool changes, and missing tool definitions.
- Plating flags beyond file naming, PTH/NPTH tool-number collisions, and whether tool diameter or finished hole diameter is represented.
- Actual measured drill diameter distribution and explicit expected drill grouping around ≤0.8, 1.0, 1.1, 1.2, 2.0, 3.0, 3.1 mm, plus unsupported diameters and larger profile-bore candidates.
- Gerber X2 `FileFunction`, `FilePolarity`, `Part`, object attributes for pad/via intent; negative images; aperture macros; holes in apertures; step-repeat; object/region polarity interactions; non-circular apertures; and complex arc regions.
- Profiles with internal cutouts, multiple islands, routed slots, closed arcs, width-bearing profile strokes, and intentionally open/incomplete paths that require a diagnostic.
- Sub-0.001 mm² real copper features, touching copper components, narrow clearances, self-intersecting/bad input diagnostics, and adversarial coordinates.
- Per-side registration fiducials/origins, X/Y mirroring, rotation/offset, and board flip strategies checked against known dimensions or a trusted EDA/CAM output.
- Isolated baselines: source hashes, expected units and extents, control dimensions, feature counts, drill table, topology/area, and visual references from a trusted Gerber viewer.

Phase 2 should promote copies of the ZIP files into a tracked fixture corpus only after checking redistribution rights and removing unrelated order/probe artifacts. Preserve original files and hashes; add a manifest with expected source identity and fixture purpose.

## 3. Existing geometry weaknesses and likely inaccuracy causes

The following are code-inspection findings, not reports of a particular fixture failure.

1. **Lossy geometry is created during ingestion.** `gerber_io.py` converts Gerber lines/arcs to buffered line strings and circles to `Point.buffer()` polygons. Arc tessellation uses a fixed 0.005 mm sagitta target and then buffering uses finite `quad_segs`; circle flashes use only 32 segments per quadrant configuration. These approximations can distort small apertures, copper boundaries, offsets and narrow clearances. Exact circular primitives should stay analytic until a consumer needs a polygon.
2. **Unsupported constructs disappear without a complete preservation path.** `_primitive_shape()` returns `None` for primitive types outside line/arc/circle/rectangle/ArcPoly. Gerbonara supports macros and transforms, but this app's converter does not clearly support every returned primitive form. Silently skipped geometry can make a layer nonempty but incomplete. Parsing must produce explicit unsupported-feature diagnostics or preserve every supported primitive type.
3. **Clear/dark composition may not preserve all image semantics.** `load_copper()` unions same-polarity runs and subtracts clear runs in object iteration order. The model reduces Gerber semantics to a sequence of Shapely shapes and a boolean flag, without explicit file polarity, region grouping, step-repeat or X2 object/function metadata. A valid Gerber image's ordered compositing behavior and layer metadata need explicit tests, particularly for negative files and nested region/macro behavior.
4. **Outline reconstruction has a false snap step.** `load_outline()` says it snaps near-coincident endpoints but calls `affinity.scale(l, 1, 1)`, which leaves coordinates unchanged. `polygonize()` requires linework to actually close/nod; near gaps may remain open. It also turns all polygonized rings into exterior-only polygons, which can fill interior cutouts. Outline stroke apertures and clear polarity are not reconstructed as a profile semantic model.
5. **Heuristic data loss is built into the core.** `drop_specks()` removes any polygon smaller than 0.001 mm² as an alleged rounding artifact. That may delete deliberate tiny pads or copper islands. Via handling drops holes below a default 0.6 mm and may remove small copper islands containing them. Vias are electrical features; omitting drill hits/pads is a manufacturing choice that should be explicit, per-feature and reversible, never an unreviewed destructive parse default.
6. **Plated, non-plated and via categories are discarded.** `load_drills()` returns only `Hole` and `Slot`; it does not retain source file, plating class, tool code, source diameter semantics or diagnostics. Combining separate PTH/NPTH/via files erases information required for classified, CNC-ready layers. A drill diameter mismatch is surfaced only as a general warning and there is no explicit unsupported/ambiguous status.
7. **Slots are simplified to straight capsule strokes.** `Slot.shape()` buffers a straight `LineString`; routed arcs, multi-segment slots and source routing semantics are not represented. Type-name string checks (`type(obj).__name__ == "Flash"`) are brittle compared with typed parser adapters.
8. **Board placement and registration lack a complete coordinate contract.** The bottom is mirrored about the board's vertical centre and alignment holes are generated outside the bounds. There is no persisted declaration of origin, mirror axis, bottom-view convention, rotation, coordinate transform or source provenance that a consumer can independently validate. Automatic origin zeroing can also turn valid negative profile extents into a hidden transform if not shown to the operator.
9. **Isolation is a fixed-width approximation, not physical cutter compensation.** `IsolationSettings.cut_width` defaults to 0.2 mm, and the generator offsets copper by half that width then steps outward. It does not derive the groove from the cutter's 30° included angle, 0.1 mm flat tip and machining depth; nor does it account for cutter wear/runout, depth variation or the board's copper thickness/stock datum. The `Tool` model can compute V-bit width/depth, but this is not the isolation generator's input contract. Buffer joins, collapsed necks, islands, narrow gaps and topology changes need explicit failure/warning treatment.
10. **DXF output erases semantics.** Exported rings and circles are grouped by names, but a downstream reader must infer whether a circle is a hole boundary, drill centre, milled bore or registration feature. DXF export cannot carry full source precision, Gerber attributes, source linkage, classification confidence, or a lossless drill/slot representation. It should be a compatibility output, not Design's transport.
11. **Defaults can misclassify work.** Filename guessing accepts only a subset of common extensions/names and selects the first matching layer. Excellon detection is a three-string header heuristic. The core defaults to skipping vias and removing lone via pads; a CAM tool cannot safely infer that a via should be ignored. Drill tools are assigned by rounding up; `plan_drills()` preserves source `Hole` only in memory but exported names do not communicate source diameter or fit risk in a machine-readable way.

These factors are plausible causes behind prior inaccurate geometry, especially lost clearances, filled board cutouts, approximation error around small circular features, misaligned drill data and incorrectly omitted/mixed drill groups. The real fixture contents have not been examined deeply enough to attribute a specific defect to a specific archive.

## 4. DemonX repositories and integration findings

Both intended downstream repositories exist next to this repository and were inspected read-only:

- `../DemonX-Circuit/` — DemonX Circuit desktop preview and native workflow shell.
- `../DemonX-Design-CNC/` — combined DemonX Design and DemonX CNC repository; `design/` is the Design application, and CNC toolpaths are part of its Design client. The separate `../DemonX/` checkout also contains a `design/` copy, but the `DemonX-Design-CNC` repository has the active Design/CNC documentation and code examined here. Confirm the authoritative downstream checkout before Phase 2 integration.

### DemonX Circuit

- **Framework/language:** Electron 45 desktop shell, TypeScript renderer/preload, CommonJS main process, Node.js 24 target. The repository's current architecture describes a workflow shell, not a full custom EDA canvas.
- **Native source project:** KiCad 10.x project files (`.kicad_pro`, `.kicad_sch`, `.kicad_pcb`), libraries, and a DemonX JSON project manifest (`demonx-project`, versioned). Native KiCad stays editable and authoritative.
- **Manufacturing boundary:** main-process adapters discover and invoke `kicad-cli`; the renderer communicates through a narrow preload IPC API. `prepareManufacturing()` is currently an operation/result API, not a direct PCB Prep data contract. Project summaries expose project root, revision, native paths and state.
- **Layer/tool geometry:** Gerbers and Excellon are outputs from the installed KiCad CLI; Circuit does not expose a PCB-prep geometry model or toolpath tool library seam in its current API.
- **Integration opportunity:** Circuit can invoke PCB Prep against a staged, revision-identified Gerber/drill export via an adapter/CLI/process contract and show diagnostics/results. Preserve the native KiCad project untouched; record source project revision and generated-file hashes in the handoff manifest. The exact integration method is not implemented.

### DemonX Design and CNC

- **Framework/language:** React 18 + TypeScript + Vite web UI; Node/TypeScript server in the combined repository. `design/` has its own package and uses `clipper-lib` 6.4.2 and `dxf-parser` 1.1.2 among its dependencies.
- **Native document:** `.dxd` JSON, `format: "demonx-design"`, current version 5. A `Doc` stores layers, shapes, workspace/material setup, machine and optional CNC data. Values are millimetres; the document coordinates are Y-up.
- **Geometry model:** `PathShape` stores one or more `Pt[][]` rings and a closed flag; `CircleShape` stores centre and radius. This is polygon/polyline geometry, without a native exact-arc segment type in the core shape union. DXF import supports several entity kinds, tessellates arcs/curves/bulges and simplifies paths (default 0.002 mm). SVG and DXF are current import/export seams.
- **Layers and tool library:** layers carry names, colours, output/display properties and general cut/engrave modes; CNC stores cutter/toolpath objects in the Design document and uses its JSON tool library. The Design tool model has V-bit angle and diameter fields but no obvious named 0.1 mm flat-tip field in the current public `LibTool` shape. The existing `tools.vtdb` parser is for a Vectric database and should not be mistaken for a Design-native tool adapter.
- **Toolpath boundary:** profile, pocket, drill, engraving, V-bit and related CNC toolpaths are calculated inside Design's CNC modules and selected shapes. PCB Prep should transfer manufacturing geometry and typed operation intent; Design remains responsible for native toolpath choice, machine setup and G-code/postprocessor output. A PCB-specific import command/API and layer/geometry metadata need joint design.
- **Current integration status:** no direct PCB Prep API, plugin protocol or native import of arbitrary structured geometry was found in the inspected Design interface. A versioned JSON bridge is the proposed seam; the receiver should call a supported Design-side import function and create native shapes/layers without serializing through DXF. Because `.dxd` parsing is strict and versioned, the adapter should use a supported API/import command rather than silently writing a project JSON file itself.

No related repository files were modified.

## 5. Parser and geometry library evaluation

### Gerber and Excellon parsing

**Gerbonara — recommended first parser adapter.** As of the audit date its current PyPI release is 1.6.3 (2026-04-25). Its documentation advertises Gerber and Excellon read/write, full aperture macro support, X2 attributes through its file objects, unit-aware primitives, and tests against real-world exports from KiCad, Altium, Eagle, Allegro, PADS, and other CAD tools. It is already used in this repository, reducing the amount of new parser code. Pin an exact reviewed version and build a compatibility wrapper: library support claims do not substitute for our corpus and semantic verification. PyPI reports no provenance metadata for 1.6.3, so record artifact hashes and review its source/license before release. ([Gerbonara documentation](https://gerbolyze.gitlab.io/gerbonara/), [release tags](https://gitlab.com/gerbolyze/gerbonara/-/tags), [PyPI 1.6.3](https://pypi.org/project/gerbonara/))

**Other options:**

- **KiCad CLI / Pcbnew:** valuable as a versioned source/export adapter and independent reference tool; not a standalone Gerber/Excellon geometry library. Circuit's native KiCad version can generate a known source export, but imported third-party Gerbers still need a CAM parser.
- **Legacy `pcb-tools`:** useful only for compatibility comparison. Gerbonara docs describe it as the predecessor and note its statement-based API; it should not be the new core choice without a current maintenance/security review.
- **KLayout:** a mature, powerful layout database and scripting environment, but its native strengths are IC/PCB layout formats; it would introduce a larger external runtime and does not remove the need to validate Gerber image and Excellon semantics for this product. Consider only if future format interoperability needs justify it.
- **Handwritten RS-274X/XNC parser:** reject for the primary path. The existing legacy code demonstrates the maintenance risk: implicit modal state, zero suppression, polarity, macros, arcs and tool tables are easy to misread. Restrict custom parsing to diagnostics or explicit compatibility gaps with specification-backed tests.

The official Ucamco source lists the Gerber Layer Format Specification revision 2026.05, an official Gerber grammar (PEG), Gerber test files, and XNC specification revision 2021.11. Use those current official documents and test files as the normative reference, while distinguishing XNC from the many exporter-specific Excellon dialects in the wild. The official fabrication guide also cautions that incomplete NC files can leave unit/format ambiguity; never guess a drill coordinate scale from apparent board size and silently continue. ([Ucamco Gerber downloads](https://www.ucamco.com/en/guest/downloads/gerber-format), [official format overview](https://www.ucamco.com/en/file-formats), [XNC 2021.11 specification PDF](https://www.ucamco.com/files/downloads/file_en/452/xnc-format-specification-revision-2021-11_en.pdf?2ccd0fdd6dd78e87ed52185bbd06038b=), [PCB fabrication data guide](https://www.ucamco.com/files/downloads/file/130/pcb_fabrication_a_guide_20150107.pdf?))

### Robust polygon, arc and offset operations

**Canonical geometry should not be only a Shapely polygon.** Keep source decimal/integer coordinates, units, exact circular arcs, flash/aperture definition, polarity event order, source file/object identity and X2 attributes in a typed intermediate representation. Preserve true circles/arcs for outline and drill operations. Generate polygon approximations only at a named operation boundary, with a documented, user-independent chord-error tolerance tied to downstream machining tolerance.

**Shapely 2.1.x with GEOS OverlayNG — recommended general boolean engine.** It is mature and already pinned in this repo. GEOS OverlayNG supports robust overlay operations and fixed-precision reduction (`set_precision` / `grid_size`). Use explicit precision policy in integer micrometres or finer only after validating coordinate range, cumulative rounding error, minimum feature retention and topology behavior. Do not run global precision snapping or simplification on source data. Shapely round buffers are useful for controlled polygonization but are not exact circles. ([Shapely precision model documentation](https://shapely.readthedocs.io/en/2.1.2/release/2.x.html), [set_precision reference](https://shapely.readthedocs.io/en/2.1.1/reference/shapely.set_precision.html))

**Clipper2 — evaluate specifically for CNC offsets and integer-grid boolean checks.** Clipper2 provides polygon union/difference/intersection and offsets with integer and floating variants. An official C++/Rust API exists, and a current Python binding (`clipper2-py`) was published in 2026; it is an unofficial wrapper, so its ABI, package maturity, provenance, licensing, Windows support and release cadence require review before adopting it. Keep it behind a geometry-engine interface and compare its outputs against GEOS and hand-constructed expected cases. The Design/CNC repo uses the older `clipper-lib` JS package; that is a separate implementation and should not become the canonical parser geometry engine by accident. ([Clipper2 overview](https://www.angusj.com/clipper2/Docs/Overview.htm), [Rust binding docs](https://docs.rs/clipper2/latest/clipper2/), [Python binding package](https://pypi.org/project/clipper2-py/))

**Recommended Phase 2 dependency decision:** Python 3.12+ runtime, Gerbonara pinned to the then-reviewed exact release; Shapely pinned with the bundled GEOS version recorded; PySide6 for the standalone desktop shell; JSON Schema validation; ezdxf retained only in the DXF adapter. Keep Clipper2 as an evaluated optional backend until corpus-backed overlay/offset benchmarks and topology tests establish whether it improves the required cases. Avoid a second independently implemented geometry engine in TypeScript. Do not install global toolchains; use project-local, reproducible environments.

## 6. Proposed shared-core architecture

One reusable Python package should be called by standalone UI/CLI and integration adapters. Circuit/Design integrations must be adapters around the same `pcbprep-core`, not separate converters.

```text
Gerber/Excellon / ZIP / optional KiCad CLI export
                    │
        input inspection + source manifest
                    │
    parser adapters (Gerbonara; version/capability checks)
                    │
 canonical manufacturing IR (mm, source identity, exact primitives,
 attributes, polarity, holes/slots/plating, transforms, diagnostics)
                    │
 geometry engine (ordered image composition, topology, profiles,
 tool/depth compensation, drill classification, validation)
          ┌─────────┼──────────┐
      preview   transfer DTO   DXF legacy export
                    │
      Circuit adapter / standalone JSON API / Design adapter
                    │
             DemonX Design native shapes/layers
                    │
      Design-owned CAM toolpaths → DemonX CNC output
```

### Canonical model and required invariants

- All physical values are millimetres internally; retain raw file units and coordinate precision in provenance. Make every unit conversion explicit.
- Preserve Gerber image events in order and distinguish file polarity from dark/clear object polarity. Preserve X2 file/object attributes and warnings.
- Distinguish copper regions, strokes, flashes/apertures and aperture holes before composition. Use semantic unioned copper only as a derived view.
- Keep board profile and interior cutouts as boundary curves/loops with closure confidence and source mapping; do not infer a filled shape from exterior rings alone.
- Preserve Excellon source file, tool id, stated tool/finished diameter, hit/slot path, PTH/NPTH/unknown class, unit/format mode, and parse confidence. Unknown stays unknown; no default size, scale, plating or via-skip policy.
- Keep original hole diameters. Provide supported drill group assignments (≤0.8 mm, then 1.0, 1.1, 1.2, 2.0, 3.0 and 3.1 mm), plus explicit unsupported/ambiguous groups. Holes larger than the selected drill ceiling become profile-bore candidates only with an explicit operation classification. Slots remain separate geometry and operation types.
- Model transforms as explicit, serializable matrices/affine operations with named source/destination frame, side, origin and revision; never use a hidden mirror.
- Model cutter geometry and machining depth, including V-bit included angle and 0.1 mm flat tip. Derive groove width from the selected cutter/depth relation; warn when requested clearance is below the tip width, when a narrow gap cannot be isolated, or when offset topology collapses.
- Every output layer has a stable id, human-readable label, semantic role, side, operation type, units, source ids, nonempty geometry count, validation state and confidence/warnings.
- Reject or prominently mark any handoff with missing required geometry, invalid topology, unclassified drill hits, ambiguous coordinate format or unsupported parser primitives. Never represent an empty layer as a usable operation.

### Proposed modules

```text
src/pcbprep/
  model/            typed IR, units, provenance, diagnostics, DTO schema
  parsers/          gerbonara adapter, X2 interpretation, Excellon normalization
  geometry/         exact primitives, polygonization, precision policy, overlays, offsets
  manufacturing/    board/profile reconstruction, alignment, drill and slot plans,
                    cutter/depth compensation, isolation checks, validation
  services/         job orchestration, preview snapshots, export results
  adapters/
    circuit/        staged KiCad manufacturing export and manifest/revision reader
    design/         versioned structured transfer DTO and Design import protocol
    dxf/            explicit lossy legacy export
  app/              PySide6 UI, preview and project/job interactions
  cli/              standalone file/ZIP input and JSON output
schemas/             versioned JSON Schema for transfer/job manifest
tests/
  parser/ fixtures/ geometry/ manufacturing/ integration_contract/
```

This is a proposal, not implementation work. Final package layout should be reconciled with packaging and the authoritative DemonX Suite integration host in Phase 2 review.

## 7. Integration boundaries and native transfer

### Circuit adapter

Circuit remains the authoring system for native PCB files. Its adapter should request or consume a staged KiCad CLI Gerber X2 + Excellon export, include the project ID/revision, engine/version, file list and hashes, and run PCB Prep as a local process or a narrow versioned JSON protocol from Circuit's main-process adapter. Use argv-based process spawning and an explicit capability/version check, matching Circuit's current secure boundary. Never mutate KiCad source files as part of geometry preparation. If PCB Prep returns revised manufacturing parameters or output manifests, stage them beside outputs and report their provenance to Circuit.

### Design native transfer

The Design adapter should send a schema-versioned DTO over a defined import command/API. The DTO should contain units, origin/orientation/side transforms, board bounds, copper paths and holes, drill/slot records with original diameters/plating class, profile cutouts, operation-role layers, cutter settings and source/hash provenance. Design should map supported linework and closed rings into native `PathShape`/`CircleShape`, create semantically named layers, and return an import summary with entity counts and warnings. Validate coordinate and layer counts before mutation. Store board-side/flip setup and imported provenance in a defined, backward-compatible project extension or PCB import record.

Current Design has no exact arc segment in its shape union and no PCB Prep import API. Therefore the adapter must choose and document a chord tolerance for Design's path format or Design must add native arc support as a separate agreed project. Preserve exact source geometry in the PCB Prep job/package so the transfer approximation is explicit and repeatable. Do not construct toolpaths automatically in Phase 1; a later integration can map prepared layers to Design's existing CNC profile/drill/pocket toolpath editors after the DTO and ownership boundary are approved.

### DXF legacy export

DXF export can remain for Vectric compatibility and visual exchange, with clear layer names and a companion manifest/setup sheet that states the losses: no guaranteed source attributes, drill plating identity, exact arcs where tessellated, processing provenance or depth/tool semantics in the entities. It is an optional terminal adapter and never a required stage between PCB Prep and Design.

## 8. Development phases and acceptance criteria

### Phase 1 — Audit and architecture (this phase)

- Deliver this report for owner review.
- No application implementation. No change to Circuit, Design/CNC or other repositories.
- **Status:** Report prepared; architecture still proposed pending review.

### Phase 2 — Core contracts and corpus baselines

- Approve parser/kernel policy, source data licensing and authoritative Design repo.
- Create fixture manifest and gold baselines from supplied boards plus official Ucamco Gerber/XNC conformance fixtures and clearly licensed real exporter fixtures.
- Define canonical IR, diagnostics, JSON schema, units, precision, coordinate frames, layer semantics, tool model and error policy before UI work.
- Establish parser/geometry verification harness and separate test evidence from manufacturing approval.

### Phase 3 — Parser and reconstruction engine

- Implement pinned Gerbonara adapters for Gerber/X2 and Excellon dialects; support supported attributes and all required aperture/region/arc/clear polarity cases.
- Reconstruct top/bottom copper, board profile and internal cutouts; retain exact primitives and source lineage.
- Parse holes and slots with PTH/NPTH/unknown class, original diameter and tool metadata. Report ambiguity rather than guessing.
- Acceptance: all golden feature counts and hole/slot classes match reviewed reference manifests; units/extents agree within 0.01 mm or the source file's documented quantization when coarser; analytic arc endpoints/radii agree within source precision; no valid feature is removed by arbitrary area filters; no unsupported primitive is silently dropped.

### Phase 4 — Manufacturing prep and geometry QA

- Add supported drill groups, larger profile-bore candidates, slot routing, single/double-sided transforms and alignment-hole workflows.
- Add geometry operation layers and a 30°/0.1 mm flat-tip cutter profile with depth-derived groove widths; support tool and depth selection without assuming one isolation width.
- Acceptance: known vector fixtures preserve topology (components, holes, nesting and connectedness) and pass symmetric-difference and Hausdorff-distance bounds; coordinate transforms round-trip with ≤0.01 mm max error; no contour self-intersects after offsets unless explicitly diagnosed; measured offset distance is within 0.01 mm of requested cutter-center geometry on straight/arc/concave/collapse fixtures; all layers with exportable operations contain entities and have source lineage.

### Phase 5 — Standalone app and saved job/package

- Build a PySide6 standalone workflow on the shared core: open ZIP/files, classify layers with user review, view overlays, adjust transforms/drills/cutter, review warnings, save reproducible job, export JSON and optional DXF.
- Acceptance: project reopen reproduces same content hashes and transforms; all layer IDs/labels stable; empty/unsupported layers blocked from operation; all warnings surfaced in UI and CLI; Windows and Linux packaged environments use pinned dependencies.

### Phase 6 — Design adapter and CNC handoff

- Co-design and implement the versioned structured import contract in the authoritative Design repository under its own approval/branch workflow; import geometry as native shapes/layers with no DXF dependency.
- Add Design-side checks and an end-to-end sample project using the same PCB Prep core output.
- Acceptance: imported geometry count, coordinates, layer names/roles, holes/cutouts and side transforms match the DTO; `.dxd` save/reopen preserves them; CNC path setup uses Design's native CAM/toolpath modules; no G-code is claimed safe until simulated and reviewed.

### Phase 7 — Circuit adapter and suite workflow

- Add staged Circuit manufacturing export handoff with source project/revision hashes, KiCad version and PCB Prep result summary.
- Acceptance: one native Circuit project exports, imports in standalone PCB Prep and through Circuit adapter with equivalent canonical model/hash; source project remains unchanged; stale revisions are rejected or visibly marked; the Design handoff preserves coordinate frames and all required manufacturing entities.

### Phase 8 — Hardening and release readiness

- Fuzz malformed inputs, property-test boolean/offset invariants, verify package provenance/licensing, performance-test complex pours, test Windows/Linux and capture independent visual review from trusted CAM/EDA viewers.
- Use non-destructive staged files, hash provenance, explicit operator sign-off, versioned schemas and rollback. Establish a release checklist and manufacturing test board policy.

### Geometry accuracy protocol (objective checks)

Every golden fixture should record input file hashes, parser/kernel versions, declared units/format, board extents, per-layer primitive and composed-polygon counts, hole/slot table, transform matrix, area, perimeter, component count, interior ring count and a verified reference render. Compare vectors against independent trustworthy output where possible; include both numeric metrics and reviewed overlays. Suggested project target is ≤0.01 mm maximum boundary displacement for CNC-prep vectors, except where source quantization or intentional rasterization requires a stricter stated exception. Keep vector/source quantization distinct from tolerance introduced by polygonization or output serialization.

For fixed precision operations, explicitly report the precision grid and prove that worst-case rounding stays below the target over the largest supported board extents. For boolean outputs, require valid geometry and test symmetric-difference area relative to a known gold result. For offsets, test signed distance on straight/curved boundaries, narrow gaps, sharp/round joins and topology collapses. For import, compare exact DTO and reopened Design geometry using per-feature tolerances and check no missing/extra layers or empty output roles. Visual inspection supplements these checks; screenshots alone do not establish dimensional accuracy.

## 9. Critical risks and mitigations

| Risk | Mitigation |
|---|---|
| Parser reports support but rare file syntax is skipped or misinterpreted | Pin parser, inspect unsupported objects, keep source provenance, official conformance corpus, third-party exporter fixtures, fail visibly on dropped semantics. |
| Numeric robustness/rounding shifts tiny PCB features | Retain source precision; define a bounded precision model; differential GEOS/Clipper experiments; property and golden geometry metrics; no arbitrary speck deletion. |
| Excellon ambiguity or file misclassification | Preserve original file identity and parser mode; require explicit unit/format confirmation when ambiguous; never scale from visual board bounds; keep unknown plating status. |
| Isolation offsets create gouges or erase clearances | Compute cutter footprint from actual geometry/depth; block impossible isolation; report changed topology; simulate tool envelope and verify on coupons before machine use. |
| Circuit, PCB Prep and Design disagree on origin/flip | Versioned frame contract with explicit origin, side, orientation, units and affine transform; source revision hashes; round-trip coordinates and validate registration test board. |
| Design's polygon-only model needs curve flattening | Add agreed chord-error and report it; preserve exact core job; consider separate Design arc enhancement before demanding tighter tolerance. |
| Existing Design CAM feature boundary evolves | Transfer operation intent and geometry, not generated G-code; call stable import API and leave machine toolpath ownership in Design. |
| Component/package dependency maintenance and security | Exact pins/lock, source hashes, provenance review, local environments, license inventory, audited distribution plan. |
| Misleading test confidence | Separate synthetic unit tests, parser conformance, real fixture verification, downstream import and physical machining evidence in reports. |
| ZIP fixture rights or unrelated personal/probe data | Review licensing and contents before extracting/committing; retain only required manufacturing files and hashes. |

## 10. Architectural decisions for owner review

1. **Geometry backend:** approve the proposal to keep Gerbonara + Shapely/GEOS as parser/general overlay basis and evaluate Clipper2 only behind an interface for CNC offsets; or require a different integer/kernel baseline before Phase 2.
2. **Shared core/runtime:** approve Python 3.12+ for the common parser/manufacturing engine, with Electron Circuit invoking a local subprocess/protocol and Design receiving structured DTO; or request a Rust/TypeScript core feasibility comparison.
3. **Authoritative Design repository:** confirm `DemonX-Design-CNC` is the active repo to integrate, despite the adjacent public `DemonX` checkout containing a Design copy.
4. **Transfer contract owner:** decide whether PCB Prep owns a versioned `demonx-pcb-prep` DTO and Design provides a local import command, or whether the contract should live in a DemonX Suite shared schema package.
5. **Fixture inclusion:** approve checking provenance/licensing of the two supplied ZIP datasets, then promoting redacted, hash-pinned copies into a tracked regression corpus.
6. **Tolerance target:** confirm the proposed ≤0.01 mm vector boundary displacement target for CNC-prep geometry, and agree on minimum reportable feature size and coordinate precision grid.
7. **Drilling policy:** decide whether nominal Gerber/Excellon drill values represent finished hole or cutter size for planning; confirm rule for assignment to the supported bit sizes, unsupported holes and >3.1 mm bore candidates. Keep source diameter either way.
8. **Via default:** choose a safe product default for via drilling and copper treatment. The recommendation is to preserve and display vias and require an explicit manufacturing decision, not omit them automatically.
9. **Profile interpretation:** decide the expected behavior for open or ambiguous outline files and whether PCB Prep may infer closure within a tolerance or must require explicit user repair/approval.
10. **Release form:** choose whether standalone UI starts as a Python/PySide6 package or a small Electron shell that launches the shared Python engine; this needs a Windows/Linux packaging spike before freezing.

## Sources checked

- Official Ucamco Gerber specification, grammar, test files, and XNC format downloads (linked above).
- Gerbonara documentation, GitLab release tags and PyPI release metadata (linked above).
- Shapely/GEOS fixed precision documentation (linked above).
- Clipper2 upstream overview and binding documentation (linked above).
- Local adjacent repositories: `../DemonX-Circuit/docs/architecture/DEMONX-CIRCUIT-ARCHITECTURE.md`, `../DemonX-Circuit/docs/architecture/DEMONX-SUITE-HANDOFFS.md`, `../DemonX-Circuit/docs/roadmap/PROTOTYPE-PLAN.md`, `../DemonX-Design-CNC/design/README.md`, `../DemonX-Design-CNC/design/src/core/types.ts`, `../DemonX-Design-CNC/design/src/core/project.ts`, `../DemonX-Design-CNC/design/src/core/dxf.ts`, and `../DemonX-Design-CNC/design/package.json`.

---

**Phase 1 stops here.** The report is proposed for review. Do not begin Phase 2 implementation until the owner has reviewed and approved the architecture decisions.
