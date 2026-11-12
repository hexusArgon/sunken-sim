"""Berserker fight for Sunken City, level 6.

Unit O005 (Fury switches to melee O01R, same sheet). Agility 28 + 2.8,
strength 14 + 1.4, intellect 8 + 0.8. White hit 29 + 1 die, attack cooldown
1.6, primary AGI. Ability rank is 1. Spec level on A0KW: 1 Headhunter,
2 Poison, 3 Fury.

Toxic Sack A0A6, Skull Split A0A7, Venomous Axes A004 (passive poison),
Blood Fury A016 (toggle, modelled always on), Regeneration A0KX (heal, not
scored). Healing is not scored.
"""

from __future__ import annotations

import math
import re

from sunken_sim.pressure import hero_hp_ratio, max_hp
from sunken_sim.shadow import (
    CAST_BACKSWING,
    CAST_POINT,
    DUMMY_ARMOR,
    FIGHT,
    LEVEL,
    MAGICAL_ADDS,
    MEDIAN_MONSTER_HP,
    PHYSICAL_ADDS,
    Build,
    Report,
    Sulfuras,
    _copy_value,
    _crit_factor,
    _execute_factor,
    _mana_regen,
    _passive_mana,
    _wears,
    armor_taken,
    attack_mana_gain,
    cast_mana_back,
    sulfuras_echo_chance,
    target_hp,
)
from sunken_sim.stacking import stack_fields
from sunken_sim.ledger import Ledger, attach, score_events  # noqa: F401

BASE_STR = int(14 + (LEVEL - 1) * 1.4)
BASE_AGI = int(28 + (LEVEL - 1) * 2.8)
BASE_INT = int(8 + (LEVEL - 1) * 0.8)
# Trophy Skull / Trophies (udg_Trophies_Total, A0L0) long-term stacks farmed
# before the fight: 13.333… per hero level, rounded to nearest (lvl 15 → 200).
# Map: every 10th enemy death drops a trophy (Trophies_Drop), +1 when the
# Berserker picks it up; DCS_Damage += Trophies_Total (DCS_Other_Damage_Sources).
# 200 trophies ≈ 2000 kills; about 38 % of the top builds' DPS (kept by decision, 2026-11-12).
TROPHIES = int(math.floor(13.33333333333333333 * LEVEL + 0.5))
WHITE_BASE = 30.0
SWING = 1.6
BASE_MANA = 120.0
BASE_HP = 230.0

SPECS = ("headhunter", "poison", "fury")
HERO_CLASS = "Berserker"
RANK = 1

TALENT_AXE_MASTERY = "I0LO"
TALENT_MIGHT_OF_DAMBALA = "I0PE"
TALENT_BERSERK = "I0A2"
TALENT_EXECUTOR = "I0LS"
TALENT_DEADLY_POISON = "I09O"
TALENT_VOODOO_SHUFFLE = "I0LP"
TALENT_POISON_BOMB = "I0LR"
TALENT_BONESLICER = "I09V"
TALENT_BLOOD_CRAZE = "I0LQ"
TALENT_NEXT_PAGE = "I0MD"
TALENT_LEECHING_POISON = "I0PD"
TALENT_POISONED_BLADES = "I0PF"
TALENT_BLOOD_HUNTER = "I0A3"
TALENT_WAY_OF_THE_SNAKE = "I0PG"
TALENT_TAZDINGO = "I0PH"
TALENT_WOUND_POISON = "I0HS"
TALENT_HEMOTOXIN = "I0TZ"
TALENT_GURUBASHI_WARD = "I0U0"
TALENT_GIFT = "I0U1"
TALENT_PREV_PAGE = "I0MC"

TALENTS = {
    TALENT_AXE_MASTERY: "Axe Mastery",
    TALENT_MIGHT_OF_DAMBALA: "Might of Dambala",
    TALENT_BERSERK: "Berserk",
    TALENT_EXECUTOR: "Executor",
    TALENT_DEADLY_POISON: "Deadly Poison",
    TALENT_VOODOO_SHUFFLE: "Voodoo Shuffle",
    TALENT_POISON_BOMB: "Poison Bomb",
    TALENT_BONESLICER: "Boneslicer",
    TALENT_BLOOD_CRAZE: "Blood Craze",
    TALENT_LEECHING_POISON: "Leeching Poison",
    TALENT_POISONED_BLADES: "Poisoned Blades",
    TALENT_BLOOD_HUNTER: "Blood Hunter",
    TALENT_WAY_OF_THE_SNAKE: "Way of the Snake",
    TALENT_TAZDINGO: "Taz'dingo",
    TALENT_WOUND_POISON: "Wound Poison",
    TALENT_HEMOTOXIN: "Hemotoxin",
    TALENT_GURUBASHI_WARD: "Gurubashi Ward",
    TALENT_GIFT: "Gift of the Blood God",
}

IGNORED_TALENTS = frozenset(
    {
        TALENT_NEXT_PAGE,
        TALENT_PREV_PAGE,
        TALENT_VOODOO_SHUFFLE,
        TALENT_TAZDINGO,
        TALENT_GURUBASHI_WARD,
    }
)

SACK_CD = 10.0
SACK_MANA = 30.0
SACK_DELAY = 0.75
SKULL_CD = 20.0
SKULL_MANA = 25.0
VA_DUR = 4.0
VA_SLOTS = 8  # expiry points kept per target (at most one per tick of the last 4 s, plus the last sure apply)
SURGE_DUR = 5.0
BERSERK_DUR = 6.0
PRESSURE_STEP = 0.2
BLOOD_CRAZE_DCS = 30.0  # A0KA level 3 (hero level 6-10)

GLYPH_UNSEALED = "I0AV"
GLYPH_GLASS = "I0JA"
GLYPH_FORTITUDE = "I07B"
GLYPH_SUPREMACY = "I0EK"
GLYPH_ANIMOSITY = "I0HC"
GLYPH_MINDHASTE = "I0OF"
GLYPH_FORTUNE = "I0EJ"
GLYPH_BATTLE_FRENZY = "I0GZ"
FIRE_ORB = "I07O"
FROST_ORB = "I0NS"
GALACTIC_FURY = "I0JO"
SULFURON_GLOVES = "I0QT"
SPELLBINDER = "tlum"
ITEM_VENOMBITE = "I0U2"
ITEM_BLOOD_FANATIC = "I0U5"


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
    executes: list[tuple[float, float]] = []
    auto_pct = 1.0
    attack_potency = 1.0
    magic_add = 0.0
    phys_add = 0.0
    mana_flat = 0.0
    health_flat = 0.0
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
        if first and bonus.get("primary") and not item.agility and not item.all_stats:
            agility += bonus["primary"]
        elif not first:
            agility += bonus.get("primary", 0)
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
            if item.execute_pct > 0:
                executes.append((item.execute_below, item.execute_pct))
            auto_pct += item.auto_pct
            if item.double_attack_potency:
                attack_potency = 2.0
            damage_pct += item.damage_pct / 100.0
            mana_flat += item.mana
            for raw in re.findall(r"\+(\d+)% Luck\b", item.tip):
                luck += int(raw) / 100.0
            for raw in re.findall(r"\+(\d+) Health\b", item.tip):
                health_flat += int(raw)
    if _has(build, GLYPH_FORTITUDE):
        agility += 4 + 2 * LEVEL
    if _has(build, GLYPH_SUPREMACY):
        mastery += 20
    if _has(build, GLYPH_ANIMOSITY):
        crit += 12
        rating += 0.15
    if _has(build, GLYPH_MINDHASTE):
        haste += 0.07
    if _has(build, GLYPH_BATTLE_FRENZY):
        attack_speed += 0.10
    if _has(build, GLYPH_UNSEALED) and not any(item.rawcode == GLYPH_UNSEALED for item in build.items):
        magic_add += 0.18
        phys_add += 0.18
    if _has(build, GLYPH_FORTUNE):
        luck += 0.15
    # Blood Fury A016 on: AGI += floor(maxHP / 25), cap 100 unless Gift of the Blood God.
    hp_before = max_hp(BASE_HP, strength) + health_flat
    fury_agi = float(int(hp_before / 25.0))
    if not _has(build, TALENT_GIFT):
        fury_agi = min(100.0, fury_agi)
    agility += fury_agi
    if _has(build, TALENT_GIFT):
        strength += 10 + LEVEL  # A0L3, added after the AGI snapshot
    hp = max_hp(BASE_HP, strength) + health_flat
    phys_add_hemo = 0.08 + 0.0025 * agility if _has(build, TALENT_HEMOTOXIN) else 0.0
    agility_speed = min(1.0, 0.004 * agility)
    attack_speed = attack_speed + agility_speed
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
    mana_max = BASE_MANA + 7.0 * intel + mana_flat
    passive = _passive_mana(build.items)
    regen = _mana_regen(build, intel, mana_max, build.items)
    cast_stun_lock = 0.0
    seen_stun: set[str] = set()
    for item in build.items:
        if item.rawcode in seen_stun:
            continue
        seen_stun.add(item.rawcode)
        if item.cast_stun_chance and item.cast_stun_duration > 0:
            cast_stun_lock += item.cast_stun_chance * item.cast_stun_duration
    return {
        "str": strength,
        "agi": agility,
        "int": intel,
        "fury_agi": fury_agi,
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
        "hemotoxin_add": phys_add_hemo,
        "armor_pen": armor_pen,
        "executes": executes,
        "auto_pct": auto_pct,
        "attack_potency": attack_potency,
        "cd_temp": cd_temp,
        "flat_cdr": flat_cdr,
        "glass": 1.0 if _has(build, GLYPH_GLASS) or GLYPH_GLASS in codes else 0.0,
        "spellbinder": 1.0 if SPELLBINDER in codes else 0.0,
        "sulfuron": 1.0 if SULFURON_GLOVES in codes else 0.0,
        "galactic": 1.0 if GALACTIC_FURY in codes else 0.0,
        "fire_orb": 1.0 if FIRE_ORB in codes else 0.0,
        "venombite": 1.0 if ITEM_VENOMBITE in codes else 0.0,
        "blood_fanatic": 1.0 if ITEM_BLOOD_FANATIC in codes else 0.0,
        "luck": luck,
        "mana_max": mana_max,
        "mana_regen": regen,
        "cast_stun_lock": cast_stun_lock,
        "hp": hp,
        **passive,
    }


def _cooldown(base: float, haste: float, stats: dict) -> float:
    return max(0.5, (base * stats["cd_temp"] - stats["flat_cdr"]) / (1.0 + haste))


def _chance(value: float) -> float:
    return max(0.0, min(1.0, value))


def _timeline_key(build: Build, stats: dict, spec: str, targets: int) -> tuple:
    """Safe GPU tape cluster key; only potency_points is unbaked.

    Item order is retained (duplicate-item stacking can depend on it). Full
    computed stats protect custom items sharing rawcodes. No CPU tape cache.
    """
    from dataclasses import fields

    def freeze(value):
        if isinstance(value, dict):
            return tuple(sorted((k, freeze(v)) for k, v in value.items()))
        if isinstance(value, (tuple, list)):
            return tuple(freeze(v) for v in value)
        if isinstance(value, (set, frozenset)):
            return tuple(sorted(value))
        return value

    esc = tuple((f.name, getattr(build, f.name)) for f in fields(build)
                if f.name.endswith("_points") and f.name != "potency_points")
    return (tuple(item.rawcode for item in build.items), tuple(sorted(build.talents)),
            tuple(sorted(build.glyphs)), esc, spec, targets,
            freeze({k: v for k, v in stats.items() if k != "potency"}))


def simulate(build: Build, targets: int = 5, spec: str = "headhunter") -> Report:
    if spec not in SPECS:
        raise ValueError(spec)
    if targets < 1:
        raise ValueError(targets)
    stats = stats_of(build)
    luck_mult = 1.0 + stats["luck"]
    has = lambda code: _has(build, code)  # noqa: E731
    blades = has(TALENT_POISONED_BLADES) or stats["venombite"] > 0
    fury_mult = 0.85 if spec == "fury" else 1.0
    agi = stats["agi"]
    mastery = stats["mastery"]

    sources = Ledger({
        "Автоатака": 0.0,
        "Toxic Sack": 0.0,
        "Skull Split": 0.0,
        "Venomous Axes": 0.0,
        "Surge of Toxins": 0.0,
        "Way of the Snake": 0.0,
        "Axe Mastery": 0.0,
        "Всплеск огня": 0.0,
    })
    haste = stats["haste"]
    # Venomous Axes buff B05J per target as a distribution of expiry times: (expiry, probability).
    # An attack or a Toxic Sack applies it for sure (one point, now + 4 s); Might of Dambala
    # re-applies it on a tick only with chance q, so that share moves to tick + 4 s.
    va_e: list[list[float]] = [[] for _ in range(targets)]
    va_m: list[list[float]] = [[] for _ in range(targets)]
    surge_p = [0.0] * targets
    surge_at = [-1.0] * targets
    actions: list[tuple[float, str]] = []
    mana = stats["mana_max"]
    mana_time = 0.0
    sulfuras = Sulfuras() if _wears(build, "I0BR") else None
    cast_time = CAST_POINT + CAST_BACKSWING

    def hero_ratio(now: float) -> float:
        return hero_hp_ratio(now, stats["hp"], 0.0)

    def berserk_speed(now: float) -> float:
        if not has(TALENT_BERSERK) or now < PRESSURE_STEP:
            return 0.0
        phase = (now - PRESSURE_STEP) % (BERSERK_DUR + PRESSURE_STEP)
        if phase >= BERSERK_DUR:
            return 0.0
        stacks = int(phase / PRESSURE_STEP + 1e-9)
        per = 0.02 if spec == "fury" else 0.03
        return 0.12 + per * stacks

    def va_mass(index: int, now: float) -> float:
        """Probability that Venomous Axes is on the target at ``now``."""
        total = 0.0
        for expiry, mass in zip(va_e[index], va_m[index]):
            if now < expiry:
                total += mass
        return total

    def va_apply(index: int, now: float) -> None:
        va_e[index] = [now + VA_DUR]
        va_m[index] = [1.0]

    def taken_for(index: int, now: float) -> float:
        armor = DUMMY_ARMOR - stats["armor_pen"]
        if has(TALENT_WOUND_POISON):
            p = va_mass(index, now)
            if p > 0.0:
                base = armor_taken(armor)
                low = armor_taken(armor - 3.0)
                return (1.0 - p) * base + p * low
        return armor_taken(armor)

    def generic(when: float) -> float:
        bonus = 1.0
        if stats["sulfuron"]:
            bonus += 0.13 + 0.25 * target_hp(when)
        if stats["glass"]:
            bonus *= 1.15
        return bonus

    def physical(when: float) -> float:
        bonus = 1.0 + stats["phys_add"] + stats["hemotoxin_add"]
        if stats["sulfuron"]:
            bonus += 0.13 + 0.25 * target_hp(when)
        if stats["glass"]:
            bonus *= 1.15
        return bonus

    def finish(name: str, raw: float, index: int, when: float, count: float = 1.0,
               pot_coeff: float = 0.0) -> float:
        execute = _execute_factor(stats, when)
        scale = taken_for(index, when) * fury_mult * count
        weight, coeff = raw * scale, pot_coeff * scale
        dealt = (weight + stats["potency"] * coeff) * execute
        sources.add_exec(name, dealt, when, execute, raw_weight=weight, pot_coeff=coeff)
        return dealt

    def surge_proc(index: int, when: float, chance: float) -> None:
        if when - surge_at[index] > SURGE_DUR:
            surge_p[index] = 0.0
        surge_p[index] = 1.0 - (1.0 - surge_p[index]) * (1.0 - _chance(chance))
        surge_at[index] = when

    def poison_spec_proc(index: int, when: float, events: float = 1.0) -> None:
        if spec == "poison" and events > 0:
            chance = 1.0 - (1.0 - _chance(0.03 * luck_mult)) ** events
            surge_proc(index, when, chance)

    def surge_consume(index: int, when: float) -> None:
        if when - surge_at[index] > SURGE_DUR:
            surge_p[index] = 0.0
        if surge_p[index] <= 0:
            return
        raw = 15.0 * LEVEL + 2.5 * agi
        finish("Surge of Toxins", raw * generic(when), index, when, surge_p[index], generic(when))
        surge_p[index] = 0.0

    def attack_hit(name: str, raw: float, when: float, potency_scale: float,
                   index: int = 0, count: float = 1.0) -> float:
        amount = raw
        increase = 1.0
        if spec == "headhunter":
            increase += 0.12  # Blood Fury always on
        if has(TALENT_EXECUTOR) and target_hp(when) <= 0.40:
            increase += 0.35
        amount *= increase
        chance = stats["crit"]
        if has(TALENT_BONESLICER):
            chance += 10.0 + 0.5 * (100.0 * (1.0 - hero_ratio(when)))
        mult = 2.0 + stats["rating"]
        if spec == "headhunter":
            mult += 0.10 + 0.008 * mastery
        crit_factor = _crit_factor(chance, mult)
        expected = amount * crit_factor
        pot_coeff = potency_scale * increase * crit_factor
        if has(TALENT_BLOOD_HUNTER):
            share = max(0.0, min(100.0, chance)) / 100.0
            expected += share * (15.0 + 0.05 * stats["hp"]) * mult
        return finish(name, expected * physical(when), index, when, count, pot_coeff * physical(when))

    def dcs(now: float) -> float:
        value = WHITE_BASE + 0.75 * agi + stats["damage"]
        value += TROPHIES  # +1 DCS per Trophy stack, like the map
        if has(TALENT_BLOOD_CRAZE):
            value += BLOOD_CRAZE_DCS
        return value

    def va_tick(index: int, now: float, weight: float, refresh: bool) -> None:
        """One Venomous_Axes_Tick on a target (global timer or Poisoned Blades), taken with
        probability ``weight`` (the buff is on). ``refresh``: Might of Dambala may re-apply the buff."""
        calls = 1.0
        for code in (TALENT_DEADLY_POISON, TALENT_WOUND_POISON, TALENT_LEECHING_POISON):
            if has(code):
                calls += _chance(0.30 * luck_mult)
        scale = 0.25 if has(TALENT_MIGHT_OF_DAMBALA) else 0.15
        raw = 10.0 * RANK + scale * dcs(now)
        coeff = _crit_factor(stats["crit"] * luck_mult, 1.5 + stats["rating"])
        raw *= coeff
        if has(TALENT_DEADLY_POISON):
            deadly = 1.0 + 0.005 * 100.0 * (1.0 - target_hp(now))
            raw *= deadly
            coeff *= deadly
        ticks = 1.0
        if spec == "poison":
            ticks += _chance((5.0 + 0.5 * mastery) / 100.0)
        typed_mult = physical(now) if has(TALENT_HEMOTOXIN) else generic(now)
        finish("Venomous Axes", raw * typed_mult, index, now, calls * ticks * weight, coeff * typed_mult)
        if spec != "poison":
            surge_proc(index, now, (1.0 - (1.0 - _chance(0.02 * luck_mult)) ** calls) * weight)
        else:
            poison_spec_proc(index, now, calls * ticks * weight)
        if refresh and has(TALENT_MIGHT_OF_DAMBALA):
            # Map: one 20% roll per Venomous_Axes_Damage call (not per poison-spec double tick).
            dambala = _chance(0.20 * luck_mult)
            keep = 1.0 - dambala
            for code in (TALENT_DEADLY_POISON, TALENT_WOUND_POISON, TALENT_LEECHING_POISON):
                if has(code):
                    keep *= 1.0 - _chance(0.30 * luck_mult) * dambala
            q = 1.0 - keep
            alive = now - 1e-9
            new_e: list[float] = []
            new_m: list[float] = []
            for expiry, mass in zip(va_e[index], va_m[index]):
                if alive < expiry:
                    new_e.append(expiry)
                    new_m.append(mass * (1.0 - q))
            new_e.append(now + VA_DUR)
            new_m.append(q * weight)
            if len(new_e) > VA_SLOTS:
                raise RuntimeError("Venomous Axes distribution overflow")
            va_e[index] = new_e
            va_m[index] = new_m

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

    def note_damage_mana(count: float) -> None:
        nonlocal mana
        if stats["damage_mana_pct"]:
            mana = min(stats["mana_max"], mana + stats["damage_mana_pct"] * stats["mana_max"] * count)

    def cast(now: float) -> float:
        if sulfuras is not None:
            sulfuras.cast()
        return now + cast_time + stats["cast_stun_lock"]

    def attack_interval(now: float) -> float:
        swing = SWING * (1.20 if stats["galactic"] else 1.0)
        speed = stats["attack_speed"] + berserk_speed(now)
        if stats["blood_fanatic"]:
            speed += 0.01 * 100.0 * (1.0 - hero_ratio(now))
        speed = min(4.0, max(-0.8, speed))
        return swing / (1.0 + speed)

    def axe_hit(now: float, count: float) -> None:
        # Emit the scaled raw/coeff directly; probing/restoring the Ledger would
        # create potency-baked FLAT deltas (including a negative probe restore).
        attack_hit("Axe Mastery", 20.0 + 1.25 * dcs(now), now,
                   stats["attack_potency"], count=count)

    next_attack = 0.0
    next_sack = 0.0
    next_skull = 0.0
    next_tick = 1.0
    next_pressure = PRESSURE_STEP
    pending_sack: list[float] = []
    busy = 0.0
    guard = 0
    while True:
        guard += 1
        if guard > 400000:
            break
        land = pending_sack[0] if pending_sack else FIGHT
        moment = min(next_attack, next_sack, next_skull, next_tick, next_pressure, land)
        if moment >= FIGHT:
            break
        # Timers that do not depend on the hero's hands.
        if moment == land:
            pending_sack.pop(0)
            raw = 80.0 * RANK - 20.0 + 2.2 * agi
            for index in range(targets):
                coeff = 1.0
                if has(TALENT_POISON_BOMB):
                    p = va_mass(index, moment)
                    coeff = 1.6 * p + 1.3 * (1.0 - p)
                finish("Toxic Sack", raw * coeff * physical(moment), index, moment,
                       pot_coeff=coeff * physical(moment))
                poison_spec_proc(index, moment)
                va_apply(index, moment)
            note_damage_mana(targets)
            continue
        if moment == next_tick:
            for index in range(targets):
                weight = va_mass(index, moment - 1e-9)
                if weight > 0.0:
                    va_tick(index, moment, weight, True)
            next_tick += 1.0
            continue
        if moment == next_pressure:
            if has(TALENT_AXE_MASTERY):
                axe_hit(moment, _chance(0.05 * luck_mult))
            next_pressure += PRESSURE_STEP
            continue
        if moment < busy:
            if moment == next_attack:
                next_attack = busy
            elif moment == next_sack:
                next_sack = busy
            elif moment == next_skull:
                next_skull = busy
            continue
        if moment == next_sack:
            if not pay(SACK_MANA, moment):
                next_sack = moment + 0.25
                continue
            actions.append((moment, "Toxic Sack"))
            pending_sack.append(moment + CAST_POINT + SACK_DELAY)
            pending_sack.sort()
            busy = cast(moment)
            next_sack = moment + _cooldown(SACK_CD, haste, stats)
            next_attack = max(next_attack, busy)
            continue
        if moment == next_skull:
            if not pay(SKULL_MANA, moment):
                next_skull = moment + 0.25
                continue
            actions.append((moment, "Skull Split"))
            hit = moment + CAST_POINT
            raw = 150.0 * RANK + 2.0 * dcs(hit) + 0.05 * MEDIAN_MONSTER_HP
            coeff = 1.35 if has(TALENT_EXECUTOR) and target_hp(hit) <= 0.40 else 1.0
            finish("Skull Split", raw * coeff * physical(hit), 0, hit, pot_coeff=coeff * physical(hit))
            poison_spec_proc(0, hit)
            note_damage_mana(1)
            busy = cast(moment)
            next_skull = moment + _cooldown(SKULL_CD, haste, stats)
            next_attack = max(next_attack, busy)
            continue
        if moment == next_attack:
            recover(moment)
            power = dcs(moment)
            had_va = va_mass(0, moment)
            surge_consume(0, moment)
            attack_hit("Автоатака", power, moment, stats["attack_potency"], count=stats["auto_pct"])
            poison_spec_proc(0, moment)
            mana = min(stats["mana_max"], mana + attack_mana_gain(stats))
            note_damage_mana(1)
            va_apply(0, moment)
            if blades and had_va > 0.0:
                # The attack has just re-applied the buff, so a Dambala roll here changes nothing.
                va_tick(0, moment, had_va, False)
            if has(TALENT_WAY_OF_THE_SNAKE):
                chance = _chance(0.20 * luck_mult)
                raw = 2.0 * (10.0 * RANK + 0.5 * agi)
                for index in range(targets):
                    finish("Way of the Snake", raw * generic(moment), index, moment, chance, generic(moment))
                    if surge_p[index] > 0 and moment - surge_at[index] <= SURGE_DUR:
                        consumed = surge_p[index] * chance
                        surge_value = (15.0 * LEVEL + 2.5 * agi) * generic(moment)
                        finish("Surge of Toxins", surge_value, index, moment, consumed, generic(moment))
                        surge_p[index] -= consumed
                note_damage_mana(targets * chance)
            if has(TALENT_AXE_MASTERY):
                # Blood Fury self-damage on every attack doubles the Axe Mastery roll.
                rolls = 1.0 + (_chance(0.30 * luck_mult) if has(TALENT_BLOOD_CRAZE) else 0.0)
                axe_hit(moment, rolls * _chance(0.10 * luck_mult))
            if stats["fire_orb"]:
                splash = (20.0 + 0.35 * agi) * targets * taken_for(0, moment) * _execute_factor(stats, moment)
                sources.add_exec("Всплеск огня", splash * fury_mult, moment, _execute_factor(stats, moment))
                note_damage_mana(targets)
            if sulfuras is not None:
                execute = _execute_factor(stats, moment)
                taken = taken_for(0, moment)
                if sulfuras.attack():
                    splash = agi * (1.0 + stats["magic_add"]) * generic(moment) * taken * execute * targets
                    sources.add_exec("Sulfuras", splash * fury_mult, moment, execute)
                    note_damage_mana(targets)
                echo = power * taken * execute * sulfuras_echo_chance(stats["luck"])
                sources.add_exec("Sulfuras (удар)", echo * fury_mult, moment, execute)
            next_attack = moment + attack_interval(moment)
            continue
        break

    total = sum(sources.values())
    recover(FIGHT)
    mana_left = 0.0 if stats["mana_max"] <= 0 else 100.0 * mana / stats["mana_max"]
    return attach(Report(build, total / FIGHT, total, sources, actions, stats, targets, mana_left=mana_left))


def best_points(build: Build, targets: int, spec: str) -> tuple[float, dict[str, int]]:
    from sunken_sim.esc import apply_points, greedy_points, points_payload

    def score(pts: dict) -> float:
        trial = apply_points(build, pts)
        report = simulate(trial, targets, spec)
        return report.dps

    dps, pts = greedy_points(score)
    return dps, points_payload(pts)


