"""Demon Hunter fight for Sunken City v2.5.2a, level 6.

Unit E00A (Meta form E00B). Agility 24 + 2.4, strength 12 + 1.2, intellect
14 + 1.4 (36 / 18 / 21 at level 6). White hit 31 + 1 die (1d1) = 32, plus
0.75 x AGI (DCS formula). Attack cooldown 1.70. Primary AGI. Ability rank 1.
Spec level on A0CY: 1 Havoc, 2 Vengeance, 3 Devourer.

Metamorphosis A0RD (E00A <-> E00B, Fury drain), Eye Beam A0RF (Havoc F),
Demon Spikes A0RH (Vengeance F, defensive), Collapsing Star A0RK (Devourer F),
The Hunt A076, Immolation Aura A06F (active + on-attack passive),
Inner Demon A0E4 (defensive; only cast to feed Chaos Nova).

Every damage formula below is copied from war3map.j; see docs/demon_hunter.md.
Healing, taunts, damage reflection and evasion are not scored.
"""

from __future__ import annotations

import heapq
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

BASE_STR = int(12 + (LEVEL - 1) * 1.2)
BASE_AGI = int(24 + (LEVEL - 1) * 2.4)
BASE_INT = int(14 + (LEVEL - 1) * 1.4)
WHITE_BASE = 32.0  # ua1b 31 + 1d1
SWING = 1.70
BASE_MANA = 120.0
BASE_HP = 250.0

SPECS = ("havoc", "vengeance", "devourer")
HERO_CLASS = "DemonHunter"
RANK = 1

TALENT_ENDURING_TORMENT = "I0DA"
TALENT_INCUBUS = "I0PC"
TALENT_CHAOS_BLADE = "I07E"
TALENT_COSMIC_FORCE = "I0FL"
TALENT_DEMONIC_WARDS = "I05M"
TALENT_CONSUME = "I04P"
TALENT_FALLOUT = "I04X"
TALENT_DARKNESS = "I0PA"
TALENT_BLOODLET = "I05S"
TALENT_NEXT_PAGE = "I0MD"
TALENT_SOUL_CLEAVE = "I07H"
TALENT_FELFIRE = "I0FK"
TALENT_CHAOS_NOVA = "I05K"
TALENT_SOUL_IMMOLATION = "I0V2"
TALENT_THROW_GLAIVE = "I0PB"
TALENT_SINGULARITY = "I08D"
TALENT_VOID_GLAIVE = "I0V1"
TALENT_CHAINS_OF_ANGUISH = "I0C5"
TALENT_DEMONIC_POWER = "I0V3"
TALENT_PREV_PAGE = "I0MC"

TALENTS = {
    TALENT_ENDURING_TORMENT: "Enduring Torment",
    TALENT_INCUBUS: "Incubus",
    TALENT_CHAOS_BLADE: "Chaos Blade",
    TALENT_COSMIC_FORCE: "Cosmic Force",
    TALENT_DEMONIC_WARDS: "Demonic Wards",
    TALENT_CONSUME: "Consume",
    TALENT_FALLOUT: "Fallout",
    TALENT_DARKNESS: "Darkness",
    TALENT_BLOODLET: "Bloodlet",
    TALENT_SOUL_CLEAVE: "Soul Cleave",
    TALENT_FELFIRE: "Felfire",
    TALENT_CHAOS_NOVA: "Chaos Nova",
    TALENT_SOUL_IMMOLATION: "Soul Immolation",
    TALENT_THROW_GLAIVE: "Throw Glaive",
    TALENT_SINGULARITY: "Singularity",
    TALENT_VOID_GLAIVE: "Void Glaive",
    TALENT_CHAINS_OF_ANGUISH: "Chains of Anguish",
    TALENT_DEMONIC_POWER: "Demonic Power",
}

# Demonic Wards / Darkness / Bloodlet are defensive or healing. Pages are UI.
IGNORED_TALENTS = frozenset(
    {TALENT_DEMONIC_WARDS, TALENT_DARKNESS, TALENT_BLOODLET, TALENT_NEXT_PAGE, TALENT_PREV_PAGE}
)

META_CD = 10.0  # A0RD acdn
META_MANA = 0.0
EYE_BEAM_CD = 10.0  # A0RF
EYE_BEAM_MANA = 25.0
EYE_BEAM_DUR = 2.50  # EyBe_Config_Duration
EYE_BEAM_STEP = 0.03  # EyBe_Config_Periodic
CHAOS_ICD = 0.20
SPIKES_CD = 10.0  # A0RH
SPIKES_MANA = 25.0
STAR_CD = 10.0  # A0RK
STAR_MANA = 25.0
STAR_DELAY = 0.75  # CollapsingStar PolledWait
HUNT_CD = 10.0  # A076
HUNT_MANA = 15.0
THRILL_DUR = 6.0
THRILL_SPEED = 0.25
IMMO_CD = 10.0  # A06F
IMMO_MANA = 20.0
IMMO_DUR = 6.0  # A0RL / A0RM
INNER_CD = 12.0  # A0E4
INNER_MANA = 20.0
BLADE_DUR = 4.0  # B06M
FALLOUT_DUR = 4.0
FALLOUT_ARMOR = 3.0
FURY_MAX = 100
FRAGMENT_FURY = 5

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
ITEM_TORMENTOR = "I0V4"
ITEM_WARGLAIVE = "I0V5"
ITEM_COSMIC_HELM = "I0V6"
ITEM_DARK_NAARU = "I0V7"
ITEM_LEGWRAPS = "I0V8"  # fragments on enemy death: none in a dummy fight
ITEM_SHOULDERPADS = "I0V9"  # Inner Demon heal: not scored


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
    spell_crit = False
    spell_mult = 1.50
    executes: list[tuple[float, float]] = []
    auto_pct = 1.0
    attack_potency = 1.0
    magic_add = 0.0
    phys_add = 0.0
    mana_flat = 0.0
    health_flat = 0.0
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
    # Incubus (I0PC): MagicalType_Bonus += 0.10 + 0.003 x INT.
    if _has(build, TALENT_INCUBUS):
        magic_add += 0.10 + 0.003 * intel
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
        "spell_crit": 1.0 if spell_crit else 0.0,
        "spell_mult": spell_mult,
        "cd_temp": cd_temp,
        "flat_cdr": flat_cdr,
        "glass": 1.0 if _has(build, GLYPH_GLASS) or GLYPH_GLASS in codes else 0.0,
        "spellbinder": 1.0 if SPELLBINDER in codes else 0.0,
        "sulfuron": 1.0 if SULFURON_GLOVES in codes else 0.0,
        "galactic": 1.0 if GALACTIC_FURY in codes else 0.0,
        "fire_orb": 1.0 if FIRE_ORB in codes else 0.0,
        "tormentor": 1.0 if ITEM_TORMENTOR in codes else 0.0,
        "warglaive": 1.0 if ITEM_WARGLAIVE in codes else 0.0,
        "cosmic_helm": 1.0 if ITEM_COSMIC_HELM in codes else 0.0,
        "dark_naaru": 1.0 if ITEM_DARK_NAARU in codes else 0.0,
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


def simulate(build: Build, targets: int = 5, spec: str = "havoc") -> Report:
    if spec not in SPECS:
        raise ValueError(spec)
    if targets < 1:
        raise ValueError(targets)
    stats = stats_of(build)
    luck_mult = 1.0 + stats["luck"]
    has = lambda code: _has(build, code)  # noqa: E731
    agi = stats["agi"]
    intel = stats["int"]
    mastery = stats["mastery"]
    haste = stats["haste"]
    havoc = spec == "havoc"
    vengeance = spec == "vengeance"
    devourer = spec == "devourer"
    nova = has(TALENT_CHAOS_NOVA)
    glaive_talent = has(TALENT_THROW_GLAIVE)
    singularity = 40.0 + 2.0 * agi + 0.10 * stats["mana_max"]
    immo_dur = IMMO_DUR + (3.0 if has(TALENT_ENDURING_TORMENT) else 0.0)
    immo_rate = 1.0 + ((0.15 + 0.12 * agi / 100.0) if has(TALENT_FELFIRE) else 0.0)
    immo_interval = (1.40 - 0.10 * RANK) / immo_rate
    # Void Glaive (I0V1) or Shard of the Dark Naaru (I0V7): base attack cooldown x0.92 (evasion 0).
    void_glaive = has(TALENT_VOID_GLAIVE) or stats["dark_naaru"]
    f_name = {"havoc": "Eye Beam", "vengeance": "Demon Spikes", "devourer": "Collapsing Star"}[spec]

    sources: dict[str, float] = {
        "Автоатака": 0.0,
        "Immolation Aura": 0.0,
        "The Hunt": 0.0,
        f_name: 0.0,
        "Chaos Blade": 0.0,
        "Throw Glaive": 0.0,
        "Chaos Nova": 0.0,
        "Singularity": 0.0,
        "Всплеск огня": 0.0,
    }
    actions: list[tuple[float, str]] = []
    mana = stats["mana_max"]
    mana_time = 0.0
    sulfuras = Sulfuras() if _wears(build, "I0BR") else None
    cast_time = CAST_POINT + CAST_BACKSWING

    meta = False
    fury = 0
    drain_stacks = 0
    thrill_until = -1.0
    main_until = -1.0
    stack_until = -1.0
    immo_next = FIGHT * 10
    blade_until = -1.0
    blade_stacks = 0
    last_chaos = -10.0
    chaos_turn = 0
    fallout_until = [-1.0] * targets
    sing_done = [False] * targets
    fury_dither = _Dither()
    power_dither = _Dither()
    cleave_dither = _Dither()
    glaive_dither = _Dither()
    beam_glaive_dither = _Dither()
    chaos_dither = _Dither()
    fall_dither = [_Dither() for _ in range(targets)]
    double_dither = [_Dither() for _ in range(targets)]
    pending: list[tuple[float, int, str, float]] = []
    seq = 0

    def push(when: float, kind: str, value: float) -> None:
        nonlocal seq
        seq += 1
        heapq.heappush(pending, (when, seq, kind, value))

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

    def gen(amount: int) -> None:
        """GenerateFury: Demonic Power (I0V3) doubles it at 25% x Luck."""
        nonlocal fury
        if has(TALENT_DEMONIC_POWER) and power_dither.roll(0.25 * luck_mult):
            fury = min(FURY_MAX, fury + amount)
        fury = min(FURY_MAX, fury + amount)

    def potency(now: float) -> float:
        value = stats["potency"]
        if havoc:
            value += 2.0  # Potency_Tooltip Func015
            if meta:
                value += 4.0 + 0.15 * agi  # Func013 (E00B)
        return value

    def increase(attack: bool) -> float:
        value = 1.0
        if has(TALENT_COSMIC_FORCE):
            value += 0.003 * fury
        if meta and stats["tormentor"]:
            value += 0.20
        if attack and has(TALENT_CHAINS_OF_ANGUISH):
            value += 0.10
        return value

    def crit_chance() -> float:
        chance = stats["crit"]
        if has(TALENT_FALLOUT) and (not vengeance or meta):
            chance += 8.0
        return chance

    def typed(magical: bool, now: float) -> float:
        bonus = 1.0 + (stats["magic_add"] if magical else stats["phys_add"])
        if stats["sulfuron"]:
            bonus += 0.13 + 0.25 * target_hp(now)
        if magical and stats["spellbinder"]:
            bonus += 0.05 + 0.005 * mastery
        if stats["glass"]:
            bonus *= 1.15
        if magical and devourer and meta:
            bonus *= 1.25 + 0.01 * drain_stacks
        return bonus

    def taken(t: int, now: float) -> float:
        armor = DUMMY_ARMOR - stats["armor_pen"]
        if fallout_until[t] > now:
            armor -= FALLOUT_ARMOR
        return armor_taken(armor) * _execute_factor(stats, now)

    def deal(name: str, raw: float, t: int, now: float, kind: str, chaos: bool = False) -> tuple[float, float]:
        """kind: attack (physical, crits), magic (magical), plain (no damage type)."""
        attack = kind == "attack"
        scale = (stats["attack_potency"] if attack else 1.0) + (0.35 if havoc else 0.0)
        amount = raw + potency(now) * scale
        amount *= increase(attack)
        share = 0.0
        if attack:
            amount *= typed(False, now) * (CHAOS_UNARMORED if chaos else 1.0)
            chance = crit_chance()
            share = max(0.0, min(100.0, chance)) / 100.0
            amount *= _crit_factor(chance, 2.0 + stats["rating"])
        elif kind == "magic":
            amount *= typed(True, now)
            if stats["spell_crit"]:
                chance = crit_chance()
                share = max(0.0, min(100.0, chance)) / 100.0
                amount *= _crit_factor(chance, stats["spell_mult"] + stats["rating"])
        amount *= taken(t, now)
        sources[name] = sources.get(name, 0.0) + amount
        note_damage_mana(1)
        if havoc and fury_dither.roll(0.08 * luck_mult):
            gen(1)
        if share > 0 and has(TALENT_FALLOUT) and fall_dither[t].roll(share):
            fallout_until[t] = now + FALLOUT_DUR
        return amount, share

    def immo_hit(t: int, now: float, name: str = "Immolation Aura") -> None:
        """Immolation_Aura_Deal_Damage."""
        raw = 5.0 + 10.0 * RANK + 0.30 * agi
        deal(name, raw, t, now, "magic")
        if havoc and double_dither[t].roll((5.0 + 0.5 * mastery) / 100.0):
            deal(name, raw, t, now, "magic")
        if has(TALENT_SOUL_IMMOLATION):
            nxt["F"] -= 0.10

    def dcs() -> float:
        return WHITE_BASE + 0.75 * agi + stats["damage"]

    def on_attack(t: int, now: float, share: float, code: bool) -> None:
        nonlocal blade_until, blade_stacks
        immo_hit(t, now)  # A06F learned: every attack burns its target
        if has(TALENT_CHAOS_BLADE):
            if blade_until > now:
                blade_stacks += 1
            else:
                blade_stacks = 1
                blade_until = now + BLADE_DUR
            for _ in range(blade_stacks):
                deal("Chaos Blade", 10.0 + 0.10 * dcs(), t, now, "plain")
        if has(TALENT_SOUL_CLEAVE):
            gen(3 if cleave_dither.roll(share) else 1)
        if not code and glaive_talent and glaive_dither.roll(share * 0.5 * luck_mult):
            glaive(t, now)

    def glaive(t: int, now: float) -> None:
        raw = 15.0 + 0.40 * dcs()
        _d, share = deal("Throw Glaive", raw, t, now, "attack", chaos=True)
        on_attack(t, now, share, True)
        other = (t + 1) % targets
        _d, share = deal("Throw Glaive", 0.5 * raw, other, now, "attack", chaos=True)
        on_attack(other, now, share, True)

    def apply_immolation(now: float) -> None:
        nonlocal main_until, stack_until, immo_next
        if main_until <= now and stack_until <= now:
            immo_next = now + immo_interval
        if main_until > now:
            stack_until = now + immo_dur
        else:
            main_until = now + immo_dur

    def class_cast(now: float, hunt: bool = False) -> None:
        """OnSpellcast for the Demon Hunter."""
        if nova:
            for t in range(targets):
                deal("Chaos Nova", 25.0 + 0.50 * agi, t, now, "magic")
        if devourer and not hunt:
            gen(FRAGMENT_FURY)  # Soul Fragment, picked up at once

    def cast(now: float, extra: float = 0.0) -> float:
        if sulfuras is not None:
            sulfuras.cast()
        return now + cast_time + extra + stats["cast_stun_lock"]

    def speed_stat(now: float) -> float:
        speed = stats["attack_speed"]
        if now < thrill_until:
            speed += THRILL_SPEED
        return min(4.0, max(-0.8, speed))

    def attack_interval(now: float) -> float:
        swing = SWING * (1.20 if stats["galactic"] else 1.0)
        if void_glaive:
            swing *= 0.92
        return swing / (1.0 + speed_stat(now))

    def fury_tick(now: float) -> None:
        nonlocal fury, drain_stacks, meta
        if meta:
            if fury > 0:
                fury -= 5 + drain_stacks
                if fury <= 0:
                    fury = 0
                    drain_stacks = 0
                    meta = False
                    actions.append((now, "Meta ends"))
                else:
                    drain_stacks += 1
                if stats["cosmic_helm"] and devourer:
                    nxt["F"] -= 1.0
        elif fury < 25:
            gen(1)

    def beam_tick(now: float, per_hit: float) -> None:
        nonlocal last_chaos, chaos_turn
        hits = 2 if targets == 1 else targets
        chaos_at = -1
        if now - last_chaos >= CHAOS_ICD - 1e-9:
            p = 1.0 - (1.0 - _chance(0.25 * luck_mult)) ** hits
            if chaos_dither.roll(p):
                last_chaos = now
                chaos_at = chaos_turn % hits
                chaos_turn += 1
        for k in range(hits):
            t = 0 if targets == 1 else k
            if k == chaos_at:
                _d, share = deal("Eye Beam", per_hit, t, now, "attack", chaos=True)
                on_attack(t, now, share, True)
                if glaive_talent and beam_glaive_dither.roll(0.20 * luck_mult):
                    glaive(t, now)
            else:
                deal("Eye Beam", per_hit, t, now, "plain")

    def star_land(now: float) -> None:
        raw = (125.0 + 2.0 * agi) * (1.0 + (0.03 / 10.0) * (agi + intel))
        for t in range(targets):
            deal("Collapsing Star", raw, t, now, "magic")
            if has(TALENT_SINGULARITY) and not sing_done[t]:
                sing_done[t] = True
                deal("Singularity", singularity, t, now, "magic")

    nxt = {"Meta": 0.0, "F": 0.0, "Hunt": 0.0, "Immolation": 0.0, "Inner": 0.0}
    if vengeance and not nova:
        nxt["F"] = FIGHT * 10  # Demon Spikes only buys Chaos Nova here
    if not nova:
        nxt["Inner"] = FIGHT * 10
    order = ("Meta", "F", "Hunt", "Immolation", "Inner")
    next_attack = 0.0
    next_fury = 1.0
    busy = 0.0
    guard = 0
    while True:
        guard += 1
        if guard > 400000:
            break
        attack_at = max(next_attack, busy)
        cast_at = FIGHT * 10
        choice = None
        for name in order:
            if name == "Meta" and meta:
                continue
            ready = max(nxt[name], busy)
            if ready < cast_at - 1e-9:
                cast_at, choice = ready, name
        event_at = pending[0][0] if pending else FIGHT * 10
        moment = min(attack_at, cast_at, event_at, next_fury, immo_next)
        if moment >= FIGHT:
            break
        if moment == event_at:
            _when, _s, kind, value = heapq.heappop(pending)
            if kind == "beam":
                beam_tick(moment, value)
            elif kind == "star":
                star_land(moment)
            continue
        if moment == next_fury:
            fury_tick(moment)
            next_fury += 1.0
            continue
        if moment == immo_next:
            count = (main_until > moment) + (stack_until > moment)
            for _ in range(count):
                for t in range(targets):
                    immo_hit(t, moment)
            immo_next = moment + immo_interval if (main_until > moment or stack_until > moment) else FIGHT * 10
            continue
        if choice is not None and cast_at <= attack_at and moment == cast_at:
            name = choice
            hit_at = moment + CAST_POINT
            if name == "Meta":
                actions.append((moment, "Metamorphosis"))
                busy = cast(moment)
                meta = True
                class_cast(hit_at)
                nxt[name] = moment + _cooldown(META_CD, haste, stats)
            elif name == "F" and havoc:
                if not pay(EYE_BEAM_MANA, moment):
                    nxt[name] = moment + 0.25
                    continue
                actions.append((moment, "Eye Beam"))
                busy = cast(moment, EYE_BEAM_DUR)
                class_cast(hit_at)
                per_hit = 7.0 + 0.15 * dcs()
                left, tick, when = EYE_BEAM_DUR, 0.0, hit_at
                while left >= EYE_BEAM_STEP - 1e-9:
                    if tick < EYE_BEAM_STEP:
                        push(when, "beam", per_hit)
                        tick = 0.50 / (1.0 + 0.50 * speed_stat(when))
                    else:
                        tick -= EYE_BEAM_STEP
                    left -= EYE_BEAM_STEP
                    when += EYE_BEAM_STEP
                nxt[name] = moment + _cooldown(EYE_BEAM_CD, haste, stats)
            elif name == "F" and devourer:
                if not pay(STAR_MANA, moment):
                    nxt[name] = moment + 0.25
                    continue
                actions.append((moment, "Collapsing Star"))
                busy = cast(moment)
                if has(TALENT_CONSUME):
                    for _ in range(3):
                        gen(FRAGMENT_FURY)
                class_cast(hit_at)
                push(hit_at + STAR_DELAY, "star", 0.0)
                nxt[name] = moment + _cooldown(STAR_CD, haste, stats)
            elif name == "F":
                if not pay(SPIKES_MANA, moment):
                    nxt[name] = moment + 0.25
                    continue
                actions.append((moment, "Demon Spikes"))
                busy = cast(moment)
                class_cast(hit_at)
                nxt[name] = moment + _cooldown(SPIKES_CD, haste, stats)
            elif name == "Hunt":
                if not pay(HUNT_MANA, moment):
                    nxt[name] = moment + 0.25
                    continue
                actions.append((moment, "The Hunt"))
                busy = cast(moment)
                class_cast(hit_at, hunt=True)
                thrill_until = hit_at + THRILL_DUR
                if stats["warglaive"]:
                    apply_immolation(hit_at)
                raw = 100.0 + 1.80 * agi
                if devourer:
                    raw *= 1.08 + 0.005 * mastery
                deal("The Hunt", raw, 0, hit_at, "magic")
                if has(TALENT_SINGULARITY):
                    deal("Singularity", 0.50 * singularity, 0, hit_at, "magic")
                if devourer:
                    gen(FRAGMENT_FURY)
                nxt[name] = moment + _cooldown(HUNT_CD, haste, stats)
            elif name == "Immolation":
                if not pay(IMMO_MANA, moment):
                    nxt[name] = moment + 0.25
                    continue
                actions.append((moment, "Immolation Aura"))
                busy = cast(moment)
                class_cast(hit_at)
                apply_immolation(hit_at)
                nxt[name] = moment + _cooldown(IMMO_CD, haste, stats)
            elif name == "Inner":
                if not pay(INNER_MANA, moment):
                    nxt[name] = moment + 0.25
                    continue
                actions.append((moment, "Inner Demon"))
                busy = cast(moment)
                class_cast(hit_at)
                nxt[name] = moment + _cooldown(INNER_CD, haste, stats)
            next_attack = max(next_attack, busy)
            continue
        # Auto-attack (E00B: ranged Chaos attack).
        moment = attack_at
        recover(moment)
        power = dcs()
        before = sources["Автоатака"]
        _dealt, share = deal("Автоатака", power, 0, moment, "attack", chaos=meta)
        if stats["auto_pct"] != 1.0:
            sources["Автоатака"] = before + (sources["Автоатака"] - before) * stats["auto_pct"]
        on_attack(0, moment, share, False)
        gain_mana(attack_mana_gain(stats))
        if stats["fire_orb"]:
            splash = (20.0 + 0.35 * agi) * targets * taken(1 % targets, moment)
            sources["Всплеск огня"] += splash
            note_damage_mana(targets)
        if sulfuras is not None:
            execute = _execute_factor(stats, moment)
            armor = armor_taken(DUMMY_ARMOR - stats["armor_pen"])
            if sulfuras.attack():
                splash = agi * (1.0 + stats["magic_add"]) * (1.15 if stats["glass"] else 1.0) * armor * execute * targets
                sources["Sulfuras"] = sources.get("Sulfuras", 0.0) + splash
                note_damage_mana(targets)
            echo = power * armor * execute * sulfuras_echo_chance(stats["luck"])
            sources["Sulfuras (удар)"] = sources.get("Sulfuras (удар)", 0.0) + echo
        next_attack = moment + attack_interval(moment)

    total = sum(sources.values())
    recover(FIGHT)
    mana_left = 0.0 if stats["mana_max"] <= 0 else 100.0 * mana / stats["mana_max"]
    return Report(build, total / FIGHT, total, sources, actions, stats, targets, mana_left=mana_left)


def best_points(build: Build, targets: int, spec: str) -> tuple[float, tuple[int, int, int, int]]:
    return simulate(build, targets, spec).dps, (0, 0, 0, 0)
