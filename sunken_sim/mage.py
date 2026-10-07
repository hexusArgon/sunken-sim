"""Mage simulator for Sunken City, level 6.

Frost, Arcane and Fire use the same fight rules as the priest: 30 seconds,
expected damage, rank-1 buttons. Formulas follow the map triggers. Where a
tooltip and a trigger disagree, the trigger wins.
"""

from __future__ import annotations

import heapq

from sunken_sim.shadow import (
    CAST_BACKSWING,
    CAST_POINT,
    CHAOS_UNARMORED,
    DUMMY_ARMOR,
    FIGHT,
    LEVEL,
    MEDIAN_MONSTER_HP,
    ORB_MODE,
    SKILL_POINTS,
    Build,
    Report,
    attack_mana_gain,
    cast_mana_back,
    _codes,
    _crit_factor,
    _execute_factor,
    _has,
    _magic_factors,
    _physical_multiplier,
    _wears,
    armor_taken,
    character,
    target_hp,
)

# O00G: 10/8/32 and +1.0/+0.8/+3.2 per level. White hit is 10 base + 1 die.
BASE_STR = int(10 + (LEVEL - 1) * 1.0)
BASE_AGI = int(8 + (LEVEL - 1) * 0.8)
BASE_INT = int(32 + (LEVEL - 1) * 3.2)
WHITE_BASE = 11.0

TALENTS = {
    "I0KQ": "Pyromaniac",
    "I0O0": "Amplification",
    "I0QA": "Ice Lance",
    "I0KP": "Supernova",
    "I0KO": "Ice Shards",
    "I0KS": "Firestarter",
    "I0KU": "Archmage",
    "I0Q7": "Freezeburn",
    "I0UP": "Lava Spawn",
    "I0NZ": "Burning Fury",
    "I0Q8": "Runemastery",
    "I0KT": "Frostbite",
    "I0UQ": "Greater Pyroblast",
    "I0QB": "Overpowered",
    "I0UO": "Frostfire Bolt",
    "I0KV": "Arcane Surge",
    "I0KR": "Blazing Soul",
    "I0Q9": "Cold Splinters",
}

SPECS = ("frost", "arcane", "fire")


def sheet(build: Build) -> dict[str, float]:
    stats = character(build, BASE_STR, BASE_AGI, BASE_INT, WHITE_BASE, bake_timed_buffs=False)
    arch = 1.35 if _has(build, "I0KU") else 1.0
    if _has(build, "I0KQ"):
        stats["potency"] += 3 + 0.05 * stats["int"] * arch
    stats["arch"] = arch
    stats["bomb_period"] = _bomb_period(build, stats)
    return stats


def _bomb_period(build: Build, stats: dict[str, float]) -> float:
    period = 0.75
    if _has(build, "I0KR"):
        period /= 1.15 + (0.50 * stats["potency"]) / 100.0
    if _wears(build, "I0UR"):
        period /= 1.25
    return period


def _cd(base: float, stats: dict, bound: bool = False, extra_flat: float = 0.0) -> float:
    temp = stats["cd_temp"] * (0.70 if bound else 1.0)
    return max(0.5, (base * temp - stats["flat_cdr"] - extra_flat) / (1.0 + stats["haste"]))


def _buttons(spec: str) -> list[str]:
    common = ["Living Bomb", "Arcane Blast", "Ring of Frost"]
    if spec == "frost":
        return ["Living Bomb", "Blizzard", "Arcane Blast", "Ring of Frost"]
    if spec == "fire":
        return ["Living Bomb", "Hydra", "Arcane Blast", "Ring of Frost"]
    return common + ["Evocation"]


def _raws(stats: dict, build: Build) -> dict[str, float]:
    intel = stats["int"]
    arch = stats["arch"]
    shards = 1.20 if _has(build, "I0KO") else 1.0
    starter = 1.25 if _has(build, "I0KS") else 1.0
    gloves = 1.15 if _wears(build, "I0UT") else 1.0
    per = (10 + 0.10 * intel * arch) if _has(build, "I0UQ") else (10 + 0.08 * intel * arch)
    return {
        "bomb": 10 + 0.12 * intel * arch,
        "burst": 10 + 0.12 * intel,
        "firebomb": (40 + intel * arch) * starter,
        "ring": (60 + 1.80 * intel * arch) * gloves,
        "blast": 80 + 2.50 * intel * arch,
        "nova": 50 + 3.0 * intel * arch,
        "lance": 20 + 0.50 * intel * arch,
        "bolt": 20 + 0.90 * intel * arch + 50,
        "pyro": per,
        "blizzard": (5 + 0.50 * intel * arch) * shards,
        "hydra": 5 + int(0.40 * intel * arch),
        "thunder": 35 + 2 * intel,
    }


def simulate(
    build: Build,
    targets: int = 1,
    counter: dict | None = None,
    bound_spell: str | None = None,
    spec: str = "frost",
    *,
    use_history: bool = True,
) -> Report:
    from sunken_sim.history import recall, remember

    if spec not in SPECS:
        raise ValueError(spec)
    if use_history and not (counter is not None and bound_spell is None):
        cached = recall("mage", spec, build, targets, bound_spell)
        if cached is not None:
            return cached
    buttons = _buttons(spec)
    if _wears(build, "I00D") and bound_spell is None:
        best_report = None
        best_counter = None
        for spell in buttons:
            if spell == "Evocation":
                continue
            trial_counter: dict | None = {"targets": targets} if counter is not None else None
            report = simulate(build, targets, trial_counter, spell, spec, use_history=use_history)
            if best_report is None or report.dps > best_report.dps:
                best_report = report
                best_counter = trial_counter
        if counter is not None and best_counter is not None:
            counter.clear()
            counter.update(best_counter)
        if not use_history:
            return best_report
        return remember("mage", spec, best_report, bound_spell)

    stats = sheet(build)
    if spec == "fire":
        stats["swing"] = 2.0
    else:
        stats["swing"] = 2.0 / (1.0 + stats["attack_speed"])
    raw = _raws(stats, build)
    events: list[tuple] = []
    actions: list[tuple[float, str]] = []

    greater = _has(build, "I0UQ")
    frostbite = _has(build, "I0KT")
    freezeburn = _has(build, "I0Q7")
    lance = _has(build, "I0QA")
    surge = _has(build, "I0KV")
    burning = _has(build, "I0NZ")
    lava = _has(build, "I0UP")
    nova = _has(build, "I0KP")
    bolt_talent = _has(build, "I0UO")
    overpowered = _has(build, "I0QB")
    girdle = _wears(build, "I0UX")
    pads = _wears(build, "I0UY")
    staff = _wears(build, "I0UW")
    mantle = _wears(build, "I0UU")
    redirect = _wears(build, "I0UV")
    thunder = _has(build, "I0H5")
    hellfire = _has(build, "I0H3")
    evocation = spec == "arcane"
    cinder_on = spec == "fire" or overpowered or pads
    pyro_on = spec == "fire" or overpowered
    stacks_on = spec == "arcane" or girdle
    split_on = spec == "fire" or girdle
    cinder_chance = (0.25 + (0.05 if staff else 0.0)) * (1.0 + stats["luck"])
    lava_chance = 0.02 * (1.0 + stats["luck"])
    max_charges = 8 if surge else 3
    hydra_duration = 14.0 if burning else 10.0
    waves = int(5.0 * (1.0 + stats["haste"]) + 0.50)
    wave_gap = (0.80 if mantle else 1.0) / (1.0 + stats["haste"])
    bomb_period = stats["bomb_period"]
    burst_chance = 0.15 + (0.15 if _has(build, "I0KR") else 0.0)

    base_cd = {
        "Living Bomb": 8.0,
        "Arcane Blast": 8.0,
        "Ring of Frost": 13.0,
        "Blizzard": 13.0,
        "Hydra": 13.0,
        "Evocation": 13.0,
    }
    extra_flat = {
        "Arcane Blast": 2.0 if _has(build, "I0O0") else 0.0,
        "Hydra": 3.0 if _wears(build, "I0US") else 0.0,
    }
    costs = {
        "Living Bomb": 30.0,
        "Ring of Frost": 40.0,
        "Blizzard": 40.0,
        "Hydra": 40.0,
        "Evocation": 0.0,
    }
    spell_cd = {
        name: _cd(base_cd[name], stats, bound_spell == name, extra_flat.get(name, 0.0))
        for name in buttons
    }
    ready = {name: 0.0 for name in spell_cd}
    mana = stats["mana_max"]
    splinter = 0.0
    frenzy_until = 0.0
    frenzy_charge = 0.0
    crit_until = 0.0
    crit_charge = 0.0
    blast_cost = 30.0
    charges = 0
    cinder = 0.0
    bomb_exp = [0.0] * targets
    bomb_power = [0.0] * targets
    chill_exp = [0.0] * targets
    freeze_exp = [0.0] * targets
    hydras: list[tuple[float, float]] = []
    hydra_ticking = False
    blizzard_until = 0.0
    hero_ready = 0.0
    busy_until = 0.0
    pending: list[tuple[float, int, str]] = []
    seq = 0

    def push(when: float, kind: str) -> None:
        nonlocal seq
        if when < FIGHT:
            seq += 1
            heapq.heappush(pending, (when, seq, kind))

    def bite(index: int, now: float) -> float:
        if not frostbite:
            return 1.0
        if freeze_exp[index] > now:
            return 1.12
        if chill_exp[index] > now:
            return 1.08
        return 1.0

    def bite_all(now: float) -> float:
        if not frostbite:
            return 1.0
        return sum(bite(index, now) for index in range(targets)) / targets

    def alive(now: float) -> float:
        return sum(count for expiry, count in hydras if expiry > now)

    def spawn_hydras(now: float, count: float, duration: float) -> None:
        nonlocal hydra_ticking
        room = 10.0 - alive(now)
        count = min(count, max(0.0, room))
        if count <= 0:
            return
        hydras.append((now + duration, count))
        if not hydra_ticking:
            hydra_ticking = True
            push(now + hydra_gap(now), "hydra")

    def gain_cinder(instances: float, disease: bool, now: float) -> None:
        nonlocal cinder
        if instances <= 0:
            return
        if cinder_on and not disease and cinder < 100:
            cinder = min(100.0, cinder + cinder_chance * instances)
        if lava and not disease:
            spawn_hydras(now, lava_chance * instances, hydra_duration * 0.5)

    def start_bomb(index: int, now: float, power: float) -> None:
        if bomb_exp[index] <= now:
            bomb_power[index] = power
            if not any(expiry > now for expiry in bomb_exp):
                push(now + bomb_period, "bomb")
        else:
            bomb_power[index] = max(bomb_power[index], power)
        bomb_exp[index] = now + 8.0

    def apply_chill(index: int, now: float, duration: float, explicit_freeze: float = 0.0) -> None:
        fresh = chill_exp[index] <= now
        chill_exp[index] = max(chill_exp[index], now + duration)
        if explicit_freeze:
            freeze_exp[index] = max(freeze_exp[index], now + explicit_freeze)
        elif frostbite and fresh:
            freeze_exp[index] = max(freeze_exp[index], now + 1.5)
        if freezeburn and bomb_exp[index] <= now:
            start_bomb(index, now, 0.20 if fresh else 0.08)
        froze = explicit_freeze > 0 or (frostbite and fresh)
        note_splinter(froze)

    def note_splinter(froze: bool) -> None:
        nonlocal splinter
        if not _has(build, "I0Q9"):
            return
        splinter = min(30.0, splinter + (4.0 if froze else 2.0))

    def extra_as(now: float) -> float:
        bonus = 0.0
        if now < frenzy_until:
            bonus += 0.32
        if now < crit_until:
            bonus += stats["crit_as"]
        return bonus

    def current_as(now: float) -> float:
        return max(-0.8, min(4.0, stats["attack_speed"] + extra_as(now)))

    def current_swing(now: float) -> float:
        if spec == "fire":
            return 2.0
        return 2.0 / (1.0 + current_as(now))

    def hydra_gap(now: float) -> float:
        if spec != "fire":
            return 1.4
        return 1.4 / (1.0 + 0.75 * current_as(now))

    def reset_chance() -> float:
        chance = 0.15
        if spec == "arcane":
            chance += 0.05 + 0.002 * (stats["mastery"] + splinter)
        if staff:
            chance += 0.05
        return min(1.0, chance)

    def on_hero_auto(now: float) -> None:
        nonlocal frenzy_charge, frenzy_until, crit_charge, crit_until, mana
        mana = min(stats["mana_max"], mana + attack_mana_gain(stats))
        if stats["frenzy"] and now >= frenzy_until:
            frenzy_charge += 0.18
            if frenzy_charge >= 1.0:
                frenzy_charge -= 1.0
                frenzy_until = now + 5.0
        if stats["crit_as"] > 0 and stats["crit_as_duration"] > 0 and now >= crit_until:
            crit_charge += min(stats["crit"], 100.0) / 100.0
            if crit_charge >= 1.0:
                crit_charge -= 1.0
                crit_until = now + stats["crit_as_duration"]

    def add(when: float, kind: str, hits: float, raw_w: float, pot_w: float, disease: bool = False, **extra) -> None:
        nonlocal mana
        if when >= FIGHT or hits <= 0:
            return
        if stats["damage_mana_pct"]:
            mana = min(stats["mana_max"], mana + stats["damage_mana_pct"] * stats["mana_max"])
        extra["mana"] = mana
        extra["splinter"] = splinter
        events.append((when, kind, hits, raw_w, pot_w, extra))
        gain_cinder(hits, disease, when)

    def cast_lance(now: float) -> None:
        if not lance:
            return
        index = next((i for i in range(targets) if chill_exp[i] <= now), 0)
        taken = bite(index, now)
        add(now, "lance", 1.0, taken, taken)
        apply_chill(index, now, 4.0)

    def finish_blast(now: float) -> None:
        nonlocal charges, cinder, blast_cost
        mult = 1.20 ** charges
        quarter = 0.25 if split_on else 1.0
        taken = bite_all(now)
        if split_on:
            add(now, "blast", 3.0, 3.0 * taken * mult * quarter, 3.0 * taken)
        if pyro_on and cinder >= (50.0 if greater else 30.0):
            spent = cinder
            cinder = 0.0
            magical = greater
            add(
                now,
                "pyro",
                targets,
                targets * taken * spent,
                (targets * taken) if magical else 0.0,
                disease=not magical,
                magical=magical,
            )
        if nova:
            chance = 1.0 if target_hp(now) > 0.90 else 0.10
            weight = targets * chance * taken
            add(now, "nova", weight, weight, weight)
        if bolt_talent:
            chilled = chill_exp[0] > now
            bombed = bomb_exp[0] > now
            bonus = (1.25 if chilled else 1.0) * (1.25 if bombed else 1.0)
            add(now, "bolt", 1.0, bite(0, now) * bonus, bite(0, now) * bonus)
            if chilled and targets > 1:
                splash = (targets - 1) * taken * bonus * 0.15
                add(now, "bolt_splash", targets - 1, splash, splash)
            if chilled and bombed:
                push(now + 0.5, "bolt2")
                chill_exp[0] = now
                bomb_exp[0] = now
                bomb_power[0] = 0.0
        add(now, "blast", 1.0, taken * mult * quarter, taken)
        if stacks_on and charges < max_charges:
            charges += 2 if surge and charges < 3 else 1
            charges = min(charges, max_charges)
            blast_cost = 30.0 * (1.15 ** charges)

    def resolve(name: str, now: float) -> None:
        nonlocal mana, blizzard_until
        cast_lance(now)
        if thunder:
            taken = 0.18 * targets * bite_all(now)
            add(now, "thunder", 0.18 * targets, taken, taken)
        if name == "Living Bomb":
            index = min(range(targets), key=lambda i: bomb_exp[i])
            if bomb_exp[index] > now:
                taken = targets * bite_all(now)
                add(now, "firebomb", targets, taken, taken)
            start_bomb(index, now, 1.0)
            if freezeburn:
                apply_chill(index, now, 4.0)
        elif name == "Ring of Frost":
            push(now + 1.65, "ring")
        elif name == "Blizzard":
            blizzard_until = now + waves * wave_gap
            for wave in range(waves):
                push(now + wave * wave_gap, "wave")
        elif name == "Hydra":
            spawn_hydras(now, 3.0, hydra_duration)
        elif name == "Arcane Blast":
            finish_blast(now)
        elif name == "Evocation":
            push(now + 1.0, "mana")
            push(now + 2.0, "mana")
            push(now + 3.0, "mana")

    def begin_cast(name: str, now: float) -> None:
        nonlocal mana, busy_until, hero_ready, cinder
        spent = blast_cost if name == "Arcane Blast" else costs[name]
        mana -= spent
        mana = min(stats["mana_max"], mana + cast_mana_back(spent, stats))
        duration = spell_cd[name]
        actions.append((now, name))
        busy_until = now + CAST_POINT + CAST_BACKSWING + stats["cast_stun_lock"]
        hero_ready = busy_until
        target = "Arcane Blast" if redirect and "Arcane Blast" in ready else name
        chance = reset_chance()
        if target == name:
            ready[name] = now + duration * (1.0 - chance)
        else:
            ready[name] = now + duration
            remaining = max(0.0, ready[target] - now)
            ready[target] = now + remaining * (1.0 - chance)
        push(now + CAST_POINT, "finish:" + name)

    def affordable(name: str, now: float) -> bool:
        if ready[name] > now:
            return False
        if name == "Blizzard" and blizzard_until > now:
            return False
        if name == "Hydra" and alive(now) >= 10:
            return False
        cost = blast_cost if name == "Arcane Blast" else costs[name]
        return mana >= cost

    def choose(now: float) -> str | None:
        order = []
        if any(expiry < now + 1 for expiry in bomb_exp):
            order.append("Living Bomb")
        if spec == "frost":
            order.append("Blizzard")
        if spec == "fire":
            order.append("Hydra")
        order.extend(["Arcane Blast", "Ring of Frost"])
        waiting = []
        for name in order:
            if name not in ready or ready[name] > now:
                continue
            if name == "Blizzard" and blizzard_until > now:
                continue
            if name == "Hydra" and alive(now) >= 10:
                continue
            waiting.append(name)
            cost = blast_cost if name == "Arcane Blast" else costs[name]
            if mana >= cost:
                return name
        if waiting and evocation and affordable("Evocation", now):
            return "Evocation"
        return None

    push(0.0, "swing")
    if hellfire:
        push(0.0, "hellfire")

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
                on_hero_auto(when)
                taken = bite_all(when)
                add(when, "auto", 1.0, taken, taken)
                if _wears(build, "I07O"):
                    add(when, "splash", targets, targets, targets)
                hero_ready = max(hero_ready, when + stats["stun_per_swing"])
                push(when + current_swing(when) + stats["stun_per_swing"], "swing")
        elif kind.startswith("finish:"):
            resolve(kind.split(":", 1)[1], when)
        elif kind == "bomb":
            active = [(i, bomb_power[i]) for i in range(targets) if bomb_exp[i] > when and bomb_power[i] > 0]
            if active:
                for index, power in active:
                    taken = power * bite(index, when)
                    add(when, "bomb", power, taken, taken)
                    burst = burst_chance * power * targets * bite_all(when)
                    add(when, "burst", burst_chance * power * targets, burst, burst)
                push(when + bomb_period, "bomb")
        elif kind == "wave":
            for index in range(targets):
                taken = bite(index, when)
                add(when, "blizzard", 1.0, taken, taken)
                apply_chill(index, when, 3.0)
        elif kind == "ring":
            freeze_for = 3.0 if _wears(build, "I0UT") else 2.0
            for index in range(targets):
                already = chill_exp[index] > when
                taken = bite(index, when)
                add(when, "ring", 1.0, taken, taken)
                if already:
                    apply_chill(index, when, 3.5, freeze_for)
                else:
                    apply_chill(index, when, 3.5)
        elif kind == "bolt2":
            taken = bite(0, when)
            add(when, "bolt", 1.0, taken, taken)
        elif kind == "hydra":
            count = alive(when)
            if count <= 0:
                hydra_ticking = False
            else:
                bitten = bite_all(when)
                primary = count * bitten * (1.20 if burning else 1.0)
                others = max(0, targets - 1)
                cleave = count * 0.20 * others * bitten
                add(when, "hydra", count, primary, primary)
                if cleave:
                    add(when, "cleave", count * others, cleave, cleave)
                push(when + hydra_gap(when), "hydra")
        elif kind == "hellfire":
            taken = targets * bite_all(when)
            add(when, "hellfire", targets, taken, taken)
            push(when + 1.25, "hellfire")
        elif kind == "mana":
            mana += 0.10 * (stats["mana_max"] - mana)

    mana_left = 0.0 if stats["mana_max"] <= 0 else 100.0 * mana / stats["mana_max"]
    compiled = _compile(events, build, stats, spec, evocation)
    if counter is not None:
        counter["engine"] = "mage"
        counter["compiled"] = compiled
        counter["stats"] = stats
        counter["spec"] = spec
        counter["targets"] = targets
        counter["mana_left"] = mana_left
        if bound_spell is None:
            return Report(build, 0.0, 0.0, {}, actions, stats, targets, mana_left=mana_left)
    total, sources = _score(compiled, stats, build, spec)
    mode = next((name for code, name in ORB_MODE.items() if _wears(build, code)), None)
    shown = dict(stats)
    shown["bomb_period"] = bomb_period
    shown["hydra_swing"] = hydra_gap(0.0) if spec == "fire" else 0.0
    report = Report(build, total / FIGHT, total, sources, actions, shown, targets, mode, bound_spell, mana_left)
    if not use_history:
        return report
    return remember("mage", spec, report, bound_spell)


def _magic(codes, when: float, mana: float, evocation: bool) -> tuple[float, float]:
    extra = (0.08 + mana / 7500.0) if evocation else 0.0
    return _magic_factors(codes, when, extra)


def _compile(events: list[tuple], build: Build, stats: dict, spec: str, evocation: bool) -> dict:
    codes = _codes(build)
    mana = stats["mana_max"]
    buckets = (
        "bomb",
        "burst",
        "firebomb",
        "ring",
        "blast",
        "nova",
        "lance",
        "bolt",
        "bolt_splash",
        "thunder",
        "blizzard",
    )
    base = {kind: 0.0 for kind in buckets}
    slope = {kind: 0.0 for kind in buckets}
    pot_base = {kind: 0.0 for kind in buckets}
    pot_slope = {kind: 0.0 for kind in buckets}
    auto_weight = 0.0
    soul_weight = 0.0
    splash = 0.0
    hell_weight = 0.0
    hell_raw = 0.0
    blood = 0.0
    pyro_base = 0.0
    pyro_slope = 0.0
    pyro_pot_base = 0.0
    pyro_pot_slope = 0.0
    pyro_raw_base = 0.0
    pyro_raw_mastery = 0.0
    pyro_m_base = 0.0
    pyro_m_slope = 0.0
    hydra_base = 0.0
    hydra_slope = 0.0
    hydra_pot_base = 0.0
    hydra_pot_slope = 0.0
    cleave_base = 0.0
    cleave_slope = 0.0
    cleave_pot_base = 0.0
    cleave_pot_slope = 0.0
    glass = 1.15 if _has(build, "I0JA") else 1.0
    blood_on = _has(build, "I0H6")
    fixed_magic = None
    if not evocation and not _has(build, "I0Q9") and "I0QT" not in codes and "I0PS" not in codes:
        fixed_magic = _magic(codes, 0.0, mana, False)

    def factors(extra: dict, magical_hit: bool) -> tuple[float, float]:
        if not magical_hit:
            return 1.0, 0.0
        event_mana = extra.get("mana", mana)
        spl = extra.get("splinter", 0.0)
        if fixed_magic is not None and spl == 0.0:
            base_factor, slope = fixed_magic
        else:
            base_factor, slope = _magic(codes, when, event_mana, evocation)
        return base_factor + slope * spl, slope

    for when, kind, hits, raw_w, pot_w, extra in events:
        if kind == "auto":
            weighed = _execute_factor(stats, when) * _physical_multiplier(codes, when) * raw_w
            auto_weight += weighed
            soul_weight += weighed * target_hp(when)
        elif kind == "splash":
            splash += raw_w
        elif kind == "hellfire":
            hell_raw = (3 + 3 * LEVEL) * (2 if hits == 1 else 0.5 if hits >= 4 else 1)
            hell_weight += raw_w
        elif kind == "pyro":
            magical = bool(extra.get("magical"))
            b, s = factors(extra, magical)
            spl = extra.get("splinter", 0.0)
            fire_m = 0.0075 if spec == "fire" else 0.0
            coef = 1.0 + fire_m * spl
            if magical:
                pyro_base += b * raw_w * coef
                pyro_slope += s * raw_w * coef
                pyro_m_base += b * raw_w * fire_m
                pyro_m_slope += s * raw_w * fire_m
                pyro_pot_base += b * pot_w
                pyro_pot_slope += s * pot_w
            else:
                pyro_raw_base += raw_w * coef
                pyro_raw_mastery += raw_w * fire_m
        elif kind == "hydra":
            b, s = factors(extra, True)
            hydra_base += b * raw_w
            hydra_slope += s * raw_w
            hydra_pot_base += b * pot_w
            hydra_pot_slope += s * pot_w
        elif kind == "cleave":
            b, s = factors(extra, True)
            cleave_base += b * raw_w
            cleave_slope += s * raw_w
            cleave_pot_base += b * pot_w
            cleave_pot_slope += s * pot_w
        elif kind in base:
            b, s = factors(extra, True)
            base[kind] += b * raw_w
            slope[kind] += s * raw_w
            pot_base[kind] += b * pot_w
            pot_slope[kind] += s * pot_w
        if blood_on:
            blood += 1.0
    return {
        "spec": spec,
        "glass": glass,
        "base": base,
        "slope": slope,
        "pot_base": pot_base,
        "pot_slope": pot_slope,
        "auto_weight": auto_weight,
        "soul_weight": soul_weight,
        "splash": splash,
        "hell_weight": hell_weight,
        "hell_raw": hell_raw,
        "blood": blood,
        "pyro_base": pyro_base,
        "pyro_slope": pyro_slope,
        "pyro_pot_base": pyro_pot_base,
        "pyro_pot_slope": pyro_pot_slope,
        "pyro_raw_base": pyro_raw_base,
        "pyro_raw_mastery": pyro_raw_mastery,
        "pyro_m_base": pyro_m_base,
        "pyro_m_slope": pyro_m_slope,
        "hydra_base": hydra_base,
        "hydra_slope": hydra_slope,
        "hydra_pot_base": hydra_pot_base,
        "hydra_pot_slope": hydra_pot_slope,
        "cleave_base": cleave_base,
        "cleave_slope": cleave_slope,
        "cleave_pot_base": cleave_pot_base,
        "cleave_pot_slope": cleave_pot_slope,
        "raw": _raws(stats, build),
        "fire_pyro": spec == "fire",
    }


def _score(compiled: dict, stats: dict, build: Build, spec: str, potency=None, crit=None, mastery=None, luck=None):
    potency = stats["potency"] if potency is None else potency
    crit = stats["crit"] if crit is None else crit
    mastery = stats["mastery"] if mastery is None else mastery
    luck = stats["luck"] if luck is None else luck
    spell_crit = _crit_factor(crit, stats["spell_mult"] + stats["rating"]) if stats["spell_crit"] else 1.0
    attack_crit = _crit_factor(crit, 2 + stats["rating"])
    raw = compiled["raw"]
    sources: dict[str, float] = {}

    def put(name: str, amount: float) -> None:
        if amount:
            sources[name] = sources.get(name, 0.0) + amount

    def magic_spell(kind: str, raw_hit: float, label: str) -> None:
        mag = compiled["base"][kind] + compiled["slope"][kind] * mastery
        pot = compiled["pot_base"][kind] + compiled["pot_slope"][kind] * mastery
        put(label, spell_crit * (raw_hit * mag + potency * pot))

    put(
        "Автоатака",
        (stats["ad"] + potency * stats["attack_potency"]) * stats["auto_pct"] * attack_crit * compiled["auto_weight"],
    )
    put(
        "Автоатака",
        stats["soul_rate"] * MEDIAN_MONSTER_HP * stats["auto_pct"] * attack_crit * compiled["soul_weight"],
    )
    put("Всплеск огня", (20 + 0.35 * stats["int"]) * compiled["splash"])
    magic_spell("bomb", raw["bomb"], "Living Bomb")
    magic_spell("burst", raw["burst"], "Взрыв Living Bomb")
    magic_spell("firebomb", raw["firebomb"], "Fire Bomb")
    magic_spell("ring", raw["ring"], "Ring of Frost")
    magic_spell("blast", raw["blast"], "Arcane Blast")
    magic_spell("nova", raw["nova"], "Supernova")
    magic_spell("lance", raw["lance"], "Ice Lance")
    magic_spell("bolt", raw["bolt"], "Frostfire Bolt")
    magic_spell("bolt_splash", raw["bolt"], "Всплеск Frostfire")
    magic_spell("thunder", raw["thunder"], "Thunder")
    magic_spell("blizzard", raw["blizzard"], "Blizzard")
    pyro_mag = (
        compiled["pyro_base"]
        + compiled["pyro_slope"] * mastery
        + (compiled["pyro_m_base"] + compiled["pyro_m_slope"] * mastery) * mastery
    )
    pyro_pot = compiled["pyro_pot_base"] + compiled["pyro_pot_slope"] * mastery
    put("Pyroblast", spell_crit * (raw["pyro"] * pyro_mag + potency * pyro_pot))
    put("Pyroblast", raw["pyro"] * (compiled["pyro_raw_base"] + compiled["pyro_raw_mastery"] * mastery))
    hydra_mag = compiled["hydra_base"] + compiled["hydra_slope"] * mastery
    hydra_pot = compiled["hydra_pot_base"] + compiled["hydra_pot_slope"] * mastery
    put(
        "Hydra",
        attack_crit * (raw["hydra"] * hydra_mag + potency * stats["attack_potency"] * hydra_pot),
    )
    cleave_mag = compiled["cleave_base"] + compiled["cleave_slope"] * mastery
    cleave_pot = compiled["cleave_pot_base"] + compiled["cleave_pot_slope"] * mastery
    put(
        "Клив Hydra",
        attack_crit * (raw["hydra"] * cleave_mag + potency * stats["attack_potency"] * cleave_pot),
    )
    if compiled["hell_weight"]:
        put("Hellfire", (compiled["hell_raw"] + potency) * compiled["glass"] * compiled["hell_weight"])
    if compiled["blood"]:
        put("Blood Violence", 0.03 * (20 + 1.6 * stats["int"] + potency) * compiled["glass"] * compiled["blood"])
    if stats["stab_chance"] and compiled["auto_weight"]:
        chance = stats["stab_chance"] * (1 + luck)
        stab_raw = stats["stab_ratio"] * stats["ad"]
        stab = (
            (stab_raw + potency * stats["attack_potency"])
            * stats["auto_pct"]
            * attack_crit
            * CHAOS_UNARMORED
            * chance
            * compiled["auto_weight"]
        )
        sources["Удар тьмы"] = sources.get("Удар тьмы", 0.0) + stab * armor_taken(DUMMY_ARMOR)
    taken = armor_taken(DUMMY_ARMOR - stats["armor_pen"])
    scaled = {}
    for name, amount in sources.items():
        scaled[name] = amount if name == "Удар тьмы" else amount * taken
    return sum(scaled.values()), scaled


def best_points(counter: dict, build: Build) -> tuple[float, tuple[int, int, int, int]]:
    from sunken_sim.search import POINT_SPLITS

    spec = counter.get("spec", "frost")
    targets = counter.get("targets", 1)
    if counter.get("full_points"):
        splits = POINT_SPLITS
    else:
        splits = (
            (0, SKILL_POINTS, 0, 0),
            (0, 0, 0, SKILL_POINTS),
            (SKILL_POINTS, 0, 0, 0),
            (0, 0, SKILL_POINTS, 0),
        )
    best_dps = -1.0
    best = (0, SKILL_POINTS, 0, 0)
    for crit_points, potency_points, luck_points, mastery_points in splits:
        trial = Build(
            build.talents,
            build.glyphs,
            build.items,
            potency_points,
            mastery_points,
            crit_points,
            luck_points,
        )
        report = simulate(trial, targets, spec=spec)
        if report.dps > best_dps:
            best_dps = report.dps
            best = (crit_points, potency_points, luck_points, mastery_points)
    return best_dps, best
