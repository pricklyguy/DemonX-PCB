"""Golden checks for Phase 2B's pinned independent parser outputs."""
import csv, hashlib, json, unittest
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parent
P2A=json.loads((ROOT.parent/'phase2a'/'results'/'parsed_geometry.json').read_text(encoding='utf-8'))
COMPARISON=json.loads((ROOT/'reference'/'comparison.json').read_text(encoding='utf-8'))
PYGERBER=json.loads((ROOT/'reference'/'pygerber-comparison.json').read_text(encoding='utf-8'))

class IndependentReferenceGoldenTests(unittest.TestCase):
    def test_original_fixture_hashes_are_unchanged(self):
        inventory=json.loads((ROOT.parent/'phase2a'/'fixture_inventory.json').read_text(encoding='utf-8'))
        for b in inventory['boards']:
            archive=ROOT.parent/b['archivePath']
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(),b['archiveSha256'],b['archive'])
            parsed=next(x for x in P2A['boards'] if x['boardId']==b['boardId'])
            folder=ROOT.parent/'phase2a'/'fixtures'/'extracted'/b['boardId']
            for source in parsed['sourceFiles']:
                self.assertEqual(hashlib.sha256((folder/source['sourceFile']).read_bytes()).hexdigest(),source['sha256'],source['sourceFile'])
            for drill in parsed['drillFiles']:
                self.assertEqual(hashlib.sha256((folder/drill['sourceFile']).read_bytes()).hexdigest(),drill['sha256'],drill['sourceFile'])

    def test_reference_record_counts_and_warning_state(self):
        expected={
            'gerber-pcb-valentine-feb-new':(4140,230,0),
            'gerber-prickly-laser-module-2-5':(6821,183,8),
        }
        for b in P2A['boards']:
            with (ROOT/'reference'/'delta'/('valentine.csv' if 'valentine' in b['boardId'] else 'laser.csv')).open(encoding='utf-8',newline='') as f:
                rows=list(csv.DictReader(f))
            gerbers=sum(r['kind']=='gerber' for r in rows)
            hits=sum(r['kind']=='drill' and r['recordType']=='DrillHit' for r in rows)
            slots=sum(r['kind']=='drill' and r['recordType']=='DrillSlot' for r in rows)
            self.assertEqual((gerbers,hits,slots),expected[b['boardId']])
            self.assertEqual(sum(bool(r['warnings']) for r in rows),0)

    def test_every_manufacturing_file_has_matching_parser_record_count(self):
        for b in P2A['boards']:
            cmp=next(x for x in COMPARISON['boards'] if x['boardId']==b['boardId'])
            for x in cmp['gerberComparisons']:
                self.assertEqual(x['phase2aCount'],x['deltaCount'],x['sourceFile'])
                self.assertTrue(x['typeCountsMatch'],x['sourceFile'])
            for x in cmp['drillComparisons']:
                self.assertEqual(x['phase2aHits'],x['deltaHits'],x['sourceFile'])
                self.assertEqual(x['phase2aSlots'],x['deltaSlots'],x['sourceFile'])
                self.assertTrue(x['hitSourceIndicesMatch'],x['sourceFile'])
                self.assertTrue(x['slotSourceIndicesMatch'],x['sourceFile'])
                for key in ('hitCoordinateMaxDiffMm','slotEndpointMaxDiffMm','diameterMaxDiffMm'):
                    if x[key] is not None: self.assertLessEqual(x[key],1e-9,(x['sourceFile'],key))

    def test_arc_bbox_disagreements_are_golden_and_visible(self):
        mismatches={(x['boardId'],g['sourceFile']):(g['bboxMismatchObjects'],g['bboxMismatchByGerbonaraType'])
                    for x in COMPARISON['boards'] for g in x['gerberComparisons'] if g['bboxMismatchObjects']}
        self.assertEqual(mismatches,{
            ('gerber-pcb-valentine-feb-new','Gerber_TopSilkscreenLayer.GTO'):(256,{'Arc':256}),
            ('gerber-pcb-valentine-feb-new','Gerber_BottomSilkscreenLayer.GBO'):(6,{'Arc':6}),
            ('gerber-pcb-valentine-feb-new','Gerber_DocumentLayer.GDL'):(8,{'Arc':8}),
            ('gerber-prickly-laser-module-2-5','Gerber_TopSilkscreenLayer.GTO'):(9,{'Arc':9}),
        })

    def test_pygerber_independently_matches_source_arc_records(self):
        self.assertEqual(PYGERBER['pygerberVersion'],'2.4.3')
        self.assertEqual(len(PYGERBER['results']),17)
        for r in PYGERBER['results']:
            self.assertEqual(r['gerbonaraObjectCount'],r['pygerberCommandCount'],r['sourceFile'])
            self.assertTrue(r['typeCountsMatch'],r['sourceFile'])
            self.assertEqual(r['arcCountGerbonara'],r['arcCountPyGerber'],r['sourceFile'])
            self.assertTrue(r['arcDirectionMatches'],r['sourceFile'])
            self.assertLessEqual(r['arcCoordinateMaxDifferenceMm'],2e-14,r['sourceFile'])

    def test_unassigned_records_reconcile_and_overlaps_remain_visible(self):
        expected={'gerber-pcb-valentine-feb-new':230,'gerber-prickly-laser-module-2-5':183}
        duplicates=defaultdict(list)
        for b in P2A['boards']:
            hits=[h for d in b['drillFiles'] for h in d['hits']]
            self.assertEqual(len(hits),expected[b['boardId']])
            self.assertEqual(sum(h['group']=='unassigned' for h in hits),22 if 'valentine' in b['boardId'] else 65)
            for h in hits:
                duplicates[(b['boardId'],h['xMm'],h['yMm'],h['sourceDiameterMm'])].append(h)
        overlaps=[v for v in duplicates.values() if len(v)>1]
        self.assertEqual(len(overlaps),12)
        self.assertTrue(all({h['role'] for h in pair}=={'through-hole','via'} for pair in overlaps))

    def test_geos_copper_and_profile_reconstruction_self_consistency(self):
        """Same-parser/kernel regression only; this is not independent geometry proof."""
        p2a=ROOT.parent/'phase2a'
        sys.path.insert(0,str(p2a))
        try:
            import verify_fixtures as harness
            for board in P2A['boards']:
                folder=p2a/'fixtures'/'extracted'/board['boardId']
                for file,key in (('Gerber_TopLayer.GTL','topCopper'),('Gerber_BottomLayer.GBL','bottomCopper'),('Gerber_BoardOutlineLayer.GKO','boardProfile')):
                    _,copper,profile,_=harness.parse_gerber(folder/file,'gerber',board['boardId'])
                    current=harness.geometry_metrics(profile if key=='boardProfile' else copper)
                    golden=board[key]
                    self.assertEqual(current['components'],golden['components'],(board['boardId'],file,'components'))
                    self.assertEqual(current['interiorVoids'],golden['interiorVoids'],(board['boardId'],file,'voids'))
                    self.assertEqual(current['valid'],golden['valid'],(board['boardId'],file,'validity'))
                    self.assertAlmostEqual(current['areaMm2'],golden['areaMm2'],delta=1e-8,msg=(board['boardId'],file,'area'))
                    for a,b in zip(current['bounds'],golden['bounds']):
                        self.assertAlmostEqual(a,b,delta=1e-8,msg=(board['boardId'],file,'bounds'))
                bounds=board['boardProfile']['bounds']; cy=(bounds[1]+bounds[3])/2
                for drill in board['drillFiles']:
                    for hit in drill['hits']:
                        mirrored=(hit['xMm'],2*cy-hit['yMm'])
                        restored=(mirrored[0],2*cy-mirrored[1])
                        self.assertAlmostEqual(restored[0],hit['xMm'],delta=1e-12)
                        self.assertAlmostEqual(restored[1],hit['yMm'],delta=1e-12)
        finally:
            sys.path.remove(str(p2a))

if __name__=='__main__': unittest.main()
