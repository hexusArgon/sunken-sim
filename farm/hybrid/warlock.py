# -*- coding: utf-8 -*-
"""GPU kind/weight compile + timeline for Warlock (demonology / destruction / affliction).

Timeline: farm.hybrid.warlock_gpu_timeline (pending+choose+demons, f64 CPU clocks).
Set FARM_HYBRID_GPU_TIMELINE=0 to force CPU sunken_sim.warlock timelines.
Event shape from sunken_sim.warlock.score_events:
  (when, name, weight, kind, pot_coeff=0)
    KIND_HERO_MAG / KIND_HERO_PHYS: (weight + potency*pot_coeff) * typed(thp, mastery) * execute
    KIND_EXEC: (weight + potency*pot_coeff) * execute
    KIND_FLAT: weight + potency*pot_coeff
Execute baked into weight at pack; GPU kind-score then score_row.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from farm.hybrid.engine import BatchFights
from farm.hybrid.lock import assert_gpu_allowed

MAX_BATCH = 512

KIND_HERO_MAG = 0.0
KIND_HERO_PHYS = 1.0
KIND_EXEC = 2.0
KIND_FLAT = 3.0
_PAD = -1.0

_KIND_IDS = (KIND_HERO_MAG, KIND_HERO_PHYS, KIND_EXEC, KIND_FLAT)

COLUMNS = (
    ("mag_w",),
    ("mag_wt",),
    ("mag_wm",),
    ("phys_w",),
    ("phys_wt",),
    ("phys_wm",),
    ("exec_w",),
    ("flat_w",),
)


@dataclass
class Timeline:
    build: object
    stats: dict
    spec: str
    events: list


def _policies_for(spec: str, targets: int):
    from sunken_sim import warlock

    for policy in warlock.POLICIES:
        if spec != "affliction" and not policy[2]:
            continue
        if targets == 1 and policy[0] == "spread":
            continue
        yield policy


def timelines(build, targets: int, spec: str, *, gpu_bundle=None) -> list[Timeline]:
    from sunken_sim import warlock

    stats = warlock.stats_of(build)
    best_events = None
    best_total = -1.0
    for policy in _policies_for(spec, targets):
        if gpu_bundle is not None and (id(build), policy) in gpu_bundle:
            events, stats = gpu_bundle[(id(build), policy)]
        else:
            key = warlock._timeline_key(build, stats, spec, targets, policy)
            cached = warlock._TIMELINE.get(key)
            if cached is None:
                warlock._simulate(build, targets, spec, policy)
                cached = warlock._TIMELINE[key]
            events, _actions, _mana = cached
        sources = warlock.score_events(events, stats)
        total = sum(sources.values())
        if total > best_total:
            best_total = total
            best_events = events
    if best_events is None:
        best_events = []
    return [Timeline(build, stats, spec, best_events)]


_EVENT_CACHE: dict[int, tuple] = {}


def _event_arrays(events: list, stats: dict) -> tuple:
    from sunken_sim.shadow import _execute_factor
    from sunken_sim import warlock

    potency = float(stats["potency"])
    key = (id(events), potency)
    found = _EVENT_CACHE.get(key)
    if found is not None and found[0] is events:
        return found[1]

    n = len(events)
    kind = np.empty(n, dtype=np.float64)
    weight = np.empty(n, dtype=np.float64)
    mastery = np.empty(n, dtype=np.float64)
    when = np.empty(n, dtype=np.float64)
    mstat = float(stats["mastery"])

    for i, ev in enumerate(events):
        t, _name, w, k = ev[0], ev[1], ev[2], ev[3]
        pot_c = ev[4] if len(ev) > 4 else 0.0
        w = w + potency * pot_c
        when[i] = t
        mastery[i] = mstat
        ex = _execute_factor(stats, t)
        if k == warlock.KIND_FLAT or k == KIND_FLAT:
            kind[i] = KIND_FLAT
            weight[i] = w
        elif k == warlock.KIND_EXEC or k == KIND_EXEC:
            kind[i] = KIND_EXEC
            weight[i] = w * ex
        elif k == warlock.KIND_HERO_MAG or k == KIND_HERO_MAG:
            kind[i] = KIND_HERO_MAG
            weight[i] = w * ex
        elif k == warlock.KIND_HERO_PHYS or k == KIND_HERO_PHYS:
            kind[i] = KIND_HERO_PHYS
            weight[i] = w * ex
        else:
            raise ValueError(f"unknown warlock kind {k}")
    arrays = (kind, weight, mastery, when)
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
    mastery = np.zeros((count, width))
    thp = np.zeros((count, width))
    for row, tl in enumerate(tls):
        k, w, m, when = _event_arrays(tl.events, tl.stats)
        n = len(tl.events)
        kind[row, :n] = k
        weight[row, :n] = w
        mastery[row, :n] = m
        thp[row, :n] = np.array([target_hp(t) for t in when], dtype=np.float64)
    return {"kind": kind, "weight": weight, "mastery": mastery, "thp": thp}


def compile_sums(torch, target, packed: dict) -> np.ndarray:
    def up(name: str):
        return torch.from_numpy(np.ascontiguousarray(packed[name], dtype=np.float32)).to(target)

    kind, weight, mastery, thp = up("kind"), up("weight"), up("mastery"), up("thp")
    feats = torch.stack([weight, weight * thp, weight * mastery], dim=2)
    ids = torch.tensor(_KIND_IDS, dtype=torch.float32, device=target)
    onehot = (kind.unsqueeze(-1) == ids).to(feats.dtype)
    moments = torch.bmm(onehot.transpose(1, 2), feats).cpu().numpy().astype(np.float64)
    out = np.zeros((moments.shape[0], len(COLUMNS)))
    # mag: kinds[0] -> w,wt,wm
    out[:, 0:3] = moments[:, 0, :]
    # phys: kinds[1]
    out[:, 3:6] = moments[:, 1, :]
    # exec: kinds[2] only w
    out[:, 6] = moments[:, 2, 0]
    # flat: kinds[3] only w
    out[:, 7] = moments[:, 3, 0]
    return out


def _typed_coeffs(stats: dict, magical: bool) -> tuple[float, float, float, float]:
    """Return (a0, a1, slope, glass) for typed = glass * (a0 + a1*thp + slope*M)."""
    a0 = 1.0 + (stats["magic_add"] if magical else stats["phys_add"])
    a1 = 0.0
    slope = 0.0
    if stats["sulfuron"]:
        a0 += 0.13
        a1 += 0.25
    if magical and stats["spellbinder"]:
        a0 += 0.05
        slope += 0.005
    glass = 1.15 if stats["glass"] else 1.0
    return a0, a1, slope, glass


def score_row(tl: Timeline, row: np.ndarray) -> float:
    a0m, a1m, sm, gm = _typed_coeffs(tl.stats, True)
    a0p, a1p, sp, gp = _typed_coeffs(tl.stats, False)
    total = 0.0
    # mag
    total += gm * (a0m * row[0] + a1m * row[1] + sm * row[2])
    # phys
    total += gp * (a0p * row[3] + a1p * row[4] + sp * row[5])
    # exec + flat
    total += row[6] + row[7]
    return float(total)


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

    def _reuse_gpu_timelines(self, builds: list) -> dict:
        """Generate one GPU tape per timeline key; rescore potency per build."""
        from sunken_sim import warlock as mod
        from farm.hybrid.warlock_gpu_timeline import generate_warlock_timelines, _policies_for

        pairs = []
        keys = []
        first = {}
        order = []
        for build in builds:
            stats = mod.stats_of(build)
            for policy in _policies_for(self.spec, self.targets):
                key = mod._timeline_key(build, stats, self.spec, self.targets, policy)
                pairs.append((build, policy))
                keys.append(key)
                if key not in first:
                    first[key] = (build, policy)
                    order.append(key)
        unique_builds = [first[k][0] for k in order]
        unique_pols = [first[k][1] for k in order]
        rows = generate_warlock_timelines(
            self.torch, self.target, unique_builds, self.spec, self.targets, unique_pols
        )
        events_by_key = {key: row for key, row in zip(order, rows)}
        bundle = {}
        for (build, policy), key in zip(pairs, keys):
            events, _rep_stats = events_by_key[key]
            stats = mod.stats_of(build)
            bundle[(id(build), policy)] = (events, stats)
        return bundle

    def dps_many(self, builds: list) -> list[float]:
        import os

        gpu_bundle = None
        want = os.environ.get("FARM_HYBRID_GPU_TIMELINE", "auto").strip().lower()
        use_gpu_tl = (
            want not in ("0", "false", "off", "cpu")
            and (want in ("1", "true", "force") or bool(getattr(self.device, "gpu", False)))
        )
        if use_gpu_tl and builds:
            gpu_bundle = self._reuse_gpu_timelines(builds)
        tls: list[Timeline] = []
        owner: list[int] = []
        for index, build in enumerate(builds):
            for tl in timelines(build, self.targets, self.spec, gpu_bundle=gpu_bundle):
                tls.append(tl)
                owner.append(index)
        scores = self._scores(tls) if tls else []
        self.fights += len(builds)
        best: list[float | None] = [None] * len(builds)
        for index, dps in zip(owner, scores):
            if best[index] is None or dps > best[index]:
                best[index] = dps
        return [float(v) for v in best]
