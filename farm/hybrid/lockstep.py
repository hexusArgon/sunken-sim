"""Run several independent per-build searches with their fights merged into shared batches.

Each search is a callable f(dps_many) -> result (e.g. esc_algebra.greedy_points_algebra
bound to one build). Every search runs in its own thread, but only ONE thread runs at a
time (baton passing): a search runs until it asks for fights, then parks; when every
live search is parked or finished, all parked requests go to one dps_many (row order,
chunked, never a 1-build call) and each search gets exactly its own slice back. So the
Python-side state (module.stats_of patching in traces, global tapes, routers) is never
touched by two searches at once, the schedule is deterministic, and a search sees the
same values it would see alone (DirectML values are batch-invariant for batch >= 2).
"""

from __future__ import annotations

import threading


class _Abort(BaseException):
    pass


def run_lockstep(searches, dps_many, chunk):
    """searches: list of f(proxy) -> result. chunk(dps_many, builds) -> list[float]."""
    n = len(searches)
    go = [threading.Event() for _ in range(n)]
    back = [threading.Event() for _ in range(n)]
    req: list = [None] * n
    res: list = [None] * n
    out: list = [None] * n
    err: list = [None] * n
    finished = [False] * n
    stats = {"calls": 0, "builds": 0, "requests": 0}

    def proxy_for(i):
        def proxy(builds):
            req[i] = list(builds)
            back[i].set()
            go[i].wait()
            go[i].clear()
            r = res[i]
            res[i] = None
            if r is _Abort:
                raise _Abort()
            return r

        return proxy

    def body(i):
        go[i].wait()
        go[i].clear()
        try:
            out[i] = searches[i](proxy_for(i))
        except _Abort:
            pass
        except BaseException as exc:  # noqa: BLE001 - re-raised by the scheduler
            err[i] = exc
        finished[i] = True
        back[i].set()

    threads = [threading.Thread(target=body, args=(i,), daemon=True) for i in range(n)]
    for t in threads:
        t.start()
    runnable = list(range(n))
    try:
        while True:
            for i in runnable:
                back[i].clear()
                go[i].set()
                back[i].wait()
                if err[i] is not None:
                    raise err[i]
            pending = [i for i in range(n) if not finished[i]]
            if not pending:
                break
            flat, cuts = [], []
            for i in pending:
                cuts.append((i, len(flat), len(req[i])))
                flat.extend(req[i])
                stats["requests"] += 1
            vals = chunk(dps_many, flat) if flat else []
            stats["calls"] += 1
            stats["builds"] += len(flat)
            for i, off, k in cuts:
                res[i] = vals[off : off + k]
                req[i] = None
            runnable = pending
    except BaseException:
        for i in range(n):
            if not finished[i]:
                res[i] = _Abort
                back[i].clear()
                go[i].set()
                back[i].wait(timeout=30)
        raise
    finally:
        for t in threads:
            t.join(timeout=30)
    return out, stats
