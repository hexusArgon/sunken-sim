"""CPU/mock resource, lifecycle and canonical-final regressions. NOT DirectML parity."""
from __future__ import annotations
import os,unittest,threading,multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
from types import SimpleNamespace
from unittest import mock
from farm.hybrid.mage_priest_resources import SCOPED_SPECS,worker_count,canonical_esc,record_execution,emit_tick
_BARRIER=None

def _init_lease(budget,barrier,hero,spec):
    global _BARRIER
    from farm import runner as R
    R.init_worker(None,{}, {},hero,spec,5,None,None,budget)
    _BARRIER=barrier

def _lease(_index):
    from farm import runner as R
    _BARRIER.wait(timeout=40)
    return os.getpid(),R._SCOPED_DML_ALLOWED

class Resources(unittest.TestCase):
    def test_default_explicit_one_reject_unvalidated_counts(self):
        for hero,spec in SCOPED_SPECS:
            self.assertEqual(worker_count(dict(hero=hero,spec=spec)),1)
            self.assertEqual(worker_count(dict(hybrid_dml_workers=1)),1)
            for bad in (True,False,0,2,6,15,1.0,"1",None):
                with self.assertRaises(ValueError):worker_count(dict(hybrid_dml_workers=bad))
    def test_native_fifteen_process_allocator_each_spec(self):
        from farm import runner as R
        ctx=mp.get_context("spawn")
        for hero,spec in sorted(SCOPED_SPECS):
            with self.subTest(hero=hero,spec=spec):
                budget=R.fire_dml_context_budget(dict(hero=hero,spec=spec,hybrid=dict(device="dml")),ctx)
                barrier=ctx.Barrier(16)
                with ProcessPoolExecutor(15,mp_context=ctx,initializer=_init_lease,initargs=(budget,barrier,hero,spec)) as pool:
                    futures=[pool.submit(_lease,i) for i in range(15)]
                    barrier.wait(timeout=40)
                    rows=[f.result(timeout=40) for f in futures]
                self.assertEqual(len(set(p for p,_ in rows)),15)
                self.assertEqual(sum(ok for _,ok in rows),1)
    def test_denied_worker_never_detects_device(self):
        from farm import runner as R
        from farm.hybrid import engine as E
        for hero,spec in SCOPED_SPECS:
            E.reset()
            with mock.patch.multiple(R,_HERO=hero,_SPEC=spec,_SCOPED_DML_ALLOWED=False),mock.patch("farm.hybrid.device.detect",side_effect=AssertionError("device touched")):
                self.assertIsNone(E._engine());self.assertEqual(E._ENGINE_STATE,"cpu")
        E.reset()
    def test_fire_and_other_classes_keep_budgets(self):
        from farm import runner as R
        ctx=SimpleNamespace(BoundedSemaphore=mock.Mock(return_value="lease"))
        self.assertEqual(R.fire_dml_context_budget(dict(hero="mage",spec="fire",fire_dml_workers=6,hybrid=dict(device="dml")),ctx),"lease")
        ctx.BoundedSemaphore.assert_called_once_with(6)
        self.assertIsNone(R.fire_dml_context_budget(dict(hero="paladin",spec="holy",hybrid=dict(device="dml")),ctx))
    def test_non_dml_scoped_backend_not_budgeted(self):
        from farm import runner as R
        self.assertIsNone(R.fire_dml_context_budget(dict(hero="priest",spec="shadow",hybrid=dict(device="cpu")),None))

class Lifecycle(unittest.TestCase):
    def test_preflight_exits_before_pool_delegation_each_spec(self):
        from farm.hybrid import runner as H,engine as E
        from farm import runner as R
        for hero,spec in SCOPED_SPECS:
            checked=dict(ok=True,meta=dict(device="dml",name="mock-owner"),lifecycle=dict(pid=17,exited=True,exitcode=0))
            with mock.patch("farm.hybrid.mage_priest_preflight.isolated_preflight",return_value=checked) as pre,mock.patch.object(H,"detect",side_effect=AssertionError("parent device")),mock.patch.object(R,"run_job",return_value={"done":1}) as run:
                job=dict(id="fixture",worker="local-hybrid",hero=hero,spec=spec,pool="mixed",targets=5,top=80,start=0,end=0)
                H.run_job(job,{},lambda _:None)
                pre.assert_called_once();self.assertIs(run.call_args.kwargs["eval_fn"],E.eval_span);self.assertTrue(run.call_args.args[0]["hybrid"]["preflight"]["exited"])
    def test_failed_preflight_honest_cpu_fallback(self):
        from farm.hybrid import runner as H
        from farm import runner as R
        with mock.patch("farm.hybrid.mage_priest_preflight.isolated_preflight",return_value=dict(ok=False,reason="parity",meta={})),mock.patch.object(R,"run_job",return_value={"done":1}) as run:
            H.run_job(dict(hero="priest",spec="holy",worker="local-hybrid"),{},lambda _:None)
        self.assertNotIn("eval_fn",run.call_args.kwargs)
        self.assertIn("parity",run.call_args.args[0]["hybrid"]["fallback"])
    def test_actual_child_lifecycle_with_cpu_backend(self):
        from farm.hybrid.mage_priest_preflight import isolated_preflight
        with mock.patch.dict(os.environ,{"FARM_HYBRID_DEVICE":"cpu"}):
            out=isolated_preflight(dict(hero="mage",spec="frost"),timeout=30)
        self.assertFalse(out["ok"]);self.assertTrue(out["lifecycle"]["exited"]);self.assertEqual(out["lifecycle"]["exitcode"],0)
    def test_locked_arcane_never_preflights(self):
        from farm.hybrid import runner as H
        from farm import runner as R
        with mock.patch.dict(os.environ,{"FARM_HYBRID_ARCANE_GPU":"0"}),mock.patch("farm.hybrid.mage_priest_preflight.isolated_preflight",side_effect=AssertionError("locked touched")),mock.patch.object(R,"run_job",return_value={}):
            H.run_job(dict(hero="mage",spec="arcane",worker="local-hybrid"),{},lambda _:None)
    def test_timeout_cleans_only_owned_mock_handle(self):
        from farm.hybrid import mage_priest_preflight as P
        receive=mock.Mock();receive.poll.return_value=False;send=mock.Mock();process=mock.Mock();process.is_alive.side_effect=[True,False]
        ctx=mock.Mock();ctx.Pipe.return_value=(receive,send);ctx.Process.return_value=process
        with mock.patch.object(P.mp,"get_context",return_value=ctx),self.assertRaises(TimeoutError):P.isolated_preflight(dict(hero="priest",spec="holy"),timeout=.01)
        process.terminate.assert_called_once();process.join.assert_called_with(10)

class Correctness(unittest.TestCase):
    def test_projected_final_is_canonical_each_spec_batched_and_algebra(self):
        from farm.hybrid.engine import BatchFights
        from farm.hybrid.test_stat_kernel_greedy import _catalog_build
        from farm.hybrid.registry import cpu_dps
        from sunken_sim.esc import empty_points,apply_points
        for hero,spec in sorted(SCOPED_SPECS):
            build=_catalog_build(hero,spec,0);points=empty_points();points["potency"]=1
            engine=BatchFights();engine.hero=hero;engine.spec=spec;engine.targets=5
            from farm.score import score_build
            with mock.patch("sunken_sim.esc.greedy_points",side_effect=lambda score:(score(points),points)):
                expected=score_build(hero,spec,5,build)[0]
            with mock.patch("farm.hybrid.esc_device.algebra_mode",return_value="off"),mock.patch("farm.hybrid.stat_kernel.greedy_points_batched",return_value=(-17.0,points)):
                self.assertEqual(engine.greedy_points(build),(expected,points))
            with mock.patch("farm.hybrid.esc_device.algebra_mode",return_value="on"),mock.patch("farm.hybrid.esc_algebra.greedy_points_algebra",return_value=(-17.0,points,None)):
                self.assertEqual(engine.greedy_points(build),(expected,points))
    def test_fire_canonical_route_unchanged(self):
        from farm.hybrid.engine import BatchFights
        from sunken_sim.shadow import Build
        from sunken_sim.esc import empty_points
        e=BatchFights();e.hero="mage";e.spec="fire";e.dps_many=mock.Mock(return_value=[123.0,123.0]);points=empty_points();b=Build(frozenset(),frozenset(),(),0,0,0,0)
        with mock.patch("farm.hybrid.registry.cpu_dps",side_effect=AssertionError("Fire oracle route changed")):
            self.assertEqual(e._canonical_fire_esc([b],[(1.,points)]),[(123.,points)])
    def test_nonfinite_scoped_selfcheck_rejected(self):
        from farm import runner as R
        from farm.hybrid import engine as E
        for hero,spec in SCOPED_SPECS:
            with mock.patch.multiple(R,_HERO=hero,_SPEC=spec,_TARGETS=5),mock.patch("farm.hybrid.registry.cpu_dps",return_value=1.):
                self.assertFalse(E._self_check([None],[float("nan")]))
        E.reset()
    def test_scoped_preflight_rejects_nan(self):
        from farm.hybrid import runner as H
        from farm.hybrid.device import DeviceInfo
        for hero,spec in SCOPED_SPECS:
            fake=SimpleNamespace(dps_many=lambda builds:[float("nan")]*len(builds))
            with mock.patch.object(H.registry,"cpu_dps",return_value=1.),mock.patch.object(H.registry,"make_engine",return_value=fake):
                self.assertFalse(H.fight_check(DeviceInfo("cpu","mock"),hero,spec,5)["ok"])
    def test_final_nonfinite_and_length_mismatch_fail_closed(self):
        e=SimpleNamespace(hero="priest",spec="holy",targets=5)
        with self.assertRaises(ValueError):canonical_esc(e,[None],[])
        with mock.patch("farm.hybrid.mage_priest_resources.canonical_final_dps",return_value=float("nan")),mock.patch("sunken_sim.esc.apply_points",return_value=None),self.assertRaises(ValueError):canonical_esc(e,[None],[(1.,{})])

class Telemetry(unittest.TestCase):
    def test_mixed_paths_pids_and_final_cpu_guard_distinct(self):
        job=dict(hybrid=dict(device="dml",name="mock"))
        for pid,actual,gpu,cpu in ((1,"hybrid",256,0),(2,"cpu-fallback",0,0),(1,"mixed",64,2)):
            record_execution(job,dict(hybrid_execution=dict(pid=pid,actual=actual,engine_state="gpu" if gpu else "cpu",lease_allowed=bool(gpu),gpu_compile_rows=gpu,cpu_compile_rows=cpu,canonical_final_builds=1,reasons=[])))
        meta=job["hybrid"];self.assertEqual(meta["device"],"mixed");self.assertEqual(meta["worker_processes"]["1"]["gpu_compile_rows"],320);self.assertEqual(meta["worker_processes"]["1"]["canonical_final_builds"],2)
    def test_observer_failure_never_becomes_math_error(self):
        emit_tick(mock.Mock(side_effect=OSError("recoverable observer failure")),{})
        record_execution(dict(hybrid={}),dict(hybrid_execution={"bad":"metadata"}))
        with mock.patch("builtins.print",side_effect=OSError("log disk unavailable")):
            emit_tick(mock.Mock(side_effect=OSError("recoverable observer failure")),{})
            record_execution(dict(hybrid={}),dict(hybrid_execution={"bad":"metadata"}))
