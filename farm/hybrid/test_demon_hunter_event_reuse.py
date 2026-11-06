"""DemonHunter raw/potency ledger, safe GPU clustering and algebra regressions."""
from __future__ import annotations

from dataclasses import fields, replace
from types import SimpleNamespace
import os
import unittest
from unittest.mock import patch

import numpy as np

from sunken_sim import demon_hunter as mod
from sunken_sim.ledger import Ledger, KIND_EXEC, KIND_FLAT, score_events
from sunken_sim.library import Item
from sunken_sim.shadow import Build, FIGHT


def fixture(talents=()):
    # Exercise auto_pct, double potency, execute, crit/luck, bonuses and CDR.
    item = Item("TEST", "Regression", "+15% Luck", potency=23, agility=31,
                damage=40, crit=27, crit_rating=0.3, mastery=17, mana=150, spell_crit=True,
                auto_pct=0.35, double_attack_potency=True, execute_pct=0.4,
                execute_below=0.4, armor_pen=4, attack_speed=11, haste=9)
    return Build(frozenset(talents), frozenset({mod.GLYPH_GLASS, mod.GLYPH_UNSEALED}),
                 (item, Item(mod.FIRE_ORB, "Fire", ""),
                  Item(mod.ITEM_TORMENTOR, "Tormentor", ""),
                  Item(mod.ITEM_WARGLAIVE, "Warglaive", ""),
                  Item(mod.ITEM_COSMIC_HELM, "Cosmic Helm", ""),
                  Item(mod.ITEM_DARK_NAARU, "Dark Naaru", ""),
                  Item(mod.SPELLBINDER, "Spellbinder", "")), 0, 9, 7, 6)


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
                    # Damage writes and auto_pct must not produce baked FLAT deltas.
                    self.assertFalse(any(ev[3] == KIND_FLAT for ev in first.events))

    def test_key_omits_only_potency_and_preserves_custom_item_stats(self):
        b = fixture(mod.TALENTS)
        key = lambda x, spec="havoc", targets=5: mod._timeline_key(x, mod.stats_of(x), spec, targets)
        self.assertEqual(key(b), key(replace(b, potency_points=20)))
        for f in fields(b):
            if f.name.endswith("_points") and f.name != "potency_points":
                self.assertNotEqual(key(b), key(replace(b, **{f.name: getattr(b, f.name)+1})), f.name)
        self.assertNotEqual(key(b), key(replace(b, talents=frozenset())))
        self.assertNotEqual(key(b), key(replace(b, glyphs=frozenset())))
        self.assertNotEqual(key(b), key(b, targets=1))
        self.assertNotEqual(key(b), key(b, spec="devourer"))
        self.assertNotEqual(key(b), key(replace(b, items=(replace(b.items[0], damage=40.0000001), *b.items[1:]))))
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

    def test_death_knight_virulent_is_not_affine(self):
        # Eligibility audit: the same affine unbake would be wrong for DK.
        from sunken_sim import death_knight as dk
        b = Build(frozenset({dk.TALENT_VIRULENT}), frozenset(), (), 0, 0)
        values = [dk.simulate(replace(b, potency_points=p), 5, "unholy").sources["Outbreak"]
                  for p in (0, 10, 20)]
        self.assertGreater(abs(values[2] - 2*values[1] + values[0]), 1e-6)


class DemonHunterGpuReuseTests(unittest.TestCase):
    def test_gpu_raw_tapes_and_cpu_parity_all_specs(self):
        import torch
        from farm.hybrid.demon_hunter_gpu_timeline import generate_demon_hunter_timelines
        from farm.hybrid.kindscore import pack, compile_sums
        for spec in mod.SPECS:
            base = fixture(mod.TALENTS)
            builds = [base, replace(base, potency_points=20), fixture(())]
            pairs = generate_demon_hunter_timelines(torch, torch.device("cpu"), builds, spec, 5)
            self.assertEqual(pairs[0][0], pairs[1][0])
            scores = compile_sums(torch, torch.device("cpu"), pack(pairs)).sum(1)/FIGHT
            for build, (events, stats), dps in zip(builds, pairs, scores):
                report = mod.simulate(build, 5, spec)
                assert_sources(self, score_events(events, stats), report.sources)
                self.assertLess(abs(dps-report.dps)/report.dps, 1e-5)

    def test_gpu_each_talent_reuses_potency_tape(self):
        import torch
        from farm.hybrid.demon_hunter_gpu_timeline import generate_demon_hunter_timelines
        for spec in mod.SPECS:
            for talents in [(), *[(t,) for t in mod.TALENTS], tuple(mod.TALENTS)]:
                for targets in (1, 5):
                    base = fixture(talents)
                    builds = [base, replace(base, potency_points=20)]
                    pairs = generate_demon_hunter_timelines(torch, torch.device("cpu"), builds, spec, targets)
                    self.assertEqual(pairs[0][0], pairs[1][0], (spec, talents, targets))
                    for build, (events, stats) in zip(builds, pairs):
                        report = mod.simulate(build, targets, spec)
                        assert_sources(self, score_events(events, stats), report.sources)

    def test_cluster_count_order_stats_and_engine_modes(self):
        import torch
        from farm.hybrid.demon_hunter import DemonHunterFights
        from farm.hybrid.demon_hunter_gpu_timeline import generate_demon_hunter_timelines
        devices = [SimpleNamespace(gpu=False)]
        if os.environ.get("FARM_HYBRID_TEST_DML") == "1":
            import torch_directml
            devices.append(SimpleNamespace(gpu=True, handle=torch_directml.device()))
        for device in devices:
            for spec in mod.SPECS:
                base = fixture(mod.TALENTS)
                builds = [base, replace(base, potency_points=20), replace(base, crit_points=8),
                          base, replace(base, luck_points=7)]
                engine = DemonHunterFights(device, "demon_hunter", spec, 5)
                with patch("farm.hybrid.demon_hunter_gpu_timeline.generate_demon_hunter_timelines",
                           wraps=generate_demon_hunter_timelines) as gen:
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


    def test_sulfuras_and_step_overflow_fallback_keep_potency_split(self):
        import torch
        from farm.hybrid import demon_hunter_gpu_timeline as gpu
        base = fixture(mod.TALENTS)
        for spec in mod.SPECS:
            for sulfuras in (False, True):
                b = replace(base, items=base.items+(Item("I0BR", "Sulfuras", ""),)) if sulfuras else base
                builds = [b, replace(b, potency_points=20)]
                with patch.object(gpu, "MAX_STEPS", 1):
                    pairs = gpu.generate_demon_hunter_timelines(torch, torch.device("cpu"), builds, spec, 5)
                self.assertEqual(pairs[0][0], pairs[1][0])
                for build, (events, stats) in zip(builds, pairs):
                    assert_sources(self, score_events(events, stats), mod.simulate(build, 5, spec).sources)

    def test_stat_dependent_schedules_are_separate(self):
        base = fixture(mod.TALENTS)
        base = replace(base, crit_points=0, luck_points=0)
        for spec in mod.SPECS:
            first = mod.simulate(base, 5, spec)
            for field, value in (("haste_points", 20), ("attack_speed_points", 20),
                                 ("crit_points", 100), ("luck_points", 100), ("mastery_points", 100)):
                trial = replace(base, **{field: value})
                fresh = mod.simulate(trial, 5, spec)
                self.assertNotEqual(mod._timeline_key(base, first.stats, spec, 5),
                                    mod._timeline_key(trial, fresh.stats, spec, 5))
                self.assertNotEqual(first.events, fresh.events, (spec, field))
                if field in ("haste_points", "attack_speed_points"):
                    self.assertNotEqual([(ev[0], ev[1]) for ev in first.events],
                                        [(ev[0], ev[1]) for ev in fresh.events], (spec, field))

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
