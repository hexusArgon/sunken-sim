"""Isolated Numba Hydra prototype; no import/dependency change in production.

Run with an optional --jit-path containing compatible numba/llvmlite wheels.
Compares complete *fresh* captures, keeping float64 order and fastmath=False.
"""
import argparse,inspect,json,statistics,sys,time,ast
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def main():
 p=argparse.ArgumentParser();p.add_argument('--jit-path');p.add_argument('--output',required=True);a=p.parse_args()
 if a.jit_path:sys.path.insert(0,a.jit_path)
 import numba,numpy as np
 from numba import njit,types
 from numba.typed import List
 from sunken_sim import mage
 from farm.test_hybrid import _sample
 @njit(fastmath=False)
 def alive_sum(hydras,now):
  total=0.0
  for expiry,count in hydras:
   if expiry>now:total+=count
  return total
 def new_hydras():return List.empty_list(types.UniTuple(types.float64,2))
 def prototype(*args,**kwargs):
  return mage.simulate(*args,**kwargs,_hydra_sum=alive_sum,_new_hydras=new_hydras)
 from dataclasses import replace
 builds=[replace(b,talents=b.talents|{'I0UP','I0NZ','I0KR'}) for b in _sample('mage','fire',32,41)]
 stats=[mage.sheet(b) for b in builds]
 def run(fn):return [fn(b,5,None,'Hydra' if mage._wears(b,'I00D') else None,'fire',use_history=False,_capture_only=True,_prepared_stats=s) for b,s in zip(builds,stats)]
 t=time.perf_counter();cold=run(prototype);cold_s=time.perf_counter()-t
 ref=run(mage.simulate);assert cold==ref,'JIT payload mismatch'
 times={'python':[],'numba':[]}
 for i in range(6):
  for name,fn in ([('python',mage.simulate),('numba',prototype)] if i%2==0 else [('numba',prototype),('python',mage.simulate)]):
   t=time.perf_counter();got=run(fn);times[name].append(time.perf_counter()-t);assert got==ref
 out=dict(numba=numba.__version__,numpy=np.__version__,fastmath=False,builds=len(builds),events=sum(len(r[0]) for r in ref),cold_numba_s=cold_s,times=times,medians={k:statistics.median(v) for k,v in times.items()},signatures=[str(s) for s in alive_sum.signatures],payload_exact=True,production_enabled=False)
 Path(a.output).write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
if __name__=='__main__':main()
