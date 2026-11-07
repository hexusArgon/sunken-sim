# -*- coding: utf-8 -*-
"""Cross-build + ESC algebra (lockstep) and cross-sub-span queueing in eval_span.

python -m unittest farm.hybrid.test_cross_algebra
"""

from __future__ import annotations

import os
import unittest

from farm.hybrid import engine as E
from farm.hybrid.lockstep import run_lockstep
from farm.hybrid.test_cross_build import Recorder, _calls, _fake, _space
from farm.hybrid.test_stat_kernel_greedy import cpu_dps_many


class _Env:
    def __init__(self, **kv):
        self.kv, self.old = kv, {}

    def __enter__(self):
        for k, v in self.kv.items():
            self.old[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def __exit__(self, *a):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class LockstepTests(unittest.TestCase):
    def test_slices_order_and_merging(self):
        def search(k, steps):
            def run(many):
                seen = []
                for s in range(steps):
                    seen.append(many([(k, s, j) for j in range(k + 1)]))
                return seen
            return run

        rec = Recorder(lambda bs: [float(100 * b[0] + 10 * b[1] + b[2]) for b in bs])
        out, st = run_lockstep([search(k, 3 + k) for k in range(4)], rec, E.chunked_many)
        for k, seen in enumerate(out):
            self.assertEqual(seen, [[float(100 * k + 10 * s + j) for j in range(k + 1)] for s in range(3 + k)])
        self.assertEqual(st["calls"], 6)  # longest search: 6 steps, all merged
        self.assertTrue(all(x >= 2 for x in rec.sizes))

    def test_error_propagates_and_threads_end(self):
        def bad(many):
            many([1, 2])
            raise ValueError("boom")

        def good(many):
            for _ in range(5):
                many([1, 2, 3])
            return "ok"

        with self.assertRaises(ValueError):
            run_lockstep([good, bad, good], lambda bs: [0.0] * len(bs), E.chunked_many)
        with self.assertRaises(RuntimeError):
            run_lockstep([good, good], lambda bs: (_ for _ in ()).throw(RuntimeError("dev")), E.chunked_many)


class CrossAlgebraTests(unittest.TestCase):
    def test_finish_many_algebra_equals_sequential(self):
        for hero, spec in (("demon_hunter", "havoc"), ("necromancer", "essence")):
            many = cpu_dps_many(hero, spec)
            calls = _calls(hero, spec, 3)
            eng = _fake(hero, spec, many)
            with _Env(FARM_HYBRID_ESC_ALGEBRA="1"):
                seq = [eng.finish_sextuple(*c) for c in calls]
                rec = Recorder(many)
                eng2 = _fake(hero, spec, rec)
                got = eng2.finish_many(calls)
            self.assertEqual(got, seq, hero)
            with _Env(FARM_HYBRID_ESC_ALGEBRA=None):
                self.assertEqual(eng.finish_many(calls, esc="batched"), seq)  # algebra exact too
            self.assertTrue(all(x >= 2 for x in rec.sizes))


class EvalSpanQueueTests(unittest.TestCase):
    def test_cross_queue_equals_default_path(self):
        from farm import runner as R

        hero, spec = "demon_hunter", "havoc"
        space, items = _space(hero, spec)
        many = cpu_dps_many(hero, spec)
        saved = {k: getattr(R, k) for k in ("_SPACE", "_ITEMS", "_SOURCES", "_HERO", "_SPEC", "_TARGETS", "_STOP", "claim_item_bars")}
        saved_e = (E._ENGINE, E._ENGINE_STATE, E.SUB_SPAN, E.CROSS_ROWS)
        try:
            R._SPACE, R._ITEMS, R._SOURCES = space, items, {}
            R._HERO, R._SPEC, R._TARGETS, R._STOP = hero, spec, 5, None
            ranked = []

            def claim(bare, group, chunk):  # deterministic fixture, not the production admission policy
                self.assertEqual(chunk, len(ranked))  # d24 identity contract
                ranked.append(bare)
                return len(ranked) % 5 == 1

            R.claim_item_bars = claim
            E._ENGINE, E._ENGINE_STATE = _fake(hero, spec, many), "gpu"
            E.SUB_SPAN, E.CROSS_ROWS = 7, 3  # admitted rows cross sub-span borders
            out = {}
            for flag in ("0", "1"):
                ranked.clear()
                with _Env(FARM_HYBRID_CROSS_BUILD=flag, FARM_HYBRID_ESC_ALGEBRA=None):
                    out[flag] = E.eval_span(0, 33)
            a, b = out["0"], out["1"]
            self.assertEqual((a["done"], a["fights"], a["errors"]), (b["done"], b["fights"], b["errors"]))
            key = lambda h: h["chunk"]  # noqa: E731
            self.assertEqual(sorted(a["hits"], key=key), sorted(b["hits"], key=key))
            self.assertGreater(len(a["hits"]), 0)
        finally:
            for k, v in saved.items():
                setattr(R, k, v)
            E._ENGINE, E._ENGINE_STATE, E.SUB_SPAN, E.CROSS_ROWS = saved_e


if __name__ == "__main__":
    unittest.main()
