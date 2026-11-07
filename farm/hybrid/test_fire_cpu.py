import os,sys,unittest
from dataclasses import replace
from unittest import mock
from farm.hybrid.fire_cpu import CpuFireFights
from farm.test_hybrid import _sample
from sunken_sim import mage
from sunken_sim.esc import empty_points,apply_points

class CpuStagedTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.bs=_sample('mage','fire',8,551)
 def test_cpu_staged_exact_ring_bs_points_and_stale_parameters(self):
  c=CpuFireFights(5)
  for targets in (5,1,3,5):
   c.targets=targets;bs=[]
   for b in self.bs:
    for pts in (0,15):
     p=empty_points();p['potency']=pts
     bs.append(apply_points(replace(b,talents=b.talents|{'I0KR'}),p))
   self.assertEqual(c.dps_many(bs),[mage.simulate(b,targets,spec='fire',use_history=False).dps for b in bs]);self.assertIsNone(c._exact_current)
  self.assertGreater(c.tape_cache.counts['invalidations'],1)

 def test_cpu_staged_does_not_import_torch(self):
  import subprocess
  script="import sys;sys.modules['torch']=None;sys.modules['torch_directml']=None;from farm.hybrid.fire_cpu import CpuFireFights;from farm.test_hybrid import _sample;from sunken_sim import mage;b=_sample('mage','fire',1,7)[0];assert CpuFireFights(5).dps_many([b])==[mage.simulate(b,5,spec='fire',use_history=False).dps]"
  subprocess.run([sys.executable,'-c',script],check=True,capture_output=True)

 def test_optin_cpu_runtime_metadata_and_no_device_detection(self):
  from farm.hybrid import runner as H
  from farm import runner as R
  job=dict(hero='mage',spec='fire',fire_backend='auto',fire_cpu_staged=True)
  with mock.patch.object(H,'detect',side_effect=AssertionError('CPU never detects')),mock.patch.object(R,'run_job',return_value={}) as run:
   H.run_job(job,{},lambda _:None)
  self.assertEqual(run.call_args.args[0]['hybrid']['actual_planner'],'cpu-staged-scalar');self.assertEqual(run.call_args.args[0]['hybrid']['device'],'cpu');self.assertEqual(run.call_args.kwargs['eval_fn'].__module__,'farm.hybrid.fire_cpu')

 def test_unknown_alias_source_and_horizon_use_public_oracle(self):
  c=CpuFireFights(5);bs=self.bs[:2];old=mage.stats_of
  def starve(b):
   st=old(b);st['mana_max']*=.12;return st
  for patch in (mock.patch.object(mage,'stats_of',starve),mock.patch.object(mage,'FIGHT',31),mock.patch.object(mage,'_score',wraps=mage._score)):
   with patch:
    self.assertEqual(c.dps_many(bs),[mage.simulate(b,5,spec='fire',use_history=False).dps for b in bs])
  self.assertGreater(c.score_counts['cpu_oracle_fallback_builds'],0)
