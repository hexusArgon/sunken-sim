# -*- coding: utf-8 -*-
"""Guarded ESC algebra (CPU scorer) vs full esc.greedy_points on the CPU sim.

python tools/_esc_algebra_parity.py [N_PER_SPEC=2] [hero,hero,...]
Points must be identical; also prints rescored/fought counts.
"""
from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from farm.hybrid import esc_algebra as A  # noqa: E402
from farm.hybrid.stat_kernel import structural_skip_attrs  # noqa: E402
from farm.hybrid.test_stat_kernel_greedy import _catalog_build  # noqa: E402


def cpu_dps_many(hero, spec, targets=5):
    mod = importlib.import_module(f"sunken_sim.{hero}")

    def many(builds):
        return [float(mod.simulate(b, targets, spec).dps) for b in builds]

    return many
from sunken_sim.esc import apply_points, greedy_points  # noqa: E402

HEROES = tuple(sorted(A.FLAT_SOURCE_HEROES))


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    heroes = sys.argv[2].split(",") if len(sys.argv) > 2 else HEROES
    total = fails = 0
    for hero in heroes:
        mod = importlib.import_module(f"sunken_sim.{hero}")
        for spec in mod.SPECS:
            many = cpu_dps_many(hero, spec)
            for i in range(n):
                build = _catalog_build(hero, spec, i)
                calls = [0, 0]

                def counted(bs):
                    calls[0] += 1
                    calls[1] += len(bs)
                    return many(bs)

                t0 = time.perf_counter()
                ref = greedy_points(lambda c: many([apply_points(build, c)])[0])
                t1 = time.perf_counter()
                got = A.greedy_points_algebra(counted, build, hero, spec, 5, skip=structural_skip_attrs(hero))
                t2 = time.perf_counter()
                ok = got[1] == ref[1] and abs(got[0] - ref[0]) <= 1e-9 * max(1.0, abs(ref[0]))
                total += 1
                fails += not ok
                print(f"{hero}/{spec}[{i}] {'OK' if ok else 'FAIL'} ref={ref[0]:.6f} got={got[0]:.6f} "
                      f"fights={calls[1]} calls={calls[0]} t_ref={t1 - t0:.2f}s t_alg={t2 - t1:.2f}s", flush=True)
    print(f"TOTAL {total - fails}/{total} OK")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
