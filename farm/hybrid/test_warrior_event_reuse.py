# -*- coding: utf-8 -*-
"""Warrior event-reuse: unbaked Whirlwind cleave, crit/potency rescore the same tape."""

from __future__ import annotations

import unittest

from farm.hybrid.test_stat_kernel_greedy import _catalog_build
from sunken_sim import warrior as mod
from sunken_sim.esc import apply_points, points_from_build
from sunken_sim.shadow import FIGHT


def _plus(build, attr: str):
    points = dict(points_from_build(build))
    points[attr] = int(points.get(attr, 0)) + 1
    return apply_points(build, points)


def _dps(report) -> float:
    return sum(float(v) for v in report.sources.values()) / FIGHT


def _shape(events):
    return [
        (ev[0], ev[2], ev[4], ev[5], ev[6], ev[8], ev[9], ev[10])
        for ev in events
    ]


class WarriorEventReuseTests(unittest.TestCase):
    def test_cleave_unbaked_and_crit_potency_reuse_tape(self):
        base = _catalog_build("warrior", "arms", 0)
        for spec in mod.SPECS:
            with self.subTest(spec=spec):
                mod._TIMELINE.clear()
                first = mod.simulate(base, 5, spec)
                keys = len(mod._TIMELINE)
                self.assertGreater(keys, 0)
                cached = next(iter(mod._TIMELINE.values()))
                events = cached[0]
                cleaves = [ev for ev in events if ev[1] == "Whirlwind (cleave)"]
                self.assertTrue(cleaves, "expected Whirlwind (cleave) events")
                for ev in cleaves:
                    self.assertIsNone(ev[-1])
                    self.assertTrue(ev[6])  # auto
                    self.assertGreater(ev[4], 0)  # count = targets-1

                crit_build = _plus(base, "crit")
                pot_build = _plus(base, "potency")
                reused_crit = mod.simulate(crit_build, 5, spec)
                reused_pot = mod.simulate(pot_build, 5, spec)
                self.assertEqual(len(mod._TIMELINE), keys)

                saved = dict(mod._TIMELINE)
                mod._TIMELINE.clear()
                fresh_crit = mod.simulate(crit_build, 5, spec)
                fresh_pot = mod.simulate(pot_build, 5, spec)
                for name, reused, fresh in (
                    ("crit", reused_crit, fresh_crit),
                    ("potency", reused_pot, fresh_pot),
                ):
                    scale = max(1.0, abs(_dps(fresh)))
                    self.assertLessEqual(
                        abs(_dps(reused) - _dps(fresh)) / scale,
                        1e-12,
                        msg=f"{spec} {name} reused={_dps(reused):.12f} fresh={_dps(fresh):.12f}",
                    )
                    self.assertAlmostEqual(
                        float(reused.sources.get("Whirlwind (cleave)", 0.0)),
                        float(fresh.sources.get("Whirlwind (cleave)", 0.0)),
                        places=9,
                    )
                # restoring is unnecessary; next spec clears again

    def test_gpu_tape_matches_cpu_and_shares_shape_across_crit(self):
        import torch
        from farm.hybrid.device import detect
        from farm.hybrid.registry import make_engine
        from farm.hybrid.warrior_gpu_timeline import generate_warrior_timelines

        base = _catalog_build("warrior", "arms", 0)
        crit_build = _plus(base, "crit")
        builds = [base, crit_build]
        for spec in mod.SPECS:
            with self.subTest(spec=spec):
                pairs = generate_warrior_timelines(torch, torch.device("cpu"), builds, spec, 5)
                self.assertEqual(_shape(pairs[0][0]), _shape(pairs[1][0]))
                engine = make_engine(detect("warrior", spec), "warrior", spec, 5)
                gpu = engine.dps_many(builds)
                mod._TIMELINE.clear()
                cpu = [_dps(mod.simulate(b, 5, spec)) for b in builds]
                for label, cpu_dps, gpu_dps in zip(("base", "crit"), cpu, gpu):
                    scale = max(1.0, abs(cpu_dps))
                    self.assertLessEqual(
                        abs(gpu_dps - cpu_dps) / scale,
                        1e-4,
                        msg=f"{spec} {label} cpu={cpu_dps:.9f} gpu={gpu_dps:.9f}",
                    )


if __name__ == "__main__":
    unittest.main()
