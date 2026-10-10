"""Incoming hits from a median hostile creature, and the hero's health.

The creature set is the same one behind MEDIAN_MONSTER_HP: custom units that
have hit points, armor and an attack, and are not buildings, locusts,
invulnerable, item-holders, or dummy/portal/chest/picker/ward/totem units.
The hit is 91 damage every 0.2 s. Armor does not reduce this hit.
"""

from __future__ import annotations

from functools import lru_cache

FIGHT = 30.0
ATTACK_INTERVAL = 0.2
ATTACK_DAMAGE = 91.0
HEAL_OF_MAX = 0.5
HP_FLOOR = 1.0
STR_HP = 15.0
AGI_ARMOR = 0.1
ARMOR_FACTOR = 0.04
LOW_HP = 0.40


def max_hp(base_hp: float, strength: float) -> float:
    return base_hp + STR_HP * strength


def _mitigated(armor: float) -> float:
    del armor
    return ATTACK_DAMAGE


@lru_cache(maxsize=256)
def _hp_table(max_milli: int, cap_milli: int) -> tuple[float, ...]:
    """Health share at each 0.01 s. Built in one pass so a fight can sample it."""
    max_health = max_milli / 1000.0
    heal_cap = cap_milli / 1000.0
    ratios = [1.0] * 3001
    if max_health <= HP_FLOOR:
        return tuple(ratios)
    hit = ATTACK_DAMAGE
    health = max_health
    ceiling = max_health * heal_cap
    next_hit = ATTACK_INTERVAL
    next_heal = 1.0
    filled = 0

    def paint(until: float) -> None:
        nonlocal filled
        index = min(3000, int(until * 100 + 1e-6))
        ratio = health / max_health
        while filled < index:
            ratios[filled] = ratio
            filled += 1

    while True:
        if next_hit <= next_heal:
            moment, kind = next_hit, "hit"
        else:
            moment, kind = next_heal, "heal"
        if moment > FIGHT:
            break
        paint(moment)
        if kind == "hit":
            health = max(HP_FLOOR, health - hit)
            next_hit += ATTACK_INTERVAL
        else:
            if health < ceiling:
                health = min(ceiling, health + HEAL_OF_MAX * max_health)
            next_heal += 1.0
    paint(FIGHT + 0.01)
    return tuple(ratios)


def hero_hp_ratio(time: float, max_health: float, armor: float, heal_cap: float = 1.0) -> float:
    """Share of maximum health at this fight time. Never below 1 hit point.

    heal_cap is the fraction of maximum health that a heal is allowed to reach.
    Crimson Fury holds that ceiling at 38% for the whole fight. Armor does not
    reduce the incoming hit.
    """
    del armor
    if max_health <= HP_FLOOR:
        return 1.0
    table = _hp_table(int(round(max_health * 1000)), int(round(heal_cap * 1000)))
    index = min(3000, max(0, int(time * 100 + 1e-6)))
    return table[index]


def hero_below_forty(time: float, max_health: float, armor: float) -> bool:
    """True when one median hit between heals can put the hero at 40% or lower."""
    if max_health <= HP_FLOOR:
        return True
    hit = _mitigated(armor)
    if ATTACK_INTERVAL >= 1.0 and hit < (1.0 - LOW_HP) * max_health and HEAL_OF_MAX * max_health >= hit:
        return False
    return hero_hp_ratio(time, max_health, armor) <= LOW_HP
