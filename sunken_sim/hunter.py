"""Hunter fight for Sunken City v2.5.2a, level 6.

Unit H001. Agility 28 + 2.8, strength 10 + 1, intellect 12 + 1.2 (42 / 15 / 18 at
level 6). White hit 29 + 1 die (1d1) = 30, plus 0.75 x AGI (DCS formula).
Attack cooldown ua1c 1.60, range 500. Primary AGI. Ability rank is 1.
Spec level on A098 (udg_Glyphs_Unit[1]): 1 Marksmanship, 2 Beast Mastery, 3 Survival.

Spells: Serpent Sting A0E3, Multi-Shot A01V (+ passive split shot), Bestial Wrath
A03X, Steel Trap A06B, Call Pet A0ME / A00N / A0MF (Huffer / Spike / Grylls),
Aspect of the Eagle A0HC (passive). Healing and pet survivability are not scored.

Pets are separate attackers: base damage = Pet_DamageBase + R2I(scaling x hunter DCS)
+ 1d1 (BlzSetUnitBaseDamage in PreDamage_Heroes), own attack cooldown, the summon
crit block of PreDamage_Increase, Pet Damage % (PetDamage_Total), Aspect of the Eagle.
"""

from __future__ import annotations

import re

from sunken_sim.pressure import max_hp
from sunken_sim.shadow import (
    CAST_BACKSWING,
    CAST_POINT,
    DUMMY_ARMOR,
    FIGHT,
    LEVEL,
    MAGICAL_ADDS,
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

BASE_STR = int(10 + (LEVEL - 1) * 1)
BASE_AGI = int(28 + (LEVEL - 1) * 2.8)
BASE_INT = int(12 + (LEVEL - 1) * 1.2)
WHITE_BASE = 30.0  # ua1b 29 + 1d1
SWING = 1.60  # H001 ua1c
BASE_MANA = 120.0
BASE_HP = 230.0

SPECS = ("marksmanship", "beast_mastery", "survival")
HERO_CLASS = "Hunter"
RANK = 1

TALENT_TALON_STRIKES = "I03P"
TALENT_UNLEASH = "I0K8"
TALENT_TRAPLAYER = "I092"
TALENT_HYDRA_SHOTS = "I02X"
TALENT_LOCK_AND_LOAD = "I0KD"
TALENT_HOWL = "I0T3"
TALENT_TRUESHOT = "I0K9"
TALENT_WILD_POWER = "I0KB"
TALENT_VOLLEY = "I0KC"
TALENT_WINDRUNNER = "I0K6"
TALENT_KILLER_INSTINCT = "I03M"
TALENT_STEEL_ARROWHEADS = "I03H"
TALENT_FLANKING = "I02D"
TALENT_DIRE_BEASTS = "I0KA"
TALENT_MONGOOSE = "I0O3"
TALENT_SCENT_OF_BLOOD = "I0K7"
TALENT_UNMATCHED = "I0T4"
TALENT_POISONED_ARROWS = "I0T5"
TALENT_NEXT_PAGE = "I0MD"
TALENT_PREV_PAGE = "I0MC"

TALENTS = {
    TALENT_TALON_STRIKES: "Talon Strikes",
    TALENT_UNLEASH: "Unleash the Beasts",
    TALENT_TRAPLAYER: "Traplayer",
    TALENT_HYDRA_SHOTS: "Hydra Shots",
    TALENT_LOCK_AND_LOAD: "Lock and Load",
    TALENT_HOWL: "Howl of the Packleader",
    TALENT_TRUESHOT: "Trueshot Aura",
    TALENT_WILD_POWER: "Wild Power",
    TALENT_VOLLEY: "Volley",
    TALENT_WINDRUNNER: "Windrunner's Quiver",
    TALENT_KILLER_INSTINCT: "Killer Instinct",
    TALENT_STEEL_ARROWHEADS: "Steel Arrowheads",
    TALENT_FLANKING: "Flanking Strike",
    TALENT_DIRE_BEASTS: "Dire Beasts",
    TALENT_MONGOOSE: "Mongoose Bite",
    TALENT_SCENT_OF_BLOOD: "Scent of Blood",
    TALENT_UNMATCHED: "Unmatched Percision",
    TALENT_POISONED_ARROWS: "Poisoned Arrows",
}

# Pages are UI. No Hunter talent is purely defensive (all 18 touch damage).
IGNORED_TALENTS = frozenset({TALENT_NEXT_PAGE, TALENT_PREV_PAGE})

STING_CD, STING_MANA = 8.0, 15.0
MULTI_CD, MULTI_MANA = 7.0, 10.0
WRATH_CD, WRATH_MANA, WRATH_DUR = 15.0, 20.0, 8.0
TRAP_CD, TRAP_MANA, TRAP_DELAY = 7.0, 20.0, 0.5
CALL_CD, CALL_MANA = 30.0, 30.0
STING_DUR = 10.0  # A0JH adur L1
WOUND_DUR, WOUND_ARMOR = 5.0, 3.0  # A06M L1, Acid Bomb armor penalty (tooltip: 3)
STING_PEN = 4.0  # ArmorDamage_Increase, A0E3 level <= 2
ASPECT = 0.10  # A0HC: min(0.13, distance/50/100) at hunter range 500
PROWESS_DUR = 3.0
LOCK_DUR = 4.0
QUILL_DUR = 5.0
MULTI_SECONDARY_DELAY = 0.5

PETS = {
    # kind: (Pet_DamageBase, Pet_DamageScaling, attack cooldown ua1c, name)
    "spike": (9, 0.50, 1.50, "Spike"),
    "huffer": (4, 0.30, 1.45, "Huffer"),
    "grylls": (17, 0.90, 1.70, "Grylls"),
}
SPEC_PET = {"marksmanship": "huffer", "beast_mastery": "spike", "survival": "grylls"}

GLYPH_UNSEALED = "I0AV"
GLYPH_GLASS = "I0JA"
GLYPH_FORTITUDE = "I07B"
GLYPH_SUPREMACY = "I0EK"
GLYPH_ANIMOSITY = "I0HC"
GLYPH_MINDHASTE = "I0OF"
GLYPH_FORTUNE = "I0EJ"
GLYPH_BATTLE_FRENZY = "I0GZ"
GLYPH_BEASTFURY = "I0OH"
FIRE_ORB = "I07O"
FROST_ORB = "I0NS"
GALACTIC_FURY = "I0JO"
SULFURON_GLOVES = "I0QT"
SPELLBINDER = "tlum"
ITEM_STEEL_QUIVER = "I0T6"
ITEM_TRAP_GLOVES = "I0T7"
ITEM_RECURVE_BOW = "I0T8"
ITEM_BEAST_HELM = "I0T9"
ITEM_MARK_OF_THE_WILD = "I06B"
ITEM_PREDAPLANT_THORN = "I05W"


def _has(build: Build, code: str) -> bool:
    return code in build.talents or code in build.glyphs


class _Dither:
    """Deterministic chance: fires once the accumulated probability reaches 1."""

    def __init__(self) -> None:
        self.acc = 0.0

    def roll(self, chance: float) -> bool:
        self.acc += max(0.0, min(1.0, chance))
        if self.acc >= 1.0 - 1e-9:
            self.acc -= 1.0
            return True
        return False


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
    pet_damage = 0.0
    luck = 0.01 * build.luck_points
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
            for raw in re.findall(r"\+(\d+)% Pet Damage\b", item.tip):
                pet_damage += int(raw) / 100.0
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
    hp = max_hp(BASE_HP, strength) + health_flat
    attack_speed += min(1.0, 0.004 * agility)
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
    # Summon crit block (PreDamage_Increase): base 0 %, x2.0.
    summon_crit = 0.0
    summon_rating = 0.0
    if _has(build, GLYPH_BEASTFURY) or GLYPH_BEASTFURY in codes:
        summon_crit += 25.0
    if ITEM_MARK_OF_THE_WILD in codes:
        summon_crit += 7.0  # pets have no mana
    if ITEM_PREDAPLANT_THORN in codes:
        summon_rating += 0.20
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
        "executes": executes,
        "auto_pct": auto_pct,
        "attack_potency": attack_potency,
        "cd_temp": cd_temp,
        "flat_cdr": flat_cdr,
        "pet_damage": pet_damage,
        "summon_crit": summon_crit,
        "summon_rating": summon_rating,
        "glass": 1.0 if _has(build, GLYPH_GLASS) or GLYPH_GLASS in codes else 0.0,
        "spellbinder": 1.0 if SPELLBINDER in codes else 0.0,
        "sulfuron": 1.0 if SULFURON_GLOVES in codes else 0.0,
        "galactic": 1.0 if GALACTIC_FURY in codes else 0.0,
        "fire_orb": 1.0 if FIRE_ORB in codes else 0.0,
        "steel_quiver": 1.0 if ITEM_STEEL_QUIVER in codes else 0.0,
        "trap_gloves": 1.0 if ITEM_TRAP_GLOVES in codes else 0.0,
        "recurve_bow": 1.0 if ITEM_RECURVE_BOW in codes else 0.0,
        "beast_helm": 1.0 if ITEM_BEAST_HELM in codes else 0.0,
        "luck": luck,
        "mana_max": mana_max,
        "mana_regen": regen,
        "cast_stun_lock": cast_stun_lock,
        "hp": hp,
        **passive,
    }


def _cooldown(base: float, haste: float, stats: dict, flat: float = 0.0) -> float:
    return max(0.5, (base * stats["cd_temp"] - stats["flat_cdr"] - flat) / (1.0 + haste))


def _chance(value: float) -> float:
    return max(0.0, min(1.0, value))


def simulate(build: Build, targets: int = 5, spec: str = "marksmanship") -> Report:
    if spec not in SPECS:
        raise ValueError(spec)
    if targets < 1:
        raise ValueError(targets)
    stats = stats_of(build)
    luck_mult = 1.0 + stats["luck"]
    has = lambda code: _has(build, code)  # noqa: E731
    agi = stats["agi"]
    mastery = stats["mastery"]
    haste = stats["haste"]
    current_pet = SPEC_PET[spec]
    pet_name = PETS[current_pet][3]

    sources: dict[str, float] = {
        "Автоатака": 0.0,
        "Serpent Sting": 0.0,
        "Serpent Sting (тики)": 0.0,
        "Multi-Shot": 0.0,
        "Split Shot": 0.0,
        "Steel Trap": 0.0,
        pet_name: 0.0,
        "Всплеск огня": 0.0,
    }
    actions: list[tuple[float, str]] = []
    mana = stats["mana_max"]
    mana_time = 0.0
    sulfuras = Sulfuras() if _wears(build, "I0BR") else None
    cast_time = CAST_POINT + CAST_BACKSWING

    stung = [-1.0] * targets
    wound = [-1.0] * targets
    wrath_until = -1.0
    lock_until = -1.0
    hunter_prowess_until = -1.0
    pet_prowess_until = -1.0
    quill_until = -1.0
    quill_count = 0
    quiver = 0.0  # probability that Windrunner's Quiver is armed
    split_flag = False
    howl_stacks = 0
    crit_dither = {"lock": _Dither(), "prowess": _Dither(), "pet_prowess": _Dither(), "split": _Dither()}
    maul_dither = _Dither()
    trap_dither = _Dither()
    shred_dither = _Dither()

    def recover(now: float) -> None:
        nonlocal mana, mana_time
        if now > mana_time and mana < stats["mana_max"]:
            mana = min(stats["mana_max"], mana + stats["mana_regen"] * (now - mana_time))
        mana_time = now

    def gain_mana(amount: float) -> None:
        nonlocal mana
        mana = min(stats["mana_max"], mana + amount)

    def pay(cost: float, now: float) -> bool:
        nonlocal mana
        recover(now)
        if mana < cost:
            return False
        mana -= cost
        gain_mana(cast_mana_back(cost, stats))
        return True

    def note_damage_mana(count: float) -> None:
        if stats["damage_mana_pct"]:
            gain_mana(stats["damage_mana_pct"] * stats["mana_max"] * count)

    def wrath_on(now: float) -> bool:
        return now < wrath_until

    def wrath_pct() -> float:
        """Inner Fire Inf1 set by Bestial Wrath (A03X level 1)."""
        value = 0.30 + 0.03 * RANK
        if has(TALENT_WILD_POWER):
            value += 0.25
        return value

    def dcs(now: float) -> float:
        value = WHITE_BASE + 0.75 * agi + stats["damage"]
        if wrath_on(now):
            value *= 1.0 + (0.35 if has(TALENT_WILD_POWER) else 0.20) + 0.05 * RANK
        return value

    def potency(now: float) -> float:
        value = stats["potency"]
        if has(TALENT_HYDRA_SHOTS):
            value += 3.0 + 0.04 * dcs(now)
        return value

    def taken_for(index: int, now: float, hunter: bool = True) -> float:
        armor = float(DUMMY_ARMOR)
        if hunter:
            armor -= stats["armor_pen"]
        if stung[index] > now:
            armor -= STING_PEN
        if wound[index] > now:
            armor -= WOUND_ARMOR
        return armor_taken(armor)

    def physical(now: float) -> float:
        bonus = 1.0 + stats["phys_add"]
        if stats["sulfuron"]:
            bonus += 0.13 + 0.25 * target_hp(now)
        if stats["glass"]:
            bonus *= 1.15
        return bonus

    def hero_crit(now: float) -> float:
        chance = stats["crit"]
        if has(TALENT_TRUESHOT):
            chance += 10.0
        if now < quill_until:
            chance += 20.0
        return chance

    def hero_rating(now: float) -> float:
        rating = 2.0 + stats["rating"]
        if has(TALENT_UNMATCHED):
            rating += 0.25 + 0.15 * hero_crit(now) / 100.0
        return rating

    def hit(
        name: str,
        raw: float,
        now: float,
        *,
        index: int = 0,
        attack: float = 0.0,
        typed: bool = True,
        potency_scale: float = 1.0,
        count: float = 1.0,
    ) -> tuple[float, float]:
        """Hunter damage through PreDamage_Increase. attack = probability the event is an attack.

        Returns (dealt, crit share)."""
        nonlocal quiver
        amount = raw + potency(now) * potency_scale
        if typed:
            amount *= physical(now)
        amount *= 1.0 + ASPECT
        taken = taken_for(index, now) * _execute_factor(stats, now)
        plain = amount * taken
        share = 0.0
        dealt = plain
        if attack > 0:
            inc = 1.0
            if has(TALENT_MONGOOSE):
                inc += 0.10
            if has(TALENT_FLANKING) and index == 0:
                inc += 0.15
            chance = hero_crit(now)
            mult = hero_rating(now)
            normal = amount * inc * taken * _crit_factor(chance, mult)
            armed = quiver * attack if has(TALENT_WINDRUNNER) else 0.0
            boosted = amount * inc * (1.0 + chance / 100.0) * taken * mult
            attack_dealt = (1.0 - armed / attack) * normal + (armed / attack) * boosted
            share = attack * ((1.0 - armed / attack) * _chance(chance / 100.0) + armed / attack)
            dealt = (1.0 - attack) * plain + attack * attack_dealt
            if armed:
                quiver -= armed
            if has(TALENT_POISONED_ARROWS) and attack >= 0.5:
                stung[index] = max(stung[index], now + STING_DUR)
        sources[name] = sources.get(name, 0.0) + dealt * count
        note_damage_mana(count)
        return dealt, share

    def pet_hit(name: str, raw: float, now: float, kind: str, index: int = 0, attack: bool = True) -> float:
        """Pet damage: Pet Damage %, Scent of Blood, Aspect, summon crit on attacks."""
        amount = raw * (1.0 + stats["pet_damage"]) * (1.0 + ASPECT)
        increase = 1.0
        if has(TALENT_SCENT_OF_BLOOD) and target_hp(now) < 0.40:
            increase += 0.28
        amount *= increase
        taken = taken_for(index, now, hunter=False) * _execute_factor(stats, now)
        share = 0.0
        if attack:
            inc = 1.0
            if has(TALENT_FLANKING) and kind == current_pet and index == 0:
                inc += 0.15
            chance = stats["summon_crit"] + (20.0 if kind == "spike" else 0.0)
            rating = 2.0 + stats["summon_rating"] + (0.30 if kind == "spike" else 0.0)
            if has(TALENT_UNMATCHED):
                rating += 0.25 + 0.15 * hero_crit(now) / 100.0
            share = _chance(chance / 100.0)
            dealt = amount * inc * taken * _crit_factor(chance, rating)
        else:
            dealt = amount * taken
        sources[name] = sources.get(name, 0.0) + dealt
        return share

    def howl(now: float) -> None:
        nonlocal howl_stacks
        if has(TALENT_HOWL) and howl_stacks < 3:
            howl_stacks += 1

    def howl_value() -> float:
        return 20.0 + 0.25 * agi + 0.50 * mastery

    def trap(index: int, now: float, count: float = 1.0) -> None:
        raw = 40.0 + 1.20 * dcs(now) + 0.50 * agi
        hit("Steel Trap", raw, now, index=index, count=count)
        if count >= 0.5:
            wound[index] = max(wound[index], now + WOUND_DUR)

    def multishot(now: float, secondary: bool) -> None:
        nonlocal quiver
        hits = min(targets, 5 if has(TALENT_VOLLEY) else 3)
        raw = 10.0 + 60.0 * RANK + 0.70 * dcs(now) + 0.30 * agi
        if has(TALENT_VOLLEY):
            raw *= 1.10  # condition A0D7 level >= 1 is always true
        if has(TALENT_MONGOOSE):
            raw *= 1.10
        if secondary:
            raw *= 0.50
        if stats["recurve_bow"]:
            raw *= 1.25
        pierce = 0.0
        if has(TALENT_STEEL_ARROWHEADS) or stats["steel_quiver"]:
            pierce = _chance(0.30 * luck_mult)
        for index in range(hits):
            hit("Multi-Shot", raw, now, index=index, attack=pierce, typed=pierce < 1.0)
            if has(TALENT_TRAPLAYER):
                chance = 0.25 * luck_mult * (0.5 if secondary else 1.0)
                if trap_dither.roll(chance):
                    trap(index, now)

    def apply_sting(now: float) -> None:
        stung[0] = max(stung[0], now + STING_DUR)

    def cut_cooldowns(now: float, fraction: float = 0.0, seconds: float = 0.0) -> None:
        for key in ("sting", "multi", "wrath", "trap"):
            left = nxt[key] - now
            if left > 0:
                left = max(0.0, left * (1.0 - fraction) - seconds)
                nxt[key] = now + left

    def cast(now: float) -> float:
        nonlocal quiver
        if sulfuras is not None:
            sulfuras.cast()
        if has(TALENT_WINDRUNNER):
            quiver = 1.0
        return now + cast_time + stats["cast_stun_lock"]

    def hunter_interval(now: float) -> float:
        swing = SWING * (1.20 if stats["galactic"] else 1.0)
        if spec == "marksmanship":
            swing *= 1.0 - ASPECT
        speed = stats["attack_speed"]
        if now < lock_until:
            speed += 0.40
        if now < hunter_prowess_until:
            speed += 0.20
        if stats["beast_helm"] and wrath_on(now):
            speed += 0.25
        speed = min(4.0, max(-0.8, speed))
        return swing / (1.0 + speed)

    def pet_interval(pet: dict, now: float) -> float:
        swing = PETS[pet["kind"]][2]
        if has(TALENT_TALON_STRIKES):
            swing *= 0.90
        speed = 0.0
        if spec == "beast_mastery":
            speed += 0.10 + 0.008 * mastery
        if pet["kind"] == current_pet and now < pet_prowess_until:
            speed += 0.40
        if pet["kind"] == current_pet and stats["beast_helm"] and wrath_on(now):
            speed += 0.25
        if pet["kind"] == "huffer" and has(TALENT_DIRE_BEASTS):
            # Frenzy Afzy: +40 % for 12 s, cooldown 20 s, used on its own.
            if (now - pet["start"]) % 20.0 < 12.0:
                speed += 0.40
        speed = min(4.0, max(-0.8, speed))
        return swing / (1.0 + speed)

    def pet_attack(pet: dict, now: float) -> None:
        nonlocal howl_stacks, quill_count, quill_until, pet_prowess_until, hunter_prowess_until
        kind = pet["kind"]
        base, scale, _swing, name = PETS[kind]
        raw = base + int(scale * dcs(now)) + 1.0
        if kind == current_pet and wrath_on(now):
            bw = wrath_pct() * (1.0 if spec == "beast_mastery" else 0.5)
            raw *= 1.0 + bw
        if kind == "grylls" and has(TALENT_DIRE_BEASTS):
            raw *= 1.20  # Roar: +20 % damage for 10 s, cooldown 10 s
        main_raw = raw
        if kind == current_pet and howl_stacks > 0:
            value = howl_value() * howl_stacks
            howl_stacks = 0
            if spec == "beast_mastery":
                main_raw += value
            else:
                hit("Howl of the Packleader", value, now)
        share = pet_hit(name, main_raw, now, kind)
        events = 1
        if kind == "huffer":
            for index in range(1, min(targets, 3)):
                pet_hit(name, raw, now, kind, index=index)
                events += 1
            quill_count += events
            while quill_count >= 15:
                quill_count -= 15
                quill_until = now + QUILL_DUR
        if kind == "grylls" and maul_dither.roll(0.20 * luck_mult):
            hit("Maul", 15.0 + 1.50 * dcs(now), now)
        if kind == "spike" and has(TALENT_DIRE_BEASTS):
            chance = 0.20 * (1.0 + share) * luck_mult
            if shred_dither.roll(chance):
                pet_hit("Shred", 50.0 + 0.50 * dcs(now), now, kind, attack=False)
        if crit_dither["pet_prowess"].roll(share):
            hunter_prowess_until = now + PROWESS_DUR
        if has(TALENT_TALON_STRIKES):
            fraction = 0.06 if kind == current_pet else 0.02
            for _ in range(events):
                cut_cooldowns(now, fraction=fraction)

    nxt = {"call": 0.0, "wrath": 0.0, "sting": 0.0, "multi": 0.0, "trap": 0.0}
    order = ("call", "wrath", "sting", "multi", "trap")
    names = {
        "call": "Call Pet",
        "wrath": "Bestial Wrath",
        "sting": "Serpent Sting",
        "multi": "Multi-Shot",
        "trap": "Steel Trap",
    }
    costs = {"call": CALL_MANA, "wrath": WRATH_MANA, "sting": STING_MANA, "multi": MULTI_MANA, "trap": TRAP_MANA}
    pets: list[dict] = []
    pending: list[tuple[float, str, int]] = []  # delayed events: (time, kind, index)
    next_attack = 0.0
    next_tick = 1.0
    busy = 0.0
    guard = 0
    while True:
        guard += 1
        if guard > 400000:
            break
        attack_at = max(next_attack, busy)
        cast_at = FIGHT * 10
        choice = None
        for key in order:
            ready = max(nxt[key], busy)
            if ready < cast_at - 1e-9:
                cast_at, choice = ready, key
        pet_at = min((p["next"] for p in pets if p["next"] < p["end"]), default=FIGHT * 10)
        pending_at = min((p[0] for p in pending), default=FIGHT * 10)
        moment = min(attack_at, cast_at, pet_at, pending_at, next_tick)
        if moment >= FIGHT:
            break
        if moment == pending_at:
            event = min(pending)
            pending.remove(event)
            _t, kind, index = event
            if kind == "trap":
                trap(index, moment)
            elif kind == "multi2":
                multishot(moment, True)
            continue
        if moment == next_tick:
            raw = 5.0 * RANK + 0.10 * dcs(moment)
            stung_now = [i for i in range(targets) if stung[i] > moment]
            for index in stung_now:
                if spec == "beast_mastery":
                    pet_hit("Serpent Sting (тики)", raw, moment, current_pet, index=index, attack=False)
                else:
                    hit("Serpent Sting (тики)", raw, moment, index=index)
                if spec == "survival":
                    cut_cooldowns(moment, seconds=_chance((5.0 + 0.20 * mastery) / 100.0))
            interval = 1.0
            if has(TALENT_POISONED_ARROWS):
                interval /= 1.0 + 0.05 * stats["potency"]
            next_tick = moment + interval
            continue
        if moment == pet_at:
            for pet in pets:
                if pet["next"] == moment and pet["next"] < pet["end"]:
                    pet_attack(pet, moment)
                    pet["next"] = moment + pet_interval(pet, moment)
            pets = [p for p in pets if p["next"] < p["end"]]
            continue
        if cast_at <= attack_at and choice is not None and moment == cast_at:
            key = choice
            if not pay(costs[key], moment):
                nxt[key] = moment + 0.25
                continue
            hit_at = moment + CAST_POINT
            actions.append((moment, names[key]))
            busy = cast(moment)
            if key == "call":
                pets = [p for p in pets if p["kind"] != current_pet]
                pets.append({"kind": current_pet, "next": hit_at, "end": FIGHT * 10, "start": hit_at})
                if has(TALENT_UNLEASH):
                    for kind in PETS:
                        if kind != current_pet:
                            end = hit_at + 6.0 + 0.10 * stats["int"]
                            pets.append({"kind": kind, "next": hit_at, "end": end, "start": hit_at})
                nxt[key] = moment + _cooldown(CALL_CD, haste, stats)
            elif key == "wrath":
                wrath_until = hit_at + WRATH_DUR
                howl(hit_at)
                flat = 3.0 if has(TALENT_WILD_POWER) else 0.0
                nxt[key] = moment + _cooldown(WRATH_CD, haste, stats, flat)
            elif key == "sting":
                raw = 85.0 * RANK + 0.85 * dcs(hit_at) + 0.40 * agi
                hit("Serpent Sting", raw, hit_at)
                apply_sting(hit_at)
                if stats["trap_gloves"]:
                    pending.append((hit_at + TRAP_DELAY, "trap", 0))
                howl(hit_at)
                flat = 1.5 if (has(TALENT_KILLER_INSTINCT) and wrath_on(moment)) else 0.0
                nxt[key] = moment + _cooldown(STING_CD, haste, stats, flat)
            elif key == "multi":
                multishot(hit_at, False)
                if spec == "survival":
                    pending.append((hit_at + MULTI_SECONDARY_DELAY, "multi2", 0))
                howl(hit_at)
                flat = 1.5 if (has(TALENT_KILLER_INSTINCT) and wrath_on(moment)) else 0.0
                nxt[key] = moment + _cooldown(MULTI_CD, haste, stats, flat)
            elif key == "trap":
                pending.append((hit_at + TRAP_DELAY, "trap", 0))
                howl(hit_at)
                nxt[key] = moment + _cooldown(TRAP_CD, haste, stats)
            next_attack = max(next_attack, busy)
            continue
        # Hunter auto-attack.
        moment = attack_at
        recover(moment)
        power = dcs(moment)
        raw = power
        if wrath_on(moment):
            # Inner Fire raises base (white) damage; DCS x1.25 already stands for it in formulas,
            # so the white part gets Inf1 on top of the un-buffed white value.
            white = WHITE_BASE + 0.75 * agi
            raw = white * (1.0 + wrath_pct()) + stats["damage"]
        before = sources["Автоатака"]
        _dealt, share = hit("Автоатака", raw, moment, attack=1.0, potency_scale=stats["attack_potency"])
        if stats["auto_pct"] != 1.0:
            sources["Автоатака"] = before + (sources["Автоатака"] - before) * stats["auto_pct"]
        # OnDamage_Heroes, real hunter attacks.
        if spec == "marksmanship":
            hit("Marksmanship", 40.0 + 3.0 * mastery, moment, typed=False, potency_scale=0.0, count=share)
        if has(TALENT_LOCK_AND_LOAD) and crit_dither["lock"].roll(share * 0.35 * luck_mult):
            lock_until = moment + LOCK_DUR
        if crit_dither["prowess"].roll(share):
            pet_prowess_until = moment + PROWESS_DUR
        if split_flag:
            split_flag = False
            hit("Split Shot", (0.45 + 0.05 * RANK) * power, moment, attack=1.0)
        if crit_dither["split"].roll(0.30 * (1.0 + 0.5 * share) * luck_mult):
            split_flag = True
        gain_mana(attack_mana_gain(stats))
        if stats["fire_orb"]:
            splash = (20.0 + 0.35 * agi) * targets * taken_for(min(1, targets - 1), moment) * _execute_factor(stats, moment)
            sources["Всплеск огня"] += splash
            note_damage_mana(targets)
        if sulfuras is not None:
            execute = _execute_factor(stats, moment)
            taken = taken_for(0, moment)
            if sulfuras.attack():
                splash = agi * (1.0 + stats["magic_add"]) * (1.15 if stats["glass"] else 1.0) * taken * execute * targets
                sources["Sulfuras"] = sources.get("Sulfuras", 0.0) + splash
                note_damage_mana(targets)
            echo = power * taken * execute * sulfuras_echo_chance(stats["luck"])
            sources["Sulfuras (удар)"] = sources.get("Sulfuras (удар)", 0.0) + echo
        next_attack = moment + hunter_interval(moment)

    total = sum(sources.values())
    recover(FIGHT)
    mana_left = 0.0 if stats["mana_max"] <= 0 else 100.0 * mana / stats["mana_max"]
    return Report(build, total / FIGHT, total, sources, actions, stats, targets, mana_left=mana_left)


def best_points(build: Build, targets: int, spec: str) -> tuple[float, tuple[int, int, int, int]]:
    return simulate(build, targets, spec).dps, (0, 0, 0, 0)
