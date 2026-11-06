# -*- coding: utf-8 -*-
"""Cross-build batching (engine.finish_many / stat_kernel.greedy_points_many).

python -m unittest farm.hybrid.test_cross_build
FARM_HYBRID_TEST_DML=1: also real DirectML engine vs sequential (min-2 convention).
"""

from __future__ import annotations

import contextlib
import io
import os
import random
import unittest

from farm.hybrid.engine import BatchFights, chunked_many
from farm.hybrid.stat_kernel import greedy_points_batched, greedy_points_many
from farm.hybrid.test_stat_kernel_greedy import _catalog_build, cpu_dps_many


def _space(hero, spec):
    try:
        from farm.catalog import load

        with contextlib.redirect_stdout(io.StringIO()):
            return load(hero, spec, "mixed", None, 80)
    except Exception as exc:  # pragma: no cover
        raise unittest.SkipTest(f"catalog: {exc}")


def _calls(hero, spec, n, seed=3):
    """Independent finish_sextuple calls with heterogeneous talent/glyph list sizes."""
    space, items = _space(hero, spec)
    rng = random.Random(seed)
    calls = []
    for k in range(n):
        eq = tuple(items[c] for c in space.decode(rng.randrange(space.total))[0])
        tal = list(space.talents)[: max(space.picks_with, len(space.talents) - k % 3)]
        gly = list(space.glyphs)[: max(space.glyph_picks, len(space.glyphs) - k % 2)]
        calls.append((eq, tal, gly, space.picks_without, space.picks_with, space.glyph_picks))
    return calls


class Recorder:
    def __init__(self, fn, fail_over=None):
        self.fn, self.sizes, self.fail_over = fn, [], fail_over

    def __call__(self, builds):
        self.sizes.append(len(builds))
        if self.fail_over is not None and len(builds) > self.fail_over:
            raise RuntimeError("batch too big")
        return self.fn(builds)


def _fake(hero, spec, many):
    class Fake(BatchFights):
        def dps_many(self, builds):
            return many(builds)

    e = Fake()
    e.hero, e.spec, e.targets = hero, spec, 5
    return e


def _min2(many):
    return lambda builds: many(list(builds) * 2)[:1] if len(builds) == 1 else many(builds)


class ChunkTests(unittest.TestCase):
    def test_order_limits_no_singletons(self):
        f = lambda bs: [float(b) for b in bs]  # noqa: E731
        for n in range(0, 12):
            for limit in (2, 3, 5, 1024):
                rec = Recorder(f)
                self.assertEqual(chunked_many(rec, list(range(n)), limit), [float(x) for x in range(n)])
                self.assertTrue(all(2 <= s <= max(2, limit) + 1 for s in rec.sizes), (n, limit, rec.sizes))


class GreedyManyTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("FARM_HYBRID_ESC_ALGEBRA", None)

    def test_lockstep_equals_sequential(self):
        for hero, spec in (("demon_hunter", "havoc"), ("berserker", "headhunter"), ("necromancer", "essence")):
            many = cpu_dps_many(hero, spec)
            builds = [_catalog_build(hero, spec, i) for i in range(3)]
            rec = Recorder(many)
            got = greedy_points_many(rec, builds, hero=hero)
            self.assertEqual(got, [greedy_points_batched(many, b, hero=hero) for b in builds], hero)
            self.assertLessEqual(len(rec.sizes), 31)  # 1 base + 30 steps for all builds together

    def test_caps_drop_out_and_ties(self):
        hero, spec = "demon_hunter", "havoc"
        base = cpu_dps_many(hero, spec)
        tied = lambda bs: [round(x, 0) for x in base(bs)]  # noqa: E731 - coarse values force ties
        builds = [_catalog_build(hero, spec, i) for i in range(3)]
        for many in (base, tied):
            got = greedy_points_many(many, builds, hero=hero, total=14, cap=1)
            ref = [greedy_points_batched(many, b, hero=hero, total=14, cap=1) for b in builds]
            self.assertEqual(got, ref)

    def test_empty(self):
        self.assertEqual(greedy_points_many(lambda b: [], [], hero="demon_hunter"), [])


class FinishManyTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("FARM_HYBRID_ESC_ALGEBRA", None)

    def test_equals_sequential_chunks_and_isolation(self):
        for hero, spec in (("demon_hunter", "havoc"), ("windmaster", "combat")):
            many = cpu_dps_many(hero, spec)
            calls = _calls(hero, spec, 4)
            eng = _fake(hero, spec, many)
            ref = [eng.finish_sextuple(*c) for c in calls]
            for limit in (2, 7, 64, 1024):
                self.assertEqual(eng.finish_many(calls, limit=limit), ref, (hero, limit))
            self.assertEqual(eng.finish_many(calls[1:2]), ref[1:2])  # alone == in a group
            self.assertEqual(eng.finish_many(calls[::-1]), ref[::-1])  # order-independent per call

    def test_failure_propagates_for_fallback(self):
        hero, spec = "demon_hunter", "havoc"
        rec = Recorder(cpu_dps_many(hero, spec), fail_over=50)
        eng = _fake(hero, spec, rec)
        with self.assertRaises(RuntimeError):
            eng.finish_many(_calls(hero, spec, 3), limit=1024)
        self.assertEqual(len(eng.finish_many(_calls(hero, spec, 3), limit=40)), 3)  # chunking keeps it under


@unittest.skipUnless(os.environ.get("FARM_HYBRID_TEST_DML") == "1", "needs DirectML")
class DirectMLTests(unittest.TestCase):
    def test_real_engine_vs_sequential_min2_and_reset(self):
        from farm.hybrid import esc_device as ed
        from farm.hybrid.device import detect
        from farm.hybrid.registry import make_engine

        os.environ.pop("FARM_HYBRID_ESC_ALGEBRA", None)
        for hero, spec in (("demon_hunter", "havoc"), ("necromancer", "essence")):
            eng = make_engine(detect(hero, spec), hero, spec, 5)
            calls = _calls(hero, spec, 3)
            raw = eng.dps_many
            eng.dps_many = _min2(raw)
            try:
                ref = [eng.finish_sextuple(*c) for c in calls]
            finally:
                eng.dps_many = raw
            got = eng.finish_many(calls, limit=64)
            for g, r in zip(got, ref):
                self.assertEqual(g[1:], r[1:])
                self.assertLessEqual(abs(g[0] - r[0]), 1e-4 * max(1.0, abs(r[0])))
            ed.reset()
            eng2 = make_engine(detect(hero, spec), hero, spec, 5)  # fresh device engine
            self.assertEqual([x[1:] for x in eng2.finish_many(calls, limit=7)], [x[1:] for x in got])


if __name__ == "__main__":
    unittest.main()
