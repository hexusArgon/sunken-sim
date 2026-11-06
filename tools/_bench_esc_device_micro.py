# -*- coding: utf-8 -*-
"""Per-call cost of the ESC algebra rescoring routes on real trial columns.

For each hero/spec/build: trace the build over its first-step ESC trials, then time
(interleaved, --reps each, after warmup) the full route as the greedy runs it:
  cpu   = numpy f64 full tape + guards + score_engine (pack + compile_sums on device)
  gpu   = numpy f64 guard closure + guards + device f32 weights/reduction (cached buffers)
  nocache = gpu route but buffers rebuilt every call (what persistence saves)
Both include host packing, upload and the blocking device->host copy.

.venv-dml\\Scripts\\python.exe tools\\_bench_esc_device_micro.py --n 2 --reps 15
"""
from __future__ import annotations

import argparse
import importlib
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from farm.hybrid import esc_algebra as A  # noqa: E402
from farm.hybrid import esc_device as ed  # noqa: E402
from farm.hybrid.test_stat_kernel_greedy import _catalog_build  # noqa: E402
from sunken_sim.esc import BUILD_FIELD, ESC_ATTRS, apply_points  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2)
    ap.add_argument("--reps", type=int, default=15)
    ap.add_argument("--heroes", default=",".join(sorted(A.ALGEBRA_HEROES)))
    ap.add_argument("--targets", type=int, default=5)
    args = ap.parse_args()
    import torch
    from farm.hybrid.device import detect

    tot = {"cpu": 0.0, "gpu": 0.0, "nocache": 0.0}
    worst = 0.0
    for hero in args.heroes.split(","):
        mod = importlib.import_module(f"sunken_sim.{hero}")
        for spec in mod.SPECS:
            dev = detect(hero, spec)
            target = dev.handle if dev.gpu else torch.device("cpu")
            for i in range(args.n):
                b = _catalog_build(hero, spec, i)
                base = mod.stats_of(b)
                trials = {a: mod.stats_of(apply_points(b, {a: 1})) for a in ESC_ATTRS}
                keys = set()
                for st in trials.values():
                    keys |= A.changed_keys(base, st)
                keys = {k for k in keys if type(base.get(k)) is float}
                for _ in range(4):
                    tr = A.trace_current(mod, b, args.targets, spec, keys)
                    if tr.ok or not tr.blame:
                        break
                    keys -= tr.blame
                if not tr.ok:
                    print(f"{hero}/{spec}[{i}] no trace: {tr.note}")
                    continue
                names = [a for a in ESC_ATTRS if BUILD_FIELD[a] not in tr.fields and A.changed_keys(base, trials[a]) <= keys]
                lk = sorted(set(tr.program.leaves.values()))
                if not names or not lk:
                    print(f"{hero}/{spec}[{i}] nothing rescorable")
                    continue

                def leafv():
                    return {k: np.asarray([float(trials[n][k]) for n in names]) for k in lk}

                def cpu():
                    V = tr.program.evaluate(leafv())
                    ok = tr.program.guards_ok(V)
                    sel = [j for j, g in enumerate(ok) if g]
                    W = A.event_weights(tr, V[:, sel])
                    if W.shape[1] == 1:
                        W = np.repeat(W, 2, 1)
                    return A.score_engine(tr, W, torch, target)[: len(sel)], sel

                def gpu(cache=True):
                    V = tr.program.evaluate(leafv(), ed.guard_groups(tr))
                    ok = tr.program.guards_ok(V)
                    sel = [j for j, g in enumerate(ok) if g]
                    dp = ed.CACHE.get(tr, torch, target, torch.float32) if cache else ed.DeviceProgram(tr, torch, target, torch.float32)
                    mat = np.asarray([[float(trials[names[j]][k]) for k in dp.leaf_keys] for j in sel])
                    return dp.score(mat), sel

                (c_ref, sel), _ = cpu(), gpu()
                g_val, _ = gpu()
                err = float(np.max(np.abs(g_val - c_ref) / np.abs(c_ref))) if len(sel) else 0.0
                worst = max(worst, err)
                t = {"cpu": [], "gpu": [], "nocache": []}
                for _r in range(args.reps):
                    for k, fn in (("cpu", cpu), ("gpu", gpu), ("nocache", lambda: gpu(False))):
                        t0 = time.perf_counter()
                        fn()
                        t[k].append(time.perf_counter() - t0)
                med = {k: statistics.median(v) for k, v in t.items()}
                p90 = {k: sorted(v)[int(0.9 * (len(v) - 1))] for k, v in t.items()}
                for k in tot:
                    tot[k] += med[k]
                dp = ed.CACHE.get(tr, torch, target, torch.float32)
                print(f"{hero}/{spec}[{i}] {dev.kind} T={len(names)} ok={len(sel)} nodes={len(tr.program.op)} "
                      f"grp={len(tr.program.groups)} gguard={len(ed.guard_groups(tr))} gdev={len(dp.groups)} ev={dp.E} "
                      f"err={err:.1e} | ms med/p90 cpu={1e3*med['cpu']:.2f}/{1e3*p90['cpu']:.2f} "
                      f"gpu={1e3*med['gpu']:.2f}/{1e3*p90['gpu']:.2f} nocache={1e3*med['nocache']:.2f} "
                      f"gpu/cpu={med['gpu']/med['cpu']:.2f}", flush=True)
    print(f"TOTAL medians cpu={1e3*tot['cpu']:.1f}ms gpu={1e3*tot['gpu']:.1f}ms nocache={1e3*tot['nocache']:.1f}ms "
          f"gpu/cpu={tot['gpu']/tot['cpu']:.2f} worst_err={worst:.1e} (ERR_LIMIT {ed.ERR_LIMIT:.0e})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
