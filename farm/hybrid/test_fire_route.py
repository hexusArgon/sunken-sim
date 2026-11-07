"""Unified Fire job route; CPU math is an oracle/fallback, not another backend."""
import os,unittest
from unittest import mock
from dataclasses import replace
from farm.hybrid import runner as H,fight as F
from farm import runner as R
from farm.hybrid.device import detect,DeviceInfo
from farm.test_hybrid import _sample
from sunken_sim import mage
from sunken_sim.esc import empty_points,apply_points

class HybridOnlyTest(unittest.TestCase):
 def test_every_legacy_backend_uses_hybrid_eval(self):
  from farm.hybrid.engine import eval_span
  for mode in ('auto','cpu','staged','hybrid'):
   j=dict(hero='mage',spec='fire',pool='mixed',start=0,end=0,targets=5,fire_backend=mode,fire_cpu_staged=True)
   with mock.patch.object(H,'detect',return_value=DeviceInfo('dml','fixture')),mock.patch.object(H,'prep_check',return_value={'parity':True}),mock.patch.object(H,'fight_check',return_value={'ok':True}),mock.patch('farm.catalog.load',return_value=(object(),{})),mock.patch.object(R,'run_job',return_value={}) as run:
    H.run_job(j,{},lambda _:None)
   self.assertIs(run.call_args.kwargs['eval_fn'],eval_span);m=run.call_args.args[0]['hybrid'];self.assertEqual(m['selection']['actual'],'hybrid');self.assertEqual(m['device'],'dml');self.assertNotIn('cpu-staged',m.get('actual_planner',''))
 def test_local_fire_run_job_and_dispatch_cannot_select_cpu(self):
  j=dict(hero='mage',spec='fire',worker='any-name',fire_backend='cpu')
  self.assertIs(H.dispatch(j),H.run_job)
  with mock.patch.object(H,'run_job',return_value={'route':'hybrid'}) as run:
   self.assertEqual(R.run_job(j,{},lambda _:None),{'route':'hybrid'});run.assert_called_once()
 def test_worker_fallback_metadata_is_not_gpu_only(self):
  j=dict(hero='mage',spec='fire',hybrid=dict(device='dml',name='fixture',gpu_fights=True,selection={'selected':'hybrid'}))
  R._record_fire_execution(j,dict(fire_execution=dict(actual='cpu-fallback',reasons=['GPU lost'],cpu_compile_rows=1)))
  self.assertEqual(j['hybrid']['device'],'cpu');self.assertEqual(j['hybrid']['status'],'cpu-fallback');self.assertFalse(j['hybrid']['gpu_fights']);self.assertEqual(j['hybrid']['name'],'cpu')
  R._record_fire_execution(j,dict(fire_execution=dict(actual='hybrid',reasons=[])))
  self.assertEqual(j['hybrid']['device'],'mixed');self.assertEqual(j['hybrid']['status'],'hybrid-with-cpu-fallback')
 def test_real_dml_ring_bs_points_targets_and_exact_oracle_compile(self):
  from farm.hybrid.mage_exact import compile_exact
  g=F.GpuFights(detect('mage','fire'),'mage','fire',5);self.assertTrue(g.device.gpu)
  base=_sample('mage','fire',8,551)
  for targets in (5,1,3,5):
   g.targets=targets;bs=[]
   for b in base:
    for pts in (0,15):
     p=empty_points();p['potency']=pts;bs.append(apply_points(replace(b,talents=b.talents|{'I0KR'}),p))
   ref=[mage.simulate(b,targets,spec='fire',use_history=False).dps for b in bs]
   self.assertTrue(F.compare(ref,g.dps_many(bs))['ok'])
   for b,expected in zip(bs,ref):
    values=[mage._score(compile_exact(t,g.tape_cache),t.stats,b,'fire')[0]/mage.FIGHT for t in F.timelines(b,targets,'fire',cache=False)]
    self.assertEqual(max(values),expected)
  self.assertGreater(g.tape_cache.counts['invalidations'],1)
 def test_removed_staged_module_not_available(self):
  import importlib.util
  self.assertIsNone(importlib.util.find_spec('farm.hybrid.fire_cpu'))
