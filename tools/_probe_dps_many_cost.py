"""Fit wall t = c0 + c1*n of engine.dps_many (whole call incl. sync) per spec."""
import statistics, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from farm.hybrid.device import detect
from farm.hybrid.registry import make_engine
from farm.hybrid.test_cross_build import _calls
from sunken_sim.shadow import Build
for hs in sys.argv[1].split(","):
    hero, spec = hs.split("/")
    eng = make_engine(detect(hero, spec), hero, spec, 5)
    eqs = [c[0] for c in _calls(hero, spec, 64, seed=5)]
    pool = [Build(frozenset(), frozenset(), e, 0, 0, 0, 0) for e in eqs]
    eng.dps_many(pool[:4])
    ns, ts = [], []
    for n in (2, 4, 9, 18, 36, 64):
        for _ in range(3):
            bs = (pool * 8)[:n]
            t0 = time.perf_counter(); eng.dps_many(bs); ts.append(time.perf_counter() - t0); ns.append(n)
    c1, c0 = np.polyfit(ns, ts, 1)
    med = {n: statistics.median([t for m, t in zip(ns, ts) if m == n]) for n in sorted(set(ns))}
    print(f"{hs} c0={1e3*c0:.2f}ms c1={1e3*c1:.2f}ms/build " + " ".join(f"n{n}={1e3*v:.1f}" for n, v in med.items()), flush=True)
