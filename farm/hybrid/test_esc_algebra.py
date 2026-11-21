# -*- coding: utf-8 -*-
"""Tests for farm/hybrid/esc_algebra.py (guarded ESC event algebra pilot).

python -m unittest farm.hybrid.test_esc_algebra   (CPU; torch optional)
"""

from __future__ import annotations

import importlib.util
import math
import tempfile
import textwrap
import unittest
from pathlib import Path

import numpy as np

from farm.hybrid import esc_algebra as A
from sunken_sim.esc import apply_points, greedy_points
from sunken_sim.shadow import Build

_SYNTH = '''
from sunken_sim.ledger import Ledger, attach
from sunken_sim.shadow import Report, FIGHT


def stats_of(build):
    return {
        "crit": 0.01 * build.crit_points,
        "potency": 0.5 * build.potency_points,
        "haste": 0.01 * build.haste_points,
        "mana_max": 100.0 + 20.0 * build.mana_points,
        "mastery": float(build.mastery_points),
        "executes": ((0.35, 0.2),),
    }


def simulate(build, targets=1, spec="base"):
    stats = stats_of(build)
    sources = Ledger()
    now, mana = 0.0, stats["mana_max"]
    cd = 1.0 / (1.0 + stats["haste"])
    while now < FIGHT:
        raw = 50.0 + 2.0 * stats["potency"]
        if mana >= 30.0:  # mana gate: control flow on a traced value
            mana -= 30.0
            raw *= 2.0
        mana = min(stats["mana_max"], mana + 1.5)
        hit = raw * (1.0 + min(1.0, stats["crit"]))
        if stats["mastery"] > 3.0:
            hit += 4.0
        sources.add_exec("Hit", hit, now, 1.0)
        sources["Flat"] = sources.get("Flat", 0.0) + 0.1 * hit
        now += cd
    total = sum(sources.values())
    return attach(Report(build, total / FIGHT, total, sources, [], stats, targets))
'''


def _module():
    tmp = Path(tempfile.mkdtemp()) / "synth_algebra_sim.py"
    tmp.write_text(textwrap.dedent(_SYNTH), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("synth_algebra_sim", tmp)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bare():
    return Build(frozenset(), frozenset(), (), 0, 0)


def _cpu_many(module, spec="base"):
    from sunken_sim.ledger import score_events
    from sunken_sim.shadow import FIGHT

    def many(builds):
        out = []
        for b in builds:
            r = module.simulate(b, 1, spec)
            out.append(sum(score_events(r.events, r.stats).values()) / FIGHT)
        return out

    return many


class SymTests(unittest.TestCase):
    def test_ops_exact_and_guards(self):
        tape = A.Tape()
        x = tape.leaf("x", 0.3)
        y = (2.0 - x) * x / 3.0 + x ** 2.0
        self.assertEqual(y.v, (2.0 - 0.3) * 0.3 / 3.0 + 0.3 ** 2.0)
        self.assertTrue(x < 0.5)
        self.assertEqual(min(1.0, x).v, 0.3)
        prog = A.Program.build(tape)
        V = prog.evaluate({"x": np.asarray([0.3, 0.4, 0.7])})
        self.assertEqual(V[y.i, 1], (2.0 - 0.4) * 0.4 / 3.0 + 0.4 ** 2.0)
        self.assertEqual(list(prog.guards_ok(V)), [True, True, False])

    def test_pin_and_unsupported(self):
        tape = A.Tape()
        x = tape.leaf("x", 2.0)
        self.assertEqual(math.floor(x), 2)
        prog = A.Program.build(tape)
        self.assertEqual(list(prog.guards_ok(prog.evaluate({"x": np.asarray([2.0, 2.5])}))), [True, False])
        with self.assertRaises(A.Untraceable):
            hash(x)
        with self.assertRaises(A.Untraceable):
            f"{x}"
        self.assertFalse(issubclass(A.Untraceable, Exception))  # sims cannot swallow it


class SyntheticGreedyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _module()

    def run_greedy(self, total=30):
        import sys

        sys.modules["sunken_sim.synth_algebra"] = self.mod
        try:
            many = _cpu_many(self.mod)
            ref = greedy_points(lambda c: many([apply_points(_bare(), c)])[0], total=total)
            got = A.greedy_points_algebra(many, _bare(), "synth_algebra", "base", 1, total=total)
        finally:
            sys.modules.pop("sunken_sim.synth_algebra", None)
        return ref, got

    def test_exact_vs_full_greedy(self):
        ref, got = self.run_greedy()
        self.assertEqual(got[:2], ref)
        self.assertGreater(got[2].rescored, 0)

    def test_timeline_key_excluded_and_fought(self):
        _ref, got = self.run_greedy(total=4)
        self.assertGreater(got[2].fought, 0)  # haste moves event times -> fought

    def test_trace_events_match_plain(self):
        b = apply_points(_bare(), {"crit": 3, "mana": 2})
        tr = A.trace_current(self.mod, b, 1, "base", {"crit", "potency", "mana_max", "mastery"})
        self.assertTrue(tr.ok, tr.note)
        plain = self.mod.simulate(b, 1, "base").events
        self.assertEqual(
            [(w, n, (x.v if isinstance(x, A.Sym) else x), k) for w, n, x, k in tr.events],
            list(plain),
        )

    def test_guard_failure_falls_back(self):
        # mastery 3 -> 4 flips `mastery > 3` -> guard fails -> trial must be fought
        b = apply_points(_bare(), {"mastery": 3})
        tr = A.trace_current(self.mod, b, 1, "base", {"mastery"})
        t = self.mod.stats_of(apply_points(_bare(), {"mastery": 4}))
        V = tr.program.evaluate({"mastery": np.asarray([t["mastery"]])})
        self.assertFalse(tr.program.guards_ok(V)[0])

    def test_rescored_trials_equal_cpu(self):
        b = apply_points(_bare(), {"crit": 2, "potency": 5})
        keys = {"crit", "potency", "mana_max", "mastery"}
        tr = A.trace_current(self.mod, b, 1, "base", keys)
        many = _cpu_many(self.mod)
        attrs = ("crit", "potency", "mana", "mastery")
        trials = [apply_points(b, {"crit": 2, "potency": 5, **{a: (2 if a == "crit" else 5 if a == "potency" else 0) + 1}}) for a in attrs]
        stats = [self.mod.stats_of(t) for t in trials]
        V = tr.program.evaluate({k: np.asarray([s[k] for s in stats]) for k in set(tr.program.leaves.values())})
        ok = tr.program.guards_ok(V)
        dps = A.score_cpu(tr, A.event_weights(tr, V))
        true = many(trials)
        for i in range(len(trials)):
            if ok[i]:
                self.assertEqual(dps[i], true[i], attrs[i])


class RealHeroTests(unittest.TestCase):
    def test_kind_heroes_exact_vs_batched(self):
        from farm.hybrid.stat_kernel import greedy_points_batched, structural_skip_attrs
        from farm.hybrid.test_stat_kernel_greedy import _catalog_build, cpu_dps_many

        for hero, spec in (("dragon_sentinel", "ruby"), ("necromancer", "essence"), ("demon_hunter", "havoc")):
            build = _catalog_build(hero, spec, 0)
            many = cpu_dps_many(hero, spec)
            ref = greedy_points_batched(many, build, hero=hero)
            got = A.greedy_points_algebra(many, build, hero, spec, 5, skip=structural_skip_attrs(hero))
            self.assertEqual(got[:2], ref, f"{hero}/{spec}")
            self.assertGreater(got[2].rescored, 0)

    def test_score_engine_matches_kindscore(self):
        try:
            import torch
        except Exception:
            raise unittest.SkipTest("torch not installed")
        from farm.hybrid.kindscore import compile_sums, pack
        from farm.hybrid.test_stat_kernel_greedy import _catalog_build
        from sunken_sim import dragon_sentinel as mod
        from sunken_sim.shadow import FIGHT

        b = _catalog_build("dragon_sentinel", "ruby", 0)
        tr = A.trace_current(mod, b, 5, "headhunter", {"crit", "potency", "luck"})
        self.assertTrue(tr.ok, tr.note)
        W = A.event_weights(tr, tr.program.val[:, None])
        got = A.score_engine(tr, W, torch, torch.device("cpu"))[0]
        r = mod.simulate(b, 5, "headhunter")
        ref = float(compile_sums(torch, torch.device("cpu"), pack([(r.events, r.stats)]))[0].sum()) / FIGHT
        self.assertEqual(got, ref)


if __name__ == "__main__":
    unittest.main()
