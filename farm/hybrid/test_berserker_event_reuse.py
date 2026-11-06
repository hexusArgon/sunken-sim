"""Berserker raw/potency ledger, safe GPU clustering and algebra regressions."""
from __future__ import annotations

from dataclasses import fields, replace
from types import SimpleNamespace
import os
import unittest
from unittest.mock import patch

import numpy as np

from sunken_sim import berserker as mod
from sunken_sim.ledger import Ledger, KIND_EXEC, KIND_FLAT, score_events
from sunken_sim.library import Item
from sunken_sim.shadow import Build, FIGHT


def fixture(talents=()):
    # Exercise auto_pct, double potency, execute, crit/luck, bonuses and CDR.
    item = Item("TEST", "Regression", "+15% Luck", potency=23, agility=31,
                damage=40, crit=27, crit_rating=0.3, mastery=17, mana=150,
                auto_pct=0.35, double_attack_potency=True, execute_pct=0.4,
                execute_below=0.4, armor_pen=4, attack_speed=11, haste=9)
    return Build(frozenset(talents), frozenset({mod.GLYPH_GLASS, mod.GLYPH_UNSEALED}),
                 (item, Item(mod.FIRE_ORB, "Fire", "")), 0, 9, 7, 6)


def assert_sources(test, got, want, tol=1e-12):
    for name in set(got) | set(want):
        a, b = got.get(name, 0.0), want.get(name, 0.0)
        test.assertLessEqual(abs(a-b), tol * max(1.0, abs(b)), name)


class LedgerPotencyTests(unittest.TestCase):
    def test_legacy_and_optional_coefficient_pack(self):
        from farm.hybrid.kindscore import pack
        ledger = Ledger()
        ledger.add_exec("legacy", 12.0, 1.0, 2.0)
        ledger["flat"] = 3.0
        ledger.add_exec("split", 0.0, 2.0, 1.0, raw_weight=0.0, pot_coeff=2.0)
        self.assertEqual([len(ev) for ev in ledger.events], [4, 4, 5])
        events = ledger.events + [(0.0, "flatpot", 5.0, KIND_FLAT, -0.5)]
        stats = {"potency": 10.0, "executes": ()}
        got = score_events(events, stats)
        self.assertEqual(got, {"legacy": 6.0, "flat": 3.0, "split": 20.0, "flatpot": 0.0})
        self.assertEqual(float(pack([(events, stats)])["weight"].sum()), sum(got.values()))
        self.assertEqual(ledger["legacy"], 12.0)

    def test_all_talents_and_potency_changes_replay_cpu_tape(self):
        cases = [(), *[(t,) for t in mod.TALENTS], tuple(mod.TALENTS)]
        for spec in mod.SPECS:
            for talents in cases:
                for targets in (1, 5):
                    base = fixture(talents)
                    first = mod.simulate(base, targets, spec)
                    for potency in (0, 1, 20):
                        report = mod.simulate(replace(base, potency_points=potency), targets, spec)
                        self.assertEqual(first.events, report.events, (spec, talents, targets, potency))
                        self.assertEqual(first.actions, report.actions)
                        assert_sources(self, score_events(first.events, report.stats), report.sources)
                    self.assertTrue(any(len(ev) > 4 and ev[4] for ev in first.events))
                    # Probe-restore and auto_pct must not produce baked FLAT deltas.
                    self.assertFalse(any(ev[3] == KIND_FLAT for ev in first.events))

    def test_key_omits_only_potency_and_preserves_custom_item_stats(self):
        b = fixture(mod.TALENTS)
        key = lambda x, spec="poison", targets=5: mod._timeline_key(x, mod.stats_of(x), spec, targets)
        self.assertEqual(key(b), key(replace(b, potency_points=20)))
        for f in fields(b):
            if f.name.endswith("_points") and f.name != "potency_points":
                self.assertNotEqual(key(b), key(replace(b, **{f.name: getattr(b, f.name)+1})), f.name)
        self.assertNotEqual(key(b), key(replace(b, talents=frozenset())))
        self.assertNotEqual(key(b), key(replace(b, glyphs=frozenset())))
        self.assertNotEqual(key(b), key(b, targets=1))
        self.assertNotEqual(key(b), key(b, spec="fury"))
        self.assertNotEqual(key(b), key(replace(b, items=(replace(b.items[0], damage=40.0000001), b.items[1]))))
        self.assertNotEqual(key(b), key(replace(b, items=tuple(reversed(b.items)))))

    def test_sulfuras_fallback_tape_reuses_potency(self):
        b = fixture(mod.TALENTS)
        b = replace(b, items=b.items+(Item("I0BR", "Sulfuras", ""),))
        for spec in mod.SPECS:
            first = mod.simulate(b, 5, spec)
            other = mod.simulate(replace(b, potency_points=20), 5, spec)
            self.assertEqual(first.events, other.events)
            assert_sources(self, score_events(first.events, other.stats), other.sources)
            self.assertTrue(any("Sulfuras" in ev[1] for ev in first.events))


class BerserkerGpuReuseTests(unittest.TestCase):
    def test_gpu_raw_tapes_and_cpu_parity_all_specs(self):
        import torch
        from farm.hybrid.berserker_gpu_timeline import generate_berserker_timelines
        from farm.hybrid.kindscore import pack, compile_sums
        for spec in mod.SPECS:
            base = fixture(mod.TALENTS)
            builds = [base, replace(base, potency_points=20), fixture(())]
            pairs = generate_berserker_timelines(torch, torch.device("cpu"), builds, spec, 5)
            self.assertEqual(pairs[0][0], pairs[1][0])
            scores = compile_sums(torch, torch.device("cpu"), pack(pairs)).sum(1)/FIGHT
            for build, (events, stats), dps in zip(builds, pairs, scores):
                report = mod.simulate(build, 5, spec)
                assert_sources(self, score_events(events, stats), report.sources)
                self.assertLess(abs(dps-report.dps)/report.dps, 1e-5)

    def test_cluster_count_order_stats_and_engine_modes(self):
        import torch
        from farm.hybrid.berserker import BerserkerFights
        from farm.hybrid.berserker_gpu_timeline import generate_berserker_timelines
        device = SimpleNamespace(gpu=False)
        for spec in mod.SPECS:
            base = fixture(mod.TALENTS)
            builds = [base, replace(base, potency_points=20), replace(base, crit_points=8),
                      base, replace(base, luck_points=7)]
            engine = BerserkerFights(device, "berserker", spec, 5)
            with patch("farm.hybrid.berserker_gpu_timeline.generate_berserker_timelines",
                       wraps=generate_berserker_timelines) as gen:
                pairs = engine._gpu_timelines(builds)
                self.assertEqual(len(gen.call_args.args[2]), 3)
                self.assertIs(pairs[0][0], pairs[1][0])
                self.assertIs(pairs[0][0], pairs[3][0])
                self.assertEqual([s for _, s in pairs], [mod.stats_of(b) for b in builds])
            for mode in ("0", "1"):
                with patch.dict(os.environ, FARM_HYBRID_GPU_TIMELINE=mode):
                    got = engine.dps_many(builds)
                for b, dps in zip(builds, got):
                    true = mod.simulate(b, 5, spec).dps
                    self.assertLess(abs(dps-true)/true, 1e-5)
            self.assertEqual(engine.fights, 10)
            self.assertEqual(engine.dps_many([]), [])

    def test_overflow_fallback_keeps_potency_split(self):
        import torch
        from farm.hybrid.berserker_gpu_timeline import generate_berserker_timelines
        base = fixture(mod.TALENTS)
        for b, targets in ((replace(base, items=base.items+(Item("I0BR", "Sulfuras", ""),)), 5),
                           (base, 9)):
            builds = [b, replace(b, potency_points=20)]
            pairs = generate_berserker_timelines(torch, torch.device("cpu"), builds, "poison", targets)
            self.assertEqual(pairs[0][0], pairs[1][0])
            for build, (events, stats) in zip(builds, pairs):
                assert_sources(self, score_events(events, stats), mod.simulate(build, targets, "poison").sources)

    def test_event_capacity_falls_back_without_truncation(self):
        import torch
        from farm.hybrid import berserker_gpu_timeline as gpu
        base = fixture(mod.TALENTS)
        with patch.object(gpu, "MAX_EVENTS", 1):
            events, stats = gpu.generate_berserker_timelines(
                torch, torch.device("cpu"), [base], "poison", 5)[0]
        self.assertGreater(len(events), 1)
        assert_sources(self, score_events(events, stats), mod.simulate(base, 5, "poison").sources)

    def test_algebra_folds_symbolic_potency_for_cpu_and_device(self):
        import torch
        from farm.hybrid import esc_algebra as A
        from farm.hybrid.esc_device import DeviceProgram
        for spec in mod.SPECS:
            base = fixture(mod.TALENTS)
            tr = A.trace_current(mod, base, 5, spec, {"potency"})
            self.assertTrue(tr.ok, tr.note)
            self.assertTrue(all(len(ev) == 4 for ev in tr.events))
            self.assertIn("potency", tr.weight_keys)
            cols = [mod.stats_of(replace(base, potency_points=p)) for p in (0, 1, 20)]
            keys = set(tr.program.leaves.values())
            V = tr.program.evaluate({k: np.asarray([s[k] for s in cols]) for k in keys})
            self.assertTrue(tr.program.guards_ok(V).all())
            exact = A.score_cpu(tr, A.event_weights(tr, V))
            targets = [torch.device("cpu")]
            if os.environ.get("FARM_HYBRID_TEST_DML") == "1":
                import torch_directml
                targets.append(torch_directml.device())
            for target in targets:
                dp = DeviceProgram(tr, torch, target, torch.float32)
                approx = dp.score(np.asarray([[s[k] for k in dp.leaf_keys] for s in cols]))
                self.assertLess(float(np.max(np.abs(approx-exact)/exact)), 1e-5)
            for p, dps in zip((0, 1, 20), exact):
                true = mod.simulate(replace(base, potency_points=p), 5, spec).dps
                self.assertLess(abs(dps-true)/true, 1e-12)


if __name__ == "__main__":
    unittest.main()
