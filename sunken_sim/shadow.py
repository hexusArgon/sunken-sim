"""Shadow Priest single-target simulator for Sunken City, level 6.

The fight is 30 seconds against one target that stays at full health and has no
armor. Damage is the expected value of crits and procs, so the search is stable.
"""

from __future__ import annotations

import heapq
import itertools
import math
from dataclasses import dataclass
from pathlib import Path

from sunken_sim.library import Item, load_items

FIGHT = 30.0
CAST_POINT = 0.15
CAST_BACKSWING = 0.30
LEVEL = 6
DUMMY_ARMOR = 15.0
ARMOR_FACTOR = 0.04
CHAOS_UNARMORED = 1.25

# Added to the type bonus before Insanity multiplies the magical bonus.
# Values are the map's MagicalType_Bonus / PhysicalType_Bonus adds.
MAGICAL_ADDS = {
    "I0AV": 0.18,
    "I0BL": 0.14,
    "ofr2": 0.15,
    "I0FU": 0.12,
    "I030": 0.08,
    "fgdg": 0.10,
    "tgrh": 0.20,
    "I07F": 0.13,
    "I0NI": 0.12,
    "fgrd": 0.30,
    "oflg": 0.08,
    "rde0": 0.05,
    "I048": 0.20,
    "I00Q": 0.05,
    "I04J": 0.10,
    "I0JO": 0.30,
}
PHYSICAL_ADDS = {
    "I0AV": 0.18,
    "I0BL": 0.14,
    "ofr2": 0.15,
    "I0AL": 0.10,
    "I017": 0.12,
    "I07K": 0.13,
    "tgrh": 0.20,
    "I0GM": 0.05,
    "I044": 0.18,
    "I055": 0.18,
}

# O009 grown with int(base + (level - 1) * per level), matching Warcraft truncation.
BASE_STR = int(3 + (LEVEL - 1) * 1.5)
BASE_AGI = int(8 + (LEVEL - 1) * 0.8)
BASE_INT = int(27 + (LEVEL - 1) * 2.7)
SKILL_POINTS = LEVEL - 1  # one point per level-up, none at level 1

TALENTS = {
    "I0KF": "Dark Torment",
    "I0HL": "Psychic Link",
    "I0PU": "Insanity",
    "I0PS": "Catharsis",
    "I0HP": "Cosmic Horrors",
    "I0SA": "Clairvoyance",
    "I0SB": "Answered Prayers",
    "I0SC": "Touch of the Naaru",
}
GLYPHS = {
    "I07B": "Fortitude",
    "I0JA": "Glass Cannon",
    "I0AV": "Unsealed Power",
    "I0OF": "Mindhaste",
    "I0H3": "Hellfire",
    "I0EK": "Supremacy",
    "I0HC": "Animosity",
    "I0H5": "Thunder",
}


@dataclass(frozen=True)
class Build:
    talents: frozenset[str]
    glyphs: frozenset[str]
    items: tuple[Item, ...]
    potency_points: int
    mastery_points: int
    crit_points: int = 0
    luck_points: int = 0


@dataclass
class Report:
    build: Build
    dps: float
    total: float
    sources: dict[str, float]
    actions: list[tuple[float, str]]
    stats: dict[str, float]
    targets: int = 1


def _has(build: Build, rawcode: str) -> bool:
    return rawcode in build.talents or rawcode in build.glyphs


def _wears(build: Build, rawcode: str) -> bool:
    return _has(build, rawcode) or any(item.rawcode == rawcode for item in build.items)


def character(build: Build) -> dict[str, float]:
    intel = BASE_INT + sum(item.intel + item.all_stats for item in build.items)
    strength = BASE_STR + sum(item.strength + item.all_stats for item in build.items)
    agility = BASE_AGI + sum(item.agility + item.all_stats for item in build.items)
    if _has(build, "I07B"):
        intel += 4 + 2 * LEVEL
    potency = sum(item.potency for item in build.items) + 0.5 * build.potency_points
    mastery = sum(item.mastery for item in build.items) + build.mastery_points
    if _has(build, "I0EK"):
        mastery += 20
    damage = 10 + 0.75 * intel + sum(item.damage for item in build.items)
    mana = 175 + 7 * intel + sum(item.mana for item in build.items)
    crit = sum(item.crit for item in build.items) + build.crit_points
    if _has(build, "I0SA"):
        crit += 8
    if _has(build, "I0HC"):
        crit += 12
    rating = sum(item.crit_rating for item in build.items)
    if _has(build, "I0HC"):
        rating += 0.15
    haste = 0.0
    for item in build.items:
        # Hand of the Magi aura is 15% to others and half of that on the wearer.
        if item.rawcode == "I06M":
            haste += 0.075
        else:
            haste += item.haste / 100
    if _has(build, "I0OF"):
        haste += 0.07
    agility_speed = min(1.0, 0.004 * agility)
    attack_speed = sum(item.attack_speed for item in build.items) / 100 + agility_speed
    attack_speed = max(-0.8, min(4.0, attack_speed))
    if _has(build, "I0GZ"):
        unbuffed_swing = 2.0 / (1 + attack_speed)
        uptime = 5.0 / (5.0 + unbuffed_swing / 0.18)
        attack_speed = max(-0.8, min(4.0, attack_speed + 0.32 * uptime))
    spell_crit = any(item.spell_crit for item in build.items)
    spell_mult = 1.65 if any(item.spell_crit and "65%" in item.tip for item in build.items) else 1.50
    flat_cdr = 0.0
    if _has(build, "I0OF"):
        flat_cdr += 0.20
    if _wears(build, "I096"):
        flat_cdr += 0.50
    if _wears(build, "I03C"):
        flat_cdr += 0.50
    if _wears(build, "I00L"):
        flat_cdr += 1.50
    if _wears(build, "I00Y"):
        flat_cdr -= 1.00
    cd_temp = 1.0
    if _wears(build, "I07P"):
        cd_temp *= 0.92
    if _wears(build, "I048"):
        cd_temp *= 0.87
    cd_increase = 1.0
    if _wears(build, "I0FW"):
        cd_increase += 0.12
    if _wears(build, "I0QT"):
        cd_increase += 0.10
    cd_temp *= cd_increase
    stun_per_swing = sum(item.stun_chance * item.stun_duration for item in build.items)
    double_attack_potency = any(item.double_attack_potency for item in build.items)
    auto_pct = 1.0 + sum(item.auto_pct for item in build.items)
    executes = [
        (item.execute_below, item.execute_pct)
        for item in build.items
        if item.execute_pct > 0
    ]
    armor_pen = sum(item.armor_pen for item in build.items)
    crit_as = sum(item.crit_as for item in build.items)
    crit_as_duration = max((item.crit_as_duration for item in build.items), default=0.0)
    if crit_as > 0 and crit > 0 and crit_as_duration > 0:
        base_speed = attack_speed
        for _ in range(2):
            swing = 2.0 / (1 + attack_speed)
            rate = min(crit, 100.0) / 100.0 / swing
            uptime = 1.0 - math.exp(-rate * crit_as_duration)
            attack_speed = max(-0.8, min(4.0, base_speed + crit_as * uptime))
    luck = 0.01 * build.luck_points
    return {
        "int": intel,
        "str": strength,
        "agi": agility,
        "potency": potency,
        "mastery": mastery,
        "ad": damage,
        "mana_max": mana,
        "crit": min(100.0, crit),
        "rating": rating,
        "haste": haste,
        "attack_speed": attack_speed,
        "spell_crit": float(spell_crit),
        "spell_mult": spell_mult,
        "flat_cdr": flat_cdr,
        "cd_temp": cd_temp,
        "stun_per_swing": stun_per_swing,
        "attack_potency": 2.0 if double_attack_potency else 1.0,
        "auto_pct": auto_pct,
        "executes": executes,
        "armor_pen": armor_pen,
        "stab_chance": sum(item.stab_chance for item in build.items),
        "stab_ratio": max((item.stab_ratio for item in build.items), default=0.0),
        "luck": luck,
        "swp_period": 1 / (1 + haste),
        "swing": 2.0 / (1 + attack_speed),
    }


def target_hp(time: float) -> float:
    return max(0.0, 1.0 - time / FIGHT)


def _execute_factor(stats: dict, time: float) -> float:
    hp = target_hp(time)
    factor = 1.0
    for threshold, bonus in stats["executes"]:
        if hp <= threshold:
            factor *= 1.0 + bonus
    return factor


def _codes(build: Build) -> frozenset[str]:
    return frozenset(item.rawcode for item in build.items) | build.talents | build.glyphs


def _type_add(codes: frozenset[str], table: dict[str, float], time: float) -> float:
    bonus = 0.0
    for code, amount in table.items():
        if code in codes:
            bonus += amount
    if "I0QT" in codes:
        bonus += 0.13 + 0.25 * target_hp(time)
    return bonus


def _magic_factors(codes: frozenset[str], time: float) -> tuple[float, float]:
    """Return (multiplier at 0 mastery from Spellbinder, slope per mastery point).

    Map order: add the type bonuses, multiply that sum by Insanity, then add
    Catharsis, then multiply by Glass Cannon.
    """
    bonus = 1.0 + _type_add(codes, MAGICAL_ADDS, time)
    slope = 0.0
    if "tlum" in codes:
        bonus += 0.05
        slope = 0.005
    if "I0PU" in codes:
        bonus *= 1.15
        slope *= 1.15
    if "I0PS" in codes:
        bonus += 0.30 * target_hp(time)
    if "I0JA" in codes:
        bonus *= 1.15
        slope *= 1.15
    return bonus, slope


def _magical_multiplier(codes: frozenset[str], time: float, mastery_stat: float) -> float:
    base, slope = _magic_factors(codes, time)
    return base + slope * mastery_stat


def _physical_multiplier(codes: frozenset[str], time: float) -> float:
    bonus = 1.0 + _type_add(codes, PHYSICAL_ADDS, time)
    if "I0JA" in codes:
        bonus *= 1.15
    return bonus


def _ability_cd(base: float, stats: dict, bound: bool = False) -> float:
    temp = stats["cd_temp"] * (0.70 if bound else 1.0)
    return max(0.5, (base * temp - stats["flat_cdr"]) / (1.0 + stats["haste"]))


def armor_taken(armor: float) -> float:
    if armor > 0:
        return 1 - (armor * ARMOR_FACTOR) / (1 + ARMOR_FACTOR * armor)
    if armor < 0:
        return 2 - (1 - ARMOR_FACTOR) ** (-armor)
    return 1.0


def _crit_factor(chance: float, multiplier: float) -> float:
    chance = max(0.0, min(100.0, chance)) / 100
    return 1 + chance * (multiplier - 1)


def score_events(
    events: list[tuple[float, str, float]],
    build: Build,
    stats: dict,
    potency: float | None = None,
    crit: float | None = None,
    mastery_stat: float | None = None,
    luck: float | None = None,
) -> tuple[float, dict[str, float]]:
    potency = stats["potency"] if potency is None else potency
    crit = stats["crit"] if crit is None else crit
    mastery_stat = stats["mastery"] if mastery_stat is None else mastery_stat
    luck = stats["luck"] if luck is None else luck
    codes = _codes(build)
    spell_crit = _crit_factor(crit, stats["spell_mult"] + stats["rating"]) if stats["spell_crit"] else 1.0
    attack_crit = _crit_factor(crit, 2 + stats["rating"])
    mastery = 1.10 + 0.006 * mastery_stat
    tick_base = (15 + 0.30 * stats["int"]) * mastery
    instant_raw = (75 + 1.50 * stats["int"]) * mastery
    mind_raw = (80 + 1.50 * stats["int"]) * (1 + 0.01 * stats["ad"])
    void_raw = (85 + 0.15 * stats["mana_max"]) * (1 + 0.007 * stats["int"])
    naaru_raw = 25 + 0.40 * stats["int"]
    thunder_raw = 35 + 2 * stats["int"]
    link = _has(build, "I0HL")
    glass = _has(build, "I0JA")
    sources: dict[str, float] = {}

    def add(name: str, amount: float) -> None:
        sources[name] = sources.get(name, 0.0) + amount

    for when, kind, hits in events:
        execute = _execute_factor(stats, when)
        magical = _magical_multiplier(codes, when, mastery_stat)
        physical = _physical_multiplier(codes, when)
        if kind == "auto":
            amount = (stats["ad"] + potency * stats["attack_potency"]) * physical * execute * stats["auto_pct"] * attack_crit * hits
            add("Автоатака", amount)
            if stats["stab_chance"]:
                chance = stats["stab_chance"] * (1 + luck)
                raw = stats["stab_ratio"] * stats["ad"]
                stab = (
                    (raw + potency * stats["attack_potency"])
                    * physical
                    * execute
                    * stats["auto_pct"]
                    * attack_crit
                    * CHAOS_UNARMORED
                    * chance
                    * hits
                )
                add("Удар тьмы", stab)
        elif kind == "mind":
            add("Mind Spike", (mind_raw + potency) * magical * spell_crit * hits)
        elif kind == "void":
            add("Void Rift", (void_raw + potency) * magical * spell_crit * hits)
        elif kind == "naaru":
            add("Naaru", (naaru_raw + potency) * magical * spell_crit * hits)
        elif kind == "swp":
            per = tick_base * ((1.15 + 0.10 * hits) if link else 1.0)
            add("Shadow Word: Pain", (per + potency) * magical * spell_crit * hits)
        elif kind == "swp_i":
            add("Shadow Word: Pain (удар при обновлении)", (instant_raw + potency) * magical * spell_crit * hits)
        elif kind == "thunder":
            add("Thunder", (thunder_raw + potency) * magical * spell_crit * hits)
        elif kind == "hellfire":
            raw = (3 + 3 * LEVEL) * (2 if hits == 1 else 0.5 if hits >= 4 else 1)
            add("Hellfire", (raw + potency) * hits * (1.15 if glass else 1.0))
        else:
            continue
        if _has(build, "I0H6"):
            explosion = 0.03 * (20 + 1.6 * stats["int"] + potency)
            if glass:
                explosion *= 1.15
            add("Blood Violence", explosion)
    taken = armor_taken(DUMMY_ARMOR - stats["armor_pen"])
    taken_stab = armor_taken(DUMMY_ARMOR)
    scaled = {}
    for name, amount in sources.items():
        scaled[name] = amount * (taken_stab if name == "Удар тьмы" else taken)
    return sum(scaled.values()), scaled


def compile_events(events: list[tuple[float, str, float]], build: Build, stats: dict) -> dict:
    codes = _codes(build)
    link = _has(build, "I0HL")
    glass = 1.15 if _has(build, "I0JA") else 1.0
    blood = _has(build, "I0H6")
    auto_weight = 0.0
    kinds = ("mind", "void", "naaru", "thunder", "swp_i")
    magic_base = {kind: 0.0 for kind in kinds}
    magic_slope = {kind: 0.0 for kind in kinds}
    swp_base_term = 0.0
    swp_slope_term = 0.0
    swp_pot_base = 0.0
    swp_pot_slope = 0.0
    hellfire_exec = 0.0
    hellfire_raw = 0.0
    blood_exec = 0.0
    for when, kind, hits in events:
        execute = _execute_factor(stats, when)
        base, slope = _magic_factors(codes, when)
        if kind == "auto":
            auto_weight += execute * _physical_multiplier(codes, when) * hits
        elif kind in magic_base:
            magic_base[kind] += base * hits
            magic_slope[kind] += slope * hits
        elif kind == "swp":
            link_factor = (1.15 + 0.10 * hits) if link else 1.0
            swp_base_term += link_factor * hits * base
            swp_slope_term += link_factor * hits * slope
            swp_pot_base += hits * base
            swp_pot_slope += hits * slope
        elif kind == "hellfire":
            hellfire_raw = (3 + 3 * LEVEL) * (2 if hits == 1 else 0.5 if hits >= 4 else 1)
            hellfire_exec += hits
        if blood:
            blood_exec += 1.0
    return {
        "glass": glass,
        "auto_weight": auto_weight,
        "magic_base": magic_base,
        "magic_slope": magic_slope,
        "swp_base_term": swp_base_term,
        "swp_slope_term": swp_slope_term,
        "swp_pot_base": swp_pot_base,
        "swp_pot_slope": swp_pot_slope,
        "hellfire_exec": hellfire_exec,
        "hellfire_raw": hellfire_raw,
        "blood_exec": blood_exec,
    }


def score_compiled(
    compiled: dict,
    stats: dict,
    potency: float,
    crit: float,
    mastery_stat: float,
    luck: float = 0.0,
) -> float:
    spell_crit = _crit_factor(crit, stats["spell_mult"] + stats["rating"]) if stats["spell_crit"] else 1.0
    attack_crit = _crit_factor(crit, 2 + stats["rating"])
    mastery = 1.10 + 0.006 * mastery_stat
    tick_base = (15 + 0.30 * stats["int"]) * mastery
    instant_raw = (75 + 1.50 * stats["int"]) * mastery
    total = (
        (stats["ad"] + potency * stats["attack_potency"])
        * stats["auto_pct"]
        * attack_crit
        * compiled["auto_weight"]
    )

    def magical_weight(kind: str) -> float:
        return compiled["magic_base"][kind] + compiled["magic_slope"][kind] * mastery_stat

    mind_raw = (80 + 1.50 * stats["int"]) * (1 + 0.01 * stats["ad"])
    void_raw = (85 + 0.15 * stats["mana_max"]) * (1 + 0.007 * stats["int"])
    total += (mind_raw + potency) * spell_crit * magical_weight("mind")
    total += (void_raw + potency) * spell_crit * magical_weight("void")
    total += (25 + 0.40 * stats["int"] + potency) * spell_crit * magical_weight("naaru")
    total += (35 + 2 * stats["int"] + potency) * spell_crit * magical_weight("thunder")
    total += (instant_raw + potency) * spell_crit * magical_weight("swp_i")
    swp_link = compiled["swp_base_term"] + compiled["swp_slope_term"] * mastery_stat
    swp_pot = compiled["swp_pot_base"] + compiled["swp_pot_slope"] * mastery_stat
    total += spell_crit * (tick_base * swp_link + potency * swp_pot)
    if compiled["hellfire_exec"]:
        total += (compiled["hellfire_raw"] + potency) * compiled["glass"] * compiled["hellfire_exec"]
    if compiled["blood_exec"]:
        total += 0.03 * (20 + 1.6 * stats["int"] + potency) * compiled["glass"] * compiled["blood_exec"]
    total *= armor_taken(DUMMY_ARMOR - stats["armor_pen"])
    if stats["stab_chance"] and compiled["auto_weight"]:
        chance = stats["stab_chance"] * (1 + luck)
        raw = stats["stab_ratio"] * stats["ad"]
        stab = (
            (raw + potency * stats["attack_potency"])
            * stats["auto_pct"]
            * attack_crit
            * CHAOS_UNARMORED
            * chance
            * compiled["auto_weight"]
        )
        total += stab * armor_taken(DUMMY_ARMOR)
    return total


def simulate(
    build: Build,
    targets: int = 1,
    counter: dict | None = None,
    bound_spell: str | None = None,
) -> Report:
    if _wears(build, "I00D") and bound_spell is None:
        best_report = None
        best_counter = None
        for spell in ("Shadow Word: Pain", "Mind Spike", "Void Rift", "Divine Image"):
            trial_counter: dict | None = {"targets": targets} if counter is not None else None
            report = simulate(build, targets, trial_counter, spell)
            if best_report is None or report.dps > best_report.dps:
                best_report = report
                best_counter = trial_counter
        if counter is not None and best_counter is not None:
            counter.clear()
            counter.update(best_counter)
        return best_report
    stats = character(build)
    events: list[tuple[float, str, float]] = []
    actions: list[tuple[float, str]] = []

    def record(when: float, kind: str, hits: float = 1.0) -> None:
        events.append((when, kind, hits))

    duration = 12.0 if _has(build, "I0HL") else 10.0
    spell_cd = {
        "Shadow Word: Pain": _ability_cd(6, stats, bound_spell == "Shadow Word: Pain"),
        "Mind Spike": _ability_cd(8, stats, bound_spell == "Mind Spike"),
        "Void Rift": _ability_cd(10, stats, bound_spell == "Void Rift"),
        "Divine Image": _ability_cd(15 if _has(build, "I0SB") else 16, stats, bound_spell == "Divine Image"),
    }
    costs = {
        "Shadow Word: Pain": 15,
        "Mind Spike": 25,
        "Void Rift": 40,
        "Divine Image": 30,
    }
    ready = {name: 0.0 for name in spell_cd}
    mana = stats["mana_max"]
    swp_exp = [0.0] * targets
    naaru_until = 0.0
    hero_ready = 0.0
    busy_until = 0.0
    pending: list[tuple[float, int, str]] = []
    seq = 0

    def push(when: float, kind: str) -> None:
        nonlocal seq
        if when < FIGHT:
            seq += 1
            heapq.heappush(pending, (when, seq, kind))

    push(0.0, "swing")
    if _has(build, "I0H3"):
        push(0.0, "hellfire")

    def weakest_swp(now: float) -> int:
        return min(range(targets), key=lambda index: swp_exp[index])

    def swp_apply(now: float, index: int) -> None:
        if swp_exp[index] > now:
            record(now, "swp_i")
        if not any(expiry > now for expiry in swp_exp):
            push(now + stats["swp_period"], "swp")
        swp_exp[index] = now + duration

    def naaru_hit(now: float) -> None:
        record(now, "naaru")
        if _has(build, "I0SC"):
            ready["Mind Spike"] = max(now, ready["Mind Spike"] - 0.4)

    def resolve(name: str, now: float) -> None:
        nonlocal naaru_until
        if name == "Mind Spike":
            record(now, "mind")
            if _has(build, "I0KF"):
                swp_apply(now, 0)
            if _has(build, "I0H5"):
                record(now, "thunder", 0.18 * targets)
        elif name == "Void Rift":
            push(now + (1.5 if _has(build, "I0HP") else 2.0), "void")
            if _has(build, "I0H5"):
                record(now, "thunder", 0.18 * targets)
        elif name == "Shadow Word: Pain":
            swp_apply(now, weakest_swp(now))
            if _has(build, "I0H5"):
                record(now, "thunder", 0.18 * targets)
        elif name == "Divine Image":
            naaru_until = now + 10
            push(now + 1, "naaru")
        if name != "Divine Image" and _has(build, "I0SB") and now < naaru_until:
            naaru_hit(now)

    def begin_cast(name: str, now: float) -> None:
        nonlocal mana, busy_until, hero_ready
        mana -= costs[name]
        ready[name] = now + spell_cd[name]
        actions.append((now, name))
        busy_until = now + CAST_POINT + CAST_BACKSWING
        hero_ready = busy_until
        push(now + CAST_POINT, "finish:" + name)

    def choose(now: float) -> str | None:
        order = ["Divine Image", "Mind Spike", "Void Rift"]
        if any(expiry < now + 1 for expiry in swp_exp):
            order.insert(0, "Shadow Word: Pain")
        for name in order:
            if ready[name] <= now and mana >= costs[name]:
                if name == "Divine Image" and naaru_until > now:
                    continue
                return name
        return None

    while pending:
        event_time = pending[0][0]
        while hero_ready <= event_time and hero_ready < FIGHT:
            cast_name = choose(hero_ready)
            if cast_name is None:
                break
            begin_cast(cast_name, hero_ready)
        when, _order, kind = heapq.heappop(pending)
        if when >= FIGHT:
            break
        if kind == "swing":
            if when < busy_until:
                push(busy_until, "swing")
            else:
                record(when, "auto")
                hero_ready = max(hero_ready, when + stats["stun_per_swing"])
                push(when + stats["swing"] + stats["stun_per_swing"], "swing")
        elif kind.startswith("finish:"):
            resolve(kind.split(":", 1)[1], when)
        elif kind == "swp":
            active = sum(1 for expiry in swp_exp if expiry > when)
            if active:
                record(when, "swp", active)
                push(when + stats["swp_period"], "swp")
        elif kind == "void":
            record(when, "void", targets)
            if _has(build, "I0HP"):
                dotted = sum(1 for expiry in swp_exp if expiry > when)
                if dotted:
                    record(when, "swp_i", 0.25 * dotted)
        elif kind == "naaru":
            if when <= naaru_until:
                naaru_hit(when)
                if when + 1 <= naaru_until:
                    push(when + 1, "naaru")
        elif kind == "hellfire":
            record(when, "hellfire", targets)
            push(when + 1.25, "hellfire")

    if counter is not None:
        counter["events"] = events
        counter["targets"] = targets
        if bound_spell is None:
            return Report(build, 0.0, 0.0, {}, actions, stats, targets)
    total, sources = score_events(events, build, stats)
    return Report(build, total / FIGHT, total, sources, actions, stats, targets)


def _item_score(item: Item) -> float:
    return (
        item.intel * 4
        + item.all_stats * 4
        + item.potency * 12
        + item.damage * 2
        + item.mana * 0.08
        + item.mastery * 0.8
        + item.haste * 5
        + item.crit * 2
        + item.attack_speed * 2
        + item.damage_pct * 10
        + (30 if item.spell_crit else 0)
    )


def _polish_items(build: Build, pool: list[Item]) -> Build:
    current = list(build.items)
    while len(current) < 6:
        current.append(pool[len(current)])
    best = build
    best_dps = simulate(best).dps
    improved = True
    passes = 0
    while improved and passes < 6:
        improved = False
        passes += 1
        for slot in range(6):
            for candidate in pool:
                if any(candidate.rawcode == owned.rawcode for owned in current):
                    continue
                trial_items = current.copy()
                trial_items[slot] = candidate
                trial = Build(build.talents, build.glyphs, tuple(trial_items), build.potency_points, build.mastery_points)
                dps = simulate(trial).dps
                if dps > best_dps + 0.05:
                    best_dps = dps
                    best = trial
                    current = trial_items
                    improved = True
    return best


def search() -> Report:
    items = load_items()
    pool = sorted(items, key=_item_score, reverse=True)[:36]
    seed = tuple(pool[:6])
    best: Report | None = None
    for talents in itertools.combinations(TALENTS, 3):
        for glyphs in itertools.combinations(GLYPHS, 3):
            for potency_points in range(SKILL_POINTS + 1):
                build = Build(
                    frozenset(talents),
                    frozenset(glyphs),
                    seed,
                    potency_points,
                    SKILL_POINTS - potency_points,
                )
                report = simulate(build)
                if best is None or report.dps > best.dps:
                    best = report
    assert best is not None
    polished = _polish_items(best.build, pool)
    final = simulate(polished)
    for potency_points in range(SKILL_POINTS + 1):
        trial = Build(
            polished.talents,
            polished.glyphs,
            polished.items,
            potency_points,
            SKILL_POINTS - potency_points,
        )
        report = simulate(trial)
        if report.dps > final.dps:
            final = report
    return simulate(_polish_items(final.build, pool))


def _ignored_lines(item: Item) -> list[str]:
    handled = (
        "abilities have their base cooldown reduced",
        "bound spell has its base cooldown reduced",
        "Critical Strike bonus damage",
        "cooldowns of all abilities",
        "cooldown of all abilities",
        "base cooldown of all abilities",
        "Stun you",
        "Potency at double effectiveness",
        "Magical Type effects benefit from Critical Strike",
        "more damage to enemies below",
        "auto-attacks by",
    )
    lines = []
    for line in item.tip.split("\n"):
        text = line.strip()
        if not (text.startswith("Equip:") or text.startswith("Use:")):
            continue
        if any(phrase in text for phrase in handled):
            continue
        lines.append(text)
    return lines


def format_report(report: Report) -> str:
    stats = report.stats
    lines = [
        f"Shadow Priest, уровень 6, {report.targets} цел., 30 секунд",
        f"DPS {report.dps:.1f}    урон {report.total:.0f}",
        "",
        "Таланты: " + ", ".join(sorted(report.build.talents)),
        "Глифы: " + ", ".join(sorted(report.build.glyphs)),
        f"Очки навыков: крит {report.build.crit_points}, Potency {report.build.potency_points}, Luck {report.build.luck_points}, Mastery {report.build.mastery_points}",
        "Предметы:",
    ]
    for item in report.build.items:
        lines.append(f"  {item.name}")
    lines += [
        "",
        f"Интеллект {stats['int']:.0f}   сила атаки {stats['ad']:.1f}   Potency {stats['potency']:.1f}   Mastery {stats['mastery']:.0f}",
        f"крит {stats['crit']:.0f}%   рейтинг крита {stats['rating']:.2f}   спешка {stats['haste'] * 100:.1f}%   скорость атаки {stats['attack_speed'] * 100:.1f}%",
        f"мана {stats['mana_max']:.0f}   взмах {stats['swing']:.2f} с   тик Shadow Word: Pain {stats['swp_period']:.2f} с",
        "",
        "Источники урона",
    ]
    for name, amount in sorted(report.sources.items(), key=lambda pair: -pair[1]):
        lines.append(f"  {name:<42} {amount / report.total * 100:5.1f}%   {amount / FIGHT:7.1f} dps")
    lines += ["", "Порядок кнопок"]
    for moment, action in report.actions:
        lines.append(f"  {moment:5.2f}  {action}")
    ignored = []
    for item in report.build.items:
        extra = _ignored_lines(item)
        if extra:
            ignored.append(f"{item.name}: " + " ".join(extra))
    if ignored:
        lines += ["", "Эффекты предметов, которые симулятор не считает:"]
        lines.extend(f"  {line}" for line in ignored)
    lines += [
        "",
        "Как считается бой",
        "Здоровье каждой цели падает линейно: 100% на 0 с, смерть на 30 с.",
        "Catharsis берёт текущее здоровье цели. Казнь Aruzal — только автоатаки, когда у цели 25% здоровья или меньше.",
        f"Броня манекена {DUMMY_ARMOR:.0f}: медиана монстров на Insane. Формула карты, коэффициент {ARMOR_FACTOR:.2f}.",
        "Заклинания жреца идут как обычный урон, поэтому броня их тоже режет. Сопротивление магии у этих монстров не найдено.",
        f"Каст: {CAST_POINT:.2f} с до эффекта и ещё {CAST_BACKSWING:.2f} с герой не атакует и не кастует. Ранги умений 1.",
        "Крит и Thunder взяты ожиданием, без случайного броска.",
        "Naaru — призванный юнит, но урон наносит жрец. Глифы призыва на этот удар не попадают.",
        "Жреца держит лекарь на полном здоровье, поэтому удвоение Insanity ниже 40% не включается.",
    ]
    return "\n".join(lines)


WIN_ITEMS = (
    "Tablet of Life",
    "Aruzal, Fang of Neltharion",
    "Gar'thok's Axe",
    "Heart of Wyrmrest",
    "Predaplant Thorn",
    "Razorwind",
)
WIN_TALENTS = frozenset({"I0PS", "I0PU", "I0SC"})
WIN_GLYPHS = frozenset({"I07B", "I0JA", "I0AV"})


def saved_build() -> Build:
    by_name = {item.name: item for item in load_items()}
    missing = [name for name in WIN_ITEMS if name not in by_name]
    if missing:
        raise KeyError(", ".join(missing))
    return Build(WIN_TALENTS, WIN_GLYPHS, tuple(by_name[name] for name in WIN_ITEMS), SKILL_POINTS, 0)


def format_comparison(reports: list[Report]) -> str:
    lines = [
        "Shadow Priest, уровень 6, та же связка, 30 секунд",
        "Таланты: Catharsis, Insanity, Touch of the Naaru",
        "Глифы: Fortitude, Glass Cannon, Unsealed Power",
        "Очки: Potency 5",
        "",
        f"{'Цели':<8}{'DPS':>10}{'Урон':>10}",
    ]
    for report in reports:
        lines.append(f"{report.targets:<8}{report.dps:10.1f}{report.total:10.0f}")
    for report in reports:
        lines += ["", format_report(report)]
    return "\n".join(lines)


def main() -> None:
    build = saved_build()
    reports = [simulate(build, targets) for targets in (1, 2, 3, 4, 5)]
    text = format_comparison(reports)
    path = Path(__file__).resolve().parents[1] / "extract" / "shadow-targets.txt"
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(text)
