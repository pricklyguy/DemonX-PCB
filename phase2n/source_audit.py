"""Independent integer audit of absolute X4.5 metric, linear Gerber regions.

No PCB Prep parser, Gerbonara, polygonizer, snapping or inferred edge is used.
This deliberately narrow audit fails on unsupported region interpolation or
coordinate modes. It is an evidence tool, not a general Gerber import service.
Command ordinals and one-based lines refer to the unmodified source text.
"""
from __future__ import annotations

import math
import re
from collections import Counter


def audit_regions(text: str) -> list[dict]:
    if not re.search(r'%FSLAX45Y45\*%', text) or '%MOMM*%' not in text:
        raise ValueError('Audit requires absolute leading-zero X4.5/Y4.5 millimetres')
    x = y = 0
    mode, operation, polarity = 1, None, 'dark'
    active = contour = None
    regions = []
    # Consume extended blocks as blocks: macro bodies must not become commands.
    tokens = re.finditer(r'%[^%]*%|[^%*]+\*', text)
    for ordinal, match in enumerate(tokens, 1):
        raw = match.group().strip()
        line = text.count('\n', 0, match.start() + len(match.group()) - len(match.group().lstrip())) + 1
        c = raw.rstrip('*')
        if raw.startswith('%'):
            if active is not None:
                raise ValueError(f'Extended command inside region at line {line}')
            if raw in ('%LPD*%', '%LPC*%'):
                polarity = 'dark' if raw == '%LPD*%' else 'clear'
            elif raw.startswith(('%FS', '%MO')) and raw not in ('%FSLAX45Y45*%', '%MOMM*%'):
                raise ValueError(f'Coordinate format/unit change at line {line}')
            elif raw.startswith(('%SR', '%AB', '%LM', '%LR', '%LS', '%IP',
                                 '%MI', '%OF', '%SF', '%IR', '%AS', '%IJ', '%LP')):
                raise ValueError(f'Unsupported image/step/transform state at line {line}')
            continue
        if c.startswith('G04'):
            continue
        if c == 'G36':
            if active is not None:
                raise ValueError('Nested region')
            active = {'index': len(regions), 'g36Line': line, 'g36Command': ordinal,
                      'polarity': polarity, 'contours': [], 'commands': []}
            contour = None
            continue
        if c == 'G37':
            if active is None:
                raise ValueError('G37 without region')
            active.update(g37Line=line, g37Command=ordinal)
            regions.append(active)
            active = contour = None
            continue
        for g in re.findall(r'G0?([123])(?!\d)', c):
            mode = int(g)
        if re.search(r'G(?:70|71|90|91)(?!\d)', c):
            raise ValueError(f'Unsupported legacy coordinate state at line {line}')
        ds = re.findall(r'D(\d+)', c)
        if ds and int(ds[-1]) >= 10:
            if active is not None:
                raise ValueError(f'Aperture selection inside region at line {line}')
            continue
        if ds:
            operation = int(ds[-1])
        coords = re.findall(r'([XY])([+-]?\d+)', c)
        if not coords and not ds:
            if active is not None and c not in ('G01', 'G1', 'G02', 'G2', 'G03', 'G3'):
                raise ValueError(f'Unsupported region command at line {line}: {raw}')
            continue
        if active is not None and re.sub(r'(?:G0?[123]|[XY][+-]?\d+|D0?[123])', '', c):
            raise ValueError(f'Unsupported region coordinate syntax at line {line}: {raw}')
        nx, ny = x, y
        for axis, value in coords:
            if axis == 'X':
                nx = int(value)
            else:
                ny = int(value)
        if active is not None:
            record = {'line': line, 'command': ordinal, 'raw': raw, 'mode': mode,
                      'operation': operation, 'startTicks': [x, y], 'endTicks': [nx, ny]}
            active['commands'].append(record)
            if operation == 2:
                contour = None  # A move ends a contour; it does not draw a bridge.
            elif operation == 1:
                if mode != 1:
                    raise ValueError(f'Nonlinear region draw at line {line}')
                if contour is None:
                    contour = {'points': [[x, y]], 'segmentLines': [], 'segmentCommands': []}
                    active['contours'].append(contour)
                contour['points'].append([nx, ny])
                contour['segmentLines'].append(line)
                contour['segmentCommands'].append(ordinal)
            else:
                raise ValueError(f'Invalid region operation at line {line}')
        x, y = nx, ny
    if active is not None:
        raise ValueError('Unterminated region')
    for region in regions:
        for contour in region['contours']:
            pts = contour['points']
            dx, dy = pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1]
            edges = list(zip(map(tuple, pts), map(tuple, pts[1:])))
            counts = Counter(edges)
            contour.update(closedExactly=(dx == dy == 0), deltaTicks=[dx, dy],
                           squaredGapTicks=dx*dx + dy*dy, gapMm=math.hypot(dx, dy)/100000,
                           zeroLengthDraws=sum(a == b for a, b in edges),
                           reverseEdgePairs=sum(min(n, counts[(b, a)]) for (a, b), n in counts.items()
                                                if a < b))
    return regions
