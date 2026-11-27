"""Exact OpenCL class fights (Shaman, Paladin, Druid, Feral Druid, Hunter, ...): parity with the Python sims and the farm span.

Runs on any OpenCL device with float64 (PoCL on CPU is fine); skips without one.
    python -m unittest farm.hybrid.test_class_cl
"""
import hashlib
import multiprocessing
import random
import unittest

from farm import admission as A
from farm import runner as R
from farm import score as S
from farm.hybrid import class_cl as C
from farm.hybrid import mage_cl

CASES = (("shaman", "restoration"), ("shaman", "enhancement"), ("shaman", "elemental"),
         ("paladin", "retribution"), ("paladin", "protection"), ("paladin", "holy"),
         ("druid", "restoration"), ("druid", "balance"),
         ("dragon_sentinel", "ruby"), ("dragon_sentinel", "obsidian"), ("dragon_sentinel", "emerald"),
         ("feral_druid", "primal"), ("feral_druid", "guardian"), ("feral_druid", "savage"),
         ("hunter", "marksmanship"), ("hunter", "beast_mastery"), ("hunter", "survival"),
         ("monk", "windwalker"), ("monk", "brewmaster"), ("monk", "mistweaver"),
         ("necromancer", "bone"), ("necromancer", "blood"), ("necromancer", "essence"))
_ENGINES = {}


def _engine(hero, spec):
    if (hero, spec) not in _ENGINES:
        try:
            from farm.catalog import load
            space, items = load(hero, spec, "mixed", None, 80)
            sources = R.source_map(items)
            engine = mage_cl.make_engine(hero, space, items, sources, 5, spec)
            _ENGINES[hero, spec] = (engine, space, items, sources)
        except Exception as exc:  # pragma: no cover - environment dependent
            raise unittest.SkipTest(f"no OpenCL float64 device: {exc}")
    return _ENGINES[hero, spec]


def _with(space, code, seed):
    """A random chunk that wears `code`."""
    rng = random.Random(seed)
    for _ in range(200000):
        i = rng.randrange(space.total)
        if code in space.decode(i)[0]:
            return i
    raise AssertionError(code)


def _stub(hero, spec, targets, equipped, *_):
    h = int(hashlib.sha256("".join(i.rawcode for i in equipped).encode()).hexdigest()[:8], 16)
    return 1000.0 + h / 1e6, ("I0F1",), ("I0JA",), {"potency": h % 20}, 607


def _gate():
    ctx = multiprocessing.get_context("spawn")
    lock = ctx.Lock()
    slots = {"__policy__": "bare-top10"}
    for key in A.KEYS:
        slots[key] = (ctx.Array("d", 10), ctx.Value("i", 0), ctx.Array("q", 10))
    return slots, lock


class ClassCLTest(unittest.TestCase):
    def test_bit_exact_random_chunks(self):
        for hero, spec in CASES:
            engine, space, items, sources = _engine(hero, spec)
            check = C.parity(engine, space, items, sources, 5, mage_cl.sample(space, 400, 7))
            self.assertTrue(check["ok"], (hero, spec, check))
            self.assertEqual(check["status_rows"], 0)

    def test_every_piece_is_exact(self):
        for hero, spec in CASES:
            engine, space, items, sources = _engine(hero, spec)
            rng = random.Random(3)
            need = {p.code: 0 for p in space.pieces}
            rows = []
            while any(v < 3 for v in need.values()) and len(rows) < 6000:
                i = rng.randrange(space.total)
                codes = set(space.decode(i)[0])
                if any(need[c] < 3 for c in codes):
                    rows.append(i)
                    for c in codes:
                        need[c] += 1
            self.assertTrue(all(v >= 3 for v in need.values()), (hero, spec))
            check = C.parity(engine, space, items, sources, 5, rows)
            self.assertTrue(check["ok"], (hero, spec, check))

    def test_talent_glyph_esc_fights_are_exact(self):
        for hero, spec in CASES:
            engine, space, items, _sources = _engine(hero, spec)
            builds = C.random_builds(space, 400, 9)
            check = C.parity_full(engine, space, items, 5, builds)
            self.assertTrue(check["ok"], (hero, spec, check))
            check = C.parity_full(engine, space, items, 5, builds, 11)
            self.assertTrue(check["ok"], (hero, spec, "timeline", check))

    def test_refine_matches_finish_sextuple(self):
        specials = {"shaman": ("I00D", "I0BR"), "paladin": ("I0BR", "I0R0"), "druid": ("I00D", "I0BR", "I0R4"),
                    "dragon_sentinel": ("I0BR", "I0TK", "I0TL", "I0TI", "I0TH"),
                    "feral_druid": ("I00D", "I0BR", "I0RV", "I0RW", "I0RY", "I0QN"),
                    "hunter": ("I0BR", "I0T6", "I0T7", "I0T8", "I0T9", "I06B", "I0QN"),
                    "monk": ("I0BR", "I0UA", "I0UC", "I0U9", "I0QN", "I04F"),
                    "necromancer": ("I0BR", "I0R5", "I0R6", "I0R7", "I0R8", "I0UN", "I06B", "I05W", "I0QN")}
        for hero, spec in CASES:
            engine, space, items, _sources = _engine(hero, spec)
            chunks = [mage_cl.sample(space, 1, 5)[0]]
            chunks += [_with(space, code, 17) for code in specials[hero] if code in {p.code for p in space.pieces}]
            for chunk in chunks:
                equipped = tuple(items[c] for c in space.decode(chunk)[0])
                args = (equipped, space.talents, space.glyphs, space.picks_without, space.picks_with, space.glyph_picks)
                got = engine.refine(chunk, *args)
                want = C.finish_reference(hero, spec, 5, equipped, space)
                self.assertEqual(float(got[0]).hex(), float(want[0]).hex(), (hero, spec, chunk))
                self.assertEqual(tuple(got[1]), tuple(want[1]))
                self.assertEqual(tuple(got[2]), tuple(want[2]))
                self.assertEqual(got[3], want[3])
                self.assertEqual(got[4], want[4])

    def test_span_payload_and_gate_match_cpu_runner(self):
        for hero, spec in (("shaman", "enhancement"), ("paladin", "retribution"), ("druid", "balance"),
                           ("dragon_sentinel", "ruby"),
                           ("feral_druid", "savage"), ("hunter", "survival"), ("monk", "windwalker"),
                           ("necromancer", "blood")):
            _engine(hero, spec)
            from farm.catalog import load
            space, items = load(hero, spec, "mixed", None, 80)
            sources = R.source_map(items)
            original = S.finish_sextuple
            refine = mage_cl._REFINE
            S.finish_sextuple = _stub
            mage_cl._ENGINE, mage_cl._ENGINE_NOTE = None, ""
            try:
                out = []
                for fn in (R.eval_span, mage_cl.eval_span):
                    slots, lock = _gate()
                    R.init_worker(space, items, sources, hero, spec, 5, (slots, lock), None)
                    mage_cl._REFINE = False
                    payload = fn(150_000_000, 150_001_500)
                    payload.pop("fire_execution", None)
                    out.append((payload, R.item_bar_snapshot(slots, lock)))
            finally:
                S.finish_sextuple = original
                mage_cl._REFINE = refine
                mage_cl._ENGINE, mage_cl._ENGINE_NOTE = None, ""
            self.assertEqual(out[0], out[1], (hero, spec))
            self.assertGreater(len(out[0][0]["hits"]), 0)

    def test_route_lists_the_new_specs(self):
        from farm.hybrid.opencl_route import SPECS, wanted
        for case in CASES:
            self.assertIn(case, SPECS)
            self.assertIn(case, mage_cl.OPENCL_SPECS)
        self.assertTrue(wanted(dict(hero="paladin", spec="holy", backend="opencl")))
        self.assertFalse(wanted(dict(hero="shaman", spec="elemental", backend="opencl", opencl=False)))
        self.assertFalse(wanted(dict(hero="feral_druid", spec="feral", backend="opencl")))


if __name__ == "__main__":
    unittest.main()
