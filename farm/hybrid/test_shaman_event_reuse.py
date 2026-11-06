# -*- coding: utf-8 -*-
"""Shaman event-reuse: unbaked Sulfuras echo; crit/potency rescore the same tape."""

from __future__ import annotations

import unittest

from farm.hybrid.test_stat_kernel_greedy import _catalog_build
from sunken_sim import shaman as mod
from sunken_sim.esc import apply_points, points_from_build
from sunken_sim.shadow import FIGHT, sulfuras_echo_chance


def _plus(build, attr: str):
    points = dict(points_from_build(build))
    points[attr] = int(points.get(attr, 0)) + 1
    return apply_points(build, points)


def _dps(report) -> float:
    return sum(float(v) for v in report.sources.values()) / FIGHT


def _shape(events):
    return [
        (ev[0], ev[1], ev[2], ev[3] if len(ev) > 3 else None, ev[4] if len(ev) > 4 else None)
        for ev in events
    ]


class ShamanEventReuseTests(unittest.TestCase):
    def test_echo_unbaked_and_crit_potency_reuse_tape(self):
        base = _catalog_build("shaman", "elemental", 0)
        for spec in mod.SPECS:
            with self.subTest(spec=spec):
                mod._TIMELINE.clear()
                first = mod.simulate(base, 5, spec)
                keys = len(mod._TIMELINE)
                self.assertGreater(keys, 0)
                cached = next(iter(mod._TIMELINE.values()))
                events = cached[0]
                stats = mod.stats_of(base)
                echoes = [ev for ev in events if ev[0] == "echo"]
                for ev in echoes:
                    self.assertAlmostEqual(ev[2], stats["ad"], places=9)
                    chance = sulfuras_echo_chance(stats["luck"])
                    self.assertNotAlmostEqual(ev[2], stats["ad"] * chance, places=9)
                sulf = [ev for ev in events if ev[0] == "deal" and ev[1] == "Sulfuras"]
                for ev in sulf:
                    self.assertAlmostEqual(ev[2], stats["int"], places=9)

                crit_build = _plus(base, "crit")
                pot_build = _plus(base, "potency")
                luck_build = _plus(base, "luck")
                reused_crit = mod.simulate(crit_build, 5, spec)
                reused_pot = mod.simulate(pot_build, 5, spec)
                self.assertEqual(len(mod._TIMELINE), keys)
                reused_luck = mod.simulate(luck_build, 5, spec)
                self.assertEqual(len(mod._TIMELINE), keys + 1)

                mod._TIMELINE.clear()
                fresh_crit = mod.simulate(crit_build, 5, spec)
                fresh_pot = mod.simulate(pot_build, 5, spec)
                fresh_luck = mod.simulate(luck_build, 5, spec)
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
        from farm.hybrid.shaman_gpu_timeline import generate_shaman_timelines

        base = _catalog_build("shaman", "elemental", 0)
        crit_build = _plus(base, "crit")
        luck_build = _plus(base, "luck")
        builds = [base, crit_build, luck_build]
        bound = [None, None, None]
        for spec in mod.SPECS:
            with self.subTest(spec=spec):
                pairs = generate_shaman_timelines(
                    torch, torch.device("cpu"), builds, spec, 5, bound
                )
                self.assertEqual(_shape(pairs[0][0]), _shape(pairs[1][0]))
                engine = make_engine(detect("shaman", spec), "shaman", spec, 5)
                gpu = engine.dps_many(builds)
                mod._TIMELINE.clear()
                cpu = [_dps(mod.simulate(b, 5, spec)) for b in builds]
                for label, cpu_dps, gpu_dps in zip(("base", "crit", "luck"), cpu, gpu):
                    scale = max(1.0, abs(cpu_dps))
                    self.assertLessEqual(
                        abs(gpu_dps - cpu_dps) / scale,
                        1e-4,
                        msg=f"{spec} {label} cpu={cpu_dps:.9f} gpu={gpu_dps:.9f}",
                    )


if __name__ == "__main__":
    unittest.main()
