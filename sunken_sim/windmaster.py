"""Windmaster fight for Sunken City v2.5.2a, level 6.

Unit O00Y. Strength 13 + 1.2, agility 26 + 2.6, intellect 11 + 1.1 (19 / 39 / 16 at
level 6). White hit ua1b 35 + 1d1 = 36, plus 0.75 x AGI (DCS formula), plus item
Attack Damage, plus 2 per Tornado stack (A078). Attack cooldown ua1c 1.60, SIEGE,
range 80, ucpt 0.08 / ucbs 0.20. HP 250, mana 120. Ability rank is 1.
Spec level on A0CC (udg_Glyphs_Unit[1]): 1 Upheaval, 2 Storm, 3 Combat.

Spells: Skyslash A0KT (next-attack buff B03L), Tornado A092 (bolts A0B0 / A0E1),
Lightning Rush A01T (+ timer), Windstorm A0QE (ANcl bear form O01K, periodic tick),
Wind Walk A08D (Combat replaces Windstorm; B08H via A0B8), Storm Cloud A0CL.
Cyclone = shared n061 dummy casting A0OD (1.0 s dummy cooldown, overlapping procs lost).
Charged Blade = n062 dummy forked lightning A00V (1.0 s cooldown), 0.5 x attack damage.

Modeling assumptions (not map numbers): Lightning Rush distance 80 (melee), Cyclone
travel 80 / 475 (A0OD missile speed), Illusion hit after its udp1 0.33 s, every Cyclone
hits all targets, Shredding Wind faerie fire lands on target 0, B08H flat damage is
added before the Physical multiplier, Storm Cloud is cast only with Illusions (I0OD).
Healing / lifesteal (Wintergrasp I03S) is not scored.
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

BASE_STR = int(13 + (LEVEL - 1) * 1.2)
BASE_AGI = int(26 + (LEVEL - 1) * 2.6)
BASE_INT = int(11 + (LEVEL - 1) * 1.1)
WHITE_BASE = 36.0  # ua1b 35 + 1d1
SWING = 1.60  # O00Y ua1c
BASE_MANA = 120.0
BASE_HP = 250.0

SPECS = ("upheaval", "storm", "combat")
HERO_CLASS = "Windmaster"
RANK = 1

ATTACK_DAMAGE_RE = re.compile(r"(?m)^\+(\d+) Attack Damage\b")

TALENT_BALANCED_BLADE = "I0DU"
TALENT_RAGING_STORM = "I0L5"
TALENT_WIND_SHIFT = "I09N"
TALENT_SKYFURY = "I0L4"
TALENT_WINDFLOW = "I0L7"
TALENT_SHREDDING_WIND = "I0JG"
TALENT_MISTRAL = "I0L3"
TALENT_STORMRAGE = "I0L6"
TALENT_WINTERGRASP = "I03S"
TALENT_GATHERING_STORM = "I0MP"
TALENT_CHARGED_BLADE = "I0MK"
TALENT_CHILLING_WINDS = "I0OE"
TALENT_GREATER_TORNADO = "I0OB"
TALENT_ILLUSIONS = "I0OD"
TALENT_PIERCING_GUST = "I0DK"
TALENT_EYE_OF_THE_STORM = "I0GO"
TALENT_HURRICANE = "I03R"
TALENT_FURY = "I00M"
TALENT_NEXT_PAGE = "I0MD"
TALENT_PREV_PAGE = "I0MC"

TALENTS = {
    TALENT_BALANCED_BLADE: "Balanced Blade",
    TALENT_RAGING_STORM: "Raging Storm",
    TALENT_WIND_SHIFT: "Wind Shift",
    TALENT_SKYFURY: "Skyfury",
    TALENT_WINDFLOW: "Windflow",
    TALENT_SHREDDING_WIND: "Shredding Wind",
    TALENT_MISTRAL: "Mistral Strikes",
    TALENT_STORMRAGE: "Stormrage",
    TALENT_WINTERGRASP: "Wintergrasp",
    TALENT_GATHERING_STORM: "Gathering Storm",
    TALENT_CHARGED_BLADE: "Charged Blade",
    TALENT_CHILLING_WINDS: "Chilling Winds",
    TALENT_GREATER_TORNADO: "Greater Tornado",
    TALENT_ILLUSIONS: "Illusions",
    TALENT_PIERCING_GUST: "Piercing Gust",
    TALENT_EYE_OF_THE_STORM: "Eye of the Storm",
    TALENT_HURRICANE: "Hurricane",
    TALENT_FURY: "Fury of the Storm Peaks",
    TALENT_NEXT_PAGE: "Next Page",
    TALENT_PREV_PAGE: "Previous Page",
}

# Pages are UI; Wintergrasp is lifesteal / heal only.
IGNORED_TALENTS = frozenset({TALENT_NEXT_PAGE, TALENT_PREV_PAGE, TALENT_WINTERGRASP})

SKY_CD, SKY_MANA, SKY_BUFF = 6.0, 10.0, 4.0  # A0KT; B03L 4 s
TORNADO_CD, TORNADO_MANA = 12.0, 20.0  # A092
TORNADO_LIFE = 7.0  # + 0.20 x Potency
BOLT_INTERVAL, BOLT_INTERVAL_GREATER = 0.75, 0.50  # A0B0 / A0E1
TORNADO_MAX_STACKS = 12
LR_CD, LR_MANA = 9.0, 15.0  # A01T
LR_SPEED, LR_DELAY, LR_DISTANCE = 1200.0, 0.15, 80.0  # distance = assumption (melee)
LR_BUFF, LR_BUFF_WINDFLOW = 4.0, 6.0  # A0BF / A02L
LR_AS = 0.11 + 0.04 * RANK
WS_CD, WS_MANA, WS_DUR, WS_PERIOD = 12.0, 20.0, 4.0, 0.5  # A0QE, Windstorm_Damage
WALK_CD, WALK_MANA, WALK_DUR = 35.0, 35.0, 10.0  # A08D, B08H
WALK_FLAT = 30.0 + 4.0 * LEVEL
CLOUD_CD, CLOUD_MANA = 3.0, 0.0  # A0CL
SHIFT_DUR, SHIFT_AS = 4.0, 0.40  # B006
DUMMY_CD = 1.0  # n061 Cyclone / n062 Charged Blade dummy ability cooldown
CYCLONE_DELAY = 80.0 / 475.0  # assumption: melee distance / A0OD missile speed
ILLUSION_DELAY = 0.33  # e00K udp1
SHRED_DUR, SHRED_ARMOR = 4.0, 2.0  # A08Q
MISTRAL_CHILL, CHILLING_CHILL = 4.0, 3.0

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
ITEM_STORMWEAVER = "I0RH"
ITEM_WARBEADS = "I0RI"
ITEM_SKYWRATH = "I0RJ"
ITEM_WINDWALKER = "I0RK"


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
    if TALENT_FURY in build.talents:
        mastery += 10.0  # I00M: +10 Mastery (Fury of the Storm Peaks)
    if TALENT_BALANCED_BLADE in build.talents:
        armor_pen += 2.0  # I0DU ArmorPenetration +2
        rating += 0.25  # I0DU critical damage +25 %
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
        "cd_temp": cd_temp,
        "flat_cdr": flat_cdr,
        "glass": 1.0 if _has(build, GLYPH_GLASS) or GLYPH_GLASS in codes else 0.0,
        "spellbinder": 1.0 if SPELLBINDER in codes else 0.0,
        "sulfuron": 1.0 if SULFURON_GLOVES in codes else 0.0,
        "galactic": 1.0 if GALACTIC_FURY in codes else 0.0,
        "fire_orb": 1.0 if FIRE_ORB in codes else 0.0,
        "stormweaver": 1.0 if ITEM_STORMWEAVER in codes else 0.0,
        "warbeads": 1.0 if ITEM_WARBEADS in codes else 0.0,
        "skywrath": 1.0 if ITEM_SKYWRATH in codes else 0.0,
        "windwalker": 1.0 if ITEM_WINDWALKER in codes else 0.0,
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


def simulate(build: Build, targets: int = 5, spec: str = "upheaval") -> Report:
    if spec not in SPECS:
        raise ValueError(spec)
    if targets < 1:
        raise ValueError(targets)
    stats = stats_of(build)
    luck_mult = 1.0 + stats["luck"]
    has = lambda code: _has(build, code)  # noqa: E731
    agi = stats["agi"]
    mastery = stats["mastery"]
    haste = stats["haste"]
    charged = has(TALENT_CHARGED_BLADE) or bool(stats["stormweaver"])

    sources: dict[str, float] = {
        "Автоатака": 0.0,
        "Skyslash": 0.0,
        "Tornado": 0.0,
        "Lightning Rush": 0.0,
        "Windstorm": 0.0,
        "Cyclone": 0.0,
        "Всплеск огня": 0.0,
    }
    actions: list[tuple[float, str]] = []
    mana = stats["mana_max"]
    mana_time = 0.0
    sulfuras = Sulfuras() if _wears(build, "I0BR") else None
    cast_time = CAST_POINT + CAST_BACKSWING

    chilled = [-1.0] * targets
    shredded = [-1.0] * targets
    sky_armed_until = -1.0
    skyfury_flag = False
    tornado_stacks = 0
    gathering = 1  # A03Z level
    lr_until = -1.0
    ws_until = -1.0
    walk_until = -1.0
    shift_until = -1.0
    shift_left = 0
    cyclone_ready = 0.0
    blade_ready = 0.0
    counters = {"cyclone_cast": 0, "cyclone_lost": 0, "blade_cast": 0, "blade_lost": 0}
    dice = {
        name: _Dither()
        for name in (
            "upheaval_reset", "upheaval_cyclone", "combat_cyclone", "hurricane", "stormrage", "blade",
            "illusion", "raging", "pierce", "shred", "skywrath",
        )
    }
    nxt = {"ws": 0.0, "walk": 0.0, "tornado": 0.0, "lr": 0.0, "sky": 0.0, "cloud": 0.0}
    pending: list[tuple[float, str, int]] = []

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

    def dcs(now: float) -> float:
        return WHITE_BASE + 0.75 * agi + stats["damage"] + 2.0 * tornado_stacks

    def lr_on(now: float) -> bool:
        return now < lr_until

    def ws_on(now: float) -> bool:
        return now < ws_until

    def attack_speed(now: float) -> float:
        speed = stats["attack_speed"]
        if lr_on(now):
            speed += LR_AS * (1.75 if has(TALENT_WINDFLOW) else 1.0)
        if has(TALENT_GATHERING_STORM):
            speed += 0.04 * (gathering - 1)
        if has(TALENT_WIND_SHIFT) and now < shift_until and shift_left > 0:
            speed += SHIFT_AS
        return min(4.0, max(-0.8, speed))

    def cdr(now: float) -> float:
        value = haste
        if has(TALENT_WINDFLOW) and lr_on(now):
            value += 0.10
        return value

    def taken_for(index: int, now: float) -> float:
        armor = float(DUMMY_ARMOR) - stats["armor_pen"]
        if shredded[index] > now:
            armor -= SHRED_ARMOR
        return armor_taken(armor)

    def physical(now: float) -> float:
        bonus = 1.0 + stats["phys_add"]
        if stats["sulfuron"]:
            bonus += 0.13 + 0.25 * target_hp(now)
        if stats["glass"]:
            bonus *= 1.15
        return bonus

    def crit_chance(now: float) -> float:
        chance = stats["crit"]
        if spec == "combat":
            chance += 5.0 + 0.5 * mastery
        if now < walk_until:
            chance += 20.0
        return chance

    def crit_rating(now: float) -> float:
        rating = 2.0 + stats["rating"]
        chance = crit_chance(now)
        if now < walk_until and chance > 100.0:
            rating += (chance - 100.0) / 100.0
        return rating

    def chill(index: int, now: float, duration: float) -> None:
        chilled[index] = max(chilled[index], now + duration)

    def cyclone(now: float) -> None:
        nonlocal cyclone_ready
        if now < cyclone_ready - 1e-9:
            counters["cyclone_lost"] += 1
            return
        cyclone_ready = now + DUMMY_CD
        counters["cyclone_cast"] += 1
        pending.append((now + CYCLONE_DELAY, "cyclone", 0))

    def illusion_roll(now: float) -> None:
        if has(TALENT_ILLUSIONS) and dice["illusion"].roll(0.50 * luck_mult):
            pending.append((now + ILLUSION_DELAY, "illusion", 0))

    def hit(
        name: str,
        raw: float,
        now: float,
        *,
        index: int = 0,
        attack: bool = False,
        typed: bool = True,
        potency_scale: float = 1.0,
        normal_type: bool = False,
        white: bool = False,
    ) -> tuple[float, float]:
        """Windmaster damage event. Returns (dealt, crit share)."""
        nonlocal gathering, blade_ready, shift_left
        amount = raw
        if attack:
            if now < walk_until:
                amount += WALK_FLAT
            if white and has(TALENT_WIND_SHIFT) and now < shift_until and shift_left > 0:
                amount += 0.40 * agi
        amount += stats["potency"] * potency_scale
        if typed:
            amount *= physical(now)
        taken = taken_for(index, now) * _execute_factor(stats, now)
        share = 0.0
        if attack:
            inc = 1.0
            if has(TALENT_MISTRAL) and chilled[index] > now:
                inc += 0.12
            chance = crit_chance(now)
            dealt = amount * inc * taken * _crit_factor(chance, crit_rating(now))
            share = _chance(chance / 100.0)
        else:
            dealt = amount * taken
        sources[name] = sources.get(name, 0.0) + dealt
        note_damage_mana(1.0)
        if spec == "upheaval" and dealt >= 1.0:
            if dice["upheaval_reset"].roll(0.035 * luck_mult):
                nxt["ws"] = min(nxt["ws"], now)
            if dice["upheaval_cyclone"].roll(0.03 * luck_mult):
                cyclone(now)
        if attack:
            if white and has(TALENT_WIND_SHIFT) and now < shift_until and shift_left > 0:
                shift_left -= 1
            if has(TALENT_GATHERING_STORM):
                gathering = min(11, gathering + 1)
            if spec == "combat":
                if not normal_type and dice["combat_cyclone"].roll(0.30 * (1.0 + 0.5 * share) * luck_mult):
                    cyclone(now)
                nxt["walk"] -= 0.5 * share
            if charged:
                chance = 0.15 * (2.0 if lr_on(now) else 1.0) * luck_mult
                if dice["blade"].roll(chance):
                    if now < blade_ready - 1e-9:
                        counters["blade_lost"] += 1
                    else:
                        blade_ready = now + DUMMY_CD
                        counters["blade_cast"] += 1
                        for j in range(min(3, targets)):
                            hit("Charged Blade", 0.5 * dealt, now, index=j, typed=False)
        return dealt, share

    def cyclone_land(now: float) -> None:
        for index in range(targets):
            power = dcs(now)
            raw = 40.0 + 0.40 * agi + 0.35 * power
            if has(TALENT_FURY):
                raw *= 1.0 + 0.004 * mastery
            if has(TALENT_HURRICANE) and dice["hurricane"].roll(0.30 * luck_mult):
                hit("Cyclone", raw, now, index=index, attack=True, typed=False)
            else:
                hit("Cyclone", raw, now, index=index)
            if has(TALENT_STORMRAGE) and dice["stormrage"].roll(0.25 * luck_mult):
                hit("Stormrage", 40.0 + 1.40 * power, now, index=index)

    def windstorm_tick(now: float) -> None:
        for index in range(targets):
            loops = 2 if (has(TALENT_RAGING_STORM) and dice["raging"].roll(0.15 * luck_mult)) else 1
            for _ in range(loops):
                power = dcs(now)
                raw = 3.0 + 7.0 * LEVEL + 0.6 * agi
                proc = False
                if has(TALENT_PIERCING_GUST) and dice["pierce"].roll(0.20 * luck_mult):
                    raw += 0.20 * power
                    proc = True
                if spec == "storm":
                    raw += 0.20 * power
                    raw *= 1.05 + 0.006 * mastery
                if targets == 1:
                    raw *= 2.0
                if has(TALENT_RAGING_STORM):
                    raw *= 1.12
                if has(TALENT_SHREDDING_WIND) and dice["shred"].roll(0.25 * luck_mult):
                    raw *= 1.40
                    shredded[0] = max(shredded[0], now + SHRED_DUR)
                raw *= 0.5
                if proc:
                    hit("Windstorm", raw, now, index=index, attack=True, typed=False)
                else:
                    hit("Windstorm", raw, now, index=index, typed=(spec == "storm"))

    def cast(now: float) -> float:
        nonlocal shift_until, shift_left
        if sulfuras is not None:
            sulfuras.cast()
        return now + cast_time + stats["cast_stun_lock"]

    def wind_shift(now: float) -> None:
        nonlocal shift_until, shift_left
        if has(TALENT_WIND_SHIFT):
            shift_until = now + SHIFT_DUR
            shift_left = 2

    order = ("walk", "tornado", "lr", "sky", "ws", "cloud")  # Windstorm last: it locks out the other spells
    names = {
        "ws": "Windstorm",
        "walk": "Wind Walk",
        "tornado": "Tornado",
        "lr": "Lightning Rush",
        "sky": "Skyslash",
        "cloud": "Storm Cloud",
    }
    costs = {"ws": WS_MANA, "walk": WALK_MANA, "tornado": TORNADO_MANA, "lr": LR_MANA, "sky": SKY_MANA, "cloud": CLOUD_MANA}
    allowed = {
        "ws": spec != "combat",
        "walk": spec == "combat",
        "tornado": True,
        "lr": True,
        "sky": True,
        "cloud": has(TALENT_ILLUSIONS),
    }
    next_attack = 0.0
    busy = 0.0
    guard = 0
    while True:
        guard += 1
        if guard > 400000:
            break
        attack_at = max(next_attack, busy, ws_until)
        cast_at = FIGHT * 10
        choice = None
        for key in order:
            if not allowed[key]:
                continue
            ready = max(nxt[key], busy)
            if key in ("ws", "tornado", "lr", "sky"):
                ready = max(ready, ws_until)
            if key == "sky" and sky_armed_until > ready:
                ready = sky_armed_until
            if ready < cast_at - 1e-9:
                cast_at, choice = ready, key
        pending_at = min((p[0] for p in pending), default=FIGHT * 10)
        moment = min(attack_at, cast_at, pending_at)
        if moment >= FIGHT:
            break
        if moment == pending_at:
            event = min(pending)
            pending.remove(event)
            _t, kind, index = event
            if kind == "cyclone":
                cyclone_land(moment)
            elif kind == "illusion":
                power = dcs(moment)
                hit("Illusions", 25.0 + 1.0 * power + 0.5 * agi, moment)
            elif kind == "bolt":
                tornado_stacks = min(TORNADO_MAX_STACKS, tornado_stacks + 1)
                power = dcs(moment)
                raw = 25.0 + 0.30 * agi + (0.30 if spec == "storm" else 0.10) * power
                hit("Tornado", raw, moment, index=index % targets)
                if stats["skywrath"] and dice["skywrath"].roll(0.50 * luck_mult):
                    nxt["sky"] = max(moment, nxt["sky"] - 0.3)
            elif kind == "ws":
                if moment <= ws_until + 1e-9:
                    windstorm_tick(moment)
            elif kind == "lr":
                lr_until = moment + (LR_BUFF_WINDFLOW if has(TALENT_WINDFLOW) else LR_BUFF)
                for j in range(targets):
                    raw = 75.0 * RANK + 1.20 * dcs(moment)
                    if spec == "storm":
                        raw *= 1.05 + 0.006 * mastery
                    if stats["windwalker"]:
                        raw *= 1.25
                    hit("Lightning Rush", raw, moment, index=j)
                    if has(TALENT_CHILLING_WINDS) and chilled[j] <= moment:
                        chill(j, moment, CHILLING_CHILL)
            continue
        if moment == cast_at and choice is not None and cast_at <= attack_at + 1e-9:
            key = choice
            if not pay(costs[key], moment):
                nxt[key] = moment + 0.25
                continue
            actions.append((moment, names[key]))
            hit_at = moment + CAST_POINT
            busy = cast(moment)
            rate = cdr(moment)
            if key != "cloud":
                wind_shift(hit_at)
            if key == "ws":
                duration = WS_DUR / (1.0 + rate) if spec == "storm" else WS_DUR
                btr = 1.0
                if has(TALENT_PIERCING_GUST):
                    btr += 0.25 * attack_speed(moment)
                if spec == "upheaval":
                    btr += 0.10 + 0.006 * mastery
                if spec == "storm":
                    btr += rate
                if stats["warbeads"]:
                    btr += 0.20
                period = WS_PERIOD / btr
                ws_until = hit_at + duration
                tick = hit_at + period
                while tick <= ws_until + 1e-9:
                    pending.append((tick, "ws", 0))
                    tick += period
                illusion_roll(hit_at)
                nxt[key] = moment + _cooldown(WS_CD, rate, stats)
            elif key == "walk":
                walk_until = hit_at + WALK_DUR
                illusion_roll(hit_at)
                nxt[key] = moment + _cooldown(WALK_CD, rate, stats)
            elif key == "tornado":
                if has(TALENT_SKYFURY):
                    skyfury_flag = True
                life = TORNADO_LIFE + 0.20 * stats["potency"]
                interval = BOLT_INTERVAL_GREATER if has(TALENT_GREATER_TORNADO) else BOLT_INTERVAL
                bolt = hit_at
                count = 0
                while bolt < hit_at + life - 1e-9:
                    pending.append((bolt, "bolt", count))
                    bolt += interval
                    count += 1
                illusion_roll(hit_at)
                flat = 2.0 if has(TALENT_GREATER_TORNADO) else 0.0
                nxt[key] = moment + _cooldown(TORNADO_CD, rate, stats, flat)
            elif key == "lr":
                land = hit_at + LR_DISTANCE / LR_SPEED + LR_DELAY
                pending.append((land, "lr", 0))
                busy = max(busy, land)
                if spec == "storm":
                    cyclone(hit_at)
                illusion_roll(hit_at)
                illusion_roll(hit_at)
                flat = 1.5 if has(TALENT_EYE_OF_THE_STORM) else 0.0
                nxt[key] = moment + _cooldown(LR_CD, rate, stats, flat)
            elif key == "sky":
                sky_armed_until = hit_at + SKY_BUFF
                illusion_roll(hit_at)
                nxt[key] = moment + _cooldown(SKY_CD, rate, stats)
            elif key == "cloud":
                illusion_roll(hit_at)
                nxt[key] = moment + _cooldown(CLOUD_CD, rate, stats)
            next_attack = max(next_attack, busy)
            continue
        # Windmaster auto-attack (SIEGE).
        moment = attack_at
        recover(moment)
        power = dcs(moment)
        before = sources["Автоатака"]
        _dealt, _share = hit("Автоатака", power, moment, attack=True, potency_scale=stats["attack_potency"], white=True)
        if stats["auto_pct"] != 1.0:
            sources["Автоатака"] = before + (sources["Автоатака"] - before) * stats["auto_pct"]
        if moment < sky_armed_until:
            sky_armed_until = -1.0
            raw = (60.0 + 40.0 * RANK) + 1.0 * power
            if skyfury_flag:
                raw *= 2.0
                skyfury_flag = False
            elif has(TALENT_SKYFURY):
                raw *= 1.10
            if spec == "storm":
                hit("Skyslash", raw * 1.25, moment)
                cyclone(moment)
            else:
                hit("Skyslash", raw, moment, attack=True, typed=False)
            if has(TALENT_MISTRAL):
                chill(0, moment, MISTRAL_CHILL)
        gain_mana(attack_mana_gain(stats))
        if stats["fire_orb"]:
            splash = (20.0 + 0.35 * agi) * targets * taken_for(min(1, targets - 1), moment) * _execute_factor(stats, moment)
            sources["Всплеск огня"] += splash
            note_damage_mana(targets)
        if sulfuras is not None:
            execute = _execute_factor(stats, moment)
            taken = taken_for(0, moment)
            if sulfuras.attack():
                splash = agi * (1.0 + stats["magic_add"]) * (1.15 if stats["glass"] else 1.0) * taken * execute * targets
                sources["Sulfuras"] = sources.get("Sulfuras", 0.0) + splash
                note_damage_mana(targets)
            echo = power * taken * execute * sulfuras_echo_chance(stats["luck"])
            sources["Sulfuras (удар)"] = sources.get("Sulfuras (удар)", 0.0) + echo
        next_attack = moment + SWING / (1.0 + attack_speed(moment))

    total = sum(sources.values())
    recover(FIGHT)
    mana_left = 0.0 if stats["mana_max"] <= 0 else 100.0 * mana / stats["mana_max"]
    stats = dict(stats)
    stats.update({f"n_{k}": float(v) for k, v in counters.items()})
    return Report(build, total / FIGHT, total, sources, actions, stats, targets, mana_left=mana_left)


def best_points(build: Build, targets: int, spec: str) -> tuple[float, dict[str, int]]:
    from sunken_sim.esc import apply_points, greedy_points, points_payload

    def score(pts: dict) -> float:
        trial = apply_points(build, pts)
        report = simulate(trial, targets, spec)
        return report.dps

    dps, pts = greedy_points(score)
    return dps, points_payload(pts)


