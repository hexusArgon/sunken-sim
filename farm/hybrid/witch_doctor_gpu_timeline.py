# -*- coding: utf-8 -*-
"""Batched next-event timeline for Witch Doctor.

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
from sunken_sim import witch_doctor as mod

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


def generate_witch_doctor_timelines(torch, device, builds, spec: str, targets: int):
    if spec not in ('voodoo', 'poison'):
        raise ValueError(f"witch_doctor GPU timeline unexpected spec {spec}")
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


def _fight_one(build: Build, targets: int, spec: str, policy: tuple[bool, str]) -> Report:
    use_soul, first = policy
    if spec not in SPECS:
        raise ValueError(spec)
    if targets < 1:
        raise ValueError(targets)
    stats = stats_of(build)
    luck_mult = 1.0 + stats["luck"]
    has = lambda code: _has(build, code)  # noqa: E731
    poison = spec == "poison"
    intel = int(stats["int"])
    agi = int(stats["agi"])
    base_mastery = int(stats["mastery"])
    mana_max = stats["mana_max"]
    crit_stat = stats["crit"]
    pen = stats["armor_pen"]
    mutated = has(TALENT_MUTATED_TOADS)
    toad_mult = 1.15 if mutated else 1.0

    sources: dict[str, float] = Ledger({"Автоатака": 0.0})
    actions: list[tuple[float, str]] = []
    mana = mana_max
    mana_time = 0.0
    sulfuras = Sulfuras() if _wears(build, "I0BR") else None
    cast_time = CAST_POINT + CAST_BACKSWING

    venom_until = [-1.0] * targets
    soul_until = [-1.0] * targets
    spiders: list[dict] = []
    cobras: list[dict] = []
    wards: list[float] = []  # end times
    pending: list[tuple[float, int, str, float]] = []
    seq = 0
    ward_roll = _Dither()
    spider_roll = _Dither()
    addling_roll = _Dither()
    dart_roll = _Dither()
    widow_roll = _Dither()
    # PlagueToad_BaseDmg before the first Plague Toad cast (map init value).
    toad_base = 50.0 + 2.0 * intel
    dart_next = 0.0 if has(TALENT_POISON_DART) else FIGHT * 10  # ASSUMPTION: first dart at t = 0
    noxious_next = 1.0  # ASSUMPTION: periodic 1 s timer ticks at whole seconds

    def push(when: float, kind: str, arg: float = 0.0) -> None:
        nonlocal seq
        seq += 1
        pending.append((when, seq, kind, arg))

    def recover(now: float) -> None:
        nonlocal mana, mana_time
        if now > mana_time and mana < mana_max:
            mana = min(mana_max, mana + stats["mana_regen"] * (now - mana_time))
        mana_time = now

    def gain_mana(amount: float) -> None:
        nonlocal mana
        mana = min(mana_max, mana + amount)

    def pay(cost: float, now: float, refund: bool = True) -> bool:
        nonlocal mana
        recover(now)
        if mana < cost:
            return False
        mana -= cost
        if refund:
            gain_mana(cast_mana_back(cost, stats))
        return True

    def note_damage_mana(count: float) -> None:
        if stats["damage_mana_pct"]:
            gain_mana(stats["damage_mana_pct"] * mana_max * count)

    def mastery_now(now: float) -> float:
        value = float(base_mastery)
        if has(TALENT_SPIRITS_UNBOUND):
            recover(now)
            if mana_max > 0 and mana >= 0.75 * mana_max:
                value += 15.0  # Mastery_Tooltip: I00A at >= 75% mana
        return value

    def typed(magical: bool, now: float) -> float:
        bonus = 1.0 + (stats["magic_add"] if magical else stats["phys_add"])
        if stats["sulfuron"]:
            bonus += 0.13 + 0.25 * target_hp(now)
        if magical and stats["spellbinder"]:
            bonus += 0.05 + 0.005 * mastery_now(now)
        if stats["glass"]:
            bonus *= 1.15
        return bonus

    def dcs() -> float:
        return WHITE_BASE + 0.75 * intel + stats["damage"]

    def increase(t: int, now: float) -> float:
        """PreDamage_Increase: Hex (I0M8) and Grasp of the Shadowlands (B028 aura, I0RN)."""
        value = 0.0
        grasp = has(TALENT_GRASP)
        souled = soul_until[t] > now
        if has(TALENT_HEX):
            # ASSUMPTION: the dummy carries no buffs of its own; count B082, B084, B028.
            buffs = (venom_until[t] > now) + souled + (1 if grasp else 0)
            value += 0.04 + 0.02 * buffs
        if grasp:
            value += 0.12 if souled else 0.07
        return value

    def taken(hero: bool) -> float:
        armor = DUMMY_ARMOR
        if hero:
            armor -= pen
        return armor_taken(armor)

    def live(group: list[dict], now: float) -> list[dict]:
        return [d for d in group if d["end"] > now]

    def wards_alive(now: float) -> int:
        return sum(1 for end in wards if end > now)

    # ---- procs on owner damage (PreDamage_Heroes) ----
    def on_owner_damage(now: float, t: int, *, hero: bool, kind: str, weight: float = 1.0) -> None:
        """kind: 'spider' / 'soul' (n022, A0QO), 'unit' (other owner units, max life >= 5), 'hero'."""
        if weight <= 0:
            return
        if has(TALENT_ADDLING_TOAD) and not hero:
            chance = (0.05 if kind == "spider" else 0.025) * luck_mult * weight
            if addling_roll.roll(chance):
                push(now + TOAD_DELAY, "addling")
        if has(TALENT_POISON_DART) and dart_roll.roll(_chance(0.10 * luck_mult) * weight):
            nonlocal dart_next
            if dart_next - now >= 0.5:
                dart_next -= 0.5
            elif dart_next > now:
                dart_next = now + 0.01
        n_wards = wards_alive(now)
        for _w in range(n_wards):
            chance = WARD_PROC
            if len(live(cobras, now)) <= 4:
                chance *= 1.5
            if has(TALENT_VENOM_RUSH) and not hero:
                chance *= 1.3
            if ward_roll.roll(_chance(chance / 100.0 * luck_mult) * weight):
                raw = 50.0 + 0.10 * mana_max + intel
                # DAMAGE_TYPE_DISEASE from the hero: no procs. ASSUMPTION: scored as physical adds.
                hero_hit("Poison Ward", raw, now, [t], magical=False, attack=False, procs=False)
                cap = 8 if has(TALENT_TIKI_ARMY) else 6
                if poison and spider_roll.roll(_chance((5.0 + 0.40 * mastery_now(now)) / 100.0)):
                    spawn_spider(now)
                elif len(live(cobras, now)) < cap:
                    spawn_cobra(now)

    def hero_hit(name: str, raw: float, now: float, tgts: list[int], *, magical: bool, attack: bool,
                 weight: float = 1.0, potency_scale: float = 1.0, chaos: bool = False,
                 procs: bool = True) -> tuple[float, float]:
        if weight <= 0 or not tgts:
            return 0.0, 0.0
        chance = crit_stat
        share = max(0.0, min(100.0, chance)) / 100.0
        first_dealt = 0.0
        total = 0.0
        execute = _execute_factor(stats, now)
        kind = typed(magical, now)
        for i, t in enumerate(tgts):
            amount = raw + stats["potency"] * potency_scale
            amount *= kind
            amount *= 1.0 + increase(t, now)
            if chaos:
                amount *= CHAOS_UNARMORED
            if attack:
                amount *= _crit_factor(chance, 2.0 + stats["rating"])
            elif stats["spell_crit"]:
                amount *= _crit_factor(chance, stats["spell_mult"] + stats["rating"])
            dealt = amount * taken(True) * execute
            if i == 0:
                first_dealt = dealt
            total += dealt
        sources.add_exec(name, total * weight, now, execute)
        note_damage_mana(len(tgts) * weight)
        if procs:
            for t in tgts:
                on_owner_damage(now, t, hero=True, kind="hero", weight=weight)
        return first_dealt, (share if (attack or stats["spell_crit"]) else 0.0)

    def summon_hit(name: str, raw: float, now: float, tgts: list[int], *, attack: bool, kind: str,
                   weight: float = 1.0, chaos: bool = False, procs: bool = True) -> float:
        """Damage by an owner unit: potency, Pet Damage, Hex / Grasp, summon crit, armor."""
        if weight <= 0 or not tgts:
            return 0.0
        chance = stats["summon_crit"]
        total = 0.0
        execute = _execute_factor(stats, now)
        for t in tgts:
            amount = raw + stats["potency"]
            amount *= 1.0 + stats["pet_damage"]
            amount *= 1.0 + increase(t, now)
            if chaos:
                amount *= CHAOS_UNARMORED
            if attack:
                amount *= _crit_factor(chance, 2.0 + stats["summon_rating"])
            total += amount * taken(False) * execute
        sources.add_exec(name, total * weight, now, execute)
        if procs:
            for t in tgts:
                on_owner_damage(now, t, hero=False, kind=kind, weight=weight)
        return total

    def spawn_spider(now: float) -> None:
        raw = 3.0 + int(4.0 * RANK + 0.20 * dcs()) + 1.0  # n022 ua1b 3 + R2I(4 x lvl + 0.2 DCS) + 1d1
        spiders.append({"next": now, "end": now + SPIDER_LIFE, "raw": raw, "mana": SPIDER_MANA_MAX,
                        "venom": now})
        push(now + SPIDER_LIFE, "death", 0.06)

    def spawn_cobra(now: float) -> None:
        tiki = has(TALENT_TIKI_ARMY)
        raw = 4.0 + int((0.18 if tiki else 0.10) * dcs()) + 1.0  # ua1b 4 + R2I(x DCS) + 1d1
        cobras.append({"next": now, "end": now + COBRA_LIFE, "raw": raw, "chaos": tiki})
        push(now + COBRA_LIFE, "death", 0.03)

    def grave_injustice(now: float, pct: float) -> None:
        if not has(TALENT_GRAVE_INJUSTICE):
            return
        for key in order:
            if nxt[key] > now:
                nxt[key] = now + (nxt[key] - now) * (1.0 - pct)

    def venom_target(now: float) -> int:
        # "Will prefer to target unaffected enemies". ASSUMPTION: lowest index first.
        fresh = [t for t in range(targets) if venom_until[t] <= now]
        if fresh:
            return fresh[0]
        return min(range(targets), key=lambda t: venom_until[t])

    def noxious(now: float, t: int, name: str, weight: float = 1.0) -> None:
        raw = 5.0 * RANK + agi
        # Source: random unit of VileSpider_Group (live spiders + dummy n01F).
        n = len(live(spiders, now))
        share = n / (n + 1.0)
        summon_hit(name, raw, now, [t], attack=False, kind="spider", weight=weight * share)
        summon_hit(name, raw, now, [t], attack=False, kind="unit", weight=weight * (1.0 - share))

    def interval(now: float) -> float:
        swing = SWING * (1.20 if stats["galactic"] else 1.0)
        speed = min(4.0, max(-0.8, stats["attack_speed"]))
        return swing / (1.0 + speed)

    fixed_cd = {"toad": TOAD_CD, "spider": SPIDER_CD, "ward": WARD_CD, "soul": SOUL_CD}
    cost = {"toad": TOAD_MANA, "spider": SPIDER_MANA, "ward": WARD_MANA, "soul": SOUL_MANA}
    names = {"toad": "Plague Toad", "spider": "Vile Spider", "ward": "Poison Ward",
             "soul": "Soul Possession"}
    order = (["ward"] if poison else []) + (["spider", "toad"] if first == "spider" else ["toad", "spider"])
    if use_soul:
        order.append("soul")
    nxt = {key: 0.0 for key in order}

    next_attack = 0.0
    busy = 0.0
    loops = 0
    clock = 0.0
    while True:
        loops += 1
        if loops > 400000:
            break
        attack_at = max(next_attack, busy, clock)
        cast_at = FIGHT * 10
        choice = None
        for key in order:
            ready = max(nxt[key], busy, clock)
            if ready < cast_at - 1e-9:
                cast_at, choice = ready, key
        pending_at = min((p[0] for p in pending), default=FIGHT * 10)
        spiders[:] = [d for d in spiders if d["end"] > clock - 1e-9]
        cobras[:] = [d for d in cobras if d["end"] > clock - 1e-9]
        units = spiders + cobras
        unit_at = min((d["next"] for d in units if d["next"] < d["end"]), default=FIGHT * 10)
        venom_at = min((d["venom"] for d in spiders if d["venom"] < d["end"] and d["mana"] >= VENOM_MANA),
                       default=FIGHT * 10)
        timers = min(noxious_next, dart_next)
        moment = min(attack_at, cast_at, pending_at, unit_at, venom_at, timers)
        if moment >= FIGHT:
            break
        clock = moment

        if moment == pending_at:
            event = min(pending)
            pending.remove(event)
            _, _, kind, arg = event
            if kind == "toad":
                # N toads (N = enemies in 600), each BaseDmg / N to everything in its AoE.
                # ASSUMPTION: the pack is clustered, every target is inside every toad's AoE.
                per = toad_base * toad_mult / targets
                hero_hit("Plague Toad", per, moment, list(range(targets)), magical=True, attack=False,
                         weight=float(targets))
            elif kind == "addling":
                # The toad unit (max life 1) deals the damage: no procs, Pet Damage applies.
                summon_hit("Addling Toad", toad_base * toad_mult, moment, list(range(targets)),
                           attack=False, kind="toad", procs=False)
            elif kind == "death":
                grave_injustice(moment, arg)
            continue

        if moment == noxious_next:
            for t in range(targets):
                if venom_until[t] <= moment:
                    continue
                noxious(moment, t, "Noxious Venom")
                if has(TALENT_WIDOW_VENOM) and widow_roll.roll(_chance(0.25 * luck_mult)):
                    noxious(moment, t, "Noxious Venom")
            noxious_next = moment + 1.0
            continue

        if moment == dart_next:
            fresh = [t for t in range(targets) if venom_until[t] <= moment]
            t = fresh[0] if fresh else 0
            raw = 1.0 * dcs() + 0.75 * agi
            # ATTACK_TYPE_CHAOS, DAMAGE_TYPE_DISEASE: attack crit, no procs.
            hero_hit("Poison Dart", raw, moment, [t], magical=False, attack=True, chaos=True, procs=False)
            venom_until[t] = max(venom_until[t], moment + VENOM_DUR)
            dart_next = moment + DART_PERIOD
            continue

        if moment == venom_at and venom_at < attack_at and venom_at < cast_at:
            d = min((u for u in spiders if u["venom"] < u["end"] and u["mana"] >= VENOM_MANA),
                    key=lambda u: u["venom"])
            d["mana"] -= VENOM_MANA
            t = venom_target(moment)
            venom_until[t] = moment + VENOM_DUR
            d["venom"] = moment + VENOM_CD
            d["next"] = max(d["next"], moment + CAST_POINT)
            continue

        if moment == unit_at and unit_at < attack_at and unit_at < cast_at:
            d = min((u for u in units if u["next"] < u["end"]), key=lambda u: u["next"])
            if d in spiders:
                summon_hit("Vile Spider", d["raw"], moment, [0], attack=True, kind="spider")
                if has(TALENT_TOXIC_BITE):
                    d["mana"] = min(SPIDER_MANA_MAX, d["mana"] + 3.0)
                    if venom_until[0] > moment:
                        noxious(moment, 0, "Toxic Bite")
                d["next"] = moment + SPIDER_SWING
            else:
                label = "Tiki" if d["chaos"] else "Cobra"
                summon_hit(label, d["raw"], moment, [0], attack=True, kind="unit", chaos=d["chaos"])
                d["next"] = moment + COBRA_SWING
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
            haste = stats["haste"]
            flat = 0.0
            if key == "toad":
                toad_base = 20.0 + 60.0 * RANK + 1.65 * intel
                push(hit_at + TOAD_DELAY, "toad")
            elif key == "spider":
                count = 2 + (1 if stats["spider_fang"] else 0)
                for _ in range(count):
                    spawn_spider(hit_at)
            elif key == "ward":
                wards.append(hit_at + WARD_LIFE)
                push(hit_at + WARD_LIFE, "death", 0.03)  # ASSUMPTION: o01S is not mechanical
            elif key == "soul":
                flat = stats["soul_cd_flat"]
                dur = SOUL_DUR + (4.0 if has(TALENT_SOUL_BIND) else 0.0)
                soul_until[0] = hit_at + dur
                push(hit_at + dur, "death", 0.06)  # the soul (A0QO) expires
            cd = _cooldown(fixed_cd[key], haste, stats, flat)
            nxt[key] = moment + cd
            next_attack = max(next_attack, busy)
            continue

        # Witch Doctor auto-attack (magic attack type).
        moment = attack_at
        recover(moment)
        white = WHITE_BASE + 0.75 * intel
        power = white + stats["damage"]
        before = sources["Автоатака"]
        hero_hit("Автоатака", power, moment, [0], magical=True, attack=True,
                 potency_scale=stats["attack_potency"])
        if stats["auto_pct"] != 1.0:
            sources["Автоатака"] = before + (sources["Автоатака"] - before) * stats["auto_pct"]
        gain_mana(attack_mana_gain(stats))
        if stats["fire_orb"]:
            splash = (20.0 + 0.35 * stats["int"]) * targets * taken(True) * _execute_factor(stats, moment)
            sources.add_exec("Всплеск огня", splash, moment, _execute_factor(stats, moment))
            note_damage_mana(targets)
        if sulfuras is not None:
            execute = _execute_factor(stats, moment)
            if sulfuras.attack():
                splash = stats["int"] * typed(True, moment) * taken(True) * execute * targets
                splash *= _crit_factor(crit_stat, 2.0 + stats["rating"])
                sources.add_exec("Sulfuras", splash, moment, execute)
                note_damage_mana(targets)
            echo = power * taken(True) * execute * sulfuras_echo_chance(stats["luck"])
            sources.add_exec("Sulfuras (удар)", echo, moment, execute)
        next_attack = moment + interval(moment)

    total = sum(sources.values())
    recover(FIGHT)
    mana_left = 0.0 if mana_max <= 0 else 100.0 * mana / mana_max
    return list(sources.events), stats, total
