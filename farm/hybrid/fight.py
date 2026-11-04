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

Arcane Mage is hard-locked to the CPU sim and never reaches this module.
"""

from __future__ import annotations

import itertools
from contextlib import contextmanager
from dataclasses import dataclass

import numpy as np

from farm.hybrid.lock import assert_gpu_allowed, cpu_locked

# Specs whose fights may run through the GPU compile stage.
GPU_FIGHT_SPECS: frozenset[tuple[str, str]] = frozenset({("mage", "fire"), ("mage", "frost")})
DPS_TOL = 1e-4  # relative; DirectML sums in float32
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


def timelines(build, targets: int, spec: str) -> list[Timeline]:
    """CPU part. One timeline, or one per bindable spell when the build wears I00D."""
    from sunken_sim import mage

    bounds: list[str | None] = [None]
    if mage._wears(build, "I00D"):
        bounds = [name for name in mage._buttons(spec) if name != "Evocation"]
    out = []
    with _capture() as sink:
        for bound in bounds:
            mage.simulate(build, targets, None, bound, spec, use_history=False)
            events, _build, stats, used_spec, evocation = sink.pop()
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
    kid = KIND_IDS.get
    for row, (tl, const) in enumerate(zip(tls, consts)):
        events = tl.events
        n = len(events)
        hell = None
        if n:
            mana_max = tl.stats["mana_max"]
            when[row, :n] = [ev[0] for ev in events]
            kind[row, :n] = [kid(ev[1], _OTHER_KIND) for ev in events]
            raw_w[row, :n] = [ev[3] for ev in events]
            pot_w[row, :n] = [ev[4] for ev in events]
            mana[row, :n] = [ev[5].get("mana", mana_max) for ev in events]
            spl[row, :n] = [ev[5].get("splinter", 0.0) for ev in events]
            magical[row, :n] = [1.0 if ev[5].get("magical") else 0.0 for ev in events]
            for ev in events:
                if ev[1] == "hellfire":
                    hell = ev[2]
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


class GpuFights:
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

    def greedy_points(self, build) -> tuple[float, dict[str, int]]:
        """sunken_sim.esc.greedy_points with each step's trials in one batch."""
        from sunken_sim.esc import ESC_ATTRS, ESC_CAP, apply_points, empty_points
        from sunken_sim.shadow import SKILL_POINTS

        counts = empty_points()
        best = self.dps_many([apply_points(build, counts)])[0]
        for _ in range(SKILL_POINTS):
            names = [name for name in ESC_ATTRS if counts[name] < ESC_CAP]
            if not names:
                break
            trials = []
            for name in names:
                trial = dict(counts)
                trial[name] += 1
                trials.append(apply_points(build, trial))
            scores = self.dps_many(trials)
            pick, pick_dps = None, -1.0
            for name, dps in zip(names, scores):
                if dps > pick_dps:
                    pick, pick_dps = name, dps
            counts[pick] += 1
            best = pick_dps
        return best, counts

    def finish_sextuple(self, equipped, talent_codes, glyph_codes, picks_without, picks_with, glyph_picks):
        """farm.score.finish_sextuple, batched. Same return shape."""
        from sunken_sim.esc import ESC_ATTRS, points_payload
        from sunken_sim.shadow import MIND_AMPLIFIER, SKILL_POINTS, Build

        picks = picks_with if any(item.rawcode == MIND_AMPLIFIER for item in equipped) else picks_without
        combos = list(itertools.combinations(talent_codes, picks))
        scores = self.dps_many([Build(frozenset(c), frozenset(), equipped, 0, 0, 0, 0) for c in combos])
        best_dps, best_talents = -1.0, ()
        for combo, dps in zip(combos, scores):
            if dps > best_dps:
                best_dps, best_talents = dps, combo
        glyph_combos = list(itertools.combinations(glyph_codes, glyph_picks))
        scores = self.dps_many(
            [Build(frozenset(best_talents), frozenset(c), equipped, 0, 0, 0, 0) for c in glyph_combos]
        )
        best_glyphs = ()
        for combo, dps in zip(glyph_combos, scores):
            if dps > best_dps:
                best_dps, best_glyphs = dps, combo
        pointed, points = self.greedy_points(Build(frozenset(best_talents), frozenset(best_glyphs), equipped, 0, 0, 0, 0))
        fights = len(combos) + len(glyph_combos) + SKILL_POINTS * len(ESC_ATTRS)
        return pointed, best_talents, best_glyphs, points_payload(points), fights


def cpu_dps(build, targets: int, spec: str) -> float:
    """Reference: the old CPU sim, untouched."""
    from sunken_sim.mage import simulate

    return simulate(build, targets, spec=spec, use_history=False).dps


def compare(reference: list[float], other: list[float]) -> dict:
    worst_abs = 0.0
    worst_rel = 0.0
    for a, b in zip(reference, other):
        diff = abs(a - b)
        worst_abs = max(worst_abs, diff)
        worst_rel = max(worst_rel, diff / max(1.0, abs(a)))
    return {
        "n": len(reference),
        "max_abs": worst_abs,
        "max_rel": worst_rel,
        "tol_rel": DPS_TOL,
        "ok": len(reference) == len(other) and worst_rel <= DPS_TOL,
    }


# --- farm worker side -------------------------------------------------------

SUB_SPAN = 256  # chunks per device batch inside one eval_span
SELF_CHECK = 8  # bare fights checked against the CPU sim per process

_ENGINE = None
_ENGINE_STATE = None  # None: not built yet, "gpu": engine ok, "cpu": use the old eval_span
_ENGINE_NOTE = ""


def _engine():
    global _ENGINE, _ENGINE_STATE, _ENGINE_NOTE
    if _ENGINE_STATE is not None:
        return _ENGINE if _ENGINE_STATE == "gpu" else None
    from farm import runner as R

    try:
        if not gpu_fights_for(R._HERO, R._SPEC):
            raise ValueError(f"{R._HERO}/{R._SPEC} not a GPU fight spec")
        import torch

        torch.set_num_threads(1)
        from farm.hybrid.device import detect

        _ENGINE = GpuFights(detect(R._HERO, R._SPEC), R._HERO, R._SPEC, R._TARGETS)
        _ENGINE_STATE = "pending"
    except Exception as exc:
        _ENGINE, _ENGINE_STATE, _ENGINE_NOTE = None, "cpu", f"{exc.__class__.__name__}: {exc}"
        print(f"hybrid: CPU fights in this worker ({_ENGINE_NOTE})", flush=True)
    return _ENGINE


def _self_check(builds, got) -> bool:
    global _ENGINE, _ENGINE_STATE, _ENGINE_NOTE
    from farm import runner as R

    ref = [cpu_dps(b, R._TARGETS, R._SPEC) for b in builds[:SELF_CHECK]]
    res = compare(ref, got[:SELF_CHECK])
    if res["ok"]:
        _ENGINE_STATE = "gpu"
        return True
    _ENGINE, _ENGINE_STATE, _ENGINE_NOTE = None, "cpu", f"self-check failed max_rel={res['max_rel']:.3g}"
    print(f"hybrid: CPU fights in this worker ({_ENGINE_NOTE})", flush=True)
    return False


def eval_span(start: int, stop: int) -> dict:
    """farm.runner.eval_span with batched GPU fights. Same payload, same top-10 gate."""
    from farm import runner as R
    from farm.score import finish_sextuple
    from sunken_sim.shadow import Build

    engine = _engine()
    if engine is None:
        return R.eval_span(start, stop)
    space = R._SPACE
    hits: list[dict] = []
    fights = 0
    errors = 0
    error = ""
    done = start
    index = start
    while index < stop:
        if R._STOP is not None and R._STOP.is_set():
            break
        end = min(stop, index + SUB_SPAN)
        try:
            rows = []
            for chunk in range(index, end):
                item_codes, _t, _g = space.decode(chunk)
                equipped = tuple(R._ITEMS[code] for code in item_codes)
                sources = [R._SOURCES.get(item.rawcode, "drop") for item in equipped]
                rows.append((chunk, equipped, sources, R.build_group(sources)))
            bare_builds = [Build(frozenset(), frozenset(), row[1], 0, 0, 0, 0) for row in rows]
            bares = engine.dps_many(bare_builds)
            if _ENGINE_STATE == "pending" and not _self_check(bare_builds, bares):
                sub = R.eval_span(index, stop)
                hits.extend(sub["hits"])
                fights += sub["fights"]
                errors += sub["errors"]
                error = error or sub["error"]
                done = sub["done"]
                break
        except Exception as exc:
            sub = R.eval_span(index, end)
            hits.extend(sub["hits"])
            fights += sub["fights"]
            errors += sub["errors"]
            error = error or sub["error"] or f"hybrid batch {index}: {exc}"
            done = sub["done"]
            if done < end:
                break
            index = end
            continue
        for (chunk, equipped, sources, group), bare in zip(rows, bares):
            fights += 1
            if not R.claim_item_bars(bare, group):
                continue
            call = (equipped, space.talents, space.glyphs, space.picks_without, space.picks_with, space.glyph_picks)
            try:
                try:
                    dps, talent_codes, glyph_codes, points, extra = engine.finish_sextuple(*call)
                except Exception:
                    dps, talent_codes, glyph_codes, points, extra = finish_sextuple(R._HERO, R._SPEC, R._TARGETS, *call)
                fights += extra
                hits.append(
                    {
                        "dps": dps,
                        "item_dps": bare,
                        "fights": extra + 1,
                        "chunk": chunk,
                        "group": group,
                        "items": [
                            {"name": item.name, "code": item.rawcode, "source": source}
                            for item, source in zip(equipped, sources)
                        ],
                        "talents": sorted(space.talent_names.get(code, code) for code in talent_codes),
                        "glyphs": sorted(space.glyph_names.get(code, code) for code in glyph_codes),
                        "points": dict(points),
                    }
                )
            except Exception as exc:
                errors += 1
                if not error:
                    error = f"{chunk}: {exc}"
        done = end
        index = end
    return {"start": start, "done": done, "fights": fights, "hits": R._compact(hits), "errors": errors, "error": error}
