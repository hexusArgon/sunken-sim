# -*- coding: utf-8 -*-
"""Batched next-event timeline for Windmaster.

Inlined CPU-exact simulate (no POLICIES). Sulfuras → overflow.
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
from sunken_sim import windmaster as mod

SPECS = mod.SPECS
POLICIES = (None,)
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


def generate_windmaster_timelines(torch, device, builds, spec: str, targets: int):
    if spec not in ('upheaval', 'storm', 'combat'):
        raise ValueError(f"windmaster GPU timeline unexpected spec {spec}")
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
    events, stats, total = _fight_one(build, targets, spec, None)
    return events, stats


def _fight_one(build, targets: int, spec: str, policy=None):
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

    sources: dict[str, float] = Ledger({
        "Автоатака": 0.0,
        "Skyslash": 0.0,
        "Tornado": 0.0,
        "Lightning Rush": 0.0,
        "Windstorm": 0.0,
        "Cyclone": 0.0,
        "Всплеск огня": 0.0,
    })
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
        sources.add_exec(name, dealt, now, _execute_factor(stats, now))
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
            sources.add_exec("Всплеск огня", splash, moment, _execute_factor(stats, moment))
            note_damage_mana(targets)
        if sulfuras is not None:
            execute = _execute_factor(stats, moment)
            taken = taken_for(0, moment)
            if sulfuras.attack():
                splash = agi * (1.0 + stats["magic_add"]) * (1.15 if stats["glass"] else 1.0) * taken * execute * targets
                sources.add_exec("Sulfuras", splash, moment, execute)
                note_damage_mana(targets)
            echo = power * taken * execute * sulfuras_echo_chance(stats["luck"])
            sources.add_exec("Sulfuras (удар)", echo, moment, execute)
        next_attack = moment + SWING / (1.0 + attack_speed(moment))

    total = sum(sources.values())
    recover(FIGHT)
    mana_left = 0.0 if stats["mana_max"] <= 0 else 100.0 * mana / stats["mana_max"]
    stats = dict(stats)
    stats.update({f"n_{k}": float(v) for k, v in counters.items()})
    return list(sources.events), stats, total
