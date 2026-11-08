"""Opt-in Fire compile service. Only its spawned owner imports DirectML.

Transport executes pure packed reductions, never admission, clocks or search.
One outstanding request/client; late replies are discarded by generation+sequence.
CPU replay is a local numerical operation, not a retry of logical search work.
"""
from __future__ import annotations
import contextlib
import dataclasses
import hashlib
import math
import multiprocessing as mp
import os
import pickle
import queue
import threading
import time
import uuid
from collections import Counter, OrderedDict


@dataclasses.dataclass(frozen=True)
class Limits:
    backend: str = 'dml'  # cpu is an explicit test backend, never called GPU
    max_rows: int = 512
    max_request_bytes: int = 8 << 20
    inflight_bytes: int = 64 << 20
    working_bytes: int = 128 << 20
    pool_bytes: int = 32 << 20
    cache_bytes: int = 8 << 20
    exact_score_cache: bool = False  # full-context key cost needs separate validation
    wait_s: float = .010
    timeout_s: float = 30.
    drain_s: float = 5.

    def __post_init__(self):
        if type(self.exact_score_cache) is not bool:
            raise ValueError('exact_score_cache must be boolean')
        if self.backend not in ('cpu', 'dml'):
            raise ValueError('broker backend must be cpu or dml')
        for key in ('max_rows','max_request_bytes','inflight_bytes','working_bytes','pool_bytes','cache_bytes'):
            if type(getattr(self,key)) is not int or getattr(self,key) <= 0:
                raise ValueError(key + ' must be a positive integer')
        if self.max_request_bytes > self.inflight_bytes or self.max_rows > 4096:
            raise ValueError('invalid broker memory/row limits')
        if not (0 <= self.wait_s <= .1 and 0 < self.timeout_s <= 120 and 0 < self.drain_s <= 30):
            raise ValueError('invalid broker deadlines')


def config(job):
    raw=job.get('fire_compile_broker')
    if raw is None or raw is False:
        return None
    if type(raw) is not dict or raw.get('enabled') is not True:
        raise ValueError('fire_compile_broker requires {enabled: true}')
    if (job.get('hero'),job.get('spec')) != ('mage','fire'):
        raise ValueError('compile broker is Fire-only')
    return Limits(**{k:v for k,v in raw.items() if k != 'enabled'})


def latency(counter,key,seconds):
    try:
        observe(counter,key+'_max_s',max(0,seconds-counter.get(key+'_max_s',0)))
        for upper in (.001,.002,.005,.01,.02,.05,.1,.2,.5,1,2,5,10,30,120):
            if seconds<=upper:
                observe(counter,key+'_hist_us_'+str(int(upper*1e6)));break
    except Exception:pass


def observe(counter, key, amount=1):
    # Measurements never enter the numerical error path.
    try: counter[key] += amount
    except Exception: pass


@dataclasses.dataclass
class Endpoint:
    generation: str
    requests: object
    replies: list
    credits: object
    credit_lock: object
    next_client: object
    stopping: object
    limits: Limits


class Replay(RuntimeError): pass


class Client:
    def __init__(self, endpoint, client_id=None):
        self.endpoint=endpoint
        if client_id is None:
            with endpoint.next_client.get_lock():
                client_id=endpoint.next_client.value
                endpoint.next_client.value+=1
        if not 0 <= client_id < len(endpoint.replies):
            raise ValueError('broker client allocation exhausted; replacement clients require a new generation')
        self.client_id=client_id; self.sequence=0
        self.lock=threading.Lock(); self.counts=Counter()
        self.cache=OrderedDict(); self.cache_size=0

    def compile(self, packed):
        import numpy as np
        e=self.endpoint; limit=e.limits; t=time.perf_counter()
        arrays={k:np.ascontiguousarray(v) for k,v in packed.items() if k!='hell_hits'}
        rows=len(arrays['kind'])
        if rows < 1 or rows > limit.max_rows:
            raise Replay('request row bound')
        if sum(a.nbytes for a in arrays.values()) > limit.max_request_bytes:
            raise Replay('request raw-byte bound')
        blob=pickle.dumps(arrays,protocol=5)
        observe(self.counts,'serialization_s',time.perf_counter()-t)
        observe(self.counts,'serialized_bytes',len(blob))
        if len(blob)>limit.max_request_bytes:
            raise Replay('request serialized-byte bound')
        key=hashlib.sha256(e.generation.encode()+blob).digest()
        # Hash match is verified against the full immutable payload (no collision alias).
        hit=self.cache.pop(key,None)
        if hit is not None:
            self.cache[key]=hit
            if hit[0]==blob:
                observe(self.counts,'compile_cache_hits'); observe(self.counts,'cached_rows',rows); self.last_route='cache'; return hit[1].copy()
        with self.lock:
            deadline=time.monotonic()+limit.timeout_s
            units=math.ceil(len(blob)/65536)
            acquired=0; enqueued=False
            try:
                if not e.credit_lock.acquire(timeout=max(0,deadline-time.monotonic())):
                    raise Replay("credit reservation timeout")
                try:
                    while acquired<units:
                        if not e.credits.acquire(timeout=max(0,deadline-time.monotonic())):
                            raise Replay("inflight byte backpressure timeout")
                        acquired+=1
                finally: e.credit_lock.release()
                self.sequence+=1; rid=(e.generation,self.client_id,self.sequence)
                if e.stopping.is_set(): raise Replay('broker stopped')
                # Empty stale late replies; never let them occupy this client's reply slot.
                while True:
                    try: e.replies[self.client_id].get_nowait()
                    except queue.Empty: break
                sent=time.monotonic()
                e.requests.put((rid,blob,units,sent,deadline),timeout=max(0,deadline-sent))
                enqueued=True; observe(self.counts,'submitted_requests')
                while True:
                    remaining=deadline-time.monotonic()
                    if remaining<=0: raise Replay('reply deadline')
                    try: reply=e.replies[self.client_id].get(timeout=min(.1,remaining))
                    except queue.Empty:
                        if e.stopping.is_set(): raise Replay('owner failed/stopped')
                        continue
                    if reply[0]!=rid:
                        observe(self.counts,'stale_replies'); continue
                    _,error,value,metrics=reply
                    if error: raise Replay(error)
                    result=np.asarray(value)
                    from farm.hybrid.fight import COLUMNS
                    if result.shape!=(rows,len(COLUMNS)) or not np.isfinite(result).all():
                        raise Replay('invalid broker result')
                    observe(self.counts,'reply_wait_s',time.monotonic()-sent)
                    latency(self.counts,'reply_wait',time.monotonic()-sent)
                    for k,v in metrics.items(): observe(self.counts,k,v)
                    cost=len(blob)+result.nbytes
                    if cost <= limit.cache_bytes:
                        while self.cache and self.cache_size+cost>limit.cache_bytes:
                            _,old=self.cache.popitem(last=False); self.cache_size-=old[2]
                        old=self.cache.pop(key,None)
                        if old is not None: self.cache_size-=old[2]
                        self.cache[key]=(blob,result.copy(),cost); self.cache_size+=cost
                    self.last_route=limit.backend
                    observe(self.counts,'returned_requests'); observe(self.counts,'returned_rows',rows)
                    return result
            except (queue.Full,queue.Empty) as exc:
                raise Replay('transport backpressure timeout') from exc
            finally:
                if not enqueued:
                    for _ in range(acquired): e.credits.release()


def _schema(arrays):
    return tuple((k,v.dtype.str,v.shape[1:]) for k,v in sorted(arrays.items()))


def _estimate(arrays, rows):
    return rows * arrays['kind'].shape[1] * 4 * (256+arrays['bonus'].shape[1])


def _owner(endpoint, ready, final):
    counts=Counter(); e=endpoint; lim=e.limits; pending=[]; seen={}
    try:
        import numpy as np
        import torch
        torch.set_num_threads(1)
        if lim.backend=='dml':
            import torch_directml
            target=torch_directml.device(torch_directml.default_device())
            actual='dml'
        else: target=torch.device('cpu'); actual='cpu-test'
        from farm.hybrid.fight import compile_sums
        from farm.hybrid.mage_device import DevicePool
        class TimedPool(DevicePool):
            def up(self,*args,**kw):
                t=time.perf_counter()
                try: return super().up(*args,**kw)
                finally: observe(counts,'upload_host_s',time.perf_counter()-t)
        pool=TimedPool(torch,target,max_bytes=lim.pool_bytes)
        ready.put({'pid':os.getpid(),'actual':actual,'gpu_owner_count':int(actual=='dml')})
        while not e.stopping.is_set() or pending:
            if not pending:
                try: pending.append(e.requests.get(timeout=.05))
                except queue.Empty: continue
            first=pending.pop(0)
            rid,blob,units,sent,deadline=first
            valid=(rid[0]==e.generation and 0<=rid[1]<len(e.replies) and rid[2]>seen.get(rid[1],0))
            if not valid or time.monotonic()>=deadline:
                for _ in range(units):e.credits.release()
                observe(counts,'invalid_or_expired_requests');continue
            seen[rid[1]]=rid[2]
            batch=[first]; start=time.monotonic()
            while time.monotonic()-start < lim.wait_s and len(pending)<len(e.replies):
                try: pending.append(e.requests.get(timeout=max(.0001,lim.wait_s-(time.monotonic()-start))))
                except queue.Empty: break
            observe(counts,'coalesce_s',time.monotonic()-start)
            a0=pickle.loads(first[1]); schema=_schema(a0); rows=len(a0['kind']); batch_arrays=[a0]
            for req in list(pending):
                arrays=pickle.loads(req[1]); n=len(arrays['kind'])
                if req[0][0]==e.generation and req[0][2]>seen.get(req[0][1],0) and time.monotonic()<req[4] and _schema(arrays)==schema and rows+n<=lim.max_rows and _estimate(a0,rows+n)<=lim.working_bytes:
                    pending.remove(req);seen[req[0][1]]=req[0][2];batch.append(req);batch_arrays.append(arrays);rows+=n
            error=''; result=None
            metrics={'broker_batch_requests':len(batch),'broker_batch_rows':rows}
            try:
                if _estimate(a0,rows)>lim.working_bytes: raise Replay('working graph bound')
                t=time.perf_counter()
                merged={k:np.concatenate([a[k] for a in batch_arrays],axis=0) for k in a0}
                metrics['merge_s']=time.perf_counter()-t
                t=time.perf_counter()
                tensor=compile_sums(torch,target,merged,workspace=pool,device_result=True)
                metrics['compile_host_submit_s']=time.perf_counter()-t
                t=time.perf_counter(); result=tensor.cpu().numpy().astype(np.float64)
                metrics['d2h_wait_s']=time.perf_counter()-t
                if not np.isfinite(result).all(): raise Replay('non-finite compile result')
                observe(counts,'compile_calls');observe(counts,'compiled_rows',rows)
            except Exception as exc:
                error=f'{type(exc).__name__}: {exc}';observe(counts,'failed_batches')
            offset=0
            for req,arrays in zip(batch,batch_arrays):
                rid,blob,units,sent,deadline=req;n=len(arrays['kind'])
                # The next request never consumes a late reply from a former sequence.
                if time.monotonic()<deadline:
                    value=None if result is None else result[offset:offset+n].copy()
                    share={k:v/len(batch) for k,v in metrics.items() if k not in ('broker_batch_requests','broker_batch_rows')}
                    share['queue_wait_s']=max(0,start-sent)
                    try: e.replies[rid[1]].put_nowait((rid,error,value,share))
                    except queue.Full: observe(counts,'dropped_replies')
                else: observe(counts,'expired_requests')
                for _ in range(units):e.credits.release()
                offset+=n
            observe(counts,'served_requests',len(batch));observe(counts,'max_batch_rows',max(0,rows-counts.get('max_batch_rows',0)))
        counts['pool_peak_bytes']=pool.counts['peak_bytes']
    except BaseException as exc:
        try: ready.put_nowait({'error':f'{type(exc).__name__}: {exc}'})
        except Exception: pass
        counts['owner_failure']=1
    finally:
        e.stopping.set()
        try: final.put_nowait(dict(counts))
        except Exception: pass


class Service:
    def __init__(self, clients, limits=None, ctx=None):
        if not 1<=clients<=64: raise ValueError('client count bound')
        self.ctx=ctx or mp.get_context('spawn'); self.limits=limits or Limits(); c=self.ctx
        self.endpoint=Endpoint(uuid.uuid4().hex,c.Queue(clients),[c.Queue(1) for _ in range(clients)],c.BoundedSemaphore(self.limits.inflight_bytes//65536),c.Lock(),c.Value('i',0),c.Event(),self.limits)
        self.ready=c.Queue(1);self.final=c.Queue(1);self.meta={};self.counts={};self.process=None
    def __enter__(self):
        self.process=self.ctx.Process(target=_owner,args=(self.endpoint,self.ready,self.final),name='fire-compile-broker')
        self.process.start()
        from multiprocessing.connection import wait
        def monitor():
            wait([self.process.sentinel]);self.endpoint.stopping.set()
        threading.Thread(target=monitor,daemon=True).start()
        try:
            self.meta=self.ready.get(timeout=self.limits.timeout_s)
            if 'error' in self.meta:raise Replay(self.meta['error'])
            return self
        except BaseException:
            self.close();raise
    def close(self):
        self.endpoint.stopping.set()
        if self.process:
            self.process.join(self.limits.drain_s)
            if self.process.is_alive():
                # Only this service's own verified Process handle; no PID-wide cleanup.
                self.process.terminate();self.process.join(self.limits.drain_s)
                self.counts['forced_own_owner_cleanup']=1
            try:self.counts.update(self.final.get(timeout=.2))
            except queue.Empty:pass
        for q in [self.endpoint.requests,*self.endpoint.replies,self.ready,self.final]:
            q.cancel_join_thread();q.close()
    def __exit__(self,*_):self.close()
