"""CPU transport/production contract tests. NOT evidence of DirectML parity."""
import dataclasses
import multiprocessing as mp
import os
import queue
import threading
import time
import unittest
from unittest.mock import patch
import numpy as np
from farm.hybrid.fire_broker import Service,Limits,Client,Replay,config,observe


def example(n=2,width=3,executes=1,seed=0):
    # Actual packed Fire inputs, including event kinds, masks, per-build tables/flags.
    from farm.catalog import load
    from farm.hybrid.fight import timelines,pack
    from sunken_sim.shadow import Build
    import random
    sp,it=load('mage','fire','mixed',None,80);rng=random.Random(seed)
    builds=[Build(frozenset(),frozenset(),tuple(it[c] for c in sp.decode(rng.randrange(sp.total))[0]),0,0,0,0) for _ in range(n)]
    tls=[timelines(b,1,'fire',cache=False)[0] for b in builds]
    return pack(tls),builds


def direct(p):
    import torch
    from farm.hybrid.fight import compile_sums
    torch.set_num_threads(1)
    return compile_sums(torch,torch.device('cpu'),p)


def child(ep,cid,p,out,barrier=None):
    try:
        client=Client(ep,cid)
        if barrier:barrier.wait(30)
        p={k:v.copy() if hasattr(v,'copy') else list(v) for k,v in p.items()}
        p['raw_w']+=cid*.125
        value=client.compile(p)
        out.put((cid,value,None,dict(client.counts)))
    except Exception as exc:out.put((cid,None,repr(exc),{}))


class BrokerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.p,cls.builds=example()
    def service(self,n=1,**kw):return Service(n,Limits(backend='cpu',timeout_s=5,**kw))
    def test_config_off_invalid_scope(self):
        self.assertIsNone(config({}))
        self.assertIsNone(config({'fire_compile_broker':False}))
        for j in ({'fire_compile_broker':True},{'hero':'priest','spec':'holy','fire_compile_broker':{'enabled':True}}):
            with self.assertRaises(ValueError):config(j)
        with self.assertRaises(ValueError):Limits(max_rows=0)
    def test_direct_broker_cache_mutation(self):
        with self.service() as s:
            c=Client(s.endpoint);a=c.compile(self.p);b=c.compile(self.p)
            np.testing.assert_array_equal(a,direct(self.p));np.testing.assert_array_equal(a,b)
            self.assertEqual(c.counts['compile_cache_hits'],1)
            p={k:v.copy() if hasattr(v,'copy') else list(v) for k,v in self.p.items()}
            p['raw_w']+=3
            c.compile(p);self.assertEqual(c.counts['submitted_requests'],2)
            self.assertLessEqual(c.cache_size,s.limits.cache_bytes)
        self.assertEqual(s.meta['gpu_owner_count'],0);self.assertEqual(s.counts['compile_calls'],2)
    def test_spawn_15_clients_coalesced_exact_order(self):
        packet={k:np.concatenate([v]*64,axis=0) if isinstance(v,np.ndarray) else v*64 for k,v in self.p.items()}
        ctx=mp.get_context('spawn');out=ctx.Queue();barrier=ctx.Barrier(15)
        with self.service(15,wait_s=.1) as s:
            procs=[ctx.Process(target=child,args=(s.endpoint,i,packet,out,barrier)) for i in reversed(range(15))]
            for p in procs:p.start()
            rows=[out.get(timeout=60) for _ in procs]
            for p in procs:p.join(10);self.assertEqual(p.exitcode,0)
            self.assertEqual(sorted(r[0] for r in rows),list(range(15)))
            for cid,value,err,_ in rows:
                expected={k:v.copy() if hasattr(v,'copy') else list(v) for k,v in packet.items()};expected['raw_w']+=cid*.125
                self.assertIsNone(err);np.testing.assert_array_equal(value,direct(expected))
        self.assertEqual(s.counts['served_requests'],15)
        self.assertLess(s.counts['compile_calls'],15)
        self.assertEqual(s.counts['compiled_rows'],1920)
        self.assertLessEqual(s.counts['max_batch_rows'],512)
    def test_heterogeneous_shapes_and_splitting(self):
        p={k:(v[:1].copy() if isinstance(v,np.ndarray) else v[:1]) for k,v in self.p.items()}
        width=p['kind'].shape[1]
        for k,v in list(p.items()):
            if isinstance(v,np.ndarray) and v.ndim>=2 and v.shape[1]==width:p[k]=v[:,:-7].copy()
        ctx=mp.get_context('spawn');out=ctx.Queue()
        with self.service(4,max_rows=2,wait_s=.05) as s:
            processes=[ctx.Process(target=child,args=(s.endpoint,i,p if i%2 else self.p,out)) for i in range(4)]
            for x in processes:x.start()
            replies=[out.get(timeout=30) for _ in processes]
            for x in processes:x.join(10);self.assertEqual(x.exitcode,0)
            for i,value,err,_ in replies:
                expected={k:v.copy() if hasattr(v,'copy') else list(v) for k,v in (p if i%2 else self.p).items()};expected['raw_w']+=i*.125
                self.assertIsNone(err);np.testing.assert_array_equal(value,direct(expected))
        self.assertLessEqual(s.counts['max_batch_rows'],2)
    def test_timeout_cancel_generation_and_owner_death(self):
        with self.service() as s:
            c=Client(s.endpoint);s.process.terminate();s.process.join(5)
            before=time.monotonic()
            with self.assertRaises(Replay):c.compile(self.p)
            self.assertLess(time.monotonic()-before,1)
        with self.service() as s:
            c=Client(s.endpoint)
            s.endpoint.replies[0].put(('wrong-generation',None,np.zeros((1,1)),{}))
            np.testing.assert_array_equal(c.compile(self.p),direct(self.p))
    def test_bounds_and_cpu_exact_replay(self):
        from farm.hybrid.fire_broker_path import BrokerFights
        from farm.hybrid.registry import cpu_dps
        with self.service(max_request_bytes=512,inflight_bytes=65536,working_bytes=65536) as s:
            e=BrokerFights(Client(s.endpoint));got=e.dps_many(self.builds)
            self.assertEqual(got,[cpu_dps('mage','fire',1,b) for b in self.builds])
            self.assertEqual(e.score_counts['gpu_compile_rows'],0)
            self.assertGreater(e.score_counts['cpu_compile_rows'],0)
            self.assertEqual(s.counts.get('compile_calls',0),0)
    def test_cpu_broker_exact_guards_payload(self):
        from farm.hybrid.fire_broker_path import BrokerFights
        from farm.hybrid.registry import cpu_dps
        with self.service() as s:
            e=BrokerFights(Client(s.endpoint));got=e.dps_many(self.builds)
            self.assertEqual(got,[cpu_dps('mage','fire',1,b) for b in self.builds])
            self.assertGreater(e.score_counts['selection_exact_builds'],0)
            self.assertEqual(e.score_counts['gpu_compile_rows'],0)
    def test_backpressure_timeout_releases_credits(self):
        with self.service() as s:
            c=Client(dataclasses.replace(s.endpoint,limits=dataclasses.replace(s.limits,timeout_s=.03)))
            tokens=s.limits.inflight_bytes//65536
            for _ in range(tokens):self.assertTrue(s.endpoint.credits.acquire(False))
            t=time.monotonic()
            with self.assertRaises(Replay):c.compile(self.p)
            self.assertLess(time.monotonic()-t,.5)
            for _ in range(tokens):s.endpoint.credits.release()
            c.endpoint=s.endpoint
            np.testing.assert_array_equal(c.compile(self.p),direct(self.p))
    def test_reply_timeout_then_new_sequence_not_double_counted(self):
        with self.service(wait_s=.1) as s:
            c=Client(dataclasses.replace(s.endpoint,limits=dataclasses.replace(s.limits,timeout_s=.02)))
            with self.assertRaises(Replay):c.compile(self.p)
            c.endpoint=s.endpoint
            np.testing.assert_array_equal(c.compile(self.p),direct(self.p))
            self.assertEqual(c.counts['submitted_requests'],2)
            self.assertEqual(c.counts['returned_requests'],1)
            self.assertEqual(c.counts['returned_rows'],2)
    def test_checkpoint_resource_guard_without_reset(self):
        import json,tempfile
        from pathlib import Path
        from farm import runner as R,admission as A
        saved={'fire_broker_protocol':{'version':1},'done_up_to':999,'search_schema':A.SCHEMA}
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'cp.json';p.write_text(json.dumps(saved));before=p.read_bytes()
            with patch.object(R,'_job_checkpoint_path',return_value=p):
                with self.assertRaises(ValueError):R._load_checkpoint({'start':0},R.Boards())
            self.assertEqual(p.read_bytes(),before)
        self.assertFalse(R._same_job(saved,{'fire_broker_protocol':{'version':2}}))
    def test_exact_score_reuse_full_context_and_guards(self):
        from farm.hybrid.fire_broker_path import BrokerFights
        from farm.hybrid.registry import cpu_dps
        from dataclasses import replace
        with self.service(exact_score_cache=True) as service:
            e=BrokerFights(Client(service.endpoint))
            ref=[cpu_dps('mage','fire',1,b) for b in self.builds]
            self.assertEqual(e.dps_many(self.builds),ref)
            self.assertEqual(e.dps_many(self.builds),ref)
            self.assertGreater(e.profile['cpu_exact_score_cache_hits'],0)
            before=e.score_counts['selection_exact_builds']
            self.assertEqual(e.dps_many(self.builds[::-1]),ref[::-1])
            self.assertGreater(e.score_counts['selection_exact_builds'],before)
            changed=[replace(self.builds[0],potency_points=3)] if hasattr(self.builds[0],'potency_points') else []
            if changed:self.assertEqual(e.dps_many(changed),[cpu_dps('mage','fire',1,b) for b in changed])
            self.assertLessEqual(e.guard_cache_bytes,service.limits.cache_bytes)
    def test_stale_fingerprint_rejected_before_owner_init(self):
        import tempfile
        from pathlib import Path
        from farm import runner as R
        from farm.hybrid import fire_broker_path as P
        job=dict(id='fixture',hero='mage',spec='fire',pool='mixed',top=80,targets=1,start=0,end=1,fire_compile_broker={'enabled':True,'backend':'cpu'})
        with tempfile.TemporaryDirectory() as tmp:
            old=Path(tmp)/'fixture-admission-old.json';old.write_text('{}')
            with patch.object(R,'_job_checkpoint_path',return_value=Path(tmp)/'fixture-admission-current.json'),patch.object(R,'_checkpoint_path',return_value=Path(tmp)/'fixture.json'),patch.object(P,'Service') as make:
                with self.assertRaises(ValueError):P.run_job(job,{},lambda _:None)
                make.assert_not_called()
            self.assertEqual(old.read_text(),'{}')
    def test_observer_nonthrowing(self):
        class Bad:
            def __getitem__(self,k):raise OSError('observer')
        observe(Bad(),'broken')
        from farm.hybrid.fire_broker_path import record
        record({}, {'broker_execution':{'broken':True}})

if __name__=='__main__':unittest.main()
