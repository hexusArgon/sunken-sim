import unittest
from unittest import mock
import numpy as np
from farm.hybrid.mage_device import DevicePool, parts
from farm.hybrid import test_mage_capacity as capacity, registry,engine,fight
from sunken_sim import mage
from sunken_sim.esc import apply_points,empty_points


class PoolTests(unittest.TestCase):
    def test_reuse_new_values_constant_keys_and_byte_budget(self):
        import torch
        p=DevicePool(torch,torch.device('cpu'),max_bytes=128)
        a=p.up('a',np.ones((2,8)));b=p.up('a',np.full((2,8),3))
        self.assertIs(a,b);self.assertEqual(float(b.sum()),48)
        p.up('b',np.ones((2,9)));self.assertLessEqual(p.resident_bytes,128)
        self.assertGreater(p.counts['evictions'],0)
        self.assertIs(p.constant('kind',2),p.constant('kind',2))
        self.assertNotEqual(float(p.constant('kind',2)),float(p.constant('kind',3)))
        p.up('oversize',np.ones(100));self.assertGreater(p.counts['uncached_uploads'],0)
    def test_context_and_owner_lifetime_isolation(self):
        import torch
        a=DevicePool(torch,torch.device('cpu'));b=DevicePool(torch,torch.device('cpu'))
        a.up('x',[1]);self.assertFalse(b.entries)
        with mock.patch('farm.hybrid.mage_device.os.getpid',return_value=-7):a.up('x',[2])
        self.assertEqual(a.counts['context_resets'],2)
        a.clear();self.assertFalse(a.entries);self.assertEqual(a.resident_bytes,0)
    def test_unsupported_copy_uploads_fresh_never_stale(self):
        class Tensor:
            def __init__(self,a):self.a=a.copy()
            def to(self,target):return self
            def copy_(self,x):raise RuntimeError('unsupported copy')
        class Torch:
            from_numpy=staticmethod(Tensor)
        p=DevicePool(Torch,'dml');p.up('x',[1]);x=p.up('x',[9])
        self.assertEqual(float(x.a[0]),9);self.assertFalse(p.copy_supported)
        self.assertEqual(p.counts['copy_unsupported'],1)


class DeviceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        capacity.DirectMLCapacityTest.setUpClass()
        cls.dev=capacity.DirectMLCapacityTest.device;cls.bs=capacity.DirectMLCapacityTest.builds
    def test_real_dml_reuses_updated_inputs_and_constants(self):
        import torch
        pool=DevicePool(torch,self.dev.handle)
        for value in (1.,9.,-3.):
            tensor=pool.up('changed-payload',np.full((4,8),value))
            self.assertTrue(np.array_equal(tensor.cpu().numpy(),np.full((4,8),value)))
        self.assertEqual(pool.counts['reuses'],2)
        g=registry.make_engine(self.dev,'mage','fire',5);a=g.dps_many(self.bs)
        p=empty_points();p['potency']=20;bs=[apply_points(b,p) for b in self.bs]
        g.dps_many(self.bs);b=g.dps_many(bs)
        self.assertGreater(g.device_pool.counts['reuses'],0)
        self.assertGreater(g.device_pool.counts['constant_reuses'],0)
        self.assertLessEqual(g.device_pool.resident_bytes,g.device_pool.max_bytes)
        self.assertTrue(engine.compare([mage.simulate(x,5,spec='fire',use_history=False).dps for x in bs],b)['ok'])
        self.assertNotEqual(a,b)
    def test_compile_failure_is_exact_cpu_and_counted(self):
        g=registry.make_engine(self.dev,'mage','fire',5)
        with mock.patch.object(fight,'compile_sums',side_effect=RuntimeError('unsupported device op')):got=g.dps_many(self.bs)
        ref=[mage.simulate(x,5,spec='fire',use_history=False).dps for x in self.bs]
        self.assertTrue(engine.compare(ref,got)['ok']);self.assertGreater(g.score_counts['device_compile_fallback_rows'],0)
    def test_memory_split_and_oversized_exact_fallback(self):
        g=registry.make_engine(self.dev,'mage','fire',5)
        with mock.patch('farm.hybrid.mage_device.parts',side_effect=lambda tls,n:parts(tls,max_rows=1,working_bytes=1)):got=g.dps_many(self.bs)
        self.assertTrue(engine.compare([mage.simulate(x,5,spec='fire',use_history=False).dps for x in self.bs],got)['ok'])
        self.assertGreater(g.score_counts['oversized_batches'],0)
        tls=[fight.timelines(b,5,'fire')[0] for b in self.bs]
        self.assertEqual(sum(len(x) for x,_ in parts(tls,max_rows=1)),len(tls))
        self.assertTrue(all(len(x)==1 and fits for x,fits in parts(tls,max_rows=1)))
