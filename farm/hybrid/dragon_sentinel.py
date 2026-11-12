# -*- coding: utf-8 -*-
"""dragon_sentinel (ruby, obsidian, emerald): GPU kind/weight + optional GPU timeline.

Set FARM_HYBRID_GPU_TIMELINE=0 to force CPU sunken_sim.dragon_sentinel timelines.
Shared kind-score kernel: farm/hybrid/kindscore.py.
"""
from __future__ import annotations

import os

from farm.hybrid.kindscore import KindFights, MAX_BATCH, compile_sums, pack, timeline


class DragonSentinelFights(KindFights):
    MODULE = "dragon_sentinel"

    def _gpu_timelines(self, builds: list) -> list[tuple[list, dict]]:
        from farm.hybrid.dragon_sentinel_gpu_timeline import generate_dragon_sentinel_timelines

        return generate_dragon_sentinel_timelines(self.torch, self.target, builds, self.spec, self.targets)

    def dps_many(self, builds: list) -> list[float]:
        from sunken_sim.shadow import FIGHT

        want = os.environ.get("FARM_HYBRID_GPU_TIMELINE", "auto").strip().lower()
        # The torch timeline (*_gpu_timeline.py) still replays the old deterministic dithers; the sim
        # counts chances as probabilities since 2026-11-12/13, so the timeline stays on the CPU sim.
        # The exact GPU route for this class is farm.hybrid.dragon_sentinel_cl (OpenCL).
        use_gpu_tl = False and (
            want not in ("0", "false", "off", "cpu")
            and (want in ("1", "true", "force") or bool(getattr(self.device, "gpu", False)))
        )
        if use_gpu_tl and builds:
            rows = self._gpu_timelines(builds)
        else:
            rows = [timeline(self.module, b, self.targets, self.spec) for b in builds]
        out: list[float] = []
        for begin in range(0, len(rows), MAX_BATCH):
            part = rows[begin : begin + MAX_BATCH]
            sums = compile_sums(self.torch, self.target, pack(part))
            out.extend(float(row.sum()) / FIGHT for row in sums)
        self.fights += len(builds)
        return out
