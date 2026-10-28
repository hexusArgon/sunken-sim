"""Death Knight fight for Sunken City v2.5.2a, level 6.

Numbers are the map's. Hero U002 (parent Udea): strength 28 + 2.8 per level,
agility 9 + 0.9, intellect 13 + 1.3, attack cooldown 2.0, white damage 11 + 1 die
(DCS_Config: base 11, 1d1, primary STR), armor 3, 310 health, 120 mana.
Ability rank is 1. Specialization is A0I0 level: 1 Frost, 2 Blood, 3 Unholy
(Unholy swaps Empower Rune Weapon A085 for Plaguebearer A038).

All DK spells set NextDamageType = Magical, so they go through the magical
branch of PreDamage_Increase. Healing, taunts, slows and damage reduction are
not modelled (see IGNORED_TALENTS and docs/death_knight.md).
"""

from __future__ import annotations

import re

from sunken_sim.pressure import max_hp
from sunken_sim.shadow import (
    MAGICAL_ADDS,
    PHYSICAL_ADDS,
    Build,
    CAST_BACKSWING,
    CAST_POINT,
    DUMMY_ARMOR,
    FIGHT,
    LEVEL,
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
    sulfuras_echo_chance,
    target_hp,
)
from sunken_sim.stacking import stack_fields

# int(base + (level - 1) * per level), Warcraft truncation. ustr/ustp, uagi/uagp, uint/uinp.
BASE_STR = int(28 + (LEVEL - 1) * 2.8)
BASE_AGI = int(9 + (LEVEL - 1) * 0.9)
BASE_INT = int(13 + (LEVEL - 1) * 1.3)
WHITE_BASE = 12.0  # DCS base 11 + 1d1
SWING = 2.0
BASE_MANA = 120.0
BASE_HP = 310.0
BASE_ARMOR = 3.0
AGI_ARMOR = 0.1  # war3mapMisc AgiDefenseBonus

SPECS = ("frost", "blood", "unholy")
HERO_CLASS = "DeathKnight"  # key used by search.class_item_codes()
RANK = 1

TALENT_ARMY = "I0CS"
TALENT_VIRULENT = "I0E3"
TALENT_SINDRAGOSA = "I0CR"
TALENT_MARROWREND = "I09S"
TALENT_BLOOD_FEAST = "I0CU"
TALENT_OBLITERATE = "I0GP"
TALENT_BLOOD_TAP = "I09T"
TALENT_LICH_KING = "I0IZ"
TALENT_UNHOLY_STRIKES = "I0EV"
TALENT_NEXT_PAGE = "I0MD"
TALENT_BLOODFORGED = "I03X"
TALENT_DECOMPOSITION = "I0CV"
TALENT_NECROPOLIS = "I0G9"
TALENT_AMZ = "I03G"
TALENT_PESTILENCE = "I0IY"
TALENT_RAZORICE = "I0DS"
TALENT_GRIM_REAPER = "I07Z"
TALENT_BLOODWORMS = "I03W"
TALENT_DEATH_PRESENCE = "I05O"
TALENT_PREV_PAGE = "I0MC"

TALENTS = {
    TALENT_ARMY: "Army of the Dead",
    TALENT_VIRULENT: "Virulent Plague",
    TALENT_SINDRAGOSA: "Breath of Sindragosa",
    TALENT_MARROWREND: "Marrowrend",
    TALENT_BLOOD_FEAST: "Blood Feast",
    TALENT_OBLITERATE: "Obliterate",
    TALENT_BLOOD_TAP: "Blood Tap",
    TALENT_LICH_KING: "Might of the Lich King",
    TALENT_UNHOLY_STRIKES: "Unholy Strikes",
    TALENT_NEXT_PAGE: "Next Page",
    TALENT_BLOODFORGED: "Bloodforged Armor",
    TALENT_DECOMPOSITION: "Decomposition",
    TALENT_NECROPOLIS: "Will of the Necropolis",
    TALENT_AMZ: "Anti-Magic Zone",
    TALENT_PESTILENCE: "Pestilence",
    TALENT_RAZORICE: "Razorice",
    TALENT_GRIM_REAPER: "Grim Reaper",
    TALENT_BLOODWORMS: "Bloodworms",
    TALENT_DEATH_PRESENCE: "Death Presence",
    TALENT_PREV_PAGE: "Previous Page",
}

# Heal-only / defensive / page buttons: no damage in a dummy fight.
IGNORED_TALENTS = frozenset(
    {TALENT_BLOOD_FEAST, TALENT_NECROPOLIS, TALENT_AMZ, TALENT_NEXT_PAGE, TALENT_PREV_PAGE}
)

# Cooldowns (acdn level 1) and spell numbers, war3map.j 122749-123507.
DEATH_GRIP_CD = 10.0  # A03W
ERW_CD = 14.0  # A085
BLOOD_STRIKE_CD = 7.0  # A0G1
UNHOLY_FURY_CD = 12.0  # A03V: acdn not set, tooltip "Cooldown: 12.0"
FROST_STRIKE_CD = 8.0  # A0IE
OUTBREAK_TIME = 8.0  # A04I adur, buff B06E
BLOOD_PLAGUE_TIME = 4.0  # A0QH adur, buff B08P
MARROW_TIME = 5.0  # B08Q
MARROW_ARMOR = 5.0
BONE_SHIELD_ARMOR = 4.0
FREEZE_TIME = 1.5  # Bfro from Frost Strike
CHILL_TIME = 5.0  # B011 from Sindragosa
GHOUL_CHILL = 4.0
GHOUL_TIME = 16.0
GHOUL_SWING = 1.65  # u007/u00O ua1c
WORM_TIME = 7.0
WORM_SWING = 1.5  # o01U ua1c
BLOOD_TAP = 1.35

GLYPH_UNSEALED = "I0AV"
GLYPH_GLASS = "I0JA"
GLYPH_FORTITUDE = "I07B"
GLYPH_SUPREMACY = "I0EK"
GLYPH_ANIMOSITY = "I0HC"
GLYPH_MINDHASTE = "I0OF"
GLYPH_BATTLE_FRENZY = "I0GZ"
GLYPH_FORTUNE = "I0EJ"
FIRE_ORB = "I07O"
FROST_ORB = "I0NS"
GALACTIC_FURY = "I0JO"
SULFURON_GLOVES = "I0QT"
SPELLBINDER = "tlum"

ITEM_PLAGUEBEARER_BELT = "I07T"  # Outbreak tick rate +0.25
ITEM_SIPHONING_SWORD = "I0NM"  # Blood Strike healing x2
ITEM_BLOOD_MASK = "I0NJ"  # Blood Feast heal, no damage
ITEM_COLDBRINGER = "I0NK"  # Frost Strike cooldown -2
ITEM_MAW = "I0RZ"  # Blood Strike: no Blood Plague, +0.35 x healing as damage


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
    armor_items = 0.0
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
            armor_items += float(getattr(item, "armor", 0) or 0)
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
    hp = max_hp(BASE_HP, strength) + health_flat
    attack_speed = min(4.0, max(-0.8, attack_speed + min(1.0, 0.004 * agility)))
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
        "armor": BASE_ARMOR + AGI_ARMOR * agility + armor_items,
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
        "belt": 1.0 if ITEM_PLAGUEBEARER_BELT in codes else 0.0,
        "siphon": 1.0 if ITEM_SIPHONING_SWORD in codes else 0.0,
        "coldbringer": 1.0 if ITEM_COLDBRINGER in codes else 0.0,
        "maw": 1.0 if ITEM_MAW in codes else 0.0,
        "luck": luck,
        "mana_max": mana_max,
        "mana_regen": regen,
        "cast_stun_lock": cast_stun_lock,
        "hp": hp,
        **passive,
    }


def _cooldown(base: float, haste: float, stats: dict, flat: float = 0.0) -> float:
    return max(0.5, (base * stats["cd_temp"] - stats["flat_cdr"] - flat) / (1.0 + haste))


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


def simulate(build: Build, targets: int = 5, spec: str = "frost") -> Report:
    if spec not in SPECS:
        raise ValueError(spec)
    if targets < 1:
        raise ValueError(targets)
    stats = stats_of(build)
    luck_mult = 1.0 + stats["luck"]
    bt = BLOOD_TAP if _has(build, TALENT_BLOOD_TAP) else 1.0
    attack_crit = _crit_factor(stats["crit"], 2.0 + stats["rating"])
    spell_crit = _crit_factor(stats["crit"], stats["spell_mult"] + stats["rating"]) if stats["spell_crit"] else 1.0
    frost_presence = spec == "frost" or _has(build, TALENT_DEATH_PRESENCE)
    unholy_presence = spec == "unholy" or _has(build, TALENT_DEATH_PRESENCE)
    has_erw = spec != "unholy"
    plaguebearer = spec == "unholy"
    bone_shield = BONE_SHIELD_ARMOR if _has(build, TALENT_MARROWREND) else 0.0
    drain = 1.5 + 2.0 * LEVEL  # mana per second while in combat

    sources: dict[str, float] = {
        "Автоатака": 0.0,
        "Death Grip": 0.0,
        "Blood Strike": 0.0,
        "Unholy Fury": 0.0,
        "Frost Strike": 0.0,
        "Outbreak": 0.0,
        "Plaguebearer": 0.0,
        "Unholy Strikes": 0.0,
        "Breath of Sindragosa": 0.0,
        "Army of the Dead": 0.0,
        "Bloodworms": 0.0,
        "Всплеск огня": 0.0,
    }
    actions: list[tuple[float, str]] = []
    hp_bonus = 0.0
    mana = stats["mana_max"]
    mana_time = 0.0
    outbreak = [-1.0] * targets
    plague = [-1.0] * targets
    chill = [-1.0] * targets
    frozen = -1.0
    marrow = -1.0
    sulfuras = Sulfuras() if _wears(build, "I0BR") else None
    pb_dither = [_Dither() for _ in range(targets)]
    decomp_dither = [_Dither() for _ in range(targets)]
    worm_dither = _Dither()
    ghoul_dither = _Dither()
    razor_dither = _Dither()
    army_count = 0

    def max_life() -> float:
        return stats["hp"] + hp_bonus

    def recover(now: float) -> None:
        nonlocal mana, mana_time
        dt = now - mana_time
        if dt > 0:
            # Presence: every 0.25 s, only while mana >= the quarter drain.
            net = stats["mana_regen"] - drain
            value = mana + net * dt
            if net < 0 and value < drain / 4.0:
                value = min(mana, drain / 4.0)
            mana = max(0.0, min(stats["mana_max"], value))
        mana_time = now

    def mastery() -> float:
        return stats["mastery"]

    def dcs() -> float:
        return WHITE_BASE + 0.75 * stats["str"] + stats["damage"]

    def potency(now: float) -> float:
        value = stats["potency"]
        if unholy_presence and stats["mana_max"] > 0:
            recover(now)
            value += (mana / stats["mana_max"]) * (3.0 + 0.4 * LEVEL)
        return value

    def increase(t: int, now: float) -> float:
        """DamageIncrease (Func029): Frost Strike passive and Grim Reaper."""
        bonus = 1.0
        is_frozen = t == 0 and frozen >= now
        if is_frozen:
            bonus += 0.15
        elif chill[t] >= now:
            bonus += 0.08
        if _has(build, TALENT_GRIM_REAPER):
            count = (plague[t] >= now) + (outbreak[t] >= now) + is_frozen + (chill[t] >= now)
            count += t == 0 and marrow >= now
            bonus += 0.06 * count
        return bonus

    def typed(magical: bool, now: float) -> float:
        bonus = 1.0 + (stats["magic_add"] if magical else stats["phys_add"])
        if stats["sulfuron"]:
            bonus += 0.13 + 0.25 * target_hp(now)
        if magical:
            if stats["spellbinder"]:
                bonus += 0.05 + 0.005 * mastery()
            if frost_presence:
                recover(now)
                bonus += 0.01 * (mana / 40.0)
            if _has(build, TALENT_BLOODFORGED):
                bonus += 0.05 + 0.01 * (stats["armor"] + bone_shield)
        if stats["glass"]:
            bonus *= 1.15
        return bonus

    def taken(t: int, now: float) -> float:
        armor = DUMMY_ARMOR - stats["armor_pen"]
        if t == 0 and marrow >= now:
            armor -= MARROW_ARMOR
        return armor_taken(armor)

    def plague_flat(t: int, now: float) -> float:
        if plague[t] < now:
            return 0.0
        value = 2.0 + RANK
        if _has(build, TALENT_DECOMPOSITION):
            value += 3.0 + 0.08 * dcs()
        return value

    def apply_outbreak(t: int, now: float) -> None:
        """Outbreak_Apply: A04I on a target already carrying B06E bursts for Unholy."""
        if plaguebearer and outbreak[t] >= now:
            raw = 20.0 + 0.015 * max_life() * bt
            # DAMAGE_TYPE_DISEASE without NextDamageType: no magical branch, no Plaguebearer.
            amount = raw * increase(t, now) * taken(t, now) * _execute_factor(stats, now)
            sources["Plaguebearer"] += amount
        outbreak[t] = now + OUTBREAK_TIME

    def after_hit(t: int, now: float) -> None:
        if plaguebearer:
            chance = 0.05 * (1.25 if _has(build, TALENT_PESTILENCE) else 1.0) * luck_mult
            if outbreak[t] < now:
                chance *= 0.5
            if pb_dither[t].roll(chance):
                apply_outbreak(t, now)

    def deal(name: str, raw: float, t: int, now: float, magical: bool = True, potency_scale: float = 1.0) -> float:
        amount = raw + potency(now) * potency_scale + plague_flat(t, now)
        amount *= typed(magical, now) * increase(t, now)
        amount *= spell_crit if magical else attack_crit
        amount *= taken(t, now) * _execute_factor(stats, now)
        sources[name] += amount
        note_damage_mana(1)
        after_hit(t, now)
        return amount

    def summon_hit(name: str, raw: float, t: int, now: float) -> float:
        amount = (raw + plague_flat(t, now)) * increase(t, now) * taken(t, now) * _execute_factor(stats, now)
        sources[name] += amount
        after_hit(t, now)
        return amount

    def note_damage_mana(count: int) -> None:
        nonlocal mana
        if stats["damage_mana_pct"]:
            mana = min(stats["mana_max"], mana + stats["damage_mana_pct"] * stats["mana_max"] * count)

    def unholy_strikes(now: float) -> None:
        if _has(build, TALENT_UNHOLY_STRIKES):
            for _ in range(2):
                deal("Unholy Strikes", 15.0 + 0.40 * stats["str"], 0, now)

    # cooldown state
    ready = {"uf": 0.0, "fs": 0.0, "bs": 0.0, "dg": 0.0, "erw": 0.0 if has_erw else FIGHT + 1}
    base_cd = {
        "uf": UNHOLY_FURY_CD,
        "fs": FROST_STRIKE_CD,
        "bs": BLOOD_STRIKE_CD,
        "dg": DEATH_GRIP_CD,
        "erw": ERW_CD,
    }
    fs_flat = (1.0 if _has(build, TALENT_LICH_KING) else 0.0) + (2.0 if stats["coldbringer"] else 0.0)
    names = {"uf": "Unholy Fury", "fs": "Frost Strike", "bs": "Blood Strike", "dg": "Death Grip", "erw": "Empower Rune Weapon"}
    last_cast: str | None = None
    rested = False
    summons: list[dict] = []  # {"kind", "end", "next", "raw"}
    tick_rate = 1.0 + (0.10 + 0.005 * mastery() if spec == "unholy" else 0.0) + (0.25 if stats["belt"] else 0.0)
    next_tick = 1.0 * (1.0 - (0.10 + 0.005 * mastery()))  # Select_Str_Hero first timer
    virulent = (0.12 + 0.005 * stats["potency"]) * luck_mult if _has(build, TALENT_VIRULENT) else 0.0

    def cast_spell(key: str, now: float) -> None:
        nonlocal frozen, marrow, hp_bonus, last_cast, rested, army_count, mana
        actions.append((now, names[key]))
        hit = now + CAST_POINT
        life = max_life()
        if key == "dg":
            raw = 20.0 + 10.0 * LEVEL + 0.10 * life * bt
            if _has(build, TALENT_OBLITERATE):
                raw += 0.75 * dcs()
            deal("Death Grip", raw, 0, hit)
            recover(hit)
            mana = min(stats["mana_max"], mana + 0.05 * stats["mana_max"])
            unholy_strikes(hit)
        elif key == "bs":
            raw = 70.0 * RANK - 10.0 + 0.10 * life * bt
            if _has(build, TALENT_OBLITERATE):
                raw += 0.75 * dcs()
            if stats["maw"]:
                healing = (70.0 * RANK - 10.0 - 40.0) + 0.10 * life * bt
                if stats["siphon"]:
                    healing *= 2.0
                raw += 0.35 * healing
            deal("Blood Strike", raw, 0, hit)
            if not stats["maw"]:
                plague[0] = hit + BLOOD_PLAGUE_TIME
            if _has(build, TALENT_MARROWREND):
                marrow = hit + MARROW_TIME
            if not rested:
                hp_bonus += 1.0
        elif key == "uf":
            raw = 50.0 + 0.05 * life * bt
            if _has(build, TALENT_OBLITERATE):
                raw += 0.50 * dcs()
            for t in range(targets):
                deal("Unholy Fury", raw, t, hit)
                apply_outbreak(t, hit)
        elif key == "fs":
            raw = 70.0 + 0.05 * life * bt + 0.15 * stats["mana_max"]
            if _has(build, TALENT_LICH_KING):
                raw *= 1.20
            if _has(build, TALENT_OBLITERATE):
                raw += 1.00 * dcs()
            if spec == "frost":
                raw = raw * (1.05 + 0.005 * mastery()) + 0.10 * stats["mana_max"]
            deal("Frost Strike", raw, 0, hit)
            frozen = hit + FREEZE_TIME
            unholy_strikes(hit)
            if _has(build, TALENT_SINDRAGOSA):
                wyrm = 20.0 + 0.05 * stats["mana_max"] + 0.05 * life * bt
                for t in range(targets):
                    if t == 0 and frozen >= hit:
                        deal("Breath of Sindragosa", wyrm * 1.5, t, hit)
                    else:
                        deal("Breath of Sindragosa", wyrm, t, hit)
                        chill[t] = max(chill[t], hit + CHILL_TIME)
        elif key == "erw":
            if last_cast is not None:
                ready[last_cast] = now
                rested = last_cast == "bs"
        if key != "erw":
            rested = False
            last_cast = key
        # OnSpellcast_Heroes: summons
        if _has(build, TALENT_BLOODWORMS):
            raw = 5.0 + int(0.12 * dcs() + 0.005 * life * bt)
            summons.append({"kind": "worm", "end": hit + WORM_TIME, "next": hit, "raw": float(raw)})
        if _has(build, TALENT_ARMY) and key != "erw":
            army_count += 1
            if army_count >= 3:
                army_count = 0
                raw = 10.0 + int(0.35 * dcs())
                summons.append({"kind": "ghoul", "end": hit + GHOUL_TIME, "next": hit, "raw": float(raw)})

    order = ("uf", "fs", "bs", "dg")
    next_attack = 0.0
    busy = 0.0
    guard = 0
    while True:
        guard += 1
        if guard > 200000:
            break
        spell_at = max(busy, min(ready[k] for k in order))
        erw_at = FIGHT + 1
        if has_erw and last_cast is not None and ready["erw"] < FIGHT and ready[last_cast] - max(busy, ready["erw"]) > 2.0:
            erw_at = max(busy, ready["erw"])
        summon_at = min((s["next"] for s in summons if s["next"] < s["end"]), default=FIGHT)
        moment = min(next_attack, spell_at, erw_at, summon_at, next_tick)
        if moment >= FIGHT:
            break
        summons = [s for s in summons if s["next"] < s["end"]]
        if moment == next_tick:
            for t in range(targets):
                if outbreak[t] >= moment:
                    raw = 5.0 * RANK + 0.008 * max_life() * bt
                    times = 1.0 + virulent
                    before = sources["Outbreak"]
                    deal("Outbreak", raw, t, moment)
                    sources["Outbreak"] = before + (sources["Outbreak"] - before) * times
                    if _has(build, TALENT_DECOMPOSITION) and decomp_dither[t].roll(0.20 * luck_mult):
                        plague[t] = moment + BLOOD_PLAGUE_TIME
            next_tick = moment + 1.25 / tick_rate
            continue
        if moment == summon_at:
            for s in summons:
                if s["next"] != moment:
                    continue
                if s["kind"] == "ghoul":
                    summon_hit("Army of the Dead", s["raw"], 0, moment)
                    if spec != "blood" and ghoul_dither.roll(0.10 * luck_mult):
                        if outbreak[0] < moment:
                            apply_outbreak(0, moment)
                        elif chill[0] < moment:
                            chill[0] = moment + GHOUL_CHILL
                        else:
                            apply_outbreak(0, moment)
                    if _has(build, TALENT_RAZORICE) and razor_dither.roll(0.15 * luck_mult):
                        ready["fs"] = max(moment, ready["fs"] - 0.30)
                    s["next"] = moment + GHOUL_SWING
                else:
                    dealt = summon_hit("Bloodworms", s["raw"], 0, moment)
                    if worm_dither.roll(0.20 * luck_mult):
                        deal("Bloodworms", 2.0 * dealt, 0, moment, potency_scale=0.0)
                    if _has(build, TALENT_RAZORICE) and razor_dither.roll(0.15 * luck_mult):
                        ready["fs"] = max(moment, ready["fs"] - 0.30)
                    s["next"] = moment + WORM_SWING
            continue
        if moment == erw_at and erw_at <= next_attack:
            cast_spell("erw", moment)
            busy = moment + CAST_POINT + CAST_BACKSWING + stats["cast_stun_lock"]
            ready["erw"] = moment + _cooldown(ERW_CD, stats["haste"], stats)
            next_attack = max(next_attack, busy)
            continue
        if moment == spell_at and spell_at <= next_attack:
            key = min(order, key=lambda k: (max(busy, ready[k]), order.index(k)))
            cast_spell(key, moment)
            busy = moment + CAST_POINT + CAST_BACKSWING + stats["cast_stun_lock"]
            flat = fs_flat if key == "fs" else 0.0
            ready[key] = moment + _cooldown(base_cd[key], stats["haste"], stats, flat)
            next_attack = max(next_attack, busy)
            continue
        if moment == next_attack and next_attack < busy:
            next_attack = busy
            continue
        if moment == next_attack:
            recover(moment)
            swing = SWING * (1.20 if stats["galactic"] else 1.0)
            interval = swing / (1.0 + stats["attack_speed"])
            before = sources["Автоатака"]
            deal("Автоатака", dcs(), 0, moment, magical=False, potency_scale=stats["attack_potency"])
            if stats["auto_pct"] != 1.0:
                sources["Автоатака"] = before + (sources["Автоатака"] - before) * stats["auto_pct"]
            mana = min(stats["mana_max"], mana + attack_mana_gain(stats))
            if _has(build, TALENT_RAZORICE):
                ready["fs"] = max(moment, ready["fs"] - 0.30)
            if stats["fire_orb"]:
                splash = (20.0 + 0.35 * stats["str"]) * targets * taken(1 % targets, moment) * _execute_factor(stats, moment)
                sources["Всплеск огня"] += splash
                note_damage_mana(targets)
            if sulfuras is not None:
                execute = _execute_factor(stats, moment)
                if sulfuras.attack():
                    splash = stats["str"] * typed(True, moment) * spell_crit * taken(1 % targets, moment) * execute * targets
                    sources["Sulfuras"] = sources.get("Sulfuras", 0.0) + splash
                    note_damage_mana(targets)
                echo = dcs() * taken(0, moment) * execute * sulfuras_echo_chance(stats["luck"])
                sources["Sulfuras (удар)"] = sources.get("Sulfuras (удар)", 0.0) + echo
            next_attack = moment + interval
            continue
        break

    total = sum(sources.values())
    recover(FIGHT)
    mana_left = 0.0 if stats["mana_max"] <= 0 else 100.0 * mana / stats["mana_max"]
    return Report(build, total / FIGHT, total, sources, actions, stats, targets, mana_left=mana_left)


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
