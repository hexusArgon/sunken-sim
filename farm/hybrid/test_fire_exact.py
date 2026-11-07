import os,sys,unittest
from dataclasses import replace
from unittest import mock
from farm.hybrid import fight as F,mage_gpu_timeline as M
from farm.hybrid.device import DeviceInfo,detect
from farm.test_hybrid import _sample
from sunken_sim import mage
from sunken_sim.shadow import Build
from sunken_sim.esc import empty_points,apply_points

def repro():
 from farm.catalog import load
 _,items=load('mage','fire','mixed',None,100)
 b=Build(frozenset({'I0KU','I0NZ','I0UP'}),frozenset({'I07B','I0H3','I0JA'}),tuple(items[x] for x in ('sbok','sor7','sor7','sor7','sor7','sor8')),0,0)
 p=empty_points();p.update(haste=1,attack_speed=1,potency=20,luck=8)
 return apply_points(b,p)

class HydraHistoryTest(unittest.TestCase):
 def test_raw_reproducer_payload_matches_not_just_score(self):
  import torch
  b=repro();ref=mage.simulate(b,5,spec='fire',use_history=False,_capture_only=True)
  row=M._mage_batch(torch,torch.device('cpu'),torch.float64,[b],'fire',5,[None])[0]
  self.assertEqual(len(row[0]),194);self.assertEqual(row,ref)
 def test_adversarial_luck_as_thresholds(self):
  import torch
  builds=[]
  for luck in (5,6,7,8,9):
   for speed in (0,1,2):
    p=empty_points();p.update(haste=1,attack_speed=speed,luck=luck,potency=29-luck-speed);builds.append(apply_points(repro(),p))
  rows=M.generate_mage_timelines(torch,torch.device('cpu'),builds,'fire',5)
  for b,row in zip(builds,rows):
   ref=mage.simulate(b,5,spec='fire',use_history=False,_capture_only=True)
   self.assertEqual(len(row[0]),len(ref[0]));self.assertTrue(F.compare([mage._score(mage._compile(row[0],b,row[1],row[2],row[3]),row[1],b,'fire')[0]],[mage.simulate(b,5,spec='fire',use_history=False).dps*mage.FIGHT])['ok'])
 def test_bounded_history_rejects_never_silently_drops(self):
  import torch
  b=repro();count={}
  with mock.patch.object(M,'MAX_HYDRA',1):
   with self.assertRaisesRegex(RuntimeError,'history capacity'):M._mage_batch(torch,torch.device('cpu'),torch.float64,[b],'fire',5,[None])
   rows=M.generate_mage_timelines(torch,torch.device('cpu'),[b],'fire',5,diagnostics=count)
  ref=mage.simulate(b,5,spec='fire',use_history=False,_capture_only=True)
  self.assertEqual(rows[0],ref);self.assertEqual(count['cpu_fallback_rows'],1)

class ExactTapeTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.bs=_sample('mage','fire',8,551)
 def test_real_dml_no_duplicate_oracle_simulation(self):
  info=detect('mage','fire');self.assertTrue(info.gpu,info.reason)
  g=F.GpuFights(info,'mage','fire',5);ref=[F.cpu_dps(b,5,'fire') for b in self.bs];calls={'capture':0,'oracle':0}
  code=mage.simulate.__code__
  def prof(frame,event,arg):
   if event=='call' and frame.f_code is code:calls['capture' if frame.f_locals.get('_capture_only') else 'oracle']+=1
  sys.setprofile(prof)
  try:a=g.dps_many(self.bs);z=g.dps_many(self.bs)
  finally:sys.setprofile(None)
  self.assertTrue(F.compare(ref,a)['ok']);self.assertEqual(a,z);self.assertEqual(calls['oracle'],0);self.assertGreater(calls['capture'],0)
  self.assertGreater(g.score_counts['canonical_owner_builds'],0);self.assertIsNone(g._exact_current)
 def test_guarded_old_path_remains_explicit_and_equal(self):
  g=F.GpuFights(DeviceInfo('cpu','cpu'),'mage','fire',5)
  with mock.patch.dict(os.environ,{'FARM_FIRE_EXACT_TAPE_SCORE':'0'}):old=g.dps_many(self.bs)
  new=g.dps_many(self.bs);self.assertEqual(old,new);self.assertGreater(g.score_counts['oracle_resim_builds'],0)
 def test_alias_unknown_source_and_horizon_fail_closed(self):
  g=F.GpuFights(DeviceInfo('cpu','cpu'),'mage','fire',5);bs=self.bs[:2];old=mage.stats_of
  def starve(b):
   st=old(b);st['mana_max']*=.12;return st
  for patch in (mock.patch.object(mage,'stats_of',starve),mock.patch.object(mage,'FIGHT',31),mock.patch.object(mage,'_score',wraps=mage._score)):
   with patch:
    ref=[mage.simulate(b,5,spec='fire',use_history=False).dps for b in bs]
    self.assertEqual(g.dps_many(bs),ref)
 def test_mandatory_vector_verification_still_repairs_clipping(self):
  import torch
  from farm.hybrid import mage_scalar as S
  b=repro();raw=M._mage_batch(torch,torch.device('cpu'),torch.float64,[b],'fire',5,[None]);raw=[(raw[0][0][:-1],)+raw[0][1:]];counter={}
  rows=S.verify_vector_rows([b],'fire',5,[None],raw,None,counter)
  self.assertEqual(rows[0],mage.simulate(b,5,spec='fire',use_history=False,_capture_only=True));self.assertEqual(counter['vector_repaired_rows'],1)
 def test_compile_context_preserves_entire_oracle_dictionary(self):
  from farm.hybrid.mage_exact import compile_exact
  from farm.hybrid.mage_reuse import TapeLRU
  guard=TapeLRU();guard.mode='scalar';guard.sync_context('fire',5);self.assertTrue(guard.split)
  for base in self.bs:
   for codes in ((),(mage._FURNACE,),(mage._CRIMSON,),(mage._GLADIATOR_MASK,),(mage._FURNACE,mage._CRIMSON,mage._GLADIATOR_MASK)):
    items=list(base.items)
    for j,code in enumerate(codes):items[j]=replace(items[j],rawcode=code)
    b=replace(base,items=tuple(items))
    for tl in F.timelines(b,5,'fire',cache=False):
     oracle=mage._compile(tl.events,b,tl.stats,tl.spec,tl.evocation)
     self.assertEqual(compile_exact(tl,guard),oracle)
     self.assertEqual(mage._score(compile_exact(tl,guard),tl.stats,b,'fire'),mage._score(oracle,tl.stats,b,'fire'))
