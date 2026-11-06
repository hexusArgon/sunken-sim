"""Mage GPU-timeline parity (default arcane; SPEC env: fire/frost/arcane) vs the CPU sim (no silent fallback: calls _mage_batch).

Usage: python tools/_parity_mage_arcane.py [N=8] [targets=1,5] [seed=7]
Checks per build+bound: event count, max |when/hits/raw/pot/mana/splinter| diff,
and final DPS via GpuFights._scores vs cpu_dps (rel <= 1e-4 required).
"""
import os, random, sys, time
SPEC = os.environ.get("SPEC", "arcane")
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import torch
from sunken_sim import mage
from farm.hybrid import fight as F
from farm.hybrid.mage_gpu_timeline import _mage_batch


if os.environ.get("STARVE"):
    # coverage: mana-starved sheets so Evocation / mana ticks actually fire (CPU and GPU
    # both read mage.sheet, so the comparison stays like-for-like)
    _sheet = mage.sheet
    _k = float(os.environ.get("STARVE"))

    def _starved(build):
        st = _sheet(build)
        st["mana_max"] = st["mana_max"] * _k
        st["mana_regen"] = st["mana_regen"] * _k
        return st

    mage.sheet = _starved


def builds_for(n, seed):
    from farm.hybrid.test_cross_build import _calls
    from sunken_sim.shadow import Build
    rng = random.Random(seed)
    out = []
    for eq, tal, gly, p0, p1, gp in _calls("mage", SPEC, n, seed=seed):
        picks = p1 if rng.random() < 0.5 else p0
        talents = frozenset(rng.sample(list(tal), min(picks, len(tal))))
        glyphs = frozenset(rng.sample(list(gly), min(gp, len(gly))))
        pts = [0] * 5
        for _ in range(rng.choice([0, 20, 60])):
            pts[rng.randrange(5)] += 1
        out.append(Build(talents, glyphs, eq, *pts))
    return out


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    tlist = [int(x) for x in (sys.argv[2] if len(sys.argv) > 2 else "1,5").split(",")]
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 7
    builds = builds_for(n, seed)
    worst_ev = 0.0; worst_dps = 0.0; bad = 0; rows = 0
    for targets in tlist:
        flat, keys = [], []
        for b in builds:
            ks = [k for k in mage._buttons(SPEC) if k != "Evocation"] if mage._wears(b, "I00D") else [None]
            for k in ks:
                flat.append(b); keys.append(k)
        t0 = time.perf_counter()
        gpu = _mage_batch(torch, torch.device("cpu"), torch.float64, flat, SPEC, targets, keys)
        t_gpu = time.perf_counter() - t0
        t0 = time.perf_counter()
        cpu_tls = {}
        for b in builds:
            for tl in F.timelines(b, targets, SPEC, cache=False):
                cpu_tls[(id(b), tl.bound)] = tl
        t_cpu = time.perf_counter() - t0
        gtls = []
        for b, k, row in zip(flat, keys, gpu):
            ev, st, sp, evo = row
            ref = cpu_tls[(id(b), k)]
            rows += 1
            d = 0.0
            def _canon(evs):
                # same-time events may come in another order (heap seq); compare canonically
                return sorted(evs, key=lambda e: (round(float(e[0]), 9), str(e[1]), float(e[2]), float(e[3])))
            ev = _canon(ev)
            ref = F.Timeline(ref.build, ref.stats, ref.spec, ref.evocation, _canon(ref.events), ref.bound)
            if len(ev) != len(ref.events) or evo != ref.evocation:
                bad += 1
                print(f"T{targets} bound={k}: events {len(ev)} vs {len(ref.events)} evo {evo}/{ref.evocation}")
                d = float("inf")
            else:
                shown = False
                for i_ev, (a, r) in enumerate(zip(ev, ref.events)):
                    if not shown and (a[1] != r[1] or abs(float(a[0]) - float(r[0])) > 1e-6 or abs(float(a[3]) - float(r[3])) > 1e-6 or abs(float(a[5].get("mana", 0)) - float(r[5].get("mana", 0))) > 1e-6):
                        shown = True
                        print(f"  T{targets} build#{[id(x) for x in builds].index(id(b))} bound={k} first diff #{i_ev}: gpu={a[:5]} m={a[5].get('mana')} | cpu={r[:5]} m={r[5].get('mana')}")
                        for j in range(max(0, i_ev - 3), min(len(ev), i_ev + 2)):
                            print(f"     {j} gpu {ev[j][0]:.4f} {ev[j][1]} mana={ev[j][5].get('mana'):.3f}  cpu {ref.events[j][0]:.4f} {ref.events[j][1]} mana={ref.events[j][5].get('mana'):.3f}")
                    for x, y in zip(a[:5], r[:5]):
                        if isinstance(x, str) or isinstance(y, str):
                            if x != y: d = float("inf")
                        else:
                            d = max(d, abs(float(x) - float(y)))
                    for key in ("mana", "splinter"):
                        d = max(d, abs(float(a[5].get(key, 0.0)) - float(r[5].get(key, 0.0))))
            worst_ev = max(worst_ev, d)
            gtls.append(F.Timeline(b, st, sp, evo, ev, k))
        eng = F.GpuFights.__new__(F.GpuFights)
        eng.torch = torch; eng.target = torch.device("cpu")
        sg = eng._scores(gtls)
        best = {}
        for b, s in zip(flat, sg):
            best[id(b)] = max(best.get(id(b), s), s)
        for b in builds:
            ref = F.cpu_dps(b, targets, SPEC)
            rel = abs(best[id(b)] - ref) / max(1e-9, abs(ref))
            worst_dps = max(worst_dps, rel)
            if rel > 1e-4:
                bad += 1
                print(f"T{targets}: dps gpu {best[id(b)]:.6f} cpu {ref:.6f} rel {rel:.2e}")
        evo = sum(1 for b in builds for _t, nm in mage.simulate(b, targets, None, None, SPEC, use_history=False).actions if nm == "Evocation")
        print(f"T{targets}: evocation casts (cpu, unbound)={evo}")
        print(f"T{targets}: rows={len(flat)} tl_gpu={t_gpu:.2f}s tl_cpu={t_cpu:.2f}s")
    print(f"{SPEC.upper()}_PARITY n={n} rows={rows} bad={bad} max_event_diff={worst_ev:.3e} max_dps_rel={worst_dps:.3e} -> {'PASS' if bad == 0 and worst_ev <= 1e-4 else 'FAIL'}")
    sys.exit(0 if bad == 0 and worst_ev <= 1e-4 else 1)


if __name__ == "__main__":
    main()
