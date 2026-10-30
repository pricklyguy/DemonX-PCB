"""Reproduce a private real-board audit without committing design fixtures.

Run with phase2g/.venv/Scripts/python.exe -m phase2n.run_audit --archive PATH
All extracted bytes, source-command evidence and renders stay in ignored results.
PyGerber's own SVG/raster backend supplies the independent display reference.
The separate PyGerber AST material comparison shares GEOS, not PCB Prep's
region converter; neither comparison proves fabrication intent for open paths.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import zipfile
from collections import Counter
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'phase2g'))
from pcbprep.inspection_model import load_archive
from phase2n.source_audit import audit_regions
from phase2c import verify_phase2c as independent
from pygerber.gerberx3.api.v2 import GerberFile as PG
from gerbonara import GerberFile as GB
from shapely import to_wkb, geos_version_string
from shapely.affinity import translate
from shapely.geometry import Polygon, LineString

OUT = ROOT / 'phase2n/results'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pg_shape(command):
    """Expand macro flashes via PyGerber AST, using its evaluated macro buffer."""
    independent.check_transform(command)
    if type(command).__name__ == 'Flash2' and type(command.aperture).__name__ == 'Macro2':
        events = [(c.transform.polarity.value == 'D', pg_shape(c))
                  for c in command.aperture.command_buffer.commands]
        return translate(independent.ordered_compose(events), *independent.xy(command.flash_point))
    return independent.command_shape(command)


def compare_layer(path, material):
    parsed = PG.from_file(str(path)).parse()
    events = []
    for command in parsed._command_buffer.commands:
        g = pg_shape(command)
        if not g.is_valid:
            # Never silently use the same repair backend as the application.
            raise ValueError(f'Independent AST material requires invalid polygon repair: {path.name}')
        events.append((command.transform.polarity.value == 'D', g))
    reference = independent.ordered_compose(events)
    # Gerber parsing, aperture evaluation and native display are all PyGerber's.
    parsed.render_svg(OUT / f'{path.stem}-pygerber.svg', scale=8)
    parsed.render_raster(OUT / f'{path.stem}-pygerber.png', dpmm=30)
    independent.render_diff(reference, material,
                            f'{path.name}: independent AST vs PCB Prep (diagnostic fill)',
                            OUT / f'{path.stem}-material-comparison.png')
    (OUT / f'{path.stem}-reference.wkb').write_bytes(to_wkb(reference))
    (OUT / f'{path.stem}-pcbprep.wkb').write_bytes(to_wkb(material))
    return {'objectTypes': dict(Counter(type(c).__name__ for c in parsed._command_buffer.commands)),
            'apertureTypes': dict(Counter(type(getattr(c, 'aperture', None)).__name__
                                         for c in parsed._command_buffer.commands)),
            'comparison': independent.metrics_compare(reference, material)}, parsed, events


def region_evidence(path, parsed, events):
    text = path.read_text(encoding='ascii')
    raw = audit_regions(text)
    pg_regions = [c for c in parsed._command_buffer.commands if type(c).__name__ == 'Region2']
    gb_regions = [o for o in GB.open(path).objects if type(o).__name__ == 'Region']
    if len(raw) != len(pg_regions) or len(raw) != len(gb_regions):
        raise ValueError('Source/reference region counts differ')
    evidence = []
    state = Polygon()
    region_states = []
    for command, (dark, g) in zip(parsed._command_buffer.commands, events):
        after = state.union(g) if dark else state.difference(g)
        if type(command).__name__ == 'Region2':
            region_states.append((state, after))
        state = after
    for r, p, g in zip(raw, pg_regions, gb_regions):
        if len(r['contours']) != 1:
            raise ValueError('Library region mapping requires one source contour per region')
        contour = r['contours'][0]
        points = contour['points']
        expected = [(a, b) for a, b in zip(points, points[1:])]
        pg_segments = [([int(Decimal(s.start_point.x.value)*100000),
                         int(Decimal(s.start_point.y.value)*100000)],
                        [int(Decimal(s.end_point.x.value)*100000),
                         int(Decimal(s.end_point.y.value)*100000)])
                       for s in p.command_buffer.commands]
        # Decimal equality is tested before integer conversion, never rounded.
        decimal_exact = all(
            Decimal(v.value)*100000 == n
            for segment, (a, b) in zip(p.command_buffer.commands, expected)
            for v, n in zip((segment.start_point.x, segment.start_point.y,
                             segment.end_point.x, segment.end_point.y), (*a, *b)))
        primitive = next(g.to_primitives('mm'))
        gb_segments = list(primitive.segments)
        float_error = max((abs(v - n/100000)
                           for seg, (a, b) in zip(gb_segments, expected)
                           for v, n in zip((*seg[0], *seg[1]), (*a, *b))), default=0)
        mm = [(x/100000, y/100000) for x, y in points]
        closing = LineString([mm[-1], mm[0]])
        candidate = Polygon(mm)
        before, after = region_states[r['index']]
        evidence.append({**r, 'pygerberSourceSegmentsExactlyEqual': decimal_exact and pg_segments == expected,
                         'gerbonaraSourceSegmentMaxDeltaMm': float_error,
                         'gerbonaraAdditionalSegmentCount': len(gb_segments)-len(expected),
                         'gerbonaraAdditionalSegmentsMm': [[list(s[0]), list(s[1])] for s in gb_segments[len(expected):]],
                         'straightClosureDiagnostic': {
                             'approved': False, 'validPolygon': candidate.is_valid,
                             'crossesOrOverlapsSource': closing.crosses(LineString(mm)) or closing.overlaps(LineString(mm)),
                             'candidate': independent.geom_metrics(candidate),
                             'materialBeforeRegionEvent': independent.geom_metrics(before),
                             'materialAfterRegionEventWithInferredChord': independent.geom_metrics(after),
                             'finalMaterialCopperInsideCandidateMm2': candidate.intersection(state).area,
                             'finalVoidAreaInsideCandidateMm2': candidate.difference(state).area,
                             'closingChordOnFinalBoundaryMm': closing.intersection(state.boundary).length,
                             'note': 'Open source has no defined material topology. Before/after here means ordered material events under an assumed chord, not a proven repair.'}})
    return evidence


def screenshots(document, cases):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from pcbprep.main_window import PcbPrepWindow
    app = QApplication.instance() or QApplication([])
    window = PcbPrepWindow()
    window.resize(1700, 1000)
    window.show()
    window.load_archive(document.archive_path)
    app.processEvents()
    window.fit_board()
    app.processEvents()
    window.grab().save(str(OUT / 'pcbprep-full-board.png'))
    for index in cases:
        window.select_region(index, zoom=True)
        window.advanced_button.setChecked(True)
        app.processEvents()
        window.grab().save(str(OUT / f'pcbprep-region-{index}.png'))
    window.close()
    app.processEvents()


def case_plot(data, material):
    import matplotlib.pyplot as plt
    from shapely.geometry import box
    from shapely.geometry.polygon import orient
    from shapely.plotting import patch_from_polygon
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), dpi=180)
    for ax, index in zip(axes, data['caseIndices']):
        r = data['regions'][index]
        c = r['contours'][0]
        xs, ys = zip(*[(x/100000, y/100000) for x, y in c['points']])
        clip = box(min(xs)-.15, min(ys)-.15, max(xs)+.15, max(ys)+.15)
        clipped = independent.polygonal(material.intersection(clip))
        polygons = [clipped] if clipped.geom_type == 'Polygon' else clipped.geoms
        for polygon in polygons:
            ax.add_patch(patch_from_polygon(orient(polygon), facecolor='#df8d42',
                                           edgecolor='none', alpha=.45))
        ax.plot(xs, ys, color='#008d83', linewidth=1.5, label='Exact source D01 path')
        ax.plot([xs[-1], xs[0]], [ys[-1], ys[0]], '--', color='#a725a7',
                linewidth=2, label='Inferred edge, unapproved')
        ax.scatter([xs[0], xs[-1]], [ys[0], ys[-1]], color='#a725a7', s=15)
        ax.set_xlim(clip.bounds[0], clip.bounds[2])
        ax.set_ylim(clip.bounds[1], clip.bounds[3])
        ax.set_aspect('equal')
        ax.set_title(f'Region {index} / {r["polarity"]}\nGap {c["gapMm"]:.9f} mm')
        ax.set_xlabel('X (mm)')
        ax.set_ylabel('Y (mm)')
        ax.legend(fontsize=7, loc='best')
        ax.grid(alpha=.2)
    fig.suptitle('Actual source paths over final bottom copper; no closure approved')
    fig.tight_layout()
    fig.savefig(OUT / 'three-case-studies.png')
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--photo', type=Path, action='append', default=[])
    parser.add_argument('--screenshots', action='store_true')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    document = load_archive(args.archive)
    try:
        data = {'archive': str(args.archive.resolve()), 'archiveSha256': document.archive_sha256,
                'runtime': {'python': platform.python_version(), 'geos': geos_version_string,
                            **{p: version(p) for p in ('gerbonara', 'pygerber', 'shapely', 'PySide6')}},
                'photos': [{'path': str(p.resolve()), 'sha256': digest(p.read_bytes())} for p in args.photo],
                'files': [], 'layers': {}, 'issues': document.issues,
                'sourceCompliance': document.source_compliance,
                'canonicalRoles': {l.name: l.role for l in document.canonical_geometry.layers},
                'hits': document.hits, 'slots': document.slots,
                'manufacturingEligibility': document.machining_eligibility}
        with zipfile.ZipFile(args.archive) as bundle:
            data['archiveInventory'] = [
                {'name': member.filename, 'bytes': member.file_size,
                 'sha256': digest(bundle.read(member))}
                for member in bundle.infolist() if not member.is_dir()]
        for path in document.extracted_files:
            content = path.read_bytes()
            (OUT / 'inputs').mkdir(exist_ok=True)
            (OUT / 'inputs' / path.name).write_bytes(content)
            data['files'].append({'name': path.name, 'bytes': len(content), 'sha256': digest(content),
                                  'header': content.decode('ascii').splitlines()[:10]})
        for layer in document.layer_files:
            if layer.kind not in ('top', 'bottom'):
                continue
            path = next(p for p in document.extracted_files if p.name == layer.name)
            comparison, parsed, events = compare_layer(path, layer.geometry)
            data['layers'][layer.kind] = comparison
            if layer.kind == 'bottom':
                data['regions'] = region_evidence(path, parsed, events)
        gaps = sorted((c['gapMm'], r['index']) for r in data['regions'] for c in r['contours'] if not c['closedExactly'])
        data['caseIndices'] = [gaps[0][1], gaps[len(gaps)//2][1], gaps[-1][1]]
        data['openContourCount'] = len(gaps)
        data['polarityCounts'] = dict(Counter(r['polarity'] for r in data['regions']))
        data['profileMetrics'] = independent.geom_metrics(document.profile_geometry)
        case_plot(data, document.bottom_geometry)
        if args.screenshots:
            screenshots(document, data['caseIndices'])
        (OUT / 'audit.json').write_text(json.dumps(data, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
        print(json.dumps({k: data[k] for k in ('openContourCount', 'polarityCounts', 'caseIndices', 'layers')}, indent=2))
    finally:
        document.close()


if __name__ == '__main__':
    main()
