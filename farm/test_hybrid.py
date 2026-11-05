"""Hybrid path tests. Run: python -m unittest farm.test_hybrid"""

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from farm import runner as cpu_runner
from farm.hybrid import HYBRID_WORKER, cpu_locked, detect
from farm.hybrid import runner as hybrid_runner
from farm.hybrid.kernel import decode_rows, item_table, parity, stat_fields, totals_cpu, totals_device
from farm.hybrid.lock import GpuLocked, assert_gpu_allowed
from sunken_sim.library import Item

ROOT = Path(__file__).resolve().parents[1]
HAS_TORCH = importlib.util.find_spec("torch") is not None
if HAS_TORCH:
    # Import once up front: patch.dict(sys.modules) below would otherwise drop
    # torch on exit, and re-importing its C extension crashes the process.
    import torch  # noqa: F401


class FakeSpace:
    slots = 3

    def __init__(self, builds):
        self.builds = builds
        self.total = len(builds)

    def decode(self, index):
        return self.builds[index], (), ()


def _items():
    return {
        "A": Item("A", "a", "", intel=10, crit=0.05, haste=0.1),
        "B": Item("B", "b", "", intel=3, potency=7, damage_pct=0.25),
        "C": Item("C", "c", "", mastery=4, cdr_pct=0.15, spell_crit=True),
    }


def _job(hero, spec, worker=HYBRID_WORKER):
    return {"id": "t", "worker": worker, "hero": hero, "spec": spec, "pool": "mixed", "start": 0, "end": 0, "targets": 1}


class LockTest(unittest.TestCase):
    def test_arcane_locked(self):
        self.assertTrue(cpu_locked("mage", "arcane"))
        self.assertTrue(cpu_locked(" Mage ", "ARCANE"))
        self.assertFalse(cpu_locked("mage", "fire"))
        self.assertFalse(cpu_locked("priest", "shadow"))
        with self.assertRaises(GpuLocked):
            assert_gpu_allowed("mage", "arcane")
        assert_gpu_allowed("mage", "fire")

    def test_arcane_detect_is_cpu_even_when_dml_forced(self):
        with mock.patch.dict(os.environ, {"FARM_HYBRID_DEVICE": "dml"}):
            info = detect("mage", "arcane")
        self.assertEqual(info.kind, "cpu")
        self.assertFalse(info.gpu)

    def test_dispatch(self):
        self.assertIs(hybrid_runner.dispatch(_job("mage", "arcane")), cpu_runner.run_job)
        self.assertIs(hybrid_runner.dispatch(_job("mage", "arcane", "local-esc")), cpu_runner.run_job)
        self.assertIs(hybrid_runner.dispatch(_job("mage", "fire", "local-esc")), cpu_runner.run_job)
        self.assertIs(hybrid_runner.dispatch(_job("mage", "fire")), hybrid_runner.run_job)

    def test_arcane_run_job_never_detects_device(self):
        with mock.patch.object(cpu_runner, "run_job", return_value={"ok": 1}) as old, \
             mock.patch.object(hybrid_runner, "detect", side_effect=AssertionError("GPU path touched")), \
             mock.patch.object(hybrid_runner, "prep_check", side_effect=AssertionError("GPU path touched")):
            ticks = []
            out = hybrid_runner.run_job(_job("mage", "arcane"), {}, ticks.append)
        self.assertEqual(out, {"ok": 1})
        old.assert_called_once()
        self.assertEqual(ticks, [])

    def test_arcane_scripts_stay_on_local_esc(self):
        for name in ("run_mage_arcane_top80_esc.py", "resume_mage_arcane_top80_esc.py"):
            path = ROOT / "tools" / name
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("hybrid", text, name)


class FallbackTest(unittest.TestCase):
    def test_cpu_env(self):
        with mock.patch.dict(os.environ, {"FARM_HYBRID_DEVICE": "cpu"}):
            self.assertEqual(detect("mage", "fire").kind, "cpu")

    def test_no_directml_falls_back(self):
        with mock.patch.dict(os.environ, {"FARM_HYBRID_DEVICE": "auto"}), \
             mock.patch.dict(sys.modules, {"torch_directml": None}):
            info = detect("mage", "fire")
        self.assertEqual(info.kind, "cpu")
        self.assertIn("not available", info.reason)

    def test_forced_dml_without_directml_raises(self):
        with mock.patch.dict(os.environ, {"FARM_HYBRID_DEVICE": "dml"}), \
             mock.patch.dict(sys.modules, {"torch_directml": None}):
            with self.assertRaises(RuntimeError):
                detect("mage", "fire")

    def test_hybrid_runs_cpu_fights(self):
        """Non-locked hybrid still hands fights to the old CPU run_job."""
        with mock.patch.dict(os.environ, {"FARM_HYBRID_DEVICE": "cpu"}), \
             mock.patch.object(cpu_runner, "run_job", return_value={"done": 1}) as old, \
             mock.patch("farm.catalog.load", return_value=(FakeSpace([("A", "B", "C")]), _items())), \
             mock.patch.object(hybrid_runner, "fight_check", side_effect=RuntimeError("no fights here")):
            ticks = []
            out = hybrid_runner.run_job(_job("mage", "fire"), {}, ticks.append)
        self.assertEqual(out, {"done": 1})
        old.assert_called_once()
        self.assertEqual(ticks[0]["hybrid"]["device"], "cpu")
        self.assertTrue(ticks[0]["hybrid"]["prep"]["parity"])


class KernelParityTest(unittest.TestCase):
    def setUp(self):
        self.items = _items()
        self.fields = stat_fields(Item)
        self.space = FakeSpace([("A", "B", "C"), ("A", "A", "A"), ("B",), ("C", "B")])
        self.index, self.table = item_table(self.items, self.fields)
        self.rows = decode_rows(self.space, self.index, 0, self.space.total)

    def test_fields_skip_bools(self):
        self.assertIn("intel", self.fields)
        self.assertIn("crit", self.fields)
        self.assertNotIn("spell_crit", self.fields)
        self.assertNotIn("rawcode", self.fields)

    def test_cpu_reference(self):
        out = totals_cpu(self.table, self.rows)
        col = self.fields.index("intel")
        self.assertEqual([row[col] for row in out], [13.0, 30.0, 3.0, 3.0])
        col = self.fields.index("haste")
        self.assertAlmostEqual(out[1][col], 0.3)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_torch_cpu_parity(self):
        from farm.hybrid.device import DeviceInfo

        ok, worst = parity(totals_cpu(self.table, self.rows), totals_device(self.table, self.rows, DeviceInfo("cpu", "cpu")))
        self.assertTrue(ok, worst)

    def test_dml_parity_if_present(self):
        info = detect("mage", "fire")
        if not info.gpu:
            self.skipTest(f"no DirectML: {info.reason}")
        ok, worst = parity(totals_cpu(self.table, self.rows), totals_device(self.table, self.rows, info))
        self.assertTrue(ok, worst)

    def test_parity_detects_mismatch(self):
        ref = totals_cpu(self.table, self.rows)
        bad = [list(row) for row in ref]
        bad[0][0] += 1.0
        self.assertFalse(parity(ref, bad)[0])


class FightTest(unittest.TestCase):
    """GPU fight stage (farm.hybrid.fight): lock, wiring, CPU-sim parity."""

    def test_arcane_never_gets_gpu_fights(self):
        from farm.hybrid.fight import GpuFights, gpu_fights_for
        from farm.hybrid.device import DeviceInfo

        self.assertFalse(gpu_fights_for("mage", "arcane"))
        self.assertTrue(gpu_fights_for("mage", "fire"))
        self.assertTrue(gpu_fights_for("mage", "frost"))
        self.assertFalse(gpu_fights_for("priest", "shadow"))
        with self.assertRaises(GpuLocked):
            GpuFights(DeviceInfo("cpu", "cpu"), "mage", "arcane", 5)

    def test_hybrid_fire_passes_gpu_eval_span(self):
        from farm.hybrid import fight

        with mock.patch.dict(os.environ, {"FARM_HYBRID_DEVICE": "cpu"}), \
             mock.patch.object(cpu_runner, "run_job", return_value={"done": 1}) as old, \
             mock.patch.object(hybrid_runner, "prep_check", return_value={"parity": True}), \
             mock.patch("farm.catalog.load", return_value=(FakeSpace([("A", "B", "C")]), _items())), \
             mock.patch.object(hybrid_runner, "fight_check", return_value={"ok": True, "n": 1}):
            ticks = []
            hybrid_runner.run_job(_job("mage", "fire"), {}, ticks.append)
        self.assertIs(old.call_args.kwargs.get("eval_fn"), fight.eval_span)
        self.assertTrue(ticks[0]["hybrid"]["gpu_fights"])

    def test_hybrid_fire_parity_fail_is_cpu(self):
        with mock.patch.dict(os.environ, {"FARM_HYBRID_DEVICE": "cpu"}), \
             mock.patch.object(cpu_runner, "run_job", return_value={"done": 1}) as old, \
             mock.patch.object(hybrid_runner, "prep_check", return_value={"parity": True}), \
             mock.patch("farm.catalog.load", return_value=(FakeSpace([("A", "B", "C")]), _items())), \
             mock.patch.object(hybrid_runner, "fight_check", return_value={"ok": False, "n": 1}):
            ticks = []
            hybrid_runner.run_job(_job("mage", "fire"), {}, ticks.append)
        self.assertNotIn("eval_fn", old.call_args.kwargs)
        self.assertFalse(ticks[0]["hybrid"]["gpu_fights"])

    def _parity(self, spec, info):
        from farm.catalog import load
        from farm.hybrid.fight import GpuFights, compare, cpu_dps
        from sunken_sim.esc import apply_points, empty_points
        from sunken_sim.shadow import Build
        import random

        try:
            space, items = load("mage", spec, "mixed", None, 80)
        except Exception as exc:  # catalog cache missing on this box
            self.skipTest(f"catalog: {exc}")
        rng = random.Random(7)
        builds = []
        for i in range(12):
            equipped = tuple(items[c] for c in space.decode(rng.randrange(space.total))[0])
            talents = frozenset(rng.sample(list(space.talents), space.picks_with)) if i % 2 else frozenset()
            build = Build(talents, frozenset(), equipped, 0, 0, 0, 0)
            if i % 3 == 0:
                points = empty_points()
                for name in list(points)[:4]:
                    points[name] = 5
                build = apply_points(build, points)
            builds.append(build)
        ref = [cpu_dps(b, 5, spec) for b in builds]
        got = GpuFights(info, "mage", spec, 5).dps_many(builds)
        res = compare(ref, got)
        self.assertTrue(res["ok"], res)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_fire_frost_torch_cpu_parity(self):
        from farm.hybrid.device import DeviceInfo

        for spec in ("fire", "frost"):
            with self.subTest(spec=spec):
                self._parity(spec, DeviceInfo("cpu", "cpu"))

    def test_fire_frost_dml_parity_if_present(self):
        info = detect("mage", "fire")
        if not info.gpu:
            self.skipTest(f"no DirectML: {info.reason}")
        for spec in ("fire", "frost"):
            with self.subTest(spec=spec):
                self._parity(spec, info)


def _sample(hero, spec, n, seed, points_every=3):
    from farm.catalog import load
    from sunken_sim.esc import apply_points, empty_points
    from sunken_sim.shadow import Build
    import random

    space, items = load(hero, spec, "mixed", None, 80)
    rng = random.Random(seed)
    builds = []
    for i in range(n):
        equipped = tuple(items[c] for c in space.decode(rng.randrange(space.total))[0])
        talents = frozenset(rng.sample(list(space.talents), space.picks_with)) if i % 2 else frozenset()
        glyphs = frozenset(rng.sample(list(space.glyphs), space.glyph_picks)) if i % 4 == 3 else frozenset()
        build = Build(talents, glyphs, equipped, 0, 0, 0, 0)
        if i % points_every == 0:
            points = empty_points()
            for name in list(points):
                points[name] = rng.randrange(0, 4)
            build = apply_points(build, points)
        builds.append(build)
    return builds


class RegistryTest(unittest.TestCase):
    """farm.hybrid.registry: one status per hero/spec, Arcane locked."""

    def test_statuses(self):
        from farm.hybrid import registry

        self.assertEqual(registry.status("mage", "arcane"), registry.LOCKED)
        self.assertEqual(registry.status("Mage", " Arcane "), registry.LOCKED)
        self.assertEqual(registry.status("mage", "fire"), registry.TIMELINE)
        self.assertEqual(registry.status("mage", "frost"), registry.TIMELINE)
        for spec in registry.PRIEST_SPECS:
            self.assertEqual(registry.status("priest", spec), registry.COMPILE)
        # every real spec is ported; cpu-only is what an unknown spec falls back to
        self.assertEqual(registry.status("paladin", "no_such_spec"), registry.CPU)
        for hero, (specs, _cls) in registry.KIND_HEROES.items():
            for spec in specs:
                self.assertEqual(registry.status(hero, spec), registry.COMPILE)
        self.assertFalse(registry.gpu_engine_for("mage", "arcane"))
        self.assertTrue(registry.gpu_engine_for("priest", "holy"))

    def test_matrix_covers_every_class(self):
        from farm.hybrid import registry

        table = registry.matrix()
        heroes = {row["hero"] for row in table}
        self.assertEqual(heroes, set(registry.MODULES))
        self.assertTrue(all(row["status"] in registry.STATUSES for row in table))
        locked = [(r["hero"], r["spec"]) for r in table if r["status"] == registry.LOCKED]
        self.assertEqual(locked, [("mage", "arcane")])

    def test_make_engine_refuses(self):
        from farm.hybrid import registry
        from farm.hybrid.device import DeviceInfo

        with self.assertRaises(GpuLocked):
            registry.make_engine(DeviceInfo("cpu", "cpu"), "mage", "arcane", 5)
        with self.assertRaises(ValueError):
            registry.make_engine(DeviceInfo("cpu", "cpu"), "paladin", "no_such_spec", 5)

    def test_cpu_only_spec_runs_old_fights(self):
        with mock.patch.dict(os.environ, {"FARM_HYBRID_DEVICE": "cpu"}), \
             mock.patch.object(cpu_runner, "run_job", return_value={"done": 1}) as old, \
             mock.patch.object(hybrid_runner, "prep_check", return_value={"parity": True}), \
             mock.patch("farm.catalog.load", return_value=(FakeSpace([("A", "B", "C")]), _items())), \
             mock.patch.object(hybrid_runner, "fight_check") as check:
            ticks = []
            hybrid_runner.run_job(_job("paladin", "no_such_spec"), {}, ticks.append)
        check.assert_not_called()
        self.assertNotIn("eval_fn", old.call_args.kwargs)
        self.assertEqual(ticks[0]["hybrid"]["status"], "cpu-only")
        self.assertFalse(ticks[0]["hybrid"]["gpu_fights"])

    def test_priest_passes_engine_eval_span(self):
        from farm.hybrid import engine

        with mock.patch.dict(os.environ, {"FARM_HYBRID_DEVICE": "cpu"}), \
             mock.patch.object(cpu_runner, "run_job", return_value={"done": 1}) as old, \
             mock.patch.object(hybrid_runner, "prep_check", return_value={"parity": True}), \
             mock.patch("farm.catalog.load", return_value=(FakeSpace([("A", "B", "C")]), _items())), \
             mock.patch.object(hybrid_runner, "fight_check", return_value={"ok": True, "n": 1}):
            ticks = []
            hybrid_runner.run_job(_job("priest", "shadow"), {}, ticks.append)
        self.assertIs(old.call_args.kwargs.get("eval_fn"), engine.eval_span)
        self.assertEqual(ticks[0]["hybrid"]["status"], "hybrid-compile")


class EngineFallbackTest(unittest.TestCase):
    """farm.hybrid.engine.eval_span: a worker that fails its self-check runs the old eval_span."""

    def tearDown(self):
        from farm.hybrid import engine

        engine.reset()

    def _run(self, gpu_value):
        from farm.hybrid import engine, registry

        class Fake(engine.BatchFights):
            def dps_many(self, builds):
                return [gpu_value] * len(builds)

        engine.reset()
        sub = {"start": 0, "done": 1, "fights": 1, "hits": [], "errors": 0, "error": ""}
        with mock.patch.multiple(
            cpu_runner, _HERO="priest", _SPEC="shadow", _TARGETS=5, _SPACE=FakeSpace([("A", "B", "C")]),
            _ITEMS=_items(), _SOURCES={}, _STOP=None, create=True,
        ), mock.patch.object(cpu_runner, "eval_span", return_value=sub) as old, \
             mock.patch.object(cpu_runner, "claim_item_bars", return_value=False), \
             mock.patch.object(registry, "make_engine", return_value=Fake()), \
             mock.patch("farm.hybrid.device.detect", return_value=None), \
             mock.patch.object(registry, "cpu_dps", return_value=100.0):
            out = engine.eval_span(0, 1)
        return out, old, engine._ENGINE_STATE

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_self_check_mismatch_falls_back(self):
        out, old, state = self._run(101.0)
        old.assert_called_once()
        self.assertEqual(state, "cpu")
        self.assertEqual(out["done"], 1)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_self_check_match_stays_gpu(self):
        out, old, state = self._run(100.0)
        old.assert_not_called()
        self.assertEqual(state, "gpu")
        self.assertEqual(out["fights"], 1)


class PriestTest(unittest.TestCase):
    """GPU compile stage for Priest (farm.hybrid.priest) vs the CPU sim."""

    def _parity(self, info):
        from farm.hybrid import registry
        from farm.hybrid.engine import compare

        for spec in registry.PRIEST_SPECS:
            with self.subTest(spec=spec):
                try:
                    builds = _sample("priest", spec, 16, 11)
                except Exception as exc:  # catalog cache missing on this box
                    self.skipTest(f"catalog: {exc}")
                ref = [registry.cpu_dps("priest", spec, 5, b) for b in builds]
                got = registry.make_engine(info, "priest", spec, 5).dps_many(builds)
                res = compare(ref, got)
                self.assertTrue(res["ok"], res)

    @unittest.skipUnless(HAS_TORCH, "torch not installed")
    def test_priest_torch_cpu_parity(self):
        from farm.hybrid.device import DeviceInfo

        self._parity(DeviceInfo("cpu", "cpu"))

    def test_priest_dml_parity_if_present(self):
        info = detect("priest", "shadow")
        if not info.gpu:
            self.skipTest(f"no DirectML: {info.reason}")
        self._parity(info)


class TimelineCacheTest(unittest.TestCase):
    """Mage exact timeline cache: same events + stats as a fresh simulate."""

    def test_cache_equals_fresh_simulate(self):
        from farm.hybrid import fight
        from sunken_sim.esc import ESC_ATTRS, apply_points, empty_points

        for spec in ("fire", "frost"):
            with self.subTest(spec=spec):
                try:
                    bases = _sample("mage", spec, 6, 21, points_every=99)
                except Exception as exc:
                    self.skipTest(f"catalog: {exc}")
                fight._TL_CACHE.clear()
                before = fight.TL_COUNTS["hit"]
                for base in bases:
                    for name in ESC_ATTRS:
                        points = empty_points()
                        points[name] = 1
                        build = apply_points(base, points)
                        cached = fight.timelines(build, 5, spec)
                        fresh = fight.timelines(build, 5, spec, cache=False)
                        self.assertEqual(len(cached), len(fresh))
                        for a, b in zip(cached, fresh):
                            self.assertEqual(a.events, b.events, (spec, name, a.bound))
                            self.assertEqual(a.stats, b.stats, (spec, name, a.bound))
                            self.assertEqual((a.spec, a.evocation, a.bound), (b.spec, b.evocation, b.bound))
                self.assertGreater(fight.TL_COUNTS["hit"], before)

    def test_timeline_stats_cover_reads(self):
        """Drift guard for map hotfixes: every sheet key the timeline reads is in the cache key."""
        from farm.hybrid import fight
        from sunken_sim import mage

        seen = set()
        on = [False]

        class Track(dict):
            def __getitem__(self, k):
                if on[0]:
                    seen.add(k)
                return dict.__getitem__(self, k)

            def get(self, k, d=None):
                if on[0]:
                    seen.add(k)
                return dict.get(self, k, d)

            def __contains__(self, k):
                if on[0]:
                    seen.add(k)
                return dict.__contains__(self, k)

        old_sheet, old_raws = mage.sheet, mage._raws

        def sheet(build):
            on[0] = True
            return Track(old_sheet(build))

        def raws(stats, build):
            on[0] = False
            try:
                return old_raws(dict(stats), build)
            finally:
                on[0] = True

        for spec in ("fire", "frost"):
            try:
                builds = _sample("mage", spec, 40, 5)
            except Exception as exc:
                self.skipTest(f"catalog: {exc}")
            with mock.patch.object(mage, "sheet", sheet), mock.patch.object(mage, "_raws", raws), fight._capture():
                for build in builds:
                    mage.simulate(build, 5, None, None, spec, use_history=False)
                    on[0] = False
        self.assertTrue(seen)
        self.assertLessEqual(seen, set(fight.TIMELINE_STATS) | {"crit"})


if __name__ == "__main__":
    unittest.main()