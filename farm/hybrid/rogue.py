# -*- coding: utf-8 -*-
"""GPU kind/weight compile for Rogue. DirectML.

Event: (when, name, weight, kind)
  KIND_PHYS / KIND_EXEC / KIND_MAG / KIND_FLAT
Execute baked at pack; GPU moments sum(w), sum(w*thp) for PHYS.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from farm.hybrid.engine import BatchFights
from farm.hybrid.lock import assert_gpu_allowed

MAX_BATCH = 512
KIND_PHYS = 0.0
KIND_EXEC = 1.0
KIND_MAG = 2.0
KIND_FLAT = 3.0
_PAD = -1.0
_KIND_IDS = (KIND_PHYS, KIND_EXEC, KIND_MAG, KIND_FLAT)

COLUMNS = (("phys_w",), ("phys_wt",), ("exec_w",), ("mag_w",), ("flat_w",))


@dataclass
class Timeline:
    build: object
    stats: dict
    spec: str
    events: list


def timelines(build, targets: int, spec: str) -> list[Timeline]:
    from sunken_sim import rogue as mod

    stats = mod.stats_of(build)
    key = mod._timeline_key(build, stats, spec, targets)
    cached = mod._TIMELINE.get(key)
    if cached is None:
        mod.simulate(build, targets, spec)
        cached = mod._TIMELINE[key]
    events, _actions, _mana = cached
    return [Timeline(build, stats, spec, events)]


_EVENT_CACHE: dict[int, tuple] = {}


def _event_arrays(events: list, stats: dict) -> tuple:
    from sunken_sim.shadow import _execute_factor
    from sunken_sim import rogue as mod

    key = id(events)
    found = _EVENT_CACHE.get(key)
    if found is not None and found[0] is events:
        return found[1]

    n = len(events)
    kind = np.empty(n, dtype=np.float64)
    weight = np.empty(n, dtype=np.float64)
    when = np.empty(n, dtype=np.float64)
    for i, ev in enumerate(events):
        t, _name, w, k = ev
        when[i] = t
        ex = _execute_factor(stats, t)
        if k in (mod.KIND_FLAT, KIND_FLAT):
            kind[i] = KIND_FLAT
            weight[i] = w
        elif k in (mod.KIND_EXEC, KIND_EXEC):
            kind[i] = KIND_EXEC
            weight[i] = w * ex
        elif k in (mod.KIND_PHYS, KIND_PHYS):
            kind[i] = KIND_PHYS
            weight[i] = w * ex
        elif k in (mod.KIND_MAG, KIND_MAG):
            kind[i] = KIND_MAG
            weight[i] = w * ex
        else:
            raise ValueError(f"unknown rogue kind {k}")
    arrays = (kind, weight, when)
    _EVENT_CACHE[key] = (events, arrays)
    if len(_EVENT_CACHE) > 4000:
        _EVENT_CACHE.clear()
    return arrays


def pack(tls: list[Timeline]) -> dict:
    from sunken_sim.shadow import target_hp

    count = len(tls)
    width = max(1, max((len(tl.events) for tl in tls), default=1))
    kind = np.full((count, width), _PAD)
    weight = np.zeros((count, width))
    thp = np.zeros((count, width))
    for row, tl in enumerate(tls):
        k, w, when = _event_arrays(tl.events, tl.stats)
        n = len(tl.events)
        kind[row, :n] = k
        weight[row, :n] = w
        thp[row, :n] = np.array([target_hp(t) for t in when], dtype=np.float64)
    return {"kind": kind, "weight": weight, "thp": thp}


def compile_sums(torch, target, packed: dict) -> np.ndarray:
    def up(name: str):
        return torch.from_numpy(np.ascontiguousarray(packed[name], dtype=np.float32)).to(target)

    kind, weight, thp = up("kind"), up("weight"), up("thp")
    feats = torch.stack([weight, weight * thp], dim=2)
    ids = torch.tensor(_KIND_IDS, dtype=torch.float32, device=target)
    onehot = (kind.unsqueeze(-1) == ids).to(feats.dtype)
    moments = torch.bmm(onehot.transpose(1, 2), feats).cpu().numpy().astype(np.float64)
    out = np.zeros((moments.shape[0], len(COLUMNS)))
    out[:, 0] = moments[:, 0, 0]  # phys w
    out[:, 1] = moments[:, 0, 1]  # phys wt
    out[:, 2] = moments[:, 1, 0]  # exec w
    out[:, 3] = moments[:, 2, 0]  # mag w
    out[:, 4] = moments[:, 3, 0]  # flat w
    return out


def _phys_coeffs(stats: dict, spec: str = "") -> tuple[float, float, float]:
    """a0, a1, glass for physical = glass * (a0 + a1*thp)."""
    strike = 0.15 if (spec == "subtlety") else 0.0
    a0 = 1.0 + stats["phys_add"] + strike
    a1 = 0.0
    if stats["sulfuron"]:
        a0 += 0.13
        a1 += 0.25
    glass = 1.15 if stats["glass"] else 1.0
    return a0, a1, glass


def score_row(tl: Timeline, row) -> float:
    a0, a1, glass = _phys_coeffs(tl.stats, tl.spec)
    mag = (1.0 + tl.stats["magic_add"]) * (1.15 if tl.stats["glass"] else 1.0)
    total = glass * (a0 * row[0] + a1 * row[1])  # phys w, wt
    total += row[2]  # exec
    total += mag * row[3]  # mag (execute already in weight)
    total += row[4]  # flat
    return float(total)


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
