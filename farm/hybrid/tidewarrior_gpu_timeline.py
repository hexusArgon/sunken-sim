# -*- coding: utf-8 -*-
"""Batched next-event timeline for Tidewarrior.

Inlined CPU-exact _simulate + best-of POLICIES. Sulfuras → overflow.
torch/device kept for API parity with other GPU timelines.
"""
from __future__ import annotations



from sunken_sim.shadow import (
    CAST_BACKSWING,
    CAST_POINT,
    DUMMY_ARMOR,
    FIGHT,
    LEVEL,
    Sulfuras,
    _crit_factor,
    _execute_factor,
    _wears,
    armor_taken,
    attack_mana_gain,
    cast_mana_back,
    sulfuras_echo_chance,
    target_hp,
)
from sunken_sim.ledger import Ledger, attach
from sunken_sim import tidewarrior as mod

SPECS = mod.SPECS
POLICIES = mod.POLICIES
stats_of = mod.stats_of
_has = mod._has
_cooldown = mod._cooldown
RANK = getattr(mod, "RANK", 1)
if hasattr(mod, "_chance"):
    _chance = mod._chance
if hasattr(mod, "_Dither"):
    _Dither = mod._Dither

_g = globals()
for _n in dir(mod):
    if _n[:1] == "_":
        continue
    if _n.isupper() or _n.startswith("TALENT_") or _n.startswith("GLYPH_"):
        _g[_n] = getattr(mod, _n)


class _Overflow(Exception):
    pass


def generate_tidewarrior_timelines(torch, device, builds, spec: str, targets: int):
    if spec not in ('myrmidon', 'guardian'):
        raise ValueError(f"tidewarrior GPU timeline unexpected spec {spec}")
    if not builds:
        return []
    _ = (torch, device)
    try:
        for b in builds:
            if _wears(b, "I0BR"):
                raise _Overflow("sulfuras")
        return [_best_fight(b, int(targets), spec) for b in builds]
    except _Overflow:
        out = []
        for b in builds:
            report = mod.simulate(b, int(targets), spec)
            out.append((list(report.events), report.stats))
        return out


def _best_fight(build, targets, spec):
    best = None
    for policy in POLICIES:
        events, stats, total = _fight_one(build, targets, spec, policy)
        if best is None or total > best[0] + 1e-9:
            best = (total, events, stats)
    return best[1], best[2]


def _fight_one(build: Build, targets: int, spec: str, policy: tuple[bool, bool]) -> Report:
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
    return list(sources.events), stats, total
