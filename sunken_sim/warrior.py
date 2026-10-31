"""Warrior fight for Sunken City, level 6.

Unit O00F. Strength 30 + 3.0, agility 12 + 1.2, intellect 8 + 0.8.
White hit is 24 + 1 die, attack cooldown 1.85, attack type normal, primary STR.
Ability rank is 1. Spec level on A0KO: 1 Protection, 2 Arms, 3 Fury.

Bloodthirst A0CS, Whirlwind A0LL, Battle Shout A0E9, Demoralizing Shout A0LU,
Ignore Pain A0KN (survivability, not scored). Healing is not scored.
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

BASE_STR = int(30 + (LEVEL - 1) * 3.0)
BASE_AGI = int(12 + (LEVEL - 1) * 1.2)
BASE_INT = int(8 + (LEVEL - 1) * 0.8)
WHITE_BASE = 25.0
SWING = 1.85
BASE_MANA = 120.0
BASE_HP = 300.0
BASE_ARMOR = 4.0

SPECS = ("protection", "arms", "fury")
HERO_CLASS = "Warrior"
RANK = 1

TALENT_SHOCKWAVE = "I0I2"
TALENT_THIRST = "I0HI"
TALENT_RELENTLESS = "I01I"
TALENT_PAIN_TRAIN = "I02U"
TALENT_TITANS_GRIP = "I07J"
TALENT_SUNDER = "I0IU"
TALENT_BERSERKER_RAGE = "I08M"
TALENT_BLADESTORM = "I07G"
TALENT_SLAUGHTERHOUSE = "I0O1"
TALENT_NEXT_PAGE = "I0MD"
TALENT_DOUBLE_TIME = "I0I7"
TALENT_BRUTALITY = "I07I"
TALENT_WARCRY = "I0FO"
TALENT_HELLSCREAM = "I0FC"
TALENT_TENACITY = "I0FJ"
TALENT_WEAPONS_MASTER = "I0GR"
TALENT_DEMOLISH = "I08I"
TALENT_BATTLE_SCARS = "I08K"
TALENT_LIVING_SHIELD = "I0O2"
TALENT_PREV_PAGE = "I0MC"

TALENTS = {
    TALENT_SHOCKWAVE: "Shockwave",
    TALENT_THIRST: "Thirst for Battle",
    TALENT_RELENTLESS: "Relentless Strikes",
    TALENT_PAIN_TRAIN: "Pain Train",
    TALENT_TITANS_GRIP: "Titan's Grip",
    TALENT_SUNDER: "Sunder Armor",
    TALENT_BERSERKER_RAGE: "Berserker Rage",
    TALENT_BLADESTORM: "Bladestorm",
    TALENT_SLAUGHTERHOUSE: "Slaughterhouse",
    TALENT_DOUBLE_TIME: "Double Time",
    TALENT_BRUTALITY: "Brutality",
    TALENT_WARCRY: "Warcry",
    TALENT_HELLSCREAM: "Hellscream",
    TALENT_TENACITY: "Tenacity",
    TALENT_WEAPONS_MASTER: "Weapons Master",
    TALENT_DEMOLISH: "Demolish",
    TALENT_BATTLE_SCARS: "Battle Scars",
    TALENT_LIVING_SHIELD: "Living Shield",
}

IGNORED_TALENTS = frozenset(
    {
        TALENT_NEXT_PAGE,
        TALENT_PREV_PAGE,
        TALENT_THIRST,
        TALENT_TENACITY,
        TALENT_BATTLE_SCARS,
        TALENT_LIVING_SHIELD,
        TALENT_HELLSCREAM,
    }
)

BT_CD = 6.0
BT_MANA = 10.0
WW_CD = 8.0
WW_MANA = 15.0
SHOUT_CD = 10.0
SHOUT_MANA = 10.0
SHOUT_DUR = 4.0
DEMO_CD = 10.0
DEMO_MANA = 10.0
ENRAGE_DUR = 4.0
ENRAGE_ATTACK_CHANCE = 0.10

GLYPH_UNSEALED = "I0AV"
GLYPH_GLASS = "I0JA"
GLYPH_FORTITUDE = "I07B"
GLYPH_SUPREMACY = "I0EK"
GLYPH_ANIMOSITY = "I0HC"
GLYPH_MINDHASTE = "I0OF"
GLYPH_FORTUNE = "I0EJ"
GLYPH_BATTLE_FRENZY = "I0GZ"
GLYPH_BLOOD_VIOLENCE = "I0H6"
FIRE_ORB = "I07O"
FROST_ORB = "I0NS"
GALACTIC_FURY = "I0JO"
SULFURON_GLOVES = "I0QT"
SPELLBINDER = "tlum"
ITEM_WW_BONUS = "I0NX"
ITEM_BT_BONUS = "I0NY"


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
            for raw in re.findall(r"\+(\d+)% Luck\b", item.tip):
                luck += int(raw) / 100.0
    if _has(build, TALENT_TITANS_GRIP):
        strength += 4 + LEVEL
        agility += 4 + LEVEL
    if _has(build, TALENT_WEAPONS_MASTER):
        mastery += 10.0
    if _has(build, TALENT_DEMOLISH):
        crit += 5.0
    if _has(build, TALENT_SUNDER):
        armor_pen += 2.0
    if _has(build, TALENT_BRUTALITY):
        executes.append((0.40, 0.25))
    if _has(build, GLYPH_FORTITUDE):
        strength += 4 + 2 * LEVEL
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
    cast_stun_lock = 0.0
    seen_stun: set[str] = set()
    for item in build.items:
        if item.rawcode in seen_stun:
            continue
        seen_stun.add(item.rawcode)
        if item.cast_stun_chance and item.cast_stun_duration > 0:
            cast_stun_lock += item.cast_stun_chance * item.cast_stun_duration
    hp = max_hp(BASE_HP, strength)
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
        "fire_orb": 1.0 if FIRE_ORB in codes else 0.0,
        "ww_item": 1.0 if ITEM_WW_BONUS in codes else 0.0,
        "bt_item": 1.0 if ITEM_BT_BONUS in codes else 0.0,
        "luck": luck,
        "mana_max": mana_max,
        "mana_regen": regen,
        "cast_stun_lock": cast_stun_lock,
        "hp": hp,
        "titans_grip": 1.0 if _has(build, TALENT_TITANS_GRIP) else 0.0,
        "weapons_master": 1.0 if _has(build, TALENT_WEAPONS_MASTER) else 0.0,
        "demolish": 1.0 if _has(build, TALENT_DEMOLISH) else 0.0,
        "slaughterhouse": 1.0 if _has(build, TALENT_SLAUGHTERHOUSE) else 0.0,
        "relentless": 1.0 if _has(build, TALENT_RELENTLESS) else 0.0,
        "sunder_fury_extra": 1.0 if _has(build, TALENT_SUNDER) else 0.0,
        **passive,
    }


def _cooldown(base: float, haste: float, stats: dict) -> float:
    return max(0.5, (base * stats["cd_temp"] - stats["flat_cdr"]) / (1.0 + haste))


def simulate(build: Build, targets: int = 5, spec: str = "arms") -> Report:
    if spec not in SPECS:
        raise ValueError(spec)
    if targets < 1:
        raise ValueError(targets)
    stats = stats_of(build)
    sunder_extra = 0.0
    if _has(build, TALENT_SUNDER):
        if spec == "fury":
            sunder_extra = 2.0  # attacks
        elif spec == "arms":
            sunder_extra = 2.0  # physical damage — applied to pen for phys below
    armor_pen = stats["armor_pen"] + (sunder_extra if spec == "arms" else 0.0)
    taken = armor_taken(DUMMY_ARMOR - armor_pen)
    taken_auto = armor_taken(DUMMY_ARMOR - armor_pen - (sunder_extra if spec == "fury" else 0.0))

    mastery_mult = 1.40 if stats["weapons_master"] else 1.00
    arms_mastery = lambda m: (1.0 + (0.10 + 0.006 * m) * mastery_mult) if spec == "arms" else 1.0

    shout_cd = SHOUT_CD - (2.0 if spec == "protection" else 0.0)
    demo_cd = DEMO_CD - (2.0 if spec == "protection" else 0.0)

    sources = {
        "Автоатака": 0.0,
        "Bloodthirst": 0.0,
        "Bloodthirst (удар)": 0.0,
        "Whirlwind": 0.0,
        "Whirlwind (cleave)": 0.0,
        "Demoralizing Shout": 0.0,
        "Shockwave": 0.0,
        "Всплеск огня": 0.0,
    }
    haste = stats["haste"]
    next_attack = 0.0
    next_bt = 0.0
    next_ww = 0.0
    next_shout = 0.0
    next_demo = 0.0 if spec == "arms" else FIGHT
    busy = 0.0
    shout_until = -1.0
    enrage_until = -1.0
    bt_extra = False
    ww_on_cd_until = -1.0
    actions: list[tuple[float, str]] = []
    mana = stats["mana_max"]
    mana_time = 0.0
    sulfuras = Sulfuras() if _wears(build, "I0BR") else None
    cast_time = CAST_POINT + CAST_BACKSWING

    def mastery() -> float:
        return stats["mastery"]

    def enraged(now: float) -> bool:
        return now < enrage_until

    def typed(magical: bool, when: float) -> float:
        bonus = 1.0 + (stats["magic_add"] if magical else stats["phys_add"])
        if stats["sulfuron"]:
            bonus += 0.13 + 0.25 * target_hp(when)
        if magical and stats["spellbinder"]:
            bonus += 0.05 + 0.005 * mastery()
        if stats["glass"]:
            bonus *= 1.15
        if enraged(when):
            bonus *= 1.10
        return bonus

    def crit_factor(when: float, physical: bool) -> float:
        crit = stats["crit"]
        rating = stats["rating"]
        if enraged(when) and spec == "fury":
            crit += 10.0
        if physical and stats["demolish"]:
            # Demolish: phys can crit for 140% (mult 1.40 instead of 2.0 base path via rating add)
            return _crit_factor(crit, 1.40 + rating)
        if stats["slaughterhouse"] and physical:
            # Slaughterhouse adds flat after auto modifiers; approximate via rating bump
            extra = (15.0 + 2.0 * stats["agi"]) / 100.0
            return _crit_factor(crit, 2.0 + rating + extra)
        return _crit_factor(crit, 2.0 + rating)

    def deal(name: str, raw: float, magical: bool, count: int, when: float, potency_scale: float = 1.0, auto: bool = False) -> float:
        amount = raw + stats["potency"] * potency_scale
        if stats["relentless"] and auto:
            amount *= 1.0 + 0.25 * 0.80
        amount *= typed(magical, when)
        amount *= crit_factor(when, not magical)
        use_taken = taken_auto if auto else taken
        amount *= use_taken * _execute_factor(stats, when)
        sources[name] += amount * count
        return amount * count

    def dcs(now: float) -> float:
        value = WHITE_BASE + 0.75 * stats["str"] + stats["damage"]
        if now < shout_until:
            if _has(build, TALENT_WARCRY):
                value += 15.0 + 20.0 * RANK
            else:
                value += 10.0 + 15.0 * RANK
        return value

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
        if sulfuras is not None:
            sulfuras.cast()
        return now + cast_time + stats["cast_stun_lock"]

    def try_enrage_on_attack(now: float) -> None:
        nonlocal enrage_until
        # Expected value: each attack has 10% chance to refresh 4s Enrage.
        # Model as probabilistic refresh contribution without RNG: extend by chance*duration capped.
        # Discrete expected uptime via soft refresh: enrage_until = max(enrage_until, now) + chance*dur
        # Better: keep a duty-cycle — if not up, chance to gain; if up, refresh.
        # Use expected: always add chance * duration onto a decaying buff clock is messy.
        # Simple EV: maintain enrage_until = max(enrage_until, now + ENRAGE_DUR) with probability;
        # replace with: if now >= enrage_until: enrage_until = now + chance*ENRAGE_DUR/(1?);
        # Practical: fractional uptime accumulator — set enrage_until = now + ENRAGE_DUR whenever
        # we "proc" in expectation every 1/chance attacks. Track attacks.
        pass

    enrage_attacks = 0

    def on_attack_enrage(now: float) -> None:
        nonlocal enrage_until, enrage_attacks
        enrage_attacks += 1
        # Expected procs: every 1/0.10 = 10 attacks refresh. Spread as continuous:
        # Each attack contributes ENRAGE_ATTACK_CHANCE chance to set buff to now+4.
        # EV remaining: use enrage_until = max(enrage_until, now) + p * (ENRAGE_DUR) clipped is wrong.
        # Use: with probability p refresh; expected time extension.
        # Implement as: enrage_until = max(enrage_until, now + ENRAGE_ATTACK_CHANCE * ENRAGE_DUR / max(p,1)? 
        # Clearest EV for expected damage: uptime U = 1 - exp(-lambda*D) approx for rare...
        # For sim determinism matching other classes: refresh every 10th attack fully.
        if enrage_attacks % 10 == 0:
            enrage_until = now + ENRAGE_DUR

    def attack_interval(now: float) -> float:
        swing = SWING * (1.20 if stats["galactic"] else 1.0)
        speed = stats["attack_speed"]
        if enraged(now) and spec == "fury":
            speed = min(4.0, speed + 0.15)
        if stats["titans_grip"]:
            # Titan's Grip: AS increases Normal attack damage instead of reducing cooldown.
            # Swing stays at base; damage bonus applied in auto deal path.
            return swing
        return swing / (1.0 + speed)

    def titans_auto_mult(now: float) -> float:
        if not stats["titans_grip"]:
            return 1.0
        speed = stats["attack_speed"]
        if enraged(now) and spec == "fury":
            speed = min(4.0, speed + 0.15)
        return 1.0 + speed

    guard = 0
    while next_attack < FIGHT or next_bt < FIGHT or next_ww < FIGHT or next_shout < FIGHT or next_demo < FIGHT:
        guard += 1
        if guard > 200000:
            break
        moment = min(next_attack, next_bt, next_ww, next_shout, next_demo)
        if moment >= FIGHT:
            break
        if moment < busy:
            if moment == next_attack:
                next_attack = busy
            elif moment == next_bt:
                next_bt = busy
            elif moment == next_ww:
                next_ww = busy
            elif moment == next_shout:
                next_shout = busy
            elif moment == next_demo:
                next_demo = busy
            else:
                break
            continue
        # Priority: Battle Shout (keep up) > Whirlwind > Bloodthirst > Demo (Arms)
        if moment == next_shout:
            if not pay(SHOUT_MANA, moment):
                next_shout = moment + 0.25
                continue
            actions.append((moment, "Battle Shout"))
            shout_until = moment + CAST_POINT + SHOUT_DUR
            busy = cast(moment)
            cd = _cooldown(shout_cd, haste, stats)
            if _has(build, TALENT_DOUBLE_TIME):
                cd *= 0.80  # 20% chance reset ≈ 20% less average CD
            next_shout = moment + cd
            next_attack = max(next_attack, busy)
            continue

        if moment == next_ww:
            if not pay(WW_MANA, moment):
                next_ww = moment + 0.25
                continue
            actions.append((moment, "Whirlwind"))
            power = dcs(moment + CAST_POINT)
            raw = (65.0 * RANK - 10.0) + 0.75 * power
            if _has(build, TALENT_PAIN_TRAIN):
                raw += 0.50 * stats["str"]
            raw *= arms_mastery(mastery())
            if stats["ww_item"]:
                raw *= 1.25
            deal("Whirlwind", raw, False, targets, moment + CAST_POINT)
            note_damage_mana(targets)
            busy = cast(moment)
            cd = _cooldown(WW_CD, haste, stats)
            if _has(build, TALENT_DOUBLE_TIME):
                cd *= 0.80
            next_ww = moment + cd
            ww_on_cd_until = next_ww
            next_attack = max(next_attack, busy)
            continue

        if moment == next_bt:
            if not pay(BT_MANA, moment):
                next_bt = moment + 0.25
                continue
            actions.append((moment, "Bloodthirst"))
            power = dcs(moment + CAST_POINT)
            raw = 75.0 * RANK + 0.50 * power + 0.05 * stats["hp"]
            if _has(build, TALENT_PAIN_TRAIN):
                raw += 0.75 * stats["str"]
            raw *= arms_mastery(mastery())
            dealt = deal("Bloodthirst", raw, False, 1, moment + CAST_POINT)
            note_damage_mana(1)
            if _has(build, TALENT_SHOCKWAVE):
                wave = 0.15 * (dealt)  # already fully modified chunk; approximate from raw path
                # Recompute from raw for cleanliness:
                wave_raw = 0.15 * raw
                deal("Shockwave", wave_raw, False, max(1, targets - 1), moment + CAST_POINT)
                note_damage_mana(max(1, targets - 1))
            bt_extra = True
            busy = cast(moment)
            cd = _cooldown(BT_CD, haste, stats)
            if _has(build, TALENT_DOUBLE_TIME):
                cd *= 0.80
            next_bt = moment + cd
            next_attack = max(next_attack, busy)
            continue

        if moment == next_demo and spec == "arms":
            if not pay(DEMO_MANA, moment):
                next_demo = moment + 0.25
                continue
            actions.append((moment, "Demoralizing Shout"))
            power = dcs(moment + CAST_POINT)
            raw = 20.0 + 0.25 * power + 0.05 * stats["hp"]
            deal("Demoralizing Shout", raw, False, targets, moment + CAST_POINT)
            note_damage_mana(targets)
            busy = cast(moment)
            cd = _cooldown(demo_cd, haste, stats)
            if _has(build, TALENT_DOUBLE_TIME):
                cd *= 0.80
            next_demo = moment + cd
            next_attack = max(next_attack, busy)
            continue


        if moment == next_attack:
            recover(moment)
            power = dcs(moment)
            auto_raw = power * titans_auto_mult(moment)
            before = sources["Автоатака"]
            deal("Автоатака", auto_raw, False, 1, moment, stats["attack_potency"], auto=True)
            if stats["auto_pct"] != 1.0:
                sources["Автоатака"] = before + (sources["Автоатака"] - before) * stats["auto_pct"]
            mana = min(stats["mana_max"], mana + attack_mana_gain(stats))
            note_damage_mana(1)
            on_attack_enrage(moment)

            # Whirlwind cleave passive: chance (30+5*rank)%; 40% (+10% if WW on CD) of auto to other targets
            cleave_chance = (30.0 + 5.0 * RANK) / 100.0 * (1.0 + stats["luck"])
            cleave_ratio = 0.40 + (0.10 if moment < ww_on_cd_until else 0.0)
            if targets > 1 and cleave_chance > 0:
                auto_dealt = sources["Автоатака"] - before
                sources["Whirlwind (cleave)"] += auto_dealt * cleave_chance * cleave_ratio * (targets - 1)
                note_damage_mana(targets - 1)

            if bt_extra:
                bt_extra = False
                extra = 20.0 + 20.0 * RANK + 0.75 * power
                if spec == "fury":
                    extra += 15.0 + 2.0 * mastery()
                if stats["bt_item"]:
                    extra *= 1.50
                deal("Bloodthirst (удар)", extra, False, 1, moment, stats["attack_potency"], auto=True)
                note_damage_mana(1)

            if stats["fire_orb"]:
                splash = (20.0 + 0.35 * stats["str"]) * targets * taken * _execute_factor(stats, moment)
                sources["Всплеск огня"] += splash
                note_damage_mana(targets)
            if sulfuras is not None:
                execute = _execute_factor(stats, moment)
                if sulfuras.attack():
                    splash = stats["str"] * typed(True, moment) * crit_factor(moment, False) * taken * execute * targets
                    sources["Sulfuras"] = sources.get("Sulfuras", 0.0) + splash
                    note_damage_mana(targets)
                echo = power * taken_auto * execute * sulfuras_echo_chance(stats["luck"])
                sources["Sulfuras (удар)"] = sources.get("Sulfuras (удар)", 0.0) + echo

            if _has(build, TALENT_BLADESTORM) and next_ww > moment:
                next_ww = max(moment, next_ww - 0.20)

            next_attack = moment + attack_interval(moment)
            continue
        break


    total = sum(sources.values())
    recover(FIGHT)
    mana_left = 0.0 if stats["mana_max"] <= 0 else 100.0 * mana / stats["mana_max"]
    return Report(build, total / FIGHT, total, sources, actions, stats, targets, mana_left=mana_left)


def best_points(build: Build, targets: int, spec: str) -> tuple[float, dict[str, int]]:
    from sunken_sim.esc import apply_points, greedy_points, points_payload

    def score(pts: dict) -> float:
        trial = apply_points(build, pts)
        report = simulate(trial, targets, spec)
        return report.dps

    dps, pts = greedy_points(score)
    return dps, points_payload(pts)


