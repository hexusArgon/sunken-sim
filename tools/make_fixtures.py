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

CLASS = {"berserker": ("Berserker", "farm.hybrid.berserker_cl", "BerserkerCL"),
         "death_knight": ("DeathKnight", "farm.hybrid.death_knight_cl", "DeathKnightCL"),
         "demon_hunter": ("DemonHunter", "farm.hybrid.demon_hunter_cl", "DemonHunterCL"),
         "dragon_sentinel": ("DragonSentinel", "farm.hybrid.dragon_sentinel_cl", "DragonSentinelCL"),
         "druid": ("Druid", "farm.hybrid.druid_cl", "DruidCL")}
REFINE = 6  # HTML top builds per spec: Python finish_sextuple == GPU refine (talents, glyphs, ESC points)
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


def refine_cases(hero: str, mod, clsname: str, full, items) -> list:
    """Top-150 refinement of HTML builds: farm.score.finish_sextuple (Python) against engine.refine."""
    from farm import runner as R
    from farm.catalog import load
    from farm.hybrid.priest_cl import find_chunk
    from farm.score import finish_sextuple
    from farm.space import Space

    out = []
    for spec in mod.SPECS:
        page = Path("docs/sim-html/sources") / f"{hero}-{spec}-enriched.json"
        if not page.exists():
            continue
        cat, _ = load(hero=hero, spec=spec, pool="mixed", top=150)
        d = json.loads(page.read_text(encoding="utf-8"))
        seen, builds = set(), []
        for runs in d["runs"].values():
            for e in runs:
                codes = tuple(sorted(it["code"] for it in e["items"]))
                if codes not in seen and len(seen) < REFINE:
                    seen.add(codes)
                    builds.append([it["code"] for it in e["items"]])
        for codes in builds:
            pieces = [p for p in full.pieces if p.code in set(codes)]
            space = Space(pieces, list(cat.talents), list(cat.glyphs), picks_without=cat.picks_without,
                          picks_with=cat.picks_with, talent_names=full.talent_names, glyph_names=full.glyph_names)
            sub = {p.code: items[p.code] for p in pieces}
            engine = getattr(mod, clsname)(space, sub, R.source_map(sub), 5, None, spec)
            chunk = find_chunk(space, codes)
            equipped = tuple(sub[c] for c in space.decode(chunk)[0])
            args = (list(cat.talents), list(cat.glyphs), cat.picks_without, cat.picks_with, cat.glyph_picks)
            got = engine.refine(chunk, equipped, *args)
            want = finish_sextuple(hero, spec, 5, equipped, *args)
            have = (float(got[0]).hex(), list(got[1]), list(got[2]), got[3], got[4])
            ref = (float(want[0]).hex(), list(want[1]), list(want[2]), want[3], want[4])
            if have != ref:
                raise SystemExit(f"refine {spec} {codes}: GPU {have} != Python {ref}")
            out.append({"spec": spec, "top": 150, "items": codes, "dps": have[0], "talents": have[1], "glyphs": have[2],
                        "points": have[3], "fights": have[4], "talent_pool": list(cat.talents), "glyph_pool": list(cat.glyphs),
                        "picks_without": cat.picks_without, "picks_with": cat.picks_with, "glyph_picks": cat.glyph_picks})
            print(hero, spec, "refine", codes, "ok", flush=True)
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
    space, items = C.full_space(hero, class_name, mod.TALENT_NAMES)
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
    fixture["refine"] = refine_cases(hero, mod, clsname, space, items)
    path = Path("farm/hybrid/fixtures") / f"{hero}.json"
    path.write_text(json.dumps(fixture, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("wrote", path, len(fixture["cases"]))


if __name__ == "__main__":
    main()
