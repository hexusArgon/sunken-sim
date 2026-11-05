# -*- coding: utf-8 -*-
"""GPU compile stage for Rogue (subtlety / combat). DirectML.

Rogue timelines are flat pre-scored (name, amount) events from sunken_sim.rogue.
GPU path batches sum(amount)/FIGHT; CPU still builds the timelines.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from farm.hybrid.engine import BatchFights
from farm.hybrid.lock import assert_gpu_allowed

MAX_BATCH = 512


@dataclass
class Timeline:
    build: object
    stats: dict
    spec: str
    events: list[tuple[str, float]]


def timelines(build, targets: int, spec: str) -> list[Timeline]:
    from sunken_sim import rogue

    stats = rogue.stats_of(build)
    key = rogue._timeline_key(build, stats, spec, targets)
    cached = rogue._TIMELINE.get(key)
    if cached is None:
        rogue.simulate(build, targets, spec)
        cached = rogue._TIMELINE[key]
    events, _actions, _mana = cached
    return [Timeline(build, stats, spec, events)]


def pack(tls: list[Timeline]) -> dict:
    count = len(tls)
    width = max(1, max(len(tl.events) for tl in tls))
    weight = np.zeros((count, width), dtype=np.float64)
    mask = np.zeros((count, width), dtype=np.float64)
    for row, tl in enumerate(tls):
        for i, (_name, amount) in enumerate(tl.events):
            weight[row, i] = amount
            mask[row, i] = 1.0
    return {"weight": weight, "mask": mask}


def compile_sums(torch, target, packed: dict) -> np.ndarray:
    weight = torch.from_numpy(np.ascontiguousarray(packed["weight"], dtype=np.float32)).to(target)
    mask = torch.from_numpy(np.ascontiguousarray(packed["mask"], dtype=np.float32)).to(target)
    totals = (weight * mask).sum(dim=1)
    return totals.detach().cpu().numpy().astype(np.float64).reshape(-1, 1)


def score_row(tl: Timeline, row: np.ndarray) -> float:
    return float(row[0])


class RogueFights(BatchFights):
    def __init__(self, device, hero: str, spec: str, targets: int) -> None:
        import torch

        assert_gpu_allowed(hero, spec)
        if hero != "rogue" or spec not in ("subtlety", "combat"):
            raise ValueError(f"{hero}/{spec}: no rogue GPU kernel")
        self.torch = torch
        self.device = device
        self.target = device.handle if device.gpu else torch.device("cpu")
        self.hero = hero
        self.spec = spec
        self.targets = int(targets)
        self.fights = 0

    def _scores(self, tls: list[Timeline]) -> list[float]:
        from sunken_sim.rogue import FIGHT

        out: list[float] = []
        for begin in range(0, len(tls), MAX_BATCH):
            part = tls[begin : begin + MAX_BATCH]
            sums = compile_sums(self.torch, self.target, pack(part))
            out.extend(score_row(tl, row) / FIGHT for tl, row in zip(part, sums))
        return out

    def dps_many(self, builds: list) -> list[float]:
        tls: list[Timeline] = []
        owner: list[int] = []
        for index, build in enumerate(builds):
            for tl in timelines(build, self.targets, self.spec):
                tls.append(tl)
                owner.append(index)
        scores = self._scores(tls) if tls else []
        self.fights += len(builds)
        best: list[float | None] = [None] * len(builds)
        for index, dps in zip(owner, scores):
            if best[index] is None or dps > best[index]:
                best[index] = dps
        return [float(v) for v in best]
