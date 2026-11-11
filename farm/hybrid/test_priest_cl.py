"""Exact OpenCL Priest fights (Shadow, Discipline, Holy): parity with the Python sim and the farm span.

Runs on any OpenCL device with float64 (PoCL on CPU is fine); skips without one.
    python -m unittest farm.hybrid.test_priest_cl
"""
import hashlib
import multiprocessing
import random
import unittest

from farm import admission as A
from farm import runner as R
from farm import score as S
from farm.hybrid import mage_cl
from farm.hybrid import priest_cl as P

SPECS = ("shadow", "discipline", "holy")
_ENGINES = {}


def _engine(spec):
    if spec not in _ENGINES:
        try:
            from farm.catalog import load
            space, items = load("priest", spec, "mixed", None, 80)
            sources = R.source_map(items)
            _ENGINES[spec] = (P.PriestCL(space, items, sources, 5, spec=spec), space, items, sources)
        except Exception as exc:  # pragma: no cover - environment dependent
            raise unittest.SkipTest(f"no OpenCL float64 device: {exc}")
    return _ENGINES[spec]


def _find(space, codes):
    """Chunk index of a six-item multiset (the space ranks multiplicity vectors in order)."""
    order = [p.code for p in space.pieces]

    def vec(cs):
        return tuple(sum(1 for c in cs if c == o) for o in order)

    target = vec(codes)
    lo, hi = (space.count_without, space.total) if "I0IC" in codes else (0, space.count_without)
    while lo < hi:
        mid = (lo + hi) // 2
        if vec(space.decode(mid)[0]) < target:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _stub(hero, spec, targets, equipped, *_):
    h = int(hashlib.sha256("".join(i.rawcode for i in equipped).encode()).hexdigest()[:8], 16)
    return 1000.0 + h / 1e6, ("I0HL",), ("I0JA",), {"potency": h % 20}, 607


def _gate():
    ctx = multiprocessing.get_context("spawn")
    lock = ctx.Lock()
    slots = {"__policy__": "bare-top10"}
    for key in A.KEYS:
        slots[key] = (ctx.Array("d", 10), ctx.Value("i", 0), ctx.Array("q", 10))
    return slots, lock


class PriestCLTest(unittest.TestCase):
    def test_bit_exact_random_chunks(self):
        for spec in SPECS:
            engine, space, items, sources = _engine(spec)
            check = P.parity(engine, space, items, sources, 5, mage_cl.sample(space, 300, 7))
            self.assertTrue(check["ok"], (spec, check))
            self.assertEqual(check["status_rows"], 0)

    def test_every_piece_is_exact(self):
        for spec in SPECS:
            engine, space, items, sources = _engine(spec)
            rng = random.Random(3)
            need = {p.code: 0 for p in space.pieces}
            rows = []
            while any(v < 3 for v in need.values()) and len(rows) < 5000:
                i = rng.randrange(space.total)
                codes = set(space.decode(i)[0])
                if any(need[c] < 3 for c in codes):
                    rows.append(i)
                    for c in codes:
                        need[c] += 1
            self.assertTrue(all(v >= 3 for v in need.values()))
            check = P.parity(engine, space, items, sources, 5, rows)
            self.assertTrue(check["ok"], (spec, check))

    def test_talent_glyph_esc_fights_are_exact(self):
        for spec in SPECS:
            engine, space, items, _sources = _engine(spec)
            builds = P.random_builds(space, 300, 9)
            for mode in (0, 1):  # simulate().dps and the farm.score._priest ESC score
                check = P.parity_full(engine, space, items, 5, builds, mode)
                self.assertTrue(check["ok"], (spec, mode, check))
            check = P.parity_timeline(engine, space, items, 5, builds, 11)
            self.assertTrue(check["ok"], (spec, "timeline", check))

    def test_silent_messenger_uptime_uses_host_exp(self):
        engine, space, items, _sources = _engine("shadow")
        chunk = _find(space, ["I0D8", "I0FW", "I0HZ", "I0MM", "I0NI", "I0QN"])
        from sunken_sim.esc import empty_points

        self.assertEqual(sorted(space.decode(chunk)[0]), sorted(["I0D8", "I0FW", "I0HZ", "I0MM", "I0NI", "I0QN"]))
        builds = []
        for crit in (0, 5, 20):  # Animosity adds 12 crit, so every row bakes the on-crit uptime
            points = empty_points()
            points["crit"] = crit
            builds.append((chunk, (), ("I0HC",), points))
        for mode in (0, 1):
            check = P.parity_full(engine, space, items, 5, builds, mode)
            self.assertTrue(check["ok"], check)
        self.assertGreater(engine.counts["exp_values"], 0)

    def test_refine_matches_finish_sextuple(self):
        cases = [
            # Top-1 sextuple of the Shadow ESC farm run, Cosmic Horrors: 3525.208859618254 (luck 6) since the
            # timeline key holds luck with I0HP (was 3523.828806953591 when luck trials replayed a luck-free fight).
            # Its luck trials
            # reuse earlier timelines in farm.score._priest, which the device refinement replays.
            ("shadow", ["I00D", "I048", "I0FW", "I0JO", "I0NT", "fgrd"], 3525.208859618254),
            ("discipline", None, None),
            ("holy", None, None),
        ]
        for spec, codes, expect in cases:
            engine, space, items, _sources = _engine(spec)
            chunk = _find(space, codes) if codes else mage_cl.sample(space, 1, 5)[0]
            equipped = tuple(items[c] for c in space.decode(chunk)[0])
            args = (equipped, space.talents, space.glyphs, space.picks_without, space.picks_with, space.glyph_picks)
            got = engine.refine(chunk, *args)
            want = P.finish_reference(spec, 5, equipped, space)
            self.assertEqual(float(got[0]).hex(), float(want[0]).hex(), spec)
            self.assertEqual(tuple(got[1]), tuple(want[1]))
            self.assertEqual(tuple(got[2]), tuple(want[2]))
            self.assertEqual(got[3], want[3])
            self.assertEqual(got[4], want[4])
            if expect is not None:
                self.assertEqual(got[0], expect)

    def test_span_payload_and_gate_match_cpu_runner(self):
        # Gate and payload plumbing with a cheap stand-in refinement on both paths;
        # test_refine_matches_finish_sextuple covers the device refinement itself.
        _engine("holy")
        from farm.catalog import load
        space, items = load("priest", "holy", "mixed", None, 80)
        sources = R.source_map(items)
        original = S.finish_sextuple
        refine = mage_cl._REFINE
        S.finish_sextuple = _stub
        mage_cl._ENGINE, mage_cl._ENGINE_NOTE = None, ""
        try:
            out = []
            for fn in (R.eval_span, mage_cl.eval_span):
                slots, lock = _gate()
                R.init_worker(space, items, sources, "priest", "holy", 5, (slots, lock), None)
                mage_cl._REFINE = False
                payload = fn(150_000_000, 150_001_500)
                payload.pop("fire_execution", None)
                out.append((payload, R.item_bar_snapshot(slots, lock)))
        finally:
            S.finish_sextuple = original
            mage_cl._REFINE = refine
            mage_cl._ENGINE, mage_cl._ENGINE_NOTE = None, ""
        self.assertEqual(out[0], out[1])
        self.assertGreater(len(out[0][0]["hits"]), 0)

    def test_route_is_opt_in(self):
        import os

        from farm.hybrid.opencl_route import wanted
        old = os.environ.pop("FARM_OPENCL", None)
        try:
            self.assertFalse(wanted(dict(hero="priest", spec="shadow")))
            self.assertTrue(wanted(dict(hero="priest", spec="shadow", backend="opencl")))
            self.assertTrue(wanted(dict(hero="priest", spec="holy", opencl=True)))
            self.assertTrue(wanted(dict(hero="mage", spec="fire", fire_backend="opencl")))
            self.assertFalse(wanted(dict(hero="mage", spec="fire", fire_backend="hybrid", opencl=False)))
            self.assertFalse(wanted(dict(hero="warlock", spec="affliction", backend="opencl")))
            os.environ["FARM_OPENCL"] = "priest,mage:frost"
            self.assertTrue(wanted(dict(hero="priest", spec="discipline")))
            self.assertTrue(wanted(dict(hero="mage", spec="frost")))
            self.assertFalse(wanted(dict(hero="mage", spec="arcane")))
            self.assertFalse(wanted(dict(hero="priest", spec="shadow", opencl=False)))
        finally:
            os.environ.pop("FARM_OPENCL", None)
            if old is not None:
                os.environ["FARM_OPENCL"] = old


if __name__ == "__main__":
    unittest.main()
