import json,sys,unittest,hashlib
from pathlib import Path
from collections import defaultdict
from decimal import Decimal
from fractions import Fraction
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import recovery as r
from phase2d.test_regions import source,SIMPLE

class Recovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=json.loads((r.OUT/'validation-records.json').read_text())
        cls.records=cls.data['records'];cls.val=cls.records[:2];cls.laser=cls.records[2:]

    def test_independent_finding_reproduction(self):
        data=json.loads((r.OUT/'independent-reproduction.json').read_text())
        for parser in ('sourceScanner','gerbonaraRawOutline','pygerberCommands'):
            v=data[r.BOARDS[0]][parser];l=data[r.BOARDS[1]][parser]
            self.assertEqual((v['fullyCoincidentReversePairs'],v['zeroLengthDraws'],l['openContours'],v['regions']+l['regions']),(117,119,182,184))
            self.assertTrue(v['allCoordinatesExactlyMatchSource']);self.assertTrue(l['allCoordinatesExactlyMatchSource'])

    def test_three_statuses_and_redundancy_does_not_reject_board(self):
        self.assertEqual(self.data['counts'],{'RECOVERABLE':2,'BLOCKED':182})
        raw=r.d.scan(source([SIMPLE]))[0]
        rec,g=r.classify_region(raw,'synthetic','0'*64,0)
        self.assertEqual(rec['status'],'VALID');self.assertTrue(rec['sourceConforms202605'])
        eligibility=json.loads((r.OUT/'manufacturing-eligibility.json').read_text())
        self.assertTrue(eligibility[0]['geometryPreparationEligible']);self.assertFalse(eligibility[1]['geometryPreparationEligible'])
        self.assertFalse(eligibility[0]['wholeBoardRejectedSolelyForRedundantCommands'])

    def test_exact_nonzero_edges_and_cut_in_holes_preserved(self):
        for record,holes in zip(self.val,(103,14)):
            raw={'contours':record['originalGeometry']['contours'],'commands':record['originalGeometry']['commands']}
            normalized,changes=r.normalize_exact_noops(raw,enabled=True)
            a=raw['contours'][0]['points'];b=normalized['contours'][0]['points']
            self.assertEqual([(x,y) for x,y in zip(a,a[1:]) if x!=y],list(zip(b,b[1:])))
            twice=lambda p:sum(x[0]*y[1]-y[0]*x[1] for x,y in zip(p,p[1:]))
            self.assertEqual(twice(a),twice(b));self.assertEqual(a[0],b[0]);self.assertEqual(a[-1],b[-1])
            self.assertEqual(len(changes),len(record['proposedChanges']))
            self.assertEqual(record['proposedRecoveryGeometry']['metrics']['interiorVoids'],holes)
            self.assertEqual(record['sourceToRecoveryAreaDeltaMm2'],0)
            self.assertFalse(record['sourceConforms202605'])

    def test_normalization_is_idempotent_and_opt_in(self):
        rec=self.val[0];raw={'contours':rec['originalGeometry']['contours'],'commands':rec['originalGeometry']['commands']}
        same,changes=r.normalize_exact_noops(raw,enabled=False);self.assertIs(same,raw);self.assertEqual(changes,[])
        with self.assertRaises(ValueError):r.d.region_geometry_ticks(same)
        normalized,changes=r.normalize_exact_noops(raw,enabled=True)
        again,new=r.normalize_exact_noops(normalized,enabled=True)
        self.assertEqual(again['contours'],normalized['contours']);self.assertEqual(new,[])

    def test_normalization_never_calls_generic_make_valid(self):
        raw=r.d.scan((r.FIX/r.BOARDS[0]/'Gerber_BottomLayer.GBL').read_text())[1]
        with patch.object(r.d,'make_valid',side_effect=AssertionError('No repair allowed')):
            record,g=r.classify_region(raw,'synthetic','0'*64,0)
        self.assertEqual(record['status'],'RECOVERABLE');self.assertTrue(g.is_valid)

    def test_one_tick_gap_is_blocked_no_snapping(self):
        raw=r.d.scan(source([SIMPLE[:-1]+[(0,1)]]))[0]
        record,g=r.classify_region(raw,'synthetic','0'*64,0)
        self.assertEqual(record['status'],'BLOCKED');self.assertIsNone(g)

    def test_zero_length_draw_outside_region_has_image_and_is_not_recovered(self):
        path=r.ROOT/'phase2e/fixtures/outside-region-zero-draw.gbr'
        path.write_text('%FSLAX45Y45*%\n%MOMM*%\n%ADD10C,1*%\nD10*\nX0Y0D02*\nX0Y0D01*\nM02*\n')
        self.assertEqual(r.d.scan(path.read_text()),[])
        cmd=r.PG.from_file(str(path)).parse()._command_buffer.commands[0]
        self.assertGreater(r.c.command_shape(cmd).area,0.78)

    def test_all_182_closures_valid_but_not_authorized(self):
        self.assertEqual(len(self.laser),182)
        for x in self.laser:
            candidate=x['proposedRecoveryGeometry']
            self.assertTrue(candidate['candidatePolygonValid']);self.assertEqual(candidate['unexpectedIntersectionCount'],0)
            self.assertEqual(x['status'],'BLOCKED');self.assertFalse(x['manufacturingEligibility']['geometryEligible'])
            self.assertTrue(x['acceptance']['unresolvedRisk']);self.assertIsNone(x['acceptance']['manualAcceptance'])
            self.assertIsNone(x['areaTopologyDifferences']['sourceToCandidateAreaDeltaMm2'])
            self.assertIsNotNone(x['areaTopologyDifferences']['marginalAllCandidatesScenario'])

    def test_exact_closure_vectors_and_area(self):
        for x in self.laser:
            candidate=x['proposedRecoveryGeometry'];end,start=candidate['edgeTicks']
            self.assertEqual([Decimal(v) for v in candidate['proposedEdgeDisplacementMm']],[(Decimal(start[i])-Decimal(end[i]))/r.SCALE for i in (0,1)])
            self.assertAlmostEqual(float(Fraction(candidate['exactCandidateAreaMm2'])),candidate['metrics']['areaMm2'],delta=1e-8)

    def test_manual_exception_is_hash_bound_and_keeps_unresolved_risk(self):
        x=self.laser[0];c=x['proposedRecoveryGeometry']
        self.assertFalse(r.manual_candidate_permission(x,c,None)['candidateUsePermittedByException'])
        acceptance={'sourceSha256':x['sourceSha256'],'candidateSha256':c['candidateSha256'],'reviewer':'synthetic test reviewer','reason':'Synthetic policy test; no real candidate acceptance','acceptUnresolvedRisk':True}
        decision=r.manual_candidate_permission(x,c,acceptance)
        self.assertTrue(decision['candidateUsePermittedByException']);self.assertEqual(decision['validationStatus'],'BLOCKED')
        self.assertFalse(decision['intendedGeometryVerified']);self.assertTrue(decision['unresolvedRisk'])
        self.assertFalse(r.manual_candidate_permission(x,c,{**acceptance,'sourceSha256':'1'*64})['candidateUsePermittedByException'])
        self.assertFalse(r.manual_candidate_permission(x,c,{**acceptance,'acceptUnresolvedRisk':False})['candidateUsePermittedByException'])
        changed={**c,'exactCandidateAreaMm2':'0'}
        self.assertFalse(r.manual_candidate_permission(x,changed,acceptance)['candidateUsePermittedByException'])

    def test_unsupported_arc_is_never_silently_treated_as_linear(self):
        raw=r.d.scan(source([SIMPLE]))[0]
        raw['commands'][1]['mode']='G02'
        record,g=r.classify_region(raw,'synthetic','0'*64,0)
        self.assertEqual(record['status'],'BLOCKED');self.assertIsNone(g)

    def test_source_specific_fixtures_independent_parsers(self):
        for i,n in enumerate((105,14)):
            for kind,zero in [('original',n),('recovered',0)]:
                path=r.ROOT/'phase2e/fixtures'/f'valentine-region-{i}.{kind}.gbr'
                source_rows=r.d.scan(path.read_text())
                data=r.parser_reproduction(path,source_rows)
                for method,row in data.items():
                    self.assertEqual(row['zeroLengthDraws'],zero);self.assertTrue(row['allCoordinatesExactlyMatchSource'])

    def test_fresh_copper_measurements_preserve_area_topology_bounds(self):
        layers=json.loads((r.OUT/'copper-remeasurement.json').read_text());self.assertEqual(len(layers),4)
        for x in layers:
            self.assertLess(abs(x['areaDeltaMm2']),1e-8);self.assertEqual(x['componentsDelta'],0);self.assertEqual(x['interiorVoidsDelta'],0)
            self.assertLess(x['maximumBoundsDeltaMm'],1e-9)
        self.assertIn('UNAPPROVED',layers[-1]['mode'])

    def test_fresh_drill_records_diameters_slots_and_duplicate_groups(self):
        golden=json.loads((r.ROOT/'phase2a/results/parsed_geometry.json').read_text())
        total_hits=total_slots=unassigned=0;dups=defaultdict(list)
        for board in golden['boards']:
            for drill in board['drillFiles']:
                path=r.FIX/board['boardId']/drill['sourceFile']
                meta,hits,slots=r.c.p2a.parse_excellon(path,'drill',board['boardId'])
                self.assertEqual(hits,drill['hits']);self.assertEqual(slots,drill['slots'])
                total_hits+=len(hits);total_slots+=len(slots);unassigned+=sum(h['group']=='unassigned' for h in hits)
                for h in hits:dups[(board['boardId'],h['xMm'],h['yMm'],h['sourceDiameterMm'])].append(h)
                cx=(board['boardProfile']['bounds'][0]+board['boardProfile']['bounds'][2])/2
                for h in hits:self.assertLess(abs((2*cx-(2*cx-h['xMm']))-h['xMm']),1e-12)
        self.assertEqual((total_hits,total_slots,unassigned),(413,8,87));self.assertEqual(sum(len(v)>1 for v in dups.values()),12)
        self.assertEqual(len(dups),401)

    def test_record_contract_and_no_nonfinite_values(self):
        schema=json.loads((r.ROOT/'phase2e/schema/source-validation-record.schema.json').read_text())
        required=set(schema['required'])
        for x in self.records:
            self.assertFalse(required-set(x));self.assertEqual(len(x['sourceSha256']),64)
            self.assertGreaterEqual(x['sourceCommandRange']['firstLine'],1)
        json.dumps(self.data,allow_nan=False)

    def test_native_source_evidence_plan_requests_no_access(self):
        data=json.loads((r.OUT/'native-project-evidence-requirements.json').read_text())
        self.assertFalse(data['accessRequested']);self.assertEqual(len(data['artifacts']),2)
        for x in json.loads((r.OUT/'archive-project-provenance.json').read_text()):
            self.assertFalse(x['containsEditableNativePCBProject']);self.assertEqual(x['nativeRevisionCorrespondence'],'NOT_VERIFIED')

if __name__=='__main__':unittest.main(verbosity=2)
