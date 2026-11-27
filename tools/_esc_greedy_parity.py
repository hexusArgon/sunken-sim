# -*- coding: utf-8 -*-
"""Sweep: stat_kernel.greedy_points_batched vs full esc.greedy_points (CPU, no torch).

python tools/_esc_greedy_parity.py [N_PER_SPEC=2] [hero,hero,...]
Same sample as farm/hybrid/test_stat_kernel_greedy.py (farm.catalog mixed/80,
random.Random(7)); 11 Ledger heroes x specs x N builds (N=2 -> 62 cases).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from farm.hybrid.stat_kernel import greedy_points_batched  # noqa: E402
from farm.hybrid.test_stat_kernel_greedy import _catalog_build, cpu_dps_many  # noqa: E402
from sunken_sim.esc import apply_points, greedy_points  # noqa: E402

HEROES = ("demon_hunter", "dragon_sentinel", "monk", "necromancer",
          "siren", "tidewarrior", "tinker", "windmaster", "witch_doctor")


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
                ref = greedy_points(lambda c: many([apply_points(build, c)])[0])
                got = greedy_points_batched(many, build, hero=hero)
                ok = got == ref
                total += 1
                fails += not ok
                print(f"{hero}/{spec}[{i}] {'OK' if ok else 'FAIL'} ref={ref[0]:.6f} got={got[0]:.6f}", flush=True)
    print(f"TOTAL {total - fails}/{total} OK")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
