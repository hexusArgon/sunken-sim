# -*- coding: utf-8 -*-
"""siren: GPU kind/weight + optional GPU timeline.

Set FARM_HYBRID_GPU_TIMELINE=0 to force CPU sunken_sim.siren timelines.
Shared kind-score kernel: farm/hybrid/kindscore.py.
"""
from __future__ import annotations

import os

from farm.hybrid.kindscore import KindFights, MAX_BATCH, compile_sums, pack, timeline


class SirenFights(KindFights):
    MODULE = "siren"

    def _gpu_timelines(self, builds: list) -> list[tuple[list, dict]]:
        """Share fixed-policy tapes, then pick a winner per original build in f64."""
        from farm.hybrid.siren_gpu_timeline import generate_siren_timelines

        from sunken_sim.ledger import score_events
        from sunken_sim.shadow import FIGHT

        stats = [self.module.stats_of(b) for b in builds]
        plan, unique = [], {}
        for build, sheet in zip(builds, stats):
            row = []
            for policy in self.module.POLICIES:
                key = self.module._timeline_key(build, sheet, self.spec, self.targets, policy)
                unique.setdefault(key, (build, policy))
                row.append(key)
            plan.append(row)
        generated = generate_siren_timelines(
            self.torch, self.target, [b for b, _p in unique.values()], self.spec,
            self.targets, policies=[p for _b, p in unique.values()])
        tapes = dict(zip(unique, generated))
        rows = []
        for keys, sheet in zip(plan, stats):
            best, best_dps = None, None
            for key in keys:
                events, representative_stats = tapes[key]
                # Counters/policy annotations are fixed-policy state; overwrite
                # sheet values (notably potency) for this original build.
                row_stats = {**representative_stats, **sheet}
                dps = sum(score_events(events, row_stats).values()) / FIGHT
                if best is None or dps > best_dps + 1e-9:
                    best, best_dps = (events, row_stats), dps
            rows.append(best)
        return rows

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
