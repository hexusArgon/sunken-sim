# -*- coding: utf-8 -*-
"""Batched next-event timeline for Dragon Sentinel (ruby / obsidian / emerald).

Inlined CPU-exact _simulate (event heap + best-of POLICIES). Sulfuras → overflow.
torch/device kept for API parity with other GPU timelines.
"""
from __future__ import annotations

import heapq
import re as _re

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
from sunken_sim import dragon_sentinel as mod

# Bind module-level names used by the inlined fight body
SPECS = mod.SPECS
POLICIES = mod.POLICIES
SPEC_LEVEL = mod.SPEC_LEVEL
stats_of = mod.stats_of
_has = mod._has
_cooldown = mod._cooldown
_Dither = mod._Dither
RANK = mod.RANK

# Pull every TALENT_*/constant the fight references
_g = globals()
for _n in dir(mod):
    if _n[:1] == "_":
        continue
    if _n.isupper() or _n.startswith("TALENT_") or _n.startswith("GLYPH_"):
        _g[_n] = getattr(mod, _n)

# Also common non-upper helpers/constants that may be needed
for _n in (
    "WHITE_BASE", "SWING", "BASE_ARMOR", "AGI_ARMOR", "SCALES_ARMOR",
    "OBSIDIAN_FORM_ARMOR", "FORM_CD", "LIFE_CD", "DRAKE_CD", "BOLT_CD",
    "FIRE_CD", "CLAW_CD", "BRAND_CD", "BURNOUT_CD", "WORLD_CD",
):
    if hasattr(mod, _n):
        _g[_n] = getattr(mod, _n)


class _Overflow(Exception):
    pass


def generate_dragon_sentinel_timelines(torch, device, builds, spec: str, targets: int):
    if spec not in ("ruby", "obsidian", "emerald"):
        raise ValueError(f"dragon_sentinel GPU timeline specs ruby/obsidian/emerald, got {spec}")
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



def _fight_one(build, targets: int, spec: str, policy: tuple[bool, bool]):
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

    sources: dict[str, float] = Ledger({"Автоатака": 0.0})
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
        sources.add_exec(name, total, now, execute)
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
            # v2.5.2b: Obsidian no longer gains +3 Dragonfury per spellcast.
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
            sources.add_exec("Всплеск огня", splash, moment, _execute_factor(stats, moment))
            note_damage_mana(targets)
        if sulfuras is not None:
            execute = _execute_factor(stats, moment)
            if sulfuras.attack():
                splash = strength * typed("magical", moment) * taken(0, moment) * execute * targets
                splash *= _crit_factor(stats["crit"], 2.0 + stats["rating"])
                sources.add_exec("Sulfuras", splash, moment, execute)
                note_damage_mana(targets)
            echo = power * taken(0, moment) * execute * sulfuras_echo_chance(stats["luck"])
            sources.add_exec("Sulfuras (удар)", echo, moment, execute)
        next_attack = moment + attack_interval(moment)

    total = sum(sources.values())
    recover(FIGHT)
    mana_left = 0.0 if mana_max <= 0 else 100.0 * mana / mana_max
    stats = dict(stats)
    stats.update({f"n_{k}": float(v) for k, v in counters.items()})
    stats["policy_lifebinder"] = 1.0 if use_life else 0.0
    stats["policy_form"] = 1.0 if use_form else 0.0
    stats["spec_level"] = float(SPEC_LEVEL[spec])
    return list(sources.events), stats, total

