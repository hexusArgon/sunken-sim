# -*- coding: utf-8 -*-
"""GPU kind/weight + optional GPU timeline for Feral Druid (primal / guardian / savage).

Set FARM_HYBRID_GPU_TIMELINE=0 to force CPU sunken_sim.feral_druid timelines.

Event: (when, name, weight, kind, pot_coeff=0)
  KIND_PHYS: (weight + potency*pot_coeff) * execute (phys/crit/taken baked in weight)
  KIND_MAG:  weight * magical_mult(codes, when, mastery) * execute
  KIND_EXEC: weight * execute
  KIND_FLAT: weight as-is
Execute baked at pack; MAG uses base+slope*M moments on GPU.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from farm.hybrid.engine import BatchFights
from farm.hybrid.lock import assert_gpu_allowed

MAX_BATCH = 512
KIND_PHYS = 0.0
KIND_MAG = 1.0
KIND_EXEC = 2.0
KIND_FLAT = 3.0
_PAD = -1.0
_KIND_IDS = (KIND_PHYS, KIND_MAG, KIND_EXEC, KIND_FLAT)

# columns: phys_w, mag_base_w, mag_slope_w, exec_w, flat_w
COLUMNS = (("phys_w",), ("mag_base_w",), ("mag_slope_w",), ("exec_w",), ("flat_w",))


@dataclass
class Timeline:
    build: object
    stats: dict
    spec: str
    events: list
    codes: frozenset


def timelines(build, targets: int, spec: str, *, gpu_bundle=None) -> list[Timeline]:
    from sunken_sim import feral_druid as mod
    from sunken_sim.shadow import _wears

    stats = mod.sheet(build, spec)
    if _wears(build, mod.DIAMOND):
        bounds = list(mod.buttons(spec))
    else:
        bounds = [None]

    best_tls: list[Timeline] = []
    best_total = -1.0
    for spell in bounds:
        if gpu_bundle is not None and (id(build), spell) in gpu_bundle:
            events, stats, codes = gpu_bundle[(id(build), spell)]
        else:
            key = mod._timeline_key(build, stats, spec, targets, spell)
            cached = mod._TIMELINE.get(key)
            if cached is None:
                if spell is None:
                    mod.simulate(build, targets, spec)
                else:
                    mod.simulate(build, targets, spec, mod.BOUND_NAME[spell])
                cached = mod._TIMELINE[key]
            events, _actions, _mana, codes = cached
        total = sum(mod.score_events(events, stats, codes).values())
        if total > best_total:
            best_total = total
            best_tls = [Timeline(build, stats, spec, events, codes)]
    return best_tls


_EVENT_CACHE: dict[int, tuple] = {}


def _event_arrays(events: list, stats: dict, codes: frozenset) -> tuple:
    from sunken_sim.shadow import _execute_factor, _magic_factors
    from sunken_sim import feral_druid as mod

    potency = float(stats["potency"])
    key = (id(events), potency)
    found = _EVENT_CACHE.get(key)
    if found is not None and found[0] is events:
        return found[1]

    n = len(events)
    kind = np.empty(n, dtype=np.float64)
    weight = np.empty(n, dtype=np.float64)
    slope = np.zeros(n, dtype=np.float64)
    when = np.empty(n, dtype=np.float64)
    for i, ev in enumerate(events):
        t, _name, w, k = ev[0], ev[1], ev[2], ev[3]
        pot_c = ev[4] if len(ev) > 4 else 0.0
        w = w + potency * pot_c
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
            base, sl = _magic_factors(codes, t)
            weight[i] = w * ex * base
            slope[i] = w * ex * sl
        else:
            raise ValueError(f"unknown feral kind {k}")
    arrays = (kind, weight, slope, when)
    _EVENT_CACHE[key] = (events, arrays)
    if len(_EVENT_CACHE) > 4000:
        _EVENT_CACHE.clear()
    return arrays


def pack(tls: list[Timeline]) -> dict:
    count = len(tls)
    width = max(1, max((len(tl.events) for tl in tls), default=1))
    kind = np.full((count, width), _PAD)
    weight = np.zeros((count, width))
    slope = np.zeros((count, width))
    for row, tl in enumerate(tls):
        k, w, s, _when = _event_arrays(tl.events, tl.stats, tl.codes)
        n = len(tl.events)
        kind[row, :n] = k
        weight[row, :n] = w
        slope[row, :n] = s
    return {"kind": kind, "weight": weight, "slope": slope}


def compile_sums(torch, target, packed: dict) -> np.ndarray:
    def up(name: str):
        return torch.from_numpy(np.ascontiguousarray(packed[name], dtype=np.float32)).to(target)

    kind, weight, slope = up("kind"), up("weight"), up("slope")
    feats = torch.stack([weight, slope], dim=2)
    ids = torch.tensor(_KIND_IDS, dtype=torch.float32, device=target)
    onehot = (kind.unsqueeze(-1) == ids).to(feats.dtype)
    moments = torch.bmm(onehot.transpose(1, 2), feats).cpu().numpy().astype(np.float64)
    out = np.zeros((moments.shape[0], len(COLUMNS)))
    out[:, 0] = moments[:, 0, 0]  # phys w
    out[:, 1] = moments[:, 1, 0]  # mag base (weight already * base)
    out[:, 2] = moments[:, 1, 1]  # mag slope channel
    out[:, 3] = moments[:, 2, 0]  # exec
    out[:, 4] = moments[:, 3, 0]  # flat
    return out


def score_row(tl: Timeline, row) -> float:
    mastery = float(tl.stats["mastery"])
    total = row[0]  # phys
    total += row[1] + mastery * row[2]  # mag
    total += row[3]  # exec
    total += row[4]  # flat
    return float(total)


class FeralDruidFights(BatchFights):
    def __init__(self, device, hero: str, spec: str, targets: int) -> None:
        import torch

        assert_gpu_allowed(hero, spec)
        if hero != "feral_druid" or spec not in ("primal", "guardian", "savage"):
            raise ValueError(f"{hero}/{spec}: no feral_druid GPU kernel")
        self.torch = torch
        self.device = device
        self.target = device.handle if device.gpu else torch.device("cpu")
        self.hero = hero
        self.spec = spec
        self.targets = int(targets)
        self.fights = 0

    def _scores(self, tls: list[Timeline]) -> list[float]:
        from sunken_sim.feral_druid import FIGHT

        out: list[float] = []
        for begin in range(0, len(tls), MAX_BATCH):
            part = tls[begin : begin + MAX_BATCH]
            sums = compile_sums(self.torch, self.target, pack(part))
            out.extend(score_row(tl, row) / FIGHT for tl, row in zip(part, sums))
        return out

    def _reuse_gpu_timelines(self, builds: list) -> dict:
        """Generate one GPU tape per timeline key; rescore potency per build."""
        from sunken_sim import feral_druid as mod
        from farm.hybrid.feral_gpu_timeline import generate_feral_timelines, _bound_keys_for

        pairs = []
        keys = []
        first = {}
        order = []
        for build in builds:
            stats = mod.sheet(build, self.spec)
            for bkey in _bound_keys_for(build, self.spec):
                key = mod._timeline_key(build, stats, self.spec, self.targets, bkey)
                pairs.append((build, bkey))
                keys.append(key)
                if key not in first:
                    first[key] = (build, bkey)
                    order.append(key)
        unique_builds = [first[k][0] for k in order]
        unique_bound = [first[k][1] for k in order]
        rows = generate_feral_timelines(
            self.torch, self.target, unique_builds, self.spec, self.targets, unique_bound
        )
        events_by_key = {key: row for key, row in zip(order, rows)}
        bundle = {}
        for (build, bkey), key in zip(pairs, keys):
            events, _rep_stats, _codes = events_by_key[key]
            stats = mod.sheet(build, self.spec)
            codes = frozenset(item.rawcode for item in build.items) | build.talents | build.glyphs
            bundle[(id(build), bkey)] = (events, stats, codes)
        return bundle

    def dps_many(self, builds: list) -> list[float]:
        import os

        gpu_bundle = None
        want = os.environ.get("FARM_HYBRID_GPU_TIMELINE", "auto").strip().lower()
        # The torch timeline (*_gpu_timeline.py) predates Battle Frenzy / Silent Messenger and the agility primary (2026-11-14): the timeline stays on the CPU sim.
        # The exact GPU route for this class is farm.hybrid.feral_druid_cl (OpenCL).
        use_gpu_tl = False and (
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
