"""Incoming hits from the target dummies, and the hero's health.

Model (set by the user on 2026-11-17):
* every dummy hits the hero for 5% of the hero's maximum health, once per second;
* the dummies attack in turn, 0.2 s apart (dummy j hits at 0.2 * (j % 5 + 1) + k seconds),
  so five dummies give one hit every 0.2 s and never a burst;
* the hero is healed for 75% of maximum health every 3 s (at 3, 6, 9, ...);
* health never drops below 1 hit point;
* round(N * 122 / 176) of the N dummies fight in melee with a Normal attack, the rest at range with a
  Magic attack: 122 of the 176 monsters placed on the 2.5.2c map have a melee weapon, most melee
  monsters attack Normal and most ranged ones Magic (user decision 2026-11-20).

Hit slot e (five slots per second) is at ``hit_time(e)`` and carries ``slot_hits(e, targets)`` hits.
The OpenCL kernels replay the same arithmetic (farm/hybrid/berserker_cl.py, mage_cl.py).
"""

from __future__ import annotations

from functools import lru_cache

FIGHT = 30.0
ATTACK_INTERVAL = 0.2   # gap between two dummies; also the hit cadence with five dummies
ATTACK_COOLDOWN = 1.0   # one dummy hits once per second
SLOTS = 5               # ATTACK_COOLDOWN / ATTACK_INTERVAL
HIT_OF_MAX = 0.05
HEAL_OF_MAX = 0.75
HEAL_EVERY = 3.0
HP_FLOOR = 1.0
STR_HP = 15.0
AGI_ARMOR = 0.1
ARMOR_FACTOR = 0.04
LOW_HP = 0.40
DEFAULT_TARGETS = 5


MELEE_SHARE = (122, 176)


def melee_count(targets: int) -> int:
    """Melee dummies among `targets`: 69.318...% rounded to the nearest whole dummy."""
    num, den = MELEE_SHARE
    return (2 * targets * num + den) // (2 * den)


def dummy_is_melee(dummy: int, targets: int) -> bool:
    """Dummies 0 .. melee_count-1 are melee (Normal attack); the rest are ranged (Magic attack)."""
    return dummy < melee_count(targets)


def slot_dummies(slot: int, targets: int) -> list[int]:
    """Dummies that hit in this slot (dummy j uses slot j % 5 of every second)."""
    return [j for j in range(slot % SLOTS, targets, SLOTS)]


def max_hp(base_hp: float, strength: float) -> float:
    return base_hp + STR_HP * strength


def hit_time(slot: int) -> float:
    """Time of hit slot 0, 1, 2, ...: 0.2, 0.4, 0.6, 0.8, 1.0, 1.2, ..."""
    return float(slot // SLOTS) + ATTACK_INTERVAL * float(slot % SLOTS + 1)


def slot_hits(slot: int, targets: int) -> int:
    """How many dummies hit in this slot (dummy j uses slot j % 5 of every second)."""
    return targets // SLOTS + (1 if slot % SLOTS < targets % SLOTS else 0)


def hit_damage(max_health: float) -> float:
    """One dummy hit."""
    return HIT_OF_MAX * max_health


@lru_cache(maxsize=256)
def _hp_table(max_milli: int, cap_milli: int, targets: int) -> tuple[float, ...]:
    """Health share at each 0.01 s. Built in one pass so a fight can sample it."""
    max_health = max_milli / 1000.0
    heal_cap = cap_milli / 1000.0
    ratios = [1.0] * 3001
    if max_health <= HP_FLOOR or targets <= 0:
        return tuple(ratios)
    hit = HIT_OF_MAX * max_health
    health = max_health
    ceiling = max_health * heal_cap
    slot = 0
    while slot_hits(slot, targets) == 0:
        slot += 1
    next_hit = hit_time(slot)
    next_heal = HEAL_EVERY
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
            health = max(HP_FLOOR, health - float(slot_hits(slot, targets)) * hit)
            slot += 1
            while slot_hits(slot, targets) == 0:
                slot += 1
            next_hit = hit_time(slot)
        else:
            if health < ceiling:
                health = min(ceiling, health + HEAL_OF_MAX * max_health)
            next_heal += HEAL_EVERY
    paint(FIGHT + 0.01)
    return tuple(ratios)


def hero_hp_ratio(time: float, max_health: float, armor: float, heal_cap: float = 1.0,
                  targets: int = DEFAULT_TARGETS) -> float:
    """Share of maximum health at this fight time. Never below 1 hit point.

    heal_cap is the fraction of maximum health that a heal is allowed to reach.
    Crimson Fury holds that ceiling at 38% for the whole fight. Armor does not
    reduce the incoming hit.
    """
    del armor
    if max_health <= HP_FLOOR:
        return 1.0
    table = _hp_table(int(round(max_health * 1000)), int(round(heal_cap * 1000)), int(targets))
    index = min(3000, max(0, int(time * 100 + 1e-6)))
    return table[index]


def hero_below_forty(time: float, max_health: float, armor: float, targets: int = DEFAULT_TARGETS) -> bool:
    """True when the hero is at 40% of maximum health or lower."""
    if max_health <= HP_FLOOR:
        return True
    return hero_hp_ratio(time, max_health, armor, 1.0, targets) <= LOW_HP
