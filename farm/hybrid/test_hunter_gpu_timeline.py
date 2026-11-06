# -*- coding: utf-8 -*-
"""GPU hunter timeline must match CPU simulate, including Survival ESC swaps."""

from __future__ import annotations

import unittest
from collections import defaultdict

import torch

from farm.hybrid.device import detect
from farm.hybrid.hunter_gpu_timeline import generate_hunter_timelines
from farm.hybrid.registry import make_engine
from farm.hybrid.test_stat_kernel_greedy import _catalog_build
from sunken_sim import hunter as mod
from sunken_sim.esc import apply_points
from sunken_sim.shadow import FIGHT


def _sum_names(events):
    by = defaultdict(float)
    for ev in events:
        by[ev[1]] += float(ev[2])
    return by


def _cpu(build):
    report = mod.simulate(build, 5, "survival")
    sources = {key: float(value) for key, value in report.sources.items()}
    return sources, sum(sources.values()) / FIGHT


class HunterGpuTimelineTests(unittest.TestCase):
    def test_survival_mastery_vs_pet_damage_matches_cpu(self):
        base = _catalog_build("hunter", "survival", 0)
        maps = (
            {"damage": 20, "mastery": 1, "pet_damage": 9},
            {"damage": 20, "pet_damage": 10},
        )
        builds = [apply_points(base, points) for points in maps]
        pairs = generate_hunter_timelines(torch, torch.device("cpu"), builds, "survival", 5)
        gpu_sums = [_sum_names(events) for events, _stats in pairs]
        cpu = [_cpu(build) for build in builds]
        self.assertAlmostEqual(gpu_sums[0]["Multi-Shot"], gpu_sums[1]["Multi-Shot"], places=6)
        self.assertAlmostEqual(
            gpu_sums[0]["Serpent Sting (\u0442\u0438\u043a\u0438)"],
            gpu_sums[1]["Serpent Sting (\u0442\u0438\u043a\u0438)"],
            places=6,
        )
        self.assertAlmostEqual(gpu_sums[0]["Grylls"], cpu[0][0]["Grylls"], places=6)
        self.assertAlmostEqual(gpu_sums[1]["Grylls"], cpu[1][0]["Grylls"], places=6)

        engine = make_engine(detect("hunter", "survival"), "hunter", "survival", 5)
        gpu = engine.dps_many(builds)
        for points, (_sources, cpu_dps), gpu_dps in zip(maps, cpu, gpu):
            scale = max(1.0, abs(cpu_dps))
            self.assertLessEqual(
                abs(gpu_dps - cpu_dps) / scale,
                1e-4,
                msg=f"{points} cpu={cpu_dps:.9f} gpu={gpu_dps:.9f}",
            )
        self.assertGreater(gpu[1], gpu[0])
        self.assertGreater(cpu[1][1], cpu[0][1])


if __name__ == "__main__":
    unittest.main()
