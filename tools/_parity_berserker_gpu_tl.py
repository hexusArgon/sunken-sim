# -*- coding: utf-8 -*-
"""Parity: CPU simulate vs GPU-timeline + kind-score for berserker x3."""
from __future__ import annotations

import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FARM_DATA", str(ROOT / "farm-data-hybrid-smoke"))
os.environ["FARM_HYBRID_GPU_TIMELINE"] = "1"

from farm.catalog import load
from farm.hybrid.device import detect
from farm.hybrid.berserker import BerserkerFights
from sunken_sim import berserker as mod


def sample_builds(space, items, n, seed):
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
        if mode >= 1 and space.talents:
            talents = frozenset(
                rng.sample(list(space.talents), min(space.picks_with, len(space.talents)))
            )
        if mode >= 2 and space.glyphs:
            glyphs = frozenset(
                rng.sample(list(space.glyphs), min(space.glyph_picks, len(space.glyphs)))
            )
        build = Build(talents, glyphs, equipped, 0, 0, 0, 0)
        if mode == 3:
            points = empty_points()
            for _ in range(SKILL_POINTS):
                open_attrs = [a for a in ESC_ATTRS if points[a] < ESC_CAP]
                points[rng.choice(open_attrs)] += 1
            build = apply_points(build, points)
        builds.append(build)
    return builds


def run_spec(spec, n=int(os.environ.get("PARITY_N", "8")), seed=42):
    device = detect("berserker", spec)
    print("device", device.kind, device.name, "spec", spec)
    targets_n = 5
    abs_lim = 1e-3
    rel_lim = 1e-4
    space, items = load("berserker", spec, "mixed", None, 80)
    builds = sample_builds(space, items, n, seed=seed + abs(hash(spec)) % 97)
    cpu = [mod.simulate(b, targets_n, spec).dps for b in builds]
    fights = BerserkerFights(device, "berserker", spec, targets_n)
    gpu = fights.dps_many(builds)
    fails = 0
    for i, (c, g) in enumerate(zip(cpu, gpu)):
        abs_e = abs(c - g)
        rel = abs_e / max(1.0, abs(c))
        status = "OK" if (abs_e <= abs_lim or rel <= rel_lim) else "FAIL"
        if status == "FAIL":
            fails += 1
        if status != "OK" or i < 3:
            print(f"{spec}[{i}] cpu={c:.6f} gpu={g:.6f} abs={abs_e:.3e} rel={rel:.3e} {status}")
    print(f"--- {spec} fails={fails}/{len(builds)} ---")
    return fails


def main():
    total = 0
    for spec in ("headhunter", "poison", "fury"):
        total += run_spec(spec)
    print(f"TOTAL fails={total}")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
