# -*- coding: utf-8 -*-
"""Repeated benchmark: ESC algebra weight route cpu (numpy f64 + engine kind-score)
vs gpu (device f32 algebra, esc_device.py) vs auto (measured-cost router).

Per hero/spec/build: reference greedy_points_batched(engine.dps_many) once (points
+ time), then R repeats of each route in rotating order (speculate='auto' in all),
fresh Router per route and spec (shared across builds, as in the engine). Checks
points == reference and best rel to reference <= 1e-4 (and == exact cpu route best).

.venv-dml\\Scripts\\python.exe tools\\_bench_esc_device.py --n 2 --repeat 3
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

from farm.hybrid import esc_device as ed  # noqa: E402
from farm.hybrid.esc_algebra import ALGEBRA_HEROES, greedy_points_algebra, score_engine  # noqa: E402
from farm.hybrid.stat_kernel import greedy_points_batched, structural_skip_attrs  # noqa: E402
from farm.hybrid.test_stat_kernel_greedy import _catalog_build  # noqa: E402

ROUTES = ("cpu", "gpu", "auto")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--heroes", default=",".join(sorted(ALGEBRA_HEROES)))
    ap.add_argument("--targets", type=int, default=5)
    ap.add_argument("--routes", default=",".join(ROUTES))
    args = ap.parse_args()
    routes = tuple(args.routes.split(","))
    from farm.hybrid.device import detect
    from farm.hybrid.registry import make_engine

    bad = total = 0
    agg = {"ref": 0.0, **{r: 0.0 for r in routes}}
    for hero in args.heroes.split(","):
        mod = importlib.import_module(f"sunken_sim.{hero}")
        skip = structural_skip_attrs(hero)
        for spec in mod.SPECS:
            device = detect(hero, spec)
            eng = make_engine(device, hero, spec, args.targets)
            many = eng.dps_many
            scorer = lambda tr, W, e=eng: score_engine(tr, W, e.torch, e.target)  # noqa: E731
            routers = {r: ed.Router(r) for r in routes}
            spec_t = {"ref": [], **{r: [] for r in routes}}
            for i in range(args.n):
                build = _catalog_build(hero, spec, i)
                many([build])  # warm-up
                t0 = time.perf_counter()
                ref = greedy_points_batched(many, build, hero=hero)
                spec_t["ref"].append(time.perf_counter() - t0)
                for rep in range(args.repeat):
                    order = routes[rep % len(routes):] + routes[: rep % len(routes)]
                    for route in order:
                        t0 = time.perf_counter()
                        got = greedy_points_algebra(many, build, hero, spec, args.targets, scorer=scorer, skip=skip,
                                                    device=(eng.torch, eng.target), router=routers[route])
                        dt = time.perf_counter() - t0
                        spec_t[route].append(dt)
                        info = got[2]
                        rel = abs(got[0] - ref[0]) / max(1.0, abs(ref[0]))
                        ok = got[1] == ref[1] and rel <= 1e-4
                        total += 1
                        bad += not ok
                        if not ok or rep == 0:
                            print(f"  {hero}/{spec}[{i}] r{rep} {route}: {'OK' if ok else 'FAIL'} rel={rel:.1e} t={dt:.3f}s "
                                  f"gpu={info.gpu_calls} cpu={info.cpu_calls} approx={info.approx} exact={info.exactified} "
                                  f"val={info.validated} t_gpu={info.t_gpu:.3f} t_ev={info.t_eval:.3f} t_sc={info.t_score:.3f} "
                                  f"t_fi={info.t_fight:.3f}", flush=True)
            med = {k: statistics.median(v) for k, v in spec_t.items()}
            for k in agg:
                agg[k] += sum(spec_t[k]) / (1 if k == "ref" else args.repeat)
            summ = {k: routers[k].summary() for k in routes}
            print(f"{hero}/{spec} {device.kind} median " + " ".join(f"{k}={v:.3f}" for k, v in med.items())
                  + " | " + " ".join(f"{k}:cur={v['current']} sw={v['switches']} ok={v['gpu_ok']} err={v['max_err']:.1e}"
                                     for k, v in summ.items() if k != "cpu")
                  + f" | cache h/m/e={ed.CACHE.hits}/{ed.CACHE.misses}/{ed.CACHE.evictions}", flush=True)
    print(f"TOTAL {total - bad}/{total} OK  per-build sums: ref={agg['ref']:.2f}s "
          + " ".join(f"{k}={agg[k]:.2f}s ({agg['ref'] / agg[k]:.2f}x)" for k in routes))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
