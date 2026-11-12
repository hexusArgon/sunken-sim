"""Item-only scan speed of the Death Knight OpenCL kernel on the device: current vs a saved older kernel.

    python tools/dk_gpu_bench.py [old_kernel.py]      # default _tmp/dkcl_before.py

Both kernels score the same 262144 chunks per spec; the checksums must match bit for bit.
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from farm.catalog import load  # noqa: E402
from farm.runner import source_map  # noqa: E402
import farm.hybrid.death_knight_cl as NEW  # noqa: E402


def main() -> None:
    old_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "_tmp" / "dkcl_before.py"
    spec = importlib.util.spec_from_file_location("dkcl_old", old_path)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    n = 262144
    for sp in ("frost", "blood", "unholy"):
        space, items = load("death_knight", sp, "mixed", None, 150)
        sums = {}
        for name, mod in (("old", old), ("new", NEW)):
            eng = mod.DeathKnightCL(space, items, source_map(items), 5, spec=sp)
            eng.bare(10**9, 4096)
            best = None
            for _ in range(3):
                t = time.time()
                dps, _g, status = eng.bare(10**9, n)
                dt = time.time() - t
                best = dt if best is None else min(best, dt)
            sums[name] = float(np.sum(dps)).hex()
            print(f"{sp:7s} {name}: {n / best:12,.0f} rows/s  status {int(np.count_nonzero(status))}  checksum {sums[name]}", flush=True)
        print(f"{sp:7s} same bits: {sums['old'] == sums['new']}", flush=True)


if __name__ == "__main__":
    main()
