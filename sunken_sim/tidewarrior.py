"""Tidewarrior fight for Sunken City v2.5.2a, level 6.

Unit H01H (Select_*_Hero). Level 6 white stats: STR 39, AGI 19, INT 16; Amplify Damage A0HI L1
adds +5 STR / +5 AGI as bonus (green) stats. White hit 22 + 1d1 = 23 (DCS BaseDamage + 1), plus
0.75 x STR (DCS) + item damage. Attack cooldown 1.85, siege (physical, no type table on the dummy).
Primary STR. Ability rank 1. Base HP 300, base mana 120. Talents on udg_Talents_Unit[2].
Spec on A0JA (udg_Mastery_Unit = Tidewarrior): 1 Myrmidon, 2 Guardian.

Spells (rank 1, numbers from the map script):
- Tidal Strike A0BT (6 s, 10 mana, B009 4 s). Next attack: if stored crit < 25 a magical hit of
  (20 + 70 r + 2 STR) x (1 + AGI/500); else the attack gets +0.70 x [(20 + 80 r) + 2.25 STR x
  (1 + AGI/500)] (crits with it). Passive (attacks only): chance 7 + r + 0.05 AGI + 0.20 bonus
  AGI + 0.35 Mastery (+5 vs Fear From Below) for an extra 1.0 x DCS siege attack.
- Amplify Damage A0HI: each hero attack +1 stack (max 8); a murloc attack at >= 2 stacks eats 2
  and deals (20 + 25 r) + 0.25 DCS + 0.20 STR physical.
- Tail Slam A0D8 (9 s, 15 mana): 20 + 1.40 DCS + 0.60 STR magical around the hero, stun 1.5 s
  (A0ED L5, BPSE). Myrmidon: next attack +25 + 10 x 6. Guardian: +4 Amplify stacks.
- Call of the Sea A0B7 (10 s, 20 mana, 0.75 s channel): 2 permanent murlocs n03E (5 + R2I(0.30 DCS),
  cd 1.4, Sea Hunter A0K7: 30 mana, B03A 10 s, +20% crit; mana 60/60, 1 regen).
- The One From Below A089 (18 s, 30 mana, 0.75 s channel): n041 for 8 s (Guardian 10 s), four
  Phoenix Fire A0A4 (1 s): 3 + 0.15 DCS attack each; aura A09Y Fear From Below (B02R).
  Guardian: owner's non-hero units ignore 4 armor vs B02R targets.
- Serpentine Fury A0MD (12 s, 15 mana): passive +12 crit chance on every hero hit; active B02P 8 s
  +0.25 attack speed (+0.15 Myrmidon). Myrmidon: AS_Base_Reduction x 0.95.
Defensive, healing and low-HP talents are not scored.
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
from sunken_sim.ledger import Ledger, attach, score_events  # noqa: F401

WHITE_STR = int(26 + (LEVEL - 1) * 2.6)  # H01H ustr/ustp
WHITE_AGI = int(12.5 + (LEVEL - 1) * 1.3)  # uagp 1.3; lvl6 white 19 → base 12.5
WHITE_INT = int(11 + (LEVEL - 1) * 1.1)  # uint/uinp
AMPLIFY_STR = 5  # A0HI L1 Istr
AMPLIFY_AGI = 5  # A0HI L1 Iagi
BASE_STR = WHITE_STR + AMPLIFY_STR
BASE_AGI = WHITE_AGI + AMPLIFY_AGI
BASE_INT = WHITE_INT
WHITE_BASE = 23.0  # DCS BaseDamage 22 + 1
SWING = 1.85
BASE_MANA = 120.0
BASE_HP = 300.0

SPECS = ("myrmidon", "guardian")
HERO_CLASS = "Tidewarrior"
RANK = 1

TALENT_COASTAL = "I0MO"
TALENT_EVOLUTION = "I0LI"
TALENT_OCEAN_SHIELD = "I05P"
TALENT_ANGLER = "I0LN"
TALENT_RISING = "I0LK"
TALENT_SHIPWRECKER = "I0MI"
TALENT_KRAKEN = "I05R"
TALENT_MAGIC_TRIDENT = "I0LM"
TALENT_CORAL = "I05G"
TALENT_OCTOPUS = "I0LL"
TALENT_PRESSURE = "I0LJ"
TALENT_TREASURES = "I04N"
TALENT_GORLOC = "I0LH"
TALENT_AZSHARA = "I0LG"
TALENT_STORM = "I05I"
TALENT_NEXT_PAGE = "I0MD"
TALENT_PREV_PAGE = "I0MC"

TALENTS = {
    TALENT_COASTAL: "Coastal Swing",
    TALENT_EVOLUTION: "Advanced Evolution",
    TALENT_OCEAN_SHIELD: "Ocean Shield",
    TALENT_ANGLER: "Aspect of the Angler",
    TALENT_RISING: "Rising Tides",
    TALENT_SHIPWRECKER: "Shipwrecker",
    TALENT_KRAKEN: "Kraken's Lair",
    TALENT_MAGIC_TRIDENT: "Magic Trident",
    TALENT_CORAL: "Coral Trident",
    TALENT_OCTOPUS: "Aspect of the Octopus",
    TALENT_PRESSURE: "Ocean Pressure",
    TALENT_TREASURES: "Treasures of Atlantis",
    TALENT_GORLOC: "Spawn Gorloc",
    TALENT_AZSHARA: "Wrath of Azshara",
    TALENT_STORM: "Storm Trident",
}

# Ocean Shield: damage reduction. Coral Trident: heal. Kraken's Lair: procs when the Tidewarrior or
# murlocs are attacked (the dummy does not attack). Wrath of Azshara: needs <= 40% own HP.
# Pages are UI only. Spawn Gorloc is scored (Frost Armor is defensive, the Gorloc loses Sea Hunter).
IGNORED_TALENTS = frozenset({
    TALENT_OCEAN_SHIELD, TALENT_CORAL, TALENT_KRAKEN, TALENT_AZSHARA, TALENT_NEXT_PAGE, TALENT_PREV_PAGE,
})

TIDAL_CD, TIDAL_MANA, TIDAL_DUR = 6.0, 10.0, 4.0  # A0BT
TAIL_CD, TAIL_MANA, TAIL_STUN = 9.0, 15.0, 1.5  # A0D8, A0ED L5
CALL_CD, CALL_MANA = 10.0, 20.0  # A0B7
OFB_CD, OFB_MANA = 18.0, 30.0  # A089
SERP_CD, SERP_MANA, SERP_DUR = 12.0, 15.0, 8.0  # A0MD / A0MY
CHANNEL = 0.75  # ANcl Ncl1 follow-through on A0B7 / A089
SERP_PASSIVE_CRIT = 12.0
MAX_STACKS = 8
MURLOC_BASE = 5.0  # n03E ua1b 4 + 1d1
MURLOC_SWING = 1.4
MURGUL_SWING = 1.1  # n042
MURLOC_MANA_MAX = 60.0  # umpm (umpi 100 clamps to 60)
MURLOC_REGEN = 1.0  # umpr
HUNTER_MANA, HUNTER_CD, HUNTER_DUR, HUNTER_CRIT = 30.0, 5.0, 10.0, 20.0  # A0K7 / B03A
MURGUL_ARMOR, MURGUL_DUR = 2.0, 3.0  # A079
OFB_LIFE = 8.0
OFB_LIFE_GUARDIAN = 10.0
OFB_FIRES = 4  # n041 has A0A4 four times
GUARDIAN_PEN = 4.0
COASTAL_RATIO = 0.17
RELICS = frozenset({
    "I0BB", "I0QN", "I06B", "I0GQ", "I0AL", "I055", "I02T", "I0NI", "I07W", "I0HR", "I04J", "I0JO", "I06S",
})

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
        if first and bonus.get("primary") and not item.strength and not item.all_stats:
            strength += bonus["primary"]
        elif not first:
            strength += bonus.get("primary", 0)
        potency += _copy_value(item.rawcode, "potency", item.potency, first)
        mastery += _copy_value(item.rawcode, "mastery", item.mastery, first)
        damage += _copy_value(item.rawcode, "damage", item.damage, first)
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
    codes = {item.rawcode for item in build.items}
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
    if _has(build, GLYPH_UNSEALED) and GLYPH_UNSEALED not in codes:
        magic_add += 0.18
        phys_add += 0.18
    if _has(build, GLYPH_FORTUNE):
        luck += 0.15
    if _has(build, TALENT_TREASURES):
        mastery += 10.0 + 8.0 * len(codes & RELICS)
    attack_speed += min(1.0, 0.004 * agility)
    flat_cdr = 0.20 if _has(build, GLYPH_MINDHASTE) else 0.0
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
        "bonus_agi": agility - WHITE_AGI,
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
        "summon_crit": summon_crit,
        "summon_rating": summon_rating,
        "luck": luck,
        "mana_max": mana_max,
        "mana_regen": regen,
        "cast_stun_lock": cast_stun_lock,
        "hp": hp,
        **passive,
    }


def _cooldown(base: float, haste: float, stats: dict) -> float:
    return max(0.5, (base * stats["cd_temp"] - stats["flat_cdr"]) / (1.0 + haste))


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


# (Serpentine Fury active cast / skipped, Call of the Sea recast on cooldown / once)
POLICIES = tuple((serp, recall) for serp in (True, False) for recall in (False, True))


def simulate(build: Build, targets: int = 5, spec: str = "myrmidon") -> Report:
    """Best of the policies (Serpentine Fury on / off, Call of the Sea recast on / off)."""
    best = None
    for policy in POLICIES:
        report = _simulate(build, targets, spec, policy)
        if best is None or report.dps > best.dps + 1e-9:
            best = report
    return best


def _simulate(build: Build, targets: int, spec: str, policy: tuple[bool, bool]) -> Report:
    use_serp, recall = policy
    if spec not in SPECS:
        raise ValueError(spec)
    if targets < 1:
        raise ValueError(targets)
    stats = stats_of(build)
    has = lambda code: _has(build, code)  # noqa: E731
    myrm = spec == "myrmidon"
    guard = spec == "guardian"
    strength = int(stats["str"])
    agi = int(stats["agi"])
    bonus_agi = int(stats["bonus_agi"])
    intel = int(stats["int"])
    mastery = stats["mastery"]
    mana_max = stats["mana_max"]
    stored_crit = stats["crit"] + SERP_PASSIVE_CRIT  # CriticalStrike_Chance after the first hit
    pen = stats["armor_pen"]

    sources: dict[str, float] = Ledger({"Автоатака": 0.0})
    actions: list[tuple[float, str]] = []
    counters = {"tidal_proc": 0, "tidal_active": 0, "amplify": 0, "murloc_hits": 0, "ship": 0}
    mana = mana_max
    mana_time = 0.0
    sulfuras = Sulfuras() if _wears(build, "I0BR") else None
    cast_time = CAST_POINT + CAST_BACKSWING

    stun_until = [-1.0] * targets
    murgul_until = [-1.0] * targets
    fear_until = -1.0
    serp_until = -1.0
    armed = False  # B009
    tail_bonus = 0.0  # TailSlam_BonusAtkDamage (Myrmidon)
    stacks = 0
    angler = 0
    ship_count = 0
    murlocs: list[dict] = []
    ofb: dict | None = None
    proc_roll = _Dither()
    rising_roll = _Dither()
    angler_roll = _Dither()

    def recover(now: float) -> None:
        nonlocal mana, mana_time
        if now > mana_time and mana < mana_max:
            mana = min(mana_max, mana + stats["mana_regen"] * (now - mana_time))
        mana_time = now

    def gain_mana(amount: float) -> None:
        nonlocal mana
        mana = min(mana_max, mana + amount)

    def pay(cost: float, now: float) -> bool:
        nonlocal mana
        recover(now)
        if mana < cost:
            return False
        mana -= cost
        if cost > 0:
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
        return WHITE_BASE + 0.75 * strength + stats["damage"]

    def feared(now: float) -> bool:
        return fear_until > now

    def pressure(t: int, now: float) -> float:
        if not has(TALENT_PRESSURE):
            return 1.0
        if stun_until[t] > now:
            return 1.30
        if feared(now):
            return 1.10
        return 1.0

    def taken(hero: bool, t: int, now: float) -> float:
        armor = DUMMY_ARMOR
        if murgul_until[t] > now:
            armor -= MURGUL_ARMOR
        if hero:
            armor -= pen
        elif guard and feared(now):
            armor -= GUARDIAN_PEN
        return armor_taken(armor)

    def hero_hit(name: str, raw: float, now: float, tgts: list[int], *, magical: bool, attack: bool,
                 potency_scale: float = 1.0, increase: float = 0.0, forced: bool = False) -> float:
        """Hero damage; returns the amount dealt to the first target (for cleave)."""
        chance = stats["crit"] + SERP_PASSIVE_CRIT
        rating = stats["rating"]
        execute = _execute_factor(stats, now)
        kind = typed(magical, now)
        first = 0.0
        total = 0.0
        for i, t in enumerate(tgts):
            amount = (raw + stats["potency"] * potency_scale) * kind * (1.0 + increase)
            if attack:
                amount *= (2.0 + rating) if forced else _crit_factor(chance, 2.0 + rating)
            elif stats["spell_crit"]:
                amount *= _crit_factor(chance, stats["spell_mult"] + rating)
            amount *= taken(True, t, now) * execute * pressure(t, now)
            if i == 0:
                first = amount
            total += amount
        sources.add_exec(name, total, now, execute)
        note_damage_mana(len(tgts))
        return first

    def summon_hit(name: str, raw: float, now: float, t: int, *, attack: bool, extra_crit: float = 0.0) -> float:
        amount = (raw + stats["potency"]) * (1.0 + stats["pet_damage"]) * typed(False, now)
        if attack:
            amount *= _crit_factor(stats["summon_crit"] + extra_crit, 2.0 + stats["summon_rating"])
        dealt = amount * taken(False, t, now) * _execute_factor(stats, now) * pressure(t, now)
        sources.add_exec(name, dealt, now, _execute_factor(stats, now))
        return dealt

    def cleave(name: str, dealt: float) -> None:
        # Coastal Swing: ENHANCED damage (skips PreDamage_Increase), copied like the warrior cleave.
        if has(TALENT_COASTAL) and targets > 1 and dealt > 0:
            sources[name] = sources.get(name, 0.0) + dealt * COASTAL_RATIO * (targets - 1)
            note_damage_mana(targets - 1)

    def add_stacks(count: int) -> None:
        nonlocal stacks
        stacks = min(MAX_STACKS, stacks + count)

    def hero_attack(now: float, raw: float, name: str, potency_scale: float, allow_proc: bool) -> None:
        """One hero attack (real swing or Tidal Strike extra attack)."""
        nonlocal armed, tail_bonus, ship_count
        increase = 0.0
        forced = False
        if has(TALENT_SHIPWRECKER):
            ship_count += 1
            if ship_count >= 5:
                ship_count = 0
                increase = 0.01 * stored_crit
                forced = True
                counters["ship"] += 1
        if tail_bonus > 0:
            raw += tail_bonus
            tail_bonus = 0.0
        if armed:
            armed = False
            counters["tidal_active"] += 1
            if stored_crit < 25.0:
                extra = (20.0 + 70.0 * RANK + 2.0 * strength) * (1.0 + agi / 500.0)
                hero_hit("Tidal Strike", extra, now, [0], magical=True, attack=False)
            else:
                raw += 0.70 * ((20.0 + 80.0 * RANK) + 2.25 * strength * (1.0 + agi / 500.0))
                if has(TALENT_RISING) and stacks < MAX_STACKS:
                    add_stacks(2)
        dealt = hero_hit(name, raw, now, [0], magical=False, attack=True, potency_scale=potency_scale,
                         increase=increase, forced=forced)
        add_stacks(1)
        if has(TALENT_RISING) and rising_roll.roll(0.35):
            add_stacks(1)
        if has(TALENT_MAGIC_TRIDENT):
            hero_hit("Magic Trident", 15.0 + 0.20 * strength + 0.05 * mana_max, now, [0], magical=True,
                     attack=False)
        cleave("Coastal Swing", dealt)
        if allow_proc:
            chance = 7.0 + RANK + 0.05 * agi + 0.20 * bonus_agi + 0.35 * mastery
            if feared(now):
                chance += 5.0
            if proc_roll.roll(chance / 100.0):
                counters["tidal_proc"] += 1
                hero_attack(now, dcs(), "Tidal Strike (доп. атака)", 1.0, False)

    def murloc_attack(now: float, m: dict) -> None:
        nonlocal stacks, angler
        counters["murloc_hits"] += 1
        crit = (10.0 if has(TALENT_ANGLER) else 0.0) + (HUNTER_CRIT if m["hunter"] > now else 0.0)
        dealt = summon_hit("Мурлоки", m["raw"], now, 0, attack=True, extra_crit=crit)
        if m["kind"] == "murgul":
            murgul_until[0] = now + MURGUL_DUR
        if has(TALENT_ANGLER) and angler < MAX_STACKS:
            if angler_roll.roll((stats["summon_crit"] + crit) / 100.0):
                angler += 1
        if stacks >= 2:
            stacks -= 2
            counters["amplify"] += 1
            summon_hit("Amplify Damage", (20.0 + 25.0 * RANK) + 0.25 * dcs() + 0.20 * strength, now, 0,
                       attack=False)
        if has(TALENT_OCTOPUS):
            # ASSUMPTION: the training dummy has no mana (no x1.5).
            summon_hit("Aspect of the Octopus", 4.0 + 0.3 * agi + 0.3 * intel, now, 0, attack=False)
        cleave("Coastal Swing (мурлоки)", dealt)

    def murloc_tick(m: dict, now: float) -> None:
        if now > m["mana_time"]:
            m["mana"] = min(MURLOC_MANA_MAX, m["mana"] + MURLOC_REGEN * (now - m["mana_time"]))
        m["mana_time"] = now
        # ASSUMPTION: the player keeps Sea Hunter up on each murloc that has it (manual cast, self).
        if m["can_hunt"] and m["hunter"] <= now and m["hunt_ready"] <= now and m["mana"] >= HUNTER_MANA:
            m["mana"] -= HUNTER_MANA
            m["hunter"] = now + HUNTER_DUR
            m["hunt_ready"] = now + HUNTER_CD

    def spawn_murlocs(now: float) -> None:
        murlocs.clear()
        raw = MURLOC_BASE + int(0.30 * dcs())
        kinds = ["murgul" if has(TALENT_EVOLUTION) else "murloc", "gorloc" if has(TALENT_GORLOC) else "murloc"]
        for kind in kinds:
            m = {"kind": kind, "raw": raw, "next": now,
                 "swing": MURGUL_SWING if kind == "murgul" else MURLOC_SWING,
                 "mana": MURLOC_MANA_MAX, "mana_time": now, "hunter": -1.0, "hunt_ready": now,
                 "can_hunt": kind != "gorloc"}
            murloc_tick(m, now)
            murlocs.append(m)

    def attack_interval(now: float) -> float:
        swing = SWING * (1.20 if stats["galactic"] else 1.0)
        if myrm:
            swing *= 0.95
        speed = stats["attack_speed"]
        if has(TALENT_RISING):
            speed += 0.10  # Tidal Aura B03G
        if serp_until > now:
            speed += 0.25 + (0.15 if myrm else 0.0)
        speed += 0.04 * angler
        if has(TALENT_STORM):
            speed += 0.20 * (1.0 - target_hp(now))
        speed = min(4.0, max(-0.8, speed))
        return swing / (1.0 + speed)

    fixed_cd = {"call": CALL_CD, "ofb": OFB_CD, "tidal": TIDAL_CD, "tail": TAIL_CD, "serp": SERP_CD}
    cost = {"call": CALL_MANA, "ofb": OFB_MANA, "tidal": TIDAL_MANA, "tail": TAIL_MANA, "serp": SERP_MANA}
    names = {"call": "Call of the Sea", "ofb": "The One From Below", "tidal": "Tidal Strike",
             "tail": "Tail Slam", "serp": "Serpentine Fury"}
    order = ["call", "ofb", "tail", "tidal", "serp"] if use_serp else ["call", "ofb", "tail", "tidal"]
    nxt = {key: 0.0 for key in order}

    next_attack = 0.0
    busy = 0.0
    clock = 0.0
    loops = 0
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
            if key == "call" and murlocs and not recall:
                continue
            ready = max(nxt[key], busy, clock)
            if ready < cast_at - 1e-9:
                cast_at, choice = ready, key
        unit_at = min((m["next"] for m in murlocs), default=FIGHT * 10)
        ofb_at = ofb["next"] if ofb is not None and ofb["next"] < ofb["end"] else FIGHT * 10
        moment = min(attack_at, cast_at, unit_at, ofb_at)
        if moment >= FIGHT:
            break
        clock = moment

        if moment == unit_at and unit_at < attack_at and unit_at < cast_at:
            m = min(murlocs, key=lambda u: u["next"])
            murloc_tick(m, moment)
            murloc_attack(moment, m)
            m["next"] = moment + m["swing"]
            continue

        if moment == ofb_at and ofb_at < attack_at and ofb_at < cast_at:
            # ASSUMPTION: every Phoenix Fire copy fires once per second, spread over the pack.
            for k in range(OFB_FIRES):
                t = (ofb["hits"] + k) % targets
                summon_hit("The One From Below", 3.0 + 0.15 * dcs(), moment, t, attack=True)
            ofb["hits"] += OFB_FIRES
            ofb["next"] = moment + 1.0
            continue

        if cast_at <= attack_at and choice is not None and moment == cast_at:
            key = choice
            if not pay(cost[key], moment):
                nxt[key] = moment + 0.25
                continue
            hit_at = moment + CAST_POINT
            actions.append((moment, names[key]))
            busy = moment + cast_time + stats["cast_stun_lock"] + (CHANNEL if key in ("call", "ofb") else 0.0)
            if sulfuras is not None:
                sulfuras.cast()
            if key == "call":
                spawn_murlocs(hit_at)
            elif key == "ofb":
                life = OFB_LIFE_GUARDIAN if guard else OFB_LIFE
                ofb = {"next": hit_at + 1.0, "end": hit_at + life, "hits": 0}
                # ASSUMPTION: the whole pack stands inside the 300 Fear From Below aura.
                fear_until = hit_at + life
            elif key == "tidal":
                armed = True  # ASSUMPTION: B009 4 s is always consumed by the next attack
            elif key == "tail":
                # ASSUMPTION: the whole pack stands within 250 of the hero.
                tgts = list(range(targets))
                hero_hit("Tail Slam", 20.0 + 1.40 * dcs() + 0.60 * strength, hit_at, tgts, magical=True,
                         attack=False)
                for t in tgts:
                    stun_until[t] = hit_at + TAIL_STUN
                if myrm:
                    tail_bonus = 25.0 + 10.0 * LEVEL
                else:
                    stacks = MAX_STACKS if stacks >= 4 else stacks + 4
            elif key == "serp":
                serp_until = hit_at + SERP_DUR
            nxt[key] = moment + _cooldown(fixed_cd[key], stats["haste"], stats)
            next_attack = max(next_attack, busy)
            continue

        moment = attack_at
        recover(moment)
        power = dcs()
        before = sources["Автоатака"]
        hero_attack(moment, power, "Автоатака", stats["attack_potency"], True)
        if stats["auto_pct"] != 1.0:
            sources["Автоатака"] = before + (sources["Автоатака"] - before) * stats["auto_pct"]
        gain_mana(attack_mana_gain(stats))
        if stats["fire_orb"]:
            splash = (20.0 + 0.35 * strength) * targets * taken(True, 0, moment) * _execute_factor(stats, moment)
            sources.add_exec("Всплеск огня", splash, moment, _execute_factor(stats, moment))
            note_damage_mana(targets)
        if sulfuras is not None:
            execute = _execute_factor(stats, moment)
            if sulfuras.attack():
                splash = strength * typed(True, moment) * taken(True, 0, moment) * execute * targets
                splash *= _crit_factor(stored_crit, 2.0 + stats["rating"])
                sources.add_exec("Sulfuras", splash, moment, execute)
                note_damage_mana(targets)
            echo = power * taken(True, 0, moment) * execute * sulfuras_echo_chance(stats["luck"])
            sources.add_exec("Sulfuras (удар)", echo, moment, execute)
        next_attack = moment + attack_interval(moment)

    total = sum(sources.values())
    recover(FIGHT)
    mana_left = 0.0 if mana_max <= 0 else 100.0 * mana / mana_max
    stats = dict(stats)
    stats.update({f"n_{k}": float(v) for k, v in counters.items()})
    stats["angler_stacks"] = float(angler)
    stats["policy_serp"] = 1.0 if use_serp else 0.0
    stats["policy_recall"] = 1.0 if recall else 0.0
    return attach(Report(build, total / FIGHT, total, sources, actions, stats, targets, mana_left=mana_left))


def best_points(build: Build, targets: int, spec: str) -> tuple[float, dict[str, int]]:
    from sunken_sim.esc import apply_points, greedy_points, points_payload

    def score(pts: dict) -> float:
        trial = apply_points(build, pts)
        report = simulate(trial, targets, spec)
        return report.dps

    dps, pts = greedy_points(score)
    return dps, points_payload(pts)


