# Canonical PCB Geometry Contract — Draft 1.0

**Purpose:** Define the single versioned geometry payload shared by PCB Prep inspection, future isolation planning, DemonX Design transfer, and CNC consumption. This is a schema/design proposal only. No receiver, toolpath engine, `.dxd` writer, or manufacturing approval is implemented here.

## 1. Authority and processing pipeline

One shared PCB Prep core owns source parsing, exact command provenance, validation, recovery records, derived material geometry, and content hashing. UI, Circuit adapters, Design transfer, and later machining clients consume immutable core results. A consumer must not re-parse the Gerber or substitute a different fill interpretation. The source command stream is retained alongside any derived geometry. The contract distinguishes source geometry from validated derived geometry and reference-only/candidate geometry.

```text
Gerber / Excellon / native inputs
                ↓
       shared parser + source model
                ↓
 validation + explicit recovery records
                ↓
 canonical PCB geometry payload
       ↙             ↓              ↘
 inspection   isolation planning   Design adapter → CNC
```

## 2. Draft artifacts

- JSON Schema: [`../phase2j/schema/canonical-pcb-geometry.schema.json`](../phase2j/schema/canonical-pcb-geometry.schema.json), Draft 2020-12, schema version `1.0.0`.
- Deterministic serialization, SHA-256, and explicit affine-transform helper: `phase2j/geometry_contract.py`.
- Board-derived example payloads are deliberately not committed. Production payloads will be generated from immutable source identities at runtime.

## 3. Required payload semantics

### Identity and provenance

Every source file has a stable ID, original file name, SHA-256 of the exact file bytes, optional parent archive SHA-256, declared format/units, source coordinate precision, and any known project/export revision. Every feature carries source file/layer identity and, where available, one-based command range, command digest, and source feature IDs. Provenance must survive geometry composition and splitting; one derived component may cite multiple source commands.

### Coordinate frame and sides

Coordinates are millimetres in one explicit, right-handed board frame rooted and oriented as defined by source registration. The top and bottom side transforms are explicit 2×3 affine matrices. During source validation, both normally use identity in the shared source frame. `implicitBottomMirror` is always false. A display or machining-side transform is a named, separately stored operation; it never overwrites source coordinates, and round trips must be tested. No automatic fit, mirror, or offset may conceal source disagreement.

No tolerance-based snapping is allowed in import, composition, or canonical serialization. Any future transformation must declare its matrix, purpose, numeric model, and bounded error, and must preserve original coordinates/provenance separately.

### Geometry types

- Preserve Gerber lines and circular arcs analytically when the source command provides them. Preserve region contour order, polarity, and exact source endpoints. Excellon hits retain tool/diameter and coordinates; slots retain routed centerline/arc path and width or tool semantics.
- A pad/flash retains its source aperture or native pad definition, transform, polarity, and source ID. A trace retains its centerline, aperture, and draw operations.
- Composed copper is explicitly material geometry: polygon or multipolygon components with exterior rings and interior void rings, after Gerber dark/clear polarity composition. Islands remain independent material components. Do not infer copper from boundary linework alone.
- For curved native or source geometry, the exact analytic description remains authoritative. If a consumer only accepts polygonal geometry, include the approximation method and a proven maximum chord deviation. Never silently linearize or use GEOS buffer output as source geometry.
- Unsupported constructs remain in the source model and receive a blocking diagnostic for dependent operations. No feature may disappear because a backend cannot represent it.

### Independent statuses

`sourceConformance` is `VALID`, `NONCONFORMING`, or `UNKNOWN`; `independentGeometryVerification` is `VERIFIED`, `PARTIAL`, or `NOT_VERIFIED`; `manufacturingEligibility` is `ELIGIBLE`, `CONDITIONAL`, or `BLOCKED`. A valid parse or close comparison cannot automatically grant manufacturing eligibility. Eligibility additionally depends on released geometry, tool/cutter model, depth, board setup, side transforms, and operation-specific checks in a later phase. A blocked source feature remains addressable and cannot be included through a default or blanket override.

Recovery records have a versioned policy ID, original command digest, derived geometry digest, exact operation, supporting independent evidence, reviewer/acceptance where applicable, and unresolved-risk state. Source bytes and original commands are immutable. The schema forbids arbitrary snapping and has no generic “repair and continue” state.

### Tolerances and content hash

Each geometry set declares source precision, approximation bound, comparison method, boundary deviation tolerance, and area tolerance. Acceptance checks record actual errors, not only Boolean pass/fail. The default comparison objective is ≤0.005 mm boundary deviation when source precision permits; ≤0.01 mm is only an interim ceiling and does not waive topology/feature checks.

`contentHash` is SHA-256 over UTF-8 JSON using sorted keys, compact separators, non-ASCII preservation, and no NaN/Infinity; `contentHash` itself is excluded from the hashed object. Schema version, source identities, transforms, geometry, statuses, provenance, recovery records, and tolerance metadata all participate. Canonical coordinates are serialized as finite decimal values with a documented quantization policy; Phase 2J does not yet define a production decimal quantizer, so the helper hashes supplied values without changing them.

## 4. Transfer boundary

The Design adapter will map semantic layers and explicit board-frame geometry directly to a native structured JSON interchange. It will not require DXF. DXF remains an optional legacy export that cannot be treated as the authoritative interchange. The Design receiver must validate the schema and content hash, preserve source/reference/derived roles and diagnostics, and reject unknown schema major versions. The future CNC boundary receives only accepted, operation-specific geometry plus tool/setup context; it does not reinterpret raw Gerber or clear blockers.

No `.dxd` files are emitted by this phase.

## 5. Validation status

The schema and deterministic envelope helper have Phase 2J unit coverage for serialization identity, hash mismatch, status separation, implicit mirror prohibition, and snapping prohibition. Phase 2K adds explicit matrix application tests and validates the schema against the Draft 2020-12 meta-schema using the project-local `jsonschema==4.25.1` environment. No production receiver exists.

## 6. Phase 2L internal material adapter (additive; draft)

Phase 2L adds an in-process immutable `CanonicalGeometry` view for the existing PCB Prep inspection and the diagnostic isolation prototype. It does not replace, reinterpret, or migrate the Phase 2J 1.0.0 interchange envelope. Existing 1.0.0 producers and consumers remain unchanged. The adapter serializes normalized material WKB and GeoJSON, source feature references, hole/slot records, explicit source-frame transforms, independent statuses, and approximation metadata to a deterministic internal envelope and SHA-256. A separate Draft 2020-12 schema describes that Phase 2L envelope; it is not the future Design/CNC transfer format.

The additive extension proposal for any future external 1.x interchange is to add optional `sourceFeatures`, `drillFeatures`, and per-layer approximation-bound metadata while retaining every existing required 1.0 field and accepting old 1.0 payloads unchanged. A receiver must ignore or preserve unknown optional 1.x fields according to its compatibility policy. A 2.0 schema/version is required before removing or changing any 1.0 field. This proposal is not yet a production transfer contract.

Current limitation: the inspection adapter obtains composed polygon material from the verified Phase 2A parser/composition path. It preserves source primitive type, coordinates, polarity, file hash and tessellation metadata alongside that material, but is not yet a fully analytic line/arc material kernel. Unsupported or unresolved source interpretations continue to block simulation. No snapping, bottom mirror, or guessed closure is introduced.
