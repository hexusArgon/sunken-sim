"""Optional native float64 Hydra sum. No import of Numba unless explicitly enabled.

No fastmath, parallelism, changed queue ordering or finite Hydra capacity.
The ordinary list/sum planner is always available if import/compile/execution fails.
"""
_FACTORY = None

def _sum(hydras, now):
    total = 0.0
    for expiry, count in hydras:
        if expiry > now:
            total += count
    return total

def hooks():
    global _FACTORY
    if _FACTORY is None:
        from numba import njit, types
        from numba.typed import List
        native = njit(fastmath=False)(_sum)
        kind = types.UniTuple(types.float64, 2)
        def make(): return List.empty_list(kind)
        # Pay compilation before generating any rows; empty sum must match.
        if native(make(), 0.0) != 0.0: raise RuntimeError("Hydra JIT self-check")
        _FACTORY = (native, make)
    return _FACTORY
