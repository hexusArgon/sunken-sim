# -*- coding: utf-8 -*-
"""Cross-build batching benchmark on the real device engine.

Per hero/spec: K independent sextuple calls (random catalog items, full talent /
glyph lists, as eval_span gives them). Modes, interleaved per repeat:
  seq      engine.finish_sextuple per call (current default path, algebra off)
  seq_alg  same with FARM_HYBRID_ESC_ALGEBRA=1 (best existing per-build path)
  xG       engine.finish_many in groups of G calls (G in --groups), batched ESC
  xaG      same with ESC = guarded algebra per call, lockstep-merged fights
Wall time covers the whole path (packing, GPU timeline, device sync, selection).
Accuracy: talents/glyphs/points must equal 'seq' with min-2 batches (DirectML
batch-1 kernel differs by f32 ulps); dps rel <= 1e-4. Also counts mismatches of
plain seq (no min-2) against that reference.

.venv-dml\\Scripts\\python.exe tools\\_bench_cross_build.py --specs demon_hunter/havoc --k 8 --groups 2,4,8 --repeat 2
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

from farm.hybrid.test_cross_build import _calls, _min2  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs", required=True)
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--groups", default="2,4,8")
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--targets", type=int, default=5)
    ap.add_argument("--no-alg", action="store_true")
    args = ap.parse_args()
    from farm.hybrid.device import detect
    from farm.hybrid.registry import make_engine
    from sunken_sim.shadow import Build

    groups = [int(g) for g in args.groups.split(",") if g and not g.startswith("a")]
    agroups = [int(g[1:]) for g in args.groups.split(",") if g.startswith("a")]
    bad = 0
    grand: dict[str, float] = {}
    for hs in args.specs.split(","):
        hero, spec = hs.split("/")
        eng = make_engine(detect(hero, spec), hero, spec, args.targets)
        calls = _calls(hero, spec, args.k, seed=11)
        os.environ.pop("FARM_HYBRID_ESC_ALGEBRA", None)
        eng.dps_many([Build(frozenset(), frozenset(), calls[0][0], 0, 0, 0, 0)] * 2)  # warm-up
        raw = eng.dps_many
        eng.dps_many = _min2(raw)
        ref = [eng.finish_sextuple(*c) for c in calls]
        eng.dps_many = raw
        modes = ["seq"] + ([] if args.no_alg else ["seq_alg"]) + [f"x{g}" for g in groups]
        modes += [f"xa{g}" for g in agroups]
        times = {m: [] for m in modes}
        plain_mismatch = 0
        for rep in range(args.repeat):
            order = modes[rep % len(modes):] + modes[: rep % len(modes)]
            for m in order:
                if m == "seq_alg":
                    os.environ["FARM_HYBRID_ESC_ALGEBRA"] = "1"
                t0 = time.perf_counter()
                if m.startswith("seq"):
                    got = [eng.finish_sextuple(*c) for c in calls]
                else:
                    alg = m.startswith("xa")
                    g = int(m[2:] if alg else m[1:])
                    got = []
                    for a in range(0, len(calls), g):
                        got.extend(eng.finish_many(calls[a : a + g], esc="algebra" if alg else "batched"))
                times[m].append(time.perf_counter() - t0)
                os.environ.pop("FARM_HYBRID_ESC_ALGEBRA", None)
                for r, x in zip(ref, got):
                    same = x[1:] == r[1:] and abs(x[0] - r[0]) <= 1e-4 * max(1.0, abs(r[0]))
                    if not same:
                        if m.startswith("seq"):
                            plain_mismatch += 1
                        else:
                            bad += 1
                            print(f"  FAIL {hs} {m} r{rep}: {x[0]:.4f} {x[3]} vs {r[0]:.4f} {r[3]}", flush=True)
        med = {m: statistics.median(v) for m, v in times.items()}
        for m in modes:
            grand[m] = grand.get(m, 0.0) + med[m]
        print(f"{hs} K={args.k} median s: " + " ".join(f"{m}={med[m]:.2f}" for m in modes)
              + " | speedup vs seq: " + " ".join(f"{m}={med['seq'] / med[m]:.2f}x" for m in modes if m != "seq")
              + f" | seq-path(no-min2) diffs={plain_mismatch}", flush=True)
    print("TOTAL fails=%d medians-sum: " % bad + " ".join(f"{m}={v:.2f}s" for m, v in grand.items()))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
