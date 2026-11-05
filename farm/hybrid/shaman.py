# -*- coding: utf-8 -*-
"""GPU timeline (elemental) + kind-score compile for Shaman. DirectML.

Elemental timeline: farm.hybrid.shaman_gpu_timeline (batched pending+choose).
Restoration / Enhancement stay CPU events_for until spirit slots pass parity.
Set FARM_HYBRID_GPU_TIMELINE=0 to force CPU timeline for elemental too.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from farm.hybrid.engine import BatchFights
from farm.hybrid.lock import assert_gpu_allowed

MAX_BATCH = 512

# kinds: 0 deal-magic, 1 deal-attack, 2 splash, 3 echo, 4 spirit
K_MAGIC, K_ATTACK, K_SPLASH, K_ECHO, K_SPIRIT = 0.0, 1.0, 2.0, 3.0, 4.0
_PAD = -1.0

COLUMNS = (
    ("mag_w", 0),
    ("mag_wt", 1),
    ("mag_wm", 2),  # w * mastery
    ("atk_w", 3),
    ("atk_wt", 4),
    ("atk_wm", 5),
    ("splash_w", 6),
    ("echo_w", 7),
    ("spirit_w", 8),
    ("spirit_wf", 9),  # spirit with fusion already applied in weight
)
COLUMN_INDEX = {n: i for i, (n, _) in enumerate(COLUMNS)}


@dataclass
class Timeline:
    build: object
    stats: dict
    codes: frozenset
    spec: str
    events: list
    taken: float


def timelines(build, targets: int, spec: str, *, gpu_bundle=None) -> list[Timeline]:
    """CPU timeline (events_for), or events from a GPU timeline batch bundle.

    gpu_bundle: optional dict (id(build), bound_key) -> (events, stats, codes, taken)
    produced by farm.hybrid.shaman_gpu_timeline.generate_shaman_timelines.
    bound_key is None or a buttons() key (chain/shield/lava/totem/spirit).
    """
    from sunken_sim import shaman

    if shaman._wears(build, shaman.DIAMOND):
        bound_pairs = [(k, shaman.BOUND_NAME[k]) for k in shaman.buttons(spec)]
    else:
        bound_pairs = [(None, None)]
    out = []
    for bkey, bound in bound_pairs:
        if gpu_bundle is not None and (id(build), bkey) in gpu_bundle:
            events, stats, codes, taken = gpu_bundle[(id(build), bkey)]
            out.append(Timeline(build, stats, codes, spec, events, taken))
            continue
        events, _actions, _mana, stats, codes, taken, _bk, _rep = shaman.events_for(
            build, targets, spec, bound
        )
        out.append(Timeline(build, stats, codes, spec, events, taken))
    return out


_EVENT_CACHE: dict[int, tuple] = {}


def _event_arrays(events: list, stats: dict) -> tuple:
    from sunken_sim.shadow import _execute_factor, FIGHT

    key = id(events)
    found = _EVENT_CACHE.get(key)
    if found is not None and found[0] is events:
        return found[1]

    n = len(events)
    kind = np.empty(n)
    weight = np.empty(n)
    mastery = np.empty(n)
    when = np.empty(n)
    fusion = np.zeros(n)  # only for bookkeeping; fusion baked into weight for deal

    for i, ev in enumerate(events):
        k0 = ev[0]
        if k0 == "splash":
            _, _name, raw, now, count = ev
            kind[i] = K_SPLASH
            weight[i] = raw * count * _execute_factor(stats, now)
            mastery[i] = 0.0
            when[i] = now
        elif k0 == "echo":
            _, _name, raw, now = ev
            kind[i] = K_ECHO
            weight[i] = raw * _execute_factor(stats, now)
            mastery[i] = 0.0
            when[i] = now
        elif k0 == "spirit":
            _, _name, hit, now, crit, fus = ev
            from sunken_sim.shadow import _crit_factor

            kind[i] = K_SPIRIT
            w = hit * _crit_factor(crit, 2.0) * _execute_factor(stats, now)
            if fus:
                w *= 1.25
            weight[i] = w
            mastery[i] = 0.0
            when[i] = now
        else:
            _, _name, raw, now, count, attack, magical, mast, crit, fus, auto_scale = ev
            from sunken_sim.shadow import _crit_factor

            execute = _execute_factor(stats, now)
            w = (raw + stats["potency"]) * count * execute
            if attack:
                w *= _crit_factor(crit, 2.0 + stats["rating"])
                kind[i] = K_ATTACK
            else:
                if stats["spell_crit"]:
                    w *= _crit_factor(crit, stats["spell_mult"] + stats["rating"])
                kind[i] = K_MAGIC
            if fus:
                w *= 1.25
            if auto_scale:
                w *= stats["auto_pct"]
            # magical multiplier applied in score_row via moments; attacks still use magical path in shaman (Автоатака is magical=True!)
            # deal(..., attack=True, magical=True) for auto — both crit attack AND magical mult!
            # Looking at original deal: if magical: * magical_mult; if attack: * attack_crit elif spell_crit: * spell_crit
            # So auto gets magical_mult AND attack_crit. Our kind K_ATTACK still needs magical moments.
            weight[i] = w
            mastery[i] = mast if magical else 0.0
            when[i] = now
            # mark non-magical deal (shouldn't happen often)
            if not magical:
                # physical-only: no magical_multiplier — use echo-like path via weight final
                # bake as splash-equivalent (already has crit/fusion/exec in w, need *taken only)
                kind[i] = K_SPLASH  # taken-only at score; weight already has everything except taken
                # Wait: splash score is taken * weight. Good if w has all else.
                # But we already put crit/fusion in w. For non-magical, original had NO magical_mult. OK.

    arrays = (kind, weight, mastery, when)
    if len(_EVENT_CACHE) >= 16384:
        _EVENT_CACHE.clear()
    _EVENT_CACHE[key] = (events, arrays)
    return arrays


def pack(tls: list[Timeline]) -> dict:
    from sunken_sim.shaman import FIGHT

    count = len(tls)
    width = max(1, max(len(tl.events) for tl in tls))
    kind = np.full((count, width), _PAD)
    weight = np.zeros((count, width))
    mastery = np.zeros((count, width))
    thp = np.zeros((count, width))
    for row, tl in enumerate(tls):
        n = len(tl.events)
        if not n:
            continue
        k, w, m, when = _event_arrays(tl.events, tl.stats)
        kind[row, :n] = k
        weight[row, :n] = w
        mastery[row, :n] = m
        thp[row, :n] = np.maximum(0.0, 1.0 - when / FIGHT)
    return {"kind": kind, "weight": weight, "mastery": mastery, "thp": thp}


def compile_sums(torch, target, packed: dict) -> np.ndarray:
    def up(name):
        return torch.from_numpy(np.ascontiguousarray(packed[name], dtype=np.float32)).to(target)

    kind, weight, mastery, thp = up("kind"), up("weight"), up("mastery"), up("thp")
    # For magic/attack: need w, w*t, w*M where magical_mult = base(t) + slope*M
    # base(t) = a0 + a1*t (from _magic_factors). Moments: sum(w), sum(w*t), sum(w*M)
    feats = torch.stack([weight, weight * thp, weight * mastery], dim=2)
    ids = torch.tensor([K_MAGIC, K_ATTACK, K_SPLASH, K_ECHO, K_SPIRIT], dtype=torch.float32, device=target)
    onehot = (kind.unsqueeze(2) == ids.view(1, 1, -1)).to(torch.float32)
    moments = torch.bmm(onehot.transpose(1, 2), feats).cpu().numpy().astype(np.float64)  # [B,5,3]
    out = np.zeros((moments.shape[0], len(COLUMNS)))
    # mag: kinds 0
    out[:, 0] = moments[:, 0, 0]
    out[:, 1] = moments[:, 0, 1]
    out[:, 2] = moments[:, 0, 2]
    # atk: kinds 1 — also need magical_mult (auto is magical)
    out[:, 3] = moments[:, 1, 0]
    out[:, 4] = moments[:, 1, 1]
    out[:, 5] = moments[:, 1, 2]
    out[:, 6] = moments[:, 2, 0]  # splash
    out[:, 7] = moments[:, 3, 0]  # echo
    out[:, 8] = moments[:, 4, 0]  # spirit (fusion already in weight)
    return out


def score_row(tl: Timeline, row: np.ndarray) -> float:
    from sunken_sim.shadow import _magic_factors, target_hp

    s = tl.stats
    codes = tl.codes
    c = lambda name: float(row[COLUMN_INDEX[name]])  # noqa: E731
    taken = tl.taken

    # _magic_factors(codes, time) returns (base, slope) where base includes time-dependent Catharsis.
    # base(t) = a0 + a1*t approximately: compute at t=0 and t=1.
    base0, slope = _magic_factors(codes, 0.0)
    base1, slope1 = _magic_factors(codes, 1.0)  # time at fight start hp=1? target_hp(0)=1
    # Actually _magic_factors uses target_hp(time), time=0 -> hp=1, time=FIGHT -> hp=0
    # So base_at_hp1 = _magic_factors(codes, 0)[0], base_at_hp0 = _magic_factors(codes, FIGHT)[0]
    from sunken_sim.shaman import FIGHT

    b_hp1, slope = _magic_factors(codes, 0.0)
    b_hp0, _ = _magic_factors(codes, FIGHT)
    # magical = (b_hp0 + (b_hp1-b_hp0)*t) + slope*M  where t=target_hp=1-when/FIGHT
    a0 = b_hp0
    a1 = b_hp1 - b_hp0

    def mag_moment(w, wt, wm):
        return a0 * w + a1 * wt + slope * wm

    total = 0.0
    total += taken * mag_moment(c("mag_w"), c("mag_wt"), c("mag_wm"))
    total += taken * mag_moment(c("atk_w"), c("atk_wt"), c("atk_wm"))
    total += taken * c("splash_w")
    total += taken * c("echo_w")
    total += taken * c("spirit_w")
    return total


class ShamanFights(BatchFights):
    def __init__(self, device, hero: str, spec: str, targets: int) -> None:
        import torch

        assert_gpu_allowed(hero, spec)
        if hero != "shaman" or spec not in ("restoration", "enhancement", "elemental"):
            raise ValueError(f"{hero}/{spec}: no shaman GPU kernel")
        self.torch = torch
        self.device = device
        self.target = device.handle if device.gpu else torch.device("cpu")
        self.hero = hero
        self.spec = spec
        self.targets = int(targets)
        self.fights = 0

    def _scores(self, tls: list[Timeline]) -> list[float]:
        from sunken_sim.shaman import FIGHT

        out: list[float] = []
        for begin in range(0, len(tls), MAX_BATCH):
            part = tls[begin : begin + MAX_BATCH]
            sums = compile_sums(self.torch, self.target, pack(part))
            out.extend(score_row(tl, row) / FIGHT for tl, row in zip(part, sums))
        return out

    def dps_many(self, builds: list) -> list[float]:
        import os

        gpu_bundle = None
        want = os.environ.get("FARM_HYBRID_GPU_TIMELINE", "auto").strip().lower()
        use_gpu_tl = (
            self.spec == "elemental"
            and want not in ("0", "false", "cpu")
            and (want in ("1", "true", "force") or bool(getattr(self.device, "gpu", False)))
        )
        if use_gpu_tl and builds:
            from sunken_sim import shaman as mod
            from farm.hybrid.shaman_gpu_timeline import generate_shaman_timelines

            flat_builds = []
            flat_keys = []
            for index, build in enumerate(builds):
                if mod._wears(build, mod.DIAMOND):
                    keys = list(mod.buttons(self.spec))
                else:
                    keys = [None]
                for bkey in keys:
                    flat_builds.append(build)
                    flat_keys.append(bkey)
            rows = generate_shaman_timelines(
                self.torch, self.target, flat_builds, self.spec, self.targets, flat_keys
            )
            gpu_bundle = {
                (id(build), bkey): row
                for build, bkey, row in zip(flat_builds, flat_keys, rows)
            }
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
