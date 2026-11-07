"""Scalar/capture/cache/routing contracts; real DirectML when requested."""
import os,unittest,sys
from dataclasses import replace
from unittest import mock
from farm.hybrid import fight as F,registry,mage_scalar as S
from farm.hybrid.mage_reuse import TapeLRU
from farm.hybrid.mage_prepare import SheetLRU
from farm.hybrid.device import DeviceInfo,detect
from sunken_sim import mage,stacking
from sunken_sim.esc import apply_points,empty_points
from farm.test_hybrid import _sample

class ScalarTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.bs=_sample('mage','fire',8,5)
 def test_payload_ring_esc_blazing_and_old_capture(self):
  for targets in (1,5):
   for base in self.bs:
    for blazing in (False,True):
     b=replace(base,talents=(base.talents|{'I0KR','I0UP'}) if blazing else base.talents-{'I0KR'})
     for points in (0,20):
      p=empty_points();p['potency']=points;b=apply_points(b,p)
      keys=[k for k in mage._buttons('fire')] if mage._wears(b,'I00D') else [None]
      rows=S.generate_scalar_timelines([b]*len(keys),'fire',targets,keys)
      refs=F.timelines(b,targets,'fire',cache=False)
      for key,row in zip(keys,rows):
       ref=next(t for t in refs if t.bound==key)
       self.assertEqual(list(row[0]),ref.events)
       self.assertEqual(row[1],ref.stats)
 def test_fire_planners_use_no_global_tape_or_event_cache_even_disabled(self):
  class Forbidden(dict):
   def get(self,*a):raise AssertionError('legacy global cache touched')
   def __setitem__(self,*a):raise AssertionError('legacy global cache touched')
  for planner in ('scalar','vector'):
   for cache in ('0','1'):
    with self.subTest(planner=planner,cache=cache),mock.patch.dict(os.environ,{'FARM_FIRE_PLANNER':planner,'FARM_FIRE_TAPE_CACHE':cache}),mock.patch.object(F,'_TL_CACHE',Forbidden()),mock.patch.object(F,'_EVENT_CACHE',Forbidden()):
     g=F.GpuFights(DeviceInfo('cpu','cpu'),'mage','fire',5)
     a=g.dps_many(self.bs);b=g.dps_many(self.bs)
     self.assertEqual(a,b)
     self.assertTrue(F.compare([F.cpu_dps(x,5,'fire') for x in self.bs],a)['ok'])
     self.assertGreater(g.timeline_counts['scalar_rows' if planner=='scalar' else 'vector_checked_rows'],0)
 def test_state_key_reuse_fresh_stats_and_blazing_cadence(self):
  base=apply_points(replace(self.bs[0],talents=self.bs[0].talents-{'I0KR'}),empty_points())
  for mode in ('scalar','vector'):
   c=TapeLRU();c.mode=mode;c.sync_context('fire',5);self.assertTrue(c.split)
   p=empty_points();p['potency']=20;b=apply_points(base,p)
   self.assertEqual(c.key(base,mage.sheet(base),None),c.key(b,mage.sheet(b),None))
   x=replace(base,talents=base.talents|{'I0KR'});y=apply_points(x,p)
   self.assertNotEqual(c.key(x,mage.sheet(x),None),c.key(y,mage.sheet(y),None))
  c=TapeLRU();c.mode='scalar';c.sync_context('fire',5)
  st=mage.sheet(base);other=dict(st,ad=st['ad']+2)
  self.assertEqual(c.key(base,st,None),c.key(base,other,None))
  g=F.GpuFights(DeviceInfo('cpu','cpu'),'mage','fire',5)
  with mock.patch.dict(os.environ,{'FARM_FIRE_PLANNER':'scalar'}):
   g.dps_many([base]);g.dps_many([b]);self.assertGreater(g.tape_cache.counts['hits'],0)
 def test_cadence_key_read_guard_and_missing_key_mutation(self):
  from farm.test_hybrid import TimelineCacheTest
  t=TimelineCacheTest();c=TapeLRU();c.mode='scalar';c.sync_context('fire',5)
  for spec,builds,reads,_ in t._timeline_reads():
   b=builds[0];st=mage.sheet(b);st.update(crit_as=.2,crit_as_duration=5)
   t._assert_key_covers(c.key,b,st,reads)
   real=c.key
   def broken(b,s,k):return real(b,dict(s,mana_max=0),k)
   with self.assertRaisesRegex(AssertionError,'mana_max'):t._assert_key_covers(broken,b,st,reads)
 def test_mana_on_crit_without_crit_as_is_in_cadence_key(self):
  b=self.bs[0];st=dict(mage.sheet(b),crit_as=0,crit_as_duration=0,
                     attack_mana_crit=True,attack_mana=50,mana_max=500,mana_regen=0,crit=10)
  hi=dict(st,crit=90);c=TapeLRU();c.mode='scalar';c.sync_context('fire',5)
  self.assertTrue(c.split);self.assertNotEqual(c.key(b,st,None),c.key(b,hi,None))
  bs=[b,b];ks=['Hydra' if mage._wears(b,'I00D') else None]*2
  def generate(bs,ks,ss):return S.generate_scalar_timelines(bs,'fire',5,ks,ss)
  got=c.rows(bs,'fire',5,ks,generate,[st,hi]);ref=generate(bs,ks,[st,hi])
  self.assertEqual(got,ref);self.assertEqual(c.counts['generated_rows'],2)
  self.assertNotEqual(ref[0][0],ref[1][0])
 def test_source_config_eviction_and_ordered_mutable_items(self):
  c=TapeLRU(max_entries=1,max_bytes=1_000_000);c.mode='scalar'
  b=self.bs[0];c.rows([b],'fire',5,[None],lambda bs,ks,ss:S.generate_scalar_timelines(bs,'fire',5,ks,ss))
  self.assertLessEqual(c.bytes,c.max_bytes)
  before=c.context
  with mock.patch.object(mage,'FIGHT',31):c.sync_context('fire',5);self.assertNotEqual(before,c.context);self.assertFalse(c.entries)
  with mock.patch.object(S,'generate_scalar_timelines',lambda *a:None):c.sync_context('fire',5);self.assertFalse(c.split)
  c.sync_context('fire',5);st=mage.sheet(b)
  rev=replace(b,items=tuple(reversed(b.items)))
  self.assertNotEqual(c.key(b,st,None),c.key(rev,st,None))
  item=replace(b.items[0],tip=b.items[0].tip+'\n+1 Health')
  changed=replace(b,items=(item,)+b.items[1:]);self.assertNotEqual(c.key(b,st,None),c.key(changed,st,None))
 def test_once_preparation_is_exact_and_never_retained(self):
  from farm.hybrid.mage_prepare import fresh_rows
  guard=TapeLRU();bs=self.bs+[self.bs[0]]
  st=fresh_rows(bs,guard,'fire',5)
  self.assertEqual(st,[mage.sheet(b) for b in bs])
  st[0]['executes'].append((1,1));self.assertNotEqual(st[0],st[-1])
  self.assertEqual(fresh_rows(bs,guard,'fire',5),[mage.sheet(b) for b in bs])
 def test_preparation_exact_bounded_mutation_and_invalidation(self):
  for mode in ('items','full'):
   c=SheetLRU(max_entries=3,max_bytes=200000);guard=TapeLRU();bs=self.bs
   with mock.patch.dict(os.environ,{'FARM_FIRE_PREP_CACHE':mode}):
    ref=[mage.sheet(b) for b in bs];self.assertEqual(c.rows(bs,guard,'fire',5),ref)
    self.assertLessEqual(c.bytes,c.max_bytes);self.assertLessEqual(len(c.entries),3)
    got=c.rows([bs[-1]],guard,'fire',5);got[0]['executes'].append((1,1))
    self.assertEqual(c.rows([bs[-1]],guard,'fire',5),[mage.sheet(bs[-1])])
    original=c.context
    with mock.patch.dict(stacking.stack_profiles(),{'TEST':{'mana':1}}):c.rows([bs[-1]],guard,'fire',5);self.assertNotEqual(c.context,original)
    with mock.patch.object(mage,'sheet',wraps=mage.sheet):self.assertEqual(c.rows([bs[-1]],guard,'fire',5),[mage.sheet(bs[-1])]);self.assertGreater(c.counts['unverified_rows'],0)
 def test_jit_failure_exact_fallback_and_no_dependency_required(self):
  from farm.hybrid import mage_jit
  bs=[self.bs[0]];keys=['Hydra' if mage._wears(bs[0],'I00D') else None]
  normal=S.generate_scalar_timelines(bs,'fire',5,keys);counts={}
  def broken(*args):raise RuntimeError('injected native failure')
  with mock.patch.dict(os.environ,{'FARM_FIRE_JIT_HYDRA':'1'}),mock.patch.object(mage_jit,'hooks',return_value=(broken,list)):
   self.assertEqual(S.generate_scalar_timelines(bs,'fire',5,keys,diagnostics=counts),normal)
  self.assertEqual(counts['jit_fallback_rows'],1)
  with mock.patch.dict(os.environ,{'FARM_FIRE_JIT_HYDRA':'1'}),mock.patch.object(mage_jit,'hooks',side_effect=ImportError('optional absent')):
   self.assertEqual(S.generate_scalar_timelines(bs,'fire',5,keys,diagnostics=counts),normal)
  self.assertEqual(counts['jit_unavailable'],1)
 def test_chunk2_vector_cadence_is_canonicalized_not_score_tolerance(self):
  import torch
  from farm.catalog import load
  from sunken_sim.shadow import Build
  from farm.hybrid import mage_gpu_timeline as M
  _,items=load('mage','fire','mixed',None,100)
  b=Build(frozenset({'I0KU','I0NZ','I0UP'}),frozenset({'I07B','I0H3','I0JA'}),tuple(items[x] for x in ('sbok','sor7','sor7','sor7','sor7','sor8')),0,0)
  p=empty_points();p.update(haste=1,attack_speed=1,potency=20,luck=8);b=apply_points(b,p)
  raw=M._mage_batch(torch,torch.device('cpu'),torch.float64,[b],'fire',5,[None])
  exact=mage.simulate(b,5,spec='fire',use_history=False,_capture_only=True)
  count={};fixed=S.verify_vector_rows([b],'fire',5,[None],raw,None,count)
  self.assertEqual(list(fixed[0][0]),exact[0]);self.assertEqual(count['vector_checked_rows'],1)
  broken=[(raw[0][0][:-1],)+raw[0][1:]]
  count={};fixed=S.verify_vector_rows([b],'fire',5,[None],broken,None,count)
  self.assertEqual(list(fixed[0][0]),exact[0]);self.assertEqual(count['vector_repaired_rows'],1)
 def test_actual_directml_scalar_and_vector_with_guards(self):
  info=detect('mage','fire')
  if not info.gpu:
   if os.environ.get('FARM_HYBRID_TEST_DML')=='1':self.fail(info.reason)
   self.skipTest(info.reason)
  ref=[F.cpu_dps(b,5,'fire') for b in self.bs]
  for mode in ('scalar','vector'):
   with mock.patch.dict(os.environ,{'FARM_FIRE_PLANNER':mode,'FARM_FIRE_PREP_CACHE':'items'}):
    g=F.GpuFights(info,'mage','fire',5);a=g.dps_many(self.bs);b=g.dps_many(self.bs)
    self.assertEqual(a,b);self.assertTrue(F.compare(ref,a)['ok'])
    self.assertGreater(g.tape_cache.counts['hits'],0)
    self.assertGreater(g.score_counts['selection_exact_builds'],0)

class FireRouteTests(unittest.TestCase):
 def test_auto_explicit_and_nonfire_policy(self):
  from farm.hybrid.fire_route import select
  j=dict(hero='mage',spec='fire')
  with mock.patch.dict(os.environ,{},clear=False):
   os.environ.pop('FARM_FIRE_BACKEND',None);self.assertEqual(select(j)['selected'],'cpu')
  with mock.patch.dict(os.environ,{'FARM_FIRE_BACKEND':'hybrid'}):
   self.assertEqual(select(j)['selected'],'hybrid');self.assertEqual(select(dict(j,fire_backend='cpu'))['selected'],'cpu')
  self.assertIsNone(select(dict(hero='priest',spec='shadow')))
  with self.assertRaises(ValueError):select(dict(j,fire_backend='bad'))
 def test_cpu_route_honest_status_no_device_and_offline_adapter(self):
  from farm import discord_runner,runner
  from farm.hybrid import runner as H
  j=dict(hero='mage',spec='fire',worker='fixture',fire_backend='auto')
  with mock.patch.object(H,'detect',side_effect=AssertionError('no device')) as d,mock.patch.object(runner,'run_job',return_value={'ok':1}) as run:
   self.assertEqual(discord_runner.run_job(j,{},lambda s:None),{'ok':1})
  d.assert_not_called();meta=run.call_args.args[0]['hybrid']
  self.assertEqual(meta['status'],'cpu-selected');self.assertEqual(meta['device'],'cpu');self.assertFalse(meta['gpu_fights'])
  self.assertNotIn('eval_fn',run.call_args.kwargs)

if __name__=='__main__':unittest.main()
