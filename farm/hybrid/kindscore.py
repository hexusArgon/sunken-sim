# -*- coding: utf-8 -*-
"""GPU kind/weight compile for the Ledger-based class sims (sunken_sim/ledger.py).

Heroes: berserker, death_knight, demon_hunter, dragon_sentinel, monk, necromancer,
siren, tidewarrior, tinker, windmaster, witch_doctor. Per-hero files in
farm/hybrid/<hero>.py only name the module.

CPU: module simulate() (its own policy pick) -> report.events (when, name, weight, kind).
Pack: optional pot_coeff adds potency * pot_coeff to weight first;
KIND_EXEC then multiplies execute(when), KIND_FLAT remains as-is.
GPU (DirectML): one-hot(kind) x [weight] bmm -> per-kind moments; CPU sums / FIGHT.
CPU reference: sunken_sim.ledger.score_events.
"""

from __future__ import annotations

import importlib

import numpy as np

from farm.hybrid.engine import BatchFights
from farm.hybrid.lock import assert_gpu_allowed

MAX_BATCH = 512
_PAD = -1.0


def _kinds():
    from sunken_sim.ledger import KIND_EXEC, KIND_FLAT

    return (KIND_EXEC, KIND_FLAT)


def timeline(module, build, targets: int, spec: str) -> tuple[list, dict]:
    report = module.simulate(build, targets, spec)
    events = getattr(report, "events", None)
    if events is None:
        raise ValueError(f"{module.__name__}: simulate() has no ledger events")
    return events, report.stats


def pack(rows: list[tuple[list, dict]]) -> dict:
    from sunken_sim.ledger import KIND_EXEC
    from sunken_sim.shadow import _execute_factor

    count = len(rows)
    width = max(1, max((len(ev) for ev, _ in rows), default=1))
    kind = np.full((count, width), _PAD)
    weight = np.zeros((count, width))
    for r, (events, stats) in enumerate(rows):
        cache: dict[float, float] = {}
        for i, ev in enumerate(events):
            when, _name, w, k = ev[:4]
            if len(ev) > 4:
                w = w + stats.get("potency", 0.0) * ev[4]
            kind[r, i] = k
            if k == KIND_EXEC:
                ex = cache.get(when)
                if ex is None:
                    ex = cache[when] = _execute_factor(stats, when)
                weight[r, i] = w * ex
            else:
                weight[r, i] = w
    return {"kind": kind, "weight": weight}


def compile_sums(torch, target, packed: dict) -> np.ndarray:
    kind = torch.from_numpy(np.ascontiguousarray(packed["kind"], dtype=np.float32)).to(target)
    weight = torch.from_numpy(np.ascontiguousarray(packed["weight"], dtype=np.float32)).to(target)
    ids = torch.tensor(_kinds(), dtype=torch.float32, device=target)
    onehot = (kind.unsqueeze(-1) == ids).to(weight.dtype)
    moments = torch.bmm(onehot.transpose(1, 2), weight.unsqueeze(-1))
    return moments.squeeze(-1).cpu().numpy().astype(np.float64)  # [batch, (exec, flat)]


class KindFights(BatchFights):
    MODULE = ""

    def __init__(self, device, hero: str, spec: str, targets: int) -> None:
        import torch

        assert_gpu_allowed(hero, spec)
        self.module = importlib.import_module(f"sunken_sim.{self.MODULE}")
        if hero != self.MODULE or spec not in self.module.SPECS:
            raise ValueError(f"{hero}/{spec}: no {self.MODULE} GPU kernel")
        self.torch = torch
        self.device = device
        self.target = device.handle if device.gpu else torch.device("cpu")
        self.hero = hero
        self.spec = spec
        self.targets = int(targets)
        self.fights = 0

    def dps_many(self, builds: list) -> list[float]:
        from sunken_sim.shadow import FIGHT

        rows = [timeline(self.module, b, self.targets, self.spec) for b in builds]
        out: list[float] = []
        for begin in range(0, len(rows), MAX_BATCH):
            part = rows[begin : begin + MAX_BATCH]
            sums = compile_sums(self.torch, self.target, pack(part))
            out.extend(float(row.sum()) / FIGHT for row in sums)
        self.fights += len(builds)
        return out
