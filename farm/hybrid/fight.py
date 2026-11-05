"""GPU fight stage for Mage Fire / Frost (DirectML, torch CPU fallback).

Split of one fight (30 s, same rules as sunken_sim.mage.simulate):

  1. CPU: the event timeline (who casts what and when). This is the old
     sunken_sim.mage.simulate loop, unchanged; we only capture its events
     instead of letting it compile them.
  2. GPU: the per-event compile of that timeline, batched over many fights:
     hero-health damage factor (Furnace / Gladiator / Crimson), execute,
     physical and magical type multipliers, Pyroblast mastery coefficient,
     and the ~70 weighted sums that sunken_sim.mage._compile builds.
  3. CPU: sunken_sim.mage._score on those sums (closed form, microseconds).

Exact discrete steps (hp table index, ratio <= 40%, execute thresholds) are
done on CPU in float64 so they never flip; the GPU only does float math and
reductions in float32. DPS must match the CPU sim within DPS_TOL (relative).

Exact timeline cache (pilot): the timeline only reads TIMELINE_STATS from the
sheet (found by tracking dict reads + a static scan of mage.py), so builds with
the same items / talents / glyphs / spec / targets / bound and equal values of
those stats get identical events. ESC trials on potency / damage / pet_damage /
healing_power / health (and crit when Crit-AS is off) reuse one timeline. On a
hit, stats = fresh sheet + the stats delta simulate wrote (e.g. fire swing).
farm.test_hybrid checks events + stats equality against a fresh simulate.

Arcane Mage is hard-locked to the CPU sim and never reaches this module.
"""

from __future__ import annotations

import itertools
from contextlib import contextmanager
from dataclasses import dataclass

import numpy as np

from farm.hybrid.engine import DPS_TOL, BatchFights, compare, eval_span  # noqa: F401 (re-exported)
from farm.hybrid.lock import assert_gpu_allowed, cpu_locked

# Specs whose fights may run through the GPU compile stage.
GPU_FIGHT_SPECS: frozenset[tuple[str, str]] = frozenset({("mage", "fire"), ("mage", "frost")})
MAX_BATCH = 512  # timelines per device call

BUCKETS = (
    "bomb",
    "burst",
    "firebomb",
    "ring",
    "blast",
    "nova",
    "lance",
    "bolt",
    "bolt_splash",
    "thunder",
    "blizzard",
)
_SPECIAL = ("auto", "splash", "hellfire", "pyro", "hydra", "cleave", "sulfuras", "sulfuras_echo")
KIND_IDS = {name: index for index, name in enumerate(_SPECIAL + BUCKETS)}
_PAD_KIND = -2.0
_OTHER_KIND = -1.0

SCALAR_COLS = (
    "auto_weight",
    "soul_weight",
    "splash",
    "hell_weight",
    "blood",
    "pyro_base",
    "pyro_slope",
    "pyro_pot_base",
    "pyro_pot_slope",
    "pyro_raw_base",
    "pyro_raw_mastery",
    "pyro_m_base",
    "pyro_m_slope",
    "hydra_base",
    "hydra_pot_base",
    "cleave_base",
    "cleave_pot_base",
    "sulf_base",
    "sulf_slope",
    "sulf_echo",
)
BUCKET_PARTS = ("base", "slope", "pot_base", "pot_slope")


def gpu_fights_for(hero: str, spec: str) -> bool:
    if cpu_locked(hero, spec):
        return False
    return (str(hero).strip().lower(), str(spec).strip().lower()) in GPU_FIGHT_SPECS


@dataclass
class Timeline:
    build: object
    stats: dict
    spec: str
    evocation: bool
    events: list
    bound: str | None


@contextmanager
def _capture():
    """Let mage.simulate run its timeline, but hand us the events instead of compiling."""
    from sunken_sim import mage

    sink: list[tuple] = []
    old_compile, old_score = mage._compile, mage._score

    def grab(events, build, stats, spec, evocation):
        sink.append((events, build, stats, spec, evocation))
        return None

    mage._compile = grab
    mage._score = lambda *args, **kwargs: (0.0, {})
    try:
        yield sink
    finally:
        mage._compile, mage._score = old_compile, old_score


# sheet keys the mage timeline (simulate before _compile) reads. _raws / _compile /
# _score read more, but they run on the stats we hand back, so those may differ.
TIMELINE_STATS = (
    "attack_base",
    "attack_mana",
    "attack_mana_crit",
    "attack_mana_pct",
    "attack_speed",
    "bomb_period",
    "cast_refund",
    "cast_refund_flat",
    "cast_refund_mastery",
    "cast_stun_lock",
    "cd_temp",
    "crit_as",
    "crit_as_duration",
    "damage_mana_pct",
    "flat_cdr",
    "frenzy",
    "haste",
    "luck",
    "mana_max",
    "mana_regen",
    "mastery",
    "str",
    "stun_per_swing",
    "swing",
)
TL_CACHE_MAX = 8000
_TL_CACHE: dict = {}
TL_COUNTS = {"hit": 0, "miss": 0}


def _tl_key(build, stats: dict, targets: int, spec: str, bound) -> tuple:
    # crit only feeds the timeline through Crit-AS charge (mage.py, crit_as > 0).
    gated = stats.get("crit") if stats.get("crit_as", 0) > 0 and stats.get("crit_as_duration", 0) > 0 else None
    return (
        spec,
        int(targets),
        bound,
        tuple(sorted(build.talents)),
        tuple(sorted(build.glyphs)),
        tuple(item.rawcode for item in build.items),
        tuple(stats.get(name) for name in TIMELINE_STATS),
        gated,
    )


@contextmanager
def _sheet_once(build, stats: dict):
    """mage.simulate calls sheet(build); hand it a copy of the sheet we already built."""
    from sunken_sim import mage

    old = mage.sheet

    def sheet(b):
        return dict(stats) if b is build else old(b)

    mage.sheet = sheet
    try:
        yield
    finally:
        mage.sheet = old


def _delta(before: dict, after: dict) -> dict:
    out = {}
    for name, value in after.items():
        if name not in before or before[name] is not value and before[name] != value:
            out[name] = value
    return out


def timelines(build, targets: int, spec: str, cache: bool = True) -> list[Timeline]:
    """CPU part. One timeline, or one per bindable spell when the build wears I00D."""
    from sunken_sim import mage

    bounds: list[str | None] = [None]
    if mage._wears(build, "I00D"):
        bounds = [name for name in mage._buttons(spec) if name != "Evocation"]
    out = []
    pre = mage.sheet(build) if cache else None
    for bound in bounds:
        key = _tl_key(build, pre, targets, spec, bound) if cache else None
        hit = _TL_CACHE.get(key) if cache else None
        if hit is not None:
            TL_COUNTS["hit"] += 1
            events, used_spec, evocation, delta = hit
            stats = dict(pre)
            stats.update(delta)
            out.append(Timeline(build, stats, used_spec, evocation, events, bound))
            continue
        with _capture() as sink:
            if cache:
                with _sheet_once(build, pre):
                    mage.simulate(build, targets, None, bound, spec, use_history=False)
            else:
                mage.simulate(build, targets, None, bound, spec, use_history=False)
        events, _build, stats, used_spec, evocation = sink.pop()
        if cache:
            TL_COUNTS["miss"] += 1
            if len(_TL_CACHE) >= TL_CACHE_MAX:
                _TL_CACHE.clear()
            _TL_CACHE[key] = (events, used_spec, evocation, _delta(pre, stats))
        out.append(Timeline(build, stats, used_spec, evocation, events, bound))
    return out


def _consts(tl: Timeline) -> dict:
    from sunken_sim import mage
    from sunken_sim.pressure import HP_FLOOR, _hp_table, max_hp
    from sunken_sim.shadow import MAGICAL_ADDS, PHYSICAL_ADDS

    build, stats = tl.build, tl.stats
    codes = mage._codes(build)
    cap = 0.38 if mage._wears(build, mage._CRIMSON) else 1.0
    health = max_hp(mage.BASE_HP, stats["str"]) + mage._flat_health(build)
    if health <= HP_FLOOR:
        table = None
    else:
        table = _hp_table(int(round(health * 1000)), int(round(cap * 1000)))
    return {
        "table": table,
        "executes": list(stats["executes"]),
        "flags": [
            1.0 if mage._wears(build, mage._FURNACE) else 0.0,
            1.0 if mage._wears(build, mage._GLADIATOR_MASK) else 0.0,
            1.0 if mage._wears(build, mage._CRIMSON) else 0.0,
            1.0 if mage._has(build, "I0H6") else 0.0,
            sum(amount for code, amount in MAGICAL_ADDS.items() if code in codes),
            sum(amount for code, amount in PHYSICAL_ADDS.items() if code in codes),
            1.0 if "I0QT" in codes else 0.0,
            1.0 if "tlum" in codes else 0.0,
            1.0 if "I0PU" in codes else 0.0,
            1.0 if "I0PS" in codes else 0.0,
            1.0 if "I0JA" in codes else 0.0,
            1.0 if tl.evocation else 0.0,
            0.0075 if tl.spec == "fire" else 0.0,
        ],
    }


_TABLE_CACHE: dict = {}


def _table_array(table) -> np.ndarray:
    if table is None:
        return np.ones(3001, dtype=np.float64)
    key = id(table)
    found = _TABLE_CACHE.get(key)
    if found is None or found[0] is not table:
        if len(_TABLE_CACHE) > 512:
            _TABLE_CACHE.clear()
        found = (table, np.asarray(table, dtype=np.float64))
        _TABLE_CACHE[key] = found
    return found[1]


_EVENT_CACHE: dict = {}


def _event_arrays(events: list, mana_max: float) -> tuple:
    """Per-event columns of one timeline; cached while the timeline cache holds the list."""
    key = id(events)
    found = _EVENT_CACHE.get(key)
    if found is not None and found[0] is events and found[1] == mana_max:
        return found[2]
    kid = KIND_IDS.get
    hell = None
    for ev in events:
        if ev[1] == "hellfire":
            hell = ev[2]
    arrays = (
        np.array([ev[0] for ev in events], dtype=np.float64),
        np.array([kid(ev[1], _OTHER_KIND) for ev in events], dtype=np.float64),
        np.array([ev[3] for ev in events], dtype=np.float64),
        np.array([ev[4] for ev in events], dtype=np.float64),
        np.array([ev[5].get("mana", mana_max) for ev in events], dtype=np.float64),
        np.array([ev[5].get("splinter", 0.0) for ev in events], dtype=np.float64),
        np.array([1.0 if ev[5].get("magical") else 0.0 for ev in events], dtype=np.float64),
        hell,
    )
    if len(_EVENT_CACHE) >= 2 * TL_CACHE_MAX:
        _EVENT_CACHE.clear()
    _EVENT_CACHE[key] = (events, mana_max, arrays)
    return arrays


def pack(tls: list[Timeline]) -> dict:
    """CPU: events to padded float64 arrays + exact discrete masks."""
    from sunken_sim.shadow import FIGHT

    count = len(tls)
    width = max(1, max(len(tl.events) for tl in tls))
    consts = [_consts(tl) for tl in tls]
    k_exec = max(1, max(len(c["executes"]) for c in consts))
    when = np.zeros((count, width))
    kind = np.full((count, width), _PAD_KIND)
    raw_w = np.zeros((count, width))
    pot_w = np.zeros((count, width))
    mana = np.zeros((count, width))
    spl = np.zeros((count, width))
    magical = np.zeros((count, width))
    ratio = np.ones((count, width))
    thr = np.full((count, k_exec), -np.inf)
    bonus = np.zeros((count, k_exec))
    hell_hits: list[float | None] = []
    for row, (tl, const) in enumerate(zip(tls, consts)):
        events = tl.events
        n = len(events)
        hell = None
        if n:
            arrays = _event_arrays(events, tl.stats["mana_max"])
            when[row, :n], kind[row, :n], raw_w[row, :n], pot_w[row, :n] = arrays[:4]
            mana[row, :n], spl[row, :n], magical[row, :n] = arrays[4:7]
            hell = arrays[7]
            idx = np.minimum(3000, np.maximum(0, (when[row, :n] * 100 + 1e-6).astype(np.int64)))
            ratio[row, :n] = _table_array(const["table"])[idx]
        hell_hits.append(hell)
        for col, (threshold, amount) in enumerate(const["executes"]):
            thr[row, col] = threshold
            bonus[row, col] = amount
    valid = kind != _PAD_KIND
    thp = np.maximum(0.0, 1.0 - when / FIGHT)
    low = (ratio <= 0.40) & valid
    exec_mask = (thp[:, :, None] <= thr[:, None, :]) & valid[:, :, None]
    flags = np.array([c["flags"] for c in consts], dtype=np.float64)
    return {
        "kind": kind,
        "raw_w": raw_w,
        "pot_w": pot_w,
        "mana": mana,
        "spl": spl,
        "magical": magical,
        "ratio": ratio,
        "low": low.astype(np.float64),
        "thp": thp,
        "valid": valid.astype(np.float64),
        "exec_mask": exec_mask.astype(np.float64),
        "bonus": bonus,
        "flags": flags,
        "hell_hits": hell_hits,
    }


def columns() -> tuple[str, ...]:
    names = list(SCALAR_COLS)
    for part in BUCKET_PARTS:
        names.extend(f"{part}:{kind}" for kind in BUCKETS)
    return tuple(names)


COLUMNS = columns()


def compile_sums(torch, target, packed: dict) -> np.ndarray:
    """Device part: [timelines, COLUMNS] weighted sums. torch ops only."""

    def up(name):
        return torch.from_numpy(np.ascontiguousarray(packed[name], dtype=np.float32)).to(target)

    kind = up("kind")
    raw_w, pot_w = up("raw_w"), up("pot_w")
    mana, spl, magical = up("mana"), up("spl"), up("magical")
    ratio, low, thp, valid = up("ratio"), up("low"), up("thp"), up("valid")
    exec_mask, bonus, flags = up("exec_mask"), up("bonus"), up("flags")

    def flag(i):
        return flags[:, i : i + 1]

    furnace, glad, crimson, blood_on = flag(0), flag(1), flag(2), flag(3)
    magic_const, phys_const = flag(4), flag(5)
    qt, tlum, pu, ps, ja, evo, fire_m = flag(6), flag(7), flag(8), flag(9), flag(10), flag(11), flag(12)

    def is_kind(name):
        return (kind == float(KIND_IDS[name])).to(torch.float32)

    pet = is_kind("hydra") + is_kind("cleave")
    dealt = 1.0 + furnace * (1.0 - pet) * 0.20 * (1.0 - ratio) + low * (0.15 * glad + 0.15 * crimson)
    raw = raw_w * dealt
    pot = pot_w * dealt

    execute = torch.ones_like(raw)
    for col in range(exec_mask.shape[2]):
        execute = execute * (1.0 + exec_mask[:, :, col] * bonus[:, col : col + 1])
    type_qt = qt * (0.13 + 0.25 * thp)
    phys = (1.0 + phys_const + type_qt) * (1.0 + 0.15 * ja)
    mag = 1.0 + magic_const + type_qt + evo * (0.08 + mana / 7500.0) + 0.05 * tlum
    slope = 0.005 * tlum * torch.ones_like(mag)
    insanity = 1.0 + 0.15 * pu
    mag = mag * insanity
    slope = slope * insanity
    mag = mag + ps * 0.30 * thp
    glass = 1.0 + 0.15 * ja
    mag = mag * glass
    slope = slope * glass
    b = mag + slope * spl
    s = slope

    out = {}
    m = is_kind("auto")
    auto = execute * phys * raw * m
    out["auto_weight"] = auto
    out["soul_weight"] = auto * thp
    out["splash"] = raw * is_kind("splash")
    out["hell_weight"] = raw * is_kind("hellfire")
    out["blood"] = dealt * valid * (1.0 - is_kind("sulfuras_echo")) * blood_on
    pyro = is_kind("pyro")
    pm = pyro * magical
    pr = pyro * (1.0 - magical)
    coef = 1.0 + fire_m * spl
    out["pyro_base"] = pm * b * raw * coef
    out["pyro_slope"] = pm * s * raw * coef
    out["pyro_m_base"] = pm * b * raw * fire_m
    out["pyro_m_slope"] = pm * s * raw * fire_m
    out["pyro_pot_base"] = pm * b * pot
    out["pyro_pot_slope"] = pm * s * pot
    out["pyro_raw_base"] = pr * raw * coef
    out["pyro_raw_mastery"] = pr * raw * fire_m
    hydra, cleave = is_kind("hydra"), is_kind("cleave")
    out["hydra_base"] = hydra * raw
    out["hydra_pot_base"] = hydra * pot
    out["cleave_base"] = cleave * raw
    out["cleave_pot_base"] = cleave * pot
    sulf = is_kind("sulfuras")
    out["sulf_base"] = sulf * b * raw
    out["sulf_slope"] = sulf * s * raw
    out["sulf_echo"] = is_kind("sulfuras_echo") * raw
    for name in BUCKETS:
        mk = is_kind(name)
        out[f"base:{name}"] = mk * b * raw
        out[f"slope:{name}"] = mk * s * raw
        out[f"pot_base:{name}"] = mk * b * pot
        out[f"pot_slope:{name}"] = mk * s * pot
    stacked = torch.stack([out[name] for name in COLUMNS], dim=2).sum(dim=1)
    return stacked.cpu().numpy().astype(np.float64)


def compiled_dict(tl: Timeline, row: np.ndarray, hell_hits) -> dict:
    """Same shape as sunken_sim.mage._compile output."""
    from sunken_sim import mage
    from sunken_sim.shadow import LEVEL

    vals = dict(zip(COLUMNS, (float(v) for v in row)))
    hell_raw = 0.0
    if hell_hits is not None:
        hell_raw = (3 + 3 * LEVEL) * (2 if hell_hits == 1 else 0.5 if hell_hits >= 4 else 1)
    compiled = {
        "spec": tl.spec,
        "glass": 1.15 if mage._has(tl.build, "I0JA") else 1.0,
        "base": {k: vals[f"base:{k}"] for k in BUCKETS},
        "slope": {k: vals[f"slope:{k}"] for k in BUCKETS},
        "pot_base": {k: vals[f"pot_base:{k}"] for k in BUCKETS},
        "pot_slope": {k: vals[f"pot_slope:{k}"] for k in BUCKETS},
        "hell_raw": hell_raw,
        "hydra_slope": 0.0,
        "hydra_pot_slope": 0.0,
        "cleave_slope": 0.0,
        "cleave_pot_slope": 0.0,
        "raw": mage._raws(tl.stats, tl.build),
        "fire_pyro": tl.spec == "fire",
    }
    for name in SCALAR_COLS:
        compiled[name] = vals[name]
    return compiled


class GpuFights(BatchFights):
    """Batched mage fights: CPU timelines, device compile, CPU score."""

    def __init__(self, device, hero: str, spec: str, targets: int) -> None:
        import torch

        assert_gpu_allowed(hero, spec)
        if not gpu_fights_for(hero, spec):
            raise ValueError(f"{hero}/{spec}: no GPU fight kernel")
        self.torch = torch
        self.device = device
        self.target = device.handle if device.gpu else torch.device("cpu")
        self.hero = hero
        self.spec = spec
        self.targets = int(targets)
        self.fights = 0

    def _scores(self, tls: list[Timeline]) -> list[float]:
        from sunken_sim import mage
        from sunken_sim.shadow import FIGHT

        out: list[float] = []
        for begin in range(0, len(tls), MAX_BATCH):
            part = tls[begin : begin + MAX_BATCH]
            packed = pack(part)
            sums = compile_sums(self.torch, self.target, packed)
            for tl, row, hell in zip(part, sums, packed["hell_hits"]):
                total, _sources = mage._score(compiled_dict(tl, row, hell), tl.stats, tl.build, tl.spec)
                out.append(total / FIGHT)
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
            # mage.simulate keeps the first bound spell on ties (strict >).
            if best[index] is None or dps > best[index]:
                best[index] = dps
        return [float(value) for value in best]


def cpu_dps(build, targets: int, spec: str) -> float:
    """Reference: the old CPU sim, untouched."""
    from sunken_sim.mage import simulate

    return simulate(build, targets, spec=spec, use_history=False).dps
