"""Read-only Gerber/Excellon inspection model backed by Phase 2 services.

Parsing, primitive-to-geometry conversion, drill interpretation, region command
scanning, and native-fill path decoding delegate to the existing Phase 2 modules.
This module adds archive safety, an in-memory presentation model, and no CAM logic.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for part in ("phase2a", "phase2d", "phase2f"):
    sys.path.insert(0, str(ROOT / part))

import verify_fixtures as phase2a  # noqa: E402
from extract_fixtures import classify_member, safe_member_name  # noqa: E402
import forensics as phase2d  # noqa: E402
import compare_revision as phase2f  # noqa: E402
from gerbonara import GerberFile  # noqa: E402
from shapely.geometry import LineString, Point, Polygon, shape as shape_from_geojson  # noqa: E402
from shapely.ops import unary_union  # noqa: E402
from phase2l.geometry import CanonicalGeometry, LayerMaterial  # noqa: E402

MAX_MEMBER_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 500 * 1024 * 1024
MAX_RATIO = 250
MAX_ENTRIES = 5000
KNOWN_EXPORTS = {
    "laser-v2.0": {
        "archive": "d17abf51ea793d7151f7cb452db5bc97a0a1a2d1f1859414c1b37a13c884e1c8",
        "bottom": "7ea428faea2d0919adc42e1209fa5d90d7106335a4bd163cd845ec44d903e04d",
        "revision_label": "EasyEDA Standard v2.0 export; native cached fill is same-revision reference evidence",
    },
    "laser-v2.5": {
        "archive": "5e682b600dd19ee798d11830f0867f8cd686853d6a05620b8af174ba9ed3eb33",
        "bottom": "6a6e08f4bf30852202e56e76d6ec43f50bcf564f33ef184e35afa71f4118359c",
        "revision_label": "v2.5 Gerber export; displayed v2.0 native fill is an earlier-revision reference only",
    },
}
REGION_RESULTS = ROOT / "phase2f/results/revision-comparison.json"
NATIVE_V20 = ROOT / "phase2f/fixtures/laser-v2.0-pcb.json"
PHASE2E_RECORDS = ROOT / "phase2e/results/validation-records.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class LayerData:
    name: str
    label: str
    kind: str
    geometry: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    features: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RegionData:
    index: int
    source_file: str
    source_sha256: str
    first_line: int
    last_line: int
    source_points_mm: list[tuple[float, float]]
    closure_start_mm: tuple[float, float]
    closure_end_mm: tuple[float, float]
    polarity: str
    issue: str
    candidate_polygon: Any = None
    native_polygon: Any = None
    native_path_index: int | None = None
    boundary_hausdorff_mm: float | None = None
    symmetric_difference_mm2: float | None = None
    candidate_area_mm2: float | None = None
    native_area_mm2: float | None = None
    closure_length_mm: float = 0.0
    recovery_status: str = "BLOCKED"
    recovery_policy: str | None = None
    source_conforms_202605: bool | None = None
    required_user_action: str | None = None
    discrepancy_geometry: Any = None
    discrepancy_point_mm: tuple[float, float] | None = None
    discrepancy_nearest_point_mm: tuple[float, float] | None = None
    discrepancy_source_line: int | None = None
    discrepancy_source_segment_index: int | None = None
    discrepancy_native_segment_index: int | None = None
    source_commands: tuple[dict[str, Any], ...] = ()
    surviving_closure: Any = None


@dataclass
class BoardDocument:
    archive_path: Path
    archive_sha256: str
    board_id: str
    temp_directory: tempfile.TemporaryDirectory
    extracted_files: list[Path]
    layer_files: list[LayerData]
    top_geometry: Any
    bottom_geometry: Any
    profile_geometry: Any
    hits: list[dict[str, Any]]
    slots: list[dict[str, Any]]
    drill_records: list[dict[str, Any]]
    regions: list[RegionData]
    native_reference_label: str | None
    source_compliance: str
    machining_eligibility: str
    issues: list[str]
    canonical_geometry: CanonicalGeometry | None = None

    @property
    def bounds(self) -> tuple[float, float, float, float] | None:
        geometries = [g for g in (self.top_geometry, self.bottom_geometry, self.profile_geometry)
                      if g is not None and not g.is_empty]
        if not geometries:
            return None
        return unary_union(geometries).bounds

    def close(self) -> None:
        self.temp_directory.cleanup()


def _extract_manufacturing_files(archive: Path, temp_root: Path, progress=None) -> list[Path]:
    """Content-sniff and safely extract manufacturing members only."""
    if progress:
        progress("Checking archive paths and manufacturing members…")
    seen: set[str] = set()
    total = 0
    extracted: list[Path] = []
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        if len(infos) > MAX_ENTRIES:
            raise ValueError(f"Archive has too many entries ({len(infos)} > {MAX_ENTRIES})")
        for info in infos:
            name = info.filename
            safe_name = safe_member_name(name.rstrip("/")) if info.is_dir() else safe_member_name(name)
            key = safe_name.as_posix().casefold()
            if key in seen:
                raise ValueError(f"Duplicate or case-colliding archive member: {name!r}")
            seen.add(key)
            if info.is_dir():
                continue
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise ValueError(f"Symbolic link member is not accepted: {name!r}")
            if info.file_size > MAX_MEMBER_BYTES:
                raise ValueError(f"Member exceeds size limit: {name!r}")
            total += info.file_size
            if total > MAX_TOTAL_BYTES:
                raise ValueError("Archive exceeds total uncompressed size limit")
            if info.file_size and info.compress_size and info.file_size / info.compress_size > MAX_RATIO:
                raise ValueError(f"Member exceeds compression-ratio limit: {name!r}")
            with bundle.open(info) as stream:
                header = stream.read(min(info.file_size, 200_000))
                kind = classify_member(name, header)
                stream.seek(0)
                if kind is None:
                    continue
                destination = temp_root.joinpath(*safe_name.parts)
                resolved = destination.resolve()
                if os.path.commonpath((str(temp_root.resolve()), str(resolved))) != str(temp_root.resolve()):
                    raise ValueError(f"Archive member escapes extraction root: {name!r}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with destination.open("xb") as output:
                    while True:
                        chunk = stream.read(1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > info.file_size or written > MAX_MEMBER_BYTES:
                            raise ValueError(f"Member size exceeded declared limits: {name!r}")
                        output.write(chunk)
                if written != info.file_size:
                    raise ValueError(f"Member size mismatch: {name!r}")
                extracted.append(destination)
    if not extracted:
        raise ValueError("No Gerber or Excellon manufacturing files detected in archive")
    return extracted


def _layer_kind(path: Path, meta: dict[str, Any]) -> tuple[str, str]:
    fn = meta.get("x2FileFunction")
    label = phase2a.layer_function(path.name, fn)
    lower = (path.name + " " + str(fn or "")).lower()
    if "toplayer" in lower or ".gtl" in lower or "copper,l1" in lower or "copper,top" in lower:
        return "top", label
    if "bottomlayer" in lower or ".gbl" in lower or "copper,l2" in lower or "copper,bot" in lower:
        return "bottom", label
    if "outline" in lower or path.suffix.lower() in {".gko", ".gm1", ".gml"} or "profile" in lower:
        return "profile", label
    return "gerber", label


def _features_for_gerber(path: Path) -> list[dict[str, Any]]:
    layer = GerberFile.open(path)
    output: list[dict[str, Any]] = []
    for object_index, obj in enumerate(layer.objects):
        try:
            primitives = list(obj.to_primitives("mm"))
        except Exception as exc:  # keep an explicit diagnostic for unconverted objects
            output.append({"sourceFile": path.name, "objectIndex": object_index,
                           "primitiveType": type(obj).__name__, "error": str(exc)})
            continue
        for primitive_index, primitive in enumerate(primitives):
            geom, sagitta = phase2a.primitive_to_geometry(primitive)
            if geom is None:
                continue
            source_coords = {key: float(getattr(primitive, key)) for key in
                             ("x", "y", "x1", "y1", "x2", "y2", "cx", "cy")
                             if getattr(primitive, key, None) is not None}
            output.append({
                "sourceFile": path.name, "sourceSha256": sha256_file(path),
                "objectIndex": object_index, "primitiveIndex": primitive_index,
                "primitiveType": type(primitive).__name__,
                "semantic": "pad / flash" if type(primitive).__name__ == "Flash" else "copper primitive",
                "polarity": "dark" if bool(getattr(primitive, "polarity_dark", True)) else "clear",
                "boundsMm": list(geom.bounds) if not geom.is_empty else None,
                "sourceCoordinatesMm": source_coords,
                "geometry": geom, "polygonizationSagittaMm": sagitta,
                "lineReference": None,
            })
    return output


def _native_region_evidence(bottom_hash: str, regions: list[dict]) -> tuple[list[RegionData], str | None]:
    known = next((entry for entry in KNOWN_EXPORTS.values() if entry["bottom"] == bottom_hash), None)
    if not known or not regions or not NATIVE_V20.is_file() or not REGION_RESULTS.is_file():
        return [], None
    comparison = json.loads(REGION_RESULTS.read_text(encoding="utf-8"))
    region_map = comparison["nativeCachedCopperFillComparison"]["regions"]
    ring_map = comparison["candidateRingVsNativeCachedFillComparison"]["regions"]
    source_hash = (ROOT / "phase2f/fixtures/extracted/laser-v2.0/Gerber_BottomLayer.GBL")
    source_v20_hash = sha256_file(source_hash) if source_hash.is_file() else ""
    source_v25_hash = next((entry["bottom"] for entry in KNOWN_EXPORTS.values()
                            if entry["revision_label"].startswith("v2.5")), "")
    if bottom_hash not in {source_v20_hash, source_v25_hash}:
        return [], None
    native = json.loads(NATIVE_V20.read_text(encoding="utf-8"))
    paths = phase2f.native_fill_paths(native)
    transform = comparison["coordinateTransformNativeToGerber"]
    forensic_path = ROOT / "phase2g/results/region79-analysis.json"
    forensic = json.loads(forensic_path.read_text(encoding="utf-8")) if forensic_path.is_file() else {}
    max_pair = forensic.get("maximumBoundaryDisplacement", {})
    records: list[RegionData] = []
    for i, raw in enumerate(regions):
        contour = raw["contours"][0]
        points = [(x / phase2d.SCALE, y / phase2d.SCALE) for x, y in contour["points"]]
        start, end = points[0], points[-1]
        candidate = Polygon(points) if len(points) >= 3 else None
        map_row = region_map[i] if i < len(region_map) else {}
        ring_row = ring_map[i] if i < len(ring_map) else {}
        path_ids = map_row.get("nativeCachedFillPathIndicesCoveringEdgeWithin0_005mm", [])
        native_index = path_ids[0] if len(path_ids) == 1 else None
        native_polygon = None
        if native_index is not None and native_index < len(paths):
            coords = [tuple(map(float, phase2f.map_point(p, transform))) for p in paths[native_index]]
            if len(coords) >= 3:
                native_polygon = Polygon(coords)
        discrepancy = (candidate.symmetric_difference(native_polygon)
                       if i == 79 and candidate is not None and native_polygon is not None
                       and candidate.is_valid and native_polygon.is_valid else None)
        point = tuple(max_pair["pointMm"]) if i == 79 and max_pair.get("pointMm") else None
        nearest = tuple(max_pair["nearestPointMm"]) if i == 79 and max_pair.get("nearestPointMm") else None
        max_source_line = forensic.get("maximumBoundaryDisplacement", {}).get("nearestGerberLine") if i == 79 else None
        max_source_segment = forensic.get("maximumBoundaryDisplacement", {}).get("nearestGerberSegmentIndex") if i == 79 else None
        max_native_segment = forensic.get("maximumBoundaryDisplacement", {}).get("nearestNativeSegmentIndex") if i == 79 else None
        polarity = "dark" if i == 0 else "clear"
        hausdorff = ring_row.get("boundaryHausdorffMm")
        difference = ring_row.get("symmetricDifferenceAreaMm2")
        issue = ("BLOCKED — full-ring mismatch; candidate closure only" if hausdorff is not None and hausdorff > 0.005
                 else "PROPOSED — native cached-fill correspondence; not machining-approved")
        records.append(RegionData(
            index=i, source_file="Gerber_BottomLayer.GBL", source_sha256=bottom_hash,
            first_line=raw["g36Line"], last_line=raw["g37Line"], source_points_mm=points,
            source_commands=tuple(raw.get("commands", [])),
            closure_start_mm=end, closure_end_mm=start, polarity=polarity, issue=issue,
            candidate_polygon=candidate, native_polygon=native_polygon, native_path_index=native_index,
            boundary_hausdorff_mm=hausdorff, symmetric_difference_mm2=difference,
            candidate_area_mm2=ring_row.get("candidateAreaMm2"), native_area_mm2=ring_row.get("nativeCachedFillAreaMm2"),
            closure_length_mm=LineString([end, start]).length,
            recovery_status="BLOCKED" if hausdorff is None or hausdorff > 0.005 else "PROPOSED_ONLY",
            discrepancy_geometry=discrepancy,
            discrepancy_point_mm=point,
            discrepancy_nearest_point_mm=nearest,
            discrepancy_source_line=max_source_line,
            discrepancy_source_segment_index=max_source_segment,
            discrepancy_native_segment_index=max_native_segment,
        ))
    return records, known["revision_label"]


def _phase2e_region_records(bottom_hash: str) -> dict[tuple[int, int], dict]:
    if not PHASE2E_RECORDS.is_file():
        return {}
    payload = json.loads(PHASE2E_RECORDS.read_text(encoding="utf-8"))
    return {(row["sourceCommandRange"]["firstLine"], row["sourceCommandRange"]["lastLine"]): row
            for row in payload["records"] if row.get("sourceSha256") == bottom_hash}


def load_archive(archive: Path, progress=None) -> BoardDocument:
    """Load an archive using Phase 2A parser services; source files stay untouched."""
    archive = archive.resolve()
    if not archive.is_file():
        raise FileNotFoundError(archive)
    if progress:
        progress("Opening archive and checking its identity…")
    archive_hash = sha256_file(archive)
    board_id = archive.stem
    # The Phase 2A parser writes a sourceRelativePath relative to its extraction root.
    # Keeping the transient staging folder beneath that root satisfies its existing
    # adapter contract, and TemporaryDirectory removes it when the document closes.
    from extract_fixtures import OUT as PHASE2A_EXTRACTION_ROOT
    temp = tempfile.TemporaryDirectory(prefix="pcbprep-inspect-", dir=PHASE2A_EXTRACTION_ROOT)
    temp_path = Path(temp.name)
    try:
        extracted = _extract_manufacturing_files(archive, temp_path, progress)
        layer_files: list[LayerData] = []
        hits: list[dict[str, Any]] = []
        slots: list[dict[str, Any]] = []
        drill_records: list[dict[str, Any]] = []
        top_parts: list[Any] = []
        bottom_parts: list[Any] = []
        profile_parts: list[Any] = []
        issues: list[str] = []
        bottom_source_hash = ""
        bottom_source_name = ""
        source_regions: list[dict] = []
        total_files = len(extracted)
        for file_index, path in enumerate(extracted, start=1):
            if progress:
                progress(f"Parsing manufacturing file {file_index} of {total_files}: {path.name}")
            kind = classify_member(path.name, path.read_bytes()[:200_000])
            if kind == "gerber":
                meta, geom, profile, unresolved = phase2a.parse_gerber(path, "gerber", board_id)
                layer_kind, label = _layer_kind(path, meta["coordinateMetadata"])
                features = _features_for_gerber(path)
                layer_files.append(LayerData(path.name, label, layer_kind, geom if geom is not None else profile,
                                             {**meta, "unresolvedCount": len(unresolved)}, features))
                if layer_kind == "top" and geom is not None:
                    top_parts.append(geom)
                elif layer_kind == "bottom" and geom is not None:
                    bottom_parts.append(geom)
                    bottom_source_hash = meta["sha256"]
                    bottom_source_name = path.name
                    try:
                        source_regions = phase2d.scan(path.read_text(encoding="ascii"))
                    except Exception as exc:
                        issues.append(f"Region source scan unavailable for {path.name}: {exc}")
                elif layer_kind == "profile" and profile is not None:
                    profile_parts.append(profile)
                if unresolved:
                    issues.append(f"{path.name}: {len(unresolved)} parser geometry warnings or unresolved features")
                if meta.get("explicitTopologyRepairs"):
                    issues.append(f"{path.name}: {len(meta['explicitTopologyRepairs'])} explicit GEOS repair records from Phase 2A parser service")
            elif kind == "excellon":
                meta, file_hits, file_slots = phase2a.parse_excellon(path, "excellon", board_id)
                layer_files.append(LayerData(path.name, f"{meta['platingClassification']} drill / {meta['roleClassification']}",
                                             "drill", None, meta, []))
                hits.extend(file_hits); slots.extend(file_slots); drill_records.append(meta)
                if meta.get("unsupportedObjects"):
                    issues.append(f"{path.name}: {len(meta['unsupportedObjects'])} unsupported drill records")
        if progress:
            progress("Combining parsed layer geometry and checking board regions…")
        top = unary_union(top_parts) if top_parts else None
        bottom = unary_union(bottom_parts) if bottom_parts else None
        profile_geom = unary_union(profile_parts) if profile_parts else None
        regions: list[RegionData] = []
        native_label = None
        if source_regions and bottom_source_hash:
            native_regions, native_label = _native_region_evidence(bottom_source_hash, source_regions)
            if native_regions:
                regions = native_regions
            else:
                audited = _phase2e_region_records(bottom_source_hash)
                for i, raw in enumerate(source_regions):
                    contour = raw["contours"][0]
                    points = [(x / phase2d.SCALE, y / phase2d.SCALE) for x, y in contour["points"]]
                    start, end = points[0], points[-1]
                    audit = audited.get((raw["g36Line"], raw["g37Line"]))
                    proposed = None
                    if audit and audit.get("proposedRecoveryGeometry", {}).get("geometry"):
                        proposed = shape_from_geojson(audit["proposedRecoveryGeometry"]["geometry"])
                    regions.append(RegionData(
                        index=i, source_file=bottom_source_name, source_sha256=bottom_source_hash,
                        first_line=raw["g36Line"], last_line=raw["g37Line"], source_points_mm=points,
                        source_commands=tuple(raw.get("commands", [])),
                        closure_start_mm=end, closure_end_mm=start,
                        polarity=audit.get("polarity", raw["polarity"]) if audit else raw["polarity"],
                        issue=(f"{audit['status']} — {audit['issueClassification']}" if audit else "BLOCKED — no source-specific evidence"),
                        candidate_polygon=proposed, closure_length_mm=LineString([end,start]).length,
                        recovery_status=audit.get("status", "BLOCKED") if audit else "BLOCKED",
                        recovery_policy=audit.get("recoveryPolicyId") if audit else None,
                        source_conforms_202605=audit.get("sourceConforms202605") if audit else (False if start != end else None),
                        required_user_action=audit.get("requiredUserAction") if audit else None,
                    ))
            open_count = sum(r.source_points_mm[0] != r.source_points_mm[-1] for r in regions)
            phase2e_records = _phase2e_region_records(bottom_source_hash)
            strict_issue_count = sum(1 for record in phase2e_records.values()
                                     if record.get("sourceConforms202605") is False)
        else:
            open_count = 0
            strict_issue_count = 0
        if open_count:
            issues.append(f"Bottom copper contains {open_count} open Gerber region contours; source conformity warning")
        if bottom is not None and not bottom.is_empty:
            boundary = bottom.boundary
            for region in regions:
                if region.closure_length_mm:
                    # Exact intersection with the final polygonal boundary:
                    # later dark/clear events may cover all or part of a chord.
                    # No buffer, endpoint motion or tolerance-based snapping.
                    region.surviving_closure = LineString([
                        region.closure_start_mm, region.closure_end_mm]).intersection(boundary)
        if all(g is None or g.is_empty for g in (top, bottom, profile_geom)):
            raise ValueError("Archive was parsed, but no copper or board profile layer was recognized")
        source_compliance = (f"NONCONFORMING — {open_count} open region contour(s)" if open_count
                             else f"WARNING — {strict_issue_count} source region issue(s) in Phase 2E" if strict_issue_count
                             else "No open-region issue detected by this inspection scan")
        eligibility = "BLOCKED — inspection preview only; no manufacturing approval in Phase 2G"
        layer_materials = []
        for name, side, geometry in (("top-copper", "top", top),
                                     ("bottom-copper", "bottom", bottom),
                                     ("board-profile", "board", profile_geom)):
            if geometry is None:
                continue
            source_rows = tuple(sorted((layer.name, str(layer.metadata.get("sha256", "unknown")))
                                       for layer in layer_files if layer.kind == side or
                                       (side == "board" and layer.kind == "profile")))
            feature_records = [feature for layer in layer_files if layer.kind == side or
                               (side == "board" and layer.kind == "profile")
                               for feature in layer.features]
            error_bounds = [feature.get("polygonizationSagittaMm") for feature in feature_records
                            if feature.get("polygonizationSagittaMm") is not None]
            # A viewer's implicit closing chord is a hypothetical fill, even if
            # its polygon is valid. Do not label it verified derived material.
            material_role = "hypothetical" if side == "bottom" and open_count else "verified-derived"
            layer_materials.append(LayerMaterial(name, side, "composed", geometry,
                                                 source_rows, material_role,
                                                 max(error_bounds) if error_bounds else None))
        source_features = tuple({key: feature[key] for key in (
            "sourceFile", "sourceSha256", "objectIndex", "primitiveIndex", "primitiveType",
            "semantic", "polarity", "sourceCoordinatesMm", "polygonizationSagittaMm", "lineReference")
            if key in feature}
            for layer in layer_files if layer.kind in {"top", "bottom", "profile"}
            for feature in layer.features)
        drill_features = tuple(
            {"kind": "circular-hole", "sourceFile": hit.get("sourceFile"),
             "sourceFeatureIndex": hit.get("sourceFeatureIndex"), "xMm": hit.get("xMm"),
             "yMm": hit.get("yMm"), "diameterMm": hit.get("sourceDiameterMm"),
             "plating": hit.get("platingClassification", "unknown"),
             "role": "original"}
            for hit in hits) + tuple(
            {"kind": "routed-slot", "sourceFile": slot.get("sourceFile"),
             "sourceFeatureIndex": slot.get("sourceFeatureIndex"),
             "centerlineMm": slot.get("coordinatesMm", []),
             "diameterMm": slot.get("sourceDiameterMm"),
             "plating": slot.get("platingClassification", "unknown"),
             "role": "original"}
            for slot in slots)
        canonical = CanonicalGeometry(
            "mm", "Gerber source-defined right-handed XY", False, tuple(layer_materials),
            "NONCONFORMING" if open_count else ("UNKNOWN" if strict_issue_count else "VALID"),
            "PARTIAL", "BLOCKED",
            "Phase 2A parser tessellation metadata is retained per source feature; source arcs remain in source objects",
            source_features, drill_features)
        return BoardDocument(archive, archive_hash, board_id, temp, extracted, layer_files, top, bottom,
                             profile_geom, hits, slots, drill_records, regions, native_label,
                             source_compliance, eligibility, issues, canonical)
    except Exception:
        temp.cleanup()
        raise

