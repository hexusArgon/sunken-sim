"""CPU vs GPU fight parity for Mage Fire/Frost (never Arcane).

  .venv-dml\Scripts\python.exe tools\run_hybrid_parity.py --spec fire --n 2000
  .venv-dml\Scripts\python.exe tools\run_hybrid_parity.py --spec frost --n 500 --finish 3

Builds are fixed by --seed: random item chunks from the top-80 space, random
talents/glyphs, random ESC points. Reference is sunken_sim.mage.simulate.
Writes JSON to farm-data-hybrid-smoke/parity-<spec>-<device>.json.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FARM_DATA", str(ROOT / "farm-data-hybrid-smoke"))


def sample_builds(space, items, n: int, seed: int, targets: int):
    from sunken_sim.esc import ESC_ATTRS, ESC_CAP, apply_points, empty_points
    from sunken_sim.shadow import SKILL_POINTS, Build

    rng = random.Random(seed)
    builds = []
    for i in range(n):
        chunk = rng.randrange(space.total)
        equipped = tuple(items[code] for code in space.decode(chunk)[0])
        mode = i % 4
        talents = frozenset()
        glyphs = frozenset()
        if mode >= 1:
            talents = frozenset(rng.sample(list(space.talents), min(space.picks_with, len(space.talents))))
        if mode >= 2:
            glyphs = frozenset(rng.sample(list(space.glyphs), min(space.glyph_picks, len(space.glyphs))))
        build = Build(talents, glyphs, equipped, 0, 0, 0, 0)
        if mode == 3:
            points = empty_points()
            for _ in range(SKILL_POINTS):
                open_attrs = [a for a in ESC_ATTRS if points[a] < ESC_CAP]
                points[rng.choice(open_attrs)] += 1
            build = apply_points(build, points)
        builds.append((chunk, build))
    return builds


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", default="fire")
    parser.add_argument("--n", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=15)
    parser.add_argument("--targets", type=int, default=5)
    parser.add_argument("--top", type=int, default=80)
    parser.add_argument("--finish", type=int, default=0, help="also compare full finish_sextuple on this many chunks")
    args = parser.parse_args()

    from farm.catalog import load
    from farm.hybrid.device import detect
    from farm.hybrid.fight import GpuFights, compare, cpu_dps, gpu_fights_for

    if not gpu_fights_for("mage", args.spec):
        raise SystemExit(f"mage/{args.spec}: GPU fights not allowed")
    device = detect("mage", args.spec)
    space, items = load("mage", args.spec, "mixed", None, args.top)
    builds = sample_builds(space, items, args.n, args.seed, args.targets)
    engine = GpuFights(device, "mage", args.spec, args.targets)

    t0 = time.perf_counter()
    ref = [cpu_dps(b, args.targets, args.spec) for _, b in builds]
    t1 = time.perf_counter()
    got = engine.dps_many([b for _, b in builds])
    t2 = time.perf_counter()
    report = {
        "spec": args.spec,
        "targets": args.targets,
        "seed": args.seed,
        "device": device.kind,
        "device_name": device.name,
        "fights": compare(ref, got),
        "cpu_s": round(t1 - t0, 3),
        "hybrid_s": round(t2 - t1, 3),
        "cpu_ms_per_fight": round(1000 * (t1 - t0) / max(1, len(builds)), 3),
        "hybrid_ms_per_fight": round(1000 * (t2 - t1) / max(1, len(builds)), 3),
    }
    worst = max(range(len(ref)), key=lambda i: abs(ref[i] - got[i])) if ref else None
    if worst is not None:
        report["worst"] = {"chunk": builds[worst][0], "cpu": ref[worst], "gpu": got[worst]}

    if args.finish:
        from farm.score import finish_sextuple

        rng = random.Random(args.seed + 1)
        rows = []
        for _ in range(args.finish):
            chunk = rng.randrange(space.total)
            equipped = tuple(items[code] for code in space.decode(chunk)[0])
            call = (equipped, space.talents, space.glyphs, space.picks_without, space.picks_with, space.glyph_picks)
            a0 = time.perf_counter()
            cpu = finish_sextuple("mage", args.spec, args.targets, *call)
            a1 = time.perf_counter()
            gpu = engine.finish_sextuple(*call)
            a2 = time.perf_counter()
            rows.append(
                {
                    "chunk": chunk,
                    "cpu_dps": cpu[0],
                    "gpu_dps": gpu[0],
                    "rel": abs(cpu[0] - gpu[0]) / max(1.0, abs(cpu[0])),
                    "same_talents": sorted(cpu[1]) == sorted(gpu[1]),
                    "same_glyphs": sorted(cpu[2]) == sorted(gpu[2]),
                    "same_points": dict(cpu[3]) == dict(gpu[3]),
                    "fights": [cpu[4], gpu[4]],
                    "cpu_s": round(a1 - a0, 2),
                    "hybrid_s": round(a2 - a1, 2),
                }
            )
        report["finish"] = rows

    out = Path(os.environ["FARM_DATA"]) / f"parity-{args.spec}-{device.kind}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["fights"]["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
