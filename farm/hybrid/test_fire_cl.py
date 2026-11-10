"""Exact OpenCL bare Fire scan: parity with the Python sim and gate-equivalent spans.

Runs on any OpenCL device with float64 (PoCL on CPU is fine); skips without one.
    python -m unittest farm.hybrid.test_fire_cl
"""
import hashlib
import multiprocessing
import unittest

import numpy as np

from farm import admission as A
from farm import runner as R
from farm import score as S
from farm.hybrid import fire_cl


def _engine():
    try:
        from farm.catalog import load
        space, items = load("mage", "fire", "mixed", None, 80)
        sources = R.source_map(items)
        return fire_cl.FireCL(space, items, sources, 5), space, items, sources
    except Exception as exc:  # pragma: no cover - environment dependent
        raise unittest.SkipTest(f"no OpenCL float64 device: {exc}")


def _stub(hero, spec, targets, equipped, *_):
    h = int(hashlib.sha256("".join(i.rawcode for i in equipped).encode()).hexdigest()[:8], 16)
    return 1000.0 + h / 1e6, ("I0KU",), ("I0JA",), {"crit": h % 20}, 915


def _gate():
    ctx = multiprocessing.get_context("spawn")
    lock = ctx.Lock()
    slots = {"__policy__": "bare-top10"}
    for key in A.KEYS:
        slots[key] = (ctx.Array("d", 10), ctx.Value("i", 0), ctx.Array("q", 10))
    return slots, lock


class FireCLTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine, cls.space, cls.items, cls.sources = _engine()

    def test_bit_exact_random_chunks(self):
        check = fire_cl.parity(self.engine, self.space, self.items, self.sources, 5, fire_cl.sample(self.space, 300, 7))
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["status_rows"], 0)

    def test_every_piece_is_exact(self):
        import random
        rng = random.Random(3)
        need = {p.code: 0 for p in self.space.pieces}
        rows = []
        while any(v < 3 for v in need.values()) and len(rows) < 5000:
            i = rng.randrange(self.space.total)
            codes = set(self.space.decode(i)[0])
            if any(need[c] < 3 for c in codes):
                rows.append(i)
                for c in codes:
                    need[c] += 1
        self.assertTrue(all(v >= 3 for v in need.values()))
        check = fire_cl.parity(self.engine, self.space, self.items, self.sources, 5, rows)
        self.assertTrue(check["ok"], check)

    def test_talent_glyph_esc_fights_are_exact(self):
        check = fire_cl.parity_full(self.engine, self.space, self.items, 5, fire_cl.random_builds(self.space, 400, 9))
        self.assertTrue(check["ok"], check)

    def test_refine_matches_finish_sextuple(self):
        for chunk in (56_041_056, 182_191_945):  # two winners of the finished Top-80 run
            equipped = tuple(self.items[c] for c in self.space.decode(chunk)[0])
            args = (equipped, self.space.talents, self.space.glyphs, self.space.picks_without,
                    self.space.picks_with, self.space.glyph_picks)
            got = self.engine.refine(chunk, *args)
            want = S.finish_sextuple("mage", "fire", 5, *args)
            self.assertEqual(float(got[0]).hex(), float(want[0]).hex())
            self.assertEqual(tuple(got[1]), tuple(want[1]))
            self.assertEqual(tuple(got[2]), tuple(want[2]))
            self.assertEqual(got[3], want[3])
            self.assertEqual(got[4], want[4])

    def test_prefilter_never_drops_an_admission(self):
        dps = np.array([5.0, 1.0, 7.0, 2.0, 9.0])
        group = np.array([1, 2, 3, 0, 2], dtype=np.uint8)
        snap = {"overall": [{"chunk": i, "dps": 6.0 + i} for i in range(10)],
                "shop": [{"chunk": i, "dps": 4.0} for i in range(10)],
                "drop": [{"chunk": i, "dps": 1.5} for i in range(9)]}
        # overall floor 6, shop floor 4, drop underfilled: shop 5>4, drop rows always, overall 7>6 and 9>6
        self.assertEqual(list(fire_cl.candidates(dps, group, snap)), [0, 1, 2, 4])

    def test_span_payload_and_gate_match_cpu_runner(self):
        # Gate and payload plumbing with a cheap stand-in refinement on both paths;
        # test_refine_matches_finish_sextuple covers the device refinement itself.
        original = S.finish_sextuple
        refine = fire_cl._REFINE
        S.finish_sextuple = _stub
        fire_cl._REFINE = False
        try:
            out = []
            for fn in (R.eval_span, fire_cl.eval_span):
                slots, lock = _gate()
                R.init_worker(self.space, self.items, self.sources, "mage", "fire", 5, (slots, lock), None)
                payload = fn(150_000_000, 150_001_500)
                payload.pop("fire_execution", None)
                out.append((payload, R.item_bar_snapshot(slots, lock)))
        finally:
            S.finish_sextuple = original
            fire_cl._REFINE = refine
        self.assertEqual(out[0], out[1])
        self.assertGreater(len(out[0][0]["hits"]), 0)

    def test_route_is_opt_in(self):
        from farm.hybrid.fire_route import select
        self.assertEqual(select(dict(hero="mage", spec="fire"))["selected"], "hybrid")
        self.assertEqual(select(dict(hero="mage", spec="fire", fire_backend="opencl"))["selected"], "opencl")
        self.assertIsNone(select(dict(hero="mage", spec="frost", fire_backend="opencl")))


if __name__ == "__main__":
    unittest.main()
