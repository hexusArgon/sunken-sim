# -*- coding: utf-8 -*-
"""Batched next-event timeline for Siren.

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
from sunken_sim import siren as mod

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


def generate_siren_timelines(torch, device, builds, spec: str, targets: int, policies=None):
    """Best-policy rows by default, or one explicit fixed policy per input row."""
    if spec not in mod.SPECS:
        raise ValueError(f"siren GPU timeline unexpected spec {spec}")
    if policies is not None:
        if len(policies) != len(builds) or any(p not in mod.POLICIES for p in policies):
            raise ValueError("one valid Siren policy is required per build")
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
    for policy in mod.POLICIES:
        events, stats, total = _fight_one(build, targets, spec, policy)
        if best is None or total / FIGHT > best[0] / FIGHT + 1e-9:
            best = (total, events, stats)
    return best[1], best[2]


def _fight_one(build: Build, targets: int, spec: str, policy: tuple[bool, bool]) -> Report:
    use_la, use_song = policy
    if spec not in SPECS:
        raise ValueError(spec)
    if targets < 1:
        raise ValueError(targets)
    stats = stats_of(build)
    luck_mult = 1.0 + stats["luck"]
    has = lambda code: _has(build, code)  # noqa: E731
    sharp = spec == "sharpshooter"
    shaper = spec == "watershaper"
    grace = spec == "seagrace"
    intel = int(stats["int"])
    agi = int(stats["agi"])
    mastery = int(stats["mastery"])
    mana_max = stats["mana_max"]
    crit_stat = stats["crit"]
    pen = stats["armor_pen"]
    reflection = 1.25 if (has(TALENT_REFLECTION) or stats["band"]) else 1.0
    mirror_song_as = 0.75 if has(TALENT_REFLECTION) else 0.50  # AS / mana hooks only check I0N1
    fletcher_dur = 6.0 if has(TALENT_STRING) else FLETCHER_DUR
    song_dur = 8.0 if has(TALENT_SOOTHING) else SONG_DUR
    song_as = 0.10 + 0.05 * RANK
    song_mana = (1.0 * RANK + 0.005 * mana_max) * (1.5 if has(TALENT_SOOTHING) else 1.0)
    icy_flat = (0.005 if grace else 0.01) * mana_max if has(TALENT_ICY_QUIVER) else 0.0
    neptulon_crit = (10.0 + 0.20 * intel) if has(TALENT_NEPTULON) else 0.0
    core_gain = 3.0 + (1.0 if has(TALENT_LIQUID_FUEL) else 0.0)
    la_cost = 0.0 if has(TALENT_VIPER) else 1.0 + 1.0 * RANK  # Viper Sting drains the target instead

    sources: dict[str, float] = Ledger({"Автоатака": 0.0})
    actions: list[tuple[float, str]] = []
    counters = {"tidal": 0, "la": 0, "wave": 0, "elementals": 0, "snake": 0}
    mana = mana_max
    mana_time = 0.0
    sulfuras = Sulfuras() if _wears(build, "I0BR") else None
    cast_time = CAST_POINT + CAST_BACKSWING

    chill_until = [-1.0] * targets
    snake_until = [-1.0] * targets
    armed = False  # B05F
    fletcher_until = -1.0  # B058
    song_until = -1.0  # B04R on the Siren
    mirror_song_until = -1.0  # B08S on the Siren
    elementals: list[dict] = []
    mirror: dict | None = None
    pending: list[tuple[float, int, str, float]] = []
    seq = 0
    la_count = 0
    wave_roll = _Dither()
    bow_roll = _Dither()
    snake_roll = _Dither()
    tick_next = 1.0  # ASSUMPTION: 1 s periodic (Siren_Periodic / Mana_Regen) ticks at whole seconds

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
        if refund and cost > 0:
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
        return WHITE_BASE + 0.75 * agi + stats["damage"]

    def taken(hero: bool, t: int, now: float) -> float:
        armor = DUMMY_ARMOR
        if snake_until[t] > now:
            armor -= 2.0  # A0GU faerie fire from Snake Bite
        if hero:
            armor -= pen
        return armor_taken(armor)

    def icy(t: int, now: float) -> float:
        return icy_flat if chill_until[t] > now else 0.0

    def hero_hit(name: str, raw: float, now: float, tgts: list[int], *, magical: bool, attack: bool,
                 weight: float = 1.0, potency_scale: float = 1.0, source_scale: float = 1.0) -> float:
        if weight <= 0 or not tgts:
            return 0.0
        chance = crit_stat
        rating = stats["rating"]
        if attack and has(TALENT_CORAL) and fletcher_until > now:
            chance += 10.0
            rating += 0.18
        execute = _execute_factor(stats, now)
        factor = typed(magical, now)
        if attack:
            factor *= _crit_factor(chance, 2.0 + rating)
        elif stats["spell_crit"]:
            factor *= _crit_factor(chance, stats["spell_mult"] + rating)
        raw_weight, pot_coeff = 0.0, 0.0
        for t in tgts:
            scale = factor * taken(True, t, now)
            raw_weight += (raw + icy(t, now)) * scale
            pot_coeff += potency_scale * scale
        total = (raw_weight + stats["potency"] * pot_coeff) * execute
        # auto_pct changes only this named source, never LA/procs/mana counts.
        scale = weight * source_scale
        sources.add_exec(name, total * scale, now, execute,
                         raw_weight=raw_weight * scale, pot_coeff=pot_coeff * scale)
        note_damage_mana(len(tgts) * weight)
        return total

    def summon_hit(name: str, raw: float, now: float, t: int, *, attack: bool, extra_crit: float = 0.0,
                   increase: float = 0.0, weight: float = 1.0) -> float:
        """Owner hit; Icy Quiver is raw, elemental mana and crit multiply both channels."""
        factor = (1.0 + stats["pet_damage"]) * (1.0 + increase)
        if attack:
            factor *= _crit_factor(stats["summon_crit"] + extra_crit, 2.0 + stats["summon_rating"])
        factor *= taken(False, t, now) * weight
        raw_weight, pot_coeff = (raw + icy(t, now)) * factor, factor
        execute = _execute_factor(stats, now)
        dealt = (raw_weight + stats["potency"] * pot_coeff) * execute
        sources.add_exec(name, dealt, now, execute, raw_weight=raw_weight, pot_coeff=pot_coeff)
        return dealt

    def liquid_arrows(now: float, t: int, from_elemental: bool) -> None:
        nonlocal mana
        cost = la_cost * (0.40 if from_elemental else 1.0)
        if cost > 0:
            recover(now)
            if mana < cost:
                return
            mana -= cost
        if has(TALENT_ICY_QUIVER) and fletcher_until > now:
            chill_until[t] = max(chill_until[t], now + CHILL_DUR)  # Chill -> frostnova A00H (Bfro)
        counters["la"] += 1
        if grace:
            return  # Seagrace: Liquid Arrows heal instead of dealing damage
        raw = (10.0 + 10.0 * RANK) + 0.40 * agi + 0.40 * intel
        if fletcher_until > now:
            raw *= 1.0 + ((0.40 if has(TALENT_SEAFLURRY) else 0.10) + 0.05 * RANK)
        if from_elemental:
            raw *= 0.40
        hero_hit("Liquid Arrows", raw, now, [t], magical=True, attack=False)

    def siren_attack(now: float, raw: float, name: str, potency_scale: float = 1.0, source_scale: float = 1.0) -> None:
        """A Siren attack (her own swing or the Mirror Image pierce hit): PreDamage_Heroes procs."""
        nonlocal armed
        t = 0
        if use_la:
            liquid_arrows(now, t, False)
        hero_hit(name, raw, now, [t], magical=False, attack=True, potency_scale=potency_scale,
                 source_scale=source_scale)
        if armed:
            armed = False
            push(now + TIDAL_DELAY, "tidal", 0.0)
            if sharp and mirror is not None and mirror["end"] > now:
                push(now + TIDAL_DELAY, "tidal", 1.0)  # image copy x0.30 x Reflection_Bonus
        elif stats["bow"] and bow_roll.roll(_chance(0.10 * luck_mult)):
            push(now + TIDAL_DELAY, "tidal", 0.0)
        if has(TALENT_SNAKE_BITE) and snake_roll.roll(_chance(0.25 * luck_mult)):
            counters["snake"] += 1
            snake_until[t] = now + 4.0
            # Dummy n03G deals it: Pet Damage applies, no crit / procs.
            summon_hit("Snake Bite", 30.0 + 0.50 * agi + 1.50 * dcs(), now, t, attack=False)

    def spawn_elemental(now: float, life: float, waterlord: bool) -> None:
        counters["elementals"] += 1
        raw = 11.0 + 1.0 + int(0.15 * dcs())  # ua1b 11 + 1d1 + R2I(0.15 DCS)
        cap = ELEMENTAL_MANA_MAX + (5.0 + mastery if shaper else 0.0) + (25.0 if stats["vest"] else 0.0)
        start = ELEMENTAL_START_MANA + (15.0 if stats["vest"] else 0.0)
        elementals.append({
            "next": now, "end": now + life, "raw": raw, "mana": min(cap, start), "cap": cap,
            "swing": 1.0 if waterlord else ELEMENTAL_SWING, "hits": 3 if waterlord else 2,
            "song": -1.0, "msong": -1.0,
        })

    def tidal_shot(now: float, copy: bool) -> None:
        nonlocal fletcher_until
        counters["tidal"] += 1
        recover(now)
        raw = 80.0 * RANK + 2.0 * agi
        if has(TALENT_EMPOWERED):
            raw += 0.40 * mana
        if sharp:
            raw *= 1.0 + (0.10 + 0.01 * mastery)
        if copy:
            raw *= 0.30 * reflection
        live = [e for e in elementals if e["end"] > now]
        if has(TALENT_CONJURE) and len(live) < 3:
            spawn_elemental(now, (ELEMENTAL_LIFE + (4.0 if has(TALENT_LIQUID_FUEL) else 0.0)) / 2.0, False)
            live = [e for e in elementals if e["end"] > now]
        if has(TALENT_ELEMENTAL_SHOT) and live:
            # Kills a random elemental. ASSUMPTION: the one with the least time left.
            victim = min(live, key=lambda e: e["end"])
            victim["end"] = now
            raw *= 1.35
        hero_hit("Tidal Shot", raw, now, [0], magical=True, attack=False)
        fletcher_until = now + fletcher_dur
        if sharp and wave_roll.roll(_chance(0.25 * luck_mult)):
            counters["wave"] += 1
            # ASSUMPTION: the clustered pack is on the wave's line, every target is hit.
            hero_hit("Crushing Wave", 0.40 * raw, now, list(range(targets)), magical=True, attack=False)

    def elemental_hit(now: float, e: dict) -> None:
        nonlocal la_count
        crit_chance = stats["summon_crit"] + neptulon_crit
        share = max(0.0, min(100.0, crit_chance)) / 100.0
        n = min(e["hits"], targets)
        for k in range(n):
            # Water Core: +0.5% damage per current mana (before the +3 mana of this hit).
            summon_hit("Sea Elemental", e["raw"] * BOUNCE_KEEP ** k, now, k, attack=True,
                       extra_crit=neptulon_crit, increase=0.005 * e["mana"])
            gain = core_gain * (1.0 + share if has(TALENT_NEPTULON) else 1.0)
            e["mana"] = min(e["cap"], e["mana"] + gain)
            # ASSUMPTION: bounce hits count as elemental attacks (Water Core and the LA counter).
            if use_la:
                la_count += 1
                if la_count >= 3:
                    la_count = 0
                    liquid_arrows(now, k, True)

    def attack_interval(now: float) -> float:
        swing = SWING * (1.20 if stats["galactic"] else 1.0)
        if has(TALENT_STRING) and fletcher_until > now:
            swing *= 0.88  # AS_Base_Reduction
        speed = stats["attack_speed"]
        if song_until > now:
            speed += song_as
        if mirror_song_until > now:
            speed += mirror_song_as * song_as
        speed = min(4.0, max(-0.8, speed))
        return swing / (1.0 + speed)

    fixed_cd = {"mirror": MIRROR_CD, "elemental": ELEMENTAL_CD, "tidal": TIDAL_CD, "song": SONG_CD,
                "gaze": GAZE_CD}
    cost = {"mirror": MIRROR_MANA, "elemental": ELEMENTAL_MANA, "tidal": TIDAL_MANA, "song": SONG_MANA,
            "gaze": GAZE_MANA}
    names = {"mirror": "Mirror Image", "elemental": "Sea Elemental", "tidal": "Tidal Shot",
             "song": "Song of the Siren", "gaze": "Stone Gaze"}
    order = ["mirror", "elemental", "tidal"] + (["song"] if use_song else []) + ["gaze"]
    nxt = {key: 0.0 for key in order}

    next_attack = 0.0
    busy = 0.0
    loops = 0
    clock = 0.0
    while True:
        loops += 1
        if loops > MAX_STEPS:
            raise _Overflow("steps")
        attack_at = max(next_attack, busy, clock)
        cast_at = FIGHT * 10
        choice = None
        for key in order:
            if key == "tidal" and armed:
                continue
            ready = max(nxt[key], busy, clock)
            if ready < cast_at - 1e-9:
                cast_at, choice = ready, key
        pending_at = min((p[0] for p in pending), default=FIGHT * 10)
        elementals[:] = [e for e in elementals if e["end"] > clock - 1e-9]
        unit_at = min((e["next"] for e in elementals if e["next"] < e["end"]), default=FIGHT * 10)
        mirror_at = mirror["next"] if mirror is not None and mirror["next"] < mirror["end"] else FIGHT * 10
        moment = min(attack_at, cast_at, pending_at, unit_at, mirror_at, tick_next)
        if moment >= FIGHT:
            break
        clock = moment

        if moment == pending_at:
            event = min(pending)
            pending.remove(event)
            _, _, kind, arg = event
            if kind == "tidal":
                tidal_shot(moment, arg > 0)
            continue

        if moment == tick_next:
            # Song mana: Siren via Mana_Regen, elementals via Siren_Periodic (1 s).
            if song_until > moment:
                gain_mana(song_mana)
            if mirror_song_until > moment:
                gain_mana(mirror_song_as * song_mana)
            for e in elementals:
                add = (song_mana if e["song"] > moment else 0.0)
                add += (0.50 * reflection * song_mana if e["msong"] > moment else 0.0)
                e["mana"] = min(e["cap"], e["mana"] + add)
            tick_next = moment + 1.0
            continue

        if moment == unit_at and unit_at < attack_at and unit_at < cast_at:
            e = min((u for u in elementals if u["next"] < u["end"]), key=lambda u: u["next"])
            elemental_hit(moment, e)
            e["next"] = moment + e["swing"]
            continue

        if moment == mirror_at and mirror_at < attack_at and mirror_at < cast_at:
            raw = int(0.5 * dcs()) + 1.0  # e00M base R2I(0.5 DCS) + 1d1 (ASSUMPTION: dice 1d1)
            summon_hit("Mirror Image", raw, moment, 0, attack=True)
            siren_attack(moment, 0.5 * dcs(), "Mirror Image (Siren)")
            mirror["next"] = moment + MIRROR_SWING
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
            flat = 0.0
            image = mirror is not None and mirror["end"] > hit_at
            if key == "mirror":
                life = MIRROR_LIFE + (3.0 if has(TALENT_REFLECTION) else 0.0)
                mirror = {"next": hit_at, "end": hit_at + life}
            elif key == "elemental":
                life = ELEMENTAL_LIFE + (4.0 if has(TALENT_LIQUID_FUEL) else 0.0)
                for i in range(2 if shaper else 1):
                    spawn_elemental(hit_at, life, has(TALENT_WATERLORD) and i == 0)
                if shaper and image:
                    for _ in range(2):
                        spawn_elemental(hit_at, life * 0.40 * reflection, False)
            elif key == "tidal":
                armed = True
            elif key == "song":
                song_until = hit_at + song_dur
                for e in elementals:
                    if e["end"] > hit_at:
                        e["song"] = hit_at + song_dur  # ASSUMPTION: elementals stand within 600
                if grace and image:
                    mirror_song_until = hit_at + song_dur
                    for e in elementals:
                        if e["end"] > hit_at:
                            e["msong"] = hit_at + song_dur
            elif key == "gaze":
                if has(TALENT_GORGON):
                    flat = 3.0
                raw = 90.0 + 1.45 * agi + 2.40 * intel
                # ASSUMPTION: the pack stands in the 600-range cone, every target is hit.
                hero_hit("Stone Gaze", raw, hit_at, list(range(targets)), magical=True, attack=False)
            cd = _cooldown(fixed_cd[key], stats["haste"], stats, flat)
            nxt[key] = moment + cd
            next_attack = max(next_attack, busy)
            continue

        # Siren auto-attack (pierce, physical).
        moment = attack_at
        recover(moment)
        power = dcs()
        siren_attack(moment, power, "Автоатака", stats["attack_potency"], stats["auto_pct"])
        gain_mana(attack_mana_gain(stats))
        if stats["fire_orb"]:
            splash = (20.0 + 0.35 * agi) * targets * taken(True, 0, moment) * _execute_factor(stats, moment)
            sources.add_exec("Всплеск огня", splash, moment, _execute_factor(stats, moment))
            note_damage_mana(targets)
        if sulfuras is not None:
            execute = _execute_factor(stats, moment)
            if sulfuras.attack():
                splash = agi * typed(True, moment) * taken(True, 0, moment) * execute * targets
                splash *= _crit_factor(crit_stat, 2.0 + stats["rating"])
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
    stats["policy_la"] = 1.0 if use_la else 0.0
    stats["policy_song"] = 1.0 if use_song else 0.0
    return list(sources.events), stats, total
