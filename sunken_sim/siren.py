"""Siren fight for Sunken City v2.5.2a, level 6.

Unit N03T (base Nngs). Level 6 stats (base + 5 x gain, floored): STR 13, AGI 39, INT 22.
White hit 27 + 1d1 = 28, plus 0.75 x AGI (DCS formula) + item damage. Attack cooldown 1.7,
pierce (physical). Primary AGI. Ability rank is 1. Base HP 230, base mana 120 (umpr 0).
Spec level on A0JW (udg_Glyphs_Unit[1]): 1 Sharpshooter (Tidal Shot x(1.10 + 0.01 Mastery),
25% x luck Crushing Wave = 0.40 x shot to every enemy on the line), 2 Watershaper (Sea Elemental
summons two, +5 + Mastery elemental max mana), 3 Seagrace (healing: Liquid Arrows heal instead of
damaging, Icy Quiver bonus halved). Talents sit on udg_Talents_Unit[1].

Spells (rank 1): Tidal Shot A0ER (5 s, 15 mana, arms B05F; the next Siren attack fires a
thunderbolt: 80 + 2.0 x AGI magical, then Tidal Fletcher B058 3.5 s on the Siren), Liquid Arrows
A0D2 toggle (B05M; 2 mana per Siren attack: 20 + 0.40 AGI + 0.40 INT magical, x1.15 while B058),
Song of the Siren A0OS (10 s, 10 mana, B04R 6 s: +15% attack speed, 1 + 0.5% max mana / s),
Sea Elemental A051 (10 s, 25 mana, n03U 10 s: 11 + 1d1 + R2I(0.15 DCS), cd 1.3, bounce to
2 targets with 35% loss, Water Core +0.5% damage per mana, +3 mana per hit, every 3rd elemental
hit fires Liquid Arrows at 40%), Stone Gaze A0JQ (15 s, 30 mana, 90 + 1.45 AGI + 2.40 INT magical
in a cone), Mirror Image A0N7 (25 s, 0 mana, e00M 15 s: own hit R2I(0.5 DCS) + 1 every 2.25 s and
the Siren deals 0.5 x DCS as a pierce attack with every image hit).
Healing, crowd control and ally-only effects are not scored.
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

BASE_STR = 13  # N03T 9 + 0.9 x 5 = 13.5 -> 13
BASE_AGI = 39  # 26 + 2.6 x 5
BASE_INT = 22  # 15 + 1.5 x 5 = 22.5 -> 22
WHITE_BASE = 28.0  # N03T ua1b 27 + 1d1
SWING = 1.7  # N03T ua1c
BASE_MANA = 120.0  # N03T umpm / umpi
BASE_HP = 230.0

SPECS = ("sharpshooter", "watershaper", "seagrace")
HERO_CLASS = "Siren"
RANK = 1

TALENT_SEAFLURRY = "I0M9"
TALENT_ELEMENTAL_SHOT = "I0MV"
TALENT_GORGON = "I0OV"
TALENT_HEALING_WATERS = "I0OY"
TALENT_SNAKE_BITE = "I0MU"
TALENT_REFLECTION = "I0N1"
TALENT_SOOTHING = "I0OW"
TALENT_NEPTULON = "I0MX"
TALENT_CORAL = "I08G"
TALENT_LIQUID_FUEL = "I0MW"
TALENT_EMPOWERED = "I0MZ"
TALENT_CONJURE = "I0OX"
TALENT_FLOW = "I0MY"
TALENT_STRING = "I0N0"
TALENT_VIPER = "I0OZ"
TALENT_ICY_QUIVER = "I0AQ"
TALENT_WATERLORD = "I08F"
TALENT_ALLURING = "I08H"
TALENT_NEXT_PAGE = "I0MD"
TALENT_PREV_PAGE = "I0MC"

TALENTS = {
    TALENT_SEAFLURRY: "Seaflurry",
    TALENT_ELEMENTAL_SHOT: "Elemental Shot",
    TALENT_GORGON: "Sight of the Gorgon",
    TALENT_HEALING_WATERS: "Healing Waters",
    TALENT_SNAKE_BITE: "Snake Bite",
    TALENT_REFLECTION: "Reflection",
    TALENT_SOOTHING: "Soothing Melody",
    TALENT_NEPTULON: "Gift of Neptulon",
    TALENT_CORAL: "Coral Arrowheads",
    TALENT_LIQUID_FUEL: "Liquid Fuel",
    TALENT_EMPOWERED: "Empowered Shot",
    TALENT_CONJURE: "Conjure Elemental",
    TALENT_FLOW: "Flow of the Ocean",
    TALENT_STRING: "Enchanted String",
    TALENT_VIPER: "Viper Sting",
    TALENT_ICY_QUIVER: "Icy Quiver",
    TALENT_WATERLORD: "Hydraxian Waterlord",
    TALENT_ALLURING: "Alluring Voice",
}

# Heal (Healing Waters), ally-only attack speed (Flow of the Ocean: the AS hook needs A0QG, which
# elementals and images lack), crowd control (Alluring Voice); pages are UI only.
IGNORED_TALENTS = frozenset({
    TALENT_HEALING_WATERS, TALENT_FLOW, TALENT_ALLURING, TALENT_NEXT_PAGE, TALENT_PREV_PAGE,
})

TIDAL_CD, TIDAL_MANA = 5.0, 15.0  # A0ER
TIDAL_DELAY = 525.0 / 1300.0  # ASSUMPTION: thunderbolt A0O5 missile 1300 over the 525 attack range
FLETCHER_DUR = 3.5  # A0JI L1 (L2 6.0 with Enchanted String)
SONG_CD, SONG_MANA = 10.0, 10.0  # A0OS
SONG_DUR = 6.0  # A0JY L1 (L2 8.0 with Soothing Melody)
ELEMENTAL_CD, ELEMENTAL_MANA = 10.0, 25.0  # A051
ELEMENTAL_LIFE = 10.0
ELEMENTAL_SWING = 1.3  # n03U ua1c (n03H 1.0)
ELEMENTAL_MANA_MAX = 100.0  # n03U umpm
ELEMENTAL_START_MANA = 0.0  # ASSUMPTION: no umpi in data
GAZE_CD, GAZE_MANA = 15.0, 30.0  # A0JQ
MIRROR_CD, MIRROR_MANA = 25.0, 0.0  # A0N7 L1 (amcs unset on L1, AIrl base costs 0)
MIRROR_LIFE = 15.0
MIRROR_SWING = 2.25  # e00M ua1c
BOUNCE_KEEP = 0.65  # n03U udl1 0.35
CHILL_DUR = 4.0

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
ITEM_SCEPTER = "I0RF"  # class item: stats; Song damage reduction is defensive
ITEM_VEST = "I0RE"  # class item: elementals +15 mana / +25 max mana
ITEM_BOW = "I0RD"  # class item: 10% x luck Tidal Shot on Siren attacks
ITEM_BAND = "I0RG"  # class item: Reflection_Bonus 1.25 (no +3 s, no 0.75 Song AS)

ATTACK_DAMAGE_RE = re.compile(r"(?m)^\+(\d+) Attack Damage\b")


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
        # library only parses "+N Damage"; class weapons say "+N Attack Damage" (DCS item damage).
        attack_damage = float(sum(int(v) for v in ATTACK_DAMAGE_RE.findall(item.tip)))
        damage += _copy_value(item.rawcode, "damage", attack_damage, first)
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
        "pet_damage": pet_damage,
        "vest": 1.0 if ITEM_VEST in codes else 0.0,
        "bow": 1.0 if ITEM_BOW in codes else 0.0,
        "band": 1.0 if ITEM_BAND in codes else 0.0,
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


# (Liquid Arrows toggle on / off, Song of the Siren cast / skipped)
POLICIES = tuple((la, song) for la in (False, True) for song in (True, False))


def simulate(build: Build, targets: int = 5, spec: str = "sharpshooter") -> Report:
    """Best of the policies (Liquid Arrows on / off, Song on / off)."""
    best = None
    for policy in POLICIES:
        report = _simulate(build, targets, spec, policy)
        if best is None or report.dps > best.dps + 1e-9:
            best = report
    return best


def _simulate(build: Build, targets: int, spec: str, policy: tuple[bool, bool]) -> Report:
    use_la, use_song = policy
    if spec not in SPECS:
        raise ValueError(spec)
    if targets < 1:
        raise ValueError(targets)
    stats = stats_of(build)
    luck_mult = 1.0 + stats["luck"]
    has = lambda code: _has(build, code)  # noqa: E731
    sharp = spec == "sharpshooter"
    shaper = spec == "watershaper"
    grace = spec == "seagrace"
    intel = int(stats["int"])
    agi = int(stats["agi"])
    mastery = int(stats["mastery"])
    mana_max = stats["mana_max"]
    crit_stat = stats["crit"]
    pen = stats["armor_pen"]
    reflection = 1.25 if (has(TALENT_REFLECTION) or stats["band"]) else 1.0
    mirror_song_as = 0.75 if has(TALENT_REFLECTION) else 0.50  # AS / mana hooks only check I0N1
    fletcher_dur = 6.0 if has(TALENT_STRING) else FLETCHER_DUR
    song_dur = 8.0 if has(TALENT_SOOTHING) else SONG_DUR
    song_as = 0.10 + 0.05 * RANK
    song_mana = (1.0 * RANK + 0.005 * mana_max) * (1.5 if has(TALENT_SOOTHING) else 1.0)
    icy_flat = (0.005 if grace else 0.01) * mana_max if has(TALENT_ICY_QUIVER) else 0.0
    neptulon_crit = (10.0 + 0.20 * intel) if has(TALENT_NEPTULON) else 0.0
    core_gain = 3.0 + (1.0 if has(TALENT_LIQUID_FUEL) else 0.0)
    la_cost = 0.0 if has(TALENT_VIPER) else 1.0 + 1.0 * RANK  # Viper Sting drains the target instead

    sources: dict[str, float] = {"Автоатака": 0.0}
    actions: list[tuple[float, str]] = []
    counters = {"tidal": 0, "la": 0, "wave": 0, "elementals": 0, "snake": 0}
    mana = mana_max
    mana_time = 0.0
    sulfuras = Sulfuras() if _wears(build, "I0BR") else None
    cast_time = CAST_POINT + CAST_BACKSWING

    chill_until = [-1.0] * targets
    snake_until = [-1.0] * targets
    armed = False  # B05F
    fletcher_until = -1.0  # B058
    song_until = -1.0  # B04R on the Siren
    mirror_song_until = -1.0  # B08S on the Siren
    elementals: list[dict] = []
    mirror: dict | None = None
    pending: list[tuple[float, int, str, float]] = []
    seq = 0
    la_count = 0
    wave_roll = _Dither()
    bow_roll = _Dither()
    snake_roll = _Dither()
    tick_next = 1.0  # ASSUMPTION: 1 s periodic (Siren_Periodic / Mana_Regen) ticks at whole seconds

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
        if refund and cost > 0:
            gain_mana(cast_mana_back(cost, stats))
        return True

    def note_damage_mana(count: float) -> None:
        if stats["damage_mana_pct"]:
            gain_mana(stats["damage_mana_pct"] * mana_max * count)

    def typed(magical: bool, now: float) -> float:
        bonus = 1.0 + (stats["magic_add"] if magical else stats["phys_add"])
        if stats["sulfuron"]:
            bonus += 0.13 + 0.25 * target_hp(now)
        if magical and stats["spellbinder"]:
            bonus += 0.05 + 0.005 * mastery
        if stats["glass"]:
            bonus *= 1.15
        return bonus

    def dcs() -> float:
        return WHITE_BASE + 0.75 * agi + stats["damage"]

    def taken(hero: bool, t: int, now: float) -> float:
        armor = DUMMY_ARMOR
        if snake_until[t] > now:
            armor -= 2.0  # A0GU faerie fire from Snake Bite
        if hero:
            armor -= pen
        return armor_taken(armor)

    def icy(t: int, now: float) -> float:
        return icy_flat if chill_until[t] > now else 0.0

    def hero_hit(name: str, raw: float, now: float, tgts: list[int], *, magical: bool, attack: bool,
                 weight: float = 1.0, potency_scale: float = 1.0) -> float:
        if weight <= 0 or not tgts:
            return 0.0
        chance = crit_stat
        rating = stats["rating"]
        if attack and has(TALENT_CORAL) and fletcher_until > now:
            chance += 10.0
            rating += 0.18
        total = 0.0
        execute = _execute_factor(stats, now)
        kind = typed(magical, now)
        for t in tgts:
            amount = raw + icy(t, now) + stats["potency"] * potency_scale
            amount *= kind
            if attack:
                amount *= _crit_factor(chance, 2.0 + rating)
            elif stats["spell_crit"]:
                amount *= _crit_factor(chance, stats["spell_mult"] + rating)
            total += amount * taken(True, t, now) * execute
        sources[name] = sources.get(name, 0.0) + total * weight
        note_damage_mana(len(tgts) * weight)
        return total

    def summon_hit(name: str, raw: float, now: float, t: int, *, attack: bool, extra_crit: float = 0.0,
                   increase: float = 0.0, weight: float = 1.0) -> float:
        """Damage by an owner unit: potency, Pet Damage, summon crit, Icy Quiver flat, armor."""
        amount = raw + icy(t, now) + stats["potency"]
        amount *= 1.0 + stats["pet_damage"]
        amount *= 1.0 + increase
        if attack:
            amount *= _crit_factor(stats["summon_crit"] + extra_crit, 2.0 + stats["summon_rating"])
        dealt = amount * taken(False, t, now) * _execute_factor(stats, now) * weight
        sources[name] = sources.get(name, 0.0) + dealt
        return dealt

    def liquid_arrows(now: float, t: int, from_elemental: bool) -> None:
        nonlocal mana
        cost = la_cost * (0.40 if from_elemental else 1.0)
        if cost > 0:
            recover(now)
            if mana < cost:
                return
            mana -= cost
        if has(TALENT_ICY_QUIVER) and fletcher_until > now:
            chill_until[t] = max(chill_until[t], now + CHILL_DUR)  # Chill -> frostnova A00H (Bfro)
        counters["la"] += 1
        if grace:
            return  # Seagrace: Liquid Arrows heal instead of dealing damage
        raw = (10.0 + 10.0 * RANK) + 0.40 * agi + 0.40 * intel
        if fletcher_until > now:
            raw *= 1.0 + ((0.40 if has(TALENT_SEAFLURRY) else 0.10) + 0.05 * RANK)
        if from_elemental:
            raw *= 0.40
        hero_hit("Liquid Arrows", raw, now, [t], magical=True, attack=False)

    def siren_attack(now: float, raw: float, name: str, potency_scale: float = 1.0) -> None:
        """A Siren attack (her own swing or the Mirror Image pierce hit): PreDamage_Heroes procs."""
        nonlocal armed
        t = 0
        if use_la:
            liquid_arrows(now, t, False)
        hero_hit(name, raw, now, [t], magical=False, attack=True, potency_scale=potency_scale)
        if armed:
            armed = False
            push(now + TIDAL_DELAY, "tidal", 0.0)
            if sharp and mirror is not None and mirror["end"] > now:
                push(now + TIDAL_DELAY, "tidal", 1.0)  # image copy x0.30 x Reflection_Bonus
        elif stats["bow"] and bow_roll.roll(_chance(0.10 * luck_mult)):
            push(now + TIDAL_DELAY, "tidal", 0.0)
        if has(TALENT_SNAKE_BITE) and snake_roll.roll(_chance(0.25 * luck_mult)):
            counters["snake"] += 1
            snake_until[t] = now + 4.0
            # Dummy n03G deals it: Pet Damage applies, no crit / procs.
            summon_hit("Snake Bite", 30.0 + 0.50 * agi + 1.50 * dcs(), now, t, attack=False)

    def spawn_elemental(now: float, life: float, waterlord: bool) -> None:
        counters["elementals"] += 1
        raw = 11.0 + 1.0 + int(0.15 * dcs())  # ua1b 11 + 1d1 + R2I(0.15 DCS)
        cap = ELEMENTAL_MANA_MAX + (5.0 + mastery if shaper else 0.0) + (25.0 if stats["vest"] else 0.0)
        start = ELEMENTAL_START_MANA + (15.0 if stats["vest"] else 0.0)
        elementals.append({
            "next": now, "end": now + life, "raw": raw, "mana": min(cap, start), "cap": cap,
            "swing": 1.0 if waterlord else ELEMENTAL_SWING, "hits": 3 if waterlord else 2,
            "song": -1.0, "msong": -1.0,
        })

    def tidal_shot(now: float, copy: bool) -> None:
        nonlocal fletcher_until
        counters["tidal"] += 1
        recover(now)
        raw = 80.0 * RANK + 2.0 * agi
        if has(TALENT_EMPOWERED):
            raw += 0.40 * mana
        if sharp:
            raw *= 1.0 + (0.10 + 0.01 * mastery)
        if copy:
            raw *= 0.30 * reflection
        live = [e for e in elementals if e["end"] > now]
        if has(TALENT_CONJURE) and len(live) < 3:
            spawn_elemental(now, (ELEMENTAL_LIFE + (4.0 if has(TALENT_LIQUID_FUEL) else 0.0)) / 2.0, False)
            live = [e for e in elementals if e["end"] > now]
        if has(TALENT_ELEMENTAL_SHOT) and live:
            # Kills a random elemental. ASSUMPTION: the one with the least time left.
            victim = min(live, key=lambda e: e["end"])
            victim["end"] = now
            raw *= 1.35
        hero_hit("Tidal Shot", raw, now, [0], magical=True, attack=False)
        fletcher_until = now + fletcher_dur
        if sharp and wave_roll.roll(_chance(0.25 * luck_mult)):
            counters["wave"] += 1
            # ASSUMPTION: the clustered pack is on the wave's line, every target is hit.
            hero_hit("Crushing Wave", 0.40 * raw, now, list(range(targets)), magical=True, attack=False)

    def elemental_hit(now: float, e: dict) -> None:
        nonlocal la_count
        crit_chance = stats["summon_crit"] + neptulon_crit
        share = max(0.0, min(100.0, crit_chance)) / 100.0
        n = min(e["hits"], targets)
        for k in range(n):
            # Water Core: +0.5% damage per current mana (before the +3 mana of this hit).
            summon_hit("Sea Elemental", e["raw"] * BOUNCE_KEEP ** k, now, k, attack=True,
                       extra_crit=neptulon_crit, increase=0.005 * e["mana"])
            gain = core_gain * (1.0 + share if has(TALENT_NEPTULON) else 1.0)
            e["mana"] = min(e["cap"], e["mana"] + gain)
            # ASSUMPTION: bounce hits count as elemental attacks (Water Core and the LA counter).
            if use_la:
                la_count += 1
                if la_count >= 3:
                    la_count = 0
                    liquid_arrows(now, k, True)

    def attack_interval(now: float) -> float:
        swing = SWING * (1.20 if stats["galactic"] else 1.0)
        if has(TALENT_STRING) and fletcher_until > now:
            swing *= 0.88  # AS_Base_Reduction
        speed = stats["attack_speed"]
        if song_until > now:
            speed += song_as
        if mirror_song_until > now:
            speed += mirror_song_as * song_as
        speed = min(4.0, max(-0.8, speed))
        return swing / (1.0 + speed)

    fixed_cd = {"mirror": MIRROR_CD, "elemental": ELEMENTAL_CD, "tidal": TIDAL_CD, "song": SONG_CD,
                "gaze": GAZE_CD}
    cost = {"mirror": MIRROR_MANA, "elemental": ELEMENTAL_MANA, "tidal": TIDAL_MANA, "song": SONG_MANA,
            "gaze": GAZE_MANA}
    names = {"mirror": "Mirror Image", "elemental": "Sea Elemental", "tidal": "Tidal Shot",
             "song": "Song of the Siren", "gaze": "Stone Gaze"}
    order = ["mirror", "elemental", "tidal"] + (["song"] if use_song else []) + ["gaze"]
    nxt = {key: 0.0 for key in order}

    next_attack = 0.0
    busy = 0.0
    loops = 0
    clock = 0.0
    while True:
        loops += 1
        if loops > 400000:
            break
        attack_at = max(next_attack, busy, clock)
        cast_at = FIGHT * 10
        choice = None
        for key in order:
            if key == "tidal" and armed:
                continue
            ready = max(nxt[key], busy, clock)
            if ready < cast_at - 1e-9:
                cast_at, choice = ready, key
        pending_at = min((p[0] for p in pending), default=FIGHT * 10)
        elementals[:] = [e for e in elementals if e["end"] > clock - 1e-9]
        unit_at = min((e["next"] for e in elementals if e["next"] < e["end"]), default=FIGHT * 10)
        mirror_at = mirror["next"] if mirror is not None and mirror["next"] < mirror["end"] else FIGHT * 10
        moment = min(attack_at, cast_at, pending_at, unit_at, mirror_at, tick_next)
        if moment >= FIGHT:
            break
        clock = moment

        if moment == pending_at:
            event = min(pending)
            pending.remove(event)
            _, _, kind, arg = event
            if kind == "tidal":
                tidal_shot(moment, arg > 0)
            continue

        if moment == tick_next:
            # Song mana: Siren via Mana_Regen, elementals via Siren_Periodic (1 s).
            if song_until > moment:
                gain_mana(song_mana)
            if mirror_song_until > moment:
                gain_mana(mirror_song_as * song_mana)
            for e in elementals:
                add = (song_mana if e["song"] > moment else 0.0)
                add += (0.50 * reflection * song_mana if e["msong"] > moment else 0.0)
                e["mana"] = min(e["cap"], e["mana"] + add)
            tick_next = moment + 1.0
            continue

        if moment == unit_at and unit_at < attack_at and unit_at < cast_at:
            e = min((u for u in elementals if u["next"] < u["end"]), key=lambda u: u["next"])
            elemental_hit(moment, e)
            e["next"] = moment + e["swing"]
            continue

        if moment == mirror_at and mirror_at < attack_at and mirror_at < cast_at:
            raw = int(0.5 * dcs()) + 1.0  # e00M base R2I(0.5 DCS) + 1d1 (ASSUMPTION: dice 1d1)
            summon_hit("Mirror Image", raw, moment, 0, attack=True)
            siren_attack(moment, 0.5 * dcs(), "Mirror Image (Siren)")
            mirror["next"] = moment + MIRROR_SWING
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
            flat = 0.0
            image = mirror is not None and mirror["end"] > hit_at
            if key == "mirror":
                life = MIRROR_LIFE + (3.0 if has(TALENT_REFLECTION) else 0.0)
                mirror = {"next": hit_at, "end": hit_at + life}
            elif key == "elemental":
                life = ELEMENTAL_LIFE + (4.0 if has(TALENT_LIQUID_FUEL) else 0.0)
                for i in range(2 if shaper else 1):
                    spawn_elemental(hit_at, life, has(TALENT_WATERLORD) and i == 0)
                if shaper and image:
                    for _ in range(2):
                        spawn_elemental(hit_at, life * 0.40 * reflection, False)
            elif key == "tidal":
                armed = True
            elif key == "song":
                song_until = hit_at + song_dur
                for e in elementals:
                    if e["end"] > hit_at:
                        e["song"] = hit_at + song_dur  # ASSUMPTION: elementals stand within 600
                if grace and image:
                    mirror_song_until = hit_at + song_dur
                    for e in elementals:
                        if e["end"] > hit_at:
                            e["msong"] = hit_at + song_dur
            elif key == "gaze":
                if has(TALENT_GORGON):
                    flat = 3.0
                raw = 90.0 + 1.45 * agi + 2.40 * intel
                # ASSUMPTION: the pack stands in the 600-range cone, every target is hit.
                hero_hit("Stone Gaze", raw, hit_at, list(range(targets)), magical=True, attack=False)
            cd = _cooldown(fixed_cd[key], stats["haste"], stats, flat)
            nxt[key] = moment + cd
            next_attack = max(next_attack, busy)
            continue

        # Siren auto-attack (pierce, physical).
        moment = attack_at
        recover(moment)
        power = dcs()
        before = sources["Автоатака"]
        siren_attack(moment, power, "Автоатака", stats["attack_potency"])
        if stats["auto_pct"] != 1.0:
            sources["Автоатака"] = before + (sources["Автоатака"] - before) * stats["auto_pct"]
        gain_mana(attack_mana_gain(stats))
        if stats["fire_orb"]:
            splash = (20.0 + 0.35 * agi) * targets * taken(True, 0, moment) * _execute_factor(stats, moment)
            sources["Всплеск огня"] = sources.get("Всплеск огня", 0.0) + splash
            note_damage_mana(targets)
        if sulfuras is not None:
            execute = _execute_factor(stats, moment)
            if sulfuras.attack():
                splash = agi * typed(True, moment) * taken(True, 0, moment) * execute * targets
                splash *= _crit_factor(crit_stat, 2.0 + stats["rating"])
                sources["Sulfuras"] = sources.get("Sulfuras", 0.0) + splash
                note_damage_mana(targets)
            echo = power * taken(True, 0, moment) * execute * sulfuras_echo_chance(stats["luck"])
            sources["Sulfuras (удар)"] = sources.get("Sulfuras (удар)", 0.0) + echo
        next_attack = moment + attack_interval(moment)

    total = sum(sources.values())
    recover(FIGHT)
    mana_left = 0.0 if mana_max <= 0 else 100.0 * mana / mana_max
    stats = dict(stats)
    stats.update({f"n_{k}": float(v) for k, v in counters.items()})
    stats["policy_la"] = 1.0 if use_la else 0.0
    stats["policy_song"] = 1.0 if use_song else 0.0
    return Report(build, total / FIGHT, total, sources, actions, stats, targets, mana_left=mana_left)


def best_points(build: Build, targets: int, spec: str) -> tuple[float, tuple[int, int, int, int]]:
    return simulate(build, targets, spec).dps, (0, 0, 0, 0)
