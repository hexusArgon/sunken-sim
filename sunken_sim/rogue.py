"""Rogue fight for Sunken City, level 6.

Unit E005. Agility 30 + 3, strength 10 + 1, intellect 10 + 1 (45 / 15 / 15 at
level 6). White hit 30 + 1 die (1d1) = 31, plus 0.75 x AGI (DCS formula).
Attack cooldown is not set by the map, so the Edem default 1.70 is used.
Primary AGI. Ability rank is 1. Spec level on A0KU: 1 Subtlety, 2 Combat.

Vendetta A0FB, Sinister Strike A0FH (Subtlety) / Dispatch A0EQ (Combat),
Shadowstep A04G, Fan of Knives A0GA, Stealth A007, Rupture A0JP (passive),
Inspect A0H2 (only cast for Elaborate Planning). Healing is not scored.
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
BASE_AGI = int(30 + (LEVEL - 1) * 3)
BASE_INT = int(10 + (LEVEL - 1) * 1)
WHITE_BASE = 31.0
SWING = 1.70
BASE_MANA = 120.0
BASE_HP = 250.0

SPECS = ("subtlety", "combat")
HERO_CLASS = "Rogue"
RANK = 1

TALENT_PHANTOM_ASSASSIN = "I0JX"
TALENT_FIND_WEAKNESS = "I0JU"
TALENT_SHADOW_DANCE = "I0QE"
TALENT_HONOR_AMONG_THIEVES = "I0QF"
TALENT_COMBAT_POTENCY = "I0JV"
TALENT_PARANOIA = "I0JS"
TALENT_SUBTERFUGE = "I0JT"
TALENT_VANISH = "I0QG"
TALENT_COUP_DE_GRACE = "I0IP"
TALENT_NIGHTSTRIKE = "I0QC"
TALENT_SURPRISE_ATTACK = "I0JQ"
TALENT_KILLING_SPREE = "I04V"
TALENT_DIRTY_TRICKS = "I0JR"
TALENT_CHEAP_SHOT = "I049"
TALENT_HIDDEN_BLADES = "I0QD"
TALENT_MARKED_FOR_DEATH = "I0JW"
TALENT_ELABORATE_PLANNING = "I0IR"
TALENT_SHURIKEN_STORM = "I0IT"
TALENT_NEXT_PAGE = "I0MD"
TALENT_PREV_PAGE = "I0MC"

TALENTS = {
    TALENT_PHANTOM_ASSASSIN: "Phantom Assassin",
    TALENT_FIND_WEAKNESS: "Find Weakness",
    TALENT_SHADOW_DANCE: "Shadow Dance",
    TALENT_HONOR_AMONG_THIEVES: "Honor Among Thieves",
    TALENT_COMBAT_POTENCY: "Combat Potency",
    TALENT_PARANOIA: "Paranoia",
    TALENT_SUBTERFUGE: "Subterfuge",
    TALENT_VANISH: "Vanish",
    TALENT_COUP_DE_GRACE: "Coup de Grace",
    TALENT_NIGHTSTRIKE: "Nightstrike",
    TALENT_SURPRISE_ATTACK: "Surprise Attack",
    TALENT_KILLING_SPREE: "Killing Spree",
    TALENT_DIRTY_TRICKS: "Dirty Tricks",
    TALENT_CHEAP_SHOT: "Cheap Shot",
    TALENT_HIDDEN_BLADES: "Hidden Blades",
    TALENT_MARKED_FOR_DEATH: "Marked for Death",
    TALENT_ELABORATE_PLANNING: "Elaborate Planning",
    TALENT_SHURIKEN_STORM: "Shuriken Storm",
}

# Cheap Shot only stuns. Pages are UI.
IGNORED_TALENTS = frozenset({TALENT_NEXT_PAGE, TALENT_PREV_PAGE, TALENT_CHEAP_SHOT})

VENDETTA_CD = 25.0
VENDETTA_MANA = 0.0  # A0FB amcs L1 not set; ANcl default
VENDETTA_FOLLOW = 0.4  # Ncl1
VENDETTA_DUR = 4.45  # trigger timer (buff B04N lasts 4.5)
STRIKE_CD = 9.0
STRIKE_MANA = 18.0
STRIKE_BUFF = 4.0
SHADOWSTEP_CD = 9.0  # AOcl default, matches tooltip
SHADOWSTEP_MANA = 15.0
FOK_CD = 7.0
FOK_MANA = 15.0
STEALTH_CD = 10.0
STEALTH_MANA = 10.0
BACKSTAB = 80.0  # A007 Owk3 L1
AMBUSH_DUR = 6.0
AMBUSH_SPEED = 0.08 + 0.08 * RANK
INSPECT_CD = 5.0
INSPECT_FOLLOW = 0.8
PLANNING_DUR = 10.0
SPREE_DUR = 4.0
VANISH_ICD = 4.0
EVADE = 0.30
PRESSURE_STEP = 0.2

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
ITEM_SHADOWGUISE = "I0RA"
ITEM_BOUNTY_BLADES = "I0RC"
ITEM_CUTTHROAT_SHIV = "I0R9"
ITEM_SHADOWCRAFT_BELT = "I0RB"


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
        "glass": 1.0 if _has(build, GLYPH_GLASS) or GLYPH_GLASS in codes else 0.0,
        "spellbinder": 1.0 if SPELLBINDER in codes else 0.0,
        "sulfuron": 1.0 if SULFURON_GLOVES in codes else 0.0,
        "galactic": 1.0 if GALACTIC_FURY in codes else 0.0,
        "fire_orb": 1.0 if FIRE_ORB in codes else 0.0,
        "shadowguise": 1.0 if ITEM_SHADOWGUISE in codes else 0.0,
        "bounty_blades": 1.0 if ITEM_BOUNTY_BLADES in codes else 0.0,
        "cutthroat_shiv": 1.0 if ITEM_CUTTHROAT_SHIV in codes else 0.0,
        "shadowcraft_belt": 1.0 if ITEM_SHADOWCRAFT_BELT in codes else 0.0,
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



def _timeline_key(build: Build, stats: dict, spec: str, targets: int) -> tuple:
    items = tuple(sorted(item.rawcode for item in build.items))
    talents = tuple(sorted(build.talents))
    glyphs = tuple(sorted(build.glyphs))
    esc = (
        build.potency_points,
        build.mastery_points,
        build.crit_points,
        build.luck_points,
        getattr(build, "haste_points", 0),
        getattr(build, "attack_speed_points", 0),
        getattr(build, "damage_points", 0),
        getattr(build, "mana_points", 0),
        getattr(build, "pet_damage_points", 0),
    )
    return (items, talents, glyphs, esc, spec, targets, round(stats.get("agi", 0), 6), round(stats.get("str", 0), 6))


_TIMELINE: dict[tuple, tuple] = {}


def score_events(events: list[tuple[str, float]]) -> dict[str, float]:
    sources: dict[str, float] = {}
    for name, amount in events:
        sources[name] = sources.get(name, 0.0) + amount
    return sources


def simulate(build: Build, targets: int = 5, spec: str = "subtlety") -> Report:
    if spec not in SPECS:
        raise ValueError(spec)
    if targets < 1:
        raise ValueError(targets)
    stats = stats_of(build)
    cache_key = _timeline_key(build, stats, spec, targets)
    cached = _TIMELINE.get(cache_key)
    if cached is not None:
        events, actions, mana_left = cached
        sources = score_events(events)
        total = sum(sources.values())
        return Report(build, total / FIGHT, total, sources, actions, stats, targets, mana_left=mana_left)
    luck_mult = 1.0 + stats["luck"]
    has = lambda code: _has(build, code)  # noqa: E731
    agi = stats["agi"]
    mastery = stats["mastery"]
    haste = stats["haste"]
    strike_name = "Sinister Strike" if spec == "subtlety" else "Dispatch"
    # A0FH learned (Subtlety only): Physical type bonus +15%.
    strike_phys = 0.15 if spec == "subtlety" else 0.0
    vendetta_feed = 0.50 + 0.01 * mastery

    sources = {
        "Автоатака": 0.0,
        strike_name: 0.0,
        "Shadowstep": 0.0,
        "Fan of Knives": 0.0,
        "Rupture": 0.0,
        "Vendetta": 0.0,
        "Paranoia": 0.0,
        "Hidden Blades": 0.0,
        "Coup de Grace": 0.0,
        "Всплеск огня": 0.0,
    }
    actions: list[tuple[float, str]] = []
    events: list[tuple[str, float]] = []

    def add_damage(name: str, amount: float) -> None:
        if amount:
            events.append((name, amount))

    mana = stats["mana_max"]
    mana_time = 0.0
    sulfuras = Sulfuras() if _wears(build, "I0BR") else None
    cast_time = CAST_POINT + CAST_BACKSWING

    vend_start = -1.0
    vend_until = -1.0
    vend_acc = 0.0
    planning_until = -1.0
    ambush_until = -1.0
    spree_until = -1.0
    strike_until = -1.0
    stealth_pending = False
    behind_pending = False
    ruptured = False
    dance_pending = False
    storm_acc = 0.0
    vanish_ready = 0.0
    vanish_acc = 0.0

    def vend_on(now: float) -> bool:
        return vend_start <= now < vend_until

    def taken_for(index: int, now: float, enhanced: bool = False) -> float:
        armor = float(DUMMY_ARMOR)
        if not enhanced:
            armor -= stats["armor_pen"]
            if has(TALENT_FIND_WEAKNESS):
                armor -= 5.0
        if index == 0 and has(TALENT_MARKED_FOR_DEATH) and vend_on(now):
            armor -= 4.0
        return armor_taken(armor)

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

    def increase(now: float) -> float:
        value = 1.0
        if has(TALENT_SUBTERFUGE):
            recover(now)
            value += 0.08 + 0.01 * (mana / 50.0)
        if has(TALENT_ELABORATE_PLANNING) and now < planning_until:
            value += 0.15
        return value

    def physical(now: float) -> float:
        bonus = 1.0 + stats["phys_add"] + strike_phys
        if stats["sulfuron"]:
            bonus += 0.13 + 0.25 * target_hp(now)
        if stats["glass"]:
            bonus *= 1.15
        return bonus

    def dcs(now: float) -> float:
        value = WHITE_BASE + 0.75 * agi + stats["damage"]
        if now < spree_until:
            value *= 1.30
        return value

    def coup(now: float, attack: bool, count: float) -> None:
        nonlocal vend_acc
        if not has(TALENT_COUP_DE_GRACE) or vend_acc <= 0:
            return
        chance = _chance((0.07 if attack else 0.04) * luck_mult) * count
        dealt = vend_acc * taken_for(0, now, enhanced=True) * chance
        add_damage("Coup de Grace", dealt)
        vend_acc += vendetta_feed * dealt

    def landed(dealt: float, index: int, now: float, attack: bool, count: float) -> None:
        nonlocal vend_acc
        if index == 0 and vend_on(now):
            vend_acc += vendetta_feed * dealt
            coup(now, attack, count)

    def hit(
        name: str,
        raw: float,
        now: float,
        *,
        index: int = 0,
        attack: bool = False,
        count: float = 1.0,
        potency_scale: float = 1.0,
        attack_inc: float = 1.0,
        crit_bonus: float = 0.0,
        sure_crit: bool = False,
    ) -> tuple[float, float]:
        """Physical hit through PreDamage_Increase. Returns (dealt, crit share)."""
        amount = raw + stats["potency"] * potency_scale
        amount *= increase(now) * physical(now)
        share = 0.0
        taken = taken_for(index, now) * _execute_factor(stats, now)
        if attack:
            amount *= attack_inc
            chance = 100.0 if sure_crit else stats["crit"] + crit_bonus
            if has(TALENT_FIND_WEAKNESS):
                chance += 5.0
            if now < ambush_until and has(TALENT_SURPRISE_ATTACK):
                chance += 15.0
            share = max(0.0, min(100.0, chance)) / 100.0
            mult = 2.0 + stats["rating"]
            dealt = amount * taken * _crit_factor(chance, mult)
            if stats["bounty_blades"]:
                flat = 40.0 if (index == 0 and vend_on(now)) else 15.0
                dealt += share * flat * mult * _execute_factor(stats, now)
        else:
            dealt = amount * taken
        add_damage(name, dealt * count)
        landed(dealt, index, now, attack, count)
        return dealt, share

    def rupture(now: float, count: float, from_potency: bool) -> None:
        raw = 10.0 + 2.25 * dcs(now)
        if has(TALENT_SHADOW_DANCE):
            raw *= 1.15
        if stats["cutthroat_shiv"]:
            raw *= 1.25
        if spec == "combat":
            # Pierce attack: crits, and re-enters OnDamage as an attack.
            _dealt, share = hit("Rupture", raw, now, attack=True, count=count)
            if has(TALENT_COMBAT_POTENCY) and not from_potency:
                chance = _chance(0.08 * (1.0 + 0.5 * share) * luck_mult)
                rupture(now, count * chance, True)
        else:
            hit("Rupture", raw, now, count=count)

    def fan(now: float, name: str, scale: float, count: float) -> None:
        nonlocal storm_acc
        raw = 70.0 * RANK + 0.75 * dcs(now)
        if stats["shadowcraft_belt"]:
            raw *= 1.25
        raw *= scale
        for index in range(targets):
            hit(name, raw, now, index=index, count=count)
        note_damage_mana(targets * count)
        if has(TALENT_SHURIKEN_STORM):
            storm_acc += count * (1.0 - (1.0 - _chance(0.08 * luck_mult)) ** targets)

    def class_cast(now: float) -> None:
        """OnSpellcast_Heroes for Ability_Agi spells."""
        if has(TALENT_PARANOIA) and vend_on(now):
            hit("Paranoia", 25.0 + 0.40 * dcs(now), now)
            note_damage_mana(1)
        if has(TALENT_HIDDEN_BLADES):
            fan(now, "Hidden Blades", 0.5, _chance(0.35 * luck_mult))

    def cast(now: float, extra: float = 0.0) -> float:
        if sulfuras is not None:
            sulfuras.cast()
        return now + cast_time + extra + stats["cast_stun_lock"]

    def attack_interval(now: float) -> float:
        swing = SWING * (1.20 if stats["galactic"] else 1.0)
        speed = stats["attack_speed"]
        if now < ambush_until:
            speed += AMBUSH_SPEED
        speed = min(4.0, max(-0.8, speed))
        return swing / (1.0 + speed)

    def release(now: float) -> None:
        nonlocal vend_acc, vend_start, vend_until
        # ENHANCED: skips PreDamage_Increase; the B04N buff (and Marked armor) is gone.
        add_damage("Vendetta", vend_acc * armor_taken(float(DUMMY_ARMOR)))
        vend_acc = 0.0
        vend_start = vend_until = -1.0
        if has(TALENT_HONOR_AMONG_THIEVES):
            recover(now)
            gain_mana(0.12 * stats["mana_max"])

    strike_flat = 1.0 if has(TALENT_DIRTY_TRICKS) else 0.0
    stealth_flat = 1.5 if has(TALENT_DIRTY_TRICKS) else 0.0
    vendetta_flat = 6.0 if has(TALENT_MARKED_FOR_DEATH) else 0.0
    shadowstep_mult = 1.25 if stats["shadowguise"] else 1.0

    next_attack = 0.0
    nxt = {
        "Inspect": 0.0 if has(TALENT_ELABORATE_PLANNING) else FIGHT * 10,
        "Vendetta": 0.0,
        "Shadowstep": 0.0,
        "Stealth": 0.0,
        "Strike": 0.0,
        "Fan of Knives": 0.0,
    }
    order = ("Inspect", "Vendetta", "Shadowstep", "Stealth", "Strike", "Fan of Knives")
    next_pressure = PRESSURE_STEP if has(TALENT_VANISH) else FIGHT * 10
    busy = 0.0
    guard = 0
    while True:
        guard += 1
        if guard > 400000:
            break
        attack_at = max(next_attack, busy)
        cast_at = FIGHT * 10
        choice = None
        if not stealth_pending:
            for name in order:
                ready = nxt[name]
                if name == "Inspect":
                    ready = max(ready, planning_until)
                ready = max(ready, busy)
                if ready < cast_at - 1e-9:
                    cast_at, choice = ready, name
        release_at = vend_until if vend_until >= 0 else FIGHT * 10
        moment = min(attack_at, cast_at, release_at, next_pressure)
        if moment >= FIGHT:
            break
        if moment == release_at:
            release(moment)
            continue
        if moment == next_pressure:
            if moment >= vanish_ready:
                vanish_acc += EVADE
                if vanish_acc >= 1.0:
                    vanish_acc = 0.0
                    vanish_ready = moment + VANISH_ICD
                    nxt["Stealth"] = min(nxt["Stealth"], moment)
                    recover(moment)
                    gain_mana(0.10 * stats["mana_max"])
            next_pressure += PRESSURE_STEP
            continue
        if cast_at <= attack_at and choice is not None and moment == cast_at:
            name = choice
            hit_at = moment + CAST_POINT
            if name == "Inspect":
                if not pay(0.0, moment):
                    nxt[name] = moment + 0.25
                    continue
                actions.append((moment, "Inspect"))
                busy = cast(moment, INSPECT_FOLLOW)
                planning_until = hit_at + PLANNING_DUR
                nxt[name] = moment + _cooldown(INSPECT_CD, haste, stats)
            elif name == "Vendetta":
                if not pay(VENDETTA_MANA, moment):
                    nxt[name] = moment + 0.25
                    continue
                actions.append((moment, "Vendetta"))
                busy = cast(moment, VENDETTA_FOLLOW)
                vend_start, vend_until, vend_acc = hit_at, hit_at + VENDETTA_DUR, 0.0
                nxt[name] = moment + _cooldown(VENDETTA_CD, haste, stats, vendetta_flat)
                # Paranoia is not credited on Vendetta's own cast (trigger order unknown).
                if has(TALENT_HIDDEN_BLADES):
                    fan(hit_at, "Hidden Blades", 0.5, _chance(0.35 * luck_mult))
            elif name == "Shadowstep":
                if not pay(SHADOWSTEP_MANA, moment):
                    nxt[name] = moment + 0.25
                    continue
                actions.append((moment, "Shadowstep"))
                busy = cast(moment)
                class_cast(hit_at)
                raw = 10.0 + 90.0 * RANK + 1.40 * dcs(hit_at)
                if hit_at < ambush_until:
                    raw *= (1.15 + 0.05 * RANK) + (0.30 if has(TALENT_NIGHTSTRIKE) else 0.0)
                    if not has(TALENT_SURPRISE_ATTACK):
                        ambush_until = hit_at
                raw *= shadowstep_mult
                if not ruptured or dance_pending:
                    ruptured, dance_pending = True, False
                    rupture(hit_at, 1.0, False)
                hit("Shadowstep", raw, hit_at)
                note_damage_mana(1)
                if has(TALENT_KILLING_SPREE):
                    spree_until = hit_at + SPREE_DUR
                behind_pending = True
                nxt[name] = moment + _cooldown(SHADOWSTEP_CD, haste, stats)
            elif name == "Stealth":
                if not pay(STEALTH_MANA, moment):
                    nxt[name] = moment + 0.25
                    continue
                actions.append((moment, "Stealth"))
                busy = cast(moment)
                class_cast(hit_at)
                stealth_pending = True
                ambush_until = hit_at + AMBUSH_DUR
                if has(TALENT_SHADOW_DANCE):
                    dance_pending = True
                if spec == "subtlety":
                    nxt["Shadowstep"] = min(nxt["Shadowstep"], moment)
                nxt[name] = moment + _cooldown(STEALTH_CD, haste, stats, stealth_flat)
            elif name == "Strike":
                if not pay(STRIKE_MANA, moment):
                    nxt[name] = moment + 0.25
                    continue
                actions.append((moment, strike_name))
                busy = cast(moment)
                class_cast(hit_at)
                strike_until = hit_at + STRIKE_BUFF
                nxt[name] = moment + _cooldown(STRIKE_CD, haste, stats, strike_flat)
            elif name == "Fan of Knives":
                if not pay(FOK_MANA, moment):
                    nxt[name] = moment + 0.25
                    continue
                actions.append((moment, "Fan of Knives"))
                busy = cast(moment)
                class_cast(hit_at)
                fan(hit_at, "Fan of Knives", 1.0, 1.0)
                nxt[name] = moment + _cooldown(FOK_CD, haste, stats)
            if storm_acc >= 1.0:
                storm_acc -= 1.0
                nxt["Fan of Knives"] = min(nxt["Fan of Knives"], busy)
            next_attack = max(next_attack, busy)
            continue
        # Auto-attack.
        moment = attack_at
        recover(moment)
        power = dcs(moment)
        raw = power + (BACKSTAB * RANK if stealth_pending else 0.0)
        attack_inc = 1.0
        if has(TALENT_PHANTOM_ASSASSIN) and behind_pending:
            attack_inc += 0.25
        dispatch = spec == "combat" and moment < strike_until
        if dispatch:
            chance_now = stats["crit"] + (5.0 if has(TALENT_FIND_WEAKNESS) else 0.0)
            attack_inc += 0.40 + 0.01 * chance_now
        auto_name = strike_name if dispatch else "Автоатака"
        mark = len(events)
        _dealt, share = hit(
            auto_name,
            raw,
            moment,
            attack=True,
            potency_scale=stats["attack_potency"],
            attack_inc=attack_inc,
            sure_crit=dispatch,
        )
        if stats["auto_pct"] != 1.0:

            for i in range(mark, len(events)):

                n, a = events[i]

                if n == auto_name:

                    events[i] = (n, a * stats["auto_pct"])
        if dispatch:
            strike_until = -1.0
        if spec == "subtlety" and moment < strike_until:
            strike_until = -1.0
            hit(strike_name, 35.0 + 1.10 * power + 0.50 * agi, moment)
            note_damage_mana(1)
        stealth_pending = False
        behind_pending = False
        if not ruptured or dance_pending:
            ruptured, dance_pending = True, False
            rupture(moment, 1.0, False)
        elif has(TALENT_COMBAT_POTENCY):
            chance = _chance(0.08 * (1.0 + 0.5 * share) * luck_mult)
            rupture(moment, chance, True)
        gain_mana(attack_mana_gain(stats))
        note_damage_mana(1)
        if stats["fire_orb"]:
            splash = (20.0 + 0.35 * agi) * targets * taken_for(1, moment) * _execute_factor(stats, moment)
            add_damage("Всплеск огня", splash)
            note_damage_mana(targets)
        if sulfuras is not None:
            execute = _execute_factor(stats, moment)
            taken = taken_for(0, moment)
            if sulfuras.attack():
                splash = agi * (1.0 + stats["magic_add"]) * (1.15 if stats["glass"] else 1.0) * taken * execute * targets
                add_damage("Sulfuras", splash)
                note_damage_mana(targets)
            echo = power * taken * execute * sulfuras_echo_chance(stats["luck"])
            add_damage("Sulfuras (удар)", echo)
        next_attack = moment + attack_interval(moment)

    recover(FIGHT)
    mana_left = 0.0 if stats["mana_max"] <= 0 else 100.0 * mana / stats["mana_max"]
    while len(_TIMELINE) >= 8000:
        _TIMELINE.pop(next(iter(_TIMELINE)))
    _TIMELINE[cache_key] = (list(events), actions, mana_left)
    sources = score_events(events)
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


