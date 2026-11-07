"""Opt-in Fire-only staged CPU search. No device detection, no Torch import."""
from collections import Counter
from types import SimpleNamespace
from farm.hybrid.fight import GpuFights
from farm.hybrid.mage_reuse import TapeLRU
from farm.hybrid.mage_prepare import SheetLRU

class CpuFireFights(GpuFights):
    cpu_staged=True
    def __init__(self,targets):
        self.hero='mage';self.spec='fire';self.targets=targets;self.fights=0
        self.device=SimpleNamespace(gpu=False,kind='cpu',name='CPU staged exact')
        self.tape_cache=TapeLRU();self.sheet_cache=SheetLRU()
        self.timeline_counts=Counter();self.score_counts=Counter();self.checked=False
    def dps_many(self,builds):
        from sunken_sim import mage
        import os
        self.tape_cache.mode='scalar';self.tape_cache.sync_context('fire',self.targets)
        from sunken_sim.shadow import FIGHT
        if not self.tape_cache.split or mage.stats_of is not mage.sheet or mage.FIGHT != FIGHT or os.environ.get('FARM_FIRE_JIT_HYDRA','0')!='0':
            self.score_counts['cpu_oracle_fallback_builds']+=len(builds);self.fights+=len(builds)
            return [mage.simulate(b,self.targets,spec='fire',use_history=False).dps for b in builds]
        return super().dps_many(builds)
    def _scores(self,tls):
        from sunken_sim import mage
        from sunken_sim.shadow import FIGHT
        out=[]
        for i,tl in enumerate(tls):
            from farm.hybrid.mage_exact import compile_exact
            compiled=compile_exact(tl,self.tape_cache)
            value=mage._score(compiled,tl.stats,tl.build,tl.spec)[0]/FIGHT
            out.append(value);self._exact_current[i]=value
        self.score_counts['cpu_canonical_rows']+=len(tls)
        return out

_ENGINE=None
_CONTEXT=None

def enabled(job):
    import os
    return str(job.get('fire_cpu_staged',os.environ.get('FARM_FIRE_CPU_STAGED','0'))).lower() in ('1','true','on')

def eval_span(start,stop):
    global _ENGINE,_CONTEXT
    from farm import runner as R
    from farm.hybrid import engine
    if (R._HERO,R._SPEC)!=('mage','fire'):return R.eval_span(start,stop)
    key=(R._HERO,R._SPEC,R._TARGETS,id(R._SPACE),id(R._ITEMS))
    if key!=_CONTEXT:_ENGINE=CpuFireFights(R._TARGETS);_CONTEXT=key
    return engine.eval_span(start,stop,cpu_engine=_ENGINE)
