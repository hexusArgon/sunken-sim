"""Tinker fixed-policy affine tapes, per-build winner selection and eligibility guards."""
from __future__ import annotations

from dataclasses import fields, replace
from types import SimpleNamespace
import os
import unittest
from unittest.mock import patch
import numpy as np

from sunken_sim import tinker as mod
from sunken_sim.ledger import Ledger, KIND_EXEC, KIND_FLAT, score_events
from sunken_sim.library import Item
from sunken_sim.shadow import Build, Report, FIGHT


def fixture(talents=()):
    item = Item("TEST", "Regression", "+15% Luck", potency=23, strength=31, intel=17,
                damage=40, crit=27, crit_rating=0.3, mastery=17, mana=150, spell_crit=True,
                auto_pct=0.35, double_attack_potency=True, execute_pct=0.4,
                execute_below=0.4, armor_pen=4, attack_speed=11, haste=9)
    return Build(frozenset(talents), frozenset({mod.GLYPH_GLASS, mod.GLYPH_UNSEALED}),
                 (item, Item(mod.FIRE_ORB, "Fire", ""), Item(mod.ITEM_WELDING, "Welding", ""),
                  Item(mod.ITEM_BOX, "Box", ""), Item(mod.ITEM_BELT, "Belt", ""),
                  Item(mod.ITEM_FLAMMABLE, "Flammable", ""), Item(mod.SPELLBINDER, "Spellbinder", "")),
                 0, 9, 7, 6)


def assert_sources(test, got, want, tol=1e-12):
    for name in set(got) | set(want):
        a, b = got.get(name, 0.0), want.get(name, 0.0)
        test.assertLessEqual(abs(a-b), tol * max(1.0, abs(b)), name)


class FixedPolicyTests(unittest.TestCase):
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

    def test_all_talents_each_policy_cpu_replay(self):
        for spec in mod.SPECS:
            for talents in [(), *[(t,) for t in mod.TALENTS], tuple(mod.TALENTS)]:
                base = fixture(talents)
                for targets in (1, 5):
                    for policy in mod.policies_for(spec):
                        first = mod._simulate(base, targets, spec, policy)
                        for potency in (0, 1, 20):
                            report = mod._simulate(replace(base, potency_points=potency), targets, spec, policy)
                            self.assertEqual(first.events, report.events, (spec, talents, targets, policy))
                            self.assertEqual(first.actions, report.actions)
                            self.assertEqual(first.mana_left, report.mana_left)
                            self.assertEqual({k:v for k,v in first.stats.items() if k != "potency"},
                                             {k:v for k,v in report.stats.items() if k != "potency"})
                            assert_sources(self, score_events(first.events, report.stats), report.sources)
                        self.assertTrue(any(len(ev) == 5 and ev[4] for ev in first.events))
                        self.assertFalse(any(ev[3] == KIND_FLAT for ev in first.events))

    def test_key_separates_policy_and_every_other_esc_field(self):
        b = fixture(mod.TALENTS)
        key = lambda x, spec="nanotech", targets=5, policy=(True,False): mod._timeline_key(
            x, mod.stats_of(x), spec, targets, policy)
        self.assertEqual(key(b), key(replace(b, potency_points=20)))
        for f in fields(b):
            if f.name.endswith("_points") and f.name != "potency_points":
                self.assertNotEqual(key(b), key(replace(b, **{f.name:getattr(b,f.name)+1})), f.name)
        self.assertNotEqual(key(b), key(b,policy=(False,False)))
        self.assertNotEqual(key(b), key(b,targets=1))
        self.assertNotEqual(key(b), key(b,spec="engineering"))
        self.assertNotEqual(key(b), key(replace(b,talents=frozenset())))
        self.assertNotEqual(key(b), key(replace(b,glyphs=frozenset())))
        self.assertNotEqual(key(b), key(replace(b,items=tuple(reversed(b.items)))))
        self.assertNotEqual(key(b), key(replace(b,items=(replace(b.items[0],damage=40.0000001),*b.items[1:]))))

    def test_state_dependent_attributes_change_tape(self):
        b = fixture(mod.TALENTS)
        for spec in mod.SPECS:
            for policy in mod.policies_for(spec):
                first = mod._simulate(b,5,spec,policy)
                for field in ("haste_points","attack_speed_points","crit_points","luck_points","mana_points","pet_damage_points"):
                    other = replace(b,**{field:20})
                    report = mod._simulate(other,5,spec,policy)
                    # Mana changes Engineering's pet multiplier; other specs can
                    # be resource-unconstrained for this fixture, but remain keyed.
                    if field != "mana_points" or spec == "engineering":
                        self.assertTrue(first.events != report.events,(spec,policy,field))
                    if field in ("haste_points","attack_speed_points"):
                        self.assertNotEqual([(e[0],e[1]) for e in first.events],
                                            [(e[0],e[1]) for e in report.events])


class HybridPolicyTests(unittest.TestCase):
    def test_gpu_each_talent_and_policy_reuses_potency(self):
        import torch
        from farm.hybrid.tinker_gpu_timeline import generate_tinker_timelines
        for spec in mod.SPECS:
            for talents in [(), *[(t,) for t in mod.TALENTS], tuple(mod.TALENTS)]:
                base = fixture(talents)
                for policy in mod.policies_for(spec):
                    builds = [base,replace(base,potency_points=20)]
                    rows = generate_tinker_timelines(torch,torch.device("cpu"),builds,spec,5,policies=[policy,policy])
                    self.assertEqual(rows[0][0],rows[1][0])
                    for b,(events,stats) in zip(builds,rows):
                        fresh = mod._simulate(b,5,spec,policy)
                        assert_sources(self,score_events(events,stats),fresh.sources)
                        self.assertEqual(stats,fresh.stats)

    def test_cluster_counts_original_order_stats_cpu_and_dml(self):
        from farm.hybrid.tinker import TinkerFights
        from farm.hybrid.tinker_gpu_timeline import generate_tinker_timelines
        devices = [SimpleNamespace(gpu=False)]
        if os.environ.get("FARM_HYBRID_TEST_DML") == "1":
            import torch_directml
            devices.append(SimpleNamespace(gpu=True,handle=torch_directml.device()))
        for device in devices:
            for spec in mod.SPECS:
                base = fixture(mod.TALENTS)
                builds = [base,replace(base,potency_points=20),replace(base,crit_points=8),base,replace(base,luck_points=7)]
                engine = TinkerFights(device,"tinker",spec,5)
                with patch("farm.hybrid.tinker_gpu_timeline.generate_tinker_timelines",wraps=generate_tinker_timelines) as gen:
                    pairs = engine._gpu_timelines(builds)
                    self.assertEqual(len(gen.call_args.args[2]),3*len(mod.policies_for(spec)))
                    self.assertEqual(len(gen.call_args.kwargs["policies"]),len(gen.call_args.args[2]))
                    self.assertIs(pairs[0][0],pairs[3][0])
                    for b,(events,stats) in zip(builds,pairs):
                        report=mod.simulate(b,5,spec)
                        self.assertEqual(stats,report.stats)
                        assert_sources(self,score_events(events,stats),report.sources)
                for mode in ("0","1"):
                    with patch.dict(os.environ,FARM_HYBRID_GPU_TIMELINE=mode):
                        scores=engine.dps_many(builds)
                    for b,score in zip(builds,scores):
                        true=mod.simulate(b,5,spec).dps
                        self.assertLess(abs(score-true)/true,1e-5)
                self.assertEqual(engine.fights,10)
                self.assertEqual(engine.dps_many([]),[])

    def test_reselects_policy_per_build_and_preserves_dps_tie_tolerance(self):
        from farm.hybrid.tinker import TinkerFights
        bare=Build(frozenset(),frozenset(),(),0,0)
        for spec in mod.SPECS:
            policies=mod.policies_for(spec)
            def fake(_torch,_device,builds,_spec,_targets,policies):
                # P=0 chooses first A, P=10 chooses B; later candidates tie B.
                return [([(0.0,"A" if p==mod.policies_for(spec)[0] else "B",
                           100.0 if p==mod.policies_for(spec)[0] else 95.0,KIND_FLAT,
                           0.0 if p==mod.policies_for(spec)[0] else 1.0)],
                         {**mod.stats_of(b),"policy_reinforce":float(p[0]),"policy_exo":float(p[1])})
                        for b,p in zip(builds,policies)]
            eng=TinkerFights(SimpleNamespace(gpu=False),"tinker",spec,5)
            with patch("farm.hybrid.tinker_gpu_timeline.generate_tinker_timelines",side_effect=fake):
                rows=eng._gpu_timelines([bare,replace(bare,potency_points=20)])
            self.assertEqual([r[0][0][1] for r in rows],["A","B"])
            self.assertEqual(rows[1][1]["policy_exo"],float(policies[1][1]))
            def near_tie(_torch,_device,builds,_spec,_targets,policies):
                return [([(0.0,str(p),100.0+(FIGHT*0.5e-9 if p!=mod.policies_for(spec)[0] else 0),KIND_FLAT)],
                         mod.stats_of(b)) for b,p in zip(builds,policies)]
            with patch("farm.hybrid.tinker_gpu_timeline.generate_tinker_timelines",side_effect=near_tie):
                row=eng._gpu_timelines([bare])[0]
            self.assertEqual(row[0][0][1],str(policies[0]))

    def test_explicit_policy_validation_and_fallback(self):
        import torch
        from farm.hybrid import tinker_gpu_timeline as gpu
        b=fixture(mod.TALENTS)
        with self.assertRaises(ValueError):
            gpu.generate_tinker_timelines(torch,None,[b],"engineering",5,policies=[])
        with self.assertRaises(ValueError):
            gpu.generate_tinker_timelines(torch,None,[b],"engineering",5,policies=[(False,True)])
        for spec in mod.SPECS:
            for sulfuras in (False,True):
                base=replace(b,items=b.items+(Item("I0BR","Sulfuras",""),)) if sulfuras else b
                builds=[base,replace(base,potency_points=20)]
                for policy in (*mod.policies_for(spec),None):
                    with patch.object(gpu,"MAX_STEPS",1):
                        rows=gpu.generate_tinker_timelines(torch,None,builds,spec,5,
                            policies=None if policy is None else [policy,policy])
                    if policy is not None:
                        self.assertEqual(rows[0][0], rows[1][0])
                        replay = score_events(rows[0][0], rows[1][1])
                        assert_sources(self, replay, mod._simulate(builds[1],5,spec,policy).sources)
                    for build,(events,stats) in zip(builds,rows):
                        report=mod.simulate(build,5,spec) if policy is None else mod._simulate(build,5,spec,policy)
                        assert_sources(self,score_events(events,stats),report.sources)
                        self.assertEqual(stats,report.stats)

    def test_actual_symbolic_esc_cpu_and_device(self):
        import torch
        from farm.hybrid import esc_algebra as A
        from farm.hybrid.esc_device import DeviceProgram
        for spec in mod.SPECS:
            b=fixture(mod.TALENTS)
            tr=A.trace_current(mod,b,5,spec,{"potency"})
            self.assertTrue(tr.ok,tr.note)
            self.assertTrue(all(len(ev)==4 for ev in tr.events))
            self.assertIn("potency",tr.weight_keys)
            cols=[mod.stats_of(replace(b,potency_points=p)) for p in (0,1,20)]
            V=tr.program.evaluate({k:np.asarray([s[k] for s in cols]) for k in set(tr.program.leaves.values())})
            exact=A.score_cpu(tr,A.event_weights(tr,V))
            self.assertTrue(tr.program.guards_ok(V).all())
            targets=[torch.device("cpu")]
            if os.environ.get("FARM_HYBRID_TEST_DML")=="1":
                import torch_directml
                targets.append(torch_directml.device())
            for target in targets:
                dp=DeviceProgram(tr,torch,target,torch.float32)
                approx=dp.score(np.asarray([[s[k] for k in dp.leaf_keys] for s in cols]))
                self.assertLess(float(np.max(np.abs(approx-exact)/exact)),1e-5)
            for p,dps in zip((0,1,20),exact):
                true=mod.simulate(replace(b,potency_points=p),5,spec).dps
                self.assertLess(abs(dps-true)/true,1e-12)

    def test_symbolic_policy_switch_fails_guard(self):
        from farm.hybrid import esc_algebra as A
        from sunken_sim.ledger import attach
        b=Build(frozenset(),frozenset(),(),0,0)
        def fake(build,targets,spec,policy):
            stats=mod.stats_of(build)
            raw,coeff=(100.0,0.0) if policy[0] else (95.0,1.0)
            sources=Ledger()
            amount=raw+stats["potency"]*coeff
            sources.add_exec("policy",amount,0.,1.,raw_weight=raw,pot_coeff=coeff)
            return attach(Report(build,amount/FIGHT,amount,sources,[],stats,targets))
        with patch.object(mod,"POLICIES",((True,False),(False,False))),patch.object(mod,"_simulate",side_effect=fake):
            tr=A.trace_current(mod,b,5,"nanotech",{"potency"})
        self.assertTrue(tr.ok,tr.note)
        V=tr.program.evaluate({"potency":np.asarray([0.,10.])})
        self.assertEqual(list(tr.program.guards_ok(V)),[True,False])


class DeferredEligibilityTests(unittest.TestCase):
    def test_necromancer_call_of_grave_changes_cadence(self):
        from sunken_sim import necromancer as n
        b=Build(frozenset({n.TALENT_CALL_OF_THE_GRAVE}),frozenset(),(),0,0)
        a=n.simulate(b,5,"bone");c=n.simulate(replace(b,potency_points=20),5,"bone")
        self.assertNotEqual([(e[0],e[1]) for e in a.events],[(e[0],e[1]) for e in c.events])

    def test_windmaster_tornado_lifetime_changes_tape(self):
        from sunken_sim import windmaster as w
        b=Build(frozenset(),frozenset(),(),0,0)
        a=w.simulate(b,5,"upheaval");c=w.simulate(replace(b,potency_points=20),5,"upheaval")
        self.assertNotEqual([(e[0],e[1]) for e in a.events],[(e[0],e[1]) for e in c.events])

    def test_monk_capped_fists_of_fury_is_not_affine(self):
        from sunken_sim import monk as m
        b=Build(frozenset({m.TALENT_FISTS_OF_FURY}),frozenset(),
                (Item("TEST","cap threshold","",strength=715),),0,0)
        v=[m._simulate(replace(b,potency_points=p),10,"windwalker",("all",True,True)).sources["Автоатака"]
           for p in (0,10,20)]
        self.assertGreater(abs(v[2]-2*v[1]+v[0]),1e-6)


if __name__=="__main__":
    unittest.main()
