"""Native Fire-only integration; default-off. Search remains engine.eval_span.

The client owns no DirectML object. CPU scalar clocks, tape cache, CPU score and
mandatory exact winner/near-tie guards are inherited unchanged from GpuFights.
"""
import os
import time
from collections import Counter, OrderedDict
from farm.hybrid.fire_broker import Client, Service, Replay, config, observe
from farm.hybrid.fight import GpuFights


class BrokerFights(GpuFights):
    def __init__(self, client, targets=1):
        from farm.hybrid.device import DeviceInfo
        super().__init__(DeviceInfo('cpu','broker CPU client'), 'mage','fire',targets)
        self.client=client;self.profile=Counter()
        self.guard_cache=OrderedDict();self.guard_cache_bytes=0

    def dps_many(self,builds):
        t=time.perf_counter()
        try:return super().dps_many(builds)
        finally:observe(self.profile,'dps_many_wall_s',time.perf_counter()-t)

    def finish_many(self,*a,**kw):
        t=time.perf_counter()
        try:return super().finish_many(*a,**kw)
        finally:observe(self.profile,'refinement_wall_s',time.perf_counter()-t)

    def _owner_scores(self,tls,*a,**kw):
        # Reuse only CPU-exact scores previously produced by the SAME guard.
        # Full stats/build/events and verified callable/constants/source context
        # are retained, never a potency-only or gear-only approximation.
        import pickle, hashlib, math
        from collections.abc import Mapping
        def freeze(value):
            if isinstance(value,Mapping):return tuple(sorted((k,freeze(v)) for k,v in value.items()))
            if isinstance(value,(tuple,list)):return tuple(freeze(v) for v in value)
            if isinstance(value,(set,frozenset)):return tuple(sorted(freeze(v) for v in value))
            if value is None or isinstance(value,(str,int,bool)):return value
            if isinstance(value,float):
                if not math.isfinite(value):raise ValueError('nonfinite cache input')
                return value
            if hasattr(value,'__dict__'):return (type(value).__module__,type(value).__qualname__,freeze(vars(value)))
            raise TypeError('uncacheable scoring input')
        keys={};t=time.perf_counter()
        eligible=(self.client.endpoint.limits.exact_score_cache and getattr(self,'_canonical_tapes',False) and self.tape_cache.split
                  and os.environ.get('FARM_FIRE_EXACT_TAPE_SCORE','1')!='0')
        if eligible:
            for j,tl in enumerate(tls):
                try:
                    blob=pickle.dumps((self.tape_cache.context,self.targets,tl.spec,tl.bound,
                                       freeze(tl.stats),freeze(tl.build),freeze(tl.events)),protocol=5)
                    if len(blob)>1<<20:continue
                    key=hashlib.sha256(blob).digest();keys[j]=(key,blob)
                    hit=self.guard_cache.get(key)
                    if hit is not None and hit[0]==blob:
                        self.guard_cache.move_to_end(key)
                        self._exact_current.setdefault(j,hit[1])
                        observe(self.profile,'cpu_exact_score_cache_hits')
                except (TypeError,ValueError,OverflowError):pass
        observe(self.profile,'cpu_exact_cache_key_s',time.perf_counter()-t)
        t=time.perf_counter()
        try:
            # All selection/tie/completeness guards still run. The inherited guard
            # already accepts _exact_current scores from its exact CPU replay.
            result=super()._owner_scores(tls,*a,**kw)
            budget=self.client.endpoint.limits.cache_bytes
            for j,value in self._exact_current.items():
                if j not in keys or not math.isfinite(value):continue
                key,blob=keys[j];cost=len(blob)+8
                if cost>budget:continue
                old=self.guard_cache.pop(key,None)
                if old:self.guard_cache_bytes-=old[2]
                while self.guard_cache and self.guard_cache_bytes+cost>budget:
                    _,old=self.guard_cache.popitem(last=False);self.guard_cache_bytes-=old[2]
                self.guard_cache[key]=(blob,value,cost);self.guard_cache_bytes+=cost
            return result
        finally:observe(self.profile,'cpu_exact_selection_s',time.perf_counter()-t)

    def _scores(self,tls):
        from farm.hybrid.fight import pack,compiled_dict
        from farm.hybrid.mage_device import parts
        from sunken_sim import mage
        from sunken_sim.shadow import FIGHT
        out=[];limits=self.client.endpoint.limits
        for part,fits in parts(tls,max_rows=min(256,limits.max_rows),working_bytes=limits.working_bytes):
            sums=None
            if fits:
                t=time.perf_counter();packed=pack(part)
                observe(self.profile,'cpu_pack_s',time.perf_counter()-t)
                t=time.perf_counter()
                try:
                    sums=self.client.compile(packed)
                    if self.client.last_route=='dml':self.score_counts['gpu_compile_rows']+=len(part)
                    elif self.client.last_route=='cpu':self.score_counts['cpu_compile_rows']+=len(part)
                    else:observe(self.profile,'cached_compile_rows',len(part))
                except Replay as exc:
                    observe(self.profile,'cpu_replay_batches')
                    observe(self.profile,'cpu_replay_'+str(exc).split(':')[0])
                finally:observe(self.profile,'compile_roundtrip_s',time.perf_counter()-t)
            t=time.perf_counter()
            if sums is None:
                self.score_counts['cpu_compile_rows']+=len(part)
                for tl in part:
                    compiled=mage._compile(tl.events,tl.build,tl.stats,tl.spec,tl.evocation)
                    exact=mage._score(compiled,tl.stats,tl.build,tl.spec)[0]/FIGHT
                    self._exact_current[len(out)]=exact
                    out.append(exact)
            else:
                for tl,row,hell in zip(part,sums,packed['hell_hits']):
                    out.append(mage._score(compiled_dict(tl,row,hell),tl.stats,tl.build,tl.spec)[0]/FIGHT)
            observe(self.profile,'cpu_score_s',time.perf_counter()-t)
        return out


def init_client(endpoint,targets):
    from farm.hybrid import engine
    engine.reset();engine._ENGINE=BrokerFights(Client(endpoint),targets)
    engine._ENGINE_STATE='pending'


def eval_span(start,stop):
    from farm.hybrid import engine
    scorer=engine._ENGINE
    before=dict(getattr(scorer,'profile',{}));cb=dict(getattr(getattr(scorer,'client',None),'counts',{}))
    result=engine.eval_span(start,stop)
    # Per-span deltas, not cumulative sums erroneously counted once per span.
    try:
        p={k:v-before.get(k,0) for k,v in scorer.profile.items()}
        p.update({k:(v if k.endswith('_max_s') else v-cb.get(k,0)) for k,v in scorer.client.counts.items()})
        p['canonical_timeline_and_other_s']=max(0,p.get('dps_many_wall_s',0)-p.get('cpu_pack_s',0)-p.get('compile_roundtrip_s',0)-p.get('cpu_score_s',0)-p.get('cpu_exact_selection_s',0))
        if scorer.client.endpoint.limits.backend=='cpu':
            result['fire_execution']['actual']='cpu-fallback'
        result['broker_execution']={'client_pid':os.getpid(),'generation':scorer.client.endpoint.generation,'backend':scorer.client.endpoint.limits.backend,'profile':p,'logical_done':result['done']-start,'errors':result['errors']}
    except Exception:pass
    return result


def record(job,payload):
    try:
        entry=payload.get('broker_execution')
        if not entry:return
        meta=job['hybrid']['compile_broker'];profile=meta.setdefault('profile',{})
        for k,v in entry['profile'].items():profile[k]=max(profile.get(k,0),v) if k.endswith('_max_s') else profile.get(k,0)+v
        meta['logical_done']=meta.get('logical_done',0)+entry['logical_done']
        meta['span_errors']=meta.get('span_errors',0)+entry['errors']
        meta.setdefault('client_pids',{})[str(entry['client_pid'])]=entry['backend']
    except Exception:pass


def preflight(service,job):
    import random
    from farm.catalog import load
    from farm.hybrid.registry import cpu_dps
    from sunken_sim.shadow import Build
    space,items=load('mage','fire',job['pool'],job.get('preset') or None,job.get('top') or None)
    rng=random.Random(15)
    builds=[]
    for i in range(8):
        gear=tuple(items[c] for c in space.decode(rng.randrange(space.total))[0])
        talents=frozenset(rng.sample(list(space.talents),space.picks_with)) if i%2 else frozenset()
        builds.append(Build(talents,frozenset(),gear,0,0,0,0))
    engine=BrokerFights(Client(service.endpoint),int(job['targets']))
    ref=[cpu_dps('mage','fire',int(job['targets']),b) for b in builds]
    got=engine.dps_many(builds)
    if ref!=got:raise Replay('broker canonical preflight mismatch')
    return {'rows':len(builds),'canonical_exact':True,'backend':service.limits.backend}


def run_job(job,box,tick):
    from farm import runner as R
    limits=config(job)
    if os.environ.get('FARM_FIRE_FINAL_GPU','0')!='0':raise ValueError('broker requires canonical CPU final selection')
    if os.environ.get('FARM_FIRE_EXACT_SELECTION','1')=='0':raise ValueError('broker requires exact selection guards')
    if os.environ.get('FARM_FIRE_PLANNER','scalar') not in ('scalar','auto'):raise ValueError('broker requires scalar planner')
    job=dict(job,fire_broker_protocol={'version':1,'mode':'packed-compile','limits':vars(limits)})
    # Validate native checkpoint before starting an owner. Never reinterpret an
    # existing different resource/path checkpoint as an empty search.
    from farm.catalog import load
    from farm import admission as A
    space,items=load('mage','fire',job['pool'],job.get('preset') or None,job.get('top') or None)
    configured=A.configure(job,space,items)
    checkpoint=R._job_checkpoint_path(configured)
    # Native filenames include source/catalog fingerprint: also refuse old
    # siblings for this exact job id, rather than silently creating a fresh file.
    siblings=list(checkpoint.parent.glob(str(job['id'])+'-admission-*.json'))
    legacy=R._checkpoint_path(job['id'])
    if legacy.exists():siblings.append(legacy)
    if any(p != checkpoint for p in siblings):
        raise ValueError('existing job checkpoint fingerprint differs; explicit new job id required')
    R._load_checkpoint(configured,R.Boards())
    clients=R.worker_count()
    # Same owner serves preflight and the pool; coordinator never detects a device.
    with Service(clients+1,limits) as service:
        checked=preflight(service,job)
        meta={'status':'hybrid-compile-broker','name':'Fire job-owned compile broker','device':limits.backend,'gpu_fights':limits.backend=='dml','compile_broker':dict(service.meta,generation=service.endpoint.generation,preflight=checked,limits=vars(limits),signature_policy='new-job only; no resident migration')}
        try:tick({'hybrid':meta})
        except Exception:pass
        result=R.run_job(dict(job,hybrid=meta),box,tick,eval_fn=eval_span,_fire_broker=service.endpoint)
    meta['compile_broker']['owner_final']=service.counts
    result['compile_broker']=meta['compile_broker']
    try:tick({'hybrid':meta})
    except Exception:pass
    return result
