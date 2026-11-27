"""Incoming-hit effects of the kernels against hand-computed values of the map formulas.

    python3.11 -m unittest farm.hybrid.test_incoming

Model (docs/defense-model.md): N dummies, dummy j attacks at 0.2 * (j % 5 + 1) + k s (k = 0, 1, ...) while
< 30 s, dummies j < round(N * 122 / 176) melee; a hit is 5% of max HP. Bare Berserker targets have armor 15:
the armor factor is 1 - 0.6 / 1.6 = 0.625.
"""

from __future__ import annotations

import unittest

import numpy as np

ARMOR = 1.0 - (15.0 * 0.04) / (1.0 + 0.04 * 15.0)


def hits(targets: int, melee_only: bool = False) -> int:
    melee = (2 * targets * 122 + 176) // 352
    total = 0
    for j in range(targets):
        if melee_only and j >= melee:
            continue
        t = 0.2 * (j % 5 + 1)
        while t < 30.0 - 1e-9:
            total += 1
            t += 1.0
    return total


class BerserkerIncoming(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from farm import runner as R
        from farm.hybrid import berserker_cl as BC, class_cl as C

        space, items = C.full_space("berserker", "Berserker", BC.TALENT_NAMES)
        cls.engines = {t: BC.BerserkerCL(space, items, R.source_map(items), t, None, "headhunter") for t in (5, 1, 7)}

    def per(self, rep, name):
        return rep["sources"].get(name, 0.0)

    def test_hit_counts(self) -> None:
        self.assertEqual((hits(5), hits(5, True), hits(1), hits(1, True), hits(7, True)), (149, 90, 30, 30, 149))

    def test_spiked_carapace(self) -> None:
        for t in (5, 1, 7):
            rep = self.engines[t].report(("stre",))
            want = hits(t, True) * 0.10 * 0.05 * rep["stats"]["hp"] * ARMOR
            self.assertAlmostEqual(self.per(rep, "Отражение урона"), want, places=6, msg=t)

    def test_spiked_and_thorns_stack(self) -> None:
        rep = self.engines[5].report(("I0BC", "I0JK"))
        self.assertAlmostEqual(self.per(rep, "Отражение урона"), hits(5, True) * 0.20 * 0.05 * rep["stats"]["hp"] * ARMOR, places=6)

    def test_same_ability_does_not_stack(self) -> None:
        rep = self.engines[5].report(("I0BC", "stre"))
        self.assertAlmostEqual(self.per(rep, "Отражение урона"), hits(5, True) * 0.10 * 0.05 * rep["stats"]["hp"] * ARMOR, places=6)

    def test_evasion_scales_landed_hits(self) -> None:
        rep = self.engines[5].report(("I0DL", "I0JK"))
        self.assertAlmostEqual(self.per(rep, "Отражение урона"), hits(5, True) * 0.82 * 0.10 * 0.05 * rep["stats"]["hp"] * ARMOR, places=6)

    def test_sunstrider_all_attacks_magical(self) -> None:
        rep = self.engines[5].report(("I04M",))
        want = hits(5) * 0.15 * 0.05 * rep["stats"]["hp"] * ARMOR * (1.0 + rep["stats"]["magic_add"])
        self.assertAlmostEqual(self.per(rep, "Sunstrider Crown"), want, places=6)

    def test_shield_of_death(self) -> None:
        rep = self.engines[5].report(("I0B5",))
        want = hits(5) * 125.0 * 0.08 * (1.0 + rep["stats"]["luck"]) * ARMOR
        self.assertAlmostEqual(self.per(rep, "Shield of Death"), want, places=6)

    def test_nerubian_stun_reduces_hits(self) -> None:
        plain = self.engines[5].report(("I0BC",))
        stun = self.engines[5].report(("I0BC", "I06N"))
        ratio = self.per(stun, "Отражение урона") / stun["stats"]["hp"] / (self.per(plain, "Отражение урона") / plain["stats"]["hp"])
        self.assertLess(ratio, 1.0)
        self.assertGreater(ratio, 0.95)

    def test_bloodlord_stores_ally_healing(self) -> None:
        # the model heal (75% max HP every 3 s, Healing Type from an ally: 20% stored, +10% received from the
        # Regalia itself) at 3, 6, ..., 27 s; each burst right after it: 20% x stored x (1 + 0.06 x 15) per target
        rep = self.engines[5].report(("I05V",))
        hp = rep["stats"]["hp"]
        burst = 0.20 * (0.20 * 0.75 * hp * 1.10) * (1.0 + 0.06 * 15)
        self.assertAlmostEqual(self.per(rep, "Bloodlord's Regalia"), 9 * 5 * burst * ARMOR, places=6)

    def test_no_incoming_effects_no_new_sources(self) -> None:
        rep = self.engines[5].report(("I0BR",))
        for name in ("Отражение урона", "Sunstrider Crown", "Shield of Death", "Shado-Pan Faceguard"):
            self.assertNotIn(name, rep["sources"])


class DeathKnightIncoming(unittest.TestCase):
    """Death Knight: shared layer through the DK kernel and the DK healing (HP cost, Blood Strike, Blood Feast)."""

    @classmethod
    def setUpClass(cls) -> None:
        from farm import runner as R
        from farm.hybrid import class_cl as C, death_knight_cl as DK

        space, items = C.full_space("death_knight", "DeathKnight", DK.TALENT_NAMES)
        src = R.source_map(items)
        cls.eng = {(spec, t): DK.DeathKnightCL(space, items, src, t, None, spec)
                   for spec in ("frost", "blood", "unholy") for t in (5, 1)}

    def src(self, rep, name):
        return rep["sources"].get(name, 0.0)

    def test_evasion_scales_reflects(self) -> None:
        # Cloak of Revan 18% evasion: reflects land on 82% of the attacks (its +7 stats move the frozen windows
        # of dummy 0 a little, hence the tolerance)
        for t in (5, 1):
            plain = self.eng["frost", t].report(("I0BC",))
            ev = self.eng["frost", t].report(("I0BC", "I0DL"))
            ratio = (self.src(ev, "Отражение урона") / ev["stats"]["hp"]) / (self.src(plain, "Отражение урона") / plain["stats"]["hp"])
            self.assertAlmostEqual(ratio, 0.82, delta=0.82 * 0.15 * 0.2, msg=t)

    def test_reflect_abilities_stack_once_each(self) -> None:
        one = self.eng["frost", 5].report(("I0BC",))
        same = self.eng["frost", 5].report(("I0BC", "stre"))
        both = self.eng["frost", 5].report(("I0BC", "I0JK"))
        # (each reflect instance also gets the Blood Plague flat on plagued dummies, hence 1% tolerance)
        r1 = self.src(one, "Отражение урона") / one["stats"]["hp"]
        self.assertAlmostEqual(self.src(same, "Отражение урона") / same["stats"]["hp"] / r1, 1.0, delta=0.01)
        self.assertAlmostEqual(self.src(both, "Отражение урона") / both["stats"]["hp"] / r1, 2.0, delta=0.02)

    def test_shield_of_death_on_every_attack(self) -> None:
        # 125 x 8% x Luck per attack started (before evasion); dummy 0 is the frozen target (+15%) at times
        rep = self.eng["blood", 5].report(("I0B5",))
        base = hits(5) * 125.0 * 0.08 * (1.0 + rep["stats"]["luck"]) * ARMOR
        got = self.src(rep, "Shield of Death")
        self.assertGreaterEqual(got, base * (1.0 - 1e-12))
        self.assertLessEqual(got, base * (1.0 + 0.15 * 30 / hits(5)))

    def test_bloodlord_stores_ally_and_blood_strike_heals(self) -> None:
        # Frost, no talents: the store per 3 s window = ally model heal (20%) + Blood Strike heals (100%,
        # 20 + 10% max HP, max HP +1 per Blood Strike), x 1.10 (the Regalia's own +10% received); the burst
        # after each model heal is 20% x stored x 1.9 to every dummy, +15% on dummy 0 while it is frozen.
        rep = self.eng["frost", 5].report(("I05V",))
        hp0 = rep["stats"]["hp"]
        acts = rep["actions"]
        total = 0.0
        for k in range(1, 10):
            t = 3.0 * k
            bonus_now = sum(1 for c, n in acts if n == "Blood Strike" and c <= t)
            stored = 0.20 * 0.75 * (hp0 + bonus_now) * 1.10
            for i, (c, n) in enumerate(acts):
                if n == "Blood Strike" and t - 3.0 < c <= t:
                    before = sum(1 for c2, n2 in acts[:i] if n2 == "Blood Strike")
                    stored += (20.0 + 0.10 * (hp0 + before)) * 1.10
            frozen = any(n == "Frost Strike" and c <= t <= c + 0.15 + 1.5 for c, n in acts)
            burst = 0.20 * stored * (1.0 + 0.06 * 15)
            total += burst * ARMOR * (4.0 + (1.15 if frozen else 1.0))
        # the hand formula leaves out the Blood Plague flat each burst instance gets on plagued dummies (< 0.5%)
        self.assertAlmostEqual(self.src(rep, "Bloodlord's Regalia") / total, 1.0, delta=0.005)

    def test_blood_feast_worms_and_blood_spec_feed_bloodlord(self) -> None:
        base = self.eng["frost", 5].report(("I05V",))
        feast = self.eng["frost", 5].report(("I05V",), talents=("I0CU",))
        worms = self.eng["frost", 5].report(("I05V",), talents=("I03W",))
        blood = self.eng["blood", 5].report(("I05V",))
        b = self.src(base, "Bloodlord's Regalia")
        self.assertGreater(self.src(feast, "Bloodlord's Regalia"), b * 1.05)
        self.assertGreater(self.src(worms, "Bloodlord's Regalia"), b)
        self.assertGreater(self.src(blood, "Bloodlord's Regalia"), b)
        # without Bloodlord's Regalia or health-dependent items healing does not change the fight
        bare = self.eng["frost", 5].report(())
        self.assertEqual(self.eng["frost", 5].report((), talents=("I0CU",))["dps"], bare["dps"])

    def test_hp_cost_feeds_health_items(self) -> None:
        # The Furnace: + missing% / 500 to the DamageIncrease pool; spells cost 10-15% of current health
        for spec in ("frost", "blood", "unholy"):
            bare = self.eng[spec, 5].report(())
            furn = self.eng[spec, 5].report(("I079",))
            self.assertGreater(furn["dps"], bare["dps"], spec)

    def test_presence_mana_from_hits(self) -> None:
        # Plasma-Core Belt +3 mana per attack against the hero: Frost / Unholy presence turn the mana into damage,
        # Blood has neither presence (its gain is the belt's stats only)
        gain = {}
        for spec in ("frost", "unholy", "blood"):
            gain[spec] = self.eng[spec, 5].report(("I0F2",))["dps"] - self.eng[spec, 5].report(())["dps"]
        self.assertGreater(gain["frost"], gain["blood"] + 1.0)
        self.assertGreater(gain["unholy"], gain["blood"] + 1.0)

    def test_armor_penetration_only_on_attacks(self) -> None:
        # ArmorDamage_Increase: item penetration only for attack types other than Spells (the hero's attacks);
        # the Shadow Orb (6) does not change Death Grip / Blood Strike / Frost Strike
        bare = self.eng["frost", 5].report(())
        orb = self.eng["frost", 5].report(("I0NT",))
        def per_cast(rep, spell):
            return rep["sources"][spell] / sum(1 for _c, n in rep["actions"] if n == spell)

        for spell in ("Death Grip", "Blood Strike"):
            ratio = per_cast(orb, spell) / per_cast(bare, spell)
            self.assertLess(ratio, 1.10, spell)  # +6 strength only; 6 armour less would be x1.34
        auto = (orb["sources"]["Автоатака"] / bare["sources"]["Автоатака"])
        self.assertGreater(auto, 1.25)

    def test_ice_cleaver_chills_and_freezes(self) -> None:
        # 3% max mana per chill, 6% per freeze (Frost Strike freezes dummy 0 on every cast)
        rep = self.eng["frost", 1].report(("lgdh",))
        fs = sum(1 for _c, n in rep["actions"] if n == "Frost Strike")
        mana = rep["stats"]["mana_max"]
        self.assertGreater(rep["sources"]["Ice Cleaver"], fs * 0.06 * mana * ARMOR * 0.9)

    def test_dk_no_incoming_effects_no_new_sources(self) -> None:
        rep = self.eng["unholy", 5].report(("I0BR",))
        for name in ("Отражение урона", "Sunstrider Crown", "Shield of Death", "Shado-Pan Faceguard", "Bloodlord's Regalia"):
            self.assertNotIn(name, rep["sources"])


class DemonHunterIncoming(unittest.TestCase):
    """Demon Hunter: Demon Spikes, Demonsurge, Bloodlet and the class evasion through the shared layer."""

    @classmethod
    def setUpClass(cls) -> None:
        from farm import runner as R
        from farm.hybrid import class_cl as C, demon_hunter_cl as DH

        space, items = C.full_space("demon_hunter", "DemonHunter", DH.TALENT_NAMES)
        src = R.source_map(items)
        cls.eng = {(spec, t): DH.DemonHunterCL(space, items, src, t, None, spec)
                   for spec in ("havoc", "vengeance", "devourer") for t in (5, 1)}

    def test_demon_spikes_on_every_attack(self) -> None:
        # 4 + 10% STR + 10% AGI per attack (before evasion), x2 for 6 s after each Demon Spikes cast (B05N),
        # once more on every evaded attack (Inner Demon learned: 12% evasion); untyped, armour 15, no talents
        for t in (5, 1):
            rep = self.eng["vengeance", t].report(())
            st = rep["stats"]
            raw = 4.0 + 0.10 * st["str"] + 0.10 * st["agi"]
            casts = [c + 0.15 for c, n in rep["actions"] if n == "Demon Spikes"]
            total = 0.0
            for j in range(t):
                when = 0.2 * (j % 5 + 1)
                while when < 30.0 - 1e-9:
                    on = any(c < when < c + 6.0 for c in casts)  # the spikes buff from the cast's hit
                    total += 1.0 + (1.0 if on else 0.0) + 0.12
                    when += 1.0
            self.assertAlmostEqual(rep["sources"]["Demon Spikes"] / (raw * ARMOR * total), 1.0, places=9, msg=t)

    def test_reflects_land_on_88_percent(self) -> None:
        # Devourer (no Potency bonus): The Blockade 10% of 5% max HP per melee attack that lands (Inner Demon 12% evasion)
        rep = self.eng["devourer", 5].report(("I0BC",))
        want = hits(5, melee_only=True) * 0.10 * 0.05 * rep["stats"]["hp"] * 0.88 * ARMOR
        self.assertAlmostEqual(rep["sources"]["Отражение урона"] / want, 1.0, places=9)

    def test_demonsurge_ends_metamorphosis(self) -> None:
        # Vengeance heals itself on every hit it deals (2 + 0.3% max HP): every 130 healed -> +1 Fury, and Fury above 0
        # drains in Metamorphosis until the form ends (trigger Fury)
        rep = self.eng["vengeance", 5].report(())
        self.assertIn("Meta ends", [n for _c, n in rep["actions"]])

    def test_bloodlet_feast_on_blood(self) -> None:
        bare = self.eng["vengeance", 5].report(())
        blood = self.eng["vengeance", 5].report((), talents=("I05S",))
        self.assertGreater(blood["dps"], bare["dps"] + 10.0)
        # without hits and heals (Havoc, no healing items) nothing reaches 40% max HP
        self.assertEqual(self.eng["havoc", 5].report((), talents=("I05S",))["dps"], self.eng["havoc", 5].report(())["dps"])

    def test_dh_no_incoming_effects_no_new_sources(self) -> None:
        rep = self.eng["havoc", 5].report(("I0BR",))
        for name in ("Отражение урона", "Sunstrider Crown", "Shield of Death", "Shado-Pan Faceguard", "Bloodlord's Regalia"):
            self.assertNotIn(name, rep["sources"])


def attack_times(targets: int) -> list:
    out = []
    for j in range(targets):
        t = 0.2 * (j % 5 + 1)
        while t < 30.0 - 1e-9:
            out.append(t)
            t += 1.0
    return sorted(out)


class DragonSentinelIncoming(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from farm import runner as R
        from farm.hybrid import class_cl as C, dragon_sentinel_cl as DS

        space, items = C.full_space("dragon_sentinel", "DragonSentinel", DS.TALENT_NAMES)
        src = R.source_map(items)
        cls.DS = DS
        cls.engines = {(spec, t): DS.DragonSentinelCL(space, items, src, t, None, spec)
                       for spec in ("ruby", "emerald") for t in (1, 5)}

        class Off(DS.DragonSentinelCL):
            KERNEL = "#define INC_OFF 1\n" + DS.KERNEL

        cls.off = Off(space, items, src, 5, None, "ruby")

    @staticmethod
    def windows(rep, name, length):
        """[cast, cast + 0.15 + length) of every cast of `name` (the kernel applies the cast's effects when it starts)"""
        return [(t, t + 0.15 + length) for t, n in rep["actions"] if n == name]

    def test_blazing_shield_answers_every_attack(self) -> None:
        for t in (1, 5):
            rep = self.engines[("ruby", t)].report(())
            st = rep["stats"]
            strength = float(int(st["str"]))
            molten = self.windows(rep, "Blazing Shield", 5.0)
            form = self.windows(rep, "Dragon Form", 12.0)
            want = 0.0
            for now in attack_times(t):
                on = any(a <= now < b for a, b in molten)
                chance = (10.0 + 0.10 * strength if on else 0.0) + (15.0 if any(a <= now < b for a, b in form) else 0.0)
                raw = 5.0 + 0.50 * (st["armor"] + (2.0 if on else 0.0))
                want += (raw + st["potency"]) * (1.0 + st["magic_add"]) * ARMOR * (1.0 + min(1.0, chance * (1.0 + st["luck"]) / 100.0))
            got = rep["sources"]["Blazing Shield (отражение)"]
            self.assertAlmostEqual(got, want, delta=1e-9 * want, msg=t)

    def test_backfire_on_attackers_under_dragonfire(self) -> None:
        for t in (1, 5):
            rep = self.engines[("ruby", t)].report((), ("I0HQ",))
            st = rep["stats"]
            strike = [(a, a + 0.15 + 5.0) for a, n in rep["actions"] if n == "Dragon Strike"]
            form = self.windows(rep, "Dragon Form", 12.0)
            want = 0.0
            for now in attack_times(t):
                fire = any(a <= now <= b for a, b in strike)
                claw = any(a <= now <= b and any(fa <= a + 0.15 < fb for fa, fb in form) for a, b in strike)
                want += (6.0 + 0.30 * float(int(st["str"])) + st["potency"]) * (1.0 + st["magic_add"]) * ARMOR * (fire + claw)
            self.assertAlmostEqual(rep["sources"]["Backfire"], want, delta=1e-9 * want, msg=t)

    def test_penetration_only_on_the_auto_attack(self) -> None:
        rep = self.engines[("emerald", 5)].report(("I0QN",))
        st = rep["stats"]
        form = self.windows(rep, "Dragon Form", 12.0)
        want = 0.0
        for a, n in rep["actions"]:
            if n == "Dragon Strike":
                f = 1.25 if any(fa <= a + 0.15 < fb for fa, fb in form) else 1.0
                want += ((60.0 + 0.03 * st["hp"]) * f + st["potency"]) * (1.0 + st["magic_add"]) * ARMOR * 5
        self.assertGreater(st["armor_pen"], 0.0)
        self.assertAlmostEqual(rep["sources"]["Dragon Strike"], want, delta=1e-9 * want)

    def test_ysera_heals_feed_emerald_procs(self) -> None:
        base = self.engines[("emerald", 5)].report(())
        ysera = self.engines[("emerald", 5)].report((), ("I0JE",))
        self.assertGreater(ysera["sources"]["Cleansing Fire (от лечения)"], base["sources"]["Cleansing Fire (от лечения)"])
        self.assertEqual(self.engines[("ruby", 5)].report((), ("I0JE",))["dps"], self.engines[("ruby", 5)].report(())["dps"])

    def test_inc_off_replays_part_a_fixtures(self) -> None:
        """INC_OFF (no hits, no health) is the kernel before the incoming model: frozen fights without changed items."""
        import json
        from pathlib import Path

        from sunken_sim.esc import ESC_ATTRS

        data = json.loads((Path(__file__).resolve().parent / "fixtures" / "dragon_sentinel.json").read_text(encoding="utf-8"))
        skip = self.DS.MODEL_FIX_ITEMS | self.DS.INCOMING_ITEMS
        cases = [c for c in data["cases"] if c["spec"] == "ruby" and c["targets"] == 5
                 and not set(c["items"]) & skip and not set(c["talents"]) & self.DS.INCOMING_TALENTS]
        e = self.off
        dps, _g, status = e.pick([e.picks_of(c["items"]) for c in cases], [e.talent_mask(c["talents"]) for c in cases],
                                 [e.glyph_mask(c["glyphs"]) for c in cases], [[c["points"][a] for a in ESC_ATTRS] for c in cases])
        self.assertGreater(len(cases), 100)
        self.assertEqual([c["items"] for c, d, s in zip(cases, dps, status) if s or float(d).hex() != c["dps"]], [])


class DruidIncoming(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from farm import runner as R
        from farm.hybrid import class_cl as C, druid_cl as DR

        space, items = C.full_space("druid", "Druid", DR.TALENT_NAMES)
        src = R.source_map(items)
        cls.DR = DR
        cls.engines = {spec: DR.DruidCL(space, items, src, 5, None, spec) for spec in ("restoration", "balance")}

        class Off(DR.DruidCL):
            KERNEL = "#define INC_OFF 1\n" + DR.KERNEL

        cls.off = Off(space, items, src, 5, None, "balance")

    def test_penetration_only_on_the_auto_attack(self) -> None:
        bare = self.engines["balance"].report(())
        pen = self.engines["balance"].report(("I0QN",))
        self.assertGreater(pen["stats"]["armor_pen"], 0.0)
        for name in ("Starfire", "Starfall", "Mass Entanglement", "Wisp Guardian"):
            self.assertEqual(pen["sources"][name], bare["sources"][name], name)
        self.assertGreater(pen["sources"]["Автоатака"], bare["sources"]["Автоатака"])

    def test_mana_from_own_heals(self) -> None:
        e = self.engines["balance"]
        base, k5 = e.report(()), e.report((), ("I0K5",))
        both = e.report((), ("I0K5", "I08Q"))
        self.assertGreater(k5["mana_left"], base["mana_left"])
        self.assertGreaterEqual(both["mana_left"], k5["mana_left"])
        self.assertEqual(e.report((), ("I08Q",))["dps"], base["dps"])  # heals without I0K5 / health items: nothing

    def test_bloodlord_stores_own_model_heal(self) -> None:
        rep = self.engines["restoration"].report(("I05V",))
        self.assertGreater(rep["sources"].get("Bloodlord's Regalia", 0.0), 0.0)

    def test_inc_off_replays_part_a_fixtures(self) -> None:
        import json
        from pathlib import Path

        from sunken_sim.esc import ESC_ATTRS

        data = json.loads((Path(__file__).resolve().parent / "fixtures" / "druid.json").read_text(encoding="utf-8"))
        skip = self.DR.MODEL_FIX_ITEMS | self.DR.INCOMING_ITEMS
        cases = [c for c in data["cases"] if c["spec"] == "balance" and c["targets"] == 5
                 and not set(c["items"]) & skip and not set(c["talents"]) & self.DR.INCOMING_TALENTS]
        e = self.off
        dps, _g, status = e.pick([e.picks_of(c["items"]) for c in cases], [e.talent_mask(c["talents"]) for c in cases],
                                 [e.glyph_mask(c["glyphs"]) for c in cases], [[c["points"][a] for a in ESC_ATTRS] for c in cases])
        self.assertGreater(len(cases), 50)
        self.assertEqual([c["items"] for c, d, s in zip(cases, dps, status) if s or float(d).hex() != c["dps"]], [])


class FeralDruidIncoming(unittest.TestCase):
    """The Feral Druid O00R (not the caster Druid)."""

    @classmethod
    def setUpClass(cls) -> None:
        from farm import runner as R
        from farm.hybrid import class_cl as C, feral_druid_cl as FD

        space, items = C.full_space("feral_druid", "FeralDruid", FD.TALENT_NAMES)
        src = R.source_map(items)
        cls.FD = FD
        cls.engines = {(spec, t): FD.FeralDruidCL(space, items, src, t, None, spec)
                       for spec in ("primal", "guardian") for t in (1, 5)}

        class Off(FD.FeralDruidCL):
            KERNEL = "#define INC_OFF 1\n" + FD.KERNEL

        cls.off = Off(space, items, src, 5, None, "primal")

    def test_survival_instincts_evasion(self) -> None:
        # Shado-Pan Faceguard: 100 untyped per evaded attack; hit chance 0.87 x (1 - (0.02 + 0.01 x 10% STR))
        for t in (1, 5):
            rep = self.engines["primal", t].report(("I07C",))
            hit = 0.87 * (1.0 - (0.02 * 1.0 + 0.01 * (0.10 * int(rep["stats"]["str"]))))
            want = sum(100.0 * (1.0 - hit) * (1.0 - 0.6 / 1.6) for _ in attack_times(t)) / 30.0
            self.assertAlmostEqual(rep["sources"]["Shado-Pan Faceguard"] / 30.0, want, places=9)

    def test_penetration_only_on_attacks(self) -> None:
        # the same build with the item penetration column zeroed: spells unchanged, attacks lower
        from farm import runner as R
        from farm.hybrid import class_cl as C

        FD = self.FD
        space, items = C.full_space("feral_druid", "FeralDruid", FD.TALENT_NAMES)

        class NoPen(FD.FeralDruidCL):
            def tables(self, space, items, sources):
                t = super().tables(space, items, sources)
                u = t["uniq"].reshape(len(space.pieces), -1).copy()
                u[:, 3] = 0.0
                t["uniq"] = np.ascontiguousarray(u.reshape(-1))
                return t

        nopen = NoPen(space, items, R.source_map(items), 5, None, "primal")
        pen, flat = self.engines["primal", 5].report(("I0NT",)), nopen.report(("I0NT",))
        self.assertGreater(pen["stats"]["armor_pen"], 0.0)
        self.assertEqual(flat["stats"]["armor_pen"], 0.0)
        self.assertEqual(pen["sources"]["Savage Bite"], flat["sources"]["Savage Bite"])
        self.assertGreater(pen["sources"]["Автоатака"], flat["sources"]["Автоатака"])

    def test_fire_orb_splash_uses_agility(self) -> None:
        # 20 + 0.35 AGI per dummy and attack, armour 15, no Potency points, no glass: a whole number of attacks
        rep = self.engines["primal", 5].report(("I07O",))
        each = (20.0 + 0.35 * rep["stats"]["agi"]) * 5 * (1.0 - 0.6 / 1.6)
        n = rep["sources"]["Всплеск огня"] / each
        self.assertAlmostEqual(n, round(n), places=9)
        self.assertGreater(round(n), 10)

    def test_sulfuras_splash_gets_potency(self) -> None:
        e = self.engines["primal", 5]
        zero = {a: 0 for a in ("health", "mana", "healing_power", "haste", "attack_speed", "damage", "crit", "potency",
                               "mastery", "luck", "pet_damage")}
        a = e.report(("I0BR",), points=zero)
        b = e.report(("I0BR",), points=dict(zero, potency=10))
        self.assertGreater(b["sources"]["Sulfuras"], a["sources"]["Sulfuras"])
        self.assertEqual(b["sources"]["Sulfuras (удар)"], a["sources"]["Sulfuras (удар)"])

    def test_no_incoming_effects_no_change(self) -> None:
        for spec in ("primal", "guardian"):
            e = self.engines[spec, 5]
            self.assertEqual(e.report((), ("I0AE",))["dps"], self.off_dps(spec, (), ("I0AE",)))

    def off_dps(self, spec, codes, talents):
        from farm import runner as R
        from farm.hybrid import class_cl as C

        if spec == "primal":
            return self.off.report(codes, talents)["dps"]
        space, items = C.full_space("feral_druid", "FeralDruid", self.FD.TALENT_NAMES)

        class Off(self.FD.FeralDruidCL):
            KERNEL = "#define INC_OFF 1\n" + self.FD.KERNEL

        return Off(space, items, R.source_map(items), 5, None, spec).report(codes, talents)["dps"]

    def test_inc_off_replays_part_a_fixtures(self) -> None:
        import json
        from pathlib import Path

        from sunken_sim.esc import ESC_ATTRS

        data = json.loads((Path(__file__).resolve().parent / "fixtures" / "feral_druid.json").read_text(encoding="utf-8"))
        skip = self.FD.MODEL_FIX_ITEMS | self.FD.INCOMING_ITEMS
        cases = [c for c in data["cases"] if c["spec"] == "primal" and c["targets"] == 5
                 and not set(c["items"]) & skip and not set(c["talents"]) & self.FD.INCOMING_TALENTS]
        e = self.off
        dps, _g, status = e.pick([e.picks_of(c["items"]) for c in cases], [e.talent_mask(c["talents"]) for c in cases],
                                 [e.glyph_mask(c["glyphs"]) for c in cases], [[c["points"][a] for a in ESC_ATTRS] for c in cases])
        self.assertGreater(len(cases), 50)
        self.assertEqual([c["items"] for c, d, s in zip(cases, dps, status) if s or float(d).hex() != c["dps"]], [])


class HunterIncoming(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from farm import runner as R
        from farm.hybrid import class_cl as C, hunter_cl as HU

        space, items = C.full_space("hunter", "Hunter", HU.TALENT_NAMES)
        src = R.source_map(items)
        cls.HU, cls.space, cls.items, cls.src = HU, space, items, src
        cls.engines = {spec: HU.HunterCL(space, items, src, 5, None, spec) for spec in ("marksmanship", "beast_mastery")}

        class Off(HU.HunterCL):
            KERNEL = "#define INC_OFF 1\n" + HU.KERNEL

        cls.off = Off(space, items, src, 5, None, "beast_mastery")

    def test_penetration_only_on_attacks(self) -> None:
        # the same build with the item penetration column zeroed: spells and pets unchanged, attacks lower
        HU = self.HU

        class NoPen(HU.HunterCL):
            def tables(self, space, items, sources):
                t = super().tables(space, items, sources)
                u = t["uniq"].reshape(len(space.pieces), -1).copy()
                u[:, 3] = 0.0
                t["uniq"] = np.ascontiguousarray(u.reshape(-1))
                return t

        nopen = NoPen(self.space, self.items, self.src, 5, None, "beast_mastery")
        pen, flat = self.engines["beast_mastery"].report(("I0NT",)), nopen.report(("I0NT",))
        self.assertGreater(pen["stats"]["armor_pen"], 0.0)
        for name in ("Serpent Sting", "Steel Trap", "Spike"):
            self.assertEqual(pen["sources"][name], flat["sources"][name], name)
        self.assertGreater(pen["sources"]["Автоатака"], flat["sources"]["Автоатака"])

    def test_sulfuras_splash_gets_potency(self) -> None:
        e = self.engines["marksmanship"]
        zero = {a: 0 for a in ("health", "mana", "healing_power", "haste", "attack_speed", "damage", "crit", "potency",
                               "mastery", "luck", "pet_damage")}
        a = e.report(("I0BR",), points=zero)
        b = e.report(("I0BR",), points=dict(zero, potency=10))
        self.assertGreater(b["sources"]["Sulfuras"], a["sources"]["Sulfuras"])
        self.assertEqual(b["sources"]["Sulfuras (удар)"], a["sources"]["Sulfuras (удар)"])

    def test_on_evade_damage_without_class_evasion(self) -> None:
        # Shado-Pan Faceguard alone: hit chance 0.87, 100 untyped x Aspect +10% per evaded attack, armour 15 under no
        # Sting / wound on the attackers it answers (dummy j), no Potency points
        rep = self.engines["marksmanship"].report(("I07C",))
        self.assertGreater(rep["sources"]["Shado-Pan Faceguard"], 0.0)

    def test_inc_off_replays_part_a_fixtures(self) -> None:
        import json
        from pathlib import Path

        from sunken_sim.esc import ESC_ATTRS

        data = json.loads((Path(__file__).resolve().parent / "fixtures" / "hunter.json").read_text(encoding="utf-8"))
        skip = self.HU.MODEL_FIX_ITEMS | self.HU.INCOMING_ITEMS
        cases = [c for c in data["cases"] if c["spec"] == "beast_mastery" and c["targets"] == 5
                 and not set(c["items"]) & skip]
        e = self.off
        dps, _g, status = e.pick([e.picks_of(c["items"]) for c in cases], [e.talent_mask(c["talents"]) for c in cases],
                                 [e.glyph_mask(c["glyphs"]) for c in cases], [[c["points"][a] for a in ESC_ATTRS] for c in cases])
        self.assertGreater(len(cases), 50)
        self.assertEqual([c["items"] for c, d, s in zip(cases, dps, status) if s or float(d).hex() != c["dps"]], [])


if __name__ == "__main__":
    unittest.main()
