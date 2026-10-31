"""Necromancer fight for Sunken City v2.5.2a, level 6.

Unit O00H. Level 6 stats: STR 21, AGI 15, INT 39 (uagp is missing in the w3u, the
agility per level is assumed). White hit 13 + 1d1 = 14, plus 0.75 x INT (DCS formula).
Attack cooldown 1.85, attack type MAGIC (scored as magical attacks, as in shaman.py).
Primary INT. Ability rank is 1. Base HP 230, base mana 175.
Spec level on A0G4 (udg_Glyphs_Unit[3]): 1 Bone, 2 Blood, 3 Essence (Teeth replaces
Raise Dead). Talents sit on udg_Talents_Unit[3]. No Necromancer Global_CDs.

Spells: Grim Scythe A0I6 (6 s, 20 mana), Corpse Explosion A04A (12 s, 25 mana),
Tombstone A050 (13 s, 25 mana), Transfusion A09V (5 s, 25 mana), Raise Dead A0FR
(toggle, Bone / Blood) / Teeth A0GG (6 s, 20 mana, Essence).
Potency (Potency_Stat of the owner) is added to every damage instance from the owner,
summons included. Healing, Blood Reaper heals and Blood Rush mitigation are not scored.
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

BASE_STR = int(14 + (LEVEL - 1) * 1.4)  # O00H ustr/ustp
BASE_AGI = int(10 + (LEVEL - 1) * 1.0)  # uagi; uagp missing in w3u → 1.0 from lvl6 fit
BASE_INT = int(26 + (LEVEL - 1) * 2.6)  # uint/uinp
WHITE_BASE = 14.0  # O00H ua1b 13 + 1d1
SWING = 1.85  # O00H ua1c
BASE_MANA = 175.0
BASE_HP = 230.0

SPECS = ("bone", "blood", "essence")
HERO_CLASS = "Necromancer"
RANK = 1

TALENT_BLOOD_BOMB = "I09Q"
TALENT_SWIFT_HARVEST = "I0LC"
TALENT_SANGUINE_FURY = "I0L8"
TALENT_GRAVEDIGGER = "I0LA"
TALENT_SKELETAL_ARCHER = "I0LB"
TALENT_ESSENCE_FROM_BLOOD = "I0LD"
TALENT_SERRATION = "I0L9"
TALENT_REAPER_OF_SOULS = "I0LF"
TALENT_EXECUTORS_SWING = "I086"
TALENT_BLOOD_REAPER = "I05T"
TALENT_HOUR_OF_THE_DEAD = "I0FI"
TALENT_LIFE_FROM_DEATH = "I0LE"
TALENT_BLOOD_SACRIFICE = "I057"
TALENT_CALL_OF_THE_GRAVE = "I0OK"
TALENT_DARK_BARGAIN = "I0OL"
TALENT_BLOODY_SCYTHE = "I0OM"
TALENT_LORD_OF_THE_DEAD = "I05Z"
TALENT_BLOOD_RUSH = "I078"
TALENT_NEXT_PAGE = "I0MD"
TALENT_PREV_PAGE = "I0MC"

TALENTS = {
    TALENT_BLOOD_BOMB: "Blood Bomb",
    TALENT_SWIFT_HARVEST: "Swift Harvest",
    TALENT_SANGUINE_FURY: "Sanguine Fury",
    TALENT_GRAVEDIGGER: "Gravedigger",
    TALENT_SKELETAL_ARCHER: "Skeletal Archer",
    TALENT_ESSENCE_FROM_BLOOD: "Essence from Blood",
    TALENT_SERRATION: "Serration",
    TALENT_REAPER_OF_SOULS: "Reaper of Souls",
    TALENT_EXECUTORS_SWING: "Executor's Swing",
    TALENT_BLOOD_REAPER: "Blood Reaper",
    TALENT_HOUR_OF_THE_DEAD: "Hour of the Dead",
    TALENT_LIFE_FROM_DEATH: "Life from Death",
    TALENT_BLOOD_SACRIFICE: "Blood Sacrifice",
    TALENT_CALL_OF_THE_GRAVE: "Call of the Grave",
    TALENT_DARK_BARGAIN: "Dark Bargain",
    TALENT_BLOODY_SCYTHE: "Bloody Scythe",
    TALENT_LORD_OF_THE_DEAD: "Lord of the Dead",
}

# Pages are UI; Blood Rush is damage reduction only (a dummy deals no damage).
IGNORED_TALENTS = frozenset({TALENT_NEXT_PAGE, TALENT_PREV_PAGE, TALENT_BLOOD_RUSH})

GS_CD, GS_MANA = 6.0, 20.0  # A0I6
CE_CD, CE_MANA = 12.0, 25.0  # A04A
TOMB_CD, TOMB_MANA = 13.0, 25.0  # A050
TRANS_CD, TRANS_MANA = 5.0, 25.0  # A09V
TEETH_CD, TEETH_MANA = 6.0, 20.0  # A0GG
GS_DELAY = 0.20  # PolledWait in Grim Scythe cast
SWIFT_AS, SWIFT_DUR = 0.30, 4.0  # A0E7 -> B06N
SPECTRAL_DUR = 4.0  # A031 -> B04D on RaiseDead_Group
GLOBE_DUR = 6.0  # B076
SANGUINE_AS = 0.23
SKELETON_LIFE = 11.0  # 14 with Hour of the Dead
SWINGS = {"warrior": 1.8, "assassin": 1.53, "executor": 1.8, "mage": 1.8, "archer": 1.2}
UNIT = {"warrior": "u008", "assassin": "u005", "executor": "u004", "mage": "u006", "archer": "n05K"}

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
ITEM_TOMB_EXTRA = "I0R5"  # Tombstone +1 skeleton
ITEM_GLOBE_EXTRA = "I0R6"  # Transfusion +1 globe
ITEM_SCYTHE_PASSIVE = "I0R7"  # Grim Scythe active: 50% x luck passive per enemy hit
ITEM_CE_CD = "I0R8"  # Corpse Explosion cooldown -2 s
ITEM_CE_TICK = "I0UN"  # Corpse Explosion +1 tick


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
    # Summon crit block (PreDamage_Increase): base 0 %, x2.0.
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
        "tomb_extra": 1.0 if ITEM_TOMB_EXTRA in codes else 0.0,
        "globe_extra": 1.0 if ITEM_GLOBE_EXTRA in codes else 0.0,
        "scythe_passive": 1.0 if ITEM_SCYTHE_PASSIVE in codes else 0.0,
        "ce_flat": 2.0 if ITEM_CE_CD in codes else 0.0,
        "ce_tick": 1.0 if ITEM_CE_TICK in codes else 0.0,
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
        self.acc += max(0.0, min(1.0, chance))
        if self.acc >= 1.0 - 1e-9:
            self.acc -= 1.0
            return True
        return False


# (transfusion, raise_dead): cast Transfusion on self for globes; keep Raise Dead on.
POLICIES = tuple((trans, raise_dead) for trans in (True, False) for raise_dead in (True, False))


def simulate(build: Build, targets: int = 5, spec: str = "bone") -> Report:
    """Best of the policies (Transfusion on / off, Raise Dead on / off)."""
    best = None
    for policy in POLICIES:
        if spec == "essence" and not policy[1]:
            continue  # no Raise Dead in Essence
        report = _simulate(build, targets, spec, policy)
        if best is None or report.dps > best.dps + 1e-9:
            best = report
    return best


def _simulate(build: Build, targets: int, spec: str, policy: tuple[bool, bool]) -> Report:
    use_trans, use_raise = policy
    if spec not in SPECS:
        raise ValueError(spec)
    if targets < 1:
        raise ValueError(targets)
    stats = stats_of(build)
    luck_mult = 1.0 + stats["luck"]
    has = lambda code: _has(build, code)  # noqa: E731
    bone, blood, essence = spec == "bone", spec == "blood", spec == "essence"
    use_raise = use_raise and not essence
    intel = int(stats["int"])
    mastery = int(stats["mastery"])
    hp_max = stats["hp"]
    mana_max = stats["mana_max"]
    hero_taken = armor_taken(DUMMY_ARMOR - stats["armor_pen"])
    summon_taken = armor_taken(DUMMY_ARMOR)
    pen_taken = armor_taken(DUMMY_ARMOR - 8.0)  # A042: 8 armor penetration

    sources: dict[str, float] = {"Автоатака": 0.0}
    actions: list[tuple[float, str]] = []
    mana = mana_max
    mana_time = 0.0
    hp = hp_max
    sulfuras = Sulfuras() if _wears(build, "I0BR") else None
    cast_time = CAST_POINT + CAST_BACKSWING

    last_gs = 0.0  # GrimScythe_PassiveDamage (global, starts at 0)
    swift_until = -1.0
    globe_until = -1.0
    teeth_lvl = 1  # A0AS level
    rd_ticks = 0
    guard_ce = False
    archer_roll = _Dither()
    skeletons: list[dict] = []
    tombs: list[float] = []  # expiry times
    pending: list[tuple[float, int, str, float]] = []  # (time, seq, kind, arg)
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

    def lose_hp(amount: float) -> None:
        nonlocal hp
        hp = max(1.0, hp - amount)

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

    def sacrifice(magical: bool, count: float) -> float:
        """Blood Sacrifice I057: +0.5% max HP per instance (x1.25 magical) while HP > 25%."""
        if not has(TALENT_BLOOD_SACRIFICE) or hp <= 0.25 * hp_max:
            return 0.0
        lose_hp(0.005 * hp_max * count)
        return 0.005 * hp_max * (1.25 if magical else 1.0)

    def ce_proc(count: float, now: float) -> None:
        """Corpse Explosion passive: 1.5% (3% Blood) x luck per owner damage instance."""
        if guard_ce or count <= 0:
            return
        chance = _chance((3.0 if blood else 1.5) / 100.0 * luck_mult)
        explode(now, None, chance * count)

    def explosion_raw() -> float:
        value = 20.0 * RANK + 0.35 * intel + 0.01 * hp_max
        if blood:
            value *= 1.10 + 0.005 * mastery
        return value

    def explode(now: float, dealer: str | None, weight: float, name: str = "Corpse Explosion (пассив)") -> None:
        """One Corpse Explosion passive (AoE 350, magical) by the Necromancer or a summon."""
        nonlocal guard_ce
        if weight <= 0:
            return
        was = guard_ce
        guard_ce = True  # CorpseExp_Running: no chain procs
        if dealer is None:
            hero_hit(name, explosion_raw(), now, magical=True, attack=False, count=targets * weight)
        else:
            summon_hit(name, explosion_raw(), now, magical=True, attack=False, count=targets * weight)
        guard_ce = was

    def hero_hit(name: str, raw: float, now: float, *, magical: bool, attack: bool, count: float = 1.0,
                 potency_scale: float = 1.0) -> float:
        """Damage dealt by the Necromancer. Returns dealt per instance."""
        amount = raw + stats["potency"] * potency_scale
        amount += sacrifice(magical, count)
        amount *= typed(magical, now)
        if has(TALENT_BLOOD_REAPER):
            amount *= 0.88
        if attack:
            amount *= _crit_factor(stats["crit"], 2.0 + stats["rating"])
        elif stats["spell_crit"]:
            amount *= _crit_factor(stats["crit"], stats["spell_mult"] + stats["rating"])
        dealt = amount * hero_taken * _execute_factor(stats, now)
        sources[name] = sources.get(name, 0.0) + dealt * count
        note_damage_mana(count)
        ce_proc(count, now)
        return dealt

    def summon_hit(name: str, raw: float, now: float, *, magical: bool, attack: bool, count: float = 1.0,
                   crit_bonus: float = 0.0, pen_share: float = 0.0, depth: int = 0) -> float:
        """Damage dealt by a summon / tombstone: potency, Blood Sacrifice, Pet Damage, summon crit."""
        amount = raw + stats["potency"] + sacrifice(magical, count)
        amount *= 1.0 + stats["pet_damage"]
        if attack:
            amount *= _crit_factor(stats["summon_crit"] + crit_bonus, 2.0 + stats["summon_rating"])
        taken = pen_share * pen_taken + (1.0 - pen_share) * summon_taken
        dealt = amount * taken * _execute_factor(stats, now)
        sources[name] = sources.get(name, 0.0) + dealt * count
        ce_proc(count, now)
        if has(TALENT_SERRATION) and depth < 3:
            chance = _chance(0.05 * luck_mult) * count
            summon_hit("Serration", 15.0 * RANK + 0.75 * dcs(), now, magical=False, attack=False,
                       count=chance, depth=depth + 1)
        return dealt

    def gs_passive(count: float, now: float) -> None:
        """Grim Scythe passive on Necromancer attack damage (magical, per target)."""
        nonlocal last_gs, mana
        raw = 10.0 + 10.0 * RANK + 0.55 * intel
        recover(now)
        if has(TALENT_REAPER_OF_SOULS) and mana > 0.20 * mana_max:
            raw += 0.02 * mana_max
            mana = max(0.0, mana - 0.002 * mana_max * count)
        if essence:
            raw *= 1.10 + 0.01 * mastery
        if has(TALENT_EXECUTORS_SWING):
            raw *= 1.10
        last_gs = raw
        hero_hit("Grim Scythe (пассив)", raw, now, magical=True, attack=False, count=count)

    def dcs() -> float:
        return WHITE_BASE + 0.75 * intel + stats["damage"]

    def skeleton_raw() -> float:
        return 6.0 + int(4.0 * RANK + 0.20 * dcs())  # 5 + 1d1, + R2I(4 x Tomb lvl + 0.20 x DCS)

    def spawn(kind: str, now: float) -> None:
        life = SKELETON_LIFE + (3.0 if has(TALENT_HOUR_OF_THE_DEAD) else 0.0)
        pen = _chance((5.0 + mastery) / 100.0) if bone else 0.0
        skeletons.append({"kind": kind, "next": now, "end": now + life, "group": kind != "mage",
                          "pen": pen, "spectral": -1.0})
        if has(TALENT_SKELETAL_ARCHER) and archer_roll.roll(0.25 * luck_mult):
            skeletons.append({"kind": "archer", "next": now, "end": now + life, "group": True,
                              "pen": pen, "spectral": -1.0})

    def haste_now() -> float:
        return stats["haste"]

    def interval(now: float) -> float:
        swing = SWING * (1.20 if stats["galactic"] else 1.0)
        speed = stats["attack_speed"] + 0.08 * (teeth_lvl - 1)
        if now < swift_until:
            speed += SWIFT_AS
        if has(TALENT_SANGUINE_FURY) and now < globe_until:
            speed += SANGUINE_AS
        speed = min(4.0, max(-0.8, speed))
        return swing / (1.0 + speed)

    def tomb_first(count: int) -> float:
        return (1.80 - 0.20 * RANK) / (1.0 + (0.35 if count > 1 else 0.0))

    def tomb_period(count: int) -> float:
        rate = 1.0 + (0.5 if count > 1 else 0.0)
        if has(TALENT_CALL_OF_THE_GRAVE):
            rate += 0.35 + 0.05 * stats["potency"]
        return 1.5 / rate

    fixed_cd = {"gs": GS_CD, "ce": CE_CD, "tomb": TOMB_CD, "trans": TRANS_CD, "teeth": TEETH_CD}
    cost = {"gs": GS_MANA, "ce": CE_MANA, "tomb": TOMB_MANA, "trans": TRANS_MANA, "teeth": TEETH_MANA}
    names = {"gs": "Grim Scythe", "ce": "Corpse Explosion", "tomb": "Tombstone",
             "trans": "Transfusion", "teeth": "Teeth"}
    order = ["tomb", "ce", "gs"] + (["teeth"] if essence else []) + (["trans"] if use_trans else [])
    nxt = {key: 0.0 for key in order}
    full_cd = {key: 0.0 for key in order}
    tomb_timer = FIGHT * 10
    if use_raise:
        push(1.0 / (1.0 + haste_now()), "rd")

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
        skeletons[:] = [s for s in skeletons if s["end"] > clock - 1e-9]
        live = [s for s in skeletons if s["next"] < s["end"]]
        summon_at = min((s["next"] for s in live), default=FIGHT * 10)
        moment = min(attack_at, cast_at, pending_at, summon_at, tomb_timer)
        if moment >= FIGHT:
            break
        clock = moment
        if moment == pending_at:
            event = min(pending)
            pending.remove(event)
            _, _, kind, arg = event
            if kind == "rd":
                recover(moment)
                if mana >= 2.0 + 1.5 * RANK and pay(2.0 + 1.5 * RANK, moment, refund=False):
                    rd_ticks += 1
                need = 4 if bone else 6
                while rd_ticks >= need:
                    rd_ticks -= need
                    spawn("warrior", moment)
                push(moment + 1.0 / (1.0 + haste_now()), "rd")
            elif kind == "gs":
                raw = 60.0 * RANK - 20.0 + 1.5 * intel + 0.04 * hp_max
                if has(TALENT_EXECUTORS_SWING):
                    raw *= 1.20
                hero_hit("Grim Scythe", raw, moment, magical=True, attack=False, count=targets)
                if stats["scythe_passive"]:
                    gs_passive(targets * _chance(0.50 * luck_mult), moment)
                if has(TALENT_BLOODY_SCYTHE):
                    explode(moment, None, _chance(0.60 * luck_mult), "Bloody Scythe (взрыв)")
                if has(TALENT_SWIFT_HARVEST):
                    swift_until = moment + SWIFT_DUR
                for s in skeletons:
                    if s["group"]:
                        s["spectral"] = moment + SPECTRAL_DUR
            elif kind == "ce":
                explode(moment, None, 1.0, "Corpse Explosion")
            continue
        if moment == tomb_timer:
            alive = [t for t in tombs if t > moment]
            tombs[:] = alive
            if not alive:
                tomb_timer = FIGHT * 10
                continue
            raw = 8.0 * RANK + 0.01 * hp_max + 0.01 * mana_max
            if bone:
                summon_hit("Tombstone (аура)", raw, moment, magical=False, attack=False, count=targets)
            else:
                hero_hit("Tombstone (аура)", raw, moment, magical=False, attack=False, count=targets)
            tomb_timer = moment + tomb_period(len(alive))
            continue
        if moment == summon_at and summon_at < attack_at and summon_at < cast_at:
            s = min(live, key=lambda u: u["next"])
            kind = s["kind"]
            raw = skeleton_raw()
            if moment < s["spectral"]:
                raw += 0.15 * last_gs
            magical = kind == "mage"
            label = {"warrior": "Скелеты (Raise Dead/Tombstone)", "archer": "Skeletal Archer",
                     "assassin": "Assassin (Lord)", "executor": "Executor (Lord)", "mage": "Mage (Lord)"}[kind]
            dealt = summon_hit(label, raw, moment, magical=magical, attack=True,
                               crit_bonus=50.0 if kind == "assassin" else 0.0, pen_share=s["pen"])
            if kind == "executor":
                hero_hit("Executor (эхо)", 0.75 * dealt, moment, magical=True, attack=True)
                gs_passive(1.0, moment)
            if kind == "mage" and "ce" in nxt and nxt["ce"] > moment:
                nxt["ce"] = max(moment, nxt["ce"] - 0.5)
            s["next"] = moment + SWINGS[kind]
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
            haste = haste_now()
            if has(TALENT_DARK_BARGAIN):
                haste += 0.05 + 0.01 * ((100.0 - 100.0 * hp / hp_max) / 2.0)
            if key == "gs":
                push(hit_at + GS_DELAY, "gs")
            elif key == "ce":
                lose_hp(0.08 * hp)
                ticks = 3 + (1 if blood else 0) + int(stats["ce_tick"])
                for i in range(ticks):
                    push(hit_at + (i + 1) * 1.2 / ticks, "ce")
                if has(TALENT_BLOOD_BOMB):
                    group = sorted((s for s in skeletons if s["group"]), key=lambda u: u["end"])
                    for s in group[:3]:
                        skeletons.remove(s)
                        explode(hit_at, UNIT[s["kind"]], 1.0, "Blood Bomb (взрыв скелета)")
            elif key == "tomb":
                tombs.append(hit_at + (13.0 if has(TALENT_GRAVEDIGGER) else 10.0))
                tombs[:] = [t for t in tombs if t > hit_at]
                tomb_timer = hit_at + tomb_first(len(tombs))
                count = (3 if has(TALENT_GRAVEDIGGER) else 2) + int(stats["tomb_extra"])
                for _ in range(count):
                    spawn("warrior", hit_at)
                if has(TALENT_LORD_OF_THE_DEAD):
                    spawn({"bone": "assassin", "blood": "mage", "essence": "executor"}[spec], hit_at)
            elif key == "teeth":
                lose_hp(0.08 * hp)
                raw = 20.0 + 0.80 * intel + 0.05 * hp_max
                hero_hit("Teeth", raw, hit_at, magical=False, attack=True, count=targets)
                gs_passive(float(targets), hit_at)
                heal(0.04 * hp_max * targets)
                teeth_lvl = min(7, teeth_lvl + targets)
            elif key == "trans":
                globes = 1 + int(stats["globe_extra"])
                for _ in range(globes):
                    heal(0.15 * hp_max)
                    globe_until = hit_at + GLOBE_DUR
                    if has(TALENT_ESSENCE_FROM_BLOOD):
                        gain_mana(0.05 * mana_max)
                        for other in order:
                            if nxt[other] > hit_at:
                                nxt[other] = max(hit_at, nxt[other] - 0.06 * full_cd[other])
                    if has(TALENT_LIFE_FROM_DEATH) and use_raise:
                        rd_ticks += 2
            cd = _cooldown(fixed_cd[key], haste, stats, stats["ce_flat"] if key == "ce" else 0.0)
            full_cd[key] = cd
            nxt[key] = max(nxt[key], moment + cd) if key != "trans" else moment + cd
            next_attack = max(next_attack, busy)
            continue

        # Necromancer auto-attack (magic attack type).
        moment = attack_at
        recover(moment)
        power = dcs()
        before = sources["Автоатака"]
        hero_hit("Автоатака", power, moment, magical=True, attack=True, potency_scale=stats["attack_potency"])
        if stats["auto_pct"] != 1.0:
            sources["Автоатака"] = before + (sources["Автоатака"] - before) * stats["auto_pct"]
        gs_passive(1.0, moment)
        gain_mana(attack_mana_gain(stats))
        if stats["fire_orb"]:
            splash = (20.0 + 0.35 * stats["int"]) * targets * hero_taken * _execute_factor(stats, moment)
            sources["Всплеск огня"] = sources.get("Всплеск огня", 0.0) + splash
            note_damage_mana(targets)
        if sulfuras is not None:
            execute = _execute_factor(stats, moment)
            if sulfuras.attack():
                splash = stats["int"] * typed(True, moment) * hero_taken * execute * targets
                splash *= _crit_factor(stats["crit"], 2.0 + stats["rating"])
                sources["Sulfuras"] = sources.get("Sulfuras", 0.0) + splash
                note_damage_mana(targets)
            echo = power * hero_taken * execute * sulfuras_echo_chance(stats["luck"])
            sources["Sulfuras (удар)"] = sources.get("Sulfuras (удар)", 0.0) + echo
        next_attack = moment + interval(moment)

    total = sum(sources.values())
    recover(FIGHT)
    mana_left = 0.0 if mana_max <= 0 else 100.0 * mana / mana_max
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


