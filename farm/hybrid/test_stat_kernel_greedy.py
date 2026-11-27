# -*- coding: utf-8 -*-
"""Regression: farm.hybrid.stat_kernel.greedy_points_batched == sunken_sim.esc.greedy_points.

CPU only, no torch: python -m unittest farm.hybrid.test_stat_kernel_greedy
Broad sweep (62 cases): python tools/_esc_greedy_parity.py
"""

from __future__ import annotations

import contextlib
import importlib
import io
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from farm.hybrid import stat_kernel as K
from sunken_sim.esc import apply_points, greedy_points, points_from_build
from sunken_sim.shadow import Build


def _bare():
    return Build(frozenset(), frozenset(), (), 0, 0)


def _many(score):
    return lambda builds: [float(score(points_from_build(b))) for b in builds]


def _ref(score, build, total=None):
    return greedy_points(lambda c: score(c), total=total)


class SyntheticGreedyTests(unittest.TestCase):
    def test_tie_then_win_attr_not_dropped(self):
        # mastery ties while potency < 20, then beats damage; the removed zero-delta
        # skip dropped it after step 1 and spent on damage instead.
        def score(p):
            return 10.0 * p["potency"] + (5.0 * p["mastery"] if p["potency"] >= 20 else 0.0) + 1.0 * p["damage"]

        got = K.greedy_points_batched(_many(score), _bare(), hero="windmaster")
        ref = _ref(score, _bare())
        self.assertEqual(got, ref)
        self.assertEqual(got[1]["mastery"], 10)

    def test_all_ties_spend_like_full_greedy_incl_structural(self):
        # flat DPS: full greedy spends health 20, mana 20, healing_power 10;
        # healing_power is not fought but must still be picked in order.
        score = lambda p: 100.0  # noqa: E731
        got = K.greedy_points_batched(_many(score), _bare(), hero="windmaster", total=50)
        ref = _ref(score, _bare(), total=50)
        self.assertEqual(got, ref)
        self.assertEqual(got[1]["healing_power"], 10)

    def test_structural_attrs_not_fought(self):
        calls = []

        def many(builds):
            calls.extend(points_from_build(b) for b in builds)
            return [100.0 + p["potency"] for p in (points_from_build(b) for b in builds)]

        K.greedy_points_batched(many, _bare(), hero="windmaster", total=3)
        self.assertTrue(all(p["healing_power"] == 0 and p["pet_damage"] == 0 for p in calls))


class StructuralGuardTests(unittest.TestCase):
    def test_unknown_hero_fails_closed(self):
        self.assertEqual(K.structural_skip_attrs(None), frozenset())
        self.assertEqual(K.structural_skip_attrs("no_such_hero"), frozenset())

    def test_pet_heroes_fight_pet_damage(self):
        for hero in K.PET_DAMAGE_HEROES:
            self.assertNotIn("pet_damage", K.structural_skip_attrs(hero), hero)

    def test_source_read_disables_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            sim = Path(tmp) / "fake.py"
            sim.write_text('def f(stats):\n    return stats["healing_power"]\n', encoding="utf-8")
            K._attr_read_in_sources.cache_clear()
            try:
                with mock.patch.object(K, "_hero_files", return_value=[sim]):
                    self.assertNotIn("healing_power", K.structural_skip_attrs("fake"))
                    self.assertIn("pet_damage", K.structural_skip_attrs("fake"))
            finally:
                K._attr_read_in_sources.cache_clear()

    def test_box_sources_keep_known_skips(self):
        for hero in ("monk", "windmaster", "warrior", "priest", "mage"):
            self.assertEqual(K.structural_skip_attrs(hero), frozenset({"healing_power", "pet_damage"}), hero)


def _catalog_build(hero, spec, index=0, seed=7):
    try:
        from farm.catalog import load

        with contextlib.redirect_stdout(io.StringIO()):
            space, items = load(hero, spec, "mixed", None, 80)
    except Exception as exc:  # pragma: no cover - depends on farm-data
        raise unittest.SkipTest(f"catalog: {exc}")
    rng = random.Random(seed)
    build = None
    for k in range(index + 1):
        eq = tuple(items[c] for c in space.decode(rng.randrange(space.total))[0])
        tal = frozenset(rng.sample(list(space.talents), min(space.picks_with, len(space.talents)))) if k % 2 else frozenset()
        build = Build(tal, frozenset(), eq, 0, 0, 0, 0)
    return build


def cpu_dps_many(hero, spec, targets=5):
    from sunken_sim.ledger import score_events
    from sunken_sim.shadow import FIGHT

    mod = importlib.import_module(f"sunken_sim.{hero}")

    def many(builds):
        out = []
        for b in builds:
            r = mod.simulate(b, targets, spec)
            out.append(sum(score_events(r.events, r.stats).values()) / FIGHT)
        return out

    return many


def _old_zero_delta_greedy(dps_many, build, hero, total=None, cap=20):
    """The removed e231ff0 heuristic, kept only to show whether a sample discriminates."""
    from sunken_sim.esc import ESC_ATTRS, empty_points
    from sunken_sim.shadow import SKILL_POINTS

    total = SKILL_POINTS if total is None else total
    counts = empty_points()
    best = float(dps_many([apply_points(build, counts)])[0])
    skip = {"healing_power"} | ({"pet_damage"} if hero not in K.PET_DAMAGE_HEROES else set())
    for _ in range(total):
        names = [n for n in ESC_ATTRS if counts[n] < cap and n not in skip]
        if not names:
            break
        scores = dps_many([apply_points(build, {**counts, n: counts[n] + 1}) for n in names])
        pick, pick_dps, noop = None, -1.0, set()
        scale = max(1.0, abs(best))
        for n, d in zip(names, scores):
            if abs(d - best) <= 1e-12 * scale:
                noop.add(n)
            if d > pick_dps:
                pick, pick_dps = n, d
        counts[pick] += 1
        if pick_dps > best + 1e-12 * scale:
            skip |= noop - {pick}
        best = pick_dps
    return best, counts


class CatalogRegressionTests(unittest.TestCase):
    """Catalog samples depend on the map/library version (box 2.5.2a gave the
    590.55 vs 596.84 demon_hunter/havoc counterexample; desktop 2.5.2b samples
    differ). So assert parity with the full greedy on the *current* catalog, never
    a hardcoded DPS. The synthetic tie-then-win test above always discriminates."""

    CASES = (("windmaster", "combat"), ("siren", "sharpshooter"))

    def test_batched_equals_full_greedy_on_current_catalog(self):
        for hero, spec in self.CASES:
            many = cpu_dps_many(hero, spec)
            for index in range(2):
                with self.subTest(hero=hero, spec=spec, index=index):
                    build = _catalog_build(hero, spec, index)
                    ref = greedy_points(lambda c: many([apply_points(build, c)])[0])
                    got = K.greedy_points_batched(many, build, hero=hero)
                    self.assertEqual(got, ref)
                    old = _old_zero_delta_greedy(many, build, hero)
                    if old != ref:  # informative only: sample still discriminates here
                        print(f"\n[info] {hero}/{spec}[{index}] old zero-delta {old[0]:.6f} vs full {ref[0]:.6f}")


if __name__ == "__main__":
    unittest.main()
