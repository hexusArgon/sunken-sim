"""Freeze Python == GPU reference fights before a class's Python model is removed.

    python3.11 tools/make_fixtures.py berserker

For every spec and 5 / 1 targets: random builds over the class's whole item pool (0..6 items, talents,
glyphs, ESC points) plus every build shown in docs/sim-html (top-20 lists). Each case is fought by the
Python sim and by the explicit-pieces kernel; they must agree to the bit. Stored: the build, the DPS
(float.hex) and the sources in Ledger order -> farm/hybrid/fixtures/<hero>.json.
farm/hybrid/test_fixtures.py replays them against the kernel.
"""

from __future__ import annotations

import importlib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CLASS = {"berserker": ("Berserker", "farm.hybrid.berserker_cl", "BerserkerCL")}
RANDOM = 400


def cases_for(hero: str, spec: str, engine, rng) -> list:
    from sunken_sim.esc import ESC_ATTRS

    mod = importlib.import_module(CLASS[hero][1])
    codes_all = [p.code for p in engine.space.pieces]
    out = []
    for _ in range(RANDOM):
        n = rng.choice([0, 1, 1, 2, 3, 6, 6, 6, 6])
        pts = {a: 0 for a in ESC_ATTRS}
        for _ in range(rng.randint(0, 30)):
            pts[rng.choice(ESC_ATTRS)] += 1
        out.append({"items": rng.sample(codes_all, n), "talents": sorted(rng.sample(list(mod.TALENT_BITS), rng.randint(0, 4))),
                    "glyphs": sorted(rng.sample(list(mod.GLYPH_BITS), rng.randint(0, 3))), "points": pts, "kind": "random"})
    page = Path("docs/sim-html/sources") / f"{hero}-{spec}-enriched.json"
    if page.exists():
        d = json.loads(page.read_text(encoding="utf-8"))
        names = engine.space.talent_names
        tcode = {v: k for k, v in names.items()}
        gcode = {v: k for k, v in engine.space.glyph_names.items()}
        for key, runs in d["runs"].items():
            for e in runs:
                out.append({"items": [it["code"] for it in e["items"]], "talents": sorted(tcode[t] for t in e["talents"]),
                            "glyphs": sorted(gcode[g] for g in e["glyphs"]), "points": {a: int(e["points"].get(a, 0)) for a in ESC_ATTRS},
                            "kind": f"html-{key}"})
    return out


def main() -> None:
    from farm import runner as R
    from farm.hybrid import class_cl as C
    from sunken_sim.esc import ESC_ATTRS, apply_points
    from sunken_sim.shadow import Build

    hero = sys.argv[1]
    class_name, modname, clsname = CLASS[hero]
    mod = importlib.import_module(modname)
    sim = importlib.import_module(f"sunken_sim.{hero}")
    space, items = C.full_space(hero, class_name, sim.TALENTS)
    sources = R.source_map(items)
    rng = random.Random(20261121)
    fixture = {"hero": hero, "note": "Python == GPU before the Python model was removed", "cases": []}
    for spec in mod.SPECS:
        for targets in (5, 1):
            engine = getattr(mod, clsname)(space, items, sources, targets, None, spec)
            cases = cases_for(hero, spec, engine, rng)
            picks = [engine.picks_of(c["items"]) for c in cases]
            dps, _g, status = engine.pick(picks, [engine.talent_mask(c["talents"]) for c in cases],
                                          [engine.glyph_mask(c["glyphs"]) for c in cases],
                                          [[c["points"][a] for a in ESC_ATTRS] for c in cases])
            bad = 0
            for c, d, s in zip(cases, dps, status):
                build = apply_points(Build(frozenset(c["talents"]), frozenset(c["glyphs"]), tuple(items[x] for x in c["items"]),
                                           0, 0, 0, 0), c["points"])
                rep = sim.simulate(build, targets, spec)
                if s or float(d) != rep.dps:
                    bad += 1
                    continue
                fixture["cases"].append({**c, "spec": spec, "targets": targets, "dps": float(d).hex(),
                                         "sources": [[k, float(v).hex()] for k, v in rep.sources.items()]})
            print(hero, spec, targets, "cases", len(cases), "mismatch", bad, flush=True)
            if bad:
                raise SystemExit("Python and GPU disagree: fix the kernel before freezing")
    path = Path("farm/hybrid/fixtures") / f"{hero}.json"
    path.write_text(json.dumps(fixture, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("wrote", path, len(fixture["cases"]))


if __name__ == "__main__":
    main()
