"""GPU compile stage for Priest (Shadow / Discipline / Holy). DirectML, torch CPU fallback.

Split of one fight (same rules as sunken_sim.shadow.simulate):

  1. CPU: the event timeline. sunken_sim.shadow._fight_events behind the module's
     own exact cache (shadow._timeline_key / shadow._TIMELINE), unchanged.
  2. CPU, exact float64: per-event execute factor (hp <= threshold) and the
     Holy Fire window amp (I0MJ). These are discrete steps, so they never go to
     float32.
  3. GPU: per-kind weighted moments sum(w), sum(w*t), sum(w*t^2) over the
     events of each fight, batched (t = target hp, w = hits*execute*amp, Pain
     link factor, Hellfire raw). Every type multiplier in shadow.py is linear in
     t, so the whole per-event loop of shadow.score_events collapses to these.
  4. CPU: closed-form score from the moments (float64, microseconds).

DPS must match shadow.simulate within DPS_TOL (relative). shadow.score_events
and shadow.compile_events + score_compiled are the same math (the ESC greedy in
farm.score uses the second); _crit_factor clamps crit to 100 in both.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from farm.hybrid.engine import BatchFights
from farm.hybrid.lock import assert_gpu_allowed

MAX_BATCH = 512

MAGIC_KINDS = ("mind", "void", "naaru", "swp_i", "thunder", "blaze", "smite", "sulfuras")
_KINDS = ("auto", "splash", "sulfuras_echo", "hellfire", "swp", "radiance") + MAGIC_KINDS
KIND_IDS = {name: float(index) for index, name in enumerate(_KINDS)}
_OTHER = -1.0
_PAD = -2.0
# kinds that add Blood Violence in score_events (splash / echo / unknown 'continue')
_BLOOD_KINDS = ("auto", "hellfire", "swp", "radiance") + MAGIC_KINDS

# moment columns: name -> (kind or None, weight id, moment)
COLUMNS = (
    ("auto0", "auto", "w", 0),
    ("auto1", "auto", "w", 1),
    ("auto2", "auto", "w", 2),
    *[(f"{k}{m}", k, "w", m) for k in MAGIC_KINDS for m in (0, 1)],
    ("swp0", "swp", "lw", 0),
    ("swp1", "swp", "lw", 1),
    ("rad_a0", "radiance", "ea", 0),
    ("rad_a1", "radiance", "ea", 1),
    ("rad_b0", "radiance", "w", 0),
    ("rad_b1", "radiance", "w", 1),
    ("splash0", "splash", "w", 0),
    ("echo0", "sulfuras_echo", "he", 0),
    ("hell_raw0", "hellfire", "rw", 0),
    ("hell0", "hellfire", "w", 0),
    ("blood0", None, "ea", 0),
)
COLUMN_INDEX = {name: index for index, (name, *_rest) in enumerate(COLUMNS)}


@dataclass
class Timeline:
    build: object
    stats: dict
    spec: str
    events: list
    windows: list | None
    bound: str | None


def timelines(build, targets: int, spec: str) -> list[Timeline]:
    """Same timelines shadow.simulate(use_history=False) scores, one per bound spell for I00D."""
    from sunken_sim import shadow

    if shadow._wears(build, "I00D"):
        bounds: list[str | None] = list(shadow._cast_spells(build, spec))
        if not bounds:
            raise ValueError("I00D without spells")
    else:
        bounds = [None]
    out = []
    for bound in bounds:
        stats = shadow.character(build)
        key = shadow._timeline_key(build, stats, spec, targets, bound)
        cached = shadow._TIMELINE.get(key)
        if cached is None:
            cached = shadow._fight_events(build, stats, spec, targets, bound)
            while len(shadow._TIMELINE) >= 8000:
                shadow._TIMELINE.pop(next(iter(shadow._TIMELINE)))
            shadow._TIMELINE[key] = cached
        events, _actions, windows, _mana_left = cached
        out.append(Timeline(build, stats, spec, events, windows, bound))
    return out


_EVENT_CACHE: dict[int, tuple] = {}


def _event_arrays(events: list) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """when, kind id, hits, hellfire raw per event. Cached by list identity (timeline cache shares lists)."""
    from sunken_sim.shadow import LEVEL

    key = id(events)
    found = _EVENT_CACHE.get(key)
    if found is not None and found[0] is events:
        return found[1]
    when = np.fromiter((ev[0] for ev in events), dtype=np.float64, count=len(events))
    kind = np.fromiter((KIND_IDS.get(ev[1], _OTHER) for ev in events), dtype=np.float64, count=len(events))
    hits = np.fromiter((ev[2] for ev in events), dtype=np.float64, count=len(events))
    raw = np.array(
        [(3 + 3 * LEVEL) * (2 if h == 1 else 0.5 if h >= 4 else 1) for h in hits], dtype=np.float64
    )
    arrays = (when, kind, hits, raw)
    if len(_EVENT_CACHE) >= 16384:
        _EVENT_CACHE.clear()
    _EVENT_CACHE[key] = (events, arrays)
    return arrays


def pack(tls: list[Timeline]) -> dict:
    """CPU float64: padded event arrays, exact execute factor and window amp."""
    from sunken_sim import shadow

    count = len(tls)
    width = max(1, max(len(tl.events) for tl in tls))
    kind = np.full((count, width), _PAD)
    hits = np.zeros((count, width))
    thp = np.zeros((count, width))
    ea = np.zeros((count, width))  # execute * amp
    he = np.zeros((count, width))  # hits * execute
    raw = np.zeros((count, width))
    link = np.zeros((count, 1))
    blood = np.zeros((count, 1))
    for row, tl in enumerate(tls):
        n = len(tl.events)
        link[row, 0] = 1.0 if shadow._has(tl.build, "I0HL") else 0.0
        blood[row, 0] = 1.0 if shadow._has(tl.build, "I0H6") else 0.0
        if not n:
            continue
        when, kid, h, hraw = _event_arrays(tl.events)
        t = np.maximum(0.0, 1.0 - when / shadow.FIGHT)
        execute = np.ones(n)
        for threshold, bonus in tl.stats["executes"]:
            execute = np.where(t <= threshold, execute * (1.0 + bonus), execute)
        amp = np.ones(n)
        if tl.windows and shadow._has(tl.build, "I0MJ"):
            inside = np.zeros(n, dtype=bool)
            for start, end in tl.windows:
                inside |= (start < when) & (when <= end)
            amp = np.where(inside, 1.05 + 0.0008 * tl.stats["str"], 1.0)
        kind[row, :n] = kid
        hits[row, :n] = h
        thp[row, :n] = t
        ea[row, :n] = execute * amp
        he[row, :n] = h * execute
        raw[row, :n] = hraw
    return {"kind": kind, "hits": hits, "thp": thp, "ea": ea, "he": he, "raw": raw, "link": link, "blood": blood}


# per-event features on device: (weight, moment); one batched matmul against the
# one-hot kind matrix gives every (kind, feature) moment at once.
FEATURES = (("w", 0), ("w", 1), ("w", 2), ("lw", 0), ("lw", 1), ("ea", 0), ("ea", 1), ("he", 0), ("rw", 0))
_FEATURE_INDEX = {f: i for i, f in enumerate(FEATURES)}
_NKIND = len(_KINDS)


def compile_sums(torch, target, packed: dict) -> np.ndarray:
    """Device part: [timelines, COLUMNS] moments. torch ops only (~20 device ops per batch)."""

    def up(name):
        return torch.from_numpy(np.ascontiguousarray(packed[name], dtype=np.float32)).to(target)

    kind, hits, thp, ea, he, raw = up("kind"), up("hits"), up("thp"), up("ea"), up("he"), up("raw")
    link = up("link")
    w = hits * ea
    lw = (1.0 + link * (0.15 + 0.10 * hits)) * w
    t2 = thp * thp
    feats = torch.stack([w, w * thp, w * t2, lw, lw * thp, ea, ea * thp, he, raw * w], dim=2)
    ids = torch.arange(_NKIND, dtype=torch.float32).to(target)
    onehot = (kind.unsqueeze(2) == ids.view(1, 1, -1)).to(torch.float32)
    moments = torch.bmm(onehot.transpose(1, 2), feats).cpu().numpy().astype(np.float64)  # [B, kinds, features]
    out = np.zeros((moments.shape[0], len(COLUMNS)))
    blood_ids = [int(KIND_IDS[k]) for k in _BLOOD_KINDS]
    ea0 = _FEATURE_INDEX[("ea", 0)]
    for col, (_name, k, weight, moment) in enumerate(COLUMNS):
        if k is None:
            out[:, col] = moments[:, blood_ids, ea0].sum(axis=1) * packed["blood"][:, 0]
        else:
            out[:, col] = moments[:, int(KIND_IDS[k]), _FEATURE_INDEX[(weight, moment)]]
    return out


def score_row(tl: Timeline, row: np.ndarray) -> float:
    """shadow.score_events total from the moments, float64."""
    from sunken_sim import shadow

    s = tl.stats
    build = tl.build
    spec = tl.spec
    c = lambda name: float(row[COLUMN_INDEX[name]])  # noqa: E731
    codes = shadow._codes(build)
    potency, crit, m, luck = s["potency"], s["crit"], s["mastery"], s["luck"]
    spell_crit = shadow._crit_factor(crit, s["spell_mult"] + s["rating"]) if s["spell_crit"] else 1.0
    attack_crit = shadow._crit_factor(crit, 2 + s["rating"])
    mastery = (1.10 + 0.006 * m) if spec == "shadow" else 1.0
    tick_base = (15 + 0.30 * s["int"]) * mastery
    instant_raw = (75 + 1.50 * s["int"]) * mastery
    nuke_raw, stored = shadow._radiance_parts(s, m, spec)
    raws = {
        "mind": (80 + 1.50 * s["int"]) * (1 + 0.01 * s["ad"]),
        "void": (85 + 0.15 * s["mana_max"]) * (1 + 0.007 * s["int"]),
        "naaru": (25 + 0.40 * s["int"]) * (0.75 if spec == "discipline" else 1.0),
        "swp_i": instant_raw,
        "thunder": 35 + 2 * s["int"],
        "blaze": (0.04 if spec == "holy" else 0.08) * stored,
        "smite": 50 + 0.80 * s["int"] + 0.80 * s["str"],
    }
    # magical(t) = a0 + a1*t + slope*mastery ; physical(t) = p0 + p1*t
    qt = 1.0 if "I0QT" in codes else 0.0
    madd = sum(v for k, v in shadow.MAGICAL_ADDS.items() if k in codes)
    padd = sum(v for k, v in shadow.PHYSICAL_ADDS.items() if k in codes)
    a0 = 1.0 + madd + 0.13 * qt
    a1 = 0.25 * qt
    slope = 0.0
    if "tlum" in codes:
        a0 += 0.05
        slope = 0.005
    if "I0PU" in codes:
        a0 *= 1.15
        a1 *= 1.15
        slope *= 1.15
    if "I0PS" in codes:
        a1 += 0.30
    glass = "I0JA" in codes
    p0 = 1.0 + padd + 0.13 * qt
    p1 = 0.25 * qt
    if glass:
        a0 *= 1.15
        a1 *= 1.15
        slope *= 1.15
        p0 *= 1.15
        p1 *= 1.15

    def mag(prefix: str) -> float:
        w0, w1 = c(prefix + "0"), c(prefix + "1")
        return (a0 + slope * m) * w0 + a1 * w1

    phys0 = p0 * c("auto0") + p1 * c("auto1")
    phys1 = p0 * c("auto1") + p1 * c("auto2")
    total = (s["ad"] + potency * s["attack_potency"]) * s["auto_pct"] * attack_crit * phys0
    total += s["soul_rate"] * shadow.MEDIAN_MONSTER_HP * s["auto_pct"] * attack_crit * phys1
    for kind, raw in raws.items():
        total += (raw + potency) * spell_crit * mag(kind)
    total += s["int"] * spell_crit * mag("sulfuras")
    total += (tick_base + potency) * spell_crit * mag("swp")
    total += spell_crit * (nuke_raw * mag("rad_a") + potency * mag("rad_b"))
    total += (20 + 0.35 * s["int"]) * c("splash0")
    total += s["ad"] * shadow.sulfuras_echo_chance(luck) * c("echo0")
    gf = 1.15 if shadow._has(build, "I0JA") else 1.0
    total += gf * (c("hell_raw0") + potency * c("hell0"))
    total += 0.03 * (20 + 1.6 * s["int"] + potency) * gf * c("blood0")
    total *= shadow.armor_taken(shadow.DUMMY_ARMOR - s["armor_pen"])
    if s["stab_chance"]:
        chance = s["stab_chance"] * (1 + luck)
        stab_raw = s["stab_ratio"] * s["ad"]
        stab = (stab_raw + potency * s["attack_potency"]) * s["auto_pct"] * attack_crit * shadow.CHAOS_UNARMORED * chance * phys0
        total += stab * shadow.armor_taken(shadow.DUMMY_ARMOR)
    return total


class PriestFights(BatchFights):
    """Batched priest fights: CPU timelines, device moments, CPU score."""

    def __init__(self, device, hero: str, spec: str, targets: int) -> None:
        import torch

        assert_gpu_allowed(hero, spec)
        if hero != "priest" or spec not in ("shadow", "discipline", "holy"):
            raise ValueError(f"{hero}/{spec}: no priest GPU kernel")
        self.torch = torch
        self.device = device
        self.target = device.handle if device.gpu else torch.device("cpu")
        self.hero = hero
        self.spec = spec
        self.targets = int(targets)
        self.fights = 0

    def _scores(self, tls: list[Timeline]) -> list[float]:
        from sunken_sim.shadow import FIGHT

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
            # shadow.simulate keeps the first bound spell on ties (strict >).
            if best[index] is None or dps > best[index]:
                best[index] = dps
        return [float(value) for value in best]
