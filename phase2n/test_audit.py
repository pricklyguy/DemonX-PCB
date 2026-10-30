"""Public authored semantics tests and opt-in private archive acceptance.

Set DEMONX_PHASE2N_ARCHIVE to the owner-approved manufacturing ZIP. No archive
name, hash, source coordinates, or board-derived expected geometry lives here.
"""
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'phase2g'))
from pcbprep.inspection_model import load_archive, phase2d
from phase2n.source_audit import audit_regions
from phase2m.repair import propose_closure
from phase2l.geometry import eligibility_for_simulation

HEADER = '%FSLAX45Y45*%\n%MOMM*%\n%ADD10C,0.1*%\nD10*\n'


def region(points, polarity='D'):
    return f'%LP{polarity}*%\nG36*\nG01*\n' + ''.join(
        f'X{x}Y{y}D0{2 if i == 0 else 1}*\n' for i, (x, y) in enumerate(points)) + 'G37*\n'


class IntegerAuditTests(unittest.TestCase):
    def test_exact_gap_and_source_location_without_inferred_segment(self):
        for ticks in (1, 3000, 70000):
            points = [(0, 0), (1000000, 0), (1000000, 1000000), (0, ticks)]
            r = audit_regions(HEADER + region(points) + 'M02*')[0]
            c = r['contours'][0]
            self.assertEqual(c['points'], [list(p) for p in points])
            self.assertEqual(c['squaredGapTicks'], ticks*ticks)
            self.assertFalse(c['closedExactly'])
            self.assertEqual(len(c['segmentLines']), 3)
            self.assertEqual(r['commands'][0]['line'], r['g36Line']+2)

    def test_cutins_and_zero_length_are_preserved_not_mistaken_for_gaps(self):
        points = [(0,0),(1000,0),(1000,1000),(0,1000),(0,500),
                  (300,500),(300,700),(700,700),(700,300),(300,300),
                  (300,500),(0,500),(0,0),(0,0)]
        c = audit_regions(HEADER + region(points))[0]['contours'][0]
        self.assertTrue(c['closedExactly'])
        self.assertEqual(c['reverseEdgePairs'], 1)
        self.assertEqual(c['zeroLengthDraws'], 1)

    def test_d02_move_only_does_not_create_phantom_contour_or_bridge(self):
        text = HEADER+'G36*\nX0Y0D02*\nX100Y100D02*\nX200Y100D01*\nX100Y100D01*\nD02*\nG37*'
        c = audit_regions(text)[0]['contours']
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]['points'], [[100,100],[200,100],[100,100]])
        self.assertTrue(c[0]['closedExactly'])

    def test_polarity_and_modal_axis_survive_region_transitions(self):
        text = HEADER+region([(0,0),(100,0),(100,100),(0,0)], 'C')
        text += '%LPD*%\nG36*\nX200Y0D02*\nX300D01*\nY100D01*\nX200Y0D01*\nG37*'
        raw = audit_regions(text)
        self.assertEqual([r['polarity'] for r in raw], ['clear', 'dark'])
        self.assertEqual([r['polarity'] for r in phase2d.scan(text)], ['clear', 'dark'])
        self.assertEqual(raw[1]['contours'][0]['points'][2], [300,100])

    def test_unsupported_formats_curves_and_transforms_fail_closed(self):
        for text in (HEADER.replace('X45Y45', 'X46Y46')+region([(0,0),(100,0)]),
                     HEADER+'G36*X0Y0D02*G02*X10Y10I10J0D01*G37*',
                     HEADER+'%LMX*%'+region([(0,0),(100,0)]),
                     HEADER+'%OFA1B0*%'+region([(0,0),(100,0)])):
            with self.assertRaises(ValueError):
                audit_regions(text)

    def test_open_display_fill_is_hypothetical_and_no_closure_is_approved(self):
        text = HEADER+region([(0,0),(100000,0),(100000,100000),(0,5000)], 'C')+'M02*'
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder)/'authored.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('authored.GBL', text)
                z.writestr('authored.GTL', HEADER+'X0Y0D03*M02*')
            d = load_archive(archive)
            try:
                self.assertEqual(d.regions[0].source_file, 'authored.GBL')
                self.assertEqual(d.regions[0].polarity, 'clear')
                self.assertFalse(d.regions[0].source_conforms_202605)
                layer = next(l for l in d.canonical_geometry.layers if l.side == 'bottom')
                self.assertEqual(layer.role, 'hypothetical')
                self.assertFalse(eligibility_for_simulation(d.canonical_geometry)[0])
                proposal = propose_closure(d.regions[0].source_points_mm,
                                           source_commands=d.regions[0].source_commands,
                                           polarity=d.regions[0].polarity)
                self.assertNotEqual(proposal.status, 'SAFE CANDIDATE')
            finally:
                d.close()


@unittest.skipUnless(os.environ.get('DEMONX_PHASE2N_ARCHIVE'), 'Private archive path not configured')
class PrivateArchiveAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_archive(Path(os.environ['DEMONX_PHASE2N_ARCHIVE']))
        path = next(p for p in cls.document.extracted_files if p.suffix.upper() == '.GBL')
        cls.raw = audit_regions(path.read_text(encoding='ascii'))

    @classmethod
    def tearDownClass(cls):
        cls.document.close()

    def test_every_source_gap_and_polarity_matches_inspector(self):
        self.assertEqual(len(self.raw), len(self.document.regions))
        for raw, inspected in zip(self.raw, self.document.regions):
            self.assertEqual(len(raw['contours']), 1)
            c = raw['contours'][0]
            self.assertEqual(inspected.polarity, raw['polarity'])
            self.assertEqual(inspected.first_line, raw['g36Line'])
            self.assertEqual(inspected.last_line, raw['g37Line'])
            self.assertAlmostEqual(inspected.closure_length_mm, c['gapMm'], places=12)

    def test_small_medium_large_source_cases_remain_unapproved(self):
        cases = sorted((c['gapMm'], r['index']) for r in self.raw for c in r['contours'] if not c['closedExactly'])
        self.assertGreaterEqual(len(cases), 3)
        for gap, index in (cases[0], cases[len(cases)//2], cases[-1]):
            r = self.document.regions[index]
            self.assertFalse(r.source_conforms_202605)
            p = propose_closure(r.source_points_mm, source_commands=r.source_commands, polarity=r.polarity)
            self.assertNotEqual(p.status, 'SAFE CANDIDATE')
            self.assertFalse(p.audit_record['userApproved'])
        self.assertEqual(self.document.canonical_geometry.machining_eligibility, 'BLOCKED')

    def test_audit_identity_and_all_independent_source_segments(self):
        report = json.loads((ROOT/'phase2n/results/audit.json').read_text(encoding='utf-8'))
        self.assertEqual(report['archiveSha256'], self.document.archive_sha256)
        self.assertEqual(len(report['regions']), len(self.raw))
        for r in report['regions']:
            self.assertTrue(r['pygerberSourceSegmentsExactlyEqual'])
            self.assertLess(r['gerbonaraSourceSegmentMaxDeltaMm'], 1e-12)
            self.assertEqual(r['gerbonaraAdditionalSegmentCount'], 1)
        for side in ('top', 'bottom'):
            self.assertLess(report['layers'][side]['comparison']['boundaryHausdorffMm'], .005)


if __name__ == '__main__':
    unittest.main(verbosity=2)
