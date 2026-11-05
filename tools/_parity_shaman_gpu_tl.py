# -*- coding: utf-8 -*-
"""Parity: CPU simulate vs GPU-timeline + kind-score for shaman elemental."""
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
from farm.hybrid.shaman import ShamanFights, timelines
from farm.hybrid.shaman_gpu_timeline import generate_shaman_timelines
from sunken_sim import shaman as mod


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


def main():
    device = detect("shaman", "elemental")
    import torch

    target = device.handle if device.gpu else torch.device("cpu")
    print("device", device.kind, device.name, "target", target)
    spec = "elemental"
    targets_n = 5
    abs_lim = 1e-3
    rel_lim = 1e-4
    space, items = load("shaman", spec, "mixed", None, 80)
    builds = sample_builds(space, items, 24, seed=42)
    cpu = []
    for b in builds:
        mod._TIMELINE.clear()
        cpu.append(mod.simulate(b, targets_n, spec).dps)
    # expand diamond like dps_many
    flat_builds, flat_keys = [], []
    for b in builds:
        if mod._wears(b, mod.DIAMOND):
            keys = list(mod.buttons(spec))
        else:
            keys = [None]
        for k in keys:
            flat_builds.append(b)
            flat_keys.append(k)
    rows = generate_shaman_timelines(torch, target, flat_builds, spec, targets_n, flat_keys)
    gpu_bundle = {(id(b), k): row for b, k, row in zip(flat_builds, flat_keys, rows)}
    fights = ShamanFights(device, "shaman", spec, targets_n)
    tls = []
    for b in builds:
        tls.extend(timelines(b, targets_n, spec, gpu_bundle=gpu_bundle))
    # best-of for diamond: score all tls then pick best per build like dps_many
    scores = fights._scores(tls)
    # rebuild best per build
    gpu_dps = []
    idx = 0
    for b in builds:
        n = len(timelines(b, targets_n, spec, gpu_bundle=gpu_bundle))
        part = scores[idx : idx + n]
        idx += n
        gpu_dps.append(max(part) if part else 0.0)
    fails = 0
    worst = []
    for i, (c, g) in enumerate(zip(cpu, gpu_dps)):
        abs_e = abs(c - g)
        rel = abs_e / max(1.0, abs(c))
        status = "OK" if (abs_e <= abs_lim or rel <= rel_lim) else "FAIL"
        if status == "FAIL":
            fails += 1
            worst.append((spec, i, c, g, abs_e, rel))
        if status != "OK" or i < 5:
            print(f"{spec}[{i}] cpu={c:.6f} gpu={g:.6f} abs={abs_e:.3e} rel={rel:.3e} {status}")
    print(f"--- {spec} fails={fails}/{len(builds)} ---")
    if worst:
        print("FAILURES", len(worst))
        for w in worst[:30]:
            print(w)
        raise SystemExit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
