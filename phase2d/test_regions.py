import hashlib,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import forensics as f
from shapely import union_all

HEADER='%FSLAX45Y45*%\n%MOMM*%\n%ADD10C,0.1*%\nD10*\n'
SIMPLE=[(0,0),(1000000,0),(1000000,1000000),(0,1000000),(0,0)]
CUTIN=[(0,0),(1000000,0),(1000000,1000000),(0,1000000),(0,500000),(300000,500000),(300000,700000),(700000,700000),(700000,300000),(300000,300000),(300000,500000),(0,500000),(0,0)]
def source(contours):
    text=HEADER+'G36*\nG01*\n'
    for pts in contours:
        for i,(x,y) in enumerate(pts):text+=f'X{x}Y{y}D0{2 if i==0 else 1}*\n'
    return text+'G37*\nM02*\n'
def region(text):
    return f.region_geometry_ticks(f.scan(text)[0])

class Regions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence=json.loads((f.OUT/'region-evidence.json').read_text())
        fixtures={'simple':source([SIMPLE]),'cutin':source([CUTIN]),
          'bowtie':source([[(0,0),(1000000,1000000),(0,1000000),(1000000,0),(0,0)]]),
          'open':source([SIMPLE[:-1]]),'precision_open':source([SIMPLE[:-1]+[(0,1)]]),
          'zero_length':source([[SIMPLE[0]]+SIMPLE]),
          'hole_and_island':source([CUTIN,[(400000,400000),(600000,400000),(600000,600000),(400000,600000),(400000,400000)]]),
          'separate_contours_union':source([SIMPLE,[(300000,300000),(700000,300000),(700000,700000),(300000,700000),(300000,300000)]])}
        for name,text in fixtures.items():(f.ROOT/'phase2d/fixtures'/f'{name}.gbr').write_text(text)
    def test_simple(self):self.assertEqual(region(source([SIMPLE])).area/1e10,100)
    def test_cut_in_hole_no_make_valid(self):
        g=region(source([CUTIN]));self.assertTrue(g.is_valid);self.assertEqual(g.area/1e10,84);self.assertEqual(len(g.interiors),1)
    def test_fully_coincident_return(self):
        a=f.analyze(CUTIN);self.assertEqual(a['intersectionTypes']['full_reverse_horizontal'],1)
        self.assertEqual(len(a['reversePairs']),1)
    def test_true_self_intersection_rejected(self):
        with self.assertRaisesRegex(ValueError,'INTERSECTION'):region((f.ROOT/'phase2d/fixtures/bowtie.gbr').read_text())
    def test_open_no_implicit_closure(self):
        with self.assertRaisesRegex(ValueError,'OPEN'):region(source([SIMPLE[:-1]]))
    def test_no_precision_tolerance_closure(self):
        pts=SIMPLE[:-1]+[(0,1)];a=f.analyze(pts);self.assertEqual(a['closureDeltaTicks'],(0,1))
        with self.assertRaisesRegex(ValueError,'OPEN'):f.cutin_geometry(pts,a)
    def test_zero_length_rejected_even_if_area_unaffected(self):
        with self.assertRaisesRegex(ValueError,'INTERSECTION'):region(source([[SIMPLE[0]]+SIMPLE]))
    def test_region_hole_island(self):
        g=region((f.ROOT/'phase2d/fixtures/hole_and_island.gbr').read_text());self.assertEqual(g.area/1e10,88);self.assertEqual(len(g.geoms),2)
    def test_d02_separates_contours_filled_union_not_holes(self):
        text=(f.ROOT/'phase2d/fixtures/separate_contours_union.gbr').read_text();self.assertEqual(len(f.scan(text)[0]['contours']),2);self.assertEqual(region(text).area/1e10,100)
    def test_g36_g37_do_not_join_separate_regions(self):
        text=source([SIMPLE]).replace('M02*','')+'G36*\nX2000000Y0D02*\nX3000000Y0D01*\nG37*\nM02*'
        a=f.scan(text);self.assertEqual(len(a),2);self.assertEqual(len(a[1]['contours'][0]['points']),2)
    def test_modal_axes_and_mode_preserved_exactly(self):
        text=HEADER+'G01*\nG36*\nX0Y0D02*\nX1000000D01*\nY1000000D01*\nX0D01*\nY0D01*\nG37*\nM02*'
        self.assertEqual(f.scan(text)[0]['contours'][0]['points'],[list(p) for p in SIMPLE])
    def test_both_parsers_preserve_synthetic_cut_in(self):
        path=f.ROOT/'phase2d/fixtures/cutin.gbr'
        gb=next(o for o in f.GerberFile.open(path).objects if type(o).__name__=='Region')
        pg=next(c for c in f.PG.from_file(str(path)).parse()._command_buffer.commands if type(c).__name__=='Region2')
        self.assertEqual(len(gb.outline),len(CUTIN));self.assertEqual(len(pg.command_buffer.commands),len(CUTIN)-1)
        self.assertEqual(gb.outline[0],gb.outline[-1])
    def test_valentine_defects_exact_and_diagnostic_material_preserved(self):
        rows=self.evidence[0]['regions'];self.assertEqual(len(rows),2)
        for r,n,holes in zip(rows,[105,14],[103,14]):
            self.assertTrue(r['analysis']['closedExactly']);self.assertEqual(r['analysis']['intersectionTypes']['zero_length'],n)
            d=r['diagnosticZeroLengthOmission'];self.assertEqual(d['interiorVoids'],holes);self.assertLess(d['symmetricDifferenceVsPhase2AMakeValidMm2'],1e-9);self.assertLess(d['hausdorffVsPhase2AMakeValidMm'],1e-9)
            self.assertTrue(r['status'].startswith('BLOCKED'));self.assertTrue(d['notApprovedForManufacturing'])
    def test_all_laser_gaps_are_source_not_rounding(self):
        rows=self.evidence[1]['regions'];self.assertEqual(len(rows),182)
        for r in rows:
            self.assertFalse(r['analysis']['closedExactly']);self.assertEqual(r['status'],'BLOCKED_OPEN_SOURCE_CONTOUR')
            self.assertEqual(r['gerbonara']['segmentCount'],r['analysis']['segmentCount']+1)
            self.assertEqual(r['pygerber']['segmentCount'],r['analysis']['segmentCount'])
            self.assertEqual(r['gerbonara']['maxCoordinateDeltaMm'],0);self.assertEqual(r['pygerber']['maxCoordinateDeltaMm'],0)
    def test_source_hashes_and_previous_copper_evidence_unchanged(self):
        for board in self.evidence:
            path=f.ROOT/'phase2a/fixtures/extracted'/board['boardId']/'Gerber_BottomLayer.GBL'
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),board['sourceSha256'])
        c=json.loads((f.ROOT/'phase2c/results/copper-comparison.json').read_text())
        self.assertEqual([x['sourceObjectCount'] for x in c['files']],[429,561,191,627])
        for x in c['files']:self.assertLess(x['comparison']['boundaryHausdorffMm'],0.005)
    def test_diagonal_cut_in_rejected(self):
        pts=[(0,0),(100,0),(100,100),(0,100),(0,50),(30,60),(30,70),(70,70),(70,30),(30,30),(30,60),(0,50),(0,0)]
        with self.assertRaises(ValueError):f.cutin_geometry(pts,f.analyze(pts))
    def test_partial_overlap_rejected(self):
        pts=[(0,0),(100,0),(100,100),(0,100),(0,50),(50,50),(20,50),(0,0)]
        with self.assertRaises(ValueError):f.cutin_geometry(pts,f.analyze(pts))
    def test_valid_cut_in_reverse_orientation(self):
        self.assertEqual(region(source([list(reversed(CUTIN))])).area/1e10,84)
    def test_coincident_spur_without_hole_is_not_a_cut_in(self):
        pts=[(0,0),(100,0),(100,100),(0,100),(0,50),(30,50),(0,50),(0,0)]
        with self.assertRaisesRegex(ValueError,'SPUR'):f.cutin_geometry(pts,f.analyze(pts))

if __name__=='__main__':unittest.main(verbosity=2)
