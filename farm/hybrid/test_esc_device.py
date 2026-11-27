# -*- coding: utf-8 -*-
"""Tests for farm/hybrid/esc_device.py (device algebra, persistent buffers, routing).

python -m unittest farm.hybrid.test_esc_device   (needs torch; CPU torch is enough,
FARM_HYBRID_TEST_DML=1 additionally runs the device tests on DirectML)
"""

from __future__ import annotations

import os
import unittest

import numpy as np

from farm.hybrid import esc_algebra as A
from farm.hybrid import esc_device as ed

try:
    import torch
except Exception:  # pragma: no cover
    torch = None

CASES = (("siren", "sharpshooter"), ("necromancer", "essence"), ("windmaster", "combat"))


def _targets():
    out = [torch.device("cpu")]
    if os.environ.get("FARM_HYBRID_TEST_DML") == "1":
        import torch_directml

        out.append(torch_directml.device())
    return out


def _trace(hero, spec, idx=0, points=None):
    import importlib

    from farm.hybrid.test_stat_kernel_greedy import _catalog_build
    from sunken_sim.esc import apply_points

    mod = importlib.import_module(f"sunken_sim.{hero}")
    b = apply_points(_catalog_build(hero, spec, idx), points or {})
    keys = {k for k, v in mod.stats_of(b).items() if type(v) is float}
    for _ in range(6):
        tr = A.trace_current(mod, b, 5, spec, keys)
        if tr.ok or not tr.blame:
            break
        keys -= tr.blame
    return mod, b, tr


@unittest.skipIf(torch is None, "torch not installed")
class DeviceProgramTests(unittest.TestCase):
    def setUp(self):
        ed.reset()

    def test_f32_error_far_below_tie_band(self):
        rng = np.random.default_rng(1)
        for target in _targets():
            for hero, spec in CASES:
                mod, b, tr = _trace(hero, spec)
                self.assertTrue(tr.ok, tr.note)
                keys = sorted(set(tr.program.leaves.values()))
                base = mod.stats_of(b)
                cols = [{k: base[k] * (1 + 0.02 * rng.standard_normal()) for k in keys} for _ in range(6)]
                cols.insert(0, {k: base[k] for k in keys})
                V = tr.program.evaluate({k: np.asarray([c[k] for c in cols]) for k in keys}) if keys else None
                exact = A.score_cpu(tr, A.event_weights(tr, V))
                dp = ed.CACHE.get(tr, torch, target, torch.float32)
                got = dp.score(np.asarray([[c[k] for k in dp.leaf_keys] for c in cols]))
                rel = np.abs(got - exact) / np.abs(exact)
                self.assertLess(float(rel.max()), ed.ERR_LIMIT / 10, f"{hero}/{spec}/{target}")

    def test_cache_hit_bounds_invalidation_reset(self):
        _m, _b, tr1 = _trace("siren", "sharpshooter")
        _m, _b, tr2 = _trace("siren", "sharpshooter", points={"crit": 3})
        self.assertNotEqual(tr1.token, tr2.token)  # new build -> new buffers, never stale weights
        c = ed.DeviceCache(max_entries=2)
        cpu = torch.device("cpu")
        p1 = c.get(tr1, torch, cpu, torch.float32)
        self.assertIs(c.get(tr1, torch, cpu, torch.float32), p1)
        self.assertEqual((c.hits, c.misses), (1, 1))
        self.assertIsNot(c.get(tr1, torch, cpu, torch.float64), p1)  # dtype in key
        self.assertIsNot(c.get(tr2, torch, cpu, torch.float32), p1)
        self.assertEqual(len(c), 2)
        self.assertEqual(c.evictions, 1)
        old = ed.SCHEMA
        try:
            ed.SCHEMA = old + 1  # schema bump: old entries unreachable
            self.assertIsNot(c.get(tr2, torch, cpu, torch.float32), p1)
        finally:
            ed.SCHEMA = old
        small = ed.DeviceCache(max_entries=8, max_bytes=1)
        small.get(tr1, torch, cpu, torch.float32)
        small.get(tr2, torch, cpu, torch.float32)
        self.assertEqual(len(small), 1)  # byte bound keeps only the newest
        c.reset()
        self.assertEqual(len(c), 0)
        ed.CACHE.get(tr1, torch, cpu, torch.float32)
        ed.reset()
        self.assertEqual(len(ed.CACHE), 0)


class RouterTests(unittest.TestCase):
    def test_forced_modes_deterministic(self):
        for mode in ("cpu", "gpu"):
            r = ed.Router(mode)
            for i in range(20):
                self.assertEqual(r.choose(), mode)
                r.record(mode, 1.0 + (i % 3))

    def test_auto_warmup_hysteresis_probe(self):
        r = ed.Router("auto", warm=2, probe=5, hysteresis=0.8)
        seen = []
        for _ in range(4):
            route = r.choose()
            seen.append(route)
            r.record(route, 1.0 if route == "gpu" else 2.0)
        self.assertEqual(sorted(seen), ["cpu", "cpu", "gpu", "gpu"])
        self.assertEqual(r.current, "gpu")
        r2 = ed.Router("auto", warm=2, probe=1000, hysteresis=0.8)
        for _ in range(4):
            route = r2.choose()
            r2.record(route, 1.0 if route == "gpu" else 1.1)  # within noise band -> no switch
        self.assertEqual(r2.current, "cpu")
        probes = [r.choose() for _ in range(10)]
        self.assertIn("cpu", probes)  # periodic re-probe of the other route

    def test_probe_backoff_and_arms(self):
        r = ed.Router("auto", warm=1, probe=2, arms=("batched", "algebra"))
        for _ in range(40):
            arm = r.choose()
            r.record(arm, 1.0 if arm == "batched" else 5.0)
        self.assertEqual(r.current, "batched")
        self.assertLessEqual(r.probes, 5)  # gap 2,4,8,16 -> few probes in 40 calls
        self.assertGreater(r.gap, 2)
        self.assertEqual(ed.Router("algebra", arms=("batched", "algebra")).choose(), "algebra")

    def test_error_disables_gpu(self):
        r = ed.Router("gpu")
        r.error(ed.ERR_LIMIT / 2)
        self.assertEqual(r.choose(), "gpu")
        r.error(ed.ERR_LIMIT * 2)
        self.assertEqual(r.choose(), "cpu")
        self.assertFalse(r.summary()["gpu_ok"])


@unittest.skipIf(torch is None, "torch not installed")
class DeviceGreedyTests(unittest.TestCase):
    def setUp(self):
        ed.reset()

    def _run(self, hero, spec, idx, router, target):
        from farm.hybrid.stat_kernel import greedy_points_batched, structural_skip_attrs
        from farm.hybrid.test_stat_kernel_greedy import _catalog_build, cpu_dps_many

        build = _catalog_build(hero, spec, idx)
        many = cpu_dps_many(hero, spec)
        ref = greedy_points_batched(many, build, hero=hero)
        got = A.greedy_points_algebra(
            many, build, hero, spec, 5, skip=structural_skip_attrs(hero), device=(torch, target), router=router
        )
        return ref, got

    def test_gpu_route_points_identical(self):
        for target in _targets():
            for hero, spec in CASES:
                for idx in (0, 1):
                    router = ed.Router("gpu")
                    ref, got = self._run(hero, spec, idx, router, target)
                    self.assertEqual(got[:2], ref, f"{hero}/{spec}/{idx}/{target}")
                    self.assertGreater(got[2].approx + got[2].validated, 0)
                    self.assertTrue(router.gpu_ok, router.summary())

    def test_auto_route_points_identical(self):
        for hero, spec in CASES:
            ref, got = self._run(hero, spec, 0, ed.Router("auto"), torch.device("cpu"))
            self.assertEqual(got[:2], ref, f"{hero}/{spec}")

    def test_injected_error_still_exact(self):
        """f32 noise below TIE_REL/2 but above ERR_LIMIT: decisions exact, route disabled."""
        orig = ed.DeviceProgram.score

        def noisy(self, m):
            out = orig(self, m)
            return out * (1 + 0.4 * ed.TIE_REL * np.where(np.arange(len(out)) % 2, 1, -1))

        ed.DeviceProgram.score = noisy
        try:
            router = ed.Router("gpu")
            ref, got = self._run("siren", "sharpshooter", 0, router, torch.device("cpu"))
        finally:
            ed.DeviceProgram.score = orig
        self.assertEqual(got[:2], ref)
        self.assertFalse(router.gpu_ok)


class StrategyRouterEngineTests(unittest.TestCase):
    def test_engine_auto_strategy_exact_and_samples_both(self):
        from farm.hybrid.engine import BatchFights
        from farm.hybrid.stat_kernel import greedy_points_batched
        from farm.hybrid.test_stat_kernel_greedy import _catalog_build, cpu_dps_many

        many = cpu_dps_many("windmaster", "combat")

        class Fake(BatchFights):
            def dps_many(self, builds):
                return many(builds)

        eng = Fake()
        eng.hero, eng.spec, eng.targets = "windmaster", "combat", 5
        ed.reset()
        old = os.environ.get("FARM_HYBRID_ESC_ALGEBRA")
        os.environ["FARM_HYBRID_ESC_ALGEBRA"] = "auto"
        try:
            for idx in (0, 1, 0, 1, 0):
                b = _catalog_build("windmaster", "combat", idx)
                self.assertEqual(eng.greedy_points(b), greedy_points_batched(many, b, hero="windmaster"))
        finally:
            if old is None:
                os.environ.pop("FARM_HYBRID_ESC_ALGEBRA", None)
            else:
                os.environ["FARM_HYBRID_ESC_ALGEBRA"] = old
        (r,) = [v for k, v in ed._ROUTERS.items() if k[2] == ("batched", "algebra")]
        self.assertTrue(all(len(v) >= 2 for v in r.t.values()), r.summary())

    def test_modes_parse(self):
        old = os.environ.get("FARM_HYBRID_ESC_ALGEBRA")
        try:
            for v, want in (("0", "off"), ("1", "on"), ("auto", "auto"), ("junk", "off")):
                os.environ["FARM_HYBRID_ESC_ALGEBRA"] = v
                self.assertEqual(ed.algebra_mode(), want)
            os.environ.pop("FARM_HYBRID_ESC_ALGEBRA", None)
            self.assertEqual(ed.algebra_mode(), "auto")
        finally:
            if old is None:
                os.environ.pop("FARM_HYBRID_ESC_ALGEBRA", None)
            else:
                os.environ["FARM_HYBRID_ESC_ALGEBRA"] = old


if __name__ == "__main__":
    unittest.main()
