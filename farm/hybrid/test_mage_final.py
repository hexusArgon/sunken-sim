import os,unittest
from unittest import mock
import numpy as np
from farm.hybrid import mage_final as MF,fight,registry,engine,test_mage_capacity as capacity
from sunken_sim import mage
from sunken_sim.shadow import FIGHT


class FinalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        capacity.DirectMLCapacityTest.setUpClass();cls.dev=capacity.DirectMLCapacityTest.device;cls.bs=capacity.DirectMLCapacityTest.builds
    def setUp(self):
        self.flags=mock.patch.dict(os.environ,{'FARM_FIRE_FINAL_GPU':'1'});self.flags.start();self.addCleanup(self.flags.stop)
    def test_coefficients_equal_reference_formula_and_armor_semantics(self):
        rng=np.random.RandomState(236)
        for b in self.bs:
            tl=fight.timelines(b,5,'fire',cache=False)[0]
            tl.stats=dict(tl.stats,stab_chance=.25,stab_ratio=1.2,luck=17,armor_pen=7)
            for hell in (None,1.,4.):
                weights=MF.coefficients(tl,hell)
                for _ in range(16):
                    sums=rng.uniform(0,20,len(fight.COLUMNS))
                    exact=mage._score(fight.compiled_dict(tl,sums,hell),tl.stats,tl.build,'fire')[0]
                    self.assertAlmostEqual(float(sums@weights)/exact,1.,places=12)
    def test_real_dml_final_and_reused_ring_cpu_parity(self):
        g=registry.make_engine(self.dev,'mage','fire',5)
        a=g.dps_many(self.bs);b=g.dps_many(self.bs)
        self.assertEqual(a,b)
        self.assertTrue(engine.compare([mage.simulate(x,5,spec='fire',use_history=False).dps for x in self.bs],a)['ok'])
        self.assertGreater(g.score_counts['gpu_final_rows'],0);self.assertGreater(g.score_counts['gpu_owner_reductions'],0)
    def test_gpu_first_tie_and_padding(self):
        import torch
        info,groups=MF.owner_reduce(torch,self.dev.handle,[10.,10.,9.],[0,0,1],2)
        self.assertEqual(info[0,2],0);self.assertEqual(info[0,0],10);self.assertEqual(info[1,0],9)
        self.assertEqual(groups,[[0,1],[2]])
    def test_duplicate_build_and_near_tie_use_exact_guard(self):
        g=registry.make_engine(self.dev,'mage','fire',5);b=self.bs[0];got=g.dps_many([b,b])
        ref=mage.simulate(b,5,spec='fire',use_history=False).dps
        self.assertAlmostEqual(got[0],ref,places=9);self.assertEqual(got[0],got[1]);self.assertEqual(g.score_counts['near_tie_exact_builds'],2)
    def test_unsupported_formula_and_owner_op_fall_back_exact(self):
        g=registry.make_engine(self.dev,'mage','fire',5)
        with mock.patch.object(MF,'supported',return_value=False):got=g.dps_many(self.bs)
        self.assertGreater(g.score_counts['device_final_fallback_rows'],0)
        ref=[mage.simulate(x,5,spec='fire',use_history=False).dps for x in self.bs]
        self.assertTrue(engine.compare(ref,got)['ok'])
        g=registry.make_engine(self.dev,'mage','fire',5)
        with mock.patch.object(MF,'owner_reduce',side_effect=RuntimeError('unsupported gather')):got=g.dps_many(self.bs)
        self.assertEqual(g.score_counts['gpu_owner_fallback_builds'],len(self.bs));self.assertTrue(engine.compare(ref,got)['ok'])
    def test_disabled_empty_and_future_formula_guard(self):
        self.assertTrue(MF.supported(mage._score));self.assertFalse(MF.supported(lambda:0))
        g=registry.make_engine(self.dev,'mage','fire',5);self.assertEqual(g.dps_many([]),[])
        with mock.patch.dict(os.environ,{'FARM_FIRE_FINAL_GPU':'0'}):g.dps_many(self.bs)
        self.assertFalse(g.score_counts['gpu_final_rows'])

    def test_official_scoring_only_engine_compatibility(self):
        import torch
        tl=fight.timelines(self.bs[0],5,'arcane',cache=False)[0]
        g=fight.GpuFights.__new__(fight.GpuFights);g.torch=torch;g.target=torch.device('cpu')
        got=g._scores([tl])[0]
        exact=mage._score(mage._compile(tl.events,tl.build,tl.stats,tl.spec,tl.evocation),tl.stats,tl.build,tl.spec)[0]/FIGHT
        self.assertTrue(engine.compare([exact],[got])['ok'])
