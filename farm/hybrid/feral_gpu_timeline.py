# -*- coding: utf-8 -*-
"""Batched next-event timeline for Feral Druid (primal / guardian / savage).

Faithful port of sunken_sim.feral_druid._simulate_feral onto batched torch.
Rows = builds x bound_keys (DIAMOND expands; else one None). f64 clocks on CPU.
Event: (when, name, weight, kind) = KIND_PHYS/MAG/EXEC/FLAT.
"""
from __future__ import annotations

MAX_STEPS = 200000
MAX_PENDING = 128
MAX_T = 8
MAX_EVENTS = 4096

A_SWIPE, A_BITE, A_ROAR = 0, 1, 2
N_ABIL = 3
COSTS = (15.0, 10.0, 20.0)
KEYS = ("swipe", "bite", "roar")

P_CAST, P_RAKE = 0, 1

N_AUTO, N_SWIPE, N_BITE, N_ROAR, N_RAKE, N_FRENZY = 0, 1, 2, 3, 4, 5
N_FIRE, N_SULF, N_SULF_ECHO = 6, 7, 8
NAMES = {
    N_AUTO: "Автоатака",
    N_SWIPE: "Swipe",
    N_BITE: "Savage Bite",
    N_ROAR: "Stampeding Roar",
    N_RAKE: "Rake",
    N_FRENZY: "Feral Frenzy",
    N_FIRE: "Всплеск огня",
    N_SULF: "Sulfuras",
    N_SULF_ECHO: "Sulfuras (удар)",
}
KIND_PHYS, KIND_MAG, KIND_EXEC, KIND_FLAT = 0.0, 1.0, 2.0, 3.0


class _Overflow(Exception):
    pass


def _bound_keys_for(build, spec: str):
    from sunken_sim import feral_druid as mod
    from sunken_sim.shadow import _wears

    if _wears(build, mod.DIAMOND):
        return list(mod.buttons(spec))
    return [None]


def generate_feral_timelines(torch, device, builds, spec: str, targets: int):
    if spec not in ("primal", "guardian", "savage"):
        raise ValueError(f"feral GPU timeline specs primal/guardian/savage, got {spec}")
    if not builds:
        return []
    dev_type = getattr(device, "type", str(device))
    if dev_type in ("privateuseone", "dml") or "privateuseone" in str(device):
        device = torch.device("cpu")
    exp_builds, exp_bounds, owners = [], [], []
    for i, b in enumerate(builds):
        for bk in _bound_keys_for(b, spec):
            exp_builds.append(b)
            exp_bounds.append(bk)
            owners.append(i)
    try:
        rows = _feral_batch(torch, device, torch.float64, exp_builds, exp_bounds, spec, int(targets))
    except _Overflow:
        return _cpu_best(builds, spec, targets)
    from sunken_sim import feral_druid as mod

    best = [None] * len(builds)
    best_tot = [-1.0] * len(builds)
    for owner, (events, stats, codes) in zip(owners, rows):
        total = sum(mod.score_events(events, stats, codes).values())
        if total > best_tot[owner]:
            best_tot[owner] = total
            best[owner] = (events, stats, codes)
    out = []
    for i, b in enumerate(builds):
        if best[i] is not None:
            out.append(best[i])
        else:
            st = mod.sheet(b, spec)
            codes = frozenset(item.rawcode for item in b.items) | b.talents | b.glyphs
            out.append(([], st, codes))
    return out


def _cpu_best(builds, spec, targets):
    from sunken_sim import feral_druid as mod

    out = []
    for build in builds:
        stats = mod.sheet(build, spec)
        best_events, best_tot, best_codes = None, -1.0, frozenset()
        for bk in _bound_keys_for(build, spec):
            key = mod._timeline_key(build, stats, spec, targets, bk)
            cached = mod._TIMELINE.get(key)
            if cached is None:
                if bk is None:
                    mod._simulate_feral(build, targets, spec, None)
                else:
                    mod.simulate(build, targets, spec, mod.BOUND_NAME[bk])
                cached = mod._TIMELINE[key]
            events, _a, _m, codes = cached
            total = sum(mod.score_events(list(events), stats, codes).values())
            if total > best_tot:
                best_tot = total
                best_events = list(events)
                best_codes = codes
        out.append((best_events or [], stats, best_codes))
    return out


def _push(torch, bufs, mask, when, weight, name_id, kind):
    if not bool(mask.any()):
        return
    B = int(mask.shape[0])
    active = mask & (bufs["length"] < MAX_EVENTS) & (weight != 0)
    if not bool(active.any()):
        return
    rows = torch.arange(B, device=weight.device)
    idx = bufs["length"].clone()
    bufs["when"][rows[active], idx[active]] = when[active]
    bufs["weight"][rows[active], idx[active]] = weight[active]
    bufs["name"][rows[active], idx[active]] = int(name_id) if not isinstance(name_id, torch.Tensor) else name_id[active]
    bufs["kind"][rows[active], idx[active]] = float(kind) if not isinstance(kind, torch.Tensor) else kind[active]
    bufs["length"] = bufs["length"] + active.to(torch.int64)


def _make_bufs(torch, device, B, dtype):
    return {
        "when": torch.zeros((B, MAX_EVENTS), dtype=dtype, device=device),
        "name": torch.zeros((B, MAX_EVENTS), dtype=torch.int64, device=device),
        "weight": torch.zeros((B, MAX_EVENTS), dtype=dtype, device=device),
        "kind": torch.zeros((B, MAX_EVENTS), dtype=dtype, device=device),
        "length": torch.zeros(B, dtype=torch.int64, device=device),
    }


def _finalize(bufs, stats_list, codes_list):
    out = []
    lengths = bufs["length"].detach().cpu().tolist()
    whens = bufs["when"].detach().cpu()
    names = bufs["name"].detach().cpu()
    weights = bufs["weight"].detach().cpu()
    kinds = bufs["kind"].detach().cpu()
    for i, (stats, codes) in enumerate(zip(stats_list, codes_list)):
        n = int(lengths[i])
        events = [
            (float(whens[i, j]), NAMES[int(names[i, j])], float(weights[i, j]), float(kinds[i, j]))
            for j in range(n)
        ]
        out.append((events, stats, codes))
    return out


def _feral_batch(torch, device, dtype, builds, bounds, spec, T):
    from sunken_sim import feral_druid as mod
    from sunken_sim.shadow import (
        CAST_BACKSWING,
        CAST_POINT,
        DUMMY_ARMOR,
        FIGHT,
        PHYSICAL_ADDS,
        _crit_factor,
        _type_add,
        _wears,
        armor_taken,
        attack_mana_gain,
        cast_mana_back,
        sulfuras_echo_chance,
        target_hp,
    )

    B = len(builds)
    fight = float(FIGHT)
    cast_point = float(CAST_POINT)
    cast_time = float(CAST_POINT + CAST_BACKSWING)
    BIG = 1e18
    Tt = min(int(T), MAX_T)
    zeros = torch.zeros(B, dtype=dtype, device=device)
    ones = torch.ones(B, dtype=dtype, device=device)
    rix = torch.arange(B, device=device)

    primal = spec == "primal"
    bear = spec == "guardian"
    cat = spec == "savage"
    shifted = bear or cat

    stats_list, codes_list = [], []
    rows_meta = []
    for build, bound_key in zip(builds, bounds):
        stats = mod.sheet(build, spec)
        codes = frozenset(item.rawcode for item in build.items) | build.talents | build.glyphs
        stats_list.append(stats)
        codes_list.append(codes)
        has = lambda c, b=build: mod._has(b, c) if hasattr(mod, "_has") else __import__("sunken_sim.shadow", fromlist=["_has"])._has(b, c)
        from sunken_sim.shadow import _has as shas

        has = lambda c, b=build: shas(b, c)
        wears = lambda c, b=build: _wears(b, c)
        ferocity_on = primal or (bear and has(mod.TALENT_GRIZZLY))
        lunar = cat and has(mod.TALENT_LUNAR)
        ursoc = has(mod.TALENT_URSOC) or wears(mod.SHOULDERPADS)
        momentum = has(mod.TALENT_MOMENTUM)
        rend = has(mod.TALENT_REND)
        maim = has(mod.TALENT_MAIM)
        wild = has(mod.TALENT_STRENGTH_WILD)
        razor = has(mod.TALENT_RAZOR_CLAWS)
        frenzy = has(mod.TALENT_FERAL_FRENZY)
        pen = float(stats["armor_pen"])
        taken_plain = float(armor_taken(DUMMY_ARMOR - pen))
        taken_maim = float(armor_taken(DUMMY_ARMOR - pen - mod.MAIM_ARMOR))
        fer_max = (100.0 + stats["mastery"] + (25.0 if has(mod.TALENT_PRIMAL_FURY) else 0.0)) if ferocity_on else 0.0
        fer_rate = 12.0 * (1.0 + stats["haste"]) * (1.0 + 0.01 * stats["mastery"]) if ferocity_on else 0.0
        rake_period = 1.0 / (1.0 + stats["haste"] + (0.25 if has(mod.TALENT_OPEN_WOUNDS) else 0.0))
        attack_inc = 0.0
        if cat:
            attack_inc += 0.05 + 0.005 * stats["mastery"]
        if has(mod.TALENT_SHRED):
            attack_inc += 0.10
        crit_bonus = 0.0
        rating_bonus = 0.0
        if cat:
            crit_bonus += 10.0
            if ursoc:
                crit_bonus += min(25.0, stats["armor"])
            if lunar:
                rating_bonus += 0.15
        # bound cd_temp
        bk = bound_key
        cd_temp = float(stats["cd_temp"])
        flat_cdr = float(stats["flat_cdr"])
        haste = float(stats["haste"])

        def cd(base, key, flat=0.0):
            temp = cd_temp * (0.70 if bk == key else 1.0)
            return max(0.5, (base * temp - flat_cdr - flat) / (1.0 + haste))

        wild_flat = 1.0 if wild else 0.0
        swipe_cd0 = cd(6.0, "swipe", wild_flat)
        bite_cd0 = cd(10.0 - (2.0 if maim else 0.0), "bite", wild_flat)
        roar_cd0 = cd(12.0, "roar", wild_flat)
        phys_extra = 0.10 if has(mod.TALENT_PRIMAL_FURY) else 0.0
        glass = 1.15 if "I0JA" in codes else 1.0
        type_add0, type_slope = _type_add_split(codes)  # helper below
        rows_meta.append(
            {
                "ferocity_on": 1.0 if ferocity_on else 0.0,
                "lunar": 1.0 if lunar else 0.0,
                "ursoc": 1.0 if ursoc else 0.0,
                "momentum": 1.0 if momentum else 0.0,
                "rend": 1.0 if rend else 0.0,
                "maim": 1.0 if maim else 0.0,
                "wild": 1.0 if wild else 0.0,
                "razor": 1.0 if razor else 0.0,
                "frenzy": 1.0 if frenzy else 0.0,
                "taken_plain": taken_plain,
                "taken_maim": taken_maim,
                "fer_max": fer_max,
                "fer_rate": fer_rate,
                "rake_period": rake_period,
                "attack_inc": attack_inc,
                "crit_bonus": crit_bonus,
                "rating_bonus": rating_bonus,
                "swipe_cd": swipe_cd0,
                "bite_cd": bite_cd0,
                "roar_cd": roar_cd0,
                "phys_extra": phys_extra,
                "glass": glass,
                "type_add0": type_add0,
                "packleader": 1.0 if wears(mod.PACKLEADER) else 0.0,
                "ashamane": 1.0 if wears(mod.ASHAMANE) else 0.0,
                "fresh_wound": 1.0 if has(mod.TALENT_FRESH_WOUND) else 0.0,
                "savage_roar": 1.0 if has(mod.TALENT_SAVAGE_ROAR) else 0.0,
                "fire_orb": 1.0 if wears(mod.FIRE_ORB) else 0.0,
                "sulfuras": 1.0 if wears(mod.SULFURAS_CODE) else 0.0,
                "ad": float(stats["ad"]),
                "agi": float(stats["agi"]),
                "str": float(stats["str"]),
                "intel": float(stats["int"]),
                "potency": float(stats["potency"]),
                "attack_potency": float(stats["attack_potency"]),
                "crit": float(stats["crit"]),
                "rating": float(stats["rating"]),
                "spell_crit": 1.0 if stats["spell_crit"] else 0.0,
                "spell_mult": float(stats["spell_mult"]),
                "luck": float(stats["luck"]),
                "mana_max": float(stats["mana_max"]),
                "mana_regen": float(stats["mana_regen"]),
                "attack_speed": float(stats["attack_speed"]),
                "attack_base": float(stats["attack_base"]),
                "cast_stun_lock": float(stats["cast_stun_lock"]),
                "auto_pct": float(stats["auto_pct"]),
                "damage_mana_pct": float(stats.get("damage_mana_pct") or 0.0),
                "max_hp": float(stats["max_hp"]),
                "amg": float(attack_mana_gain(stats)),
                "echo_ch": float(sulfuras_echo_chance(stats["luck"])),
            }
        )

    def F(name):
        return torch.tensor([m[name] for m in rows_meta], dtype=dtype, device=device)

    def Bool(name):
        return F(name) > 0.5

    ferocity_on = Bool("ferocity_on")
    lunar = Bool("lunar")
    ursoc = Bool("ursoc")
    momentum = Bool("momentum")
    rend = Bool("rend")
    maim_t = Bool("maim")
    wild = Bool("wild")
    razor = Bool("razor")
    frenzy = Bool("frenzy")
    packleader = Bool("packleader")
    ashamane = Bool("ashamane")
    fresh_wound = Bool("fresh_wound")
    savage_roar_t = Bool("savage_roar")
    fire_orb = Bool("fire_orb")
    sulfuras_on = Bool("sulfuras")
    spell_crit_f = Bool("spell_crit")

    taken_plain = F("taken_plain")
    taken_maim = F("taken_maim")
    fer_max = F("fer_max")
    fer_rate = F("fer_rate")
    rake_period = F("rake_period")
    attack_inc = F("attack_inc")
    crit_bonus = F("crit_bonus")
    rating_bonus = F("rating_bonus")
    swipe_cd = F("swipe_cd")
    bite_cd = F("bite_cd")
    roar_cd = F("roar_cd")
    phys_extra = F("phys_extra")
    glass = F("glass")
    type_add0 = F("type_add0")
    ad0 = F("ad")
    agi = F("agi")
    strength = F("str")
    intel = F("intel")
    potency0 = F("potency")
    attack_potency = F("attack_potency")
    crit0 = F("crit")
    rating0 = F("rating")
    spell_mult = F("spell_mult")
    luck = F("luck")
    mana_max = F("mana_max")
    mana_regen = F("mana_regen")
    attack_speed0 = F("attack_speed")
    attack_base = F("attack_base")
    cast_stun = F("cast_stun_lock")
    auto_pct = F("auto_pct")
    dmp = F("damage_mana_pct")
    max_hp = F("max_hp")
    amg = F("amg")
    echo_ch = F("echo_ch")
    luck_mult = ones + luck

    mana = mana_max.clone()
    mana_time = zeros.clone()
    fer = zeros.clone()
    fer_time = zeros.clone()
    ready = torch.zeros((B, N_ABIL), dtype=dtype, device=device)
    rake = torch.full((B, MAX_T), -1.0, dtype=dtype, device=device)
    berserk_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    roar_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    maim_until = torch.full((B,), -1.0, dtype=dtype, device=device)
    bite_window = torch.full((B,), -1.0, dtype=dtype, device=device)
    swipe_window = torch.full((B,), -1.0, dtype=dtype, device=device)
    next_hit_bonus = zeros.clone()
    hero_ready = zeros.clone()
    next_attack = zeros.clone()
    rake_timer = torch.full((B,), BIG, dtype=dtype, device=device)
    rake_clock = torch.zeros(B, dtype=torch.bool, device=device)
    # sulfuras state: charges accumulator like CPU Sulfuras
    sulf_acc = zeros.clone()

    p_time = torch.full((B, MAX_PENDING), BIG, dtype=dtype, device=device)
    p_order = torch.zeros((B, MAX_PENDING), dtype=torch.int64, device=device)
    p_kind = torch.zeros((B, MAX_PENDING), dtype=torch.int64, device=device)
    p_abil = torch.zeros((B, MAX_PENDING), dtype=torch.int64, device=device)
    order_c = torch.zeros(B, dtype=torch.int64, device=device)

    bufs = _make_bufs(torch, device, B, dtype)
    alive = torch.ones(B, dtype=torch.bool, device=device)

    def full(v):
        return v if isinstance(v, torch.Tensor) else torch.full((B,), float(v), dtype=dtype, device=device)

    def target_hp_t(now):
        now = full(now)
        return torch.clamp(ones - now / fight, min=0.0)

    def cf(chance, mult):
        # _crit_factor(chance, mult) = 1 + chance/100 * (mult-1) clamped
        ch = torch.clamp(full(chance), 0.0, 100.0)
        return ones + (ch / 100.0) * (full(mult) - ones)

    def recover(mask, now):
        nonlocal mana, mana_time, fer, fer_time
        now = full(now)
        grow = mask & (now > mana_time) & (mana < mana_max)
        mana = torch.where(grow, torch.minimum(mana_max, mana + mana_regen * (now - mana_time)), mana)
        mana_time = torch.where(mask, now, mana_time)
        fg = mask & ferocity_on & (now > fer_time)
        fer = torch.where(fg, torch.minimum(fer_max, fer + fer_rate * (now - fer_time)), fer)
        fer_time = torch.where(fg, now, fer_time)

    def pay(mask, cost, now):
        nonlocal mana
        recover(mask, now)
        cost = full(cost)
        ok = mask & (mana >= cost)
        mana = torch.where(ok, mana - cost, mana)
        # cast_mana_back
        back = torch.tensor([cast_mana_back(float(c), stats_list[i]) for i, c in enumerate(cost.tolist())], dtype=dtype, device=device)
        # approximate: use per-row from stats — better recompute
        # cast_mana_back depends on cost and stats; vectorize simply:
        from sunken_sim.shadow import cast_mana_back as cmb

        backs = []
        for i in range(B):
            backs.append(cmb(float(cost[i].item()), stats_list[i]))
        back = torch.tensor(backs, dtype=dtype, device=device)
        mana = torch.where(ok, torch.minimum(mana_max, mana + back), mana)
        return ok

    def dcs(now):
        now = full(now)
        bonus = torch.where(
            (now < berserk_until) & (torch.full((B,), cat, dtype=torch.bool, device=device) | momentum),
            full(0.20) + torch.where(momentum & torch.full((B,), shifted, device=device), full(0.15), zeros),
            zeros,
        )
        return ad0 * (ones + bonus)

    def crit_of():
        return torch.clamp(crit0 + crit_bonus, max=100.0)

    def physical(now):
        now = full(now)
        extra = phys_extra + torch.where(packleader & (now < roar_until), full(0.15), zeros)
        # type_add from PHYSICAL_ADDS — bake base; timed buffs rare
        bonus = ones + type_add0 + extra
        return bonus * glass

    def taken_main(now):
        now = full(now)
        return torch.where(now < maim_until, taken_maim, taken_plain)

    def deal(mask, name_id, raw, now, count, attack, main_share, attack_share=0.0, magical=None, pot_scale=1.0):
        if not bool(mask.any()):
            return
        now = full(now)
        raw = full(raw)
        count = full(count)
        main_share = full(main_share)
        attack_share = full(attack_share)
        pot_scale = full(pot_scale)
        if magical is None:
            is_magic = lunar
        elif isinstance(magical, bool):
            is_magic = torch.full((B,), magical, dtype=torch.bool, device=device)
        else:
            is_magic = magical
        amount = raw + potency0 * pot_scale
        amount = torch.where(is_magic, amount, amount * physical(now))
        attack_mult = (ones + attack_inc) * cf(crit_of(), 2.0 + rating0 + rating_bonus)
        spell_m = torch.where(spell_crit_f, cf(crit_of(), spell_mult + rating0 + rating_bonus), ones)
        amount = torch.where(
            torch.full((B,), attack, dtype=torch.bool, device=device) if isinstance(attack, bool) else attack,
            amount * attack_mult,
            amount * (attack_share * attack_mult + (ones - attack_share) * spell_m),
        )
        share = torch.clamp(main_share, 0.0, 1.0)
        amount = amount * (share * taken_main(now) + (ones - share) * taken_plain)
        weight = amount * count
        kind = torch.where(is_magic, full(KIND_MAG), full(KIND_PHYS))
        _push(torch, bufs, mask & (weight != 0), now, weight, name_id, kind)
        # damage mana
        mana_gain = dmp * mana_max * count
        nonlocal mana
        mana = torch.where(mask & (dmp > 0), torch.minimum(mana_max, mana + mana_gain), mana)

    def apply_rake(mask, now, indexes):
        nonlocal rake_clock, rake_timer
        now = full(now)
        for index in indexes:
            rake[:, index] = torch.where(mask, now + float(mod.RAKE_LIFE), rake[:, index])
        start = mask & ~rake_clock
        rake_clock = rake_clock | mask
        rake_timer = torch.where(start, now + rake_period, rake_timer)

    def swipe_raw(now):
        power = dcs(now)
        raw = full(30.0) + 1.15 * power
        if primal:
            raw = raw + 0.55 * agi + 0.20 * power
            raw = torch.where(ursoc, raw * (ones + 0.005 * strength), raw)
        elif bear:
            raw = raw + 0.03 * max_hp
        elif cat:
            raw = raw + 0.40 * agi
        raw = torch.where(ashamane, raw * 1.25, raw)
        return raw

    def swipe_hit(mask, now, raw, name_id, weight):
        now = full(now)
        raw = full(raw)
        weight = full(weight)
        low = torch.where(target_hp_t(now) * 100.0 <= crit_of(), full(1.15), ones)
        share = torch.where(razor, 0.10 * luck_mult, zeros)
        deal(mask, name_id, raw * low, now, full(float(Tt)) * weight, False, ones / float(Tt), torch.clamp(share, max=1.0))

    def peek_pend():
        return p_time.min(dim=1).values

    def push_pend(mask, when, kind, abil=0):
        nonlocal order_c
        if not bool(mask.any()):
            return
        when = full(when)
        free = p_time >= BIG
        if bool((mask & ~free.any(dim=1)).any()):
            raise _Overflow("pending")
        slot = torch.argmax(free.to(torch.int8), dim=1)
        r = rix[mask]
        s = slot[mask]
        p_time[r, s] = when[mask]
        p_order[r, s] = order_c[mask]
        p_kind[r, s] = int(kind)
        p_abil[r, s] = int(abil) if not isinstance(abil, torch.Tensor) else abil[mask]
        order_c = order_c + mask.to(torch.int64)

    def pop_pend(mask):
        # pop earliest by (time, order)
        scored = p_time * 1e6 + p_order.to(dtype)
        scored = torch.where(p_time < BIG, scored, torch.full_like(scored, BIG * 1e7))
        slot = scored.argmin(dim=1)
        when = p_time[rix, slot].clone()
        kind = p_kind[rix, slot].clone()
        abil = p_abil[rix, slot].clone()
        p_time[rix[mask], slot[mask]] = BIG
        return when, kind, abil

    # Sulfuras / auto_pct rare → CPU overflow
    if bool(sulfuras_on.any()) or bool((auto_pct != 1.0).any()):
        raise _Overflow("sulfuras_or_auto_pct")

    steps = 0
    while bool(alive.any()):
        steps += 1
        if steps > MAX_STEPS:
            raise _Overflow("steps")

        pending_at = peek_pend()
        moment = torch.minimum(torch.minimum(next_attack, pending_at), rake_timer)

        can_hero = alive & (hero_ready <= moment) & (hero_ready < fight)
        choice = torch.full((B,), -1, dtype=torch.int64, device=device)
        for a in range(N_ABIL):
            take = can_hero & (choice < 0) & (ready[:, a] <= hero_ready)
            choice = torch.where(take, torch.full((B,), a, dtype=torch.int64, device=device), choice)
        has_choice = can_hero & (choice >= 0)

        # Cast attempt (CPU continue) — mark acted so we skip world events this step
        acted = torch.zeros(B, dtype=torch.bool, device=device)
        if bool(has_choice.any()):
            now_h = hero_ready
            recover(has_choice, now_h)
            costs = torch.stack([full(COSTS[0]), full(COSTS[1]), full(COSTS[2])], dim=1)
            cost = costs[rix, choice.clamp(min=0)]
            ok = has_choice & (mana >= cost)
            fail = has_choice & ~ok
            for a in range(N_ABIL):
                ready[:, a] = torch.where(fail & (choice == a), hero_ready + 0.25, ready[:, a])
            if bool(ok.any()):
                mana = torch.where(ok, mana - cost, mana)
                backs = [cast_mana_back(float(cost[i].item()), stats_list[i]) if bool(ok[i]) else 0.0 for i in range(B)]
                mana = torch.where(ok, torch.minimum(mana_max, mana + torch.tensor(backs, dtype=dtype, device=device)), mana)
                cds = torch.stack([swipe_cd, bite_cd, roar_cd], dim=1)
                cdv = cds[rix, choice.clamp(min=0)]
                for a in range(N_ABIL):
                    ready[:, a] = torch.where(ok & (choice == a), hero_ready + cdv, ready[:, a])
                bite_cast = ok & (choice == A_BITE) & ferocity_on & (fer >= 40.0)
                left2 = ready[:, A_BITE] - hero_ready
                spent = torch.where(bite_cast, torch.minimum(torch.minimum(fer, full(80.0)), left2 * 10.0), zeros)
                fer = torch.where(bite_cast, fer - spent, fer)
                ready[:, A_BITE] = torch.where(
                    bite_cast, torch.maximum(hero_ready + 0.5, ready[:, A_BITE] - spent / 10.0), ready[:, A_BITE]
                )
                bonus = torch.where(wild, full(25.0) + 0.75 * agi, zeros)
                bonus = bonus + torch.where(
                    ok & (choice == A_ROAR) & torch.full((B,), cat, dtype=torch.bool, device=device),
                    full(50.0) + 1.5 * agi,
                    zeros,
                )
                next_hit_bonus = torch.where(ok, bonus, next_hit_bonus)
                push_pend(ok, hero_ready + cast_point, P_CAST, choice)
                busy = hero_ready + cast_time + cast_stun
                hero_ready = torch.where(ok, busy, hero_ready)
                next_attack = torch.where(ok, torch.maximum(next_attack, busy), next_attack)
            acted = has_choice

        waiting = can_hero & ~has_choice
        if bool(waiting.any()):
            fut = torch.where(
                ready > hero_ready.view(B, 1) + 1e-9,
                ready,
                full(fight).view(B, 1).expand(B, N_ABIL),
            )
            wake = fut.min(dim=1).values
            # wake <= moment → set hero_ready=wake and act (continue)
            early = waiting & (wake <= moment)
            hero_ready = torch.where(early, wake, hero_ready)
            acted = acted | early
            # else advance hero_ready toward wake without consuming event
            late = waiting & ~early
            hero_ready = torch.where(late, torch.maximum(hero_ready, torch.minimum(wake, full(fight))), hero_ready)

        # Rows that cast/failed/woke early skip world events this iteration
        world = alive & ~acted
        if not bool(world.any()):
            continue

        done = world & (moment >= fight)
        alive = alive & ~done
        world = world & ~done
        if not bool(world.any()):
            if not bool(alive.any()):
                break
            continue

        # Same-time: rake before cast (CPU: prior rake reschedule usually precedes cast push)
        is_rake = world & (moment == rake_timer) & rake_clock
        is_pend = world & ~is_rake & (moment == pending_at) & (pending_at < BIG)
        is_auto = world & ~is_rake & ~is_pend & (moment == next_attack)

        # PENDING cast resolve
        if bool(is_pend.any()):
            _when, pk, ab = pop_pend(is_pend)
            m = is_pend & (pk == P_CAST)
            if bool(m.any()):
                recover(m, moment)
                # swipe
                ms = m & (ab == A_SWIPE)
                if bool(ms.any()):
                    raw = swipe_raw(moment)
                    raw = torch.where(ms & rend & (moment < swipe_window), raw * 1.25, raw)
                    swipe_window = torch.where(ms & rend & (moment < swipe_window), full(-1.0), swipe_window)
                    # ferocity spend
                    fer_ok = ms & ferocity_on & (fer >= 40.0)
                    spent = torch.where(fer_ok, torch.minimum(fer, full(80.0)), zeros)
                    fer = torch.where(fer_ok, fer - spent, fer)
                    raw = torch.where(fer_ok, raw * (ones + 0.01 * spent), raw)
                    swipe_hit(ms, moment, raw, N_SWIPE, ones)
                    apply_rake(ms, moment, list(range(Tt)))
                    bite_window = torch.where(ms & rend, moment + float(mod.REND_LIFE), bite_window)
                # bite
                mb = m & (ab == A_BITE)
                if bool(mb.any()):
                    raw = full(100.0) + 1.5 * dcs(moment)
                    if primal:
                        raw = raw * 1.25
                        raw = torch.where(ursoc, raw * (ones + 0.005 * strength), raw)
                    raw = torch.where(mb & rend & (moment < bite_window), raw * 1.35, raw)
                    bite_window = torch.where(mb & rend & (moment < bite_window), full(-1.0), bite_window)
                    maim_until = torch.where(mb & maim_t, moment + float(mod.MAIM_LIFE), maim_until)
                    deal(mb, N_BITE, raw, moment, ones, False, ones)
                    berserk_until = torch.where(mb & (torch.full((B,), shifted, device=device) | momentum), moment + float(mod.BERSERK_LIFE), berserk_until)
                    apply_rake(mb, moment, [0])
                    swipe_window = torch.where(mb & rend, moment + float(mod.REND_LIFE), swipe_window)
                # roar
                mr = m & (ab == A_ROAR)
                if bool(mr.any()):
                    roar_until = torch.where(mr, moment + float(mod.ROAR_LIFE), roar_until)
                    fer = torch.where(mr & ferocity_on, torch.minimum(fer_max, fer + 0.25 * fer_max), fer)

        # RAKE
        if bool(is_rake.any()):
            live_count = zeros.clone()
            main_share = zeros.clone()
            for ti in range(Tt):
                live = is_rake & (moment <= rake[:, ti] + 1e-9)
                live_count = live_count + live.to(dtype)
                if ti == 0:
                    main_share = torch.where(live, ones, main_share)
            none = is_rake & (live_count <= 0)
            rake_clock = rake_clock & ~none
            rake_timer = torch.where(none, full(BIG), rake_timer)
            active = is_rake & (live_count > 0)
            if bool(active.any()):
                raw = full(10.0) + 0.10 * dcs(moment)
                if primal:
                    chance = torch.clamp(full(0.30) * luck_mult, max=1.0)
                    raw = raw * (ones + 0.35 * chance)
                    recover(active & ferocity_on, moment)
                    fer = torch.where(active & ferocity_on, torch.minimum(fer_max, fer + 2.0 * chance * live_count), fer)
                share = torch.where(razor, torch.clamp(0.15 * luck_mult, max=1.0), zeros)
                main = torch.where(main_share > 0, ones / live_count, zeros)
                deal(active, N_RAKE, raw, moment, live_count, False, main, share)
                rake_timer = torch.where(active, moment + rake_period, rake_timer)


        # AUTO
        if bool(is_auto.any()):
            recover(is_auto, moment)
            raw = dcs(moment) + next_hit_bonus
            next_hit_bonus = torch.where(is_auto, zeros, next_hit_bonus)
            raw = raw + torch.where(fresh_wound, 0.02 * max_hp, zeros)
            deal(is_auto, N_AUTO, raw, moment, ones, True, ones, magical=False, pot_scale=attack_potency)
            mana = torch.where(is_auto, torch.minimum(mana_max, mana + amg), mana)
            # cat refresh rake
            cat_mask = is_auto & torch.full((B,), cat, device=device) & (moment >= rake[:, 0])
            apply_rake(cat_mask, moment, [0])
            # frenzy
            if bool((is_auto & frenzy).any()):
                crit_p = crit_of() / 100.0
                chance = (ones - crit_p) * torch.clamp(full(0.05) * luck_mult, max=1.0) + crit_p * torch.clamp(full(0.075) * luck_mult, max=1.0)
                swipe_hit(is_auto & frenzy & (chance > 0), moment, swipe_raw(moment), N_FRENZY, chance)
            # fire orb
            splash = (full(20.0) + 0.35 * intel) * float(Tt) * taken_plain
            _push(torch, bufs, is_auto & fire_orb & (splash != 0), moment, splash, N_FIRE, KIND_EXEC)
            speed = attack_speed0 + torch.where(savage_roar_t & (moment < roar_until), full(0.28), zeros)
            speed = torch.clamp(speed, -0.8, 4.0)
            next_attack = torch.where(is_auto, moment + attack_base / (ones + speed), next_attack)

    return _finalize(bufs, stats_list, codes_list)


def _type_add_split(codes):
    """Static physical type-add at t=0 (timed adds ignored in GPU TL; rare)."""
    from sunken_sim.shadow import PHYSICAL_ADDS, _type_add

    return float(_type_add(codes, PHYSICAL_ADDS, 0.0)), 0.0

