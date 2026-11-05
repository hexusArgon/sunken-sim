# -*- coding: utf-8 -*-
"""Batched next-event timeline for Monk (windwalker / brewmaster / mistweaver).

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
from sunken_sim import monk as mod

SPECS = mod.SPECS
POLICIES = mod.POLICIES
stats_of = mod.stats_of
_has = mod._has
_cooldown = mod._cooldown
_chance = mod._chance
RANK = mod.RANK

_g = globals()
for _n in dir(mod):
    if _n[:1] == "_":
        continue
    if _n.isupper() or _n.startswith("TALENT_") or _n.startswith("GLYPH_"):
        _g[_n] = getattr(mod, _n)
for _n in (
    "WHITE_BASE", "SWING", "XUEN", "NIUZAO", "YULON", "TIGER", "OX", "SERPENT",
    "STANCE_DAMAGE", "STANCE_TANK", "STANCE_HEAL",
):
    if hasattr(mod, _n):
        _g[_n] = getattr(mod, _n)


class _Overflow(Exception):
    pass


def generate_monk_timelines(torch, device, builds, spec: str, targets: int):
    if spec not in ("windwalker", "brewmaster", "mistweaver"):
        raise ValueError(f"monk GPU timeline specs windwalker/brewmaster/mistweaver, got {spec}")
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



def _fight_one(build, targets: int, spec: str, policy):
    hold, plain_mist, brew_first = policy
    if spec not in SPECS:
        raise ValueError(spec)
    if targets < 1:
        raise ValueError(targets)
    stats = stats_of(build)
    luck_mult = 1.0 + stats["luck"]
    has = lambda code: _has(build, code)  # noqa: E731
    ww = spec == "windwalker"
    strength = int(stats["str"])
    agility = int(stats["agi"])
    mastery = int(stats["mastery"])
    taken = armor_taken(DUMMY_ARMOR - stats["armor_pen"])

    sources: dict[str, float] = Ledger({
        "Автоатака": 0.0,
        "Fortifying Brew (удар)": 0.0,
        "Power Strike": 0.0,
        "Power Strike (WW-повтор)": 0.0,
        "Celestial Attack (Xuen)": 0.0,
        "White Tiger": 0.0,
        "Wrath of Xuen": 0.0,
        "Всплеск огня": 0.0,
    })
    actions: list[tuple[float, str]] = []
    mana = stats["mana_max"]
    mana_time = 0.0
    sulfuras = Sulfuras() if _wears(build, "I0BR") else None
    cast_time = CAST_POINT + CAST_BACKSWING

    stance = ""
    emp = 0
    jab = 0
    ps_buff_until = -1.0
    fb_attack = False
    avatar = ""  # Avatar_Current
    ps_avatar = ""  # PowerStrike_Avatar
    wrath_until = -1.0
    fof = 0.0
    blessing_xuen_until = -1.0
    blessing_yulon_until = -1.0
    pending: list[tuple[float, float]] = []  # Windwalker Power Strike echoes (time, chance)

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

    def haste_at(now: float) -> float:
        return stats["haste"] + (BLESSING_YULON_CDR if now < blessing_yulon_until else 0.0)

    def typed(magical: bool, now: float) -> float:
        bonus = 1.0 + (stats["magic_add"] if magical else stats["phys_add"])
        if stats["sulfuron"]:
            bonus += 0.13 + 0.25 * target_hp(now)
        if magical and stats["spellbinder"]:
            bonus += 0.05 + 0.005 * stats["mastery"]
        if stats["glass"]:
            bonus *= 1.15
        return bonus * (1.0 + stats["increase"])

    def cut_wrath(crits: float, now: float) -> None:
        if stats["warstaff"] and crits > 0 and nxt["cw"] > now:
            nxt["cw"] = max(now, nxt["cw"] - CHIJI_CW_CUT * crits)

    def magic(name: str, raw: float, now: float, count: float = 1.0) -> float:
        """Magical spell damage from the Monk (NextDamageType magical). Returns dealt per hit."""
        nonlocal fof
        amount = (raw + stats["potency"]) * typed(True, now)
        crits = 0.0
        if stats["spell_crit"]:
            amount *= _crit_factor(stats["crit"], stats["spell_mult"] + stats["rating"])
            crits = _chance(stats["crit"] / 100.0) * count
        dealt = amount * taken * _execute_factor(stats, now)
        sources.add_exec(name, dealt * count, now, _execute_factor(stats, now))
        note_damage_mana(count)
        if has(TALENT_FISTS_OF_FURY):
            fof = min(50.0 * LEVEL, fof + 0.10 * dealt * count)
        cut_wrath(crits, now)
        return dealt

    def attack_hit(name: str, raw: float, now: float, *, red_crane: bool, potency_scale: float) -> float:
        """Physical attack through PreDamage_Increase: FoF add, crit, Red Crane."""
        nonlocal fof
        amount = raw + stats["potency"] * potency_scale
        if fof > 0:
            amount += fof
            fof = 0.0
        amount *= typed(False, now)
        chance = stats["crit"]
        rating = 2.0 + stats["rating"]
        if red_crane:
            amount *= (1.0 + chance / 100.0) * rating
            crits = 1.0
        else:
            amount *= _crit_factor(chance, rating)
            crits = _chance(chance / 100.0)
        dealt = amount * taken * _execute_factor(stats, now)
        sources.add_exec(name, dealt, now, _execute_factor(stats, now))
        note_damage_mana(1)
        cut_wrath(crits, now)
        return dealt

    def ps_damage() -> float:
        value = (60.0 * RANK + 10.0 + 1.0 * strength) * (1.0 + 0.005 * agility)
        if ww:
            value *= 1.05 + 0.008 * mastery
        return value

    def white_tiger(amount: float, now: float) -> None:
        magic("White Tiger", 2.0 * amount, now, count=targets)

    def power_strike(now: float, proc: bool, weight: float = 1.0) -> None:
        nonlocal ps_avatar
        damage = ps_damage()
        if proc:
            damage *= 0.50
        elif ww:
            pending.append((now + WW_PROC_DELAY, _chance(0.40 * luck_mult)))
        if ps_avatar == CHIJI and not proc:
            ps_avatar = ""
            white_tiger(0.15 * damage, now)
            damage *= 1.40
        if proc:
            magic("Power Strike (WW-повтор)", damage, now, count=weight)
        else:
            magic("Power Strike", damage, now)
        if not proc and ps_avatar in (NIUZAO, YULON):
            ps_avatar = ""  # stun / heal only
        if stats["xuens_gaze"] and not proc:
            white_tiger(0.15 * damage, now)

    def spend_emp(now: float) -> None:
        nonlocal emp, stance, jab
        emp -= 1
        if emp <= 0:
            emp = 0
            stance = ""
        if has(TALENT_JAB):
            jab += 1
            if jab == 5:
                jab = 0
                power_strike(now, False)

    def emp_max() -> int:
        return 3 if has(TALENT_MARTIAL_ARTIST) else 2

    def set_stance(value: str) -> None:
        nonlocal stance, emp
        stance = value
        emp = 3 if has(TALENT_MARTIAL_ARTIST) else 2

    def celestial(now: float, code: bool) -> None:
        """PreDamage_Heroes Func028: Xuen stance / Windwalker celestial attacks."""
        if not (stance == XUEN or ww):
            return
        amount = 0.15 * ps_damage()
        if stance == XUEN and not code:
            spend_emp(now)
            white_tiger(amount, now)
        elif ww:
            magic("Celestial Attack (Xuen)", amount, now)
        if has(TALENT_FLURRY) and ww:
            magic("Celestial Attack (Xuen)", amount, now, count=_chance(0.40 * luck_mult))

    def wrath_of_xuen(dealt: float, now: float) -> None:
        nonlocal wrath_until
        if now < wrath_until:
            wrath_until = -1.0
            magic("Wrath of Xuen", 20.0 + 1.0 * strength + 0.50 * dealt, now, count=targets)

    def dcs() -> float:
        return WHITE_BASE + 0.75 * strength + stats["damage"]

    def interval(now: float) -> float:
        swing = SWING * (1.20 if stats["galactic"] else 1.0)
        speed = stats["attack_speed"]
        if stance:
            speed += STANCE_AS
        if now < blessing_xuen_until:
            speed += BLESSING_XUEN_AS
        speed = min(4.0, max(-0.8, speed))
        return swing / (1.0 + speed)

    def gcd(now: float) -> float:
        return (1.0 if has(TALENT_LEGACY) else 1.5) / (1.0 + haste_at(now))

    nxt = {"ps": 0.0, "cw": 0.0, "fb": 0.0, "rm": 0.0}
    order = ("ps", "cw", "fb", "rm")
    names = {"ps": "Power Strike", "cw": "Celestial Wrath", "fb": "Fortifying Brew", "rm": "Renewing Mist"}

    def allowed(key: str, now: float) -> bool:
        # Do not overwrite a damage stance that still has empowered attacks.
        if stance in DAMAGE_STANCES and emp > 0:
            if hold == "spent2":
                if emp_max() - emp < 2:
                    return False
            elif hold == "filler":
                if key in ("fb", "rm"):
                    return False
            elif hold.startswith("all"):
                limit = float(hold[3:]) if len(hold) > 3 else FIGHT
                if now - nxt[key] < limit:
                    return False
        if key == "rm" and not plain_mist and avatar not in (XUEN, CHIJI):
            return False
        if brew_first and key == "cw" and avatar == XUEN and nxt["fb"] <= now + gcd(now) + cast_time:
            return False  # Celestial Wrath would reset Avatar of Xuen before Fortifying Brew
        if key == "ps" and now < ps_buff_until:
            return False
        if key in ("fb", "rm") and avatar == CHIJI:
            return False  # keep Avatar of Chi'Ji for Power Strike (x1.40 + White Tiger)
        if key == "rm" and avatar == XUEN and nxt["fb"] <= now + gcd(now) + cast_time:
            return False  # Fortifying Brew spends Avatar of Xuen better (two White Tigers)
        return True

    next_attack = 0.0
    busy = 0.0
    guard = 0
    clock = 0.0
    while True:
        guard += 1
        if guard > 400000:
            break
        attack_at = max(next_attack, busy, clock)
        cast_at = FIGHT * 10
        choice = None
        for key in order:
            ready = max(nxt[key], busy, clock)
            if ready < cast_at - 1e-9 and allowed(key, ready):
                cast_at, choice = ready, key
        pending_at = min((when for when, _ in pending), default=FIGHT * 10)
        moment = min(attack_at, cast_at, pending_at)
        if moment >= FIGHT:
            break
        clock = moment
        if moment == pending_at:
            echo = min(pending)
            pending.remove(echo)
            power_strike(moment, True, echo[1])
            continue
        if cast_at <= attack_at and choice is not None and moment == cast_at:
            key = choice
            if not pay(SPELL_MANA, moment):
                nxt[key] = moment + 0.25
                continue
            hit_at = moment + CAST_POINT
            actions.append((moment, names[key]))
            busy = moment + cast_time + stats["cast_stun_lock"]
            if sulfuras is not None:
                sulfuras.cast()
            if key == "ps":
                if avatar:
                    ps_avatar = avatar
                    avatar = ""
                if has(TALENT_AVATAR_XUEN):
                    ps_avatar = ""
                    avatar = XUEN
                if has(TALENT_WAY_OF_THE_TIGER):
                    set_stance({"windwalker": CHIJI, "brewmaster": NIUZAO, "mistweaver": YULON}[spec])
                else:
                    set_stance(XUEN)
                ps_buff_until = hit_at + PS_BUFF
            elif key == "cw":
                avatar = ""
                if spec == "windwalker":
                    wrath_until = hit_at + WRATH_XUEN_BUFF
                if has(TALENT_AVATAR_CHIJI):
                    ps_avatar = ""
                    avatar = CHIJI
                set_stance(CHIJI)
            elif key == "fb":
                fb_attack = True
                if avatar == XUEN:
                    avatar = ""
                    amount = 0.15 * ps_damage()
                    white_tiger(amount, hit_at)
                    white_tiger(amount, hit_at)
                elif avatar:
                    avatar = ""  # Niuzao: nothing; Yu'lon: heal; Chi'Ji: armor (A0EP)
                if has(TALENT_AVATAR_NIUZAO):
                    ps_avatar = ""
                    avatar = NIUZAO
                set_stance(NIUZAO)
            elif key == "rm":
                if avatar == XUEN:
                    blessing_xuen_until = hit_at + BLESSING
                elif avatar == CHIJI:
                    blessing_yulon_until = hit_at + BLESSING
                avatar = ""
                set_stance(YULON)
            nxt[key] = moment + _cooldown(SPELL_CD, haste_at(moment), stats)
            spread = moment + gcd(moment)
            for other in order:
                if other != key and nxt[other] < spread:
                    nxt[other] = spread
            next_attack = max(next_attack, busy)
            continue

        # Monk auto-attack.
        moment = attack_at
        recover(moment)
        power = dcs()
        # PreDamage_Heroes Func024: Power Strike on the next attack under B02D.
        if moment < ps_buff_until:
            ps_buff_until = -1.0
            power_strike(moment, False)
        # Func026: Fortifying Brew extra attack (code attack, SIEGE).
        if fb_attack:
            fb_attack = False
            fb_dealt = attack_hit("Fortifying Brew (удар)", 25.0 * RANK + 0.50 * power, moment, red_crane=False, potency_scale=1.0)
            celestial(moment, code=True)
            wrath_of_xuen(fb_dealt, moment)
        # Func028 / 030 / 032 on the real attack.
        # Event 1 (PreDamage_Heroes) runs before PreDamage_Increase (Red Crane).
        celestial(moment, code=False)
        if stance in (NIUZAO, YULON):
            spend_emp(moment)
        red_crane = False
        if stance == CHIJI:
            red_crane = True
            spend_emp(moment)
        before = sources["Автоатака"]
        dealt = attack_hit("Автоатака", power, moment, red_crane=red_crane, potency_scale=stats["attack_potency"])
        if stats["auto_pct"] != 1.0:
            sources["Автоатака"] = before + (sources["Автоатака"] - before) * stats["auto_pct"]
        wrath_of_xuen(dealt, moment)
        gain_mana(attack_mana_gain(stats))
        if stats["fire_orb"]:
            splash = (20.0 + 0.35 * stats["str"]) * targets * taken * _execute_factor(stats, moment)
            sources.add_exec("Всплеск огня", splash, moment, _execute_factor(stats, moment))
            note_damage_mana(targets)
        if sulfuras is not None:
            execute = _execute_factor(stats, moment)
            if sulfuras.attack():
                splash = stats["str"] * typed(True, moment) * taken * execute * targets
                splash *= _crit_factor(stats["crit"], 2.0 + stats["rating"])
                sources.add_exec("Sulfuras", splash, moment, execute)
                note_damage_mana(targets)
            echo = power * taken * execute * sulfuras_echo_chance(stats["luck"])
            sources.add_exec("Sulfuras (удар)", echo, moment, execute)
        next_attack = moment + interval(moment)

    total = sum(sources.values())
    recover(FIGHT)
    mana_left = 0.0 if stats["mana_max"] <= 0 else 100.0 * mana / stats["mana_max"]
    return list(sources.events), stats, total

