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


if __name__ == "__main__":
    unittest.main()
