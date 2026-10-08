"""Incoming hits from a median hostile creature, and the hero's health.

The creature set is the same one behind MEDIAN_MONSTER_HP: custom units that
have hit points, armor and an attack, and are not buildings, locusts,
invulnerable, item-holders, or dummy/portal/chest/picker/ward/totem units.
The hit is 91 damage every 0.2 s. Armor does not reduce this hit.
"""

from __future__ import annotations

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


def hero_hp_ratio(time: float, max_health: float, armor: float) -> float:
    """Share of maximum health at this fight time. Never below 1 hit point."""
    if max_health <= HP_FLOOR:
        return 1.0
    hit = _mitigated(armor)
    health = max_health
    next_hit = ATTACK_INTERVAL
    next_heal = 1.0
    while True:
        if next_hit <= next_heal:
            moment, kind = next_hit, "hit"
        else:
            moment, kind = next_heal, "heal"
        if moment > time:
            break
        if kind == "hit":
            health = max(HP_FLOOR, health - hit)
            next_hit += ATTACK_INTERVAL
        else:
            health = min(max_health, health + HEAL_OF_MAX * max_health)
            next_heal += 1.0
    return health / max_health


def hero_below_forty(time: float, max_health: float, armor: float) -> bool:
    """True when one median hit between heals can put the hero at 40% or lower."""
    if max_health <= HP_FLOOR:
        return True
    hit = _mitigated(armor)
    if ATTACK_INTERVAL >= 1.0 and hit < (1.0 - LOW_HP) * max_health and HEAL_OF_MAX * max_health >= hit:
        return False
    return hero_hp_ratio(time, max_health, armor) <= LOW_HP
