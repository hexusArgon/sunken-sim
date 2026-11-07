import os,unittest
from unittest import mock
from farm.hybrid.mage_reuse import TapeLRU
from farm.hybrid import test_mage_capacity as capacity
from farm.hybrid import registry,engine,mage_gpu_timeline as M
from sunken_sim import mage
from sunken_sim.esc import apply_points,empty_points


class ReuseTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):capacity.DirectMLCapacityTest.setUpClass();cls.dev=capacity.DirectMLCapacityTest.device;cls.bs=capacity.DirectMLCapacityTest.builds
 def test_reused_fresh_cpu_and_old_normal_equivalence(self):
  gpu=registry.make_engine(self.dev,'mage','fire',5)
  a=gpu.dps_many(self.bs);b=gpu.dps_many(self.bs)
  ref=[mage.simulate(x,5,spec='fire',use_history=False).dps for x in self.bs]
  self.assertTrue(engine.compare(ref,a)['ok']);self.assertEqual(a,b);self.assertGreater(gpu.tape_cache.counts['hits'],0)
 def test_potency_reuse_without_blazing_and_separation_with_it(self):
  from dataclasses import replace
  b=self.bs[0];p=empty_points();p['potency']=20
  c=apply_points(b,p)
  cache=TapeLRU();cache.sync_context('fire',5)
  sa,sb=map(mage.sheet,(b,c))
  self.assertEqual(cache.key(b,sa,None),cache.key(c,sb,None))
  b=replace(b,talents=b.talents|{'I0KR'});c=apply_points(b,p)
  self.assertNotEqual(cache.key(b,mage.sheet(b),None),cache.key(c,mage.sheet(c),None))
  gpu=registry.make_engine(self.dev,'mage','fire',5);got=gpu.dps_many([b,c])
  self.assertTrue(engine.compare([mage.simulate(x,5,spec='fire',use_history=False).dps for x in (b,c)],got)['ok'])
 def test_context_caps_and_policies(self):
  cache=TapeLRU();cache.sync_context('fire',5);c=cache.context
  with mock.patch.object(M,'MAX_EVENTS',17):cache.sync_context('fire',5);self.assertNotEqual(c,cache.context)
  cache.sync_context('fire',5);st=mage.sheet(self.bs[2]);self.assertNotEqual(cache.key(self.bs[2],st,'Hydra'),cache.key(self.bs[2],st,'Living Bomb'))
  for field in ('crit','luck','mastery','mana_max','haste','bomb_period'):
   other=dict(st);other[field]+=1;self.assertNotEqual(cache.key(self.bs[2],st,None),cache.key(self.bs[2],other,None))
 def test_eviction_isolation_immutability_and_disabled(self):
  gpu=registry.make_engine(self.dev,'mage','fire',5);gpu.tape_cache=TapeLRU(max_entries=1,max_bytes=1_000_000)
  gpu.dps_many(self.bs);self.assertLessEqual(len(gpu.tape_cache.entries),1);self.assertGreater(gpu.tape_cache.counts['evictions'],0)
  for e,_,_ in gpu.tape_cache.entries.values():
   with self.assertRaises(TypeError):e[0][5]['mana']=0
  other=registry.make_engine(self.dev,'mage','fire',5);self.assertFalse(other.tape_cache.entries)
  with mock.patch.dict(os.environ,{'FARM_FIRE_TAPE_CACHE':'0'}):other.dps_many(self.bs)
  self.assertFalse(other.tape_cache.entries)

 def test_bounded_tapes_not_retained_by_global_array_cache(self):
  from farm.hybrid import fight
  gpu=registry.make_engine(self.dev,'mage','fire',5);gpu.dps_many(self.bs)
  for events,_,_ in gpu.tape_cache.entries.values():self.assertNotIn(id(events),fight._EVENT_CACHE)
