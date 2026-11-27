# -*- coding: utf-8 -*-
"""Accuracy + speed of the ESC guarded-algebra pilot (farm/hybrid/esc_algebra.py).

  cpu mode (box / any):   reference = stat_kernel.greedy_points_batched on CPU
                          simulate+score_events; pilot = greedy_points_algebra
                          with score_cpu. Expect bit-exact equality.
  engine mode (desktop):  reference = greedy_points_batched(engine.dps_many)
                          (GPU timeline + DirectML kind-score, the production
                          exact path); pilot = greedy_points_algebra(engine.dps_many,
                          scorer=score_engine on the same device). Also checks both
                          against the CPU events reference (tol 1e-4 rel, DPS_TOL).

python tools/_bench_esc_algebra.py --mode cpu --n 2
.venv-dml\\Scripts\\python.exe tools\\_bench_esc_algebra.py --mode engine --n 2 --heroes berserker,necromancer
Timings are wall clock per greedy, including trace/eval/score overhead.
"""
from __future__ import annotations

import argparse
import importlib
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from farm.hybrid.esc_algebra import greedy_points_algebra, score_cpu, score_engine  # noqa: E402
from farm.hybrid.stat_kernel import greedy_points_batched, structural_skip_attrs  # noqa: E402
from farm.hybrid.test_stat_kernel_greedy import _catalog_build, cpu_dps_many  # noqa: E402

HEROES = ("demon_hunter", "dragon_sentinel", "monk", "necromancer",
          "siren", "tidewarrior", "tinker", "windmaster", "witch_doctor")
TOL = 1e-4


class Count:
    def __init__(self, fn):
        self.fn, self.n, self.calls = fn, 0, 0

    def __call__(self, builds):
        self.n += len(builds)
        self.calls += 1
        return self.fn(builds)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("cpu", "engine"), default="cpu")
    ap.add_argument("--n", type=int, default=2)
    ap.add_argument("--heroes", default=",".join(HEROES))
    ap.add_argument("--targets", type=int, default=5)
    args = ap.parse_args()
    bad = total = 0
    t_ref_all = 0.0
    sums = {"alg": 0.0, "spec": 0.0, "auto": 0.0}
    for hero in args.heroes.split(","):
        mod = importlib.import_module(f"sunken_sim.{hero}")
        skip = structural_skip_attrs(hero)
        for spec in mod.SPECS:
            cpu_many = cpu_dps_many(hero, spec, args.targets)
            engine = None
            if args.mode == "engine":
                from farm.hybrid.device import detect
                from farm.hybrid.registry import make_engine

                device = detect(hero, spec)
                engine = make_engine(device, hero, spec, args.targets)
                many = engine.dps_many
                scorer = lambda tr, W, e=engine: score_engine(tr, W, e.torch, e.target)  # noqa: E731
                dev = f"{device.kind}:{getattr(device, 'name', '')}"
            else:
                many, scorer, dev = cpu_many, score_cpu, "cpu"
            for i in range(args.n):
                build = _catalog_build(hero, spec, i)
                if engine is not None:
                    many([build])  # warm-up (kernels, caches) outside timing
                ref_c = Count(many)
                t0 = time.perf_counter()
                ref = greedy_points_batched(ref_c, build, hero=hero)
                t_ref = time.perf_counter() - t0
                runs = {}
                for label, spec_on in (("alg", False), ("spec", True), ("auto", "auto")):
                    c = Count(many)
                    t0 = time.perf_counter()
                    got = greedy_points_algebra(c, build, hero, spec, args.targets, scorer=scorer, skip=skip,
                                                speculate=spec_on)
                    runs[label] = (got, c, time.perf_counter() - t0)
                total += 1
                line_ok = True
                parts = []
                for label, (got, c, t_run) in runs.items():
                    info = got[2]
                    same_pts = got[1] == ref[1]
                    if args.mode == "cpu":
                        ok = got[:2] == ref
                        note = ""
                    else:
                        from sunken_sim.esc import apply_points

                        cpu_ref = cpu_many([apply_points(build, ref[1])])[0]
                        rel = abs(got[0] - ref[0]) / max(1.0, abs(ref[0]))
                        rel_cpu = abs(got[0] - cpu_ref) / max(1.0, abs(cpu_ref))
                        ok = same_pts and rel <= TOL and rel_cpu <= TOL
                        note = f" rel_eng={rel:.1e} rel_cpu={rel_cpu:.1e}"
                    line_ok &= ok
                    sums[label] += t_run
                    parts.append(
                        f"{label}:{'OK' if ok else 'FAIL'}{note} fights={c.n} calls={c.calls} "
                        f"resc={info.rescored} traces={info.traces} gfail={info.guard_fail} wasted={info.wasted} "
                        f"t={t_run:.3f}s[tr {info.t_trace:.2f} ev {info.t_eval:.2f} sc {info.t_score:.2f} fi {info.t_fight:.2f}]"
                    )
                bad += not line_ok
                t_ref_all += t_ref
                print(f"{hero}/{spec}[{i}] {dev} {'OK' if line_ok else 'FAIL'} ref: fights={ref_c.n} calls={ref_c.calls} "
                      f"t={t_ref:.3f}s | " + " | ".join(parts), flush=True)
    print(
        f"TOTAL {total - bad}/{total} OK  t_ref={t_ref_all:.2f}s "
        + " ".join(f"t_{k}={v:.2f}s ({t_ref_all / v:.2f}x)" for k, v in sums.items() if v)
    )
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
