"""Kernels against the frozen Python == GPU fights (tools/make_fixtures.py).

    python3.11 -m unittest farm.hybrid.test_fixtures

A case marked "incoming": true depends on the incoming-hit model and is checked by
farm/hybrid/test_incoming.py instead (its value changed on purpose when the model changed); "model_fix": <why>
marks a case whose value changed with a deliberate fix of the kernel (e.g. the Death Knight Fire Orb splash).
"""

from __future__ import annotations

import importlib
import json
import unittest
from pathlib import Path

FIX = Path(__file__).resolve().parent / "fixtures"
ENGINES = {"berserker": ("Berserker", "farm.hybrid.berserker_cl", "BerserkerCL"),
           "death_knight": ("DeathKnight", "farm.hybrid.death_knight_cl", "DeathKnightCL"),
           "demon_hunter": ("DemonHunter", "farm.hybrid.demon_hunter_cl", "DemonHunterCL"),
           "dragon_sentinel": ("DragonSentinel", "farm.hybrid.dragon_sentinel_cl", "DragonSentinelCL"),
           "druid": ("Druid", "farm.hybrid.druid_cl", "DruidCL"),
           "feral_druid": ("FeralDruid", "farm.hybrid.feral_druid_cl", "FeralDruidCL"),
           "hunter": ("Hunter", "farm.hybrid.hunter_cl", "HunterCL")}


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
        if C.fixture_value(case) is None:
            continue
        groups.setdefault((case["spec"], case["targets"]), []).append(case)
    for (spec, targets), cases in groups.items():
        engine = getattr(mod, clsname)(space, items, sources, targets, None, spec)
        dps, _g, status = engine.pick([engine.picks_of(c["items"]) for c in cases],
                                      [engine.talent_mask(c["talents"]) for c in cases],
                                      [engine.glyph_mask(c["glyphs"]) for c in cases],
                                      [[c["points"][a] for a in ESC_ATTRS] for c in cases])
        for c, d, s in zip(cases, dps, status):
            if s or float(d).hex() != C.fixture_value(c):
                errors.append(f"{spec} {targets} {c['items']} {c['talents']} {c['glyphs']}: {float(d)!r} != "
                              f"{float.fromhex(C.fixture_value(c))!r}")
        frozen = [c for c in cases if C.fixture_value(c) == c["dps"]]
        for c in frozen[:: max(1, len(frozen) // 25)]:
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
        if case.get("incoming") or case.get("model_fix"):
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

    def test_death_knight_refine(self) -> None:
        errors = replay_refine("death_knight")
        self.assertEqual(errors, [])

    def test_death_knight(self) -> None:
        errors = replay("death_knight")
        self.assertEqual(errors[:10], [], f"{len(errors)} mismatches")

    def test_demon_hunter_refine(self) -> None:
        errors = replay_refine("demon_hunter")
        self.assertEqual(errors, [])

    def test_demon_hunter(self) -> None:
        errors = replay("demon_hunter")
        self.assertEqual(errors[:10], [], f"{len(errors)} mismatches")

    def test_dragon_sentinel_refine(self) -> None:
        errors = replay_refine("dragon_sentinel")
        self.assertEqual(errors, [])

    def test_dragon_sentinel(self) -> None:
        errors = replay("dragon_sentinel")
        self.assertEqual(errors[:10], [], f"{len(errors)} mismatches")

    def test_druid_refine(self) -> None:
        errors = replay_refine("druid")
        self.assertEqual(errors, [])

    def test_druid(self) -> None:
        errors = replay("druid")
        self.assertEqual(errors[:10], [], f"{len(errors)} mismatches")

    def test_feral_druid_refine(self) -> None:
        errors = replay_refine("feral_druid")
        self.assertFalse(errors, errors[:3])

    def test_feral_druid(self) -> None:
        errors = replay("feral_druid")
        self.assertFalse(errors, errors[:3])

    def test_hunter_refine(self) -> None:
        errors = replay_refine("hunter")
        self.assertFalse(errors, errors[:3])

    def test_hunter(self) -> None:
        errors = replay("hunter")
        self.assertFalse(errors, errors[:3])


if __name__ == "__main__":
    unittest.main()
