"""Operation relevance and independent eligibility reporting."""
from __future__ import annotations

from dataclasses import dataclass


OPERATIONS = (
    ("copper-isolation", "Copper isolation"),
    ("drilling", "Drilling"),
    ("outline-cutting", "Board outline cutting"),
    ("full-archive", "Full archive inspection"),
)


def relevant_to_operation(issue: dict, operation: str) -> bool:
    if operation == "full-archive":
        return True
    layer = str(issue.get("layer", "")).casefold()
    kind = str(issue.get("kind", "")).casefold()
    if operation == "copper-isolation":
        return ("copper" in layer or "gerber_bottom" in layer or "gerber_toplayer" in layer
                or kind in {"region", "copper", "isolation"}) and not any(
                    label in layer for label in ("silk", "legend", "mask", "paste", "document"))
    if operation == "drilling":
        return any(label in layer for label in ("drill", "slot", "pth", "npth", "via"))
    if operation == "outline-cutting":
        return any(label in layer for label in ("profile", "outline", "edge.cuts", ".gko", ".gm1", ".gml"))
    return False


@dataclass(frozen=True)
class OperationStatus:
    operation: str
    status: str
    blocking_findings: int
    informational_findings: int
    source_conformance: str
    independent_verification: str


def evaluate_operation_status(operation: str, issues: list[dict], *,
                              source_conformance: str,
                              independent_verification: str) -> OperationStatus:
    relevant = [issue for issue in issues if relevant_to_operation(issue, operation)]
    blocked_categories = {"BLOCKED", "NEEDS VERIFICATION", "CANNOT AUTOMATICALLY REPAIR"}
    blockers = sum(issue.get("category", "").upper() in blocked_categories for issue in relevant)
    info = len(relevant) - blockers
    if blockers:
        status = "BLOCKED"
    elif source_conformance != "VALID" or independent_verification != "VERIFIED":
        status = "NOT VERIFIED"
    else:
        # This phase never promotes actual user archives to production eligibility.
        status = "ELIGIBLE FOR FURTHER REVIEW"
    return OperationStatus(operation, status, blockers, info,
                           source_conformance, independent_verification)
