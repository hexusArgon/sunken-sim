# -*- coding: utf-8 -*-
"""Guarded event algebra for ESC greedy trials (pilot, opt-in).

One CPU trace of the *current* greedy build replaces the float values of the
stats keys that the step's trials change with ``Sym`` leaves. Every arithmetic
op on a Sym is recorded on a tape; every place where a traced value decides
control flow (``<``, ``==``, ``bool``, ``min``/``max``, ``int``/``floor``,
``float()`` into math.*) records a *guard* with the outcome seen on the
current build. Ledger events then hold Sym weights; ``when`` must stay concrete.

For T trial builds the tape is evaluated vectorised (numpy float64, one column
per trial, ops grouped by topological level). A trial whose guards all hold
takes the identical control path, so its events are the traced events with the
evaluated weights - bit-for-bit the same IEEE ops the CPU sim would do. A trial
with any failed guard, a changed non-float stats key, or an ESC ``*_points``
field read outside stats_of() is not rescored: the caller fights it normally.

Scoring backends for rescored rows:
  cpu     exact replica of ledger.score_events + sum / FIGHT (float64)
  engine  the engine's own kindscore pack + compile_sums (DirectML on desktop),
          i.e. the same GPU kind-score reduction dps_many uses.

DirectML has no reliable float64, so guards and tape values are evaluated on
CPU in float64; only the kind-score reduction runs on the device. Any
exception in the trace (unsupported op on a Sym: hash, format, index, ...) ->
whole step falls back to normal fights.
"""

from __future__ import annotations

import importlib
import math
import operator
import time
from dataclasses import dataclass, field

import numpy as np

from sunken_sim.esc import BUILD_FIELD, ESC_ATTRS, ESC_CAP, apply_points, empty_points


# Ledger kind-heroes: simulate() calls module.stats_of(build), events via sunken_sim.ledger.
ALGEBRA_HEROES = frozenset({
    "berserker", "death_knight", "demon_hunter", "dragon_sentinel", "monk", "necromancer",
    "siren", "tidewarrior", "tinker", "windmaster", "witch_doctor",
})


# stats_of heroes whose simulate() returns plain-dict sources (no Ledger events);
# traced through their per-source totals (FLAT events, see trace_current).
FLAT_SOURCE_HEROES = frozenset({"hunter", "paladin", "rogue", "warlock", "warrior"})
ALGEBRA_HEROES = ALGEBRA_HEROES | FLAT_SOURCE_HEROES


def hero_flat_sources(module) -> bool:
    return module.__name__.rsplit(".", 1)[-1] in FLAT_SOURCE_HEROES


class Untraceable(BaseException):  # not swallowable by `except Exception`
    def __init__(self, msg: str, sym: "Sym | None" = None) -> None:
        super().__init__(msg)
        self.sym = sym


# op codes
_LEAF, _CONST, _ADD, _SUB, _MUL, _DIV, _POW, _NEG, _FLOORDIV, _MOD = range(10)
_BIN = {_ADD: np.add, _SUB: np.subtract, _MUL: np.multiply, _DIV: np.divide, _POW: np.power,
        _FLOORDIV: np.floor_divide, _MOD: np.mod}

# guard kinds on node value x: x < 0, x >= 0, x == 0, x != 0, x > 0, x <= 0
_LT, _GE, _EQ, _NE, _GT, _LE = range(6)
_GCHECK = {_LT: np.less, _GE: np.greater_equal, _EQ: np.equal, _NE: np.not_equal,
           _GT: np.greater, _LE: np.less_equal}


class Tape:
    def __init__(self) -> None:
        self.op: list[int] = []
        self.a: list[int] = []
        self.b: list[int] = []
        self.val: list[float] = []  # concrete value on the current build
        self.const: dict[float, int] = {}
        self.leaf_key: dict[int, str] = {}
        self.guards: list[tuple[int, int]] = []  # (node, kind) over (lhs - rhs) or x

    def _push(self, op, a, b, v) -> int:
        self.op.append(op)
        self.a.append(a)
        self.b.append(b)
        self.val.append(v)
        return len(self.op) - 1

    def leaf(self, key, v) -> "Sym":
        i = self._push(_LEAF, -1, -1, float(v))
        self.leaf_key[i] = key
        return Sym(self, i, float(v))

    def leaves_of(self, nodes) -> set[str]:
        seen: set[int] = set()
        stack = [int(n) for n in nodes]
        out: set[str] = set()
        while stack:
            i = stack.pop()
            if i < 0 or i in seen:
                continue
            seen.add(i)
            if self.op[i] == _LEAF:
                out.add(self.leaf_key[i])
            elif self.op[i] > _CONST:
                stack.append(self.a[i])
                stack.append(self.b[i])
        return out

    def cnode(self, c: float) -> int:
        c = float(c)
        key = (c, math.copysign(1.0, c)) if c == 0.0 else c
        i = self.const.get(key)
        if i is None:
            i = self.const[key] = self._push(_CONST, -1, -1, c)
        return i


_TAPE: Tape | None = None


def _num(x) -> bool:
    return type(x) in (float, int) or (isinstance(x, (np.floating, np.integer)) and not isinstance(x, bool))


class Sym:
    __slots__ = ("t", "i", "v")

    def __init__(self, tape: Tape, index: int, value: float) -> None:
        self.t, self.i, self.v = tape, index, value

    # -- arithmetic -------------------------------------------------------
    def _bin(self, other, op, fn, swap=False):
        t = self.t
        if isinstance(other, Sym):
            if other.t is not t:
                raise Untraceable("foreign tape")
            oi, ov = other.i, other.v
        elif type(other) is bool or _num(other):
            ov = float(other)
            oi = t.cnode(ov)
        else:
            return NotImplemented
        a, b = (oi, self.i) if swap else (self.i, oi)
        av, bv = (ov, self.v) if swap else (self.v, ov)
        if op in (_DIV, _FLOORDIV, _MOD):
            if bv == 0.0:
                raise ZeroDivisionError("float division by zero")
            t.guards.append((b, _NE))
        v = fn(av, bv)
        if type(v) is not float:
            raise Untraceable("non-float result", self)
        return Sym(t, t._push(op, a, b, v), v)

    def __add__(self, o): return self._bin(o, _ADD, operator.add)
    def __radd__(self, o): return self._bin(o, _ADD, operator.add, True)
    def __sub__(self, o): return self._bin(o, _SUB, operator.sub)
    def __rsub__(self, o): return self._bin(o, _SUB, operator.sub, True)
    def __mul__(self, o): return self._bin(o, _MUL, operator.mul)
    def __rmul__(self, o): return self._bin(o, _MUL, operator.mul, True)
    def __truediv__(self, o): return self._bin(o, _DIV, operator.truediv)
    def __rtruediv__(self, o): return self._bin(o, _DIV, operator.truediv, True)

    def __pow__(self, o):
        r = self._bin(o, _POW, operator.pow)
        return r

    def __rpow__(self, o): return self._bin(o, _POW, operator.pow, True)

    def __floordiv__(self, o): raise Untraceable("floordiv", self)
    __rfloordiv__ = __mod__ = __rmod__ = __divmod__ = __rdivmod__ = __floordiv__

    def __neg__(self):
        t = self.t
        return Sym(t, t._push(_NEG, self.i, -1, -self.v), -self.v)

    def __pos__(self):
        return self

    # -- control flow -> guards ---------------------------------------------
    def _cmp(self, other, pyop):
        if isinstance(other, Sym):
            ov = other.v
            diff = self - other
        elif _num(other) or type(other) is bool:
            ov = float(other)
            diff = self - ov
        else:
            raise Untraceable("compare with non-number", self)
        res = pyop(self.v, ov)
        # NB: guard on (self - other); exact for the comparisons used by sims
        # only if a - b preserves the order, which holds for finite IEEE floats
        # (Sterbenz / monotone rounding: a<b <=> a-b<0, a==b <=> a-b==0).
        if pyop is operator.lt:
            kind = _LT if res else _GE
        elif pyop is operator.le:
            kind = _LE if res else _GT
        elif pyop is operator.gt:
            kind = _GT if res else _LE
        elif pyop is operator.ge:
            kind = _GE if res else _LT
        elif pyop is operator.eq:
            kind = _EQ if res else _NE
        else:
            kind = _NE if res else _EQ
        self.t.guards.append((diff.i, kind))
        return res

    def __lt__(self, o): return self._cmp(o, operator.lt)
    def __le__(self, o): return self._cmp(o, operator.le)
    def __gt__(self, o): return self._cmp(o, operator.gt)
    def __ge__(self, o): return self._cmp(o, operator.ge)
    def __eq__(self, o): return self._cmp(o, operator.eq)
    def __ne__(self, o): return self._cmp(o, operator.ne)

    def __bool__(self):
        res = self.v != 0.0
        self.t.guards.append((self.i, _NE if res else _EQ))
        return res

    def _pin(self) -> float:
        """Concretise: guard value == current exactly (trial must match)."""
        self.t.guards.append((self.t._push(_SUB, self.i, self.t.cnode(self.v), 0.0), _EQ))
        return self.v

    def __float__(self): return self._pin()
    def __int__(self): return int(self._pin())
    def __floor__(self): return math.floor(self._pin())
    def __ceil__(self): return math.ceil(self._pin())
    def __trunc__(self): return math.trunc(self._pin())
    def __round__(self, n=None): return round(self._pin(), n) if n is not None else round(self._pin())

    def __abs__(self):
        return self if self._cmp(0.0, operator.ge) else -self

    def __hash__(self): raise Untraceable("hash", self)
    def __index__(self): raise Untraceable("index", self)
    def __format__(self, spec): raise Untraceable("format", self)
    def __str__(self): raise Untraceable("str", self)
    def __repr__(self): return f"Sym#{self.i}({self.v!r})"


# --- program -----------------------------------------------------------------


@dataclass
class Program:
    op: np.ndarray
    a: np.ndarray
    b: np.ndarray
    val: np.ndarray
    leaves: dict  # node -> key
    groups: list  # [(op, ids, a_ids, b_ids)] in dependency order
    guards: list

    @classmethod
    def build(cls, tape: Tape) -> "Program":
        n = len(tape.op)
        op = np.asarray(tape.op, dtype=np.int64)
        a = np.asarray(tape.a, dtype=np.int64)
        b = np.asarray(tape.b, dtype=np.int64)
        level = np.zeros(n, dtype=np.int64)
        for i in range(n):  # tape order is topological
            if op[i] > _CONST:
                la = level[a[i]]
                lb = level[b[i]] if b[i] >= 0 else 0
                level[i] = 1 + (la if la > lb else lb)
        groups = []
        mask = op > _CONST
        if mask.any():
            keys = level[mask] * 16 + op[mask]
            ids = np.nonzero(mask)[0]
            order = np.argsort(keys, kind="stable")
            ids, keys = ids[order], keys[order]
            cuts = np.flatnonzero(np.diff(keys)) + 1
            for chunk in np.split(ids, cuts):
                o = int(op[chunk[0]])
                groups.append((o, chunk, a[chunk], b[chunk]))
        return cls(op, a, b, np.asarray(tape.val), dict(tape.leaf_key), groups, list(tape.guards))

    def evaluate(self, leaf_values: dict, groups=None) -> np.ndarray:
        """leaf_values: key -> float64[T]. Returns node values [n, T].

        groups: subset of self.groups (e.g. the guard closure); other nodes keep
        their traced value."""
        T = len(next(iter(leaf_values.values()))) if leaf_values else 1
        V = np.repeat(self.val[:, None], T, axis=1)
        for node, key in self.leaves.items():
            V[node] = leaf_values[key]
        with np.errstate(all="ignore"):
            for o, ids, ia, ib in self.groups if groups is None else groups:
                if o == _NEG:
                    V[ids] = -V[ia]
                else:
                    V[ids] = _BIN[o](V[ia], V[ib])
        return V

    def guards_ok(self, V: np.ndarray) -> np.ndarray:
        ok = np.ones(V.shape[1], dtype=bool)
        if not self.guards:
            return ok
        nodes = np.asarray([g[0] for g in self.guards])
        kinds = np.asarray([g[1] for g in self.guards])
        for k, fn in _GCHECK.items():
            sel = nodes[kinds == k]
            if len(sel):
                ok &= fn(V[sel], 0.0).all(axis=0)
        ok &= np.isfinite(V).all(axis=0)
        return ok


# --- tracing a kind-hero sim ------------------------------------------------------

_FIELD_TO_ATTR = {v: k for k, v in BUILD_FIELD.items()}


@dataclass
class Trace:
    ok: bool
    note: str = ""
    program: Program | None = None
    events: list = field(default_factory=list)  # (when, name, weight(Sym|float), kind)
    executes: object = None
    fields: frozenset = frozenset()
    nodes: int = 0
    blame: frozenset = frozenset()  # traced keys that caused the failure (retry without them)
    token: int = 0  # unique per successful trace: key of persistent device buffers


class _FieldLog:
    def __init__(self) -> None:
        self.fields: set[str] = set()
        self.active = False


_FIELDS: _FieldLog | None = None
_TRACKED_TYPES: dict = {}


def _tracked_type(base):
    """Build subclass logging ESC *_points reads (stats_of gets the plain build)."""
    cached = _TRACKED_TYPES.get(base)
    if cached is None:
        class TracedBuild(base):  # type: ignore[misc, valid-type]
            def __getattribute__(self, name):
                log = _FIELDS
                if log is not None and name in _FIELD_TO_ATTR:
                    log.fields.add(name)
                return base.__getattribute__(self, name)

        TracedBuild.__name__ = f"Traced{base.__name__}"
        cached = _TRACKED_TYPES[base] = TracedBuild
    return cached


def changed_keys(before: dict, after: dict) -> frozenset:
    missing = object()
    out = set()
    for k in set(before) | set(after):
        a, b = before.get(k, missing), after.get(k, missing)
        if a is missing or b is missing or type(a) is not type(b):
            out.add(k)
        elif isinstance(a, float):
            if not (a == b and math.copysign(1.0, a) == math.copysign(1.0, b)):
                out.add(k)
        else:
            try:
                if not (a == b):
                    out.add(k)
            except Exception:
                out.add(k)
    return frozenset(out)


def trace_current(module, build, targets: int, spec: str, keys: set[str]) -> Trace:
    """Run module.simulate(build) once with stats[k] -> Sym leaf for k in keys."""
    global _TAPE, _FIELDS
    tape = Tape()
    orig = module.stats_of
    tracked = _tracked_type(type(build))(**{f: getattr(build, f) for f in build.__dataclass_fields__})
    log = _FieldLog()
    bad = []

    def patched(b, *args, **kwargs):
        if b is not tracked:
            bad.append("foreign build")
            return orig(b, *args, **kwargs)
        stats = dict(orig(build, *args, **kwargs))
        for key in keys:
            v = stats.get(key)
            if type(v) is not float:
                bad.append(f"{key} not float")
                continue
            stats[key] = tape.leaf(key, v)
        return stats

    prev_fields = _FIELDS
    # Timeline memo (warrior/hunter/paladin/rogue/warlock): its key reads every
    # ESC *_points field and a hit would replay concrete events without guards,
    # while a miss would store Sym events. Trace with an always-miss key and a
    # throwaway memo, restored afterwards.
    memo = getattr(module, "_TIMELINE", None) if hasattr(module, "_timeline_key") else None
    if memo is not None:
        orig_key = module._timeline_key
        module._timeline_key = lambda *_a, **_k: object()
        module._TIMELINE = {}
    module.stats_of = patched
    _FIELDS = log
    _TAPE = tape
    try:
        report = module.simulate(tracked, targets, spec)
    except Untraceable as exc:
        blame = frozenset(tape.leaves_of([exc.sym.i])) if exc.sym is not None else frozenset()
        return Trace(False, f"trace: {exc}", blame=blame)
    except (ZeroDivisionError, TypeError, ValueError, OverflowError) as exc:
        return Trace(False, f"trace: {exc.__class__.__name__}: {exc}")
    finally:
        _TAPE = None
        _FIELDS = prev_fields
        module.stats_of = orig
        if memo is not None:
            module._timeline_key = orig_key
            module._TIMELINE = memo
    if bad:
        return Trace(False, bad[0])
    events = getattr(report, "events", None)
    if events is None and hero_flat_sources(module) and isinstance(getattr(report, "sources", None), dict):
        # stats_of heroes without a Ledger (warrior/hunter/paladin/rogue/warlock):
        # dps == sum(sources.values()) / FIGHT, every per-source total already a
        # tape value -> one FLAT event per source, in dict order (same sum).
        from sunken_sim.ledger import KIND_FLAT

        events = [(0.0, name, value, KIND_FLAT) for name, value in report.sources.items()]
    if events is None:
        return Trace(False, "no ledger events")
    timed = [when.i for when, _name, _w, _k in events if isinstance(when, Sym)]
    if timed:
        return Trace(False, "event time depends on traced stat", blame=frozenset(tape.leaves_of(timed)))
    executes = report.stats.get("executes") if isinstance(report.stats, dict) else None
    from farm.hybrid.esc_device import new_token

    return Trace(
        True, "", Program.build(tape), list(events), executes, frozenset(log.fields), len(tape.op), token=new_token()
    )


def event_weights(trace: Trace, V: np.ndarray) -> np.ndarray:
    """[E, T] float64 event weights for every trial column."""
    T = V.shape[1]
    W = np.empty((len(trace.events), T))
    for e, (_when, _name, w, _k) in enumerate(trace.events):
        W[e] = V[w.i] if isinstance(w, Sym) else float(w)
    return W


def score_cpu(trace: Trace, W: np.ndarray) -> np.ndarray:
    """Exact replica of sum(ledger.score_events(events, stats).values()) / FIGHT."""
    from sunken_sim.ledger import KIND_EXEC, KIND_FLAT
    from sunken_sim.shadow import FIGHT, _execute_factor

    stats = {"executes": trace.executes}
    names: dict[str, int] = {}
    idx = np.empty(len(trace.events), dtype=np.int64)
    amounts = W.copy()
    for e, (when, name, _w, kind) in enumerate(trace.events):
        idx[e] = names.setdefault(name, len(names))
        if kind == KIND_EXEC:
            amounts[e] = W[e] * _execute_factor(stats, when)
        elif kind != KIND_FLAT:
            raise ValueError(f"unknown ledger kind {kind}")
    src = np.zeros((len(names), W.shape[1]))
    np.add.at(src, idx, amounts)  # unbuffered, event order per name (== dict +=)
    # builtin sum() over the per-name floats in dict order: same algorithm as
    # sum(sources.values()) (compensated on Python >= 3.12)
    return np.asarray([sum([float(x) for x in src[:, t]]) / FIGHT for t in range(W.shape[1])])


def score_engine(trace: Trace, W: np.ndarray, torch, target) -> np.ndarray:
    """Same GPU kind-score reduction as KindFights.dps_many (pack + compile_sums)."""
    from farm.hybrid.kindscore import MAX_BATCH, compile_sums, pack
    from sunken_sim.shadow import FIGHT

    stats = {"executes": trace.executes}
    rows = []
    for t in range(W.shape[1]):
        ev = [(when, name, float(W[e, t]), kind) for e, (when, name, _w, kind) in enumerate(trace.events)]
        rows.append((ev, stats))
    out: list[float] = []
    for begin in range(0, len(rows), MAX_BATCH):
        sums = compile_sums(torch, target, pack(rows[begin : begin + MAX_BATCH]))
        out.extend(float(row.sum()) / FIGHT for row in sums)
    return np.asarray(out)


# --- greedy --------------------------------------------------------------------------


MAX_RETRACE = 3


@dataclass
class AlgebraStats:
    traces: int = 0
    trace_fail: int = 0
    rescored: int = 0
    fought: int = 0
    nodes: int = 0
    guards: int = 0
    guard_fail: int = 0
    t_trace: float = 0.0
    t_eval: float = 0.0
    t_score: float = 0.0
    t_fight: float = 0.0
    calls: int = 0  # dps_many calls (GPU timeline batches)
    rounds: int = 0
    wasted: int = 0  # speculative fights after a divergence
    gpu_calls: int = 0  # rescore calls on the device algebra route
    cpu_calls: int = 0  # rescore calls on the CPU float64 algebra route
    approx: int = 0  # trials scored by device f32 algebra
    exactified: int = 0  # of them recomputed exactly (tie band / best)
    validated: int = 0  # trials cross-checked on first device use of a trace
    t_gpu: float = 0.0
    t_exact: float = 0.0
    router: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)


def _changed(before: dict, after: dict):
    return changed_keys(before, after)


def greedy_points_algebra(
    dps_many,
    build,
    hero: str,
    spec: str,
    targets: int,
    *,
    scorer=None,
    total: int | None = None,
    cap: int = ESC_CAP,
    skip: frozenset = frozenset(),
    speculate: bool | str = "auto",
    device=None,
    router=None,
):
    """sunken_sim.esc.greedy_points with guarded-algebra rescoring of trials.

    Round = trace current build, then walk the greedy *speculatively* inside the
    trace's guard region: each step's rescorable trials are scored by the
    algebra; the others (timeline attrs, failed guards) are queued. All queued
    trials of the round go to ONE dps_many call. Then the real greedy is replayed
    with every score known; the first step whose real pick differs from the
    speculative pick (a fought attr won) ends the round, later queued fights are
    discarded, and the next round retraces. Every committed step therefore uses
    exactly the scores the full greedy would see (rescored ones bit-exact with
    score_cpu). speculate=False: one step per round (dps_many every step).

    scorer(trace, W) -> dps[T]; default score_cpu.
    skip: structural attrs (not fought, scored as current; same as stat_kernel).
    device=(torch, target) + router (esc_device.Router): rescoring may run the
    weight algebra on the device in float32 (guards stay CPU float64). Such
    values are approximate; every decision with a competitor within
    esc_device.TIE_REL of the winner recomputes the approximate values exactly
    (CPU float64 + scorer), and so does the returned best, so points equal the
    exact path whenever the f32 error stays below TIE_REL/2 (checked on every
    recompute and on the first device use of each trace; violation -> device off).
    """
    from farm.hybrid import esc_device as ed
    from sunken_sim.shadow import SKILL_POINTS

    module = importlib.import_module(f"sunken_sim.{hero}")
    scorer = scorer or score_cpu
    total = SKILL_POINTS if total is None else total
    info = AlgebraStats()
    samples: list[tuple[int, float]] = []  # (builds, seconds) per dps_many call
    raw_many = dps_many

    def dps_many(builds):  # noqa: F811 - timed wrapper
        t0 = time.perf_counter()
        out = raw_many(builds)
        samples.append((len(builds), time.perf_counter() - t0))
        return out

    def cost_fit():
        """(c0, c1) of t = c0 + c1 * n, or None without two distinct sizes."""
        if len({n for n, _ in samples}) < 2:
            return None
        n = np.asarray([x for x, _ in samples], dtype=float)
        t = np.asarray([y for _, y in samples], dtype=float)
        c1, c0 = np.polyfit(n, t, 1)
        return max(0.0, float(c0)), max(1e-9, float(c1))

    auto = speculate == "auto"
    counts = empty_points()
    current = apply_points(build, counts)
    best = float(dps_many([current])[0])
    info.calls += 1
    excluded: set[str] = set()  # keys that moved the timeline / broke the trace
    done = 0
    depth = total  # adaptive speculation depth (bounds wasted fights after a divergence)
    carry = None  # (trace, its stats, its keys) while current stays inside its guard region
    best_src = None  # (trace, stats, name) when best is a device approximation

    def step_trials(cnt):
        names = [n for n in ESC_ATTRS if cnt[n] < cap]
        trials = {n: apply_points(build, {**cnt, n: cnt[n] + 1}) for n in names}
        cand = [n for n in names if n not in skip]
        return names, trials, cand, {n: module.stats_of(trials[n]) for n in cand}

    validated_tokens: set[int] = set()

    def leaf_values(tr, names, trial_stats):
        return {key: np.asarray([float(trial_stats[n][key]) for n in names]) for key in set(tr.program.leaves.values())}

    def exact_scores(tr, names, trial_stats) -> dict:
        """CPU float64 algebra + scorer (the exact route)."""
        out: dict[str, float] = {}
        if not names:
            return out
        t0 = time.perf_counter()
        lv = leaf_values(tr, names, trial_stats)
        V = tr.program.evaluate(lv) if lv else np.repeat(tr.program.val[:, None], len(names), 1)
        good = tr.program.guards_ok(V)
        sel = [i for i, g in enumerate(good) if g]
        info.guard_fail += len(names) - len(sel)
        info.t_eval += time.perf_counter() - t0
        if sel:
            t0 = time.perf_counter()
            W = event_weights(tr, V[:, sel])
            if W.shape[1] == 1:  # DirectML bmm takes another kernel at batch 1 (differs by f32 ulps)
                W = np.repeat(W, 2, axis=1)
            dps = scorer(tr, W)
            info.t_score += time.perf_counter() - t0
            for j, i in enumerate(sel):
                out[names[i]] = float(dps[j])
        return out

    def device_scores(tr, names, trial_stats):
        """Guards CPU f64 (guard closure only), weights+reduction on device f32."""
        torch, target = device
        lv = leaf_values(tr, names, trial_stats)
        V = tr.program.evaluate(lv, ed.guard_groups(tr)) if lv else np.repeat(tr.program.val[:, None], len(names), 1)
        good = tr.program.guards_ok(V)
        sel = [n for n, g in zip(names, good) if g]
        info.guard_fail += len(names) - len(sel)
        if not sel:
            return {}
        dprog = ed.CACHE.get(tr, torch, target, torch.float32)
        mat = np.asarray([[float(trial_stats[n][k]) for k in dprog.leaf_keys] for n in sel], dtype=np.float64)
        dps = dprog.score(mat.reshape(len(sel), len(dprog.leaf_keys)))
        if not np.isfinite(dps).all():
            return None
        return dict(zip(sel, (float(x) for x in dps)))

    def rescore(tr, tr_stats, tr_keys, cand, trial_stats):
        """-> (scores, approx names)."""
        ok_names = [
            n for n in cand if BUILD_FIELD[n] not in tr.fields and _changed(tr_stats, trial_stats[n]) <= tr_keys
        ]
        if not ok_names:
            return {}, set()
        route = router.choose() if (router is not None and device is not None) else "cpu"
        if route == "gpu":
            t0 = time.perf_counter()
            out = device_scores(tr, ok_names, trial_stats)
            dt = time.perf_counter() - t0
            if out is not None:
                info.gpu_calls += 1
                info.t_gpu += dt
                router.record("gpu", dt)
                if tr.token not in validated_tokens and out:  # first device use of this trace
                    validated_tokens.add(tr.token)
                    exact = exact_scores(tr, list(out), trial_stats)
                    for n, v in out.items():
                        if n in exact:
                            router.error(abs(v - exact[n]) / max(abs(exact[n]), 1e-300))
                    info.validated += len(exact)
                    if set(exact) != set(out):
                        raise RuntimeError("device/CPU guard mismatch")
                    return exact, set()
                info.approx += len(out)
                return out, set(out)
        t0 = time.perf_counter()
        out = exact_scores(tr, ok_names, trial_stats)
        info.cpu_calls += 1
        if router is not None and device is not None:
            router.record("cpu", time.perf_counter() - t0)
        return out, set()

    def _new_trace(names, cand, trial_stats):
        tr = None
        base = module.stats_of(current)
        keys = set()
        for n in cand:
            keys |= _changed(base, trial_stats[n])
        keys = {k for k in keys if type(base.get(k)) is float} - excluded
        if keys:
            t0 = time.perf_counter()
            for _attempt in range(MAX_RETRACE):
                tr = trace_current(module, current, targets, spec, keys)
                info.traces += 1
                if tr.ok or not tr.blame or not (tr.blame & keys):
                    break
                excluded.update(tr.blame)
                keys -= tr.blame
                if not keys:
                    break
            info.t_trace += time.perf_counter() - t0
            if not tr.ok:
                info.trace_fail += 1
                if len(info.notes) < 5:
                    info.notes.append(tr.note)
                tr = None
            else:
                info.nodes += tr.nodes
                info.guards += len(tr.program.guards)
        return tr, base, frozenset(keys)

    def pick_of(names, scores, cur_best, exclude=()):
        pick, pick_dps = None, -1.0
        for n in names:
            if n in exclude:
                continue
            dps = cur_best if n in skip else scores[n]
            if dps > pick_dps:
                pick, pick_dps = n, dps
        return pick, pick_dps

    def exactify(tr, names, trial_stats, scores, approx):
        t0 = time.perf_counter()
        exact = exact_scores(tr, names, trial_stats)
        if set(exact) != set(names):
            raise RuntimeError("exact recompute lost a guard")
        for n in names:
            router.error(abs(scores[n] - exact[n]) / max(abs(exact[n]), 1e-300))
            scores[n] = exact[n]
            approx.discard(n)
        info.exactified += len(names)
        dt = time.perf_counter() - t0
        info.t_exact += dt
        router.charge("gpu", dt)

    def exact_best():
        nonlocal best, best_src
        if best_src is not None:
            tr_, st_, n_ = best_src
            sc = {n_: best}
            exactify(tr_, [n_], {n_: st_}, sc, {n_})
            best, best_src = sc[n_], None

    def decide(names, scores, approx, tr, stats):
        """Greedy pick; values within TIE_REL of the winner are made exact first."""
        for _ in range(len(names) + 2):
            pick, pv = pick_of(names, scores, best)
            band = ed.TIE_REL * abs(pv)
            val = lambda n: best if n in skip else scores[n]  # noqa: E731
            near = [n for n in names if n != pick and abs(val(n) - pv) <= band]
            if not near:
                return pick, pv
            group = near + [pick]
            amb = [n for n in group if n not in skip and n in approx]
            need_best = best_src is not None and any(n in skip for n in group)
            if not amb and not need_best:
                return pick, pv
            if amb:
                exactify(tr, amb, stats, scores, approx)
            if need_best:
                exact_best()
        raise RuntimeError("tie resolution did not converge")

    while done < total:
        names, trials, cand, trial_stats = step_trials(counts)
        if not names:
            break
        info.rounds += 1
        # -- trace the current build (or keep the last one while still inside it) ----
        if carry is not None:
            tr, base, tr_keys = carry
        else:
            tr, base, tr_keys = _new_trace(names, cand, trial_stats)
        spec_now = bool(speculate) and not auto
        if auto and info.rounds > 1:
            fit = cost_fit()
            if fit is not None:
                c0, c1 = fit
                per_step = max(1.0, info.fought / max(1, done))  # fought builds per step so far
                spec_now = c0 > c1 * per_step
        # -- speculative walk inside the guard region -------------------------------
        path = []  # (names, trials, cand, scores, pending, spec_pick, approx, stats)
        s_counts, s_best = dict(counts), best
        s_names, s_trials, s_cand, s_stats = names, trials, cand, trial_stats
        while True:
            scores, approx = rescore(tr, base, tr_keys, s_cand, s_stats) if tr is not None else ({}, set())
            pending = [n for n in s_cand if n not in scores]
            spick, sdps = pick_of(s_names, scores, s_best, exclude=pending)
            path.append((s_names, s_trials, s_cand, scores, pending, spick, approx, s_stats))
            if spick is None or spick in skip or not spec_now:
                break
            if done + len(path) >= total or len(path) >= depth:
                break
            s_counts[spick] += 1
            s_best = sdps
            s_names, s_trials, s_cand, s_stats = step_trials(s_counts)
            if not s_names:
                break
        # -- one batched fight for every queued trial of the round --------------------
        queue = [(k, n) for k, entry in enumerate(path) for n in entry[4]]
        fought: dict[tuple[int, str], float] = {}
        if queue:
            t0 = time.perf_counter()
            res = dps_many([path[k][1][n] for k, n in queue])
            info.t_fight += time.perf_counter() - t0
            info.calls += 1
            info.fought += len(queue)
            fought = {q: float(x) for q, x in zip(queue, res)}
        # -- replay the real greedy -------------------------------------------------
        used = 0
        carry = None
        for k, (p_names, p_trials, p_cand, scores, pending, spick, approx, p_stats) in enumerate(path):
            full = dict(scores)
            for n in pending:
                full[n] = fought[(k, n)]
            if approx or best_src is not None:
                pick, pick_dps = decide(p_names, full, approx, tr, p_stats)
            else:
                pick, pick_dps = pick_of(p_names, full, best)
            info.rescored += len(scores)
            used += len(pending)
            counts[pick] += 1
            current = p_trials[pick]
            if pick in skip:
                pass  # best unchanged (possibly still approximate)
            else:
                best_src = (tr, p_stats[pick], pick) if pick in approx else None
            best = pick_dps
            done += 1
            if pick != spick or pick in pending or pick in skip:
                break
        else:
            if path and tr is not None and pick in path[-1][3]:
                carry = (tr, base, tr_keys)  # last committed pick was rescored: still in region
        info.wasted += len(queue) - used
        committed = k + 1 if path else 0
        if committed < len(path):  # diverged: speculate about as far as we got
            depth = max(2, 2 * committed)
        else:
            depth = min(total, 2 * depth)
    exact_best()
    if router is not None:
        info.router = router.summary()
    return best, counts, info
