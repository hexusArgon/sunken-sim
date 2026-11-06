"""Device side of the ESC guarded event algebra (farm/hybrid/esc_algebra.py).

Three pieces, all opt-in (FARM_HYBRID_ESC_ALGEBRA_DEVICE=cpu|gpu|auto, default cpu):

1. DeviceProgram: the *weight* part of a trace's tape (closure of the event-weight
   nodes) evaluated on the torch device in float32, level by level
   (index_select -> op -> index_copy_), then execute factor * weight and a blocked
   reduction (f32 blocks of BLOCK events on device, f64 over blocks on host).
   Guards are NOT evaluated here: the guard closure stays CPU float64 (numpy),
   exactly as in the CPU route. Results are *approximate* (flagged); the greedy
   recomputes exactly (CPU float64 weights + the exact scorer) every value that is
   within TIE_REL of the step's winner, so picks are those of the exact path as long
   as the f32 error stays below TIE_REL/2. Every exact recompute is also an error
   sample: an error above ERR_LIMIT disables the device route (fail closed).
2. DeviceCache: persistent device buffers per trace (index tensors, base values,
   event gather/execute factors), reused across greedy steps while the trace is
   reused. LRU bounded by entries and bytes; key = (trace token, device, dtype,
   SCHEMA), so a new trace / device / dtype / schema never sees old buffers.
3. Router: picks the cpu or gpu route per call from measured wall time of the whole
   route (leaf packing, upload, kernels, the blocking .cpu() copy, host reduction,
   and for gpu also the exact recomputes it caused). Warmup samples both, then the
   cheaper median wins; the other route is re-probed (gap doubles while it keeps
   losing) and a switch needs HYSTERESIS (no thrash on noise). Forced 'cpu'/'gpu'
   are deterministic. The same Router (arms batched/algebra) picks the ESC greedy
   strategy per hero/spec in engine.py (FARM_HYBRID_ESC_ALGEBRA=auto).
"""

from __future__ import annotations

import itertools
import os
import statistics
import time
from collections import OrderedDict, deque

import numpy as np

SCHEMA = 1
TIE_REL = 1e-4  # relative band around the winner recomputed exactly (= engine DPS_TOL)
ERR_LIMIT = TIE_REL / 4  # observed |approx-exact|/|exact| above this -> device route off
BLOCK = 64  # events per f32 partial sum on device

_TOKENS = itertools.count(1)


def new_token() -> int:
    return next(_TOKENS)


def algebra_mode() -> str:
    """FARM_HYBRID_ESC_ALGEBRA: 0/off | 1/on | auto (default; measured batched vs algebra)."""
    v = os.environ.get("FARM_HYBRID_ESC_ALGEBRA", "auto").strip().lower()
    if v in ("1", "true", "on"):
        return "on"
    return "auto" if v == "auto" else "off"


def device_mode() -> str:
    mode = os.environ.get("FARM_HYBRID_ESC_ALGEBRA_DEVICE", "cpu").strip().lower()
    return mode if mode in ("cpu", "gpu", "auto") else "cpu"


# --- closures ------------------------------------------------------------------------


def closure(program, roots) -> np.ndarray:
    """bool[n]: nodes the roots depend on (incl. roots)."""
    mask = np.zeros(len(program.op), dtype=bool)
    roots = np.asarray(list(roots), dtype=np.int64)
    if len(roots):
        mask[roots] = True
    for _o, ids, ia, ib in reversed(program.groups):
        sel = mask[ids]
        if sel.any():
            mask[ia[sel]] = True
            bb = ib[sel]
            mask[bb[bb >= 0]] = True
    return mask


def masked_groups(program, mask):
    out = []
    for o, ids, ia, ib in program.groups:
        sel = mask[ids]
        if sel.all():
            out.append((o, ids, ia, ib))
        elif sel.any():
            out.append((o, ids[sel], ia[sel], ib[sel]))
    return out


def guard_groups(trace):
    """CPU float64 groups needed by the guards (cached on the trace)."""
    g = getattr(trace, "_guard_groups", None)
    if g is None:
        prog = trace.program
        g = masked_groups(prog, closure(prog, [x[0] for x in prog.guards]))
        trace._guard_groups = g
    return g


# --- persistent device buffers --------------------------------------------------------


class DeviceProgram:
    def __init__(self, trace, torch, device, dtype) -> None:
        from farm.hybrid.esc_algebra import Sym
        from sunken_sim.ledger import KIND_EXEC, KIND_FLAT
        from sunken_sim.shadow import _execute_factor

        prog = trace.program
        # trace_current folds optional Ledger pot_coeff into symbolic weights;
        # this device IR is always four-tuples (including potency dependencies).
        ev_nodes = [w.i for (_t, _n, w, _k) in trace.events if isinstance(w, Sym)]
        mask = closure(prog, ev_nodes)
        self.torch, self.device, self.dtype = torch, device, dtype
        lt = lambda x: torch.as_tensor(np.ascontiguousarray(x, dtype=np.int64), device=device)  # noqa: E731
        # Relayout: leaves first, then the other inputs, then every op group as one
        # contiguous slice -> writes are slice copies (DirectML has no index_copy).
        groups = masked_groups(prog, mask)
        n = len(prog.op)
        computed = np.zeros(n, dtype=bool)
        for _o, ids, _a, _b in groups:
            computed[ids] = True
        leaf_nodes = sorted(prog.leaves)
        is_leaf = np.zeros(n, dtype=bool)
        is_leaf[leaf_nodes] = True
        rest = np.flatnonzero(~computed & ~is_leaf)
        order = np.concatenate([np.asarray(leaf_nodes, dtype=np.int64), rest] + [ids for _o, ids, _a, _b in groups])
        new = np.empty(n, dtype=np.int64)
        new[order] = np.arange(n)
        self.groups = []
        pos = len(leaf_nodes) + len(rest)
        for o, ids, ia, ib in groups:
            self.groups.append((o, pos, pos + len(ids), lt(new[ia]), lt(new[np.where(ib >= 0, ib, ia)])))
            pos += len(ids)
        self.n = n
        self.val0 = torch.as_tensor(np.asarray(prog.val, dtype=np.float32)[order], device=device)
        self.leaf_keys = sorted(set(prog.leaves.values()))
        kidx = {k: j for j, k in enumerate(self.leaf_keys)}
        self.n_leaf = len(leaf_nodes)
        self.leaf_col = [kidx[prog.leaves[x]] for x in leaf_nodes]
        self._new = new
        stats = {"executes": trace.executes}
        E = len(trace.events)
        node = np.zeros(E, dtype=np.int64)
        sym = np.zeros(E, dtype=bool)
        const = np.zeros(E, dtype=np.float64)
        exf = np.ones(E, dtype=np.float64)
        for e, (when, _name, w, kind) in enumerate(trace.events):
            if isinstance(w, Sym):
                node[e], sym[e] = w.i, True
            else:
                const[e] = float(w)
            if kind == KIND_EXEC:
                exf[e] = _execute_factor(stats, when)
            elif kind != KIND_FLAT:
                raise ValueError(f"unknown ledger kind {kind}")
        pad = (-E) % BLOCK
        self.E, self.pad = E, pad
        self.ev_node = lt(new[node])
        self.ev_sym = torch.as_tensor(sym, device=device)
        self.ev_const = torch.as_tensor((const * exf).astype(np.float32), device=device)
        self.ev_exf = torch.as_tensor(exf.astype(np.float32), device=device)
        self.nbytes = int(
            sum(a.numel() * 8 * 2 for _o, _s, _e, a, _b in self.groups) + self.n * 4 + E * (8 + 1 + 4 + 4)
        )

    def score(self, leaf_matrix: np.ndarray) -> np.ndarray:
        """leaf_matrix [T, L] float64 -> dps[T] (float32 algebra, f64 over blocks)."""
        from farm.hybrid.esc_algebra import _ADD, _DIV, _MUL, _NEG, _POW, _SUB
        from sunken_sim.shadow import FIGHT

        torch = self.torch
        T = leaf_matrix.shape[0]
        V = self.val0.unsqueeze(1).repeat(1, T)
        if self.n_leaf:
            L = torch.as_tensor(np.ascontiguousarray(leaf_matrix[:, self.leaf_col].T, dtype=np.float32), device=self.device)
            V[: self.n_leaf] = L
        for o, start, end, ia, ib in self.groups:
            x = V.index_select(0, ia)
            if o == _NEG:
                r = -x
            else:
                y = V.index_select(0, ib)
                if o == _ADD:
                    r = x + y
                elif o == _SUB:
                    r = x - y
                elif o == _MUL:
                    r = x * y
                elif o == _DIV:
                    r = x / y
                elif o == _POW:
                    r = torch.pow(x, y)
                else:
                    raise ValueError(f"op {o}")
            V[start:end] = r
        W = V.index_select(0, self.ev_node) * self.ev_exf.unsqueeze(1)
        A = torch.where(self.ev_sym.unsqueeze(1), W, self.ev_const.unsqueeze(1).expand(-1, T))
        if self.pad:
            A = torch.cat([A, torch.zeros((self.pad, T), dtype=A.dtype, device=self.device)], 0)
        part = A.reshape(-1, BLOCK, T).sum(1)
        host = part.cpu().numpy().astype(np.float64)  # blocking copy = real sync point
        return host.sum(0) / FIGHT


class DeviceCache:
    """LRU of DeviceProgram; bounded by entries and bytes."""

    def __init__(self, max_entries: int = 8, max_bytes: int = 256 << 20) -> None:
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self._d: OrderedDict = OrderedDict()
        self.hits = self.misses = self.evictions = 0

    @property
    def nbytes(self) -> int:
        return sum(v.nbytes for v in self._d.values())

    def __len__(self) -> int:
        return len(self._d)

    def get(self, trace, torch, device, dtype) -> DeviceProgram:
        key = (getattr(trace, "token", None), str(device), str(dtype), SCHEMA)
        if key[0] is None:
            raise ValueError("trace without token")
        prog = self._d.get(key)
        if prog is not None:
            self.hits += 1
            self._d.move_to_end(key)
            return prog
        self.misses += 1
        prog = DeviceProgram(trace, torch, device, dtype)
        self._d[key] = prog
        while len(self._d) > self.max_entries or (len(self._d) > 1 and self.nbytes > self.max_bytes):
            self._d.popitem(last=False)
            self.evictions += 1
        return prog

    def reset(self) -> None:
        self._d.clear()


CACHE = DeviceCache()


# --- measured-cost routing --------------------------------------------------------------


class Router:
    """Measured-cost choice between two exact arms (default cpu/gpu algebra route).

    Forced mode (= an arm name) is deterministic. 'auto': warmup `warm` samples of
    each arm, then the lower median of the last `window` wins; switching needs the
    other arm to be below `hysteresis` x current (noise does not flip it). The loser
    is re-probed after `probe` calls; every probe that confirms it doubles the gap
    (<= max_probe), so a much slower arm costs O(log n) probes. A disabled arm
    (error()) is never chosen again.
    """

    def __init__(self, mode: str = "auto", warm: int = 2, probe: int = 16, hysteresis: float = 0.8,
                 window: int = 8, arms=("cpu", "gpu"), max_probe: int = 1024):
        self.mode, self.warm, self.hyst, self.arms = mode, warm, hysteresis, tuple(arms)
        self.probe0 = self.gap = probe
        self.max_probe = max_probe
        self.t = {a: deque(maxlen=window) for a in self.arms}
        self.current = self.arms[0]
        self.calls = 0
        self.since = 0
        self.disabled: set = set()
        self.max_err = 0.0
        self.err_samples = 0
        self.switches = 0
        self.probes = 0
        self.disabled_note = ""

    @property
    def gpu_ok(self) -> bool:
        return self.arms[1] not in self.disabled

    def _other(self, arm):
        return self.arms[1] if arm == self.arms[0] else self.arms[0]

    def choose(self) -> str:
        self.calls += 1
        if self.mode in self.arms:
            return self.mode if self.mode not in self.disabled else self.arms[0]
        if self.disabled:
            return self.arms[0]
        for r in self.arms[::-1]:
            if len(self.t[r]) < self.warm:
                return r
        self.since += 1
        if self.since >= self.gap:
            self.since = 0
            self.probes += 1
            return self._other(self.current)
        return self.current

    def record(self, route: str, seconds: float) -> None:
        self.t[route].append(seconds)
        if route != self.current and self.mode == "auto" and all(len(v) >= self.warm for v in self.t.values()):
            before = self.current
            self._maybe_switch()
            if self.current == before:  # probe confirmed the loser: back off
                self.gap = min(self.max_probe, 2 * self.gap)
            return
        self._maybe_switch()

    def charge(self, route: str, seconds: float) -> None:
        """Add follow-up cost (exact recomputes) to the route's last sample."""
        if self.t[route]:
            self.t[route][-1] += seconds
            self._maybe_switch()

    def _maybe_switch(self) -> None:
        if self.mode != "auto" or any(len(v) < self.warm for v in self.t.values()):
            return
        other = self._other(self.current)
        if statistics.median(self.t[other]) < self.hyst * statistics.median(self.t[self.current]):
            self.current = other
            self.switches += 1
            self.gap = self.probe0

    def error(self, rel: float) -> None:
        self.err_samples += 1
        self.max_err = max(self.max_err, rel)
        if rel > ERR_LIMIT and self.gpu_ok:
            self.disabled.add(self.arms[1])
            self.disabled_note = f"f32 error {rel:.2e} > {ERR_LIMIT:.1e}"

    def summary(self) -> dict:
        med = {k: (statistics.median(v) if v else None) for k, v in self.t.items()}
        return {
            "mode": self.mode, "current": self.current, "gpu_ok": self.gpu_ok, "switches": self.switches,
            "probes": self.probes, "median_s": med, "max_err": self.max_err, "err_samples": self.err_samples,
            "note": self.disabled_note,
        }


_ROUTERS: dict = {}


def router_for(key, mode: str, arms=("cpu", "gpu"), **kw) -> Router:
    r = _ROUTERS.get((key, mode, arms))
    if r is None:
        r = _ROUTERS[(key, mode, arms)] = Router(mode, arms=arms, **kw)
    return r


def reset() -> None:
    """Drop every device buffer and routing state (device/schema change, tests)."""
    CACHE.reset()
    _ROUTERS.clear()


def timed(fn, *a, **k):
    t0 = time.perf_counter()
    out = fn(*a, **k)
    return out, time.perf_counter() - t0
