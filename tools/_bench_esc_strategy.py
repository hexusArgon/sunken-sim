# -*- coding: utf-8 -*-
"""Engine-level ESC strategy: FARM_HYBRID_ESC_ALGEBRA=0 (batched) vs 1 (algebra) vs
auto (measured-cost router batched/algebra), through engine.greedy_points on the
real device. Modes interleaved (rotating order), points must equal mode 0.

.venv-dml\\Scripts\\python.exe tools\\_bench_esc_strategy.py --specs demon_hunter/havoc,windmaster/combat --n 3 --repeat 3
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from farm.hybrid import esc_device as ed  # noqa: E402
from farm.hybrid.test_stat_kernel_greedy import _catalog_build  # noqa: E402

MODES = ("0", "1", "auto")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs", required=True)
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--targets", type=int, default=5)
    args = ap.parse_args()
    from farm.hybrid.device import detect
    from farm.hybrid.registry import make_engine

    bad = 0
    tot = {m: 0.0 for m in MODES}
    for hs in args.specs.split(","):
        hero, spec = hs.split("/")
        ed.reset()
        eng = make_engine(detect(hero, spec), hero, spec, args.targets)
        times = {m: [] for m in MODES}
        for rep in range(args.repeat):
            for i in range(args.n):
                b = _catalog_build(hero, spec, i)
                eng.dps_many([b])
                ref = None
                order = MODES[(rep + i) % 3:] + MODES[: (rep + i) % 3]
                res = {}
                for m in order:
                    os.environ["FARM_HYBRID_ESC_ALGEBRA"] = m
                    t0 = time.perf_counter()
                    res[m] = eng.greedy_points(b)
                    times[m].append(time.perf_counter() - t0)
                ref = res["0"]
                for m in MODES:
                    same = res[m][1] == ref[1] and abs(res[m][0] - ref[0]) <= 1e-4 * max(1.0, abs(ref[0]))
                    if not same:
                        bad += 1
                        print(f"  FAIL {hs}[{i}] r{rep} mode={m} {res[m][0]} vs {ref[0]}", flush=True)
        os.environ.pop("FARM_HYBRID_ESC_ALGEBRA", None)
        med = {m: statistics.median(v) for m, v in times.items()}
        for m in MODES:
            tot[m] += sum(times[m])
        rs = [v.summary() for k, v in ed._ROUTERS.items() if k[2] == ("batched", "algebra")]
        r = rs[0] if rs else {}
        print(f"{hs} median batched={med['0']:.3f} algebra={med['1']:.3f} auto={med['auto']:.3f} "
              f"| algebra/batched={med['1'] / med['0']:.2f} auto/batched={med['auto'] / med['0']:.2f} "
              f"| sum auto/batched={sum(times['auto']) / sum(times['0']):.2f} | router cur={r.get('current')} "
              f"sw={r.get('switches')} probes={r.get('probes')} med={r.get('median_s')}", flush=True)
    print(f"TOTAL fails={bad} sums batched={tot['0']:.2f}s algebra={tot['1']:.2f}s ({tot['0'] / tot['1']:.2f}x) "
          f"auto={tot['auto']:.2f}s ({tot['0'] / tot['auto']:.2f}x)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
