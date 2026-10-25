import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from extract_fixtures import safe_member_name
from verify_fixtures import CHORD_ERROR_MM, DRILL_TOLERANCE_MM, classify_diameter, sample_arc


def test_zip_member_paths_reject_traversal_and_platform_paths():
    for unsafe in ("../escape.gbr", "/root.gbr", "C:/root.gbr", "dir\\escape.gbr"):
        with pytest.raises(ValueError):
            safe_member_name(unsafe)
    assert safe_member_name("board/layer.gbr").as_posix() == "board/layer.gbr"


@pytest.mark.parametrize(
    ("diameter", "group"),
    [
        (0.2, "PCB - Drill 0.8mm"),
        (0.8, "PCB - Drill 0.8mm"),
        (0.804, "PCB - Drill 0.8mm"),
        (0.8051, "unassigned"),
        (0.996, "PCB - Drill 1.0mm"),
        (1.104, "PCB - Drill 1.1mm"),
        (1.196, "PCB - Drill 1.2mm"),
        (2.004, "PCB - Drill 2.0mm"),
        (3.004, "PCB - Drill 3.0mm"),
        (3.104, "PCB - Drill 3.1mm"),
        (3.106, "profile-bore candidate"),
        (1.05, "unassigned"),
    ],
)
def test_nominal_drill_grouping(diameter, group):
    assert classify_diameter(diameter, DRILL_TOLERANCE_MM) == group


def test_arc_subdivision_meets_requested_chord_tolerance():
    pts, error = sample_arc(1, 0, 0, 1, 0, 0, False, CHORD_ERROR_MM)
    assert pts[0] == pytest.approx((1, 0))
    assert pts[-1] == pytest.approx((0, 1))
    assert error <= CHORD_ERROR_MM


def test_archives_parsed_and_all_recognized_hits_reconcile():
    result_path = HERE / "results" / "parsed_geometry.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["runContext"]["geometryReferenceStatus"] == "not independently verified"
    assert len(result["boards"]) == 2
    assert sum(len(b["sourceFiles"]) for b in result["boards"]) == 17
    assert sum(len(b["drillFiles"]) for b in result["boards"]) == 5
    for board in result["boards"]:
        reconciliation = board["drillReconciliation"]
        assert reconciliation["reconciles"]
        assert reconciliation["duplicates"] == 0
        assert reconciliation["allParsedHits"] == reconciliation["groupAssignmentCount"]
        assert board["boardWidthMm"] > 0
        assert board["boardHeightMm"] > 0
        assert board["topCopper"]["valid"]
        assert board["bottomCopper"]["valid"]


def test_preliminary_schema_is_well_formed_json():
    schema = HERE / "schema" / "pcb-manufacturing.schema.json"
    parsed = json.loads(schema.read_text(encoding="utf-8"))
    assert parsed["$schema"].endswith("2020-12/schema")
