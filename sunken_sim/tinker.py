"""Tinker fight for Sunken City v2.5.2a, level 6.

Unit N03Y (base Ntin: attack cooldown 2.00, AGI +1 / level). Level 6 white stats: STR 36, AGI 15,
INT 24; Attribute Bonus A0F6 L1 adds +4 STR / +4 INT as bonus stats (learned, like the
Tidewarrior's A0HI). White hit 12 + 1d1 = 13 (DCS BaseDamage + 1), plus 0.75 x STR + item damage.
Ranged 600, siege (physical, no type table on the dummy). HP 300, mana 120 + 7 x INT.
Exosuit form N04I (A0A5, Nanotech only): same stats, melee 80. Ability rank 1.
Spec: A0NB level on udg_Glyphs_Unit[2]: 1 Engineering, 2 Demolitions, 3 Nanotech.

Numbers come from war3map.j and the w3u/w3a object data (see docs/tinker.md):
- Pocket Factory A0BR (21 s, 50 mana): a goblin every 0.45 s for 2.5 s (3.0 s with Advanced
  Production). Goblin 3 + R2I(0.18 DCS), cd 1.3, life 21 s. Engineering: Clockwerk n04K with Zap
  A0A3 (60 mana, 5 s): 10 + 0.10 x Tinker max mana, x1.30 vs Ionized, no damage type. Demolitions:
  suicide n05R, explodes on contact for 20 + 1.0 DCS physical (hero source, 250 AoE), 50% napalm.
  Nanotech: nanobots n04H (mana 0 -> 100, regen 1), excluded from procs (A0BZ).
- Master Engineer A0C1 (Engineering, Demolitions): every damage instance of the hero, goblins or
  sentries has 1.5% x Luck to spawn a goblin for 10.5 s (Clockwerk_Group < 18).
- Ion Grenade A0QQ (15 s, 25 mana; Engineering, Nanotech): 60 + 1.2 STR + 1.6 INT + all nanobot
  mana, Nanotech x(1.05 + 0.006 M), Exosuit x(1 + 0.004 STR) x (1 + 0.002 INT), x1.25 vs Ionized,
  magical 200 AoE, Ionized B070 7 s. Each Homing Missile hit cuts its cooldown by 0.4 s.
- Homing Missiles A02T (4 s, 10 mana): 5 missiles (+2 Cluster Rockets, +2 Box of Harmless Tools,
  + Wrist Launcher; cap 13, 15 with the Box), each 15 + 0.20 DCS + 0.15 STR physical (magical in
  Exosuit), Demolitions x(1.10 + 0.01 M). Engineering: dealt by a random sentry if one exists.
- Reinforce A0C0 (10 s, 25 mana): goblin / nanobot mana +15% of max (x1.5 Battery Pack).
- Minigun Sentry A00C (5 s, 15 mana): o013 for 20 s, 15 + R2I(0.10 DCS), cd 1.0, max 2 (3 with
  Pocket Turret). Each sentry attack: 25% x Luck (x1.5 on crit with Target Locking) for one missile.
- Napalm A0C2 (Demolitions): chance attack 35 / missile 20 / sentry 15 (+5 Flammable Rounds) /
  suicide 50, x1.25 Oiled Munition, x Luck. B069 5 s (8 s); re-apply while up adds a stack.
  Tick 1.0 s: 5 + 0.25 DCS + (1 + 0.04 DCS) x stacks, cap 75 x level, physical from the hero.
- Engineering: Clockwerk / sentry attacks +2 + 0.30 Mastery; pet damage + (current mana / 50)%.
Defensive, healing and movement talents are not scored.
"""

from __future__ import annotations

import heapq
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

WHITE_STR = int(24 + (LEVEL - 1) * 2.4)  # N03Y ustr/ustp
WHITE_AGI = int(10 + (LEVEL - 1) * 1.0)  # uagi; uagp missing → +1/level (Ntin)
WHITE_INT = int(16 + (LEVEL - 1) * 1.6)  # uint/uinp
ATTR_STR = 4  # A0F6 L1 Istr
ATTR_INT = 4  # A0F6 L1 Iint
BASE_STR = WHITE_STR + ATTR_STR
BASE_AGI = WHITE_AGI
BASE_INT = WHITE_INT + ATTR_INT
WHITE_BASE = 13.0  # DCS BaseDamage 12 + 1
SWING = 2.00  # Ntin default (N03Y has no ua1c)
BASE_MANA = 120.0
BASE_HP = 300.0
HERO_RANGE = 600.0
EXO_RANGE = 80.0

SPECS = ("engineering", "demolitions", "nanotech")
SPEC_LEVEL = {"engineering": 1, "demolitions": 2, "nanotech": 3}
HERO_CLASS = "Tinker"
RANK = 1

TALENT_BATTERY = "I0N3"
TALENT_ROCKET_BOOTS = "I0I6"
TALENT_ROCKETPACK = "I0N7"
TALENT_LIGHTNING_ROD = "I0Q5"
TALENT_TARGET_LOCKING = "I0N8"
TALENT_ADV_PRODUCTION = "I0N9"
TALENT_NANO_DECON = "I0N6"
TALENT_REPEATER = "I0N2"
TALENT_FIELD_REPAIR = "I0N4"
TALENT_NEXT_PAGE = "I0MD"
TALENT_OILED = "I0Q3"
TALENT_UNSTABLE_CORE = "I0Q2"
TALENT_CLUSTER = "I0EF"
TALENT_SHIELDTRONIC = "I0N5"
TALENT_POCKET_TURRET = "I0Q4"
TALENT_GAMBLER = "I0S0"
TALENT_WRIST = "I0S1"
TALENT_DISCHARGE = "I0Q1"
TALENT_OVERCLOCK = "I0S2"
TALENT_PREV_PAGE = "I0MC"

TALENTS = {
    TALENT_BATTERY: "Battery Pack",
    TALENT_ROCKET_BOOTS: "Rocket Boots",
    TALENT_ROCKETPACK: "Rocketpack",
    TALENT_LIGHTNING_ROD: "Lightning Rod",
    TALENT_TARGET_LOCKING: "Target Locking",
    TALENT_ADV_PRODUCTION: "Advanced Production",
    TALENT_NANO_DECON: "Nano Deconstruction",
    TALENT_REPEATER: "Repeater Cannon",
    TALENT_FIELD_REPAIR: "Field Repair",
    TALENT_OILED: "Oiled Munition",
    TALENT_UNSTABLE_CORE: "Unstable Core",
    TALENT_CLUSTER: "Cluster Rockets",
    TALENT_SHIELDTRONIC: "Shieldtronic Gear",
    TALENT_POCKET_TURRET: "Pocket Turret",
    TALENT_GAMBLER: "Master Gambler",
    TALENT_WRIST: "Wrist Launcher",
    TALENT_DISCHARGE: "Electric Discharge",
    TALENT_OVERCLOCK: "Overclocking",
}

# Nano Deconstruction: heal on lethal damage. Rocket Boots: potency only while moving (the dummy
# fight is stationary). Pages are UI only. Shieldtronic Gear is scored (taunt / armour are
# defensive, the x0.75 goblin damage is a loss in Engineering).
IGNORED_TALENTS = frozenset({TALENT_NANO_DECON, TALENT_ROCKET_BOOTS, TALENT_NEXT_PAGE, TALENT_PREV_PAGE})
IGNORED_REASONS = {
    TALENT_NANO_DECON: "лечение союзного героя при смертельном уроне",
    TALENT_ROCKET_BOOTS: "потенция только в движении (бой у пустышки стоячий)",
    TALENT_NEXT_PAGE: "страница талантов (UI)",
    TALENT_PREV_PAGE: "страница талантов (UI)",
}

ITEM_FLAMMABLE = "I0S3"
ITEM_WELDING = "I0S4"
ITEM_BOX = "I0S5"
ITEM_BELT = "I0S6"

FACTORY_CD, FACTORY_MANA, FACTORY_DUR, FACTORY_DUR_ADV, FACTORY_EVERY = 21.0, 50.0, 2.5, 3.0, 0.45  # A0BR
GOBLIN_SWING, GOBLIN_BASE, GOBLIN_LIFE = 1.3, 3.0, 21.0  # n04K / n05R / n04H
ENGINEER_CHANCE, ENGINEER_LIFE, ENGINEER_CAP = 1.5, 10.5, 18  # A0C1, Clockwerk_Duration x 0.5
GOBLIN_MANA, GOBLIN_REGEN = 100.0, 1.0
ZAP_MANA, ZAP_CD = 60.0, 5.0  # A0A3
SUICIDE_DELAY = 1.0  # ASSUMPTION: ms 295, spawned ~100 from the hero, explodes ~1 s after spawn
ION_CD, ION_MANA, ION_DUR = 15.0, 25.0, 7.0  # A0QQ, A0QR B070
HM_CD, HM_MANA, HM_SPEED = 4.0, 10.0, 750.0  # A02T
HM_DELAY, HM_DELAY_FAST = 1.0, 0.6  # random 0.8-1.2 / 0.4-0.8 s (Rocketpack)
REINFORCE_CD, REINFORCE_MANA, REINFORCE_PCT = 10.0, 25.0, 0.15  # A0C0
SENTRY_CD, SENTRY_MANA, SENTRY_LIFE, SENTRY_SWING, SENTRY_BASE = 5.0, 15.0, 20.0, 1.0, 15.0  # A00C / o013
SENTRY_RANGE = 400.0
EXO_CD, EXO_MANA = 5.0, 20.0  # A0A5
NAPALM_TICK, NAPALM_DUR, NAPALM_DUR_OILED = 1.0, 5.0, 8.0
OVERCLOCK_AS, OVERCLOCK_DUR, OVERCLOCK_CHANCE = 0.50, 4.0, 20.0  # A0B3 B00F via Attack_Speed

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


# (Reinforce cast / skipped, Exosuit on / off - Nanotech only)
POLICIES = tuple((reinforce, exo) for reinforce in (True, False) for exo in (False, True))


def simulate(build: Build, targets: int = 5, spec: str = "engineering") -> Report:
    """Best of the policies (Reinforce on / off; Nanotech: Exosuit on / off)."""
    best = None
    for policy in POLICIES:
        if policy[1] and spec != "nanotech":
            continue
        report = _simulate(build, targets, spec, policy)
        if best is None or report.dps > best.dps + 1e-9:
            best = report
    return best


def _simulate(build: Build, targets: int, spec: str, policy: tuple[bool, bool]) -> Report:
    use_reinforce, use_exo = policy
    if spec not in SPECS:
        raise ValueError(spec)
    if targets < 1:
        raise ValueError(targets)
    stats = stats_of(build)
    has = lambda code: _has(build, code)  # noqa: E731
    wears = lambda code: _wears(build, code)  # noqa: E731
    eng = spec == "engineering"
    demo = spec == "demolitions"
    nano = spec == "nanotech"
    has_engineer = eng or demo  # A0C1 removed in Nanotech
    has_ion = eng or nano  # A0QQ removed in Demolitions
    strength = int(stats["str"])
    intel = int(stats["int"])
    mastery = stats["mastery"]
    mana_max = stats["mana_max"]
    pen = stats["armor_pen"]
    cast_time = CAST_POINT + CAST_BACKSWING

    sources: dict[str, float] = {"Автоатака": 0.0}
    actions: list[tuple[float, str]] = []
    counters = {"goblins": 0, "engineer": 0, "zaps": 0, "missiles": 0, "sentry_missiles": 0,
                "napalm_apply": 0, "rod": 0, "overclock": 0, "hm_reset": 0, "suicide": 0}
    mana = mana_max
    mana_time = 0.0
    sulfuras = Sulfuras() if _wears(build, "I0BR") else None

    events: list = []
    seq = [0]

    def push(at: float, kind: str, data=None) -> None:
        seq[0] += 1
        heapq.heappush(events, (at, seq[0], kind, data))

    goblins: list[dict] = []
    sentries: list[dict] = []
    ion_until = -1.0
    exo = False
    discharge_used = False
    hero_oc_until = -1.0
    wrist_missiles = 0
    nap_stacks = [0] * targets
    nap_until = [-1.0] * targets
    hm_target = [0]
    rolls = {k: _Dither() for k in ("engineer", "napalm_attack", "napalm_hm", "napalm_sentry", "napalm_suicide",
                                    "oc", "wrist", "sentry_hm", "rod", "hm_reset")}

    def luck_mult(now: float) -> float:
        bonus = stats["luck"]
        if has(TALENT_GAMBLER):
            bonus += min(30, 2 * int(now)) / 100.0  # Out_of_Combat_Tinker, +2 / s up to 30
        return 1.0 + bonus

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
        """kind: 'magical', 'physical' or None (no NextDamageType: no magical / physical adds)."""
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

    def ionized(now: float) -> bool:
        return ion_until > now

    def taken(hero: bool) -> float:
        return armor_taken(DUMMY_ARMOR - (pen if hero else 0.0))

    def engineer(count: int, now: float) -> None:
        """Master Engineer A0C1: each damage instance of hero / goblin / sentry rolls 1.5% x Luck."""
        if not has_engineer:
            return
        chance = ENGINEER_CHANCE * luck_mult(now) / 100.0
        for _ in range(count):
            if rolls["engineer"].roll(chance) and len(goblins) < ENGINEER_CAP:
                counters["engineer"] += 1
                spawn_goblin(now, ENGINEER_LIFE)

    def hero_hit(name: str, raw: float, now: float, tgts: list[int], *, kind: str | None, attack: bool,
                 potency_scale: float = 1.0, mult: float = 1.0) -> float:
        chance = stats["crit"]
        execute = _execute_factor(stats, now)
        factor = typed(kind, now)
        total = 0.0
        for _t in tgts:
            amount = (raw + stats["potency"] * potency_scale) * factor * mult
            if attack:
                amount *= _crit_factor(chance, 2.0 + stats["rating"])
            elif stats["spell_crit"]:
                amount *= _crit_factor(chance, stats["spell_mult"] + stats["rating"])
            total += amount * taken(True) * execute
        sources[name] = sources.get(name, 0.0) + total
        note_damage_mana(len(tgts))
        engineer(len(tgts), now)
        return total

    def pet_bonus(now: float) -> float:
        bonus = stats["pet_damage"]
        if eng:
            recover(now)
            bonus += mana / 50.0 / 100.0  # PetDamage + (Tinker mana / 50)%
        return bonus

    def summon_hit(name: str, raw: float, now: float, count: int, *, kind: str | None, attack: bool,
                   sentry: bool = False, extra_crit: float = 0.0, mult: float = 1.0, procs: bool = True) -> float:
        increase = 0.0
        if sentry and has(TALENT_REPEATER):
            increase += 0.10  # ASSUMPTION: dummy is not Heavy / Hero / Divine (else 0.50)
        if wears(ITEM_BELT) and ionized(now):
            increase += 0.30
        amount = (raw + stats["potency"]) * (1.0 + pet_bonus(now)) * typed(kind, now) * mult * (1.0 + increase)
        if attack:
            amount *= _crit_factor(stats["summon_crit"] + extra_crit, 2.0 + stats["summon_rating"])
        dealt = amount * taken(False) * _execute_factor(stats, now) * count
        sources[name] = sources.get(name, 0.0) + dealt
        if procs:
            engineer(count, now)
        return dealt

    def napalm(source: str, t: int, now: float) -> None:
        if not demo:
            return
        base = {"attack": 35.0, "hm": 20.0, "sentry": 15.0 + (5.0 if wears(ITEM_FLAMMABLE) else 0.0),
                "suicide": 50.0}[source]
        if has(TALENT_OILED):
            base *= 1.25
        if rolls["napalm_" + source].roll(base * luck_mult(now) / 100.0):
            counters["napalm_apply"] += 1
            if nap_until[t] > now:
                nap_stacks[t] += 1
            else:
                nap_stacks[t] = 0
            nap_until[t] = now + (NAPALM_DUR_OILED if has(TALENT_OILED) else NAPALM_DUR)

    def overclock(unit: dict | None, now: float, hero_source: bool) -> None:
        nonlocal hero_oc_until
        if not has(TALENT_OVERCLOCK):
            return
        until = hero_oc_until if unit is None else unit["oc"]
        if until > now:
            return
        chance = OVERCLOCK_CHANCE
        if ionized(now) or (hero_source and exo):
            chance *= 1.5
        if rolls["oc"].roll(chance * luck_mult(now) / 100.0):
            counters["overclock"] += 1
            if unit is None:
                hero_oc_until = now + OVERCLOCK_DUR
            else:
                unit["oc"] = now + OVERCLOCK_DUR

    def missile_hit(now: float, t: int, label: str) -> None:
        counters["missiles"] += 1
        raw = 15.0 * RANK + 0.20 * dcs() + 0.15 * strength
        if demo:
            raw *= 1.10 + 0.01 * mastery
        kind = "magical" if exo else "physical"
        live = [s for s in sentries if s["die"] > now]
        if eng and live:
            summon_hit(label + " [от турели]", raw, now, 1, kind=kind, attack=False, sentry=True)
        else:
            hero_hit(label, raw, now, [t], kind=kind, attack=False)
        if has_ion:
            nxt["ion"] -= 0.4
        if has(TALENT_ROCKETPACK) and rolls["hm_reset"].roll(0.04 * luck_mult(now)):
            counters["hm_reset"] += 1
            nxt["hm"] = min(nxt["hm"], now)
        napalm("hm", t, now)

    def flight(range_: float) -> float:
        return range_ / HM_SPEED

    def spawn_goblin(now: float, life: float) -> None:
        counters["goblins"] += 1
        kind = "suicide" if demo else ("nano" if nano else "clock")
        gmax = GOBLIN_MANA + (int(0.10 * mana_max) if has(TALENT_BATTERY) and kind != "suicide" else 0.0)
        g = {"kind": kind, "raw": GOBLIN_BASE + int(0.18 * dcs()), "next": now, "die": now + life,
             "mana": 0.0 if kind == "nano" else gmax, "max": gmax, "mana_time": now, "zap": now, "oc": -1.0}
        goblins.append(g)
        if kind == "suicide":
            push(now + SUICIDE_DELAY, "suicide", g)
        else:
            push(now, "goblin", g)
        push(now + life, "gdeath", g)

    def goblin_mana(g: dict, now: float) -> None:
        if now > g["mana_time"]:
            g["mana"] = min(g["max"], g["mana"] + GOBLIN_REGEN * (now - g["mana_time"]))
        g["mana_time"] = now

    def mech_death(now: float) -> None:
        if has(TALENT_FIELD_REPAIR):
            gain_mana(0.02 * mana_max)

    def lightning_rod(now: float) -> None:
        if has(TALENT_LIGHTNING_ROD) and rolls["rod"].roll(0.30 * luck_mult(now)):
            counters["rod"] += 1
            hero_hit("Lightning Rod", 40.0 + 1.25 * strength + 1.25 * intel, now, list(range(targets)),
                     kind="magical", attack=False)

    def attack_interval(now: float) -> float:
        swing = SWING * (1.20 if stats["galactic"] else 1.0)
        speed = stats["attack_speed"]
        if hero_oc_until > now:
            speed += OVERCLOCK_AS
        speed = min(4.0, max(-0.8, speed))
        return swing / (1.0 + speed)

    sentry_max = 3 if has(TALENT_POCKET_TURRET) else 2
    fixed_cd = {"exo": EXO_CD, "factory": FACTORY_CD, "sentry": SENTRY_CD, "ion": ION_CD, "hm": HM_CD,
                "reinforce": REINFORCE_CD}
    flat_cd = {
        "factory": (5.0 if wears(ITEM_WELDING) else 0.0) + (3.0 if has(TALENT_ADV_PRODUCTION) else 0.0),
        "sentry": 1.0 if has(TALENT_POCKET_TURRET) else 0.0,
        "ion": 3.0 if has(TALENT_UNSTABLE_CORE) else 0.0,
        "reinforce": 2.0 if has(TALENT_FIELD_REPAIR) else 0.0,
    }
    cost = {"exo": EXO_MANA, "factory": FACTORY_MANA, "sentry": SENTRY_MANA, "ion": ION_MANA, "hm": HM_MANA,
            "reinforce": REINFORCE_MANA}
    names = {"exo": "Exosuit", "factory": "Pocket Factory", "sentry": "Minigun Sentry", "ion": "Ion Grenade",
             "hm": "Homing Missiles", "reinforce": "Reinforce"}
    order = ["factory", "sentry"]
    if has_ion:
        order.append("ion")
    order.append("hm")
    if use_reinforce and not demo:
        order.append("reinforce")
    if use_exo and nano:
        order.insert(0, "exo")
    nxt = {key: 0.0 for key in order}
    nxt.setdefault("ion", FIGHT * 10)
    nxt.setdefault("hm", 0.0)

    if demo:
        push(NAPALM_TICK, "napalm_tick")

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
            if key == "exo" and exo:
                continue
            if key == "sentry" and sum(1 for s in sentries if s["die"] > clock) >= sentry_max:
                continue
            if key == "reinforce" and not any(g["die"] > clock and g["kind"] != "suicide" for g in goblins):
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
            if kind == "goblin":
                g = data
                if g["die"] <= moment:
                    continue
                goblin_mana(g, moment)
                mult = 0.75 if (g["kind"] == "clock" and has(TALENT_SHIELDTRONIC)) else 1.0  # n040
                raw = g["raw"]
                if eng:
                    raw += 2.0 + 0.30 * mastery
                if g["kind"] == "nano":
                    summon_hit("Наноботы", raw, moment, 1, kind="physical", attack=True, procs=False)
                else:
                    summon_hit("Гоблины", raw, moment, 1, kind="physical", attack=True, mult=mult)
                    overclock(g, moment, False)
                    if g["mana"] >= ZAP_MANA and g["zap"] <= moment:
                        g["mana"] -= ZAP_MANA
                        g["zap"] = moment + ZAP_CD
                        counters["zaps"] += 1
                        zap_mult = mult * (1.30 if ionized(moment) else 1.0)
                        summon_hit("Zap", 10.0 + 0.10 * mana_max, moment, 1, kind=None, attack=False, mult=zap_mult)
                swing = GOBLIN_SWING / (1.0 + (OVERCLOCK_AS if g["oc"] > moment else 0.0))
                push(moment + swing, "goblin", g)
            elif kind == "suicide":
                g = data
                if g["die"] <= moment:
                    continue
                counters["suicide"] += 1
                g["die"] = moment
                goblins.remove(g)
                # ASSUMPTION: the whole pack stands inside the 250 explosion.
                tgts = list(range(targets))
                hero_hit("Suicide Goblin", 20.0 + 1.0 * dcs(), moment, tgts, kind="physical", attack=False)
                for t in tgts:
                    napalm("suicide", t, moment)
                mech_death(moment)
            elif kind == "gdeath":
                g = data
                if g in goblins:
                    goblins.remove(g)
                    mech_death(moment)
            elif kind == "sentry":
                s = data
                if s["die"] <= moment:
                    continue
                raw = s["raw"] + (2.0 + 0.30 * mastery if eng else 0.0)
                crit_extra = 15.0 if has(TALENT_TARGET_LOCKING) else 0.0
                summon_hit("Minigun Sentry", raw, moment, 1, kind="physical", attack=True, sentry=True,
                           extra_crit=crit_extra)
                overclock(s, moment, False)
                napalm("sentry", 0, moment)
                chance = 25.0
                if has(TALENT_TARGET_LOCKING):
                    p = max(0.0, min(100.0, stats["summon_crit"] + crit_extra)) / 100.0
                    chance *= 1.0 + 0.5 * p
                if rolls["sentry_hm"].roll(chance * luck_mult(moment) / 100.0):
                    counters["sentry_missiles"] += 1
                    push(moment + flight(SENTRY_RANGE), "missile", (0, "Ракета турели"))
                swing = SENTRY_SWING / (1.0 + (OVERCLOCK_AS if s["oc"] > moment else 0.0))
                push(moment + swing, "sentry", s)
            elif kind == "sdeath":
                if data in sentries:
                    sentries.remove(data)
                    mech_death(moment)
            elif kind == "missile":
                t, label = data
                missile_hit(moment, t, label)
            elif kind == "ion":
                dmg = data
                mult = 1.25 if ionized(moment) else 1.0
                hero_hit("Ion Grenade", dmg, moment, list(range(targets)), kind="magical", attack=False, mult=mult)
                ion_until = moment + ION_DUR
            elif kind == "factory":
                spawn_goblin(moment, GOBLIN_LIFE)
            elif kind == "napalm_tick":
                tgts = [t for t in range(targets) if nap_until[t] > moment]
                for t in tgts:
                    tick = 5.0 + 0.25 * dcs() + (1.0 + 0.04 * dcs()) * nap_stacks[t]
                    tick = min(tick, 75.0 * LEVEL)
                    hero_hit("Napalm", tick, moment, [t], kind="physical", attack=False)
                for t in range(targets):
                    if nap_until[t] <= moment:
                        nap_stacks[t] = 0
                push(moment + NAPALM_TICK, "napalm_tick")
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
            if key == "exo":
                exo = True
                if has(TALENT_DISCHARGE) and not discharge_used:
                    discharge_used = True
                    hero_hit("Electric Discharge", (100.0 + 4.0 * strength) * (1.0 + 0.01 * intel), hit_at,
                             list(range(targets)), kind="magical", attack=False)
                    ion_until = hit_at + ION_DUR
            elif key == "factory":
                dur = FACTORY_DUR_ADV if has(TALENT_ADV_PRODUCTION) else FACTORY_DUR
                for k in range(1, int(dur / FACTORY_EVERY + 1e-9) + 1):
                    push(hit_at + k * FACTORY_EVERY, "factory")
            elif key == "sentry":
                live = [s for s in sentries if s["die"] > hit_at]
                s = {"raw": SENTRY_BASE + int(0.10 * dcs()), "die": hit_at + SENTRY_LIFE, "oc": -1.0}
                sentries.append(s)
                push(hit_at, "sentry", s)
                push(hit_at + SENTRY_LIFE, "sdeath", s)
                del live
            elif key == "ion":
                dmg = 60.0 + 1.20 * strength + 1.60 * intel
                for g in goblins:
                    if g["kind"] == "nano":
                        goblin_mana(g, hit_at)
                        dmg += g["mana"]
                        g["mana"] = 0.0
                if nano:
                    dmg *= 1.05 + 0.006 * mastery
                if exo:
                    dmg *= (1.0 + 0.004 * strength) * (1.0 + 0.002 * intel)
                # ASSUMPTION: ranged cast > 200 away (0.70 s); in Exosuit the target is 50-200 away (0.35 s).
                push(hit_at + (0.35 if exo else 0.70), "ion", dmg)
            elif key == "hm":
                cap = 15 if wears(ITEM_BOX) else 13
                count = 5 + (2 if has(TALENT_CLUSTER) else 0) + (2 if wears(ITEM_BOX) else 0) + wrist_missiles
                count = min(cap, count)
                wrist_missiles = 0
                delay = HM_DELAY_FAST if has(TALENT_ROCKETPACK) else HM_DELAY
                travel = flight(EXO_RANGE + 20.0 if exo else HERO_RANGE)
                for _k in range(count):
                    t = hm_target[0] % targets
                    hm_target[0] += 1
                    push(hit_at + delay + travel, "missile", (t, "Homing Missiles"))
            elif key == "reinforce":
                pct = REINFORCE_PCT * (1.5 if has(TALENT_BATTERY) else 1.0)
                for g in goblins:
                    if g["kind"] != "suicide":
                        goblin_mana(g, hit_at)
                        g["mana"] = min(g["max"], g["mana"] + pct * g["max"])
            lightning_rod(hit_at)
            nxt[key] = moment + _cooldown(fixed_cd[key], stats["haste"], stats, flat_cd.get(key, 0.0))
            next_attack = max(next_attack, busy)
            continue

        moment = attack_at
        recover(moment)
        power = dcs()
        before = sources["Автоатака"]
        hero_hit("Автоатака", power, moment, [0], kind="physical", attack=True,
                 potency_scale=stats["attack_potency"])
        if stats["auto_pct"] != 1.0:
            sources["Автоатака"] = before + (sources["Автоатака"] - before) * stats["auto_pct"]
        napalm("attack", 0, moment)
        overclock(None, moment, True)
        if has(TALENT_WRIST):
            for _ in range(2):
                if rolls["wrist"].roll(0.33 * luck_mult(moment)):
                    wrist_missiles += 1
        gain_mana(attack_mana_gain(stats))
        if stats["fire_orb"]:
            splash = (20.0 + 0.35 * strength) * targets * taken(True) * _execute_factor(stats, moment)
            sources["Всплеск огня"] = sources.get("Всплеск огня", 0.0) + splash
            note_damage_mana(targets)
        if sulfuras is not None:
            execute = _execute_factor(stats, moment)
            if sulfuras.attack():
                splash = strength * typed("magical", moment) * taken(True) * execute * targets
                splash *= _crit_factor(stats["crit"], 2.0 + stats["rating"])
                sources["Sulfuras"] = sources.get("Sulfuras", 0.0) + splash
                note_damage_mana(targets)
            echo = power * taken(True) * execute * sulfuras_echo_chance(stats["luck"])
            sources["Sulfuras (удар)"] = sources.get("Sulfuras (удар)", 0.0) + echo
        next_attack = moment + attack_interval(moment)

    total = sum(sources.values())
    recover(FIGHT)
    mana_left = 0.0 if mana_max <= 0 else 100.0 * mana / mana_max
    stats = dict(stats)
    stats.update({f"n_{k}": float(v) for k, v in counters.items()})
    stats["policy_reinforce"] = 1.0 if use_reinforce else 0.0
    stats["policy_exo"] = 1.0 if use_exo else 0.0
    stats["spec_level"] = float(SPEC_LEVEL[spec])
    return Report(build, total / FIGHT, total, sources, actions, stats, targets, mana_left=mana_left)


def best_points(build: Build, targets: int, spec: str) -> tuple[float, dict[str, int]]:
    from sunken_sim.esc import apply_points, greedy_points, points_payload

    def score(pts: dict) -> float:
        trial = apply_points(build, pts)
        report = simulate(trial, targets, spec)
        return report.dps

    dps, pts = greedy_points(score)
    return dps, points_payload(pts)


