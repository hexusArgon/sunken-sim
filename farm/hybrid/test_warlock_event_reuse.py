# -*- coding: utf-8 -*-
"""Warlock event-reuse: potency is unbaked and rescores the same tape; crit/luck do not."""

from __future__ import annotations

import unittest

from farm.hybrid.test_stat_kernel_greedy import _catalog_build
from sunken_sim import warlock as mod
from sunken_sim.esc import apply_points, points_from_build
from sunken_sim.shadow import FIGHT


def _plus(build, attr: str):
    points = dict(points_from_build(build))
    points[attr] = int(points.get(attr, 0)) + 1
    return apply_points(build, points)


def _dps(report) -> float:
    return sum(float(v) for v in report.sources.values()) / FIGHT


def _shape(events):
    return [(ev[0], ev[1], ev[2], ev[3], ev[4] if len(ev) > 4 else 0.0) for ev in events]


class WarlockEventReuseTests(unittest.TestCase):
    def test_potency_reuses_tape_crit_and_luck_do_not(self):
        base = _catalog_build("warlock", "demonology", 0)
        for spec in mod.SPECS:
            with self.subTest(spec=spec):
                mod._TIMELINE.clear()
                first = mod.simulate(base, 5, spec)
                keys = len(mod._TIMELINE)
                self.assertGreater(keys, 0)
                cached = next(iter(mod._TIMELINE.values()))
                events = cached[0]
                self.assertTrue(any(len(ev) > 4 and ev[4] for ev in events), msg=f"{spec} no pot_coeff")

                pot_build = _plus(base, "potency")
                crit_build = _plus(base, "crit")
                luck_build = _plus(base, "luck")
                reused_pot = mod.simulate(pot_build, 5, spec)
                self.assertEqual(len(mod._TIMELINE), keys)
                reused_crit = mod.simulate(crit_build, 5, spec)
                after_crit = len(mod._TIMELINE)
                self.assertGreater(after_crit, keys)
                reused_luck = mod.simulate(luck_build, 5, spec)
                self.assertGreater(len(mod._TIMELINE), after_crit)

                mod._TIMELINE.clear()
                fresh_pot = mod.simulate(pot_build, 5, spec)
                fresh_crit = mod.simulate(crit_build, 5, spec)
                fresh_luck = mod.simulate(luck_build, 5, spec)
                for name, reused, fresh in (
                    ("potency", reused_pot, fresh_pot),
                    ("crit", reused_crit, fresh_crit),
                    ("luck", reused_luck, fresh_luck),
                    ("base", first, mod.simulate(base, 5, spec)),
                ):
                    scale = max(1.0, abs(_dps(fresh)))
                    self.assertLessEqual(
                        abs(_dps(reused) - _dps(fresh)) / scale,
                        1e-12,
                        msg=f"{spec} {name} reused={_dps(reused):.12f} fresh={_dps(fresh):.12f}",
                    )

    def test_gpu_tape_matches_cpu_and_shares_shape_across_potency(self):
        import torch
        from farm.hybrid.device import detect
        from farm.hybrid.registry import make_engine
        from farm.hybrid.warlock_gpu_timeline import generate_warlock_timelines, _policies_for

        base = _catalog_build("warlock", "demonology", 0)
        pot_build = _plus(base, "potency")
        crit_build = _plus(base, "crit")
        builds = [base, pot_build, crit_build]
        for spec in mod.SPECS:
            with self.subTest(spec=spec):
                first = next(_policies_for(spec, 5))
                pairs = generate_warlock_timelines(
                    torch, torch.device("cpu"), builds, spec, 5, [first] * len(builds)
                )
                self.assertEqual(_shape(pairs[0][0]), _shape(pairs[1][0]))
                engine = make_engine(detect("warlock", spec), "warlock", spec, 5)
                gpu = engine.dps_many(builds)
                mod._TIMELINE.clear()
                cpu = [_dps(mod.simulate(b, 5, spec)) for b in builds]
                for label, cpu_dps, gpu_dps in zip(("base", "potency", "crit"), cpu, gpu):
                    scale = max(1.0, abs(cpu_dps))
                    self.assertLessEqual(
                        abs(gpu_dps - cpu_dps) / scale,
                        1e-4,
                        msg=f"{spec} {label} cpu={cpu_dps:.9f} gpu={gpu_dps:.9f}",
                    )


if __name__ == "__main__":
    unittest.main()
