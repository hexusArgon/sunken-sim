import os,unittest
from unittest.mock import patch
import numpy as np
import torch
from farm.hybrid.mage_gpu_timeline import _store_hydra_groups

class HydraStoreTests(unittest.TestCase):
 def test_storage_bitwise_masks_first_free_full_rows_both_dtypes(self):
  torch.set_num_threads(1)
  rng=np.random.RandomState(238)
  for dtype in (torch.float32,torch.float64):
   for rows,width in ((1,1),(17,9),(32,256)):
    alive=torch.tensor(rng.random_sample((rows,width))>.4);alive[0,:]=True
    if rows>1:alive[1,:]=False
    original=[alive,torch.randn((rows,width),dtype=dtype),torch.randn((rows,width),dtype=dtype)]
    mask=torch.tensor(rng.random_sample(rows)>.3);mask[0]=True
    now=torch.randn(rows,dtype=dtype);duration=torch.randn(rows,dtype=dtype);count=torch.randn(rows,dtype=dtype)
    a=[x.clone() for x in original];b=[x.clone() for x in original]
    with patch.dict(os.environ,{'FARM_MAGE_FAST_HYDRA':'0'}):_store_hydra_groups(torch,*a,mask,now,duration,count)
    with patch.dict(os.environ,{'FARM_MAGE_FAST_HYDRA':'1'}):_store_hydra_groups(torch,*b,mask,now,duration,count)
    for x,y in zip(a,b):self.assertTrue(torch.equal(x,y))
 def test_empty_mask_unchanged(self):
  a=torch.zeros((2,3),dtype=torch.bool);e=torch.ones((2,3),dtype=torch.float64);c=e.clone();v=torch.ones(2,dtype=torch.float64)
  with patch.dict(os.environ,{'FARM_MAGE_FAST_HYDRA':'1'}):_store_hydra_groups(torch,a,e,c,torch.zeros(2,dtype=torch.bool),v,v,v)
  self.assertFalse(a.any());self.assertTrue(torch.equal(e,c))
 def test_complete_fire_tapes_original_vs_fast_including_blazing_soul(self):
  from farm.hybrid import mage_gpu_timeline as M,engine
  from farm.catalog import _parts
  from sunken_sim import mage
  from sunken_sim.shadow import Build
  from dataclasses import replace
  items=_parts('mage','fire','mixed',None,100)[5]
  gear=tuple(items[c] for c in ('I04G','I06U','I0BR','I0D8','fgrd','sor8'))
  bs=[Build(frozenset({'I0KR','I0NZ','I0UP'}),frozenset({'I07B','I0H3','I0JA'}),gear,0,0),Build(frozenset({'I0KU','I0NZ','I0UP'}),frozenset({'I07B','I0H3','I0JA'}),gear,20,0)]
  for targets in (1,5):
   with patch.dict(os.environ,{'FARM_MAGE_FAST_HYDRA':'0'}):old=M.generate_mage_timelines(torch,torch.device('cpu'),bs,'fire',targets)
   with patch.dict(os.environ,{'FARM_MAGE_FAST_HYDRA':'1'}):new=M.generate_mage_timelines(torch,torch.device('cpu'),bs,'fire',targets)
   self.assertEqual(old,new)
   from farm.hybrid.fight import Timeline
   from farm.hybrid.device import DeviceInfo
   from farm.hybrid import registry
   gpu=registry.make_engine(DeviceInfo('cpu','cpu'),'mage','fire',targets)
   scored=gpu._scores([Timeline(b,st,spec,evo,ev,None) for b,(ev,st,spec,evo) in zip(bs,new)])
   self.assertTrue(engine.compare([mage.simulate(b,targets,spec='fire',use_history=False).dps for b in bs],scored)['ok'])
