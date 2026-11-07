"""Bounded regressions for identity snapshots and bare-top10-by-default admission."""
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace as NS
import unittest
from unittest import mock
from farm import admission as A, runner as R


def job(**extra):
    return dict(id='fixture', worker='local', start=0, end=99, hero='priest', spec='shadow', pool='mixed',
                targets=5, top=80, search_schema=A.SCHEMA, admission_policy=A.BARE,
                catalog_fingerprint='catalog', scoring_fingerprint='sources', **extra)


def slots(policy=A.BARE, scores=()):
    return {'__policy__': policy, **{k: (list(scores)+[0.]*(10-len(scores)), NS(value=len(scores)), list(range(10))) for k in A.KEYS}}


def snapshot(ids, score=100.):
    return {'overall': [{'chunk': c, 'dps': score} for c in ids], 'shop': [], 'drop': []}


class AdmissionTest(unittest.TestCase):
    def test_default_is_bare_top10(self):
        with mock.patch.dict(os.environ, {}, clear=True): self.assertEqual(A.policy(), A.BARE)

    def test_legacy_alias_normalizes_and_all_is_removed(self):
        self.assertEqual(A.policy({'admission_policy':A.UNSAFE}),A.BARE)
        for flag in ('0','1','true','all',''):
            with mock.patch.dict(os.environ, {'FARM_UNSAFE_BARE_GATE':flag}): self.assertEqual(A.policy(),A.BARE)
        for value in ('all','exhaustive'):
            with self.assertRaisesRegex(ValueError,'bare-top10'): A.policy({'admission_policy':value})

    def test_equal_scores_different_chunks_remain_ten(self):
        merged=A.merge(snapshot(range(6)),snapshot(range(4,10)))
        self.assertEqual(len(merged['overall']),10)
        self.assertEqual([r['chunk'] for r in merged['overall']],list(range(10)))

    def test_overlap_is_idempotent_and_commutative(self):
        a,b=snapshot(range(7)),snapshot(range(4,12),99.)
        ab=A.merge(a,b)
        self.assertEqual(ab,A.merge(b,a))
        for _ in range(30): ab=A.merge(ab,b)
        self.assertEqual(ab,A.merge(a,b))
        self.assertEqual(A.merge(ab,ab),ab)

    def test_duplicate_identity_is_not_new_observation(self):
        b=A.Observations(snapshot([1]));self.assertFalse(b.claim(1,100.,'shop_random'))
        self.assertTrue(b.claim(2,100.,'shop_random'));self.assertEqual(len(b.snapshot()['overall']),2)

    def test_legacy_floats_cannot_become_observations(self):
        self.assertEqual(A.Observations({'overall':[100.]*10}).snapshot(),snapshot([]))
        self.assertEqual(R._merge_bars({'overall':[100.]*10},snapshot([3]))['overall'],[{'chunk':3,'dps':100.}])

    def test_catalog_context_covers_stats_options_and_forced_item(self):
        space=NS(pieces=[NS(code='A',kind='stack',amp=False)],slots=6,require_leg=False,
                 talents=['t'],glyphs=['g'],picks_without=3,picks_with=4,glyph_picks=3)
        items={'A':NS(intel=10)}; original={'admission_policy':A.BARE}
        first=A.configure(original,space,items)
        self.assertEqual(first,A.configure(original,space,items));self.assertEqual(original,{'admission_policy':A.BARE})
        items['A'].intel=11;second=A.configure(original,space,items)
        self.assertNotEqual(first['catalog_fingerprint'],second['catalog_fingerprint'])
        space.forced='A';third=A.configure(original,space,items)
        self.assertNotEqual(second['catalog_fingerprint'],third['catalog_fingerprint'])
        space.picks_with=5;fourth=A.configure(original,space,items)
        self.assertNotEqual(third['catalog_fingerprint'],fourth['catalog_fingerprint'])

    def test_legacy_environment_cannot_enable_all(self):
        for flag in ('0','1'):
            with mock.patch.dict(os.environ,{'FARM_UNSAFE_BARE_GATE':flag}):
                self.assertEqual(A.policy({'admission_policy':A.BARE}),A.BARE)
                with self.assertRaisesRegex(ValueError,'removed'): A.policy({'admission_policy':'all'})

    def test_bad_scores_rejected(self):
        for value in (float('inf'),float('nan')):
            with self.assertRaises(ValueError): A.Observations(snapshot([1],value))

    def test_every_hero_default_rejects_below_current_floor(self):
        from farm.protocol import SPECS
        with mock.patch.object(R,'_BAR',(slots(scores=[1466.4726078431374]*10),threading.Lock())):
            for hero in SPECS:
                with self.subTest(hero=hero): self.assertFalse(R.claim_item_bars(1437.650818627451,'shop_random',973490555))

    def test_legacy_alias_shared_gate_preserves_identity_snapshot(self):
        state=slots(A.UNSAFE, [100.]*9)
        with mock.patch.object(R,'_BAR',(state,threading.Lock())):
            self.assertTrue(R.claim_item_bars(100.,'shop_random',99))
            self.assertFalse(R.claim_item_bars(99.,'shop_random',100))
            self.assertFalse(R.claim_item_bars(100.,'shop_random',99))
            got=R.item_bar_snapshot(*R._BAR)
        self.assertEqual(len(got['overall']),10)
        self.assertEqual(A.merge(got,got),got)

    def test_anonymous_legacy_gate_state_is_not_imported(self):
        raw={k:([200.]*10,NS(value=10)) for k in A.KEYS};raw['__policy__']=A.BARE
        with mock.patch.object(R,'_BAR',(raw,threading.Lock())):
            with self.assertRaisesRegex(ValueError,'identity-aware'):R.claim_item_bars(1.,'shop_random',20)

    def test_context_and_results_are_namespaced(self):
        j=job(); changed=dict(j,admission_policy=A.UNSAFE)
        self.assertNotEqual(R._job_checkpoint_path(j),R._job_checkpoint_path(changed))
        self.assertNotEqual(R._result_path(j),R._result_path({k:v for k,v in j.items() if k not in A.metadata(j)}))
        for key,value in [('catalog_fingerprint','other'),('scoring_fingerprint','other'),('end',199)]:
            self.assertNotEqual(R._job_checkpoint_path(j),R._job_checkpoint_path(dict(j,**{key:value})))

    def test_legacy_resume_restarts_without_mutating_file(self):
        j=job();legacy={k:v for k,v in j.items() if k not in A.metadata(j)}
        legacy.update(done_up_to=99,ahead=[],item_bar={'overall':[1466.47]*10},top=[])
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'legacy.json';path.write_text(json.dumps(legacy));before=path.read_bytes()
            with mock.patch.object(R,'_job_checkpoint_path',return_value=path):
                done,ahead,errors,bars=R._load_checkpoint(j,R.Boards())
            self.assertEqual((done,ahead,errors),(0,[],0));self.assertEqual(path.read_bytes(),before)
            self.assertEqual(A.Observations(bars).snapshot(),snapshot([]))

    def test_new_checkpoint_roundtrip_and_repeated_save(self):
        j=job(); rows=snapshot(range(10));board=R.Boards()
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'v2.json'
            with mock.patch.object(R,'_job_checkpoint_path',return_value=path):
                for _ in range(12): R._save_checkpoint(j,20,[(30,40)],board,0,rows)
                done,ahead,err,restored=R._load_checkpoint(j,R.Boards())
                self.assertEqual((done,ahead,err),(20,[(30,40)],0));self.assertEqual(rows,restored)
                saved=json.loads(path.read_text());self.assertEqual(saved['item_bar']['overall'],[100.]*10)

    def test_merge_watermarks_observations_and_ahead(self):
        j=job();a=dict(j,top=[],done_up_to=20,ahead=[[30,40]],errors=0,item_observations=snapshot(range(7)))
        b=dict(j,top=[],done_up_to=30,ahead=[],errors=0,item_observations=snapshot(range(4,10)))
        merged=R._merge_checkpoint(a,b)
        self.assertEqual(merged['done_up_to'],40);self.assertEqual(merged['ahead'],[])
        self.assertEqual(len(merged['item_observations']['overall']),10)
        self.assertEqual(R._merge_checkpoint(merged,merged),merged)

    def test_schema_and_policy_mismatch_not_resumed(self):
        j=job();self.assertFalse(R._same_job(j,dict(j,admission_policy=A.UNSAFE)))
        self.assertFalse(R._same_job(j,{k:v for k,v in j.items() if k not in A.metadata(j)}))

    def test_result_metadata_distinguishes_complete_sweep_from_admission(self):
        j=job()
        with tempfile.TemporaryDirectory() as t, mock.patch.object(R,'_result_path',return_value=Path(t)/'x.json'):
            p=R._write_result(j,R.Boards(),100,False,0);data=json.loads(Path(p).read_text())
        self.assertTrue(data['item_sweep_complete']);self.assertFalse(data['item_admission_complete'])
        self.assertFalse(data['admission_is_lossless']);self.assertFalse(data['global_optimum_proven'])
        self.assertEqual(data['admission_policy'],A.BARE)
        self.assertIn('Heuristic',A.description(j));self.assertIn('No global optimum guarantee',A.description(j))

    def test_matches_pre_d24_running_top10_thresholds_ties_categories_updates(self):
        import random
        old=R.CategoryBars();state=slots();rng=random.Random(248)
        with mock.patch.object(R,'_BAR',(state,threading.Lock())):
            for i in range(250):
                group=rng.choice(('shop','drop','shop_random'));score=rng.choice((1.,2.,50.,99.,100.,101.,150.))
                self.assertEqual(R.claim_item_bars(score,group,10000+i),old.claim(score,group))
                now=R.item_bar_snapshot(*R._BAR)
                self.assertEqual({k:[x['dps'] for x in now[k]] for k in A.KEYS},old.snapshot())

    def test_removed_all_and_missing_identity_never_bypass_live_gate(self):
        for policy in (A.BARE,A.UNSAFE,'all'):
            with mock.patch.object(R,'_BAR',(slots(policy,[100.]*10),threading.Lock())):
                if policy=='all':
                    with self.assertRaisesRegex(ValueError,'removed'):R.claim_item_bars(99.,'drop',99)
                else:
                    self.assertFalse(R.claim_item_bars(99.,'drop',99))
                    with self.assertRaisesRegex(ValueError,'chunk identity'):R.claim_item_bars(101.,'drop')

    def test_removed_all_rejected_before_catalog_or_device_in_production_entries(self):
        from farm.hybrid import runner as H
        from farm.discord_runner import run_job as discord_job
        j=dict(hero='mage',spec='fire',admission_policy='all')
        with mock.patch('farm.catalog.load',side_effect=AssertionError('no catalog')),mock.patch.object(H,'detect',side_effect=AssertionError('no device')):
            for entry in (R.run_job,H.run_job,discord_job):
                with self.assertRaisesRegex(ValueError,'removed'):entry(j,{},lambda _:None)

    def test_other_policy_resume_never_imports_spans_or_thresholds(self):
        j=job()
        for old_policy in ('all',A.UNSAFE):
            saved=dict(j,admission_policy=old_policy,done_up_to=99,ahead=[[99,100]],item_observations=snapshot(range(10)),top=[])
            with tempfile.TemporaryDirectory() as t:
                p=Path(t)/'other.json';p.write_text(json.dumps(saved));before=p.read_bytes()
                with mock.patch.object(R,'_job_checkpoint_path',return_value=p):done,ahead,err,observations=R._load_checkpoint(j,R.Boards())
                self.assertEqual((done,ahead,err),(0,[],0));self.assertEqual(A.Observations(observations).snapshot(),snapshot([]));self.assertEqual(p.read_bytes(),before)


class PipelineTest(unittest.TestCase):
    def test_below_tie_rejected_before_refinement_admitted_refined_all_routes(self):
        from farm.hybrid import engine as H
        item=NS(rawcode='A',name='A');space=NS(decode=lambda i:(('A',),(),()),talents=[],glyphs=[],picks_without=0,picks_with=0,glyph_picks=0,talent_names={},glyph_names={})
        finish=(3523.8,(),(),{},0)
        for bare,admit in ((99.,False),(100.,False),(101.,True)):
            for route in ('cpu','hybrid-seq','hybrid-cross','cpu-staged'):
                fake=NS(checked=True,dps_many=mock.Mock(side_effect=lambda bs:[bare]*len(bs)),finish_sextuple=mock.Mock(return_value=finish),finish_many=mock.Mock(side_effect=lambda cs:[finish]*len(cs)))
                with self.subTest(bare=bare,route=route), mock.patch.multiple(R,_SPACE=space,_ITEMS={'A':item},_SOURCES={'A':'shop'},_HERO='mage',_SPEC='fire',_TARGETS=5,_STOP=None,_BAR=(slots(scores=[100.]*10),threading.Lock())), mock.patch('farm.score.item_dps',return_value=bare), mock.patch('farm.score.finish_sextuple',return_value=finish) as cpu_finish, mock.patch.object(H,'_engine',return_value=fake),mock.patch.object(H,'_ENGINE_STATE','gpu'),mock.patch.object(H,'_cross_build_enabled',return_value=route in ('hybrid-cross','cpu-staged')):
                    result=R.eval_span(99,100) if route=='cpu' else H.eval_span(99,100,cpu_engine=fake) if route=='cpu-staged' else H.eval_span(99,100)
                    self.assertEqual(result['errors'],0);self.assertEqual(len(result['hits']),int(admit))
                    refined=cpu_finish.call_count+fake.finish_sextuple.call_count+fake.finish_many.call_count
                    self.assertEqual(refined,int(admit))


@unittest.skipUnless(os.environ.get('FARM_ADMISSION_DML_TEST')=='1','explicit bounded DirectML integration')
class ShadowDirectMLTest(unittest.TestCase):
    def test_old_shadow_winner_is_a_documented_gate_limitation_cpu_dml(self):
        from sunken_sim import shadow
        from sunken_sim.library import load_items
        from sunken_sim.search import TALENTS,GLYPHS
        from farm.hybrid import engine as H
        from farm.hybrid.device import detect
        from farm.hybrid.priest import PriestFights
        codes=('I00D','I048','I0FW','I0JO','I0NT','fgrd');items={i.rawcode:i for i in load_items() if i.rawcode in codes}
        space=NS(decode=lambda i:(codes,(),()),talents=['I0HL','I0HP','I0KF','I0PS','I0PU','I0SA','I0SB','I0SC'],glyphs=['I07B','I0AV','I0EJ','I0EK','I0EN','I0GZ','I0H3','I0H5','I0H6','I0HC','I0JA','I0OF'],picks_without=3,picks_with=4,glyph_picks=3,talent_names=TALENTS,glyph_names=GLYPHS)
        dev=detect('priest','shadow');self.assertEqual(dev.kind,'dml');gpu=PriestFights(dev,'priest','shadow',5)
        # Historical full winner3523.8288 loses at bare1437.6508 < floor1466.4726.
        with mock.patch.dict(os.environ,{'FARM_HYBRID_GPU_TIMELINE':'1','FARM_HYBRID_ESC_ALGEBRA':'0'}), mock.patch.multiple(R,_SPACE=space,_ITEMS=items,_SOURCES=R.source_map(items),_HERO='priest',_SPEC='shadow',_TARGETS=5,_STOP=None,_BAR=(slots(scores=[1466.4726078431374]*10),threading.Lock())), mock.patch('farm.score.finish_sextuple',side_effect=AssertionError('rejected before refinement')),mock.patch.object(gpu,'finish_many',side_effect=AssertionError('rejected before refinement')),mock.patch.object(gpu,'finish_sextuple',side_effect=AssertionError('rejected before refinement')):
            shadow._TIMELINE.clear();cpu=R.eval_span(973490555,973490556)
            with mock.patch.object(H,'_engine',return_value=gpu),mock.patch.object(H,'_ENGINE_STATE','gpu'):hybrid=H.eval_span(973490555,973490556)
        for result in (cpu,hybrid):
            self.assertEqual(result['errors'],0);self.assertEqual(result['hits'],[]);self.assertEqual(result['fights'],1)

if __name__=='__main__':unittest.main()
