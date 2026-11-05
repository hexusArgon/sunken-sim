# -*- coding: utf-8 -*-
"""GPU timeline + kind-score compile for Paladin (retribution / protection / holy). DirectML.

Timeline generation: farm.hybrid.paladin_gpu_timeline (batched next-event).
Set FARM_HYBRID_GPU_TIMELINE=0 to force the CPU paladin._fight_events timeline.

Split (same rules as sunken_sim.paladin.simulate):

  1. Timeline: GPU batched next-event (default) or CPU _fight_events + _TIMELINE.
  2. CPU float64: per-event execute factor (discrete HP steps).
  3. GPU: moments sum(w), sum(w*t), sum(w*M) for magic / phys, plus splash/echo.
  4. CPU closed-form score from moments.

typed(magical) is linear in target HP t and in the event's mastery_now M, so the
per-event loop of score_events collapses to these moments.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from farm.hybrid.engine import BatchFights
from farm.hybrid.lock import assert_gpu_allowed

MAX_BATCH = 512

# kind ids: 0 magic, 1 phys, 2 fire splash (taken*exec only), 3 sulfuras echo (taken*exec only)
KIND_MAGIC = 0.0
KIND_PHYS = 1.0
KIND_SPLASH = 2.0
KIND_ECHO = 3.0
_PAD = -1.0

COLUMNS = (
    ("mag_w", "mag", 0),
    ("mag_wt", "mag", 1),
    ("mag_wm", "mag", 2),
    ("phys_w", "phys", 0),
    ("phys_wt", "phys", 1),
    ("phys_wm", "phys", 2),
    ("splash_w", "splash", 0),
    ("echo_w", "echo", 0),
)
COLUMN_INDEX = {name: i for i, (name, *_r) in enumerate(COLUMNS)}


@dataclass
class Timeline:
    build: object
    stats: dict
    spec: str
    events: list
    knowledge: float


def timelines(build, targets: int, spec: str, *, gpu_bundle=None) -> list[Timeline]:
    """CPU timeline (module cache), or events from a GPU timeline batch bundle.

    gpu_bundle: optional dict id(build) -> (events, stats, knowledge)
    produced by farm.hybrid.paladin_gpu_timeline.generate_paladin_timelines.
    """
    from sunken_sim import paladin

    if gpu_bundle is not None and id(build) in gpu_bundle:
        events, stats, knowledge = gpu_bundle[id(build)]
        return [Timeline(build, stats, spec, events, knowledge)]

    stats = paladin.stats_of(build)
    knowledge = (
        1.0 + 0.003 * stats["int"]
        if spec == "retribution" and paladin._has(build, paladin.TALENT_DIVINE_KNOWLEDGE)
        else 1.0
    )
    key = paladin._timeline_key(build, stats, spec, targets)
    cached = paladin._TIMELINE.get(key)
    if cached is None:
        cached = paladin._fight_events(build, stats, spec, targets)
        while len(paladin._TIMELINE) >= 8000:
            paladin._TIMELINE.pop(next(iter(paladin._TIMELINE)))
        paladin._TIMELINE[key] = cached
    events, _actions, _mana = cached
    return [Timeline(build, stats, spec, events, knowledge)]


_EVENT_CACHE: dict[int, tuple] = {}


def _event_arrays(events: list, stats: dict) -> tuple[np.ndarray, ...]:
    """kind, weight=(raw+pot*scale)*count*[auto], mastery, when — cached by list id."""
    from sunken_sim.shadow import _execute_factor, FIGHT

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
        t_when, name, raw, magical, count, pot_scale, mastery_now, auto_scale = ev
        when[i] = t_when
        mastery[i] = mastery_now
        execute = _execute_factor(stats, t_when)
        if name == "Всплеск огня":
            kind[i] = KIND_SPLASH
            weight[i] = raw * count * execute
        elif name == "Sulfuras (удар)":
            kind[i] = KIND_ECHO
            weight[i] = raw * count * execute
        else:
            kind[i] = KIND_MAGIC if magical else KIND_PHYS
            w = (raw + stats["potency"] * pot_scale) * count * execute
            if auto_scale:
                w *= stats["auto_pct"]
            weight[i] = w
    arrays = (kind, weight, mastery, when)
    if len(_EVENT_CACHE) >= 16384:
        _EVENT_CACHE.clear()
    _EVENT_CACHE[key] = (events, arrays)
    return arrays


def pack(tls: list[Timeline]) -> dict:
    from sunken_sim import paladin

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
        thp[row, :n] = np.maximum(0.0, 1.0 - when / paladin.FIGHT)
    return {"kind": kind, "weight": weight, "mastery": mastery, "thp": thp}


def compile_sums(torch, target, packed: dict) -> np.ndarray:
    def up(name):
        return torch.from_numpy(np.ascontiguousarray(packed[name], dtype=np.float32)).to(target)

    kind, weight, mastery, thp = up("kind"), up("weight"), up("mastery"), up("thp")
    feats = torch.stack([weight, weight * thp, weight * mastery], dim=2)  # [B,E,3]
    ids = torch.tensor([KIND_MAGIC, KIND_PHYS, KIND_SPLASH, KIND_ECHO], dtype=torch.float32, device=target)
    onehot = (kind.unsqueeze(2) == ids.view(1, 1, -1)).to(torch.float32)  # [B,E,4]
    moments = torch.bmm(onehot.transpose(1, 2), feats).cpu().numpy().astype(np.float64)  # [B,4,3]
    out = np.zeros((moments.shape[0], len(COLUMNS)))
    # mag / phys use all 3 moments; splash/echo use weight only
    out[:, 0] = moments[:, 0, 0]
    out[:, 1] = moments[:, 0, 1]
    out[:, 2] = moments[:, 0, 2]
    out[:, 3] = moments[:, 1, 0]
    out[:, 4] = moments[:, 1, 1]
    out[:, 5] = moments[:, 1, 2]
    out[:, 6] = moments[:, 2, 0]
    out[:, 7] = moments[:, 3, 0]
    return out


def score_row(tl: Timeline, row: np.ndarray) -> float:
    from sunken_sim import paladin
    from sunken_sim.shadow import _crit_factor, armor_taken, DUMMY_ARMOR

    s = tl.stats
    c = lambda name: float(row[COLUMN_INDEX[name]])  # noqa: E731
    attack_crit = _crit_factor(s["crit"], 2.0 + s["rating"])
    spell_crit = _crit_factor(s["crit"], s["spell_mult"] + s["rating"]) if s["spell_crit"] else 1.0
    taken = armor_taken(DUMMY_ARMOR - s["armor_pen"])
    knowledge = tl.knowledge
    glass = 1.15 if s["glass"] else 1.0
    sulf = 1.0 if s["sulfuron"] else 0.0
    sb = 1.0 if s["spellbinder"] else 0.0

    # magical typed = knowledge*glass * (1+madd+0.13*sulf + 0.05*sb + 0.005*sb*M) + knowledge*glass*0.25*sulf * t
    mag_scale = knowledge * glass
    mag_c0 = mag_scale * (1.0 + s["magic_add"] + 0.13 * sulf + 0.05 * sb)
    mag_cm = mag_scale * (0.005 * sb)
    mag_c1 = mag_scale * (0.25 * sulf)

    phys_scale = glass
    phys_c0 = phys_scale * (1.0 + s["phys_add"] + 0.13 * sulf)
    phys_cm = 0.0
    phys_c1 = phys_scale * (0.25 * sulf)

    total = 0.0
    total += spell_crit * taken * (mag_c0 * c("mag_w") + mag_c1 * c("mag_wt") + mag_cm * c("mag_wm"))
    total += attack_crit * taken * (phys_c0 * c("phys_w") + phys_c1 * c("phys_wt") + phys_cm * c("phys_wm"))
    total += taken * c("splash_w")
    total += taken * c("echo_w")
    return total


class PaladinFights(BatchFights):
    def __init__(self, device, hero: str, spec: str, targets: int) -> None:
        import torch

        assert_gpu_allowed(hero, spec)
        if hero != "paladin" or spec not in ("retribution", "protection", "holy"):
            raise ValueError(f"{hero}/{spec}: no paladin GPU kernel")
        self.torch = torch
        self.device = device
        self.target = device.handle if device.gpu else torch.device("cpu")
        self.hero = hero
        self.spec = spec
        self.targets = int(targets)
        self.fights = 0

    def _scores(self, tls: list[Timeline]) -> list[float]:
        from sunken_sim.paladin import FIGHT

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
        use_gpu_tl = want not in ("0", "false", "cpu") and (
            want in ("1", "true", "force") or bool(getattr(self.device, "gpu", False))
        )
        if use_gpu_tl and builds:
            from farm.hybrid.paladin_gpu_timeline import generate_paladin_timelines

            rows = generate_paladin_timelines(
                self.torch, self.target, builds, self.spec, self.targets
            )
            gpu_bundle = {
                id(build): (events, stats, knowledge)
                for build, (events, stats, knowledge) in zip(builds, rows)
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
