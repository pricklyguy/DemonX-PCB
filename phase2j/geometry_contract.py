"""Canonical PCB geometry envelope helpers (draft contract v1.0)."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_bytes(document: dict[str, Any]) -> bytes:
    """Serialize JSON deterministically; reject non-finite values and caller-supplied digest."""
    payload = dict(document)
    payload.pop("contentHash", None)
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return encoded


def content_hash(document: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(document)).hexdigest()


def seal(document: dict[str, Any]) -> dict[str, Any]:
    result = dict(document)
    result["contentHash"] = content_hash(result)
    return result


def validate_status_separation(document: dict[str, Any]) -> None:
    """Enforce that geometry verification cannot silently grant manufacturing eligibility."""
    statuses = document["validation"]
    if statuses["manufacturingEligibility"] not in {"ELIGIBLE", "BLOCKED", "CONDITIONAL"}:
        raise ValueError("INVALID_MANUFACTURING_ELIGIBILITY")
    if statuses["manufacturingEligibility"] == "ELIGIBLE" and (
            statuses["sourceConformance"] != "VALID" or
            statuses["independentGeometryVerification"] != "VERIFIED"):
        raise ValueError("ELIGIBILITY_REQUIRES_VALIDATED_GEOMETRY")
    if document.get("boardCoordinateFrame", {}).get("implicitBottomMirror") is not False:
        raise ValueError("IMPLICIT_BOTTOM_MIRROR_FORBIDDEN")
    if document.get("recovery", {}).get("arbitrarySnapping") is not False:
        raise ValueError("ARBITRARY_SNAPPING_FORBIDDEN")
    claimed = document.get("contentHash")
    if claimed is not None and claimed != content_hash(document):
        raise ValueError("CONTENT_HASH_MISMATCH")
