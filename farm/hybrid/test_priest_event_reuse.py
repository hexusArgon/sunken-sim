# -*- coding: utf-8 -*-
"""Priest event-reuse: crit/potency/luck rescore the same tape."""

from __future__ import annotations

import unittest

from farm.hybrid.test_stat_kernel_greedy import _catalog_build
from sunken_sim import shadow as mod
from sunken_sim.esc import apply_points, points_from_build
from sunken_sim.shadow import FIGHT, sulfuras_echo_chance


SPECS = ("shadow", "discipline", "holy")


def _plus(build, attr: str):
    points = dict(points_from_build(build))
    points[attr] = int(points.get(attr, 0)) + 1
    return apply_points(build, points)


def _dps(report) -> float:
    return sum(float(v) for v in report.sources.values()) / FIGHT


def _shape(events):
    return [(ev[0], ev[1], ev[2]) for ev in events]


def _key(build, spec: str, bound=None):
    stats = mod.character(build)
    return mod._timeline_key(build, stats, spec, 5, bound)


class PriestEventReuseTests(unittest.TestCase):
    def test_crit_potency_luck_reuse_tape(self):
        base = _catalog_build("priest", "shadow", 0)
        for spec in SPECS:
            with self.subTest(spec=spec):
                mod._TIMELINE.clear()
                first = mod.simulate(base, 5, spec=spec, use_history=False)
                keys = len(mod._TIMELINE)
                self.assertGreater(keys, 0)
                cached = next(iter(mod._TIMELINE.values()))
                events = cached[0]
                stats = mod.character(base)
                echoes = [ev for ev in events if ev[1] == "sulfuras_echo"]
                for ev in echoes:
                    chance = sulfuras_echo_chance(stats["luck"])
                    self.assertNotAlmostEqual(ev[2], stats["ad"] * chance, places=9)

                crit_build = _plus(base, "crit")
                pot_build = _plus(base, "potency")
                luck_build = _plus(base, "luck")
                reused_crit = mod.simulate(crit_build, 5, spec=spec, use_history=False)
                reused_pot = mod.simulate(pot_build, 5, spec=spec, use_history=False)
                reused_luck = mod.simulate(luck_build, 5, spec=spec, use_history=False)
                base_key = _key(base, spec)
                self.assertEqual(_key(pot_build, spec), base_key)
                self.assertEqual(_key(luck_build, spec), base_key)
                if _key(crit_build, spec) == base_key:
                    self.assertEqual(len(mod._TIMELINE), keys)

                mod._TIMELINE.clear()
                fresh_crit = mod.simulate(crit_build, 5, spec=spec, use_history=False)
                fresh_pot = mod.simulate(pot_build, 5, spec=spec, use_history=False)
                fresh_luck = mod.simulate(luck_build, 5, spec=spec, use_history=False)
                for name, reused, fresh in (
                    ("crit", reused_crit, fresh_crit),
                    ("potency", reused_pot, fresh_pot),
                    ("luck", reused_luck, fresh_luck),
                ):
                    scale = max(1.0, abs(_dps(fresh)))
                    self.assertLessEqual(
                        abs(_dps(reused) - _dps(fresh)) / scale,
                        1e-12,
                        msg=f"{spec} {name} reused={_dps(reused):.12f} fresh={_dps(fresh):.12f}",
                    )
                self.assertGreater(_dps(first), 0.0)

    def test_gpu_tape_matches_cpu_and_shares_shape_across_crit(self):
        import torch
        from farm.hybrid.device import detect
        from farm.hybrid.registry import make_engine
        from farm.hybrid.priest_gpu_timeline import generate_priest_timelines

        base = _catalog_build("priest", "shadow", 0)
        crit_build = _plus(base, "crit")
        luck_build = _plus(base, "luck")
        builds = [base, crit_build, luck_build]
        bound = [None, None, None]
        for spec in SPECS:
            with self.subTest(spec=spec):
                pairs = generate_priest_timelines(
                    torch, torch.device("cpu"), builds, spec, 5, bound
                )
                if _key(crit_build, spec) == _key(base, spec):
                    self.assertEqual(_shape(pairs[0][0]), _shape(pairs[1][0]))
                if _key(luck_build, spec) == _key(base, spec):
                    self.assertEqual(_shape(pairs[0][0]), _shape(pairs[2][0]))
                engine = make_engine(detect("priest", spec), "priest", spec, 5)
                gpu = engine.dps_many(builds)
                mod._TIMELINE.clear()
                cpu = [_dps(mod.simulate(b, 5, spec=spec, use_history=False)) for b in builds]
                for label, cpu_dps, gpu_dps in zip(("base", "crit", "luck"), cpu, gpu):
                    scale = max(1.0, abs(cpu_dps))
                    self.assertLessEqual(
                        abs(gpu_dps - cpu_dps) / scale,
                        1e-4,
                        msg=f"{spec} {label} cpu={cpu_dps:.9f} gpu={gpu_dps:.9f}",
                    )


if __name__ == "__main__":
    unittest.main()
