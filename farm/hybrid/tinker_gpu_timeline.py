# -*- coding: utf-8 -*-
"""Batched next-event timeline for Tinker.

Inlined CPU-exact _simulate + best-of POLICIES. Sulfuras → overflow.
torch/device kept for API parity with other GPU timelines.
"""
from __future__ import annotations

import heapq


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
from sunken_sim import tinker as mod

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


MAX_STEPS = 400000


def generate_tinker_timelines(torch, device, builds, spec: str, targets: int, policies=None):
    """Best-policy rows by default, or one explicit fixed policy per input row."""
    if spec not in mod.SPECS:
        raise ValueError(f"tinker GPU timeline unexpected spec {spec}")
    if policies is not None:
        if len(policies) != len(builds) or any(p not in mod.policies_for(spec) for p in policies):
            raise ValueError("one valid Tinker policy is required per build")
    if not builds:
        return []
    _ = (torch, device)
    try:
        for b in builds:
            if _wears(b, "I0BR"):
                raise _Overflow("sulfuras")
        if policies is None:
            return [_best_fight(b, int(targets), spec) for b in builds]
        return [_fight_one(b, int(targets), spec, p)[:2] for b, p in zip(builds, policies)]
    except _Overflow:
        out = []
        for i, b in enumerate(builds):
            report = (mod.simulate(b, int(targets), spec) if policies is None else
                      mod._simulate(b, int(targets), spec, policies[i]))
            out.append((list(report.events), report.stats))
        return out


def _best_fight(build, targets, spec):
    best = None
    for policy in mod.policies_for(spec):
        events, stats, total = _fight_one(build, targets, spec, policy)
        if best is None or total / FIGHT > best[0] / FIGHT + 1e-9:
            best = (total, events, stats)
    return best[1], best[2]


def _fight_one(build: Build, targets: int, spec: str, policy: tuple[bool, bool]) -> Report:
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

    sources: dict[str, float] = Ledger({"Автоатака": 0.0})
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
                 potency_scale: float = 1.0, mult: float = 1.0, source_scale: float = 1.0) -> float:
        chance = stats["crit"]
        execute = _execute_factor(stats, now)
        factor = typed(kind, now) * mult
        if attack:
            factor *= _crit_factor(chance, 2.0 + stats["rating"])
        elif stats["spell_crit"]:
            factor *= _crit_factor(chance, stats["spell_mult"] + stats["rating"])
        weight, coeff = 0.0, 0.0
        for _t in tgts:
            weight += raw * factor * taken(True)
            coeff += potency_scale * factor * taken(True)
        total = (weight + stats["potency"] * coeff) * execute
        sources.add_exec(name, total * source_scale, now, execute,
                         raw_weight=weight * source_scale, pot_coeff=coeff * source_scale)
        # Scaling displayed auto damage must not scale hit/proc/mana counts.
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
        factor = (1.0 + pet_bonus(now)) * typed(kind, now) * mult * (1.0 + increase)
        if attack:
            factor *= _crit_factor(stats["summon_crit"] + extra_crit, 2.0 + stats["summon_rating"])
        factor *= taken(False) * count
        weight, coeff = raw * factor, factor
        execute = _execute_factor(stats, now)
        dealt = (weight + stats["potency"] * coeff) * execute
        sources.add_exec(name, dealt, now, execute, raw_weight=weight, pot_coeff=coeff)
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
        if loops > MAX_STEPS:
            raise _Overflow("steps")
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
        hero_hit("Автоатака", power, moment, [0], kind="physical", attack=True,
                 potency_scale=stats["attack_potency"], source_scale=stats["auto_pct"])
        napalm("attack", 0, moment)
        overclock(None, moment, True)
        if has(TALENT_WRIST):
            for _ in range(2):
                if rolls["wrist"].roll(0.33 * luck_mult(moment)):
                    wrist_missiles += 1
        gain_mana(attack_mana_gain(stats))
        if stats["fire_orb"]:
            splash = (20.0 + 0.35 * strength) * targets * taken(True) * _execute_factor(stats, moment)
            sources.add_exec("Всплеск огня", splash, moment, _execute_factor(stats, moment))
            note_damage_mana(targets)
        if sulfuras is not None:
            execute = _execute_factor(stats, moment)
            if sulfuras.attack():
                splash = strength * typed("magical", moment) * taken(True) * execute * targets
                splash *= _crit_factor(stats["crit"], 2.0 + stats["rating"])
                sources.add_exec("Sulfuras", splash, moment, execute)
                note_damage_mana(targets)
            echo = power * taken(True) * execute * sulfuras_echo_chance(stats["luck"])
            sources.add_exec("Sulfuras (удар)", echo, moment, execute)
        next_attack = moment + attack_interval(moment)

    total = sum(sources.values())
    recover(FIGHT)
    mana_left = 0.0 if mana_max <= 0 else 100.0 * mana / mana_max
    stats = dict(stats)
    stats.update({f"n_{k}": float(v) for k, v in counters.items()})
    stats["policy_reinforce"] = 1.0 if use_reinforce else 0.0
    stats["policy_exo"] = 1.0 if use_exo else 0.0
    stats["spec_level"] = float(SPEC_LEVEL[spec])
    return list(sources.events), stats, total
