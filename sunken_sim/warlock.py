"""Warlock fight for Sunken City v2.5.2b, level 6.

Unit O00A. Level 6 stats: STR 18, AGI 13, INT 43. White hit 17 + 1d1 = 18, plus 0.75 x INT
(DCS formula). Attack cooldown 1.85, attack type MAGIC (scored as magical attacks).
Primary INT. Ability rank is 1. Base HP 230, base mana 175.
Spec level on A0LF (udg_Glyphs_Unit[3]): 1 Demonology, 2 Destruction, 3 Affliction.
Destruction swaps Agony A0LI for Chaos Bolt A0QZ; Affliction swaps Backdraft A0QX for
Siphon Life A0EG. Talents sit on udg_Talents_Unit[3]; I0TP turns on every Mastery effect
that checks it (tick rates, Destruction crit, demon attack speed).

Spells: Haunt A0QW (7 s, 35 mana), Demonwrath A0E2 (6 s, 40 mana), Summon Felguard A048
(12 s, 40 mana), Chaos Bolt A0QZ (12 s, 40 mana), Life Tap A0O4 (4 s, free),
Siphon Life A0EG (3 s, 20 mana, 6 s channel).
Periodic damage: Haunt (B00V, global timer), Agony (B08R, global timer), Immolate (B08N,
global timer). Potency (owner) is added to every damage instance from the owner, demons
included, except ENHANCED damage (Havoc, Felguard cleave). Healing is not scored.
"""

from __future__ import annotations

import re

from sunken_sim.pressure import max_hp
from sunken_sim.shadow import (
    CAST_BACKSWING,
    CAST_POINT,
    CHAOS_UNARMORED,
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

BASE_STR = int(12 + (LEVEL - 1) * 1.2)  # O00A ustr/ustp
BASE_AGI = int(9 + (LEVEL - 1) * 0.9)  # uagi/uagp
BASE_INT = int(29 + (LEVEL - 1) * 2.9)  # uint/uinp
WHITE_BASE = 18.0  # O00A ua1b 17 + 1d1
SWING = 1.85  # O00A ua1c
BASE_MANA = 175.0
BASE_HP = 230.0

SPECS = ("demonology", "destruction", "affliction")
HERO_CLASS = "Warlock"
RANK = 1
TARGET_LEVEL = LEVEL  # GetUnitLevel(target) for Drain Soul: assumed equal to hero level

TALENT_WRATHGUARD = "I0M2"
TALENT_DRAIN_SOUL = "I0LY"
TALENT_CHAOTIC_ENERGIES = "I0M4"
TALENT_INCINERATE = "I043"
TALENT_SOUL_LEECH = "I0PJ"
TALENT_MALEFIC_GRASP = "I0LX"
TALENT_HAVOC = "I0M3"
TALENT_DEMONIC_FURY = "I0M1"
TALENT_CONSUMPTION = "I0LZ"
TALENT_ACCELERATION = "I0PK"
TALENT_IMPLOSION = "I040"
TALENT_RAIN_OF_FIRE = "I0TQ"
TALENT_GRIMOIRE = "I0M0"
TALENT_CREMATION = "I0PM"
TALENT_DEMON_RAGE = "I0PL"
TALENT_WITHERED_SOUL = "I0TR"
TALENT_DEMONIC_EMPOWERMENT = "I0PI"
TALENT_ALL_MASTERY = "I0TP"
TALENT_NEXT_PAGE = "I0MD"
TALENT_PREV_PAGE = "I0MC"

TALENTS = {
    TALENT_WRATHGUARD: "Wrathguard",
    TALENT_DRAIN_SOUL: "Drain Soul",
    TALENT_CHAOTIC_ENERGIES: "Chaotic Energies",
    TALENT_INCINERATE: "Incinerate",
    TALENT_SOUL_LEECH: "Soul Leech",
    TALENT_MALEFIC_GRASP: "Malefic Grasp",
    TALENT_HAVOC: "Havoc",
    TALENT_DEMONIC_FURY: "Demonic Fury",
    TALENT_CONSUMPTION: "Consumption",
    TALENT_ACCELERATION: "Acceleration",
    TALENT_IMPLOSION: "Implosion",
    TALENT_RAIN_OF_FIRE: "Rain of Fire",
    TALENT_GRIMOIRE: "Grimoire of Service",
    TALENT_CREMATION: "Cremation",
    TALENT_DEMON_RAGE: "Demon Rage",
    TALENT_WITHERED_SOUL: "Withered Soul",
    TALENT_DEMONIC_EMPOWERMENT: "Demonic Empowerment",
    TALENT_ALL_MASTERY: "Mastery of All",
}

# Pages are UI only.
IGNORED_TALENTS = frozenset({TALENT_NEXT_PAGE, TALENT_PREV_PAGE})

HAUNT_CD, HAUNT_MANA, HAUNT_DUR = 7.0, 35.0, 10.0  # A0QW -> A046 (B00V)
HAUNT_ARMOR = 2.0  # A046 Nab3
WRATH_CD, WRATH_MANA, WRATH_DUR = 6.0, 40.0, 10.0  # A0E2 (B033)
WRATH_DCS = 0.35  # 0.30 + 0.05 x lvl
WRATH_AS = 0.15  # 0.10 + 0.05 x lvl
FELGUARD_CD, FELGUARD_MANA = 12.0, 40.0  # A048
CB_CD, CB_MANA, CB_DUR = 12.0, 40.0, 4.0  # A0QZ (B08Z)
TAP_CD = 4.0  # A0O4
SIPHON_CD, SIPHON_MANA, SIPHON_CHANNEL = 3.0, 20.0, 6.0  # A0EG
AGONY_DUR = 12.0  # A0MZ -> B08R
IMMOLATE_DUR = 8.0  # A0LH -> B08N
DRAIN_SOUL_DUR = 6.0  # A0R1 -> B01L
REVEL_BONUS = 0.50  # A0QY -> B08Y, next demon attack
FELGUARD_LIFE = 12.0
IMP_LIFE = 10.0
FELGUARD_SWING = 1.5
IMP_SWING = 1.35
FIREBOLT_PERIOD = 2.0  # A0R4

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
ITEM_MARK_OF_THE_WILD = "I06B"
ITEM_PREDAPLANT_THORN = "I05W"
ITEM_GULDAN = "I0TS"  # Life Tap: -8% of full CD on all other abilities
ITEM_SARGERAS = "I0TT"  # Backdraft x1.25
ITEM_ASHEN_MANTLE = "I0TU"  # demons get Firebolt
ITEM_SINISTER_GAZE = "I0TV"  # Haunt CD -1.5 s
ITEM_SKULL = "I0TW"  # Felguard duration x1.2, Imp +1.2 s
ITEM_MALEFIC_HOOD = "I0TX"  # 33% x luck on Haunt / Agony / Immolate apply


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
    health_flat = 0.0
    pet_damage = 0.0
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
    pet_damage += _esc_pet
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
        if first and bonus.get("primary") and not item.intel and not item.all_stats:
            intel += bonus["primary"]
        elif not first:
            intel += bonus.get("primary", 0)
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
            for raw in re.findall(r"\+(\d+) Health\b", item.tip):
                health_flat += int(raw)
            for raw in re.findall(r"\+(\d+)% Pet Damage\b", item.tip):
                pet_damage += int(raw) / 100.0
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
    if _has(build, GLYPH_FORTUNE):
        luck += 0.15
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
    hp = max_hp(BASE_HP, strength) + health_flat
    summon_crit = 0.0
    summon_rating = 0.0
    if _has(build, GLYPH_BEASTFURY) or GLYPH_BEASTFURY in codes:
        summon_crit += 25.0
    if ITEM_MARK_OF_THE_WILD in codes:
        summon_crit += 7.0
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
        "guldan": 1.0 if ITEM_GULDAN in codes else 0.0,
        "sargeras": 1.0 if ITEM_SARGERAS in codes else 0.0,
        "ashen": 1.0 if ITEM_ASHEN_MANTLE in codes else 0.0,
        "haunt_flat": 1.5 if ITEM_SINISTER_GAZE in codes else 0.0,
        "skull": 1.0 if ITEM_SKULL in codes else 0.0,
        "hood": 1.0 if ITEM_MALEFIC_HOOD in codes else 0.0,
        "pet_damage": pet_damage,
        "summon_crit": summon_crit,
        "summon_rating": summon_rating,
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


class _Dither:
    """Deterministic chance: fires once the accumulated probability reaches 1."""

    def __init__(self) -> None:
        self.acc = 0.0

    def roll(self, chance: float) -> bool:
        self.acc += max(0.0, chance)
        if self.acc >= 1.0 - 1e-9:
            self.acc -= 1.0
            return True
        return False


# (haunt, life_tap, siphon): Haunt focus on the main target (recast = instant burst) or spread
# over fresh targets; Life Tap off / only when mana is short / on cooldown; Siphon Life channel.
POLICIES = tuple(
    (haunt, tap, siphon)
    for haunt in ("focus", "spread")
    for tap in ("off", "mana", "always")
    for siphon in (True, False)
)



def _timeline_key(build: Build, stats: dict, spec: str, targets: int, policy: tuple) -> tuple:
    items = tuple(sorted(item.rawcode for item in build.items))
    talents = tuple(sorted(build.talents))
    glyphs = tuple(sorted(build.glyphs))
    # potency_points omitted: score_events applies stats["potency"] via pot_coeff.
    # crit stays: Backdraft chance and several baked crit weights use hero/summon crit.
    # luck stays: Malefic Hood, agony/haunt rolls, and Sulfuras echo change the tape.
    esc = (
        build.mastery_points,
        build.crit_points,
        build.luck_points,
        getattr(build, "haste_points", 0),
        getattr(build, "attack_speed_points", 0),
        getattr(build, "damage_points", 0),
        getattr(build, "mana_points", 0),
        getattr(build, "pet_damage_points", 0),
    )
    return (
        items,
        talents,
        glyphs,
        esc,
        spec,
        targets,
        policy,
        round(stats.get("int", 0), 6),
        round(stats.get("mastery", 0), 6),
    )


_TIMELINE: dict[tuple, tuple] = {}


# Event kinds for GPU kind/weight compile (farm/hybrid/warlock.py).
KIND_HERO_MAG = 0.0
KIND_HERO_PHYS = 1.0
KIND_EXEC = 2.0  # weight * execute(when) only (summon / fire splash / sulf echo)
KIND_FLAT = 3.0  # fully scored already (Havoc, Demon Rage cleave)


def _typed_bonus(stats: dict, magical: bool, now: float) -> float:
    bonus = 1.0 + (stats["magic_add"] if magical else stats["phys_add"])
    if stats["sulfuron"]:
        bonus += 0.13 + 0.25 * target_hp(now)
    if magical and stats["spellbinder"]:
        bonus += 0.05 + 0.005 * stats["mastery"]
    if stats["glass"]:
        bonus *= 1.15
    return bonus


def score_events(events: list, stats: dict) -> dict[str, float]:
    """Score typed timeline events into named sources.

    Event: (when, name, weight, kind, pot_coeff=0)
      KIND_HERO_MAG/PHYS: weight * typed * execute
      KIND_EXEC: weight * execute
      KIND_FLAT: weight as-is
    weight is pre-typed / pre-execute (crit, taken, agony already applied).
    potency is applied here as weight + potency * pot_coeff.
    """
    sources: dict[str, float] = {}
    potency = stats["potency"]
    for ev in events:
        when, name, weight, kind = ev[0], ev[1], ev[2], ev[3]
        pot_c = ev[4] if len(ev) > 4 else 0.0
        weight = weight + potency * pot_c
        if kind == KIND_FLAT:
            amount = weight
        elif kind == KIND_EXEC:
            amount = weight * _execute_factor(stats, when)
        elif kind == KIND_HERO_MAG:
            amount = weight * _typed_bonus(stats, True, when) * _execute_factor(stats, when)
        elif kind == KIND_HERO_PHYS:
            amount = weight * _typed_bonus(stats, False, when) * _execute_factor(stats, when)
        else:
            raise ValueError(f"unknown warlock event kind {kind}")
        if amount:
            sources[name] = sources.get(name, 0.0) + amount
    return sources


def simulate(build: Build, targets: int = 5, spec: str = "demonology") -> Report:
    """Best of the policies (Haunt focus / spread, Life Tap, Siphon Life channel)."""
    best = None
    for policy in POLICIES:
        if spec != "affliction" and not policy[2]:
            continue  # Siphon Life only exists in Affliction
        if targets == 1 and policy[0] == "spread":
            continue
        report = _simulate(build, targets, spec, policy)
        if best is None or report.dps > best.dps + 1e-9:
            best = report
    return best


def _simulate(build: Build, targets: int, spec: str, policy: tuple[str, str, bool]) -> Report:
    haunt_mode, tap_mode, use_siphon = policy
    if spec not in SPECS:
        raise ValueError(spec)
    if targets < 1:
        raise ValueError(targets)
    stats = stats_of(build)
    luck_mult = 1.0 + stats["luck"]
    has = lambda code: _has(build, code)  # noqa: E731
    demo, destro, affli = spec == "demonology", spec == "destruction", spec == "affliction"
    all_mastery = has(TALENT_ALL_MASTERY)
    has_backdraft = not affli  # A0QX
    has_agony = not destro  # A0LI
    has_cb = destro  # A0QZ
    use_siphon = use_siphon and affli  # A0EG
    intel = int(stats["int"])
    mastery = int(stats["mastery"])
    hp_max = stats["hp"]
    mana_max = stats["mana_max"]
    crit_stat = stats["crit"]
    pen = stats["armor_pen"]
    cache_key = _timeline_key(build, stats, spec, targets, policy)
    cached = _TIMELINE.get(cache_key)
    if cached is not None:
        events, actions, mana_left = cached
        sources = score_events(events, stats)
        total = sum(sources.values())
        return Report(build, total / FIGHT, total, sources, actions, stats, targets, mana_left=mana_left)

    sources: dict[str, float] = {"Автоатака": 0.0}
    actions: list[tuple[float, str]] = []
    events: list = []

    def add_damage(name: str, amount: float, pot_c: float = 0.0) -> None:
        """Fully-scored flat event (Havoc / Demon Rage / legacy)."""
        if amount or pot_c:
            events.append((0.0, name, amount, KIND_FLAT, pot_c))

    def add_event(when: float, name: str, weight: float, kind: float, pot_c: float = 0.0) -> None:
        if weight or pot_c:
            events.append((when, name, weight, kind, pot_c))

    mana = mana_max
    mana_time = 0.0
    hp = hp_max
    sulfuras = Sulfuras() if _wears(build, "I0BR") else None
    cast_time = CAST_POINT + CAST_BACKSWING

    haunt_until = [-1.0] * targets
    agony_until = [-1.0] * targets
    immolate_until = [-1.0] * targets
    withered = [0] * targets
    agony_roll = [_Dither() for _ in range(targets)]
    drain_roll = _Dither()
    imp_roll = _Dither()
    revel_roll = _Dither()
    haunt_apply_roll = _Dither()
    wrath_until = -1.0
    drain_until = -1.0
    cb_buff_until = -1.0
    siphon_until = -1.0
    siphon_target = 0
    casts = 0
    demons: list[dict] = []
    pending: list[tuple[float, int, str, float]] = []
    seq = 0

    def push(when: float, kind: str, arg: float = 0.0) -> None:
        nonlocal seq
        seq += 1
        pending.append((when, seq, kind, arg))

    def recover(now: float) -> None:
        nonlocal mana, mana_time
        if now > mana_time and mana < mana_max:
            mana = min(mana_max, mana + stats["mana_regen"] * (now - mana_time))
        mana_time = now

    def gain_mana(amount: float) -> None:
        nonlocal mana
        mana = min(mana_max, mana + amount)

    def pay(cost: float, now: float, refund: bool = True) -> bool:
        nonlocal mana
        recover(now)
        if mana < cost:
            return False
        mana -= cost
        if refund:
            gain_mana(cast_mana_back(cost, stats))
        return True

    def note_damage_mana(count: float) -> None:
        if stats["damage_mana_pct"]:
            gain_mana(stats["damage_mana_pct"] * mana_max * count)

    def heal(amount: float) -> None:
        nonlocal hp
        hp = min(hp_max, hp + amount)

    def typed(magical: bool, now: float) -> float:
        bonus = 1.0 + (stats["magic_add"] if magical else stats["phys_add"])
        if stats["sulfuron"]:
            bonus += 0.13 + 0.25 * target_hp(now)
        if magical and stats["spellbinder"]:
            bonus += 0.05 + 0.005 * stats["mastery"]
        if stats["glass"]:
            bonus *= 1.15
        return bonus

    def dcs(now: float) -> float:
        value = WHITE_BASE + 0.75 * intel + stats["damage"]
        if now < wrath_until:
            value *= 1.0 + WRATH_DCS  # DCS_Other_Damage_Sources: B033
        return value

    def live_demons(now: float) -> list[dict]:
        return [d for d in demons if d["end"] > now]

    def taken(t: int, hero: bool, now: float) -> float:
        armor = DUMMY_ARMOR - withered[t]
        if haunt_until[t] > now:
            armor -= HAUNT_ARMOR
        if hero:
            armor -= pen
        return armor_taken(armor)

    def agony_flat(t: int, now: float) -> float:
        # PreDamage_Increase: A0LF level 3 only (I0TP not checked here).
        if affli and agony_until[t] > now:
            return 5.0 + 0.07 * intel
        return 0.0

    def hero_crit_chance(now: float) -> float:
        chance = crit_stat
        if destro or all_mastery:
            chance += 5.0 + 0.5 * mastery
        if has(TALENT_DEMONIC_EMPOWERMENT):
            chance += 3.0 * len(live_demons(now))
        return chance

    def hero_hit(name: str, raw: float, now: float, tgts: list[int], *, magical: bool, attack: bool,
                 weight: float = 1.0, potency_scale: float = 1.0, chaos: bool = False) -> tuple[float, float]:
        """Damage by the Warlock on each target in tgts. Returns (dealt on first target, crit share)."""
        if weight <= 0 or not tgts:
            return 0.0, 0.0, 0.0
        chance = hero_crit_chance(now)
        share = max(0.0, min(100.0, chance)) / 100.0
        first = 0.0
        first_pot = 0.0
        pre_total = 0.0
        pre_pot_total = 0.0
        execute = _execute_factor(stats, now)
        typed_m = typed(magical, now)
        for i, t in enumerate(tgts):
            base = raw + agony_flat(t, now)
            mult = 1.0
            if chaos:
                mult *= CHAOS_UNARMORED
            rating = stats["rating"]
            if has(TALENT_CREMATION):
                rating += 0.15
            if has(TALENT_INCINERATE) and immolate_until[t] > now:
                rating += 0.30
            if attack:
                mult *= _crit_factor(chance, 2.0 + rating)
            elif stats["spell_crit"]:
                mult *= _crit_factor(chance, stats["spell_mult"] + rating)
            take = taken(t, True, now)
            pre = base * mult * take
            pre_pot = potency_scale * mult * take
            dealt = pre * typed_m * execute
            dealt_pot = pre_pot * typed_m * execute
            if i == 0:
                first = dealt
                first_pot = dealt_pot
            pre_total += pre
            pre_pot_total += pre_pot
        ev_kind = KIND_HERO_MAG if magical else KIND_HERO_PHYS
        add_event(now, name, pre_total * weight, ev_kind, pre_pot_total * weight)
        note_damage_mana(len(tgts) * weight)
        return first, first_pot, (share if (attack or stats["spell_crit"]) else 0.0)

    def summon_hit(name: str, raw: float, now: float, tgts: list[int], *, magical: bool, attack: bool,
                   weight: float = 1.0, crit_bonus: float = 0.0, increase: float = 0.0,
                   chaos: bool = False) -> tuple[float, float]:
        """Damage by a demon: potency, Pet Damage (+ Revel in Pain), summon crit, armor."""
        if weight <= 0 or not tgts:
            return 0.0, 0.0, 0.0
        chance = stats["summon_crit"] + crit_bonus
        if has(TALENT_DEMONIC_EMPOWERMENT):
            chance += 10.0 + 0.25 * crit_stat
        share = max(0.0, min(100.0, chance)) / 100.0 if attack else 0.0
        first = 0.0
        first_pot = 0.0
        pre_total = 0.0
        pre_pot_total = 0.0
        execute = _execute_factor(stats, now)
        pet = 1.0 + stats["pet_damage"] + increase
        for i, t in enumerate(tgts):
            base = (raw + agony_flat(t, now)) * pet
            pot_part = pet
            if chaos:
                base *= CHAOS_UNARMORED
                pot_part *= CHAOS_UNARMORED
            if attack:
                cf = _crit_factor(chance, 2.0 + stats["summon_rating"])
                base *= cf
                pot_part *= cf
            take = taken(t, False, now)
            pre = base * take
            pre_pot = pot_part * take
            dealt = pre * execute
            dealt_pot = pre_pot * execute
            if i == 0:
                first = dealt
                first_pot = dealt_pot
            pre_total += pre
            pre_pot_total += pre_pot
        add_event(now, name, pre_total * weight, KIND_EXEC, pre_pot_total * weight)
        return first, first_pot, share

    def malefic(now: float, t: int) -> None:
        if stats["hood"]:
            hero_hit("Malefic Hood", 30.0 + 0.30 * intel, now, [t], magical=True, attack=False,
                     weight=_chance(0.33 * luck_mult))

    def agony_apply(now: float, t: int) -> None:
        if not has_agony:
            return
        agony_until[t] = now + AGONY_DUR
        malefic(now, t)

    def agony_chance(now: float, t: int, chance: float) -> None:
        if has_agony and agony_roll[t].roll(chance):
            agony_apply(now, t)

    def haunt_tick_raw(now: float) -> float:
        raw = 10.0 * RANK + 0.15 * intel
        if has(TALENT_DRAIN_SOUL):
            raw += 0.10 * dcs(now)
        return raw

    def haunt_rate(now: float) -> float:
        rate = 1.0
        if affli or all_mastery:
            rate += 0.05 + 0.005 * mastery
        if has(TALENT_ACCELERATION):
            rate += 0.12 + 0.12 * dcs(now) / 100.0
        return rate

    def agony_rate(now: float) -> float:
        rate = 1.0
        if has(TALENT_ACCELERATION):
            rate += 0.12 + 0.12 * dcs(now) / 100.0
        return rate

    def immolate_rate(now: float) -> float:
        rate = 1.0
        if affli or all_mastery:
            rate += 0.05 + 0.005 * mastery
        return rate

    def immolate_raw(now: float) -> float:
        return 5.0 * RANK + 0.10 * dcs(now)

    def haunt_apply(now: float, t: int) -> None:
        if haunt_until[t] > now:
            raw = haunt_tick_raw(now) * 10.0 * haunt_rate(now)
            hero_hit("Haunt (повтор)", raw, now, [t], magical=True, attack=False)
            agony_apply(now, t)
        haunt_until[t] = now + HAUNT_DUR
        if has(TALENT_WITHERED_SOUL):
            withered[t] = min(8, withered[t] + 1)
        malefic(now, t)

    def spawn_imp(now: float) -> None:
        life = IMP_LIFE + (1.2 if stats["skull"] else 0.0)
        raw = 6.0 * RANK + int(0.10 * dcs(now)) + 1.0
        demons.append({"kind": "imp", "next": now, "end": now + life, "raw": raw,
                       "wrath": -1.0, "revel": False, "bolt": now + FIREBOLT_PERIOD})

    def imp_chance(now: float, base: float, weight: float = 1.0) -> None:
        if not has(TALENT_IMPLOSION):
            return
        imps = sum(1 for d in live_demons(now) if d["kind"] == "imp")
        chance = base * 0.75 ** imps * luck_mult * weight
        if imp_roll.roll(chance):
            spawn_imp(now)

    def spawn_felguard(now: float) -> None:
        life = FELGUARD_LIFE * (1.2 if stats["skull"] else 1.0)
        demons.append({"kind": "felguard", "next": now, "end": now + life, "raw": 0.0,
                       "wrath": -1.0, "revel": False, "bolt": now + FIREBOLT_PERIOD})

    def backdraft(now: float, weight: float, hero_source: bool, by_name: str) -> None:
        """Backdraft_Damage on target 0: full on it, half on the others in 200."""
        nonlocal nxt
        if weight <= 0:
            return
        raw = 20.0 + 0.40 * dcs(now)
        if stats["sargeras"]:
            raw *= 1.25
        others = list(range(1, targets))
        if hero_source:
            hero_hit("Backdraft", raw, now, [0], magical=False, attack=False, weight=weight)
            hero_hit("Backdraft", raw / 2.0, now, others, magical=False, attack=False, weight=weight)
            if has_cb and "cb" in nxt and nxt["cb"] > now:
                nxt["cb"] = max(now, nxt["cb"] - 0.75 * weight)
        else:
            summon_hit(f"Backdraft ({by_name})", raw, now, [0], magical=False, attack=False, weight=weight)
            summon_hit(f"Backdraft ({by_name})", raw / 2.0, now, others, magical=False, attack=False,
                       weight=weight)
        if FELGUARD_KEY in nxt:
            imp_chance(now, 0.50, weight)

    def backdraft_on_attack(now: float, crit_share: float, hero_source: bool, by_name: str) -> None:
        if not has_backdraft:
            return
        base = crit_share * 30.0 + (1.0 - crit_share) * 12.0
        chance = (base + 0.08 * dcs(now)) / 100.0
        if not hero_source:
            chance *= 0.5
        if has(TALENT_CREMATION):
            chance *= 1.2
        # v2.5.2b: the roll is BackdraftChance_Total x Luck_Multiplier.
        chance *= luck_mult
        backdraft(now, _chance(chance), hero_source, by_name)

    def havoc(now: float, dealt: float, dealt_pot: float = 0.0) -> None:
        if not has(TALENT_HAVOC):
            return
        if dealt == 0.0 and dealt_pot == 0.0:
            return
        haunted = sum(1 for t in range(targets) if haunt_until[t] > now)
        if haunted:
            add_damage("Havoc", 0.12 * dealt * haunted, 0.12 * dealt_pot * haunted)

    def demon_speed(d: dict, now: float) -> float:
        speed = 0.0
        if demo or all_mastery:
            speed += 0.08 + 0.006 * mastery
        if now < d["wrath"]:
            speed += WRATH_AS + (0.20 if has(TALENT_DEMONIC_FURY) else 0.0)
        return min(4.0, max(-0.8, speed))

    def interval(now: float) -> float:
        swing = SWING * (1.20 if stats["galactic"] else 1.0)
        speed = stats["attack_speed"]
        if now < wrath_until:
            speed += WRATH_AS + (0.20 if has(TALENT_DEMONIC_FURY) else 0.0)
        speed = min(4.0, max(-0.8, speed))
        return swing / (1.0 + speed)

    def spellcast(now: float) -> None:
        """OnSpellcast_Heroes: Grimoire of Service every 8 casts."""
        nonlocal casts
        casts += 1
        if has(TALENT_GRIMOIRE) and casts % 8 == 0:
            spawn_felguard(now)

    FELGUARD_KEY = "felguard"
    fixed_cd = {"felguard": FELGUARD_CD, "haunt": HAUNT_CD, "wrath": WRATH_CD, "cb": CB_CD,
                "siphon": SIPHON_CD, "tap": TAP_CD}
    cost = {"felguard": FELGUARD_MANA, "haunt": HAUNT_MANA, "wrath": WRATH_MANA, "cb": CB_MANA,
            "siphon": SIPHON_MANA, "tap": 0.0}
    names = {"felguard": "Summon Felguard", "haunt": "Haunt", "wrath": "Demonwrath", "cb": "Chaos Bolt",
             "siphon": "Siphon Life", "tap": "Life Tap"}
    order = ["felguard", "wrath", "haunt"] + (["cb"] if has_cb else []) + (["siphon"] if use_siphon else [])
    if tap_mode != "off":
        order.append("tap")
    nxt = {key: 0.0 for key in order}
    full_cd = {key: fixed_cd[key] for key in order}
    tap_value = 25.0 + 25.0 * LEVEL

    haunt_timer = 1.0 / haunt_rate(0.0)
    agony_timer = 1.0 / agony_rate(0.0) if has_agony else FIGHT * 10
    immolate_timer = 1.5 / immolate_rate(0.0)

    next_attack = 0.0
    busy = 0.0
    loops = 0
    clock = 0.0
    while True:
        loops += 1
        if loops > 400000:
            break
        attack_at = max(next_attack, busy, clock, siphon_until)
        cast_at = FIGHT * 10
        choice = None
        for key in order:
            ready = max(nxt[key], busy, clock, siphon_until)
            if key == "tap":
                if hp - tap_value < 0.30 * hp_max:
                    continue
                guess = min(mana_max, mana + stats["mana_regen"] * max(0.0, ready - mana_time))
                if tap_mode == "mana" and guess > mana_max - 0.40 * tap_value:
                    continue
            if key == "wrath":
                # Refresh Demonwrath only when it is about to drop or a demon lacks it.
                due = wrath_until - 1.0
                for d in demons:
                    if d["end"] > ready and d["wrath"] < d["end"]:
                        due = min(due, max(d["next"] - 0.5, d["wrath"] - 1.0))
                ready = max(ready, due)
            if key == "siphon" and ready >= FIGHT - 0.5:
                continue
            if ready < cast_at - 1e-9:
                cast_at, choice = ready, key
        pending_at = min((p[0] for p in pending), default=FIGHT * 10)
        demons[:] = [d for d in demons if d["end"] > clock - 1e-9]
        demon_at = min((d["next"] for d in demons if d["next"] < d["end"]), default=FIGHT * 10)
        bolt_at = FIGHT * 10
        if stats["ashen"]:
            bolt_at = min((d["bolt"] for d in demons if d["bolt"] < d["end"]), default=FIGHT * 10)
        timers = min(haunt_timer, agony_timer, immolate_timer)
        moment = min(attack_at, cast_at, pending_at, demon_at, bolt_at, timers)
        if moment >= FIGHT:
            break
        clock = moment

        if moment == pending_at:
            event = min(pending)
            pending.remove(event)
            _, _, kind, arg = event
            if kind == "siphon":
                t = siphon_target
                raw = (10.0 + 5.0 * LEVEL + 0.65 * intel) / 4.0
                hero_hit("Siphon Life", raw, moment, [t], magical=True, attack=False)
                heal((18.0 + 0.08 * hp_max) / 4.0)
                agony_chance(moment, t, 0.05 * luck_mult)
                if has(TALENT_SOUL_LEECH) and haunt_apply_roll.roll(0.04 * luck_mult):
                    haunt_apply(moment, t)
                imp_chance(moment, 0.20)
            elif kind == "rof":
                raw = 5.0 + 0.20 * dcs(moment)
                hero_hit("Rain of Fire", raw, moment, list(range(targets)), magical=True, attack=False)
                for t in range(targets):
                    immolate_until[t] = max(immolate_until[t], moment + IMMOLATE_DUR)
                if has_backdraft:
                    chance = _chance((5.0 + 0.20 * crit_stat) / 100.0 * luck_mult)
                    for _t in range(targets):
                        backdraft(moment, chance, True, "Rain of Fire")
            continue

        if moment == haunt_timer:
            raw = haunt_tick_raw(moment)
            for t in range(targets):
                if haunt_until[t] <= moment:
                    continue
                ticks = 2.0 if (has(TALENT_MALEFIC_GRASP) and moment < siphon_until and t == siphon_target) else 1.0
                hero_hit("Haunt", raw, moment, [t], magical=True, attack=False, weight=ticks)
                agony_chance(moment, t, 0.20 * luck_mult * ticks)
                if has(TALENT_DRAIN_SOUL) and moment >= drain_until and drain_roll.roll(0.12 * luck_mult * ticks):
                    drain_until = moment + DRAIN_SOUL_DUR
            haunt_timer = moment + 1.0 / haunt_rate(moment)
            continue

        if moment == agony_timer:
            raw = 5.0 + 0.10 * intel
            for t in range(targets):
                if agony_until[t] <= moment:
                    continue
                hero_hit("Agony", raw, moment, [t], magical=True, attack=False)
                if demo and revel_roll.roll(0.20 * luck_mult):
                    pool = [d for d in live_demons(moment) if not d["revel"]] or live_demons(moment)
                    if pool:
                        pool[0]["revel"] = True
            agony_timer = moment + 1.0 / agony_rate(moment)
            continue

        if moment == immolate_timer:
            raw = immolate_raw(moment)
            for t in range(targets):
                if immolate_until[t] <= moment:
                    continue
                weight = 1.0 + _chance(crit_stat / 100.0 * luck_mult)
                if has(TALENT_MALEFIC_GRASP) and agony_until[t] > moment:
                    weight += _chance(0.20 * luck_mult)
                hero_hit("Immolate", raw, moment, [t], magical=True, attack=False, weight=weight)
            immolate_timer = moment + 1.5 / immolate_rate(moment)
            continue

        if moment == bolt_at and bolt_at < attack_at and bolt_at < cast_at:
            d = min((u for u in demons if u["bolt"] < u["end"]), key=lambda u: u["bolt"])
            summon_hit("Firebolt (Ashen Mantle)", 10.0 + 0.10 * intel, moment, [0], magical=True, attack=False)
            d["bolt"] = moment + FIREBOLT_PERIOD
            continue

        if moment == demon_at and demon_at < attack_at and demon_at < cast_at:
            d = min((u for u in demons if u["next"] < u["end"]), key=lambda u: u["next"])
            increase = REVEL_BONUS if d["revel"] else 0.0
            d["revel"] = False
            if d["kind"] == "imp":
                dealt, dealt_pot, share = summon_hit("Imp", d["raw"], moment, [0], magical=True, attack=True,
                                          increase=increase)
                havoc(moment, dealt, dealt_pot)
                swing = IMP_SWING
                label = "Imp"
            else:
                wrathguard = has(TALENT_WRATHGUARD)
                raw = 7.0 + int(8.0 * RANK + 0.20 * dcs(moment) + 0.02 * hp_max) + 1.0
                label = "Wrathguard" if wrathguard else "Felguard"
                dealt, dealt_pot, share = summon_hit(label, raw, moment, [0], magical=False, attack=True,
                                          increase=increase, chaos=wrathguard)
                if wrathguard:
                    havoc(moment, dealt, dealt_pot)
                if has(TALENT_DEMON_RAGE):
                    extra = max(1, targets - 1)
                    add_damage("Demon Rage (cleave)", 0.15 * dealt * extra, 0.15 * dealt_pot * extra)
                swing = FELGUARD_SWING * (1.20 if has(TALENT_CONSUMPTION) else 1.0)
            agony_chance(moment, 0, 0.05 * luck_mult)
            backdraft_on_attack(moment, share, False, label)
            d["next"] = moment + swing / (1.0 + demon_speed(d, moment))
            continue

        if cast_at <= attack_at and choice is not None and moment == cast_at:
            key = choice
            if not pay(cost[key], moment):
                nxt[key] = moment + 0.25
                continue
            hit_at = moment + CAST_POINT
            actions.append((moment, names[key]))
            busy = moment + cast_time + stats["cast_stun_lock"]
            if sulfuras is not None:
                sulfuras.cast()
            spellcast(hit_at)
            haste = stats["haste"]
            flat = 0.0
            if key == "felguard":
                for t in range(targets):
                    immolate_until[t] = hit_at + IMMOLATE_DUR
                    if has(TALENT_INCINERATE):
                        raw = immolate_raw(hit_at) * 8.0 * immolate_rate(hit_at)
                        hero_hit("Incinerate", raw, hit_at, [t], magical=True, attack=False)
                    malefic(hit_at, t)
                if has(TALENT_RAIN_OF_FIRE):
                    speed = 0.5 * stats["attack_speed"]
                    waves = int(5.0 * (1.0 + speed) + 0.5)
                    gap = 1.0 / (1.0 + speed)
                    for i in range(waves):
                        push(hit_at + (i + 1) * gap, "rof")
                for _ in range(2 if demo else 1):
                    spawn_felguard(hit_at)
            elif key == "haunt":
                flat = stats["haunt_flat"]
                if haunt_mode == "focus":
                    t = 0
                else:
                    fresh = [i for i in range(targets) if haunt_until[i] <= hit_at]
                    t = fresh[0] if fresh else min(range(targets), key=lambda i: haunt_until[i])
                haunt_apply(hit_at, t)
            elif key == "wrath":
                wrath_until = hit_at + WRATH_DUR
                for d in live_demons(hit_at):
                    d["wrath"] = hit_at + WRATH_DUR
            elif key == "cb":
                cb_buff_until = hit_at + CB_DUR
            elif key == "tap":
                hp -= tap_value
                gain_mana(0.40 * tap_value)
                if stats["guldan"]:
                    for other in order:
                        if other != "tap" and nxt[other] > hit_at:
                            nxt[other] = max(hit_at, nxt[other] - 0.08 * full_cd[other])
            elif key == "siphon":
                rate = immolate_rate(hit_at)  # Siphon tick rate: same Affliction term
                period = 0.25 / rate
                siphon_target = 0
                # Channel until full or until another spell is ready (casting it breaks the channel).
                stop = hit_at + SIPHON_CHANNEL
                for other in order:
                    if other in ("siphon", "tap"):
                        continue
                    when = nxt[other]
                    if other == "wrath":
                        when = max(when, wrath_until - 1.0)
                    if when > hit_at:
                        stop = min(stop, when)
                siphon_until = max(hit_at + period, stop)
                n = int((siphon_until - hit_at) / period + 1e-9)
                for i in range(n):
                    push(hit_at + (i + 1) * period, "siphon")
                busy = max(busy, siphon_until)
            cd = _cooldown(fixed_cd[key], haste, stats, flat)
            full_cd[key] = cd
            nxt[key] = moment + cd
            next_attack = max(next_attack, busy)
            continue

        # Warlock auto-attack (magic attack type).
        moment = attack_at
        recover(moment)
        white = WHITE_BASE + 0.75 * intel
        if moment < wrath_until:
            white *= 1.0 + WRATH_DCS  # Roar Roa1 on base damage
        power = white + stats["damage"]
        if has(TALENT_DRAIN_SOUL) and moment < drain_until:
            power += 5.0 + 5.0 * TARGET_LEVEL  # A0R1 Nbr1
        mark = len(events)
        dealt, dealt_pot, share = hero_hit("Автоатака", power, moment, [0], magical=True, attack=True,
                                potency_scale=stats["attack_potency"])
        if stats["auto_pct"] != 1.0:
            scale = stats["auto_pct"]
            for i in range(mark, len(events)):
                when, n, w, k, *rest = events[i]
                if n == "Автоатака":
                    pot_c = rest[0] * scale if rest else 0.0
                    events[i] = (when, n, w * scale, k, pot_c)
        havoc(moment, dealt, dealt_pot)
        agony_chance(moment, 0, 0.05 * luck_mult)
        backdraft_on_attack(moment, share, True, "Warlock")
        if has_cb and moment < cb_buff_until:
            cb_buff_until = -1.0
            raw = (75.0 + 1.5 * dcs(moment)) * (1.0 + 0.01 * crit_stat)
            if has(TALENT_CHAOTIC_ENERGIES):
                raw *= 1.0 + 0.255
            cb_dealt, cb_dealt_pot, cb_share = hero_hit("Chaos Bolt", raw, moment, [0], magical=False, attack=True, chaos=True)
            havoc(moment, cb_dealt, cb_dealt_pot)
            backdraft_on_attack(moment, cb_share, True, "Warlock")
        gain_mana(attack_mana_gain(stats))
        if stats["fire_orb"]:
            splash_w = (20.0 + 0.35 * stats["int"]) * targets * taken(0, True, moment)
            add_event(moment, "Всплеск огня", splash_w, KIND_EXEC)
            note_damage_mana(targets)
        if sulfuras is not None:
            if sulfuras.attack():
                splash_w = stats["int"] * taken(0, True, moment) * targets
                splash_w *= _crit_factor(hero_crit_chance(moment), 2.0 + stats["rating"])
                add_event(moment, "Sulfuras", splash_w, KIND_HERO_MAG)
                note_damage_mana(targets)
            echo_w = power * taken(0, True, moment) * sulfuras_echo_chance(stats["luck"])
            add_event(moment, "Sulfuras (удар)", echo_w, KIND_EXEC)
        next_attack = moment + interval(moment)

    recover(FIGHT)
    mana_left = 0.0 if mana_max <= 0 else 100.0 * mana / mana_max
    while len(_TIMELINE) >= 8000:
        _TIMELINE.pop(next(iter(_TIMELINE)))
    _TIMELINE[cache_key] = (list(events), actions, mana_left)
    sources = score_events(events, stats)
    total = sum(sources.values())
    report = Report(build, total / FIGHT, total, sources, actions, stats, targets, mana_left=mana_left)
    return report


def best_points(build: Build, targets: int, spec: str) -> tuple[float, dict[str, int]]:
    from sunken_sim.esc import apply_points, greedy_points, points_payload

    def score(pts: dict) -> float:
        trial = apply_points(build, pts)
        report = simulate(trial, targets, spec)
        return report.dps

    dps, pts = greedy_points(score)
    return dps, points_payload(pts)


