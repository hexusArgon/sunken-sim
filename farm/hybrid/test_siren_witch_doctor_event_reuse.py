"""Siren/Witch Doctor fixed-policy affine tapes, per-build winner selection and eligibility guards."""
from __future__ import annotations

from dataclasses import fields, replace
from types import SimpleNamespace
import os
import unittest
from unittest.mock import patch
import numpy as np

from sunken_sim import siren, witch_doctor
from sunken_sim.ledger import Ledger, KIND_EXEC, KIND_FLAT, score_events
from sunken_sim.library import Item
from sunken_sim.shadow import Build, Report, FIGHT


def fixture(mod, talents=()):
    item = Item("TEST", "Regression", "+15% Luck", potency=23, strength=31, agility=29, intel=17,
                damage=40, crit=27, crit_rating=0.3, mastery=17, mana=150, spell_crit=True,
                auto_pct=0.35, double_attack_potency=True, execute_pct=0.4,
                execute_below=0.4, armor_pen=4, attack_speed=11, haste=9)
    codes = [getattr(mod,n) for n in dir(mod) if n.startswith("ITEM_")]
    codes += [mod.FIRE_ORB, mod.SPELLBINDER, mod.SULFURON_GLOVES]
    return Build(frozenset(talents), frozenset({mod.GLYPH_GLASS,mod.GLYPH_UNSEALED,mod.GLYPH_BEASTFURY}),
                 (item, *(Item(code,code,"") for code in codes)),0,9,7,6)


def assert_sources(test, got, want, tol=1e-12):
    for name in set(got) | set(want):
        a, b = got.get(name, 0.0), want.get(name, 0.0)
        test.assertLessEqual(abs(a-b), tol * max(1.0, abs(b)), name)


class HeroMixin:
    def test_legacy_and_optional_coefficient_pack(self):
        mod = self.mod
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
        mod = self.mod
        for spec in mod.SPECS:
            for talents in [(), *[(t,) for t in mod.TALENTS], tuple(mod.TALENTS)]:
                base = fixture(mod,talents)
                for targets in (1, 5):
                    for policy in mod.POLICIES:
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
        mod = self.mod
        b = fixture(mod,mod.TALENTS)
        key = lambda x, spec=mod.SPECS[0], targets=5, policy=mod.POLICIES[0]: mod._timeline_key(
            x, mod.stats_of(x), spec, targets, policy)
        self.assertEqual(key(b), key(replace(b, potency_points=20)))
        for f in fields(b):
            if f.name.endswith("_points") and f.name != "potency_points":
                self.assertNotEqual(key(b), key(replace(b, **{f.name:getattr(b,f.name)+1})), f.name)
        self.assertNotEqual(key(b), key(b,policy=mod.POLICIES[-1]))
        self.assertNotEqual(key(b), key(b,targets=1))
        self.assertNotEqual(key(b), key(b,spec=mod.SPECS[1]))
        self.assertNotEqual(key(b), key(replace(b,talents=frozenset())))
        self.assertNotEqual(key(b), key(replace(b,glyphs=frozenset())))
        self.assertNotEqual(key(b), key(replace(b,items=tuple(reversed(b.items)))))
        self.assertNotEqual(key(b), key(replace(b,items=(replace(b.items[0],damage=40.0000001),*b.items[1:]))))

    def test_state_dependent_attributes_change_tape(self):
        mod=self.mod
        b=fixture(mod,mod.TALENTS)
        changed=set(); cadence=set()
        names=("haste_points","attack_speed_points","crit_points","luck_points","mana_points","pet_damage_points")
        for spec in mod.SPECS:
            for policy in mod.POLICIES:
                first=mod._simulate(b,5,spec,policy)
                for field in names:
                    report=mod._simulate(replace(b,**{field:20}),5,spec,policy)
                    if first.events != report.events: changed.add(field)
                    if [(e[0],e[1]) for e in first.events] != [(e[0],e[1]) for e in report.events]:
                        cadence.add(field)
        self.assertTrue(set(names) <= changed, changed)
        self.assertTrue({"haste_points","attack_speed_points","luck_points"} <= cadence,cadence)

    def test_gpu_each_talent_and_policy_reuses_potency(self):
        mod = self.mod
        import torch
        generate = self.generate
        for spec in mod.SPECS:
            for talents in [(), *[(t,) for t in mod.TALENTS], tuple(mod.TALENTS)]:
                base = fixture(mod,talents)
                for policy in mod.POLICIES:
                    builds = [base,replace(base,potency_points=20)]
                    rows = generate(torch,torch.device("cpu"),builds,spec,5,policies=[policy,policy])
                    self.assertEqual(rows[0][0],rows[1][0])
                    for b,(events,stats) in zip(builds,rows):
                        fresh = mod._simulate(b,5,spec,policy)
                        assert_sources(self,score_events(events,stats),fresh.sources)
                        self.assertEqual(stats,fresh.stats)

    def test_cluster_counts_original_order_stats_cpu_and_dml(self):
        mod = self.mod
        HeroFights = self.engine_type
        generate = self.generate
        devices = [SimpleNamespace(gpu=False)]
        if os.environ.get("FARM_HYBRID_TEST_DML") == "1":
            import torch_directml
            devices.append(SimpleNamespace(gpu=True,handle=torch_directml.device()))
        for device in devices:
            for spec in mod.SPECS:
                base = fixture(mod,mod.TALENTS)
                builds = [base,replace(base,potency_points=20),replace(base,crit_points=8),base,replace(base,luck_points=7)]
                engine = HeroFights(device,self.hero,spec,5)
                with patch(self.generator_path,wraps=generate) as gen:
                    pairs = engine._gpu_timelines(builds)
                    self.assertEqual(len(gen.call_args.args[2]),3*len(mod.POLICIES))
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
        mod = self.mod
        HeroFights = self.engine_type
        bare=Build(frozenset(),frozenset(),(),0,0)
        for spec in mod.SPECS:
            policies=mod.POLICIES
            def fake(_torch,_device,builds,_spec,_targets,policies):
                # P=0 chooses first A, P=10 chooses B; later candidates tie B.
                return [([(0.0,"A" if p==mod.POLICIES[0] else "B",
                           100.0 if p==mod.POLICIES[0] else 95.0,KIND_FLAT,
                           0.0 if p==mod.POLICIES[0] else 1.0)],
                         {**mod.stats_of(b),"chosen_policy":p})
                        for b,p in zip(builds,policies)]
            eng=HeroFights(SimpleNamespace(gpu=False),self.hero,spec,5)
            with patch(self.generator_path,side_effect=fake):
                rows=eng._gpu_timelines([bare,replace(bare,potency_points=20)])
            self.assertEqual([r[0][0][1] for r in rows],["A","B"])
            self.assertEqual(rows[1][1]["chosen_policy"],policies[1])
            def near_tie(_torch,_device,builds,_spec,_targets,policies):
                return [([(0.0,str(p),100.0+(FIGHT*0.5e-9 if p!=mod.POLICIES[0] else 0),KIND_FLAT)],
                         mod.stats_of(b)) for b,p in zip(builds,policies)]
            with patch(self.generator_path,side_effect=near_tie):
                row=eng._gpu_timelines([bare])[0]
            self.assertEqual(row[0][0][1],str(policies[0]))

    def test_explicit_policy_validation_and_fallback(self):
        mod = self.mod
        import torch
        gpu = self.gpu
        b=fixture(mod,mod.TALENTS)
        with self.assertRaises(ValueError):
            self.generate(torch,None,[b],mod.SPECS[0],5,policies=[])
        with self.assertRaises(ValueError):
            self.generate(torch,None,[b],mod.SPECS[0],5,policies=[("invalid","policy")])
        for spec in mod.SPECS:
            for sulfuras in (False,True):
                base=replace(b,items=b.items+(Item("I0BR","Sulfuras",""),)) if sulfuras else b
                builds=[base,replace(base,potency_points=20)]
                for policy in (*mod.POLICIES,None):
                    with patch.object(gpu,"MAX_STEPS",1):
                        rows=self.generate(torch,None,builds,spec,5,
                            policies=None if policy is None else [policy,policy])
                    if policy is not None:
                        self.assertEqual(rows[0][0], rows[1][0])
                        replay = score_events(rows[0][0], rows[1][1])
                        assert_sources(self, replay, mod._simulate(builds[1],5,spec,policy).sources)
                    for build,(events,stats) in zip(builds,rows):
                        report=mod.simulate(build,5,spec) if policy is None else mod._simulate(build,5,spec,policy)
                        assert_sources(self,score_events(events,stats),report.sources)
                        self.assertEqual(stats,report.stats)

    def test_default_generator_keeps_best_policy_api(self):
        mod=self.mod
        for spec in mod.SPECS:
            for targets in (1,5):
                builds=[fixture(mod,()),fixture(mod,mod.TALENTS)]
                builds += [replace(b,potency_points=20) for b in builds]
                rows=self.generate(None,None,builds,spec,targets)
                self.assertEqual(self.generate(None,None,[],spec,targets),[])
                for b,(events,stats) in zip(builds,rows):
                    report=mod.simulate(b,targets,spec)
                    self.assertEqual(stats,report.stats)
                    assert_sources(self,score_events(events,stats),report.sources)
        with self.assertRaises(ValueError):
            self.generate(None,None,[],"invalid",5)
        with self.assertRaises(ValueError):
            self.generate(None,None,[fixture(mod)],mod.SPECS[0],0)

    def test_actual_symbolic_esc_cpu_and_device(self):
        mod = self.mod
        import torch
        from farm.hybrid import esc_algebra as A
        from farm.hybrid.esc_device import DeviceProgram
        for spec in mod.SPECS:
            b=fixture(mod,mod.TALENTS)
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
        mod = self.mod
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
            tr=A.trace_current(mod,b,5,mod.SPECS[0],{"potency"})
        self.assertTrue(tr.ok,tr.note)
        V=tr.program.evaluate({"potency":np.asarray([0.,10.])})
        self.assertEqual(list(tr.program.guards_ok(V)),[True,False])


    def test_auto_scaling_and_zero_crossing_replay_do_not_change_procs(self):
        mod=self.mod
        for spec in mod.SPECS:
            base=fixture(mod,mod.TALENTS)
            for policy in mod.POLICIES:
                reference=mod._simulate(base,5,spec,policy)
                for auto in (-1.25,-1.0,0.0,0.35):
                    b=replace(base,items=(replace(base.items[0],auto_pct=auto),*base.items[1:]))
                    rows=self.generate(None,None,[b,replace(b,potency_points=20)],spec,5,policies=[policy,policy])
                    self.assertEqual(rows[0][0],rows[1][0])
                    for p,(events,stats) in zip((0,20),rows):
                        fresh=mod._simulate(replace(b,potency_points=p),5,spec,policy)
                        assert_sources(self,score_events(rows[0][0],stats),fresh.sources)
                        assert_sources(self,score_events(events,stats),fresh.sources)
                        self.assertEqual(fresh.actions,reference.actions)
                        self.assertEqual(fresh.mana_left,reference.mana_left)
                        self.assertEqual([(e[0],e[1]) for e in fresh.events],
                                         [(e[0],e[1]) for e in reference.events])
                # Zero damage still carries a nonzero coefficient: don't lose it.
                bare=Build(frozenset(),frozenset(),(),0,0)
                stats=mod.stats_of(bare)
                attr='agi' if self.hero=='siren' else 'int'
                damage=-mod.WHITE_BASE-0.75*int(stats[attr])
                b=replace(bare,items=(Item('TEST','zero raw','',damage=damage),))
                r0=mod._simulate(b,5,spec,policy)
                r1=mod._simulate(replace(b,potency_points=20),5,spec,policy)
                self.assertEqual(r0.events,r1.events)
                assert_sources(self,score_events(r0.events,r1.stats),r1.sources)
                self.assertTrue(any(e[1]=='Автоатака' and len(e)==5 and e[2]==0 and e[4]!=0 for e in r0.events))


from farm.hybrid.siren import SirenFights
from farm.hybrid.witch_doctor import WitchDoctorFights
from farm.hybrid import siren_gpu_timeline, witch_doctor_gpu_timeline

class SirenTests(HeroMixin,unittest.TestCase):
    hero='siren'; mod=siren; engine_type=SirenFights; gpu=siren_gpu_timeline
    generate=staticmethod(siren_gpu_timeline.generate_siren_timelines)
    generator_path='farm.hybrid.siren_gpu_timeline.generate_siren_timelines'

class WitchDoctorTests(HeroMixin,unittest.TestCase):
    hero='witch_doctor'; mod=witch_doctor; engine_type=WitchDoctorFights; gpu=witch_doctor_gpu_timeline
    generate=staticmethod(witch_doctor_gpu_timeline.generate_witch_doctor_timelines)
    generator_path='farm.hybrid.witch_doctor_gpu_timeline.generate_witch_doctor_timelines'

class TidewarriorEligibilityTests(unittest.TestCase):
    def test_coastal_damage_sign_gate_is_not_globally_affine(self):
        from sunken_sim import tidewarrior as mod
        bare=Build(frozenset({mod.TALENT_COASTAL}),frozenset(),(),0,0)
        damage=-mod.WHITE_BASE-0.75*int(mod.stats_of(bare)['str'])-5.0
        b=replace(bare,items=(Item('TEST','synthetic negative damage','',damage=damage),))
        self.assertEqual(damage,-78.25)
        for spec in mod.SPECS:
            rows=[mod._simulate(replace(b,potency_points=p),5,spec,mod.POLICIES[0]) for p in (0,10,20)]
            v=[r.sources.get('Coastal Swing',0.) for r in rows]
            self.assertGreater(abs(v[2]-2*v[1]+v[0]),40.)
            self.assertNotEqual([(e[0],e[1]) for e in rows[0].events],[(e[0],e[1]) for e in rows[2].events])

if __name__=='__main__':
    unittest.main()
