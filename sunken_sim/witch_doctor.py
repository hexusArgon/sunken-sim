"""Witch Doctor fight for Sunken City v2.5.2a, level 6.

Unit O00N. Level 6 stats (base + 5 x gain, floored): STR 15, AGI 19, INT 40.
White hit 10 + 1d1 = 11, plus 0.75 x INT (DCS formula). Attack cooldown 2.0, attack type MAGIC
(scored as magical attacks). Primary INT. Ability rank is 1. Base HP 230, base mana 175.
Spec level on A0J8 (udg_Glyphs_Unit[3]): 1 Voodoo (Voodoo Ward A0GO, heal only), 2 Poison
(Poison Ward A0LS). Talents sit on udg_Talents_Unit[3].

Spells: Plague Toad A0PK (5.5 s, 20 mana), Vile Spider A07U (12 s, 30 mana, 2 spiders n022 for
12 s), Soul Possession A0PJ (25 s, 40 mana, B084 on the target), Poison Ward A0LS (12 s, 30 mana,
ward o01S lives 12 s; Poison spec only). Soul Harvest A0F3 (mana drain) and Voodoo Ward A0GO
(heal) are not cast: no scored damage.
Periodic damage: Noxious Venom (B082, global 1 s timer, 5 x rank + AGI per tick, source = random
unit of VileSpider_Group which always holds the dummy n01F), Poison Dart I0FN (global 3 s timer).
Procs (PreDamage_Heroes): Poison Ward (3% x 1.5 if cobras <= 4, x1.3 Venom Rush for non-hero
sources), Addling Toad I0A4 (2.5% / 5% from spiders and souls), Poison Dart -0.5 s (10%).
Potency (owner) is added to every damage instance from the owner, summons included.
Healing and defensive effects are not scored.
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
from sunken_sim.ledger import Ledger, attach, score_events  # noqa: F401

BASE_STR = int(10 + (LEVEL - 1) * 1.0)  # O00N ustr/ustp
BASE_AGI = int(13 + (LEVEL - 1) * 1.3)  # uagi/uagp
BASE_INT = int(27 + (LEVEL - 1) * 2.7)  # uint/uinp
WHITE_BASE = 11.0  # O00N ua1b 10 + 1d1
SWING = 2.0  # O00N ua1c
BASE_MANA = 175.0
BASE_HP = 230.0

SPECS = ("voodoo", "poison")
HERO_CLASS = "WitchDoctor"
RANK = 1

TALENT_TIKI_ARMY = "I0M5"
TALENT_HEX = "I0M8"
TALENT_WIDOW_VENOM = "I0MH"
TALENT_POISON_DART = "I0FN"
TALENT_ADDLING_TOAD = "I0A4"
TALENT_RAVENOUS_SPIRIT = "I0FM"
TALENT_JUNGLE_FORTITUDE = "I0BA"
TALENT_GRAVE_INJUSTICE = "I013"
TALENT_VENOM_RUSH = "I0AK"
TALENT_TRIBAL_WARDING = "I012"
TALENT_MUTATED_TOADS = "I0M7"
TALENT_SPIRITS_UNBOUND = "I00A"
TALENT_TOXIC_BITE = "I0RM"
TALENT_GRASP = "I0RN"
TALENT_SOUL_BIND = "I0RL"
TALENT_SPIRITUAL_TOUCH = "I0M6"
TALENT_SUPERSTITION = "I0MG"
TALENT_HORRIFY = "I09P"
TALENT_NEXT_PAGE = "I0MD"
TALENT_PREV_PAGE = "I0MC"

TALENTS = {
    TALENT_TIKI_ARMY: "Tiki Army",
    TALENT_HEX: "Hex",
    TALENT_WIDOW_VENOM: "Widow Venom",
    TALENT_POISON_DART: "Poison Dart",
    TALENT_ADDLING_TOAD: "Addling Toad",
    TALENT_RAVENOUS_SPIRIT: "Ravenous Spirit",
    TALENT_JUNGLE_FORTITUDE: "Jungle Fortitude",
    TALENT_GRAVE_INJUSTICE: "Grave Injustice",
    TALENT_VENOM_RUSH: "Venom Rush",
    TALENT_TRIBAL_WARDING: "Tribal Warding",
    TALENT_MUTATED_TOADS: "Mutated Toads",
    TALENT_SPIRITS_UNBOUND: "Spirits Unbound",
    TALENT_TOXIC_BITE: "Toxic Bite",
    TALENT_GRASP: "Grasp of the Shadowlands",
    TALENT_SOUL_BIND: "Soul Bind",
    TALENT_SPIRITUAL_TOUCH: "Spiritual Touch",
    TALENT_SUPERSTITION: "Superstition",
    TALENT_HORRIFY: "Horrify",
}

# Heal (Spiritual Touch), defensive (Superstition, Horrify); pages are UI only.
IGNORED_TALENTS = frozenset({
    TALENT_SPIRITUAL_TOUCH, TALENT_SUPERSTITION, TALENT_HORRIFY, TALENT_NEXT_PAGE, TALENT_PREV_PAGE,
})

TOAD_CD, TOAD_MANA = 5.5, 20.0  # A0PK
TOAD_DELAY = 1.0  # ASSUMPTION: toad travel / hop to the target, no data
SPIDER_CD, SPIDER_MANA = 12.0, 30.0  # A07U
SPIDER_LIFE = 12.0
SPIDER_SWING = 1.5  # n022 ua1c
SPIDER_MANA_MAX = 60.0  # n022 umpm (umpi 100 is capped by max)
SPIDER_MANA_REGEN = 0.0  # ASSUMPTION: no umpr in data, treated as 0
VENOM_CD, VENOM_MANA, VENOM_DUR = 2.0, 30.0, 4.0  # A0PL -> B082
SOUL_CD, SOUL_MANA, SOUL_DUR = 25.0, 40.0, 12.0  # A0PJ -> B084 (+4 s Soul Bind)
WARD_CD, WARD_MANA, WARD_LIFE = 12.0, 30.0, 12.0  # A0LS -> o01S
COBRA_LIFE = 20.0
COBRA_SWING = 1.5  # n04C / n03J ua1c
DART_PERIOD = 3.0  # PoisonDart_CD
WARD_PROC = 3.00  # PreDamage_Heroes (tooltip says 2.5%)

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
ITEM_BLACK_TOAD = "I0RO"  # class item; flat CDR lands on ability slot 2 (Soul Harvest), not Plague Toad
ITEM_WD_SPIDER = "I0RP"  # class item: +1 Vile Spider
ITEM_WD_REGEN = "I0RQ"  # class item: stats + mana regen only
ITEM_WD_SOUL = "I0RR"  # Soul Possession CD -6 s


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
        "pet_damage": pet_damage + (0.006 * agility if _has(build, TALENT_JUNGLE_FORTITUDE) else 0.0),
        "black_toad": 1.0 if ITEM_BLACK_TOAD in codes else 0.0,
        "spider_fang": 1.0 if ITEM_WD_SPIDER in codes else 0.0,
        "soul_cd_flat": 6.0 if ITEM_WD_SOUL in codes else 0.0,
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


# (possession, order): Soul Possession on target 0 for B084 (Hex / Grasp) or never;
# spider first or toad first when both are ready.
POLICIES = tuple((soul, first) for soul in (True, False) for first in ("spider", "toad"))


def _timeline_key(build: Build, stats: dict, spec: str, targets: int, policy: tuple) -> tuple:
    """Safe GPU tape cluster key; only potency_points is unbaked.

    This is a fixed-policy key, never a key for the representative's winner.
    Crit/luck, mastery, pets, timing and resources stay baked.
    All policy tapes must be rescored before choosing a winner for each build.

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
            tuple(sorted(build.glyphs)), esc, spec, targets, policy,
            freeze({k: v for k, v in stats.items() if k != "potency"}))


def simulate(build: Build, targets: int = 5, spec: str = "voodoo") -> Report:
    """Best of the policies (Soul Possession on / off, spider or toad first)."""
    best = None
    for policy in POLICIES:
        report = _simulate(build, targets, spec, policy)
        if best is None or report.dps > best.dps + 1e-9:
            best = report
    return best


def _simulate(build: Build, targets: int, spec: str, policy: tuple[bool, str]) -> Report:
    use_soul, first = policy
    if spec not in SPECS:
        raise ValueError(spec)
    if targets < 1:
        raise ValueError(targets)
    stats = stats_of(build)
    luck_mult = 1.0 + stats["luck"]
    has = lambda code: _has(build, code)  # noqa: E731
    poison = spec == "poison"
    intel = int(stats["int"])
    agi = int(stats["agi"])
    base_mastery = int(stats["mastery"])
    mana_max = stats["mana_max"]
    crit_stat = stats["crit"]
    pen = stats["armor_pen"]
    mutated = has(TALENT_MUTATED_TOADS)
    toad_mult = 1.15 if mutated else 1.0

    sources: dict[str, float] = Ledger({"Автоатака": 0.0})
    actions: list[tuple[float, str]] = []
    mana = mana_max
    mana_time = 0.0
    sulfuras = Sulfuras() if _wears(build, "I0BR") else None
    cast_time = CAST_POINT + CAST_BACKSWING

    venom_until = [-1.0] * targets
    soul_until = [-1.0] * targets
    spiders: list[dict] = []
    cobras: list[dict] = []
    wards: list[float] = []  # end times
    pending: list[tuple[float, int, str, float]] = []
    seq = 0
    ward_roll = _Dither()
    spider_roll = _Dither()
    addling_roll = _Dither()
    dart_roll = _Dither()
    widow_roll = _Dither()
    # PlagueToad_BaseDmg before the first Plague Toad cast (map init value).
    toad_base = 50.0 + 2.0 * intel
    dart_next = 0.0 if has(TALENT_POISON_DART) else FIGHT * 10  # ASSUMPTION: first dart at t = 0
    noxious_next = 1.0  # ASSUMPTION: periodic 1 s timer ticks at whole seconds

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

    def mastery_now(now: float) -> float:
        value = float(base_mastery)
        if has(TALENT_SPIRITS_UNBOUND):
            recover(now)
            if mana_max > 0 and mana >= 0.75 * mana_max:
                value += 15.0  # Mastery_Tooltip: I00A at >= 75% mana
        return value

    def typed(magical: bool, now: float) -> float:
        bonus = 1.0 + (stats["magic_add"] if magical else stats["phys_add"])
        if stats["sulfuron"]:
            bonus += 0.13 + 0.25 * target_hp(now)
        if magical and stats["spellbinder"]:
            bonus += 0.05 + 0.005 * mastery_now(now)
        if stats["glass"]:
            bonus *= 1.15
        return bonus

    def dcs() -> float:
        return WHITE_BASE + 0.75 * intel + stats["damage"]

    def increase(t: int, now: float) -> float:
        """PreDamage_Increase: Hex (I0M8) and Grasp of the Shadowlands (B028 aura, I0RN)."""
        value = 0.0
        grasp = has(TALENT_GRASP)
        souled = soul_until[t] > now
        if has(TALENT_HEX):
            # ASSUMPTION: the dummy carries no buffs of its own; count B082, B084, B028.
            buffs = (venom_until[t] > now) + souled + (1 if grasp else 0)
            value += 0.04 + 0.02 * buffs
        if grasp:
            value += 0.12 if souled else 0.07
        return value

    def taken(hero: bool) -> float:
        armor = DUMMY_ARMOR
        if hero:
            armor -= pen
        return armor_taken(armor)

    def live(group: list[dict], now: float) -> list[dict]:
        return [d for d in group if d["end"] > now]

    def wards_alive(now: float) -> int:
        return sum(1 for end in wards if end > now)

    # ---- procs on owner damage (PreDamage_Heroes) ----
    def on_owner_damage(now: float, t: int, *, hero: bool, kind: str, weight: float = 1.0) -> None:
        """kind: 'spider' / 'soul' (n022, A0QO), 'unit' (other owner units, max life >= 5), 'hero'."""
        if weight <= 0:
            return
        if has(TALENT_ADDLING_TOAD) and not hero:
            chance = (0.05 if kind == "spider" else 0.025) * luck_mult * weight
            if addling_roll.roll(chance):
                push(now + TOAD_DELAY, "addling")
        if has(TALENT_POISON_DART) and dart_roll.roll(_chance(0.10 * luck_mult) * weight):
            nonlocal dart_next
            if dart_next - now >= 0.5:
                dart_next -= 0.5
            elif dart_next > now:
                dart_next = now + 0.01
        n_wards = wards_alive(now)
        for _w in range(n_wards):
            chance = WARD_PROC
            if len(live(cobras, now)) <= 4:
                chance *= 1.5
            if has(TALENT_VENOM_RUSH) and not hero:
                chance *= 1.3
            if ward_roll.roll(_chance(chance / 100.0 * luck_mult) * weight):
                raw = 50.0 + 0.10 * mana_max + intel
                # DAMAGE_TYPE_DISEASE from the hero: no procs. ASSUMPTION: scored as physical adds.
                hero_hit("Poison Ward", raw, now, [t], magical=False, attack=False, procs=False)
                cap = 8 if has(TALENT_TIKI_ARMY) else 6
                if poison and spider_roll.roll(_chance((5.0 + 0.40 * mastery_now(now)) / 100.0)):
                    spawn_spider(now)
                elif len(live(cobras, now)) < cap:
                    spawn_cobra(now)

    def hero_hit(name: str, raw: float, now: float, tgts: list[int], *, magical: bool, attack: bool,
                 weight: float = 1.0, potency_scale: float = 1.0, chaos: bool = False,
                 procs: bool = True, source_scale: float = 1.0) -> tuple[float, float]:
        if weight <= 0 or not tgts:
            return 0.0, 0.0
        chance = crit_stat
        share = max(0.0, min(100.0, chance)) / 100.0
        first_dealt = 0.0
        raw_weight, pot_coeff = 0.0, 0.0
        execute = _execute_factor(stats, now)
        kind = typed(magical, now)  # preserves Spirits Unbound's recovery call
        for i, t in enumerate(tgts):
            factor = kind * (1.0 + increase(t, now))
            if chaos:
                factor *= CHAOS_UNARMORED
            if attack:
                factor *= _crit_factor(chance, 2.0 + stats["rating"])
            elif stats["spell_crit"]:
                factor *= _crit_factor(chance, stats["spell_mult"] + stats["rating"])
            factor *= taken(True)
            raw_weight += raw * factor
            pot_coeff += potency_scale * factor
            if i == 0:
                first_dealt = (raw * factor + stats["potency"] * potency_scale * factor) * execute
        total = (raw_weight + stats["potency"] * pot_coeff) * execute
        scale = weight * source_scale
        sources.add_exec(name, total * scale, now, execute,
                         raw_weight=raw_weight * scale, pot_coeff=pot_coeff * scale)
        # Source-only auto scaling must not alter weighted owner-proc dithers.
        note_damage_mana(len(tgts) * weight)
        if procs:
            for t in tgts:
                on_owner_damage(now, t, hero=True, kind="hero", weight=weight)
        return first_dealt, (share if (attack or stats["spell_crit"]) else 0.0)

    def summon_hit(name: str, raw: float, now: float, tgts: list[int], *, attack: bool, kind: str,
                   weight: float = 1.0, chaos: bool = False, procs: bool = True) -> float:
        """Owner-unit raw/potency channels; original weighting and proc order unchanged."""
        if weight <= 0 or not tgts:
            return 0.0
        chance = stats["summon_crit"]
        raw_weight, pot_coeff = 0.0, 0.0
        execute = _execute_factor(stats, now)
        for t in tgts:
            factor = (1.0 + stats["pet_damage"]) * (1.0 + increase(t, now))
            if chaos:
                factor *= CHAOS_UNARMORED
            if attack:
                factor *= _crit_factor(chance, 2.0 + stats["summon_rating"])
            factor *= taken(False)
            raw_weight += raw * factor
            pot_coeff += factor
        total = (raw_weight + stats["potency"] * pot_coeff) * execute
        sources.add_exec(name, total * weight, now, execute,
                         raw_weight=raw_weight * weight, pot_coeff=pot_coeff * weight)
        if procs:
            for t in tgts:
                on_owner_damage(now, t, hero=False, kind=kind, weight=weight)
        return total

    def spawn_spider(now: float) -> None:
        raw = 3.0 + int(4.0 * RANK + 0.20 * dcs()) + 1.0  # n022 ua1b 3 + R2I(4 x lvl + 0.2 DCS) + 1d1
        spiders.append({"next": now, "end": now + SPIDER_LIFE, "raw": raw, "mana": SPIDER_MANA_MAX,
                        "venom": now})
        push(now + SPIDER_LIFE, "death", 0.06)

    def spawn_cobra(now: float) -> None:
        tiki = has(TALENT_TIKI_ARMY)
        raw = 4.0 + int((0.18 if tiki else 0.10) * dcs()) + 1.0  # ua1b 4 + R2I(x DCS) + 1d1
        cobras.append({"next": now, "end": now + COBRA_LIFE, "raw": raw, "chaos": tiki})
        push(now + COBRA_LIFE, "death", 0.03)

    def grave_injustice(now: float, pct: float) -> None:
        if not has(TALENT_GRAVE_INJUSTICE):
            return
        for key in order:
            if nxt[key] > now:
                nxt[key] = now + (nxt[key] - now) * (1.0 - pct)

    def venom_target(now: float) -> int:
        # "Will prefer to target unaffected enemies". ASSUMPTION: lowest index first.
        fresh = [t for t in range(targets) if venom_until[t] <= now]
        if fresh:
            return fresh[0]
        return min(range(targets), key=lambda t: venom_until[t])

    def noxious(now: float, t: int, name: str, weight: float = 1.0) -> None:
        raw = 5.0 * RANK + agi
        # Source: random unit of VileSpider_Group (live spiders + dummy n01F).
        n = len(live(spiders, now))
        share = n / (n + 1.0)
        summon_hit(name, raw, now, [t], attack=False, kind="spider", weight=weight * share)
        summon_hit(name, raw, now, [t], attack=False, kind="unit", weight=weight * (1.0 - share))

    def interval(now: float) -> float:
        swing = SWING * (1.20 if stats["galactic"] else 1.0)
        speed = min(4.0, max(-0.8, stats["attack_speed"]))
        return swing / (1.0 + speed)

    fixed_cd = {"toad": TOAD_CD, "spider": SPIDER_CD, "ward": WARD_CD, "soul": SOUL_CD}
    cost = {"toad": TOAD_MANA, "spider": SPIDER_MANA, "ward": WARD_MANA, "soul": SOUL_MANA}
    names = {"toad": "Plague Toad", "spider": "Vile Spider", "ward": "Poison Ward",
             "soul": "Soul Possession"}
    order = (["ward"] if poison else []) + (["spider", "toad"] if first == "spider" else ["toad", "spider"])
    if use_soul:
        order.append("soul")
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
            ready = max(nxt[key], busy, clock)
            if ready < cast_at - 1e-9:
                cast_at, choice = ready, key
        pending_at = min((p[0] for p in pending), default=FIGHT * 10)
        spiders[:] = [d for d in spiders if d["end"] > clock - 1e-9]
        cobras[:] = [d for d in cobras if d["end"] > clock - 1e-9]
        units = spiders + cobras
        unit_at = min((d["next"] for d in units if d["next"] < d["end"]), default=FIGHT * 10)
        venom_at = min((d["venom"] for d in spiders if d["venom"] < d["end"] and d["mana"] >= VENOM_MANA),
                       default=FIGHT * 10)
        timers = min(noxious_next, dart_next)
        moment = min(attack_at, cast_at, pending_at, unit_at, venom_at, timers)
        if moment >= FIGHT:
            break
        clock = moment

        if moment == pending_at:
            event = min(pending)
            pending.remove(event)
            _, _, kind, arg = event
            if kind == "toad":
                # N toads (N = enemies in 600), each BaseDmg / N to everything in its AoE.
                # ASSUMPTION: the pack is clustered, every target is inside every toad's AoE.
                per = toad_base * toad_mult / targets
                hero_hit("Plague Toad", per, moment, list(range(targets)), magical=True, attack=False,
                         weight=float(targets))
            elif kind == "addling":
                # The toad unit (max life 1) deals the damage: no procs, Pet Damage applies.
                summon_hit("Addling Toad", toad_base * toad_mult, moment, list(range(targets)),
                           attack=False, kind="toad", procs=False)
            elif kind == "death":
                grave_injustice(moment, arg)
            continue

        if moment == noxious_next:
            for t in range(targets):
                if venom_until[t] <= moment:
                    continue
                noxious(moment, t, "Noxious Venom")
                if has(TALENT_WIDOW_VENOM) and widow_roll.roll(_chance(0.25 * luck_mult)):
                    noxious(moment, t, "Noxious Venom")
            noxious_next = moment + 1.0
            continue

        if moment == dart_next:
            fresh = [t for t in range(targets) if venom_until[t] <= moment]
            t = fresh[0] if fresh else 0
            raw = 1.0 * dcs() + 0.75 * agi
            # ATTACK_TYPE_CHAOS, DAMAGE_TYPE_DISEASE: attack crit, no procs.
            hero_hit("Poison Dart", raw, moment, [t], magical=False, attack=True, chaos=True, procs=False)
            venom_until[t] = max(venom_until[t], moment + VENOM_DUR)
            dart_next = moment + DART_PERIOD
            continue

        if moment == venom_at and venom_at < attack_at and venom_at < cast_at:
            d = min((u for u in spiders if u["venom"] < u["end"] and u["mana"] >= VENOM_MANA),
                    key=lambda u: u["venom"])
            d["mana"] -= VENOM_MANA
            t = venom_target(moment)
            venom_until[t] = moment + VENOM_DUR
            d["venom"] = moment + VENOM_CD
            d["next"] = max(d["next"], moment + CAST_POINT)
            continue

        if moment == unit_at and unit_at < attack_at and unit_at < cast_at:
            d = min((u for u in units if u["next"] < u["end"]), key=lambda u: u["next"])
            if d in spiders:
                summon_hit("Vile Spider", d["raw"], moment, [0], attack=True, kind="spider")
                if has(TALENT_TOXIC_BITE):
                    d["mana"] = min(SPIDER_MANA_MAX, d["mana"] + 3.0)
                    if venom_until[0] > moment:
                        noxious(moment, 0, "Toxic Bite")
                d["next"] = moment + SPIDER_SWING
            else:
                label = "Tiki" if d["chaos"] else "Cobra"
                summon_hit(label, d["raw"], moment, [0], attack=True, kind="unit", chaos=d["chaos"])
                d["next"] = moment + COBRA_SWING
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
            haste = stats["haste"]
            flat = 0.0
            if key == "toad":
                toad_base = 20.0 + 60.0 * RANK + 1.65 * intel
                push(hit_at + TOAD_DELAY, "toad")
            elif key == "spider":
                count = 2 + (1 if stats["spider_fang"] else 0)
                for _ in range(count):
                    spawn_spider(hit_at)
            elif key == "ward":
                wards.append(hit_at + WARD_LIFE)
                push(hit_at + WARD_LIFE, "death", 0.03)  # ASSUMPTION: o01S is not mechanical
            elif key == "soul":
                flat = stats["soul_cd_flat"]
                dur = SOUL_DUR + (4.0 if has(TALENT_SOUL_BIND) else 0.0)
                soul_until[0] = hit_at + dur
                push(hit_at + dur, "death", 0.06)  # the soul (A0QO) expires
            cd = _cooldown(fixed_cd[key], haste, stats, flat)
            nxt[key] = moment + cd
            next_attack = max(next_attack, busy)
            continue

        # Witch Doctor auto-attack (magic attack type).
        moment = attack_at
        recover(moment)
        white = WHITE_BASE + 0.75 * intel
        power = white + stats["damage"]
        hero_hit("Автоатака", power, moment, [0], magical=True, attack=True,
                 potency_scale=stats["attack_potency"], source_scale=stats["auto_pct"])
        gain_mana(attack_mana_gain(stats))
        if stats["fire_orb"]:
            splash = (20.0 + 0.35 * stats["int"]) * targets * taken(True) * _execute_factor(stats, moment)
            sources.add_exec("Всплеск огня", splash, moment, _execute_factor(stats, moment))
            note_damage_mana(targets)
        if sulfuras is not None:
            execute = _execute_factor(stats, moment)
            if sulfuras.attack():
                splash = stats["int"] * typed(True, moment) * taken(True) * execute * targets
                splash *= _crit_factor(crit_stat, 2.0 + stats["rating"])
                sources.add_exec("Sulfuras", splash, moment, execute)
                note_damage_mana(targets)
            echo = power * taken(True) * execute * sulfuras_echo_chance(stats["luck"])
            sources.add_exec("Sulfuras (удар)", echo, moment, execute)
        next_attack = moment + interval(moment)

    total = sum(sources.values())
    recover(FIGHT)
    mana_left = 0.0 if mana_max <= 0 else 100.0 * mana / mana_max
    return attach(Report(build, total / FIGHT, total, sources, actions, stats, targets, mana_left=mana_left))


def best_points(build: Build, targets: int, spec: str) -> tuple[float, dict[str, int]]:
    from sunken_sim.esc import apply_points, greedy_points, points_payload

    def score(pts: dict) -> float:
        trial = apply_points(build, pts)
        report = simulate(trial, targets, spec)
        return report.dps

    dps, pts = greedy_points(score)
    return dps, points_payload(pts)


