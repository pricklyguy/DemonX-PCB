import unittest
import math

from shapely.geometry import LineString, Point

from engine.bridge import PROTOCOL, number, path_data
from phase2l.geometry import VBit


class EngineContractTests(unittest.TestCase):
    def test_protocol_and_manufacturing_status_are_inspection_only(self):
        self.assertEqual(PROTOCOL, "demonx.pcbprep.engine/1")
        self.assertEqual(VBit(30, 0.1).effective_width_mm(0.1), 0.1 + 2 * 0.1 * math.tan(math.radians(15)))

    def test_vbit_width_uses_existing_geometry_calculation(self):
        cutter = VBit(30, 0.1)
        expected = 0.1 + 2 * 0.1 * math.tan(math.radians(15))
        self.assertAlmostEqual(cutter.effective_width_mm(0.1), expected, places=12)

    def test_numeric_inputs_reject_non_finite_and_boolean_values(self):
        self.assertEqual(number("0.2", "SPACING", 0.005, 1), 0.2)
        for value in (True, float("nan"), float("inf"), 2):
            with self.subTest(value=value), self.assertRaises(ValueError):
                number(value, "SPACING", 0.005, 1)

    def test_svg_path_serialization_preserves_coordinate_direction(self):
        self.assertEqual(path_data(LineString([(1, 2), (3, 4)])), "M1,-2L3,-4")

    def test_point_geometry_uses_only_allowlisted_svg_commands(self):
        self.assertEqual(path_data(Point(1, 2)), "M1,-2L1.0001,-2")


if __name__ == "__main__":
    unittest.main()
