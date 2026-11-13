"""GPU speed of Dragon Sentinel kernel variants (speed only, no parity): python tools/ds_variant_bench.py"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from farm import runner as R
from farm.catalog import load
from farm.hybrid import dragon_sentinel_cl as K
from farm.hybrid import mage_cl

VARIANTS = {"current": {}}


def main():
    base = K.DragonSentinelCL.KERNEL
    for spec in ("obsidian", "ruby", "emerald"):
        space, items = load("dragon_sentinel", spec, "mixed", None, 150)
        sources = R.source_map(items)
        for name, subs in VARIANTS.items():
            src = base
            for a, b in subs.items():
                assert a in src
                src = src.replace(a, b)
            K.DragonSentinelCL.KERNEL = src
            e = mage_cl.make_engine("dragon_sentinel", space, items, sources, 5, spec)
            e.bare(1000, 4096)
            n = 1 << 16
            t = time.time()
            d, g, st = e.bare(5_000_000, n)
            dt = time.time() - t
            print(f"{spec:9s} {name}: {n / dt:,.0f} rows/s  status {int((st != 0).sum())}", flush=True)
        K.DragonSentinelCL.KERNEL = base


if __name__ == "__main__":
    main()
