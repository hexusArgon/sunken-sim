"""Fire-only DirectML multi-context containment, retaining honest CPU fallback."""
import multiprocessing as mp
import unittest
from unittest import mock
from farm import runner as R
from farm.hybrid import engine as E, registry

class FireDmlBudgetTest(unittest.TestCase):
 def test_only_fire_dml_gets_one_shared_context(self):
  ctx=mock.Mock();token=ctx.BoundedSemaphore.return_value
  for hero,spec,device in [('mage','fire','cpu'),('paladin','holy','dml'),('warrior','fury','dml')]:
   self.assertIsNone(R.fire_dml_context_budget(dict(hero=hero,spec=spec,hybrid={'device':device}),ctx))
  ctx.BoundedSemaphore.assert_not_called()
  self.assertIs(R.fire_dml_context_budget(dict(hero='mage',spec='fire',hybrid={'device':'dml'}),ctx),token)
  ctx.BoundedSemaphore.assert_called_once_with(1)
 def test_fifteen_workers_have_one_lease_without_waiting(self):
  budget=mp.get_context('spawn').BoundedSemaphore(1)
  names=['_SPACE','_ITEMS','_SOURCES','_HERO','_SPEC','_TARGETS','_BAR','_STOP','_FIRE_DML_ALLOWED','_SCOPED_DML_ALLOWED']
  old={n:getattr(R,n) for n in names};leases=[]
  try:
   for _ in range(15):
    R.init_worker(None,{},{} ,'mage','fire',5,None,None,budget);leases.append(R._FIRE_DML_ALLOWED)
   self.assertEqual(leases,[True]+[False]*14)
  finally:
   for n,v in old.items():setattr(R,n,v)
 def test_other_class_and_legacy_init_do_not_acquire(self):
  names=['_SPACE','_ITEMS','_SOURCES','_HERO','_SPEC','_TARGETS','_BAR','_STOP','_FIRE_DML_ALLOWED','_SCOPED_DML_ALLOWED']
  old={n:getattr(R,n) for n in names};budget=mock.Mock()
  try:
   R.init_worker(None,{},{} ,'paladin','holy',5,None,None,budget);budget.acquire.assert_not_called();self.assertTrue(R._FIRE_DML_ALLOWED)
   R.init_worker(None,{},{} ,'mage','fire',5,None,None);self.assertTrue(R._FIRE_DML_ALLOWED)
  finally:
   for n,v in old.items():setattr(R,n,v)
 def test_denied_worker_falls_back_before_creating_device(self):
  with mock.patch.multiple(R,_HERO='mage',_SPEC='fire',_FIRE_DML_ALLOWED=False),mock.patch.multiple(E,_ENGINE=None,_ENGINE_STATE=None,_ENGINE_NOTE=''),mock.patch.object(registry,'make_engine') as make:
   self.assertIsNone(E._engine());self.assertEqual(E._ENGINE_STATE,'cpu');self.assertIn('context budget',E._ENGINE_NOTE);make.assert_not_called()
 def test_other_class_routing_is_not_budget_denied(self):
  with mock.patch.multiple(R,_HERO='mage',_SPEC='frost',_FIRE_DML_ALLOWED=False,_TARGETS=5),mock.patch.multiple(E,_ENGINE=None,_ENGINE_STATE=None,_ENGINE_NOTE=''),mock.patch.object(registry,'gpu_engine_for',return_value=False):
   self.assertIsNone(E._engine());self.assertNotIn('context budget',E._ENGINE_NOTE)
 def test_mixed_execution_is_not_reported_as_gpu_only(self):
  job=dict(hero='mage',spec='fire',hybrid=dict(device='dml',name='fixture',gpu_fights=True,selection={'selected':'hybrid'}))
  R._record_fire_execution(job,dict(fire_execution=dict(actual='cpu-fallback',reasons=['DirectML Fire context budget'],cpu_compile_rows=1)))
  self.assertEqual(job['hybrid']['device'],'cpu');self.assertFalse(job['hybrid']['gpu_fights'])
  R._record_fire_execution(job,dict(fire_execution=dict(actual='hybrid',reasons=[])))
  self.assertEqual(job['hybrid']['device'],'mixed');self.assertEqual(job['hybrid']['status'],'hybrid-with-cpu-fallback')
 def test_fire_algebra_value_is_canonical_without_changing_points(self):
  from sunken_sim.shadow import Build
  from sunken_sim.esc import empty_points
  e=E.BatchFights();e.hero='mage';e.spec='fire';e.targets=5;e.dps_many=mock.Mock(return_value=[9.,9.])
  b=Build(frozenset(),frozenset(),(),0,0);points=empty_points();points['crit']=1
  result=e._canonical_fire_esc([b],[(8.999999,points)])
  self.assertEqual(result,[(9.,points)]);self.assertIs(result[0][1],points);self.assertEqual(len(e.dps_many.call_args.args[0]),2)
 def test_other_class_algebra_score_is_untouched(self):
  e=E.BatchFights();e.hero='paladin';e.spec='holy';e.dps_many=mock.Mock();r=[(7.,{})]
  self.assertIs(e._canonical_fire_esc([None],r),r);e.dps_many.assert_not_called()
 def test_real_dml_algebra_final_payload_matches_cpu_oracle(self):
  from farm.catalog import load
  from farm.hybrid.fight import GpuFights
  from farm.hybrid.device import detect
  from farm.score import finish_sextuple
  space,items=load('mage','fire','mixed',None,80);equipped=tuple(items[c] for c in space.decode(0)[0])
  call=(equipped,space.talents,space.glyphs,space.picks_without,space.picks_with,space.glyph_picks)
  g=GpuFights(detect('mage','fire'),'mage','fire',5);self.assertTrue(g.device.gpu)
  out=g.finish_many([call],esc='algebra')[0];oracle=finish_sextuple('mage','fire',5,*call)
  self.assertEqual(out[:4],oracle[:4])
if __name__=='__main__':unittest.main()
