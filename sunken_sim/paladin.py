"""Paladin fight for Sunken City, level 6.

Numbers are the map's. Hero H000 is a Paladin (parent Hpal): strength 25 + 2.5
per level, agility 10 + 1, intellect 15 + 1.5, attack cooldown 1.85, white
damage 12 + 1 die. Primary stat adds the same 0.75 used for the intellect
heroes, here on strength. Ability rank is 1.

Crusader Strike A0GE is the next swing within 4 seconds, base cooldown 6.
Blessed Hammer A07L lasts 9 seconds. A clump at the 80 weapon range in front
is hit together, and only while the spiral's pulse covers that point. The same
pair then waits 0.85 seconds. Holy Light heals and does not add damage.
"""

from __future__ import annotations

import math
import re

from sunken_sim.shadow import (
    item_luck,
    MAGICAL_ADDS,
    PHYSICAL_ADDS,
    Build,
    CAST_BACKSWING,
    CAST_POINT,
    DUMMY_ARMOR,
    FIGHT,
    LEVEL,
    Report,
    _copy_value,
    _crit_factor,
    _execute_factor,
    _mana_regen,
    _passive_mana,
    armor_taken,
    attack_mana_gain,
    cast_mana_back,
    sulfuras_echo_chance,
    Sulfuras,
    _wears,
    target_hp,
)
from sunken_sim.stacking import stack_fields

# int(base + (level - 1) * per level), Warcraft truncation. Fields ustr/ustp, uagi/uagp, uint/uinp.
BASE_STR = int(25 + (LEVEL - 1) * 2.5)
BASE_AGI = int(10 + (LEVEL - 1) * 1.0)
BASE_INT = int(15 + (LEVEL - 1) * 1.5)
WHITE_BASE = 13.0
SWING = 1.85
BASE_MANA = 120.0
MELEE = 80.0  # H000 attack range. A clump stands this far in front.

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
CS_MANA = 15.0
HAMMER_MANA = 5.0
# Rank 1 of A03U does not set a mana cost. Levels 2–4 are 55, 80 and 105.
HOJ_MANA = 0.0
HOJ_COOLDOWN = 18.0
GLYPH_UNSEALED = "I0AV"
GLYPH_GLASS = "I0JA"
GLYPH_FORTITUDE = "I07B"
GLYPH_SUPREMACY = "I0EK"
GLYPH_ANIMOSITY = "I0HC"
GLYPH_MINDHASTE = "I0OF"
FIRE_ORB = "I07O"
FROST_ORB = "I0NS"
GALACTIC_FURY = "I0JO"
SULFURON_GLOVES = "I0QT"
SPELLBINDER = "tlum"
JUDGEMENT_HELM = "I0QX"
BELL_RINGER = "I0R0"
GLYPH_FORTUNE = "I0EJ"


def _has(build: Build, code: str) -> bool:
    return code in build.talents or code in build.glyphs


def _orbit_hits(duration: float, pulse: float) -> tuple[float, ...]:
    """Times a clump at melee range is inside a hammer pulse.

    The hammer starts 100 in front and each 0.03 s gains 6° and 0.33 range.
    A pulse fires when the tick counter reaches 5, then the same pair waits 0.85 s.
    Targets in one point are hit together.
    """
    angle = 0.0
    distance = 100.0
    tick = 0
    time = 0.0
    left = duration
    lock = -1.0
    hits: list[float] = []
    while left > 1e-9:
        time += 0.03
        left -= 0.03
        angle += 6.0
        distance += 0.33
        if tick != 5:
            tick += 1
            continue
        tick = 0
        rad = math.radians(angle)
        hx = distance * math.cos(rad)
        hy = distance * math.sin(rad)
        if (hx - MELEE) ** 2 + hy ** 2 <= pulse * pulse and time >= lock:
            hits.append(time)
            lock = time + HAMMER_HIT
    return tuple(hits)


_ORBIT = {
    (9.0, 100.0): _orbit_hits(9.0, 100.0),
    (12.0, 100.0): _orbit_hits(12.0, 100.0),
    (9.0, 150.0): _orbit_hits(9.0, 150.0),
    (12.0, 150.0): _orbit_hits(12.0, 150.0),
}


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
    spell_mult = 1.50
    executes: list[tuple[float, float]] = []
    auto_pct = 1.0
    attack_potency = 1.0
    magic_add = 0.0
    phys_add = 0.0
    mana_flat = 0.0
    luck = 0.01 * build.luck_points
    # ESC menu (beyond crit/potency/luck/mastery)
    _esc_haste = 0.01 * getattr(build, "haste_points", 0)
    _esc_as = 0.02 * getattr(build, "attack_speed_points", 0)
    _esc_dmg = 2.0 * getattr(build, "damage_points", 0)
    _esc_mana = 20.0 * getattr(build, "mana_points", 0)
    _esc_pet = 0.015 * getattr(build, "pet_damage_points", 0)

    haste += _esc_haste
    attack_speed += _esc_as
    damage += _esc_dmg
    mana_flat += _esc_mana
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
            both = item.damage_pct / 100.0 - item.source_pct / 100.0
            magic_add += MAGICAL_ADDS.get(item.rawcode, 0.0)
            phys_add += PHYSICAL_ADDS.get(item.rawcode, 0.0)
            magic_add += item.source_pct / 100.0
            phys_add += item.source_pct / 100.0
            if item.rawcode not in MAGICAL_ADDS and item.rawcode not in PHYSICAL_ADDS:
                magic_add += both
                phys_add += both
            if item.rawcode not in (FIRE_ORB, FROST_ORB):
                armor_pen += item.armor_pen
            spell_crit = spell_crit or item.spell_crit
            if item.spell_crit and "65%" in item.tip:
                spell_mult = 1.65
            if item.execute_pct > 0:
                executes.append((item.execute_below, item.execute_pct))
            auto_pct += item.auto_pct
            if item.double_attack_potency:
                attack_potency = 2.0
            damage_pct += item.damage_pct / 100.0
            mana_flat += item.mana
            luck += item_luck(item)  # stat-line luck only (shadow.item_luck)
    if _has(build, GLYPH_FORTITUDE):
        strength += 4 + 2 * LEVEL
    if _has(build, GLYPH_SUPREMACY):
        mastery += 20
    if _has(build, GLYPH_ANIMOSITY):
        crit += 12
        rating += 0.15
    if _has(build, GLYPH_MINDHASTE):
        haste += 0.07
    if _has(build, GLYPH_UNSEALED) and not any(item.rawcode == GLYPH_UNSEALED for item in build.items):
        magic_add += 0.18
        phys_add += 0.18
    agility_speed = min(1.0, 0.004 * agility)
    attack_speed = min(4.0, max(-0.8, attack_speed + agility_speed))
    flat_cdr = 0.20 if _has(build, GLYPH_MINDHASTE) else 0.0
    codes = {item.rawcode for item in build.items}
    for code, seconds in (("I096", 0.50), ("I03C", 0.50), ("I00L", 1.50)):
        if code in codes:
            flat_cdr += seconds
    if "I00Y" in codes:
        flat_cdr -= 1.00
    cd_temp = 1.0
    if "I07P" in codes:
        cd_temp *= 0.92
    if "I048" in codes:
        cd_temp *= 0.87
    cd_temp *= 1.0 + 0.12 * sum(item.rawcode == "I0FW" for item in build.items) + 0.10 * sum(
        item.rawcode == SULFURON_GLOVES for item in build.items
    )
    if _has(build, GLYPH_FORTUNE):
        luck += 0.15
    mana_max = BASE_MANA + 7.0 * intel + mana_flat
    passive = _passive_mana(build.items)
    regen = _mana_regen(build, intel, mana_max, build.items)
    if _has(build, TALENT_DIVINE_KNOWLEDGE):
        regen += 0.03 * intel * 0.80
    cast_stun_lock = 0.0
    stun_hit_damage = 0.0
    own_stun_duration_pct = 0.0
    seen_stun: set[str] = set()
    for item in build.items:
        if item.rawcode in seen_stun:
            continue
        seen_stun.add(item.rawcode)
        if item.cast_stun_chance and item.cast_stun_duration > 0:
            cast_stun_lock += item.cast_stun_chance * item.cast_stun_duration
        stun_hit_damage += getattr(item, "stun_hit_damage", 0.0) or 0.0
        own_stun_duration_pct += getattr(item, "own_stun_duration_pct", 0.0) or 0.0
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
        "magic_add": magic_add,
        "phys_add": phys_add,
        "armor_pen": armor_pen,
        "spell_crit": 1.0 if spell_crit else 0.0,
        "spell_mult": spell_mult,
        "executes": executes,
        "auto_pct": auto_pct,
        "attack_potency": attack_potency,
        "cd_temp": cd_temp,
        "flat_cdr": flat_cdr,
        "glass": 1.0 if _has(build, GLYPH_GLASS) or GLYPH_GLASS in codes else 0.0,
        "spellbinder": 1.0 if SPELLBINDER in codes else 0.0,
        "sulfuron": 1.0 if SULFURON_GLOVES in codes else 0.0,
        "galactic": 1.0 if GALACTIC_FURY in codes else 0.0,
        "judgement": 1.0 if JUDGEMENT_HELM in codes else 0.0,
        "fire_orb": 1.0 if FIRE_ORB in codes else 0.0,
        "bell": 1.0 if BELL_RINGER in codes else 0.0,
        "luck": luck,
        "mana_max": mana_max,
        "mana_regen": regen,
        "cast_stun_lock": cast_stun_lock,
        "stun_hit_damage": stun_hit_damage,
        "own_stun_duration_pct": own_stun_duration_pct,
        **passive,
    }


def _cooldown(base: float, haste: float, stats: dict) -> float:
    return max(0.5, (base * stats["cd_temp"] - stats["flat_cdr"]) / (1.0 + haste))


def _typed_bonus(stats: dict, magical: bool, when: float, mastery_now: float, knowledge: float) -> float:
    bonus = 1.0 + (stats["magic_add"] if magical else stats["phys_add"])
    if stats["sulfuron"]:
        bonus += 0.13 + 0.25 * target_hp(when)
    if magical and stats["spellbinder"]:
        bonus += 0.05 + 0.005 * mastery_now
    if stats["glass"]:
        bonus *= 1.15
    if magical:
        bonus *= knowledge
    return bonus


def _timeline_key(build: Build, stats: dict, spec: str, targets: int) -> tuple:
    items = tuple(sorted(item.rawcode for item in build.items))
    talents = tuple(sorted(build.talents))
    glyphs = tuple(sorted(build.glyphs))
    # All fight inputs among the ESC points: luck (Divine Toll / bell hammer weight), crit (crit-doubled
    # attack mana); potency is score-time only but kept too, so a replay never comes from other points.
    esc = (
        build.crit_points,
        build.potency_points,
        build.mastery_points,
        build.luck_points,
        getattr(build, "haste_points", 0),
        getattr(build, "attack_speed_points", 0),
        getattr(build, "damage_points", 0),
        getattr(build, "mana_points", 0),
        getattr(build, "pet_damage_points", 0),
    )
    return (items, talents, glyphs, esc, spec, targets, round(stats["str"], 6), round(stats["int"], 6))


_TIMELINE: dict[tuple, tuple] = {}


def _fight_events(build: Build, stats: dict, spec: str, targets: int) -> tuple:
    """CPU timeline: list of damage events + actions + mana_left. No scoring."""
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
    actions: list[tuple[float, str]] = []
    events: list[tuple] = []
    fury_attacks = 0
    crusade = 0
    hammer_duration = 12.0 if _has(build, TALENT_DIVINE_HAMMER) else 9.0
    pulse = 150.0 if _has(build, TALENT_DIVINE_HAMMER) else 100.0
    orbit = _ORBIT[(hammer_duration, pulse)]
    mana = stats["mana_max"]
    mana_time = 0.0
    sulfuras = Sulfuras() if _wears(build, "I0BR") else None
    toll = 0.25 * (1.0 + stats["luck"]) if _has(build, TALENT_DIVINE_TOLL) or stats["bell"] else 0.0

    def mastery() -> float:
        return stats["mastery"] + mastery_bonus

    def emit(name: str, raw: float, magical: bool, count: int, when: float, potency_scale: float = 1.0, auto_scale: bool = False) -> None:
        events.append((when, name, raw, magical, count, potency_scale, mastery(), auto_scale))

    def hammer_count(now: float) -> float:
        return sum(hammer["weight"] for hammer in hammers if hammer["start"] <= now < hammer["end"])

    def spawn(now: float, weight: float) -> None:
        nonlocal hammers
        if weight <= 0:
            return
        first = orbit[0] if orbit else hammer_duration
        hammers.append(
            {
                "start": now,
                "end": now + hammer_duration,
                "hits": orbit,
                "index": 0,
                "next": now + first,
                "weight": weight,
            }
        )

    def recover(now: float) -> None:
        nonlocal mana, mana_time
        if now > mana_time and mana < stats["mana_max"]:
            mana = min(stats["mana_max"], mana + stats["mana_regen"] * (now - mana_time))
        mana_time = now

    def pay(cost: float, now: float) -> bool:
        nonlocal mana
        recover(now)
        if mana < cost:
            return False
        mana -= cost
        mana = min(stats["mana_max"], mana + cast_mana_back(cost, stats))
        return True

    def note_damage_mana(count: int) -> None:
        nonlocal mana
        if stats["damage_mana_pct"]:
            mana = min(stats["mana_max"], mana + stats["damage_mana_pct"] * stats["mana_max"] * count)

    def cast(now: float) -> float:
        nonlocal zeal_charges, zeal_until
        if sulfuras is not None:
            sulfuras.cast()
        if _has(build, TALENT_ZEAL):
            zeal_charges = 2
            zeal_until = now + 4.0
        return now + CAST_POINT + CAST_BACKSWING + stats["cast_stun_lock"]

    guard = 0
    while next_attack < FIGHT or next_cs < FIGHT or next_hammer < FIGHT or hammers:
        guard += 1
        if guard > 200000:
            break
        hit_at = FIGHT
        for hammer in hammers:
            if hammer["next"] < hammer["end"]:
                hit_at = min(hit_at, hammer["next"])
        expire = min((hammer["end"] for hammer in hammers), default=FIGHT)
        moment = min(
            next_attack,
            next_cs,
            next_hammer,
            next_hoj if _has(build, TALENT_HAMMER_OF_JUSTICE) else FIGHT,
            hit_at,
            expire,
        )
        if moment >= FIGHT:
            break
        due = [hammer for hammer in hammers if hammer["next"] <= moment < hammer["end"]]
        if due and hit_at <= moment + 1e-9:
            recover(moment)
            for hammer in due:
                emit(
                    "Blessed Hammer",
                    (5.0 + 10.0 * RANK + 0.45 * stats["str"]) * hammer["weight"],
                    True,
                    targets,
                    moment,
                )
                note_damage_mana(targets)
                hammer["index"] += 1
                hits = hammer["hits"]
                hammer["next"] = hammer["start"] + hits[hammer["index"]] if hammer["index"] < len(hits) else hammer["end"]
                if _has(build, TALENT_HAMMER_MASTERY):
                    mastery_bonus = min(30.0, mastery_bonus + 2.0 * hammer["weight"] * targets)
                if _has(build, TALENT_HAMMER_OF_JUSTICE):
                    next_hoj = max(moment, next_hoj - 0.10 * hammer["weight"] * targets)
            hammers = [hammer for hammer in hammers if hammer["end"] > moment + 1e-9]
            continue
        if abs(moment - expire) <= 1e-9:
            hammers = [hammer for hammer in hammers if hammer["end"] > moment + 1e-9]
            continue
        if moment == next_attack and next_attack < busy:
            next_attack = busy
            continue
        if moment == next_attack:
            recover(moment)
            swing = SWING * (1.20 if stats["galactic"] else 1.0)
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
                if stats["judgement"]:
                    raw *= 1.0 + 0.05 * hammer_count(moment)
                emit("Crusader Strike", raw, True, 1, moment)
                note_damage_mana(1)
                cs_until = -1.0
                if _has(build, TALENT_DIVINE_STORM):
                    storm = 20.0 + stats["str"] + stats["int"] + mastery()
                    if spec != "retribution":
                        storm *= 0.5
                    emit("Divine Storm", storm, True, targets, moment)
                    note_damage_mana(targets)
            emit(
                "Автоатака",
                WHITE_BASE + 0.75 * stats["str"] + stats["damage"],
                False,
                1,
                moment,
                stats["attack_potency"],
                True,
            )
            mana = min(stats["mana_max"], mana + attack_mana_gain(stats))
            note_damage_mana(1)
            fury_attacks += 1
            if not _has(build, TALENT_HAMMER_OF_JUSTICE) and fury_attacks >= 3:
                fury_attacks = 0
                emit("Righteous Fury", 5.0 + 25.0 * RANK + 2.0 * stats["str"], True, 1, moment)
                note_damage_mana(1)
            if stats["fire_orb"]:
                # fire splash: no potency / crit / typed in the old path — keep same
                emit("Всплеск огня", (20.0 + 0.35 * stats["str"]), False, targets, moment, 0.0, False)
                # Old code skipped typed/crit and used taken*execute only; flag via pot_scale=-1 sentinel? 
                # Handled in score_events via name special-case below.
                note_damage_mana(targets)
            if sulfuras is not None:
                if sulfuras.attack():
                    emit("Sulfuras", stats["str"], True, targets, moment, 0.0, False)
                    note_damage_mana(targets)
                emit(
                    "Sulfuras (удар)",
                    WHITE_BASE + 0.75 * stats["str"] + stats["damage"],
                    False,
                    1,
                    moment,
                    0.0,
                    False,
                )
            if _has(build, TALENT_CRUSADE) and crusade < 20:
                crusade = min(20, crusade + 2)
                haste = stats["haste"] + crusade / 100.0
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
            if not pay(CS_MANA, moment):
                next_cs = moment + 0.25
                continue
            actions.append((moment, "Crusader Strike"))
            cs_until = moment + CS_BUFF
            busy = cast(moment)
            next_cs = moment + _cooldown(CS_COOLDOWN, haste, stats)
            next_attack = max(next_attack, busy)
            continue
        if moment == next_hammer:
            if not pay(HAMMER_MANA, moment):
                next_hammer = moment + 0.25
                continue
            actions.append((moment, "Blessed Hammer"))
            spawn(moment + CAST_POINT, 1.0)
            if toll:
                spawn(moment + CAST_POINT + 0.5, toll)
            busy = cast(moment)
            next_hammer = moment + _cooldown(HAMMER_COOLDOWN, haste, stats)
            next_attack = max(next_attack, busy)
            continue
        if _has(build, TALENT_HAMMER_OF_JUSTICE) and moment == next_hoj:
            if not pay(HOJ_MANA, moment):
                next_hoj = moment + 0.25
                continue
            actions.append((moment, "Hammer of Justice"))
            raw = (60.0 + 1.75 * stats["str"]) * (1.0 + 0.01 * stats["int"])
            emit("Hammer of Justice", raw, True, 1, moment)
            if stats.get("stun_hit_damage"):
                # I0E4: flat 100 whenever you Stun; through typed/crit/armor like other hits.
                emit("Stun", float(stats["stun_hit_damage"]), False, 1, moment, 0.0, False)
            busy = cast(moment)
            next_hoj = moment + _cooldown(HOJ_COOLDOWN, haste, stats)
            next_attack = max(next_attack, busy)
            continue
        break

    recover(FIGHT)
    mana_left = 0.0 if stats["mana_max"] <= 0 else 100.0 * mana / stats["mana_max"]
    return events, actions, mana_left


def score_events(
    events: list[tuple],
    stats: dict,
    *,
    attack_crit: float,
    spell_crit: float,
    knowledge: float,
    taken: float,
) -> dict[str, float]:
    """Score timeline events. Fire-orb splash keeps the old taken*execute-only path."""
    sources: dict[str, float] = {}
    for when, name, raw, magical, count, pot_scale, mastery_now, auto_scale in events:
        if name == "Всплеск огня":
            # old: (20+0.35*str)*targets * taken * execute  (no typed/crit/potency)
            amount = raw * taken * _execute_factor(stats, when)
            sources[name] = sources.get(name, 0.0) + amount * count
            continue
        if name == "Sulfuras (удар)":
            # white * taken * execute * echo_chance  (no typed/crit/potency)
            amount = raw * taken * _execute_factor(stats, when) * sulfuras_echo_chance(stats["luck"])
            sources[name] = sources.get(name, 0.0) + amount * count
            continue
        amount = raw + stats["potency"] * pot_scale
        amount *= _typed_bonus(stats, magical, when, mastery_now, knowledge)
        amount *= spell_crit if magical else attack_crit
        amount *= taken * _execute_factor(stats, when)
        if auto_scale:
            amount *= stats["auto_pct"]
        sources[name] = sources.get(name, 0.0) + amount * count
    return sources


def simulate(build: Build, targets: int = 5, spec: str = "retribution") -> Report:
    if spec not in SPECS:
        raise ValueError(spec)
    if targets < 1:
        raise ValueError(targets)
    stats = stats_of(build)
    taken = armor_taken(DUMMY_ARMOR - stats["armor_pen"])
    attack_crit = _crit_factor(stats["crit"], 2.0 + stats["rating"])
    spell_crit = _crit_factor(stats["crit"], stats["spell_mult"] + stats["rating"]) if stats["spell_crit"] else 1.0
    knowledge = (
        1.0 + 0.003 * stats["int"]
        if spec == "retribution" and _has(build, TALENT_DIVINE_KNOWLEDGE)
        else 1.0
    )
    key = _timeline_key(build, stats, spec, targets)
    cached = _TIMELINE.get(key)
    if cached is None:
        cached = _fight_events(build, stats, spec, targets)
        while len(_TIMELINE) >= 8000:
            _TIMELINE.pop(next(iter(_TIMELINE)))
        _TIMELINE[key] = cached
    events, actions, mana_left = cached
    sources = score_events(
        events,
        stats,
        attack_crit=attack_crit,
        spell_crit=spell_crit,
        knowledge=knowledge,
        taken=taken,
    )
    total = sum(sources.values())
    return Report(build, total / FIGHT, total, sources, actions, stats, targets, mana_left=mana_left)


def best_points(build: Build, targets: int, spec: str) -> tuple[float, dict[str, int]]:
    from sunken_sim.esc import apply_points, greedy_points, points_payload

    def score(pts: dict) -> float:
        trial = apply_points(build, pts)
        report = simulate(trial, targets, spec)
        return report.dps

    dps, pts = greedy_points(score)
    return dps, points_payload(pts)


