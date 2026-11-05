# -*- coding: utf-8 -*-
"""Batched next-event timeline for Demon Hunter (havoc / vengeance / devourer).

Lockstep python-float scheduling (CPU-exact cast_time = CAST_POINT+CAST_BACKSWING)
with per-row pending heaps for Eye Beam / Collapsing Star. Damage mirrors
sunken_sim.demon_hunter.simulate; ledger KIND_EXEC events collected per row.
Sulfuras → _Overflow → CPU fallback. torch/device kept for API parity with
other GPU timelines; clocks stay on CPU floats (DirectML kind-score after pack).
"""
from __future__ import annotations

import heapq

MAX_STEPS = 400000


class _Overflow(Exception):
    pass


def generate_demon_hunter_timelines(torch, device, builds, spec: str, targets: int):
    if spec not in ("havoc", "vengeance", "devourer"):
        raise ValueError(f"demon_hunter GPU timeline specs havoc/vengeance/devourer, got {spec}")
    if not builds:
        return []
    _ = (torch, device)
    try:
        return _dh_batch(builds, spec, int(targets))
    except _Overflow:
        return _cpu_fallback(builds, spec, int(targets))


def _cpu_fallback(builds, spec, targets):
    from sunken_sim import demon_hunter as mod

    out = []
    for b in builds:
        report = mod.simulate(b, targets, spec)
        out.append((list(report.events), report.stats))
    return out


def _dh_batch(builds, spec, T):
    from sunken_sim.shadow import _wears

    for b in builds:
        if _wears(b, "I0BR"):
            raise _Overflow("sulfuras")
    return [_fight_one(b, spec, T) for b in builds]


def _fight_one(build, spec, targets):
    """Faithful single-row port of sunken_sim.demon_hunter.simulate → (events, stats)."""
    from sunken_sim import demon_hunter as mod
    from sunken_sim.shadow import (
        CAST_BACKSWING,
        CAST_POINT,
        CHAOS_UNARMORED,
        DUMMY_ARMOR,
        FIGHT,
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
    from sunken_sim.ledger import Ledger

    stats = mod.stats_of(build)
    luck_mult = 1.0 + stats["luck"]
    has = lambda code: mod._has(build, code)
    agi = stats["agi"]
    intel = stats["int"]
    mastery = stats["mastery"]
    haste = stats["haste"]
    havoc = spec == "havoc"
    vengeance = spec == "vengeance"
    devourer = spec == "devourer"
    nova = has(mod.TALENT_CHAOS_NOVA)
    glaive_talent = has(mod.TALENT_THROW_GLAIVE)
    singularity = 40.0 + 2.0 * agi + 0.10 * stats["mana_max"]
    immo_dur = mod.IMMO_DUR + (3.0 if has(mod.TALENT_ENDURING_TORMENT) else 0.0)
    immo_rate = 1.0 + ((0.15 + 0.12 * agi / 100.0) if has(mod.TALENT_FELFIRE) else 0.0)
    immo_interval = (1.40 - 0.10 * mod.RANK) / immo_rate
    void_glaive = has(mod.TALENT_VOID_GLAIVE) or stats["dark_naaru"]
    f_name = {"havoc": "Eye Beam", "vengeance": "Demon Spikes", "devourer": "Collapsing Star"}[spec]

    sources = Ledger(
        {
            "Автоатака": 0.0,
            "Immolation Aura": 0.0,
            "The Hunt": 0.0,
            f_name: 0.0,
            "Chaos Blade": 0.0,
            "Throw Glaive": 0.0,
            "Chaos Nova": 0.0,
            "Singularity": 0.0,
            "Всплеск огня": 0.0,
        }
    )
    mana = stats["mana_max"]
    mana_time = 0.0
    # Sulfuras already overflowed in _dh_batch; keep None path for safety
    sulfuras = Sulfuras() if _wears(build, "I0BR") else None
    # CPU uses pre-summed cast_time (NOT stepwise CAST_POINT+CAST_BACKSWING)
    cast_time = CAST_POINT + CAST_BACKSWING

    meta = False
    fury = 0
    drain_stacks = 0
    thrill_until = -1.0
    main_until = -1.0
    stack_until = -1.0
    immo_next = FIGHT * 10
    blade_until = -1.0
    blade_stacks = 0
    last_chaos = -10.0
    chaos_turn = 0
    fallout_until = [-1.0] * targets
    sing_done = [False] * targets
    fury_dither = mod._Dither()
    power_dither = mod._Dither()
    cleave_dither = mod._Dither()
    glaive_dither = mod._Dither()
    beam_glaive_dither = mod._Dither()
    chaos_dither = mod._Dither()
    fall_dither = [mod._Dither() for _ in range(targets)]
    double_dither = [mod._Dither() for _ in range(targets)]
    pending: list[tuple[float, int, str, float]] = []
    seq = 0

    def push(when: float, kind: str, value: float) -> None:
        nonlocal seq
        seq += 1
        heapq.heappush(pending, (when, seq, kind, value))

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

    def gen(amount: int) -> None:
        nonlocal fury
        if has(mod.TALENT_DEMONIC_POWER) and power_dither.roll(0.25 * luck_mult):
            fury = min(mod.FURY_MAX, fury + amount)
        fury = min(mod.FURY_MAX, fury + amount)

    def potency(now: float) -> float:
        value = stats["potency"]
        if havoc:
            value += 2.0
            if meta:
                value += 4.0 + 0.15 * agi
        return value

    def increase(attack: bool) -> float:
        value = 1.0
        if has(mod.TALENT_COSMIC_FORCE):
            value += 0.003 * fury
        if meta and stats["tormentor"]:
            value += 0.20
        if attack and has(mod.TALENT_CHAINS_OF_ANGUISH):
            value += 0.10
        return value

    def crit_chance() -> float:
        chance = stats["crit"]
        if has(mod.TALENT_FALLOUT) and (not vengeance or meta):
            chance += 8.0
        return chance

    def typed(magical: bool, now: float) -> float:
        bonus = 1.0 + (stats["magic_add"] if magical else stats["phys_add"])
        if stats["sulfuron"]:
            bonus += 0.13 + 0.25 * target_hp(now)
        if magical and stats["spellbinder"]:
            bonus += 0.05 + 0.005 * mastery
        if stats["glass"]:
            bonus *= 1.15
        if magical and devourer and meta:
            bonus *= 1.25 + 0.01 * drain_stacks
        return bonus

    def taken(t: int, now: float) -> float:
        armor = DUMMY_ARMOR - stats["armor_pen"]
        if fallout_until[t] > now:
            armor -= mod.FALLOUT_ARMOR
        return armor_taken(armor) * _execute_factor(stats, now)

    def deal(name: str, raw: float, t: int, now: float, kind: str, chaos: bool = False):
        attack = kind == "attack"
        scale = (stats["attack_potency"] if attack else 1.0) + (0.35 if havoc else 0.0)
        amount = raw + potency(now) * scale
        amount *= increase(attack)
        share = 0.0
        if attack:
            amount *= typed(False, now) * (CHAOS_UNARMORED if chaos else 1.0)
            chance = crit_chance()
            share = max(0.0, min(100.0, chance)) / 100.0
            amount *= _crit_factor(chance, 2.0 + stats["rating"])
        elif kind == "magic":
            amount *= typed(True, now)
            if stats["spell_crit"]:
                chance = crit_chance()
                share = max(0.0, min(100.0, chance)) / 100.0
                amount *= _crit_factor(chance, stats["spell_mult"] + stats["rating"])
        amount *= taken(t, now)
        sources.add_exec(name, amount, now, _execute_factor(stats, now))
        note_damage_mana(1)
        if havoc and fury_dither.roll(0.08 * luck_mult):
            gen(1)
        if share > 0 and has(mod.TALENT_FALLOUT) and fall_dither[t].roll(share):
            fallout_until[t] = now + mod.FALLOUT_DUR
        return amount, share

    def immo_hit(t: int, now: float, name: str = "Immolation Aura") -> None:
        raw = 5.0 + 10.0 * mod.RANK + 0.30 * agi
        deal(name, raw, t, now, "magic")
        if havoc and double_dither[t].roll((5.0 + 0.5 * mastery) / 100.0):
            deal(name, raw, t, now, "magic")
        if has(mod.TALENT_SOUL_IMMOLATION):
            nxt["F"] -= 0.10

    def dcs() -> float:
        return mod.WHITE_BASE + 0.75 * agi + stats["damage"]

    def on_attack(t: int, now: float, share: float, code: bool) -> None:
        nonlocal blade_until, blade_stacks
        immo_hit(t, now)
        if has(mod.TALENT_CHAOS_BLADE):
            if blade_until > now:
                blade_stacks += 1
            else:
                blade_stacks = 1
                blade_until = now + mod.BLADE_DUR
            for _ in range(blade_stacks):
                deal("Chaos Blade", 10.0 + 0.10 * dcs(), t, now, "plain")
        if has(mod.TALENT_SOUL_CLEAVE):
            gen(3 if cleave_dither.roll(share) else 1)
        if not code and glaive_talent and glaive_dither.roll(share * 0.5 * luck_mult):
            glaive(t, now)

    def glaive(t: int, now: float) -> None:
        raw = 15.0 + 0.40 * dcs()
        _d, share = deal("Throw Glaive", raw, t, now, "attack", chaos=True)
        on_attack(t, now, share, True)
        other = (t + 1) % targets
        _d, share = deal("Throw Glaive", 0.5 * raw, other, now, "attack", chaos=True)
        on_attack(other, now, share, True)

    def apply_immolation(now: float) -> None:
        nonlocal main_until, stack_until, immo_next
        if main_until <= now and stack_until <= now:
            immo_next = now + immo_interval
        if main_until > now:
            stack_until = now + immo_dur
        else:
            main_until = now + immo_dur

    def class_cast(now: float, hunt: bool = False) -> None:
        if nova:
            for t in range(targets):
                deal("Chaos Nova", 25.0 + 0.50 * agi, t, now, "magic")
        if devourer and not hunt:
            gen(mod.FRAGMENT_FURY)

    def cast(now: float, extra: float = 0.0) -> float:
        if sulfuras is not None:
            sulfuras.cast()
        return now + cast_time + extra + stats["cast_stun_lock"]

    def speed_stat(now: float) -> float:
        speed = stats["attack_speed"]
        if now < thrill_until:
            speed += mod.THRILL_SPEED
        return min(4.0, max(-0.8, speed))

    def attack_interval(now: float) -> float:
        swing = mod.SWING * (1.20 if stats["galactic"] else 1.0)
        if void_glaive:
            swing *= 0.92
        return swing / (1.0 + speed_stat(now))

    def fury_tick(now: float) -> None:
        nonlocal fury, drain_stacks, meta
        if meta:
            if fury > 0:
                fury -= 5 + drain_stacks
                if fury <= 0:
                    fury = 0
                    drain_stacks = 0
                    meta = False
                else:
                    drain_stacks += 1
                if stats["cosmic_helm"] and devourer:
                    nxt["F"] -= 1.0
        elif fury < 25:
            gen(1)

    def beam_tick(now: float, per_hit: float) -> None:
        nonlocal last_chaos, chaos_turn
        hits = 2 if targets == 1 else targets
        chaos_at = -1
        if now - last_chaos >= mod.CHAOS_ICD - 1e-9:
            p = 1.0 - (1.0 - mod._chance(0.25 * luck_mult)) ** hits
            if chaos_dither.roll(p):
                last_chaos = now
                chaos_at = chaos_turn % hits
                chaos_turn += 1
        for k in range(hits):
            t = 0 if targets == 1 else k
            if k == chaos_at:
                _d, share = deal("Eye Beam", per_hit, t, now, "attack", chaos=True)
                on_attack(t, now, share, True)
                if glaive_talent and beam_glaive_dither.roll(0.20 * luck_mult):
                    glaive(t, now)
            else:
                deal("Eye Beam", per_hit, t, now, "plain")

    def star_land(now: float) -> None:
        raw = (125.0 + 2.0 * agi) * (1.0 + (0.03 / 10.0) * (agi + intel))
        for t in range(targets):
            deal("Collapsing Star", raw, t, now, "magic")
            if has(mod.TALENT_SINGULARITY) and not sing_done[t]:
                sing_done[t] = True
                deal("Singularity", singularity, t, now, "magic")

    nxt = {"Meta": 0.0, "F": 0.0, "Hunt": 0.0, "Immolation": 0.0, "Inner": 0.0}
    if vengeance and not nova:
        nxt["F"] = FIGHT * 10
    if not nova:
        nxt["Inner"] = FIGHT * 10
    order = ("Meta", "F", "Hunt", "Immolation", "Inner")
    next_attack = 0.0
    next_fury = 1.0
    busy = 0.0
    guard = 0
    while True:
        guard += 1
        if guard > MAX_STEPS:
            break
        attack_at = max(next_attack, busy)
        cast_at = FIGHT * 10
        choice = None
        for name in order:
            if name == "Meta" and meta:
                continue
            ready = max(nxt[name], busy)
            if ready < cast_at - 1e-9:
                cast_at, choice = ready, name
        event_at = pending[0][0] if pending else FIGHT * 10
        moment = min(attack_at, cast_at, event_at, next_fury, immo_next)
        if moment >= FIGHT:
            break
        if moment == event_at:
            _when, _s, kind, value = heapq.heappop(pending)
            if kind == "beam":
                beam_tick(moment, value)
            elif kind == "star":
                star_land(moment)
            continue
        if moment == next_fury:
            fury_tick(moment)
            next_fury += 1.0
            continue
        if moment == immo_next:
            count = (main_until > moment) + (stack_until > moment)
            for _ in range(count):
                for t in range(targets):
                    immo_hit(t, moment)
            immo_next = (
                moment + immo_interval
                if (main_until > moment or stack_until > moment)
                else FIGHT * 10
            )
            continue
        if choice is not None and cast_at <= attack_at and moment == cast_at:
            name = choice
            hit_at = moment + CAST_POINT
            if name == "Meta":
                busy = cast(moment)
                meta = True
                class_cast(hit_at)
                nxt[name] = moment + mod._cooldown(mod.META_CD, haste, stats)
            elif name == "F" and havoc:
                if not pay(mod.EYE_BEAM_MANA, moment):
                    nxt[name] = moment + 0.25
                    continue
                busy = cast(moment, mod.EYE_BEAM_DUR)
                class_cast(hit_at)
                per_hit = 7.0 + 0.15 * dcs()
                left, tick, when = mod.EYE_BEAM_DUR, 0.0, hit_at
                while left >= mod.EYE_BEAM_STEP - 1e-9:
                    if tick < mod.EYE_BEAM_STEP:
                        push(when, "beam", per_hit)
                        tick = 0.50 / (1.0 + 0.50 * speed_stat(when))
                    else:
                        tick -= mod.EYE_BEAM_STEP
                    left -= mod.EYE_BEAM_STEP
                    when += mod.EYE_BEAM_STEP
                nxt[name] = moment + mod._cooldown(mod.EYE_BEAM_CD, haste, stats)
            elif name == "F" and devourer:
                if not pay(mod.STAR_MANA, moment):
                    nxt[name] = moment + 0.25
                    continue
                busy = cast(moment)
                if has(mod.TALENT_CONSUME):
                    for _ in range(3):
                        gen(mod.FRAGMENT_FURY)
                class_cast(hit_at)
                push(hit_at + mod.STAR_DELAY, "star", 0.0)
                nxt[name] = moment + mod._cooldown(mod.STAR_CD, haste, stats)
            elif name == "F":
                if not pay(mod.SPIKES_MANA, moment):
                    nxt[name] = moment + 0.25
                    continue
                busy = cast(moment)
                class_cast(hit_at)
                nxt[name] = moment + mod._cooldown(mod.SPIKES_CD, haste, stats)
            elif name == "Hunt":
                if not pay(mod.HUNT_MANA, moment):
                    nxt[name] = moment + 0.25
                    continue
                busy = cast(moment)
                class_cast(hit_at, hunt=True)
                thrill_until = hit_at + mod.THRILL_DUR
                if stats["warglaive"]:
                    apply_immolation(hit_at)
                raw = 100.0 + 1.80 * agi
                if devourer:
                    raw *= 1.08 + 0.005 * mastery
                deal("The Hunt", raw, 0, hit_at, "magic")
                if has(mod.TALENT_SINGULARITY):
                    deal("Singularity", 0.50 * singularity, 0, hit_at, "magic")
                if devourer:
                    gen(mod.FRAGMENT_FURY)
                nxt[name] = moment + mod._cooldown(mod.HUNT_CD, haste, stats)
            elif name == "Immolation":
                if not pay(mod.IMMO_MANA, moment):
                    nxt[name] = moment + 0.25
                    continue
                busy = cast(moment)
                class_cast(hit_at)
                apply_immolation(hit_at)
                nxt[name] = moment + mod._cooldown(mod.IMMO_CD, haste, stats)
            elif name == "Inner":
                if not pay(mod.INNER_MANA, moment):
                    nxt[name] = moment + 0.25
                    continue
                busy = cast(moment)
                class_cast(hit_at)
                nxt[name] = moment + mod._cooldown(mod.INNER_CD, haste, stats)
            next_attack = max(next_attack, busy)
            continue
        moment = attack_at
        recover(moment)
        power = dcs()
        before = sources["Автоатака"]
        _dealt, share = deal("Автоатака", power, 0, moment, "attack", chaos=meta)
        if stats["auto_pct"] != 1.0:
            sources["Автоатака"] = before + (sources["Автоатака"] - before) * stats["auto_pct"]
        on_attack(0, moment, share, False)
        gain_mana(attack_mana_gain(stats))
        if stats["fire_orb"]:
            splash = (20.0 + 0.35 * agi) * targets * taken(1 % targets, moment)
            sources.add_exec("Всплеск огня", splash, moment, _execute_factor(stats, moment))
            note_damage_mana(targets)
        if sulfuras is not None:
            execute = _execute_factor(stats, moment)
            armor = armor_taken(DUMMY_ARMOR - stats["armor_pen"])
            if sulfuras.attack():
                splash = (
                    agi
                    * (1.0 + stats["magic_add"])
                    * (1.15 if stats["glass"] else 1.0)
                    * armor
                    * execute
                    * targets
                )
                sources.add_exec("Sulfuras", splash, moment, execute)
                note_damage_mana(targets)
            echo = power * armor * execute * sulfuras_echo_chance(stats["luck"])
            sources.add_exec("Sulfuras (удар)", echo, moment, execute)
        next_attack = moment + attack_interval(moment)

    return list(sources.events), stats
