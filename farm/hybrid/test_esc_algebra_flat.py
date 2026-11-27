# -*- coding: utf-8 -*-
"""Guarded ESC algebra on stats_of heroes without a Ledger (FLAT per-source events).

python -m unittest farm.hybrid.test_esc_algebra_flat
"""
from __future__ import annotations

import unittest

from farm.hybrid import esc_algebra as A
from farm.hybrid.stat_kernel import structural_skip_attrs
from farm.hybrid.test_stat_kernel_greedy import _catalog_build
from sunken_sim.esc import apply_points, greedy_points

_FARM_HERO = {"shadow": "priest"}


def _farm_hero(module_hero: str) -> str:
    return _FARM_HERO.get(module_hero, module_hero)


def _specs(farm_hero: str):
    mod = A.hero_module(farm_hero)
    specs = getattr(mod, "SPECS", None)
    if specs:
        return tuple(specs)
    if farm_hero == "priest":
        return ("shadow", "discipline", "holy")
    raise AssertionError(f"no SPECS for {farm_hero}")


def _many(hero, spec, targets=5):
    import inspect

    mod = A.hero_module(hero)
    use_hist = "use_history" in inspect.signature(mod.simulate).parameters

    def fn(builds):
        out = []
        for b in builds:
            kw = {"spec": spec}
            if use_hist:
                kw["use_history"] = False
            out.append(float(mod.simulate(b, targets, **kw).dps))
        return out

    return fn


class FlatAlgebraTest(unittest.TestCase):
    def test_exact_vs_full_greedy(self):
        for module_hero in sorted(A.FLAT_SOURCE_HEROES):
            hero = _farm_hero(module_hero)
            spec = _specs(hero)[0]
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

    def test_mage_priest_all_specs_match_full_greedy(self):
        self.assertIn("mage", A.FLAT_SOURCE_HEROES)
        self.assertIn("shadow", A.FLAT_SOURCE_HEROES)
        self.assertIn("priest", A.ALGEBRA_HEROES)
        self.assertIn("mage", A.ALGEBRA_HEROES)
        self.assertNotIn("shadow", A.ALGEBRA_HEROES)
        for hero, specs in (("mage", ("frost", "fire", "arcane")),
                            ("priest", ("shadow", "discipline", "holy"))):
            for spec in specs:
                with self.subTest(hero=hero, spec=spec):
                    build = _catalog_build(hero, spec, 0)
                    many = _many(hero, spec)
                    ref = greedy_points(lambda c: many([apply_points(build, c)])[0])
                    got = A.greedy_points_algebra(many, build, hero, spec, 5, skip=structural_skip_attrs(hero))
                    self.assertEqual(got[1], ref[1], f"{hero}/{spec}")
                    self.assertAlmostEqual(got[0], ref[0], delta=1e-9 * max(1.0, abs(ref[0])))


if __name__ == "__main__":
    unittest.main()
