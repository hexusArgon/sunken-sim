"""Real Top-100 chunk 2: tiny reduction ties used to change ESC and lose DPS."""
import os,unittest
from unittest.mock import patch
import torch
from farm.catalog import load
from farm.hybrid import registry,engine
from farm.hybrid.device import detect,DeviceInfo
from farm.score import finish_sextuple
from sunken_sim.esc import apply_points
from sunken_sim.shadow import Build

class SelectionTests(unittest.TestCase):
 def test_cpu_guard_restores_old_cpu_esc_and_reused_scores(self):
  torch.set_num_threads(1)
  space,items=load('mage','fire','mixed',None,100)
  gear=tuple(items[c] for c in space.decode(2)[0])
  call=(gear,space.talents,space.glyphs,space.picks_without,space.picks_with,space.glyph_picks)
  ref=finish_sextuple('mage','fire',5,*call)
  devices=[DeviceInfo('cpu','cpu')];d=detect('mage','fire')
  if d.gpu:devices.append(d)
  with patch.dict(os.environ,{'FARM_FIRE_EXACT_SELECTION':'1','FARM_HYBRID_GPU_TIMELINE':'1','FARM_MAGE_FAST_HYDRA':'1','FARM_FIRE_FINAL_GPU':'0'}):
   for device in devices:
    g=registry.make_engine(device,'mage','fire',5);got=g.finish_many([call])[0]
    self.assertEqual(got[1:4],ref[1:4]);self.assertLessEqual(abs(got[0]-ref[0]),1e-4*max(1.,abs(ref[0])))
    build=apply_points(Build(frozenset(got[1]),frozenset(got[2]),gear,0,0),got[3])
    a=g.dps_many([build]);b=g.dps_many([build]);fresh=registry.make_engine(device,'mage','fire',5).dps_many([build])
    self.assertEqual(a,b);self.assertEqual(a,fresh);self.assertEqual(a,[ref[0]])
    self.assertGreater(g.score_counts['cpu_owner_reductions'],0)
