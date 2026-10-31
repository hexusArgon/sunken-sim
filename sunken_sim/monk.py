"""Monk fight for Sunken City v2.5.2a, level 6.

Unit N04R. Strength 24 + 2.4, agility 13 + 1.3, intellect 13 + 1.3 (36 / 19 / 19 at
level 6). White hit 13 + 1d1 = 14, plus 0.75 x STR (DCS formula). Attack cooldown
1.85, melee, attack type SIEGE. Primary STR. Ability rank is 1.
Spec level on A040 (udg_Glyphs_Unit[2]): 1 Windwalker, 2 Brewmaster, 3 Mistweaver.
Talents sit on udg_Talents_Unit[2].

Spells (all 6 s, 12 mana): Power Strike A0JS, Fortifying Brew A0IL, Renewing Mist A0F7,
Celestial Wrath A0OM (Xuen, WW) / A0R7 (Niuzao, Brew) / A0R6 (Yu'lon, MW).
Global_CDs: every cast puts the other Monk spells on (1.5, 1.0 with I0KZ) / (1 + CDR).
Celestial Stance: 2 empowered attacks (3 with I0KW), +40% attack speed while a stance
is up. Healing, Stagger, taunts and stuns are not scored.
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

BASE_STR = int(24 + (LEVEL - 1) * 2.4)
BASE_AGI = int(13 + (LEVEL - 1) * 1.3)
BASE_INT = int(13 + (LEVEL - 1) * 1.3)
WHITE_BASE = 14.0  # N04R ua1b 13 + 1d1
SWING = 1.85  # N04R ua1c
BASE_MANA = 120.0
BASE_HP = 300.0

SPECS = ("windwalker", "brewmaster", "mistweaver")
HERO_CLASS = "Monk"
RANK = 1

TALENT_AVATAR_XUEN = "I0U6"
TALENT_AVATAR_NIUZAO = "I0PP"
TALENT_AVATAR_YULON = "I0U7"
TALENT_AVATAR_CHIJI = "I0U8"
TALENT_MARTIAL_ARTIST = "I0KW"
TALENT_EXPEL_HARM = "I0L2"
TALENT_FISTS_OF_FURY = "I0KX"
TALENT_WAY_OF_THE_TIGER = "I0HX"
TALENT_INNER_HARMONY = "I0L0"
TALENT_NEXT_PAGE = "I0MD"
TALENT_LEGACY = "I0KZ"
TALENT_COMING_OF_YULON = "I0PN"
TALENT_FRENZIED_ASSAULT = "I0PQ"
TALENT_JAB = "I0PO"
TALENT_DRUNKEN_HAZE = "I0L1"
TALENT_SHADO_PAN = "I09U"
TALENT_RISING_MIST = "I04Y"
TALENT_TIGEREYE_BREW = "I0KY"
TALENT_FLURRY = "I0PR"
TALENT_PREV_PAGE = "I0MC"

TALENTS = {
    TALENT_AVATAR_XUEN: "Avatar of Xuen",
    TALENT_AVATAR_NIUZAO: "Avatar of Niuzao",
    TALENT_AVATAR_YULON: "Avatar of Yu'lon",
    TALENT_AVATAR_CHIJI: "Avatar of Chi'Ji",
    TALENT_MARTIAL_ARTIST: "Martial Artist",
    TALENT_EXPEL_HARM: "Expel Harm",
    TALENT_FISTS_OF_FURY: "Fists of Fury",
    TALENT_WAY_OF_THE_TIGER: "Way of the Tiger",
    TALENT_INNER_HARMONY: "Inner Harmony",
    TALENT_LEGACY: "Legacy of the Emperor",
    TALENT_COMING_OF_YULON: "Coming of Yu'lon",
    TALENT_FRENZIED_ASSAULT: "Frenzied Assault",
    TALENT_JAB: "Jab",
    TALENT_DRUNKEN_HAZE: "Drunken Haze",
    TALENT_SHADO_PAN: "Shado-Pan Teachings",
    TALENT_RISING_MIST: "Rising Mist",
    TALENT_TIGEREYE_BREW: "Tigereye Brew",
    TALENT_FLURRY: "Flurry Strikes",
}

# Pages are UI. The rest only heal, mitigate, slow or need Stagger / evasion (a dummy
# deals no damage, so Stagger and evasion stay at zero).
IGNORED_TALENTS = frozenset(
    {
        TALENT_NEXT_PAGE,
        TALENT_PREV_PAGE,
        TALENT_AVATAR_YULON,  # PS: Renewing Mist ticks (heal); FB: healing brew
        TALENT_EXPEL_HARM,  # Renewing Mist health scaling, Stagger clear, cleanse
        TALENT_COMING_OF_YULON,  # Renewing Mist casts Wrath of Yu'lon at 50% healing
        TALENT_DRUNKEN_HAZE,  # slow + ally evasion
        TALENT_SHADO_PAN,  # PS + 18% of Stagger; Stagger is 0 against a dummy
        TALENT_RISING_MIST,  # Renewing Mist heal crit
        TALENT_TIGEREYE_BREW,  # counterattack on evasion
    }
)

SPELL_CD = 6.0  # A0JS / A0IL / A0F7 / A0OM / A0R7 / A0R6 acdn L1
SPELL_MANA = 12.0  # amcs L1
PS_BUFF = 4.0  # A0JS adur, buff B02D
WRATH_XUEN_BUFF = 3.0  # A0ON adur, buff B07B
BLESSING = 6.0  # A0FF (B08G) / A0L2 (B091)
BLESSING_XUEN_AS = 0.40  # Attack_Speed_Tooltip: B08G +0.40
BLESSING_YULON_CDR = 0.18  # CDR_Buffs: B091 0.18
STANCE_AS = 0.40  # Attack_Speed_Tooltip: CelestialStance_Current != 0
WW_PROC_DELAY = 0.50  # WindwalkerSpec_Timer
CHIJI_CW_CUT = 0.30  # I0UC: CD_Dynamic_Reduction per crit, seconds

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
ITEM_SCEPTER_NIUZAO = "I0U9"  # FB heals from Stagger: not scored
ITEM_XUENS_GAZE = "I0UA"  # Power Strike triggers White Tiger
ITEM_WARSTAFF_CHIJI = "I0UC"  # crits cut Celestial Wrath cooldown by 0.3 s
ITEM_MISTWEAVERS_BLOOM = "I0UB"  # Renewing Mist duration / heal: not scored
ITEM_SHOULDERPADS = "I0UD"  # Renewing Mist instant heal: not scored

XUEN, CHIJI, NIUZAO, YULON = "xuen", "chiji", "niuzao", "yulon"
DAMAGE_STANCES = (XUEN, CHIJI)


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
            for raw in re.findall(r"\+(\d+) Health\b", item.tip):
                health_flat += int(raw)
    if _has(build, TALENT_INNER_HARMONY):
        # A0EI (Aamk) level 1: +5 STR / AGI / INT.
        strength += 5
        agility += 5
        intel += 5
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
    if _has(build, TALENT_FRENZIED_ASSAULT):
        # Attack_Speed_Tooltip: +0.10 + 0.01 x Mastery (integer stat).
        attack_speed += 0.10 + 0.01 * int(mastery)
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
    # Inner Harmony: DamageIncrease + (0.05 / 25) x lowest attribute (PreDamage_Increase).
    increase = 0.0
    if _has(build, TALENT_INNER_HARMONY):
        increase = (0.05 / 25.0) * min(int(strength), int(agility), int(intel))
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
        "increase": increase,
        "glass": 1.0 if _has(build, GLYPH_GLASS) or GLYPH_GLASS in codes else 0.0,
        "spellbinder": 1.0 if SPELLBINDER in codes else 0.0,
        "sulfuron": 1.0 if SULFURON_GLOVES in codes else 0.0,
        "galactic": 1.0 if GALACTIC_FURY in codes else 0.0,
        "fire_orb": 1.0 if FIRE_ORB in codes else 0.0,
        "xuens_gaze": 1.0 if ITEM_XUENS_GAZE in codes else 0.0,
        "warstaff": 1.0 if ITEM_WARSTAFF_CHIJI in codes else 0.0,
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


# (hold, plain_mist, brew_first). hold: "all" keeps every cast while Xuen / Chi'Ji
# stance still has empowered attacks ("all1.4" / "all0.7": at most 1.4 / 0.7 s past
# the cooldown), "spent2" waits only until two empowered attacks are spent, "filler" keeps only Brew and Mist, "none" never waits. plain_mist: cast Renewing Mist without a damage avatar (it only swaps the
# stance then). brew_first: Celestial Wrath waits for Brew when Avatar of Xuen is up.
POLICIES = tuple(
    (hold, plain_mist, brew_first)
    for hold in ("all", "all1.4", "all0.7", "spent2", "filler", "none")
    for plain_mist in (True, False)
    for brew_first in (True, False)
)


def simulate(build: Build, targets: int = 5, spec: str = "windwalker") -> Report:
    """Best of the rotation policies (hold casts in damage stances, Brew before Wrath on Avatar of Xuen)."""
    best = None
    for policy in POLICIES:
        report = _simulate(build, targets, spec, policy)
        if best is None or report.dps > best.dps + 1e-9:
            best = report
    return best


def _simulate(build: Build, targets: int, spec: str, policy: tuple[str, bool, bool]) -> Report:
    hold, plain_mist, brew_first = policy
    if spec not in SPECS:
        raise ValueError(spec)
    if targets < 1:
        raise ValueError(targets)
    stats = stats_of(build)
    luck_mult = 1.0 + stats["luck"]
    has = lambda code: _has(build, code)  # noqa: E731
    ww = spec == "windwalker"
    strength = int(stats["str"])
    agility = int(stats["agi"])
    mastery = int(stats["mastery"])
    taken = armor_taken(DUMMY_ARMOR - stats["armor_pen"])

    sources: dict[str, float] = {
        "Автоатака": 0.0,
        "Fortifying Brew (удар)": 0.0,
        "Power Strike": 0.0,
        "Power Strike (WW-повтор)": 0.0,
        "Celestial Attack (Xuen)": 0.0,
        "White Tiger": 0.0,
        "Wrath of Xuen": 0.0,
        "Всплеск огня": 0.0,
    }
    actions: list[tuple[float, str]] = []
    mana = stats["mana_max"]
    mana_time = 0.0
    sulfuras = Sulfuras() if _wears(build, "I0BR") else None
    cast_time = CAST_POINT + CAST_BACKSWING

    stance = ""
    emp = 0
    jab = 0
    ps_buff_until = -1.0
    fb_attack = False
    avatar = ""  # Avatar_Current
    ps_avatar = ""  # PowerStrike_Avatar
    wrath_until = -1.0
    fof = 0.0
    blessing_xuen_until = -1.0
    blessing_yulon_until = -1.0
    pending: list[tuple[float, float]] = []  # Windwalker Power Strike echoes (time, chance)

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

    def haste_at(now: float) -> float:
        return stats["haste"] + (BLESSING_YULON_CDR if now < blessing_yulon_until else 0.0)

    def typed(magical: bool, now: float) -> float:
        bonus = 1.0 + (stats["magic_add"] if magical else stats["phys_add"])
        if stats["sulfuron"]:
            bonus += 0.13 + 0.25 * target_hp(now)
        if magical and stats["spellbinder"]:
            bonus += 0.05 + 0.005 * stats["mastery"]
        if stats["glass"]:
            bonus *= 1.15
        return bonus * (1.0 + stats["increase"])

    def cut_wrath(crits: float, now: float) -> None:
        if stats["warstaff"] and crits > 0 and nxt["cw"] > now:
            nxt["cw"] = max(now, nxt["cw"] - CHIJI_CW_CUT * crits)

    def magic(name: str, raw: float, now: float, count: float = 1.0) -> float:
        """Magical spell damage from the Monk (NextDamageType magical). Returns dealt per hit."""
        nonlocal fof
        amount = (raw + stats["potency"]) * typed(True, now)
        crits = 0.0
        if stats["spell_crit"]:
            amount *= _crit_factor(stats["crit"], stats["spell_mult"] + stats["rating"])
            crits = _chance(stats["crit"] / 100.0) * count
        dealt = amount * taken * _execute_factor(stats, now)
        sources[name] = sources.get(name, 0.0) + dealt * count
        note_damage_mana(count)
        if has(TALENT_FISTS_OF_FURY):
            fof = min(50.0 * LEVEL, fof + 0.10 * dealt * count)
        cut_wrath(crits, now)
        return dealt

    def attack_hit(name: str, raw: float, now: float, *, red_crane: bool, potency_scale: float) -> float:
        """Physical attack through PreDamage_Increase: FoF add, crit, Red Crane."""
        nonlocal fof
        amount = raw + stats["potency"] * potency_scale
        if fof > 0:
            amount += fof
            fof = 0.0
        amount *= typed(False, now)
        chance = stats["crit"]
        rating = 2.0 + stats["rating"]
        if red_crane:
            amount *= (1.0 + chance / 100.0) * rating
            crits = 1.0
        else:
            amount *= _crit_factor(chance, rating)
            crits = _chance(chance / 100.0)
        dealt = amount * taken * _execute_factor(stats, now)
        sources[name] = sources.get(name, 0.0) + dealt
        note_damage_mana(1)
        cut_wrath(crits, now)
        return dealt

    def ps_damage() -> float:
        value = (60.0 * RANK + 10.0 + 1.0 * strength) * (1.0 + 0.005 * agility)
        if ww:
            value *= 1.05 + 0.008 * mastery
        return value

    def white_tiger(amount: float, now: float) -> None:
        magic("White Tiger", 2.0 * amount, now, count=targets)

    def power_strike(now: float, proc: bool, weight: float = 1.0) -> None:
        nonlocal ps_avatar
        damage = ps_damage()
        if proc:
            damage *= 0.50
        elif ww:
            pending.append((now + WW_PROC_DELAY, _chance(0.40 * luck_mult)))
        if ps_avatar == CHIJI and not proc:
            ps_avatar = ""
            white_tiger(0.15 * damage, now)
            damage *= 1.40
        if proc:
            magic("Power Strike (WW-повтор)", damage, now, count=weight)
        else:
            magic("Power Strike", damage, now)
        if not proc and ps_avatar in (NIUZAO, YULON):
            ps_avatar = ""  # stun / heal only
        if stats["xuens_gaze"] and not proc:
            white_tiger(0.15 * damage, now)

    def spend_emp(now: float) -> None:
        nonlocal emp, stance, jab
        emp -= 1
        if emp <= 0:
            emp = 0
            stance = ""
        if has(TALENT_JAB):
            jab += 1
            if jab == 5:
                jab = 0
                power_strike(now, False)

    def emp_max() -> int:
        return 3 if has(TALENT_MARTIAL_ARTIST) else 2

    def set_stance(value: str) -> None:
        nonlocal stance, emp
        stance = value
        emp = 3 if has(TALENT_MARTIAL_ARTIST) else 2

    def celestial(now: float, code: bool) -> None:
        """PreDamage_Heroes Func028: Xuen stance / Windwalker celestial attacks."""
        if not (stance == XUEN or ww):
            return
        amount = 0.15 * ps_damage()
        if stance == XUEN and not code:
            spend_emp(now)
            white_tiger(amount, now)
        elif ww:
            magic("Celestial Attack (Xuen)", amount, now)
        if has(TALENT_FLURRY) and ww:
            magic("Celestial Attack (Xuen)", amount, now, count=_chance(0.40 * luck_mult))

    def wrath_of_xuen(dealt: float, now: float) -> None:
        nonlocal wrath_until
        if now < wrath_until:
            wrath_until = -1.0
            magic("Wrath of Xuen", 20.0 + 1.0 * strength + 0.50 * dealt, now, count=targets)

    def dcs() -> float:
        return WHITE_BASE + 0.75 * strength + stats["damage"]

    def interval(now: float) -> float:
        swing = SWING * (1.20 if stats["galactic"] else 1.0)
        speed = stats["attack_speed"]
        if stance:
            speed += STANCE_AS
        if now < blessing_xuen_until:
            speed += BLESSING_XUEN_AS
        speed = min(4.0, max(-0.8, speed))
        return swing / (1.0 + speed)

    def gcd(now: float) -> float:
        return (1.0 if has(TALENT_LEGACY) else 1.5) / (1.0 + haste_at(now))

    nxt = {"ps": 0.0, "cw": 0.0, "fb": 0.0, "rm": 0.0}
    order = ("ps", "cw", "fb", "rm")
    names = {"ps": "Power Strike", "cw": "Celestial Wrath", "fb": "Fortifying Brew", "rm": "Renewing Mist"}

    def allowed(key: str, now: float) -> bool:
        # Do not overwrite a damage stance that still has empowered attacks.
        if stance in DAMAGE_STANCES and emp > 0:
            if hold == "spent2":
                if emp_max() - emp < 2:
                    return False
            elif hold == "filler":
                if key in ("fb", "rm"):
                    return False
            elif hold.startswith("all"):
                limit = float(hold[3:]) if len(hold) > 3 else FIGHT
                if now - nxt[key] < limit:
                    return False
        if key == "rm" and not plain_mist and avatar not in (XUEN, CHIJI):
            return False
        if brew_first and key == "cw" and avatar == XUEN and nxt["fb"] <= now + gcd(now) + cast_time:
            return False  # Celestial Wrath would reset Avatar of Xuen before Fortifying Brew
        if key == "ps" and now < ps_buff_until:
            return False
        if key in ("fb", "rm") and avatar == CHIJI:
            return False  # keep Avatar of Chi'Ji for Power Strike (x1.40 + White Tiger)
        if key == "rm" and avatar == XUEN and nxt["fb"] <= now + gcd(now) + cast_time:
            return False  # Fortifying Brew spends Avatar of Xuen better (two White Tigers)
        return True

    next_attack = 0.0
    busy = 0.0
    guard = 0
    clock = 0.0
    while True:
        guard += 1
        if guard > 400000:
            break
        attack_at = max(next_attack, busy, clock)
        cast_at = FIGHT * 10
        choice = None
        for key in order:
            ready = max(nxt[key], busy, clock)
            if ready < cast_at - 1e-9 and allowed(key, ready):
                cast_at, choice = ready, key
        pending_at = min((when for when, _ in pending), default=FIGHT * 10)
        moment = min(attack_at, cast_at, pending_at)
        if moment >= FIGHT:
            break
        clock = moment
        if moment == pending_at:
            echo = min(pending)
            pending.remove(echo)
            power_strike(moment, True, echo[1])
            continue
        if cast_at <= attack_at and choice is not None and moment == cast_at:
            key = choice
            if not pay(SPELL_MANA, moment):
                nxt[key] = moment + 0.25
                continue
            hit_at = moment + CAST_POINT
            actions.append((moment, names[key]))
            busy = moment + cast_time + stats["cast_stun_lock"]
            if sulfuras is not None:
                sulfuras.cast()
            if key == "ps":
                if avatar:
                    ps_avatar = avatar
                    avatar = ""
                if has(TALENT_AVATAR_XUEN):
                    ps_avatar = ""
                    avatar = XUEN
                if has(TALENT_WAY_OF_THE_TIGER):
                    set_stance({"windwalker": CHIJI, "brewmaster": NIUZAO, "mistweaver": YULON}[spec])
                else:
                    set_stance(XUEN)
                ps_buff_until = hit_at + PS_BUFF
            elif key == "cw":
                avatar = ""
                if spec == "windwalker":
                    wrath_until = hit_at + WRATH_XUEN_BUFF
                if has(TALENT_AVATAR_CHIJI):
                    ps_avatar = ""
                    avatar = CHIJI
                set_stance(CHIJI)
            elif key == "fb":
                fb_attack = True
                if avatar == XUEN:
                    avatar = ""
                    amount = 0.15 * ps_damage()
                    white_tiger(amount, hit_at)
                    white_tiger(amount, hit_at)
                elif avatar:
                    avatar = ""  # Niuzao: nothing; Yu'lon: heal; Chi'Ji: armor (A0EP)
                if has(TALENT_AVATAR_NIUZAO):
                    ps_avatar = ""
                    avatar = NIUZAO
                set_stance(NIUZAO)
            elif key == "rm":
                if avatar == XUEN:
                    blessing_xuen_until = hit_at + BLESSING
                elif avatar == CHIJI:
                    blessing_yulon_until = hit_at + BLESSING
                avatar = ""
                set_stance(YULON)
            nxt[key] = moment + _cooldown(SPELL_CD, haste_at(moment), stats)
            spread = moment + gcd(moment)
            for other in order:
                if other != key and nxt[other] < spread:
                    nxt[other] = spread
            next_attack = max(next_attack, busy)
            continue

        # Monk auto-attack.
        moment = attack_at
        recover(moment)
        power = dcs()
        # PreDamage_Heroes Func024: Power Strike on the next attack under B02D.
        if moment < ps_buff_until:
            ps_buff_until = -1.0
            power_strike(moment, False)
        # Func026: Fortifying Brew extra attack (code attack, SIEGE).
        if fb_attack:
            fb_attack = False
            fb_dealt = attack_hit("Fortifying Brew (удар)", 25.0 * RANK + 0.50 * power, moment, red_crane=False, potency_scale=1.0)
            celestial(moment, code=True)
            wrath_of_xuen(fb_dealt, moment)
        # Func028 / 030 / 032 on the real attack.
        # Event 1 (PreDamage_Heroes) runs before PreDamage_Increase (Red Crane).
        celestial(moment, code=False)
        if stance in (NIUZAO, YULON):
            spend_emp(moment)
        red_crane = False
        if stance == CHIJI:
            red_crane = True
            spend_emp(moment)
        before = sources["Автоатака"]
        dealt = attack_hit("Автоатака", power, moment, red_crane=red_crane, potency_scale=stats["attack_potency"])
        if stats["auto_pct"] != 1.0:
            sources["Автоатака"] = before + (sources["Автоатака"] - before) * stats["auto_pct"]
        wrath_of_xuen(dealt, moment)
        gain_mana(attack_mana_gain(stats))
        if stats["fire_orb"]:
            splash = (20.0 + 0.35 * stats["str"]) * targets * taken * _execute_factor(stats, moment)
            sources["Всплеск огня"] += splash
            note_damage_mana(targets)
        if sulfuras is not None:
            execute = _execute_factor(stats, moment)
            if sulfuras.attack():
                splash = stats["str"] * typed(True, moment) * taken * execute * targets
                splash *= _crit_factor(stats["crit"], 2.0 + stats["rating"])
                sources["Sulfuras"] = sources.get("Sulfuras", 0.0) + splash
                note_damage_mana(targets)
            echo = power * taken * execute * sulfuras_echo_chance(stats["luck"])
            sources["Sulfuras (удар)"] = sources.get("Sulfuras (удар)", 0.0) + echo
        next_attack = moment + interval(moment)

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


