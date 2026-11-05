"""Ledger refactor check: old module snapshot vs new simulate (exact dps) + score_events == total."""
import importlib.util, sys, os, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("FARM_DATA", str(ROOT / "farm-data-hybrid-smoke"))
from run_hybrid_parity import sample_builds
from farm.catalog import load
from sunken_sim.ledger import score_events

hero = sys.argv[1]; n = int(sys.argv[2]) if len(sys.argv) > 2 else 120
new = importlib.import_module(f"sunken_sim.{hero}")
spec_ = importlib.util.spec_from_file_location(f"_old_{hero}", ROOT / "_snapshots" / f"{hero}_pre_ledger.py")
old = importlib.util.module_from_spec(spec_); spec_.loader.exec_module(old)
ok = True
for spec in new.SPECS:
    space, items = load(hero, spec, "mixed", None, 80)
    builds = sample_builds(space, items, n, 15, 5)
    worst_old = worst_ev = 0.0; nev = 0; t0 = time.time()
    for _chunk, b in builds:
        for targets in (5, 1):
            a = old.simulate(b, targets, spec); r = new.simulate(b, targets, spec)
            worst_old = max(worst_old, abs(a.dps - r.dps) / max(1.0, abs(a.dps)))
            tot = sum(score_events(r.events, r.stats).values())
            worst_ev = max(worst_ev, abs(tot - r.total) / max(1.0, abs(r.total)))
            nev = max(nev, len(r.events))
            if a.sources.keys() != r.sources.keys() and set(a.sources) != set(r.sources):
                print("  sources keys differ", spec, set(a.sources) ^ set(r.sources)); ok = False
    good = worst_old <= 1e-12 and worst_ev <= 1e-9
    ok &= good
    print(f"{hero}/{spec}: old-vs-new rel {worst_old:.2e}  events-vs-total rel {worst_ev:.2e}  max_events {nev}  {time.time()-t0:.1f}s  {'OK' if good else 'FAIL'}")
print("ALL OK" if ok else "FAILED")
