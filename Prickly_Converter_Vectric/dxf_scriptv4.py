#!/usr/bin/env python3
"""
Gerber/Excellon to DXF converter for VCarve Pro.

v4 improvements:
- Copper polarity support (LPD/LPC): clear geometry subtracts from dark copper (normal mode)
- Optional isolation contour layer generation (*_ISO)
- More robust Excellon parsing:
  * format override (auto / 2.4 / 2.3 / 3.3 / 2.2)
  * zero suppression override (auto / LZ / TZ)
  * modal coordinate handling (X-only / Y-only drill moves)
  * optional XY offsets
  * candidate auto-selection scored against copper bounds
- Safer defaults:
  * fallback trace width = 0.25 mm
  * include copper regions = True
- NEW: Quarantine layer mode
  * splits copper into TRACE/FLASH/REGION layers per side
  * disables merge/boolean cleanup to preserve source geometry
  * emits _DARK and _CLEAR layers for inspection/manual selection
"""

from __future__ import annotations

import math
import os
import re
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

try:
    import ezdxf
except ImportError as exc:  # pragma: no cover - hard dependency
    raise SystemExit("ERROR: ezdxf is required. Install with: pip install ezdxf") from exc

try:
    from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Point, Polygon
    from shapely.ops import unary_union

    SHAPELY_AVAILABLE = True
except ImportError:
    SHAPELY_AVAILABLE = False


@dataclass
class GerberPoint:
    x: float
    y: float


class ExcellonParser:
    """Parse Excellon drill files with optional format/zero-suppression overrides."""

    def __init__(
        self,
        format_override: str = "auto",
        zero_suppression_override: str = "auto",
        x_offset: float = 0.0,
        y_offset: float = 0.0,
    ) -> None:
        self.drills: List[dict] = []
        self.current_tool: Optional[str] = None
        self.tools: Dict[str, float] = {}

        self.unit = "mm"
        self.format_x = "2.4"
        self.format_y = "2.4"
        self.zero_suppression = "AUTO"  # AUTO / LZ / TZ

        self.copper_bounds: Optional[Tuple[float, float, float, float]] = None

        self.format_override = format_override.strip().lower()
        self.zero_suppression_override = zero_suppression_override.strip().upper()
        self.x_offset = x_offset
        self.y_offset = y_offset

    @staticmethod
    def _clean_line(line: str) -> str:
        return line.strip()

    @staticmethod
    def parse_coordinate(coord_str: str, format_spec: str, zero_suppression: str = "AUTO") -> float:
        """
        Parse Excellon integer coordinate using format and zero suppression.
        format_spec like "2.4" => 2 integer + 4 decimal digits.
        """
        if not coord_str:
            raise ValueError("Empty coordinate")

        if "." in coord_str:
            return float(coord_str)

        sign = -1 if coord_str.startswith("-") else 1
        raw = coord_str.lstrip("+-")

        int_digits, dec_digits = map(int, format_spec.split("."))
        total_digits = int_digits + dec_digits
        z = zero_suppression.upper()

        if z == "LZ":
            raw = raw.zfill(total_digits)
        elif z == "TZ":
            raw = raw.ljust(total_digits, "0")
        elif z == "AUTO":
            # default to LZ-style fill in AUTO for variable-width coordinates
            if len(raw) < total_digits:
                raw = raw.zfill(total_digits)
        # else: unknown mode => leave raw as-is

        value = int(raw) / (10**dec_digits)
        return sign * value

    def _detect_header_hints(self, lines: List[str]) -> None:
        """Best-effort detection of units/format/zero suppression from header text."""
        sample_coords: List[str] = []

        for line in lines[:200]:
            s = self._clean_line(line).upper()

            if "INCH" in s or "MILS" in s:
                self.unit = "inch"
            elif "METRIC" in s or "MM" in s:
                self.unit = "mm"

            if "LZ" in s:
                self.zero_suppression = "LZ"
            elif "TZ" in s:
                self.zero_suppression = "TZ"

            # Common style: ;FILE_FORMAT=2:4 or ;FORMAT=2:4
            m_fmt = re.search(r"(?:FILE_)?FORMAT\s*=?\s*(\d)\s*[:.]\s*(\d)", s)
            if m_fmt:
                self.format_x = self.format_y = f"{m_fmt.group(1)}.{m_fmt.group(2)}"

            # Excellon coordinate samples for heuristic fallback
            if "X" in s and ("Y" in s or "X" in s):
                xm = re.search(r"X([+-]?\d+\.?\d*)", s)
                if xm:
                    sample_coords.append(xm.group(1).replace("+", "").replace("-", ""))

        if sample_coords and "." not in sample_coords[0]:
            digits = len(sample_coords[0])
            if digits >= 6:
                self.format_x = self.format_y = "2.4"
            elif digits == 5:
                self.format_x = self.format_y = "2.3"
            elif digits == 4:
                self.format_x = self.format_y = "2.2"

        if self.zero_suppression_override in ("LZ", "TZ"):
            self.zero_suppression = self.zero_suppression_override
        elif self.zero_suppression_override == "AUTO":
            pass
        else:
            self.zero_suppression = "AUTO"

        if self.format_override != "auto" and re.fullmatch(r"\d\.\d", self.format_override):
            self.format_x = self.format_y = self.format_override

    def _parse_lines(
        self, lines: List[str], format_spec: str, zero_suppression: str
    ) -> Tuple[List[dict], Dict[str, float], str]:
        drills: List[dict] = []
        tools: Dict[str, float] = {}

        current_tool: Optional[str] = None
        unit = self.unit
        incremental = False

        last_x: Optional[float] = None
        last_y: Optional[float] = None

        for raw in lines:
            line = self._clean_line(raw)
            if not line:
                continue

            upper = line.upper()

            if "INCH" in upper or "MILS" in upper:
                unit = "inch"
            elif "METRIC" in upper or "MM" in upper:
                unit = "mm"

            if "ICI,ON" in upper:
                incremental = True
            elif "ICI,OFF" in upper:
                incremental = False

            # Tool definition: T01C0.800
            if upper.startswith("T") and "C" in upper:
                match = re.search(r"T(\d+).*?C([0-9.]+)", upper)
                if match:
                    tool_num = match.group(1)
                    diameter = float(match.group(2))
                    if unit == "inch":
                        diameter *= 25.4
                    tools[tool_num] = diameter
                continue

            # Tool select: T01
            if upper.startswith("T") and "C" not in upper and "X" not in upper and "Y" not in upper:
                if len(upper) <= 6 and upper[1:].isdigit():
                    current_tool = upper[1:]
                continue

            x_match = re.search(r"X([+-]?\d+\.?\d*)", upper)
            y_match = re.search(r"Y([+-]?\d+\.?\d*)", upper)

            if not x_match and not y_match:
                continue

            x_val = None
            y_val = None

            if x_match:
                x_str = x_match.group(1)
                x_val = self.parse_coordinate(x_str, format_spec, zero_suppression)
                if unit == "inch":
                    x_val *= 25.4

            if y_match:
                y_str = y_match.group(1)
                y_val = self.parse_coordinate(y_str, format_spec, zero_suppression)
                if unit == "inch":
                    y_val *= 25.4

            # Modal coordinates (if one axis omitted, reuse previous)
            if x_val is None:
                if last_x is None:
                    continue
                x_val = last_x
            if y_val is None:
                if last_y is None:
                    continue
                y_val = last_y

            if incremental:
                if last_x is None:
                    last_x = 0.0
                if last_y is None:
                    last_y = 0.0
                x_val = last_x + x_val
                y_val = last_y + y_val

            last_x, last_y = x_val, y_val

            diameter = tools.get(current_tool or "", 0.8)
            drills.append(
                {
                    "x": x_val + self.x_offset,
                    "y": y_val + self.y_offset,
                    "diameter": diameter,
                }
            )

        return drills, tools, unit

    def _score_drills_against_copper(self, drills: List[dict]) -> float:
        """
        Higher score is better.
        Uses in-bounds count and scale plausibility against copper bounds when available.
        """
        if not drills:
            return -1e9

        score = float(len(drills))  # baseline

        if not self.copper_bounds or len(drills) < 4:
            return score

        cminx, cmaxx, cminy, cmaxy = self.copper_bounds
        cwidth = max(cmaxx - cminx, 1e-9)
        cheight = max(cmaxy - cminy, 1e-9)

        xs = [d["x"] for d in drills]
        ys = [d["y"] for d in drills]
        dminx, dmaxx = min(xs), max(xs)
        dminy, dmaxy = min(ys), max(ys)
        dwidth = max(dmaxx - dminx, 1e-9)
        dheight = max(dmaxy - dminy, 1e-9)

        # Expanded copper bounds allowance
        margin = max(cwidth, cheight) * 0.05 + 1.0
        in_count = 0
        for d in drills:
            if (
                cminx - margin <= d["x"] <= cmaxx + margin
                and cminy - margin <= d["y"] <= cmaxy + margin
            ):
                in_count += 1

        score += in_count * 10.0

        rx = dwidth / cwidth
        ry = dheight / cheight
        # Penalize unrealistic scale mismatch
        scale_penalty = abs(math.log(max(rx, 1e-9))) + abs(math.log(max(ry, 1e-9)))
        score -= scale_penalty * 8.0

        return score

    def parse_file(self, filename: str) -> List[dict]:
        print(f"  Parsing drill file: {os.path.basename(filename)}")

        with open(filename, "r", encoding="utf-8", errors="ignore") as file:
            lines = file.readlines()

        self._detect_header_hints(lines)

        # Build candidate format/suppression combos
        format_candidates = []
        if self.format_override != "auto" and re.fullmatch(r"\d\.\d", self.format_override):
            format_candidates = [self.format_override]
        else:
            format_candidates = [self.format_x, "2.4", "2.3", "3.3", "2.2"]
        format_candidates = list(dict.fromkeys(format_candidates))  # unique, stable order

        z_candidates = []
        if self.zero_suppression_override in ("LZ", "TZ"):
            z_candidates = [self.zero_suppression_override]
        else:
            z_candidates = [self.zero_suppression, "LZ", "TZ", "AUTO"]
        z_candidates = [z for z in dict.fromkeys(z_candidates) if z in ("LZ", "TZ", "AUTO")]

        best_drills: List[dict] = []
        best_tools: Dict[str, float] = {}
        best_unit = self.unit
        best_fmt = self.format_x
        best_z = self.zero_suppression
        best_score = -1e18

        for fmt in format_candidates:
            for zsup in z_candidates:
                drills, tools, unit = self._parse_lines(lines, fmt, zsup)
                score = self._score_drills_against_copper(drills)
                if score > best_score:
                    best_score = score
                    best_drills = drills
                    best_tools = tools
                    best_unit = unit
                    best_fmt = fmt
                    best_z = zsup

        self.drills = best_drills
        self.tools = best_tools
        self.unit = best_unit
        self.format_x = self.format_y = best_fmt
        self.zero_suppression = best_z

        print(f"    Drill format: {self.format_x}, ZS={self.zero_suppression}, unit={self.unit}")
        print(f"    Holes found: {len(self.drills)}")
        return self.drills


class GerberParser:
    """Lightweight Gerber RS-274X parser for copper geometry extraction (with polarity tracking)."""

    def __init__(self) -> None:
        self.current_x = 0.0
        self.current_y = 0.0
        self.format_x = "2.4"
        self.format_y = "2.4"
        self.unit = "mm"

        self.paths: List[List[GerberPoint]] = []
        self.path_apertures: List[Optional[str]] = []
        self.path_polarities: List[str] = []

        self.current_path: List[GerberPoint] = []
        self.current_path_aperture: Optional[str] = None
        self.current_path_polarity: str = "dark"

        self.apertures: Dict[str, dict] = {}
        self.current_aperture: Optional[str] = None
        self.current_operation = "D02"

        self.flashes: List[dict] = []
        self.regions: List[List[GerberPoint]] = []
        self.region_polarities: List[str] = []

        self.in_region = False
        self.region_points: List[GerberPoint] = []

        self.current_polarity = "dark"  # LPD = dark, LPC = clear
        self.unsupported_macro_count = 0

    @staticmethod
    def parse_coordinate(coord_str: str, format_spec: str) -> float:
        value = int(coord_str)
        _, decimal_digits = map(int, format_spec.split("."))
        return value / (10**decimal_digits)

    def _flush_current_path(self) -> None:
        if self.current_path and len(self.current_path) > 1:
            self.paths.append(self.current_path)
            self.path_apertures.append(self.current_path_aperture or self.current_aperture)
            self.path_polarities.append(self.current_path_polarity)
        self.current_path = []
        self.current_path_aperture = None
        self.current_path_polarity = self.current_polarity

    def _apply_units(self, value: float) -> float:
        return value * 25.4 if self.unit == "inch" else value

    def parse_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return

        upper = line.upper()

        if "FSLAX" in upper or "FSTAX" in upper:
            match = re.search(r"FSL?[AT]X(\d)(\d)Y(\d)(\d)", upper)
            if match:
                self.format_x = f"{match.group(1)}.{match.group(2)}"
                self.format_y = f"{match.group(3)}.{match.group(4)}"
            return

        if "MOIN" in upper:
            self.unit = "inch"
        elif "MOMM" in upper:
            self.unit = "mm"

        if "%LPD" in upper:
            self.current_polarity = "dark"
            return
        if "%LPC" in upper:
            self.current_polarity = "clear"
            return

        # Aperture macro declaration (not fully implemented)
        if upper.startswith("%AM"):
            self.unsupported_macro_count += 1
            return

        if upper.startswith("%ADD"):
            match = re.search(r"%ADD(\d+)([A-Za-z][A-Za-z0-9_]*),([^*]+)", line)
            if match:
                num, kind, params = match.groups()
                kind_u = kind.upper()
                parts = [p.strip() for p in params.split("X") if p.strip()]

                if kind_u.startswith("C"):
                    size = float(parts[0])
                    self.apertures[num] = {"type": "circle", "size": size}

                elif kind_u.startswith("R") or kind_u == "ROUNDRECT":
                    if len(parts) >= 2:
                        w = float(parts[0])
                        h = float(parts[1])
                    else:
                        w = h = float(parts[0])
                    self.apertures[num] = {
                        "type": "rectangle",
                        "size": max(w, h),
                        "width": w,
                        "height": h,
                    }

                elif kind_u.startswith("O"):
                    if len(parts) >= 2:
                        w = float(parts[0])
                        h = float(parts[1])
                    else:
                        w = h = float(parts[0])
                    self.apertures[num] = {
                        "type": "obround",
                        "size": max(w, h),
                        "width": w,
                        "height": h,
                    }

                else:
                    # Unsupported AD kind fallback as circle using first size token
                    try:
                        size = float(parts[0])
                    except Exception:
                        size = 0.5
                    self.apertures[num] = {"type": "circle", "size": size}
            return

        if "G36" in upper:
            self._flush_current_path()
            self.in_region = True
            self.region_points = []
            return

        if "G37" in upper:
            if self.in_region and len(self.region_points) > 2:
                if (
                    self.region_points[0].x != self.region_points[-1].x
                    or self.region_points[0].y != self.region_points[-1].y
                ):
                    self.region_points.append(
                        GerberPoint(self.region_points[0].x, self.region_points[0].y)
                    )
                self.regions.append(self.region_points)
                self.region_polarities.append(self.current_polarity)
            self.in_region = False
            self.region_points = []
            return

        if line.startswith("%"):
            return

        aperture_or_op = re.fullmatch(r"(?:G54)?D(\d+)\*", upper)
        if aperture_or_op:
            code = aperture_or_op.group(1)
            n = int(code)
            if n >= 10:
                self._flush_current_path()
                self.current_aperture = code
            elif n in (1, 2, 3):
                self.current_operation = f"D{n:02d}"
            return

        x_match = re.search(r"X([+-]?\d+)", upper)
        y_match = re.search(r"Y([+-]?\d+)", upper)

        new_x = self.current_x
        new_y = self.current_y

        if x_match:
            new_x = self.parse_coordinate(x_match.group(1), self.format_x)
            new_x = self._apply_units(new_x)

        if y_match:
            new_y = self.parse_coordinate(y_match.group(1), self.format_y)
            new_y = self._apply_units(new_y)

        op_match = re.search(r"D0([123])", upper)
        if op_match:
            self.current_operation = f"D0{op_match.group(1)}"

        op = self.current_operation

        if not x_match and not y_match and op != "D03":
            return

        if op == "D03":
            self._flush_current_path()
            if self.current_aperture and self.current_aperture in self.apertures:
                self.flashes.append(
                    {
                        "x": new_x,
                        "y": new_y,
                        "aperture": self.current_aperture,
                        "polarity": self.current_polarity,
                    }
                )

        elif op == "D02":
            self._flush_current_path()
            if self.in_region:
                self.region_points = [GerberPoint(new_x, new_y)]

        elif op == "D01":
            if self.in_region:
                if not self.region_points:
                    self.region_points = [GerberPoint(self.current_x, self.current_y)]
                self.region_points.append(GerberPoint(new_x, new_y))
            else:
                if not self.current_path:
                    self.current_path = [GerberPoint(self.current_x, self.current_y)]
                    self.current_path_aperture = self.current_aperture
                    self.current_path_polarity = self.current_polarity
                self.current_path.append(GerberPoint(new_x, new_y))

        self.current_x = new_x
        self.current_y = new_y

    def parse_file(self, filename: str):
        print(f"  Parsing copper file: {os.path.basename(filename)}")
        with open(filename, "r", encoding="utf-8", errors="ignore") as file:
            for line in file:
                self.parse_line(line)

        self._flush_current_path()

        print(
            f"    Paths={len(self.paths)}, Flashes={len(self.flashes)}, Regions={len(self.regions)}"
        )
        if self.unsupported_macro_count:
            print(
                f"    Warning: encountered {self.unsupported_macro_count} aperture macro block(s) (%AM)."
                " Full macro rendering is not implemented."
            )

        return (
            self.paths,
            self.flashes,
            self.regions,
            self.path_apertures,
            self.path_polarities,
            self.region_polarities,
            self.apertures,
        )


class DXFExporter:
    """Collect copper/drill geometry and write layered DXF output."""

    def __init__(
        self,
        default_trace_width: float = 0.25,
        isolation_offset: float = 0.2,
        quarantine_mode: bool = False,
    ) -> None:
        self.doc = ezdxf.new("R2010")
        self.msp = self.doc.modelspace()
        self.default_trace_width = default_trace_width
        self.isolation_offset = isolation_offset
        self.quarantine_mode = quarantine_mode

        # layer -> {"dark": [geom...], "clear": [geom...]}
        self.copper_geometries: Dict[str, Dict[str, List]] = {}
        self.drill_geometries: List = []

    def _simplify_polygon(self, poly, tolerance=0.005):
        if not SHAPELY_AVAILABLE:
            return poly
        try:
            simplified = poly.simplify(tolerance, preserve_topology=True)
            if simplified.is_empty:
                return poly
            return simplified
        except Exception:
            return poly

    def _append_geom(self, layer: str, geom, polarity: str = "dark") -> None:
        if geom is None:
            return
        try:
            if geom.is_empty:
                return
        except Exception:
            pass

        p = "clear" if str(polarity).lower() == "clear" else "dark"
        if layer not in self.copper_geometries:
            self.copper_geometries[layer] = {"dark": [], "clear": []}
        self.copper_geometries[layer][p].append(geom)

    def _clean_geom(self, geom):
        if geom is None:
            return None
        try:
            if geom.is_empty:
                return None
            if hasattr(geom, "is_valid") and not geom.is_valid:
                geom = geom.buffer(0)
            if geom.is_empty:
                return None
            return geom
        except Exception:
            return None

    def _iter_polygons(self, geom):
        if geom is None:
            return
        try:
            if geom.is_empty:
                return
        except Exception:
            return

        if isinstance(geom, Polygon):
            yield geom
            return

        if isinstance(geom, MultiPolygon):
            for g in geom.geoms:
                yield g
            return

        if isinstance(geom, GeometryCollection):
            for g in geom.geoms:
                yield from self._iter_polygons(g)
            return

        if hasattr(geom, "geoms"):
            for g in geom.geoms:
                yield from self._iter_polygons(g)

    def add_path_as_polygon(
        self,
        path: List[GerberPoint],
        layer: str,
        trace_width: Optional[float],
        polarity: str = "dark",
    ) -> None:
        if len(path) < 2:
            return

        if not SHAPELY_AVAILABLE:
            # Best-effort fallback without boolean polarity ops
            if polarity == "dark":
                pts = [(p.x, p.y) for p in path]
                self.msp.add_lwpolyline(pts, dxfattribs={"layer": layer})
            return

        width = trace_width if trace_width and trace_width > 0 else self.default_trace_width
        line = LineString([(p.x, p.y) for p in path])
        poly = line.buffer(width / 2.0, cap_style=1, join_style=1)
        poly = self._clean_geom(poly)
        self._append_geom(layer, poly, polarity=polarity)

    def add_region(self, region: List[GerberPoint], layer: str, polarity: str = "dark") -> None:
        if len(region) < 3:
            return

        pts = [(p.x, p.y) for p in region]
        if pts[0] != pts[-1]:
            pts.append(pts[0])

        if SHAPELY_AVAILABLE:
            poly = Polygon(pts)
            poly = self._clean_geom(poly)
            self._append_geom(layer, poly, polarity=polarity)
        else:
            if polarity == "dark":
                self.msp.add_lwpolyline(pts, dxfattribs={"layer": layer, "closed": True})

    def add_outline_region(self, region: List[GerberPoint], layer: str = "BOARD_OUTLINE") -> None:
        if len(region) < 3:
            return
        pts = [(p.x, p.y) for p in region]
        if pts[0] != pts[-1]:
            pts.append(pts[0])
        self.msp.add_lwpolyline(pts, dxfattribs={"layer": layer, "closed": True})

    def _make_obround(self, x: float, y: float, w: float, h: float):
        if not SHAPELY_AVAILABLE:
            return None

        if abs(w - h) < 1e-9:
            return Point(x, y).buffer(w / 2.0, resolution=32)

        if w > h:
            radius = h / 2.0
            half_len = (w - h) / 2.0
            line = LineString([(x - half_len, y), (x + half_len, y)])
            return line.buffer(radius, cap_style=1, join_style=1)

        radius = w / 2.0
        half_len = (h - w) / 2.0
        line = LineString([(x, y - half_len), (x, y + half_len)])
        return line.buffer(radius, cap_style=1, join_style=1)

    def add_flash(self, flash: dict, apertures: dict, layer: str) -> None:
        aperture = apertures.get(flash["aperture"])
        if not aperture:
            return

        x = flash["x"]
        y = flash["y"]
        typ = aperture.get("type")
        polarity = flash.get("polarity", "dark")

        if SHAPELY_AVAILABLE:
            if typ == "circle":
                geom = Point(x, y).buffer(aperture["size"] / 2.0, resolution=32)
            elif typ == "rectangle":
                w = aperture.get("width", aperture["size"])
                h = aperture.get("height", aperture["size"])
                geom = Polygon(
                    [
                        (x - w / 2, y - h / 2),
                        (x + w / 2, y - h / 2),
                        (x + w / 2, y + h / 2),
                        (x - w / 2, y + h / 2),
                    ]
                )
            elif typ == "obround":
                w = aperture.get("width", aperture["size"])
                h = aperture.get("height", aperture["size"])
                geom = self._make_obround(x, y, w, h)
            else:
                geom = Point(x, y).buffer(aperture.get("size", 0.5) / 2.0, resolution=32)

            geom = self._clean_geom(geom)
            self._append_geom(layer, geom, polarity=polarity)
            return

        # no-shapely fallback: draw dark only
        if polarity == "dark":
            size = aperture.get("size", 0.5)
            self.msp.add_circle((x, y), size / 2.0, dxfattribs={"layer": layer})

    def add_drill(self, drill: dict, layer: str = "DRILLS") -> None:
        radius = drill["diameter"] / 2.0
        self.msp.add_circle((drill["x"], drill["y"]), radius, dxfattribs={"layer": layer})

        if SHAPELY_AVAILABLE:
            geom = Point(drill["x"], drill["y"]).buffer(radius, resolution=32)
            geom = self._clean_geom(geom)
            if geom is not None:
                self.drill_geometries.append(geom)

    def add_outline_path(self, path: List[GerberPoint], layer: str = "BOARD_OUTLINE") -> None:
        if len(path) < 2:
            return
        self.msp.add_lwpolyline([(p.x, p.y) for p in path], dxfattribs={"layer": layer})

    def _emit_polygon(self, polygon, layer: str) -> None:
        polygon = self._clean_geom(polygon)
        if polygon is None:
            return

        ext = list(polygon.exterior.coords)
        if len(ext) >= 2:
            self.msp.add_lwpolyline(ext, dxfattribs={"layer": layer, "closed": True})

        for interior in polygon.interiors:
            pts = list(interior.coords)
            if len(pts) >= 2:
                self.msp.add_lwpolyline(pts, dxfattribs={"layer": layer, "closed": True})

    def _union_clean(self, geoms: List):
        cleaned = [self._clean_geom(g) for g in geoms if self._clean_geom(g) is not None]
        if not cleaned:
            return None
        try:
            return self._clean_geom(unary_union(cleaned))
        except Exception:
            out = None
            for g in cleaned:
                out = g if out is None else self._clean_geom(out.union(g))
            return self._clean_geom(out)

    def finalize_copper(self, include_isolation: bool = False) -> None:
        if not SHAPELY_AVAILABLE:
            if include_isolation:
                print("  Warning: isolation generation requires shapely.")
            return

        # Quarantine mode: emit each geometry directly, no union/no diff/no weld/no simplify
        if self.quarantine_mode:
            if include_isolation:
                print("  Note: isolation contours are skipped in quarantine mode.")
            for layer, bucket in self.copper_geometries.items():
                for pol in ("dark", "clear"):
                    out_layer = f"{layer}_{pol.upper()}"
                    for geom in bucket.get(pol, []):
                        geom = self._clean_geom(geom)
                        if geom is None:
                            continue
                        for poly in self._iter_polygons(geom):
                            self._emit_polygon(poly, out_layer)
            return

        weld_eps = 0.0002

        for layer, bucket in self.copper_geometries.items():
            dark_union = self._union_clean(bucket.get("dark", []))
            clear_union = self._union_clean(bucket.get("clear", []))

            if dark_union is None:
                continue

            final_geom = dark_union
            if clear_union is not None:
                try:
                    final_geom = dark_union.difference(clear_union)
                except Exception:
                    pass
            final_geom = self._clean_geom(final_geom)
            if final_geom is None:
                continue

            try:
                final_geom = final_geom.buffer(weld_eps, join_style=1).buffer(-weld_eps, join_style=1)
                final_geom = self._simplify_polygon(final_geom, tolerance=0.005)
            except Exception:
                pass

            # Emit copper result
            for poly in self._iter_polygons(final_geom):
                self._emit_polygon(poly, layer)

            # Emit isolation contour ring
            if include_isolation and self.isolation_offset > 0:
                try:
                    iso = final_geom.buffer(self.isolation_offset, join_style=1).difference(final_geom)
                    iso = self._clean_geom(iso)
                    if iso is not None:
                        iso_layer = f"{layer}_ISO"
                        for poly in self._iter_polygons(iso):
                            self._emit_polygon(poly, iso_layer)
                except Exception:
                    print(f"  Warning: could not generate isolation for layer {layer}")

    def save(self, filename: str) -> None:
        self.doc.saveas(filename)
        print(f"\nDXF saved: {filename}")


def process_pcb_to_dxf(
    file_dict: dict,
    output_file: str,
    use_only_regions: bool = False,
    default_trace_width: float = 0.25,
    isolation_offset: float = 0.10,
    include_isolation: bool = True,
    include_copper_regions: bool = True,
    drill_format: str = "auto",
    drill_zero_suppression: str = "auto",
    drill_x_offset: float = 0.0,
    drill_y_offset: float = 0.0,
    quarantine_layers: bool = False,
) -> None:
    exporter = DXFExporter(
        default_trace_width=default_trace_width,
        isolation_offset=isolation_offset,
        quarantine_mode=quarantine_layers,
    )

    copper_min_x, copper_max_x = float("inf"), float("-inf")
    copper_min_y, copper_max_y = float("inf"), float("-inf")

    def update_bounds(paths, regions):
        nonlocal copper_min_x, copper_max_x, copper_min_y, copper_max_y
        for seq in (paths + regions):
            for p in seq:
                copper_min_x = min(copper_min_x, p.x)
                copper_max_x = max(copper_max_x, p.x)
                copper_min_y = min(copper_min_y, p.y)
                copper_max_y = max(copper_max_y, p.y)

    for side_name, key in (("TOP", "top_copper"), ("BOTTOM", "bottom_copper")):
        if not file_dict.get(key):
            continue

        print(f"\nProcessing {side_name} copper")
        parser = GerberParser()
        (
            paths,
            flashes,
            regions,
            path_apertures,
            path_polarities,
            region_polarities,
            apertures,
        ) = parser.parse_file(file_dict[key])
        update_bounds(paths, regions)

        if quarantine_layers:
            trace_layer = f"{side_name}_COPPER_TRACE"
            region_layer = f"{side_name}_COPPER_REGION"
            flash_layer = f"{side_name}_COPPER_FLASH"
        else:
            trace_layer = f"{side_name}_COPPER"
            region_layer = f"{side_name}_COPPER"
            flash_layer = f"{side_name}_COPPER"

        if not use_only_regions:
            for idx, path in enumerate(paths):
                ap_id = path_apertures[idx] if idx < len(path_apertures) else None
                pol = path_polarities[idx] if idx < len(path_polarities) else "dark"
                trace_width = apertures.get(ap_id, {}).get("size") if ap_id else None
                exporter.add_path_as_polygon(
                    path,
                    layer=trace_layer,
                    trace_width=trace_width,
                    polarity=pol,
                )

        if include_copper_regions:
            for idx, region in enumerate(regions):
                pol = region_polarities[idx] if idx < len(region_polarities) else "dark"
                exporter.add_region(region, layer=region_layer, polarity=pol)

        for flash in flashes:
            exporter.add_flash(flash, apertures, layer=flash_layer)

    if file_dict.get("board_outline"):
        print("\nProcessing board outline")
        parser = GerberParser()
        (
            paths,
            _flashes,
            regions,
            _path_apertures,
            _path_polarities,
            _region_polarities,
            _apertures,
        ) = parser.parse_file(file_dict["board_outline"])
        for path in paths:
            exporter.add_outline_path(path)
        for region in regions:
            exporter.add_outline_region(region, layer="BOARD_OUTLINE")

    if copper_min_x < float("inf"):
        print(
            f"\nCopper bounds: X=[{copper_min_x:.3f}, {copper_max_x:.3f}], "
            f"Y=[{copper_min_y:.3f}, {copper_max_y:.3f}]"
        )

    all_drills: List[dict] = []
    for drill_file in file_dict.get("drills", []):
        parser = ExcellonParser(
            format_override=drill_format,
            zero_suppression_override=drill_zero_suppression,
            x_offset=drill_x_offset,
            y_offset=drill_y_offset,
        )
        if copper_min_x < float("inf"):
            parser.copper_bounds = (copper_min_x, copper_max_x, copper_min_y, copper_max_y)
        all_drills.extend(parser.parse_file(drill_file))

    for drill in all_drills:
        exporter.add_drill(drill)

    exporter.finalize_copper(include_isolation=include_isolation)
    exporter.save(output_file)


def detect_files(gerber_dir: str) -> dict:
    files = {"top_copper": None, "bottom_copper": None, "board_outline": None, "drills": []}

    # Explicitly excluded non-copper suffixes
    excluded_suffixes = (
        ".gto", ".gbo",  # silkscreen
        ".gts", ".gbs",  # solder mask
        ".gtp", ".gbp",  # paste
        ".gm2", ".gm3", ".gm4",
    )

    def is_top_copper(name: str) -> bool:
        return (
            name.endswith((".gtl", ".cmp", ".top", "f_cu.gbr"))
            or re.search(r"(^|[_\-.])f[_\-.]?cu([_\-.]|$)", name) is not None
        )

    def is_bottom_copper(name: str) -> bool:
        return (
            name.endswith((".gbl", ".sol", ".bot", "b_cu.gbr"))
            or re.search(r"(^|[_\-.])b[_\-.]?cu([_\-.]|$)", name) is not None
        )

    def is_outline(name: str) -> bool:
        return (
            name.endswith((".gko", ".gm1", ".gml", "edge_cuts.gbr"))
            or "edge.cuts" in name
            or "edge_cuts" in name
            or "outline" in name
        )

    for filename in os.listdir(gerber_dir):
        filepath = os.path.join(gerber_dir, filename)
        name = filename.lower()

        if name.endswith((".drl", ".xln")) or ("drill" in name and name.endswith(".txt")):
            files["drills"].append(filepath)
            continue

        if name.endswith(excluded_suffixes):
            continue

        if files["top_copper"] is None and is_top_copper(name):
            files["top_copper"] = filepath
        elif files["bottom_copper"] is None and is_bottom_copper(name):
            files["bottom_copper"] = filepath
        elif files["board_outline"] is None and is_outline(name):
            files["board_outline"] = filepath

    print("\nAuto-detect selection:")
    print("  TOP:", files["top_copper"])
    print("  BOTTOM:", files["bottom_copper"])
    print("  OUTLINE:", files["board_outline"])
    print("  DRILLS:", files["drills"])

    return files


def run_cli() -> None:
    if len(sys.argv) < 2:
        print("Usage: python dxf_scriptv3.py <gerber_directory> [output.dxf]")
        raise SystemExit(1)

    gerber_dir = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "pcb_complete.dxf"

    files = detect_files(gerber_dir)
    if not any([files["top_copper"], files["bottom_copper"], files["board_outline"], files["drills"]]):
        raise SystemExit("No Gerber/Excellon files detected.")

    process_pcb_to_dxf(files, output_file)


def launch_gui() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("Gerber to DXF by The Prickly Guy")
    root.geometry("980x700")
    root.minsize(920, 640)

    COLORS = {
        "bg": "#111111",
        "panel": "#1a1a1a",
        "panel2": "#232323",
        "panel3": "#2b2b2b",
        "text": "#f4efe7",
        "muted": "#c9b8a3",
        "accent": "#c97a2b",
        "accent_hover": "#de8c38",
        "accent_press": "#a55f1b",
        "accent_dark": "#7f4814",
        "border": "#3a2a1d",
        "entry": "#0f0f0f",
        "soft": "#353535",
    }

    root.configure(bg=COLORS["bg"])
    style = ttk.Style()
    style.theme_use("clam")

    default_font = ("Segoe UI", 10)
    title_font = ("Segoe UI Semibold", 20)
    subtitle_font = ("Segoe UI", 10)
    section_font = ("Segoe UI Semibold", 10)
    small_font = ("Segoe UI", 9)

    style.configure(
        "Dark.TEntry",
        fieldbackground=COLORS["entry"],
        background=COLORS["entry"],
        foreground=COLORS["text"],
        bordercolor=COLORS["border"],
        lightcolor=COLORS["border"],
        darkcolor=COLORS["border"],
        insertcolor=COLORS["text"],
        padding=7,
        relief="flat",
    )
    style.configure(
        "Dark.TCombobox",
        fieldbackground=COLORS["entry"],
        background=COLORS["entry"],
        foreground=COLORS["text"],
        bordercolor=COLORS["border"],
        lightcolor=COLORS["border"],
        darkcolor=COLORS["border"],
        arrowsize=14,
    )

    vars_ = {
        "top": tk.StringVar(),
        "bottom": tk.StringVar(),
        "outline": tk.StringVar(),
        "drills": tk.StringVar(),
        "output": tk.StringVar(value=os.path.abspath("pcb_complete.dxf")),

        "isolation": tk.DoubleVar(value=0.10),
        "default_width": tk.DoubleVar(value=0.25),
        "regions_only": tk.BooleanVar(value=False),
        "include_copper_regions": tk.BooleanVar(value=True),
        "write_iso": tk.BooleanVar(value=True),
        "quarantine_layers": tk.BooleanVar(value=False),

        "drill_format": tk.StringVar(value="auto"),
        "drill_zs": tk.StringVar(value="auto"),
        "drill_x_offset": tk.DoubleVar(value=0.0),
        "drill_y_offset": tk.DoubleVar(value=0.0),
    }

    status_var = tk.StringVar(value="Ready. Choose files or auto-detect a Gerber folder.")

    def set_status(message: str) -> None:
        status_var.set(message)
        root.update_idletasks()

    def make_button(parent, text, command, variant="secondary", width=None):
        if variant == "primary":
            bg = COLORS["accent"]
            fg = "#ffffff"
            hover = COLORS["accent_hover"]
            pressed = COLORS["accent_press"]
            border = COLORS["accent_dark"]
        elif variant == "ghost":
            bg = COLORS["bg"]
            fg = COLORS["muted"]
            hover = COLORS["panel2"]
            pressed = COLORS["panel3"]
            border = COLORS["soft"]
        else:
            bg = COLORS["panel3"]
            fg = COLORS["text"]
            hover = "#343434"
            pressed = "#2b2b2b"
            border = COLORS["border"]

        btn = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=hover,
            activeforeground=fg,
            relief="flat",
            bd=0,
            padx=14,
            pady=8,
            font=("Segoe UI Semibold", 10) if variant == "primary" else ("Segoe UI", 10),
            cursor="hand2",
            width=width,
            highlightthickness=1,
            highlightbackground=border,
            highlightcolor=border,
        )

        def on_enter(_event):
            btn.configure(bg=hover)

        def on_leave(_event):
            btn.configure(bg=bg)

        def on_press(_event):
            btn.configure(bg=pressed)

        def on_release(_event):
            if btn.winfo_containing(root.winfo_pointerx(), root.winfo_pointery()) == btn:
                btn.configure(bg=hover)
            else:
                btn.configure(bg=bg)

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        btn.bind("<ButtonPress-1>", on_press)
        btn.bind("<ButtonRelease-1>", on_release)
        return btn

    def make_check(parent, text, variable):
        return tk.Checkbutton(
            parent,
            text=text,
            variable=variable,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            activebackground=COLORS["panel"],
            activeforeground=COLORS["text"],
            selectcolor=COLORS["panel2"],
            bd=0,
            highlightthickness=0,
            font=default_font,
            cursor="hand2",
        )

    def browse_file(target: str, title: str):
        path = filedialog.askopenfilename(title=title)
        if path:
            vars_[target].set(path)
            set_status(f"Loaded {os.path.basename(path)}")

    def browse_drills():
        paths = filedialog.askopenfilenames(
            title="Select drill files",
            filetypes=[("Drill files", "*.drl *.xln *.txt"), ("All files", "*.*")],
        )
        if paths:
            vars_["drills"].set(";".join(paths))
            set_status(f"Loaded {len(paths)} drill file(s)")

    def autodetect():
        folder = filedialog.askdirectory(title="Select Gerber folder")
        if not folder:
            return
        found = detect_files(folder)
        vars_["top"].set(found.get("top_copper") or "")
        vars_["bottom"].set(found.get("bottom_copper") or "")
        vars_["outline"].set(found.get("board_outline") or "")
        vars_["drills"].set(";".join(found.get("drills") or []))
        vars_["output"].set(os.path.join(folder, "pcb_complete.dxf"))

        found_count = sum(
            1 for item in [
                found.get("top_copper"),
                found.get("bottom_copper"),
                found.get("board_outline"),
            ] if item
        ) + len(found.get("drills") or [])

        set_status(f"Auto-detected files in {os.path.basename(folder)} ({found_count} item(s))")

    def clear_paths():
        vars_["top"].set("")
        vars_["bottom"].set("")
        vars_["outline"].set("")
        vars_["drills"].set("")
        vars_["output"].set(os.path.abspath("pcb_complete.dxf"))
        set_status("Cleared selected files.")

    def export_now():
        drills = [d for d in vars_["drills"].get().split(";") if d]
        file_dict = {
            "top_copper": vars_["top"].get() or None,
            "bottom_copper": vars_["bottom"].get() or None,
            "board_outline": vars_["outline"].get() or None,
            "drills": drills,
        }

        if not any([
            file_dict["top_copper"],
            file_dict["bottom_copper"],
            file_dict["board_outline"],
            file_dict["drills"],
        ]):
            messagebox.showerror("Missing files", "Please select at least one Gerber or drill file.", parent=root)
            set_status("Export blocked: no files selected.")
            return

        try:
            set_status("Exporting DXF...")
            process_pcb_to_dxf(
                file_dict=file_dict,
                output_file=vars_["output"].get(),
                use_only_regions=vars_["regions_only"].get(),
                default_trace_width=vars_["default_width"].get(),
                isolation_offset=vars_["isolation"].get(),
                include_isolation=vars_["write_iso"].get(),
                include_copper_regions=vars_["include_copper_regions"].get(),
                drill_format=vars_["drill_format"].get(),
                drill_zero_suppression=vars_["drill_zs"].get(),
                drill_x_offset=vars_["drill_x_offset"].get(),
                drill_y_offset=vars_["drill_y_offset"].get(),
                quarantine_layers=vars_["quarantine_layers"].get(),
            )
            set_status(f"Export complete: {os.path.basename(vars_['output'].get())}")
            messagebox.showinfo("Done", f"DXF exported:\n{vars_['output'].get()}", parent=root)
        except Exception as exc:
            set_status("Export failed.")
            messagebox.showerror("Export failed", str(exc), parent=root)

    def add_file_row(parent, row, label, key, button_text, callback):
        lbl = tk.Label(parent, text=label, bg=COLORS["panel"], fg=COLORS["text"], font=default_font, anchor="w")
        lbl.grid(row=row, column=0, sticky="w", pady=7)

        entry = ttk.Entry(parent, textvariable=vars_[key], style="Dark.TEntry", width=78)
        entry.grid(row=row, column=1, sticky="ew", padx=12)

        btn = make_button(parent, button_text, callback, variant="secondary", width=11)
        btn.grid(row=row, column=2, sticky="e")

    root.bind("<Control-e>", lambda _e: export_now())
    root.bind("<Control-d>", lambda _e: autodetect())
    root.bind("<Control-l>", lambda _e: clear_paths())
    root.bind("<Escape>", lambda _e: root.destroy())

    app = tk.Frame(root, bg=COLORS["bg"], padx=16, pady=14)
    app.pack(fill="both", expand=True)

    top_bar = tk.Frame(app, bg=COLORS["accent"], height=3)
    top_bar.pack(fill="x", pady=(0, 10))
    top_bar.pack_propagate(False)

    header = tk.Frame(
        app,
        bg=COLORS["panel2"],
        padx=16,
        pady=14,
        highlightthickness=1,
        highlightbackground=COLORS["border"],
    )
    header.pack(fill="x", pady=(0, 14))

    tk.Label(
        header,
        text="Gerber to DXF by The Prickly Guy",
        bg=COLORS["panel2"],
        fg=COLORS["text"],
        font=title_font,
        anchor="w",
    ).grid(row=0, column=0, sticky="w")

    tk.Label(
        header,
        text="Polarity + isolation + drill parsing + quarantine copper mode",
        bg=COLORS["panel2"],
        fg=COLORS["muted"],
        font=subtitle_font,
        anchor="w",
    ).grid(row=1, column=0, sticky="w", pady=(4, 0))

    badge = tk.Label(
        header,
        text="CNC APP v4",
        bg=COLORS["accent_dark"],
        fg="#ffffff",
        font=("Segoe UI Semibold", 9),
        padx=10,
        pady=4,
    )
    badge.grid(row=0, column=1, rowspan=2, sticky="e", padx=(12, 0))
    header.columnconfigure(0, weight=1)

    files_frame = tk.LabelFrame(
        app,
        text="Project files",
        bg=COLORS["panel"],
        fg=COLORS["accent"],
        font=section_font,
        padx=14,
        pady=12,
        bd=1,
        relief="solid",
        highlightbackground=COLORS["border"],
    )
    files_frame.pack(fill="x", pady=(0, 12))

    add_file_row(files_frame, 0, "Top copper", "top", "Browse", lambda: browse_file("top", "Select top copper Gerber"))
    add_file_row(files_frame, 1, "Bottom copper", "bottom", "Browse", lambda: browse_file("bottom", "Select bottom copper Gerber"))
    add_file_row(files_frame, 2, "Board outline", "outline", "Browse", lambda: browse_file("outline", "Select board outline Gerber"))

    tk.Label(files_frame, text="Drill files", bg=COLORS["panel"], fg=COLORS["text"], font=default_font).grid(
        row=3, column=0, sticky="w", pady=7
    )
    ttk.Entry(files_frame, textvariable=vars_["drills"], style="Dark.TEntry", width=78).grid(
        row=3, column=1, sticky="ew", padx=12
    )
    make_button(files_frame, "Select", browse_drills, variant="secondary", width=11).grid(row=3, column=2, sticky="e")

    tk.Label(files_frame, text="Output DXF", bg=COLORS["panel"], fg=COLORS["text"], font=default_font).grid(
        row=4, column=0, sticky="w", pady=7
    )
    ttk.Entry(files_frame, textvariable=vars_["output"], style="Dark.TEntry", width=78).grid(
        row=4, column=1, sticky="ew", padx=12
    )
    make_button(
        files_frame,
        "Save as",
        lambda: vars_["output"].set(
            filedialog.asksaveasfilename(defaultextension=".dxf", filetypes=[("DXF", "*.dxf")])
            or vars_["output"].get()
        ),
        variant="secondary",
        width=11,
    ).grid(row=4, column=2, sticky="e")

    files_frame.columnconfigure(1, weight=1)

    opts = tk.LabelFrame(
        app,
        text="Processing options",
        bg=COLORS["panel"],
        fg=COLORS["accent"],
        font=section_font,
        padx=14,
        pady=12,
        bd=1,
        relief="solid",
        highlightbackground=COLORS["border"],
    )
    opts.pack(fill="x", pady=(0, 12))

    # Row 0
    tk.Label(opts, text="Isolation offset (mm)", bg=COLORS["panel"], fg=COLORS["text"], font=default_font).grid(
        row=0, column=0, sticky="w", pady=(0, 8)
    )
    ttk.Entry(opts, textvariable=vars_["isolation"], style="Dark.TEntry", width=12).grid(
        row=0, column=1, sticky="w", padx=(8, 24), pady=(0, 8)
    )

    tk.Label(opts, text="Fallback trace width (mm)", bg=COLORS["panel"], fg=COLORS["text"], font=default_font).grid(
        row=0, column=2, sticky="w", pady=(0, 8)
    )
    ttk.Entry(opts, textvariable=vars_["default_width"], style="Dark.TEntry", width=12).grid(
        row=0, column=3, sticky="w", padx=(8, 0), pady=(0, 8)
    )

    # Row 1: drill parse controls
    tk.Label(opts, text="Drill format", bg=COLORS["panel"], fg=COLORS["text"], font=default_font).grid(
        row=1, column=0, sticky="w", pady=(0, 8)
    )
    ttk.Combobox(
        opts,
        textvariable=vars_["drill_format"],
        values=("auto", "2.4", "2.3", "3.3", "2.2"),
        state="readonly",
        width=10,
        style="Dark.TCombobox",
    ).grid(row=1, column=1, sticky="w", padx=(8, 24), pady=(0, 8))

    tk.Label(opts, text="Drill zero suppression", bg=COLORS["panel"], fg=COLORS["text"], font=default_font).grid(
        row=1, column=2, sticky="w", pady=(0, 8)
    )
    ttk.Combobox(
        opts,
        textvariable=vars_["drill_zs"],
        values=("auto", "LZ", "TZ"),
        state="readonly",
        width=10,
        style="Dark.TCombobox",
    ).grid(row=1, column=3, sticky="w", padx=(8, 0), pady=(0, 8))

    # Row 2: drill offsets
    tk.Label(opts, text="Drill X offset (mm)", bg=COLORS["panel"], fg=COLORS["text"], font=default_font).grid(
        row=2, column=0, sticky="w", pady=(0, 8)
    )
    ttk.Entry(opts, textvariable=vars_["drill_x_offset"], style="Dark.TEntry", width=12).grid(
        row=2, column=1, sticky="w", padx=(8, 24), pady=(0, 8)
    )

    tk.Label(opts, text="Drill Y offset (mm)", bg=COLORS["panel"], fg=COLORS["text"], font=default_font).grid(
        row=2, column=2, sticky="w", pady=(0, 8)
    )
    ttk.Entry(opts, textvariable=vars_["drill_y_offset"], style="Dark.TEntry", width=12).grid(
        row=2, column=3, sticky="w", padx=(8, 0), pady=(0, 8)
    )

    # Row 3+: toggles
    make_check(opts, "Include copper fill regions", vars_["include_copper_regions"]).grid(
        row=3, column=0, columnspan=2, sticky="w", pady=(4, 0)
    )
    make_check(opts, "Generate isolation contour layers (*_ISO)", vars_["write_iso"]).grid(
        row=3, column=2, columnspan=2, sticky="w", pady=(4, 0)
    )
    make_check(opts, "Use regions only (ignore stroke traces)", vars_["regions_only"]).grid(
        row=4, column=0, columnspan=4, sticky="w", pady=(8, 0)
    )
    make_check(opts, "Quarantine copper layers (no merge/boolean cleanup)", vars_["quarantine_layers"]).grid(
        row=5, column=0, columnspan=4, sticky="w", pady=(8, 0)
    )

    actions = tk.Frame(app, bg=COLORS["bg"])
    actions.pack(fill="x", pady=(2, 8))

    left_actions = tk.Frame(actions, bg=COLORS["bg"])
    left_actions.pack(side="left")

    right_actions = tk.Frame(actions, bg=COLORS["bg"])
    right_actions.pack(side="right")

    make_button(left_actions, "Auto-detect folder", autodetect, variant="secondary").pack(side="left")
    tk.Frame(left_actions, bg=COLORS["bg"], width=8).pack(side="left")
    make_button(left_actions, "Clear", clear_paths, variant="ghost", width=10).pack(side="left")
    make_button(right_actions, "Export DXF", export_now, variant="primary", width=14).pack(side="right")

    status_frame = tk.Frame(
        app,
        bg=COLORS["panel2"],
        padx=12,
        pady=8,
        highlightthickness=1,
        highlightbackground=COLORS["border"],
    )
    status_frame.pack(fill="x", pady=(8, 0))

    tk.Label(
        status_frame,
        textvariable=status_var,
        bg=COLORS["panel2"],
        fg=COLORS["muted"],
        font=small_font,
        anchor="w",
    ).pack(side="left", fill="x", expand=True)

    tk.Label(
        status_frame,
        text="Ctrl+D Auto-detect   •   Ctrl+E Export   •   Ctrl+L Clear   •   Esc Exit",
        bg=COLORS["panel2"],
        fg=COLORS["muted"],
        font=small_font,
        anchor="e",
    ).pack(side="right")

    root.mainloop()


if __name__ == "__main__":
    if "--gui" in sys.argv or len(sys.argv) == 1:
        launch_gui()
    else:
        run_cli()