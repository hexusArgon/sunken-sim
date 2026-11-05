# -*- coding: utf-8 -*-
"""tinker: GPU kind/weight + optional GPU timeline.

Set FARM_HYBRID_GPU_TIMELINE=0 to force CPU sunken_sim.tinker timelines.
Shared kind-score kernel: farm/hybrid/kindscore.py.
"""
from __future__ import annotations

import os

from farm.hybrid.kindscore import KindFights, MAX_BATCH, compile_sums, pack, timeline


class TinkerFights(KindFights):
    MODULE = "tinker"

    def _gpu_timelines(self, builds: list) -> list[tuple[list, dict]]:
        from farm.hybrid.tinker_gpu_timeline import generate_tinker_timelines

        return generate_tinker_timelines(self.torch, self.target, builds, self.spec, self.targets)

    def dps_many(self, builds: list) -> list[float]:
        from sunken_sim.shadow import FIGHT

        want = os.environ.get("FARM_HYBRID_GPU_TIMELINE", "auto").strip().lower()
        use_gpu_tl = (
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
