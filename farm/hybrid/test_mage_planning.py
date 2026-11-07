import os,unittest
from unittest import mock
import numpy as np
import torch
from farm.hybrid import mage_gpu_timeline as M,mage_reuse as MR,test_mage_capacity as capacity
from sunken_sim import mage,shadow


class PlanningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        capacity.DirectMLCapacityTest.setUpClass();cls.bs=capacity.DirectMLCapacityTest.builds;cls.dev=capacity.DirectMLCapacityTest.device
    def test_push_cpu_fast_and_original_bitwise_including_overflow(self):
        for dtype in (torch.float32,torch.float64):
            rng=np.random.RandomState(236)
            with mock.patch.object(M,'MAX_EVENTS',7):
                a=M._make_bufs(torch,torch.device('cpu'),32,dtype);b=M._make_bufs(torch,torch.device('cpu'),32,dtype)
                for step in range(32):
                    mask=torch.tensor(rng.random_sample(32)>.6)
                    values=[torch.tensor(rng.normal(size=32),dtype=dtype) for _ in range(6)]
                    args=(*values,step%10,None if step%2 else mask)
                    with mock.patch.dict(os.environ,{'FARM_MAGE_FAST_PUSH':'0'}):M._push(torch,a,mask,*args)
                    with mock.patch.dict(os.environ,{'FARM_MAGE_FAST_PUSH':'1'}):M._push(torch,b,mask,*args)
                for key in a:self.assertTrue(torch.equal(a[key],b[key]),(dtype,key))
    def test_prepared_sheets_exact_and_not_recomputed(self):
        keys=[None]*len(self.bs);st=[mage.sheet(b) for b in self.bs]
        ref=M.generate_mage_timelines(torch,self.dev.handle,self.bs,'fire',5,keys)
        with mock.patch.object(mage,'sheet',side_effect=AssertionError('duplicate sheet')):
            got=M.generate_mage_timelines(torch,self.dev.handle,self.bs,'fire',5,keys,prepared_stats=st)
        self.assertEqual(ref,got)
    def test_vetted_context_mutable_constants_and_unknown_code_fail_closed(self):
        cache=MR.TapeLRU();cache.sync_context('fire',5);self.assertTrue(cache.split)
        ctx=cache.context
        with mock.patch.dict(shadow.MAGICAL_ADDS,{'audit-constant':.1}):cache.sync_context('fire',5);self.assertNotEqual(ctx,cache.context)
        import re
        ctx=cache.context
        with mock.patch.object(mage,'_FLAT_HEALTH',re.compile('audit')):cache.sync_context('fire',5);self.assertNotEqual(ctx,cache.context)
        with mock.patch.object(M,'_mage_batch',wraps=M._mage_batch):
            cache.sync_context('fire',5);self.assertFalse(cache.split)
        import functools
        original=M._mage_batch
        @functools.wraps(original)
        def wrapped(*args,**kwargs):return original(*args,**kwargs)
        with mock.patch.object(M,'_mage_batch',wrapped):
            cache.sync_context('fire',5);self.assertFalse(cache.split)
        with mock.patch.object(MR.Path,'read_text',side_effect=OSError('unreadable proof source')):
            cache.sync_context('fire',5);self.assertFalse(cache.split);self.assertFalse(cache.entries)
        cache.sync_context('fire',5);self.assertTrue(cache.split)
        with mock.patch.dict(MR.VERIFIED_SOURCES,{},clear=True):
            other=MR.TapeLRU();other.sync_context('fire',5);self.assertFalse(other.split)
    def test_bad_prepared_lengths_and_cache_generator_lengths_rejected(self):
        with self.assertRaises(ValueError):M.generate_mage_timelines(torch,self.dev.handle,self.bs,'fire',5,prepared_stats=[])
        cache=MR.TapeLRU()
        with self.assertRaises(ValueError):cache.rows(self.bs,'fire',5,[],lambda *args:[])
        with self.assertRaises(ValueError):cache.rows(self.bs,'fire',5,[None]*len(self.bs),lambda *args:[])

    def test_unknown_context_runs_fresh_without_cache_or_cluster(self):
        from farm.hybrid import registry,engine
        g=registry.make_engine(self.dev,'mage','fire',5)
        with mock.patch.object(MR,'verified',return_value=False):
            a=g.dps_many(self.bs);b=g.dps_many(self.bs)
        self.assertFalse(g.tape_cache.entries);self.assertEqual(g.tape_cache.counts['hits'],0)
        self.assertEqual(g.tape_cache.counts['generated_rows'],g.tape_cache.counts['requested_rows'])
        self.assertGreater(g.tape_cache.counts['uncached_unverified'],0)
        self.assertTrue(engine.compare([mage.simulate(x,5,spec='fire',use_history=False).dps for x in self.bs],b)['ok'])
    def test_device_pool_optout_includes_gpu_owner_reduction(self):
        from farm.hybrid import registry
        g=registry.make_engine(self.dev,'mage','fire',5)
        with mock.patch.dict(os.environ,{'FARM_FIRE_DEVICE_POOL':'0','FARM_FIRE_FINAL_GPU':'1'}):g.dps_many([self.bs[2]])
        self.assertGreater(g.score_counts['gpu_owner_reductions'],0)
        self.assertFalse(g.device_pool.entries)
