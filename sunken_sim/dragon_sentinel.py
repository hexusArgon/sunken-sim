"""Dragon Sentinel fight for Sunken City v2.5.2a, level 6.

Unit O00P (base Obla: attack cooldown 2.00, melee 80, hero attack). Level 6 white stats:
STR 27 + 2.7 x 5 = 40, AGI 9 + 0.9 x 5 = 13, INT 14 + 1.4 x 5 = 21; Attribute Bonus A0F6 L1 adds
+4 STR / +4 INT. White hit 13 + 1d1 = 14 (DCS BaseDamage + 1), plus 0.75 x STR + item damage.
Armor udef 4 + 0.1 x AGI. HP 300, mana 120 + 7 x INT. Ability rank 1.
Spec: A0O6 level on udg_Glyphs_Unit[2]: 1 Ruby, 2 Obsidian, 3 Emerald.
Dragon Form A0HW morphs: O007 Ruby, O015 Obsidian (udef 12), O01Q Emerald; all chaos attack.

Numbers come from war3map.j and the w3u/w3a object data (see docs/dragon_sentinel.md):
- Burnout A00B (8 s, 20 mana; replaced by Cleansing Fire in Emerald): 25 + 1.2 STR per hit,
  Burnout_Triggers = 2 hits per enemy in 200, magical. Ruby x(1.05 + 0.005 M), Ruby Dragon Form
  x(1 + 0.05 + 0.002 STR), Dragonplate Gauntlets I0TK x1.25, Worldbreaker (Ruby, hero cast) 3rd hit
  x0.60. Dragon Form: cooldown -2 s.
  Passive: any non-disease DS damage has (1 + bonus)% x Luck (x1.15 Legacy) to fire Burnout from
  Dummies_Burnout at x0.40, DISEASE type (no procs). Ruby: +0.5% bonus per spellcast until it procs.
  Crit attacks: 33% x Luck to fire Burnout from Dummies_BlazingStrikes at full damage (no I0TF check).
- Dragon Strike A0OB (7 s, 15 mana): 60 + 0.03 x max HP magical to every enemy in the line,
  Dragonfire B02B 5 s. Dragon Form x1.25 and Dragon Claw B06C; Ruby Form x(1 + RubyBonus).
- Blazing Shield A0O1 (8 s, 10 mana): (50 + 1.1 STR) x (1 + 0.03 armor) magical, one target; Ruby
  Form x(1 + RubyBonus), Heated Shield x1.25. Molten Armor B03K: +2 armor 5 s (+3 / +2 s Earthen
  Crust).
- Lifebinder A0N5 (7 s, 15 mana): self buff 6 s (+6 s Form, +2 s Alexstrasza's Gift), tick every
  1 / (1 + Gift of Life 0.15 + 0.008 P + Lifebinder's Helm 0.25) s. Healing only matters through
  Alexstrasza's Gift (x1.10 damage), Burning Heart (5 + 3 x level per tick in 250) and Emerald's
  heal proc.
- Cleansing Fire A0OO (Emerald; 8 s, 20 mana): B08M 4 s, global 1 s tick, 7 + 0.01 x max HP.
  Every DS heal on a hero: 8% x Luck to deal 4 x that to a random enemy.
- Dragon Form A0HW (3 s, 0 mana, 12 s): needs full Dragonfury (100, 85 with Waking Dragon). +1 every
  1 / (1 + haste) s (/(1 + 0.01 M) Dragonborn, /1.2 Eye of Wyrmrest), +1 on 2% x Luck per damage
  instance, Obsidian +3 per spellcast. Ruby bolts 25 every 0.5 s.
- Obsidian: Branded on unbranded targets for 3 s, armor -R2I(1 + 0.08 armor) (max 6).
Defensive, healing-only, CC and enemy-attack talents are not scored.
"""

from __future__ import annotations

import heapq
import re

from sunken_sim.pressure import AGI_ARMOR, max_hp
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

WHITE_STR = 40  # O00P level 6: 27 + 2.7 x 5
WHITE_AGI = 13  # 9 + 0.9 x 5
WHITE_INT = 21  # 14 + 1.4 x 5
ATTR_STR = 4  # A0F6 L1 Istr
ATTR_INT = 4  # A0F6 L1 Iint
BASE_STR = WHITE_STR + ATTR_STR
BASE_AGI = WHITE_AGI
BASE_INT = WHITE_INT + ATTR_INT
WHITE_BASE = 14.0  # DCS BaseDamage 13 + 1
SWING = 2.00  # O00P ua1c
BASE_MANA = 120.0
BASE_HP = 300.0
BASE_ARMOR = 4.0  # O00P udef
OBSIDIAN_FORM_ARMOR = 8.0  # O015 udef 12 - 4
SCALES_ARMOR = 3.0  # A0O9 L2 (Draconic Scales)

SPECS = ("ruby", "obsidian", "emerald")
SPEC_LEVEL = {"ruby": 1, "obsidian": 2, "emerald": 3}
HERO_CLASS = "DragonSentinel"
RANK = 1

TALENT_YSERA = "I0JE"
TALENT_PACIFY = "I0MF"
TALENT_WORLDBREAKER = "I0QJ"
TALENT_DRAGONBORN = "I0LV"
TALENT_EARTHEN = "I0LU"
TALENT_SCALES = "I0JF"
TALENT_BACKFIRE = "I0HQ"
TALENT_GIFT_OF_LIFE = "I0QH"
TALENT_MELTING = "I0B0"
TALENT_NEXT_PAGE = "I0MD"
TALENT_HEATED = "I0TG"
TALENT_ENGULFING = "I0QI"
TALENT_ALEXSTRASZA = "I0LT"
TALENT_BURNING_HEART = "I0LW"
TALENT_WAKING = "I0QK"
TALENT_EXPLOSIVE = "I0QL"
TALENT_LEGACY = "I0TE"
TALENT_BLAZING_STRIKES = "I0TF"
TALENT_LIFEBLOSSOM = "I0MQ"
TALENT_PREV_PAGE = "I0MC"

TALENTS = {
    TALENT_YSERA: "Ysera's Gift",
    TALENT_PACIFY: "Pacify",
    TALENT_WORLDBREAKER: "Worldbreaker",
    TALENT_DRAGONBORN: "Dragonborn",
    TALENT_EARTHEN: "Earthen Crust",
    TALENT_SCALES: "Draconic Scales",
    TALENT_BACKFIRE: "Backfire",
    TALENT_GIFT_OF_LIFE: "Gift of Life",
    TALENT_MELTING: "Melting Flames",
    TALENT_HEATED: "Heated Shield",
    TALENT_ENGULFING: "Engulfing Flames",
    TALENT_ALEXSTRASZA: "Alexstrasza's Gift",
    TALENT_BURNING_HEART: "Burning Heart",
    TALENT_WAKING: "Waking Dragon",
    TALENT_EXPLOSIVE: "Explosive Impact",
    TALENT_LEGACY: "Legacy of the Aspects",
    TALENT_BLAZING_STRIKES: "Blazing Strikes",
    TALENT_LIFEBLOSSOM: "Lifeblossom",
}

IGNORED_TALENTS = frozenset({TALENT_YSERA, TALENT_PACIFY, TALENT_BACKFIRE, TALENT_LIFEBLOSSOM,
                             TALENT_NEXT_PAGE, TALENT_PREV_PAGE})
IGNORED_REASONS = {
    TALENT_YSERA: "лечение самого раненого союзного героя (только если его HP < 100%, сам DS исключён)",
    TALENT_PACIFY: "контроль (CC), урона нет",
    TALENT_BACKFIRE: "урон только когда враг под Dragonfire атакует — пустышка не атакует",
    TALENT_LIFEBLOSSOM: "лечение / раздача Lifebinder союзникам, урона нет",
    TALENT_NEXT_PAGE: "страница талантов (UI)",
    TALENT_PREV_PAGE: "страница талантов (UI)",
}

ITEM_EYE = "I0TI"  # Eye of Wyrmrest: Dragonfury generation x1.2
ITEM_HELM = "I0TH"  # Lifebinder's Helm: Lifebinder tick rate +0.25
ITEM_GUARD = "I0TJ"  # Blazewing Guard: Molten Armor damage reduction (defensive)
ITEM_GAUNTLETS = "I0TK"  # Dragonplate Gauntlets: Burnout x1.25
ITEM_DRAKE_SWORD = "I0TL"  # Drake Sword: attacks 15% (30% on crit) x Luck -> Dragon Strike

BURNOUT_CD, BURNOUT_MANA, BURNOUT_FORM_CDR = 8.0, 20.0, 2.0  # A00B, CDR_Flat_Str[2]
BURNOUT_DELAY = 0.5  # ASSUMPTION: farsight-point projectile, short flight
STRIKE_CD, STRIKE_MANA = 7.0, 15.0  # A0OB
SHIELD_CD, SHIELD_MANA = 8.0, 10.0  # A0O1
LIFE_CD, LIFE_MANA, LIFE_DUR = 7.0, 15.0, 6.0  # A0N5 / A0N0
CLEANSE_CD, CLEANSE_MANA, CLEANSE_DUR = 8.0, 20.0, 4.0  # A0OO / A0OT B08M
FORM_CD, FORM_DUR = 3.0, 12.0  # A0HW
DRAGONFIRE_DUR = 5.0
BRANDED_DUR, BRANDED_CAP = 3.0, 6  # A0QT L1
MOLTEN_DUR, MOLTEN_ARMOR = 5.0, 2.0  # B03K, 1 + level
BOLT_EVERY, BOLT_DAMAGE = 0.5, 25.0  # A0OA pxf1 25; 2 per second per the tooltip
ENGULF_PERIOD = 1.5
LEGACY = 1.15  # udg_LegacyAspects_Value
LEGACY_CDR = 0.75

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
    armor_items = 0.0
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
            armor_items += float(getattr(item, "armor", 0) or 0)
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
    if _has(build, TALENT_DRAGONBORN):
        mastery += 10  # Mastery_Gain I0LV
    if _has(build, TALENT_BLAZING_STRIKES):
        attack_speed += 0.20  # Attack_Speed_Gain I0TF
        crit += 5.0  # Critical_Gain I0TF
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
        "armor": BASE_ARMOR + AGI_ARMOR * agility + armor_items + (SCALES_ARMOR if _has(build, TALENT_SCALES) else 0.0),
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


# (Lifebinder on self cast / skipped, Dragon Form used / not used)
POLICIES = tuple((life, form) for life in (True, False) for form in (True, False))


def simulate(build: Build, targets: int = 5, spec: str = "ruby") -> Report:
    """Best of the policies (Lifebinder on self on / off, Dragon Form on / off)."""
    best = None
    for policy in POLICIES:
        report = _simulate(build, targets, spec, policy)
        if best is None or report.dps > best.dps + 1e-9:
            best = report
    return best


def _simulate(build: Build, targets: int, spec: str, policy: tuple[bool, bool]) -> Report:
    use_life, use_form = policy
    if spec not in SPECS:
        raise ValueError(spec)
    if targets < 1:
        raise ValueError(targets)
    stats = stats_of(build)
    has = lambda code: _has(build, code)  # noqa: E731
    wears = lambda code: _wears(build, code)  # noqa: E731
    ruby = spec == "ruby"
    obsidian = spec == "obsidian"
    emerald = spec == "emerald"
    has_burnout = not emerald  # A00B is swapped for A0OO in Emerald
    strength = int(stats["str"])
    mastery = stats["mastery"]
    mana_max = stats["mana_max"]
    pen = stats["armor_pen"]
    max_life = stats["hp"]
    cast_time = CAST_POINT + CAST_BACKSWING
    all_t = list(range(targets))

    sources: dict[str, float] = {"Автоатака": 0.0}
    actions: list[tuple[float, str]] = []
    counters = {"burnout_passive": 0, "burnout_crit": 0, "drake": 0, "form": 0, "branded": 0,
                "heal_proc": 0, "legacy": 0, "life_ticks": 0, "bolts": 0, "fury_luck": 0}
    mana = mana_max
    mana_time = 0.0
    sulfuras = Sulfuras() if _wears(build, "I0BR") else None

    events: list = []
    seq = [0]

    def push(at: float, kind: str, data=None) -> None:
        seq[0] += 1
        heapq.heappush(events, (at, seq[0], kind, data))

    fire_until = [-1.0] * targets  # Dragonfire B02B
    claw_until = [-1.0] * targets  # Dragon Claw B06C
    brand_until = [-1.0] * targets
    brand_value = [0] * targets
    cleanse_until = [-1.0] * targets
    molten_until = -1.0
    life_until = -1.0
    life_ticking = False
    form_until = -1.0
    heated = False
    burnout_bonus = 0.0
    burnout_triggers = 0  # udg_Burnout_Triggers starts at 0
    fury = 0.0
    fury_max = 85.0 if has(TALENT_WAKING) else 100.0
    bolt_target = [0]
    rolls = {k: _Dither() for k in ("burnout", "crit_burnout", "drake", "fury", "cf_dmg", "cf_heal")}

    def luck_mult() -> float:
        return 1.0 + stats["luck"]

    def in_form(now: float) -> bool:
        return form_until > now

    def armor(now: float) -> float:
        value = stats["armor"]
        if obsidian and in_form(now):
            value += OBSIDIAN_FORM_ARMOR
        if molten_until > now:
            value += MOLTEN_ARMOR + (3.0 if has(TALENT_EARTHEN) else 0.0)
        return value

    def potency(now: float) -> float:
        value = stats["potency"]
        if has(TALENT_SCALES):
            value += 0.5 * armor(now)  # Potency_Tooltip: Potency_Bonus + 0.5 x armor
        return value

    def ruby_bonus() -> float:
        return 0.05 + 0.20 * strength / 100.0  # DragonForm_RubyBonus

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

    def typed(kind: str | None, now: float) -> float:
        bonus = 1.0
        if kind == "magical":
            bonus += stats["magic_add"]
        elif kind == "physical":
            bonus += stats["phys_add"]
        if stats["sulfuron"]:
            bonus += 0.13 + 0.25 * target_hp(now)
        if kind == "magical" and stats["spellbinder"]:
            bonus += 0.05 + 0.005 * mastery
        if stats["glass"]:
            bonus *= 1.15
        return bonus

    def dcs() -> float:
        return WHITE_BASE + 0.75 * strength + stats["damage"]

    def taken(t: int, now: float) -> float:
        reduce = brand_value[t] if brand_until[t] > now else 0
        return armor_taken(DUMMY_ARMOR - pen - reduce)

    def melting(t: int, now: float) -> float:
        """Melting Flames I0B0: flat bonus per damage instance on Dragonfire / Dragon Claw targets."""
        if not has(TALENT_MELTING):
            return 0.0
        flat = 0.0
        if fire_until[t] > now:
            flat += 5.0 + (0.004 * max_life if ruby else 0.0)
        if claw_until[t] > now:
            flat += 5.0 + (0.005 * max_life if ruby else 0.0)
        return flat

    def legacy_cdr(now: float) -> None:
        """Legacy of the Aspects: the longest remaining cooldown among the hero spells -0.75 s."""
        if not has(TALENT_LEGACY):
            return
        keys = [k for k in order if k != "form"]
        if not keys:
            return
        key = max(keys, key=lambda k: nxt[k])
        if nxt[key] > now:
            counters["legacy"] += 1
            nxt[key] = max(now, nxt[key] - LEGACY_CDR)

    def add_fury(amount: float) -> None:
        nonlocal fury
        fury = min(fury_max, fury + amount)

    def hero_hit(name: str, raw: float, now: float, tgts: list[int], *, kind: str | None, attack: bool,
                 potency_scale: float = 1.0, mult: float = 1.0, procs: bool = True, crit: bool = True) -> float:
        nonlocal burnout_bonus
        chance = stats["crit"]
        execute = _execute_factor(stats, now)
        factor = typed(kind, now)
        if has(TALENT_ALEXSTRASZA) and life_until > now:
            factor *= 1.10
        pot = potency(now)
        total = 0.0
        for t in tgts:
            amount = (raw + pot * potency_scale) * factor * mult
            if attack and crit:
                amount *= _crit_factor(chance, 2.0 + stats["rating"])
            elif stats["spell_crit"] and crit:
                amount *= _crit_factor(chance, stats["spell_mult"] + stats["rating"])
            amount += melting(t, now)
            total += amount * taken(t, now) * execute
            if obsidian and brand_until[t] <= now:
                counters["branded"] += 1
                brand_until[t] = now + BRANDED_DUR
                brand_value[t] = min(BRANDED_CAP, int(1.0 + 0.08 * armor(now)))
            if not procs:
                continue
            if rolls["fury"].roll(0.02 * luck_mult()):  # Dragonwrath A0B4
                counters["fury_luck"] += 1
                add_fury(1.0)
            if has_burnout:
                proc = (1.0 + burnout_bonus) * (LEGACY if has(TALENT_LEGACY) else 1.0)
                if rolls["burnout"].roll(proc * luck_mult() / 100.0):
                    counters["burnout_passive"] += 1
                    burnout_bonus = 0.0
                    push(now + BURNOUT_DELAY, "burnout", ("passive", t))
                    legacy_cdr(now)
            if emerald:
                proc = 3.0 * (LEGACY if has(TALENT_LEGACY) else 1.0)
                if rolls["cf_dmg"].roll(proc * luck_mult() / 100.0):
                    legacy_cdr(now)  # the heal itself has PreventOnHeal: no heal -> damage proc
        sources[name] = sources.get(name, 0.0) + total
        note_damage_mana(len(tgts))
        return total

    def cleansing_damage() -> float:
        return 7.0 + 0.01 * max_life  # CleansingFire_Damage

    def heal(now: float) -> None:
        """A DS heal on a hero (self): Emerald 8% x Luck (x1.15 Legacy) for 4 x Cleansing Fire damage."""
        if not emerald:
            return
        proc = 8.0 * (LEGACY if has(TALENT_LEGACY) else 1.0)
        if rolls["cf_heal"].roll(proc * luck_mult() / 100.0):
            counters["heal_proc"] += 1
            t = counters["heal_proc"] % targets
            hero_hit("Cleansing Fire (от лечения)", 4.0 * cleansing_damage(), now, [t], kind=None, attack=False,
                     potency_scale=0.0, crit=False)
            legacy_cdr(now)

    def burnout_impact(now: float, source: str) -> None:
        """Burnout_B: 25 + 1.2 STR per hit, Burnout_Triggers hits per enemy in 200."""
        nonlocal burnout_triggers
        dmg = 25.0 * RANK + 1.20 * strength
        if source == "passive":
            dmg *= 0.40
        if ruby:
            dmg *= 1.05 + 0.005 * mastery
        if ruby and in_form(now):
            dmg *= 1.0 + ruby_bonus()
        if wears(ITEM_GAUNTLETS):
            dmg *= 1.25
        if has(TALENT_WORLDBREAKER) and source == "hero":
            if not obsidian:
                burnout_triggers = 3
            # Obsidian: stun, Burnout_Triggers keeps its previous value (0 before any proc).
        else:
            burnout_triggers = 2
        label = {"hero": "Burnout", "passive": "Burnout (пассив)", "crit": "Burnout (крит, Blazing Strikes)"}[source]
        for hit in range(1, burnout_triggers + 1):
            if hit == 3:
                dmg *= 0.60
            # ASSUMPTION: the whole pack is inside the 200 impact.
            hero_hit(label, dmg, now, all_t, kind="magical", attack=False, potency_scale=1.0,
                     procs=(source != "passive"))

    def dragon_strike(now: float, label: str) -> None:
        dmg = 60.0 * RANK + 0.03 * max_life
        form = in_form(now)
        if form:
            dmg *= 1.25
        if ruby and form:
            dmg *= 1.0 + ruby_bonus()
        # ASSUMPTION: all enemies stand in the line.
        hero_hit(label, dmg, now, all_t, kind="magical", attack=False)
        for t in all_t:
            fire_until[t] = now + DRAGONFIRE_DUR
            if form:
                claw_until[t] = now + DRAGONFIRE_DUR

    def tick_rate() -> float:
        rate = 1.0
        if has(TALENT_GIFT_OF_LIFE):
            rate += 0.15 + 0.008 * potency(0.0)
        if wears(ITEM_HELM):
            rate += 0.25
        return rate

    def attack_interval(now: float) -> float:
        swing = SWING * (1.20 if stats["galactic"] else 1.0)
        speed = min(4.0, max(-0.8, stats["attack_speed"]))
        return swing / (1.0 + speed)

    gen = 1.0 / (1.0 + stats["haste"])
    if has(TALENT_DRAGONBORN):
        gen /= 1.0 + 0.01 * mastery
    if wears(ITEM_EYE):
        gen /= 1.20
    push(gen, "fury")
    if has(TALENT_ENGULFING):
        push(ENGULF_PERIOD / (1.0 + 0.01 * mastery), "engulf")
    if emerald:
        push(1.0, "cleanse_tick")

    fixed_cd = {"form": FORM_CD, "burnout": BURNOUT_CD, "cleanse": CLEANSE_CD, "strike": STRIKE_CD,
                "shield": SHIELD_CD, "life": LIFE_CD}
    cost = {"form": 0.0, "burnout": BURNOUT_MANA, "cleanse": CLEANSE_MANA, "strike": STRIKE_MANA,
            "shield": SHIELD_MANA, "life": LIFE_MANA}
    names = {"form": "Dragon Form", "burnout": "Burnout", "cleanse": "Cleansing Fire", "strike": "Dragon Strike",
             "shield": "Blazing Shield", "life": "Lifebinder"}
    order = []
    if use_form:
        order.append("form")
    if use_life:
        order.append("life")
    order.append("cleanse" if emerald else "burnout")
    order += ["strike", "shield"]
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
            if key == "form" and (fury < fury_max - 1e-9 or in_form(clock)):
                continue
            ready = max(nxt[key], busy, clock)
            if ready < cast_at - 1e-9:
                cast_at, choice = ready, key
        event_at = events[0][0] if events else FIGHT * 10
        moment = min(attack_at, cast_at, event_at)
        if moment >= FIGHT:
            break
        clock = moment

        if event_at == moment and event_at < attack_at and event_at < cast_at:
            _at, _s, kind, data = heapq.heappop(events)
            if kind == "fury":
                add_fury(1.0)
                push(moment + gen, "fury")
            elif kind == "burnout":
                burnout_impact(moment, data[0])
            elif kind == "engulf":
                # Engulfing Flames: 5 x level + 0.5 x armor to every enemy in 400.
                hero_hit("Engulfing Flames", 5.0 * RANK + 0.5 * armor(moment), moment, all_t, kind="magical",
                         attack=False)
                push(moment + ENGULF_PERIOD / (1.0 + 0.01 * mastery), "engulf")
            elif kind == "cleanse_tick":
                tgts = [t for t in all_t if cleanse_until[t] > moment]
                if tgts:
                    hero_hit("Cleansing Fire", cleansing_damage(), moment, tgts, kind=None, attack=False,
                             potency_scale=0.0, crit=False)
                push(moment + 1.0, "cleanse_tick")
            elif kind == "life_tick":
                if life_until > moment:
                    counters["life_ticks"] += 1
                    heal(moment)
                    if has(TALENT_BURNING_HEART):
                        # ASSUMPTION: the pack is within 250 of the (self-buffed) DS.
                        hero_hit("Burning Heart", 5.0 + 3.0 * LEVEL, moment, all_t, kind=None, attack=False,
                                 potency_scale=0.0, crit=False)
                    push(moment + 1.0 / tick_rate(), "life_tick")
                else:
                    life_ticking = False
            elif kind == "bolt":
                if in_form(moment):
                    counters["bolts"] += 1
                    t = bolt_target[0] % targets
                    bolt_target[0] += 1
                    hero_hit("Ruby Dragon Form (огненные снаряды)", BOLT_DAMAGE, moment, [t], kind=None,
                             attack=False, potency_scale=0.0)
                    push(moment + BOLT_EVERY, "bolt")
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
            if ruby:
                burnout_bonus += 0.50
            if obsidian:
                add_fury(3.0)
            flat = 0.0
            if key == "form":
                counters["form"] += 1
                fury = 0.0
                form_until = hit_at + FORM_DUR
                heal(hit_at)
                if has(TALENT_WAKING):
                    for other in order:
                        if other != "form":
                            nxt[other] = min(nxt[other], hit_at)
                if ruby:
                    push(hit_at + BOLT_EVERY, "bolt")
            elif key == "life":
                dur = LIFE_DUR + (6.0 if in_form(hit_at) else 0.0) + (2.0 if has(TALENT_ALEXSTRASZA) else 0.0)
                life_until = max(life_until, hit_at + dur)
                heal(hit_at)
                if not life_ticking:
                    life_ticking = True
                    push(hit_at + 1.0, "life_tick")  # Lifebinder_Timer first tick at 1.00
            elif key == "burnout":
                push(hit_at + BURNOUT_DELAY, "burnout", ("hero", 0))
                heated = has(TALENT_HEATED)
                if in_form(hit_at):
                    flat = BURNOUT_FORM_CDR
            elif key == "cleanse":
                # ASSUMPTION: the pack and the DS stand in the 250 area (self heal -> heal proc).
                for t in all_t:
                    cleanse_until[t] = hit_at + CLEANSE_DUR
                heal(hit_at)
            elif key == "strike":
                dragon_strike(hit_at, "Dragon Strike")
            elif key == "shield":
                dmg = (50.0 * RANK + 1.10 * strength) * (1.0 + 0.03 * armor(hit_at))
                if ruby and in_form(hit_at):
                    dmg *= 1.0 + ruby_bonus()
                if heated:
                    dmg *= 1.25
                    heated = False
                hero_hit("Blazing Shield", dmg, hit_at, [0], kind="magical", attack=False)
                if has(TALENT_EXPLOSIVE) and targets > 1:
                    hero_hit("Blazing Shield (Explosive Impact)", 0.15 * dmg, hit_at, all_t[1:], kind="magical",
                             attack=False, potency_scale=0.0)
                molten_until = hit_at + MOLTEN_DUR + (2.0 if has(TALENT_EARTHEN) else 0.0)
                if has(TALENT_EXPLOSIVE):
                    flat = 1.0
            if key != "form":
                nxt[key] = moment + _cooldown(fixed_cd[key], stats["haste"], stats, flat)
            else:
                nxt[key] = moment + FORM_CD  # unaffected by CDR
            next_attack = max(next_attack, busy)
            continue

        moment = attack_at
        recover(moment)
        power = dcs()
        before = sources["Автоатака"]
        chaos = CHAOS_UNARMORED if in_form(moment) else 1.0
        hero_hit("Автоатака", power, moment, [0], kind="physical", attack=True,
                 potency_scale=stats["attack_potency"], mult=chaos)
        if stats["auto_pct"] != 1.0:
            sources["Автоатака"] = before + (sources["Автоатака"] - before) * stats["auto_pct"]
        p_crit = max(0.0, min(100.0, stats["crit"])) / 100.0
        if has_burnout and rolls["crit_burnout"].roll(p_crit * 0.33 * luck_mult()):
            counters["burnout_crit"] += 1
            push(moment + BURNOUT_DELAY, "burnout", ("crit", 0))
        if wears(ITEM_DRAKE_SWORD):
            chance = (p_crit * 30.0 + (1.0 - p_crit) * 15.0) / 100.0
            if rolls["drake"].roll(chance * luck_mult()):
                counters["drake"] += 1
                dragon_strike(moment, "Dragon Strike (Drake Sword)")
        gain_mana(attack_mana_gain(stats))
        if stats["fire_orb"]:
            splash = (20.0 + 0.35 * strength) * targets * taken(0, moment) * _execute_factor(stats, moment)
            sources["Всплеск огня"] = sources.get("Всплеск огня", 0.0) + splash
            note_damage_mana(targets)
        if sulfuras is not None:
            execute = _execute_factor(stats, moment)
            if sulfuras.attack():
                splash = strength * typed("magical", moment) * taken(0, moment) * execute * targets
                splash *= _crit_factor(stats["crit"], 2.0 + stats["rating"])
                sources["Sulfuras"] = sources.get("Sulfuras", 0.0) + splash
                note_damage_mana(targets)
            echo = power * taken(0, moment) * execute * sulfuras_echo_chance(stats["luck"])
            sources["Sulfuras (удар)"] = sources.get("Sulfuras (удар)", 0.0) + echo
        next_attack = moment + attack_interval(moment)

    total = sum(sources.values())
    recover(FIGHT)
    mana_left = 0.0 if mana_max <= 0 else 100.0 * mana / mana_max
    stats = dict(stats)
    stats.update({f"n_{k}": float(v) for k, v in counters.items()})
    stats["policy_lifebinder"] = 1.0 if use_life else 0.0
    stats["policy_form"] = 1.0 if use_form else 0.0
    stats["spec_level"] = float(SPEC_LEVEL[spec])
    return Report(build, total / FIGHT, total, sources, actions, stats, targets, mana_left=mana_left)


def best_points(build: Build, targets: int, spec: str) -> tuple[float, tuple[int, int, int, int]]:
    return simulate(build, targets, spec).dps, (0, 0, 0, 0)
