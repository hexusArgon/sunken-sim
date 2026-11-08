"""Job-local Fire DML resource controls, not a new scoring route."""
import multiprocessing as mp
import unittest
from unittest import mock
from farm import runner as R
from farm.hybrid import runner as H

class FireDmlResourcesTest(unittest.TestCase):
 def test_conservative_default_and_explicit_six(self):
  self.assertEqual(R.fire_dml_worker_count({}),1)
  self.assertEqual(R.fire_dml_worker_count({'fire_dml_workers':6}),6)
  ctx=mock.Mock()
  R.fire_dml_context_budget(dict(hero='mage',spec='fire',fire_dml_workers=6,hybrid={'device':'dml'}),ctx)
  ctx.BoundedSemaphore.assert_called_once_with(6)
 def test_reject_unmeasured_or_ambiguous_counts(self):
  for value in (0,-1,7,15,True,False,6.0,'6',None):
   with self.subTest(value=value),self.assertRaises(ValueError):R.fire_dml_worker_count({'fire_dml_workers':value})
 def test_six_leases_and_nine_honest_fallbacks(self):
  ctx=mp.get_context('spawn');budget=R.fire_dml_context_budget(dict(hero='mage',spec='fire',fire_dml_workers=6,hybrid={'device':'dml'}),ctx)
  names=['_SPACE','_ITEMS','_SOURCES','_HERO','_SPEC','_TARGETS','_BAR','_STOP','_FIRE_DML_ALLOWED'];old={n:getattr(R,n) for n in names};leases=[]
  try:
   for _ in range(15):
    R.init_worker(None,{},{} ,'mage','fire',5,None,None,budget);leases.append(R._FIRE_DML_ALLOWED)
   self.assertEqual(leases,[True]*6+[False]*9)
  finally:
   for n,v in old.items():setattr(R,n,v)
 def test_worker_identity_telemetry_is_additive(self):
  job=dict(hero='mage',spec='fire',hybrid=dict(device='dml',name='fixture',gpu_fights=True))
  p=dict(actual='hybrid',pid=42,engine_state='gpu',gpu_compile_rows=256,cpu_compile_rows=0,reasons=[])
  R._record_fire_execution(job,dict(fire_execution=p));R._record_fire_execution(job,dict(fire_execution=p))
  self.assertEqual(job['hybrid']['worker_processes']['42'],dict(returned_spans=2,gpu_compile_rows=512,cpu_compile_rows=0,actual='hybrid',engine_state='gpu'))
 def test_six_uses_exited_preflight_not_parent_detect(self):
  result=dict(ok=True,meta=dict(device='dml',name='fixture',prep={'parity':True},fights={'ok':True}),lifecycle=dict(pid=123,exited=True,exitcode=0,isolated=True))
  job=dict(hero='mage',spec='fire',fire_dml_workers=6,pool='mixed',top=80,targets=5,start=0,end=0)
  with mock.patch('farm.hybrid.preflight.isolated_fire_preflight',return_value=result),mock.patch.object(H,'detect') as detect,mock.patch.object(R,'run_job',return_value={'done':1}) as run:
   self.assertEqual(H.run_job(job,{},lambda v:None),{'done':1});detect.assert_not_called()
   actual=run.call_args.args[0];self.assertEqual(actual['fire_dml_workers'],6);self.assertTrue(actual['hybrid']['preflight']['exited'])
 def test_requested_multi_gpu_preflight_failure_does_not_start_cpu_farm(self):
  job=dict(hero='mage',spec='fire',fire_dml_workers=6,pool='mixed',top=80,targets=5,start=0,end=0)
  with mock.patch('farm.hybrid.preflight.isolated_fire_preflight',return_value=dict(ok=False,reason='fixture',meta={})),mock.patch.object(R,'run_job') as run,self.assertRaises(RuntimeError):
   H.run_job(job,{},lambda v:None)
  run.assert_not_called()
 def test_resources_not_scoring_identity(self):
  from farm.catalog import load
  from farm import admission as A
  space,items=load('mage','fire','mixed',None,80)
  j=dict(hero='mage',spec='fire',pool='mixed',top=80,targets=5,start=0,end=312052229)
  a=A.configure(j,space,items);b=A.configure(dict(j,fire_dml_workers=6),space,items)
  self.assertEqual(A.metadata(a),A.metadata(b));self.assertEqual(A.suffix(a),A.suffix(b))
 def test_signature_guards_still_reject_other_source(self):
  saved=dict(search_schema=2,admission_policy='bare-top10',catalog_fingerprint='catalog',scoring_fingerprint='old')
  self.assertFalse(R._same_job(saved,dict(saved,scoring_fingerprint='new')))
 def test_preflight_is_fire_only(self):
  from farm.hybrid.preflight import isolated_fire_preflight
  with self.assertRaises(ValueError):isolated_fire_preflight(dict(hero='mage',spec='frost'))
if __name__=='__main__':unittest.main()
