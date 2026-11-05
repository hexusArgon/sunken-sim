# -*- coding: utf-8 -*-
"""GPU kind/weight compile for Druid (restoration / balance). DirectML.

Event shape from sunken_sim.druid.score_events:
  (when, name, raw, count, mastery_scale, attack, has_wisp, extra, special)
  special: None | "splash" | "echo" | "treant" | "sulfuras"

GPU moments: per kind sum(w), sum(w*t), sum(w*M), sum(w*extra).
Magical multiplier = A0 + A1*t + slope*M + ef*extra (see _magic_coeffs).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from farm.hybrid.engine import BatchFights
from farm.hybrid.lock import assert_gpu_allowed

MAX_BATCH = 512

KIND_PLAIN = 0.0
KIND_WISP = 1.0
KIND_SPLASH = 2.0
KIND_ECHO = 3.0
KIND_TREANT = 4.0
KIND_SULF = 5.0
_PAD = -1.0
_KIND_IDS = (KIND_PLAIN, KIND_WISP, KIND_SPLASH, KIND_ECHO, KIND_TREANT, KIND_SULF)

COLUMNS = (
    "plain_w", "plain_wt", "plain_wm", "plain_we",
    "wisp_w", "wisp_wt", "wisp_wm", "wisp_we",
    "sulf_w", "sulf_wt", "sulf_wm", "sulf_we",
    "splash_w", "echo_w", "treant_w",
)
COLUMN_INDEX = {n: i for i, n in enumerate(COLUMNS)}


@dataclass
class Timeline:
    build: object
    stats: dict
    codes: frozenset
    spec: str
    events: list
    taken_plain: float
    taken_wisp: float


def _bound_keys(build, spec: str):
    from sunken_sim import druid

    if druid._wears(build, druid.DIAMOND):
        return list(druid.buttons(spec))
    return [None]


def timelines(build, targets: int, spec: str) -> list[Timeline]:
    from sunken_sim import druid
    from sunken_sim.shadow import armor_taken, DUMMY_ARMOR

    stats = druid.sheet(build, spec)
    codes = frozenset(item.rawcode for item in build.items) | build.talents | build.glyphs
    pen = stats["armor_pen"]
    taken_plain = armor_taken(DUMMY_ARMOR - pen)
    taken_wisp = armor_taken(DUMMY_ARMOR - pen - druid.WISP_ARMOR)
    best_events = None
    best_total = -1.0
    for bound_key in _bound_keys(build, spec):
        key = druid._timeline_key(build, stats, spec, targets, bound_key)
        cached = druid._TIMELINE.get(key)
        if cached is None:
            druid._simulate_druid(build, targets, spec, bound_key)
            cached = druid._TIMELINE[key]
        events, _actions, _mana = cached
        sources = druid.score_events(events, stats, codes, taken_plain, taken_wisp)
        total = sum(sources.values())
        if total > best_total:
            best_total = total
            best_events = events
    if best_events is None:
        best_events = []
    return [Timeline(build, stats, codes, spec, best_events, taken_plain, taken_wisp)]


_EVENT_CACHE: dict[int, tuple] = {}


def _event_arrays(events: list, stats: dict) -> tuple:
    from sunken_sim.shadow import _execute_factor, _crit_factor

    key = id(events)
    found = _EVENT_CACHE.get(key)
    if found is not None and found[0] is events:
        return found[1]

    n = len(events)
    kind = np.empty(n, dtype=np.float64)
    weight = np.empty(n, dtype=np.float64)
    mastery = np.empty(n, dtype=np.float64)
    extra = np.empty(n, dtype=np.float64)
    when = np.empty(n, dtype=np.float64)
    for i, ev in enumerate(events):
        t_when, _name, raw, count, mastery_scale, attack, has_wisp, extr, special = ev
        when[i] = t_when
        mastery[i] = stats["mastery"]
        extra[i] = float(extr)
        execute = _execute_factor(stats, t_when)
        if special == "splash":
            kind[i] = KIND_SPLASH
            weight[i] = raw * count * execute
            extra[i] = 0.0
        elif special == "echo":
            kind[i] = KIND_ECHO
            weight[i] = raw * count * execute
            extra[i] = 0.0
        elif special == "treant":
            kind[i] = KIND_TREANT
            weight[i] = raw * count * execute
            extra[i] = 0.0
        elif special == "sulfuras":
            kind[i] = KIND_SULF
            w = raw * count * execute
            if stats["spell_crit"]:
                w *= _crit_factor(stats["crit"], stats["spell_mult"] + stats["rating"])
            weight[i] = w
            extra[i] = 0.0
        else:
            kind[i] = KIND_WISP if has_wisp else KIND_PLAIN
            w = (raw * mastery_scale + stats["potency"]) * count * execute
            if attack:
                w *= _crit_factor(stats["crit"], 2.0 + stats["rating"])
            elif stats["spell_crit"]:
                w *= _crit_factor(stats["crit"], stats["spell_mult"] + stats["rating"])
            weight[i] = w
    arrays = (kind, weight, mastery, extra, when)
    if len(_EVENT_CACHE) >= 16384:
        _EVENT_CACHE.clear()
    _EVENT_CACHE[key] = (events, arrays)
    return arrays


def pack(tls: list) -> dict:
    from sunken_sim.druid import FIGHT

    count = len(tls)
    width = max(1, max(len(tl.events) for tl in tls))
    kind = np.full((count, width), _PAD)
    weight = np.zeros((count, width))
    mastery = np.zeros((count, width))
    extra = np.zeros((count, width))
    thp = np.zeros((count, width))
    for row, tl in enumerate(tls):
        n = len(tl.events)
        if not n:
            continue
        k, w, m, e, when = _event_arrays(tl.events, tl.stats)
        kind[row, :n] = k
        weight[row, :n] = w
        mastery[row, :n] = m
        extra[row, :n] = e
        thp[row, :n] = np.maximum(0.0, 1.0 - when / FIGHT)
    return {"kind": kind, "weight": weight, "mastery": mastery, "extra": extra, "thp": thp}


def compile_sums(torch, target, packed: dict):
    def up(name):
        return torch.from_numpy(np.ascontiguousarray(packed[name], dtype=np.float32)).to(target)

    kind, weight, mastery, extra, thp = (
        up("kind"), up("weight"), up("mastery"), up("extra"), up("thp")
    )
    feats = torch.stack([weight, weight * thp, weight * mastery, weight * extra], dim=2)
    ids = torch.tensor(_KIND_IDS, dtype=torch.float32, device=target)
    onehot = (kind.unsqueeze(2) == ids.view(1, 1, -1)).to(torch.float32)
    moments = torch.bmm(onehot.transpose(1, 2), feats).cpu().numpy().astype(np.float64)
    out = np.zeros((moments.shape[0], len(COLUMNS)))
    out[:, 0:4] = moments[:, 0, :]
    out[:, 4:8] = moments[:, 1, :]
    out[:, 8:12] = moments[:, 5, :]
    out[:, 12] = moments[:, 2, 0]
    out[:, 13] = moments[:, 3, 0]
    out[:, 14] = moments[:, 4, 0]
    return out


def _magic_coeffs(codes: frozenset):
    from sunken_sim.shadow import MAGICAL_ADDS

    type_fixed = sum(amount for code, amount in MAGICAL_ADDS.items() if code in codes)
    has_sulf = "I0QT" in codes
    type_flat_sulf = 0.13 if has_sulf else 0.0
    type_thp = 0.25 if has_sulf else 0.0
    pre = 1.0 + type_fixed + type_flat_sulf
    slope = 0.0
    if "tlum" in codes:
        pre += 0.05
        slope = 0.005
    ins = 1.15 if "I0PU" in codes else 1.0
    cath = 0.30 if "I0PS" in codes else 0.0
    gls = 1.15 if "I0JA" in codes else 1.0
    a0 = gls * ins * pre
    a1 = gls * (ins * type_thp + cath)
    ef = gls * ins
    slope = slope * ins * gls
    return a0, a1, slope, ef


def score_row(tl: Timeline, row) -> float:
    c = lambda name: float(row[COLUMN_INDEX[name]])  # noqa: E731
    a0, a1, slope, ef = _magic_coeffs(tl.codes)

    def mag(prefix: str) -> float:
        return (
            a0 * c(f"{prefix}_w")
            + a1 * c(f"{prefix}_wt")
            + slope * c(f"{prefix}_wm")
            + ef * c(f"{prefix}_we")
        )

    total = 0.0
    total += tl.taken_plain * mag("plain")
    total += tl.taken_wisp * mag("wisp")
    total += tl.taken_plain * mag("sulf")
    total += tl.taken_plain * c("splash_w")
    total += tl.taken_plain * c("echo_w")
    total += tl.taken_plain * c("treant_w")
    return total


class DruidFights(BatchFights):
    def __init__(self, device, hero: str, spec: str, targets: int) -> None:
        import torch

        assert_gpu_allowed(hero, spec)
        if hero != "druid" or spec not in ("restoration", "balance"):
            raise ValueError(f"{hero}/{spec}: no druid GPU kernel")
        self.torch = torch
        self.device = device
        self.target = device.handle if device.gpu else torch.device("cpu")
        self.hero = hero
        self.spec = spec
        self.targets = int(targets)
        self.fights = 0

    def _scores(self, tls: list) -> list:
        from sunken_sim.druid import FIGHT

        out = []
        for begin in range(0, len(tls), MAX_BATCH):
            part = tls[begin : begin + MAX_BATCH]
            sums = compile_sums(self.torch, self.target, pack(part))
            out.extend(score_row(tl, row) / FIGHT for tl, row in zip(part, sums))
        return out

    def dps_many(self, builds: list) -> list:
        tls = []
        owner = []
        for index, build in enumerate(builds):
            for tl in timelines(build, self.targets, self.spec):
                tls.append(tl)
                owner.append(index)
        scores = self._scores(tls) if tls else []
        self.fights += len(builds)
        best = [None] * len(builds)
        for index, dps in zip(owner, scores):
            if best[index] is None or dps > best[index]:
                best[index] = dps
        return [float(v) for v in best]
