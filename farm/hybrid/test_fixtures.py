"""Kernels against the frozen Python == GPU fights (tools/make_fixtures.py).

    python3.11 -m unittest farm.hybrid.test_fixtures

A case marked "incoming": true depends on the incoming-hit model and is checked by
farm/hybrid/test_incoming.py instead (its value changed on purpose when the model changed).
"""

from __future__ import annotations

import importlib
import json
import unittest
from pathlib import Path

FIX = Path(__file__).resolve().parent / "fixtures"
ENGINES = {"berserker": ("Berserker", "farm.hybrid.berserker_cl", "BerserkerCL")}


def replay(hero: str) -> list[str]:
    from farm import runner as R
    from farm.hybrid import class_cl as C
    from sunken_sim.esc import ESC_ATTRS

    class_name, modname, clsname = ENGINES[hero]
    mod = importlib.import_module(modname)
    data = json.loads((FIX / f"{hero}.json").read_text(encoding="utf-8"))
    space, items = C.full_space(hero, class_name, mod.TALENT_NAMES)
    sources = R.source_map(items)
    errors = []
    groups: dict = {}
    for case in data["cases"]:
        if case.get("incoming"):
            continue
        groups.setdefault((case["spec"], case["targets"]), []).append(case)
    for (spec, targets), cases in groups.items():
        engine = getattr(mod, clsname)(space, items, sources, targets, None, spec)
        dps, _g, status = engine.pick([engine.picks_of(c["items"]) for c in cases],
                                      [engine.talent_mask(c["talents"]) for c in cases],
                                      [engine.glyph_mask(c["glyphs"]) for c in cases],
                                      [[c["points"][a] for a in ESC_ATTRS] for c in cases])
        for c, d, s in zip(cases, dps, status):
            if s or float(d).hex() != c["dps"]:
                errors.append(f"{spec} {targets} {c['items']} {c['talents']} {c['glyphs']}: {float(d)!r} != {float.fromhex(c['dps'])!r}")
        for c in cases[:: max(1, len(cases) // 25)]:
            rep = engine.report(c["items"], c["talents"], c["glyphs"], c["points"])
            got = [[k, float(v).hex()] for k, v in rep["sources"].items()]
            if got != c["sources"]:
                errors.append(f"{spec} {targets} {c['items']}: sources differ")
    return errors


def replay_refine(hero: str) -> list[str]:
    """Talent / glyph / ESC refinement of frozen chunks (Python finish_sextuple == GPU refine when frozen)."""
    from farm import runner as R
    from farm.hybrid import class_cl as C
    from farm.hybrid.priest_cl import find_chunk
    from farm.space import Space

    class_name, modname, clsname = ENGINES[hero]
    mod = importlib.import_module(modname)
    data = json.loads((FIX / f"{hero}.json").read_text(encoding="utf-8"))
    _full, items = C.full_space(hero, class_name, mod.TALENT_NAMES)
    errors = []
    for case in data.get("refine", []):
        if case.get("incoming"):
            continue
        pieces = [p for p in _full.pieces if p.code in set(case["items"])]
        space = Space(pieces, case["talent_pool"], case["glyph_pool"], picks_without=case["picks_without"],
                      picks_with=case["picks_with"], talent_names=_full.talent_names, glyph_names=_full.glyph_names)
        sub = {p.code: items[p.code] for p in pieces}
        engine = getattr(mod, clsname)(space, sub, R.source_map(sub), 5, None, case["spec"])
        chunk = find_chunk(space, case["items"])
        equipped = tuple(sub[c] for c in space.decode(chunk)[0])
        got = engine.refine(chunk, equipped, case["talent_pool"], case["glyph_pool"], case["picks_without"],
                            case["picks_with"], case["glyph_picks"])
        want = (case["dps"], case["talents"], case["glyphs"], case["points"], case["fights"])
        have = (float(got[0]).hex(), list(got[1]), list(got[2]), got[3], got[4])
        if have != want:
            errors.append(f"{case['spec']} {case['items']}: {have} != {want}")
    return errors


class FixtureTest(unittest.TestCase):
    def test_berserker_refine(self) -> None:
        errors = replay_refine("berserker")
        self.assertEqual(errors, [])

    def test_berserker(self) -> None:
        errors = replay("berserker")
        self.assertEqual(errors[:10], [], f"{len(errors)} mismatches")


if __name__ == "__main__":
    unittest.main()
