"""Paladin fight for Sunken City, level 6.

Numbers are the map's. Hero H000 is a Paladin (parent Hpal): strength 25 + 2.5
per level, agility 10 + 1, intellect 15 + 1.5, attack cooldown 1.85, white
damage 12 + 1 die. Primary stat adds the same 0.75 used for the intellect
heroes, here on strength. Ability rank is 1.

Crusader Strike A0GE is the next swing within 4 seconds, base cooldown 6.
Blessed Hammer A07L lasts 9 seconds, hits each target every 0.85 seconds,
base cooldown 4.5. Holy Light heals and does not add damage. Hammer of Justice
is the talent that replaces Righteous Fury.
"""

from __future__ import annotations

from sunken_sim.shadow import (
    Build,
    CAST_BACKSWING,
    CAST_POINT,
    DUMMY_ARMOR,
    FIGHT,
    LEVEL,
    Report,
    _copy_value,
    _crit_factor,
    armor_taken,
)
from sunken_sim.stacking import stack_fields

# int(base + (level - 1) * per level), Warcraft truncation. Fields ustr/ustp, uagi/uagp, uint/uinp.
BASE_STR = int(25 + (LEVEL - 1) * 2.5)
BASE_AGI = int(10 + (LEVEL - 1) * 1.0)
BASE_INT = int(15 + (LEVEL - 1) * 1.5)
WHITE_BASE = 13.0
SWING = 1.85

CS = "I0"  # talent ids below
TALENT_DIVINE_STORM = "I04C"
TALENT_DIVINE_HAMMER = "I064"
TALENT_DIVINE_TOLL = "I09Y"
TALENT_DIVINE_KNOWLEDGE = "I09R"
TALENT_ZEAL = "I01J"
TALENT_HAMMER_MASTERY = "I0G8"
TALENT_HAMMER_OF_JUSTICE = "I0NG"
TALENT_CRUSADE = "I0NC"
TALENT_SACRED_TOUCH = "I0OQ"

TALENTS = {
    "I0OT": "Righteousness",
    "I09Y": "Divine Toll",
    "I09R": "Divine Knowledge",
    "I069": "Holy Avenger",
    "I064": "Divine Hammer",
    "I04C": "Divine Storm",
    "I09L": "Beacon of Light",
    "I01J": "Zeal",
    "I0NG": "Hammer of Justice",
    "I0I1": "Guarded by the Light",
    "I09Z": "Barrier of Faith",
    "I0OR": "Holy Aura",
    "I0OQ": "Sacred Touch",
    "I0G8": "Hammer Mastery",
    "I0OU": "Redemption",
    "I0OS": "Judgement",
    "I0NC": "Crusade",
    "I0ND": "Infusion of Light",
}

SPECS = ("retribution", "protection", "holy")
RANK = 1
CS = "A0GE"
CS_COOLDOWN = 6.0
CS_BUFF = 4.0
HAMMER_COOLDOWN = 4.5
HAMMER_HIT = 0.85
HOJ_COOLDOWN = 18.0
GLYPH_UNSEALED = "I0AV"
GLYPH_GLASS = "I0JA"


def _has(build: Build, code: str) -> bool:
    return code in build.talents or code in build.glyphs


def stats_of(build: Build) -> dict[str, float]:
    strength = float(BASE_STR)
    agility = float(BASE_AGI)
    intel = float(BASE_INT)
    potency = 0.5 * build.potency_points
    mastery = float(build.mastery_points)
    damage = 0.0
    crit = float(build.crit_points)
    rating = 0.0
    haste = 0.0
    attack_speed = 0.0
    damage_pct = 0.0
    armor_pen = 0.0
    spell_crit = False
    seen: set[str] = set()
    for item in build.items:
        first = item.rawcode not in seen
        seen.add(item.rawcode)
        bonus = stack_fields(item.rawcode)
        strength += _copy_value(item.rawcode, "strength", item.strength, first)
        strength += _copy_value(item.rawcode, "all_stats", item.all_stats, first)
        agility += _copy_value(item.rawcode, "agility", item.agility, first)
        agility += _copy_value(item.rawcode, "all_stats", item.all_stats, first)
        intel += _copy_value(item.rawcode, "intel", item.intel, first)
        intel += _copy_value(item.rawcode, "all_stats", item.all_stats, first)
        if first and bonus.get("primary") and not item.strength and not item.all_stats:
            strength += bonus["primary"]
        elif not first:
            strength += bonus.get("primary", 0)
        potency += _copy_value(item.rawcode, "potency", item.potency, first)
        mastery += _copy_value(item.rawcode, "mastery", item.mastery, first)
        damage += _copy_value(item.rawcode, "damage", item.damage, first)
        crit += _copy_value(item.rawcode, "crit", item.crit, first)
        rating += _copy_value(item.rawcode, "crit_rating", item.crit_rating, first)
        haste += _copy_value(item.rawcode, "haste", item.haste, first) / 100
        attack_speed += _copy_value(item.rawcode, "attack_speed", item.attack_speed, first) / 100
        if first:
            damage_pct += item.damage_pct
            armor_pen += item.armor_pen
            spell_crit = spell_crit or item.spell_crit
    attack_speed += 0.004 * agility
    attack_speed = min(4.0, max(-0.8, attack_speed))
    return {
        "str": strength,
        "agi": agility,
        "int": intel,
        "potency": potency,
        "mastery": mastery,
        "damage": damage,
        "crit": crit,
        "rating": rating,
        "haste": haste,
        "attack_speed": attack_speed,
        "damage_pct": damage_pct,
        "armor_pen": armor_pen,
        "spell_crit": 1.0 if spell_crit else 0.0,
    }


def _cooldown(base: float, haste: float) -> float:
    return max(0.5, base / (1.0 + haste))


def simulate(build: Build, targets: int = 5, spec: str = "retribution") -> Report:
    if spec not in SPECS:
        raise ValueError(spec)
    if targets < 1:
        raise ValueError(targets)
    stats = stats_of(build)
    taken = armor_taken(DUMMY_ARMOR - stats["armor_pen"])
    attack_crit = _crit_factor(stats["crit"], 2.0 + stats["rating"])
    spell_crit = attack_crit if stats["spell_crit"] else 1.0
    magic = 1.0 + stats["damage_pct"]
    physical = 1.0 + stats["damage_pct"]
    if _has(build, GLYPH_UNSEALED):
        magic += 0.18
        physical += 0.18
    if _has(build, GLYPH_GLASS):
        magic *= 1.15
        physical *= 1.15
    if spec == "retribution" and _has(build, TALENT_DIVINE_KNOWLEDGE):
        magic *= 1.0 + 0.003 * stats["int"]

    sources = {"Автоатака": 0.0, "Crusader Strike": 0.0, "Blessed Hammer": 0.0, "Divine Storm": 0.0, "Hammer of Justice": 0.0}
    haste = stats["haste"]
    mastery_bonus = 0.0
    zeal_charges = 0
    zeal_until = -1.0
    cs_until = -1.0
    next_attack = 0.0
    next_cs = 0.0
    next_hammer = 0.0
    next_hoj = 0.0
    busy = 0.0
    hammers: list[dict] = []
    hammer_duration = 12.0 if _has(build, TALENT_DIVINE_HAMMER) else 9.0

    def mastery() -> float:
        return stats["mastery"] + mastery_bonus

    def deal(name: str, raw: float, magical: bool, count: int) -> None:
        amount = raw + stats["potency"]
        amount *= magic if magical else physical
        amount *= spell_crit if magical else attack_crit
        amount *= taken
        sources[name] += amount * count

    def hammer_count(now: float) -> float:
        return sum(hammer["weight"] for hammer in hammers if hammer["start"] <= now < hammer["end"])

    def spawn(now: float, weight: float) -> None:
        hammers.append({"start": now, "end": now + hammer_duration, "next": now, "weight": weight})

    def cast(now: float) -> float:
        nonlocal zeal_charges, zeal_until
        if _has(build, TALENT_ZEAL):
            zeal_charges = 2
            zeal_until = now + 4.0
        return now + CAST_POINT + CAST_BACKSWING

    guard = 0
    while next_attack < FIGHT or next_cs < FIGHT or next_hammer < FIGHT or hammers:
        guard += 1
        if guard > 200000:
            break
        hit_at = FIGHT
        for hammer in hammers:
            if hammer["next"] < hammer["end"]:
                hit_at = min(hit_at, hammer["next"])
        moment = min(next_attack, next_cs, next_hammer, next_hoj if _has(build, TALENT_HAMMER_OF_JUSTICE) else FIGHT, hit_at)
        if moment >= FIGHT:
            break
        due = [hammer for hammer in hammers if hammer["next"] <= moment < hammer["end"]]
        if due and hit_at <= moment + 1e-9:
            for hammer in due:
                deal("Blessed Hammer", (5.0 + 10.0 * RANK + 0.45 * stats["str"]) * hammer["weight"], True, targets)
                hammer["next"] += HAMMER_HIT
                if _has(build, TALENT_HAMMER_MASTERY):
                    mastery_bonus = min(30.0, mastery_bonus + 2.0 * hammer["weight"] * targets)
                if _has(build, TALENT_HAMMER_OF_JUSTICE):
                    next_hoj = max(moment, next_hoj - 0.10 * hammer["weight"] * targets)
            hammers = [hammer for hammer in hammers if hammer["next"] < hammer["end"]]
            continue
        if moment == next_attack and next_attack < busy:
            next_attack = busy
            continue
        if moment == next_attack:
            swing = SWING
            if spec == "retribution":
                swing *= max(0.2, 1.0 - 0.03 * hammer_count(moment))
            speed = stats["attack_speed"]
            if zeal_charges and moment <= zeal_until:
                speed = min(4.0, speed + 0.80)
                zeal_charges -= 1
            interval = swing / (1.0 + speed)
            if cs_until >= moment:
                raw = 90.0 * RANK + 30.0 + 2.75 * stats["str"]
                if spec == "retribution":
                    raw *= 1.10 + 0.01 * mastery()
                deal("Crusader Strike", raw, True, 1)
                cs_until = -1.0
                if _has(build, TALENT_DIVINE_STORM):
                    storm = 20.0 + stats["str"] + stats["int"] + mastery()
                    if spec != "retribution":
                        storm *= 0.5
                    deal("Divine Storm", storm, True, targets)
            deal("Автоатака", WHITE_BASE + 0.75 * stats["str"] + stats["damage"], False, 1)
            if _has(build, TALENT_CRUSADE):
                haste = min(0.20, haste + 0.02)
            next_attack = moment + interval
            continue
        if moment < busy:
            if moment == next_cs:
                next_cs = busy
            elif moment == next_hammer:
                next_hammer = busy
            elif moment == next_hoj:
                next_hoj = busy
            else:
                break
            continue
        if moment == next_cs:
            cs_until = moment + CS_BUFF
            busy = cast(moment)
            next_cs = moment + _cooldown(CS_COOLDOWN, haste)
            next_attack = max(next_attack, busy)
            continue
        if moment == next_hammer:
            spawn(moment + CAST_POINT, 1.0)
            if _has(build, TALENT_DIVINE_TOLL):
                spawn(moment + CAST_POINT + 0.5, 0.25)
            busy = cast(moment)
            next_hammer = moment + _cooldown(HAMMER_COOLDOWN, haste)
            next_attack = max(next_attack, busy)
            continue
        if _has(build, TALENT_HAMMER_OF_JUSTICE) and moment == next_hoj:
            raw = (60.0 + 1.75 * stats["str"]) * (1.0 + 0.01 * stats["int"])
            deal("Hammer of Justice", raw, True, 1)
            busy = cast(moment)
            next_hoj = moment + _cooldown(HOJ_COOLDOWN, haste)
            next_attack = max(next_attack, busy)
            continue
        break

    total = sum(sources.values())
    return Report(build, total / FIGHT, total, sources, [], stats, targets)


def best_points(build: Build, targets: int, spec: str) -> tuple[float, tuple[int, int, int, int]]:
    from sunken_sim.search import POINT_SPLITS

    best_dps = -1.0
    best = (0, 5, 0, 0)
    for crit, potency, luck, mastery in POINT_SPLITS:
        trial = Build(build.talents, build.glyphs, build.items, potency, mastery, crit, luck)
        report = simulate(trial, targets, spec)
        if report.dps > best_dps:
            best_dps = report.dps
            best = (crit, potency, luck, mastery)
    return best_dps, best
