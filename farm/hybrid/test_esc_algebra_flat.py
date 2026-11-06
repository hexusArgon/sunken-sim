# -*- coding: utf-8 -*-
"""Guarded ESC algebra on stats_of heroes without a Ledger (FLAT per-source events).

python -m unittest farm.hybrid.test_esc_algebra_flat
"""
from __future__ import annotations

import importlib
import unittest

from farm.hybrid import esc_algebra as A
from farm.hybrid.stat_kernel import structural_skip_attrs
from farm.hybrid.test_stat_kernel_greedy import _catalog_build
from sunken_sim.esc import apply_points, greedy_points


def _many(hero, spec, targets=5):
    mod = importlib.import_module(f"sunken_sim.{hero}")
    return lambda builds: [float(mod.simulate(b, targets, spec).dps) for b in builds]


class FlatAlgebraTest(unittest.TestCase):
    def test_exact_vs_full_greedy(self):
        for hero in sorted(A.FLAT_SOURCE_HEROES):
            mod = importlib.import_module(f"sunken_sim.{hero}")
            spec = mod.SPECS[0]
            with self.subTest(hero=hero, spec=spec):
                build = _catalog_build(hero, spec, 0)
                many = _many(hero, spec)
                ref = greedy_points(lambda c: many([apply_points(build, c)])[0])
                got = A.greedy_points_algebra(many, build, hero, spec, 5, skip=structural_skip_attrs(hero))
                self.assertEqual(got[1], ref[1])
                self.assertAlmostEqual(got[0], ref[0], delta=1e-9 * max(1.0, abs(ref[0])))
                self.assertGreater(got[2].rescored, 0)

    def test_trace_leaves_memo_clean(self):
        from sunken_sim import warrior

        build = _catalog_build("warrior", "fury", 0)
        warrior.simulate(build, 5, "fury")
        before = dict(warrior._TIMELINE)
        keys = {k for k, v in warrior.stats_of(build).items() if type(v) is float}
        tr = A.trace_current(warrior, build, 5, "fury", keys)
        self.assertTrue(tr.ok, tr.note)
        self.assertEqual(warrior._TIMELINE, before)
        self.assertNotIn("crit_points", tr.fields)


if __name__ == "__main__":
    unittest.main()
