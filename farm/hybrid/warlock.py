# -*- coding: utf-8 -*-
"""GPU compile stage for Warlock (demonology / destruction / affliction). DirectML.

Warlock timelines are flat pre-scored (name, amount) events from sunken_sim.warlock.
GPU path batches sum(amount)/FIGHT; CPU still builds the policy timelines.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from farm.hybrid.engine import BatchFights
from farm.hybrid.lock import assert_gpu_allowed

MAX_BATCH = 512
_PAD = -1.0


@dataclass
class Timeline:
    build: object
    stats: dict
    spec: str
    events: list[tuple[str, float]]


def _policies_for(spec: str, targets: int):
    from sunken_sim import warlock

    for policy in warlock.POLICIES:
        if spec != "affliction" and not policy[2]:
            continue
        if targets == 1 and policy[0] == "spread":
            continue
        yield policy


def timelines(build, targets: int, spec: str) -> list[Timeline]:
    from sunken_sim import warlock

    stats = warlock.stats_of(build)
    best_events = None
    best_total = -1.0
    for policy in _policies_for(spec, targets):
        key = warlock._timeline_key(build, stats, spec, targets, policy)
        cached = warlock._TIMELINE.get(key)
        if cached is None:
            warlock._simulate(build, targets, spec, policy)
            cached = warlock._TIMELINE[key]
        events, _actions, _mana = cached
        total = sum(amount for _n, amount in events)
        if total > best_total:
            best_total = total
            best_events = events
    if best_events is None:
        best_events = []
    return [Timeline(build, stats, spec, best_events)]


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


class WarlockFights(BatchFights):
    def __init__(self, device, hero: str, spec: str, targets: int) -> None:
        import torch

        assert_gpu_allowed(hero, spec)
        if hero != "warlock" or spec not in ("demonology", "destruction", "affliction"):
            raise ValueError(f"{hero}/{spec}: no warlock GPU kernel")
        self.torch = torch
        self.device = device
        self.target = device.handle if device.gpu else torch.device("cpu")
        self.hero = hero
        self.spec = spec
        self.targets = int(targets)
        self.fights = 0

    def _scores(self, tls: list[Timeline]) -> list[float]:
        from sunken_sim.warlock import FIGHT

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
