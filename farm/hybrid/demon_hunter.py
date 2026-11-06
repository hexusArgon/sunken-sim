# -*- coding: utf-8 -*-
"""demon_hunter (havoc, vengeance, devourer): GPU kind/weight + optional GPU timeline.

Set FARM_HYBRID_GPU_TIMELINE=0 to force CPU sunken_sim.demon_hunter timelines.
Shared kind-score kernel: farm/hybrid/kindscore.py.
"""
from __future__ import annotations

import os

from farm.hybrid.kindscore import KindFights, MAX_BATCH, compile_sums, pack, timeline


class DemonHunterFights(KindFights):
    MODULE = "demon_hunter"

    def _gpu_timelines(self, builds: list) -> list[tuple[list, dict]]:
        """Generate one tape per safe key; preserve row order and each row's stats."""
        from farm.hybrid.demon_hunter_gpu_timeline import generate_demon_hunter_timelines

        stats = [self.module.stats_of(b) for b in builds]
        keys = [self.module._timeline_key(b, s, self.spec, self.targets)
                for b, s in zip(builds, stats)]
        unique = {}
        for key, build in zip(keys, builds):
            unique.setdefault(key, build)
        generated = generate_demon_hunter_timelines(
            self.torch, self.target, list(unique.values()), self.spec, self.targets)
        tapes = {key: events for key, (events, _stats) in zip(unique, generated)}
        return [(tapes[key], s) for key, s in zip(keys, stats)]

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
