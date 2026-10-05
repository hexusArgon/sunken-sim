"""Shadow Priest single-target simulator for Sunken City, level 6.

The fight is 30 seconds against one target that stays at full health and has no
armor. Damage is the expected value of crits and procs, so the search is stable.
"""

from __future__ import annotations

import heapq
import itertools
import math
import re
from dataclasses import dataclass
from pathlib import Path

from sunken_sim.library import Item, load_items
from sunken_sim.stacking import allows_copies, stack_fields

FIGHT = 30.0
CAST_POINT = 0.15
CAST_BACKSWING = 0.30
LEVEL = 6
DUMMY_ARMOR = 15.0
ARMOR_FACTOR = 0.04
CHAOS_UNARMORED = 1.25
# Median max health of custom monsters that have explicit armor and an attack,
# excluding locusts, invulnerable units, and hero inventories.
MEDIAN_MONSTER_HP = 5300.0
ORB_MODE = {"I07O": "Fire", "I0NS": "Frost", "I0NT": "Shadow"}

# Added to the type bonus before Insanity multiplies the magical bonus.
# Values are the map's MagicalType_Bonus / PhysicalType_Bonus adds.
MAGICAL_ADDS = {
    "I0AV": 0.18,
    "I0BL": 0.14,
    "ofr2": 0.15,
    "I0FU": 0.12,
    "I030": 0.08,
    "fgdg": 0.10,
    "tgrh": 0.20,
    "I07F": 0.13,
    "I0NI": 0.12,
    "fgrd": 0.30,
    "oflg": 0.08,
    "rde0": 0.05,
    "I048": 0.20,
    "I00Q": 0.05,
    "I04J": 0.10,
    "I0JO": 0.30,
}
PHYSICAL_ADDS = {
    "I0AV": 0.18,
    "I0BL": 0.14,
    "ofr2": 0.15,
    "I0AL": 0.10,
    "I017": 0.12,
    "I07K": 0.13,
    "tgrh": 0.20,
    "I0GM": 0.05,
    "I044": 0.18,
    "I055": 0.18,
}

# O009 grown with int(base + (level - 1) * per level), matching Warcraft truncation.
BASE_STR = int(3 + (LEVEL - 1) * 1.5)
BASE_AGI = int(8 + (LEVEL - 1) * 0.8)
BASE_INT = int(27 + (LEVEL - 1) * 2.7)
SKILL_POINTS = LEVEL - 1  # one point per level-up, none at level 1
MIND_AMPLIFIER = "I0IC"

TALENTS = {
    "I0KF": "Dark Torment",
    "I0HL": "Psychic Link",
    "I0PU": "Insanity",
    "I0PS": "Catharsis",
    "I0HP": "Cosmic Horrors",
    "I0SA": "Clairvoyance",
    "I0SB": "Answered Prayers",
    "I0SC": "Touch of the Naaru",
}
GLYPHS = {
    "I07B": "Fortitude",
    "I0JA": "Glass Cannon",
    "I0AV": "Unsealed Power",
    "I0OF": "Mindhaste",
    "I0H3": "Hellfire",
    "I0EK": "Supremacy",
    "I0HC": "Animosity",
    "I0H5": "Thunder",
}


@dataclass(frozen=True)
class Build:
    talents: frozenset[str]
    glyphs: frozenset[str]
    items: tuple[Item, ...]
    potency_points: int
    mastery_points: int
    crit_points: int = 0
    luck_points: int = 0


@dataclass
class Report:
    build: Build
    dps: float
    total: float
    sources: dict[str, float]
    actions: list[tuple[float, str]]
    stats: dict[str, float]
    targets: int = 1
    orb_mode: str | None = None
    bound_spell: str | None = None
    mana_left: float = 100.0


def _has(build: Build, rawcode: str) -> bool:
    return rawcode in build.talents or rawcode in build.glyphs


def _wears(build: Build, rawcode: str) -> bool:
    return _has(build, rawcode) or any(item.rawcode == rawcode for item in build.items)


def _copy_value(rawcode: str, field: str, tooltip: float, first: bool) -> float:
    if first:
        return tooltip
    bonus = stack_fields(rawcode)
    if field not in bonus:
        return 0.0
    return bonus[field]


# Percent added to the base mana regen (1.20 + 0.10×intellect), once per item type.
_MANA_REGEN_RATE = {
    "sbch": 0.20,
    "pmna": 0.15,
    "anfg": 0.15,
    "tmmt": 0.15,
    "I0GH": 0.55,
    "I0CL": 0.40,
    "I0E5": 0.15,
    "I05F": 0.25,
    "I0G0": 0.30,
    "I02V": 0.20,
    "I0CF": 0.30,
    "I0G1": 0.20,
    "I0AJ": 0.70,
    "I0AC": 0.70,
    "I0J3": 0.95,
    "I0J7": 0.40,
    "I08E": 0.30,
}
# Fraction of maximum mana added to the same per-second stat, once per item type.
_MANA_MAX_FRACTION = {
    "I04U": 0.003,
    "I0D8": 0.004,
    "I0T2": 0.004,
    "I05E": 0.01,
    "I009": 0.01,
    "I0SM": 0.004,
    "I08L": 0.005,
    "I06S": 0.004,
}
_MP5 = re.compile(r"(\d+(?:[.,]\d+)?)\s+mana per 5 seconds", re.I)
_REFUND_PCT = re.compile(r"spellcasts refund (\d+(?:[.,]\d+)?)% of their mana cost", re.I)
_REFUND_CHANCE = re.compile(
    r"(\d+(?:[.,]\d+)?)% chance to refund (\d+(?:[.,]\d+)?)% of their mana cost",
    re.I,
)
_REFUND_FLAT = re.compile(r"spellcasts to refund (\d+(?:[.,]\d+)?) mana\b", re.I)
_REFUND_MASTERY = re.compile(
    r"spellcasts refund mana equal to (\d+(?:[.,]\d+)?)% of your Mastery",
    re.I,
)
_MAX_MANA_SEC = re.compile(
    r"Restores mana equal to (\d+(?:[.,]\d+)?)% of your maximum mana each second",
    re.I,
)
_ATTACK_MANA = re.compile(
    r"attacks restore (\d+(?:[.,]\d+)?) [Mm]ana(?:, plus additional amount equal to | plus additional )(\d+(?:[.,]\d+)?)% of maximum [Mm]ana",
)
_DAMAGE_MANA = re.compile(
    r"Dealing damage from any source causes your hero to restore (\d+(?:[.,]\d+)?)% of maximum mana",
    re.I,
)


def _tip_number(text: str) -> float:
    return float(text.replace(",", "."))


def _passive_mana(items: tuple) -> dict[str, float]:
    """Mana the hero gets back from item passives. A second copy does not repeat it.

    Percent refunds multiply the mana cost the way the map does: two 15% refunds
    leave 85% × 85% of the cost, and the hero is given back the rest.
    """
    keep = 1.0
    flat = 0.0
    mastery = 0.0
    per_second = 0.0
    attack = 0.0
    attack_pct = 0.0
    attack_crit = 0.0
    damage_pct = 0.0
    seen: set[str] = set()
    for item in items:
        if item.rawcode in seen:
            continue
        seen.add(item.rawcode)
        tip = item.tip
        for raw in _REFUND_PCT.findall(tip):
            keep *= 1.0 - _tip_number(raw) / 100.0
        for chance, part in _REFUND_CHANCE.findall(tip):
            keep *= 1.0 - (_tip_number(chance) / 100.0) * (_tip_number(part) / 100.0)
        for raw in _REFUND_FLAT.findall(tip):
            flat += _tip_number(raw)
        for raw in _REFUND_MASTERY.findall(tip):
            mastery += _tip_number(raw) / 100.0
        if _MAX_MANA_SEC.search(tip):
            for raw in _MAX_MANA_SEC.findall(tip):
                per_second += _tip_number(raw) / 100.0
        elif item.rawcode in _MANA_MAX_FRACTION:
            per_second += _MANA_MAX_FRACTION[item.rawcode]
        for raw_flat, raw_pct in _ATTACK_MANA.findall(tip):
            attack += _tip_number(raw_flat)
            attack_pct += _tip_number(raw_pct) / 100.0
        if "doubled for Critical Strikes" in tip and _ATTACK_MANA.search(tip):
            attack_crit = 1.0
        for raw in _DAMAGE_MANA.findall(tip):
            damage_pct += _tip_number(raw) / 100.0
    return {
        "cast_refund": 1.0 - keep,
        "cast_refund_flat": flat,
        "cast_refund_mastery": mastery,
        "mana_per_second": per_second,
        "attack_mana": attack,
        "attack_mana_pct": attack_pct,
        "attack_mana_crit": attack_crit,
        "damage_mana_pct": damage_pct,
    }


def cast_mana_back(cost: float, stats: dict) -> float:
    return (
        cost * stats["cast_refund"]
        + stats["cast_refund_flat"]
        + stats["cast_refund_mastery"] * stats["mastery"]
    )


def attack_mana_gain(stats: dict) -> float:
    gain = stats["attack_mana"] + stats["attack_mana_pct"] * stats["mana_max"]
    if stats["attack_mana_crit"]:
        gain *= 1.0 + min(stats["crit"], 100.0) / 100.0
    return gain


def _mana_regen(build: Build, intel: float, mana_max: float, items: tuple) -> float:
    """Mana gained per second while below maximum.

    The map adds (1.20 + 0.10×intellect) plus item bonuses, then every 0.25 s
    applies 20% of that stat. Four ticks are 80% of the stat per second.
    """
    rate = 0.0
    mp5 = 0.0
    seen: set[str] = set()
    for item in items:
        if item.rawcode in seen:
            continue
        seen.add(item.rawcode)
        rate += _MANA_REGEN_RATE.get(item.rawcode, 0.0)
        for match in _MP5.findall(item.tip):
            mp5 += float(match.replace(",", "."))
    passive = _passive_mana(items)
    stat = (1.20 + 0.10 * intel) * (1.0 + rate)
    stat += mp5 / 5.0
    stat += passive["mana_per_second"] * mana_max
    if _has(build, "I0H0"):
        stat += 1.50 + 0.0075 * mana_max
    return stat * 0.80


def character(
    build: Build,
    base_str: int | None = None,
    base_agi: int | None = None,
    base_int: int | None = None,
    white_base: float = 10.0,
    bake_timed_buffs: bool = True,
) -> dict[str, float]:
    intel = BASE_INT if base_int is None else base_int
    strength = BASE_STR if base_str is None else base_str
    agility = BASE_AGI if base_agi is None else base_agi
    potency = 0.5 * build.potency_points
    mastery = build.mastery_points
    damage = 0.0
    mana = 0.0
    crit = build.crit_points
    rating = 0.0
    haste = 0.0
    attack_speed = 0.0
    seen: set[str] = set()
    for item in build.items:
        first = item.rawcode not in seen
        seen.add(item.rawcode)
        bonus = stack_fields(item.rawcode)
        intel += _copy_value(item.rawcode, "intel", item.intel, first)
        intel += _copy_value(item.rawcode, "all_stats", item.all_stats, first)
        strength += _copy_value(item.rawcode, "strength", item.strength, first)
        strength += _copy_value(item.rawcode, "all_stats", item.all_stats, first)
        agility += _copy_value(item.rawcode, "agility", item.agility, first)
        agility += _copy_value(item.rawcode, "all_stats", item.all_stats, first)
        if first and bonus.get("primary") and not item.intel and not item.all_stats:
            intel += bonus["primary"]
        elif not first:
            intel += bonus.get("primary", 0)
        potency += _copy_value(item.rawcode, "potency", item.potency, first)
        mastery += _copy_value(item.rawcode, "mastery", item.mastery, first)
        damage += _copy_value(item.rawcode, "damage", item.damage, first)
        mana += item.mana if first else 0
        crit += _copy_value(item.rawcode, "crit", item.crit, first)
        rating += _copy_value(item.rawcode, "crit_rating", item.crit_rating, first)
        if item.rawcode == "I06M":
            if first:
                haste += 0.075
        else:
            haste += _copy_value(item.rawcode, "haste", item.haste, first) / 100
        attack_speed += _copy_value(item.rawcode, "attack_speed", item.attack_speed, first) / 100
    if _has(build, "I07B"):
        intel += 4 + 2 * LEVEL
    if _has(build, "I0EK"):
        mastery += 20
    damage = white_base + 0.75 * intel + damage
    mana = 175 + 7 * intel + mana
    if _has(build, "I0SA"):
        crit += 8
    if _has(build, "I0HC"):
        crit += 12
        rating += 0.15
    if _has(build, "I0OF"):
        haste += 0.07
    agility_speed = min(1.0, 0.004 * agility)
    attack_speed = max(-0.8, min(4.0, attack_speed + agility_speed))
    attack_base = 2.0 * (1.20 if any(item.rawcode == "I0JO" for item in build.items) else 1.0)
    if bake_timed_buffs and _has(build, "I0GZ"):
        unbuffed_swing = attack_base / (1 + attack_speed)
        uptime = 5.0 / (5.0 + unbuffed_swing / 0.18)
        attack_speed = max(-0.8, min(4.0, attack_speed + 0.32 * uptime))
    spell_crit = any(item.spell_crit for item in build.items)
    spell_mult = 1.65 if any(item.spell_crit and "65%" in item.tip for item in build.items) else 1.50
    flat_cdr = 0.0
    if _has(build, "I0OF"):
        flat_cdr += 0.20
    if _wears(build, "I096"):
        flat_cdr += 0.50
    if _wears(build, "I03C"):
        flat_cdr += 0.50
    if _wears(build, "I00L"):
        flat_cdr += 1.50
    if _wears(build, "I00Y"):
        flat_cdr -= 1.00
    cd_temp = 1.0
    if _wears(build, "I07P"):
        cd_temp *= 0.92
    if _wears(build, "I048"):
        cd_temp *= 0.87
    cd_increase = 1.0
    cd_increase += 0.12 * sum(item.rawcode == "I0FW" for item in build.items)
    cd_increase += 0.10 * sum(item.rawcode == "I0QT" for item in build.items)
    cd_temp *= cd_increase
    crit_as = 0.0
    crit_as_duration = 0.0
    stab_chance = 0.0
    stab_ratio = 0.0
    auto_pct = 1.0
    executes = []
    stun_per_swing = 0.0
    cast_stun_lock = 0.0
    double_attack_potency = False
    armor_pen = 0.0
    once: set[str] = set()
    for item in build.items:
        if item.rawcode in once:
            continue
        once.add(item.rawcode)
        stun_per_swing += item.stun_chance * item.stun_duration
        if item.cast_stun_chance and item.cast_stun_duration > 0:
            cast_stun_lock += item.cast_stun_chance * item.cast_stun_duration
        double_attack_potency = double_attack_potency or item.double_attack_potency
        if item.rawcode not in ("I07O", "I0NS"):
            armor_pen += item.armor_pen
        crit_as += item.crit_as
        crit_as_duration = max(crit_as_duration, item.crit_as_duration)
        stab_chance += item.stab_chance
        stab_ratio = max(stab_ratio, item.stab_ratio)
        auto_pct += item.auto_pct
        if item.execute_pct > 0:
            executes.append((item.execute_below, item.execute_pct))
    soul_rate = 0.003 if _wears(build, "I03L") else 0.0
    if bake_timed_buffs and crit_as > 0 and crit > 0 and crit_as_duration > 0:
        base_speed = attack_speed
        for _ in range(2):
            swing = attack_base / (1 + attack_speed)
            rate = min(crit, 100.0) / 100.0 / swing
            uptime = 1.0 - math.exp(-rate * crit_as_duration)
            attack_speed = max(-0.8, min(4.0, base_speed + crit_as * uptime))
    luck = 0.01 * build.luck_points
    return {
        "int": intel,
        "str": strength,
        "agi": agility,
        "potency": potency,
        "mastery": mastery,
        "ad": damage,
        "mana_max": mana,
        "crit": min(100.0, crit),
        "rating": rating,
        "haste": haste,
        "attack_speed": attack_speed,
        "frenzy": 1.0 if _has(build, "I0GZ") else 0.0,
        "crit_as": crit_as,
        "crit_as_duration": crit_as_duration,
        "spell_crit": float(spell_crit),
        "spell_mult": spell_mult,
        "flat_cdr": flat_cdr,
        "cd_temp": cd_temp,
        "stun_per_swing": stun_per_swing,
        "cast_stun_lock": cast_stun_lock,
        "attack_potency": 2.0 if double_attack_potency else 1.0,
        "auto_pct": auto_pct,
        "executes": executes,
        "armor_pen": armor_pen,
        "soul_rate": soul_rate,
        "stab_chance": stab_chance,
        "stab_ratio": stab_ratio,
        "luck": luck,
        "swp_period": 1 / (1 + haste),
        "swing": attack_base / (1 + attack_speed),
        "mana_regen": _mana_regen(build, intel, mana, build.items),
        **{key: value for key, value in _passive_mana(build.items).items() if key != "mana_per_second"},
    }


def target_hp(time: float) -> float:
    return max(0.0, 1.0 - time / FIGHT)


def _execute_factor(stats: dict, time: float) -> float:
    hp = target_hp(time)
    factor = 1.0
    for threshold, bonus in stats["executes"]:
        if hp <= threshold:
            factor *= 1.0 + bonus
    return factor


def _codes(build: Build) -> frozenset[str]:
    return frozenset(item.rawcode for item in build.items) | build.talents | build.glyphs


def _type_add(codes: frozenset[str], table: dict[str, float], time: float) -> float:
    bonus = 0.0
    for code, amount in table.items():
        if code in codes:
            bonus += amount
    if "I0QT" in codes:
        bonus += 0.13 + 0.25 * target_hp(time)
    return bonus


def _magic_factors(codes: frozenset[str], time: float, extra: float = 0.0) -> tuple[float, float]:
    """Return (multiplier at 0 mastery from Spellbinder, slope per mastery point).

    Map order: add the type bonuses, multiply that sum by Insanity, then add
    Catharsis, then multiply by Glass Cannon.
    """
    bonus = 1.0 + _type_add(codes, MAGICAL_ADDS, time) + extra
    slope = 0.0
    if "tlum" in codes:
        bonus += 0.05
        slope = 0.005
    if "I0PU" in codes:
        bonus *= 1.15
        slope *= 1.15
    if "I0PS" in codes:
        bonus += 0.30 * target_hp(time)
    if "I0JA" in codes:
        bonus *= 1.15
        slope *= 1.15
    return bonus, slope


def _magical_multiplier(codes: frozenset[str], time: float, mastery_stat: float, extra: float = 0.0) -> float:
    base, slope = _magic_factors(codes, time, extra)
    return base + slope * mastery_stat


def _physical_multiplier(codes: frozenset[str], time: float) -> float:
    bonus = 1.0 + _type_add(codes, PHYSICAL_ADDS, time)
    if "I0JA" in codes:
        bonus *= 1.15
    return bonus


def _ability_cd(base: float, stats: dict, bound: bool = False) -> float:
    temp = stats["cd_temp"] * (0.70 if bound else 1.0)
    return max(0.5, (base * temp - stats["flat_cdr"]) / (1.0 + stats["haste"]))


_TIMELINE: dict[tuple, tuple] = {}


def _timeline_key(build: Build, stats: dict, spec: str, targets: int, bound_spell: str | None) -> tuple:
    """Schedule identity. Haste, attack speed, cooldowns and mana change when casts happen.

    Intellect, Potency, Mastery and crit only change the damage of those casts.
    """
    spells = _cast_spells(build, spec)
    base_cd = {
        "Shadow Word: Pain": 6.0,
        "Mind Spike": 8.0,
        "Void Rift": 10.0,
        "Divine Image": 16.0 - (1.0 if _has(build, "I0SB") else 0.0) - (1.0 if _has(build, "I0SC") else 0.0),
        "Radiance": 8.0,
        "Renew": 6.0,
    }
    cooldowns = tuple(
        (name, round(_ability_cd(base_cd[name], stats, bound_spell == name), 5))
        for name in spells
    )
    return (
        spec,
        targets,
        bound_spell or "",
        tuple(sorted(build.talents)),
        tuple(sorted(build.glyphs)),
        round(stats["swing"], 5),
        round(stats["attack_speed"], 5),
        round(stats["haste"], 5),
        round(stats["stun_per_swing"], 5),
        round(stats["cast_stun_lock"], 5),
        round(stats["mana_max"], 4),
        round(stats["mana_regen"], 5),
        round(stats["cast_refund"], 5),
        round(stats["cast_refund_flat"], 4),
        round(stats["cast_refund_mastery"], 5),
        round(stats["attack_mana"], 4),
        round(stats["attack_mana_pct"], 5),
        round(stats["damage_mana_pct"], 5),
        round(stats["swp_period"], 5),
        _wears(build, "I07O"),
        cooldowns,
    )


def _fight_events(
    build: Build,
    stats: dict,
    spec: str,
    targets: int,
    bound_spell: str | None,
) -> tuple[list, list, list, float]:
    events: list[tuple[float, str, float]] = []
    actions: list[tuple[float, str]] = []
    duration = 12.0 if _has(build, "I0HL") else 10.0
    cast_names = _cast_spells(build, spec)
    base_cd = {
        "Shadow Word: Pain": 6.0,
        "Mind Spike": 8.0,
        "Void Rift": 10.0,
        "Divine Image": 16.0 - (1.0 if _has(build, "I0SB") else 0.0) - (1.0 if _has(build, "I0SC") else 0.0),
        "Radiance": 8.0,
        "Renew": 6.0,
    }
    costs = {
        "Shadow Word: Pain": 15,
        "Mind Spike": 25,
        "Void Rift": 40,
        "Divine Image": 30,
        "Radiance": 35,
        "Renew": 20,
    }
    spell_cd = {name: _ability_cd(base_cd[name], stats, bound_spell == name) for name in cast_names}
    ready = {name: 0.0 for name in spell_cd}
    mana = stats["mana_max"]
    mana_time = 0.0
    swp_exp = [0.0] * targets
    naaru_until = 0.0
    blaze_until = 0.0
    renew_until = 0.0
    windows: list[tuple[float, float]] = []
    hero_ready = 0.0
    busy_until = 0.0
    pending: list[tuple[float, int, str]] = []
    seq = 0

    def record(when: float, kind: str, hits: float = 1.0) -> None:
        nonlocal mana
        events.append((when, kind, hits))
        if stats["damage_mana_pct"]:
            mana = min(stats["mana_max"], mana + stats["damage_mana_pct"] * stats["mana_max"])

    def push(when: float, kind: str) -> None:
        nonlocal seq
        if when < FIGHT:
            seq += 1
            heapq.heappush(pending, (when, seq, kind))

    push(0.0, "swing")
    if _has(build, "I0H3"):
        push(0.0, "hellfire")

    def weakest_swp(now: float) -> int:
        return min(range(targets), key=lambda index: swp_exp[index])

    def swp_apply(now: float, index: int) -> None:
        if swp_exp[index] > now:
            record(now, "swp_i")
        if not any(expiry > now for expiry in swp_exp):
            push(now + stats["swp_period"], "swp")
        swp_exp[index] = now + duration

    def naaru_hit(now: float) -> None:
        record(now, "naaru")
        if _has(build, "I0SC"):
            ready["Mind Spike"] = max(now, ready["Mind Spike"] - (0.20 if spec == "discipline" else 0.40))

    def resolve(name: str, now: float) -> None:
        nonlocal naaru_until, blaze_until, renew_until
        if name == "Mind Spike":
            record(now, "mind")
            if _has(build, "I0KF") and "Shadow Word: Pain" in ready:
                swp_apply(now, 0)
            if _has(build, "I0H5"):
                record(now, "thunder", 0.18 * targets)
        elif name == "Void Rift":
            push(now + (1.5 if _has(build, "I0HP") else 2.0), "void")
            if _has(build, "I0H5"):
                record(now, "thunder", 0.18 * targets)
        elif name == "Shadow Word: Pain":
            swp_apply(now, weakest_swp(now))
            if _has(build, "I0H5"):
                record(now, "thunder", 0.18 * targets)
        elif name == "Divine Image":
            naaru_until = now + 10
            push(now + 1, "naaru")
        elif name == "Radiance":
            if spec == "discipline":
                record(now, "radiance", targets)
            if _has(build, "I0MJ"):
                span = 6.0 if _has(build, "I0KH") else 4.0
                if blaze_until <= now:
                    push(now + 1.0, "blaze")
                blaze_until = now + span
                windows.append((now, blaze_until))
            if _has(build, "I0H5"):
                record(now, "thunder", 0.18 * targets)
        elif name == "Renew":
            if renew_until > now:
                record(now, "smite", targets)
            renew_until = now + 9.0
            if _has(build, "I0H5"):
                record(now, "thunder", 0.18 * targets)
        if name != "Divine Image" and _has(build, "I0SB") and now < naaru_until:
            naaru_hit(now)

    def recover_mana(now: float) -> None:
        nonlocal mana, mana_time
        if now > mana_time and mana < stats["mana_max"]:
            mana = min(stats["mana_max"], mana + stats["mana_regen"] * (now - mana_time))
        mana_time = now

    def begin_cast(name: str, now: float) -> None:
        nonlocal mana, busy_until, hero_ready
        recover_mana(now)
        spent = costs[name]
        mana -= spent
        mana = min(stats["mana_max"], mana + cast_mana_back(spent, stats))
        ready[name] = now + spell_cd[name]
        actions.append((now, name))
        busy_until = now + CAST_POINT + CAST_BACKSWING + stats["cast_stun_lock"]
        hero_ready = busy_until
        push(now + CAST_POINT, "finish:" + name)

    def choose(now: float) -> str | None:
        if spec == "shadow":
            order = ["Divine Image", "Mind Spike", "Void Rift"]
        else:
            order = [name for name in ("Divine Image", "Radiance", "Mind Spike", "Renew") if name in ready]
        if "Shadow Word: Pain" in ready and any(expiry < now + 1 for expiry in swp_exp):
            order.insert(0, "Shadow Word: Pain")
        for name in order:
            if ready[name] <= now and mana >= costs[name]:
                if name == "Divine Image" and naaru_until > now:
                    continue
                return name
        return None

    while pending:
        event_time = pending[0][0]
        while hero_ready <= event_time and hero_ready < FIGHT:
            recover_mana(hero_ready)
            cast_name = choose(hero_ready)
            if cast_name is None:
                break
            begin_cast(cast_name, hero_ready)
        when, _order, kind = heapq.heappop(pending)
        if when >= FIGHT:
            break
        if kind == "swing":
            if when < busy_until:
                push(busy_until, "swing")
            else:
                record(when, "auto")
                mana = min(stats["mana_max"], mana + attack_mana_gain(stats))
                if _wears(build, "I07O"):
                    record(when, "splash", targets)
                hero_ready = max(hero_ready, when + stats["stun_per_swing"])
                push(when + stats["swing"] + stats["stun_per_swing"], "swing")
        elif kind.startswith("finish:"):
            resolve(kind.split(":", 1)[1], when)
        elif kind == "swp":
            active = sum(1 for expiry in swp_exp if expiry > when)
            if active:
                record(when, "swp", active)
                push(when + stats["swp_period"], "swp")
        elif kind == "void":
            record(when, "void", targets)
            if _has(build, "I0HP"):
                dotted = sum(1 for expiry in swp_exp if expiry > when)
                if dotted:
                    record(when, "swp_i", 0.25 * dotted)
        elif kind == "naaru":
            if when <= naaru_until:
                naaru_hit(when)
                if when + 1 <= naaru_until:
                    push(when + 1, "naaru")
        elif kind == "hellfire":
            record(when, "hellfire", targets)
            push(when + 1.25, "hellfire")
        elif kind == "blaze":
            if when <= blaze_until:
                record(when, "blaze", targets)
                if when + 1 <= blaze_until:
                    push(when + 1, "blaze")

    recover_mana(FIGHT)
    mana_left = 0.0 if stats["mana_max"] <= 0 else 100.0 * mana / stats["mana_max"]
    return events, actions, windows, mana_left


def _cast_spells(build: Build, spec: str) -> list[str]:
    if spec == "shadow":
        return ["Shadow Word: Pain", "Mind Spike", "Void Rift", "Divine Image"]
    if spec == "discipline":
        spells = ["Shadow Word: Pain", "Mind Spike", "Radiance", "Divine Image"]
    else:
        spells = ["Mind Spike"]
        if _has(build, "I0MJ"):
            spells.append("Radiance")
    if _has(build, "I0KG"):
        spells.append("Renew")
    return spells


def _radiance_parts(stats: dict, mastery_stat: float, spec: str) -> tuple[float, float]:
    """Return (discipline nuke, healing stored for Empyreal Blaze)."""
    base = 120 + 1.20 * stats["int"] + 0.10 * stats["mana_max"]
    if spec == "discipline":
        scaled = base * (1.10 + 0.008 * mastery_stat)
        return scaled * 0.80, scaled * 0.60
    return 0.0, base


def _event_amp(build: Build, stats: dict, windows: list[tuple[float, float]] | None, when: float) -> float:
    if not windows or not _has(build, "I0MJ"):
        return 1.0
    if any(start < when <= end for start, end in windows):
        return 1.05 + 0.0008 * stats["str"]
    return 1.0


def armor_taken(armor: float) -> float:
    if armor > 0:
        return 1 - (armor * ARMOR_FACTOR) / (1 + ARMOR_FACTOR * armor)
    if armor < 0:
        return 2 - (1 - ARMOR_FACTOR) ** (-armor)
    return 1.0


def _crit_factor(chance: float, multiplier: float) -> float:
    chance = max(0.0, min(100.0, chance)) / 100
    return 1 + chance * (multiplier - 1)


def score_events(
    events: list[tuple[float, str, float]],
    build: Build,
    stats: dict,
    potency: float | None = None,
    crit: float | None = None,
    mastery_stat: float | None = None,
    luck: float | None = None,
    spec: str = "shadow",
    windows: list[tuple[float, float]] | None = None,
) -> tuple[float, dict[str, float]]:
    potency = stats["potency"] if potency is None else potency
    crit = stats["crit"] if crit is None else crit
    mastery_stat = stats["mastery"] if mastery_stat is None else mastery_stat
    luck = stats["luck"] if luck is None else luck
    codes = _codes(build)
    spell_crit = _crit_factor(crit, stats["spell_mult"] + stats["rating"]) if stats["spell_crit"] else 1.0
    attack_crit = _crit_factor(crit, 2 + stats["rating"])
    mastery = (1.10 + 0.006 * mastery_stat) if spec == "shadow" else 1.0
    tick_base = (15 + 0.30 * stats["int"]) * mastery
    instant_raw = (75 + 1.50 * stats["int"]) * mastery
    mind_raw = (80 + 1.50 * stats["int"]) * (1 + 0.01 * stats["ad"])
    void_raw = (85 + 0.15 * stats["mana_max"]) * (1 + 0.007 * stats["int"])
    naaru_raw = (25 + 0.40 * stats["int"]) * (0.75 if spec == "discipline" else 1.0)
    nuke_raw, _stored = _radiance_parts(stats, mastery_stat, spec)
    blaze_raw = (0.04 if spec == "holy" else 0.08) * _stored
    smite_raw = 50 + 0.80 * stats["int"] + 0.80 * stats["str"]
    thunder_raw = 35 + 2 * stats["int"]
    link = _has(build, "I0HL")
    glass = _has(build, "I0JA")
    sources: dict[str, float] = {}

    def add(name: str, amount: float) -> None:
        sources[name] = sources.get(name, 0.0) + amount

    for when, kind, hits in events:
        execute = _execute_factor(stats, when)
        amp = _event_amp(build, stats, windows, when)
        magical = _magical_multiplier(codes, when, mastery_stat) * amp
        physical = _physical_multiplier(codes, when) * amp
        if kind == "auto":
            soul = stats["soul_rate"] * MEDIAN_MONSTER_HP * target_hp(when)
            amount = (stats["ad"] + potency * stats["attack_potency"] + soul) * physical * execute * stats["auto_pct"] * attack_crit * hits
            add("Автоатака", amount)
            if stats["stab_chance"]:
                chance = stats["stab_chance"] * (1 + luck)
                raw = stats["stab_ratio"] * stats["ad"]
                stab = (
                    (raw + potency * stats["attack_potency"])
                    * physical
                    * execute
                    * stats["auto_pct"]
                    * attack_crit
                    * CHAOS_UNARMORED
                    * chance
                    * hits
                )
                add("Удар тьмы", stab)
        elif kind == "mind":
            add("Mind Spike", (mind_raw + potency) * magical * spell_crit * hits * execute)
        elif kind == "void":
            add("Void Rift", (void_raw + potency) * magical * spell_crit * hits * execute)
        elif kind == "naaru":
            add("Naaru", (naaru_raw + potency) * magical * spell_crit * hits * execute)
        elif kind == "swp":
            link_factor = (1.15 + 0.10 * hits) if link else 1.0
            add("Shadow Word: Pain", (tick_base + potency) * link_factor * magical * spell_crit * hits * execute)
        elif kind == "swp_i":
            add("Shadow Word: Pain (удар при обновлении)", (instant_raw + potency) * magical * spell_crit * hits * execute)
        elif kind == "thunder":
            add("Thunder", (thunder_raw + potency) * magical * spell_crit * hits * execute)
        elif kind == "radiance":
            add("Radiance", (nuke_raw + potency * hits) * magical * spell_crit * execute)
        elif kind == "blaze":
            add("Empyreal Blaze", (blaze_raw + potency) * magical * spell_crit * hits * execute)
        elif kind == "smite":
            add("Smite", (smite_raw + potency) * magical * spell_crit * hits * execute)
        elif kind == "splash":
            add("Всплеск огня", (20 + 0.35 * stats["int"]) * hits * amp * execute)
            continue
        elif kind == "hellfire":
            raw = (3 + 3 * LEVEL) * (2 if hits == 1 else 0.5 if hits >= 4 else 1)
            add("Hellfire", (raw + potency) * hits * (1.15 if glass else 1.0) * amp * execute)
        else:
            continue
        if _has(build, "I0H6"):
            explosion = 0.03 * (20 + 1.6 * stats["int"] + potency)
            if glass:
                explosion *= 1.15
            add("Blood Violence", explosion * amp * execute)
    taken = armor_taken(DUMMY_ARMOR - stats["armor_pen"])
    taken_stab = armor_taken(DUMMY_ARMOR)
    scaled = {}
    for name, amount in sources.items():
        scaled[name] = amount * (taken_stab if name == "Удар тьмы" else taken)
    return sum(scaled.values()), scaled


def compile_events(
    events: list[tuple[float, str, float]],
    build: Build,
    stats: dict,
    spec: str = "shadow",
    windows: list[tuple[float, float]] | None = None,
) -> dict:
    codes = _codes(build)
    link = _has(build, "I0HL")
    glass = 1.15 if _has(build, "I0JA") else 1.0
    blood = _has(build, "I0H6")
    auto_weight = 0.0
    soul_weight = 0.0
    splash_hits = 0.0
    kinds = ("mind", "void", "naaru", "thunder", "swp_i", "blaze", "smite")
    magic_base = {kind: 0.0 for kind in kinds}
    magic_slope = {kind: 0.0 for kind in kinds}
    swp_base_term = 0.0
    swp_slope_term = 0.0
    swp_pot_base = 0.0
    swp_pot_slope = 0.0
    hellfire_exec = 0.0
    hellfire_raw = 0.0
    blood_exec = 0.0
    rad_base = 0.0
    rad_slope = 0.0
    rad_pot_base = 0.0
    rad_pot_slope = 0.0
    for when, kind, hits in events:
        execute = _execute_factor(stats, when)
        amp = _event_amp(build, stats, windows, when)
        base, slope = _magic_factors(codes, when)
        base *= amp
        slope *= amp
        if kind == "auto":
            weighed = execute * _physical_multiplier(codes, when) * amp * hits
            auto_weight += weighed
            soul_weight += weighed * target_hp(when)
        elif kind == "splash":
            splash_hits += hits * amp * execute
        elif kind == "radiance":
            rad_base += base * execute
            rad_slope += slope * execute
            rad_pot_base += base * hits * execute
            rad_pot_slope += slope * hits * execute
        elif kind in magic_base:
            magic_base[kind] += base * hits * execute
            magic_slope[kind] += slope * hits * execute
        elif kind == "swp":
            link_factor = (1.15 + 0.10 * hits) if link else 1.0
            swp_base_term += link_factor * hits * base * execute
            swp_slope_term += link_factor * hits * slope * execute
            swp_pot_base += link_factor * hits * base * execute
            swp_pot_slope += link_factor * hits * slope * execute
        elif kind == "hellfire":
            hellfire_raw = (3 + 3 * LEVEL) * (2 if hits == 1 else 0.5 if hits >= 4 else 1)
            hellfire_exec += hits * amp * execute
        if blood:
            blood_exec += amp * execute
    return {
        "spec": spec,
        "glass": glass,
        "auto_weight": auto_weight,
        "soul_weight": soul_weight,
        "splash_hits": splash_hits,
        "magic_base": magic_base,
        "magic_slope": magic_slope,
        "swp_base_term": swp_base_term,
        "swp_slope_term": swp_slope_term,
        "swp_pot_base": swp_pot_base,
        "swp_pot_slope": swp_pot_slope,
        "hellfire_exec": hellfire_exec,
        "hellfire_raw": hellfire_raw,
        "blood_exec": blood_exec,
        "rad_base": rad_base,
        "rad_slope": rad_slope,
        "rad_pot_base": rad_pot_base,
        "rad_pot_slope": rad_pot_slope,
    }


def score_compiled(
    compiled: dict,
    stats: dict,
    potency: float,
    crit: float,
    mastery_stat: float,
    luck: float = 0.0,
) -> float:
    spell_crit = _crit_factor(crit, stats["spell_mult"] + stats["rating"]) if stats["spell_crit"] else 1.0
    attack_crit = _crit_factor(crit, 2 + stats["rating"])
    spec = compiled.get("spec", "shadow")
    mastery = (1.10 + 0.006 * mastery_stat) if spec == "shadow" else 1.0
    tick_base = (15 + 0.30 * stats["int"]) * mastery
    instant_raw = (75 + 1.50 * stats["int"]) * mastery
    total = (
        (stats["ad"] + potency * stats["attack_potency"])
        * stats["auto_pct"]
        * attack_crit
        * compiled["auto_weight"]
    )
    total += (
        stats["soul_rate"]
        * MEDIAN_MONSTER_HP
        * stats["auto_pct"]
        * attack_crit
        * compiled["soul_weight"]
    )
    total += (20 + 0.35 * stats["int"]) * compiled["splash_hits"]

    def magical_weight(kind: str) -> float:
        return compiled["magic_base"][kind] + compiled["magic_slope"][kind] * mastery_stat

    mind_raw = (80 + 1.50 * stats["int"]) * (1 + 0.01 * stats["ad"])
    void_raw = (85 + 0.15 * stats["mana_max"]) * (1 + 0.007 * stats["int"])
    total += (mind_raw + potency) * spell_crit * magical_weight("mind")
    total += (void_raw + potency) * spell_crit * magical_weight("void")
    naaru_raw = (25 + 0.40 * stats["int"]) * (0.75 if spec == "discipline" else 1.0)
    total += (naaru_raw + potency) * spell_crit * magical_weight("naaru")
    total += (35 + 2 * stats["int"] + potency) * spell_crit * magical_weight("thunder")
    nuke_raw, stored = _radiance_parts(stats, mastery_stat, spec)
    rad_mag = compiled["rad_base"] + compiled["rad_slope"] * mastery_stat
    rad_pot = compiled["rad_pot_base"] + compiled["rad_pot_slope"] * mastery_stat
    total += spell_crit * (nuke_raw * rad_mag + potency * rad_pot)
    blaze_raw = (0.04 if spec == "holy" else 0.08) * stored
    total += (blaze_raw + potency) * spell_crit * magical_weight("blaze")
    smite_raw = 50 + 0.80 * stats["int"] + 0.80 * stats["str"]
    total += (smite_raw + potency) * spell_crit * magical_weight("smite")
    total += (instant_raw + potency) * spell_crit * magical_weight("swp_i")
    swp_link = compiled["swp_base_term"] + compiled["swp_slope_term"] * mastery_stat
    swp_pot = compiled["swp_pot_base"] + compiled["swp_pot_slope"] * mastery_stat
    total += spell_crit * (tick_base * swp_link + potency * swp_pot)
    if compiled["hellfire_exec"]:
        total += (compiled["hellfire_raw"] + potency) * compiled["glass"] * compiled["hellfire_exec"]
    if compiled["blood_exec"]:
        total += 0.03 * (20 + 1.6 * stats["int"] + potency) * compiled["glass"] * compiled["blood_exec"]
    total *= armor_taken(DUMMY_ARMOR - stats["armor_pen"])
    if stats["stab_chance"] and compiled["auto_weight"]:
        chance = stats["stab_chance"] * (1 + luck)
        raw = stats["stab_ratio"] * stats["ad"]
        stab = (
            (raw + potency * stats["attack_potency"])
            * stats["auto_pct"]
            * attack_crit
            * CHAOS_UNARMORED
            * chance
            * compiled["auto_weight"]
        )
        total += stab * armor_taken(DUMMY_ARMOR)
    return total


def simulate(
    build: Build,
    targets: int = 1,
    counter: dict | None = None,
    bound_spell: str | None = None,
    spec: str = "shadow",
    *,
    use_history: bool = True,
) -> Report:
    from sunken_sim.history import recall, remember

    if use_history and not (counter is not None and bound_spell is None):
        cached = recall("priest", spec, build, targets, bound_spell)
        if cached is not None:
            return cached
    if _wears(build, "I00D") and bound_spell is None:
        best_report = None
        best_counter = None
        for spell in _cast_spells(build, spec):
            trial_counter: dict | None = {"targets": targets} if counter is not None else None
            report = simulate(build, targets, trial_counter, spell, spec, use_history=use_history)
            if best_report is None or report.dps > best_report.dps:
                best_report = report
                best_counter = trial_counter
        if counter is not None and best_counter is not None:
            counter.clear()
            counter.update(best_counter)
        if not use_history:
            return best_report
        return remember("priest", spec, best_report, bound_spell)
    stats = character(build)
    key = _timeline_key(build, stats, spec, targets, bound_spell)
    cached = _TIMELINE.get(key)
    if cached is None:
        events, actions, windows, mana_left = _fight_events(build, stats, spec, targets, bound_spell)
        if len(_TIMELINE) >= 8000:
            _TIMELINE.clear()
        _TIMELINE[key] = (events, actions, windows, mana_left)
    else:
        events, actions, windows, mana_left = cached
    if counter is not None:
        counter["events"] = events
        counter["targets"] = targets
        counter["spec"] = spec
        counter["windows"] = windows
        counter["mana_left"] = mana_left
        if bound_spell is None:
            return Report(build, 0.0, 0.0, {}, actions, stats, targets, mana_left=mana_left)
    total, sources = score_events(events, build, stats, spec=spec, windows=windows)
    mode = next((name for code, name in ORB_MODE.items() if _wears(build, code)), None)
    report = Report(
        build,
        total / FIGHT,
        total,
        sources,
        actions,
        stats,
        targets,
        mode,
        bound_spell,
        mana_left,
    )
    if not use_history:
        return report
    return remember("priest", spec, report, bound_spell)


def _item_score(item: Item) -> float:
    return (
        item.intel * 4
        + item.all_stats * 4
        + item.potency * 12
        + item.damage * 2
        + item.mana * 0.08
        + item.mastery * 0.8
        + item.haste * 5
        + item.crit * 2
        + item.attack_speed * 2
        + item.damage_pct * 10
        + (30 if item.spell_crit else 0)
    )


def _polish_items(build: Build, pool: list[Item]) -> Build:
    current = list(build.items)
    while len(current) < 6:
        current.append(pool[len(current)])
    best = build
    best_dps = simulate(best).dps
    improved = True
    passes = 0
    while improved and passes < 6:
        improved = False
        passes += 1
        for slot in range(6):
            for candidate in pool:
                if any(candidate.rawcode == owned.rawcode for owned in current):
                    continue
                trial_items = current.copy()
                trial_items[slot] = candidate
                trial = Build(build.talents, build.glyphs, tuple(trial_items), build.potency_points, build.mastery_points)
                dps = simulate(trial).dps
                if dps > best_dps + 0.05:
                    best_dps = dps
                    best = trial
                    current = trial_items
                    improved = True
    return best


def search() -> Report:
    items = load_items()
    pool = sorted(items, key=_item_score, reverse=True)[:36]
    seed = tuple(pool[:6])
    talent_picks = 4 if any(item.rawcode == MIND_AMPLIFIER for item in seed) else 3
    best: Report | None = None
    for talents in itertools.combinations(TALENTS, talent_picks):
        for glyphs in itertools.combinations(GLYPHS, 3):
            for potency_points in range(SKILL_POINTS + 1):
                build = Build(
                    frozenset(talents),
                    frozenset(glyphs),
                    seed,
                    potency_points,
                    SKILL_POINTS - potency_points,
                )
                report = simulate(build)
                if best is None or report.dps > best.dps:
                    best = report
    assert best is not None
    polished = _polish_items(best.build, pool)
    final = simulate(polished)
    for potency_points in range(SKILL_POINTS + 1):
        trial = Build(
            polished.talents,
            polished.glyphs,
            polished.items,
            potency_points,
            SKILL_POINTS - potency_points,
        )
        report = simulate(trial)
        if report.dps > final.dps:
            final = report
    return simulate(_polish_items(final.build, pool))


def _ignored_lines(item: Item) -> list[str]:
    handled = (
        "abilities have their base cooldown reduced",
        "bound spell has its base cooldown reduced",
        "Increases the damage dealt by Magical Type effects",
        "Increases damage dealt by Magical and Physical",
        "base attack cooldown",
        "Critical Strike bonus damage",
        "cooldowns of all abilities",
        "cooldown of all abilities",
        "base cooldown of all abilities",
        "Stun you",
        "stun you",
        "Potency at double effectiveness",
        "Magical Type effects benefit from Critical Strike",
        "more damage to enemies below",
        "auto-attacks by",
    )
    lines = []
    for line in item.tip.split("\n"):
        text = line.strip()
        if not (text.startswith("Equip:") or text.startswith("Use:")):
            continue
        if any(phrase in text for phrase in handled):
            continue
        lines.append(text)
    return lines


def format_report(report: Report) -> str:
    stats = report.stats
    lines = [
        f"Shadow Priest, уровень 6, {report.targets} цел., 30 секунд",
        f"DPS {report.dps:.1f}    урон {report.total:.0f}",
        "",
        "Таланты: " + ", ".join(sorted(report.build.talents)),
        "Глифы: " + ", ".join(sorted(report.build.glyphs)),
        f"Очки навыков: крит {report.build.crit_points}, Potency {report.build.potency_points}, Luck {report.build.luck_points}, Mastery {report.build.mastery_points}",
        "Предметы:",
    ]
    for item in report.build.items:
        lines.append(f"  {item.name}")
    lines += [
        "",
        f"Интеллект {stats['int']:.0f}   сила атаки {stats['ad']:.1f}   Potency {stats['potency']:.1f}   Mastery {stats['mastery']:.0f}",
        f"крит {stats['crit']:.0f}%   рейтинг крита {stats['rating']:.2f}   спешка {stats['haste'] * 100:.1f}%   скорость атаки {stats['attack_speed'] * 100:.1f}%",
        f"мана {stats['mana_max']:.0f}   взмах {stats['swing']:.2f} с   тик Shadow Word: Pain {stats['swp_period']:.2f} с",
        "",
        "Источники урона",
    ]
    for name, amount in sorted(report.sources.items(), key=lambda pair: -pair[1]):
        lines.append(f"  {name:<42} {amount / report.total * 100:5.1f}%   {amount / FIGHT:7.1f} dps")
    lines += ["", "Порядок кнопок"]
    for moment, action in report.actions:
        lines.append(f"  {moment:5.2f}  {action}")
    ignored = []
    for item in report.build.items:
        extra = _ignored_lines(item)
        if extra:
            ignored.append(f"{item.name}: " + " ".join(extra))
    if ignored:
        lines += ["", "Эффекты предметов, которые симулятор не считает:"]
        lines.extend(f"  {line}" for line in ignored)
    lines += [
        "",
        "Как считается бой",
        "Здоровье каждой цели падает линейно: 100% на 0 с, смерть на 30 с.",
        "Catharsis берёт текущее здоровье цели. Казнь Aruzal — 18% ко всему урону, когда у цели 25% здоровья или меньше.",
        f"Броня манекена {DUMMY_ARMOR:.0f}: медиана монстров на Insane. Формула карты, коэффициент {ARMOR_FACTOR:.2f}.",
        "Заклинания жреца идут как обычный урон, поэтому броня их тоже режет. Сопротивление магии у этих монстров не найдено.",
        f"Каст: {CAST_POINT:.2f} с до эффекта и ещё {CAST_BACKSWING:.2f} с герой не атакует и не кастует. Ранги умений 1.",
    ]
    if stats["cast_stun_lock"]:
        lines.append(
            "Pipe of Deew: после каждого заклинания оглушение на 0,3 с. "
            "В это время нет атак, кастов и предметов."
        )
    lines += [
        "Крит и Thunder взяты ожиданием, без случайного броска.",
        "Naaru — призванный юнит, но урон наносит жрец. Глифы призыва на этот удар не попадают.",
        "Жреца держит лекарь на полном здоровье, поэтому удвоение Insanity ниже 40% не включается.",
    ]
    return "\n".join(lines)


WIN_ITEMS = (
    "Tablet of Life",
    "Aruzal, Fang of Neltharion",
    "Gar'thok's Axe",
    "Heart of Wyrmrest",
    "Predaplant Thorn",
    "Razorwind",
)
WIN_TALENTS = frozenset({"I0PS", "I0PU", "I0SC"})
WIN_GLYPHS = frozenset({"I07B", "I0JA", "I0AV"})


def saved_build() -> Build:
    by_name = {item.name: item for item in load_items()}
    missing = [name for name in WIN_ITEMS if name not in by_name]
    if missing:
        raise KeyError(", ".join(missing))
    return Build(WIN_TALENTS, WIN_GLYPHS, tuple(by_name[name] for name in WIN_ITEMS), SKILL_POINTS, 0)


def format_comparison(reports: list[Report]) -> str:
    lines = [
        "Shadow Priest, уровень 6, та же связка, 30 секунд",
        "Таланты: Catharsis, Insanity, Touch of the Naaru",
        "Глифы: Fortitude, Glass Cannon, Unsealed Power",
        "Очки: Potency 5",
        "",
        f"{'Цели':<8}{'DPS':>10}{'Урон':>10}",
    ]
    for report in reports:
        lines.append(f"{report.targets:<8}{report.dps:10.1f}{report.total:10.0f}")
    for report in reports:
        lines += ["", format_report(report)]
    return "\n".join(lines)


def main() -> None:
    build = saved_build()
    reports = [simulate(build, targets) for targets in (5,)]
    text = format_comparison(reports)
    path = Path(__file__).resolve().parents[1] / "extract" / "shadow-targets.txt"
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(text)
