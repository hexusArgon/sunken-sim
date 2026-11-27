"""Incoming-hit effects of the kernels against hand-computed values of the map formulas.

    python3.11 -m unittest farm.hybrid.test_incoming

Model (docs/defense-model.md): N dummies, dummy j attacks at 0.2 * (j % 5 + 1) + k s (k = 0, 1, ...) while
< 30 s, dummies j < round(N * 122 / 176) melee; a hit is 5% of max HP. Bare Berserker targets have armor 15:
the armor factor is 1 - 0.6 / 1.6 = 0.625.
"""

from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
