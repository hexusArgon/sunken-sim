# -*- coding: utf-8 -*-
"""GPU timeline + kind-score compile for Warrior (protection / arms / fury). DirectML.

Timeline generation: farm.hybrid.warrior_gpu_timeline (batched next-event on device).
Set FARM_HYBRID_GPU_TIMELINE=0 to force the CPU sunken_sim.warrior.simulate timeline.

Event shape from sunken_sim.warrior.score_events:
  (when, name, raw, magical, count, pot_scale, auto, mastery_now, enraged,
   auto_pct_scale, special)  special: None | "splash" | "echo" | "flat"

Enrage (*1.10 typed) is baked into weight. Fury enrage also +10 crit → separate kinds.
Auto hits use taken_auto; flat cleave is pre-scored.
"""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from farm.hybrid.engine import BatchFights
from farm.hybrid.lock import assert_gpu_allowed

MAX_BATCH = 512

KIND_MAG = 0.0
KIND_PHYS = 1.0
KIND_MAG_ENR = 2.0
KIND_PHYS_ENR = 3.0
KIND_MAG_AUTO = 4.0
KIND_PHYS_AUTO = 5.0
KIND_MAG_AUTO_ENR = 6.0
KIND_PHYS_AUTO_ENR = 7.0
KIND_SPLASH = 8.0
KIND_ECHO = 9.0
KIND_FLAT = 10.0
_PAD = -1.0

_KIND_IDS = (
    KIND_MAG,
    KIND_PHYS,
    KIND_MAG_ENR,
    KIND_PHYS_ENR,
    KIND_MAG_AUTO,
    KIND_PHYS_AUTO,
    KIND_MAG_AUTO_ENR,
    KIND_PHYS_AUTO_ENR,
    KIND_SPLASH,
    KIND_ECHO,
    KIND_FLAT,
)

COLUMNS = (
    ("mag_w",),
    ("mag_wt",),
    ("mag_wm",),
    ("phys_w",),
    ("phys_wt",),
    ("phys_wm",),
    ("mag_enr_w",),
    ("mag_enr_wt",),
    ("mag_enr_wm",),
    ("phys_enr_w",),
    ("phys_enr_wt",),
    ("phys_enr_wm",),
    ("mag_auto_w",),
    ("mag_auto_wt",),
    ("mag_auto_wm",),
    ("phys_auto_w",),
    ("phys_auto_wt",),
    ("phys_auto_wm",),
    ("mag_auto_enr_w",),
    ("mag_auto_enr_wt",),
    ("mag_auto_enr_wm",),
    ("phys_auto_enr_w",),
    ("phys_auto_enr_wt",),
    ("phys_auto_enr_wm",),
    ("splash_w",),
    ("echo_w",),
    ("flat_w",),
)
COLUMN_INDEX = {name[0]: i for i, name in enumerate(COLUMNS)}


@dataclass
class Timeline:
    build: object
    stats: dict
    spec: str
    events: list
    taken: float
    taken_auto: float


def _taken_pair(build, stats: dict, spec: str) -> tuple[float, float]:
    from sunken_sim import warrior
    from sunken_sim.shadow import armor_taken, DUMMY_ARMOR

    sunder_extra = 0.0
    if warrior._has(build, warrior.TALENT_SUNDER):
        if spec in ("fury", "arms"):
            sunder_extra = 2.0
    armor_pen = stats["armor_pen"] + (sunder_extra if spec == "arms" else 0.0)
    taken = armor_taken(DUMMY_ARMOR - armor_pen)
    taken_auto = armor_taken(DUMMY_ARMOR - armor_pen - (sunder_extra if spec == "fury" else 0.0))
    return taken, taken_auto


def timelines(build, targets: int, spec: str, *, gpu_bundle=None) -> list[Timeline]:
    """CPU timeline (module cache), or events from a GPU timeline batch bundle.

    gpu_bundle: optional dict id(build) -> (events, stats, taken, taken_auto)
    produced by farm.hybrid.warrior_gpu_timeline.generate_warrior_timelines.
    """
    from sunken_sim import warrior

    if gpu_bundle is not None and id(build) in gpu_bundle:
        events, stats, taken, taken_auto = gpu_bundle[id(build)]
        return [Timeline(build, stats, spec, events, taken, taken_auto)]

    stats = warrior.stats_of(build)
    taken, taken_auto = _taken_pair(build, stats, spec)
    key = warrior._timeline_key(build, stats, spec, targets)
    cached = warrior._TIMELINE.get(key)
    if cached is None:
        warrior.simulate(build, targets, spec)
        cached = warrior._TIMELINE[key]
    events, _actions, _mana = cached
    return [Timeline(build, stats, spec, events, taken, taken_auto)]

_EVENT_CACHE: dict[int, tuple] = {}


def _kind_for(magical: bool, auto: bool, enraged: bool, fury: bool) -> float:
    enr = bool(enraged and fury)
    if magical and auto and enr:
        return KIND_MAG_AUTO_ENR
    if (not magical) and auto and enr:
        return KIND_PHYS_AUTO_ENR
    if magical and auto:
        return KIND_MAG_AUTO
    if (not magical) and auto:
        return KIND_PHYS_AUTO
    if magical and enr:
        return KIND_MAG_ENR
    if (not magical) and enr:
        return KIND_PHYS_ENR
    if magical:
        return KIND_MAG
    return KIND_PHYS


def _event_arrays(events: list, stats: dict, fury: bool) -> tuple[np.ndarray, ...]:
    from sunken_sim.shadow import _execute_factor

    key = id(events)
    found = _EVENT_CACHE.get(key)
    if found is not None and found[0] is events:
        return found[1]

    n = len(events)
    kind = np.empty(n, dtype=np.float64)
    weight = np.empty(n, dtype=np.float64)
    mastery = np.empty(n, dtype=np.float64)
    when = np.empty(n, dtype=np.float64)
    for i, ev in enumerate(events):
        t_when, name, raw, magical, count, pot_scale, auto, mastery_now, enraged, auto_pct_scale, special = ev
        when[i] = t_when
        mastery[i] = mastery_now
        execute = _execute_factor(stats, t_when)
        if special == "splash":
            kind[i] = KIND_SPLASH
            weight[i] = raw * count * execute
        elif special == "echo":
            kind[i] = KIND_ECHO
            weight[i] = raw * count * execute
        elif special == "flat":
            kind[i] = KIND_FLAT
            weight[i] = raw * count
        else:
            kind[i] = _kind_for(magical, auto, enraged, fury)
            w = (raw + stats["potency"] * pot_scale) * count * execute
            if stats.get("relentless") and auto:
                w *= 1.0 + 0.25 * 0.80
            if auto_pct_scale:
                w *= stats["auto_pct"]
            if enraged:
                w *= 1.10
            weight[i] = w
    arrays = (kind, weight, mastery, when)
    if len(_EVENT_CACHE) >= 16384:
        _EVENT_CACHE.clear()
    _EVENT_CACHE[key] = (events, arrays)
    return arrays


def pack(tls: list[Timeline]) -> dict:
    from sunken_sim import warrior

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
        k, w, m, when = _event_arrays(tl.events, tl.stats, fury=(tl.spec == "fury"))
        kind[row, :n] = k
        weight[row, :n] = w
        mastery[row, :n] = m
        thp[row, :n] = np.maximum(0.0, 1.0 - when / warrior.FIGHT)
    return {"kind": kind, "weight": weight, "mastery": mastery, "thp": thp}


def compile_sums(torch, target, packed: dict) -> np.ndarray:
    def up(name):
        return torch.from_numpy(np.ascontiguousarray(packed[name], dtype=np.float32)).to(target)

    kind, weight, mastery, thp = up("kind"), up("weight"), up("mastery"), up("thp")
    feats = torch.stack([weight, weight * thp, weight * mastery], dim=2)
    ids = torch.tensor(_KIND_IDS, dtype=torch.float32, device=target)
    onehot = (kind.unsqueeze(2) == ids.view(1, 1, -1)).to(torch.float32)
    moments = torch.bmm(onehot.transpose(1, 2), feats).cpu().numpy().astype(np.float64)
    out = np.zeros((moments.shape[0], len(COLUMNS)))
    col = 0
    for ki in range(8):
        out[:, col] = moments[:, ki, 0]
        out[:, col + 1] = moments[:, ki, 1]
        out[:, col + 2] = moments[:, ki, 2]
        col += 3
    out[:, col] = moments[:, 8, 0]
    out[:, col + 1] = moments[:, 9, 0]
    out[:, col + 2] = moments[:, 10, 0]
    return out


def _phys_crit(stats: dict, crit: float) -> float:
    from sunken_sim.shadow import _crit_factor

    rating = stats["rating"]
    if stats["demolish"]:
        return _crit_factor(crit, 1.40 + rating)
    if stats["slaughterhouse"]:
        extra = (15.0 + 2.0 * stats["agi"]) / 100.0
        return _crit_factor(crit, 2.0 + rating + extra)
    return _crit_factor(crit, 2.0 + rating)


def _mag_crit(stats: dict, crit: float) -> float:
    from sunken_sim.shadow import _crit_factor

    return _crit_factor(crit, 2.0 + stats["rating"])


def _typed_parts(stats: dict, magical: bool) -> tuple[float, float, float]:
    glass = 1.15 if stats["glass"] else 1.0
    sulf = 1.0 if stats["sulfuron"] else 0.0
    sb = 1.0 if (magical and stats["spellbinder"]) else 0.0
    add = stats["magic_add"] if magical else stats["phys_add"]
    c0 = glass * (1.0 + add + 0.13 * sulf + 0.05 * sb)
    c_t = glass * (0.25 * sulf)
    c_m = glass * (0.005 * sb)
    return c0, c_t, c_m


def score_row(tl: Timeline, row: np.ndarray) -> float:
    s = tl.stats
    c = lambda name: float(row[COLUMN_INDEX[name]])  # noqa: E731

    crit0 = s["crit"]
    mag_c0, mag_ct, mag_cm = _typed_parts(s, True)
    phys_c0, phys_ct, phys_cm = _typed_parts(s, False)

    mag_crit = _mag_crit(s, crit0)
    phys_crit = _phys_crit(s, crit0)
    mag_crit_enr = _mag_crit(s, crit0 + 10.0)
    phys_crit_enr = _phys_crit(s, crit0 + 10.0)

    taken = tl.taken
    taken_auto = tl.taken_auto

    def bucket(prefix: str, c0: float, ct: float, cm: float, crit: float, use_taken: float) -> float:
        return crit * use_taken * (
            c0 * c(f"{prefix}_w") + ct * c(f"{prefix}_wt") + cm * c(f"{prefix}_wm")
        )

    total = 0.0
    total += bucket("mag", mag_c0, mag_ct, mag_cm, mag_crit, taken)
    total += bucket("phys", phys_c0, phys_ct, phys_cm, phys_crit, taken)
    total += bucket("mag_enr", mag_c0, mag_ct, mag_cm, mag_crit_enr, taken)
    total += bucket("phys_enr", phys_c0, phys_ct, phys_cm, phys_crit_enr, taken)
    total += bucket("mag_auto", mag_c0, mag_ct, mag_cm, mag_crit, taken_auto)
    total += bucket("phys_auto", phys_c0, phys_ct, phys_cm, phys_crit, taken_auto)
    total += bucket("mag_auto_enr", mag_c0, mag_ct, mag_cm, mag_crit_enr, taken_auto)
    total += bucket("phys_auto_enr", phys_c0, phys_ct, phys_cm, phys_crit_enr, taken_auto)
    total += taken * c("splash_w")
    total += taken_auto * c("echo_w")
    total += c("flat_w")
    return total


class WarriorFights(BatchFights):
    def __init__(self, device, hero: str, spec: str, targets: int) -> None:
        import torch

        assert_gpu_allowed(hero, spec)
        if hero != "warrior" or spec not in ("protection", "arms", "fury"):
            raise ValueError(f"{hero}/{spec}: no warrior GPU kernel")
        self.torch = torch
        self.device = device
        self.target = device.handle if device.gpu else torch.device("cpu")
        self.hero = hero
        self.spec = spec
        self.targets = int(targets)
        self.fights = 0

    def _scores(self, tls: list[Timeline]) -> list[float]:
        from sunken_sim.warrior import FIGHT

        out: list[float] = []
        for begin in range(0, len(tls), MAX_BATCH):
            part = tls[begin : begin + MAX_BATCH]
            sums = compile_sums(self.torch, self.target, pack(part))
            out.extend(score_row(tl, row) / FIGHT for tl, row in zip(part, sums))
        return out

    def dps_many(self, builds: list) -> list[float]:
        import os

        tls: list[Timeline] = []
        owner: list[int] = []
        gpu_bundle = None
        # GPU timeline when on DirectML (or FARM_HYBRID_GPU_TIMELINE=1). Opt out with =0.
        want = os.environ.get('FARM_HYBRID_GPU_TIMELINE', 'auto').strip().lower()
        use_gpu_tl = want not in ('0', 'false', 'cpu') and (
            want in ('1', 'true', 'force') or bool(getattr(self.device, 'gpu', False))
        )
        if use_gpu_tl and builds:
            from farm.hybrid.warrior_gpu_timeline import generate_warrior_timelines

            rows = generate_warrior_timelines(
                self.torch, self.target, builds, self.spec, self.targets
            )
            gpu_bundle = {
                id(build): (events, stats, taken, taken_auto)
                for build, (events, stats, taken, taken_auto) in zip(builds, rows)
            }
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
